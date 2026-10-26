import os
import sqlite3
import sys
import unicodedata
from collections import defaultdict

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from core.database import init_db
from core.settings import DB_PATH


def normalize(text):
    """Remove acentos, converte para minúsculo e tira espaços sobrando."""
    if not text:
        return ""
    text = unicodedata.normalize('NFKD', str(text))
    return "".join([c for c in text if not unicodedata.combining(c)]).lower().strip()


def pos_compatible(fb_pos, s_pos):
    """Verifica se as posições do FBref e SofaScore são compatíveis usando conjuntos."""
    if not fb_pos or not s_pos:
        return True
    fb_pos, s_pos = str(fb_pos).upper(), str(s_pos).upper()
    
    fb_cats = set()
    if 'GK' in fb_pos or fb_pos == 'G':
        fb_cats.add('GK')
    if 'DF' in fb_pos or 'CB' in fb_pos or 'LB' in fb_pos or 'RB' in fb_pos or 'FB' in fb_pos or fb_pos == 'D':
        fb_cats.add('DEF')
    if 'MF' in fb_pos or 'DM' in fb_pos or 'CM' in fb_pos or 'AM' in fb_pos or fb_pos == 'M':
        fb_cats.add('MID')
    if 'FW' in fb_pos or 'ST' in fb_pos or 'CF' in fb_pos or 'LW' in fb_pos or 'RW' in fb_pos or fb_pos == 'F':
        fb_cats.add('FWD')

    s_cats = set()
    if 'GK' in s_pos or s_pos == 'G':
        s_cats.add('GK')
    if 'DF' in s_pos or 'CB' in s_pos or 'LB' in s_pos or 'RB' in s_pos or 'FB' in s_pos or s_pos == 'D':
        s_cats.add('DEF')
    if 'MF' in s_pos or 'DM' in s_pos or 'CM' in s_pos or 'AM' in s_pos or s_pos == 'M':
        s_cats.add('MID')
    if 'FW' in s_pos or 'ST' in s_pos or 'CF' in s_pos or 'LW' in s_pos or 'RW' in s_pos or s_pos == 'F':
        s_cats.add('FWD')

    return bool(fb_cats & s_cats)


