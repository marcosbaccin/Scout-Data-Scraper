"""
Rotas do Explorador de Jogadores (busca configurável por qualquer estatística coletada).

- GET  /explorer/schema  : catálogo de estatísticas, opções de filtros, perfis prontos.
- POST /explorer/bounds  : limites reais de cada estatística no recorte (escala dos sliders).
- POST /explorer/search  : busca paginada com filtros de identificação + faixas por estatística.
- POST /explorer/sheet   : ficha completa do atleta (todas as estatísticas por categoria).
- POST /explorer/export  : download CSV com todos os resultados.
"""
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from explorer_engine import (
    ExplorerError,
    ExplorerQuery,
    ScopeSpec,
    SheetRequest,
    get_engine,
)

router = APIRouter(prefix="/explorer", tags=["Explorador"])


def _guard(fn, *args):
    try:
        return fn(*args)
    except ExplorerError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/schema")
def explorer_schema() -> Dict[str, Any]:
    """Catálogo completo: estatísticas (rótulo, categoria, unidade, modos), opções de filtros e perfis prontos."""
    return _guard(get_engine().schema)


@router.get("/players")
def explorer_players() -> Dict[str, Any]:
    """Diretório leve de todos os atletas monitorados para seleção rápida e comparação no Raio-X & Radar."""
    items = _guard(get_engine().players_directory)
    return {"total": len(items), "players": items}


@router.post("/bounds")
def explorer_bounds(scope: ScopeSpec) -> Dict[str, Any]:
    """Mínimo/máximo/passo de cada estatística (total, por 90' e percentil) dentro do recorte informado."""
    return _guard(get_engine().bounds, scope)


@router.post("/search")
def explorer_search(query: ExplorerQuery) -> Dict[str, Any]:
    """Aplica o perfil configurado (identificação + faixas estatísticas) e devolve a página de atletas."""
    return _guard(get_engine().search, query)


@router.post("/sheet")
def explorer_sheet(req: SheetRequest) -> Dict[str, Any]:
    """Ficha completa do atleta no recorte, com total, por 90' e percentil de cada estatística."""
    sheet = _guard(get_engine().sheet, req)
    if sheet is None:
        raise HTTPException(status_code=404, detail="Atleta sem estatísticas no recorte selecionado.")
    return sheet


@router.post("/export")
def explorer_export(query: ExplorerQuery) -> Response:
    """Exporta TODOS os resultados do perfil (sem paginação) em CSV, com totais e valores por 90'."""
    csv_text = _guard(get_engine().export_csv, query)
    filename = f"scout_explorer_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        content="\ufeff" + csv_text,  # BOM: abre corretamente com acentos no Excel
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

