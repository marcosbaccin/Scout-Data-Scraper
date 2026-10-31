"""
Catálogo de estatísticas do Explorador (fonte única da verdade).

Define TODAS as métricas filtráveis, com rótulo e descrição em PT-BR, categoria, fonte, unidade e
regra de agregação, para que API, frontend, perfis prontos e testes consumam a mesma definição.

Regras:
- Colunas brutas do SofaScore são SOMADAS entre as linhas do recorte (temporadas/competições/clubes);
  `top_speed` usa o MÁXIMO; métricas médias (PPM, ratings do WhoScored) usam MÉDIA PONDERADA.
- Métricas derivadas (percentuais, somas, saldos) são calculadas DEPOIS da agregação (razão das somas),
  nunca como média de percentuais.
- `per90=True` habilita o modo "por 90 minutos" (usa os minutos do SofaScore como denominador).
- Para cada estatística o usuário pode filtrar por: valor (`total`), por 90 min (`p90`) ou
  percentil dentro do papel tático do atleta (`pct`).
"""
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import pandas as pd

Frame = pd.DataFrame


# =====================================================================================
# Categorias (ordem de exibição)
# =====================================================================================
CATEGORIES: List[Dict[str, str]] = [
    {"id": "participacao", "label": "Participação & Minutagem", "icon": "🏟️"},
    {"id": "finalizacao", "label": "Gols & Finalização", "icon": "🎯"},
    {"id": "penaltis", "label": "Pênaltis", "icon": "⚽"},
    {"id": "passes", "label": "Passes & Criação", "icon": "🧠"},
    {"id": "posse", "label": "Posse & Dribles", "icon": "🌀"},
    {"id": "defesa", "label": "Defesa & Duelos", "icon": "🛡️"},
    {"id": "disciplina", "label": "Disciplina & Faltas", "icon": "🟨"},
    {"id": "goleiros", "label": "Ações de Goleiro", "icon": "🧤"},
    {"id": "fisico", "label": "Físico & Tracking", "icon": "🏃"},
    {"id": "fbref", "label": "Impacto em Campo & Coletivo", "icon": "📈"},
    {"id": "fbref_gk", "label": "Resultados de Goleiro", "icon": "🥅"},
    {"id": "whoscored", "label": "Posse Avançada & Decisão", "icon": "🔭"},
]

SOURCE_LABELS = {
    "sofascore": "",
    "fbref": "",
    "whoscored": "",
    "derived": "",
}


@dataclass(frozen=True)
class StatDef:
    key: str
    label: str
    category: str
    description: str
    source: str = "sofascore"          # sofascore | fbref | whoscored | derived
    column: Optional[str] = None       # coluna da base agregada (padrão = key); None se derivada
    agg: str = "sum"                   # sum | max | wavg
    derive: Optional[Callable[[Frame], pd.Series]] = None
    per90: bool = True                 # habilita modo "por 90 min"
    unit: str = ""                     # '', '%', 'km', 'km/h'
    decimals: int = 0
    scale: float = 1.0                 # fator aplicado ao valor bruto agregado (ex.: metros -> km)
    floor0: bool = True                # slider começa em 0 (False p/ ratings e saldos)

    @property
    def base_column(self) -> str:
        return self.column or self.key


def _num(d: Frame, col: str) -> pd.Series:
    return d[col] if col in d.columns else pd.Series(float("nan"), index=d.index)


def _ratio(num: str, den: str, mult: float = 100.0) -> Callable[[Frame], pd.Series]:
    return lambda d: _num(d, num) * mult / _num(d, den).where(_num(d, den) > 0)


def _plus(a: str, b: str) -> Callable[[Frame], pd.Series]:
    return lambda d: _num(d, a).add(_num(d, b), fill_value=0).where(_num(d, a).notna() | _num(d, b).notna())


def _duels_won_pct(d: Frame) -> pd.Series:
    won = _num(d, "ground_duels_won").add(_num(d, "aerial_duels_won"), fill_value=0)
    total = won + _num(d, "duel_lost")  # NaN quando a fonte não trouxe 'duel_lost'
    return won * 100.0 / total.where(total > 0)


