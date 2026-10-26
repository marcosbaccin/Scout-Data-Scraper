"""
Coletor de Clubes por Liga no Transfermarkt.

Navega pelas páginas das ligas configuradas e extrai a tabela principal de clubes:
- Código e Nome da Liga
- Nome do Clube
- URL do Clube no Transfermarkt
- Plantel (nº de jogadores), Média de Idade, Estrangeiros e Valor de Mercado Total

Salva os resultados em:
- scrapers/transfermarkt/teams_to_scrape.csv
- scrapers/transfermarkt/data/teams_to_scrape.json
"""
import csv
import json
import os
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.transfermarkt.com.br"
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(CURRENT_DIR, "data")
CSV_OUTPUT = os.path.join(CURRENT_DIR, "teams_to_scrape.csv")
JSON_OUTPUT = os.path.join(DATA_DIR, "teams_to_scrape.json")

# Ligas configuradas pelo usuário (México Apertura selecionado para representar a Liga MX)
LEAGUES = {
    "ING": {
        "name": "Premier League",
        "url": "https://www.transfermarkt.com.br/premier-league/startseite/wettbewerb/GB1",
    },
    "ESP": {
        "name": "LaLiga",
        "url": "https://www.transfermarkt.com.br/laliga/startseite/wettbewerb/ES1",
    },
    "ITA": {
        "name": "Serie A",
        "url": "https://www.transfermarkt.com.br/serie-a/startseite/wettbewerb/IT1",
    },
    "ALE": {
        "name": "Bundesliga",
        "url": "https://www.transfermarkt.com.br/bundesliga/startseite/wettbewerb/L1",
    },
    "FRA": {
        "name": "Ligue 1",
        "url": "https://www.transfermarkt.com.br/ligue-1/startseite/wettbewerb/FR1",
    },
    "BRA": {
        "name": "Campeonato Brasileiro Série A",
        "url": "https://www.transfermarkt.com.br/campeonato-brasileiro-serie-a/startseite/wettbewerb/BRA1",
    },
    "EUA": {
        "name": "Major League Soccer",
        "url": "https://www.transfermarkt.com.br/major-league-soccer/startseite/wettbewerb/MLS1",
    },
    "MEX": {
        "name": "Liga MX Apertura",
        "url": "https://www.transfermarkt.com.br/liga-mx-apertura/startseite/wettbewerb/MEXA",
    },
    "HOL": {
        "name": "Eredivisie",
        "url": "https://www.transfermarkt.com.br/eredivisie/startseite/wettbewerb/NL1",
    },
    "POR": {
        "name": "Liga Portugal",
        "url": "https://www.transfermarkt.com.br/liga-portugal/startseite/wettbewerb/PO1",
    },
    "ARA": {
        "name": "Saudi Pro League",
        "url": "https://www.transfermarkt.com.br/saudi-pro-league/startseite/wettbewerb/SA1",
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.transfermarkt.com.br/",
    "Connection": "keep-alive",
}


def fetch_page(url, retries=3, delay=2):
    """Realiza requisição HTTP com tentativas e tratamento de erros."""
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                return response.text
            print(f"       [!] Tentativa {attempt}: status HTTP {response.status_code}")
        except Exception as e:
            print(f"       [!] Tentativa {attempt}: falha de conexão: {e}")
        time.sleep(delay * attempt)
    return None


def extract_teams_from_league(code, league_info):
    """Extrai os dados da tabela de clubes de uma liga."""
    url = league_info["url"]
    league_name = league_info["name"]

    print(f"\n[*] Extraindo clubes de [{code}] {league_name}...")
    html = fetch_page(url)
    if not html:
        print(f"    [!] Não foi possível baixar a página de {league_name}.")
        return []

    soup = BeautifulSoup(html, "html.parser")

    # Localiza a tabela com a classe 'items' correspondente aos clubes
    target_table = None
    for t in soup.find_all("table", class_="items"):
        header_text = " ".join([th.get_text(strip=True) for th in t.find_all("th")])
        if "Clube" in header_text and ("Plantel" in header_text or "valor de mercado" in header_text):
            target_table = t
            break

    if not target_table:
        print(f"    [!] Tabela principal de clubes não encontrada em {league_name}.")
        return []

    teams = []
    tbody = target_table.find("tbody")
    if not tbody:
        return []

    for row in tbody.find_all("tr"):
        # Célula com o nome e link do clube
        club_td = row.find("td", class_="hauptlink")
        if not club_td:
            continue
        link = club_td.find("a")
        if not link or not link.get("href"):
            continue

        club_name = link.get_text(strip=True)
        club_rel_url = link.get("href")
        club_full_url = urljoin(BASE_URL, club_rel_url)

        # Captura colunas adicionais da tabela caso existam
        all_tds = [td.get_text(strip=True) for td in row.find_all("td")]
        squad_size = all_tds[2] if len(all_tds) > 2 else ""
        avg_age = all_tds[3] if len(all_tds) > 3 else ""
        foreigners = all_tds[4] if len(all_tds) > 4 else ""
        total_market_value = all_tds[6] if len(all_tds) > 6 else (all_tds[5] if len(all_tds) > 5 else "")

        teams.append({
            "league_code": code,
            "league_name": league_name,
            "club_name": club_name,
            "club_url": club_full_url,
            "squad_size": squad_size,
            "avg_age": avg_age,
            "foreigners": foreigners,
            "total_market_value": total_market_value,
        })

    print(f"    [+] {len(teams)} clubes identificados com sucesso!")
    return teams


def scrape_all_teams():
    os.makedirs(DATA_DIR, exist_ok=True)
    all_teams = []

    print("=" * 80)
    print(" INICIANDO MAPEAMENTO DE CLUBES NO TRANSFERMARKT")
    print("=" * 80)

    for code, info in LEAGUES.items():
        teams = extract_teams_from_league(code, info)
        all_teams.extend(teams)
        time.sleep(1.2)  # Pausa respeitosa entre ligas

    # Salva em CSV
    with open(CSV_OUTPUT, "w", encoding="utf-8-sig", newline="") as f:
        fieldnames = [
            "league_code", "league_name", "club_name", "club_url",
            "squad_size", "avg_age", "foreigners", "total_market_value",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_teams)

    # Salva em JSON
    with open(JSON_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(all_teams, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print(f"[+] MAPEAMENTO FINALIZADO!")
    print(f"    -> Total de ligas processadas: {len(LEAGUES)}")
    print(f"    -> Total de clubes extraídos: {len(all_teams)}")
    print(f"    -> Arquivo CSV salvo em: {CSV_OUTPUT}")
    print(f"    -> Arquivo JSON salvo em: {JSON_OUTPUT}")
    print("=" * 80)


if __name__ == "__main__":
    scrape_all_teams()
