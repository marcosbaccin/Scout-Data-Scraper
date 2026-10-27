"""
DDL das Views SQL Analíticas (Camada Gold).

Centraliza todas as regras de negócio analíticas e derivações estatísticas:
- v_fbref_outfield_derived / v_fbref_keeper_derived: Métricas táticas e percentuais do FBref.
- v_sofascore_stats_derived: Rating médio, Per 90s, percentuais de passe, drible e duelos.
- v_sofascore_characteristics_named: Dicionário decodificado de pontos fortes/fracos.
- v_whoscored_season_stats: Estatísticas de histórico e táticas do WhoScored.
- v_player_profiles: Dossiê unificado dos atletas com normalização posicional (scout_role e scout_category).
- v_player_gold_analytics: Camada Gold unificada (SofaScore primária + FBref exclusivas + WhoScored exclusivas + Valuation TM).

Todas as views são recriadas de forma idempotente em `core.database.init_db()`.
"""

# Regra SQL para categorização posicional
SQL_SCOUT_ROLE_CASE = """
    CASE
        WHEN LOWER(pos) LIKE '%gol%' OR LOWER(pos) LIKE '%gk%' OR LOWER(pos) LIKE '%guarda%' OR LOWER(pos) = 'g' THEN 'GK'
        WHEN LOWER(pos) LIKE '%ponta%' OR LOWER(pos) LIKE '%winger%' OR LOWER(pos) LIKE '%extremo%' OR LOWER(pos) LIKE '%m(d)%' OR LOWER(pos) LIKE '%m(e)%' OR LOWER(pos) LIKE '%a(d)%' OR LOWER(pos) LIKE '%a(e)%' THEN 'WNG'
        WHEN LOWER(pos) LIKE '%lateral%' OR LOWER(pos) LIKE '%ala%' OR LOWER(pos) LIKE '%back%' OR LOWER(pos) LIKE '%lb%' OR LOWER(pos) LIKE '%rb%' OR LOWER(pos) LIKE '%d(d)%' OR LOWER(pos) LIKE '%d(e)%' THEN 'FB'
        WHEN LOWER(pos) LIKE '%zagueiro%' OR LOWER(pos) LIKE '%centre-back%' OR LOWER(pos) LIKE '%cb%' OR LOWER(pos) LIKE '%d(c)%' OR LOWER(pos) = 'df' THEN 'CB'
        WHEN LOWER(pos) LIKE '%volante%' OR LOWER(pos) LIKE '%defensive mid%' OR LOWER(pos) LIKE '%dm%' THEN 'DM'
        WHEN LOWER(pos) LIKE '%centroavante%' OR LOWER(pos) LIKE '%striker%' OR LOWER(pos) LIKE '%centre-forward%' OR LOWER(pos) LIKE '%cf%' OR LOWER(pos) LIKE '%pl%' OR LOWER(pos) = 'fw' THEN 'ST'
        WHEN LOWER(pos) LIKE '%meio%' OR LOWER(pos) LIKE '%meia%' OR LOWER(pos) LIKE '%midfield%' OR LOWER(pos) LIKE '%cm%' OR LOWER(pos) LIKE '%am%' OR LOWER(pos) LIKE '%mc%' OR LOWER(pos) = 'mf' OR LOWER(pos) = 'm' THEN 'CM_AM'
        WHEN LOWER(pos) LIKE '%atacante%' OR LOWER(pos) = 'f' THEN 'ST'
        WHEN LOWER(pos) LIKE '%defesa%' OR LOWER(pos) = 'd' THEN 'CB'
        ELSE 'CM_AM'
    END
"""

SQL_SCOUT_CATEGORY_CASE = """
    CASE
        WHEN scout_role = 'GK' THEN 'GK'
        WHEN scout_role IN ('CB', 'FB') THEN 'DEF'
        WHEN scout_role IN ('DM', 'CM_AM') THEN 'MID'
        WHEN scout_role IN ('WNG', 'ST') THEN 'ATT'
        ELSE 'MID'
    END
"""


