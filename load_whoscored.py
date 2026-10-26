"""
Carga dos dados do WhoScored no banco único (scout.db).

Lê:
- scrapers/whoscored/data/teams_with_characteristics.json -> whoscored_teams
- scrapers/whoscored/data/brazilian_players.json -> whoscored_players

Pipeline idempotente (upsert por ID).
"""
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from core.database import get_session, init_db
from core.models import WhoscoredPlayer, WhoscoredTeam

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEAMS_JSON = os.path.join(BASE_DIR, "scrapers", "whoscored", "data", "teams_with_characteristics.json")
PLAYERS_DETAILED_JSON = os.path.join(BASE_DIR, "scrapers", "whoscored", "data", "players_detailed.json")
PLAYERS_BASIC_JSON = os.path.join(BASE_DIR, "scrapers", "whoscored", "data", "brazilian_players.json")
SEASON_STATS_JSON = os.path.join(BASE_DIR, "scrapers", "whoscored", "data", "players_season_stats.json")

from core.models import WhoscoredPlayer, WhoscoredPlayerSeasonStat, WhoscoredTeam
import datetime as dt


def load_whoscored_db():
    init_db()
    session = get_session()

    print("[*] Iniciando carga de dados do WhoScored no scout.db...")

    # 1. Carga de Clubes
    if os.path.exists(TEAMS_JSON):
        with open(TEAMS_JSON, "r", encoding="utf-8") as f:
            teams_data = json.load(f)

        t_loaded = t_updated = 0
        for t in teams_data:
            t_id = t.get("whoscored_team_id")
            if not t_id:
                continue

            fields = dict(
                team_name=t.get("team_name"),
                team_url=t.get("team_url"),
                league_code=t.get("league_code"),
                league_name=t.get("league_name"),
                strengths=json.dumps(t.get("strengths", []), ensure_ascii=False),
                weaknesses=json.dumps(t.get("weaknesses", []), ensure_ascii=False),
                style=json.dumps(t.get("style", []), ensure_ascii=False),
            )

            existing = session.query(WhoscoredTeam).filter_by(id=t_id).first()
            if existing:
                for k, v in fields.items():
                    setattr(existing, k, v)
                t_updated += 1
            else:
                session.add(WhoscoredTeam(id=t_id, **fields))
                t_loaded += 1

        session.commit()
        print(f"    [+] Clubes WhoScored: {t_loaded} inseridos, {t_updated} atualizados.")
    else:
        print(f"    [!] Arquivo de clubes {TEAMS_JSON} não encontrado.")

    # 2. Carga de Jogadores Brasileiros (Prioriza detalhados se existir)
    players_file = PLAYERS_DETAILED_JSON if os.path.exists(PLAYERS_DETAILED_JSON) else PLAYERS_BASIC_JSON
    if os.path.exists(players_file):
        with open(players_file, "r", encoding="utf-8") as f:
            players_data = json.load(f)

        p_loaded = p_updated = 0
        for p in players_data:
            p_id = p.get("whoscored_player_id")
            if not p_id:
                continue

            birth = None
            raw_b = p.get("birth_date")
            if raw_b:
                try:
                    birth = dt.date.fromisoformat(raw_b)
                except Exception:
                    birth = None

            fields = dict(
                name=p.get("name"),
                full_name=p.get("full_name"),
                player_url=p.get("player_url"),
                current_team=p.get("current_team"),
                shirt_number=p.get("shirt_number"),
                age=p.get("age"),
                birth_date=birth,
                height=p.get("height"),
                nationality=p.get("nationality", "Brasil"),
                position=p.get("position"),
                strengths=json.dumps(p.get("strengths", []), ensure_ascii=False) if p.get("strengths") else None,
                weaknesses=json.dumps(p.get("weaknesses", []), ensure_ascii=False) if p.get("weaknesses") else None,
                style_of_play=json.dumps(p.get("style_of_play", []), ensure_ascii=False) if p.get("style_of_play") else None,
                whoscored_team_id=p.get("whoscored_team_id"),
                team_name=p.get("team_name"),
                league_code=p.get("league_code"),
                league_name=p.get("league_name"),
            )

            existing = session.query(WhoscoredPlayer).filter_by(id=p_id).first()
            if existing:
                for k, v in fields.items():
                    setattr(existing, k, v)
                p_updated += 1
            else:
                session.add(WhoscoredPlayer(id=p_id, **fields))
                p_loaded += 1

        session.commit()
        print(f"    [+] Jogadores Brasileiros WhoScored: {p_loaded} inseridos, {p_updated} atualizados.")

    # 3. Carga de Estatísticas de Temporada (Histórico - Opção 2)
    if os.path.exists(SEASON_STATS_JSON):
        with open(SEASON_STATS_JSON, "r", encoding="utf-8") as f:
            stats_data = json.load(f)

        s_loaded = s_updated = 0
        for s in stats_data:
            pid = s.get("player_id")
            season = s.get("season")
            team = s.get("team")
            comp = s.get("competition")
            if not pid or not season or not team or not comp:
                continue

            fields = dict(
                matches=s.get("matches"),
                minutes=s.get("minutes"),
                goals=s.get("goals"),
                assists=s.get("assists"),
                motm=s.get("motm"),
                rating=s.get("rating"),
                through_balls_per_game=s.get("through_balls_per_game"),
                dispossessed_per_game=s.get("dispossessed_per_game"),
                unsuccessful_touches_per_game=s.get("unsuccessful_touches_per_game"),
            )

            existing = session.query(WhoscoredPlayerSeasonStat).filter_by(
                player_id=pid, season=season, team=team, competition=comp
            ).first()

            if existing:
                for k, v in fields.items():
                    setattr(existing, k, v)
                s_updated += 1
            else:
                session.add(WhoscoredPlayerSeasonStat(
                    player_id=pid, season=season, team=team, competition=comp, **fields
                ))
                s_loaded += 1

        session.commit()
        print(f"    [+] Estatísticas de Temporada WhoScored: {s_loaded} inseridas, {s_updated} atualizadas.")

    session.close()
    print("[+] Carga do WhoScored concluída no scout.db!")


if __name__ == "__main__":
    load_whoscored_db()
