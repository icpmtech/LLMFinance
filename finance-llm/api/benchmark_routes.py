"""Rotas do módulo **Benchmark de preços e concorrência** (`/benchmark/*`).

Dá a uma entidade do sistema (empresa que vende ao Estado ou entidade que
compra), e opcionalmente um CPV, a leitura do mercado em que se move. Funciona
em **Portugal, Espanha e França** — o parâmetro `country` escolhe o índice:

- `GET  /benchmark/meta`    — países, volumetria e anos disponíveis
- `GET  /benchmark/cpv`     — CPV mais usados de um país (seletor), com descrição
- `GET  /benchmark/entities`— entidades de um país no papel pedido (seletor)
- `GET  /benchmark/entity`  — preço de referência, concorrência, historial e oportunidades
- `POST /benchmark/compare` — comparação de **até 10 empresas** no mesmo segmento
- `GET  /benchmark/by-cpv`  — quadro por CPV com o volume/preço de cada país
- `GET  /benchmark/by-entity`— empresas (ou compradores) de cada país e os seus CPV
- `POST /benchmark/cross`   — empresas de países diferentes: CPV e contrapartes em comum

`country` aceita `pt`, `es`, `fr` ou `all` (meta); `/benchmark/entity` e
`/benchmark/compare` usam `nif` (NIF/DIR3/SIRET) ou `name`, o papel
(`adjudicatario` = vende, `adjudicante` = compra), o `cpv_code` e a janela de
anos. Todos os valores são em euros.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import benchmark_countries as bc
from api import benchmark_service as benchmark
from api.auth_routes import require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/benchmark", tags=["benchmark"])


class BenchmarkCompareEntity(BaseModel):
    """Uma das empresas a comparar."""

    nif: Optional[str] = Field(None, description="NIF da entidade (preferido)")
    name: Optional[str] = Field(None, description="Nome da entidade (usado quando não há NIF)")


class BenchmarkCompareRequest(BaseModel):
    """Comparação de até 10 empresas no mesmo segmento."""

    entities: list[BenchmarkCompareEntity] = Field(..., description="Empresas a comparar (1 a 10)")
    role: str = Field(
        "adjudicatario",
        description="Papel comum a todas: `adjudicatario` (vendem) ou `adjudicante` (compram)",
    )
    country: str = Field("pt", description="País dos dados: `pt`, `es` ou `fr`")
    cpv_code: Optional[str] = Field(None, description="Código CPV do segmento (prefixo aceite)")
    year_from: Optional[int] = Field(None, description="Ano inicial (inclusive)")
    year_to: Optional[int] = Field(None, description="Ano final (inclusive)")
    region: Optional[str] = Field(None, description="Região/NUTS ou distrito (conforme o país)")
    top: int = Field(10, ge=1, le=50, description="Quantas posições mostrar no ranking do segmento")


class BenchmarkCrossEntity(BaseModel):
    """Uma empresa a cruzar, com o país dos seus dados."""

    country: str = Field("pt", description="País dos dados desta empresa: `pt`, `es` ou `fr`")
    nif: Optional[str] = Field(None, description="NIF/DIR3/SIRET da entidade (preferido)")
    name: Optional[str] = Field(None, description="Nome da entidade (usado quando não há identificador)")


class BenchmarkCrossRequest(BaseModel):
    """Cruzamento de empresas de países diferentes (até 6)."""

    entities: list[BenchmarkCrossEntity] = Field(..., description="Empresas a cruzar (2 a 6)")
    role: str = Field(
        "adjudicatario",
        description="Papel comum a todas: `adjudicatario` (vendem) ou `adjudicante` (compram)",
    )
    cpv_code: Optional[str] = Field(None, description="Código CPV do segmento (prefixo aceite)")
    year_from: Optional[int] = Field(None, description="Ano inicial (inclusive)")
    year_to: Optional[int] = Field(None, description="Ano final (inclusive)")
    top: int = Field(0, ge=0, le=50, description="Quantas contrapartes por empresa considerar no cruzamento")


class BenchmarkReportRequest(BaseModel):
    """Pedido do relatório PDF do benchmark (pago na área «Relatórios»)."""

    mode: str = Field("empresa", description="`empresa`, `mercado` (por CPV) ou `cruzar` (entre países)")
    country: str = Field("pt", description="País dos dados no modo `empresa`")
    nif: Optional[str] = Field(None, description="NIF/DIR3/SIRET (modo `empresa`)")
    name: Optional[str] = Field(None, description="Nome da entidade (modo `empresa`)")
    role: str = Field("adjudicatario", description="`adjudicatario` (vende) ou `adjudicante` (compra)")
    cpv_code: Optional[str] = Field(None, description="CPV do segmento (prefixo aceite)")
    year_from: Optional[int] = Field(None, description="Ano inicial (inclusive)")
    year_to: Optional[int] = Field(None, description="Ano final (inclusive)")
    region: Optional[str] = Field(None, description="Região/distrito (PT)")
    countries: Optional[list[str]] = Field(None, description="Países do quadro por CPV (modo `mercado`)")
    top: Optional[int] = Field(None, ge=5, le=200, description="Quantos CPV no quadro (modo `mercado`)")
    entities: Optional[list[BenchmarkCrossEntity]] = Field(
        None, description="Empresas a cruzar (modo `cruzar`, 2 a 6)"
    )
    mbway_phone: str = Field("", description="Telemóvel para o pedido de pagamento MB Way")
    notes: str = Field("", max_length=2000, description="Notas que acompanham o pedido")


@router.get("/meta")
def benchmark_meta(
    country: str = Query("all", description="`pt`, `es`, `fr` ou `all` (resumo dos três)"),
) -> Dict[str, Any]:
    """Países disponíveis, volumetria de cada índice e anos com contratos."""
    resultado = benchmark.benchmark_meta(country=country)
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=str(resultado["error"]))
    return resultado


@router.get("/cpv")
def benchmark_cpv(
    q: Optional[str] = Query(None, description="Prefixo do código CPV (ex.: `90511`)"),
    size: int = Query(20, ge=1, le=100, description="Quantos CPV devolver"),
    country: str = Query("pt", description="`pt`, `es` ou `fr`"),
) -> Dict[str, Any]:
    """CPV mais usados no país (para escolher o segmento)."""
    resultado = benchmark.top_cpv(q=q, size=size, country=country)
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=str(resultado["error"]))
    return resultado


@router.get("/entities")
def benchmark_entities(
    q: str = Query(..., min_length=2, description="Nome ou identificador (NIF/DIR3/SIRET) da entidade"),
    role: str = Query(
        "adjudicatario",
        description="Papel da entidade: `adjudicatario` (vende) ou `adjudicante` (compra)",
    ),
    country: str = Query("pt", description="País dos dados: `pt`, `es` ou `fr`"),
    size: int = Query(8, ge=1, le=25, description="Quantas entidades devolver"),
) -> Dict[str, Any]:
    """Entidades do país no papel pedido (seletor da página do benchmark)."""
    resultado = benchmark.search_entities(q=q, role=role, country=country, size=size)
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=str(resultado["error"]))
    return resultado


@router.get("/by-cpv")
def benchmark_by_cpv(
    countries: Optional[str] = Query(
        None, description="Países separados por vírgula (`pt,es,fr`); por omissão, os três"
    ),
    cpv_code: Optional[str] = Query(None, description="Prefixo de CPV a filtrar"),
    year_from: Optional[int] = Query(None, description="Ano inicial (inclusive)"),
    year_to: Optional[int] = Query(None, description="Ano final (inclusive)"),
    top: int = Query(40, ge=1, le=200, description="Quantos CPV devolver (por valor)"),
) -> Dict[str, Any]:
    """Quadro por CPV: contratos, valor e mediana de cada país, e o total."""
    escolhidos = [c.strip() for c in (countries or "").split(",") if c.strip()]
    resultado = benchmark.benchmark_by_cpv(
        countries=escolhidos or None,
        cpv_code=cpv_code,
        year_from=year_from,
        year_to=year_to,
        top=top,
    )
    if resultado.get("error"):
        raise HTTPException(status_code=502, detail=str(resultado["error"]))
    return resultado


@router.get("/by-entity")
def benchmark_by_entity(
    countries: Optional[str] = Query(
        None, description="Países separados por vírgula (`pt,es,fr`); por omissão, os três"
    ),
    role: str = Query(
        "adjudicatario",
        description="`adjudicatario` (quem vende) ou `adjudicante` (quem compra) — igual nos três países",
    ),
    cpv_code: Optional[str] = Query(None, description="Prefixo de CPV a filtrar"),
    year_from: Optional[int] = Query(None, description="Ano inicial (inclusive)"),
    year_to: Optional[int] = Query(None, description="Ano final (inclusive)"),
    size: int = Query(10, ge=1, le=30, description="Quantas entidades por país"),
    cpv_size: int = Query(6, ge=1, le=20, description="Quantos CPV principais por entidade"),
) -> Dict[str, Any]:
    """Empresas (ou compradores) de cada país, com os CPV onde cada uma atua."""
    escolhidos = [c.strip() for c in (countries or "").split(",") if c.strip()]
    resultado = benchmark.top_entities(
        countries=escolhidos or None,
        role=role,
        cpv_code=cpv_code,
        year_from=year_from,
        year_to=year_to,
        size=size,
        cpv_size=cpv_size,
    )
    if resultado.get("error"):
        raise HTTPException(status_code=502, detail=str(resultado["error"]))
    return resultado


@router.post("/cross")
def benchmark_cross_endpoint(req: BenchmarkCrossRequest) -> Dict[str, Any]:
    """Cruza empresas de países diferentes: preços, CPV e contrapartes em comum.

    Cada empresa é analisada no mercado do seu país (cada uma tem o seu
    `country`); a comparação entre países faz-se pelo **CPV** — a classificação
    comum aos três registos — e pelas contrapartes que partilham.
    """
    if len(req.entities) < 2:
        raise HTTPException(status_code=422, detail="Indique pelo menos duas empresas.")
    resultado = benchmark.benchmark_cross(
        entities=[alvo.model_dump() for alvo in req.entities],
        role=req.role,
        cpv_code=req.cpv_code,
        year_from=req.year_from,
        year_to=req.year_to,
        top=req.top,
    )
    if resultado.get("error"):
        raise HTTPException(status_code=502, detail=str(resultado["error"]))
    return resultado


@router.post("/report", status_code=201)
def benchmark_report(
    req: BenchmarkReportRequest,
    session: Annotated[Any, Depends(require_session)],
) -> Dict[str, Any]:
    """Pede o **relatório PDF** do benchmark (preço definido no backoffice).

    O pedido entra na área «Relatórios» como qualquer outro: o cliente paga (por
    MB Way, se o passo seguinte for pedido com `mbway_phone`) e o PDF é gerado
    automaticamente a partir dos mesmos dados das páginas. A resposta traz o
    pedido, o preço em vigor e os dados públicos de pagamento.
    """
    from api import benchmark_report as relatorio
    from api import reports_payments as payments
    from api import reports_store as reports

    try:
        params = relatorio.normalise(req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    pacote = reports.package("benchmark")
    if not pacote or not reports._bool(pacote.get("active"), True):
        raise HTTPException(status_code=503, detail="O relatório de benchmark está indisponível.")

    email = str(getattr(session, "user", None).email or "").lower()
    nome = str(getattr(session, "user", None).name or "") or email
    try:
        pedido = reports.create_request(
            {"email": email, "name": nome},
            {
                "package_id": "benchmark",
                "targets": _alvos_do_pedido(params),
                "benchmark": params,
                "notes": req.notes,
                "mbway_phone": req.mbway_phone,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Se o cliente já deu o telemóvel e o MB Way está configurado, o pedido de
    # pagamento é lançado logo (a notificação aparece na app MB Way).
    automatico: Dict[str, Any] = {"ok": False, "configured": payments.api_configured(reports.settings())}
    telefone = reports.normalise_phone(req.mbway_phone)
    valor = reports.money((pedido.get("amounts") or {}).get("total"))
    if telefone and valor > 0 and automatico["configured"]:
        automatico = payments.create_payment_request(
            reports.settings(),
            phone=telefone,
            amount=valor,
            reference=str(pedido.get("reference") or ""),
            description=f"{pedido.get('package_title')} — {pedido.get('reference')}",
        )
        if automatico.get("ok") and automatico.get("request_id"):
            reports.record_mbway_request(str(pedido.get("id")), automatico["request_id"], automatico.get("status", ""))
            pedido = reports.get_request_view(str(pedido.get("id")), include_internal=True) or pedido

    return {
        "request": pedido,
        "package": pacote,
        "report": {
            "mode": params["mode"],
            "title": relatorio.titulo(params),
            "subtitle": relatorio.subtitulo(params),
        },
        "settings": reports.public_settings(),
        "automatic": automatico,
    }


def _alvos_do_pedido(params: Dict[str, Any]) -> List[Dict[str, str]]:
    """Alvos mostrados no pedido (empresa(s) ou o âmbito do quadro por CPV)."""
    if params["mode"] == "empresa":
        return [{"name": params.get("name") or "", "nif": params.get("nif") or ""}]
    if params["mode"] == "cruzar":
        return [
            {"name": alvo.get("name") or alvo.get("nif") or "", "nif": alvo.get("nif") or ""}
            for alvo in params.get("entities") or []
        ][:6]
    paises = ", ".join(bc.dialect(pais)["label"] for pais in params.get("countries") or [])
    return [{"name": f"Quadro por CPV — {paises}", "nif": params.get("cpv_code") or ""}]


@router.get("/entity")
def benchmark_entity(
    nif: Optional[str] = Query(None, description="NIF/DIR3/SIRET da entidade (preferido)"),
    name: Optional[str] = Query(None, description="Nome da entidade (usado quando não há identificador)"),
    role: str = Query(
        "adjudicatario",
        description="Papel da entidade: `adjudicatario` (vende) ou `adjudicante` (compra)",
    ),
    country: str = Query("pt", description="País dos dados: `pt`, `es` ou `fr`"),
    cpv_code: Optional[str] = Query(None, description="Código CPV do segmento (prefixo aceite)"),
    year_from: Optional[int] = Query(None, description="Ano inicial (inclusive)"),
    year_to: Optional[int] = Query(None, description="Ano final (inclusive)"),
    region: Optional[str] = Query(None, description="Região/NUTS ou distrito (conforme o país)"),
    top: int = Query(12, ge=1, le=50, description="Quantas linhas por tabela"),
) -> Dict[str, Any]:
    """Benchmark de preços, concorrência, historial e oportunidades."""
    if not (nif or (name or "").strip()):
        raise HTTPException(status_code=422, detail="Indique a entidade por `nif` ou `name`.")
    resultado = benchmark.benchmark_entity(
        nif=nif,
        name=name,
        role=role,
        country=country,
        cpv_code=cpv_code,
        year_from=year_from,
        year_to=year_to,
        region=region,
        top=top,
    )
    if resultado.get("error"):
        raise HTTPException(status_code=502, detail=str(resultado["error"]))
    return resultado


@router.post("/compare")
def benchmark_compare_endpoint(req: BenchmarkCompareRequest) -> Dict[str, Any]:
    """Compara até 10 empresas no mesmo segmento (papel + CPV + anos).

    Devolve, para cada empresa, os contratos, o valor, a média e a mediana do
    segmento, a quota de valor, a posição no ranking do segmento e o índice de
    preço face à mediana do mercado — mais o preço de referência do mercado (uma
    só vez) e o ranking do segmento com as empresas comparadas assinaladas.
    """
    entidades = [
        {"nif": item.nif, "name": item.name}
        for item in req.entities
        if (item.nif or "").strip() or (item.name or "").strip()
    ]
    if not entidades:
        raise HTTPException(status_code=422, detail="Indique as empresas a comparar (nif ou name).")
    if len(entidades) > benchmark.MAX_COMPARE:
        raise HTTPException(
            status_code=422,
            detail=f"Só é possível comparar até {benchmark.MAX_COMPARE} empresas de cada vez.",
        )
    resultado = benchmark.benchmark_compare(
        entities=entidades,
        role=req.role,
        country=req.country,
        cpv_code=req.cpv_code,
        year_from=req.year_from,
        year_to=req.year_to,
        region=req.region,
        top=req.top,
    )
    if resultado.get("error"):
        raise HTTPException(status_code=502, detail=str(resultado["error"]))
    return resultado
