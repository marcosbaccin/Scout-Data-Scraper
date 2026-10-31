"""
⚽ Motor de Análise Estatística & Scouting (Analytics Engine)

Responsável pelo cálculo de métricas avançadas, Per 90 (P90), Percentis relativos
por grupo posicional e índice de similaridade entre atletas:
- Consulta a View Gold `v_player_gold_analytics`.
- Agrupa atletas por `scout_role` (ST, WNG, CM_AM, DM, FB, CB, GK) para cálculo justo de percentis.
- Gera dados prontos para visualização em Radar Charts e Tabelas Comparativas.
- Algoritmo de Similaridade de Atletas (Cosine / Euclidean Similarity em vetor de percentis).
"""
import argparse
from collections import OrderedDict
import os
import sqlite3
import sys
import threading
from typing import Dict, List, Optional, Any

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import numpy as np
import pandas as pd

# Permite importação dos módulos centrais
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from core.scouting_roles import classify_position
from core.seasons import season_year
from core.settings import DB_PATH


# Métricas fundamentais para o cálculo de P90
RAW_VOLUME_METRICS = [
    'goals', 'assists', 'goal_involvements', 'xg', 'xa', 'shots', 'shots_on_target',
    'key_passes', 'big_chances_created', 'accurate_passes', 'total_passes',
    'successful_dribbles', 'tackles', 'interceptions', 'ball_recovery',
    'ground_duels_won', 'aerial_duels_won', 'duels_won_total', 'fouls',
    'yellow_cards', 'red_cards', 'fbref_team_goals_on', 'fbref_team_goals_against_on',
    'fbref_team_goal_diff_on', 'fbref_matches_completed', 'fbref_subs_in',
    'ws_motm'
]

# Configuração de métricas ideais para o Radar por Função Tática
RADAR_METRICS_BY_ROLE = {
    'ST': [
        ('goals', 'Gols / 90', False),
        ('xg', 'xG / 90', False),
        ('shots_on_target', 'Chutes no Alvo / 90', False),
        ('key_passes', 'Passes Chave / 90', False),
        ('aerial_duels_won', 'Duelos Aéreos Ganhos / 90', False),
        ('successful_dribbles', 'Dribles Certos / 90', False),
        ('sofascore_rating', 'Rating Geral', False),
    ],
    'WNG': [
        ('successful_dribbles', 'Dribles Certos / 90', False),
        ('key_passes', 'Passes Chave / 90', False),
        ('xa', 'xA / 90', False),
        ('goals', 'Gols / 90', False),
        ('shots', 'Finalizações / 90', False),
        ('ws_through_balls_per_game', 'Bolas Enfiadas / Jogo', False),
        ('sofascore_rating', 'Rating Geral', False),
    ],
    'CM_AM': [
        ('key_passes', 'Passes Chave / 90', False),
        ('xa', 'xA / 90', False),
        ('pass_accuracy_pct', 'Precisão de Passe %', False),
        ('ball_recovery', 'Bolas Recuperadas / 90', False),
        ('successful_dribbles', 'Dribles Certos / 90', False),
        ('tackles', 'Desarmes / 90', False),
        ('sofascore_rating', 'Rating Geral', False),
    ],
    'DM': [
        ('tackles', 'Desarmes / 90', False),
        ('interceptions', 'Interceptações / 90', False),
        ('ball_recovery', 'Bolas Recuperadas / 90', False),
        ('duels_won_total', 'Duelos Ganhos / 90', False),
        ('pass_accuracy_pct', 'Precisão de Passe %', False),
        ('fbref_team_ppm', 'Pontos / Partida (PPM)', False),
        ('sofascore_rating', 'Rating Geral', False),
    ],
    'FB': [
        ('tackles', 'Desarmes / 90', False),
        ('interceptions', 'Interceptações / 90', False),
        ('key_passes', 'Passes Chave / 90', False),
        ('successful_dribbles', 'Dribles Certos / 90', False),
        ('duels_won_total', 'Duelos Ganhos / 90', False),
        ('fbref_team_ppm', 'Pontos / Partida (PPM)', False),
        ('sofascore_rating', 'Rating Geral', False),
    ],
    'CB': [
        ('tackles', 'Desarmes / 90', False),
        ('interceptions', 'Interceptações / 90', False),
        ('aerial_duels_won', 'Duelos Aéreos Ganhos / 90', False),
        ('pass_accuracy_pct', 'Precisão de Passe %', False),
        ('fbref_team_goal_diff_on', 'Saldo Gols On-Pitch', False),
        ('fbref_team_ppm', 'Pontos / Partida (PPM)', False),
        ('sofascore_rating', 'Rating Geral', False),
    ],
    'GK': [
        ('sofascore_rating', 'Rating Geral', False),
        ('fbref_team_ppm', 'Pontos / Partida (PPM)', False),
        ('fbref_team_goal_diff_on', 'Saldo Gols On-Pitch', False),
    ],
}


