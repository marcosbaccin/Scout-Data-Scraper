"""
Carga do Sofascore no banco único (scout.db).

Lê data/sofascore/sofascore_final_stats.json (gerado por scrapers/sofascore/stats_spider.py) e persiste:
  - sofascore_players          (dimensão)
  - sofascore_characteristics  (pontos fortes/fracos: código do tipo + rank)
  - sofascore_player_positions (posições devolvidas por /characteristics)
  - sofascore_stats            (todas as métricas brutas catalogadas em core/sofascore_metrics.py)
O pipeline é idempotente (upsert por jogador); métricas derivadas ficam em v_sofascore_stats_derived.
"""
import collections
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from core.database import get_session
from core.models import SofascoreCharacteristic, SofascorePlayer, SofascorePlayerPosition, SofascoreStat
from core.settings import SOFASCORE_DATA_DIR
from core.sofascore_metrics import DERIVED_METRICS, RAW_METRICS, column_name

JSON_PATH = os.path.join(SOFASCORE_DATA_DIR, "sofascore_final_stats.json")


def _coerce(value, kind):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(round(value)) if kind == 'int' else float(value)


def _characteristics(chars):
    """Aceita a resposta bruta da API ({'positive': [{'type', 'rank'}], 'negative': [...]})."""
    rows = {}
    for polarity in ('positive', 'negative'):
        for item in chars.get(polarity) or []:
            code = item.get('type') if isinstance(item, dict) else None
            if code is not None:
                rows[(polarity, code)] = item.get('rank')
    return rows


def build_sofascore_db():
    if not os.path.exists(JSON_PATH):
        print(f"[!] Erro: Arquivo {JSON_PATH} não encontrado.")
        return

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        players_data = json.load(f)

    session = get_session()
    print("[*] Iniciando carga completa do Sofascore (linha + goleiros + métricas físicas)...")

    seen_players, seen_stats = set(), set()
    unknown_metrics = collections.Counter()
    n_players = n_stats = n_chars = n_positions = n_skipped = 0

    for p in players_data:
        p_id = p.get('id')
        if not p_id or p_id in seen_players:  # jogador listado em mais de um elenco (transferência)
            continue
        seen_players.add(p_id)

        chars = p.get('characteristics') or {}
        fields = dict(
            name=p.get('name'), position=p.get('position'),
            current_team=p.get('team'), current_league=p.get('league'),
            nationality=p.get('nationality'),
            footed=p.get('footed') or p.get('preferredFoot'),
            height=p.get('height'),
            weight=p.get('weight'),
            characteristics_raw=json.dumps(chars, ensure_ascii=False) if chars else None,
        )
        player = session.get(SofascorePlayer, p_id)
        if player is None:
            player = SofascorePlayer(id=p_id, **fields)
            session.add(player)
        else:
            for key, val in fields.items():
                setattr(player, key, val)
            player.stats.clear()
            player.characteristics.clear()
            player.positions.clear()
        session.flush()
        n_players += 1

        for ordinal, pos in enumerate(dict.fromkeys(chars.get('positions') or [])):
            session.add(SofascorePlayerPosition(player_id=p_id, position=pos, ordinal=ordinal))
            n_positions += 1

        for (polarity, code), rank in _characteristics(chars).items():
            session.add(SofascoreCharacteristic(player_id=p_id, polarity=polarity, type_code=code, rank=rank))
            n_chars += 1

        for s in p.get('statistics', {}).get('seasons', []):
            tournament = s.get('uniqueTournament') or {}
            season = s.get('season') or {}
            team = s.get('team') or {}
            key = (p_id, tournament.get('id'), season.get('id'), team.get('id'))
            if None in key or key in seen_stats:
                n_skipped += 1
                continue
            seen_stats.add(key)

            metrics = s.get('statistics') or {}
            row = dict(
                player_id=p_id, tournament_id=key[1], season_id=key[2], team_id=key[3],
                season=s.get('year'), competition=tournament.get('name'), squad=team.get('name'),
            )
            for metric, value in metrics.items():
                if metric in RAW_METRICS:
                    row[column_name(metric)] = _coerce(value, RAW_METRICS[metric])
                elif metric not in DERIVED_METRICS:
                    unknown_metrics[metric] += 1
            session.add(SofascoreStat(**row))
            n_stats += 1

    session.commit()
    session.close()

    print("[+] Integração Sofascore concluída!")
    print(f"    -> {n_players} jogadores")
    print(f"    -> {n_stats} recortes jogador/competição/temporada ({len(RAW_METRICS)} métricas brutas)")
    print(f"    -> {n_chars} características (fortes/fracos)")
    print(f"    -> {n_positions} posições")
    if n_skipped:
        print(f"    -> {n_skipped} recortes ignorados (sem IDs ou duplicados)")
    if unknown_metrics:
        print(f"    [!] Métricas novas na API, ainda não catalogadas em core/sofascore_metrics.py: {dict(unknown_metrics)}")


if __name__ == "__main__":
    build_sofascore_db()