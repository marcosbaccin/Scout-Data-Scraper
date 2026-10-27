"""
⚽ Scout Data Intelligence API (FastAPI)

API RESTful para consulta, filtragem, inteligência e análise avançada de dados
de jogadores brasileiros nas 11 principais ligas globais de futebol:
- /players: Busca e listagem com filtros avançados por papel tático, liga, clube e valuation.
- /players/{id}: Dossiê cadastral detalhado com características qualitativas das 4 fontes.
- /players/{id}/dossier: Dossiê analítico com Radar Chart P90 e percentis ranqueados por posição.
- /players/{id}/similar: Motor vetorial de similaridade de atletas na mesma função tática.
- /analytics/rankings: Rankings e líderes por métrica volumétrica e P90.
- /analytics/compare: Comparativo lado a lado de múltiplos atletas para scout comparado.
- /metadata: Filtros e opções dinâmicas para preenchimento de UIs e dashboards.
"""
import json
import os
import sqlite3
import sys
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from pydantic import BaseModel, Field

# Ajusta path para importar módulos da raiz do projeto
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from analytics_engine import ScoutAnalyticsEngine, RADAR_METRICS_BY_ROLE
from core.settings import DB_PATH

app = FastAPI(
    title="⚽ Scout Data Intelligence API",
    version="2.0",
    description="API RESTful de Scouting Esportivo de Alto Desempenho para Atletas Brasileiros",
)

# Libera CORS para frontends (Streamlit, React, Vite, Next.js)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine_analytics = ScoutAnalyticsEngine(db_path=DB_PATH)


def get_db_connection() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=503, detail="Banco de dados scout.db não inicializado.")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def safe_json_loads(val: Any) -> Any:
    if not val or not isinstance(val, str):
        return val
    try:
        return json.loads(val)
    except Exception:
        return val


# =============================================================================
# SCHEMAS PYDANTIC
# =============================================================================
class PlayerSummary(BaseModel):
    mapping_id: Optional[int] = None
    profile_id: Optional[int] = None
    name: str
    full_name: Optional[str] = None
    scout_role: str
    scout_category: str
    position_raw: Optional[str] = None
    current_team: Optional[str] = None
    current_league: Optional[str] = None
    birth_date: Optional[str] = None
    nationality: Optional[str] = None
    market_value_eur: Optional[int] = None
    market_value_raw: Optional[str] = None
    sofascore_id: Optional[int] = None
    fbref_id: Optional[str] = None
    transfermarkt_id: Optional[int] = None
    whoscored_id: Optional[int] = None


class PlayersResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[PlayerSummary]


# =============================================================================
# ENDPOINTS PRINCIPAIS
# =============================================================================
@app.get("/", tags=["Status"])
def root():
    conn = get_db_connection()
    try:
        total_mapped = conn.execute("SELECT COUNT(*) FROM player_mapping").fetchone()[0]
    except Exception:
        total_mapped = 0
    finally:
        conn.close()

    return {
        "status": "online",
        "service": "Scout Data Intelligence API",
        "version": "2.0",
        "total_players_tracked": total_mapped,
        "docs_url": "/docs",
    }


@app.get("/metadata", tags=["Metadata"])
def get_metadata():
    """Retorna filtros dinâmicos disponíveis no banco de dados para UIs e formulários."""
    conn = get_db_connection()
    try:
        seasons = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT season FROM sofascore_stats WHERE season IS NOT NULL ORDER BY season DESC"
            ).fetchall()
        ]
        competitions = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT competition FROM sofascore_stats WHERE competition IS NOT NULL ORDER BY competition ASC"
            ).fetchall()
        ]
        leagues = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT current_league FROM v_player_profiles WHERE current_league IS NOT NULL ORDER BY current_league ASC"
            ).fetchall()
        ]
        teams = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT current_team FROM v_player_profiles WHERE current_team IS NOT NULL ORDER BY current_team ASC"
            ).fetchall()
        ]
    except Exception:
        seasons, competitions, leagues, teams = [], [], [], []
    finally:
        conn.close()

    roles = [
        {"role": "ST", "category": "ATT", "label": "Centroavante / Homem de Área"},
        {"role": "WNG", "category": "ATT", "label": "Ponta / Atacante de Lado"},
        {"role": "CM_AM", "category": "MID", "label": "Meia Central / Meia Ofensivo"},
        {"role": "DM", "category": "MID", "label": "Volante / Meio-Campo Defensivo"},
        {"role": "FB", "category": "DEF", "label": "Lateral (Direito / Esquerdo)"},
        {"role": "CB", "category": "DEF", "label": "Zagueiro Central"},
        {"role": "GK", "category": "GK", "label": "Goleiro"},
    ]

    return {
        "seasons": seasons,
        "competitions": competitions,
        "leagues": leagues,
        "teams": teams,
        "roles": roles,
        "categories": ["ATT", "MID", "DEF", "GK"],
    }


