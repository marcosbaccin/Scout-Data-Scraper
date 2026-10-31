"""
Modelos do banco único `scout.db`.

Decisão de arquitetura: UM banco, tabelas separadas por fonte (prefixo `fbref_`, `sofascore_`,
futuramente `whoscored_` e `transfermarkt_`) + camada de integração (`player_mapping`).
Motivos: o cruzamento entre fontes é feito por JOIN, SQLite não suporta FK entre arquivos
diferentes, a API/analytics consultam tudo numa conexão só e cada fonte continua isolada
pelo prefixo (pode ser recarregada sem tocar nas outras).
"""
import datetime as dt
from typing import List, Optional

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

from core.sofascore_metrics import RAW_METRICS, column_name

Base = declarative_base()


# =====================================================================================
# FBref
# =====================================================================================
class FbrefPlayer(Base):
    __tablename__ = 'fbref_players'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fbref_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    birth_date: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)
    nationality: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    primary_position: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    footed: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # cm
    weight: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # kg
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    outfield_stats: Mapped[List["FbrefOutfieldStat"]] = relationship(back_populates="player", cascade="all, delete-orphan")
    keeper_stats: Mapped[List["FbrefKeeperStat"]] = relationship(back_populates="player", cascade="all, delete-orphan")


def _int():
    # NULL = a fonte não trouxe a métrica para aquela temporada (diferente de 0 real).
    return mapped_column(Integer, nullable=True)


