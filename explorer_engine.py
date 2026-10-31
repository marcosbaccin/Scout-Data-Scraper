"""
Motor do Explorador de Jogadores (busca configurável por qualquer estatística coletada).

Inspirado na "Plataforma de Scout" do Scout-Brazil-Serie-A: o usuário define faixas (mín–máx) para
qualquer estatística e encontra os atletas que correspondem ao perfil desejado — agora sobre as
4 fontes (SofaScore primária + FBref + Transfermarkt + WhoScored).

Fluxo:
1. `scope_result(scope)`  : escolhe o RECORTE (temporada mais recente com amostra mínima, temporadas
   escolhidas ou carreira) + competições, agrega por jogador e calcula total / por 90' / percentil.
2. `search(query)`        : aplica filtros de identificação e de estatísticas, ordena e pagina.
3. `bounds(scope)`        : limites reais de cada estatística no recorte (escala dos sliders).
4. `sheet(id, scope)`     : ficha completa do atleta agrupada por categoria.
5. `export_csv(query)`    : todos os resultados com todas as estatísticas.

Modos de filtro por estatística:
- `total` : valor agregado no recorte (ex.: 12 gols; 78,5% de passes certos);
- `p90`   : valor por 90 minutos (somente métricas de volume);
- `pct`   : percentil (0–100) dentro do papel tático (ST, WNG, CM_AM, DM, FB, CB, GK) entre os
            atletas do recorte — permite perfis sem limiares absolutos arbitrários.
"""
from __future__ import annotations

import io
import json
import math
import os
import sqlite3
import threading
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from core.explorer_catalog import (
    AUX_COLUMNS,
    CATEGORIES,
    CHARACTERISTIC_LABELS,
    FBREF_SOURCE_COLUMNS,
    FOOT_LABELS,
    POSITION_LABELS,
    PRESETS,
    ROLE_LABELS,
    SOURCE_FLAGS,
    SOURCE_LABELS,
    STAT_INDEX,
    STATS,
    WHOSCORED_SOURCE_COLUMNS,
    StatDef,
)
from core.seasons import normalize_season_label, season_year
from core.settings import DB_PATH
from core.sofascore_metrics import RAW_METRICS, column_name

Mode = Literal["total", "p90", "pct"]

SOFA_RAW_COLUMNS = [column_name(k) for k in RAW_METRICS]
MAX_SCOPE_CACHE = 12

LEGACY_METRIC_ALIASES: Dict[str, str] = {
    "xg": "expected_goals",
    "xa": "expected_assists",
    "shots": "total_shots",
    "pass_accuracy_pct": "accurate_passes_pct",
    "dribble_success_pct": "successful_dribbles_pct",
    "duels_won_total": "duels_won",
    "fouls": "fouls_committed",
}

DEFAULT_RADAR_KEYS_BY_ROLE: Dict[str, List[str]] = {
    "ST": [
        "goals", "expected_goals", "shots_on_target", "goal_conversion_pct",
        "touches_in_opp_box", "key_passes", "aerial_duels_won", "goal_involvements",
    ],
    "WNG": [
        "successful_dribbles", "key_passes", "expected_assists", "goals",
        "accurate_crosses", "touches_in_opp_box", "ws_through_balls_per_game", "goal_involvements",
    ],
    "CM_AM": [
        "key_passes", "expected_assists", "accurate_passes_pct", "accurate_final_third_passes",
        "successful_dribbles", "ball_recovery", "tackles_won", "goal_involvements",
    ],
    "DM": [
        "tackles_won", "interceptions", "ball_recovery", "duels_won_pct",
        "accurate_passes_pct", "accurate_long_balls", "fbref_team_ppm", "ground_duels_won",
    ],
    "FB": [
        "tackles_won", "interceptions", "accurate_crosses", "key_passes",
        "successful_dribbles", "duels_won", "ball_recovery", "accurate_passes_pct",
    ],
    "CB": [
        "aerial_duels_won", "aerial_duels_pct", "interceptions", "clearances",
        "tackles_won", "accurate_passes_pct", "accurate_long_balls", "duels_won_pct",
    ],
    "GK": [
        "saves_pct", "goals_prevented", "saves", "clean_sheets",
        "high_claims", "accurate_long_balls_pct", "fbref_team_ppm", "fbref_win_pct",
    ],
}
assert all(k in STAT_INDEX for keys in DEFAULT_RADAR_KEYS_BY_ROLE.values() for k in keys)


def _json_list(val: Any) -> List[Any]:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, str) and val.strip():
        try:
            parsed = json.loads(val)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


class ExplorerError(ValueError):
    """Erro de validação de consulta do Explorador (traduzido para HTTP 422 na API)."""


# =====================================================================================
# Contratos de entrada
# =====================================================================================
class StatFilter(BaseModel):
    key: str
    mode: Mode = "total"
    min: Optional[float] = None
    max: Optional[float] = None


class ScopeSpec(BaseModel):
    season_mode: Literal["latest", "selected", "all"] = "latest"
    seasons: List[str] = Field(default_factory=list)
    competitions: List[str] = Field(default_factory=list)
    min_minutes: int = Field(450, ge=0)


class IdentityFilter(BaseModel):
    name: Optional[str] = None
    roles: List[str] = Field(default_factory=list)
    positions: List[str] = Field(default_factory=list)
    leagues: List[str] = Field(default_factory=list)
    teams: List[str] = Field(default_factory=list)
    foot: List[str] = Field(default_factory=list)
    age_min: Optional[float] = None
    age_max: Optional[float] = None
    height_min: Optional[float] = None
    height_max: Optional[float] = None
    weight_min: Optional[float] = None
    weight_max: Optional[float] = None
    value_min: Optional[float] = None  # EUR
    value_max: Optional[float] = None  # EUR
    strengths: List[str] = Field(default_factory=list)            # precisa ter TODOS (SofaScore)
    exclude_weaknesses: List[str] = Field(default_factory=list)   # não pode ter NENHUM (SofaScore)
    require_sources: List[Literal["fbref", "transfermarkt", "whoscored"]] = Field(default_factory=list)


class ExplorerQuery(BaseModel):
    scope: ScopeSpec = Field(default_factory=ScopeSpec)
    identity: IdentityFilter = Field(default_factory=IdentityFilter)
    stats: List[StatFilter] = Field(default_factory=list)
    sort_by: Optional[str] = None
    sort_mode: Optional[Mode] = None
    sort_dir: Literal["asc", "desc"] = "desc"
    page: int = Field(1, ge=1)
    page_size: int = Field(12, ge=1, le=100)


class SheetRequest(BaseModel):
    player_id: int
    scope: ScopeSpec = Field(default_factory=ScopeSpec)


# =====================================================================================
# Utilitários
# =====================================================================================
def _fold(text: Any) -> str:
    """Minúsculas sem acentos, para busca por nome."""
    s = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def _clean(v: Any) -> Any:
    """Converte escalares numpy/pandas em tipos JSON válidos (NaN/NaT -> None)."""
    if v is None:
        return None
    if isinstance(v, (list, tuple, set, dict)):
        return v
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return None if not math.isfinite(float(v)) else round(float(v), 4)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _nice_ceil(x: float) -> float:
    """Arredonda para cima mantendo 2 algarismos significativos (8,27 -> 8,3; 487 -> 490)."""
    if not math.isfinite(x) or x <= 0:
        return 0.0
    unit = 10 ** (math.floor(math.log10(x)) - 1)
    return round(math.ceil(x / unit - 1e-9) * unit, 10)


