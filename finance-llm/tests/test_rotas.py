"""Todas as rotas da API: registo, schema OpenAPI e contrato com o cliente ES.

A divisão de `api/elasticsearch_client.py` em `api/es/*` mexeu no módulo que
**todas** as rotas usam. Este teste percorre `api.main.app` e valida, rota a rota:

- o caminho e os métodos (e que não há caminho+método repetido);
- que o endpoint existe e o módulo onde está definido importa sem erros;
- que os nomes que esse módulo importa de `api.elasticsearch_client` existem —
  é o que garante que nenhuma rota ficou a apontar para uma função "perdida";
- que o schema OpenAPI é gerado (assinaturas, `response_model` e modelos válidos).
"""
from __future__ import annotations

import ast
import importlib
import sys
from functools import lru_cache
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.main import app  # noqa: E402


def _rotas_registadas(rotas, prefixo: str = ""):
    """Percorre `app.routes` em profundidade.

    O `include_router` do FastAPI é preguiçoso: cada router incluído aparece como
    um `_IncludedRouter` (com o router original e o prefixo em `include_context`),
    não como rotas achatadas. Sem descer a estes níveis só se viam as rotas
    declaradas diretamente em `api/main.py`, pelo que a tabela de rotas tem de ser
    construída recursivamente.
    """
    for rota in rotas:
        if isinstance(rota, APIRoute):
            yield prefixo + rota.path, rota
            continue
        original = getattr(rota, "original_router", None)
        if original is None:
            continue
        contexto = getattr(rota, "include_context", None)
        yield from _rotas_registadas(original.routes, prefixo + (getattr(contexto, "prefix", "") or ""))


ROTAS = sorted(_rotas_registadas(app.routes), key=lambda par: (par[0], sorted(par[1].methods or [])))
IDS = [f"{sorted(rota.methods or ['?'])[0]} {caminho}" for caminho, rota in ROTAS]


@lru_cache(maxsize=None)
def _nomes_do_cliente_usados(modulo: str) -> tuple[str, ...]:
    """Nomes que o módulo indicado importa de `api.elasticsearch_client`."""
    origem = importlib.import_module(modulo)
    caminho = Path(origem.__file__ or "")
    if not caminho.exists():
        return ()
    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
    nomes: list[str] = []
    for node in ast.walk(arvore):
        if isinstance(node, ast.ImportFrom) and node.module == "api.elasticsearch_client":
            nomes.extend(alias.name for alias in node.names)
    return tuple(sorted(set(nomes)))


def test_existem_rotas_registadas() -> None:
    """A app expõe o conjunto de rotas esperado (nenhum router ficou por registar)."""
    assert len(ROTAS) > 1200, f"só {len(ROTAS)} rotas — algum router deixou de ser incluído?"
    for caminho, rota in ROTAS:
        assert caminho.startswith("/"), caminho
        assert rota.methods, f"{caminho} sem métodos"


#: Caminho+método registados mais de uma vez **antes** da divisão do cliente ES.
#: São rotas de dados «sombreadas» por uma página da SPA (a segunda cópia nunca
#: chega a correr, porque o Starlette fica com a primeira que casa). Ficam
#: congeladas aqui: se aparecer outra duplicação, o teste falha.
DUPLICADAS_CONHECIDAS = {
    ("GET", "/companies/search"),
    ("POST", "/companies/search"),
    ("GET", "/pessoas-iq/pesquisa"),
}


def test_sem_caminho_e_metodo_repetidos() -> None:
    """Nenhuma rota nova ficou duplicada (as que já existiam estão congeladas)."""
    vistos: dict[tuple[str, str], str] = {}
    repetidos: set[tuple[str, str]] = set()
    for caminho, rota in ROTAS:
        for metodo in sorted(rota.methods or []):
            chave = (metodo, caminho)
            if chave in vistos:
                repetidos.add(chave)
            vistos[chave] = rota.endpoint.__module__
    novas = sorted(repetidos - DUPLICADAS_CONHECIDAS)
    assert not novas, f"Rotas duplicadas novas: {novas}"


