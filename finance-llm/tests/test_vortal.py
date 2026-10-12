"""Peças do procedimento da Vortal — resolução, descarga, texto e índice.

Testes puros: a sessão HTTP e o Elasticsearch são falsos, o disco é `tmp_path`.
O que se fixa aqui é o contrato do módulo:

- o token sai do URL da página pública de peças (e o UID do `contractNoticeUrl`);
- a lista de peças é normalizada (nome, extensão, tipo) a partir da API;
- nomes de ficheiro perigosos (`../`, barras, controlos) não saem do destino;
- descarregar é **idempotente** (o mesmo `sha256` não se volta a descarregar);
- só se descarrega de `*.vortal.biz` (guarda contra SSRF);
- PDF digitalizado fica marcado (`precisa_ocr`), em vez de parecer vazio;
- o índice recebe um documento por peça, com `_id` estável (`uid::sha256`);
- o histórico de recolhas é o que alimenta a monitorização de administração.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from api import vortal_service as vortal

TOKEN = "NDR3OVplcDc3Q2ZSb1RWUEpQaDd4MTVMWnBtN3o1OEsvbElnN2hDTjBxM1RUNUQxc1FNbDR5Z29xdytt"
URL_PAGINA = f"https://community.vortal.biz/Public/public-tender-documents/{TOKEN}"
UID = "PT1.NTC.3612674"
URL_AVISO = f"https://community.vortal.biz/Public/contract-notice-view/{UID}/"


# --------------------------------------------------------------------- falsos
class _Resposta:
    def __init__(self, *, json_dados: Any = None, conteudo: bytes = b"", cabecalhos: Optional[Dict[str, str]] = None, estado: int = 200) -> None:
        self._json = json_dados
        self._conteudo = conteudo
        self.headers = cabecalhos or {}
        self.status_code = estado

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, tamanho: int = 65536):
        for inicio in range(0, len(self._conteudo), tamanho):
            yield self._conteudo[inicio : inicio + tamanho]


class _Sessao:
    """Sessão falsa: devolve respostas por URL (prefixo) e regista os pedidos."""

    def __init__(self, respostas: Dict[str, _Resposta]) -> None:
        self.respostas = respostas
        self.pedidos: List[Dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> _Resposta:
        self.pedidos.append({"url": url, **kwargs})
        for chave, resposta in self.respostas.items():
            if url.startswith(chave):
                return resposta
        raise AssertionError(f"pedido inesperado: {url}")


class _ES:
    """Cliente de Elasticsearch mínimo (contagem e pesquisa)."""

    def __init__(self, *, total: int = 0, aggs: Optional[Dict[str, Any]] = None, hits: Optional[List[Dict[str, Any]]] = None) -> None:
        self.total = total
        self.aggs = aggs or {"avisos": {"value": 0}, "bytes": {"value": 0}}
        self.hits = hits or []
        self.pedidos: List[Dict[str, Any]] = []

    def count(self, **_kwargs: Any) -> Dict[str, Any]:
        return {"count": self.total}

    def search(self, **kwargs: Any) -> Dict[str, Any]:
        self.pedidos.append(kwargs)
        return {
            "aggregations": self.aggs,
            "hits": {"total": {"value": self.total}, "hits": self.hits},
        }

    def indices(self):  # pragma: no cover - só usado pelo caminho de `recriar`
        raise AssertionError("índice não deve ser tocado neste teste")


@pytest.fixture(autouse=True)
def _sem_elastico(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nenhum teste fala com o Elasticsearch real."""
    monkeypatch.setattr(vortal, "ensure_indices", lambda *args, **kwargs: True)


# ----------------------------------------------------------------- identificação
def test_token_de_url_aceita_url_query_e_token_cru():
    assert vortal.token_de_url(URL_PAGINA) == TOKEN
    assert vortal.token_de_url(f"{URL_PAGINA}?currentLanguage=en") == TOKEN
    assert vortal.token_de_url(TOKEN) == TOKEN
    assert vortal.token_de_url("https://community.vortal.biz/Public/contract-notice-view/PT1.NTC.1/") is None
    assert vortal.token_de_url("") is None


