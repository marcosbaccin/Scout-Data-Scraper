import csv
import json
import time
import os
import re
import pandas as pd
from bs4 import BeautifulSoup, Comment
from seleniumbase import Driver
from io import StringIO

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)
TEAMS_CKPT_FILE = os.path.join(OUTPUT_DIR, "scraped_teams_ckpt.json")

TARGET_TABLES = ['stats_playing_time', 'stats_keeper']

# Colunas calculáveis a partir de outras (per 90, %, razões, somas, 90s, +/-): não são coletadas.
# O banco expõe esses valores por views (core/views.py).
DERIVED_EXACT = {'90s', 'Matches', 'G+A', 'G-PK', 'G+A-PK', 'Playing Time_90s'}


def is_derived_column(col):
    col = str(col)
    if col in DERIVED_EXACT or col.endswith('_90s') or col.endswith('G+A') or col.endswith('G-PK') or col.endswith('G+A-PK'):
        return True
    return 'Per 90' in col or '%' in col or '/' in col or col.endswith('90')


def load_teams():
    csv_path = os.path.join(os.path.dirname(__file__), 'teams_to_scrape.csv')
    if not os.path.exists(csv_path):
        print(f"[!] Erro: Arquivo {csv_path} não encontrado.")
        return []
    with open(csv_path, 'r', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def safe_uc_open(driver, url, reconnect_time=3.2):
    """Abre URL no FBref com detecção automática de rate-limit (429) e Cloudflare."""
    driver.uc_open_with_reconnect(url, reconnect_time=reconnect_time)
    time.sleep(1.2)
    html = driver.page_source or ""
    if "Too Many Requests" in html or "429 Too Many" in html or "Rate Limited" in html:
        print("       [!] Rate limit FBref (429) detectado. Aguardando 50s para liberar...")
        time.sleep(50)
        driver.uc_open_with_reconnect(url, reconnect_time=4)
        time.sleep(2)
        html = driver.page_source or ""
    if "Just a moment" in html:
        try:
            driver.uc_gui_click_captcha()
        except Exception:
            pass
        time.sleep(4)
        html = driver.page_source or ""
    return html


def extract_player_urls_from_team(driver, team_url):
    print(f"\n[*] Mapeando elenco: {team_url}", flush=True)
    time.sleep(1.5)
    html = safe_uc_open(driver, team_url, reconnect_time=3.2)

    soup = BeautifulSoup(html, 'html.parser')
    roster_table = soup.find('table', class_='stats_table')

    if not roster_table:
        return [], False

    player_urls = []
    tbody = roster_table.find('tbody')
    if not tbody:
        return [], True

    for row in tbody.find_all('tr'):
        # Filtra apenas jogadores com nacionalidade BRA
        nation_cell = row.find('td', {'data-stat': 'nationality'})
        if not nation_cell or 'BRA' not in nation_cell.text.upper():
            continue

        player_cell = row.find('th', {'data-stat': 'player'}) or row.find('td', {'data-stat': 'player'})
        if player_cell:
            link_tag = player_cell.find('a')
            if link_tag and '/players/' in link_tag['href']:
                base_url = f"https://fbref.com{link_tag['href']}"
                parts = base_url.split('/')
                player_id = parts[5]
                slug = parts[6]

                # Salvamos as duas URLs para usar o sistema de Fallback
                all_comps_url = f"https://fbref.com/en/players/{player_id}/all_comps/{slug}-Stats---All-Competitions"

                player_urls.append({
                    'name': link_tag.text.strip(),
                    'id': player_id,
                    'url_all_comps': all_comps_url,
                    'url_base': base_url
                })

    return player_urls, True


def verify_current_club(soup, target_teams_list):
    """Verifica se o ID do clube atual do jogador pertence à lista de clubes alvo."""
    meta_div = soup.find('div', id='meta')
    if not meta_div:
        return True  # Fallback de segurança

    club_tag = meta_div.find('strong', string=lambda t: t and 'Club:' in t)
    if club_tag:
        club_link = club_tag.find_next_sibling('a')
        if club_link and 'href' in club_link.attrs:
            match = re.search(r'/squads/([a-z0-9]+)/', club_link['href'])
            if match:
                current_club_id = match.group(1)
                is_valid = any(current_club_id in team['url'] for team in target_teams_list)
                return is_valid

    return False


def get_table_html(soup, comments, table_id):
    """Procura a tabela no DOM e depois nos comentários ocultos."""
    tag = soup.find('table', id=table_id)
    if tag:
        return tag
    for comment in comments:
        if f'id="{table_id}"' in comment:
            c_soup = BeautifulSoup(comment, 'html.parser')
            return c_soup.find('table', id=table_id)
    return None


def scrape_player_data(driver, player, target_teams_list):
    print(f"    -> Avaliando: {player['name']} ({player['id']})", flush=True)
    time.sleep(2.2)

    html = safe_uc_open(driver, player['url_all_comps'], reconnect_time=3.2)
    soup = BeautifulSoup(html, 'html.parser')

    if "Page Not Found" in html or not soup.find('div', id='meta'):
        print("       [*] Perfil 'All Comps' não existe. Acessando perfil Base...")
        time.sleep(1.5)
        html = safe_uc_open(driver, player['url_base'], reconnect_time=3.2)
        soup = BeautifulSoup(html, 'html.parser')

    if not verify_current_club(soup, target_teams_list):
        print(f"       [!] Descartado: Transferido para fora do escopo ou sem clube.")
        return None

    # --- BLOCO DE METADADOS (Tático e Físico) ---
    meta = soup.find('div', id='meta')
    player['birth_date'] = "None"
    player['position'] = "None"
    player['nationality'] = "Brazil"  # Elenco já filtrado por BRA; fallback quando 'Citizenship' não existe na página
    player['footed'] = "None"
    player['height'] = "None"
    player['weight'] = "None"

    if meta:
        meta_text = meta.text.replace('\xa0', ' ')

        # 1. Altura e Peso via Regex
        height_match = re.search(r'(\d+)\s*cm', meta_text)
        if height_match:
            player['height'] = height_match.group(1)

        weight_match = re.search(r'(\d+)\s*kg', meta_text)
        if weight_match:
            player['weight'] = weight_match.group(1)

        # 2. Data de Nascimento
        birth_tag = meta.find('span', id='necro-birth')
        if birth_tag and 'data-birth' in birth_tag.attrs:
            player['birth_date'] = birth_tag['data-birth']

        # 3. Posição, Pé Dominante e Nacionalidade
        for p in meta.find_all('p'):
            text = p.text.replace('\xa0', ' ').strip()

            if 'Position:' in text:
                pos_part = text.split('Position:')[1]
                player['position'] = " ".join(pos_part.split('▪')[0].strip().split())

            if 'Footed:' in text:
                foot_part = text.split('Footed:')[1]
                foot_part = foot_part.split('▪')[0].strip()
                foot_part = foot_part.split('(')[0].strip()
                player['footed'] = foot_part

            if 'Citizenship:' in text:
                a_tag = p.find('a')
                if a_tag:
                    player['nationality'] = a_tag.text.strip()
                else:
                    nat_text = text.split('Citizenship:')[1].strip()
                    player['nationality'] = nat_text.split()[0] if nat_text else "None"
    # ---------------------------------------------------

    player_data = {}
    comments = soup.find_all(string=lambda text: isinstance(text, Comment))

    for cat in TARGET_TABLES:
        nat_id = f"{cat}_nat_tm"
        t_nat = get_table_html(soup, comments, nat_id)
        if t_nat:
            _parse_table(t_nat, nat_id, player_data)

        exp_id = f"{cat}_expanded"
        t_exp = get_table_html(soup, comments, exp_id)

        if t_exp:
            _parse_table(t_exp, exp_id, player_data)
        else:
            dom_id = f"{cat}_dom_lg"
            t_dom = get_table_html(soup, comments, dom_id)
            if t_dom:
                print(f"       [*] Tabela '{exp_id}' ausente. Extraindo '{dom_id}' como substituta.")
                _parse_table(t_dom, exp_id, player_data)

    if not player_data:
        print("       [!] Sem tabelas de estatísticas (Base/Sem minutos).")

    return player_data


def _parse_table(table_tag, table_id, data_dict):
    try:
        html_content = StringIO(str(table_tag))
        df_list = pd.read_html(html_content, flavor='lxml')
        if df_list:
            df = df_list[0]

            if isinstance(df.columns, pd.MultiIndex):
                new_cols = []
                for col in df.columns.values:
                    if 'Unnamed' in col[0]:
                        new_cols.append(col[1])
                    elif col[0] == col[1]:
                        new_cols.append(col[0])
                    else:
                        new_cols.append(f"{col[0]}_{col[1]}")
                df.columns = new_cols

            data_dict[table_id] = df
            print(f"       [+] Tabela '{table_id}' extraída.")
    except Exception as e:
        print(f"       [!] Erro na tabela '{table_id}': {e}")


def save_player_data(player_info, scraped_tables):
    if not scraped_tables:
        return

    player_dir = os.path.join(OUTPUT_DIR, player_info['id'])
    os.makedirs(player_dir, exist_ok=True)

    with open(os.path.join(player_dir, 'info.txt'), 'w', encoding='utf-8') as f:
        f.write(f"Name: {player_info['name']}\n")
        f.write(f"ID: {player_info['id']}\n")
        f.write(f"URL: {player_info['url_base']}\n")
        f.write(f"BirthDate: {player_info.get('birth_date', 'None')}\n")
        f.write(f"Nationality: {player_info.get('nationality', 'None')}\n")
        f.write(f"Position: {player_info.get('position', 'None')}\n")
        f.write(f"Footed: {player_info.get('footed', 'None')}\n")
        f.write(f"Height: {player_info.get('height', 'None')}\n")
        f.write(f"Weight: {player_info.get('weight', 'None')}\n")

    for table_name, df in scraped_tables.items():
        df_clean = df[df['Season'] != 'Total'] if 'Season' in df.columns else df
        df_clean = df_clean[[c for c in df_clean.columns if not is_derived_column(c)]]
        csv_path = os.path.join(player_dir, f"{table_name}.csv")
        df_clean.to_csv(csv_path, index=False, encoding='utf-8')


def init_fbref_driver():
    drv = Driver(uc=True, incognito=True)
    drv.uc_open_with_reconnect("https://fbref.com/en/comps/", reconnect_time=5)
    try:
        drv.uc_gui_click_captcha()
    except Exception:
        pass
    time.sleep(3)
    return drv


def run_pipeline():
    teams = load_teams()
    if not teams:
        return

    scraped_teams = set()
    if os.path.exists(TEAMS_CKPT_FILE):
        try:
            with open(TEAMS_CKPT_FILE, "r", encoding="utf-8") as f:
                scraped_teams = set(json.load(f))
            print(f"[*] Retomando checkpoint FBref com {len(scraped_teams)} clubes já concluídos.")
        except Exception:
            scraped_teams = set()

    driver = init_fbref_driver()

    try:
        for idx, team in enumerate(teams, 1):
            t_url = team['url']
            t_name = team['team']
            if t_url in scraped_teams:
                continue

            print(f"\n[{idx}/{len(teams)}] Clube: {t_name}", flush=True)
            try:
                players, team_ok = extract_player_urls_from_team(driver, t_url)
            except Exception as e:
                print(f"    [!] Erro de sessão ao abrir {t_name} ({e}). Reiniciando navegador...")
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = init_fbref_driver()
                try:
                    players, team_ok = extract_player_urls_from_team(driver, t_url)
                except Exception as e2:
                    print(f"    [!] Falha ao processar clube {t_name}: {e2}")
                    continue

            if not team_ok:
                print(f"    [!] Tabela de elenco não carregou para {t_name}.")
                continue

            if not players:
                print(f"    [-] Nenhum brasileiro no elenco do {t_name}.")
                scraped_teams.add(t_url)
                with open(TEAMS_CKPT_FILE, "w", encoding="utf-8") as f:
                    json.dump(list(scraped_teams), f)
                continue

            print(f"    [+] {len(players)} brasileiros encontrados no elenco do {t_name}.")

            all_players_done = True
            for player in players:
                player_dir = os.path.join(OUTPUT_DIR, player['id'])
                if os.path.exists(os.path.join(player_dir, 'info.txt')):
                    print(f"    [>] Pulando {player['name']} - Já coletado.")
                    continue

                try:
                    scraped_tables = scrape_player_data(driver, player, teams)
                    if scraped_tables:
                        save_player_data(player, scraped_tables)
                        print(f"    [+] Dados salvos com sucesso.")
                except Exception as e:
                    print(f"    [!] Erro ao coletar {player['name']} ({e}). Reiniciando navegador...")
                    all_players_done = False
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = init_fbref_driver()

            if all_players_done:
                scraped_teams.add(t_url)
                with open(TEAMS_CKPT_FILE, "w", encoding="utf-8") as f:
                    json.dump(list(scraped_teams), f)

    finally:
        print("\n[*] Fechando navegador...")
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    run_pipeline()
