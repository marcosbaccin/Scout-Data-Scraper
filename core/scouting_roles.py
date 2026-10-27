"""
Mapeamento e Padronização de Funções Táticas e Posicionais de Scouting.

Categoriza qualquer nomenclatura de posição das 4 fontes (SofaScore, FBref, Transfermarkt, WhoScored)
em 7 Funções Táticas Principais (Scout Roles) e 4 Macro-Categorias (Scout Categories).

Funções Táticas (scout_role):
- GK    : Goleiro (Goalkeeper)
- CB    : Zagueiro Central (Centre-Back)
- FB    : Lateral / Ala Direito ou Esquerdo (Full-Back / Wing-Back)
- DM    : Volante / Meio-Campo Defensivo (Defensive Midfielder)
- CM_AM : Meia Central / Meia Ofensivo / Armador (Central / Attacking Midfielder)
- WNG   : Ponta / Extremo / Atacante de Lado (Winger)
- ST    : Centroavante / Homem de Área (Striker / Centre-Forward)

Macro-Categorias (scout_category):
- GK  : Goleiros
- DEF : Linha de Defesa (CB, FB)
- MID : Linha de Meio-Campo (DM, CM_AM)
- ATT : Linha de Ataque (WNG, ST)
"""
import unicodedata
from typing import Tuple


def normalize_str(text: str) -> str:
    """Remove acentuação, casing e espaços excedentes."""
    if not text:
        return ""
    nfkd = unicodedata.normalize('NFKD', str(text))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def classify_position(raw_pos: str) -> Tuple[str, str]:
    """
    Classifica uma string de posição em (scout_role, scout_category).
    Retorna tupla com (role, category), ex: ('ST', 'ATT') ou ('CB', 'DEF').
    """
    p = normalize_str(raw_pos)
    if not p:
        return "MID", "MID"

    # 1. Goleiro
    if any(k in p for k in ['gol', 'gk', 'guarda-redes', 'guarda redes', 'portero']) or p == 'g':
        return "GK", "GK"

    # 2. Ponta / Extremo (avaliado antes de atacante genérico)
    if any(k in p for k in ['ponta', 'winger', 'extremo', 'segundo ponta', 'm(d)', 'm(e)', 'a(d)', 'a(e)']):
        return "WNG", "ATT"

    # 3. Lateral / Ala (avaliado antes de zagueiro/defesa genérica)
    if any(k in p for k in ['lateral', 'ala', 'full-back', 'wing-back', 'left back', 'right back',
                           'lb', 'rb', 'lwb', 'rwb', 'd(d)', 'd(e)']):
        return "FB", "DEF"

    # 4. Zagueiro
    if any(k in p for k in ['zagueiro', 'centre-back', 'central defender', 'cb', 'd(c)', 'libero']):
        return "CB", "DEF"

    # 5. Volante
    if any(k in p for k in ['volante', 'defensive midfield', 'dm', 'md', 'trinco']):
        return "DM", "MID"

    # 6. Centroavante / Homem de Área
    if any(k in p for k in ['centroavante', 'striker', 'centre-forward', 'pl', 'ponta de lanca',
                           'segundo atacante', 'segundo avancado', 'cf']):
        return "ST", "ATT"

    # 7. Meia Central / Ofensivo
    if any(k in p for k in ['meio-campo', 'meia', 'attacking midfield', 'central midfield',
                           'am', 'cm', 'mc', 'playmaker', 'armador', 'cam', 'm(c)']):
        return "CM_AM", "MID"

    # 8. Genéricos de códigos curtos (FBref e SofaScore)
    if p in ['df', 'defesa', 'd']:
        return "CB", "DEF"
    if p in ['fw', 'atacante', 'avancado', 'f']:
        return "ST", "ATT"
    if p in ['mf', 'medio', 'm']:
        return "CM_AM", "MID"

    # Fallback
    return "MID", "MID"


def sql_scout_role_case(column_name: str) -> str:
    """Gera cláusula CASE SQL para categorizar a posição diretamente no SQLite."""
    c = f"LOWER({column_name})"
    return f"""
    CASE
        WHEN {c} LIKE '%gol%' OR {c} LIKE '%gk%' OR {c} LIKE '%guarda%' OR {c} = 'g' THEN 'GK'
        WHEN {c} LIKE '%ponta%' OR {c} LIKE '%winger%' OR {c} LIKE '%extremo%' OR {c} LIKE '%m(d)%' OR {c} LIKE '%m(e)%' OR {c} LIKE '%a(d)%' OR {c} LIKE '%a(e)%' THEN 'WNG'
        WHEN {c} LIKE '%lateral%' OR {c} LIKE '%ala%' OR {c} LIKE '%back%' OR {c} LIKE '%lb%' OR {c} LIKE '%rb%' OR {c} LIKE '%d(d)%' OR {c} LIKE '%d(e)%' THEN 'FB'
        WHEN {c} LIKE '%zagueiro%' OR {c} LIKE '%centre-back%' OR {c} LIKE '%cb%' OR {c} LIKE '%d(c)%' OR {c} = 'df' THEN 'CB'
        WHEN {c} LIKE '%volante%' OR {c} LIKE '%defensive mid%' OR {c} LIKE '%dm%' THEN 'DM'
        WHEN {c} LIKE '%centroavante%' OR {c} LIKE '%striker%' OR {c} LIKE '%centre-forward%' OR {c} LIKE '%cf%' OR {c} LIKE '%pl%' OR {c} = 'fw' THEN 'ST'
        WHEN {c} LIKE '%meio%' OR {c} LIKE '%meia%' OR {c} LIKE '%midfield%' OR {c} LIKE '%cm%' OR {c} LIKE '%am%' OR {c} LIKE '%mc%' OR {c} = 'mf' OR {c} = 'm' THEN 'CM_AM'
        WHEN {c} LIKE '%atacante%' OR {c} = 'f' THEN 'ST'
        WHEN {c} LIKE '%defesa%' OR {c} = 'd' THEN 'CB'
        ELSE 'CM_AM'
    END
    """


def sql_scout_category_case(role_column_name: str) -> str:
    """Gera cláusula CASE SQL para converter scout_role em scout_category."""
    return f"""
    CASE
        WHEN {role_column_name} = 'GK' THEN 'GK'
        WHEN {role_column_name} IN ('CB', 'FB') THEN 'DEF'
        WHEN {role_column_name} IN ('DM', 'CM_AM') THEN 'MID'
        WHEN {role_column_name} IN ('WNG', 'ST') THEN 'ATT'
        ELSE 'MID'
    END
    """
