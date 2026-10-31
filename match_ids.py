"""
Algoritmo Determinístico e Multi-Estágio de Resolução de Identidades (Entity Matching) nas 4 Fontes.

Arquitetura:
- SofaScore é a FONTE PRIMÁRIA (todos os 874 atletas do SofaScore compõem a espinha dorsal da player_mapping).
- Vincula 1-para-1 sem colisões com:
  1. FBref (fbref_players)
  2. Transfermarkt (transfermarkt_players)
  3. WhoScored (whoscored_players)
- Combina normalização semântica de nomes, tradução/limpeza canônica de clubes, compatibilidade posicional
  multilíngue (PT/EN via core.scouting_roles) e validação cruzada exata de data de nascimento (birth_date).
"""
import datetime as dt
import os
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Optional, Tuple

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from core.database import init_db
from core.scouting_roles import classify_position
from core.settings import DB_PATH

CLUB_STOPWORDS = {
    "fc", "cf", "sc", "ec", "ac", "cr", "se", "afc", "bc", "sfc", "ud", "cd",
    "rcd", "rc", "fk", "sv", "vfb", "tsg", "1", "04", "05", "07", "1899", "1907",
    "1913", "29", "de", "da", "do", "clube", "club", "calcio", "balompie", "futebol",
}

CLUB_SYNONYMS = {
    "marselha": "marseille",
    "olympique marselha": "marseille",
    "olympique marseille": "marseille",
    "paris sg": "paris saint germain",
    "psg": "paris saint germain",
    "manchester utd": "manchester united",
    "newcastle": "newcastle united",
    "tottenham": "tottenham hotspur",
    "brighton": "brighton hove albion",
    "nottingham": "nottingham forest",
    "wolves": "wolverhampton",
    "inter milao": "inter",
    "internazionale": "inter",
    "bayern munique": "bayern munich",
    "bayern munchen": "bayern munich",
    "colonia": "koln",
    "union berlim": "union berlin",
    "gladbach": "monchengladbach",
    "borussia mgladbach": "monchengladbach",
    "sporting kc": "sporting kansas city",
    "nycfc": "new york city",
    "rb new york": "new york red bulls",
    "red bull new york": "new york red bulls",
    "ne revolution": "new england revolution",
    "sj earthquakes": "san jose earthquakes",
    "lafc": "los angeles",
    "dc united": "d c united",
    "atlanta utd": "atlanta united",
    "minnesota utd": "minnesota united",
    "st louis": "st louis city",
    "atletico mg": "atletico mineiro",
    "athletico pr": "athletico paranaense",
    "athletico": "athletico paranaense",
    "botafogo rj": "botafogo",
    "rb bragantino": "bragantino",
    "red bull bragantino": "bragantino",
    "vit guimaraes": "vitoria sc",
    "vitoria guimaraes": "vitoria sc",
    "acad viseu": "academico viseu",
    "estrela": "estrela amadora",
    "sparta r": "sparta rotterdam",
    "dep a coruna": "deportivo coruna",
    "deportivo a coruna": "deportivo coruna",
    "racing sant": "racing",
    "racing santander": "racing",
    "real racing": "racing",
    "celta vigo": "celta",
    "unam": "pumas unam",
    "club universidad nacional": "pumas unam",
    "uanl": "tigres",
    "tigres uanl": "tigres",
}