def test_openapi_inclui_todas_as_rotas() -> None:
    """O schema OpenAPI é gerado e lista cada rota documentável.

    Ficam de fora as rotas com conversor de caminho (`{...:path}`), que o FastAPI
    serve mas não documenta.
    """
    schema = app.openapi()
    caminhos = set(schema.get("paths", {}))
    em_falta = sorted(
        caminho
        for caminho, rota in ROTAS
        if rota.include_in_schema and ":path" not in caminho and caminho not in caminhos
    )
    assert not em_falta, f"Rotas fora do OpenAPI: {em_falta}"
    assert len(caminhos) > 1200, f"o schema só tem {len(caminhos)} caminhos"


@pytest.mark.parametrize("caminho", [caminho for caminho, _ in ROTAS], ids=IDS)
def test_rota_tem_endpoint_num_modulo_importavel(caminho: str) -> None:
    """O endpoint é chamável e o módulo onde vive importa (o split não o partiu)."""
    rota = next(r for c, r in ROTAS if c == caminho)
    endpoint = rota.endpoint
    assert callable(endpoint), f"{caminho}: endpoint não é chamável"
    if endpoint.__module__.startswith(("api.", "mcp_server.")):
        modulo = importlib.import_module(endpoint.__module__)
        assert getattr(modulo, endpoint.__name__, None) is not None
    if rota.response_model is not None:
        assert isinstance(rota.response_model, type) or hasattr(rota.response_model, "__origin__")


@pytest.mark.parametrize("caminho", [caminho for caminho, _ in ROTAS], ids=IDS)
def test_rota_so_usa_nomes_que_existem_no_cliente(caminho: str) -> None:
    """A rota importa de `api.elasticsearch_client` apenas nomes que a fachada expõe."""
    from api import elasticsearch_client as esc

    rota = next(r for c, r in ROTAS if c == caminho)
    nomes = _nomes_do_cliente_usados(rota.endpoint.__module__)
    em_falta = [nome for nome in nomes if not hasattr(esc, nome)]
    assert not em_falta, f"{rota.endpoint.__module__}: importa {em_falta} do cliente, que não existe"


def test_cire_analytics_delega_os_filtros(monkeypatch: pytest.MonkeyPatch) -> None:
    """`GET /cire/analytics` passa os filtros ao serviço e devolve o resultado."""
    from api import cire_routes, cire_service

    recebido: dict[str, object] = {}

    def analitica(**kwargs: object) -> dict:
        recebido.update(kwargs)
        return {"total": 7, "por_tipo": [{"key": "PER", "count": 7}]}

    monkeypatch.setattr(cire_service, "analytics", analitica)

    resposta = cire_routes.cire_analytics_endpoint(
        q="construcao", nif=None, tipo="PER", papel=None, tribunal=None,
        tribunal_comarca="Comarca do Porto", especie=None, ato=None,
        data_from="2026-01-01", data_to=None, top=5,
    )

    assert resposta["total"] == 7
    assert recebido == {
        "q": "construcao",
        "nif": None,
        "tipo": "PER",
        "papel": None,
        "tribunal": None,
        "tribunal_comarca": "Comarca do Porto",
        "especie": None,
        "ato": None,
        "data_from": "2026-01-01",
        "data_to": None,
        "top": 5,
    }


def test_cire_analytics_erro_do_elastic_da_502(monkeypatch: pytest.MonkeyPatch) -> None:
    """Falha do Elasticsearch vira 502 (e não 500) na rota da analítica."""
    from fastapi import HTTPException

    from api import cire_routes, cire_service

    monkeypatch.setattr(cire_service, "analytics", lambda **_kwargs: {"error": "indisponível"})

    with pytest.raises(HTTPException) as erro:
        cire_routes.cire_analytics_endpoint(top=5)
    assert erro.value.status_code == 502
