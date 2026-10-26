import time
import csv
import os
from bs4 import BeautifulSoup, Comment
from seleniumbase import Driver

TARGET_COUNTRIES = ['ENG', 'ITA', 'ESP', 'GER', 'FRA', 'KSA', 'BRA', 'NED', 'POR', 'USA', 'MEX']

def fetch_leagues_and_teams():
    print("[*] Inicializando SeleniumBase (Modo UC)...")
    
    driver = Driver(uc=True, incognito=True)
    team_urls = []
    
    try:
        print("[*] Acessando FBref Competitions...")
        driver.uc_open_with_reconnect("https://fbref.com/en/comps/", reconnect_time=6)
        
        # Tenta resolver o CAPTCHA do Cloudflare se existir
        driver.uc_gui_click_captcha()
        time.sleep(5)
        
        html = driver.page_source
        
        if "Just a moment" in html or "Cloudflare" in html:
            print("[!] Cloudflare detectado. Resolva manualmente (30 segundos).")
            time.sleep(30)
            html = driver.page_source
            
        print("[+] Acesso validado! Extraindo Ligas...")
        soup = BeautifulSoup(html, 'html.parser')
        
        # ID atualizado com base no seu mapeamento
        leagues_table = soup.find('table', id='comps_1_fa_club_league_senior')
        
        if not leagues_table:
            comments = soup.find_all(string=lambda text: isinstance(text, Comment))
            for comment in comments:
                if 'id="comps_1_fa_club_league_senior"' in comment:
                    comment_soup = BeautifulSoup(comment, 'html.parser')
                    leagues_table = comment_soup.find('table', id='comps_1_fa_club_league_senior')
                    break
                    
        if not leagues_table:
            print("[!] Falha crítica: Tabela de Ligas não localizada no HTML.")
            return

        league_urls = []
        for row in leagues_table.find('tbody').find_all('tr'):
            country_cell = row.find('td', {'data-stat': 'country'})
            gender_cell = row.find('td', {'data-stat': 'gender'})
            # Atributo atualizado para maxseason
            last_season_cell = row.find('td', {'data-stat': 'maxseason'})
            
            if not (country_cell and gender_cell and last_season_cell):
                continue
                
            country = country_cell.text.strip()
            gender = gender_cell.text.strip()
            
            if gender == 'M' and any(target in country for target in TARGET_COUNTRIES):
                link_tag = last_season_cell.find('a')
                if link_tag:
                    full_url = f"https://fbref.com{link_tag['href']}"
                    league_urls.append((country, full_url))
                    print(f"    -> Liga Alvo encontrada: {country}")

        if not league_urls:
            print("[!] Nenhuma liga alvo encontrada.")
            return

        for country, league_url in league_urls:
            print(f"\n[*] Acessando liga: {league_url}")
            print("    [zZz] Pausa anti-ban (6 segundos)...")
            time.sleep(6)
            
            driver.uc_open_with_reconnect(league_url, reconnect_time=4)
            time.sleep(3)
            
            league_html = driver.page_source
            league_soup = BeautifulSoup(league_html, 'html.parser')
            
            # Mudança: Usamos find_all para capturar MÚLTIPLAS tabelas (Ex: MLS Leste e Oeste)
            standings_tables = league_soup.find_all('table', class_='stats_table')
            
            if not standings_tables:
                comments = league_soup.find_all(string=lambda text: isinstance(text, Comment))
                for comment in comments:
                    if 'class="stats_table"' in comment:
                        comment_soup = BeautifulSoup(comment, 'html.parser')
                        found_tables = comment_soup.find_all('table', class_='stats_table')
                        standings_tables.extend(found_tables)

            if not standings_tables:
                print(f"    [!] Nenhuma tabela de classificação encontrada para a liga.")
                continue
                
            for table in standings_tables:
                tbody = table.find('tbody')
                if not tbody:
                    continue
                    
                for row in tbody.find_all('tr'):
                    squad_cell = row.find('td', {'data-stat': 'team'})
                    if squad_cell:
                        link_tag = squad_cell.find('a')
                        if link_tag:
                            team_name = link_tag.text.strip()
                            team_url = f"https://fbref.com{link_tag['href']}"
                            
                            # Evita adicionar o mesmo time duas vezes
                            if not any(t['team'] == team_name for t in team_urls):
                                team_urls.append({"country": country, "team": team_name, "url": team_url})
                                print(f"        - {team_name}")

    except Exception as e:
        print(f"\n[!] Erro durante a execução: {e}")
        
    finally:
        print("\n[*] Encerrando o navegador...")
        driver.quit()
        
    if team_urls:
        save_path = os.path.join(os.path.dirname(__file__), 'teams_to_scrape.csv')
        keys = team_urls[0].keys()
        with open(save_path, 'w', newline='', encoding='utf-8') as output_file:
            dict_writer = csv.DictWriter(output_file, fieldnames=keys)
            dict_writer.writeheader()
            dict_writer.writerows(team_urls)
        print(f"[+] Salvo em: {save_path}")
        
    print(f"[+] Raspagem finalizada! {len(team_urls)} times mapeados.")
    return team_urls

if __name__ == "__main__":
    fetch_leagues_and_teams()