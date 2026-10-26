import json
import os
import time
import sys
from bs4 import BeautifulSoup

# Permite importar o pacote core ao rodar o script a partir da raiz do projeto
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.browser import new_chrome

LEAGUES_CONFIG = {
    "Brazil": {"t_id": 325, "s_id": 87678},
    "England": {"t_id": 17, "s_id": 96668},
    "Spain": {"t_id": 8, "s_id": 97268},
    "Germany": {"t_id": 35, "s_id": 97464},
    "Italy": {"t_id": 23, "s_id": 95836}, 
    "France": {"t_id": 34, "s_id": 96127},
    "Saudi Arabia": {"t_id": 955, "s_id": 99275},
    "Netherlands": {"t_id": 37, "s_id": 96143},
    "Portugal": {"t_id": 238, "s_id": 97436},
    "USA (MLS)": {"t_id": 242, "s_id": 86668},
    "Mexico (Liga MX)": {"t_id": 11621, "s_id": 96191}
}

OUTPUT_DIR = "data/sofascore"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "sofascore_teams.json")

def scrape_leagues():
    all_teams = {}
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("[*] Iniciando a varredura global de Clubes do Sofascore via Chrome...")
    
    # Inicia o navegador para burlar o firewall. 
    # Rodamos sem modo headless (oculto) para garantir aprovação no Cloudflare.
    driver = new_chrome()
    
    for league_name, ids in LEAGUES_CONFIG.items():
        print(f"\n    -> Mapeando: {league_name}")
        t_id = ids["t_id"]
        s_id = ids["s_id"]

        url = f"https://www.sofascore.com/api/v1/unique-tournament/{t_id}/season/{s_id}/standings/total"

        try:
            driver.get(url)
            time.sleep(3) # Aguarda o desafio anti-bot passar e o JSON carregar
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            # O navegador injeta o JSON puro dentro de uma tag <pre>
            pre_tag = soup.find('pre')
            
            if pre_tag:
                data = json.loads(pre_tag.text)
                league_teams = []

                standings = data.get("standings", [])
                
                for standing in standings:
                    rows = standing.get("rows", [])
                    for row in rows:
                        team = row.get("team", {})
                        team_name = team.get("name")
                        team_id = team.get("id")

                        if team_id and team_name:
                            league_teams.append({"id": team_id, "name": team_name})

                # Remove duplicatas
                unique_teams = {t['id']: t for t in league_teams}.values()
                all_teams[league_name] = list(unique_teams)
                
                print(f"       [+] {len(unique_teams)} clubes capturados.")
            else:
                # Verifica se a Itália (ou outra liga) retornou erro 404 (Not Found)
                if "Not Found" in driver.page_source or "error" in driver.page_source.lower():
                    print(f"       [!] Erro na API: s_id incorreto para esta liga.")
                else:
                    print(f"       [!] Erro: Tag <pre> com JSON não encontrada. Bloqueio ativo.")

        except Exception as e:
            print(f"       [!] Falha de conexão/processamento: {e}")

    driver.quit()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_teams, f, ensure_ascii=False, indent=4)

    print(f"\n[+] Extração concluída! Matriz de IDs salva em: {OUTPUT_FILE}")

if __name__ == "__main__":
    scrape_leagues()