def _gk_win_pct(d: Frame) -> pd.Series:
    wins = _num(d, "fbref_wins")
    games = wins.add(_num(d, "fbref_draws"), fill_value=0).add(_num(d, "fbref_losses"), fill_value=0)
    return wins * 100.0 / games.where(games > 0)


# ----- helpers de definição -----------------------------------------------------------
def S(key, label, cat, desc, *, per90=True, unit="", dec=0, scale=1.0, agg="sum", floor0=True):
    """Métrica bruta do SofaScore."""
    return StatDef(key, label, cat, desc, "sofascore", None, agg, None, per90, unit, dec, scale, floor0)


def D(key, label, cat, desc, fn, *, per90=False, unit="", dec=2, floor0=True, source="derived"):
    """Métrica derivada (calculada após a agregação)."""
    return StatDef(key, label, cat, desc, source, None, "sum", fn, per90, unit, dec, 1.0, floor0)


def F(key, label, cat, desc, *, per90=False, agg="sum", dec=0, floor0=True, source="fbref"):
    """Métrica exclusiva de outra fonte (FBref/WhoScored) já prefixada pelo nome da coluna agregada."""
    return StatDef(key, label, cat, desc, source, None, agg, None, per90, "", dec, 1.0, floor0)


P = "participacao"
G = "finalizacao"
PN = "penaltis"
PS = "passes"
PO = "posse"
DF = "defesa"
DI = "disciplina"
GK = "goleiros"
FI = "fisico"
FB = "fbref"
FG = "fbref_gk"
WS = "whoscored"

