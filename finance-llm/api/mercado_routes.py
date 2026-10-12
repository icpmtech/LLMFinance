"""Rotas do módulo de inteligência de mercado (`/mercado/*`).

Cruza **CPV + CAE + contratos + empresas + entidades adjudicantes** para comparar
empresas dentro do seu mercado, medir dependências recíprocas com as entidades
públicas, seguir a evolução temporal e simular alterações na rede.

- Leitura pública: `GET /mercado/meta`, `/mercado/mercados`, `/mercado/benchmark`,
  `/mercado/empresa/{nif}`, `/mercado/pares`, `/mercado/dependencias`,
  `/mercado/grafo`, `/mercado/cenarios`, `/mercado/sensibilidade`,
  `/mercado/evidencias`, `/mercado/execucoes[/{run_id}]`, `/mercado/tabela`.
- Escrita (exige sessão): `PUT /mercado/tabela`, `POST /mercado/execucoes`.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import lorenz_service as lz
from api import mercado_service as mercado
from api.auth_routes import CurrentSession, require_session

router = APIRouter(prefix="/mercado", tags=["mercado"])

Session = Annotated[CurrentSession, Depends(require_session)]


# ------------------------------------------------------------------ modelos
class RegraCaeCpv(BaseModel):
    """Uma regra da tabela CPV↔CAE."""

    cae: str = Field(..., min_length=1, max_length=8, description="Prefixo do código CAE")
    cpv: str = Field(..., min_length=1, max_length=8, description="Prefixo do código CPV")
    grau: str = Field(..., description="alta | média | baixa")
    nota: Optional[str] = Field(None, max_length=300)
    fonte: Optional[str] = Field(None, max_length=200)


class TabelaRequest(BaseModel):
    """Substituição da tabela CPV↔CAE e/ou dos parâmetros."""

    regras: List[RegraCaeCpv]
    parametros: Optional[Dict[str, Any]] = None


class ExecucaoRequest(BaseModel):
    """Guardar um benchmark calculado (exige sessão)."""

    titulo: Optional[str] = Field(None, max_length=200)
    area: Optional[str] = None
    cpv: Optional[str] = None
    ano_de: Optional[int] = Field(None, ge=1900, le=2100)
    ano_ate: Optional[int] = Field(None, ge=1900, le=2100)
    regiao: Optional[str] = None
    nif: Optional[str] = None
    nifs: Optional[List[str]] = None
    limite: Optional[int] = Field(None, ge=1, le=60)


# ------------------------------------------------------------------ utilidades
def _escopo(
    area: Optional[str],
    cpv: Optional[str],
    ano_de: Optional[int],
    ano_ate: Optional[int],
    regiao: Optional[str],
    nif: Optional[str],
    valor_min: Optional[float],
    valor_max: Optional[float],
    texto: Optional[str],
) -> Dict[str, Any]:
    if ano_de and ano_ate and ano_de > ano_ate:
        raise HTTPException(status_code=422, detail="`ano_de` não pode ser maior que `ano_ate`")
    return lz.escopo(
        area=area,
        cpv=cpv,
        ano_de=ano_de,
        ano_ate=ano_ate,
        regiao=regiao,
        nif=nif,
        valor_min=valor_min,
        valor_max=valor_max,
        texto=texto,
    )


# ------------------------------------------------------------------ metadados
@router.get("/meta", summary="Metamodelo: camadas, indicadores, eventos e tabela CPV↔CAE")
def mercado_meta() -> Dict[str, Any]:
    return mercado.meta()


@router.get("/tabela", summary="Tabela CPV↔CAE atual e parâmetros")
def mercado_tabela() -> Dict[str, Any]:
    return {"regras": mercado.regras_cae_cpv(), "parametros": mercado.parametros(), "graus": mercado.GRAUS}


@router.put("/tabela", summary="Substituir a tabela CPV↔CAE e/ou os parâmetros (exige sessão)")
def mercado_guardar_tabela(pedido: TabelaRequest, session: Session = None) -> Dict[str, Any]:
    return mercado.guardar_tabela([regra.model_dump() for regra in pedido.regras], pedido.parametros)


@router.get("/compatibilidade", summary="Grau de compatibilidade entre um CAE e um CPV")
def mercado_compatibilidade(
    cae: str = Query(..., description="Código CAE (ex.: 46460)"),
    cpv: str = Query(..., description="Código ou prefixo de CPV (ex.: 33600000-6)"),
) -> Dict[str, Any]:
    return mercado.compatibilidade(cae, cpv)


# ------------------------------------------------------------------ mercados
@router.get("/mercados", summary="Mercados comparáveis (classe de CPV × CAE × período)")
def mercado_mercados(
    area: Optional[str] = Query(None, description="Área predefinida (ver /lorenz/areas)"),
    cpv: Optional[str] = Query(None, description="Prefixos de CPV separados por vírgula"),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None),
    nif: Optional[str] = Query(None),
    valor_min: Optional[float] = Query(None, ge=0),
    valor_max: Optional[float] = Query(None, ge=0),
    texto: Optional[str] = Query(None),
    top: int = Query(12, ge=1, le=30, description="Nº de mercados (classes de CPV) a devolver"),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, cpv, ano_de, ano_ate, regiao, nif, valor_min, valor_max, texto)
    return mercado.mercados(escopo_def, top=top)


@router.get("/benchmark", summary="Benchmark entre empresas do mesmo mercado")
def mercado_benchmark(
    area: Optional[str] = Query(None),
    cpv: Optional[str] = Query(None),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None),
    nif: Optional[str] = Query(None),
    valor_min: Optional[float] = Query(None, ge=0),
    valor_max: Optional[float] = Query(None, ge=0),
    texto: Optional[str] = Query(None),
    nifs: Optional[str] = Query(None, description="NIFs das empresas a comparar, separados por vírgula"),
    limite: int = Query(20, ge=1, le=60, description="Nº de empresas quando não são indicados NIFs"),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, cpv, ano_de, ano_ate, regiao, nif, valor_min, valor_max, texto)
    lista = [nif.strip() for nif in (nifs or "").split(",") if nif.strip()]
    return mercado.benchmark(escopo_def, nifs=lista or None, cpv=cpv, limite=limite)


@router.get("/empresa/{nif}", summary="Ficha de mercado de uma empresa")
def mercado_empresa(
    nif: str,
    area: Optional[str] = Query(None),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, None, ano_de, ano_ate, regiao, None, None, None, None)
    ficha = mercado.empresa(nif, escopo_def=escopo_def)
    if ficha.get("erro"):
        raise HTTPException(status_code=502, detail=ficha["erro"])
    return ficha


@router.get("/pares", summary="Empresas comparáveis (mesmos CPV, CAE compatível, mesmo período)")
def mercado_pares(
    nif: str = Query(..., description="NIF da empresa de referência"),
    area: Optional[str] = Query(None),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None),
    limite: int = Query(12, ge=1, le=40),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, None, ano_de, ano_ate, regiao, None, None, None, None)
    return mercado.pares(nif, escopo_def=escopo_def, limite=limite)


@router.get("/dependencias", summary="Dependências recíprocas: empresa→entidades e entidade→fornecedores")
def mercado_dependencias(
    area: Optional[str] = Query(None),
    cpv: Optional[str] = Query(None),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None),
    nifs: Optional[str] = Query(None, description="NIFs das empresas, separados por vírgula"),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, cpv, ano_de, ano_ate, regiao, None, None, None, None)
    lista = [nif.strip() for nif in (nifs or "").split(",") if nif.strip()]
    return mercado.dependencias(escopo_def, nifs=lista or None)


@router.get("/grafo", summary="Grafo temporal empresa → contrato → entidade → CPV → CAE")
def mercado_grafo(
    area: Optional[str] = Query(None),
    cpv: Optional[str] = Query(None),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None),
    nifs: Optional[str] = Query(None),
    contratos: int = Query(24, ge=0, le=50, description="Contratos (maiores por valor) a incluir como nós"),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, cpv, ano_de, ano_ate, regiao, None, None, None, None)
    lista = [nif.strip() for nif in (nifs or "").split(",") if nif.strip()]
    return mercado.grafo_temporal(escopo_def, nifs=lista or None, contratos=contratos)


# ------------------------------------------------------------------ cenários
@router.get("/cenarios", summary="Eventos simulados (World Model) + sensibilidade (Lorenz)")
def mercado_cenarios(
    area: Optional[str] = Query(None),
    cpv: Optional[str] = Query(None),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None),
    nif: Optional[str] = Query(None, description="Empresa alvo dos eventos que a referem"),
    entidade_nif: Optional[str] = Query(None),
    fornecedor_nif: Optional[str] = Query(None),
    horizonte_dias: Optional[int] = Query(None, ge=30, le=730),
    forca_relativa: float = Query(1.0, ge=0.0, le=5.0, description="Força do novo concorrente (× mediana do mercado)"),
    variacao_precos: Optional[float] = Query(None, ge=-0.5, le=1.0),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, cpv, ano_de, ano_ate, regiao, None, None, None, None)
    return mercado.cenarios(
        escopo_def,
        nif=nif,
        entidade_nif=entidade_nif,
        fornecedor_nif=fornecedor_nif,
        horizonte_dias=horizonte_dias,
        forca_relativa=forca_relativa,
        variacao_precos=variacao_precos,
    )


@router.get("/sensibilidade", summary="Motor Lorenz aplicado à série do mercado")
def mercado_sensibilidade(
    area: Optional[str] = Query(None),
    cpv: Optional[str] = Query(None),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, cpv, ano_de, ano_ate, regiao, None, None, None, None)
    return mercado.sensibilidade(escopo_def)


@router.get("/evidencias", summary="Contratos que sustentam um indicador")
def mercado_evidencias(
    area: Optional[str] = Query(None),
    cpv: Optional[str] = Query(None),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None),
    comprador_nif: Optional[str] = Query(None),
    fornecedor_nif: Optional[str] = Query(None),
    cpv_prefixo: Optional[str] = Query(None),
    limite: int = Query(15, ge=1, le=50),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, cpv, ano_de, ano_ate, regiao, None, None, None, None)
    return lz.evidencias(
        escopo_def,
        comprador_nif=comprador_nif,
        fornecedor_nif=fornecedor_nif,
        cpv_prefixo=cpv_prefixo,
        limite=limite,
    )


# ------------------------------------------------------------------ execuções
@router.post("/execucoes", summary="Calcular e guardar um benchmark (exige sessão)")
def mercado_guardar_execucao(pedido: ExecucaoRequest, session: Session = None) -> Dict[str, Any]:
    escopo_def = _escopo(pedido.area, pedido.cpv, pedido.ano_de, pedido.ano_ate, pedido.regiao, pedido.nif, None, None, None)
    resultado = mercado.benchmark(escopo_def, nifs=pedido.nifs, cpv=pedido.cpv, limite=pedido.limite)
    if resultado.get("erro"):
        raise HTTPException(status_code=502, detail=resultado["erro"])
    autor = getattr(getattr(session, "user", None), "email", None) if session else None
    guardado = mercado.guardar_execucao(escopo_def, resultado, autor=autor, titulo=pedido.titulo)
    if guardado.get("erro"):
        raise HTTPException(status_code=502, detail=guardado["erro"])
    return {**guardado, "mercado": resultado.get("mercado")}


@router.get("/execucoes", summary="Execuções guardadas")
def mercado_execucoes(limite: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    return {"itens": mercado.listar_execucoes(limite=limite)}


@router.get("/execucoes/{run_id}", summary="Execução guardada (fotografia completa)")
def mercado_execucao(run_id: str) -> Dict[str, Any]:
    documento = mercado.obter_execucao(run_id)
    if not documento:
        raise HTTPException(status_code=404, detail="Execução não encontrada")
    return documento
