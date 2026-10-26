import os
import sqlite3
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scout.db")

def inspect_player_profile(player_name):
    conn = sqlite3.connect(DB_PATH)
    
    # 1. Pega os dados cadastrais e características
    player_query = f"SELECT * FROM sofascore_players WHERE name LIKE '%{player_name}%'"
    player_df = pd.read_sql(player_query, conn)
    
    if player_df.empty:
        print(f"[!] Jogador '{player_name}' não encontrado no Sofascore.")
        conn.close()
        return

    p_id = player_df.iloc[0]['id']
    p_name = player_df.iloc[0]['name']
    p_pos = player_df.iloc[0]['position']
    p_team = player_df.iloc[0]['current_team']
    p_league = player_df.iloc[0]['current_league']
    chars_df = pd.read_sql(
        f"SELECT polarity, characteristic_name, rank FROM v_sofascore_characteristics_named WHERE player_id = {p_id} ORDER BY rank", conn)
    p_strengths = ", ".join(f"{r.characteristic_name} (rank {r.rank})" for r in chars_df[chars_df.polarity == 'positive'].itertuples())
    p_weaknesses = ", ".join(f"{r.characteristic_name} (rank {r.rank})" for r in chars_df[chars_df.polarity == 'negative'].itertuples())

    print("=" * 70)
    print(f" DOSSIÊ SOFASCORE: {p_name} (ID: {p_id})")
    print("=" * 70)
    print(f" Posição          : {p_pos}")
    print(f" Time Atual       : {p_team} ({p_league})")
    print(f" Pontos Fortes    : {p_strengths if p_strengths else 'N/A'}")
    print(f" Pontos Fracos    : {p_weaknesses if p_weaknesses else 'N/A'}")
    
    # 2. Pega todo o histórico de estatísticas armazenado (rating vem da view de métricas derivadas)
    stats_query = f"""
    SELECT season, competition, squad, minutes_played, rating, goals, assists, 
           shots_on_target, key_passes, successful_dribbles, 
           tackles, interceptions, ball_recovery, ground_duels_won, aerial_duels_won,
           expected_goals, expected_assists, saves, goals_conceded
    FROM v_sofascore_stats_derived
    WHERE player_id = {p_id}
    ORDER BY season DESC
    """
    stats_df = pd.read_sql(stats_query, conn)
    conn.close()

    print(f"\n Histórico de Desempenho ({len(stats_df)} registros de competições/temporadas):")
    print("-" * 70)
    if not stats_df.empty:
        print(stats_df.to_string(index=False))
    else:
        print("  [!] Nenhuma estatística de minutos registrada para este jogador.")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    inspect_player_profile("Bruno Henrique")
    inspect_player_profile("Hugo Souza")