STATS: List[StatDef] = [
    # ---------------------------------------------------------------- Participação
    S("appearances", "Jogos", P, "Partidas disputadas no recorte.", per90=False),
    S("matches_started", "Jogos como titular", P, "Partidas iniciadas no time titular.", per90=False),
    S("minutes_played", "Minutos jogados", P, "Total de minutos em campo no recorte.", per90=False),
    S("totw_appearances", "Seleções da rodada", P, "Vezes em que entrou na Seleção da Rodada.", per90=False),
    # ---------------------------------------------------------------- Gols & Finalização
    S("goals", "Gols", G, "Gols marcados (inclui pênaltis)."),
    S("assists", "Assistências", G, "Assistências concedidas."),
    D("goal_involvements", "Participações em gol", G, "Gols + assistências.", _plus("goals", "assists"),
      per90=True, dec=0),
    D("non_penalty_goals", "Gols sem pênaltis", G, "Gols marcados descontando os de pênalti.",
      lambda d: _num(d, "goals").sub(_num(d, "penalty_goals").fillna(0)), per90=True, dec=0),
    S("headed_goals", "Gols de cabeça", G, "Gols marcados de cabeça."),
    S("left_foot_goals", "Gols com o pé esquerdo", G, "Gols marcados com a perna esquerda."),
    S("right_foot_goals", "Gols com o pé direito", G, "Gols marcados com a perna direita."),
    S("goals_from_inside_the_box", "Gols dentro da área", G, "Gols marcados de dentro da área."),
    S("goals_from_outside_the_box", "Gols de fora da área", G, "Gols marcados de fora da área."),
    S("free_kick_goals", "Gols de falta", G, "Gols marcados de cobrança direta de falta."),
    S("own_goals", "Gols contra", G, "Gols contra marcados."),
    S("total_shots", "Finalizações", G, "Total de finalizações."),
    S("shots_on_target", "Finalizações no alvo", G, "Finalizações na direção do gol."),
    S("shots_off_target", "Finalizações para fora", G, "Finalizações que não foram ao alvo."),
    S("blocked_shots", "Finalizações bloqueadas", G, "Finalizações bloqueadas por adversários."),
    S("shots_from_inside_the_box", "Finalizações dentro da área", G, "Finalizações realizadas de dentro da área."),
    S("shots_from_outside_the_box", "Finalizações de fora da área", G, "Finalizações realizadas de fora da área."),
    S("shots_from_set_piece", "Finalizações de bola parada", G, "Finalizações originadas de bola parada."),
    S("hit_woodwork", "Bolas na trave", G, "Finalizações que acertaram trave/travessão."),
    S("big_chances_missed", "Grandes chances perdidas", G, "Chances claras de gol desperdiçadas."),
    S("expected_goals", "xG (gols esperados)", G, "Soma da probabilidade de gol de cada finalização.", dec=2),
    S("expected_goals_on_target", "xGOT (xG no alvo)", G, "Gols esperados considerando a qualidade da finalização no alvo.", dec=2),
    D("goals_minus_xg", "Gols − xG", G, "Diferença entre gols e xG: positivo indica finalização acima do esperado.",
      lambda d: _num(d, "goals") - _num(d, "expected_goals"), per90=True, dec=2, floor0=False),
    D("goal_conversion_pct", "Conversão de finalizações", G, "Gols ÷ finalizações.", _ratio("goals", "total_shots"),
      unit="%", dec=1),
    D("shots_on_target_pct", "Precisão de finalização", G, "Finalizações no alvo ÷ finalizações.",
      _ratio("shots_on_target", "total_shots"), unit="%", dec=1),
    # ---------------------------------------------------------------- Pênaltis
    S("penalties_taken", "Pênaltis cobrados", PN, "Pênaltis batidos.", per90=False),
    S("penalty_goals", "Pênaltis convertidos", PN, "Gols de pênalti.", per90=False),
    S("attempt_penalty_miss", "Pênaltis para fora", PN, "Pênaltis cobrados para fora.", per90=False),
    S("attempt_penalty_post", "Pênaltis na trave", PN, "Pênaltis que acertaram a trave.", per90=False),
    S("attempt_penalty_target", "Pênaltis no alvo", PN, "Pênaltis cobrados na direção do gol.", per90=False),
    S("penalties_won", "Pênaltis sofridos", PN, "Pênaltis conquistados (falta sofrida na área).", per90=False),
    S("penalties_conceded", "Pênaltis cometidos", PN, "Pênaltis que o jogador cometeu.", per90=False),
    # ---------------------------------------------------------------- Passes & Criação
    S("total_passes", "Passes tentados", PS, "Total de passes tentados."),
    S("accurate_passes", "Passes certos", PS, "Passes completados."),
    D("accurate_passes_pct", "Precisão de passe", PS, "Passes certos ÷ passes tentados.",
      _ratio("accurate_passes", "total_passes"), unit="%", dec=1),
    S("total_own_half_passes", "Passes no campo de defesa (tentados)", PS, "Passes tentados na própria metade."),
    S("accurate_own_half_passes", "Passes certos no campo de defesa", PS, "Passes completados na própria metade."),
    S("total_opposition_half_passes", "Passes no campo de ataque (tentados)", PS, "Passes tentados na metade adversária."),
    S("accurate_opposition_half_passes", "Passes certos no campo de ataque", PS, "Passes completados na metade adversária."),
    D("accurate_opposition_half_passes_pct", "Precisão de passe no campo de ataque", PS,
      "Passes certos ÷ tentados na metade adversária.",
      _ratio("accurate_opposition_half_passes", "total_opposition_half_passes"), unit="%", dec=1),
    S("accurate_final_third_passes", "Passes certos no terço final", PS, "Passes completados no terço final do campo."),
    S("total_long_balls", "Bolas longas (tentadas)", PS, "Lançamentos/bolas longas tentadas."),
    S("accurate_long_balls", "Bolas longas certas", PS, "Bolas longas completadas."),
    D("accurate_long_balls_pct", "Precisão de bolas longas", PS, "Bolas longas certas ÷ tentadas.",
      _ratio("accurate_long_balls", "total_long_balls"), unit="%", dec=1),
    S("total_chipped_passes", "Passes por cobertura (tentados)", PS, "Passes por cobertura tentados."),
    S("accurate_chipped_passes", "Passes por cobertura certos", PS, "Passes por cobertura completados."),
    S("total_crosses", "Cruzamentos (tentados)", PS, "Cruzamentos tentados."),
    S("accurate_crosses", "Cruzamentos certos", PS, "Cruzamentos completados."),
    D("accurate_crosses_pct", "Precisão de cruzamentos", PS, "Cruzamentos certos ÷ tentados.",
      _ratio("accurate_crosses", "total_crosses"), unit="%", dec=1),
    S("key_passes", "Passes-chave", PS, "Passes que resultaram em finalização de um companheiro."),
    S("big_chances_created", "Grandes chances criadas", PS, "Passes que geraram chances claras de gol."),
    S("total_attempt_assist", "Passes para finalização (total)", PS, "Total de ações que originaram finalização."),
    S("pass_to_assist", "Pré-assistências", PS, "Passes que antecederam uma assistência."),
    S("expected_assists", "xA (assistências esperadas)", PS, "Probabilidade de assistência dos passes finais.", dec=2),
    D("expected_goal_involvements", "xG + xA", PS, "Gols esperados + assistências esperadas.",
      _plus("expected_goals", "expected_assists"), per90=True, dec=2),
    S("corners_taken", "Escanteios cobrados", PS, "Cobranças de escanteio."),
    # ---------------------------------------------------------------- Posse & Dribles
    S("touches", "Toques na bola", PO, "Total de toques na bola."),
    S("touches_in_opp_box", "Toques na área adversária", PO, "Toques na bola dentro da área do adversário."),
    S("unsuccessful_touches", "Toques mal sucedidos", PO, "Domínios/toques com perda de controle."),
    S("possession_lost", "Posses perdidas", PO, "Vezes em que perdeu a bola."),
    S("dispossessed", "Desarmado pelo adversário", PO, "Vezes em que teve a bola tomada."),
    S("total_contest", "Dribles tentados", PO, "Tentativas de drible."),
    S("successful_dribbles", "Dribles certos", PO, "Dribles bem sucedidos."),
    D("successful_dribbles_pct", "Sucesso nos dribles", PO, "Dribles certos ÷ tentados.",
      _ratio("successful_dribbles", "total_contest"), unit="%", dec=1),
    S("possession_won_att_third", "Bolas recuperadas no terço final", PO, "Posses recuperadas no terço de ataque."),
    # ---------------------------------------------------------------- Defesa & Duelos
    S("tackles", "Desarmes", DF, "Total de desarmes tentados."),
    S("tackles_won", "Desarmes certos", DF, "Desarmes bem sucedidos."),
    D("tackles_won_pct", "Sucesso nos desarmes", DF, "Desarmes certos ÷ desarmes.", _ratio("tackles_won", "tackles"),
      unit="%", dec=1),
    S("interceptions", "Interceptações", DF, "Passes adversários interceptados."),
    S("clearances", "Cortes / afastamentos", DF, "Bolas afastadas da área."),
    S("outfielder_blocks", "Bloqueios de jogador de linha", DF, "Finalizações bloqueadas por jogadores de linha."),
    S("ball_recovery", "Recuperações de bola", DF, "Bolas recuperadas."),
    S("dribbled_past", "Dribles sofridos", DF, "Vezes em que foi driblado."),
    S("ground_duels_won", "Duelos no chão ganhos", DF, "Disputas no solo vencidas."),
    S("aerial_duels_won", "Duelos aéreos ganhos", DF, "Disputas aéreas vencidas."),
    S("aerial_lost", "Duelos aéreos perdidos", DF, "Disputas aéreas perdidas."),
    S("duel_lost", "Duelos perdidos (total)", DF, "Duelos perdidos (chão + aéreos)."),
    D("duels_won", "Duelos ganhos (total)", DF, "Duelos no chão + aéreos ganhos.", _plus("ground_duels_won", "aerial_duels_won"),
      per90=True, dec=0),
    D("duels_won_pct", "Aproveitamento em duelos", DF, "Duelos ganhos ÷ (ganhos + perdidos).", _duels_won_pct,
      unit="%", dec=1),
    D("aerial_duels_pct", "Aproveitamento em duelos aéreos", DF, "Aéreos ganhos ÷ (ganhos + perdidos).",
      _ratio("aerial_duels_won", "_aerial_total"), unit="%", dec=1),
    D("ground_duels_pct", "Aproveitamento em duelos no chão", DF, "Chão ganhos ÷ (ganhos + perdidos no chão).",
      _ratio("ground_duels_won", "_ground_total"), unit="%", dec=1),
    S("defensive_contributions", "Contribuições defensivas", DF, "Ações defensivas (desarmes, interceptações, cortes)."),
    S("error_lead_to_goal", "Erros que geraram gol", DF, "Falhas individuais que resultaram em gol adversário.", per90=False),
    S("error_lead_to_shot", "Erros que geraram finalização", DF, "Falhas individuais que resultaram em finalização adversária.", per90=False),
    # ---------------------------------------------------------------- Disciplina
    S("fouls_committed", "Faltas cometidas", DI, "Faltas cometidas."),
    S("fouls_drawn", "Faltas sofridas", DI, "Faltas sofridas."),
    S("offsides", "Impedimentos", DI, "Vezes em que foi flagrado em impedimento."),
    S("yellow_cards", "Cartões amarelos", DI, "Cartões amarelos recebidos.", per90=False),
    S("yellow_red_cards", "Expulsões por 2º amarelo", DI, "Expulsões por acúmulo de amarelos.", per90=False),
    S("direct_red_cards", "Cartões vermelhos diretos", DI, "Expulsões diretas.", per90=False),
    D("red_cards", "Expulsões (total)", DI, "Vermelhos diretos + 2º amarelo.", _plus("direct_red_cards", "yellow_red_cards")),
    # ---------------------------------------------------------------- Goleiros (SofaScore)
    S("saves", "Defesas", GK, "Defesas realizadas."),
    S("saves_caught", "Defesas com encaixe", GK, "Defesas em que segurou a bola."),
    S("saves_parried", "Defesas com rebote", GK, "Defesas em que espalmou."),
    D("saves_pct", "% de defesas", GK, "Defesas ÷ (defesas + gols sofridos).", _ratio("saves", "_shots_faced"),
      unit="%", dec=1),
    S("clean_sheets", "Jogos sem sofrer gol", GK, "Partidas sem sofrer gols.", per90=False),
    S("goals_conceded", "Gols sofridos", GK, "Gols sofridos."),
    S("goals_conceded_inside_the_box", "Gols sofridos dentro da área", GK, "Gols sofridos de finalizações dentro da área."),
    S("goals_conceded_outside_the_box", "Gols sofridos de fora da área", GK, "Gols sofridos de finalizações de fora da área."),
    S("saved_shots_from_inside_the_box", "Defesas dentro da área", GK, "Defesas de finalizações dentro da área."),
    S("saved_shots_from_outside_the_box", "Defesas de fora da área", GK, "Defesas de finalizações de fora da área."),
    S("expected_goals_conceded", "xG sofrido", GK, "Gols esperados contra o goleiro.", dec=2),
    S("goals_prevented", "Gols evitados", GK, "xGOT enfrentado − gols sofridos: positivo indica desempenho acima do esperado.",
      dec=2, floor0=False),
    S("high_claims", "Saídas em bolas altas", GK, "Bolas aéreas seguradas na saída do gol."),
    S("punches", "Socos", GK, "Bolas afastadas com os punhos."),
    S("runs_out", "Saídas do gol", GK, "Saídas do gol tentadas."),
    S("successful_runs_out", "Saídas do gol certas", GK, "Saídas do gol bem sucedidas."),
    S("crosses_not_claimed", "Cruzamentos não alcançados", GK, "Cruzamentos em que o goleiro não alcançou a bola."),
    S("goal_kicks", "Tiros de meta", GK, "Tiros de meta cobrados."),
    S("penalties_faced", "Pênaltis enfrentados", GK, "Pênaltis que o goleiro enfrentou.", per90=False),
    S("penalties_saved", "Pênaltis defendidos", GK, "Pênaltis defendidos.", per90=False),
    # ---------------------------------------------------------------- Físico
    S("meters_covered", "Distância total", FI, "Distância percorrida (km).", unit="km", dec=1, scale=0.001),
    S("meters_covered_walking_jogging", "Distância caminhando/trotando", FI, "Distância em baixa intensidade (km).",
      unit="km", dec=1, scale=0.001),
    S("meters_covered_running", "Distância correndo", FI, "Distância em corrida (km).", unit="km", dec=1, scale=0.001),
    S("meters_covered_high_speed_running", "Distância em alta velocidade", FI, "Distância em corrida de alta velocidade (km).",
      unit="km", dec=1, scale=0.001),
    S("meters_covered_sprinting", "Distância em sprint", FI, "Distância em sprints (km).", unit="km", dec=2, scale=0.001),
    S("number_of_sprints", "Número de sprints", FI, "Quantidade de sprints."),
    S("top_speed", "Velocidade máxima", FI, "Maior velocidade registrada (km/h).", per90=False, unit="km/h", dec=1, agg="max"),
    # ---------------------------------------------------------------- Impacto em Campo & Coletivo
    F("fbref_matches_completed", "Partidas completas", FB, "Partidas disputadas por inteiro."),
    F("fbref_subs_in", "Entradas como substituto", FB, "Vezes em que entrou no decorrer do jogo."),
    F("fbref_subs_unused", "Vezes no banco sem entrar", FB, "Partidas como reserva não utilizado."),
    F("fbref_team_ppm", "Pontos por jogo do time (PPM)", FB, "Pontos por partida do time quando o jogador atua.", agg="wavg",
      dec=2),
    F("fbref_team_goals_on", "Gols do time com ele em campo", FB, "Gols marcados pelo time enquanto o jogador está em campo.",
      per90=True),
    F("fbref_team_goals_against_on", "Gols sofridos com ele em campo", FB, "Gols sofridos pelo time enquanto o jogador está em campo.",
      per90=True),
    D("fbref_team_goal_diff_on", "Saldo de gols com ele em campo", FB, "Gols do time − gols sofridos com o jogador em campo.",
      lambda d: _num(d, "fbref_team_goals_on") - _num(d, "fbref_team_goals_against_on"), per90=True, dec=0,
      floor0=False, source="fbref"),
    F("fbref_team_on_off", "Saldo On/Off por 90", FB, "Diferença de saldo de gols por 90' do time com o jogador em campo vs. fora.",
      agg="wavg", dec=2, floor0=False),
    # ---------------------------------------------------------------- Resultados de Goleiro
    F("fbref_shots_on_target_against", "Chutes no alvo enfrentados", FG, "Finalizações no alvo contra o goleiro.",
      per90=True),
    F("fbref_wins", "Vitórias (goleiro)", FG, "Vitórias nas partidas em que atuou."),
    F("fbref_draws", "Empates (goleiro)", FG, "Empates nas partidas em que atuou."),
    F("fbref_losses", "Derrotas (goleiro)", FG, "Derrotas nas partidas em que atuou."),
    D("fbref_win_pct", "% de vitórias (goleiro)", FG, "Vitórias ÷ partidas.", _gk_win_pct,
      unit="%", dec=1, source="fbref"),
    F("fbref_pens_allowed", "Pênaltis sofridos (goleiro)", FG, "Pênaltis marcados contra o goleiro."),
    F("fbref_pens_missed_gk", "Pênaltis desperdiçados pelo adversário", FG, "Pênaltis que o adversário errou diante do goleiro."),
    # ---------------------------------------------------------------- Posse Avançada & Decisão
    F("ws_motm", "Homem do jogo (MOTM)", WS, "Vezes eleito o melhor em campo (MOTM).", source="whoscored"),
    F("ws_through_balls_per_game", "Bolas enfiadas por jogo", WS, "Passes em profundidade por partida.", agg="wavg", dec=2,
      source="whoscored"),
    F("ws_dispossessed_per_game", "Desarmado por jogo", WS, "Vezes desarmado por partida.", agg="wavg", dec=2,
      source="whoscored"),
    F("ws_unsuccessful_touches_per_game", "Toques mal sucedidos por jogo", WS, "Domínios malsucedidos por partida.",
      agg="wavg", dec=2, source="whoscored"),
]

