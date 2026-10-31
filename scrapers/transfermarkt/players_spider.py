"""
Scraper de Jogadores Brasileiros no Transfermarkt.

Navega pelas páginas de elenco dos 218 clubes mapeados e extrai apenas jogadores brasileiros:
- Nome do jogador
- URL do perfil individual e ID do Transfermarkt (spieler/<id>)
- Posição detalhada
- Data de nascimento e Idade
- Nacionalidade primária e secundária
- Valor de mercado atual (formato texto e número em Euros)

REGRA CRUCIAL DE DUPLA NACIONALIDADE:
O Transfermarkt posiciona a nacionalidade principal no topo (primeira bandeira).
Se a primeira bandeira NÃO for Brasil (ex.: Matheus Nunes com Portugal no topo e Brasil abaixo),
o jogador é descartado. Se a primeira bandeira for Brasil, é mantido.
"""
import csv
import json
import os
import re
import sys
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.browser import new_chrome

BASE_URL = "https://www.transfermarkt.com.br"
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(CURRENT_DIR, "data")
TEAMS_CSV = os.path.join(CURRENT_DIR, "teams_to_scrape.csv")
CHECKPOINT_JSON = os.path.join(DATA_DIR, "brazilians_checkpoint.json")
FINAL_CSV = os.path.join(CURRENT_DIR, "brazilian_players.csv")
FINAL_JSON = os.path.join(DATA_DIR, "brazilian_players.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.transfermarkt.com.br/",
    "Connection": "keep-alive",
}


def _has_roster_table(html: str) -> bool:
    if not html or "Human Verification" in html:
        return False
    return bool(BeautifulSoup(html, "html.parser").find("table", class_="items"))


