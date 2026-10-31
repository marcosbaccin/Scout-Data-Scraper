"""
Utilitários de temporada compartilhados entre o motor analítico e o Explorador.

As 4 fontes usam rótulos diferentes para a mesma temporada:
- SofaScore : '25/26' (Europa) ou '2025' (ligas de ano-calendário: BRA, EUA, MEX, ARA)
- FBref     : '2025-2026' ou '2025'
- WhoScored : '2025/2026' ou '2025'
`normalize_season_label` converte todos para o formato SofaScore.
"""
from typing import Any


def normalize_season_label(label: Any) -> str:
    """'2025-2026' / '2025/2026' -> '25/26'. Demais rótulos são mantidos."""
    s = str(label or "").strip()
    if len(s) == 9 and s[4] in "-/" and s[:4].isdigit() and s[5:].isdigit():
        return f"{s[2:4]}/{s[7:9]}"
    return s


def season_year(label: Any) -> int:
    """Ano de encerramento da temporada, para ordenação cronológica ('25/26' -> 2026; '2025' -> 2025)."""
    s = str(label or "").strip()
    if "/" in s:
        tail = s.split("/")[-1].strip()
        if tail.isdigit():
            return 2000 + int(tail) if len(tail) == 2 else int(tail)
    if s.isdigit():
        return 2000 + int(s) if len(s) == 2 else int(s)
    return 0