class FbrefOutfieldStat(Base):
    """Uma linha por jogador + temporada + clube/seleção + competição (jogadores de linha).
    Contém apenas as métricas exclusivas do FBref não coletadas pelo SofaScore."""
    __tablename__ = 'fbref_outfield_stats'
    __table_args__ = (UniqueConstraint('player_id', 'season', 'squad', 'comp', 'is_national_team',
                                       name='uq_fbref_outfield_key'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey('fbref_players.id'), index=True, nullable=False)

    # Chaves de contexto
    season: Mapped[str] = mapped_column(String, nullable=False)
    squad: Mapped[str] = mapped_column(String, nullable=False)
    comp: Mapped[str] = mapped_column(String, nullable=False)
    is_national_team: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Colunas exclusivas do FBref para manter
    matches_completed: Mapped[Optional[int]] = _int()
    subs_in: Mapped[Optional[int]] = _int()
    subs_unused: Mapped[Optional[int]] = _int()
    team_ppm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    team_goals_on: Mapped[Optional[int]] = _int()
    team_goals_against_on: Mapped[Optional[int]] = _int()
    team_on_off: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    player: Mapped["FbrefPlayer"] = relationship(back_populates="outfield_stats")


class FbrefKeeperStat(Base):
    """Uma linha por jogador + temporada + clube/seleção + competição (goleiros).
    Contém apenas as métricas exclusivas do FBref não coletadas pelo SofaScore."""
    __tablename__ = 'fbref_keeper_stats'
    __table_args__ = (UniqueConstraint('player_id', 'season', 'squad', 'comp', 'is_national_team',
                                       name='uq_fbref_keeper_key'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey('fbref_players.id'), index=True, nullable=False)

    # Chaves de contexto
    season: Mapped[str] = mapped_column(String, nullable=False)
    squad: Mapped[str] = mapped_column(String, nullable=False)
    comp: Mapped[str] = mapped_column(String, nullable=False)
    is_national_team: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Colunas exclusivas do FBref para manter
    matches_completed: Mapped[Optional[int]] = _int()
    subs_in: Mapped[Optional[int]] = _int()
    subs_unused: Mapped[Optional[int]] = _int()
    team_ppm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    team_goals_on: Mapped[Optional[int]] = _int()
    team_goals_against_on: Mapped[Optional[int]] = _int()
    team_on_off: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    shots_on_target_against: Mapped[Optional[int]] = _int()
    wins: Mapped[Optional[int]] = _int()
    draws: Mapped[Optional[int]] = _int()
    losses: Mapped[Optional[int]] = _int()
    pens_allowed: Mapped[Optional[int]] = _int()
    pens_missed_gk: Mapped[Optional[int]] = _int()

    player: Mapped["FbrefPlayer"] = relationship(back_populates="keeper_stats")


# =====================================================================================
# Sofascore
# =====================================================================================
class SofascorePlayer(Base):
    __tablename__ = 'sofascore_players'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # ID do Sofascore
    name: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    current_team: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    current_league: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    nationality: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    footed: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # cm
    weight: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # kg
    # Resposta bruta de /characteristics (JSON), para não perder nenhum campo da API
    characteristics_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    stats: Mapped[List["SofascoreStat"]] = relationship(back_populates="player", cascade="all, delete-orphan")
    characteristics: Mapped[List["SofascoreCharacteristic"]] = relationship(
        back_populates="player", cascade="all, delete-orphan")
    positions: Mapped[List["SofascorePlayerPosition"]] = relationship(
        back_populates="player", cascade="all, delete-orphan")


class SofascorePlayerPosition(Base):
    """Posições em que o jogador atua segundo o Sofascore (ex.: ST, LW), na ordem devolvida pela API."""
    __tablename__ = 'sofascore_player_positions'
    __table_args__ = (UniqueConstraint('player_id', 'position', name='uq_sofascore_position'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey('sofascore_players.id'), index=True, nullable=False)
    position: Mapped[str] = mapped_column(String, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)  # ordem em que a API devolveu

    player: Mapped["SofascorePlayer"] = relationship(back_populates="positions")


class SofascoreCharacteristic(Base):
    """Pontos fortes (positive) e fracos (negative). `type_code` é o código numérico da API."""
    __tablename__ = 'sofascore_characteristics'
    __table_args__ = (UniqueConstraint('player_id', 'polarity', 'type_code', name='uq_sofascore_char'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey('sofascore_players.id'), index=True, nullable=False)
    polarity: Mapped[str] = mapped_column(String, nullable=False)  # 'positive' | 'negative'
    type_code: Mapped[int] = mapped_column(Integer, nullable=False)
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    player: Mapped["SofascorePlayer"] = relationship(back_populates="characteristics")


class SofascoreStat(Base):
    """Uma linha por jogador + competição + temporada + clube. Métricas brutas (colunas geradas
    a partir de core.sofascore_metrics.RAW_METRICS). NULL = o Sofascore não trouxe a métrica."""
    __tablename__ = 'sofascore_stats'
    __table_args__ = (UniqueConstraint('player_id', 'tournament_id', 'season_id', 'team_id',
                                       name='uq_sofascore_stat_key'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey('sofascore_players.id'), index=True, nullable=False)

    tournament_id: Mapped[int] = mapped_column(Integer, nullable=False)
    season_id: Mapped[int] = mapped_column(Integer, nullable=False)
    team_id: Mapped[int] = mapped_column(Integer, nullable=False)
    season: Mapped[Optional[str]] = mapped_column(String, nullable=True)       # ex.: '23/24' ou '2023'
    competition: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    squad: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    player: Mapped["SofascorePlayer"] = relationship(back_populates="stats")


# Gera uma coluna (nullable) por métrica bruta catalogada em core/sofascore_metrics.py
for _key, _kind in RAW_METRICS.items():
    setattr(SofascoreStat, column_name(_key), Column(Integer if _kind == 'int' else Float, nullable=True))


# =====================================================================================
# Transfermarkt
# =====================================================================================
class TransfermarktPlayer(Base):
    """Dados cadastrais e valor de mercado dos jogadores no Transfermarkt."""
    __tablename__ = 'transfermarkt_players'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # ID do Transfermarkt (spieler/<id>)
    name: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    shirt_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    position: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    birth_date: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    nationality: Mapped[str] = mapped_column(String, nullable=False, default="Brasil")
    secondary_nationality: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    current_club: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    league_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    league_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    market_value_raw: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # ex.: '€ 45,00 mi.'
    market_value_eur: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # ex.: 45000000
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


# =====================================================================================
# WhoScored
# =====================================================================================
class WhoscoredTeam(Base):
    """Clubes catalogados no WhoScored com características (pontos fortes, fracos, estilo)."""
    __tablename__ = 'whoscored_teams'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # whoscored_team_id
    team_name: Mapped[str] = mapped_column(String, nullable=False)
    team_url: Mapped[str] = mapped_column(String, nullable=False)
    league_code: Mapped[str] = mapped_column(String, nullable=False)
    league_name: Mapped[str] = mapped_column(String, nullable=False)
    strengths: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON string com lista de {name, level}
    weaknesses: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string com lista de {name, level}
    style: Mapped[Optional[str]] = mapped_column(Text, nullable=True)       # JSON string com lista de tópicos
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    players: Mapped[List["WhoscoredPlayer"]] = relationship(back_populates="team")


class WhoscoredPlayer(Base):
    """Jogadores brasileiros cadastrados no WhoScored (URL, perfil e características)."""
    __tablename__ = 'whoscored_players'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # whoscored_player_id
    name: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    player_url: Mapped[str] = mapped_column(String, nullable=False)
    current_team: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    shirt_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    birth_date: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    nationality: Mapped[Optional[str]] = mapped_column(String, nullable=True, default="Brasil")
    position: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    strengths: Mapped[Optional[str]] = mapped_column(Text, nullable=True)      # JSON list de {name, level}
    weaknesses: Mapped[Optional[str]] = mapped_column(Text, nullable=True)     # JSON list de {name, level}
    style_of_play: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list de strings
    whoscored_team_id: Mapped[Optional[int]] = mapped_column(ForeignKey('whoscored_teams.id'), nullable=True, index=True)
    team_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    league_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    league_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    team: Mapped[Optional["WhoscoredTeam"]] = relationship(back_populates="players")
    season_stats: Mapped[List["WhoscoredPlayerSeasonStat"]] = relationship(back_populates="player", cascade="all, delete-orphan")


class WhoscoredPlayerSeasonStat(Base):
    """Estatísticas históricas do jogador por temporada e torneio (Opção 2: Resumo + Métricas Táticas)."""
    __tablename__ = 'whoscored_player_season_stats'
    __table_args__ = (UniqueConstraint('player_id', 'season', 'team', 'competition', name='uq_whoscored_season_stat'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey('whoscored_players.id'), index=True, nullable=False)

    season: Mapped[str] = mapped_column(String, nullable=False)
    team: Mapped[str] = mapped_column(String, nullable=False)
    competition: Mapped[str] = mapped_column(String, nullable=False)

    matches: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    goals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    assists: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    motm: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Homem do Jogo / JdaP (Exclusivo WhoScored)
    rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Nota WhoScored (Exclusivo)
    through_balls_per_game: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # BEnfiada (Exclusivo)
    dispossessed_per_game: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Des (Exclusivo)
    unsuccessful_touches_per_game: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # DomErr (Exclusivo)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    player: Mapped["WhoscoredPlayer"] = relationship(back_populates="season_stats")


# =====================================================================================
# Integração entre fontes
# =====================================================================================
class PlayerMapping(Base):
    """Ponte Sofascore (Primária) <-> FBref <-> Transfermarkt <-> WhoScored (gerada por match_ids.py). 1-para-1 garantido."""
    __tablename__ = 'player_mapping'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sofascore_id: Mapped[Optional[int]] = mapped_column(ForeignKey('sofascore_players.id'), nullable=True, unique=True, index=True)
    fbref_db_id: Mapped[Optional[int]] = mapped_column(ForeignKey('fbref_players.id'), nullable=True, unique=True, index=True)
    transfermarkt_id: Mapped[Optional[int]] = mapped_column(ForeignKey('transfermarkt_players.id'), nullable=True, unique=True, index=True)
    whoscored_id: Mapped[Optional[int]] = mapped_column(ForeignKey('whoscored_players.id'), nullable=True, unique=True, index=True)
    merged_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)