class ScoutAnalyticsEngine:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DB_PATH
        self._lock = threading.RLock()
        self._cache: "OrderedDict[tuple, pd.DataFrame]" = OrderedDict()

    def _get_connection(self) -> sqlite3.Connection:
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Banco de dados '{self.db_path}' não encontrado.")
        return sqlite3.connect(self.db_path)

    def get_gold_dataset(
        self,
        season: Optional[str] = None,
        competition: Optional[str] = None,
        min_minutes: int = 450,
        scout_role: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Retorna a base Gold com P90 calculado e Percentis ranqueados dentro de cada grupo posicional.
        """
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Banco de dados '{self.db_path}' não encontrado.")

        mtime = os.path.getmtime(self.db_path)
        cache_key = (mtime, season or "", competition or "", int(min_minutes))

        with self._lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache.move_to_end(cache_key)
                if scout_role:
                    return cached[cached['scout_role'] == scout_role].reset_index(drop=True)
                return cached.copy()

        conn = self._get_connection()
        where_clauses = ["minutes_played >= ?"]
        params: List[Any] = [min_minutes]

        if season:
            where_clauses.append("season LIKE ?")
            params.append(f"%{season}%")

        if competition:
            where_clauses.append("competition LIKE ?")
            params.append(f"%{competition}%")

        sql = f"""
        SELECT *
        FROM v_player_gold_analytics
        WHERE {' AND '.join(where_clauses)}
        """
        df = pd.read_sql(sql, conn, params=params)
        conn.close()

        if df.empty:
            return df

        # Seleciona a amostra mais recente e representativa por jogador (evita duplicatas de temporadas passadas)
        df['_season_year'] = df['season'].apply(season_year)
        df = (
            df.sort_values(by=['_season_year', 'minutes_played'], ascending=[False, False])
            .drop_duplicates(subset=['mapping_id'], keep='first')
            .drop(columns=['_season_year'])
            .reset_index(drop=True)
        )

        # 1. Calcula Per 90 para métricas volumétricas
        for col in RAW_VOLUME_METRICS:
            if col in df.columns:
                df[f"{col}_p90"] = (df[col] / df['minutes_played']) * 90.0

        # Adiciona taxas que já são taxas/médias diretas
        direct_metrics = [
            'sofascore_rating', 'pass_accuracy_pct', 'dribble_success_pct',
            'fbref_team_ppm', 'ws_rating', 'ws_through_balls_per_game',
            'ws_dispossessed_per_game', 'ws_unsuccessful_touches_per_game'
        ]

        # 2. Calcula Percentis agrupados por Função Tática (scout_role)
        all_metrics_to_rank = [f"{col}_p90" for col in RAW_VOLUME_METRICS if col in df.columns]
        all_metrics_to_rank.extend([col for col in direct_metrics if col in df.columns])

        for col in all_metrics_to_rank:
            pct_col = col.replace('_p90', '') + '_pct'
            # Ranking percentil relativo ao grupo posicional
            df[pct_col] = df.groupby('scout_role')[col].rank(pct=True, method='average') * 100.0

        with self._lock:
            self._cache[cache_key] = df
            while len(self._cache) > 12:
                self._cache.popitem(last=False)

        if scout_role:
            return df[df['scout_role'] == scout_role].reset_index(drop=True)
        return df.copy()

    def get_player_dossier(
        self,
        player_identifier: str,
        season: Optional[str] = None,
        min_minutes: int = 450,
    ) -> Optional[Dict[str, Any]]:
        """
        Gera o dossiê completo de scouting para um jogador específico, incluindo radar e características.
        """
        df = self.get_gold_dataset(season=season, min_minutes=min_minutes)
        if df.empty:
            return None

        # Busca por mapping_id ou nome
        if player_identifier.isdigit():
            player_df = df[df['mapping_id'] == int(player_identifier)]
        else:
            player_df = df[df['player_name'].str.contains(player_identifier, case=False, na=False)]

        if player_df.empty:
            if min_minutes > 90:
                return self.get_player_dossier(player_identifier, season=season, min_minutes=90)
            return None

        row = player_df.iloc[0]
        role = row.get('scout_role', 'CM_AM')

        # Constrói os dados do Radar de acordo com o papel tático
        radar_specs = RADAR_METRICS_BY_ROLE.get(role, RADAR_METRICS_BY_ROLE['CM_AM'])
        radar_items = []

        for metric_key, label, is_inverted in radar_specs:
            raw_val = row.get(metric_key, None)
            p90_val = row.get(f"{metric_key}_p90", raw_val)
            pct_val = row.get(f"{metric_key}_pct", 50.0)

            # Inverte se métrica negativa (ex: desarmes sofridos ou erros)
            if is_inverted and pct_val is not None:
                pct_val = 100.0 - pct_val

            radar_items.append({
                "metric_key": metric_key,
                "label": label,
                "raw_value": round(float(raw_val), 2) if raw_val is not None and not pd.isna(raw_val) else None,
                "p90_value": round(float(p90_val), 2) if p90_val is not None and not pd.isna(p90_val) else None,
                "percentile": round(float(pct_val), 1) if pct_val is not None and not pd.isna(pct_val) else None,
            })

        def _clean_trait(v: Any) -> Any:
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return None
            return v

        return {
            "profile": {
                "mapping_id": int(row['mapping_id']),
                "name": str(row['player_name']),
                "full_name": str(row['full_name']) if pd.notna(row['full_name']) and row['full_name'] else None,
                "scout_role": str(row['scout_role']),
                "scout_category": str(row['scout_category']),
                "position_raw": str(row['position_raw']),
                "current_team": str(row['current_team']),
                "current_league": str(row['current_league']),
                "season": str(row['season']),
                "competition": str(row['competition']),
                "minutes_played": int(row['minutes_played']),
                "market_value_eur": int(row['market_value_eur']) if pd.notna(row['market_value_eur']) else None,
                "market_value_raw": str(row['market_value_raw']) if pd.notna(row['market_value_raw']) else None,
                "transfermarkt_url": str(row['transfermarkt_url']) if pd.notna(row['transfermarkt_url']) else None,
                "whoscored_url": str(row['whoscored_url']) if pd.notna(row['whoscored_url']) else None,
            },
            "characteristics": {
                "player_strengths": _clean_trait(row.get('player_strengths')),
                "player_weaknesses": _clean_trait(row.get('player_weaknesses')),
                "player_style_of_play": _clean_trait(row.get('player_style_of_play')),
                "team_strengths": _clean_trait(row.get('team_strengths')),
                "team_weaknesses": _clean_trait(row.get('team_weaknesses')),
                "team_style": _clean_trait(row.get('team_style')),
            },
            "radar": radar_items,
        }

    def find_similar_players(
        self,
        target_name_or_id: str,
        season: Optional[str] = None,
        top_n: int = 5,
        min_minutes: int = 450,
    ) -> List[Dict[str, Any]]:
        """
        Encontra os jogadores brasileiros mais semelhantes ao alvo dentro da mesma função tática,
        usando distância Euclidiana no espaço de percentis das métricas do radar.
        """
        dossier = self.get_player_dossier(target_name_or_id, season=season, min_minutes=min_minutes)
        if not dossier:
            return []

        target_role = dossier["profile"]["scout_role"]
        target_mapping_id = dossier["profile"]["mapping_id"]

        df = self.get_gold_dataset(season=season, min_minutes=min_minutes, scout_role=target_role)
        if len(df) < 2:
            return []

        radar_specs = RADAR_METRICS_BY_ROLE.get(target_role, RADAR_METRICS_BY_ROLE['CM_AM'])
        pct_cols = [f"{m[0]}_pct" for m in radar_specs if f"{m[0]}_pct" in df.columns]

        if not pct_cols:
            return []

        # Matriz de percentis (preenche NaN com mediana)
        matrix = df[pct_cols].fillna(50.0).values
        target_idx = df.index[df['mapping_id'] == target_mapping_id].tolist()
        if not target_idx:
            return []

        target_vector = matrix[target_idx[0]]

        # Distância Euclidiana normalizada (máxima distância possível = sqrt(N * 100^2))
        max_dist = np.sqrt(len(pct_cols) * (100.0 ** 2))
        distances = np.linalg.norm(matrix - target_vector, axis=1)

        similarities = (1.0 - (distances / max_dist)) * 100.0
        df = df.copy()
        df['similarity_pct'] = similarities

        # Descarta o próprio jogador e ordena pelos mais similares
        similar_df = df[df['mapping_id'] != target_mapping_id].sort_values(
            by='similarity_pct', ascending=False
        ).head(top_n)

        results = []
        for _, r in similar_df.iterrows():
            results.append({
                "mapping_id": int(r['mapping_id']),
                "player_name": str(r['player_name']),
                "scout_role": str(r['scout_role']),
                "current_team": str(r['current_team']),
                "current_league": str(r['current_league']),
                "similarity_pct": round(float(r['similarity_pct']), 1),
                "market_value_raw": str(r['market_value_raw']) if pd.notna(r['market_value_raw']) else "N/A",
                "minutes_played": int(r['minutes_played']),
            })

        return results


def main():
    parser = argparse.ArgumentParser(description="Scout Analytics Engine - P90 & Percentis")
    parser.add_argument("--player", type=str, default="Pedro", help="Nome do jogador para emissão do relatório")
    parser.add_argument("--season", type=str, default=None, help="Temporada (ex: 2023, 2024)")
    parser.add_argument("--min-minutes", type=int, default=450, help="Minutos mínimos jogados (padrão: 450)")
    args = parser.parse_args()

    engine = ScoutAnalyticsEngine()
    print("\n" + "=" * 80)
    print(f" DOSSIE DE SCOUTING & MOTOR ANALITICO (Alvo: {args.player})")
    print("=" * 80)

    try:
        dossier = engine.get_player_dossier(args.player, season=args.season, min_minutes=args.min_minutes)
        if not dossier:
            print(f"[!] Nenhum registro encontrado para '{args.player}' com minutos >= {args.min_minutes}.")
            return

        prof = dossier["profile"]
        print(f"\n[PERFIL CADASTRAL]")
        print(f"  Atleta          : {prof['name']} (ID Mapping: {prof['mapping_id']})")
        print(f"  Função Tática   : {prof['scout_role']} ({prof['scout_category']}) - Posição: {prof['position_raw']}")
        print(f"  Clube / Liga    : {prof['current_team']} ({prof['current_league']})")
        print(f"  Amostra / Tempo : {prof['minutes_played']} minutos ({prof['season']} - {prof['competition']})")
        print(f"  Valor de Mercado: {prof['market_value_raw'] or 'N/A'}")

        print(f"\n[RADAR DE SCOUTING - PERCENTIS RELATIVOS AO GRUPO {prof['scout_role']}]")
        print(f"  {'Métrica'.ljust(26)} | {'Bruto'.ljust(10)} | {'P90'.ljust(10)} | Percentil")
        print("  " + "-" * 60)
        for item in dossier["radar"]:
            raw_s = f"{item['raw_value']:.1f}" if item['raw_value'] is not None else "N/A"
            p90_s = f"{item['p90_value']:.2f}" if item['p90_value'] is not None else "N/A"
            pct_s = f"{item['percentile']:.1f}%" if item['percentile'] is not None else "N/A"
            bar = "█" * int((item['percentile'] or 0) / 10)
            print(f"  {item['label'].ljust(26)} | {raw_s.ljust(10)} | {p90_s.ljust(10)} | {pct_s.ljust(8)} {bar}")

        # Similaridade
        print(f"\n[JOGADORES BRASILEIROS MAIS SIMILARES NA FUNÇÃO {prof['scout_role']}]")
        similars = engine.find_similar_players(args.player, season=args.season, top_n=3, min_minutes=args.min_minutes)
        if similars:
            for sim in similars:
                print(f"  - {sim['player_name']} ({sim['current_team']}) - Similaridade: {sim['similarity_pct']}% | Valuation: {sim['market_value_raw']}")
        else:
            print("  (Aguardando nova rodada de coleta global para cálculo de similaridade com toda a base)")

        print("\n" + "=" * 80 + "\n")

    except Exception as e:
        print(f"[!] Erro ao executar motor analítico: {e}")


if __name__ == "__main__":
    main()