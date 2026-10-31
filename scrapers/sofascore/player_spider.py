import json
import os
import time
import sys
from bs4 import BeautifulSoup

# Permite importar o pacote core ao rodar o script a partir da raiz do projeto
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.browser import new_chrome

DATA_DIR = "data/sofascore"
TEAMS_FILE = os.path.join(DATA_DIR, "sofascore_teams.json")
PLAYERS_FILE = os.path.join(DATA_DIR, "sofascore_players.json")


def scrape_squads():
    if not os.path.exists(TEAMS_FILE):
        print(f"[!] Arquivo de times não encontrado em {TEAMS_FILE}. Rode o team_spider.py primeiro.")
        return

    with open(TEAMS_FILE, "r", encoding="utf-8") as f:
        leagues_data = json.load(f)

    all_players = {}
    if os.path.exists(PLAYERS_FILE):
        try:
            with open(PLAYERS_FILE, "r", encoding="utf-8") as f:
                all_players = json.load(f)
            print(f"[*] Retomando checkpoint existente com {len(all_players)} clubes já processados.")
        except Exception:
            all_players = {}

    total_players_found = sum(len(v) for v in all_players.values())

    print("[*] Iniciando a Extração Global de Brasileiros via __NEXT_DATA__...")
    driver = new_chrome()

    for league_name, teams in leagues_data.items():
        if not teams:
            continue

        print(f"\n--- Processando Liga: {league_name} ({len(teams)} times) ---")

        for team in teams:
            team_id = str(team["id"])
            team_name = team["name"]

            if team_id in all_players:
                print(f"    [>] {team_name} (ID: {team_id}): Já coletado ({len(all_players[team_id])} BRs).")
                continue

            url = f"https://www.sofascore.com/pt/football/team/team/{team_id}"

            try:
                driver.get(url)
                time.sleep(3)

                html_source = driver.page_source
                soup = BeautifulSoup(html_source, 'html.parser')
                script_tag = soup.find('script', id='__NEXT_DATA__')

                if script_tag:
                    data = json.loads(script_tag.string)
                    players_array = data.get('props', {}).get('pageProps', {}).get('players', {}).get('players', [])

                    team_roster = []
                    for p in players_array:
                        player_info = p.get('player', {})
                        p_id = player_info.get('id')
                        name = player_info.get('name')
                        pos = player_info.get('position')

                        # Extrai a sigla do país (ex: 'BR', 'AR', 'ES')
                        country_obj = player_info.get('country') or {}
                        country = country_obj.get('alpha2')

                        # O FILTRO DE OURO: Salva apenas se for do Brasil
                        if p_id and name and country == 'BR':
                            team_roster.append({
                                "id": p_id,
                                "name": name,
                                "position": pos,
                                "team": team_name,
                                "league": league_name,
                                "nationality": country_obj.get("name") or "Brazil",
                                "preferredFoot": player_info.get("preferredFoot"),
                                "height": player_info.get("height"),
                            })

                    all_players[team_id] = team_roster
                    total_players_found += len(team_roster)
                    print(f"    [+] {team_name} (ID: {team_id}): {len(team_roster)} BRs mapeados.")

                else:
                    print(f"    [!] {team_name}: Tag __NEXT_DATA__ não encontrada.")

            except Exception as e:
                print(f"    [!] {team_name}: Falha ao processar página. Erro: {e}")

        # Salva checkpoint ao fim de cada liga
        with open(PLAYERS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_players, f, ensure_ascii=False, indent=4)

    driver.quit()

    with open(PLAYERS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_players, f, ensure_ascii=False, indent=4)

    print(f"\n[+] Extração Finalizada! {total_players_found} jogadores BRASILEIROS salvos em: {PLAYERS_FILE}")


if __name__ == "__main__":
    scrape_squads()
