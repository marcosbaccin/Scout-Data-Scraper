"""
Coletor Detalhado de Jogadores Brasileiros no WhoScored (Etapa 3 - Opção 2).

Para cada jogador brasileiro identificado na Etapa 2:
1. Página Principal (/show/<slug>):
   - Perfil e Dados Cadastrais: Nome, Nome Completo, Clube Atual, Camisa, Idade, Data de Nascimento, Altura, Nacionalidade, Posição.
   - Características Exclusivas: Pontos Fortes (com nível), Pontos Fracos (com nível), Estilo de Jogo.
2. Página de Histórico (/history/<slug>):
   - Tabela de Resumo: Temporada, Time, Campeonato, Jogos, Minutos, Gols, Assistências, JdaP (MotM), Rating.
   - Aba Ofensivo: Vezes Desarmado (Des / Dispossessed), Domínios Errados (DomErr / Unsuccessful Touches).
   - Aba Passes: Bolas Enfiadas certas (BEnfiada / Through Balls).

Salva checkpoints contínuos e exporta em JSON, CSV e scout.db.
"""
import csv
import datetime as dt
import json
import os
import re
import sys
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from seleniumbase import Driver

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(CURRENT_DIR, "data")
INPUT_PLAYERS_JSON = os.path.join(DATA_DIR, "brazilian_players.json")
CHECKPOINT_FILE = os.path.join(DATA_DIR, "checkpoint_player_details.json")

PLAYERS_DETAILED_JSON = os.path.join(DATA_DIR, "players_detailed.json")
PLAYERS_DETAILED_CSV = os.path.join(CURRENT_DIR, "players_detailed.csv")
SEASON_STATS_JSON = os.path.join(DATA_DIR, "players_season_stats.json")
SEASON_STATS_CSV = os.path.join(CURRENT_DIR, "players_season_stats.csv")


def parse_show_page(driver, url):
    """Extrai perfil cadastral e características da página /show/."""
    driver.uc_open_with_reconnect(url, reconnect_time=2.5)
    driver.sleep(2)
    soup = BeautifulSoup(driver.page_source, "html.parser")

    fields = {}
    for lbl in soup.select("span.info-label"):
        key = lbl.get_text(strip=True).rstrip(":")
        val = lbl.parent.get_text(strip=True).replace(lbl.get_text(strip=True), "").strip()
        fields[key] = val

    # Idade e Data de Nascimento: "29 anos (20-06-1997)"
    age = None
    birth_date = None
    idade_raw = fields.get("Idade", "")
    m_age = re.search(r"(\d+)\s*anos", idade_raw)
    if m_age:
        age = int(m_age.group(1))
    m_date = re.search(r"\((\d{2})-(\d{2})-(\d{4})\)", idade_raw)
    if m_date:
        d, m, y = m_date.groups()
        birth_date = f"{y}-{m}-{d}"

    # Altura
    height = None
    alt_raw = fields.get("Altura", "")
    m_h = re.search(r"(\d+)", alt_raw)
    if m_h:
        height = int(m_h.group(1))

    # Número da camisa
    shirt = None
    camisa_raw = fields.get("Número da Camisa", "")
    if camisa_raw.isdigit():
        shirt = int(camisa_raw)

    profile = {
        "name": fields.get("Nome", ""),
        "full_name": fields.get("Nome Completo", ""),
        "current_team": fields.get("Time Atual", ""),
        "shirt_number": shirt,
        "age": age,
        "birth_date": birth_date,
        "height": height,
        "nationality": fields.get("Nacionalidade", "Brasil"),
        "position": fields.get("Posições", ""),
    }

    # Características
    strengths = []
    str_div = soup.select_one(".strengths")
    if str_div:
        for c in str_div.select(".character"):
            n = c.select_one(".iconize")
            l = c.select_one(".sws-level-wrapper, .level")
            if n and l and "nenhum ponto forte" not in n.get_text(strip=True).lower():
                strengths.append({"name": n.get_text(strip=True), "level": l.get_text(strip=True)})

    weaknesses = []
    weak_div = soup.select_one(".weaknesses")
    if weak_div:
        for c in weak_div.select(".character"):
            n = c.select_one(".iconize")
            l = c.select_one(".sws-level-wrapper, .level")
            if n and l and "nenhum ponto fraco" not in n.get_text(strip=True).lower():
                weaknesses.append({"name": n.get_text(strip=True), "level": l.get_text(strip=True)})

    style = []
    style_div = soup.select_one(".style")
    if style_div:
        for c in style_div.select(".character, li"):
            txt = c.get_text(strip=True)
            if txt and "nenhum" not in txt.lower():
                style.append(txt)

    characteristics = {
        "strengths": strengths,
        "weaknesses": weaknesses,
        "style_of_play": style,
    }

    return profile, characteristics


