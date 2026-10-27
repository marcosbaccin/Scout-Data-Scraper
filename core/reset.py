"""
Gerenciador de Higienização e Reset de Dados (Data Sanitizer).

Permite inspecionar o volume de dados e realizar resets granulares ou totais:
- Banco de dados SQLite (scout.db): recriação do schema e views limpas.
- Coletas brutas e checkpoints de cada uma das 4 fontes (SofaScore, FBref, Transfermarkt, WhoScored).
- Arquivos de lock e caches residuais de webdrivers.
"""
import glob
import os
import shutil
import sqlite3
from typing import Dict, Any

from core.database import init_db
from core.settings import (
    BASE_DIR,
    DB_PATH,
    FBREF_DATA_DIR,
    SOFASCORE_DATA_DIR,
    TRANSFERMARKT_DATA_DIR,
    WHOSCORED_DATA_DIR,
)


def _get_dir_size_and_count(dir_path: str):
    """Calcula tamanho total em bytes e contagem de arquivos de um diretório recursivamente."""
    if not os.path.exists(dir_path):
        return 0, 0
    total_size = 0
    total_files = 0
    for root, _, files in os.walk(dir_path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total_size += os.path.getsize(fp)
                total_files += 1
            except OSError:
                pass
    return total_size, total_files


def _format_size(size_bytes: int) -> str:
    """Formata bytes para exibição humana amigável (B, KB, MB, GB)."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def get_pipeline_status() -> Dict[str, Any]:
    """Inspeciona o estado atual dos dados no banco e no sistema de arquivos."""
    status = {
        "database": {"exists": os.path.exists(DB_PATH), "size": 0, "size_formatted": "0 B", "tables": {}},
        "scrapers": {},
    }

    # 1. Status do Banco SQLite
    if os.path.exists(DB_PATH):
        db_size = os.path.getsize(DB_PATH)
        status["database"]["size"] = db_size
        status["database"]["size_formatted"] = _format_size(db_size)
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            tables = [
                "sofascore_players", "sofascore_stats", "sofascore_characteristics",
                "fbref_players", "fbref_outfield_stats", "fbref_keeper_stats",
                "transfermarkt_players",
                "whoscored_teams", "whoscored_players", "whoscored_player_season_stats",
                "player_mapping",
            ]
            for t in tables:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {t}")
                    status["database"]["tables"][t] = cur.fetchone()[0]
                except sqlite3.OperationalError:
                    status["database"]["tables"][t] = "N/A"
            conn.close()
        except Exception as e:
            status["database"]["error"] = str(e)

    # 2. Status dos Dumps das 4 Fontes
    sources = {
        "sofascore": {
            "dirs": [SOFASCORE_DATA_DIR],
            "files": [os.path.join(SOFASCORE_DATA_DIR, f) for f in [
                "sofascore_teams.json", "sofascore_players.json", "sofascore_final_stats.json"
            ]],
        },
        "fbref": {
            "dirs": [FBREF_DATA_DIR],
            "files": [os.path.join(BASE_DIR, "scrapers", "fbref", "teams_to_scrape.csv")],
        },
        "transfermarkt": {
            "dirs": [TRANSFERMARKT_DATA_DIR],
            "files": [
                os.path.join(BASE_DIR, "scrapers", "transfermarkt", "teams_to_scrape.csv"),
                os.path.join(BASE_DIR, "scrapers", "transfermarkt", "brazilian_players.csv"),
            ],
        },
        "whoscored": {
            "dirs": [WHOSCORED_DATA_DIR],
            "files": [
                os.path.join(BASE_DIR, "scrapers", "whoscored", "teams_to_scrape.csv"),
                os.path.join(BASE_DIR, "scrapers", "whoscored", "teams_with_characteristics.csv"),
                os.path.join(BASE_DIR, "scrapers", "whoscored", "brazilian_players.csv"),
                os.path.join(BASE_DIR, "scrapers", "whoscored", "players_detailed.csv"),
                os.path.join(BASE_DIR, "scrapers", "whoscored", "players_season_stats.csv"),
            ],
        },
    }

    for name, paths in sources.items():
        total_sz = 0
        total_fc = 0
        existing_files = []
        for d in paths["dirs"]:
            sz, fc = _get_dir_size_and_count(d)
            total_sz += sz
            total_fc += fc
        for f in paths["files"]:
            if os.path.exists(f):
                total_sz += os.path.getsize(f)
                total_fc += 1
                existing_files.append(os.path.basename(f))
        status["scrapers"][name] = {
            "total_size": total_sz,
            "total_size_formatted": _format_size(total_sz),
            "file_count": total_fc,
            "key_files": existing_files,
        }

    return status


def reset_database() -> bool:
    """Remove e reinicializa scout.db com todas as tabelas e views estruturadas vazias."""
    print("[*] Reinicializando banco de dados scout.db...")
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
            print(f"    [-] Arquivo removido: {DB_PATH}")
        except Exception as e:
            print(f"    [!] Erro ao remover {DB_PATH}: {e}")
            return False

    backup_db = os.path.join(BASE_DIR, "scout_backup_pre_refactor.db")
    if os.path.exists(backup_db):
        try:
            os.remove(backup_db)
            print(f"    [-] Arquivo de backup antigo removido: {backup_db}")
        except Exception:
            pass

    init_db()
    print("    [+] Esquema DDL e Views analíticas recriados com sucesso no scout.db!")
    return True


def reset_sofascore_data() -> int:
    """Remove arquivos brutos e intermediários do SofaScore."""
    print("[*] Limpando dados do SofaScore...")
    removed = 0
    if os.path.exists(SOFASCORE_DATA_DIR):
        for f in os.listdir(SOFASCORE_DATA_DIR):
            fp = os.path.join(SOFASCORE_DATA_DIR, f)
            if os.path.isfile(fp):
                os.remove(fp)
                removed += 1
    print(f"    [-] {removed} arquivos limpos em data/sofascore/.")
    return removed


def reset_fbref_data() -> int:
    """Remove pastas de jogadores e CSV de times do FBref."""
    print("[*] Limpando dados brutos do FBref...")
    removed = 0
    if os.path.exists(FBREF_DATA_DIR):
        for item in os.listdir(FBREF_DATA_DIR):
            item_path = os.path.join(FBREF_DATA_DIR, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path, ignore_errors=True)
                removed += 1
            elif os.path.isfile(item_path):
                os.remove(item_path)
                removed += 1

    teams_csv = os.path.join(BASE_DIR, "scrapers", "fbref", "teams_to_scrape.csv")
    if os.path.exists(teams_csv):
        os.remove(teams_csv)
        removed += 1
    print(f"    [-] {removed} itens/pastas removidos no FBref.")
    return removed


def reset_transfermarkt_data() -> int:
    """Remove dumps JSON e CSVs do Transfermarkt."""
    print("[*] Limpando dados do Transfermarkt...")
    removed = 0
    tm_dir = os.path.join(BASE_DIR, "scrapers", "transfermarkt")
    for f in ["teams_to_scrape.csv", "brazilian_players.csv"]:
        fp = os.path.join(tm_dir, f)
        if os.path.exists(fp):
            os.remove(fp)
            removed += 1

    if os.path.exists(TRANSFERMARKT_DATA_DIR):
        for f in os.listdir(TRANSFERMARKT_DATA_DIR):
            fp = os.path.join(TRANSFERMARKT_DATA_DIR, f)
            if os.path.isfile(fp):
                os.remove(fp)
                removed += 1
    print(f"    [-] {removed} arquivos limpos no Transfermarkt.")
    return removed


def reset_whoscored_data() -> int:
    """Remove checkpoints, JSONs e CSVs do WhoScored."""
    print("[*] Limpando dados do WhoScored...")
    removed = 0
    ws_dir = os.path.join(BASE_DIR, "scrapers", "whoscored")
    csvs = [
        "teams_to_scrape.csv", "teams_with_characteristics.csv",
        "brazilian_players.csv", "players_detailed.csv", "players_season_stats.csv"
    ]
    for f in csvs:
        fp = os.path.join(ws_dir, f)
        if os.path.exists(fp):
            os.remove(fp)
            removed += 1

    if os.path.exists(WHOSCORED_DATA_DIR):
        for f in os.listdir(WHOSCORED_DATA_DIR):
            fp = os.path.join(WHOSCORED_DATA_DIR, f)
            if os.path.isfile(fp):
                os.remove(fp)
                removed += 1
    print(f"    [-] {removed} arquivos limpos no WhoScored.")
    return removed


def clean_locks_and_temps():
    """Remove travas do SeleniumBase e caches temporários."""
    download_dir = os.path.join(BASE_DIR, "downloaded_files")
    if os.path.exists(download_dir):
        for f in os.listdir(download_dir):
            if f.endswith(".lock"):
                try:
                    os.remove(os.path.join(download_dir, f))
                except Exception:
                    pass


def reset_all_collected_data(reset_db: bool = True) -> None:
    """Executa a faxina completa de todas as 4 fontes e reinicia o banco de dados."""
    print("\n" + "=" * 80)
    print(" INICIANDO HIGIENIZAÇÃO TOTAL DO AMBIENTE (RESET DO ZERO)")
    print("=" * 80)
    reset_sofascore_data()
    reset_fbref_data()
    reset_transfermarkt_data()
    reset_whoscored_data()
    clean_locks_and_temps()

    if reset_db:
        reset_database()

    print("=" * 80)
    print(" FAXINA CONCLUÍDA: Todos os dados residuais foram removidos!")
    print(" O ambiente está pronto para uma nova coleta unificada 'do zero'.")
    print("=" * 80 + "\n")
