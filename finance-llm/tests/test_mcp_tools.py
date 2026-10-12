"""Testes do orçamento de ferramentas do servidor MCP (`mcp_server/server.py`).

Cobrem o filtro por grupos, a exclusão e o teto — o que evita o erro dos
clientes que recusam pedidos com mais de 128 funções.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp_server import server as mcp  # noqa: E402
from mcp_server.catalog import OPERATIONS, TAGS  # noqa: E402


def _tags_for(tags: str) -> list[str]:
    wanted = {tag.strip().lower() for tag in tags.split(",") if tag.strip()}
    return sorted({op.tag.lower() for op in OPERATIONS if op.tag.lower() in wanted})


def test_sem_variaveis_expoe_o_catalogo_completo(monkeypatch):
    for name in ("IQOS_MCP_TAGS", "IQOS_MCP_EXCLUDE_TAGS", "IQOS_MCP_MAX_TOOLS"):
        monkeypatch.delenv(name, raising=False)
    assert len(mcp._selected_operations()) == len(OPERATIONS)


def test_asterisco_equivale_ao_catalogo_completo(monkeypatch):
    monkeypatch.setenv("IQOS_MCP_TAGS", "*")
    assert len(mcp._selected_operations()) == len(OPERATIONS)


def test_filtro_por_grupos(monkeypatch):
    monkeypatch.delenv("IQOS_MCP_EXCLUDE_TAGS", raising=False)
    monkeypatch.delenv("IQOS_MCP_MAX_TOOLS", raising=False)
    monkeypatch.setenv("IQOS_MCP_TAGS", "contratos,empresas")
    selected = mcp._selected_operations()
    assert selected
    assert {op.tag for op in selected} == {"contratos", "empresas"}
    assert len(selected) == len([op for op in OPERATIONS if op.tag in {"contratos", "empresas"}])


def test_grupos_desconhecidos_sao_ignorados(monkeypatch):
    monkeypatch.setenv("IQOS_MCP_TAGS", "contratos,nao-existe")
    selected = mcp._selected_operations()
    assert {op.tag for op in selected} == {"contratos"}


def test_exclusao_retira_grupos(monkeypatch):
    monkeypatch.setenv("IQOS_MCP_TAGS", "contratos,empresas")
    monkeypatch.setenv("IQOS_MCP_EXCLUDE_TAGS", "empresas")
    monkeypatch.delenv("IQOS_MCP_MAX_TOOLS", raising=False)
    selected = mcp._selected_operations()
    assert {op.tag for op in selected} == {"contratos"}


def test_teto_corta_na_ordem_do_catalogo(monkeypatch):
    monkeypatch.setenv("IQOS_MCP_TAGS", "contratos,empresas")
    monkeypatch.setenv("IQOS_MCP_MAX_TOOLS", "5")
    selected = mcp._selected_operations()
    assert len(selected) == 5
    assert selected == [op for op in OPERATIONS if op.tag in {"contratos", "empresas"}][:5]


def test_teto_invalido_e_ignorado(monkeypatch):
    monkeypatch.setenv("IQOS_MCP_TAGS", "contratos")
    monkeypatch.setenv("IQOS_MCP_MAX_TOOLS", "muitas")
    assert len(mcp._selected_operations()) == len([op for op in OPERATIONS if op.tag == "contratos"])


def test_teto_zero_nao_limita(monkeypatch):
    monkeypatch.delenv("IQOS_MCP_TAGS", raising=False)
    monkeypatch.setenv("IQOS_MCP_MAX_TOOLS", "0")
    assert len(mcp._selected_operations()) == len(OPERATIONS)


def test_relatorio_do_orcamento_conta_genericas(monkeypatch):
    monkeypatch.setenv("IQOS_MCP_TAGS", "hermes")
    monkeypatch.delenv("IQOS_MCP_MAX_TOOLS", raising=False)
    monkeypatch.delenv("IQOS_MCP_EXCLUDE_TAGS", raising=False)
    report = mcp.tool_report()
    assert report["catalog"] == len(OPERATIONS)
    assert report["selected"] == len([op for op in OPERATIONS if op.tag == "hermes"])
    assert report["total"] == report["selected"] + mcp.GENERIC_TOOLS
    assert report["tags"] == ["hermes"]
    assert report["over_client_limit"] is False
    assert report["client_limit"] == 128


def test_relatorio_marca_excesso_do_limite_do_cliente(monkeypatch):
    monkeypatch.delenv("IQOS_MCP_TAGS", raising=False)
    monkeypatch.delenv("IQOS_MCP_MAX_TOOLS", raising=False)
    report = mcp.tool_report()
    assert report["total"] > mcp.CLIENT_TOOL_LIMIT
    assert report["over_client_limit"] is True


def test_selecao_recomendada_cabe_no_orcamento(monkeypatch):
    """A seleção do `.vscode/mcp.json` (38 ferramentas) tem de caber com folga."""
    monkeypatch.setenv("IQOS_MCP_TAGS", "contratos,empresas,deep-search,hermes")
    monkeypatch.setenv("IQOS_MCP_MAX_TOOLS", "40")
    monkeypatch.delenv("IQOS_MCP_EXCLUDE_TAGS", raising=False)
    report = mcp.tool_report()
    assert report["total"] <= 40
    assert report["tags"] == _tags_for("contratos,empresas,deep-search,hermes")


@pytest.mark.parametrize("tag", sorted(TAGS))
def test_todos_os_grupos_do_catalogo_sao_validos(tag):
    assert tag.strip(), "grupo sem nome"