def parse_history_page(driver, history_url, player_id):
    """Extrai histórico por temporada (Opção 2: Resumo + Ofensivo + Passes)."""
    try:
        driver.uc_open_with_reconnect(history_url, reconnect_time=2.5)
        driver.sleep(2)
    except Exception as e:
        print(f"      [!] Erro ao abrir histórico: {e}")
        return []

    soup = BeautifulSoup(driver.page_source, "html.parser")
    summary_data = {}

    sum_container = soup.select_one("#player-tournament-stats-summary")
    if not sum_container:
        return []

    for r in sum_container.select("tbody tr"):
        tds = [td.get_text(strip=True) for td in r.select("td")]
        if len(tds) >= 14:
            season = tds[0]
            team = tds[1]
            comp = tds[4] if tds[2] == season else tds[2]
            row_key = f"{season}|{team}|{comp}"

            motm = None
            m_txt = tds[-2]
            if m_txt.isdigit():
                motm = int(m_txt)

            rating = None
            r_txt = tds[-1].replace(",", ".")
            try:
                rating = float(r_txt)
            except ValueError:
                rating = None

            mins = None
            min_col = tds[6] if tds[2] == season else tds[4]
            if min_col.isdigit():
                mins = int(min_col)

            goals = 0
            g_col = tds[7] if tds[2] == season else tds[5]
            if g_col.isdigit():
                goals = int(g_col)

            assists = 0
            a_col = tds[8] if tds[2] == season else tds[6]
            if a_col.isdigit():
                assists = int(a_col)

            summary_data[row_key] = {
                "player_id": player_id,
                "season": season,
                "team": team,
                "competition": comp,
                "matches": tds[5] if tds[2] == season else tds[3],
                "minutes": mins,
                "goals": goals,
                "assists": assists,
                "motm": motm,
                "rating": rating,
                "through_balls_per_game": None,
                "dispossessed_per_game": None,
                "unsuccessful_touches_per_game": None,
            }

    if not summary_data:
        return []

    # 2. Aba Ofensivo (Des / DomErr)
    try:
        link_off = driver.find_element("css selector", "a[href='#player-tournament-stats-offensive']")
        driver.execute_script("arguments[0].scrollIntoView(true);", link_off)
        link_off.click()
        driver.sleep(1.5)
        soup_off = BeautifulSoup(driver.page_source, "html.parser")
        off_container = soup_off.select_one("#player-tournament-stats-offensive")
        if off_container:
            for r in off_container.select("tbody tr"):
                tds = [td.get_text(strip=True) for td in r.select("td")]
                if len(tds) >= 15:
                    season = tds[0]
                    team = tds[1]
                    comp = tds[4] if tds[2] == season else tds[2]
                    row_key = f"{season}|{team}|{comp}"

                    des = None
                    try:
                        des = float(tds[-3].replace(",", "."))
                    except ValueError:
                        des = None

                    dom_err = None
                    try:
                        dom_err = float(tds[-2].replace(",", "."))
                    except ValueError:
                        dom_err = None

                    if row_key in summary_data:
                        summary_data[row_key]["dispossessed_per_game"] = des
                        summary_data[row_key]["unsuccessful_touches_per_game"] = dom_err
    except Exception:
        pass

    # 3. Aba Passes (BEnfiada)
    try:
        link_pass = driver.find_element("css selector", "a[href='#player-tournament-stats-passing']")
        driver.execute_script("arguments[0].scrollIntoView(true);", link_pass)
        link_pass.click()
        driver.sleep(1.5)
        soup_pass = BeautifulSoup(driver.page_source, "html.parser")
        pass_container = soup_pass.select_one("#player-tournament-stats-passing")
        if pass_container:
            for r in pass_container.select("tbody tr"):
                tds = [td.get_text(strip=True) for td in r.select("td")]
                if len(tds) >= 13:
                    season = tds[0]
                    team = tds[1]
                    comp = tds[4] if tds[2] == season else tds[2]
                    row_key = f"{season}|{team}|{comp}"

                    b_enf = None
                    try:
                        b_enf = float(tds[-2].replace(",", "."))
                    except ValueError:
                        b_enf = None

                    if row_key in summary_data:
                        summary_data[row_key]["through_balls_per_game"] = b_enf
    except Exception:
        pass

    return list(summary_data.values())


