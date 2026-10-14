"""Permissões por papel: quem lê e quem escreve.

O que se fixa aqui é a regra pedida — **um utilizador comum só lê dados** — e os
três casos que a tornam delicada: os POST que são leitura (pesquisas, análises e
previsões), as escritas públicas (sem sessão) e a escrita do próprio estado
(sessão, subscrição, favoritos).
"""
from __future__ import annotations

import pytest

from api import permissions_service as perms


class _ClienteFalso:
    def __init__(self) -> None:
        self.documentos: dict = {}

    def exists(self, *, index: str, id: str) -> bool:  # noqa: A002 - API do Elasticsearch
        return id in self.documentos

    def get(self, *, index: str, id: str):  # noqa: A002
        return {"_source": self.documentos[id]}

    def index(self, *, index: str, id: str, document: dict, refresh: bool = False):  # noqa: A002
        self.documentos[id] = document
        return {"result": "created"}


@pytest.fixture()
def sem_indice(monkeypatch):
    """Sem Elasticsearch: tudo cai nos valores por omissão."""
    monkeypatch.setattr(perms, "_client", lambda: None)
    return None


@pytest.fixture()
def com_indice(monkeypatch):
    cliente = _ClienteFalso()
    monkeypatch.setattr(perms, "_client", lambda: cliente)
    monkeypatch.setattr(perms, "ensure_indices", lambda _client: None)
    return cliente


# ------------------------------------------------------------------- por omissão
def test_utilizador_comum_so_le(sem_indice):
    """`member` lê em todo o lado e escreve apenas o seu próprio estado."""
    membro = {"role": "member"}

    assert perms.can(membro, "crm", "read") is True
    assert perms.can(membro, "crm", "write") is False
    assert perms.can(membro, "contracts", "write") is False
    assert perms.can(membro, "cms", "write") is False

    for modulo in ("auth", "billing", "favorites", "workspace"):
        assert perms.can(membro, modulo, "write") is True, modulo


def test_gestor_escreve_conteudo_mas_nao_administra(sem_indice):
    gestor = {"role": "manager"}

    assert perms.can(gestor, "crm", "write") is True
    assert perms.can(gestor, "cms", "write") is True
    assert perms.can(gestor, "contracts", "write") is True
    # A administração da plataforma fica fora do alcance do gestor.
    assert perms.can(gestor, "admin", "write") is False
    assert perms.can(gestor, "permissions", "write") is False


def test_admin_escreve_em_tudo(sem_indice):
    admin = {"role": "admin"}

    for modulo in perms.MODULE_IDS:
        assert perms.can(admin, modulo, "write") is True, modulo


def test_sem_utilizador_nao_escreve(sem_indice):
    assert perms.can(None, "crm", "write") is False
    assert perms.can({"role": "papel_inventado"}, "crm", "write") is False


# ------------------------------------------------- POST que sao leitura
@pytest.mark.parametrize(
    "caminho",
    [
        "/contracts/search",
        "/companies/search",
        "/entities/search",
        "/sentiment/analyze/AAPL",
        "/forecast",
        "/translate",
        "/chat",
        "/rag/chat",
        "/visualizador/export/csv",
        "/search/report/pdf",
        "/ontology/ai/suggest-links",
        "/benchmark/compare",
    ],
)
def test_post_de_leitura_nunca_e_escrita(caminho):
    assert perms.is_write_operation("POST", caminho) is False


@pytest.mark.parametrize(
    "caminho",
    [
        "/contracts/ingest",
        "/elastic/ingest/prices/AAPL",
        "/cms/newsletter",
        "/scraper/sources",
        "/admin/service-keys",
        "/crm/accounts",
        "/rss/feeds",
        "/tickers/add",
    ],
)
def test_escritas_reais_sao_detetadas(caminho):
    assert perms.is_write_operation("POST", caminho) is True


def test_leitura_por_metodo_nunca_e_escrita():
    for caminho in ("/crm/accounts", "/contracts/search", "/admin/users"):
        assert perms.is_write_operation("GET", caminho) is False


# ------------------------------------------------------------- modulo do caminho
@pytest.mark.parametrize(
    ("caminho", "esperado"),
    [
        ("/crm/accounts/1", "crm"),
        ("/contracts/ingest", "contracts"),
        ("/contracts-es/search", "contracts-es"),
        ("/admin/users/1", "admin"),
        ("/permissions", "permissions"),
        ("/area-desconhecida/x", perms.FALLBACK_MODULE),
        ("", perms.FALLBACK_MODULE),
    ],
)
def test_modulo_do_caminho(caminho, esperado):
    assert perms.module_for_path(caminho) == esperado


def test_modulo_desconhecido_nao_deixa_o_utilizador_escrever(sem_indice):
    """Área que não classificámos: o utilizador comum não escreve, o gestor sim."""
    assert perms.module_for_path("/area-nova/x") == perms.FALLBACK_MODULE

    assert perms.can({"role": "member"}, perms.FALLBACK_MODULE) is False
    assert perms.can({"role": "manager"}, perms.FALLBACK_MODULE) is True


# ------------------------------------------------------------------ gravar
def test_gravar_e_ler_matriz(com_indice):
    matriz = perms.default_matrix()
    matriz["member"]["crm"]["write"] = True

    resultado = perms.save(matriz, utilizador="admin@exemplo.pt")

    assert resultado["ok"] is True
    assert perms.matrix()["member"]["crm"]["write"] is True
    assert perms.can({"role": "member"}, "crm", "write") is True


def test_gravacao_nao_deixa_o_gestor_receber_administracao(com_indice):
    """Mesmo que se grave o contrário, o módulo de administração é só do admin."""
    matriz = perms.default_matrix()
    matriz["manager"]["admin"]["write"] = True
    matriz["manager"]["permissions"]["write"] = True

    perms.save(matriz, utilizador="admin@exemplo.pt")

    assert perms.matrix()["manager"]["admin"]["write"] is False
    assert perms.matrix()["manager"]["permissions"]["write"] is False
    assert perms.can({"role": "manager"}, "admin", "write") is False


def test_gravacao_recusa_papel_desconhecido(com_indice):
    with pytest.raises(ValueError):
        perms.save({"superuser": {"crm": {"write": True}}}, utilizador="admin@exemplo.pt")


def test_matriz_ignora_modulos_desconhecidos(com_indice):
    """Um módulo inventado na matriz não cria permissões."""
    matriz = perms.default_matrix()
    matriz["member"]["modulo_inventado"] = {"read": True, "write": True}

    perms.save(matriz, utilizador="admin@exemplo.pt")

    assert "modulo_inventado" not in perms.matrix()["member"]
    assert perms.can({"role": "member"}, "modulo_inventado", "write") is False


# --------------------------------------------------------------- resumo
def test_resumo_do_utilizador(sem_indice):
    resumo = perms.effective_for_user({"role": "member"})

    assert resumo["read_only"] is True
    assert resumo["can_write_all"] is False
    assert "crm" not in resumo["writable_modules"]
    assert "billing" in resumo["writable_modules"]

    gestor = perms.effective_for_user({"role": "manager"})
    assert gestor["read_only"] is False
    assert gestor["can_write_all"] is True


def test_catalogo_cobre_as_areas_com_escrita():
    """Todos os módulos têm identificador único e um grupo para a interface."""
    ids = [module["id"] for module in perms.MODULES]

    assert len(ids) == len(set(ids))
    assert all(module["label"] and module["group"] for module in perms.MODULES)
    assert len(perms.default_matrix()["member"]) == len(ids)
