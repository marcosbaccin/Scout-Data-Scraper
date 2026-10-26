import pandas as pd
import sqlite3
import os

def calculate_percentiles(db_path, player_name, target_season="2023"):
    if not os.path.exists(db_path):
        print(f"[!] Banco de dados '{db_path}' não encontrado.")
        return

    conn = sqlite3.connect(db_path)
    
    # ---------------------------------------------------------
    # RAIO-X: Verifica o que existe no banco (SofaScore como fonte primária)
    # ---------------------------------------------------------
    check_query = f"""
    SELECT p.name, s.season, s.competition, s.squad, s.minutes_played 
    FROM sofascore_players p
    JOIN sofascore_stats s ON p.id = s.player_id
    WHERE p.name LIKE '%{player_name}%'
    ORDER BY s.season DESC LIMIT 10
    """
    check_df = pd.read_sql(check_query, conn)
    
    if check_df.empty:
        print(f"[!] Falha: Nenhum jogador contendo '{player_name}' foi encontrado no Sofascore.")
        conn.close()
        return
        
    print(f"\n[*] RAIO-X: Registros encontrados para '{player_name}':")
    print("-" * 65)
    print(check_df.to_string(index=False))
    print("-" * 65)

    # ---------------------------------------------------------
    # MOTOR ANALÍTICO
    # ---------------------------------------------------------
    query = f"""
    SELECT p.name, s.* 
    FROM sofascore_stats s
    JOIN sofascore_players p ON p.id = s.player_id
    WHERE s.minutes_played >= 450 AND s.season LIKE '%{target_season}%'
    """
    df = pd.read_sql(query, conn)
    conn.close()
    
    if df.empty:
        print(f"\n[!] A query principal retornou vazia. Ninguém na temporada contendo '{target_season}' tem >= 450 min.")
        return
        
    metrics = [
        'goals', 'assists', 'total_shots', 'shots_on_target', 
        'tackles', 'interceptions', 'fouls', 'yellow_cards'
    ]
               
    for col in metrics:
        if col in df.columns:
            df[f"{col}_p90"] = (df[col] / df['minutes_played']) * 90
            df[f"{col}_pct"] = df[f"{col}_p90"].rank(pct=True) * 100
        
    # Filtra o alvo
    player_df = df[df['name'].str.contains(player_name, case=False, na=False)]
    
    if player_df.empty:
        print(f"\n[!] O jogador não passou no filtro analítico (verifique os minutos do Raio-X).")
        return
        
    print(f"\n[*] RELATÓRIO DE DESEMPENHO: {player_df.iloc[0]['name']} | Temporada: {target_season}")
    print("=" * 65)
    print(f"{'Métrica (P90)'.ljust(20)} | {'Valor Bruto'.ljust(12)} | {'Por 90'.ljust(10)} | Percentil")
    print("-" * 65)
    
    for col in metrics:
        if col in player_df.columns:
            val_raw = player_df.iloc[0][col]
            val_p90 = player_df.iloc[0][f"{col}_p90"]
            val_pct = player_df.iloc[0][f"{col}_pct"]
            print(f"{col.replace('_', ' ').title().ljust(20)} | {str(val_raw).ljust(12)} | {val_p90:<10.2f} | {val_pct:.1f}")

if __name__ == "__main__":
    calculate_percentiles("scout.db", "Pedro", "2023")