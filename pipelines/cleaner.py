import os
import re
import sys
from datetime import datetime

import pandas as pd

# Ajusta o path para importar o pacote core a partir da raiz do projeto
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.database import get_session
from core.models import FbrefKeeperStat, FbrefOutfieldStat, FbrefPlayer, PlayerMapping, SofascorePlayer
from core.settings import FBREF_DATA_DIR as DATA_DIR

KEYS = ['Season', 'Squad', 'Comp']
SEASON_RE = re.compile(r'^\d{4}(-\d{4})?$')  # descarta cabeçalhos repetidos, NaN e subtotais ("2 Seasons")

# Coluna do FBref (último segmento do cabeçalho achatado) -> coluna do banco.
# Contém APENAS as colunas exclusivas solicitadas para manter.
_PLAYING_TIME = {
    'Compl': 'matches_completed',
    'Subs': 'subs_in',
    'unSub': 'subs_unused',
    'PPM': 'team_ppm',
    'onG': 'team_goals_on',
    'onGA': 'team_goals_against_on',
    'On-Off': 'team_on_off',
}
OUTFIELD_MAPS = {
    'playing_time': _PLAYING_TIME,
}
KEEPER_MAPS = {
    'keeper': {
        'SoTA': 'shots_on_target_against',
        'W': 'wins',
        'D': 'draws',
        'L': 'losses',
        'PKA': 'pens_allowed',
        'PKm': 'pens_missed_gk',
    },
    'playing_time': _PLAYING_TIME,
}
FLOAT_COLS = {'team_ppm', 'team_on_off'}
SCOPES = {'expanded': False, 'nat_tm': True}  # scope -> is_national_team


def parse_info_txt(file_path):
    info = {}
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if ':' in line:
                key, val = line.split(':', 1)
                info[key.strip()] = val.strip()
    return info


def _to_number(series, as_float=False):
    cleaned = series.astype(str).str.replace(',', '', regex=False).str.replace('+', '', regex=False)
    num = pd.to_numeric(cleaned, errors='coerce')
    return num if as_float else num.round().astype('Int64')


def read_category(player_dir, cat, scope, col_map):
    """Lê um CSV do FBref e devolve DataFrame indexado pelas chaves, só com as colunas brutas mapeadas."""
    csv_path = os.path.join(player_dir, f"stats_{cat}_{scope}.csv")
    if not os.path.exists(csv_path):
        return None
    try:
        df = pd.read_csv(csv_path, dtype=str)
    except Exception as e:
        print(f"       [!] CSV ilegível {csv_path}: {e}")
        return None
    if df.empty or not all(k in df.columns for k in KEYS):
        return None

    # 1. Mantém só linhas reais de temporada (remove cabeçalhos repetidos, NaN e subtotais)
    df = df[df['Season'].astype(str).str.match(SEASON_RE) & df['Squad'].notna() & df['Comp'].notna()]
    if df.empty:
        return None

    # 2. Remove colunas "Per 90" antes de achatar (colidiriam com as colunas brutas de mesmo nome)
    df = df[[c for c in df.columns if 'Per 90' not in c]]

    # 3. Achata o cabeçalho ("Performance_Gls" -> "Gls"), mantendo a primeira ocorrência
    df.columns = [c if c in KEYS else c.rsplit('_', 1)[-1] for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]

    out = df[KEYS].copy()
    for src, dst in col_map.items():
        if src in df.columns:
            out[dst] = _to_number(df[src], as_float=dst in FLOAT_COLS)

    # Duplicatas reais (mesma temporada/clube/competição) seriam ambíguas: mantém a primeira
    out = out.drop_duplicates(subset=KEYS, keep='first')
    return out.set_index(KEYS)


def build_stats(player_dir, maps):
    """Une as categorias (outer join pelas chaves) por escopo (clube / seleção)."""
    frames = []
    for scope, is_national in SCOPES.items():
        merged = None
        for cat, col_map in maps.items():
            df = read_category(player_dir, cat, scope, col_map)
            if df is None:
                continue
            # combine_first faz o outer join e preenche valores ausentes com a categoria seguinte
            merged = df if merged is None else merged.combine_first(df)
        if merged is not None and not merged.empty:
            merged = merged.reset_index()
            merged['is_national_team'] = is_national
            frames.append(merged)
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def _clean(value):
    """NaN/NA -> None; numpy -> tipos nativos (NULL no banco = métrica não informada)."""
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, 'item') else value