VIEWS = {
    # -------------------------------------------------------------------------
    # FBREF DERIVADAS
    # -------------------------------------------------------------------------
    'v_fbref_outfield_derived': """
        SELECT
            s.*,
            p.name AS player_name,
            s.team_goals_on - s.team_goals_against_on                      AS team_goal_diff_on
        FROM fbref_outfield_stats s
        JOIN fbref_players p ON p.id = s.player_id
    """,
    'v_fbref_keeper_derived': """
        SELECT
            s.*,
            p.name AS player_name,
            s.team_goals_on - s.team_goals_against_on                      AS team_goal_diff_on,
            s.wins * 100.0 / NULLIF(s.wins + s.draws + s.losses, 0)        AS win_pct,
            s.pens_missed_gk * 100.0 / NULLIF(s.pens_allowed + s.pens_missed_gk, 0) AS pens_missed_pct
        FROM fbref_keeper_stats s
        JOIN fbref_players p ON p.id = s.player_id
    """,

    # -------------------------------------------------------------------------
    # WHOSCORED ESTATÍSTICAS
    # -------------------------------------------------------------------------
    'v_whoscored_season_stats': """
        SELECT
            s.*,
            p.name AS player_name,
            p.player_url
        FROM whoscored_player_season_stats s
        JOIN whoscored_players p ON p.id = s.player_id
    """,

    # -------------------------------------------------------------------------
    # SOFASCORE DERIVADAS E CARACTERÍSTICAS
    # -------------------------------------------------------------------------
    'v_sofascore_stats_derived': """
        SELECT
            s.*,
            p.name AS player_name,
            s.total_rating / NULLIF(s.count_rating, 0)                     AS rating,
            s.minutes_played / 90.0                                        AS nineties,
            s.goals + s.assists                                            AS goal_involvements,
            s.expected_goals + s.expected_assists                          AS expected_goal_involvements,
            s.yellow_red_cards + s.direct_red_cards                        AS red_cards,
            s.ground_duels_won + s.aerial_duels_won                        AS total_duels_won,
            s.total_passes - s.accurate_passes                             AS inaccurate_passes,
            s.accurate_passes * 100.0 / NULLIF(s.total_passes, 0)          AS accurate_passes_pct,
            s.accurate_long_balls * 100.0 / NULLIF(s.total_long_balls, 0)  AS accurate_long_balls_pct,
            s.accurate_crosses * 100.0 / NULLIF(s.total_crosses, 0)        AS accurate_crosses_pct,
            s.successful_dribbles * 100.0 / NULLIF(s.total_contest, 0)     AS successful_dribbles_pct,
            s.tackles_won * 100.0 / NULLIF(s.tackles, 0)                   AS tackles_won_pct,
            s.saves * 100.0 / NULLIF(s.saves + s.goals_conceded, 0)        AS saves_pct,
            s.meters_covered / 1000.0                                      AS kilometers_covered,
            s.goals * 90.0 / NULLIF(s.minutes_played, 0)                   AS goals_per90,
            s.assists * 90.0 / NULLIF(s.minutes_played, 0)                 AS assists_per90,
            s.key_passes * 90.0 / NULLIF(s.minutes_played, 0)              AS key_passes_per90,
            s.minutes_played * 1.0 / NULLIF(s.goals, 0)                    AS minutes_per_goal
        FROM sofascore_stats s
        JOIN sofascore_players p ON p.id = s.player_id
    """,
    'v_sofascore_characteristics_named': """
        SELECT
            c.*,
            p.name AS player_name,
            CASE c.type_code
                WHEN 1 THEN 'Anchor play'
                WHEN 2 THEN 'Penalty taking'
                WHEN 3 THEN 'Direct free kicks'
                WHEN 4 THEN 'Long shots'
                WHEN 5 THEN 'Finishing'
                WHEN 6 THEN 'Passing'
                WHEN 7 THEN 'Playmaking'
                WHEN 9 THEN 'Tackling'
                WHEN 11 THEN 'Consistency'
                WHEN 13 THEN 'Long balls'
                WHEN 14 THEN 'Ball control'
                WHEN 15 THEN 'Ground duels'
                WHEN 16 THEN 'Aerial duels'
                WHEN 17 THEN 'Error proneness'
                WHEN 18 THEN 'Discipline'
                WHEN 19 THEN 'Penalty saving'
                WHEN 20 THEN 'Reflexes'
                WHEN 22 THEN 'High claims'
                WHEN 23 THEN 'Handling'
                WHEN 24 THEN 'Long shots saving'
                WHEN 25 THEN 'Positioning'
                WHEN 26 THEN 'High pressing'
                ELSE 'Characteristic #' || c.type_code
            END AS characteristic_name
        FROM sofascore_characteristics c
        JOIN sofascore_players p ON p.id = c.player_id
    """,

    # -------------------------------------------------------------------------
    # PERFIL UNIFICADO COM PAPEL TÁTICO NORMALIZADO (DIMENSÃO GOLD)
    # -------------------------------------------------------------------------
    'v_player_profiles': f"""
        WITH raw_profiles AS (
            SELECT
                COALESCE(pm.sofascore_id, pm.fbref_db_id)                       AS mapping_id,
                COALESCE(sp.id, fp.id)                                          AS profile_id,
                COALESCE(sp.name, fp.name, wp.name)                             AS name,
                wp.full_name                                                    AS full_name,
                COALESCE(tp.position, sp.position, fp.primary_position, wp.position) AS pos,
                COALESCE(sp.current_team, tp.current_club, wp.current_team)     AS current_team,
                COALESCE(sp.current_league, tp.league_name, wp.league_name)     AS current_league,
                COALESCE(fp.birth_date, tp.birth_date, wp.birth_date)           AS birth_date,
                COALESCE(sp.nationality, fp.nationality, tp.nationality, wp.nationality) AS nationality,
                COALESCE(sp.footed, fp.footed)                                  AS footed,
                COALESCE(sp.height, fp.height, wp.height)                       AS height,
                COALESCE(sp.weight, fp.weight)                                  AS weight,
                tp.market_value_raw,
                tp.market_value_eur,
                tp.url                                                          AS transfermarkt_url,
                fp.fbref_id,
                sp.id                                                           AS sofascore_id,
                tp.id                                                           AS transfermarkt_id,
                wp.id                                                           AS whoscored_id,
                wp.player_url                                                   AS whoscored_url,
                wp.strengths                                                    AS player_strengths,
                wp.weaknesses                                                   AS player_weaknesses,
                wp.style_of_play                                                AS player_style_of_play,
                wt.strengths                                                    AS team_strengths,
                wt.weaknesses                                                   AS team_weaknesses,
                wt.style                                                        AS team_style
            FROM player_mapping pm
            LEFT JOIN sofascore_players sp ON sp.id = pm.sofascore_id
            LEFT JOIN fbref_players fp ON fp.id = pm.fbref_db_id
            LEFT JOIN transfermarkt_players tp ON tp.id = pm.transfermarkt_id
            LEFT JOIN whoscored_players wp ON wp.id = pm.whoscored_id
            LEFT JOIN whoscored_teams wt ON wt.id = wp.whoscored_team_id
        ),
        typed_profiles AS (
            SELECT
                *,
                pos AS position,
                {SQL_SCOUT_ROLE_CASE} AS scout_role
            FROM raw_profiles
        )
        SELECT
            *,
            {SQL_SCOUT_CATEGORY_CASE} AS scout_category
        FROM typed_profiles
    """,

    # -------------------------------------------------------------------------
    # TABELA FATO ANALÍTICA GOLD (ESTATÍSTICAS CONSOLIDADAS DAS 4 FONTES)
    # -------------------------------------------------------------------------
    'v_player_gold_analytics': """
        SELECT
            p.mapping_id,
            p.name                                                          AS player_name,
            p.full_name,
            p.scout_role,
            p.scout_category,
            p.position                                                      AS position_raw,
            p.current_team,
            p.current_league,
            p.birth_date,
            p.nationality,
            p.market_value_eur,
            p.market_value_raw,
            p.transfermarkt_url,
            p.whoscored_url,
            p.player_strengths,
            p.player_weaknesses,
            p.player_style_of_play,
            p.team_strengths,
            p.team_weaknesses,
            p.team_style,

            -- Dimensão da Temporada / Competição (SofaScore Primária)
            s.season,
            s.competition,
            s.squad,
            s.minutes_played,
            s.minutes_played / 90.0                                        AS nineties,

            -- Métricas Volumétricas e Ofensivas (SofaScore)
            s.goals,
            s.assists,
            s.goals + s.assists                                            AS goal_involvements,
            s.expected_goals                                                AS xg,
            s.expected_assists                                              AS xa,
            s.total_shots                                                   AS shots,
            s.shots_on_target,
            s.key_passes,
            s.big_chances_created,

            -- Construção e Posse (SofaScore)
            s.accurate_passes,
            s.total_passes,
            s.accurate_passes * 100.0 / NULLIF(s.total_passes, 0)          AS pass_accuracy_pct,
            s.successful_dribbles,
            s.total_contest                                                 AS dribble_attempts,
            s.successful_dribbles * 100.0 / NULLIF(s.total_contest, 0)     AS dribble_success_pct,

            -- Combate e Defesa (SofaScore)
            s.tackles,
            s.interceptions,
            s.ball_recovery,
            s.ground_duels_won,
            s.aerial_duels_won,
            s.ground_duels_won + s.aerial_duels_won                        AS duels_won_total,
            s.fouls_committed                                               AS fouls,
            s.yellow_cards,
            s.direct_red_cards + s.yellow_red_cards                        AS red_cards,

            -- Avaliação Geral (SofaScore)
            s.total_rating / NULLIF(s.count_rating, 0)                     AS sofascore_rating,

            -- Métricas Exclusivas FBref (On-Pitch Impact & Participação)
            fb.team_ppm                                                     AS fbref_team_ppm,
            fb.team_goals_on                                                AS fbref_team_goals_on,
            fb.team_goals_against_on                                        AS fbref_team_goals_against_on,
            (fb.team_goals_on - fb.team_goals_against_on)                  AS fbref_team_goal_diff_on,
            fb.matches_completed                                            AS fbref_matches_completed,
            fb.subs_in                                                      AS fbref_subs_in,
            fb.subs_unused                                                  AS fbref_subs_unused,

            -- Métricas Exclusivas WhoScored (Táticas de Jogo & Erros Não Forçados)
            ws.motm                                                         AS ws_motm,
            ws.rating                                                       AS ws_rating,
            ws.through_balls_per_game                                       AS ws_through_balls_per_game,
            ws.dispossessed_per_game                                        AS ws_dispossessed_per_game,
            ws.unsuccessful_touches_per_game                                AS ws_unsuccessful_touches_per_game,

            -- IDs das 4 Fontes
            p.sofascore_id,
            p.fbref_id,
            p.transfermarkt_id,
            p.whoscored_id

        FROM sofascore_stats s
        JOIN v_player_profiles p ON p.sofascore_id = s.player_id
        LEFT JOIN fbref_outfield_stats fb ON fb.player_id = p.fbref_id
            AND (
                fb.season = s.season
                OR s.season LIKE '%' || SUBSTR(fb.season, -2) || '%'
                OR fb.season LIKE '%' || SUBSTR(s.season, 1, 4) || '%'
            )
        LEFT JOIN whoscored_player_season_stats ws ON ws.player_id = p.whoscored_id
            AND (
                ws.season = s.season
                OR s.season LIKE '%' || SUBSTR(ws.season, -2) || '%'
                OR ws.season LIKE '%' || SUBSTR(s.season, 1, 4) || '%'
            )
    """,
}