STAT_INDEX: Dict[str, StatDef] = {s.key: s for s in STATS}
assert len(STAT_INDEX) == len(STATS), "chaves de estatística duplicadas no catálogo"

# Colunas auxiliares (não filtráveis) calculadas junto às agregações para suportar derivadas.
AUX_COLUMNS = {
    "_aerial_total": lambda d: _num(d, "aerial_duels_won").add(_num(d, "aerial_lost"), fill_value=0)
                                .where(_num(d, "aerial_duels_won").notna() | _num(d, "aerial_lost").notna()),
    "_ground_total": lambda d: (_num(d, "ground_duels_won")
                                + (_num(d, "duel_lost") - _num(d, "aerial_lost").fillna(0)).clip(lower=0)),
    "_shots_faced": lambda d: _num(d, "saves").add(_num(d, "goals_conceded"), fill_value=0)
                               .where(_num(d, "saves").notna() | _num(d, "goals_conceded").notna()),
}

# Colunas exclusivas FBref/WhoScored e suas colunas de origem nas tabelas.
FBREF_SOURCE_COLUMNS = {
    "fbref_matches_completed": "matches_completed",
    "fbref_subs_in": "subs_in",
    "fbref_subs_unused": "subs_unused",
    "fbref_team_ppm": "team_ppm",
    "fbref_team_goals_on": "team_goals_on",
    "fbref_team_goals_against_on": "team_goals_against_on",
    "fbref_team_on_off": "team_on_off",
    "fbref_shots_on_target_against": "shots_on_target_against",
    "fbref_wins": "wins",
    "fbref_draws": "draws",
    "fbref_losses": "losses",
    "fbref_pens_allowed": "pens_allowed",
    "fbref_pens_missed_gk": "pens_missed_gk",
}
WHOSCORED_SOURCE_COLUMNS = {
    "ws_motm": "motm",
    "ws_rating": "rating",
    "ws_through_balls_per_game": "through_balls_per_game",
    "ws_dispossessed_per_game": "dispossessed_per_game",
    "ws_unsuccessful_touches_per_game": "unsuccessful_touches_per_game",
}


