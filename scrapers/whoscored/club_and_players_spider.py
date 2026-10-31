"""
Coletor de Características dos Clubes e Jogadores Brasileiros no WhoScored.

Etapa 2 da coleta do WhoScored:
1. Para cada clube das 11 ligas:
   - Coleta características do clube:
     * Pontos fortes (strengths): nome da característica e nível (Muito forte, Forte)
     * Pontos fracos (weaknesses): nome da característica e nível (Muito fraco, Fraco)
     * Estilo de jogo (style): tópicos descritivos de estilo tático
   - Atualiza dados do clube mantendo: whoscored_team_id, league_code, league_name, team_name, team_url,
     e removendo colunas de tabela de classificação (matches_played, wins, draws, losses, goals_for, goals_against, goal_diff, points).
2. Para os jogadores:
   - Filtra APENAS jogadores com nacionalidade brasileira (classe 'flg-br').
   - Coleta apenas dados básicos de identificação e URL individual:
     * whoscored_player_id
     * name
     * player_url
     * age
     * position
     * whoscored_team_id
     * team_name
     * league_code
     * league_name

Saídas:
- scrapers/whoscored/teams_with_characteristics.csv
- scrapers/whoscored/data/teams_with_characteristics.json
- scrapers/whoscored/brazilian_players.csv
- scrapers/whoscored/data/brazilian_players.json
- Atualiza também scrapers/whoscored/teams_to_scrape.csv e data/teams_to_scrape.json conforme especificação.
"""
import csv
import json
import os
import re
import sys
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from seleniumbase import Driver

BASE_URL = "https://br.whoscored.com"
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(CURRENT_DIR, "data")
INPUT_TEAMS_JSON = os.path.join(DATA_DIR, "teams_to_scrape.json")
if not os.path.exists(INPUT_TEAMS_JSON) and os.path.exists(os.path.join(DATA_DIR, "teams_seed.json")):
    INPUT_TEAMS_JSON = os.path.join(DATA_DIR, "teams_seed.json")
CHECKPOINT_FILE = os.path.join(DATA_DIR, "checkpoint_whoscored.json")

TEAMS_CSV_OUT = os.path.join(CURRENT_DIR, "teams_with_characteristics.csv")
TEAMS_JSON_OUT = os.path.join(DATA_DIR, "teams_with_characteristics.json")
PLAYERS_CSV_OUT = os.path.join(CURRENT_DIR, "brazilian_players.csv")
PLAYERS_JSON_OUT = os.path.join(DATA_DIR, "brazilian_players.json")

# Também atualizamos os arquivos de times da etapa 1
TEAMS_TO_SCRAPE_CSV = os.path.join(CURRENT_DIR, "teams_to_scrape.csv")
TEAMS_TO_SCRAPE_JSON = os.path.join(DATA_DIR, "teams_to_scrape.json")


def clean_name(raw_text: str) -> str:
    """Remove números iniciais de ranking ou camisa do texto do jogador."""
    if not raw_text:
        return ""
    return re.sub(r"^\d+", "", raw_text).strip()


def parse_characteristics(soup: BeautifulSoup):
    """Extrai pontos fortes, fracos e estilo de jogo de uma página de clube."""
    # 1. Strengths
    strengths = []
    str_container = soup.select_one(".strengths")
    if str_container:
        for c in str_container.select(".character"):
            name_el = c.select_one(".iconize")
            lvl_el = c.select_one(".sws-level-wrapper")
            if name_el and lvl_el:
                c_name = name_el.get_text(strip=True)
                c_level = lvl_el.get_text(strip=True)
                if c_name and "nenhum ponto forte" not in c_name.lower():
                    strengths.append({"name": c_name, "level": c_level})

    # 2. Weaknesses
    weaknesses = []
    weak_container = soup.select_one(".weaknesses")
    if weak_container:
        for c in weak_container.select(".character"):
            name_el = c.select_one(".iconize")
            lvl_el = c.select_one(".sws-level-wrapper")
            if name_el and lvl_el:
                c_name = name_el.get_text(strip=True)
                c_level = lvl_el.get_text(strip=True)
                if c_name and "nenhum ponto fraco" not in c_name.lower():
                    weaknesses.append({"name": c_name, "level": c_level})

    # 3. Style
    style = []
    style_container = soup.select_one(".style")
    if style_container:
        for c in style_container.select("li.character, .character"):
            txt = c.get_text(strip=True)
            if txt and "nenhum" not in txt.lower():
                style.append(txt)

    return strengths, weaknesses, style


