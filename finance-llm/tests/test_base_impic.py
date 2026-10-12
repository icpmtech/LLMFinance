"""Testes da importação dos Contratos Públicos do Portal Base (dados.gov.pt).

Cobrem as peças que não dependem da rede nem do Elasticsearch: a leitura do
catálogo da API do dados.gov.pt, o reconhecimento do formato do ZIP (array JSON
vs NDJSON), o **leitor em streaming** (o JSON do ano tem centenas de MB e tem de
ser lido por blocos) e a comparação de `sha1` que decide se o ZIP em cache ainda
serve ou tem de ser descarregado de novo.

O ZIP de teste é construído em memória: assim o teste continua válido quando o
IMPIC publicar o ano seguinte.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from api import base_impic


def _zip_com(nome: str, conteudo: str, tmp_path: Path) -> Path:
    caminho = tmp_path / "contratos2099.zip"
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as zipper:
        zipper.writestr(nome, conteudo)
    return caminho


# --------------------------------------------------------------------- leitura


def test_iter_registos_le_array_json_em_blocos_pequenos(tmp_path: Path) -> None:
    """O leitor tem de atravessar blocos — o JSON real tem 300 MB."""
    registos = [
        {"idcontrato": f"{i}", "objectoContrato": f"contrato {i} " + ("á" * 40) if i % 2 else f"contrato {i}"}
        for i in range(50)
    ]
    caminho = _zip_com("Contratos2099.json", json.dumps(registos, ensure_ascii=False), tmp_path)

    # Bloco de 64 bytes: muito mais pequeno do que um registo.
    lidos = list(base_impic.iter_registos(caminho, bloco=64))

    assert len(lidos) == 50
    assert lidos[0]["idcontrato"] == "0"
    assert lidos[-1]["idcontrato"] == "49"


def test_iter_registos_respeita_o_limite(tmp_path: Path) -> None:
    registos = [{"idcontrato": str(i)} for i in range(20)]
    caminho = _zip_com("Contratos2099.json", json.dumps(registos), tmp_path)

    lidos = list(base_impic.iter_registos(caminho, limite=7))

    assert [item["idcontrato"] for item in lidos] == [str(i) for i in range(7)]


def test_iter_registos_aceita_ndjson(tmp_path: Path) -> None:
    texto = "\n".join(json.dumps({"idcontrato": str(i)}) for i in range(5))
    caminho = _zip_com("contratos.json", texto, tmp_path)

    assert len(list(base_impic.iter_registos(caminho, bloco=32))) == 5


def test_iter_registos_sem_json_no_zip(tmp_path: Path) -> None:
    caminho = _zip_com("leia-me.txt", "sem json", tmp_path)

    with pytest.raises(ValueError):
        list(base_impic.iter_registos(caminho))


def test_membro_json_aceita_path_e_zipfile_aberto(tmp_path: Path) -> None:
    """Regressão: o leitor em streaming passava o caminho a quem esperava o ZipFile."""
    caminho = _zip_com("Contratos2099.json", "[]", tmp_path)

    assert base_impic.membro_json(caminho).filename == "Contratos2099.json"
    with zipfile.ZipFile(caminho) as zipper:
        assert base_impic.membro_json(zipper).filename == "Contratos2099.json"


# --------------------------------------------------------------------- formato


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ('[{"idcontrato": "1"}]', "array JSON"),
        ('  \n [ ]', "array JSON"),
        ('{"idcontrato": "1"}\n{"idcontrato": "2"}', "objeto JSON (possivelmente NDJSON)"),
        ("", "desconhecida"),
    ],
)
def test_forma_json(texto: str, esperado: str) -> None:
    assert base_impic._forma_json(texto) == esperado


def test_primeiro_registo_le_o_primeiro_objeto() -> None:
    registo = base_impic._primeiro_registo('[\n {"idcontrato": "12014814", "Ano": 2026},\n {"idcontrato": "2"}]')

    assert registo == {"idcontrato": "12014814", "Ano": 2026}


def test_primeiro_registo_sem_objeto() -> None:
    assert base_impic._primeiro_registo("[]") is None


# -------------------------------------------------------------------- catálogo


def test_listar_recursos_le_a_api_do_dados_gov_pt(monkeypatch: pytest.MonkeyPatch) -> None:
    corpo = {
        "resources": [
            {
                "title": "contratos2026.zip",
                "format": "zip",
                "filesize": 40047831,
                "last_modified": "2026-10-11T09:04:13",
                "url": "https://dados.gov.pt/zip/2026",
                "latest": "https://dados.gov.pt/zip/2026/latest",
                "checksum": {"value": "abc123"},
                "id": "r1",
            },
            {"title": "contratos2026.xlsx", "format": "xlsx", "filesize": 100, "url": "https://dados.gov.pt/xlsx/2026"},
        ]
    }

    class _Resposta:
        def raise_for_status(self) -> None:  # pragma: no cover - sem erro
            return None

        def json(self) -> dict:
            return corpo

    class _Cliente:
        def __enter__(self) -> "_Cliente":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, url: str) -> _Resposta:
            assert url == base_impic.DATASET_API
            return _Resposta()

    monkeypatch.setattr(base_impic.httpx, "Client", lambda **_kwargs: _Cliente())
    monkeypatch.setitem(base_impic._cache, "recursos", None)

    recursos = base_impic.listar_recursos(forcar=True)

    # Ordenados por (ano, formato): o ZIP vem depois do XLSX.
    assert [item["ano"] for item in recursos] == ["2026", "2026"]
    zip_2026 = base_impic.encontrar_recurso(recursos, 2026, "zip")
    assert zip_2026["bytes"] == 40047831
    assert zip_2026["sha1"] == "abc123"
    assert zip_2026["url_estavel"] == "https://dados.gov.pt/zip/2026/latest"
    assert zip_2026["atualizado_em"] == "2026-10-11T09:04:13"


def test_encontrar_recurso_por_ano_e_formato() -> None:
    recursos = [
        {"ano": "2025", "formato": "zip"},
        {"ano": "2026", "formato": "zip"},
        {"ano": "2026", "formato": "xlsx"},
    ]

    assert base_impic.encontrar_recurso(recursos, 2026, "xlsx")["formato"] == "xlsx"
    assert base_impic.encontrar_recurso(recursos, "2026")["formato"] == "zip"
    assert base_impic.encontrar_recurso(recursos, 1999) is None


def test_ano_atual_usa_o_zip_mais_recente(monkeypatch: pytest.MonkeyPatch) -> None:
    """Em Janeiro o conjunto pode ainda não ter o ano novo do relógio."""
    monkeypatch.setattr(
        base_impic,
        "listar_recursos",
        lambda **_kwargs: [{"ano": "2026", "formato": "zip"}, {"ano": "2012", "formato": "zip"}],
    )

    assert base_impic.ano_atual() == 2026


def test_caminho_local_segue_a_convencao_do_pipeline() -> None:
    assert base_impic.caminho_local(2026).name == "contratos2026.zip"
    assert base_impic.caminho_local("2026", "xlsx").name == "contratos2026.xlsx"


# ------------------------------------------------------------------ cache/sha1


def test_descarregar_reutiliza_o_ficheiro_quando_o_sha1_confere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destino = tmp_path / "contratos2026.zip"
    destino.write_bytes(b"conteudo-do-zip")
    monkeypatch.setattr(base_impic, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(base_impic, "caminho_local", lambda ano, formato="zip": destino)

    def _nao_descarregar(*_args: object, **_kwargs: object) -> None:  # pragma: no cover
        raise AssertionError("não devia descarregar: o SHA-1 confere")

    monkeypatch.setattr(base_impic.httpx, "Client", _nao_descarregar)
    recurso = {"ano": "2026", "formato": "zip", "bytes": len(b"conteudo-do-zip"), "sha1": base_impic._sha1(destino)}

    assert base_impic.descarregar(recurso) == destino


def test_descarregar_ignora_cache_desactualizado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """O conjunto é actualizado semanalmente: um ZIP antigo não pode passar.

    O que se testa é a decisão (detecta que não serve), não o descarregamento.
    """
    destino = tmp_path / "contratos2026.zip"
    destino.write_bytes(b"versao-antiga")
    monkeypatch.setattr(base_impic, "caminho_local", lambda ano, formato="zip": destino)

    class _Cliente:
        def __enter__(self) -> "_Cliente":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def stream(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("chegou a descarregar: era isso que se esperava")

    monkeypatch.setattr(base_impic.httpx, "Client", lambda **_kwargs: _Cliente())
    recurso = {"ano": "2026", "formato": "zip", "bytes": 11, "sha1": "outro-sha1", "url": "https://dados.gov.pt/x"}

    with pytest.raises(AssertionError):
        base_impic.descarregar(recurso)


# ---------------------------------------------------------------------- estado


def test_estado_por_omissao_e_parado_e_cancelar_sem_trabalho() -> None:
    estado = base_impic.estado(1999)

    assert estado["estado"] == "parado"
    assert estado["ano"] == 1999
    assert base_impic.cancelar(1999)["cancelado"] is False


def test_importar_em_segundo_plano_e_idempotente_por_idcontrato(monkeypatch: pytest.MonkeyPatch) -> None:
    """O pedido de importação só arranca uma vez por ano (o segundo é recusado)."""
    base_impic._trabalhos.pop(2026, None)

    def _nao_correr(*_args: object, **_kwargs: object) -> None:  # pragma: no cover
        return None

    monkeypatch.setattr(base_impic, "_correr_importacao", _nao_correr)
    monkeypatch.setattr(base_impic.threading, "Thread", lambda **_kwargs: type("T", (), {"start": lambda self: None})())

    primeiro = base_impic.importar(2026)
    assert primeiro["iniciado"] is True
    assert primeiro["ano"] == 2026

    base_impic._atualizar(2026, estado="a_correr")
    segundo = base_impic.importar(2026)
    assert segundo["iniciado"] is False
    assert "a correr" in segundo["mensagem"]

    base_impic._trabalhos.pop(2026, None)


# ---------------------------------------------------------------- amostra/índice


def test_amostra_sem_zip_em_cache_avisa(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(base_impic, "caminho_local", lambda ano, formato="zip": tmp_path / "inexistente.zip")

    assert "erro" in base_impic.amostra(2026)


def test_resumo_indice_sem_elasticsearch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("api.elasticsearch_client.get_es_client", lambda: None)

    assert base_impic.resumo_indice()["disponivel"] is False


def test_resumo_indice_conta_por_ano(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Cliente:
        def search(self, **_kwargs: object) -> dict:
            return {
                "hits": {"total": {"value": 2250969}},
                "aggregations": {"anos": {"buckets": [{"key": 2026, "doc_count": 173500}, {"key": 2012, "doc_count": 13315}]}},
            }

    monkeypatch.setattr("api.elasticsearch_client.get_es_client", lambda: _Cliente())

    resumo = base_impic.resumo_indice()

    assert resumo["disponivel"] is True
    assert resumo["indice"] == "contratos"
    assert resumo["total"] == 2250969
    assert resumo["por_ano"][0] == {"ano": 2026, "contratos": 173500}
