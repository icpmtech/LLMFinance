"""Capa de um artigo publicado a partir de uma notícia — a imagem da própria notícia.

O índice `finance_news` guarda o título, o resumo, a fonte e a ligação, mas **não**
guarda imagens. A fotografia está na página da notícia, anunciada em `og:image`
(é a que as redes sociais mostram quando se partilha a ligação) — é de lá que sai
a capa do artigo.

A imagem é **copiada para o CMS** em vez de se guardar a ligação para o site de
origem: a ligação direta é muitas vezes bloqueada (*hotlink*), muda de caminho
quando a notícia é reorganizada e desaparece quando sai do ar. Guardada, a capa
continua a ser servida pelo site e o `og:image` do artigo não fica pendurado num
endereço de terceiros.

A leitura da página usa a mesma pilha do módulo das redes sociais (`Scrapling`
com impressão digital de Chrome, com `httpx` como alternativa): as fontes de
notícias recusam pedidos que se apresentem como robô.

Nada aqui impede uma publicação: qualquer falha devolve `{"error": "..."}` e o
artigo nasce sem capa, com o aviso à vista no editor.
"""
from __future__ import annotations

import base64
import io
import logging
import re
from html import unescape
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

from api.cms_store import MIME_EXT
from api.social_collectors import _absolutize, _fetch_text, _page_metas

logger = logging.getLogger(__name__)

#: O que se aceita descarregar para capa: uma fotografia de notícia é maior do
#: que isto (o mínimo exclui os pixels de contagem e as imagens de espaço).
MIN_BYTES = 3_000
MAX_BYTES = 8 * 1024 * 1024
MIN_LARGURA = 200
MIN_ALTURA = 100

TIMEOUT = 20.0

#: Metas que anunciam a imagem de partilha, por ordem de preferência.
_CHAVES_DA_IMAGEM = (
    "og:image:secure_url",
    "og:image",
    "og:image:url",
    "twitter:image",
    "twitter:image:src",
)

_NAO_UTILIZAVEIS = re.compile(r"[^\w.\-]+")


def url_da_imagem(html: str, base: str) -> str:
    """URL absoluto da imagem que a página anuncia (`""` quando não anuncia nenhuma).

    O `content` da meta vem escapado no HTML (`&amp;` nas query strings), pelo que
    se descodifica antes de o usar: um `&amp;w=1920` no pedido é um parâmetro
    inválido e a imagem vem no tamanho errado (ou não vem).
    """
    metas = _page_metas(html)
    for chave in _CHAVES_DA_IMAGEM:
        absoluto = _absolutize(unescape(metas.get(chave) or ""), base)
        if absoluto.lower().startswith(("http://", "https://")):
            return absoluto
    return ""


def _nome_do_ficheiro(imagem: str, mime: str) -> str:
    """Nome de ficheiro legível a partir do URL da imagem.

    A extensão vem do **tipo real** do ficheiro, não do caminho: o mesmo URL
    serve `.jpg` ou `.webp` conforme o browser, e um nome que diz `.jpg` num
    ficheiro PNG atrapalha quem o descarrega do CMS.
    """
    nome = _NAO_UTILIZAVEIS.sub("-", Path(urlparse(imagem).path).name).strip("-.") or "capa"
    extensao = MIME_EXT.get(mime) or ""
    if extensao:
        return f"{Path(nome).stem[:84]}{extensao}"[:90]
    return nome[:90] if Path(nome).suffix else f"{nome}.jpg"[:90]


def _descarregar(imagem: str) -> tuple:
    """Bytes da imagem e o tipo que o servidor declarou (levanta se não servir)."""
    import httpx

    resposta = httpx.get(
        imagem,
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; IQOS/1.0)", "Accept": "image/*,*/*"},
    )
    if resposta.status_code != 200:
        raise ValueError(f"o servidor respondeu {resposta.status_code}")
    mime = str(resposta.headers.get("content-type") or "").split(";")[0].strip().lower()
    return resposta.content, mime


def _mime_dos_bytes(blob: bytes) -> str:
    """Tipo da imagem lido do próprio ficheiro (para servidores que não o declaram)."""
    try:
        from PIL import Image

        formato = str(Image.open(io.BytesIO(blob)).format or "").upper()
    except Exception:  # noqa: BLE001 - ficheiro ilegível (já recusado antes)
        return ""
    return {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "GIF": "image/gif",
        "WEBP": "image/webp",
        "AVIF": "image/avif",
    }.get(formato, "")


def _motivo_de_recusa(blob: bytes, mime: str) -> str:
    """Porque é que estes bytes não servem de capa (`""` quando servem)."""
    if not blob:
        return "a imagem veio vazia"
    if mime and not mime.startswith("image/"):
        return f"o servidor devolveu «{mime}» em vez de uma imagem"
    if len(blob) < MIN_BYTES:
        return f"a imagem é demasiado pequena ({len(blob)} bytes)"
    if len(blob) > MAX_BYTES:
        return f"a imagem é demasiado grande ({len(blob)} bytes, máximo {MAX_BYTES // (1024 * 1024)} MB)"
    try:
        from PIL import Image

        largura, altura = Image.open(io.BytesIO(blob)).size
    except Exception:  # noqa: BLE001 - formato exótico ou ficheiro corrompido
        return "o ficheiro não é uma imagem que se possa abrir"
    if largura < MIN_LARGURA or altura < MIN_ALTURA:
        return f"a imagem é {largura}×{altura} (mínimo {MIN_LARGURA}×{MIN_ALTURA})"
    return ""


def capa_da_url(imagem: str) -> Dict[str, Any]:
    """Descarrega a imagem e devolve o que é preciso para a guardar no CMS.

    Sucesso: `data` (base64), `mime`, `filename` e `origem` (o URL de onde veio —
    fica como crédito da fotografia). Falha: `error`, sempre em texto que se possa
    mostrar ao editor.
    """
    imagem = (imagem or "").strip()
    if not imagem.lower().startswith(("http://", "https://")):
        return {"error": "a imagem não é um endereço http(s)"}
    try:
        blob, mime = _descarregar(imagem)
    except Exception as exc:  # noqa: BLE001 - rede, TLS, 403, redireccionamentos
        logger.info("Capa: falhou descarregar %s (%s).", imagem, exc)
        return {"error": f"não foi possível descarregar a imagem: {exc}"}
    motivo = _motivo_de_recusa(blob, mime)
    if motivo:
        logger.info("Capa: %s recusada (%s).", imagem, motivo)
        return {"error": motivo}
    mime = mime or _mime_dos_bytes(blob) or "image/jpeg"
    return {
        "data": base64.b64encode(blob).decode("ascii"),
        "mime": mime,
        "filename": _nome_do_ficheiro(imagem, mime),
        "origem": imagem,
    }


def capa_da_noticia(pagina: str) -> Dict[str, Any]:
    """A imagem com que a notícia se anuncia na **sua própria página**."""
    pagina = (pagina or "").strip()
    if not pagina.lower().startswith(("http://", "https://")):
        return {"error": "a notícia não tem ligação de origem para procurar a imagem"}
    try:
        html = _fetch_text(pagina)
    except Exception as exc:  # noqa: BLE001 - bloqueio, DNS, tempo esgotado
        logger.info("Capa: falhou abrir %s (%s).", pagina, exc)
        return {"error": f"não foi possível abrir a notícia: {exc}"}
    imagem = url_da_imagem(html, pagina)
    if not imagem:
        return {"error": "a notícia não anuncia nenhuma imagem de partilha (`og:image`)"}
    return capa_da_url(imagem)
