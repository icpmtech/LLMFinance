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

ROTAS = sorted(
    (rota for rota in app.routes if isinstance(rota, APIRoute)),
    key=lambda rota: (rota.path, sorted(rota.methods or [])),
)
IDS = [f"{sorted(rota.methods or ['?'])[0]} {rota.path}" for rota in ROTAS]


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
    assert len(ROTAS) > 300, f"só {len(ROTAS)} rotas — algum router deixou de ser incluído?"
    for rota in ROTAS:
        assert rota.path.startswith("/"), rota.path
        assert rota.methods, f"{rota.path} sem métodos"


def test_sem_caminho_e_metodo_repetidos() -> None:
    vistos: dict[tuple[str, str], str] = {}
    repetidos: list[str] = []
    for rota in ROTAS:
        for metodo in sorted(rota.methods or []):
            chave = (metodo, rota.path)
            if chave in vistos:
                repetidos.append(f"{metodo} {rota.path} ({vistos[chave]} e {rota.endpoint.__module__})")
            vistos[chave] = rota.endpoint.__module__
    assert not repetidos, "Rotas repetidas:\n" + "\n".join(repetidos)


def test_openapi_inclui_todas_as_rotas() -> None:
    """O schema OpenAPI é gerado e lista cada rota (valida assinaturas e modelos)."""
    schema = app.openapi()
    caminhos = set(schema.get("paths", {}))
    em_falta = sorted(rota.path for rota in ROTAS if rota.path not in caminhos)
    assert not em_falta, f"Rotas fora do OpenAPI: {em_falta}"
    assert len(caminhos) > 300


@pytest.mark.parametrize("rota", ROTAS, ids=IDS)
def test_rota_tem_endpoint_num_modulo_importavel(rota: APIRoute) -> None:
    """O endpoint é chamável e o módulo onde vive importa (o split não o partiu)."""
    endpoint = rota.endpoint
    assert callable(endpoint), f"{rota.path}: endpoint não é chamável"
    modulo = importlib.import_module(endpoint.__module__)
    assert getattr(modulo, endpoint.__name__) is endpoint
    if rota.response_model is not None:
        assert isinstance(rota.response_model, type) or hasattr(rota.response_model, "__origin__")


@pytest.mark.parametrize("rota", ROTAS, ids=IDS)
def test_rota_so_usa_nomes_que_existem_no_cliente(rota: APIRoute) -> None:
    """A rota importa de `api.elasticsearch_client` apenas nomes que a fachada expõe."""
    from api import elasticsearch_client as esc

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
