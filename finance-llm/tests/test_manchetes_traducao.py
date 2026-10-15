"""Tradução PT das manchetes do mercado com IA: cache, lotes e honestidade.

O que se testa aqui, por ordem de importância:

* a tradução é **em lote** e a mesma manchete nunca é enviada duas vezes ao
  modelo — a segunda chamada sai toda da cache, mesmo depois de o módulo perder
  o que tinha em memória (é o que acontece num reinício do servidor);
* uma manchete que **já estava em português** fica contada em `unchanged` e é
  guardada na cache (não volta a ser paga);
* uma resposta **inutilizável** do modelo conta como falha e não envenena a
  cache: a manchete fica por traduzir e é tentada outra vez;
* **sem fornecedor de IA configurado** a função diz que não traduziu, em vez de
  devolver o inglês como se fosse tradução;
* a rota `POST /sentiment/market/translate` faz exatamente isto.

Nenhum teste fala com o modelo: `pick_provider` e `cloud_chat.complete_answer`
são substituídos.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import cloud_chat  # noqa: E402
from api import main  # noqa: E402
from api import manchetes_traducao as mt  # noqa: E402
from api import scraper_ai  # noqa: E402

PROVIDER = ("fake-ai", {"label": "IA de teste", "default_model": "fake-1"}, "fake-1", "chave")


@pytest.fixture(autouse=True)
def cache_em_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Cache isolada por teste (o ficheiro real nunca é tocado)."""
    monkeypatch.setattr(mt, "CACHE_PATH", tmp_path / "manchetes-pt.json")
    monkeypatch.setattr(mt, "_cache", None)
    return tmp_path / "manchetes-pt.json"


def _modelo(monkeypatch: pytest.MonkeyPatch, resposta) -> List[List[str]]:
    """Substitui o modelo: devolve os lotes recebidos, na ordem em que chegaram."""
    monkeypatch.setattr(
        scraper_ai,
        "pick_provider",
        lambda *args, **kwargs: PROVIDER,
    )
    lotes: List[List[str]] = []

    async def complete_answer(*, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        lote = json.loads(messages[-1]["content"])
        lotes.append([str(item) for item in lote])
        return resposta(lote)

    monkeypatch.setattr(cloud_chat, "complete_answer", complete_answer)
    return lotes


def test_traduz_por_lotes_e_nao_repete_o_que_ja_traduziu(
    cache_em_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lotes = _modelo(monkeypatch, lambda lote: json.dumps([f"PT: {item}" for item in lote]))
    titulos = ["Apple beats estimates", "Tesla cuts prices", "Oil rises 3 %"]

    primeiro = mt.traduzir_manchetes(titulos)

    assert primeiro["requested"] == 3
    assert primeiro["translated"] == 3
    assert primeiro["cached"] == 0
    assert primeiro["failed"] == 0
    assert primeiro["translations"]["Apple beats estimates"] == "PT: Apple beats estimates"
    assert primeiro["ai"]["provider_label"] == "IA de teste"
    assert len(lotes) == 1 and lotes[0] == titulos
    assert cache_em_tmp.is_file()

    # Reinício do servidor: a cache em memória perde-se, a do disco não.
    monkeypatch.setattr(mt, "_cache", None)
    segundo = mt.traduzir_manchetes(titulos + ["Novo título"])

    assert segundo["cached"] == 3
    assert segundo["translated"] == 1
    assert len(lotes) == 2 and lotes[1] == ["Novo título"]


def test_lotes_respeitam_o_limite_de_itens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mt, "MAX_ITENS", 2)
    lotes = _modelo(monkeypatch, lambda lote: json.dumps([f"PT: {item}" for item in lote]))

    resultado = mt.traduzir_manchetes(["a", "b", "c", "d", "e"])

    assert resultado["translated"] == 5
    assert [len(lote) for lote in lotes] == [2, 2, 1]


def test_manchete_ja_em_portugues_fica_na_cache_e_em_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lotes = _modelo(monkeypatch, lambda lote: json.dumps(list(lote)))

    primeiro = mt.traduzir_manchetes(["EDP sobe com resultados", "Apple beats estimates"])

    assert primeiro["unchanged"] == 2
    assert primeiro["translated"] == 0
    assert primeiro["failed"] == 0
    assert primeiro["translations"]["EDP sobe com resultados"] == "EDP sobe com resultados"

    monkeypatch.setattr(mt, "_cache", None)
    segundo = mt.traduzir_manchetes(["EDP sobe com resultados"])

    assert segundo["cached"] == 1
    assert len(lotes) == 1


def test_resposta_inutilizavel_conta_como_falha_e_nao_entra_na_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lotes = _modelo(monkeypatch, lambda lote: "desculpa, não consigo traduzir")

    resultado = mt.traduzir_manchetes(["Apple beats estimates"])

    assert resultado["failed"] == 1
    assert resultado["translated"] == 0
    assert resultado["translations"] == {}
    assert resultado["status"]["cached"] == 0

    # Sem cache, a manchete é tentada outra vez.
    mt.traduzir_manchetes(["Apple beats estimates"])
    assert len(lotes) == 2


def test_sem_fornecedor_configurado_devolve_erro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scraper_ai, "pick_provider", lambda *args, **kwargs: (None, None, None, None))

    resultado = mt.traduzir_manchetes(["Apple beats estimates"])

    assert "fornecedor de IA" in resultado["error"]
    assert resultado["translations"] == {}
    assert resultado["requested"] == 1


def test_rota_traduz_manchetes(monkeypatch: pytest.MonkeyPatch) -> None:
    _modelo(monkeypatch, lambda lote: json.dumps([f"PT: {item}" for item in lote]))
    cliente = TestClient(main.app)

    resposta = cliente.post(
        "/sentiment/market/translate",
        json={"texts": ["Apple beats estimates", "  ", "Tesla cuts prices"]},
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["translations"]["Apple beats estimates"] == "PT: Apple beats estimates"
    assert corpo["translated"] == 2
    assert corpo["requested"] == 2

    vazio = cliente.post("/sentiment/market/translate", json={"texts": []})
    assert vazio.status_code == 422


def test_sem_fornecedor_a_rota_diz_porque(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scraper_ai, "pick_provider", lambda *args, **kwargs: (None, None, None, None))
    cliente = TestClient(main.app)

    resposta = cliente.post("/sentiment/market/translate", json={"texts": ["Apple beats estimates"]})

    assert resposta.status_code == 409
    assert "fornecedor de IA" in resposta.json()["detail"]
