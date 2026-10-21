"""A divisão de `api/elasticsearch_client.py` em `api/es/*` não perdeu nada.

O ficheiro tinha mais de 21 mil linhas e passou a ser uma **fachada** sobre
módulos por domínio (`api/es/core.py`, `indices.py`, `mappings.py`, `contratos.py`,
`pessoas.py`, `cire.py`, …). Estes testes são o contrato da migração:

- a API exposta por `api.elasticsearch_client` continua **igual à do original**
  (`tests/data/es_api_manifest.json`, gerado a partir do ficheiro antes da divisão:
  nomes, assinaturas completas e tipo/tamanho das constantes);
- todos os módulos do backend que importam do cliente encontram o que pedem,
  incluindo os auxiliares com `_` (`_text_search`, `_build_contract_query`, …);
- atribuir um atributo na fachada — o que os serviços e os testes fazem com
  `monkeypatch`, p. ex. `esc.get_es_client = fake` — continua a chegar às funções
  que passaram para os módulos novos.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import elasticsearch_client as esc  # noqa: E402

MANIFEST = Path(__file__).parent / "data" / "es_api_manifest.json"

#: Pastas do backend que consomem o cliente (o `chat-ui` é TypeScript e não entra).
CONSUMIDORES = ("api", "collectors", "mcp_server", "processing", "training", "inference")


def _nome_do_modulo(funcao: object) -> str:
    return str(getattr(funcao, "__name__", funcao))


def test_api_publica_e_igual_a_do_ficheiro_original() -> None:
    """Nenhum nome desapareceu e nenhuma assinatura mudou na divisão."""
    esperado = json.loads(MANIFEST.read_text(encoding="utf-8"))
    em_falta: list[str] = []
    diferentes: list[str] = []

    for nome, info in esperado.items():
        if not hasattr(esc, nome):
            em_falta.append(nome)
            continue
        objeto = getattr(esc, nome)
        if info["kind"] == "function":
            if not callable(objeto):
                diferentes.append(f"{nome}: deixou de ser função")
            elif str(inspect.signature(objeto)) != info["sig"]:
                diferentes.append(
                    f"{nome}: assinatura mudou\n  antes: {info['sig']}"
                    f"\n  agora: {inspect.signature(objeto)}"
                )
        else:
            if type(objeto).__name__ != info["kind"]:
                diferentes.append(f"{nome}: {info['kind']} → {type(objeto).__name__}")
            elif info["len"] is not None and len(objeto) != info["len"]:
                diferentes.append(f"{nome}: tamanho {info['len']} → {len(objeto)}")

    assert not em_falta, f"Nomes que desapareceram da fachada: {em_falta}"
    assert not diferentes, "API alterada pela divisão:\n" + "\n".join(diferentes)


def test_todos_os_imports_do_cliente_no_backend_resolvem() -> None:
    """Cada `from api.elasticsearch_client import …` do backend aponta para algo que existe."""
    em_falta: list[str] = []
    ficheiros = 0
    for pasta in CONSUMIDORES:
        for caminho in sorted((ROOT / pasta).rglob("*.py")):
            ficheiros += 1
            arvore = ast.parse(caminho.read_text(encoding="utf-8"))
            for node in ast.walk(arvore):
                if not isinstance(node, ast.ImportFrom) or node.module != "api.elasticsearch_client":
                    continue
                for alias in node.names:
                    if not hasattr(esc, alias.name):
                        em_falta.append(f"{caminho.relative_to(ROOT)}: {alias.name}")

    assert ficheiros > 100, f"esperava varrer o backend todo, vi {ficheiros} ficheiros"
    assert not em_falta, "Importações sem destino:\n" + "\n".join(sorted(set(em_falta)))


def test_atribuicao_na_fachada_chega_aos_modulos(monkeypatch: pytest.MonkeyPatch) -> None:
    """`esc.get_es_client = fake` (monkeypatch) continua a valer dentro de `api.es`."""
    contratos = importlib.import_module("api.es.contratos")
    cire = importlib.import_module("api.es.cire")
    pessoa_falsa = lambda *_args, **_kwargs: None  # noqa: E731

    monkeypatch.setattr(esc, "get_es_client", pessoa_falsa)

    assert esc.get_es_client is pessoa_falsa
    assert contratos.get_es_client is pessoa_falsa
    assert cire.get_es_client is pessoa_falsa


def test_atribuicao_de_constantes_mutaveis_chega_ao_modulo(monkeypatch: pytest.MonkeyPatch) -> None:
    """As caches de módulo (ex.: `_PARTE_NOME_CACHE`) seguem a atribuição na fachada."""
    contratos = importlib.import_module("api.es.contratos")
    nova: dict = {}

    monkeypatch.setattr(esc, "_PARTE_NOME_CACHE", nova)

    assert contratos._PARTE_NOME_CACHE is nova


def test_modulos_do_pacote_ficam_pequenos() -> None:
    """Guarda contra o regresso do ficheiro gigante: cada módulo com um só domínio."""
    pacote = ROOT / "api" / "es"
    tamanhos = {
        caminho.name: len(caminho.read_text(encoding="utf-8").splitlines())
        for caminho in sorted(pacote.glob("*.py"))
    }
    assert len(tamanhos) >= 20, f"esperava o pacote dividido por domínio: {tamanhos}"

    grandes = {nome: linhas for nome, linhas in tamanhos.items() if linhas > 3500}
    assert not grandes, f"Módulos demasiado grandes (divida por domínio): {grandes}"

    fachada = len((ROOT / "api" / "elasticsearch_client.py").read_text(encoding="utf-8").splitlines())
    assert fachada < 800, f"a fachada deve ser fina, tem {fachada} linhas"


def test_nao_ha_funcoes_definidas_em_dois_modulos() -> None:
    """Uma função mora num módulo só (a fachada reexporta, não duplica)."""
    definicoes: dict[str, list[str]] = {}
    for caminho in sorted((ROOT / "api" / "es").glob("*.py")):
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        for node in arvore.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definicoes.setdefault(node.name, []).append(caminho.name)

    duplicadas = {nome: ficheiros for nome, ficheiros in definicoes.items() if len(ficheiros) > 1}
    assert not duplicadas, f"Funções duplicadas entre módulos: {duplicadas}"
