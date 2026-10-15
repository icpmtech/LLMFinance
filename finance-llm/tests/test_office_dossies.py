"""`source` de um documento do Office: origem textual (antiga) e origem em objeto.

Os documentos mais antigos guardam a origem como texto (`"mirofish"`) e os novos
como objeto (`{"type": "dossier360", ...}`). O código que lia o campo à espera de
objeto rebentava com `'str' object has no attribute 'get'` — o
`GET /office/dossiers/available` respondia **500** por causa de um único documento
de semente com `source: "mirofish"` (a página `/documentos` ficava sem dados).

Nada aqui toca em `data/`: a loja do Office vive em `tmp_path`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import office_routes, office_store  # noqa: E402


@pytest.fixture()
def loja(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Loja do Office isolada em `tmp_path` (sem ler nem escrever em `data/`)."""
    monkeypatch.setattr(office_store, "OFFICE_DIR", tmp_path)
    monkeypatch.setattr(office_store, "OFFICE_PATH", tmp_path / "office.json")
    office_store._cache = None
    yield tmp_path / "office.json"
    office_store._cache = None


def _guardar(caminho: Path, documentos: List[Dict[str, Any]]) -> None:
    caminho.write_text(
        json.dumps({"version": 1, "documents": documentos, "folders": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    office_store._cache = None


def _documento(document_id: str, source: Any) -> Dict[str, Any]:
    return {
        "id": document_id,
        "title": document_id,
        "kind": "dossier",
        "markdown": "# conteúdo",
        "words": 2,
        "tags": [],
        "author": "qa@iqos.local",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "source": source,
    }


# ------------------------------------------------------------------ normalização
def test_source_metadata_aceita_texto_objeto_e_vazio() -> None:
    assert office_store.source_metadata("mirofish") == {"type": "mirofish"}
    assert office_store.source_metadata("  mirofish  ") == {"type": "mirofish"}
    assert office_store.source_metadata({"type": "dossier360", "id": "x"}) == {"type": "dossier360", "id": "x"}
    assert office_store.source_metadata(None) == {}
    assert office_store.source_metadata("") == {}
    assert office_store.source_metadata("   ") == {}
    assert office_store.source_metadata(42) == {}


def test_source_metadata_nao_devolve_o_objeto_original() -> None:
    """Quem recebe o resultado não pode alterar o documento por referência."""
    original = {"type": "sentiment"}
    copia = office_store.source_metadata(original)
    copia["type"] = "outro"
    assert original == {"type": "sentiment"}


def test_listagem_devolve_source_sempre_como_objeto(loja: Path) -> None:
    _guardar(loja, [_documento("semente", "mirofish"), _documento("dossie", {"type": "dossier360", "id": "d1"})])
    itens = {item["id"]: item for item in office_store.list_documents(limit=50)["items"]}
    assert itens["semente"]["source"] == {"type": "mirofish"}
    assert itens["dossie"]["source"] == {"type": "dossier360", "id": "d1"}


# ---------------------------------------------------------------- rota dos dossiês
def test_dossies_disponiveis_liga_o_documento_do_dossie(loja: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _guardar(
        loja,
        [
            _documento("semente", "mirofish"),
            _documento("edp_dossie_360", {"type": "dossier360", "id": "edp_dossie_360"}),
        ],
    )
    monkeypatch.setattr(
        office_routes.dossier_store,
        "list_dossiers",
        lambda limit=40: {
            "total": 2,
            "items": [{"id": "edp_dossie_360"}, {"id": "sem_documento_dossie_360"}],
        },
    )

    resposta = office_routes.available_dossiers(limit=40)

    assert resposta["total"] == 2
    ligados = {item["id"]: item["document_id"] for item in resposta["items"]}
    assert ligados == {"edp_dossie_360": "edp_dossie_360", "sem_documento_dossie_360": None}


def test_dossies_disponiveis_com_origem_textual_nao_rebenta(loja: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Era este o 500: um documento com `source` textual rebentava a rota inteira."""
    _guardar(loja, [_documento("semente", "mirofish")])
    monkeypatch.setattr(
        office_routes.dossier_store,
        "list_dossiers",
        lambda limit=40: {"total": 0, "items": []},
    )

    resposta = office_routes.available_dossiers(limit=40)

    assert resposta == {"total": 0, "items": []}


# --------------------------------------------------------- dossiê -> documento
def test_documento_de_dossie_convive_com_origem_textual(loja: Path) -> None:
    """`document_from_dossier` também lia `source` como objeto ao procurar o existente."""
    _guardar(loja, [_documento("semente", "mirofish")])
    dossie = {"id": "edp_dossie_360", "term": "EDP", "title": "EDP — dossiê 360", "ontology_id": "iqos", "snapshot": {}}

    documento = office_store.document_from_dossier(dossie, "# EDP", author="qa@iqos.local")

    # O id sai do título quando o dossiê ainda não tem documento ligado.
    assert documento["id"] == "edp_dossie_360"
    assert documento["source"]["type"] == "dossier360"
    assert documento["source"]["id"] == "edp_dossie_360"

    # A segunda passagem reencontra o documento pelo `source` (é aqui que a origem
    # textual rebentava) em vez de criar um duplicado.
    assert office_store.document_from_dossier(dossie, "# EDP (revisto)")["id"] == "edp_dossie_360"
    assert len(office_store.list_documents(limit=50)["items"]) == 2