def test_uid_de_url_aceita_url_e_uid_cru():
    assert vortal.uid_de_url(URL_AVISO) == UID
    assert vortal.uid_de_url(UID) == UID
    assert vortal.uid_de_url("https://example.com/x") is None


def test_informacao_aviso_extrai_uid_publicado_e_url():
    sessao = _Sessao(
        {
            f"{vortal.PUBLICO}/api/PublicTenderDocuments/GetPublicTenderInformation": _Resposta(
                json_dados={
                    "documentList": [],
                    "contractNoticeUrl": URL_AVISO,
                    "tenderInformation": {"tenderIsPublished": True},
                }
            )
        }
    )
    info = vortal.informacao_aviso(TOKEN, cliente=sessao)
    assert info["uid"] == UID
    assert info["publicado"] is True
    assert info["url_aviso"] == URL_AVISO
    assert sessao.pedidos[0]["params"]["uniqueIdentifierEncrypted"] == TOKEN


def test_documentos_do_aviso_normaliza_lista():
    sessao = _Sessao(
        {
            f"{vortal.PUBLICO}/api/ContractNoticeDetail/GetContractNoticeDocuments": _Resposta(
                json_dados=[
                    {"id": 1, "fileId": "ABC", "name": "CE_Refª 2026.pdf", "description": "caderno", "downloadUrl": "https://community.vortal.biz/archive/x"},
                    {"id": 2, "name": "Mapa de Quantidades.xlsx", "downloadUrl": "https://community.vortal.biz/archive/y"},
                    {"sem": "nome"},
                ]
            )
        }
    )
    pecas = vortal.documentos_do_aviso(UID, cliente=sessao)
    assert [peca["nome"] for peca in pecas] == ["CE_Refª 2026.pdf", "Mapa de Quantidades.xlsx"]
    assert pecas[0]["extensao"] == ".pdf"
    assert pecas[0]["tipo"] == "caderno_encargos"
    assert pecas[1]["tipo"] == "mapa_quantidades"
    assert all(peca["uid"] == UID for peca in pecas)


def test_documentos_do_aviso_aceita_resposta_embrulhada():
    sessao = _Sessao(
        {
            f"{vortal.PUBLICO}/api/ContractNoticeDetail/GetContractNoticeDocuments": _Resposta(
                json_dados={"documents": [{"id": 9, "name": "espd-request.xml", "downloadUrl": "https://community.vortal.biz/archive/z"}]}
            )
        }
    )
    pecas = vortal.documentos_do_aviso(UID, cliente=sessao)
    assert len(pecas) == 1
    assert pecas[0]["tipo"] == "espd"


# -------------------------------------------------------------------- nomes
@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("CE_Refª 2026.pdf", "CE_Refª 2026.pdf"),
        ("../../etc/passwd", "passwd"),
        ("pasta\\sub\\peca.docx", "peca.docx"),
        ('nome:com"caracteres?ruins*.pdf', "nome_com_caracteres_ruins_.pdf"),
        ("   .   ", "peca"),
    ],
)
def test_nome_ficheiro_seguro(entrada, esperado):
    assert vortal.nome_ficheiro_seguro(entrada) == esperado


def test_nome_ficheiro_seguro_corta_mantendo_extensao():
    nome = vortal.nome_ficheiro_seguro("a" * 400 + ".pdf", limite=40)
    assert len(nome) <= 40
    assert nome.endswith(".pdf")


@pytest.mark.parametrize(
    ("nome", "tipo"),
    [
        ("CE_Consumíveis.pdf", "caderno_encargos"),
        ("PC Retificado_2026.pdf", "programa_concurso"),
        ("2026_Mapa de Quantidades (Anexo II CE).xlsx", "caderno_encargos"),
        ("Modelo de resposta (Anexo I PC).xlsx", "programa_concurso"),
        ("espd-request.xml", "espd"),
        ("Resposta a Esclarecimentos.pdf", "esclarecimentos"),
        ("ID Prorrogação de Prazo.pdf", "prorrogacao"),
        ("qualquer-coisa.bin", "outro"),
    ],
)
def test_tipo_da_peca(nome, tipo):
    assert vortal.tipo_da_peca(nome) == tipo