class TransfermarktFetcher:
    """Sessão HTTP com transição automática para sessão Chrome autenticada quando AWS WAF exige CAPTCHA."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.driver = None
        self.waf_blocked = False
        self.use_browser_mode = True

    def _fetch_with_browser(self, url):
        """Usa a janela visível do Chrome (mantendo o cookie/TLS autenticado após verificação humana)."""
        if self.waf_blocked:
            return None
        try:
            if self.driver is None:
                print("\n       [*] Abrindo navegador Chrome para verificação humana (AWS WAF) do Transfermarkt...")
                self.driver = new_chrome()
                self.driver.set_page_load_timeout(25)
            try:
                self.driver.get(url)
            except Exception:
                pass

            # Aguarda até 180s (3 min) caso o AWS WAF exiba CAPTCHA manual na janela do Chrome
            notified = False
            for _ in range(90):
                time.sleep(2)
                html = self.driver.page_source or ""
                if _has_roster_table(html):
                    self.use_browser_mode = True
                    return html
                if not notified and ("Human Verification" in html or "captcha-container" in html):
                    print("\n       [!] AÇÃO NECESSÁRIA: Resolva o CAPTCHA 'Human Verification' na janela aberta do Chrome (aguardando até 3 minutos)...", flush=True)
                    notified = True

            if "Human Verification" in (self.driver.page_source or ""):
                print("\n       [!] Tempo esgotado aguardando resolução do CAPTCHA AWS WAF. Lote pausado.")
                self.waf_blocked = True
            return None
        except Exception as e:
            print(f"\n       [!] Erro na sessão Chrome: {e}")
            return None

    def fetch_page(self, url, retries=2, delay=2):
        """Realiza requisição HTTP ou usa diretamente o Chrome autenticado após desafio AWS WAF."""
        if self.waf_blocked:
            return None
        if self.use_browser_mode:
            return self._fetch_with_browser(url)

        for attempt in range(1, retries + 1):
            try:
                response = self.session.get(url, timeout=20)
                if response.status_code == 200 and _has_roster_table(response.text):
                    return response.text
                if response.status_code in (403, 405, 429) or "Human Verification" in response.text:
                    break
                print(f"       [!] Tentativa {attempt}: status HTTP {response.status_code}")
            except Exception as e:
                print(f"       [!] Tentativa {attempt}: falha de conexão: {e}")
            time.sleep(delay * attempt)

        return self._fetch_with_browser(url)

    def close(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None


def parse_market_value(val_str):
    """Converte valor de mercado textual do Transfermarkt em inteiro (Euros)."""
    if not val_str or val_str.strip() in ['-', 'N/A', '']:
        return None
    val = val_str.replace('€', '').replace(' ', '').strip().lower()
    m = re.search(r'([\d]+(?:[.,]\d+)?)', val)
    if not m:
        return None
    num_str = m.group(1).replace(',', '.')
    try:
        num = float(num_str)
        if 'bi' in val:
            return int(num * 1_000_000_000)
        elif 'mil' in val or 'k' in val or 'ths' in val:
            return int(num * 1_000)
        elif 'mi' in val or 'm' in val:
            return int(num * 1_000_000)
        return int(num)
    except Exception:
        return None


def parse_birth_age(text):
    """Extrai data de nascimento (YYYY-MM-DD) e idade inteira."""
    if not text:
        return None, None
    m_date = re.search(r'(\d{2})/(\d{2})/(\d{4})', text)
    birth_date = f'{m_date.group(3)}-{m_date.group(2)}-{m_date.group(1)}' if m_date else None
    m_age = re.search(r'\((\d+)\)', text)
    age = int(m_age.group(1)) if m_age else None
    return birth_date, age


def extract_brazilians_from_club(fetcher, club_info):
    """Extrai apenas jogadores com nacionalidade primária brasileira do elenco. Retorna (lista, sucesso_bool)."""
    club_name = club_info["club_name"]
    club_url = club_info["club_url"]
    league_code = club_info.get("league_code", "")
    league_name = club_info.get("league_name", "")

    html = fetcher.fetch_page(club_url)
    if not html:
        print(f"       [!] Não foi possível baixar a página de {club_name}.")
        return [], False

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="items")
    if not table or not table.find("tbody"):
        print(f"       [!] Tabela de elenco não encontrada para {club_name}.")
        return [], False

    brazilians = []
    tbody = table.find("tbody")

    for row in tbody.find_all("tr", class_=["odd", "even"]):
        # Nome e URL do jogador
        name_td = row.find("table", class_="inline-table")
        if not name_td:
            continue
        a_tags = name_td.find_all("a")
        if not a_tags:
            continue
        player_link = a_tags[-1]
        player_name = player_link.get_text(strip=True)
        player_rel_url = player_link.get("href")
        player_full_url = urljoin(BASE_URL, player_rel_url)

        m_id = re.search(r'spieler/(\d+)', player_full_url)
        transfermarkt_id = int(m_id.group(1)) if m_id else None

        # Posição detalhada
        pos_tr = name_td.find_all("tr")[-1]
        position = pos_tr.find("td").get_text(strip=True) if pos_tr and pos_tr.find("td") else ""

        # Bandeiras / Nacionalidade
        flags_img = row.find_all("img", class_="flaggenrahmen")
        flags = [img.get("title") or img.get("alt") for img in flags_img if (img.get("title") or img.get("alt"))]

        # REGRA CRUCIAL: Apenas brasileiros onde a bandeira PRINCIPAL (primeira / no topo) é Brasil
        if not flags or flags[0].strip().lower() != "brasil":
            continue

        primary_nat = flags[0].strip()
        secondary_nat = flags[1].strip() if len(flags) > 1 else None

        # Camisa
        num_div = row.find("div", class_="rn_nummer")
        shirt_num = int(num_div.get_text(strip=True)) if (num_div and num_div.get_text(strip=True).isdigit()) else None

        # Data de nascimento e Idade
        birth_date, age = None, None
        for td in row.find_all("td", class_="zentriert"):
            b, a = parse_birth_age(td.get_text(strip=True))
            if b or a:
                birth_date, age = b, a
                break

        # Valor de mercado
        mv_td = row.find("td", class_="rechts")
        mv_raw = mv_td.get_text(strip=True) if mv_td else ""
        mv_eur = parse_market_value(mv_raw)

        brazilians.append({
            "transfermarkt_id": transfermarkt_id,
            "name": player_name,
            "url": player_full_url,
            "shirt_number": shirt_num,
            "position": position,
            "birth_date": birth_date,
            "age": age,
            "nationality": primary_nat,
            "secondary_nationality": secondary_nat,
            "current_club": club_name,
            "league_code": league_code,
            "league_name": league_name,
            "market_value_raw": mv_raw,
            "market_value_eur": mv_eur,
        })

    return brazilians, True


def scrape_all_players(limit=None):
    if not os.path.exists(TEAMS_CSV):
        print(f"[!] Erro: Arquivo {TEAMS_CSV} não encontrado. Execute teams_spider.py primeiro.")
        return

    os.makedirs(DATA_DIR, exist_ok=True)

    with open(TEAMS_CSV, "r", encoding="utf-8-sig") as f:
        teams = list(csv.DictReader(f))

    if limit:
        teams = teams[:limit]

    total_teams = len(teams)
    print("=" * 85)
    print(f" INICIANDO EXTRAÇÃO DE JOGADORES BRASILEIROS EM {total_teams} CLUBES NO TRANSFERMARKT")
    print("=" * 85)

    # Carrega checkpoint anterior se existir
    scraped_club_urls = set()
    all_players_by_id = {}
    if os.path.exists(CHECKPOINT_JSON):
        try:
            with open(CHECKPOINT_JSON, "r", encoding="utf-8") as f:
                ckpt = json.load(f)
                scraped_club_urls = set(ckpt.get("scraped_clubs", []))
                for p in ckpt.get("players", []):
                    if p.get("transfermarkt_id"):
                        all_players_by_id[p["transfermarkt_id"]] = p
            print(f"[*] Checkpoint restaurado: {len(scraped_club_urls)} clubes e {len(all_players_by_id)} jogadores já processados.")
        except Exception as e:
            print(f"[!] Erro ao ler checkpoint: {e}")

    fetcher = TransfermarktFetcher()
    failed_clubs = []

    try:
        for idx, club in enumerate(teams, 1):
            c_url = club["club_url"]
            c_name = club["club_name"]
            c_lg = club["league_code"]

            if c_url in scraped_club_urls:
                continue

            print(f"[{idx:03d}/{total_teams:03d}] [{c_lg}] {c_name}...", end=" ", flush=True)
            players, ok = extract_brazilians_from_club(fetcher, club)
            if not ok:
                failed_clubs.append(c_name)
                if fetcher.waf_blocked:
                    break
                continue

            for p in players:
                p_id = p["transfermarkt_id"]
                if p_id:
                    all_players_by_id[p_id] = p

            scraped_club_urls.add(c_url)
            print(f"{len(players)} brasileiros encontrados.")

            # Checkpoint incremental a cada 10 clubes válidos
            if len(scraped_club_urls) % 10 == 0:
                with open(CHECKPOINT_JSON, "w", encoding="utf-8") as f:
                    json.dump({
                        "scraped_clubs": list(scraped_club_urls),
                        "players": list(all_players_by_id.values()),
                    }, f, ensure_ascii=False, indent=2)

            time.sleep(2.2)
    finally:
        fetcher.close()

    # Salva checkpoint atualizado
    with open(CHECKPOINT_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "scraped_clubs": list(scraped_club_urls),
            "players": list(all_players_by_id.values()),
        }, f, ensure_ascii=False, indent=2)

    player_list = list(all_players_by_id.values())

    # Salva arquivos finais
    with open(FINAL_JSON, "w", encoding="utf-8") as f:
        json.dump(player_list, f, ensure_ascii=False, indent=2)

    fieldnames = [
        "transfermarkt_id", "name", "url", "shirt_number", "position",
        "birth_date", "age", "nationality", "secondary_nationality",
        "current_club", "league_code", "league_name", "market_value_raw", "market_value_eur"
    ]
    with open(FINAL_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(player_list)

    print("\n" + "=" * 85)
    print(f"[+] EXTRAÇÃO CONCLUÍDA!")
    print(f"    -> Clubes processados com sucesso: {len(scraped_club_urls)}/{total_teams}")
    if failed_clubs:
        print(f"    -> Clubes pendentes ({len(failed_clubs)}): {', '.join(failed_clubs[:10])}")
    print(f"    -> Total de jogadores brasileiros extraídos: {len(player_list)}")
    print(f"    -> Arquivo JSON salvo em: {FINAL_JSON}")
    print(f"    -> Arquivo CSV salvo em: {FINAL_CSV}")
    print("=" * 85)


if __name__ == "__main__":
    scrape_all_players()
