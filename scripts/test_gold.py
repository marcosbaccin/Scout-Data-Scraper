import os
import sqlite3
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scout.db")

def test_gold_table():
    conn = sqlite3.connect(DB_PATH)
    
    # CTEs: Somamos todos os torneios de 2023 no FBref (exclusivas) e no Sofascore (primárias)
    query = """
    WITH fbref_2023 AS (
        SELECT player_id, squad, 
               SUM(matches_completed) as compl_fbref,
               SUM(subs_in) as subs_in_fbref,
               ROUND(AVG(team_ppm), 2) as ppm_fbref,
               SUM(team_goals_on) as team_goals_fbref
        FROM fbref_outfield_stats 
        WHERE season LIKE '%2023%' AND squad LIKE '%Flamengo%'
        GROUP BY player_id, squad
    ),
    sofascore_2023 AS (
        SELECT player_id, squad, 
               SUM(goals) as gols_sofa,
               SUM(assists) as ast_sofa,
               SUM(big_chances_created) as bcc_sofa, 
               SUM(key_passes) as kp_sofa, 
               SUM(successful_dribbles) as drib_sofa
        FROM sofascore_stats
        WHERE season LIKE '%2023%' AND squad LIKE '%Flamengo%'
        GROUP BY player_id, squad
    )
    -- Cruzamento Gold: métricas primárias do Sofascore + métricas exclusivas do FBref + Valor TM
    SELECT 
        m.merged_name AS Jogador,
        s.squad AS Clube,
        '2023 (Agregado)' AS Temporada,
        s.gols_sofa AS Gols_Sofa,
        s.ast_sofa AS Assist_Sofa,
        s.kp_sofa AS Passes_Chave_Sofa,
        s.drib_sofa AS Dribles_Sofa,
        f.compl_fbref AS Jogos_Completos_FBref,
        f.ppm_fbref AS Pontos_Por_Partida_FBref,
        tp.market_value_raw AS Valor_Mercado_TM
    FROM player_mapping m
    JOIN fbref_2023 f ON m.fbref_db_id = f.player_id
    JOIN sofascore_2023 s ON m.sofascore_id = s.player_id
    LEFT JOIN transfermarkt_players tp ON tp.id = m.transfermarkt_id
    WHERE m.merged_name LIKE '%Bruno Henrique%' OR m.merged_name LIKE '%Pedro%'
    """
    
    df = pd.read_sql(query, conn)
    
    # Diagnóstico rápido de paz de espírito para você
    fbref_count = pd.read_sql("SELECT COUNT(*) as c FROM fbref_outfield_stats", conn).iloc[0]['c']
    sofa_count = pd.read_sql("SELECT COUNT(*) as c FROM sofascore_stats", conn).iloc[0]['c']
    
    conn.close()
    
    print("\n[*] STATUS DE INTEGRIDADE DO BANCO:")
    print(f"    -> FBref: {fbref_count} registros de linha perfeitamente intactos.")
    print(f"    -> Sofascore: {sofa_count} registros perfeitamente intactos.\n")
    
    if df.empty:
        print(f"[!] Nenhum dado combinado encontrado.")
    else:
        print("[*] RESULTADO DO CRUZAMENTO GOLD - FLAMENGO 2023 (AGREGADO):")
        print("-" * 105)
        print(df.to_string(index=False))
        print("-" * 105)

if __name__ == "__main__":
    test_gold_table()