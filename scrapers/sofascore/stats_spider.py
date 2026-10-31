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

FETCH_PAIR_JS = """
const pid = arguments[0];
const done = arguments[1];
Promise.all([
    fetch(`/api/v1/player/${pid}/statistics`, { credentials: 'include' })
        .then(async r => ({ status: r.status, data: await r.json().catch(() => ({})) }))
        .catch(e => ({ status: 0, error: String(e), data: {} })),
    fetch(`/api/v1/player/${pid}/characteristics`, { credentials: 'include' })
        .then(async r => ({ status: r.status, data: await r.json().catch(() => ({})) }))
        .catch(e => ({ status: 0, error: String(e), data: {} }))
]).then(res => done(res));
"""


def fetch_json_fallback(driver, url, wait):
    """Fallback clássico: navega direto na URL da API e lê a tag <pre>."""
    driver.get(url)
    time.sleep(wait)
    pre_tag = BeautifulSoup(driver.page_source, 'html.parser').find('pre')
    return json.loads(pre_tag.text) if pre_tag else {}


WARMUP_URL = "https://www.sofascore.com/api/v1/unique-tournament/325/season/87678/standings/total"


def init_warm_driver():
    """Inicializa Chrome em endpoint JSON leve do próprio domínio SofaScore (sem anúncios/iframes pesados)."""
    for attempt in range(1, 4):
        drv = None
        try:
            drv = new_chrome()
            drv.set_page_load_timeout(25)
            drv.set_script_timeout(20)
            drv.get(WARMUP_URL)
            time.sleep(2.5)
            return drv
        except Exception as e:
            print(f"    [!] Tentativa {attempt} de inicializar Chrome falhou ({e}). Retentando...")
            if drv is not None:
                try:
                    drv.quit()
                except Exception:
                    pass
            time.sleep(2)
    raise RuntimeError("Não foi possível inicializar sessão Chrome no SofaScore.")


def slim_statistics(stats_data):
    """Mantém só o necessário de cada temporada: ids/nomes e as métricas BRUTAS (sem derivadas)."""
    seasons = []
    for s in (stats_data or {}).get('seasons', []):
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
        final_stats = []
        if os.path.exists(STATS_FILE):
            try:
                with open(STATS_FILE, "r", encoding="utf-8") as f:
                    final_stats = json.load(f)
                print(f"[*] Retomando checkpoint de estatísticas com {len(final_stats)} jogadores já coletados.")
            except Exception:
                final_stats = []
        done_ids = {p.get("id") for p in final_stats if p.get("id")}
        players = []
        seen_roster_ids = set(done_ids)
        for team_id, roster in teams_data.items():
            for p in roster:
                pid = p.get("id")
                if pid and pid not in seen_roster_ids:
                    seen_roster_ids.add(pid)
                    players.append(p)

    total_players = len(players)
    if total_players == 0 and not characteristics_only:
        print(f"[+] Todos os jogadores já foram coletados ({len(final_stats)} registros em {STATS_FILE}).")
        return

    print(f"[*] Iniciando extração de {total_players} jogadores pendentes (characteristics_only={characteristics_only})...")

    driver = init_warm_driver()

    for index, player in enumerate(players):
        p_id = player["id"]
        print(f"[{index+1}/{total_players}] Processando: {player['name']} (ID: {p_id})", flush=True)

        try:
            if characteristics_only:
                player_data = player
                player_data["statistics"] = slim_statistics(player_data.get("statistics") or {})
                player_data["characteristics"] = fetch_json_fallback(
                    driver, f"https://www.sofascore.com/api/v1/player/{p_id}/characteristics", 1.5
                )
            else:
                player_data = player.copy()
                res = driver.execute_async_script(FETCH_PAIR_JS, p_id)
                st_res, ch_res = res[0], res[1]

                if st_res.get("status") in (200, 404) and ch_res.get("status") in (200, 404):
                    stats_data = st_res.get("data") or {}
                    chars_data = ch_res.get("data") or {}
                else:
                    # Fallback via navegação direta caso fetch in-page encontre bloqueio
                    if st_res.get("status") == 429 or ch_res.get("status") == 429:
                        print("    [!] Rate limit 429 detectado. Aguardando 8s...")
                        time.sleep(8)
                    stats_data = fetch_json_fallback(driver, f"https://www.sofascore.com/api/v1/player/{p_id}/statistics", 2)
                    chars_data = fetch_json_fallback(driver, f"https://www.sofascore.com/api/v1/player/{p_id}/characteristics", 1.5)
                    driver.get(WARMUP_URL)
                    time.sleep(1.5)

                player_data["statistics"] = slim_statistics(stats_data)
                player_data["characteristics"] = chars_data
                final_stats.append(player_data)

            time.sleep(0.45)

        except Exception as e:
            print(f"    [!] Falha ao processar {player['name']}: {e}. Reiniciando sessão Chrome...")
            try:
                driver.quit()
            except Exception:
                pass
            try:
                driver = init_warm_driver()
                player_data = player.copy()
                stats_data = fetch_json_fallback(driver, f"https://www.sofascore.com/api/v1/player/{p_id}/statistics", 2)
                chars_data = fetch_json_fallback(driver, f"https://www.sofascore.com/api/v1/player/{p_id}/characteristics", 1.5)
                player_data["statistics"] = slim_statistics(stats_data)
                player_data["characteristics"] = chars_data
                if not characteristics_only:
                    final_stats.append(player_data)
                driver.get("https://www.sofascore.com/")
                time.sleep(2)
            except Exception as e2:
                print(f"    [!] Falha definitiva em {player['name']}: {e2}")

        if (index + 1) % 25 == 0:
            save(final_stats)  # checkpoint contínuo a cada 25 atletas

    try:
        driver.quit()
    except Exception:
        pass
    save(final_stats)
    print(f"\n[+] Script Finalizado! {len(final_stats)} jogadores salvos em: {STATS_FILE}")


if __name__ == "__main__":
    scrape_player_stats(characteristics_only="--characteristics-only" in sys.argv)
