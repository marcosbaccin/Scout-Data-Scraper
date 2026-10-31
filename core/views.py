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

from core.scouting_roles import sql_scout_category_case, sql_scout_role_case

# Regra SQL para categorização posicional (fonte única de verdade em core/scouting_roles.py)
SQL_SCOUT_ROLE_CASE = sql_scout_role_case("pos")
SQL_SCOUT_CATEGORY_CASE = sql_scout_category_case("scout_role")


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
                COALESCE(
                    (SELECT spp.position FROM sofascore_player_positions spp WHERE spp.player_id = sp.id ORDER BY spp.ordinal ASC LIMIT 1),
                    tp.position,
                    wp.position,
                    fp.primary_position,
                    sp.position
                )                                                               AS pos,
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
                pm.fbref_db_id                                                  AS fbref_db_id,
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
        WITH fb_agg AS (
            SELECT
                player_id,
                CASE
                    WHEN LENGTH(season) = 9 THEN SUBSTR(season, 3, 2) || '/' || SUBSTR(season, 8, 2)
                    ELSE season
                END AS norm_season,
                AVG(team_ppm) AS team_ppm,
                SUM(team_goals_on) AS team_goals_on,
                SUM(team_goals_against_on) AS team_goals_against_on,
                SUM(matches_completed) AS matches_completed,
                SUM(subs_in) AS subs_in,
                SUM(subs_unused) AS subs_unused
            FROM fbref_outfield_stats
            WHERE COALESCE(is_national_team, 0) = 0
            GROUP BY player_id, norm_season
        ),
        ws_agg AS (
            SELECT
                player_id,
                CASE
                    WHEN LENGTH(season) = 9 THEN SUBSTR(season, 3, 2) || '/' || SUBSTR(season, 8, 2)
                    ELSE season
                END AS norm_season,
                SUM(COALESCE(motm, 0)) AS motm,
                SUM(COALESCE(minutes, 1) * COALESCE(rating, 0)) / NULLIF(SUM(CASE WHEN rating IS NOT NULL THEN COALESCE(minutes, 1) ELSE 0 END), 0) AS rating,
                SUM(COALESCE(minutes, 1) * COALESCE(through_balls_per_game, 0)) / NULLIF(SUM(CASE WHEN through_balls_per_game IS NOT NULL THEN COALESCE(minutes, 1) ELSE 0 END), 0) AS through_balls_per_game,
                SUM(COALESCE(minutes, 1) * COALESCE(dispossessed_per_game, 0)) / NULLIF(SUM(CASE WHEN dispossessed_per_game IS NOT NULL THEN COALESCE(minutes, 1) ELSE 0 END), 0) AS dispossessed_per_game,
                SUM(COALESCE(minutes, 1) * COALESCE(unsuccessful_touches_per_game, 0)) / NULLIF(SUM(CASE WHEN unsuccessful_touches_per_game IS NOT NULL THEN COALESCE(minutes, 1) ELSE 0 END), 0) AS unsuccessful_touches_per_game
            FROM whoscored_player_season_stats
            GROUP BY player_id, norm_season
        )
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
        LEFT JOIN fb_agg fb ON fb.player_id = p.fbref_db_id AND fb.norm_season = s.season
        LEFT JOIN ws_agg ws ON ws.player_id = p.whoscored_id AND ws.norm_season = s.season
    """,
}