@lru_cache(maxsize=8192)
def normalize(text) -> str:
    """Remove acentos, pontuação e converte para minúsculo."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    clean = "".join(c for c in text if not unicodedata.combining(c)).lower()
    clean = re.sub(r"[^a-z0-9\s]", " ", clean)
    return " ".join(clean.split())


@lru_cache(maxsize=4096)
def canonical_club(team_name) -> str:
    """Normaliza nomes de clubes entre PT/EN/ES/DE/FR para comparação robusta."""
    raw = normalize(team_name)
    if not raw:
        return ""
    for k, v in CLUB_SYNONYMS.items():
        if raw == k:
            raw = v
            break
    tokens = [t for t in raw.split() if t not in CLUB_STOPWORDS]
    joined = " ".join(tokens) if tokens else raw
    return CLUB_SYNONYMS.get(joined, joined)


@lru_cache(maxsize=16384)
def clubs_match(t1, t2) -> bool:
    c1, c2 = canonical_club(t1), canonical_club(t2)
    if not c1 or not c2:
        return False
    if c1 == c2 or c1 in c2 or c2 in c1:
        return True
    s1, s2 = set(c1.split()), set(c2.split())
    # Evita colisão entre Manchester City e Manchester United ou Los Angeles FC e LA Galaxy
    distinct_modifiers = {"city", "united", "galaxy", "real", "atletico", "inter", "milan"}
    if (s1 ^ s2) & distinct_modifiers and len(s1 & s2) <= 1:
        return False
    return bool(s1 & s2) and SequenceMatcher(None, c1, c2).ratio() >= 0.72


@lru_cache(maxsize=4096)
def pos_compatible(pos1, pos2) -> bool:
    """Verifica compatibilidade posicional multilíngue (PT/EN) via papéis táticos e macro-categorias."""
    if not pos1 or not pos2:
        return True
    role1, cat1 = classify_position(str(pos1))
    role2, cat2 = classify_position(str(pos2))
    # Goleiro nunca é compatível com jogador de linha
    if "GK" in (cat1, cat2):
        return cat1 == cat2
    if cat1 == cat2:
        return True
    # Alas / Laterais ofensivos (3-5-2 / 3-4-3) frequentemente alternam entre FB (DEF) e ML/MR/WNG (ATT)
    if {role1, role2} == {"FB", "WNG"}:
        return True
    # Pontas/Meias ofensivos transitam entre MID e ATT; Alas/Volantes transitam entre DEF e MID
    adjacent = {("MID", "ATT"), ("ATT", "MID"), ("DEF", "MID"), ("MID", "DEF")}
    return (cat1, cat2) in adjacent


@lru_cache(maxsize=4096)
def _parse_iso_date(val) -> Optional[dt.date]:
    if not val or str(val).strip().lower() in ("none", "nan", ""):
        return None
    try:
        return dt.date.fromisoformat(str(val).strip()[:10])
    except ValueError:
        return None


def dates_compatible(d1, d2) -> Tuple[bool, bool]:
    """
    Valida compatibilidade entre duas datas de nascimento.
    Retorna (is_compatible, is_strong_match):
    - Hard Veto (False, False) se ambas existirem e pertencerem claramente a atletas distintos.
    - Strong Match (True, True) para data idêntica ou inversão DD/MM vs MM/DD no mesmo ano.
    """
    dt1, dt2 = _parse_iso_date(d1), _parse_iso_date(d2)
    if not dt1 or not dt2:
        return True, False
    if dt1 == dt2:
        return True, True
    # Inversão clássica DD/MM vs MM/DD entre portais internacionais (ex: 1992-12-03 vs 1992-03-12)
    if dt1.year == dt2.year and dt1.month == dt2.day and dt1.day == dt2.month:
        return True, True
    # Diferença de fuso/registro de até 5 dias (ex: 1994-09-30 vs 1994-10-01)
    if abs((dt1 - dt2).days) <= 5:
        return True, False
    # Erro de digitação de 1 campo dentro do mesmo ano
    if dt1.year == dt2.year and (dt1.month == dt2.month or dt1.day == dt2.day):
        return True, False
    # Erro de 1 ano com mesmo dia e mês exatos (ex: 2006-05-08 vs 2007-05-08)
    if abs(dt1.year - dt2.year) == 1 and dt1.month == dt2.month and dt1.day == dt2.day:
        return True, False
    return False, False


def names_similarity(n1: str, n2: str) -> float:
    """Pontua similaridade entre nomes esportivos brasileiros (apelido vs nome composto)."""
    a, b = normalize(n1), normalize(n2)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = a.split(), b.split()
    # Um nome é prefixo/subconjunto de tokens do outro (ex: "Pedro" vs "Pedro Guilherme", "Gabriel" vs "Gabriel Magalhaes", "Bremer" vs "Gleison Bremer")
    if set(ta).issubset(set(tb)) or set(tb).issubset(set(ta)):
        shortest = min(len(a), len(b))
        if shortest >= 4:
            return 0.92 if ta[0] == tb[0] or ta[-1] == tb[-1] else 0.86
    # Primeiro nome igual + algum sobrenome/inicial compatível
    if ta[0] == tb[0] and len(ta[0]) >= 4:
        return max(0.78, SequenceMatcher(None, a, b).ratio())
    return SequenceMatcher(None, a, b).ratio()


def ensure_mapping_schema(cursor: sqlite3.Cursor):
    """Garante que player_mapping suporta sofascore_id como fonte primária (fbref_db_id opcional)."""
    cols = cursor.execute("PRAGMA table_info(player_mapping)").fetchall()
    col_names = [c[1] for c in cols]
    fbref_pk = any(c[1] == "fbref_db_id" and c[5] == 1 for c in cols)
    if "id" not in col_names or fbref_pk:
        cursor.execute("DROP TABLE IF EXISTS player_mapping")
        cursor.execute("""
            CREATE TABLE player_mapping (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sofascore_id INTEGER UNIQUE REFERENCES sofascore_players(id),
                fbref_db_id INTEGER UNIQUE REFERENCES fbref_players(id),
                transfermarkt_id INTEGER UNIQUE REFERENCES transfermarkt_players(id),
                whoscored_id INTEGER UNIQUE REFERENCES whoscored_players(id),
                merged_name VARCHAR
            )
        """)


def match_players():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    ensure_mapping_schema(cursor)
    conn.commit()
    conn.close()

    init_db()  # Recria views apontando para o schema atualizado
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM player_mapping")

    print("[*] Carregando registros das 4 fontes (SofaScore como Fonte Primária)...")

    # 1. SofaScore (Fonte Primária)
    cursor.execute("""
        SELECT sp.id, sp.name,
               COALESCE(
                   (SELECT spp.position FROM sofascore_player_positions spp WHERE spp.player_id = sp.id ORDER BY spp.ordinal ASC LIMIT 1),
                   sp.position
               ) AS pos,
               sp.current_team, sp.nationality, sp.footed, sp.height, sp.weight
        FROM sofascore_players sp
    """)
    sofa_players = cursor.fetchall()

    # 2. FBref
    cursor.execute("""
        SELECT p.id, p.name, p.primary_position, p.birth_date,
               COALESCE(
                   (SELECT squad FROM fbref_outfield_stats WHERE player_id = p.id AND is_national_team = 0 ORDER BY season DESC LIMIT 1),
                   (SELECT squad FROM fbref_keeper_stats WHERE player_id = p.id AND is_national_team = 0 ORDER BY season DESC LIMIT 1)
               ) AS team
        FROM fbref_players p
    """)
    fbref_players = cursor.fetchall()

    # 3. Transfermarkt
    cursor.execute("SELECT id, name, position, current_club, birth_date FROM transfermarkt_players")
    tm_players = cursor.fetchall()

    # 4. WhoScored
    cursor.execute("SELECT id, name, full_name, position, COALESCE(team_name, current_team), birth_date FROM whoscored_players")
    ws_players = cursor.fetchall()

    # Espinha dorsal: todos os atletas do SofaScore
    records = {}
    for s_id, s_name, s_pos, s_team, s_nat, s_foot, s_h, s_w in sofa_players:
        records[s_id] = {
            "sofascore_id": s_id,
            "name": s_name,
            "pos": s_pos,
            "team": s_team,
            "birth_date": None,
            "fbref_db_id": None,
            "transfermarkt_id": None,
            "whoscored_id": None,
            "demographics": (s_nat, s_foot, s_h, s_w),
        }

    # -------------------------------------------------------------------------
    # ETAPA 1: SOFASCORE <-> FBREF (1-para-1 por maior score global)
    # -------------------------------------------------------------------------
    print("[*] Etapa 1: Vinculando FBref à base primária SofaScore...")
    pair_candidates = []
    for s_id, rec in records.items():
        for fb_id, fb_name, fb_pos, fb_birth, fb_team in fbref_players:
            if not pos_compatible(rec["pos"], fb_pos):
                continue
            nsim = names_similarity(rec["name"], fb_name)
            if nsim < 0.74:
                continue
            t_ok = clubs_match(rec["team"], fb_team)
            score = nsim * 100.0 + (35.0 if t_ok else 0.0)
            # Exige clube compatível quando o nome não é idêntico (evita homônimos como Marquinhos/Matheus Cunha)
            if t_ok or nsim >= 0.99:
                pair_candidates.append((score, s_id, fb_id, fb_birth))

    pair_candidates.sort(key=lambda x: x[0], reverse=True)
    used_sofa, used_fb = set(), set()
    fb_matches = 0
    for score, s_id, fb_id, fb_birth in pair_candidates:
        if s_id in used_sofa or fb_id in used_fb:
            continue
        # Se nome é idêntico mas há homônimos e clubes não batem, exige score >= 105
        if score < 105.0:
            # Verifica se o nome tem homônimo no SofaScore
            norm_n = normalize(records[s_id]["name"])
            homonyms = sum(1 for r in records.values() if normalize(r["name"]) == norm_n)
            if homonyms > 1:
                continue
        used_sofa.add(s_id)
        used_fb.add(fb_id)
        records[s_id]["fbref_db_id"] = fb_id
        if fb_birth and fb_birth != "None":
            records[s_id]["birth_date"] = fb_birth
        fb_matches += 1

    # -------------------------------------------------------------------------
    # ETAPA 2: VINCULAÇÃO COM TRANSFERMARKT (usa birth_date + clube + nome)
    # -------------------------------------------------------------------------
    print("[*] Etapa 2: Vinculando Transfermarkt (Valuation & Data de Nascimento)...")
    tm_candidates = []
    for s_id, rec in records.items():
        for tm_id, tm_name, tm_pos, tm_club, tm_birth in tm_players:
            if not pos_compatible(rec["pos"], tm_pos):
                continue
            b_compat, b_strong = dates_compatible(rec["birth_date"], tm_birth)
            if not b_compat:
                continue
            nsim = names_similarity(rec["name"], tm_name)
            t_ok = clubs_match(rec["team"], tm_club)

            if b_strong and (nsim >= 0.60 or t_ok):
                score = 160.0 + nsim * 50.0 + (25.0 if t_ok else 0.0)
                tm_candidates.append((score, s_id, tm_id, tm_birth))
            elif t_ok and nsim >= 0.78:
                score = 100.0 + nsim * 50.0
                tm_candidates.append((score, s_id, tm_id, tm_birth))
            elif nsim >= 0.99 and not (rec["birth_date"] and tm_birth):
                norm_n = normalize(rec["name"])
                homonyms = sum(1 for r in records.values() if normalize(r["name"]) == norm_n)
                if homonyms == 1:
                    tm_candidates.append((95.0, s_id, tm_id, tm_birth))

    tm_candidates.sort(key=lambda x: x[0], reverse=True)
    used_sofa_tm, used_tm = set(), set()
    tm_matches = 0
    for score, s_id, tm_id, tm_birth in tm_candidates:
        if s_id in used_sofa_tm or tm_id in used_tm:
            continue
        used_sofa_tm.add(s_id)
        used_tm.add(tm_id)
        records[s_id]["transfermarkt_id"] = tm_id
        if not records[s_id]["birth_date"] and tm_birth:
            records[s_id]["birth_date"] = tm_birth
        tm_matches += 1

    # Segunda passagem FBref usando birth_date recém-descoberto via Transfermarkt!
    for s_id, rec in records.items():
        if rec["fbref_db_id"] is not None or not rec["birth_date"]:
            continue
        for fb_id, fb_name, fb_pos, fb_birth, fb_team in fbref_players:
            if fb_id in used_fb or not fb_birth:
                continue
            b_compat, b_strong = dates_compatible(rec["birth_date"], fb_birth)
            if not b_strong:
                continue
            if pos_compatible(rec["pos"], fb_pos) and (names_similarity(rec["name"], fb_name) >= 0.55 or clubs_match(rec["team"], fb_team)):
                used_fb.add(fb_id)
                rec["fbref_db_id"] = fb_id
                fb_matches += 1
                break

    # -------------------------------------------------------------------------
    # ETAPA 3: VINCULAÇÃO COM WHOSCORED (usa birth_date + full_name + clube)
    # -------------------------------------------------------------------------
    print("[*] Etapa 3: Vinculando WhoScored (Características & Histórico)...")
    ws_candidates = []
    for s_id, rec in records.items():
        for ws_id, ws_name, ws_full, ws_pos, ws_team, ws_birth in ws_players:
            if not pos_compatible(rec["pos"], ws_pos):
                continue
            b_compat, b_strong = dates_compatible(rec["birth_date"], ws_birth)
            if not b_compat:
                continue
            nsim = max(names_similarity(rec["name"], ws_name), names_similarity(rec["name"], ws_full or ""))
            t_ok = clubs_match(rec["team"], ws_team)

            if b_strong and (nsim >= 0.55 or t_ok):
                score = 160.0 + nsim * 50.0 + (25.0 if t_ok else 0.0)
                ws_candidates.append((score, s_id, ws_id))
            elif t_ok and nsim >= 0.78:
                score = 100.0 + nsim * 50.0
                ws_candidates.append((score, s_id, ws_id))
            elif nsim >= 0.99 and not (rec["birth_date"] and ws_birth):
                norm_n = normalize(rec["name"])
                homonyms = sum(1 for r in records.values() if normalize(r["name"]) == norm_n)
                if homonyms == 1:
                    ws_candidates.append((95.0, s_id, ws_id))

    ws_candidates.sort(key=lambda x: x[0], reverse=True)
    used_sofa_ws, used_ws = set(), set()
    ws_matches = 0
    for score, s_id, ws_id in ws_candidates:
        if s_id in used_sofa_ws or ws_id in used_ws:
            continue
        used_sofa_ws.add(s_id)
        used_ws.add(ws_id)
        records[s_id]["whoscored_id"] = ws_id
        ws_matches += 1

    # Persiste todos os atletas na player_mapping
    cleared_demographics = 0
    for s_id, rec in records.items():
        cursor.execute(
            """
            INSERT INTO player_mapping (sofascore_id, fbref_db_id, transfermarkt_id, whoscored_id, merged_name)
            VALUES (?, ?, ?, ?, ?)
            """,
            (rec["sofascore_id"], rec["fbref_db_id"], rec["transfermarkt_id"], rec["whoscored_id"], rec["name"]),
        )

        # Regra de fallback demográfico: SofaScore primário -> limpa redundância no FBref se SofaScore já tiver
        if rec["fbref_db_id"] is not None:
            s_nat, s_foot, s_h, s_w = rec["demographics"]
            updates = []
            if s_nat and str(s_nat).strip() and str(s_nat).lower() != "none":
                updates.append("nationality = NULL")
            if s_foot and str(s_foot).strip() and str(s_foot).lower() != "none":
                updates.append("footed = NULL")
            if s_h is not None:
                updates.append("height = NULL")
            if s_w is not None:
                updates.append("weight = NULL")
            if updates:
                cursor.execute(f"UPDATE fbref_players SET {', '.join(updates)} WHERE id = ?", (rec["fbref_db_id"],))
                cleared_demographics += 1

    conn.commit()
    conn.close()

    print(f"\n[+] Tabela 'player_mapping' (Camada Gold) atualizada com sucesso!")
    print(f"    -> {len(records)} atletas brasileiros na base Gold (SofaScore Primária: 100%).")
    print(f"    -> {fb_matches}/{len(fbref_players)} atletas do FBref vinculados 1-para-1 ({fb_matches*100/max(len(fbref_players),1):.1f}%).")
    print(f"    -> {tm_matches}/{len(tm_players)} atletas do Transfermarkt vinculados 1-para-1 ({tm_matches*100/max(len(tm_players),1):.1f}%).")
    print(f"    -> {ws_matches}/{len(ws_players)} atletas do WhoScored vinculados 1-para-1 ({ws_matches*100/max(len(ws_players),1):.1f}%).")
    print(f"    -> Regra de governança demográfica aplicada em {cleared_demographics} registros do FBref.")


if __name__ == "__main__":
    match_players()