def save_checkpoint(processed_ids: set, detailed_players: list, season_stats: list):
    """Salva checkpoint em disco."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "processed_player_ids": list(processed_ids),
            "players": detailed_players,
            "season_stats": season_stats,
        }, f, ensure_ascii=False, indent=2)


def export_data(detailed_players: list, season_stats: list):
    """Exporta os resultados em JSON e CSV."""
    os.makedirs(DATA_DIR, exist_ok=True)

    # 1. Jogadores Detalhados (JSON & CSV)
    with open(PLAYERS_DETAILED_JSON, "w", encoding="utf-8") as f:
        json.dump(detailed_players, f, ensure_ascii=False, indent=2)

    fieldnames_p = [
        "whoscored_player_id", "name", "full_name", "player_url", "current_team",
        "shirt_number", "age", "birth_date", "height", "nationality", "position",
        "strengths", "weaknesses", "style_of_play", "whoscored_team_id", "team_name",
        "league_code", "league_name"
    ]
    with open(PLAYERS_DETAILED_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames_p)
        writer.writeheader()
        for p in detailed_players:
            row = dict(p)
            row["strengths"] = json.dumps(p.get("strengths", []), ensure_ascii=False)
            row["weaknesses"] = json.dumps(p.get("weaknesses", []), ensure_ascii=False)
            row["style_of_play"] = json.dumps(p.get("style_of_play", []), ensure_ascii=False)
            writer.writerow(row)

    # 2. Estatísticas Históricas de Temporada (JSON & CSV)
    with open(SEASON_STATS_JSON, "w", encoding="utf-8") as f:
        json.dump(season_stats, f, ensure_ascii=False, indent=2)

    fieldnames_s = [
        "player_id", "season", "team", "competition", "matches", "minutes",
        "goals", "assists", "motm", "rating", "through_balls_per_game",
        "dispossessed_per_game", "unsuccessful_touches_per_game"
    ]
    with open(SEASON_STATS_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames_s)
        writer.writeheader()
        for s in season_stats:
            writer.writerow(s)


def main():
    if not os.path.exists(INPUT_PLAYERS_JSON):
        print(f"[!] Erro: Arquivo {INPUT_PLAYERS_JSON} não encontrado!")
        sys.exit(1)

    with open(INPUT_PLAYERS_JSON, "r", encoding="utf-8") as f:
        raw_players = json.load(f)

    # Garante lista única de jogadores por whoscored_player_id
    players_by_id = {}
    for p in raw_players:
        pid = p.get("whoscored_player_id")
        if pid and pid not in players_by_id:
            players_by_id[pid] = p

    all_players = list(players_by_id.values())
    total = len(all_players)
    print(f"[*] Total de {total} jogadores brasileiros únicos carregados para coleta detalhada.")

    # Carrega checkpoint se existir
    processed_ids = set()
    detailed_players = []
    all_season_stats = []

    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                chk = json.load(f)
                processed_ids = set(chk.get("processed_player_ids", []))
                detailed_players = chk.get("players", [])
                all_season_stats = chk.get("season_stats", [])
                print(f"[i] Checkpoint recuperado: {len(processed_ids)} jogadores já processados.")
        except Exception as e:
            print(f"[!] Erro ao ler checkpoint: {e}")

    driver = Driver(uc=True, headless=True)
    count = len(processed_ids)

    try:
        for idx, p in enumerate(all_players, 1):
            p_id = p["whoscored_player_id"]
            if p_id in processed_ids:
                continue

            name = p.get("name")
            show_url = p.get("player_url")
            history_url = show_url.replace("/show/", "/history/")

            print(f"[{idx}/{total}] Coletando: {name} (ID: {p_id})...")
            try:
                # 1. Página Show (Perfil + Características)
                prof, chars = parse_show_page(driver, show_url)

                # 2. Página History (Temporadas + Exclusividades Opção 2)
                season_stats = parse_history_page(driver, history_url, p_id)

                merged_player = {
                    "whoscored_player_id": p_id,
                    "name": prof.get("name") or name,
                    "full_name": prof.get("full_name"),
                    "player_url": show_url,
                    "current_team": prof.get("current_team") or p.get("team_name"),
                    "shirt_number": prof.get("shirt_number"),
                    "age": prof.get("age") or p.get("age"),
                    "birth_date": prof.get("birth_date"),
                    "height": prof.get("height"),
                    "nationality": prof.get("nationality") or "Brasil",
                    "position": prof.get("position") or p.get("position"),
                    "strengths": chars.get("strengths", []),
                    "weaknesses": chars.get("weaknesses", []),
                    "style_of_play": chars.get("style_of_play", []),
                    "whoscored_team_id": p.get("whoscored_team_id"),
                    "team_name": p.get("team_name"),
                    "league_code": p.get("league_code"),
                    "league_name": p.get("league_name"),
                }

                detailed_players.append(merged_player)
                all_season_stats.extend(season_stats)
                processed_ids.add(p_id)
                count += 1

                print(f"    -> Fortes: {len(chars['strengths'])} | Fracos: {len(chars['weaknesses'])} | Estilos: {len(chars['style_of_play'])} | Histórico: {len(season_stats)} temporadas")

            except Exception as ex:
                print(f"    [!] Erro ao processar jogador {name}: {ex}")

            # Checkpoint a cada 5 jogadores
            if count % 5 == 0:
                save_checkpoint(processed_ids, detailed_players, all_season_stats)
                export_data(detailed_players, all_season_stats)

        # Salva final
        save_checkpoint(processed_ids, detailed_players, all_season_stats)
        export_data(detailed_players, all_season_stats)
        print("\n[V] Coleta detalhada do WhoScored finalizada com sucesso!")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