# ------------------------------------------------------------------ descarga
def test_descarregar_peca_grava_e_e_idempotente(tmp_path: Path):
    conteudo = b"%PDF-1.7 peca" * 100
    sessao = _Sessao({"https://community.vortal.biz/archive/ok": _Resposta(conteudo=conteudo, cabecalhos={"content-type": "application/pdf"})})
    peca = {"uid": UID, "nome": "CE.pdf", "url": "https://community.vortal.biz/archive/ok", "tipo": "caderno_encargos"}

    primeiro = vortal.descarregar_peca(peca, tmp_path, cliente=sessao)
    assert primeiro["bytes"] == len(conteudo)
    assert primeiro["sha256"] == vortal._sha256(conteudo)
    assert (tmp_path / "CE.pdf").is_file()
    assert len(sessao.pedidos) == 1

    segundo = vortal.descarregar_peca(peca, tmp_path, cliente=sessao)
    assert segundo["reutilizado"] is True
    assert segundo["sha256"] == primeiro["sha256"]
    assert len(sessao.pedidos) == 1, "não deve voltar a descarregar o que já tem o mesmo sha256"


def test_descarregar_peca_recusa_anfitriao_estranho(tmp_path: Path):
    sessao = _Sessao({})
    registo = vortal.descarregar_peca({"nome": "x.pdf", "url": "https://exemplo.pt/x.pdf"}, tmp_path, cliente=sessao)
    assert "anfitrião não autorizado" in str(registo["erro"])
    assert sessao.pedidos == []


def test_descarregar_peca_sem_url(tmp_path: Path):
    registo = vortal.descarregar_peca({"nome": "x.pdf"}, tmp_path, cliente=_Sessao({}))
    assert registo["erro"] == "sem URL de descarga"
    assert registo["bytes"] == 0


def test_descarregar_peca_usa_nome_do_content_disposition(tmp_path: Path):
    conteudo = b"conteudo"
    sessao = _Sessao(
        {
            "https://community.vortal.biz/archive/nome": _Resposta(
                conteudo=conteudo,
                cabecalhos={"content-disposition": "attachment; filename=\"a.pdf\"; filename*=UTF-8''CE%20Retificado.pdf"},
            )
        }
    )
    registo = vortal.descarregar_peca({"nome": "generico.pdf", "url": "https://community.vortal.biz/archive/nome"}, tmp_path, cliente=sessao)
    assert registo["ficheiro"] == "CE Retificado.pdf"
    assert (tmp_path / "CE Retificado.pdf").is_file()


def test_descarregar_peca_registra_erro_http(tmp_path: Path):
    sessao = _Sessao({"https://community.vortal.biz/archive/falha": _Resposta(estado=500)})
    registo = vortal.descarregar_peca({"nome": "x.pdf", "url": "https://community.vortal.biz/archive/falha"}, tmp_path, cliente=sessao)
    assert registo["erro"] and "RuntimeError" in registo["erro"]
    assert not (tmp_path / "x.pdf").exists()


# --------------------------------------------------------------------- texto
def test_extrair_texto_ficheiro_de_texto(tmp_path: Path):
    caminho = tmp_path / "nota.txt"
    caminho.write_text("Preço  base   100 €\n", encoding="utf-8")
    extraido = vortal.extrair_texto(caminho)
    assert extraido["meta"]["metodo"] == "texto"
    assert "Preço base 100 €" in extraido["texto"]


def test_extrair_texto_xml_sem_etiquetas(tmp_path: Path):
    caminho = tmp_path / "espd.xml"
    caminho.write_text("<root><a>Concorrente X</a><b>NIF 500000000</b></root>", encoding="utf-8")
    extraido = vortal.extrair_texto(caminho)
    assert "Concorrente X" in extraido["texto"]
    assert "<root>" not in extraido["texto"]


