from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import pandas as pd
import os

app = FastAPI(title="Scout Analytics API", version="1.0")

# Libera o acesso para o React/Vite consumir a API localmente
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Localiza o banco de dados na raiz do projeto
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scout.db')

def get_connection():
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail="Banco de dados não encontrado.")
    return sqlite3.connect(DB_PATH)

@app.get("/")
def read_root():
    return {"status": "online", "message": "Scout API operante."}

@app.get("/players")
def search_players(name: str = ""):
    """Busca jogadores pelo perfil unificado."""
    conn = get_connection()
    query = """
    SELECT profile_id as id, name, position, current_team, current_league, 
           nationality, footed, height, weight, fbref_id, sofascore_id
    FROM v_player_profiles 
    WHERE name LIKE ? 
    ORDER BY name 
    LIMIT 50
    """
    df = pd.read_sql(query, conn, params=(f'%{name}%',))
    conn.close()
    
    import json
    return json.loads(df.to_json(orient="records"))

@app.get("/metadata")
def get_metadata():
    """Retorna todas as temporadas e campeonatos únicos para preencher os filtros."""
    conn = get_connection()
    seasons = pd.read_sql("SELECT DISTINCT season FROM sofascore_stats WHERE season IS NOT NULL ORDER BY season DESC", conn)['season'].tolist()
    comps = pd.read_sql("SELECT DISTINCT competition FROM sofascore_stats WHERE competition IS NOT NULL ORDER BY competition ASC", conn)['competition'].tolist()
    conn.close()
    return {"seasons": seasons, "comps": comps}

@app.get("/analytics/{player_id}")
def get_player_radar(player_id: int, season: str = "", comp: str = "", min_minutes: int = 450):
    """Calcula P90 e Percentis usando o Sofascore como fonte primária."""
    conn = get_connection()
    
    where_clauses = []
    params = []
    
    if season:
        where_clauses.append("s.season = ?")
        params.append(season)
    if comp:
        where_clauses.append("s.competition = ?")
        params.append(comp)
        
    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    
    query = f"""
    SELECT 
        p.id as player_id, 
        p.name,
        MAX(s.squad) as squad,
        COALESCE(SUM(s.minutes_played), 0) as minutes,
        COALESCE(SUM(s.goals), 0) as goals,
        COALESCE(SUM(s.assists), 0) as assists,
        COALESCE(SUM(s.total_shots), 0) as shots,
        COALESCE(SUM(s.shots_on_target), 0) as shots_on_target,
        COALESCE(SUM(s.tackles), 0) as tackles,
        COALESCE(SUM(s.interceptions), 0) as interceptions
    FROM sofascore_stats s
    JOIN sofascore_players p ON p.id = s.player_id
    {where_sql}
    GROUP BY p.id, p.name
    HAVING SUM(s.minutes_played) >= ?
    """
    params.append(min_minutes)
    
    df = pd.read_sql(query, conn, params=tuple(params))
    conn.close()
    
    if df.empty:
        raise HTTPException(status_code=404, detail="Nenhum dado base encontrado com esses filtros.")
        
    metrics = ['goals', 'assists', 'shots', 'shots_on_target', 'tackles', 'interceptions']
    
    for col in metrics:
        df[f"{col}_p90"] = (df[col] / df['minutes']) * 90
        df[f"{col}_pct"] = df[f"{col}_p90"].rank(pct=True) * 100
        
    player_df = df[df['player_id'] == player_id]
    
    if player_df.empty:
        raise HTTPException(status_code=404, detail=f"Jogador não atingiu o mínimo de {min_minutes} minutos com estes filtros.")
        
    result = player_df.iloc[0]
    
    radar_data = []
    for col in metrics:
        radar_data.append({
            "metric": col.replace('_', ' ').title(),
            "raw": int(result[col]),
            "p90": round(float(result[f"{col}_p90"]), 2),
            "percentile": round(float(result[f"{col}_pct"]), 1)
        })
        
    return {
        "player_info": {
            "id": int(result['player_id']),
            "name": str(result['name']),
            "squad": str(result['squad']),
            "total_minutes": int(result['minutes'])
        },
        "radar": radar_data
    }
