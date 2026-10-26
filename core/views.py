"""
VIEWs com as métricas DERIVADAS.

O scraper e as tabelas guardam só dados brutos; qualquer métrica calculável a partir deles
(per 90, percentuais, somas, rating médio...) é exposta aqui, sempre consistente com o bruto.
As views são recriadas a cada `init_db()`.
"""

VIEWS = {
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
    'v_player_profiles': """
        SELECT
            COALESCE(sp.id, fp.id)                                          AS profile_id,
            COALESCE(sp.name, fp.name, wp.name)                             AS name,
            wp.full_name                                                    AS full_name,
            COALESCE(sp.position, fp.primary_position, wp.position)         AS position,
            COALESCE(sp.current_team, tp.current_club, wp.current_team)     AS current_team,
            COALESCE(sp.current_league, tp.league_name, wp.league_name)     AS current_league,
            COALESCE(fp.birth_date, tp.birth_date, wp.birth_date)           AS birth_date,
            COALESCE(sp.nationality, fp.nationality, tp.nationality, wp.nationality) AS nationality,
            COALESCE(sp.footed, fp.footed)                                  AS footed,
            COALESCE(sp.height, fp.height, wp.height)                       AS height,
            COALESCE(sp.weight, fp.weight)                                  AS weight,
            tp.market_value_raw,
            tp.market_value_eur,
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
        FROM fbref_players fp
        LEFT JOIN player_mapping pm ON pm.fbref_db_id = fp.id
        LEFT JOIN sofascore_players sp ON sp.id = pm.sofascore_id
        LEFT JOIN transfermarkt_players tp ON tp.id = pm.transfermarkt_id
        LEFT JOIN whoscored_players wp ON wp.id = pm.whoscored_id
        LEFT JOIN whoscored_teams wt ON wt.id = wp.whoscored_team_id
    """,
    'v_whoscored_season_stats': """
        SELECT
            s.*,
            p.name AS player_name,
            p.player_url
        FROM whoscored_player_season_stats s
        JOIN whoscored_players p ON p.id = s.player_id
    """,
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
}