def test_extrair_texto_xlsx(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    livro = openpyxl.Workbook()
    folha = livro.active
    folha.title = "Quantidades"
    folha.append(["Artigo", "Quantidade"])
    folha.append(["Toner", 120])
    caminho = tmp_path / "mapa.xlsx"
    livro.save(caminho)
    extraido = vortal.extrair_texto(caminho)
    assert extraido["meta"]["metodo"] == "xlsx"
    assert "Toner | 120" in extraido["texto"]


def test_extrair_texto_pdf_marca_digitalizado(tmp_path: Path):
    fitz = pytest.importorskip("fitz")

    com_texto = fitz.open()
    pagina = com_texto.new_page()
    pagina.insert_text((72, 72), "Preco base: 100 EUR")
    caminho = tmp_path / "caderno.pdf"
    com_texto.save(caminho)
    com_texto.close()

    extraido = vortal.extrair_texto(caminho)
    assert extraido["meta"]["metodo"] == "pdf"
    assert extraido["meta"]["paginas"] == 1
    assert "Preco base" in extraido["texto"]

    vazio = fitz.open()
    vazio.new_page()  # imagem sem camada de texto
    caminho_vazio = tmp_path / "digitalizado.pdf"
    vazio.save(caminho_vazio)
    vazio.close()

    extraido_vazio = vortal.extrair_texto(caminho_vazio)
    assert extraido_vazio["texto"] == ""
    assert extraido_vazio["meta"]["metodo"] == "pdf-sem-texto"
    assert extraido_vazio["meta"]["precisa_ocr"] is True


def test_extrair_texto_binario_desconhecido(tmp_path: Path):
    caminho = tmp_path / "video.mp4"
    caminho.write_bytes(b"\x00\x01\x02\x03binario")
    extraido = vortal.extrair_texto(caminho)
    assert extraido["texto"] == ""
    assert extraido["meta"]["metodo"] == "binario"


def test_guardar_e_ler_texto(tmp_path: Path):
    relativo = vortal.guardar_texto("conteudo", tmp_path, "peca.pdf")
    assert relativo == "_texto/peca.pdf.txt"
    assert vortal.ler_texto(tmp_path, "peca.pdf") == "conteudo"
    assert vortal.ler_texto(tmp_path, "inexistente.pdf") == ""


# -------------------------------------------------------------------- recolha
def _pdf_de_teste(texto: str = "Preco base: 100 EUR") -> bytes:
    """PDF mínimo com texto (para a extração ser real, não simulada)."""
    fitz = pytest.importorskip("fitz")
    documento = fitz.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 72), texto)
    conteudo = documento.tobytes()
    documento.close()
    return conteudo


def _sessao_recolha() -> _Sessao:
    return _Sessao(
        {
            f"{vortal.PUBLICO}/api/PublicTenderDocuments/GetPublicTenderInformation": _Resposta(
                json_dados={"contractNoticeUrl": URL_AVISO, "tenderInformation": {"tenderIsPublished": True}, "documentList": []}
            ),
            f"{vortal.PUBLICO}/api/ContractNoticeDetail/GetContractNoticeDocuments": _Resposta(
                json_dados=[
                    {"id": 1, "fileId": "A", "name": "CE.pdf", "downloadUrl": "https://community.vortal.biz/archive/a"},
                    {"id": 2, "fileId": "B", "name": "PC.pdf", "downloadUrl": "https://exemplo.pt/b"},
                ]
            ),
            "https://community.vortal.biz/archive/a": _Resposta(conteudo=_pdf_de_teste()),
        }
    )


