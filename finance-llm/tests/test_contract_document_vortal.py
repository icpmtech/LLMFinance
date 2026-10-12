"""Ficha do contrato: peças da Vortal lidas em memória (ligação contrato ↔ módulo).

O que se garante aqui:
- uma ligação Vortal é aceite (a guarda de anfitriões autoriza a plataforma);
- o texto das peças passa por `extract_values`, logo a ficha mostra valores;
- um aviso sem peças públicas não é erro: é um convite, e a ficha diz isso;
- a resposta traz o `source` certo para a UI decidir o que mostrar.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from api import contract_document as cd
from api import vortal_service as vortal

TOKEN = "SXF0dTJoWmcwSmNJckl3N3hsNFlXcW9UTjAxalppTnVuUmpuWkFENHV5UGlnaXEv"
URL_PAGINA = f"https://community.vortal.biz/Public/public-tender-documents/{TOKEN}"
UID = "PT1.NTC.3485001"

CONTRATO: Dict[str, Any] = {
    "idcontrato": "11970015",
    "linkPecasProc": URL_PAGINA,
    "objetoContrato": "Aquisição de serviços",
}


@pytest.fixture(autouse=True)
def _cache_limpa():
    """O cache de fichas é do processo: cada teste começa limpo."""
    cd._cache.clear()
    yield
    cd._cache.clear()


def _ficha(monkeypatch: pytest.MonkeyPatch, *, pecas: List[Dict[str, Any]], publicado: bool = True, total: int | None = None):
    """Corre `contract_document` com a Vortal em memória (sem rede)."""

    def _em_memoria(url: str, **_kwargs: Any) -> Dict[str, Any]:
        return {
            "uid": UID,
            "url_aviso": f"https://community.vortal.biz/Public/contract-notice-view/{UID}/",
            "publicado": publicado,
            "total": len(pecas) if total is None else total,
            "incluidas": len(pecas),
            "pecas": pecas,
            "nota": "nota de teste",
        }

    monkeypatch.setattr(vortal, "pecas_em_memoria", _em_memoria)
    return cd.contract_document("11970015", CONTRATO)


def test_ficha_le_pecas_vortal_e_extrai_valores(monkeypatch: pytest.MonkeyPatch):
    pecas = [
        {
            "nome": "CADERNO-DE-ENCARGOS.pdf",
            "extensao": ".pdf",
            "texto": "Preço Base 250.000,00 €\nCaução\nPrestação de caução: 5 % do preço contratual",
        }
    ]
    ficha = _ficha(monkeypatch, pecas=pecas)

    assert ficha["source"] == "vortal"
    assert ficha["uid"] == UID
    assert ficha["pieces_total"] == 1
    assert [peca["name"] for peca in ficha["pieces"]] == ["CADERNO-DE-ENCARGOS.pdf"]
    assert "Preço Base" in ficha["pieces"][0]["text"]
    assert ficha["pieces"][0]["kind"] == ".pdf"
    etiquetas = {destaque["label"] for destaque in ficha["highlights"]}
    assert "Preço base" in etiquetas
    assert all(destaque["document"] == "CADERNO-DE-ENCARGOS.pdf" for destaque in ficha["highlights"])
    assert ficha["error"] is None


def test_ficha_deduplica_valores_iguais_em_pecas_diferentes(monkeypatch: pytest.MonkeyPatch):
    texto = "Preço Base 100.000,00 €"
    pecas = [
        {"nome": "a.pdf", "extensao": ".pdf", "texto": texto},
        {"nome": "b.pdf", "extensao": ".pdf", "texto": texto},
    ]
    ficha = _ficha(monkeypatch, pecas=pecas)
    precos = [h for h in ficha["highlights"] if h["label"] == "Preço base"]
    assert len(precos) == 1, "o mesmo valor repetido não deve aparecer duas vezes"


def test_ficha_aviso_sem_pecas_publicas_nao_e_erro(monkeypatch: pytest.MonkeyPatch):
    ficha = _ficha(monkeypatch, pecas=[], total=0)

    assert ficha["error"] is None
    assert ficha["source"] == "vortal"
    assert ficha["pieces"] == []
    assert ficha["highlights"] == []
    assert ficha["pieces_total"] == 0
    assert ficha["note"] == "nota de teste"
    # as ligações oficiais continuam disponíveis, para a UI não ficar vazia
    assert any("BASE.gov.pt" in str(link.get("label")) for link in ficha["links"])
    assert any("vortal.biz" in str(link.get("url")) for link in ficha["links"])


def test_ficha_le_varias_pecas_e_guarda_a_origem(monkeypatch: pytest.MonkeyPatch):
    pecas = [
        {"nome": "CE.pdf", "extensao": ".pdf", "texto": "Preço Base 10.000,00 €"},
        {"nome": "MQ.xlsx", "extensao": ".xlsx", "texto": "As propostas são apresentadas até às 17h00 do dia 21 de maio de 2025"},
    ]
    ficha = _ficha(monkeypatch, pecas=pecas)
    assert len(ficha["pieces"]) == 2
    etiquetas = {destaque["label"] for destaque in ficha["highlights"]}
    assert {"Preço base", "Prazo de apresentação de propostas"} <= etiquetas
    assert {destaque["document"] for destaque in ficha["highlights"]} == {"CE.pdf", "MQ.xlsx"}


def test_ficha_reaproveita_o_cache_da_segunda_leitura(monkeypatch: pytest.MonkeyPatch):
    contagem = {"chamadas": 0}

    def _em_memoria(url: str, **_kwargs: Any) -> Dict[str, Any]:
        contagem["chamadas"] += 1
        return {"uid": UID, "publicado": True, "total": 1, "incluidas": 1, "pecas": [{"nome": "CE.pdf", "extensao": ".pdf", "texto": "Caução: 5 %"}]}

    monkeypatch.setattr(vortal, "pecas_em_memoria", _em_memoria)
    cd.contract_document("11970015", CONTRATO)
    segunda = cd.contract_document("11970015", CONTRATO)
    assert contagem["chamadas"] == 1
    assert segunda["source"] == "vortal"
    assert segunda["pieces_total"] == 1


def test_ficha_com_ligacao_vortal_estranha_nao_quebra(monkeypatch: pytest.MonkeyPatch):
    """Se a plataforma recusar, a ficha mantém ligações e valores do contrato."""

    def _falha(url: str, **_kwargs: Any):
        raise RuntimeError("anfitrião não autorizado")

    monkeypatch.setattr(vortal, "pecas_em_memoria", _falha)
    ficha = cd.contract_document("11970015", CONTRATO)
    assert ficha["error"] and "Vortal" in ficha["error"]
    assert ficha["pieces"] == []
    assert ficha["values"] is not None