@app.get("/players", response_model=PlayersResponse, tags=["Jogadores"])
def list_players(
    name: Optional[str] = Query(None, description="Busca textual por nome do jogador"),
    role: Optional[str] = Query(None, description="Filtrar por Função Tática (ST, WNG, CM_AM, DM, FB, CB, GK)"),
    category: Optional[str] = Query(None, description="Filtrar por Macro-Categoria (ATT, MID, DEF, GK)"),
    league: Optional[str] = Query(None, description="Filtrar por Liga Atual"),
    team: Optional[str] = Query(None, description="Filtrar por Clube Atual"),
    min_valuation: Optional[int] = Query(None, description="Valor de mercado mínimo em Euros"),
    max_valuation: Optional[int] = Query(None, description="Valor de mercado máximo em Euros"),
    page: int = Query(1, ge=1, description="Número da página"),
    page_size: int = Query(50, ge=1, le=200, description="Tamanho da página"),
):
    """Lista jogadores com paginação e múltiplos filtros analíticos."""
    conn = get_db_connection()
    where_clauses = ["1=1"]
    params: List[Any] = []

    if name:
        where_clauses.append("(name LIKE ? OR full_name LIKE ?)")
        params.extend([f"%{name}%", f"%{name}%"])
    if role:
        where_clauses.append("scout_role = ?")
        params.append(role.upper())
    if category:
        where_clauses.append("scout_category = ?")
        params.append(category.upper())
    if league:
        where_clauses.append("current_league LIKE ?")
        params.append(f"%{league}%")
    if team:
        where_clauses.append("current_team LIKE ?")
        params.append(f"%{team}%")
    if min_valuation is not None:
        where_clauses.append("market_value_eur >= ?")
        params.append(min_valuation)
    if max_valuation is not None:
        where_clauses.append("market_value_eur <= ?")
        params.append(max_valuation)

    where_sql = " AND ".join(where_clauses)

    try:
        # Total count
        count_sql = f"SELECT COUNT(*) FROM v_player_profiles WHERE {where_sql}"
        total = conn.execute(count_sql, params).fetchone()[0]

        # Items paginados
        offset = (page - 1) * page_size
        query_sql = f"""
        SELECT mapping_id, profile_id, name, full_name, scout_role, scout_category,
               position as position_raw, current_team, current_league, birth_date,
               nationality, market_value_eur, market_value_raw,
               sofascore_id, fbref_id, transfermarkt_id, whoscored_id
        FROM v_player_profiles
        WHERE {where_sql}
        ORDER BY market_value_eur DESC NULLS LAST, name ASC
        LIMIT ? OFFSET ?
        """
        rows = conn.execute(query_sql, params + [page_size, offset]).fetchall()
        items = [dict(r) for r in rows]
    finally:
        conn.close()

    return PlayersResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


