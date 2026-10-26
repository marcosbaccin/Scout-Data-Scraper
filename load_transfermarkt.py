"""
Carga do Transfermarkt no banco único (scout.db).

Lê scrapers/transfermarkt/data/brazilian_players.json e persiste na tabela:
- transfermarkt_players (dados cadastrais + valor de mercado atual em euros)

O pipeline é idempotente (upsert por transfermarkt_id).
"""
import datetime as dt
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from core.database import get_session, init_db
from core.models import TransfermarktPlayer

JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scrapers", "transfermarkt", "data", "brazilian_players.json")


def load_transfermarkt_db():
    if not os.path.exists(JSON_PATH):
        print(f"[!] Erro: Arquivo {JSON_PATH} não encontrado.")
        return

    init_db()  # Garante tabelas e views atualizadas
    session = get_session()

    print("[*] Iniciando carga de jogadores do Transfermarkt no scout.db...")

    with open(JSON_PATH, "r", encoding="utf-8") as f:
        players_data = json.load(f)

    loaded = updated = 0

    for p in players_data:
        p_id = p.get("transfermarkt_id")
        if not p_id:
            continue

        raw_birth = p.get("birth_date")
        birth = None
        if raw_birth:
            try:
                birth = dt.date.fromisoformat(raw_birth)
            except Exception:
                birth = None

        fields = dict(
            name=p.get("name"),
            url=p.get("url"),
            shirt_number=p.get("shirt_number"),
            position=p.get("position"),
            birth_date=birth,
            age=p.get("age"),
            nationality=p.get("nationality", "Brasil"),
            secondary_nationality=p.get("secondary_nationality"),
            current_club=p.get("current_club"),
            league_code=p.get("league_code"),
            league_name=p.get("league_name"),
            market_value_raw=p.get("market_value_raw"),
            market_value_eur=p.get("market_value_eur"),
        )

        player = session.get(TransfermarktPlayer, p_id)
        if player is None:
            player = TransfermarktPlayer(id=p_id, **fields)
            session.add(player)
            loaded += 1
        else:
            for k, v in fields.items():
                setattr(player, k, v)
            updated += 1

        if (loaded + updated) % 100 == 0:
            session.commit()

    session.commit()
    session.close()

    print(f"\n[+] Carga do Transfermarkt concluída com sucesso!")
    print(f"    -> {loaded} novos jogadores inseridos.")
    print(f"    -> {updated} jogadores atualizados.")
    print(f"    -> Total na base: {loaded + updated} jogadores brasileiros.")


if __name__ == "__main__":
    load_transfermarkt_db()
