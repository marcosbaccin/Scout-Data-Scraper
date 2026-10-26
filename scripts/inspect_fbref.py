import os
import sqlite3
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scout.db")

def inspect_fbref_profile(player_name):
    conn = sqlite3.connect(DB_PATH)
    
    # 1. Busca os metadados na tabela de dimensão
    player_query = f"SELECT * FROM fbref_players WHERE name LIKE '%{player_name}%'"
    player_df = pd.read_sql(player_query, conn)
    
    if player_df.empty:
        print(f"[!] Jogador '{player_name}' não encontrado no FBref.")
        conn.close()
        return

    # Se houver mais de um, pega o primeiro (ex: múltiplos "Pedro")
    p_id = player_df.iloc[0]['id']
    p_name = player_df.iloc[0]['name']
    p_pos = player_df.iloc[0]['primary_position']
    p_foot = player_df.iloc[0]['footed']
    p_height = player_df.iloc[0]['height']
    p_weight = player_df.iloc[0]['weight']

    print("=" * 100)
    print(f" DOSSIÊ FBREF: {p_name} (ID Interno: {p_id})")
    print("=" * 100)
    print(f" Posição Principal : {p_pos}")
    print(f" Pé Preferencial   : {p_foot if p_foot else 'N/A'}")
    print(f" Físico            : {p_height}cm / {p_weight}kg")
    
    # 2. Direciona a busca para a tabela correta dependendo se é Goleiro ou Linha
    if p_pos == 'GK':
        stats_query = f"""
        SELECT season, comp, squad, is_national_team, matches_completed, subs_in, subs_unused,
               team_ppm, team_goals_on, team_goals_against_on, team_on_off,
               shots_on_target_against, wins, draws, losses, pens_allowed, pens_missed_gk
        FROM fbref_keeper_stats
        WHERE player_id = {p_id}
        ORDER BY season DESC
        """
    else:
        stats_query = f"""
        SELECT season, comp, squad, is_national_team, matches_completed, subs_in, subs_unused,
               team_ppm, team_goals_on, team_goals_against_on, team_on_off
        FROM fbref_outfield_stats
        WHERE player_id = {p_id}
        ORDER BY season DESC
        """
    
    stats_df = pd.read_sql(stats_query, conn)
    conn.close()

    print(f"\n Histórico de Desempenho FBref ({len(stats_df)} registros de competições/temporadas):")
    print("-" * 100)
    if not stats_df.empty:
        print(stats_df.to_string(index=False))
    else:
        print("  [!] Nenhuma estatística registrada na tabela de fatos para este jogador.")
    print("=" * 100 + "\n")

if __name__ == "__main__":
    inspect_fbref_profile("Bruno Henrique")
    inspect_fbref_profile("Hugo Souza")