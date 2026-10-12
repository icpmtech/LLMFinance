"""Rotas da importação dos **Contratos Públicos do Portal Base** (dados.gov.pt).

- `GET  /base-impic/recursos`        — ficheiros publicados por ano (zip/xlsx)
- `GET  /base-impic/formato/{ano}`   — formato do ZIP do ano (membro, campos, exemplo)
- `GET  /base-impic/amostra/{ano}`   — primeiros contratos já normalizados
- `POST /base-impic/importar`        — descarregar + normalizar + indexar (segundo plano)
- `GET  /base-impic/estado`          — progresso das importações e volumetria do índice
- `POST /base-impic/cancelar/{ano}`  — pedir a paragem de uma importação

Escrever exige sessão (é uma operação de administração); ler é aberto a quem tem
sessão, para a página poder mostrar o catálogo e o formato.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api import base_impic
from api.auth_routes import CurrentSession, optional_session, require_session

router = APIRouter(prefix="/base-impic", tags=["base-impic"])

Session = Annotated[CurrentSession, Depends(require_session)]
ReadSession = Annotated[CurrentSession, Depends(optional_session)]


class ImportarPayload(BaseModel):
    """Parâmetros da importação de um ano do Portal Base.

    A importação **só acrescenta contratos que ainda não existem** no índice: os
    que já lá estão (mesmo `idcontrato`) são ignorados e contados à parte.
    """

    ano: Optional[int] = Field(None, description="Ano a importar (por omissão, o mais recente)")
    limite: Optional[int] = Field(None, ge=1, le=2_000_000, description="Máximo de contratos (ensaio)")
    descarregar: bool = Field(True, description="Descarregar o ZIP do dados.gov.pt se ainda não estiver em cache")


def _email(session: CurrentSession) -> str:
    return str(getattr(getattr(session, "user", None), "email", "") or "")


@router.get("/recursos")
def base_recursos(session: ReadSession = None, forcar: bool = False) -> Dict[str, Any]:
    """Ficheiros do conjunto no dados.gov.pt, com o ano atual e a cache local."""
    recursos = base_impic.listar_recursos(forcar=forcar)
    return {
        "dataset": base_impic.DATASET_SLUG,
        "url_dataset": "https://dados.gov.pt/pt/datasets/" + base_impic.DATASET_SLUG + "/",
        "ano_atual": base_impic.ano_atual(),
        "anos": base_impic.anos_disponiveis(recursos),
        "recursos": recursos,
        "em_cache": base_impic.cache_local(),
        "indice": base_impic.resumo_indice(),
    }


@router.get("/formato/{ano}")
def base_formato(ano: str, session: ReadSession = None, descarregar: bool = False) -> Dict[str, Any]:
    """Formato do ZIP do ano: que ficheiro traz, forma do JSON, campos e exemplo."""
    if not str(ano).isdigit():
        raise HTTPException(status_code=400, detail="Indique o ano (ex.: 2026).")
    return base_impic.inspecionar(ano, descarregar_se_preciso=descarregar)


@router.get("/amostra/{ano}")
def base_amostra(ano: str, session: ReadSession = None, registos: int = 3) -> Dict[str, Any]:
    """Primeiros contratos do ZIP, já normalizados (o que vai para o Elasticsearch)."""
    if not str(ano).isdigit():
        raise HTTPException(status_code=400, detail="Indique o ano (ex.: 2026).")
    return base_impic.amostra(ano, registos=max(1, min(int(registos), 20)))


@router.post("/importar")
def base_importar(payload: ImportarPayload, session: Session) -> Dict[str, Any]:
    """Arranca a importação de um ano em segundo plano."""
    ano = payload.ano or base_impic.ano_atual()
    recursos = base_impic.listar_recursos()
    if not base_impic.encontrar_recurso(recursos, ano, "zip"):
        raise HTTPException(status_code=404, detail=f"Não há ZIP de {ano} em dados.gov.pt.")
    resultado = base_impic.importar(
        ano,
        limite=payload.limite,
        descarregar_se_preciso=payload.descarregar,
        utilizador=_email(session),
    )
    return {**resultado, "estado": base_impic.estado(ano)}


@router.get("/estado")
def base_estado(session: ReadSession = None) -> Dict[str, Any]:
    """Progresso das importações e o que já está indexado, por ano."""
    return {
        "trabalhos": base_impic.estado(),
        "indice": base_impic.resumo_indice(),
        "em_cache": base_impic.cache_local(),
        "ano_atual": base_impic.ano_atual(),
    }


@router.post("/cancelar/{ano}")
def base_cancelar(ano: str, session: Session) -> Dict[str, Any]:
    """Pede a paragem da importação de um ano."""
    if not str(ano).isdigit():
        raise HTTPException(status_code=400, detail="Indique o ano (ex.: 2026).")
    return base_impic.cancelar(int(ano))


@router.get("/anos")
def base_anos(session: ReadSession = None) -> Dict[str, Any]:
    """Anos disponíveis (para o formulário)."""
    recursos = base_impic.listar_recursos()
    return {"anos": base_impic.anos_disponiveis(recursos), "ano_atual": base_impic.ano_atual()}