# =====================================================================================
# Rótulos de identificação
# =====================================================================================
ROLE_LABELS = [
    {"value": "ST", "label": "ST · Centroavante", "category": "ATT"},
    {"value": "WNG", "label": "WNG · Ponta / Extremo", "category": "ATT"},
    {"value": "CM_AM", "label": "CM/AM · Meia Central / Ofensivo", "category": "MID"},
    {"value": "DM", "label": "DM · Volante", "category": "MID"},
    {"value": "FB", "label": "FB · Lateral / Ala", "category": "DEF"},
    {"value": "CB", "label": "CB · Zagueiro", "category": "DEF"},
    {"value": "GK", "label": "GK · Goleiro", "category": "GK"},
]

POSITION_LABELS = {
    "GK": "Goleiro", "DC": "Zagueiro", "DL": "Lateral esquerdo", "DR": "Lateral direito",
    "DM": "Volante", "MC": "Meio-campista", "AM": "Meia ofensivo", "ML": "Meia esquerda", "MR": "Meia direita",
    "LW": "Ponta esquerda", "RW": "Ponta direita", "ST": "Centroavante",
}

FOOT_LABELS = {"Left": "Esquerdo", "Right": "Direito", "Both": "Ambidestro"}

# Características do SofaScore (chave = nome em inglês da view v_sofascore_characteristics_named)
CHARACTERISTIC_LABELS = {
    "Anchor play": "Jogo de pivô / apoio",
    "Penalty taking": "Cobrança de pênaltis",
    "Direct free kicks": "Faltas diretas",
    "Long shots": "Chutes de longa distância",
    "Finishing": "Finalização",
    "Passing": "Passe",
    "Playmaking": "Criação de jogadas",
    "Tackling": "Desarme",
    "Consistency": "Consistência",
    "Long balls": "Bolas longas",
    "Ball control": "Controle de bola",
    "Ground duels": "Duelos no chão",
    "Aerial duels": "Duelos aéreos",
    "Error proneness": "Propensão a erros",
    "Discipline": "Disciplina",
    "Penalty saving": "Defesa de pênaltis",
    "Reflexes": "Reflexos",
    "High claims": "Saídas em bolas altas",
    "Handling": "Segurança com as mãos",
    "Long shots saving": "Defesa de chutes de longe",
    "Positioning": "Posicionamento",
    "High pressing": "Pressão alta",
}

