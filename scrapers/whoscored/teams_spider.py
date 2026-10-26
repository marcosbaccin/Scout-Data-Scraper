"""
Coletor de Clubes por Liga no WhoScored.

Navega pelas páginas das ligas configuradas e extrai a tabela principal de classificação:
- Código e Nome da Liga
- ID do Time no WhoScored (teams/<id>/show/...)
- Nome do Clube
- URL do Clube no WhoScored
- Estatísticas de Classificação (Jogos, Vitórias, Empates, Derrotas, GM, GS, SG, Pontos)

Salva os resultados em:
- scrapers/whoscored/teams_to_scrape.csv
- scrapers/whoscored/data/teams_to_scrape.json
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
CSV_OUTPUT = os.path.join(CURRENT_DIR, "teams_to_scrape.csv")
JSON_OUTPUT = os.path.join(DATA_DIR, "teams_to_scrape.json")

# Ligas configuradas pelo usuário
LEAGUES = {
    "ING": {
        "name": "Inglaterra - Premier League",
        "url": "https://br.whoscored.com/regions/252/tournaments/2/inglaterra-premier-league",
    },
    "BRA": {
        "name": "Brasil - Brasileirão",
        "url": "https://br.whoscored.com/regions/31/tournaments/95/brasil-brasileir%C3%A3o",
    },
    "ESP": {
        "name": "Espanha - LaLiga",
        "url": "https://br.whoscored.com/regions/206/tournaments/4/espanha-laliga",
    },
    "FRA": {
        "name": "França - Ligue 1",
        "url": "https://br.whoscored.com/regions/74/tournaments/22/fran%C3%A7a-ligue-1",
    },
    "EUA": {
        "name": "EUA - Major League Soccer",
        "url": "https://br.whoscored.com/regions/233/tournaments/85/eua-major-league-soccer",
    },
    "ITA": {
        "name": "Itália - Serie A",
        "url": "https://br.whoscored.com/regions/108/tournaments/5/it%C3%A1lia-serie-a",
    },
    "HOL": {
        "name": "Países Baixos - Eredivisie",
        "url": "https://br.whoscored.com/regions/155/tournaments/13/pa%C3%ADses-baixos-eredivisie",
    },
    "ALE": {
        "name": "Alemanha - Bundesliga",
        "url": "https://br.whoscored.com/regions/81/tournaments/3/alemanha-bundesliga",
    },
    "POR": {
        "name": "Portugal - Liga Portugal",
        "url": "https://br.whoscored.com/regions/177/tournaments/21/portugal-liga-portugal",
    },
    "MEX": {
        "name": "México - Liga MX",
        "url": "https://br.whoscored.com/regions/142/tournaments/103/m%C3%A9xico-liga-mx",
    },
    "ARA": {
        "name": "Arábia Saudita - Pro League",
        "url": "https://br.whoscored.com/regions/194/tournaments/282/ar%C3%A1bia-saudita-pro-league",
    },
}


def _clean_int(val):
    if not val:
        return None
    val_clean = re.sub(r"[^\d-]", "", str(val))
    try:
        return int(val_clean)
    except ValueError:
        return None


def extract_teams_from_league(driver, code, league_info):
    url = league_info["url"]
    league_name = league_info["name"]

    print(f"\n[*] Acessando [{code}] {league_name}...")
    try:
        driver.uc_open_with_reconnect(url, reconnect_time=4)
        time.sleep(5)
    except Exception as e:
        print(f"    [!] Erro ao abrir URL da liga {league_name}: {e}")
        return []

    soup = BeautifulSoup(driver.page_source, "html.parser")

    # Localiza todas as tabelas de classificação (geral, conferências leste/oeste, etc.)
    standings_tables = soup.find_all("table", id=lambda x: x and "standings" in x)
    if not standings_tables:
        # Fallback para qualquer tabela com colunas de classificação
        standings_tables = [
            t for t in soup.find_all("table")
            if "Time" in " ".join([th.get_text(strip=True) for th in t.find_all("th")])
        ]

    if not standings_tables:
        print(f"    [!] Nenhuma tabela de classificação encontrada em {league_name}.")
        return []

    teams = []
    seen_ids = set()

    for table in standings_tables:
        tbody = table.find("tbody")
        if not tbody:
            continue

        for row in tbody.find_all("tr"):
            team_a = row.find("a", href=lambda h: h and "/teams/" in h)
            if not team_a:
                continue

            rel_href = team_a.get("href")
            team_name = team_a.get_text(strip=True)
            if not team_name or not rel_href:
                continue

            full_url = urljoin(BASE_URL, rel_href)

            # Extrai o ID numérico do clube no WhoScored (/teams/<id>/show/...)
            m_id = re.search(r"/teams/(\d+)/", full_url)
            whoscored_team_id = int(m_id.group(1)) if m_id else None

            if whoscored_team_id and whoscored_team_id in seen_ids:
                continue
            if whoscored_team_id:
                seen_ids.add(whoscored_team_id)

            # Extrai colunas da classificação (Time, J, V, E, D, GM, GS, SG, Pts)
            tds = [td.get_text(strip=True) for td in row.find_all("td")]
            # Localiza o índice da coluna que contém o nome do time
            team_idx = -1
            for i, td_text in enumerate(tds):
                if team_name in td_text:
                    team_idx = i
                    break

            teams.append({
                "whoscored_team_id": whoscored_team_id,
                "league_code": code,
                "league_name": league_name,
                "team_name": team_name,
                "team_url": full_url,
            })

    print(f"    [+] {len(teams)} clubes identificados com sucesso!")
    return teams


def scrape_all_teams():
    os.makedirs(DATA_DIR, exist_ok=True)
    all_teams = []

    print("=" * 80)
    print(" INICIANDO MAPEAMENTO DE CLUBES NO WHOSCORED")
    print("=" * 80)

    driver = Driver(uc=True, headless=True)
    try:
        for code, info in LEAGUES.items():
            teams = extract_teams_from_league(driver, code, info)
            all_teams.extend(teams)
            time.sleep(2)  # Pausa respeitosa entre ligas
    finally:
        print("\n[*] Fechando sessão do navegador...")
        driver.quit()

    # Salva em CSV
    fieldnames = [
        "whoscored_team_id", "league_code", "league_name", "team_name", "team_url"
    ]
    with open(CSV_OUTPUT, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_teams)

    # Salva em JSON
    with open(JSON_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(all_teams, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print(f"[+] MAPEAMENTO WHOSCORED FINALIZADO!")
    print(f"    -> Total de ligas processadas: {len(LEAGUES)}")
    print(f"    -> Total de clubes extraídos: {len(all_teams)}")
    print(f"    -> Arquivo CSV salvo em: {CSV_OUTPUT}")
    print(f"    -> Arquivo JSON salvo em: {JSON_OUTPUT}")
    print("=" * 80)


if __name__ == "__main__":
    scrape_all_teams()
