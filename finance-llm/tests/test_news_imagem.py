"""Capa do artigo a partir da imagem da própria notícia (`api/news_imagem.py`).

O índice de notícias não guarda imagens: a fotografia está na página original,
anunciada em `og:image`. O que se testa aqui:

* a escolha do URL (prioridade ao `og:image`, alternativa no `twitter:image`,
  caminhos relativos resolvidos contra a página);
* as recusas que evitam uma capa inútil — endereço que não é `http(s)`, página
  que não é imagem, ficheiro minúsculo (pixels de contagem), imagem 1×1 e falhas
  de rede — sempre com um `error` legível e nunca com uma exceção;
* o que sai para o CMS: bytes em base64, tipo e nome de ficheiro.
"""
from __future__ import annotations

import base64
import io
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import news_imagem  # noqa: E402

PAGINA = "https://exemplo.pt/noticia/obra"
IMAGEM = "https://exemplo.pt/img/obra.jpg"


def _imagem(largura: int = 600, altura: int = 315, formato: str = "PNG") -> bytes:
    """Imagem real (ruído, para não comprimir até ao osso) com as dimensões pedidas."""
    from PIL import Image

    ruido = Image.frombytes("RGB", (largura, altura), os.urandom(largura * altura * 3))
    memoria = io.BytesIO()
    ruido.save(memoria, formato)
    return memoria.getvalue()


def _html(**metas: str) -> str:
    linhas = "".join(f'<meta property="{chave.replace("_", ":")}" content="{valor}">' for chave, valor in metas.items())
    return f"<html><head>{linhas}</head><body><img src=\"/img/outra.jpg\"></body></html>"


# ------------------------------------------------------------ escolha do URL
def test_prefere_o_og_image():
    assert news_imagem.url_da_imagem(_html(og_image=IMAGEM), PAGINA) == IMAGEM


def test_usa_o_twitter_image_quando_nao_ha_og_image():
    assert news_imagem.url_da_imagem(_html(twitter_image=IMAGEM), PAGINA) == IMAGEM


def test_resolve_o_caminho_relativo_contra_a_pagina():
    assert news_imagem.url_da_imagem(_html(og_image="/img/obra.jpg"), PAGINA) == "https://exemplo.pt/img/obra.jpg"


def test_sem_metas_nao_ha_imagem():
    assert news_imagem.url_da_imagem("<html><body><img src='/img/x.jpg'></body></html>", PAGINA) == ""


def test_ignora_imagem_que_nao_e_um_endereco():
    assert news_imagem.url_da_imagem(_html(og_image="data:image/png;base64,AAAA"), PAGINA) == ""


# ------------------------------------------------------------- o que se aceita
def test_capa_valida_sai_em_base64_pronta_para_o_cms(monkeypatch):
    blob = _imagem()
    monkeypatch.setattr(news_imagem, "_descarregar", lambda imagem: (blob, "image/png"))
    capa = news_imagem.capa_da_url(IMAGEM)
    assert "error" not in capa, capa.get("error")
    assert base64.b64decode(capa["data"]) == blob
    assert capa["mime"] == "image/png"
    assert capa["filename"].endswith(".png")
    assert capa["origem"] == IMAGEM


def test_sem_tipo_declarado_o_tipo_sai_do_ficheiro(monkeypatch):
    monkeypatch.setattr(news_imagem, "_descarregar", lambda imagem: (_imagem(formato="JPEG"), ""))
    capa = news_imagem.capa_da_url(IMAGEM)
    assert capa["mime"] == "image/jpeg"
    assert capa["filename"].endswith(".jpg")


def test_nome_do_ficheiro_ganha_extensao_quando_o_url_nao_a_tem(monkeypatch):
    monkeypatch.setattr(news_imagem, "_descarregar", lambda imagem: (_imagem(), "image/png"))
    capa = news_imagem.capa_da_url("https://exemplo.pt/imagem?id=42")
    assert capa["filename"].startswith("imagem")
    assert capa["filename"].endswith(".png")


# ------------------------------------------------------------------- recusas
def test_recusa_endereco_que_nao_e_http():
    capa = news_imagem.capa_da_url("ftp://exemplo.pt/obra.jpg")
    assert "http" in capa["error"]


def test_recusa_quando_o_servidor_responde_com_html(monkeypatch):
    monkeypatch.setattr(news_imagem, "_descarregar", lambda imagem: (b"<html>erro</html>" * 400, "text/html"))
    capa = news_imagem.capa_da_url(IMAGEM)
    assert "text/html" in capa["error"]


def test_recusa_imagem_demasiado_pequena(monkeypatch):
    monkeypatch.setattr(news_imagem, "_descarregar", lambda imagem: (_imagem(4, 4), "image/png"))
    capa = news_imagem.capa_da_url(IMAGEM)
    assert "pequena" in capa["error"]


def test_recusa_imagem_com_dimensoes_de_pixel_de_contagem(monkeypatch):
    # Bytes suficientes para passar no tamanho, mas 100×50 não é uma fotografia.
    monkeypatch.setattr(news_imagem, "_descarregar", lambda imagem: (_imagem(100, 50), "image/png"))
    capa = news_imagem.capa_da_url(IMAGEM)
    assert "100×50" in capa["error"]


def test_recusa_o_que_nao_abre_como_imagem(monkeypatch):
    monkeypatch.setattr(news_imagem, "_descarregar", lambda imagem: (os.urandom(9000), "image/jpeg"))
    capa = news_imagem.capa_da_url(IMAGEM)
    assert "imagem" in capa["error"]


def test_falha_de_rede_nao_levanta(monkeypatch):
    def rebentar(imagem: str) -> Any:
        raise ValueError("o servidor respondeu 403")

    monkeypatch.setattr(news_imagem, "_descarregar", rebentar)
    capa = news_imagem.capa_da_url(IMAGEM)
    assert "403" in capa["error"]


# ------------------------------------------------------------- página da notícia
def test_capa_da_noticia_le_a_pagina_e_descarrega_a_imagem(monkeypatch):
    pedidos: List[str] = []
    monkeypatch.setattr(news_imagem, "_fetch_text", lambda url: _html(og_image=IMAGEM))

    def descarregar(imagem: str):
        pedidos.append(imagem)
        return _imagem(), "image/png"

    monkeypatch.setattr(news_imagem, "_descarregar", descarregar)
    capa = news_imagem.capa_da_noticia(PAGINA)
    assert pedidos == [IMAGEM]
    assert base64.b64decode(capa["data"]).startswith(b"\x89PNG")


def test_capa_da_noticia_sem_og_image_explica_porque(monkeypatch):
    monkeypatch.setattr(news_imagem, "_fetch_text", lambda url: "<html><head></head></html>")
    capa = news_imagem.capa_da_noticia(PAGINA)
    assert "og:image" in capa["error"]


def test_capa_da_noticia_sem_ligacao_de_origem():
    capa = news_imagem.capa_da_noticia("")
    assert "ligação de origem" in capa["error"]


def test_capa_da_noticia_com_pagina_bloqueada(monkeypatch):
    def bloqueada(url: str) -> str:
        raise RuntimeError("403")

    monkeypatch.setattr(news_imagem, "_fetch_text", bloqueada)
    capa = news_imagem.capa_da_noticia(PAGINA)
    assert "abrir a notícia" in capa["error"]


def test_todas_as_recusas_trazem_um_error_em_texto() -> None:
    capa: Dict[str, Any] = news_imagem.capa_da_url("   ")
    assert isinstance(capa.get("error"), str) and capa["error"]