@app.get("/players/{player_id}", tags=["Jogadores"])
def get_player_profile(player_id: str):
    """Retorna o perfil cadastral detalhado com características qualitativas das 4 fontes."""
    conn = get_db_connection()
    try:
        # Busca por mapping_id ou profile_id ou sofascore_id
        sql = """
        SELECT *
        FROM v_player_profiles
        WHERE mapping_id = ? OR profile_id = ? OR sofascore_id = ?
        LIMIT 1
        """
        row = conn.execute(sql, [player_id, player_id, player_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Jogador '{player_id}' não encontrado.")

        profile_dict = dict(row)

        # Decodifica características JSON do WhoScored
        profile_dict["player_strengths"] = safe_json_loads(profile_dict.get("player_strengths"))
        profile_dict["player_weaknesses"] = safe_json_loads(profile_dict.get("player_weaknesses"))
        profile_dict["player_style_of_play"] = safe_json_loads(profile_dict.get("player_style_of_play"))
        profile_dict["team_strengths"] = safe_json_loads(profile_dict.get("team_strengths"))
        profile_dict["team_weaknesses"] = safe_json_loads(profile_dict.get("team_weaknesses"))
        profile_dict["team_style"] = safe_json_loads(profile_dict.get("team_style"))

        # Busca características pontuais do SofaScore
        if profile_dict.get("sofascore_id"):
            chars_sql = """
            SELECT polarity, characteristic_name, rank
            FROM v_sofascore_characteristics_named
            WHERE player_id = ?
            ORDER BY rank ASC
            """
            c_rows = conn.execute(chars_sql, [profile_dict["sofascore_id"]]).fetchall()
            profile_dict["sofascore_characteristics"] = [dict(cr) for cr in c_rows]

        return profile_dict
    finally:
        conn.close()


@app.get("/players/{player_id}/dossier", tags=["Analytics & Radar"])
def get_player_dossier(
    player_id: str,
    season: Optional[str] = Query(None, description="Temporada analítica (ex: 2023, 2024, 23/24)"),
    min_minutes: int = Query(450, ge=0, description="Minutos mínimos jogados na amostra"),
):
    """
    Retorna o dossiê analítico do atleta com Radar Chart P90 e Percentis ranqueados dentro de seu papel tático.
    """
    dossier = engine_analytics.get_player_dossier(
        player_identifier=player_id,
        season=season,
        min_minutes=min_minutes,
    )
    if not dossier:
        raise HTTPException(
            status_code=404,
            detail=f"Dossiê analítico não disponível para '{player_id}' na temporada especificada (min_minutes={min_minutes})."
        )
    return dossier


@app.get("/players/{player_id}/similar", tags=["Analytics & Radar"])
def get_similar_players(
    player_id: str,
    season: Optional[str] = Query(None, description="Temporada para cálculo da similaridade"),
    top_n: int = Query(5, ge=1, le=20, description="Quantidade de atletas similares a retornar"),
    min_minutes: int = Query(450, ge=0, description="Minutos mínimos jogados"),
):
    """
    Identifica os atletas brasileiros mais similares na mesma função tática,
    utilizando cálculo de proximidade no espaço vetorial de percentis do radar.
    """
    similars = engine_analytics.find_similar_players(
        target_name_or_id=player_id,
        season=season,
        top_n=top_n,
        min_minutes=min_minutes,
    )
    return {
        "target_player": player_id,
        "count": len(similars),
        "similar_players": similars,
    }


@app.get("/analytics/rankings", tags=["Analytics & Radar"])
def get_metric_rankings(
    metric: str = Query("goals", description="Métrica para ranking (goals, xg, assists, xa, key_passes, tackles, etc.)"),
    role: Optional[str] = Query(None, description="Filtrar por função tática (ST, WNG, CM_AM, DM, FB, CB, GK)"),
    season: Optional[str] = Query(None, description="Temporada analítica"),
    min_minutes: int = Query(450, ge=0, description="Minutos mínimos jogados"),
    limit: int = Query(20, ge=1, le=100, description="Quantidade de atletas no ranking"),
):
    """
    Retorna o ranking de líderes para uma métrica específica, ordenado tanto pelo valor P90 quanto bruto.
    """
    df = engine_analytics.get_gold_dataset(season=season, min_minutes=min_minutes, scout_role=role)
    if df.empty:
        return {"metric": metric, "total": 0, "rankings": []}

    sort_col = f"{metric}_p90" if f"{metric}_p90" in df.columns else metric
    if sort_col not in df.columns:
        raise HTTPException(status_code=400, detail=f"Métrica '{metric}' não encontrada.")

    ranked_df = df.sort_values(by=sort_col, ascending=False).head(limit)

    results = []
    for rank_pos, (_, r) in enumerate(ranked_df.iterrows(), 1):
        raw_val = r.get(metric)
        p90_val = r.get(f"{metric}_p90", raw_val)
        pct_val = r.get(f"{metric}_pct")

        results.append({
            "rank": rank_pos,
            "mapping_id": int(r['mapping_id']),
            "name": str(r['player_name']),
            "scout_role": str(r['scout_role']),
            "current_team": str(r['current_team']),
            "current_league": str(r['current_league']),
            "minutes_played": int(r['minutes_played']),
            "raw_value": round(float(raw_val), 2) if raw_val is not None and not pd.isna(raw_val) else None,
            "p90_value": round(float(p90_val), 2) if p90_val is not None and not pd.isna(p90_val) else None,
            "percentile": round(float(pct_val), 1) if pct_val is not None and not pd.isna(pct_val) else None,
            "market_value_raw": str(r['market_value_raw']) if pd.notna(r['market_value_raw']) else "N/A",
        })

    return {
        "metric": metric,
        "scout_role": role,
        "season": season,
        "total": len(results),
        "rankings": results,
    }


@app.get("/analytics/compare", tags=["Analytics & Radar"])
def compare_players(
    player_ids: List[int] = Query(..., description="Lista de mapping_ids para comparação lado a lado"),
    season: Optional[str] = Query(None, description="Temporada analítica"),
    min_minutes: int = Query(0, description="Minutos mínimos jogados"),
):
    """
    Compara 2 ou mais jogadores lado a lado, devolvendo seus dossiês e métricas de radar sobrepostas.
    """
    if len(player_ids) < 2:
        raise HTTPException(status_code=400, detail="Forneça ao menos 2 IDs de jogadores para comparação.")
    if len(player_ids) > 6:
        raise HTTPException(status_code=400, detail="Comparação limitada a no máximo 6 jogadores simultâneos.")

    comparisons = []
    for pid in player_ids:
        dossier = engine_analytics.get_player_dossier(str(pid), season=season, min_minutes=min_minutes)
        if dossier:
            comparisons.append(dossier)

    return {
        "count": len(comparisons),
        "players": comparisons,
    }


# =============================================================================
# MONTAGEM DO FRONTEND (DASHBOARD ESTÁTICO)
# =============================================================================
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/dashboard", include_in_schema=False)
    @app.get("/app", include_in_schema=False)
    def serve_dashboard():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