def match_players():
    init_db()  # garante tabelas (inclui player_mapping com constraint única) e views
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Limpa mapeamentos antigos se o script for rodado novamente
    cursor.execute('DELETE FROM player_mapping')

    print("[*] Lendo bases do FBref e Sofascore...")

    # Busca todos os jogadores do FBref com sua posição e o clube mais recente
    try:
        query_fbref = """
        SELECT p.id, p.name, p.primary_position,
               COALESCE(
                   (SELECT squad FROM fbref_outfield_stats WHERE player_id = p.id AND is_national_team = 0 ORDER BY season DESC LIMIT 1),
                   (SELECT squad FROM fbref_keeper_stats WHERE player_id = p.id AND is_national_team = 0 ORDER BY season DESC LIMIT 1)
               ) as team
        FROM fbref_players p
        """
        cursor.execute(query_fbref)
        fbref_players = cursor.fetchall()
    except sqlite3.OperationalError as e:
        print(f"[!] Erro ao acessar o banco do FBref: {e}")
        conn.close()
        return

    # Busca todos os jogadores do Sofascore
    try:
        cursor.execute("SELECT id, name, position, current_team, nationality, footed, height, weight FROM sofascore_players")
        sofascore_players = cursor.fetchall()
    except sqlite3.OperationalError as e:
        print(f"[!] Erro ao acessar a tabela do Sofascore: {e}")
        conn.close()
        return

    # Agrupa Sofascore por nome normalizado
    sofa_by_norm_name = defaultdict(list)
    sofa_player_dict = {}
    for row in sofascore_players:
        s_id, s_name, s_pos, s_team, s_nat, s_foot, s_h, s_w = row
        sofa_by_norm_name[normalize(s_name)].append(row)
        sofa_player_dict[s_id] = row

    matched_sofa_ids = set()
    matches = []

    print("[*] Executando algoritmo de cruzamento (Entity Resolution 1-para-1 com pontuação de candidatos)...")

    # Passagem 1: Match Exato do Nome Normalizado + Seleção do Melhor Candidato por Clube/Posição
    for fb_id, fb_name, fb_pos, fb_team in fbref_players:
        norm_fb = normalize(fb_name)
        candidates = sofa_by_norm_name.get(norm_fb, [])
        if not candidates:
            continue

        norm_fb_team = normalize(fb_team)

        best_cand = None
        best_score = -1

        for cand in candidates:
            if cand[0] in matched_sofa_ids:
                continue

            cand_team = normalize(cand[3])
            team_m = bool(norm_fb_team and cand_team and (norm_fb_team in cand_team or cand_team in norm_fb_team))
            pos_ok = pos_compatible(fb_pos, cand[2])

            score = 0
            if team_m and pos_ok:
                score = 30
            elif team_m:
                score = 20
            elif pos_ok and not norm_fb_team:
                score = 15
            elif pos_ok and len(candidates) == 1:
                score = 10
            elif pos_ok:
                score = 5

            if score > best_score:
                best_score = score
                best_cand = cand

        if best_cand and best_score >= 10:
            matched_sofa_ids.add(best_cand[0])
            matches.append((fb_id, best_cand[0], fb_name))

    # Passagem 2: Match Parcial com validação estrita de Clube E Posição
    already_matched_fb = {m[0] for m in matches}
    for fb_id, fb_name, fb_pos, fb_team in fbref_players:
        if fb_id in already_matched_fb:
            continue
        norm_fb = normalize(fb_name)
        norm_fb_team = normalize(fb_team)
        if not norm_fb_team:
            continue

        for s_id, s_name, s_pos, s_team, *_ in sofascore_players:
            if s_id in matched_sofa_ids:
                continue
            norm_s_name = normalize(s_name)
            norm_s_team = normalize(s_team)

            # Substring de nome com comprimento mínimo >= 5 para evitar falsos positivos
            name_match = (norm_fb in norm_s_name or norm_s_name in norm_fb) and len(min(norm_fb, norm_s_name, key=len)) >= 5
            team_match = (norm_fb_team in norm_s_team or norm_s_team in norm_fb_team) if norm_s_team else False
            pos_ok = pos_compatible(fb_pos, s_pos)

            if name_match and team_match and pos_ok:
                matched_sofa_ids.add(s_id)
                matches.append((fb_id, s_id, fb_name))
                break

    # Persiste os mapeamentos 1-para-1 na tabela player_mapping
    for fb_id, s_id, merged_name in matches:
        cursor.execute(
            'INSERT INTO player_mapping (fbref_db_id, sofascore_id, merged_name) VALUES (?, ?, ?)',
            (fb_id, s_id, merged_name)
        )

    # ---------------------------------------------------------------------------------
    # REGRA DE NEGÓCIO: nationality, footed, height, weight
    # Se o Sofascore já possui o dado coletado (não nulo/não vazio), o FBref NÃO persiste.
    # Se o Sofascore tiver null/None, o dado do FBref é mantido como fallback.
    # ---------------------------------------------------------------------------------
    cleared_demographics = 0
    for fb_id, s_id, _ in matches:
        s_row = sofa_player_dict.get(s_id)
        if not s_row:
            continue
        _, _, _, _, s_nat, s_foot, s_h, s_w = s_row

        updates = []
        params = []
        if s_nat and s_nat.strip() and s_nat.lower() != 'none':
            updates.append("nationality = NULL")
        if s_foot and s_foot.strip() and s_foot.lower() != 'none':
            updates.append("footed = NULL")
        if s_h is not None:
            updates.append("height = NULL")
        if s_w is not None:
            updates.append("weight = NULL")

        if updates:
            sql = f"UPDATE fbref_players SET {', '.join(updates)} WHERE id = ?"
            params.append(fb_id)
            cursor.execute(sql, tuple(params))
            cleared_demographics += 1

    # ---------------------------------------------------------------------------------
    # ETAPA 3: CRUZAMENTO COM TRANSFERMARKT (Valor de Mercado)
    # ---------------------------------------------------------------------------------
    print("[*] Cruzando com base de dados do Transfermarkt...")
    try:
        cursor.execute("SELECT id, name, position, current_club, birth_date FROM transfermarkt_players")
        tm_players = cursor.fetchall()
    except sqlite3.OperationalError:
        tm_players = []

    tm_by_norm_name = defaultdict(list)
    for p in tm_players:
        tm_by_norm_name[normalize(p[1])].append(p)

    matched_tm_ids = set()
    tm_matches = 0

    cursor.execute("""
        SELECT m.fbref_db_id, m.merged_name,
               fp.primary_position,
               sp.position, sp.current_team
        FROM player_mapping m
        LEFT JOIN fbref_players fp ON fp.id = m.fbref_db_id
        LEFT JOIN sofascore_players sp ON sp.id = m.sofascore_id
    """)
    current_mappings = cursor.fetchall()

    for fb_id, m_name, fb_pos, sofa_pos, sofa_team in current_mappings:
        norm_name = normalize(m_name)
        candidates = tm_by_norm_name.get(norm_name, [])
        if not candidates:
            continue

        best_cand = None
        best_score = -1
        norm_sofa_team = normalize(sofa_team)

        for cand in candidates:
            if cand[0] in matched_tm_ids:
                continue
            c_id, c_name, c_pos, c_club, c_birth = cand
            norm_club = normalize(c_club)

            team_m = bool(norm_sofa_team and norm_club and (norm_sofa_team in norm_club or norm_club in norm_sofa_team))
            pos_ok = pos_compatible(fb_pos or sofa_pos, c_pos)

            score = 0
            if team_m and pos_ok:
                score = 30
            elif team_m:
                score = 20
            elif pos_ok and len(candidates) == 1:
                score = 10
            elif pos_ok:
                score = 5

            if score > best_score:
                best_score = score
                best_cand = cand

        if best_cand and best_score >= 10:
            matched_tm_ids.add(best_cand[0])
            cursor.execute(
                "UPDATE player_mapping SET transfermarkt_id = ? WHERE fbref_db_id = ?",
                (best_cand[0], fb_id)
            )
            tm_matches += 1

    # Pass 2: Match Parcial com validação estrita de Clube e Posição
    for fb_id, m_name, fb_pos, sofa_pos, sofa_team in current_mappings:
        cursor.execute("SELECT transfermarkt_id FROM player_mapping WHERE fbref_db_id = ?", (fb_id,))
        curr = cursor.fetchone()
        if curr and curr[0] is not None:
            continue

        norm_name = normalize(m_name)
        norm_sofa_team = normalize(sofa_team)
        if not norm_sofa_team:
            continue

        for cand in tm_players:
            if cand[0] in matched_tm_ids:
                continue
            c_id, c_name, c_pos, c_club, _ = cand
            norm_c_name = normalize(c_name)
            norm_c_club = normalize(c_club)

            name_m = (norm_name in norm_c_name or norm_c_name in norm_name) and len(min(norm_name, norm_c_name, key=len)) >= 5
            team_m = (norm_sofa_team in norm_c_club or norm_c_club in norm_sofa_team)
            pos_ok = pos_compatible(fb_pos or sofa_pos, c_pos)

            if name_m and team_m and pos_ok:
                matched_tm_ids.add(c_id)
                cursor.execute(
                    "UPDATE player_mapping SET transfermarkt_id = ? WHERE fbref_db_id = ?",
                    (c_id, fb_id)
                )
                tm_matches += 1
                break

    # =========================================================================
    # Etapa 3: Vincular Jogadores do WhoScored à Tabela Gold
    # =========================================================================
    print("[*] Vinculando jogadores do WhoScored à Tabela Gold...")
    cursor.execute("SELECT id, name, position, team_name, age FROM whoscored_players")
    ws_players = cursor.fetchall()

    ws_by_norm_name = defaultdict(list)
    for p in ws_players:
        ws_by_norm_name[normalize(p[1])].append(p)

    matched_ws_ids = set()
    ws_matches = 0

    # Pass 1: Nome exato normalizado
    for fb_id, m_name, fb_pos, sofa_pos, sofa_team in current_mappings:
        norm_name = normalize(m_name)
        cands = ws_by_norm_name.get(norm_name, [])
        if not cands:
            continue

        norm_team = normalize(sofa_team)
        best_cand = None
        for cand in cands:
            if cand[0] in matched_ws_ids:
                continue
            c_id, c_name, c_pos, c_team, c_age = cand
            norm_c_team = normalize(c_team)
            team_m = bool(norm_team and norm_c_team and (norm_team in norm_c_team or norm_c_team in norm_team))
            if team_m or len(cands) == 1:
                best_cand = cand
                break

        if best_cand:
            matched_ws_ids.add(best_cand[0])
            cursor.execute(
                "UPDATE player_mapping SET whoscored_id = ? WHERE fbref_db_id = ?",
                (best_cand[0], fb_id)
            )
            ws_matches += 1

    # Pass 2: Nome parcial + Clube
    for fb_id, m_name, fb_pos, sofa_pos, sofa_team in current_mappings:
        cursor.execute("SELECT whoscored_id FROM player_mapping WHERE fbref_db_id = ?", (fb_id,))
        curr = cursor.fetchone()
        if curr and curr[0] is not None:
            continue

        norm_name = normalize(m_name)
        norm_team = normalize(sofa_team)
        if not norm_team:
            continue

        for cand in ws_players:
            if cand[0] in matched_ws_ids:
                continue
            c_id, c_name, c_pos, c_team, c_age = cand
            norm_c_name = normalize(c_name)
            norm_c_team = normalize(c_team)

            name_m = (norm_name in norm_c_name or norm_c_name in norm_name) and len(min(norm_name, norm_c_name, key=len)) >= 5
            team_m = (norm_team in norm_c_team or norm_c_team in norm_team)
            if name_m and team_m:
                matched_ws_ids.add(c_id)
                cursor.execute(
                    "UPDATE player_mapping SET whoscored_id = ? WHERE fbref_db_id = ?",
                    (c_id, fb_id)
                )
                ws_matches += 1
                break

    conn.commit()
    conn.close()

    total_fbref = len(fbref_players)
    unmatched = total_fbref - len(matches)
    print(f"\n[+] Tabela 'player_mapping' atualizada com sucesso!")
    print(f"    -> {len(matches)} jogadores FBref <-> Sofascore mapeados 1-para-1 sem colisões.")
    print(f"    -> {tm_matches} jogadores do Transfermarkt vinculados à Tabela Gold.")
    print(f"    -> {ws_matches} jogadores do WhoScored vinculados à Tabela Gold.")
    print(f"    -> {unmatched} jogadores do FBref não encontrados no Sofascore.")
    print(f"    -> Regra de fallback demográfico aplicada: {cleared_demographics} jogadores processados.")


if __name__ == "__main__":
    match_players()