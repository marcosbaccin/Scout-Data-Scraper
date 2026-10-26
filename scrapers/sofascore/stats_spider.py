import json
import os
import sys
import time
from bs4 import BeautifulSoup

# Permite importar o pacote core ao rodar `python scrapers/sofascore/stats_spider.py` da raiz do projeto
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.browser import new_chrome
from core.sofascore_metrics import strip_derived

DATA_DIR = "data/sofascore"
PLAYERS_FILE = os.path.join(DATA_DIR, "sofascore_players.json")
STATS_FILE = os.path.join(DATA_DIR, "sofascore_final_stats.json")


def fetch_json(driver, url, wait):
    """O navegador injeta o JSON puro da API dentro de uma tag <pre>."""
    driver.get(url)
    time.sleep(wait)
    pre_tag = BeautifulSoup(driver.page_source, 'html.parser').find('pre')
    return json.loads(pre_tag.text) if pre_tag else {}


def slim_statistics(stats_data):
    """Mantém só o necessário de cada temporada: ids/nomes e as métricas BRUTAS (sem derivadas)."""
    seasons = []
    for s in stats_data.get('seasons', []):
        seasons.append({
            "year": s.get("year"),
            "startYear": s.get("startYear"),
            "endYear": s.get("endYear"),
            "team": {k: (s.get("team") or {}).get(k) for k in ("id", "name")},
            "uniqueTournament": {k: (s.get("uniqueTournament") or {}).get(k) for k in ("id", "name")},
            "season": {k: (s.get("season") or {}).get(k) for k in ("id", "name", "year")},
            "statistics": strip_derived(s.get("statistics") or {}),
        })
    return {"seasons": seasons} if seasons else {}


def save(final_stats):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(final_stats, f, ensure_ascii=False, indent=4)


def scrape_player_stats(characteristics_only=False):
    """
    characteristics_only=True: reaproveita as estatísticas já coletadas em STATS_FILE e
    refaz apenas a chamada de /characteristics (python stats_spider.py --characteristics-only).
    """
    if not os.path.exists(PLAYERS_FILE):
        print(f"[!] Arquivo {PLAYERS_FILE} não encontrado.")
        return

    if characteristics_only:
        if not os.path.exists(STATS_FILE):
            print(f"[!] {STATS_FILE} não encontrado: rode sem --characteristics-only primeiro.")
            return
        with open(STATS_FILE, "r", encoding="utf-8") as f:
            final_stats = json.load(f)
        players = final_stats
    else:
        with open(PLAYERS_FILE, "r", encoding="utf-8") as f:
            teams_data = json.load(f)
        players, final_stats = [], []
        for team_id, roster in teams_data.items():
            players.extend(roster)

    total_players = len(players)
    print(f"[*] Iniciando extração de {total_players} jogadores (characteristics_only={characteristics_only})...")

    driver = new_chrome()

    for index, player in enumerate(players):
        p_id = player["id"]
        print(f"\n[{index+1}/{total_players}] Processando: {player['name']} (ID: {p_id})")

        try:
            if characteristics_only:
                player_data = player
                player_data["statistics"] = slim_statistics(player_data.get("statistics") or {})
            else:
                player_data = player.copy()
                stats_data = fetch_json(driver, f"https://www.sofascore.com/api/v1/player/{p_id}/statistics", 2)
                player_data["statistics"] = slim_statistics(stats_data)

            # A API devolve {"positive": [{"type", "rank"}], "negative": [...], ...} na raiz
            # (não existe a chave "characteristics"). Guardamos a resposta inteira.
            player_data["characteristics"] = fetch_json(
                driver, f"https://www.sofascore.com/api/v1/player/{p_id}/characteristics", 1.5)

            if not characteristics_only:
                final_stats.append(player_data)

        except Exception as e:
            print(f"    [!] Falha ao processar {player['name']}: {e}")

        if (index + 1) % 100 == 0:
            save(final_stats)  # checkpoint

    driver.quit()
    save(final_stats)
    print(f"\n[+] Script Finalizado! Resultados salvos em: {STATS_FILE}")


if __name__ == "__main__":
    scrape_player_stats(characteristics_only="--characteristics-only" in sys.argv)