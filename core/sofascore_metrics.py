"""
Catálogo das métricas do Sofascore.

Regra do projeto: o scraper coleta apenas métricas BRUTAS. Tudo que pode ser obtido por
cálculo entre outras métricas (percentuais, somas, médias por 90 min, conversões de
unidade) fica de fora da coleta e é exposto no banco por VIEWs (ver core/views.py).
Validado contra o JSON bruto (sofascore_final_stats.json): as métricas em
DERIVED_METRICS são reproduzidas exatamente a partir das brutas (ex.: totalDuelsWon =
groundDuelsWon + aerialDuelsWon; inaccuratePasses = totalPasses - accuratePasses).
"""
import re

# json_key -> 'int' | 'float'  (tipo da coluna no banco)
RAW_METRICS = {
    # Participação
    'appearances': 'int', 'matchesStarted': 'int', 'minutesPlayed': 'int',
    'totwAppearances': 'int', 'totalRating': 'float', 'countRating': 'int',
    # Gols, assistências e finalização
    'goals': 'int', 'assists': 'int', 'headedGoals': 'int', 'leftFootGoals': 'int',
    'rightFootGoals': 'int', 'goalsFromInsideTheBox': 'int', 'goalsFromOutsideTheBox': 'int',
    'freeKickGoal': 'int', 'shotFromSetPiece': 'int', 'ownGoals': 'int',
    'totalShots': 'int', 'shotsOnTarget': 'int', 'shotsOffTarget': 'int', 'blockedShots': 'int',
    'shotsFromInsideTheBox': 'int', 'shotsFromOutsideTheBox': 'int', 'hitWoodwork': 'int',
    'bigChancesMissed': 'int', 'bigChancesCreated': 'int',
    'expectedGoals': 'float', 'expectedAssists': 'float', 'expectedGoalsOnTarget': 'float',
    # Pênaltis
    'penaltiesTaken': 'int', 'penaltyGoals': 'int', 'attemptPenaltyMiss': 'int',
    'attemptPenaltyPost': 'int', 'attemptPenaltyTarget': 'int',
    'penaltyWon': 'int', 'penaltyConceded': 'int', 'penaltyFaced': 'int', 'penaltySave': 'int',
    # Passes e criação
    'totalPasses': 'int', 'accuratePasses': 'int',
    'totalOwnHalfPasses': 'int', 'accurateOwnHalfPasses': 'int',
    'totalOppositionHalfPasses': 'int', 'accurateOppositionHalfPasses': 'int',
    'accurateFinalThirdPasses': 'int', 'totalLongBalls': 'int', 'accurateLongBalls': 'int',
    'totalChippedPasses': 'int', 'accurateChippedPasses': 'int',
    'totalCross': 'int', 'accurateCrosses': 'int', 'keyPasses': 'int',
    'totalAttemptAssist': 'int', 'passToAssist': 'int', 'cornersTaken': 'int',
    # Posse e dribles
    'touches': 'int', 'touchesInOppBox': 'int', 'unsuccessfulTouches': 'int',
    'possessionLost': 'int', 'dispossessed': 'int', 'totalContest': 'int',
    'successfulDribbles': 'int', 'possessionWonAttThird': 'int',
    # Defesa e duelos
    'tackles': 'int', 'tacklesWon': 'int', 'interceptions': 'int', 'clearances': 'int',
    'outfielderBlocks': 'int', 'ballRecovery': 'int', 'dribbledPast': 'int',
    'groundDuelsWon': 'int', 'aerialDuelsWon': 'int', 'aerialLost': 'int', 'duelLost': 'int',
    'defensiveContributions': 'int', 'errorLeadToGoal': 'int', 'errorLeadToShot': 'int',
    # Disciplina
    'fouls': 'int', 'wasFouled': 'int', 'offsides': 'int',
    'yellowCards': 'int', 'yellowRedCards': 'int', 'directRedCards': 'int',
    # Goleiros
    'saves': 'int', 'savesCaught': 'int', 'savesParried': 'int', 'cleanSheet': 'int',
    'goalsConceded': 'int', 'goalsConcededInsideTheBox': 'int', 'goalsConcededOutsideTheBox': 'int',
    'savedShotsFromInsideTheBox': 'int', 'savedShotsFromOutsideTheBox': 'int',
    'expectedGoalsConceded': 'float', 'goalsPrevented': 'float',
    'highClaims': 'int', 'punches': 'int', 'runsOut': 'int', 'successfulRunsOut': 'int',
    'crossesNotClaimed': 'int', 'goalKicks': 'int',
    # Tracking físico
    'metersCovered': 'float', 'metersCoveredWalkingJogging': 'float', 'metersCoveredRunning': 'float',
    'metersCoveredHighSpeedRunning': 'float', 'metersCoveredSprinting': 'float',
    'numberOfSprints': 'int', 'topSpeed': 'float',
}