def parse_brazilian_players(soup: BeautifulSoup, team_info: dict):
    """Extrai apenas jogadores brasileiros da tabela de elenco do clube."""
    players = []
    seen_player_ids = set()

    for r in soup.select("#top-player-stats-summary-grid tbody tr"):
        link = r.select_one("a.player-link")
        if not link:
            continue

        flag = link.select_one(".country, .ui-icon")
        flag_cls = flag.get("class", []) if flag else []
        is_br = any("flg-br" in c for c in flag_cls)
        if not is_br:
            continue

        href = link.get("href")
        if not href:
            continue

        m_id = re.search(r"/players/(\d+)/", href)
        if not m_id:
            continue
        player_id = int(m_id.group(1))

        if player_id in seen_player_ids:
            continue
        seen_player_ids.add(player_id)

        # Nome
        iconize = link.select_one(".iconize")
        raw_name = iconize.get_text(strip=True) if iconize else link.get_text(strip=True)
        name = clean_name(raw_name)

        full_url = urljoin(BASE_URL, href)

        # Idade e Posição
        metas = r.select(".player-meta-data")
        age = None
        pos = None
        if len(metas) >= 1:
            age_txt = metas[0].get_text(strip=True).replace(",", "")
            if age_txt.isdigit():
                age = int(age_txt)
        if len(metas) >= 2:
            pos = metas[1].get_text(strip=True).lstrip(", ").strip()

        players.append({
            "whoscored_player_id": player_id,
            "name": name,
            "player_url": full_url,
            "age": age,
            "position": pos,
            "whoscored_team_id": team_info.get("whoscored_team_id"),
            "team_name": team_info.get("team_name"),
            "league_code": team_info.get("league_code"),
            "league_name": team_info.get("league_name"),
        })

    return players