def _nice_step(span: float, integer: bool) -> float:
    raw = span / 200.0 if span > 0 else 1.0
    exp = 10 ** math.floor(math.log10(raw))
    m = raw / exp
    step = 10 * exp
    for n in (1, 2, 5, 10):
        if m <= n + 1e-9:
            step = n * exp
            break
    return float(max(1, round(step))) if integer else float(max(round(step, 6), 0.01))


def _group_aggregate(df: pd.DataFrame, key_col: str, defs: List[StatDef], weight: pd.Series) -> pd.DataFrame:
    """Agrega colunas exclusivas (FBref/WhoScored): soma, máximo ou média ponderada por jogador."""
    out: Dict[str, pd.Series] = {}
    grp = df.groupby(key_col)
    for sd in defs:
        col = sd.base_column
        if col not in df.columns:
            continue
        if sd.agg == "sum":
            out[col] = grp[col].sum(min_count=1)
        elif sd.agg == "max":
            out[col] = grp[col].max()
        else:  # wavg
            valid = df[col].notna()
            w = weight.where(valid, 0.0)
            num = (df[col].fillna(0.0) * w).groupby(df[key_col]).sum()
            den = w.groupby(df[key_col]).sum()
            out[col] = num / den.where(den > 0)
    return pd.DataFrame(out)


# =====================================================================================
# Estruturas internas
# =====================================================================================
@dataclass
class _Dataset:
    mtime: float
    base: pd.DataFrame
    sofa: pd.DataFrame
    fbref: pd.DataFrame
    ws: pd.DataFrame
    seasons: List[Dict[str, Any]]
    competitions: List[Dict[str, Any]]


@dataclass
class _Scope:
    tot: pd.DataFrame
    p90: pd.DataFrame
    meta: pd.DataFrame
    roles: pd.Series
    _pct: Dict[str, pd.Series] = field(default_factory=dict)
    _role_bench: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def pct(self, key: str) -> pd.Series:
        """Percentil (0–100) do valor (por 90' quando elegível) dentro do papel tático."""
        if key not in self._pct:
            series = self.p90[key] if key in self.p90.columns else self.tot[key]
            self._pct[key] = series.groupby(self.roles).rank(pct=True) * 100.0
        return self._pct[key]

    def role_benchmarks(self, role: str) -> Dict[str, Any]:
        """Média e máximo de cada uma das 143 estatísticas para os pares da mesma função tática."""
        if role not in self._role_bench:
            mask = self.roles == role
            sub_tot = self.tot[mask]
            sub_p90 = self.p90[mask]
            self._role_bench[role] = {
                "pool_size": int(mask.sum()),
                "tot_mean": sub_tot.mean(numeric_only=True),
                "tot_max": sub_tot.max(numeric_only=True),
                "p90_mean": sub_p90.mean(numeric_only=True),
                "p90_max": sub_p90.max(numeric_only=True),
            }
        return self._role_bench[role]