SOURCE_FLAGS = [
    {"value": "fbref", "label": "FBref"},
    {"value": "transfermarkt", "label": "Transfermarkt"},
    {"value": "whoscored", "label": "WhoScored"},
]


# =====================================================================================
# Perfis prontos (modo percentil = comparação dentro do papel tático, sem limiares arbitrários)
# =====================================================================================
def _pf(key: str, mode: str = "pct", min_: Optional[float] = None, max_: Optional[float] = None) -> Dict:
    return {"key": key, "mode": mode, "min": min_, "max": max_}


PRESETS: List[Dict] = [
    {
        "id": "centroavante_finalizador",
        "name": "Centroavante finalizador",
        "description": "Atacantes no top 30% em gols, xG e finalizações no alvo por 90'.",
        "identity": {"roles": ["ST"]},
        "stats": [_pf("goals", min_=70), _pf("expected_goals", min_=70), _pf("shots_on_target", min_=60)],
    },
    {
        "id": "ponta_driblador",
        "name": "Ponta driblador e criador",
        "description": "Pontas acima da média em dribles, passes-chave e xA por 90'.",
        "identity": {"roles": ["WNG"]},
        "stats": [_pf("successful_dribbles", min_=70), _pf("key_passes", min_=60), _pf("expected_assists", min_=60)],
    },
    {
        "id": "meia_criador",
        "name": "Meia criador",
        "description": "Meias com muita criação (passes-chave, xA) e passe seguro.",
        "identity": {"roles": ["CM_AM"]},
        "stats": [_pf("key_passes", min_=70), _pf("expected_assists", min_=60), _pf("accurate_passes_pct", min_=50)],
    },
    {
        "id": "volante_recuperador",
        "name": "Volante recuperador",
        "description": "Meio-campistas defensivos no top 30% em desarmes, interceptações e recuperações.",
        "identity": {"roles": ["DM", "CM_AM"]},
        "stats": [_pf("tackles", min_=70), _pf("interceptions", min_=60), _pf("ball_recovery", min_=60)],
    },
    {
        "id": "zagueiro_dominante",
        "name": "Zagueiro dominante",
        "description": "Zagueiros fortes no jogo aéreo e com bom aproveitamento em duelos.",
        "identity": {"roles": ["CB"]},
        "stats": [_pf("aerial_duels_won", min_=70), _pf("duels_won_pct", min_=60), _pf("clearances", min_=40)],
    },
    {
        "id": "lateral_ofensivo",
        "name": "Lateral ofensivo",
        "description": "Laterais com muitos cruzamentos certos, passes-chave e dribles.",
        "identity": {"roles": ["FB"]},
        "stats": [_pf("accurate_crosses", min_=70), _pf("key_passes", min_=60), _pf("successful_dribbles", min_=50)],
    },
    {
        "id": "goleiro_seguro",
        "name": "Goleiro de alto rendimento",
        "description": "Goleiros no top 30% em % de defesas e gols evitados.",
        "identity": {"roles": ["GK"]},
        "stats": [_pf("saves_pct", min_=70), _pf("goals_prevented", min_=70)],
    },
    {
        "id": "jovem_promessa",
        "name": "Jovem promessa",
        "description": "Até 21 anos com destaque em participações em gol no seu papel tático.",
        "identity": {"age_max": 21},
        "stats": [_pf("goal_involvements", min_=60)],
    },
]
