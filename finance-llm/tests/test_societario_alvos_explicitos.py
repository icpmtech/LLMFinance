"""«Obter dados societários» a partir da ficha de uma empresa.

Regressão de 2026-10-22: na ficha da entidade 502844205 (uma empresa sem
contratos públicos, só no diretório Racius) o botão «Obter dados societários»
terminava em segundos com «Nenhuma entidade elegível» e zero publicações.

Duas peças contribuíam:

* `societario_targets_filtered` exigia `country_code=PT`, `has_nif=true` e
  `contracts_count>=1` mesmo quando os NIFs vinham **explícitos** — a empresa
  nunca passava o filtro e nem chegava a ser recolhida;
* o trabalho desistia quando a seleção vinha vazia, sem tentar os NIFs pedidos.

Estes testes fixam as duas: com NIF explícito a recolha corre sempre.
"""
from __future__ import annotations

from typing import Any, Dict, List

from api import societario_recolha as recolha
from api.es.societario import societario_targets_filtered

NIF = "502844205"


class EsFalso:
    """Regista os pedidos e devolve uma entidade mínima e nenhuma publicação."""

    def __init__(self) -> None:
        self.corpos: List[Dict[str, Any]] = []

    def search(self, *, index: str = "", body: Dict[str, Any] | None = None, **_: Any) -> Dict[str, Any]:
        self.corpos.append({"index": index, "body": body or {}})
        if index == "finance_entities":
            return {"hits": {"hits": [{"_source": {"nif": NIF, "name": NIF}}]}}
        return {"aggregations": {"by_nif": {"buckets": []}}}


def _filtros(body: Dict[str, Any]) -> List[Dict[str, Any]]:
    return body["query"]["bool"]["filter"]


def test_nif_explicito_nao_exige_contratos() -> None:
    es = EsFalso()
    resposta = societario_targets_filtered(nifs=[NIF], es=es)

    filtros = _filtros(es.corpos[0]["body"])
    assert {"terms": {"nif": [NIF]}} in filtros
    for proibido in ("country_code", "has_nif", "contracts_count"):
        assert not any(proibido in filtro.get("term", {}) or proibido in filtro.get("range", {}) for filtro in filtros)
    assert [item["nif"] for item in resposta["items"]] == [NIF]


def test_sem_nif_explicito_mantem_filtros_de_elegibilidade() -> None:
    es = EsFalso()
    societario_targets_filtered(es=es)

    filtros = _filtros(es.corpos[0]["body"])
    assert {"term": {"country_code": "PT"}} in filtros
    assert {"term": {"has_nif": True}} in filtros
    assert any("contracts_count" in filtro.get("range", {}) for filtro in filtros)


class _PublicacaoFalsa:
    def __init__(self, acto: str) -> None:
        self._acto = acto

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pub_id": f"pub-{self._acto}",
            "nif": NIF,
            "entidade": "AIRES & AIRES LDA",
            "data_publicacao": "2026-07-15",
            "acto": self._acto,
        }


class _ClienteFalso:
    """Substitui o cliente do MJ (que precisaria de 2captcha e do portal)."""

    def __init__(self, **_: Any) -> None:
        pass

    def collect(self, **kwargs: Any) -> List[_PublicacaoFalsa]:
        return [_PublicacaoFalsa("PRESTAÇÃO DE CONTAS INDIVIDUAL"), _PublicacaoFalsa("ALTERAÇÃO DE SEDE")]


def test_trabalho_recorre_aos_nifs_explicitos(monkeypatch: Any) -> None:
    """Sem alvos no cadastro, o trabalho recolhe na mesma os NIFs pedidos."""
    gravados: List[Dict[str, Any]] = []

    monkeypatch.setattr(recolha, "targets", lambda **_: {"items": [], "total": 0})
    monkeypatch.setattr(
        recolha,
        "write_export",
        lambda nif, nome, items, criteria=None: gravados.append({"nif": nif, "name": nome, "total": len(items)})
        or {"nif": nif, "name": nome, "total": len(items)},
    )
    monkeypatch.setattr(recolha.societario, "ingest", lambda *_, **__: {"indexed_count": 2})
    monkeypatch.setattr("collectors.publicacoes_mj_captcha.PublicacoesMjCaptchaClient", _ClienteFalso)

    job: Dict[str, Any] = {
        "job_id": "teste-nif-explicito",
        "status": recolha._RUNNING,
        "stop_requested": False,
        "payload": {"nifs": [NIF], "max_entities": 1, "ingest": True, "with_details": False},
        "progress": {
            "phase": "a escolher os alvos",
            "entities_done": 0,
            "entities_total": 0,
            "publications": 0,
            "files": 0,
            "publications_live": 0,
            "pages_read": 0,
            "saved_total": 0,
            "current": None,
        },
        "result": None,
        "error": None,
    }

    recolha._run_job_inner(job)

    assert job["status"] == "done"
    assert job["result"]["entities"] == 1
    assert job["result"]["publications"] == 2
    assert gravados == [{"nif": NIF, "name": "AIRES & AIRES LDA", "total": 2}]