def test_recolher_escreve_disco_manifesto_e_texto(tmp_path: Path):
    resultado = vortal.recolher([URL_PAGINA], destino_base=tmp_path, cliente=_sessao_recolha(), indexar=False)
    assert resultado["avisos"] == 1
    assert resultado["pecas"] == 2
    assert resultado["bytes"] > 0
    assert len(resultado["erros"]) == 1  # a peça do anfitrião estranho
    assert "anfitrião não autorizado" in resultado["erros"][0]
    assert resultado["duracao_s"] is not None

    pasta = tmp_path / UID
    assert (pasta / "CE.pdf").is_file()
    texto = (pasta / "_texto" / "CE.pdf.txt").read_text(encoding="utf-8")
    assert "Preco base" in texto
    manifesto = json.loads((pasta / "_manifesto.json").read_text(encoding="utf-8"))
    assert manifesto["uid"] == UID
    assert manifesto["publicado"] is True
    assert manifesto["totais"]["pecas"] == 2
    assert manifesto["totais"]["com_texto"] == 1
    assert manifesto["totais"]["erros"] == 1
    assert manifesto["pecas"][0]["texto_ficheiro"] == "_texto/CE.pdf.txt"
    assert vortal.listar_avisos_em_disco(destino_base=tmp_path)[0]["uid"] == UID


def test_recolher_com_uid_em_cru(tmp_path: Path):
    sessao = _Sessao(
        {
            f"{vortal.PUBLICO}/api/ContractNoticeDetail/GetContractNoticeDocuments": _Resposta(
                json_dados=[{"id": 1, "name": "CE.pdf", "downloadUrl": "https://community.vortal.biz/archive/a"}]
            ),
            "https://community.vortal.biz/archive/a": _Resposta(conteudo=b"x"),
        }
    )
    resultado = vortal.recolher([UID], destino_base=tmp_path, cliente=sessao, indexar=False)
    assert resultado["avisos"] == 1
    assert resultado["detalhe"][0]["uid"] == UID


def test_recolher_regista_erro_quando_nao_resolve_o_aviso(tmp_path: Path):
    resultado = vortal.recolher(["https://exemplo.pt/nada"], destino_base=tmp_path, cliente=_Sessao({}), indexar=False)
    assert resultado["avisos"] == 0
    assert resultado["erros"]


# ------------------------------------------------------------------- histórico
def test_registar_e_ler_historico(tmp_path: Path):
    entrada = vortal.registar_recolha(
        {"avisos": 1, "pecas": 14, "bytes": 1000, "erros": ["x"], "indice": {"indexados": 14}, "destino": str(tmp_path)},
        autor="admin@iqos.pt",
        urls=[URL_PAGINA],
        destino_base=tmp_path,
    )
    assert entrada["autor"] == "admin@iqos.pt"
    assert entrada["indexados"] == 14
    historico = vortal.historico_recolhas(destino_base=tmp_path)
    assert len(historico) == 1 and historico[0]["pecas"] == 14
    assert (tmp_path / "_recolhas.json").is_file()


def test_historico_respeita_o_limite_e_a_ordem(tmp_path: Path):
    for indice in range(5):
        vortal.registar_recolha({"avisos": 1, "pecas": indice}, destino_base=tmp_path)
    historico = vortal.historico_recolhas(limite=2, destino_base=tmp_path)
    assert [item["pecas"] for item in historico] == [4, 3]


# ---------------------------------------------------------------------- índice
def test_documento_para_indice_leva_texto_e_id_estavel(tmp_path: Path):
    pasta = tmp_path / UID
    vortal.guardar_texto("texto indexado", pasta, "CE.pdf")
    aviso = {"uid": UID, "token": TOKEN, "pasta": str(pasta), "recolhido_em": "2026-10-12T00:00:00+00:00"}
    peca = {"uid": UID, "ficheiro": "CE.pdf", "nome": "CE.pdf", "tipo": "caderno_encargos", "sha256": "a" * 64, "bytes": 10, "texto_chars": 14}

    identificador, corpo = vortal.documento_para_indice(peca, aviso, destino_base=tmp_path)
    assert identificador == f"{UID}::{'a' * 16}"
    assert corpo["tipo_label"] == "Caderno de encargos"
    assert corpo["texto"] == "texto indexado"
    assert corpo["uid"] == UID
    assert "erro" not in corpo