# Métricas que o Sofascore devolve mas que são cálculo de outras (não coletadas).
DERIVED_METRICS = {
    'rating',                       # totalRating / countRating
    'goalInvolvements', 'goalsAssistsSum',               # goals + assists
    'expectedGoalInvolvements',                          # xG + xA
    'totalDuelsWon',                                     # groundDuelsWon + aerialDuelsWon
    'inaccuratePasses',                                  # totalPasses - accuratePasses
    'redCards',                                          # directRedCards + yellowRedCards
    'kilometersCovered', 'kilometersCoveredPer90', 'numberOfSprintsPer90',
    'scoringFrequency',
    'accuratePassesPercentage', 'accurateLongBallsPercentage', 'accurateCrossesPercentage',
    'aerialDuelsWonPercentage', 'groundDuelsWonPercentage', 'totalDuelsWonPercentage',
    'tacklesWonPercentage', 'successfulDribblesPercentage', 'goalConversionPercentage',
    'penaltyConversion', 'setPieceConversion', 'savesPercentage',
    'highSpeedRunningPercentage', 'runningPercentage', 'sprintingPercentage',
    'walkingJoggingPercentage',
    # Metadados do bloco (não são métricas)
    'id', 'type',
}

# Nomes de coluna que não seguem a conversão automática camelCase -> snake_case.
COLUMN_OVERRIDES = {
    'cleanSheet': 'clean_sheets',
    'totalCross': 'total_crosses',
    'fouls': 'fouls_committed',
    'wasFouled': 'fouls_drawn',
    'shotFromSetPiece': 'shots_from_set_piece',
    'freeKickGoal': 'free_kick_goals',
    'penaltySave': 'penalties_saved',
    'penaltyWon': 'penalties_won',
    'penaltyConceded': 'penalties_conceded',
    'penaltyFaced': 'penalties_faced',
    'totwAppearances': 'totw_appearances',
}


def column_name(json_key: str) -> str:
    if json_key in COLUMN_OVERRIDES:
        return COLUMN_OVERRIDES[json_key]
    return re.sub(r'(?<!^)(?=[A-Z])', '_', json_key).lower()


def strip_derived(metrics: dict) -> dict:
    """Remove do bloco de estatísticas tudo o que é calculável (mantém o bruto)."""
    return {k: v for k, v in metrics.items() if k not in DERIVED_METRICS}


CHARACTERISTIC_NAMES = {
    1: 'Anchor play',
    2: 'Penalty taking',
    3: 'Direct free kicks',
    4: 'Long shots',
    5: 'Finishing',
    6: 'Passing',
    7: 'Playmaking',
    9: 'Tackling',
    11: 'Consistency',
    13: 'Long balls',
    14: 'Ball control',
    15: 'Ground duels',
    16: 'Aerial duels',
    17: 'Error proneness',
    18: 'Discipline',
    19: 'Penalty saving',
    20: 'Reflexes',
    22: 'High claims',
    23: 'Handling',
    24: 'Long shots saving',
    25: 'Positioning',
    26: 'High pressing',
}


def characteristic_name(type_code: int) -> str:
    return CHARACTERISTIC_NAMES.get(type_code, f"Characteristic #{type_code}")
