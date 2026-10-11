"""Rotas do modelo Lorenz 1963 (`/lorenz/*`) — dinâmica da contratação pública.

Serve qualquer **área** (prefixos de CPV), região, entidade e intervalo de anos;
o módulo não está preso à saúde — a saúde é apenas uma das áreas predefinidas em
`data/lorenz/config.json`.

- Leitura pública: `GET /lorenz/meta`, `GET /lorenz/areas`, `GET /lorenz/panorama`,
  `GET /lorenz/serie`, `GET /lorenz/grafo`, `GET /lorenz/propagacao`,
  `GET /lorenz/cenarios`, `GET /lorenz/cpv`, `GET /lorenz/entidades`,
  `GET /lorenz/evidencias`, `GET /lorenz/execucoes[/{run_id}]`.
- Escrita (exige sessão): `PUT /lorenz/areas`, `POST /lorenz/execucoes`.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import lorenz_service as lorenz
from api.auth_routes import CurrentSession, require_session

router = APIRouter(prefix="/lorenz", tags=["lorenz"])

Session = Annotated[CurrentSession, Depends(require_session)]


# ------------------------------------------------------------------ modelos
class AreaModel(BaseModel):
    """Área de contratação: um conjunto de prefixos de CPV."""

    id: str = Field(..., min_length=1, max_length=60, description="Identificador estável (sem espaços)")
    label: str = Field(..., min_length=1, max_length=160)
    cpv_prefixos: List[str] = Field(default_factory=list, description="Prefixos de CPV (ex.: ['33','851']); vazio = todas as áreas")
    descricao: Optional[str] = Field(None, max_length=400)


class AreasRequest(BaseModel):
    """Gravação das áreas (substitui a lista) e, opcionalmente, dos parâmetros."""

    areas: List[AreaModel]
    parametros: Optional[Dict[str, Any]] = None


class ExecucaoRequest(BaseModel):
    """Execução guardada: ou um `panorama` já calculado, ou um escopo para calcular."""

    titulo: Optional[str] = Field(None, max_length=200)
    area: Optional[str] = None
    cpv: Optional[str] = None
    ano_de: Optional[int] = Field(None, ge=1900, le=2100)
    ano_ate: Optional[int] = Field(None, ge=1900, le=2100)
    regiao: Optional[str] = None
    nif: Optional[str] = None
    valor_min: Optional[float] = None
    valor_max: Optional[float] = None


# ------------------------------------------------------------------ utilidades
def _escopo(
    area: Optional[str],
    cpv: Optional[str],
    ano_de: Optional[int],
    ano_ate: Optional[int],
    regiao: Optional[str],
    nif: Optional[str],
    nif_contraparte: Optional[str],
    valor_min: Optional[float],
    valor_max: Optional[float],
    texto: Optional[str],
    ecologico: Optional[bool],
) -> Dict[str, Any]:
    if ano_de and ano_ate and ano_de > ano_ate:
        raise HTTPException(status_code=422, detail="`ano_de` não pode ser maior que `ano_ate`")
    return lorenz.escopo(
        area=area,
        cpv=cpv,
        ano_de=ano_de,
        ano_ate=ano_ate,
        regiao=regiao,
        nif=nif,
        nif_contraparte=nif_contraparte,
        valor_min=valor_min,
        valor_max=valor_max,
        texto=texto,
        ecologico=ecologico,
    )


# ------------------------------------------------------------------ metadados
@router.get("/meta", summary="Metamodelo do módulo (arquitetura, áreas, parâmetros)")
def lorenz_meta() -> Dict[str, Any]:
    return lorenz.meta()


@router.get("/areas", summary="Áreas de contratação disponíveis (prefixos de CPV)")
def lorenz_areas() -> Dict[str, Any]:
    return {"areas": lorenz.areas(), "parametros": lorenz.parametros()}


@router.put("/areas", summary="Substituir as áreas e/ou os parâmetros (exige sessão)")
def lorenz_guardar_areas(pedido: AreasRequest, session: Session = None) -> Dict[str, Any]:
    dados = lorenz.guardar_areas([area.model_dump() for area in pedido.areas], pedido.parametros)
    return {"ok": True, "areas": dados["areas"], "parametros": dados["parametros"], "atualizado_em": dados.get("atualizado_em")}


# ------------------------------------------------------------------ análise
@router.get("/panorama", summary="Estado, regime, dependências, CPV e alertas do escopo")
def lorenz_panorama(
    area: Optional[str] = Query(None, description="Área predefinida (ex.: saude, construcao, ti) ou id personalizado"),
    cpv: Optional[str] = Query(None, description="Prefixos de CPV separados por vírgula (sobrepõe a área)"),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None, description="NUTs (ex.: PT170)"),
    nif: Optional[str] = Query(None, description="NIF da entidade (comprador ou fornecedor)"),
    nif_contraparte: Optional[str] = Query(None, description="NIF da contraparte (par exato)"),
    valor_min: Optional[float] = Query(None, ge=0),
    valor_max: Optional[float] = Query(None, ge=0),
    texto: Optional[str] = Query(None, description="Texto no objeto/partes"),
    ecologico: Optional[bool] = Query(None),
    grafo: bool = Query(False, description="Incluir o grafo comprador↔fornecedor (mais pesado)"),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, cpv, ano_de, ano_ate, regiao, nif, nif_contraparte, valor_min, valor_max, texto, ecologico)
    resultado = lorenz.panorama(escopo_def, incluir_grafo=grafo)
    if resultado.get("erro"):
        raise HTTPException(status_code=502, detail=resultado["erro"])
    return resultado


@router.get("/serie", summary="Série por período com o estado observado")
def lorenz_serie(
    area: Optional[str] = Query(None),
    cpv: Optional[str] = Query(None),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None),
    nif: Optional[str] = Query(None),
    granularidade: str = Query("ano", pattern="^(ano|trimestre)$"),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, cpv, ano_de, ano_ate, regiao, nif, None, None, None, None, None)
    dados = lorenz.serie(escopo_def, granularidade=granularidade)
    if dados.get("erro"):
        raise HTTPException(status_code=502, detail=dados["erro"])
    return {
        **dados,
        "estado": lorenz.estado_da_serie(dados["periodos"]),
        "parametros_estimados": lorenz.estimar_parametros(dados["periodos"]),
    }


@router.get("/grafo", summary="Grafo comprador↔fornecedor (formato do canvas)")
def lorenz_grafo(
    area: Optional[str] = Query(None),
    cpv: Optional[str] = Query(None),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None),
    nif: Optional[str] = Query(None),
    top_compradores: Optional[int] = Query(None, ge=5, le=200),
    limite_fornecedores: int = Query(40, ge=5, le=300),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, cpv, ano_de, ano_ate, regiao, nif, None, None, None, None, None)
    dados = lorenz.matriz_dependencia(escopo_def, top_compradores=top_compradores)
    dep = lorenz.dependencias(dados)
    grafo = lorenz._grafo_studio(dados, dep, limite_fornecedores=limite_fornecedores)  # noqa: SLF001 — formato interno
    return grafo


@router.get("/cpv", summary="Fragilidade e concentração por classe de CPV")
def lorenz_cpv(
    area: Optional[str] = Query(None),
    cpv: Optional[str] = Query(None),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None),
    nif: Optional[str] = Query(None),
    top_cpvs: Optional[int] = Query(None, ge=3, le=60),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, cpv, ano_de, ano_ate, regiao, nif, None, None, None, None, None)
    dados = lorenz.matriz_cpv(escopo_def, top_cpvs=top_cpvs)
    return lorenz._dependencia_cpv(dados)  # noqa: SLF001


@router.get("/entidades", summary="Compradores mais frágeis e fornecedores mais expostos")
def lorenz_entidades(
    area: Optional[str] = Query(None),
    cpv: Optional[str] = Query(None),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None),
    nif: Optional[str] = Query(None),
    top_compradores: Optional[int] = Query(None, ge=5, le=200),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, cpv, ano_de, ano_ate, regiao, nif, None, None, None, None, None)
    dados = lorenz.matriz_dependencia(escopo_def, top_compradores=top_compradores)
    dep = lorenz.dependencias(dados)
    cpvs = lorenz.matriz_cpv(escopo_def)
    return {
        "compradores": dep["compradores"][:40],
        "fornecedores": [
            {**fornecedor, "compradores": fornecedor["compradores"][:10]} for fornecedor in dep["fornecedores"][:40]
        ],
        "alertas": dep["alertas"],
        "amplificadores": lorenz.ranking_amplificadores(dados, cpvs=cpvs, topo=20),
        "limiares": dep["limiares"],
    }


@router.get("/propagacao", summary="Cenário de propagação de um fornecedor (7/30/60 dias)")
def lorenz_propagacao(
    area: Optional[str] = Query(None),
    cpv: Optional[str] = Query(None),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None),
    nif: Optional[str] = Query(None),
    fornecedor_nif: Optional[str] = Query(None, description="NIF do fornecedor a perturbar"),
    fornecedor_nome: Optional[str] = Query(None, description="Nome (parcial) do fornecedor a perturbar"),
    atraso_dias: float = Query(30.0, ge=0, le=365),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, cpv, ano_de, ano_ate, regiao, nif, None, None, None, None, None)
    resultado = lorenz.propagacao(
        escopo_def, fornecedor_nif=fornecedor_nif, fornecedor_nome=fornecedor_nome, atraso_dias=atraso_dias
    )
    if not resultado.get("disponivel"):
        raise HTTPException(status_code=404, detail=resultado.get("motivo") or "sem fornecedores no escopo")
    return resultado


@router.get("/cenarios", summary="Comparação 7/30/60 dias e elasticidade ao choque")
def lorenz_cenarios(
    area: Optional[str] = Query(None),
    cpv: Optional[str] = Query(None),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None),
    nif: Optional[str] = Query(None),
    fornecedor_nif: Optional[str] = Query(None),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, cpv, ano_de, ano_ate, regiao, nif, None, None, None, None, None)
    dados = lorenz.matriz_dependencia(escopo_def)
    cpvs = lorenz.matriz_cpv(escopo_def)
    return {
        "cenarios": lorenz.cenarios_atraso(dados, fornecedor_nif=fornecedor_nif, cpvs=cpvs),
        "sensibilidade": lorenz.sensibilidade(dados, fornecedor_nif=fornecedor_nif, cpvs=cpvs),
    }


@router.get("/evidencias", summary="Contratos que sustentam uma relação ou um CPV")
def lorenz_evidencias(
    area: Optional[str] = Query(None),
    cpv: Optional[str] = Query(None),
    ano_de: Optional[int] = Query(None, ge=1900, le=2100),
    ano_ate: Optional[int] = Query(None, ge=1900, le=2100),
    regiao: Optional[str] = Query(None),
    nif: Optional[str] = Query(None),
    comprador_nif: Optional[str] = Query(None),
    fornecedor_nif: Optional[str] = Query(None),
    cpv_prefixo: Optional[str] = Query(None),
    limite: int = Query(12, ge=1, le=50),
) -> Dict[str, Any]:
    escopo_def = _escopo(area, cpv, ano_de, ano_ate, regiao, nif, None, None, None, None, None)
    return lorenz.evidencias(
        escopo_def,
        comprador_nif=comprador_nif,
        fornecedor_nif=fornecedor_nif,
        cpv_prefixo=cpv_prefixo,
        limite=limite,
    )


# ------------------------------------------------------------------ execuções
@router.post("/execucoes", summary="Calcular e guardar um panorama (exige sessão)")
def lorenz_guardar_execucao(pedido: ExecucaoRequest, session: Session = None) -> Dict[str, Any]:
    escopo_def = _escopo(
        pedido.area, pedido.cpv, pedido.ano_de, pedido.ano_ate, pedido.regiao, pedido.nif, None, pedido.valor_min, pedido.valor_max, None, None
    )
    resultado = lorenz.panorama(escopo_def)
    if resultado.get("erro"):
        raise HTTPException(status_code=502, detail=resultado["erro"])
    autor = getattr(getattr(session, "user", None), "email", None) if session else None
    guardado = lorenz.guardar_execucao(escopo_def, resultado, autor=autor, titulo=pedido.titulo)
    if guardado.get("erro"):
        raise HTTPException(status_code=502, detail=guardado["erro"])
    return {**guardado, "kpis": resultado.get("kpis")}


@router.get("/execucoes", summary="Execuções guardadas")
def lorenz_execucoes(limite: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    return {"itens": lorenz.listar_execucoes(limite=limite)}


@router.get("/execucoes/{run_id}", summary="Execução guardada (fotografia completa)")
def lorenz_execucao(run_id: str) -> Dict[str, Any]:
    documento = lorenz.obter_execucao(run_id)
    if not documento:
        raise HTTPException(status_code=404, detail="Execução não encontrada")
    return documento