def test_indexar_pecas_envia_um_documento_por_peca(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pasta = tmp_path / UID
    vortal.guardar_texto("conteudo", pasta, "CE.pdf")
    aviso = {
        "uid": UID,
        "pecas": [
            {"ficheiro": "CE.pdf", "nome": "CE.pdf", "tipo": "caderno_encargos", "sha256": "b" * 64, "bytes": 5},
            {"ficheiro": "PC.pdf", "nome": "PC.pdf", "tipo": "programa_concurso", "sha256": "c" * 64, "bytes": 5},
        ],
        "pasta": str(pasta),
    }
    capturado: Dict[str, Any] = {}

    def _bulk(cliente, acoes, **kwargs):
        capturado["acoes"] = list(acoes)
        return len(acoes), []

    monkeypatch.setattr(vortal, "bulk", _bulk)
    monkeypatch.setattr(vortal, "get_es_client", lambda *args, **kwargs: _ES())

    resultado = vortal.indexar_pecas([aviso], destino_base=tmp_path)
    assert resultado["ok"] is True
    assert resultado["indexados"] == 2
    assert capturado["acoes"][0]["_index"] == vortal.VORTAL_PECAS_INDEX
    assert capturado["acoes"][0]["_id"] == f"{UID}::{'b' * 16}"
    assert capturado["acoes"][0]["_source"]["texto"] == "conteudo"


def test_indexar_pecas_sem_elastico_devolve_erro(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vortal, "get_es_client", lambda *args, **kwargs: None)
    resultado = vortal.indexar_pecas([{"uid": UID, "pecas": []}], destino_base=tmp_path)
    assert resultado["ok"] is False and resultado["indexados"] == 0


def test_indexar_em_disco_aviso_inexistente(tmp_path: Path):
    resultado = vortal.indexar_em_disco(uid="PT1.NTC.999", destino_base=tmp_path)
    assert resultado["ok"] is False


# ------------------------------------------------------------------- consulta
def test_estado_junta_disco_e_indice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    resultado = vortal.recolher([URL_PAGINA], destino_base=tmp_path, cliente=_sessao_recolha(), indexar=False)
    assert resultado["avisos"] == 1

    es = _ES(total=2, aggs={"avisos": {"value": 1}, "bytes": {"value": 12}})
    monkeypatch.setattr(vortal, "get_es_client", lambda *args, **kwargs: es)
    estado = vortal.estado(destino_base=tmp_path)
    assert estado["disco"]["avisos"] == 1
    assert estado["disco"]["pecas"] == 2
    assert estado["disco"]["com_texto"] == 1
    assert estado["disco"]["por_tipo"]["caderno_encargos"] == 1
    assert estado["indice"]["documentos"] == 2
    assert estado["indice"]["avisos"] == 1
    assert estado["ultimos"][0]["uid"] == UID


def test_monitorizacao_junta_estado_avisos_e_historico(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    vortal.recolher([URL_PAGINA], destino_base=tmp_path, cliente=_sessao_recolha(), indexar=False)
    vortal.registar_recolha({"avisos": 1, "pecas": 2, "bytes": 10}, autor="admin@iqos.pt", destino_base=tmp_path)
    monkeypatch.setattr(vortal, "get_es_client", lambda *args, **kwargs: _ES(total=2))

    dados = vortal.monitorizacao(limite=5, destino_base=tmp_path)
    assert dados["disco"]["avisos"] == 1
    assert dados["historico"][0]["autor"] == "admin@iqos.pt"
    assert dados["avisos"][0]["uid"] == UID
    assert {peca["ficheiro"] for peca in dados["avisos"][0]["pecas"]} == {"CE.pdf", "PC.pdf"}


def test_meta_descreve_o_modulo():
    dados = vortal.meta()
    assert dados["indice"] == vortal.VORTAL_PECAS_INDEX
    assert "public-tender-documents" in dados["endpoints_api"][0] or "GetPublicTenderInformation" in dados["endpoints_api"][0]
    assert "community.vortal.biz" in dados["hosts_permitidos"]
    assert dados["tipos"]["caderno_encargos"] == "Caderno de encargos"
