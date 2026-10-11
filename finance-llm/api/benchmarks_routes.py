"""Rotas dos **benchmarks de produtos** (`/benchmarks/*`).

Um benchmark compara o mesmo produto em várias lojas online: define-se o estudo,
recolhem-se os preços dos sites e publica-se o resultado (no painel, e — a pedido
— como página pública no site do CMS).

- `GET    /benchmarks/meta`                 — categorias, moedas, chaves de comparação e modelos de recolha
- `GET    /benchmarks/lista`                — benchmarks (com volumetria)
- `POST   /benchmarks`                      — criar (cria logo o índice `finance_bench_<slug>`)
- `GET    /benchmarks/{slug}`               — definição
- `PUT    /benchmarks/{slug}`               — editar (lojas, seletores, moeda…)
- `DELETE /benchmarks/{slug}`               — apagar (e o índice dele)
- `POST   /benchmarks/{slug}/recolher`      — correr a recolha das lojas
- `GET    /benchmarks/{slug}/ofertas`       — ofertas item a item, com facetas
- `GET    /benchmarks/{slug}/comparacao`    — o mesmo produto entre lojas
- `GET    /benchmarks/{slug}/analise`       — KPIs, ranking de lojas e oportunidades
- `POST   /benchmarks/{slug}/publicar`      — publicar no site (página no CMS)
- `DELETE /benchmarks/{slug}/publicar`      — retirar do site
- `GET    /benchmarks/publico/lista`        — benchmarks públicos (sem sessão)
- `GET    /benchmarks/publico/{slug}`       — resumo público (sem sessão)
- `GET    /site/benchmarks/{slug}/pesquisa` — **página pública com pesquisa** (HTML, sem sessão)
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from api import benchmarks_service as servico
from api import benchmarks_store as store
from api import elasticsearch_client as esc
from api import scraper_templates
from api.auth_routes import CurrentSession, optional_session, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])

#: Router sem prefixo para a **página pública** — tem de ser registado *antes* do
#: router do CMS, senão o `GET /site/{path}` do CMS captura o caminho primeiro.
site_router = APIRouter(tags=["benchmarks"])

#: Escrever exige sessão; ler não (a lista e a comparação podem ser partilhadas).
Session = Annotated[CurrentSession, Depends(require_session)]
ReadSession = Annotated[CurrentSession, Depends(optional_session)]


class LojaPayload(BaseModel):
    """Uma loja (site) do benchmark."""

    id: Optional[str] = Field(None, description="Identificador da loja (gerado a partir do nome)")
    name: str = Field("", description="Nome da loja")
    url: str = Field("", description="URL da listagem a recolher")
    enabled: bool = Field(True, description="Participa na recolha")
    source_id: Optional[str] = Field(None, description="Reutilizar uma fonte já existente do módulo de recolha")
    template_id: Optional[str] = Field(None, description="Modelo de recolha usado como ponto de partida")
    scraper: Optional[Dict[str, Any]] = Field(None, description="Definição de recolha própria (url, list, fields…)")
    tags: List[str] = Field(default_factory=list)


class BenchmarkPayload(BaseModel):
    """Definição de um benchmark de produtos."""

    name: str = Field(..., description="Nome do estudo (ex.: «Portáteis 16 GB»)")
    slug: Optional[str] = Field(None, description="Endereço (gerado a partir do nome se não vier)")
    description: str = Field("", description="O que está a ser comparado")
    category: str = Field("", description="Categoria dos produtos")
    unit: str = Field("unidade", description="Unidade comparada")
    currency: str = Field("EUR", description="Moeda dos preços")
    tags: List[str] = Field(default_factory=list)
    public: bool = Field(False, description="Publicado no site")
    active: bool = Field(True)
    match_on: str = Field("nome", description="O que faz «o mesmo produto»: ean | sku | nome | url")
    field_map: Dict[str, str] = Field(
        default_factory=dict,
        description="Ligação campo do benchmark → campo extraído (price, product_name, brand, ean, sku, url…)",
    )
    stores: List[LojaPayload] = Field(default_factory=list, description="Lojas a comparar")


class RecolhaPayload(BaseModel):
    """Parâmetros de uma recolha."""

    stores: List[str] = Field(default_factory=list, description="Só estas lojas (por omissão, todas as ativas)")
    limite_por_loja: int = Field(500, ge=1, le=5000, description="Máximo de ofertas lidas por loja")


class SondaPayload(BaseModel):
    """Sonda de uma página de loja (preço, imagem e descrição)."""

    url: str = Field(..., description="Endereço da listagem de produtos")
    fetcher: str = Field("http", description="http | dynamic | stealth (browser real para sites protegidos)")
    hint: str = Field("", description="Contexto extra para a IA (ex.: «portáteis, preço com IVA»)")
    use_ai: bool = Field(True, description="Pedir a proposta ao modelo de IA (além da análise determinística)")
    provider: Optional[str] = Field(None, description="Fornecedor de IA (por omissão, o predefinido)")
    model: Optional[str] = Field(None, description="Modelo de IA a usar")
    benchmark: Optional[str] = Field(None, description="Benchmark onde a loja vai entrar (afina o mapa de campos)")
    nome_loja: str = Field("", description="Nome da loja (para a proposta)")


# ---------------------------------------------------------------------------
# Metadados
# ---------------------------------------------------------------------------
@router.get("/meta")
def benchmarks_meta(session: ReadSession = None) -> Dict[str, Any]:
    """O que a interface precisa para construir o formulário de um benchmark."""
    return {
        "match_keys": [
            {"id": "ean", "label": "Código EAN/GTIN", "hint": "Mais rigoroso: compara o mesmo artigo exacto."},
            {"id": "sku", "label": "Referência (SKU)", "hint": "Usa a referência do vendedor."},
            {"id": "nome", "label": "Nome do produto", "hint": "Funciona sempre; agrupa por nome normalizado."},
            {"id": "url", "label": "Endereço do produto", "hint": "Compara apenas ofertas da mesma página."},
        ],
        "field_map_keys": list(store.FIELD_MAP_KEYS),
        "currencies": ["EUR", "USD", "GBP", "BRL"],
        "templates": [
            {
                "id": modelo.get("id"),
                "name": modelo.get("name"),
                "site": modelo.get("site"),
                "category": modelo.get("category"),
                "requires": modelo.get("requires"),
            }
            for modelo in scraper_templates.list_templates()
        ],
        "total": len(store.listar()),
    }


@router.get("/modelo/{template_id}")
def benchmarks_modelo(template_id: str, session: ReadSession = None) -> Dict[str, Any]:
    """Definição de recolha pronta a usar, a partir de um modelo do módulo de scraping.

    A interface usa isto para preencher os seletores de uma loja sem os pedir à mão.
    """
    modelo = scraper_templates.get_template(template_id)
    if not modelo:
        raise HTTPException(status_code=404, detail="Modelo de recolha não encontrado.")
    try:
        fonte = scraper_templates.build_source(template_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Não foi possível construir o modelo: {exc}") from exc
    return {
        "id": modelo.get("id"),
        "name": modelo.get("name"),
        "site": modelo.get("site"),
        "description": modelo.get("description"),
        "notes": modelo.get("notes"),
        "requires": modelo.get("requires"),
        "scraper": {
            "fetcher": fonte.get("fetcher"),
            "list": fonte.get("list"),
            "fields": fonte.get("fields"),
            "pagination": fonte.get("pagination"),
            "options": fonte.get("options"),
            "respect_robots": fonte.get("respect_robots"),
            "id_fields": fonte.get("id_fields"),
        },
    }


# ---------------------------------------------------------------------------
# Sonda (análise da página + IA)
# ---------------------------------------------------------------------------
@router.post("/sonda")
async def benchmarks_sonda(payload: SondaPayload, session: Session) -> Dict[str, Any]:
    """Analisa uma página de loja e devolve a definição de recolha pronta a usar.

    A análise é primeiro **determinística** (procura o contentor repetido, o preço
    pelo formato, a imagem e o bloco de texto que parece descrição); a IA é
    chamada a seguir para afinar os seletores e as duas propostas são validadas a
    sério. Quando nada extrai, o erro explica se foi robots, bloqueio ou markup.
    """
    if not payload.url.strip():
        raise HTTPException(status_code=400, detail="Indique o endereço da página de produtos.")
    resultado = await servico.sondar_loja(
        payload.url.strip(),
        fetcher=payload.fetcher,
        hint=payload.hint,
        use_ai=payload.use_ai,
        provider=payload.provider,
        model=payload.model,
        user_id=_email(session),
        benchmark=payload.benchmark,
        nome_loja=payload.nome_loja,
    )
    if not resultado.get("ok") and not resultado.get("amostra"):
        # 502: a falha é da página (bloqueio, JavaScript, markup) — não do pedido.
        raise HTTPException(status_code=502, detail=resultado.get("erro") or "A sonda não encontrou produtos.")
    return resultado


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
@router.get("/lista")
def benchmarks_lista(session: ReadSession = None) -> Dict[str, Any]:
    """Todos os benchmarks, com a volumetria de cada um."""
    itens = store.listar()
    return {
        "items": itens,
        "total": len(itens),
        "publicos": len([b for b in itens if b.get("public")]),
        "indexes": [esc.benchmark_items_index(b.get("slug")) for b in itens],
    }


@router.get("/publico/lista")
def benchmarks_publicos() -> Dict[str, Any]:
    """Benchmarks publicados no site (sem sessão)."""
    itens = [
        {
            "slug": b.get("slug"),
            "name": b.get("name"),
            "description": b.get("description"),
            "category": b.get("category"),
            "path": b.get("public_path"),
            "url": f"/site/{b.get('public_path')}" if b.get("public_path") else "",
            "search_url": f"/site/benchmarks/{b.get('slug')}/pesquisa",
            "stats": b.get("stats"),
        }
        for b in store.listar()
        if b.get("public")
    ]
    return {"items": itens, "total": len(itens)}


@router.get("/publico/{slug}")
def benchmark_publico(slug: str, tamanho: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    """Resumo público de um benchmark (KPIs e melhores preços)."""
    benchmark = store.obter(slug)
    if not benchmark or not benchmark.get("public"):
        raise HTTPException(status_code=404, detail="Benchmark não publicado.")
    estudo = servico.analise(slug, tamanho=tamanho)
    if estudo.get("error"):
        raise HTTPException(status_code=502, detail=estudo["error"])
    return {
        **estudo,
        "search_url": f"/site/benchmarks/{slug}/pesquisa",
    }


@router.get("/{slug}")
def benchmark_detalhe(slug: str, session: ReadSession = None) -> Dict[str, Any]:
    """Definição de um benchmark."""
    benchmark = store.obter(slug)
    if not benchmark:
        raise HTTPException(status_code=404, detail="Benchmark não encontrado.")
    return benchmark


# ---------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------
@router.post("")
def benchmark_criar(payload: BenchmarkPayload, session: Session) -> Dict[str, Any]:
    """Cria um benchmark e o índice de ofertas dele."""
    try:
        criado = store.criar(payload.model_dump(exclude_none=True), autor=_email(session))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if criado.get("error"):
        raise HTTPException(status_code=502, detail=criado["error"])
    return criado


@router.put("/{slug}")
def benchmark_editar(slug: str, payload: BenchmarkPayload, session: Session) -> Dict[str, Any]:
    """Actualiza a definição (as lojas podem ser substituídas por inteiro)."""
    try:
        atualizado = store.atualizar(slug, payload.model_dump(exclude_none=True), autor=_email(session))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if atualizado.get("error"):
        raise HTTPException(status_code=404, detail=atualizado["error"])
    return atualizado


@router.delete("/{slug}")
def benchmark_apagar(
    slug: str,
    com_dados: bool = Query(True, description="Apagar também o índice de ofertas do benchmark"),
    session: Session = None,
) -> Dict[str, Any]:
    """Apaga o benchmark (e, por omissão, o índice próprio dele)."""
    resultado = store.apagar(slug, com_dados=com_dados)
    if resultado.get("error"):
        raise HTTPException(status_code=404, detail=resultado["error"])
    return resultado


@router.post("/{slug}/recolher")
def benchmark_recolher(
    slug: str,
    payload: Optional[RecolhaPayload] = Body(None),
    session: Session = None,
) -> Dict[str, Any]:
    """Corre a recolha das lojas do benchmark (síncrono: devolve o resumo).

    A recolha passa pelo motor do módulo de scraping; cada loja tem a sua fonte
    (`bench-<slug>-<loja>`) e as ofertas normalizadas ficam no índice do benchmark.
    """
    pedido = payload or RecolhaPayload()
    resultado = servico.recolher(slug, lojas=pedido.stores, limite_por_loja=pedido.limite_por_loja)
    if resultado.get("error"):
        raise HTTPException(status_code=404 if "não encontrado" in str(resultado["error"]) else 502, detail=resultado["error"])
    return resultado


@router.get("/{slug}/ofertas")
def benchmark_ofertas(
    slug: str,
    q: Optional[str] = Query(None, description="Pesquisa por nome, marca, SKU ou EAN"),
    loja: Optional[str] = Query(None, description="Filtrar por loja"),
    ordem: str = Query("preco", pattern="^(preco|preco_desc|recentes|nome|desconto)$"),
    size: int = Query(50, ge=1, le=200),
    from_: int = Query(0, ge=0, alias="from"),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Todas as ofertas recolhidas, com facetas por loja e categoria."""
    return esc.benchmark_offers(slug, q=q, store_id=loja, order=ordem, size=size, from_=from_)