# =====================================================================================
# Motor
# =====================================================================================
class ExplorerEngine:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DB_PATH
        self._lock = threading.RLock()
        self._data: Optional[_Dataset] = None
        self._scopes: "OrderedDict[tuple, _Scope]" = OrderedDict()

    # ------------------------------------------------------------------ carga
    def _load(self) -> _Dataset:
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Banco de dados '{self.db_path}' não encontrado.")
        mtime = os.path.getmtime(self.db_path)
        with self._lock:
            if self._data is not None and self._data.mtime == mtime:
                return self._data

            conn = sqlite3.connect(self.db_path)
            try:
                base = pd.read_sql(
                    """
                    SELECT mapping_id, sofascore_id, name, full_name, scout_role, scout_category,
                           position AS position_raw, current_team, current_league, birth_date, footed,
                           height, weight, market_value_eur, market_value_raw, transfermarkt_url,
                           whoscored_url, fbref_db_id, transfermarkt_id, whoscored_id,
                           player_strengths, player_weaknesses, player_style_of_play,
                           team_strengths, team_weaknesses, team_style
                    FROM v_player_profiles
                    WHERE sofascore_id IS NOT NULL
                    """,
                    conn,
                )
                positions = pd.read_sql(
                    "SELECT player_id, position FROM sofascore_player_positions ORDER BY player_id, ordinal", conn
                )
                chars = pd.read_sql(
                    "SELECT player_id, polarity, characteristic_name FROM v_sofascore_characteristics_named", conn
                )
                sofa = pd.read_sql(
                    f"SELECT player_id, season, competition, squad, {', '.join(SOFA_RAW_COLUMNS)} FROM sofascore_stats",
                    conn,
                )
                gk_cols = ["shots_on_target_against", "wins", "draws", "losses", "pens_allowed", "pens_missed_gk"]
                common = [c for c in FBREF_SOURCE_COLUMNS.values() if c not in gk_cols]
                outfield_sel = ", ".join(common + [f"NULL AS {c}" for c in gk_cols])
                keeper_sel = ", ".join(common + gk_cols)
                fbref = pd.read_sql(
                    f"""
                    SELECT player_id, season, {outfield_sel}
                    FROM fbref_outfield_stats WHERE COALESCE(is_national_team, 0) = 0
                    UNION ALL
                    SELECT player_id, season, {keeper_sel}
                    FROM fbref_keeper_stats WHERE COALESCE(is_national_team, 0) = 0
                    """,
                    conn,
                )
                ws = pd.read_sql(
                    f"""
                    SELECT player_id, season, minutes AS _ws_minutes, {', '.join(WHOSCORED_SOURCE_COLUMNS.values())}
                    FROM whoscored_player_season_stats
                    """,
                    conn,
                )
            finally:
                conn.close()

            base = base.drop_duplicates("sofascore_id").copy()
            base["sofascore_id"] = base["sofascore_id"].astype(int)
            base["mapping_id"] = base["mapping_id"].astype(int)
            base = base.set_index("sofascore_id", drop=False)
            base.index.name = None

            birth = pd.to_datetime(base["birth_date"], errors="coerce")
            today = pd.Timestamp.today().normalize()
            base["age"] = np.floor((today - birth).dt.days / 365.25)
            base["name_norm"] = (base["name"].fillna("") + " " + base["full_name"].fillna("")).map(_fold)

            pos_map = positions.groupby("player_id")["position"].apply(list).to_dict()
            base["positions"] = [pos_map.get(i, []) for i in base.index]
            pos_chars = chars[chars["polarity"] == "positive"].groupby("player_id")["characteristic_name"].apply(set).to_dict()
            neg_chars = chars[chars["polarity"] == "negative"].groupby("player_id")["characteristic_name"].apply(set).to_dict()
            base["strength_set"] = [pos_chars.get(i, set()) for i in base.index]
            base["weakness_set"] = [neg_chars.get(i, set()) for i in base.index]

            # ---- SofaScore (primária)
            sofa["season"] = sofa["season"].map(normalize_season_label)

            # ---- FBref -> sofascore_id
            fb_to_sofa = {int(f): int(s) for f, s in zip(base["fbref_db_id"], base["sofascore_id"]) if pd.notna(f)}
            fbref["sofascore_id"] = fbref["player_id"].map(fb_to_sofa)
            fbref = fbref.dropna(subset=["sofascore_id"]).copy()
            fbref["sofascore_id"] = fbref["sofascore_id"].astype(int)
            fbref["season"] = fbref["season"].map(normalize_season_label)
            fbref = fbref.rename(columns={v: k for k, v in FBREF_SOURCE_COLUMNS.items()}).drop(columns=["player_id"])

            # ---- WhoScored -> sofascore_id
            ws_to_sofa = {int(w): int(s) for w, s in zip(base["whoscored_id"], base["sofascore_id"]) if pd.notna(w)}
            ws["sofascore_id"] = ws["player_id"].map(ws_to_sofa)
            ws = ws.dropna(subset=["sofascore_id"]).copy()
            ws["sofascore_id"] = ws["sofascore_id"].astype(int)
            ws["season"] = ws["season"].map(normalize_season_label)
            ws = ws.rename(columns={v: k for k, v in WHOSCORED_SOURCE_COLUMNS.items()}).drop(columns=["player_id"])

            season_tbl = (
                sofa.groupby("season")["player_id"].nunique().rename("players").reset_index()
            )
            season_tbl["_y"] = season_tbl["season"].map(season_year)
            season_tbl = season_tbl.sort_values(["_y", "season"], ascending=[False, False])
            seasons = [{"value": r.season, "players": int(r.players)} for r in season_tbl.itertuples()]

            comp_tbl = (
                sofa.dropna(subset=["competition"]).groupby("competition")["player_id"].nunique().rename("players").reset_index()
                .sort_values(["players", "competition"], ascending=[False, True])
            )
            competitions = [{"value": r.competition, "players": int(r.players)} for r in comp_tbl.itertuples()]

            self._data = _Dataset(mtime, base, sofa, fbref, ws, seasons, competitions)
            self._scopes.clear()
            return self._data

    # ------------------------------------------------------------------ recorte
    def scope_result(self, scope: ScopeSpec) -> _Scope:
        data = self._load()
        key = (
            data.mtime, scope.season_mode, tuple(sorted(scope.seasons)),
            tuple(sorted(scope.competitions)), int(scope.min_minutes),
        )
        with self._lock:
            if key in self._scopes:
                self._scopes.move_to_end(key)
                return self._scopes[key]

        result = self._compute_scope(data, scope)
        with self._lock:
            self._scopes[key] = result
            while len(self._scopes) > MAX_SCOPE_CACHE:
                self._scopes.popitem(last=False)
        return result

    def _compute_scope(self, data: _Dataset, scope: ScopeSpec) -> _Scope:
        sofa = data.sofa
        if scope.competitions:
            sofa = sofa[sofa["competition"].isin(scope.competitions)]
        if scope.season_mode == "selected":
            if not scope.seasons:
                raise ExplorerError("Selecione ao menos uma temporada para o recorte.")
            sofa = sofa[sofa["season"].isin(scope.seasons)]

        per_season = sofa.groupby(["player_id", "season"], as_index=False)["minutes_played"].sum()
        per_season["minutes_played"] = per_season["minutes_played"].fillna(0)
        if scope.season_mode == "latest":
            per_season = per_season[per_season["minutes_played"] >= scope.min_minutes].copy()
            per_season["_year"] = per_season["season"].map(season_year)
            per_season = (
                per_season.sort_values(["player_id", "_year", "minutes_played"], ascending=[True, False, False])
                .drop_duplicates("player_id")
            )
        sel = per_season[["player_id", "season"]]
        rows = sofa.merge(sel, on=["player_id", "season"], how="inner")

        sum_cols = [c for c in SOFA_RAW_COLUMNS if c != "top_speed"]
        grp = rows.groupby("player_id")
        agg = grp[sum_cols].sum(min_count=1)
        agg["top_speed"] = grp["top_speed"].max()

        # metadados do recorte (exibição)
        comp_min = (
            rows.groupby(["player_id", "competition"], as_index=False)["minutes_played"].sum()
            .sort_values(["player_id", "minutes_played"], ascending=[True, False])
        )
        top_comps = comp_min.groupby("player_id")["competition"].apply(lambda s: list(s.head(4)))
        meta = pd.DataFrame({
            "scope_seasons": grp["season"].apply(
                lambda s: ", ".join(sorted({x for x in s if isinstance(x, str)}, key=season_year, reverse=True))
            ),
            "scope_competitions": top_comps,
            "scope_n_competitions": grp["competition"].nunique(),
            "scope_squads": grp["squad"].apply(lambda s: ", ".join(pd.unique(s.dropna()))),
        })

        # exclusivas FBref / WhoScored, restritas às mesmas temporadas escolhidas por jogador
        sel_sofa = sel.rename(columns={"player_id": "sofascore_id"})
        fb = data.fbref.merge(sel_sofa, on=["sofascore_id", "season"], how="inner")
        if not fb.empty:
            fb_defs = [sd for sd in STATS if sd.base_column in FBREF_SOURCE_COLUMNS and sd.derive is None]
            w = fb["fbref_matches_completed"].where(fb["fbref_matches_completed"] > 0).fillna(1.0)
            agg = agg.join(_group_aggregate(fb, "sofascore_id", fb_defs, w), how="left")
        ws = data.ws.merge(sel_sofa, on=["sofascore_id", "season"], how="inner")
        if not ws.empty:
            ws_defs = [sd for sd in STATS if sd.base_column in WHOSCORED_SOURCE_COLUMNS and sd.derive is None]
            w = ws["_ws_minutes"].where(ws["_ws_minutes"] > 0).fillna(1.0)
            agg = agg.join(_group_aggregate(ws, "sofascore_id", ws_defs, w), how="left")

        for sd in STATS:
            if sd.derive is None and sd.base_column not in agg.columns:
                agg[sd.base_column] = np.nan
        for name, fn in AUX_COLUMNS.items():
            agg[name] = fn(agg)

        agg = agg[agg["minutes_played"].fillna(0) >= scope.min_minutes]
        meta = meta.reindex(agg.index)

        totals: Dict[str, pd.Series] = {}
        for sd in STATS:
            vals = sd.derive(agg) if sd.derive is not None else agg[sd.base_column]
            if sd.scale != 1.0:
                vals = vals * sd.scale
            totals[sd.key] = vals.astype(float)
        tot = pd.DataFrame(totals, index=agg.index)

        mins = tot["minutes_played"].where(tot["minutes_played"] > 0)
        p90 = pd.DataFrame({sd.key: tot[sd.key] * 90.0 / mins for sd in STATS if sd.per90}, index=tot.index)
        roles = data.base["scout_role"].reindex(tot.index)
        return _Scope(tot=tot, p90=p90, meta=meta, roles=roles)

    # ------------------------------------------------------------------ schema
    def schema(self) -> Dict[str, Any]:
        data = self._load()
        base = data.base

        def _rng(col: str) -> Dict[str, Optional[float]]:
            s = base[col].dropna()
            return {"min": float(math.floor(s.min())) if len(s) else None,
                    "max": float(math.ceil(s.max())) if len(s) else None}

        leagues = sorted(base["current_league"].dropna().unique())
        team_league = (
            base.dropna(subset=["current_team"]).groupby("current_team")["current_league"]
            .agg(lambda s: s.dropna().mode().iloc[0] if s.dropna().size else None)
        )
        teams = [{"value": t, "group": l} for t, l in sorted(team_league.items())]
        pos_codes = sorted({p for lst in base["positions"] for p in lst})
        char_names = sorted({c for s in base["strength_set"] for c in s} | {c for s in base["weakness_set"] for c in s})

        stats = []
        for sd in STATS:
            stats.append({
                "key": sd.key, "label": sd.label, "category": sd.category, "description": sd.description,
                "source": sd.source, "source_label": SOURCE_LABELS.get(sd.source, sd.source),
                "unit": sd.unit, "decimals": sd.decimals, "per90": sd.per90,
                "modes": ["total", "p90", "pct"] if sd.per90 else ["total", "pct"],
            })
        return {
            "categories": CATEGORIES,
            "stats": stats,
            "roles": ROLE_LABELS,
            "positions": [{"value": p, "label": f"{p} · {POSITION_LABELS.get(p, p)}"} for p in pos_codes],
            "feet": [{"value": k, "label": v} for k, v in FOOT_LABELS.items()],
            "sources": SOURCE_FLAGS,
            "leagues": [{"value": l, "label": l} for l in leagues],
            "teams": teams,
            "characteristics": [{"value": c, "label": CHARACTERISTIC_LABELS.get(c, c)} for c in char_names],
            "seasons": data.seasons,
            "competitions": data.competitions,
            "identity_bounds": {
                "age": _rng("age"), "height": _rng("height"), "weight": _rng("weight"),
                "value_eur": {"min": 0.0, "max": float(base["market_value_eur"].max()) if base["market_value_eur"].notna().any() else 0.0},
            },
            "presets": PRESETS,
            "total_players": int(len(base)),
            "data_updated_at": datetime.fromtimestamp(data.mtime).strftime("%d/%m/%Y"),
        }

    # ------------------------------------------------------------------ limites dos sliders
    def bounds(self, scope: ScopeSpec) -> Dict[str, Any]:
        sc = self.scope_result(scope)
        out: Dict[str, Any] = {}

        def _calc(s: pd.Series, sd: StatDef, integer: bool, clip_outliers: bool = False) -> Dict[str, Any]:
            v = s.dropna()
            if v.empty:
                return {"available": False, "min": 0, "max": 1, "step": 1, "n": 0}
            vmin, vmax = float(v.min()), float(v.max())
            if sd.unit == "%":
                lo, hi = 0.0, 100.0
            else:
                hi = _nice_ceil(vmax)
                if clip_outliers and len(v) >= 20:
                    q = float(v.quantile(0.995))
                    if q > 0 and vmax > 3 * q:
                        hi = _nice_ceil(q)
                if vmin < 0:
                    lo = -_nice_ceil(-vmin)
                elif sd.floor0 or vmin < 1:
                    lo = 0.0
                else:
                    lo = float(math.floor(vmin))
                if hi <= lo:
                    hi = lo + 1.0
            return {"available": True, "min": lo, "max": hi, "step": _nice_step(hi - lo, integer), "n": int(len(v))}

        for sd in STATS:
            entry = {"total": _calc(sc.tot[sd.key], sd, integer=(sd.decimals == 0 and sd.unit == ""), clip_outliers=False),
                     "pct": {"available": True, "min": 0, "max": 100, "step": 1, "n": int(sc.tot[sd.key].notna().sum())}}
            if sd.per90:
                entry["p90"] = _calc(sc.p90[sd.key], sd, integer=False, clip_outliers=True)
            out[sd.key] = entry
        return {"players_in_scope": int(len(sc.tot)), "stats": out}

    # ------------------------------------------------------------------ busca
    def _identity_mask(self, df: pd.DataFrame, f: IdentityFilter) -> pd.Series:
        mask = pd.Series(True, index=df.index)
        if f.name and f.name.strip():
            tokens = _fold(f.name).split()
            mask &= df["name_norm"].map(lambda n: all(t in n for t in tokens))
        if f.roles:
            mask &= df["scout_role"].isin(f.roles)
        if f.positions:
            wanted = set(f.positions)
            mask &= df["positions"].map(lambda lst: bool(wanted.intersection(lst)))
        if f.leagues:
            mask &= df["current_league"].isin(f.leagues)
        if f.teams:
            mask &= df["current_team"].isin(f.teams)
        if f.foot:
            mask &= df["footed"].isin(f.foot)
        for col, lo, hi in (
            ("age", f.age_min, f.age_max), ("height", f.height_min, f.height_max),
            ("weight", f.weight_min, f.weight_max), ("market_value_eur", f.value_min, f.value_max),
        ):
            if lo is not None:
                mask &= df[col] >= lo
            if hi is not None:
                mask &= df[col] <= hi
        if f.strengths:
            need = set(f.strengths)
            mask &= df["strength_set"].map(lambda s: need.issubset(s))
        if f.exclude_weaknesses:
            avoid = set(f.exclude_weaknesses)
            mask &= df["weakness_set"].map(lambda s: not avoid.intersection(s))
        flag_cols = {"fbref": "fbref_db_id", "transfermarkt": "transfermarkt_id", "whoscored": "whoscored_id"}
        for src in f.require_sources:
            mask &= df[flag_cols[src]].notna()
        return mask

    @staticmethod
    def _stat_series(sc: _Scope, key: str, mode: str) -> pd.Series:
        sd = STAT_INDEX.get(key)
        if sd is None:
            raise ExplorerError(f"Estatística desconhecida: '{key}'.")
        if mode == "total":
            return sc.tot[key]
        if mode == "p90":
            if not sd.per90:
                raise ExplorerError(f"'{sd.label}' não possui modo por 90 minutos.")
            return sc.p90[key]
        if mode == "pct":
            return sc.pct(key)
        raise ExplorerError(f"Modo inválido: '{mode}'.")

    def _run_filters(self, q: ExplorerQuery) -> Tuple[pd.DataFrame, _Scope]:
        data = self._load()
        sc = self.scope_result(q.scope)
        needs_stats = bool(q.stats) or q.scope.min_minutes > 0
        df = data.base.join(sc.meta, how="inner" if needs_stats else "left")
        df = df[self._identity_mask(df, q.identity).reindex(df.index, fill_value=False)] if len(df) else df
        for sf in q.stats:
            series = self._stat_series(sc, sf.key, sf.mode).reindex(df.index)
            keep = series.notna()
            if sf.min is not None:
                keep &= series >= sf.min
            if sf.max is not None:
                keep &= series <= sf.max
            df = df[keep]
        return df, sc

    def _sorted(self, df: pd.DataFrame, sc: _Scope, q: ExplorerQuery) -> pd.DataFrame:
        if df.empty:
            return df
        sort_by = q.sort_by or (q.stats[0].key if q.stats else "market_value")
        ascending = q.sort_dir == "asc"
        if sort_by == "name":
            key = df["name"].map(_fold)
        elif sort_by == "age":
            key = df["age"]
        elif sort_by == "market_value":
            key = df["market_value_eur"]
        else:
            mode = q.sort_mode or next((s.mode for s in q.stats if s.key == sort_by), "total")
            key = self._stat_series(sc, sort_by, mode).reindex(df.index)
        order = pd.DataFrame({"k": key, "n": df["name"].map(_fold)}, index=df.index)
        order = order.sort_values(["k", "n"], ascending=[ascending, True], na_position="last", kind="mergesort")
        return df.loc[order.index]

    def _identity_item(self, row: pd.Series) -> Dict[str, Any]:
        age = row.get("age")
        return {
            "mapping_id": int(row["mapping_id"]),
            "sofascore_id": int(row["sofascore_id"]),
            "name": row["name"],
            "full_name": _clean(row.get("full_name")),
            "scout_role": row["scout_role"],
            "scout_category": row["scout_category"],
            "positions": list(row["positions"]) if isinstance(row["positions"], list) else [],
            "position_raw": _clean(row.get("position_raw")),
            "current_team": _clean(row.get("current_team")),
            "current_league": _clean(row.get("current_league")),
            "age": int(age) if pd.notna(age) else None,
            "birth_date": _clean(row.get("birth_date")),
            "footed": _clean(row.get("footed")),
            "height": _clean(row.get("height")),
            "weight": _clean(row.get("weight")),
            "market_value_eur": _clean(row.get("market_value_eur")),
            "market_value_raw": _clean(row.get("market_value_raw")),
            "transfermarkt_url": _clean(row.get("transfermarkt_url")),
            "whoscored_url": _clean(row.get("whoscored_url")),
            "sources": {
                "sofascore": True,
                "fbref": bool(pd.notna(row.get("fbref_db_id"))),
                "transfermarkt": bool(pd.notna(row.get("transfermarkt_id"))),
                "whoscored": bool(pd.notna(row.get("whoscored_id"))),
            },
        }

    def search(self, q: ExplorerQuery) -> Dict[str, Any]:
        t0 = datetime.now()
        df, sc = self._run_filters(q)
        df = self._sorted(df, sc, q)
        total = int(len(df))
        start = (q.page - 1) * q.page_size
        page_df = df.iloc[start:start + q.page_size]

        role_defaults = {
            "GK": ["saves_pct", "goals_prevented", "clean_sheets", "saves"],
            "CB": ["aerial_duels_won", "interceptions", "accurate_passes_pct", "tackles"],
            "FB": ["tackles", "key_passes", "accurate_crosses", "successful_dribbles"],
            "DM": ["tackles", "interceptions", "ball_recovery", "duels_won_pct"],
            "CM_AM": ["key_passes", "assists", "accurate_passes_pct", "goal_involvements"],
            "WNG": ["successful_dribbles", "key_passes", "goal_involvements", "goals"],
            "ST": ["goals", "expected_goals", "shots_on_target", "goal_involvements"],
        }
        active = list(dict.fromkeys((s.key, s.mode) for s in q.stats))
        active_keys = {k for k, _ in active}
        items = []
        for sid, row in page_df.iterrows():
            item = self._identity_item(row)
            in_scope = sid in sc.tot.index
            item["scope"] = {
                "seasons": _clean(row.get("scope_seasons")),
                "squads": _clean(row.get("scope_squads")),
                "competitions": row.get("scope_competitions") if isinstance(row.get("scope_competitions"), list) else [],
                "n_competitions": _clean(row.get("scope_n_competitions")),
                "minutes_played": _clean(sc.tot["minutes_played"].get(sid)) if in_scope else None,
                "appearances": _clean(sc.tot["appearances"].get(sid)) if in_scope else None,
            }
            display_pairs: List[Tuple[str, str, bool]] = [(k, m, True) for k, m in active]
            if q.sort_by and q.sort_by in STAT_INDEX and q.sort_by not in active_keys:
                display_pairs.append((q.sort_by, q.sort_mode or "total", False))
            if len(display_pairs) < 4:
                for dk in role_defaults.get(row["scout_role"], role_defaults["CM_AM"]):
                    if dk not in {p[0] for p in display_pairs}:
                        display_pairs.append((dk, "total", False))
                    if len(display_pairs) >= 4:
                        break
            metrics = []
            if in_scope:
                for key, mode, is_filtered in display_pairs:
                    sd = STAT_INDEX[key]
                    metrics.append({
                        "key": key, "mode": mode, "filtered": is_filtered,
                        "value": _clean(self._stat_series(sc, key, mode).get(sid)),
                        "total": _clean(sc.tot[key].get(sid)),
                        "p90": _clean(sc.p90[key].get(sid)) if sd.per90 else None,
                        "pct": _clean(sc.pct(key).get(sid)),
                    })
            item["metrics"] = metrics
            items.append(item)

        return {
            "total": total,
            "page": q.page,
            "page_size": q.page_size,
            "pages": max(1, math.ceil(total / q.page_size)),
            "players_in_scope": int(len(sc.tot)),
            "items": items,
            "elapsed_ms": int((datetime.now() - t0).total_seconds() * 1000),
        }

    # ------------------------------------------------------------------ ficha completa
    def sheet(self, req: SheetRequest) -> Optional[Dict[str, Any]]:
        data = self._load()
        sc = self.scope_result(req.scope)
        sid = int(req.player_id)
        if sid not in data.base.index or sid not in sc.tot.index:
            return None
        row = data.base.loc[sid].copy()
        tot_row = sc.tot.loc[sid]
        categories = []
        for cat in CATEGORIES:
            stats = []
            for sd in STATS:
                if sd.category != cat["id"]:
                    continue
                total = tot_row[sd.key]
                if pd.isna(total) or total == 0:
                    continue
                stats.append({
                    "key": sd.key, "label": sd.label, "description": sd.description, "unit": sd.unit,
                    "decimals": sd.decimals, "total": _clean(total),
                    "p90": _clean(sc.p90[sd.key].get(sid)) if sd.per90 else None,
                    "pct": _clean(sc.pct(sd.key).get(sid)),
                })
            if stats:
                categories.append({**cat, "stats": stats})
        meta = sc.meta.loc[sid]
        return {
            "player": self._identity_item(row),
            "scope": {
                "seasons": _clean(meta.get("scope_seasons")),
                "squads": _clean(meta.get("scope_squads")),
                "minutes_played": _clean(tot_row["minutes_played"]),
            },
            "categories": categories,
        }

    # ------------------------------------------------------------------ exportação
    def export_csv(self, q: ExplorerQuery) -> str:
        df, sc = self._run_filters(q)
        df = self._sorted(df, sc, q)
        cols = ["mapping_id", "name", "full_name", "scout_role", "position_raw", "current_team", "current_league",
                "age", "birth_date", "footed", "height", "weight", "market_value_eur", "market_value_raw",
                "scope_seasons", "scope_squads"]
        out = df[cols].copy()
        out["positions"] = df["positions"].map(lambda p: ",".join(p))
        tot = sc.tot.reindex(df.index)
        p90 = sc.p90.reindex(df.index).add_suffix("_p90")
        out = pd.concat([out, tot, p90], axis=1)
        buf = io.StringIO()
        out.to_csv(buf, index=False)
        return buf.getvalue()

    # ------------------------------------------------------------------ rankings & líderes (todas as 143 estatísticas)
    def rankings(
        self,
        metric: str = "goals",
        mode: str = "auto",
        order: str = "desc",
        role: Optional[str] = None,
        category: Optional[str] = None,
        league: Optional[str] = None,
        season: Optional[str] = None,
        competition: Optional[str] = None,
        min_minutes: int = 450,
        limit: int = 20,
    ) -> Dict[str, Any]:
        canon_key = LEGACY_METRIC_ALIASES.get(metric, metric)
        sd = STAT_INDEX.get(canon_key)
        if sd is None:
            raise ExplorerError(f"Métrica '{metric}' não encontrada no catálogo ({len(STAT_INDEX)} estatísticas disponíveis).")

        if not season or season == "latest":
            scope = ScopeSpec(season_mode="latest", competitions=[competition] if competition else [], min_minutes=min_minutes)
        elif season == "all":
            scope = ScopeSpec(season_mode="all", competitions=[competition] if competition else [], min_minutes=min_minutes)
        else:
            scope = ScopeSpec(season_mode="selected", seasons=[season], competitions=[competition] if competition else [], min_minutes=min_minutes)

        data = self._load()
        sc = self.scope_result(scope)
        df = data.base.join(sc.meta, how="inner")

        if league:
            df = df[df["current_league"] == league]

        if mode == "p90" and sd.per90:
            eff_mode = "p90"
        elif mode == "total" or not sd.per90:
            eff_mode = "total"
        else:
            eff_mode = "p90" if sd.per90 else "total"

        metric_meta = {
            "key": sd.key,
            "label": sd.label,
            "category": sd.category,
            "description": sd.description,
            "source": sd.source,
            "source_label": SOURCE_LABELS.get(sd.source, sd.source),
            "unit": sd.unit,
            "decimals": sd.decimals,
            "per90": sd.per90,
        }

        if df.empty:
            return {
                "metric": canon_key,
                "metric_meta": metric_meta,
                "effective_mode": eff_mode,
                "order": order,
                "scout_role": role,
                "season": season,
                "league": league,
                "min_minutes": min_minutes,
                "eligible_players": 0,
                "total": 0,
                "rankings": [],
                "benchmarks_by_category": [],
                "benchmarks_by_role": [],
            }

        val_series = (sc.p90[sd.key] if eff_mode == "p90" else sc.tot[sd.key]).reindex(df.index)
        dec_places = max(sd.decimals, 2) if eff_mode == "p90" else sd.decimals

        # Benchmarks posicionais sobre o universo elegível (como no Scout-Brazil-Serie-A)
        cat_labels = [
            ("ATT", "Atacantes (ATT)"),
            ("MID", "Meio-Campistas (MID)"),
            ("DEF", "Defensores (DEF)"),
            ("GK", "Goleiros (GK)"),
        ]
        benchmarks_cat = []
        for code, lbl in cat_labels:
            sub = val_series[df["scout_category"] == code].dropna()
            if len(sub) == 0:
                continue
            benchmarks_cat.append({
                "code": code,
                "label": lbl,
                "count": int(len(sub)),
                "mean": round(float(sub.mean()), max(dec_places, 2)),
                "median": round(float(sub.median()), max(dec_places, 2)),
                "max": round(float(sub.max()), max(dec_places, 2)),
                "min": round(float(sub.min()), max(dec_places, 2)),
            })

        benchmarks_role = []
        for r_info in ROLE_LABELS:
            code = r_info["value"]
            sub = val_series[df["scout_role"] == code].dropna()
            if len(sub) == 0:
                continue
            benchmarks_role.append({
                "code": code,
                "label": r_info["label"],
                "count": int(len(sub)),
                "mean": round(float(sub.mean()), max(dec_places, 2)),
                "median": round(float(sub.median()), max(dec_places, 2)),
                "max": round(float(sub.max()), max(dec_places, 2)),
                "min": round(float(sub.min()), max(dec_places, 2)),
            })

        if role:
            df = df[df["scout_role"] == role.upper()]
        if category:
            df = df[df["scout_category"] == category.upper()]

        ranked_vals = val_series.reindex(df.index)
        valid_mask = ranked_vals.notna()
        df = df[valid_mask]
        ranked_vals = ranked_vals[valid_mask]
        eligible_count = int(len(df))

        asc = order == "asc"
        order_df = pd.DataFrame({
            "v": ranked_vals,
            "m": sc.tot["minutes_played"].reindex(df.index).fillna(0),
        }, index=df.index).sort_values(["v", "m"], ascending=[asc, False], kind="mergesort")

        top_df = df.loc[order_df.index].head(limit)
        pct_series = sc.pct(sd.key)

        results = []
        for rank_pos, (sid, r) in enumerate(top_df.iterrows(), 1):
            raw_v = sc.tot[sd.key].get(sid)
            p90_v = sc.p90[sd.key].get(sid) if sd.per90 else raw_v
            rk_v = ranked_vals.get(sid)
            pct_v = pct_series.get(sid)
            mins_v = sc.tot["minutes_played"].get(sid)
            apps_v = sc.tot["appearances"].get(sid)
            age_v = r.get("age")

            results.append({
                "rank": rank_pos,
                "mapping_id": int(r["mapping_id"]),
                "sofascore_id": int(sid),
                "name": str(r["name"]),
                "scout_role": str(r["scout_role"]),
                "scout_category": str(r["scout_category"]),
                "current_team": str(r["current_team"] or "Sem clube"),
                "current_league": str(r["current_league"] or "N/A"),
                "age": int(age_v) if pd.notna(age_v) else None,
                "season_used": _clean(r.get("scope_seasons")),
                "minutes_played": int(round(float(mins_v))) if mins_v is not None and pd.notna(mins_v) else 0,
                "appearances": int(round(float(apps_v))) if apps_v is not None and pd.notna(apps_v) else None,
                "raw_value": round(float(raw_v), max(sd.decimals, 2) if sd.decimals > 0 else 0) if raw_v is not None and pd.notna(raw_v) else None,
                "p90_value": round(float(p90_v), max(sd.decimals, 2)) if p90_v is not None and pd.notna(p90_v) else None,
                "ranked_value": round(float(rk_v), max(dec_places, 2) if dec_places > 0 else 0) if rk_v is not None and pd.notna(rk_v) else None,
                "percentile": round(float(pct_v), 1) if pct_v is not None and pd.notna(pct_v) else None,
                "market_value_raw": str(r["market_value_raw"]) if pd.notna(r["market_value_raw"]) else "N/A",
            })

        return {
            "metric": canon_key,
            "metric_meta": metric_meta,
            "effective_mode": eff_mode,
            "order": order,
            "scout_role": role,
            "season": season,
            "league": league,
            "min_minutes": min_minutes,
            "eligible_players": eligible_count,
            "total": len(results),
            "rankings": results,
            "benchmarks_by_category": benchmarks_cat,
            "benchmarks_by_role": benchmarks_role,
        }

    # ------------------------------------------------------------------ diretório leve de atletas (874 jogadores)
    def players_directory(self) -> List[Dict[str, Any]]:
        data = self._load()
        df = data.base.sort_values(
            by=["market_value_eur", "name"],
            ascending=[False, True],
            na_position="last",
            kind="mergesort",
        )
        items: List[Dict[str, Any]] = []
        for sid, r in df.iterrows():
            items.append({
                "mapping_id": int(r["mapping_id"]),
                "sofascore_id": int(sid),
                "name": str(r["name"]),
                "scout_role": str(r["scout_role"]),
                "scout_category": str(r["scout_category"]),
                "current_team": str(r["current_team"] or "Sem clube"),
                "current_league": str(r["current_league"] or ""),
                "market_value_raw": str(r["market_value_raw"]) if pd.notna(r["market_value_raw"]) else None,
            })
        return items

    # ------------------------------------------------------------------ resolução de atleta & recorte p/ Raio-X & Radar
    def _resolve_player_id(self, player_identifier: str) -> Optional[int]:
        data = self._load()
        raw = str(player_identifier or "").strip()
        if not raw:
            return None
        if raw.isdigit():
            num = int(raw)
            if num in data.base.index:
                return num
            sub = data.base[data.base["mapping_id"] == num]
            if not sub.empty:
                return int(sub.index[0])
            return None

        folded = _fold(raw)
        if not folded:
            return None
        exact = data.base[data.base["name"].fillna("").map(_fold) == folded]
        if not exact.empty:
            exact = exact.sort_values("market_value_eur", ascending=False, na_position="last")
            return int(exact.index[0])

        tokens = folded.split()
        matches = data.base[data.base["name_norm"].map(lambda n: all(t in n for t in tokens))]
        if matches.empty:
            return None
        matches = matches.sort_values("market_value_eur", ascending=False, na_position="last")
        return int(matches.index[0])

    @staticmethod
    def _build_scope(season: Optional[str], min_minutes: int) -> ScopeSpec:
        if not season or season == "latest":
            return ScopeSpec(season_mode="latest", min_minutes=min_minutes)
        if season == "all":
            return ScopeSpec(season_mode="all", min_minutes=min_minutes)
        return ScopeSpec(season_mode="selected", seasons=[normalize_season_label(season)], min_minutes=min_minutes)

    def _resolve_player_scope(self, sid: int, season: Optional[str], min_minutes: int) -> Tuple[_Scope, int]:
        eff_min = max(0, int(min_minutes))
        sc = self.scope_result(self._build_scope(season, eff_min))
        if sid in sc.tot.index:
            return sc, eff_min
        for fallback_min in (90, 1, 0):
            if eff_min > fallback_min:
                sc_fb = self.scope_result(self._build_scope(season, fallback_min))
                if sid in sc_fb.tot.index:
                    return sc_fb, fallback_min
        return sc, eff_min

    # ------------------------------------------------------------------ raio-x & radar completo (todas as 143 estatísticas)
    def dossier(
        self,
        player_identifier: str,
        season: Optional[str] = None,
        min_minutes: int = 450,
        radar_metrics: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        data = self._load()
        sid = self._resolve_player_id(player_identifier)
        if sid is None or sid not in data.base.index:
            return None

        row = data.base.loc[sid]
        role = str(row["scout_role"] or "CM_AM")
        sc, eff_min = self._resolve_player_scope(sid, season, min_minutes)
        in_scope = sid in sc.tot.index
        bench = sc.role_benchmarks(role) if in_scope else {
            "pool_size": 0,
            "tot_mean": pd.Series(dtype=float),
            "tot_max": pd.Series(dtype=float),
            "p90_mean": pd.Series(dtype=float),
            "p90_max": pd.Series(dtype=float),
        }

        # Temporadas disponíveis especificamente para este atleta
        p_sofa = data.sofa[data.sofa["player_id"] == sid]
        avail_seasons: List[Dict[str, Any]] = []
        if not p_sofa.empty:
            s_grp = (
                p_sofa.groupby("season", as_index=False)["minutes_played"]
                .sum()
            )
            s_grp["_y"] = s_grp["season"].map(season_year)
            s_grp = s_grp.sort_values(["_y", "season"], ascending=[False, False])
            avail_seasons = [
                {"season": str(r.season), "minutes": int(round(float(r.minutes_played or 0)))}
                for r in s_grp.itertuples()
            ]

        meta_row = sc.meta.loc[sid] if (in_scope and sid in sc.meta.index) else None
        tot_row = sc.tot.loc[sid] if in_scope else None

        def _fmt_num(val: Any, dec: int) -> Optional[float]:
            if val is None or (isinstance(val, (float, np.floating)) and (math.isnan(float(val)) or not math.isfinite(float(val)))):
                return None
            try:
                if pd.isna(val):
                    return None
            except Exception:
                pass
            f = float(val)
            return round(f, dec) if dec > 0 else round(f, 2) if not f.is_integer() else int(round(f))

        # Constrói TODAS as 143 estatísticas agrupadas nas 12 categorias
        stat_lookup: Dict[str, Dict[str, Any]] = {}
        categories_out: List[Dict[str, Any]] = []
        populated_count = 0

        for cat in CATEGORIES:
            cat_stats: List[Dict[str, Any]] = []
            cat_non_zero = 0
            for sd in STATS:
                if sd.category != cat["id"]:
                    continue
                raw_v = tot_row[sd.key] if tot_row is not None else None
                p90_v = sc.p90[sd.key].get(sid) if (in_scope and sd.per90) else None
                pct_v = sc.pct(sd.key).get(sid) if in_scope else None
                mean_raw_v = bench["tot_mean"].get(sd.key) if in_scope else None
                mean_p90_v = bench["p90_mean"].get(sd.key) if (in_scope and sd.per90) else None
                max_raw_v = bench["tot_max"].get(sd.key) if in_scope else None
                max_p90_v = bench["p90_max"].get(sd.key) if (in_scope and sd.per90) else None

                raw_clean = _fmt_num(raw_v, sd.decimals)
                p90_clean = _fmt_num(p90_v, max(sd.decimals, 2)) if sd.per90 else None
                pct_clean = _fmt_num(pct_v, 1)
                mean_raw_clean = _fmt_num(mean_raw_v, max(sd.decimals, 2) if sd.decimals > 0 else 1)
                mean_p90_clean = _fmt_num(mean_p90_v, max(sd.decimals, 2)) if sd.per90 else None
                max_raw_clean = _fmt_num(max_raw_v, sd.decimals)
                max_p90_clean = _fmt_num(max_p90_v, max(sd.decimals, 2)) if sd.per90 else None

                has_val = raw_clean is not None and raw_clean != 0
                if has_val:
                    populated_count += 1
                    cat_non_zero += 1

                entry = {
                    "key": sd.key,
                    "label": sd.label,
                    "category": sd.category,
                    "description": sd.description,
                    "source": sd.source,
                    "source_label": SOURCE_LABELS.get(sd.source, sd.source),
                    "unit": sd.unit,
                    "decimals": sd.decimals,
                    "per90": sd.per90,
                    "raw_value": raw_clean,
                    "p90_value": p90_clean,
                    "role_mean_raw": mean_raw_clean,
                    "role_mean_p90": mean_p90_clean,
                    "role_max_raw": max_raw_clean,
                    "role_max_p90": max_p90_clean,
                    "percentile": pct_clean,
                    "has_value": has_val,
                }
                stat_lookup[sd.key] = entry
                cat_stats.append(entry)

            categories_out.append({
                "id": cat["id"],
                "label": cat["label"],
                "icon": cat["icon"],
                "total_count": len(cat_stats),
                "populated_count": cat_non_zero,
                "stats": cat_stats,
            })

        # Seleciona os eixos do Radar (personalizados ou template tático de 8 eixos da função)
        default_keys = DEFAULT_RADAR_KEYS_BY_ROLE.get(role, DEFAULT_RADAR_KEYS_BY_ROLE["CM_AM"])
        if radar_metrics:
            chosen_keys = []
            for mk in radar_metrics:
                ck = LEGACY_METRIC_ALIASES.get(mk, mk)
                if ck in STAT_INDEX and ck not in chosen_keys:
                    chosen_keys.append(ck)
            if not chosen_keys:
                chosen_keys = list(default_keys)
        else:
            chosen_keys = list(default_keys)

        radar_items: List[Dict[str, Any]] = []
        for k in chosen_keys:
            st_entry = stat_lookup[k]
            radar_items.append({
                "metric_key": k,
                "label": f"{st_entry['label']} /90" if st_entry["per90"] else st_entry["label"],
                "short_label": st_entry["label"],
                "unit": st_entry["unit"],
                "decimals": st_entry["decimals"],
                "per90": st_entry["per90"],
                "source_label": st_entry["source_label"],
                "raw_value": st_entry["raw_value"],
                "p90_value": st_entry["p90_value"],
                "role_mean": st_entry["role_mean_p90"] if st_entry["per90"] else st_entry["role_mean_raw"],
                "percentile": st_entry["percentile"],
            })

        pos_list = list(row["positions"]) if isinstance(row["positions"], list) else []
        sofa_pos = sorted(CHARACTERISTIC_LABELS.get(c, c) for c in (row["strength_set"] or set()))
        sofa_neg = sorted(CHARACTERISTIC_LABELS.get(c, c) for c in (row["weakness_set"] or set()))

        mins_played = int(round(float(tot_row["minutes_played"]))) if (tot_row is not None and pd.notna(tot_row["minutes_played"])) else 0
        apps_played = int(round(float(tot_row["appearances"]))) if (tot_row is not None and pd.notna(tot_row["appearances"])) else 0
        comps_used = meta_row["scope_competitions"] if (meta_row is not None and isinstance(meta_row.get("scope_competitions"), list)) else []
        seasons_used = str(_clean(meta_row.get("scope_seasons")) or (season or "N/A")) if meta_row is not None else (season or "N/A")
        squads_used = _clean(meta_row.get("scope_squads")) if meta_row is not None else _clean(row.get("current_team"))

        return {
            "has_stats": in_scope,
            "profile": {
                "mapping_id": int(row["mapping_id"]),
                "sofascore_id": int(sid),
                "name": str(row["name"]),
                "full_name": str(row["full_name"]) if pd.notna(row["full_name"]) and row["full_name"] else None,
                "scout_role": role,
                "scout_category": str(row["scout_category"]),
                "position_raw": str(row["position_raw"]) if pd.notna(row["position_raw"]) else None,
                "positions": pos_list,
                "positions_labels": [f"{p} · {POSITION_LABELS.get(p, p)}" for p in pos_list],
                "current_team": str(row["current_team"]) if pd.notna(row["current_team"]) else "Sem clube",
                "current_league": str(row["current_league"]) if pd.notna(row["current_league"]) else "N/A",
                "age": int(row["age"]) if pd.notna(row["age"]) else None,
                "birth_date": str(row["birth_date"]) if pd.notna(row["birth_date"]) else None,
                "footed": _clean(row.get("footed")),
                "footed_label": FOOT_LABELS.get(row.get("footed"), _clean(row.get("footed"))),
                "height": int(row["height"]) if pd.notna(row["height"]) else None,
                "weight": int(row["weight"]) if pd.notna(row["weight"]) else None,
                "season": seasons_used,
                "competition": ", ".join(comps_used) if comps_used else "Todas as competições",
                "competitions": comps_used,
                "squads": squads_used,
                "minutes_played": mins_played,
                "appearances": apps_played,
                "requested_min_minutes": int(min_minutes),
                "effective_min_minutes": int(eff_min),
                "role_pool_size": int(bench["pool_size"]),
                "available_seasons": avail_seasons,
                "market_value_eur": int(row["market_value_eur"]) if pd.notna(row["market_value_eur"]) else None,
                "market_value_raw": str(row["market_value_raw"]) if pd.notna(row["market_value_raw"]) else None,
                "transfermarkt_url": str(row["transfermarkt_url"]) if pd.notna(row["transfermarkt_url"]) else None,
                "whoscored_url": str(row["whoscored_url"]) if pd.notna(row["whoscored_url"]) else None,
            },
            "characteristics": {
                "player_strengths": _json_list(row.get("player_strengths")),
                "player_weaknesses": _json_list(row.get("player_weaknesses")),
                "player_style_of_play": _json_list(row.get("player_style_of_play")),
                "team_strengths": _json_list(row.get("team_strengths")),
                "team_weaknesses": _json_list(row.get("team_weaknesses")),
                "team_style": _json_list(row.get("team_style")),
                "sofascore_strengths": sofa_pos,
                "sofascore_weaknesses": sofa_neg,
            },
            "total_stats": len(STATS),
            "populated_stats": populated_count,
            "default_radar_keys": list(default_keys),
            "default_radar_by_role": DEFAULT_RADAR_KEYS_BY_ROLE,
            "radar": radar_items,
            "categories": categories_out,
        }

    # ------------------------------------------------------------------ similaridade vetorial (sobre qualquer conjunto das 143 estatísticas)
    def similar(
        self,
        player_identifier: str,
        season: Optional[str] = None,
        top_n: int = 5,
        min_minutes: int = 450,
        metrics: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        data = self._load()
        sid = self._resolve_player_id(player_identifier)
        if sid is None or sid not in data.base.index:
            return []

        target_row = data.base.loc[sid]
        role = str(target_row["scout_role"] or "CM_AM")
        sc, _ = self._resolve_player_scope(sid, season, min_minutes)
        if sid not in sc.tot.index:
            return []

        peer_ids = sc.roles[sc.roles == role].index
        if len(peer_ids) < 2:
            return []

        default_keys = DEFAULT_RADAR_KEYS_BY_ROLE.get(role, DEFAULT_RADAR_KEYS_BY_ROLE["CM_AM"])
        chosen_keys: List[str] = []
        if metrics:
            for mk in metrics:
                ck = LEGACY_METRIC_ALIASES.get(mk, mk)
                if ck in STAT_INDEX and ck not in chosen_keys:
                    chosen_keys.append(ck)
        if not chosen_keys:
            chosen_keys = list(default_keys)

        pct_df = pd.DataFrame(
            {k: sc.pct(k).reindex(peer_ids) for k in chosen_keys},
            index=peer_ids,
        ).fillna(50.0)

        target_vec = pct_df.loc[sid].values
        matrix = pct_df.values
        max_dist = math.sqrt(len(chosen_keys) * (100.0 ** 2))
        distances = np.linalg.norm(matrix - target_vec, axis=1)
        sims = (1.0 - (distances / max_dist)) * 100.0

        sim_series = pd.Series(sims, index=peer_ids).drop(index=sid, errors="ignore")
        top_ids = sim_series.sort_values(ascending=False).head(top_n).index

        results: List[Dict[str, Any]] = []
        for pid in top_ids:
            r = data.base.loc[pid]
            mins_v = sc.tot["minutes_played"].get(pid)
            meta_r = sc.meta.loc[pid] if pid in sc.meta.index else None
            results.append({
                "mapping_id": int(r["mapping_id"]),
                "sofascore_id": int(pid),
                "player_name": str(r["name"]),
                "scout_role": str(r["scout_role"]),
                "current_team": str(r["current_team"] or "Sem clube"),
                "current_league": str(r["current_league"] or "N/A"),
                "similarity_pct": round(float(sim_series.loc[pid]), 1),
                "market_value_raw": str(r["market_value_raw"]) if pd.notna(r["market_value_raw"]) else "N/A",
                "minutes_played": int(round(float(mins_v))) if mins_v is not None and pd.notna(mins_v) else 0,
                "season_used": _clean(meta_r.get("scope_seasons")) if meta_r is not None else None,
            })
        return results


_ENGINE: Optional[ExplorerEngine] = None


def get_engine() -> ExplorerEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = ExplorerEngine()
    return _ENGINE
