"""Indexação parcial de publicações societárias (regressão 2026-10-01).

A recolha com **janela de datas** (ex.: «um mês») devolve apenas uma parte das
publicações da entidade. Como `index_societario_items` apagava os registos da
entidade que não constassem da recolha atual, uma janela de setembro apagava
tudo o que estava fora dela: a JAJA (503106542) passou de 25 publicações para 1
depois de recolher a janela 2026-07-01→2026-09-30.

`drop_stale` passa a ser explícito: só uma recolha **completa** (sem janela)
pode remover obsoletos.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from api import elasticsearch_client as esc

ITEM = {
    "pub_id": "a1b2c3",
    "nif": "503106542",
    "firma": "JAJA - GESTÃO E INVESTIMENTOS S.A.",
    "data_publicacao": "2026-07-14",
    "acto": "PRESTAÇÃO DE CONTAS INDIVIDUAL",
}


@pytest.fixture()
def es_falso(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    """Substitui o cliente ES e conta as limpezas de obsoletos."""
    registo: Dict[str, Any] = {"limpezas": 0, "indexados": 0}

    def fake_bulk(index: str, docs: List[Dict[str, Any]], id_field: str, es: Optional[Any] = None) -> Dict[str, Any]:
        registo["indexados"] += len(docs)
        return {"indexed_count": len(docs), "total": len(docs), "errors": 0}

    def fake_delete(index: str, field: str, value: str, keep_ids: List[str], es: Optional[Any] = None) -> int:
        registo["limpezas"] += 1
        registo["keep_ids"] = keep_ids
        return 7

    monkeypatch.setattr(esc, "_bulk_index_docs", fake_bulk)
    monkeypatch.setattr(esc, "_delete_stale_docs", fake_delete)
    return registo


def test_recolha_parcial_nao_apaga_publicacoes_fora_da_janela(es_falso: Dict[str, Any]) -> None:
    resultado = esc.index_societario_items(
        [ITEM], replace_for_nif="503106542", drop_stale=False, es=object()
    )
    assert es_falso["indexados"] == 1
    assert es_falso["limpezas"] == 0
    assert "deleted_stale" not in resultado


def test_recolha_completa_continua_a_remover_obsoletos(es_falso: Dict[str, Any]) -> None:
    resultado = esc.index_societario_items(
        [ITEM], replace_for_nif="503106542", drop_stale=True, es=object()
    )
    assert es_falso["limpezas"] == 1
    assert resultado["deleted_stale"] == 7
    assert es_falso["keep_ids"] == [f"{esc.SOCIETARIO_INDEX}:a1b2c3"]


def test_ingest_do_servico_propaga_drop_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    """`societario_service.ingest` não pode reintroduzir a limpeza por omissão."""
    from api import societario_service

    visto: Dict[str, Any] = {}

    def fake_index(items: List[Dict[str, Any]], replace_for_nif: Optional[str] = None,
                   drop_stale: bool = True, es: Optional[Any] = None) -> Dict[str, Any]:
        visto["drop_stale"] = drop_stale
        return {"indexed_count": len(items), "total": len(items)}

    monkeypatch.setattr(esc, "index_societario_items", fake_index)
    monkeypatch.setattr(esc, "index_people_from_societario", lambda **kwargs: {"indexed_count": 0, "total": 0})

    societario_service.ingest([ITEM], replace_for_nif="503106542", drop_stale=False)
    assert visto["drop_stale"] is False

    societario_service.ingest([ITEM], replace_for_nif="503106542")
    assert visto["drop_stale"] is True