@router.get("/{slug}/comparacao")
def benchmark_comparacao(
    slug: str,
    q: Optional[str] = Query(None),
    loja: Optional[str] = Query(None),
    ordem: str = Query("dispersao", pattern="^(dispersao|poupanca|lojas|preco|nome)$"),
    min_lojas: int = Query(2, ge=1, le=50, description="Só produtos presentes em pelo menos N lojas"),
    size: int = Query(50, ge=1, le=200),
    from_: int = Query(0, ge=0, alias="from"),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """O mesmo produto comparado entre lojas: mínimo, dispersão e loja mais barata."""
    return esc.benchmark_product_comparison(
        slug, q=q, store_id=loja, order=ordem, size=size, from_=from_, min_stores=min_lojas
    )


@router.get("/{slug}/analise")
def benchmark_analise(slug: str, session: ReadSession = None) -> Dict[str, Any]:
    """KPIs do estudo, ranking de lojas (índice de preço) e oportunidades."""
    resultado = servico.analise(slug)
    if resultado.get("error"):
        raise HTTPException(status_code=404, detail=resultado["error"])
    return resultado


@router.post("/{slug}/publicar")
def benchmark_publicar(slug: str, session: Session) -> Dict[str, Any]:
    """Publica o estudo: cria/actualiza a página no CMS e marca-o como público."""
    resultado = servico.publicar(slug, autor=_email(session))
    if resultado.get("error"):
        raise HTTPException(status_code=502, detail=resultado["error"])
    return resultado


@router.delete("/{slug}/publicar")
def benchmark_despublicar(slug: str, session: Session) -> Dict[str, Any]:
    """Retira o estudo do site."""
    resultado = servico.despublicar(slug, autor=_email(session))
    if resultado.get("error"):
        raise HTTPException(status_code=404, detail=resultado["error"])
    return resultado


# ---------------------------------------------------------------------------
# Página pública com pesquisa
#
# Fica em `/site/benchmarks/<slug>/pesquisa` — fora do caminho da página do CMS
# (`/site/benchmarks/<slug>`), que é a versão «publicada» do estudo.
# ---------------------------------------------------------------------------
@site_router.get("/site/benchmarks/{slug}/pesquisa", response_class=HTMLResponse, include_in_schema=False)
def benchmark_pagina_publica(
    slug: str,
    q: str = Query("", description="Pesquisa por produto, marca ou referência"),
    loja: str = Query("", description="Filtrar por loja"),
    ordem: str = Query("dispersao", pattern="^(dispersao|poupanca|lojas|preco|nome)$"),
    pagina: int = Query(0, ge=0),
) -> HTMLResponse:
    """Página pública do benchmark, com pesquisa (sem sessão)."""
    estado, html = servico.html_publico(slug, q=q, loja=loja, ordem=ordem, pagina=pagina)
    return HTMLResponse(content=html, status_code=estado, headers={"Cache-Control": "no-store"})


def _email(session: Optional[CurrentSession]) -> str:
    """Email do autor da operação (para o registo de auditoria)."""
    try:
        return str(session.user.email)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        return ""