def stats_rows(df, model, player_id):
    columns = {c.name for c in model.__table__.columns}
    rows = []
    for record in df.to_dict(orient='records'):
        data = {'player_id': player_id}
        for key, val in record.items():
            col = {'Season': 'season', 'Squad': 'squad', 'Comp': 'comp'}.get(key, key)
            if col in columns:
                data[col] = _clean(val)
        rows.append(model(**data))
    return rows


def parse_player_info(info, is_keeper):
    position = info.get('Position')
    if not position or position == 'None':
        position = "GK" if is_keeper else "Outfield"

    birth = None
    raw_birth = info.get('BirthDate')
    if raw_birth and raw_birth != 'None':
        try:
            birth = datetime.strptime(raw_birth, '%Y-%m-%d').date()
        except ValueError:
            birth = None

    # O scraper só coleta jogadores com nacionalidade BRA no elenco; quando a página do jogador
    # não traz "Citizenship" (~30% dos casos) assumimos o filtro de coleta.
    nationality = info.get('Nationality')
    if not nationality or nationality == 'None':
        nationality = 'Brazil'

    foot = info.get('Footed')
    foot = foot if foot and foot != 'None' else None

    def _num(key):
        raw = info.get(key)
        return int(raw) if raw and raw.isdigit() else None

    return dict(
        name=info.get('Name', 'Unknown'), birth_date=birth, nationality=nationality,
        primary_position=position, footed=foot, height=_num('Height'), weight=_num('Weight'),
    )


def process_players():
    session = get_session()
    print("[*] Iniciando o Pipeline de Limpeza e Carga de Dados (FBref)...")
    loaded = skipped = 0

    # Cache de jogadores do Sofascore mapeados para respeitar a regra:
    # nationality, footed, height, weight só são persistidas se NÃO foram coletadas no SofaScore
    sofa_lookup = {}
    try:
        mappings = session.query(PlayerMapping).all()
        for m in mappings:
            if m.sofascore_id:
                sp = session.get(SofascorePlayer, m.sofascore_id)
                if sp:
                    sofa_lookup[m.fbref_db_id] = sp
    except Exception:
        pass

    for player_id in sorted(os.listdir(DATA_DIR)):
        player_dir = os.path.join(DATA_DIR, player_id)
        info_file = os.path.join(player_dir, 'info.txt')
        if not os.path.isdir(player_dir) or not os.path.exists(info_file):
            continue

        info = parse_info_txt(info_file)
        is_keeper = (
            info.get('Position', '').startswith('GK')
            or any(os.path.exists(os.path.join(player_dir, f"stats_keeper_{s}.csv")) for s in SCOPES)
        )
        fields = parse_player_info(info, is_keeper)

        # Upsert: recarrega jogador e estatísticas (pipeline idempotente)
        player = session.query(FbrefPlayer).filter_by(fbref_id=player_id).first()

        # Se já mapeado no Sofascore e o Sofascore possui a coluna, não persiste no FBref
        if player and player.id in sofa_lookup:
            sp = sofa_lookup[player.id]
            if sp.nationality:
                fields['nationality'] = None
            if sp.footed:
                fields['footed'] = None
            if sp.height is not None:
                fields['height'] = None
            if sp.weight is not None:
                fields['weight'] = None

        if player is None:
            player = FbrefPlayer(fbref_id=player_id, **fields)
            session.add(player)
        else:
            for key, val in fields.items():
                setattr(player, key, val)
            player.outfield_stats.clear()
            player.keeper_stats.clear()
        session.flush()

        if is_keeper:
            df = build_stats(player_dir, KEEPER_MAPS)
            model = FbrefKeeperStat
        else:
            df = build_stats(player_dir, OUTFIELD_MAPS)
            model = FbrefOutfieldStat

        if df is None:
            skipped += 1
            print(f"    [!] Sem estatísticas utilizáveis: {fields['name']} ({player_id})")
        else:
            session.add_all(stats_rows(df, model, player.id))
            loaded += 1

        if (loaded + skipped) % 100 == 0:
            session.commit()

    session.commit()
    session.close()
    print(f"\n[+] Pipeline finalizado! {loaded} jogadores com estatísticas, {skipped} sem estatísticas.")


if __name__ == "__main__":
    process_players()