def save_checkpoint(processed_team_ids: set, teams_data: list, players_data: list):
    """Salva checkpoint em disco."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "processed_team_ids": list(processed_team_ids),
            "teams": teams_data,
            "players": players_data,
        }, f, ensure_ascii=False, indent=2)


def export_data(teams_data: list, players_data: list):
    """Exporta os dados finais em JSON e CSV, atualizando os arquivos principais."""
    os.makedirs(DATA_DIR, exist_ok=True)

    # 1. Teams JSON (teams_with_characteristics.json & teams_to_scrape.json)
    with open(TEAMS_JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(teams_data, f, ensure_ascii=False, indent=2)

    with open(TEAMS_TO_SCRAPE_JSON, "w", encoding="utf-8") as f:
        json.dump(teams_data, f, ensure_ascii=False, indent=2)

    # 2. Teams CSV (teams_with_characteristics.csv & teams_to_scrape.csv)
    # Apenas os campos permitidos: whoscored_team_id, league_code, league_name, team_name, team_url, strengths, weaknesses, style
    fieldnames_teams = [
        "whoscored_team_id",
        "league_code",
        "league_name",
        "team_name",
        "team_url",
        "strengths",
        "weaknesses",
        "style",
    ]

    for path in [TEAMS_CSV_OUT, TEAMS_TO_SCRAPE_CSV]:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames_teams)
            writer.writeheader()
            for t in teams_data:
                row = {
                    "whoscored_team_id": t.get("whoscored_team_id"),
                    "league_code": t.get("league_code"),
                    "league_name": t.get("league_name"),
                    "team_name": t.get("team_name"),
                    "team_url": t.get("team_url"),
                    "strengths": json.dumps(t.get("strengths", []), ensure_ascii=False),
                    "weaknesses": json.dumps(t.get("weaknesses", []), ensure_ascii=False),
                    "style": json.dumps(t.get("style", []), ensure_ascii=False),
                }
                writer.writerow(row)

    # 3. Brazilian Players JSON
    with open(PLAYERS_JSON_OUT, "w", encoding="utf-8") as f:
        json.dump(players_data, f, ensure_ascii=False, indent=2)

    # 4. Brazilian Players CSV
    fieldnames_players = [
        "whoscored_player_id",
        "name",
        "player_url",
        "age",
        "position",
        "whoscored_team_id",
        "team_name",
        "league_code",
        "league_name",
    ]
    with open(PLAYERS_CSV_OUT, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames_players)
        writer.writeheader()
        for p in players_data:
            writer.writerow(p)

    print(f"\n[OK] Arquivos salvos com sucesso!")
    print(f"     Clubes: {len(teams_data)} salvos em {TEAMS_CSV_OUT}")
    print(f"     Jogadores Brasileiros: {len(players_data)} salvos em {PLAYERS_CSV_OUT}")


def main():
    if not os.path.exists(INPUT_TEAMS_JSON):
        print(f"[!] Erro: Arquivo de clubes {INPUT_TEAMS_JSON} não encontrado!")
        sys.exit(1)

    with open(INPUT_TEAMS_JSON, "r", encoding="utf-8") as f:
        all_teams = json.load(f)

    print(f"[*] Total de {len(all_teams)} clubes carregados da primeira etapa.")

    # Carrega checkpoint se existir
    processed_ids = set()
    teams_results = []
    players_results = []

    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                chk = json.load(f)
                processed_ids = set(chk.get("processed_team_ids", []))
                teams_results = chk.get("teams", [])
                players_results = chk.get("players", [])
                print(f"[i] Checkpoint recuperado: {len(processed_ids)} clubes já processados.")
        except Exception as e:
            print(f"[!] Erro ao carregar checkpoint: {e}")

    # Inicializa Driver SeleniumBase UC
    driver = Driver(uc=True, headless=True)
    count = len(processed_ids)
    total = len(all_teams)

    try:
        for idx, team in enumerate(all_teams, 1):
            t_id = team.get("whoscored_team_id")
            if t_id in processed_ids:
                continue

            t_name = team.get("team_name")
            t_url = team.get("team_url")
            l_code = team.get("league_code")

            print(f"[{idx}/{total}] [{l_code}] {t_name} (ID: {t_id})...")
            try:
                driver.uc_open_with_reconnect(t_url, reconnect_time=2.5)
                driver.sleep(2)
                soup = BeautifulSoup(driver.page_source, "html.parser")

                # Extrai características
                strengths, weaknesses, style = parse_characteristics(soup)

                # Extrai jogadores brasileiros
                br_players = parse_brazilian_players(soup, team)

                # Monta registro do clube mantendo apenas os campos desejados
                cleaned_team = {
                    "whoscored_team_id": t_id,
                    "league_code": team.get("league_code"),
                    "league_name": team.get("league_name"),
                    "team_name": t_name,
                    "team_url": t_url,
                    "strengths": strengths,
                    "weaknesses": weaknesses,
                    "style": style,
                }

                teams_results.append(cleaned_team)
                players_results.extend(br_players)
                processed_ids.add(t_id)
                count += 1

                print(f"    -> Fortes: {len(strengths)} | Fracos: {len(weaknesses)} | Estilos: {len(style)} | Brazucas: {len(br_players)}")

            except Exception as ex:
                print(f"    [!] Erro ao processar clube {t_name}: {ex}. Reiniciando driver...")
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = Driver(uc=True, headless=True)

            # Recicla o navegador a cada 80 clubes para liberar RAM
            if count > 0 and count % 80 == 0:
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = Driver(uc=True, headless=True)

            # Salva checkpoint a cada 5 clubes ou no final
            if count % 5 == 0:
                save_checkpoint(processed_ids, teams_results, players_results)
                export_data(teams_results, players_results)

        # Salva final
        save_checkpoint(processed_ids, teams_results, players_results)
        export_data(teams_results, players_results)
        print("\n[V] Coleta do WhoScored concluída com sucesso!")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
