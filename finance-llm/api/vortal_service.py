"""Peças do procedimento do Portal Vortal — descarga para disco e indexação.

O Portal Vortal (plataforma de contratação eletrónica) publica, para cada
procedimento, uma **página pública de peças do procedimento**:

    https://community.vortal.biz/Public/public-tender-documents/<token>

A página é uma SPA: o conteúdo chega por API. Esta sonda ao bundle
(`public/main/static/index-*.js`) deu os dois passos que interessam, ambos
**públicos** (sem sessão nem cookie):

1. `GET {base}/public/api/PublicTenderDocuments/GetPublicTenderInformation?uniqueIdentifierEncrypted=<token>&languageCode=<idioma>`
   → devolve `contractNoticeUrl` (com o **UID do aviso**, ex.: `PT1.NTC.3612674`)
   e uma `documentList` (vazia na maioria dos avisos).
2. `GET {base}/public/api/ContractNoticeDetail/GetContractNoticeDocuments?contractNoticeUId=<uid>`
   → lista das peças: `{id, fileId, name, description, downloadUrl}`. O
   `downloadUrl` é um URL público com token
   (`{base}/archive/api/PublicDownload/download?token=…`) que devolve o ficheiro
   com `Content-Disposition` (PDF, XLSX, DOCX, XML, ZIP…).

Este módulo:
- resolve `token → UID → lista de peças`;
- **descarrega para disco** em `data/vortal/<uid>/` (com manifesto `_manifesto.json`
  e o texto extraído em `_texto/` — o disco é a fonte de verdade);
- extrai o texto (PDF com `pymupdf`, DOCX com `zipfile`+`xml`, XLSX com
  `openpyxl`, XML/CSV/TXT como texto, ZIP por dentro);
- **indexa no Elasticsearch** (`finance_vortal_pecas`, um documento por peça,
  com o texto pesquisável), de forma idempotente (o `_id` inclui o `sha256`).

Notas de segurança e de limites:
- só se descarrega de anfitriões do domínio `vortal.biz` (guarda contra SSRF,
  como em `api/contract_document.py`);
- cada peça tem limite de tamanho (`MAX_BYTES`) e o texto guardado é truncado
  (`MAX_TEXTO`);
- uma peça que falhe **não** aborta a recolha: fica registada com o erro.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import time
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlparse

import requests
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from api.contract_document import _docx_text, _pdf_text, _read_archive
from api.elasticsearch_client import VORTAL_PECAS_INDEX, ensure_indices, get_es_client

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]

#: Base do portal. O caminho das APIs públicas vive em `<base>/public/api/...`.
BASE = (os.environ.get("VORTAL_BASE_URL") or "https://community.vortal.biz").rstrip("/")
PUBLICO = f"{BASE}/public"

#: Raiz em disco das peças (configurável por `VORTAL_DIR`).
DESTINO_DIR = Path(os.environ.get("VORTAL_DIR") or (ROOT / "data" / "vortal"))

#: Anfitriões de onde é aceitável descarregar (a lista de peças vem de uma
#: resposta que já é nossa, mas a guarda evita que um URL estranho seja seguido).
HOSTS_PERMITIDOS = {
    "community.vortal.biz",
    "www.vortal.biz",
    "vortal.biz",
    "www.community.vortal.biz",
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

TIMEOUT = 90.0
#: Limite por peça (as peças grandes são ZIP com projetos; 200 MB é folgado).
MAX_BYTES = 200 * 1024 * 1024
#: Caracteres de texto guardados por peça (no disco e no índice).
MAX_TEXTO = 200_000
#: Extensões cujo conteúdo é texto direto.
EXTENSOES_TEXTO = {".txt", ".csv", ".json", ".xml", ".html", ".htm", ".md", ".tsv", ".jsonl"}

#: Tipos de peça reconhecidos pelo nome (heurística declarada, nada de magia).
TIPOS: List[Tuple[str, str]] = [
    (r"caderno\s*de\s*encargos|\bce\b|_ce_|ce[_\s-]", "caderno_encargos"),
    (r"programa\s*(de|do)\s*concurso|\bpc\b|_pc_|pc[_\s-]", "programa_concurso"),
    (r"mapa\s*de\s*quantidades|mq\b|anexo\s*ii", "mapa_quantidades"),
    (r"modelo\s*de\s*resposta|anexo\s*i\b", "modelo_resposta"),
    (r"esclarecimento|perguntas?\s*e\s*respostas|resposta\s*a\s*esclarecimentos", "esclarecimentos"),
    (r"retific", "retificacao"),
    (r"prorroga|altera[çc][ãa]o\s*de\s*prazo", "prorrogacao"),
    (r"espd|documento\s*europeu\s*[úu]nico", "espd"),
    (r"convite", "convite"),
    (r"proposta|or[çc]amento", "proposta"),
    (r"anexo", "anexo"),
    (r"relat[óo]rio|auto|ata", "relatorio"),
]

TIPOS_LABEL = {
    "caderno_encargos": "Caderno de encargos",
    "programa_concurso": "Programa do concurso",
    "mapa_quantidades": "Mapa de quantidades",
    "modelo_resposta": "Modelo de resposta",
    "esclarecimentos": "Esclarecimentos",
    "retificacao": "Retificação",
    "prorrogacao": "Prorrogação",
    "espd": "ESPD (documento único de contratação)",
    "convite": "Convite",
    "proposta": "Proposta / orçamento",
    "anexo": "Anexo",
    "relatorio": "Relatório / auto",
    "outro": "Outro documento",
}


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nome_sem_extensao(nome: str) -> str:
    return nome.rsplit(".", 1)[0] if "." in nome else nome


# ---------------------------------------------------------------------------
# Identificação do aviso (token → UID)
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-=+/]{24,}")
_UID_RE = re.compile(r"contract-notice-view/([^/?#]+)", flags=re.I)
_UID_DIRETO_RE = re.compile(r"^[A-Z]{2,}[0-9A-Z]*\.[A-Z]+\.\d+$")


def token_de_url(valor: str) -> Optional[str]:
    """Extrai o token público de um URL da Vortal (ou aceita o token em cru).

    Aceita:
    - `https://community.vortal.biz/Public/public-tender-documents/<token>`
    - `.../public-tender-documents/<token>?currentLanguage=en`
    - o próprio `<token>`.
    """
    texto = str(valor or "").strip()
    if not texto:
        return None
    if "public-tender-documents" in texto:
        cauda = texto.split("public-tender-documents", 1)[1]
        cauda = cauda.lstrip("/").split("?", 1)[0].split("#", 1)[0].strip("/")
        return cauda or None
    if texto.startswith(("http://", "https://")):
        return None
    achado = _TOKEN_RE.search(texto)
    return achado.group(0) if achado else None


def uid_de_url(valor: str) -> Optional[str]:
    """UID do aviso a partir de um URL `contract-notice-view/<uid>` (ou em cru)."""
    texto = str(valor or "").strip()
    achado = _UID_RE.search(texto)
    if achado:
        return achado.group(1)
    if _UID_DIRETO_RE.match(texto):
        return texto
    return None


# ---------------------------------------------------------------------------
# Cliente HTTP
# ---------------------------------------------------------------------------
def _cabecalhos(referer: Optional[str] = None) -> Dict[str, str]:
    cabecalhos = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
    }
    if referer:
        cabecalhos["Referer"] = referer
    return cabecalhos


def _cliente(cliente: Optional[requests.Session] = None) -> requests.Session:
    return cliente if cliente is not None else requests.Session()


def _host_permitido(url: str) -> bool:
    anfitriao = (urlparse(url).hostname or "").lower()
    return anfitriao in HOSTS_PERMITIDOS or anfitriao.endswith(".vortal.biz")


def informacao_aviso(token: str, *, idioma: str = "pt-PT", cliente: Optional[requests.Session] = None) -> Dict[str, Any]:
    """`GetPublicTenderInformation` — UID do aviso, URL público e lista de peças."""
    sessao = _cliente(cliente)
    resposta = sessao.get(
        f"{PUBLICO}/api/PublicTenderDocuments/GetPublicTenderInformation",
        params={"uniqueIdentifierEncrypted": token, "languageCode": idioma},
        headers=_cabecalhos(),
        timeout=TIMEOUT,
    )
    resposta.raise_for_status()
    dados = resposta.json() or {}
    url_aviso = str(dados.get("contractNoticeUrl") or "")
    return {
        "token": token,
        "idioma": idioma,
        "uid": uid_de_url(url_aviso),
        "url_aviso": url_aviso or None,
        "publicado": bool((dados.get("tenderInformation") or {}).get("tenderIsPublished")),
        "documentos_iniciais": dados.get("documentList") or [],
        "bruto": dados,
    }


def documentos_do_aviso(uid: str, *, cliente: Optional[requests.Session] = None) -> List[Dict[str, Any]]:
    """`GetContractNoticeDocuments` — lista normalizada das peças do aviso."""
    sessao = _cliente(cliente)
    resposta = sessao.get(
        f"{PUBLICO}/api/ContractNoticeDetail/GetContractNoticeDocuments",
        params={"contractNoticeUId": uid},
        headers=_cabecalhos(referer=f"{BASE}/Public/contract-notice-view/{uid}/"),
        timeout=TIMEOUT,
    )
    resposta.raise_for_status()
    bruto = resposta.json() or []
    if isinstance(bruto, dict):  # algumas respostas vêm embrulhadas
        bruto = bruto.get("documents") or bruto.get("documentList") or []
    pecas: List[Dict[str, Any]] = []
    for item in bruto:
        if not isinstance(item, dict):
            continue
        nome = str(item.get("name") or item.get("fileName") or "").strip()
        url = str(item.get("downloadUrl") or item.get("url") or "").strip()
        if not nome and not url:
            continue
        pecas.append(
            {
                "uid": uid,
                "doc_id": item.get("id"),
                "file_id": item.get("fileId"),
                "nome": nome or f"peca-{item.get('id')}",
                "descricao": item.get("description"),
                "url": url,
                "extensao": Path(nome).suffix.lower() if nome else "",
                "tipo": tipo_da_peca(nome),
            }
        )
    return pecas


# ---------------------------------------------------------------------------
# Nomes e classificação
# ---------------------------------------------------------------------------
def tipo_da_peca(nome: str) -> str:
    """Tipo da peça a partir do nome (heurística declarada em `TIPOS`)."""
    alvo = _sem_acentos(_nome_sem_extensao(nome or "")).lower()
    for padrao, tipo in TIPOS:
        if re.search(padrao, alvo):
            return tipo
    return "outro"


def _sem_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto or "")
    return "".join(ch for ch in decomposto if not unicodedata.combining(ch))


def nome_ficheiro_seguro(nome: str, *, limite: int = 120) -> str:
    """Nome de ficheiro utilizável em disco (sem caminhos, controlos nem lixo).

    Preserva acentos e o que é legível; corta o excesso mantendo a extensão.
    """
    texto = unquote(str(nome or "")).replace("\x00", "")
    texto = texto.replace("\\", "/").split("/")[-1].strip()
    texto = re.sub(r"[\x00-\x1f\x7f]", "", texto)
    texto = re.sub(r'[<>:"|?*]', "_", texto)
    texto = re.sub(r"\s+", " ", texto).strip(" .")
    if texto in ("", ".", ".."):
        texto = "peca"
    if len(texto) > limite:
        sufixo = Path(texto).suffix
        base = texto[: max(1, limite - len(sufixo) - 1)]
        texto = f"{base}{sufixo}" if sufixo else base
    return texto


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------
def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def descarregar_bytes(
    url: str,
    *,
    cliente: Optional[requests.Session] = None,
    timeout: float = TIMEOUT,
    maximo: int = MAX_BYTES,
) -> Tuple[bytes, Dict[str, Any]]:
    """Bytes de uma peça, sem tocar no disco (usado pela ficha do contrato).

    Levanta exceção quando o anfitrião não é autorizado ou o ficheiro excede o
    limite — quem chama decide se quer um erro no registo ou uma exceção.
    """
    if not _host_permitido(url):
        raise ValueError(f"anfitrião não autorizado: {urlparse(url).hostname}")
    sessao = _cliente(cliente)
    resposta = sessao.get(
        url,
        headers=_cabecalhos(referer=f"{BASE}/Public/public-tender-documents"),
        timeout=timeout,
        stream=True,
    )
    resposta.raise_for_status()
    pedacos: List[bytes] = []
    total = 0
    for pedaco in resposta.iter_content(65536):
        if not pedaco:
            continue
        total += len(pedaco)
        if total > maximo:
            raise ValueError(f"peça maior que o limite ({maximo} bytes)")
        pedacos.append(pedaco)
    blob = b"".join(pedacos)
    meta = {
        "url": url,
        "bytes": len(blob),
        "content_type": resposta.headers.get("content-type"),
        "nome": _nome_do_content_disposition(resposta.headers.get("content-disposition")),
    }
    return blob, meta


def descarregar_peca(
    peca: Dict[str, Any],
    destino_dir: Path,
    *,
    cliente: Optional[requests.Session] = None,
    forcar: bool = False,
    timeout: float = TIMEOUT,
) -> Dict[str, Any]:
    """Descarrega uma peça para `destino_dir` e devolve o registo da peça.

    Idempotente: se o ficheiro já existir com o **mesmo `sha256`**, não se volta
    a descarregar (a não ser com `forcar=True`).
    """
    url = str(peca.get("url") or "")
    nome = nome_ficheiro_seguro(str(peca.get("nome") or Path(url).name or "peca"))
    caminho = destino_dir / nome
    registo: Dict[str, Any] = {
        "uid": peca.get("uid"),
        "doc_id": peca.get("doc_id"),
        "file_id": peca.get("file_id"),
        "nome": peca.get("nome") or nome,
        "ficheiro": nome,
        "descricao": peca.get("descricao"),
        "url": url,
        "extensao": Path(nome).suffix.lower(),
        "tipo": peca.get("tipo") or tipo_da_peca(nome),
        "bytes": 0,
        "sha256": None,
        "descarregado_em": _agora(),
        "reutilizado": False,
        "erro": None,
    }

    if not url:
        registo["erro"] = "sem URL de descarga"
        return registo
    if not _host_permitido(url):
        registo["erro"] = f"anfitrião não autorizado: {urlparse(url).hostname}"
        logger.warning("Vortal: peça ignorada (%s)", registo["erro"])
        return registo

    if caminho.is_file() and not forcar:
        registo["bytes"] = caminho.stat().st_size
        registo["sha256"] = _sha256(caminho.read_bytes())
        registo["reutilizado"] = True
        return registo

    sessao = _cliente(cliente)
    try:
        blob, meta_descarga = descarregar_bytes(url, cliente=sessao, timeout=timeout)
        nome_resposta = meta_descarga.get("nome")
        if nome_resposta:
            seguro = nome_ficheiro_seguro(str(nome_resposta))
            if seguro.lower().endswith(Path(nome).suffix.lower()) and seguro != nome:
                nome = seguro
                caminho = destino_dir / nome
                registo["ficheiro"] = nome
                registo["extensao"] = Path(nome).suffix.lower()
    except Exception as erro:  # noqa: BLE001
        registo["erro"] = f"{type(erro).__name__}: {erro}"
        logger.warning("Vortal: falhou a descarga de %s (%s)", nome, erro)
        return registo

    destino_dir.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(blob)
    registo["bytes"] = len(blob)
    registo["sha256"] = _sha256(blob)
    registo["content_type"] = meta_descarga.get("content_type")
    return registo


def _nome_do_content_disposition(cabecalho: Optional[str]) -> Optional[str]:
    """Nome do ficheiro no `Content-Disposition` (prefere a forma `filename*`)."""
    if not cabecalho:
        return None
    estrela = re.search(r"filename\*\s*=\s*UTF-8''([^;]+)", cabecalho, flags=re.I)
    if estrela:
        return unquote(estrela.group(1).strip().strip('"'))
    simples = re.search(r'filename\s*=\s*"([^"]+)"', cabecalho, flags=re.I) or re.search(r"filename\s*=\s*([^;]+)", cabecalho, flags=re.I)
    if simples:
        return simples.group(1).strip().strip('"')
    return None


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------
def extrair_texto(caminho: Path, *, limite: int = MAX_TEXTO) -> Dict[str, Any]:
    """Texto de uma peça em disco (PDF, DOCX, XLSX, XML/CSV/TXT, ZIP) e como foi obtido."""
    try:
        blob = caminho.read_bytes()
    except Exception as erro:  # noqa: BLE001
        return {
            "texto": "",
            "meta": {"ficheiro": caminho.name, "extensao": caminho.suffix.lower(), "metodo": None, "chars": 0, "erro": f"{type(erro).__name__}: {erro}"},
        }
    return extrair_texto_de_bytes(blob, caminho.name, limite=limite)


def extrair_texto_de_bytes(blob: bytes, nome: str, *, limite: int = MAX_TEXTO) -> Dict[str, Any]:
    """Texto de uma peça a partir dos bytes (mesma leitura usada no disco e em memória)."""
    meta: Dict[str, Any] = {"ficheiro": nome, "extensao": Path(nome).suffix.lower(), "metodo": None, "chars": 0, "erro": None}
    extensao = meta["extensao"]
    try:
        if blob[:2] == b"PK" and extensao in (".zip", ".docx", ".xlsx", ".pptx", ".odt", ".ods"):
            if extensao == ".zip":
                partes = _read_archive(blob)
                meta["metodo"] = "zip"
                meta["partes"] = [{"nome": parte["name"], "chars": len(parte["text"])} for parte in partes]
                texto = "\n\n".join(f"### {parte['name']}\n{parte['text']}" for parte in partes)
            elif extensao == ".docx":
                texto = _docx_text(blob)
                meta["metodo"] = "docx"
            elif extensao == ".xlsx":
                texto = _xlsx_text(blob)
                meta["metodo"] = "xlsx"
            else:
                texto = _xml_texto(blob)
                meta["metodo"] = "zip-generico"
        elif blob[:4] == b"%PDF" or extensao == ".pdf":
            texto, paginas = _pdf_texto_e_paginas(blob)
            meta["metodo"] = "pdf"
            meta["paginas"] = paginas
        elif extensao in EXTENSOES_TEXTO or not extensao:
            texto = _xml_texto(blob) if extensao in (".xml", ".html", ".htm") else blob.decode("utf-8", errors="replace")
            meta["metodo"] = "texto"
        else:
            texto = ""
            meta["metodo"] = "binario"
    except Exception as erro:  # noqa: BLE001
        meta["erro"] = f"{type(erro).__name__}: {erro}"
        logger.debug("Vortal: não foi possível extrair texto de %s (%s)", nome, erro)
        return {"texto": "", "meta": meta}

    texto = re.sub(r"[ \t\u00a0]+", " ", texto or "").strip()
    if len(texto) > limite:
        texto = texto[:limite]
        meta["truncado"] = True
    if meta["metodo"] == "pdf" and not texto:
        # PDF digitalizado (imagem sem camada de texto): a plataforma não faz OCR,
        # por isso o facto fica declarado em vez de parecer «documento vazio».
        meta["metodo"] = "pdf-sem-texto"
        meta["precisa_ocr"] = True
    meta["chars"] = len(texto)
    return {"texto": texto, "meta": meta}


def _pdf_texto_e_paginas(blob: bytes) -> Tuple[str, int]:
    """Texto e nº de páginas de um PDF (`pymupdf`)."""
    import fitz  # pymupdf

    documento = fitz.open(stream=blob, filetype="pdf")
    try:
        paginas = documento.page_count
        return "\n".join(pagina.get_text() for pagina in documento), paginas
    finally:
        documento.close()


def _xml_texto(blob: bytes) -> str:
    """Texto de um XML/HTML (valores dos nós, sem etiquetas)."""
    try:
        from lxml import etree

        raiz = etree.fromstring(blob, parser=etree.XMLParser(recover=True))
        if raiz is None:
            raise ValueError("XML ilegível")
        linhas = [texto.strip() for texto in raiz.itertext() if texto and texto.strip()]
        return "\n".join(linhas)
    except Exception:
        return blob.decode("utf-8", errors="replace")


def _xlsx_text(blob: bytes) -> str:
    """Texto de um XLSX: uma linha por linha da folha, células separadas por ` | `."""
    try:
        from openpyxl import load_workbook
    except Exception:  # pragma: no cover - openpyxl faz parte dos requisitos
        return _xml_texto(blob)
    livro = load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    linhas: List[str] = []
    try:
        for folha in livro.worksheets:
            linhas.append(f"### {folha.title}")
            for linha in folha.iter_rows(values_only=True):
                celulas = [str(celula).strip() for celula in linha if celula is not None and str(celula).strip()]
                if celulas:
                    linhas.append(" | ".join(celulas))
    finally:
        livro.close()
    return "\n".join(linhas)


def guardar_texto(texto: str, destino_dir: Path, ficheiro: str) -> Optional[str]:
    """Grava o texto extraído em `_texto/<ficheiro>.txt` (o disco é a fonte de verdade).

    Devolve o caminho relativo **em barras normais** (`/_texto/…`): o manifesto
    pode ser lido noutra máquina (o backend de produção corre em Linux).
    """
    if not texto:
        return None
    pasta = destino_dir / "_texto"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{ficheiro}.txt"
    caminho.write_text(texto, encoding="utf-8")
    return caminho.relative_to(destino_dir).as_posix()


def ler_texto(destino_dir: Path, ficheiro: str, *, limite: int = MAX_TEXTO) -> str:
    """Lê o texto guardado em disco (usado pela indexação)."""
    caminho = destino_dir / "_texto" / f"{ficheiro}.txt"
    if not caminho.is_file():
        return ""
    try:
        return caminho.read_text(encoding="utf-8")[:limite]
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Manifesto em disco
# ---------------------------------------------------------------------------
MANIFESTO = "_manifesto.json"
#: Histórico das recolhas/indexações (para a monitorização de administração).
REGISTOS = "_recolhas.json"
#: Quantas entradas do histórico se mantêm em disco.
MAX_REGISTOS = 200


def _registos_path(destino_base: Optional[Path] = None) -> Path:
    return Path(destino_base or DESTINO_DIR) / REGISTOS


def registar_recolha(resultado: Dict[str, Any], *, autor: Optional[str] = None, tipo: str = "recolha", urls: Optional[Sequence[str]] = None, destino_base: Optional[Path] = None) -> Dict[str, Any]:
    """Acrescenta uma entrada ao histórico (`_recolhas.json`) e devolve-a.

    O histórico é o que permite **monitorizar** o módulo: quando correu, o que
    foi pedido, quantas peças vieram, quantos bytes, que erros e se indexou.
    É mantido em disco (últimas `MAX_REGISTOS` entradas).
    """
    caminho = _registos_path(destino_base)
    registos: List[Dict[str, Any]] = []
    if caminho.is_file():
        try:
            registos = json.loads(caminho.read_text(encoding="utf-8")) or []
        except Exception as erro:  # noqa: BLE001
            logger.warning("Vortal: histórico ilegível (%s); recomeça-se", erro)
            registos = []
    entrada = {
        "em": _agora(),
        "tipo": tipo,
        "autor": autor,
        "urls": [str(url) for url in (urls or [])][:20],
        "avisos": int(resultado.get("avisos") or 0),
        "pecas": int(resultado.get("pecas") or resultado.get("indexados") or 0),
        "bytes": int(resultado.get("bytes") or 0),
        "erros": [str(erro)[:200] for erro in (resultado.get("erros") or [])[:5]],
        "indexados": int((resultado.get("indice") or {}).get("indexados") or 0),
        "destino": str(resultado.get("destino") or destino_base or DESTINO_DIR),
        "duracao_s": resultado.get("duracao_s"),
    }
    registos.append(entrada)
    registos = registos[-MAX_REGISTOS:]
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(json.dumps(registos, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    except Exception as erro:  # noqa: BLE001
        logger.warning("Vortal: não foi possível gravar o histórico (%s)", erro)
    return entrada


def historico_recolhas(*, limite: int = 20, destino_base: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Últimas recolhas/indexações, da mais recente para a mais antiga."""
    caminho = _registos_path(destino_base)
    if not caminho.is_file():
        return []
    try:
        registos = json.loads(caminho.read_text(encoding="utf-8")) or []
    except Exception:  # noqa: BLE001
        return []
    registos = list(registos)[::-1]
    return registos[: max(1, int(limite))]


def pasta_do_aviso(uid: str, *, destino_base: Optional[Path] = None) -> Path:
    raiz = Path(destino_base or DESTINO_DIR)
    return raiz / nome_ficheiro_seguro(uid, limite=80)


def ler_manifesto(uid: str, *, destino_base: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    caminho = pasta_do_aviso(uid, destino_base=destino_base) / MANIFESTO
    if not caminho.is_file():
        return None
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception as erro:  # noqa: BLE001
        logger.warning("Vortal: manifesto ilegível em %s (%s)", caminho, erro)
        return None


def guardar_manifesto(uid: str, manifesto: Dict[str, Any], *, destino_base: Optional[Path] = None) -> Path:
    pasta = pasta_do_aviso(uid, destino_base=destino_base)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / MANIFESTO
    caminho.write_text(json.dumps(manifesto, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return caminho


def listar_avisos_em_disco(*, destino_base: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Avisos já em disco (lendo os manifestos), do mais recente para o mais antigo."""
    raiz = Path(destino_base or DESTINO_DIR)
    if not raiz.is_dir():
        return []
    avisos: List[Dict[str, Any]] = []
    for pasta in sorted(raiz.iterdir()):
        if not pasta.is_dir():
            continue
        manifesto = ler_manifesto(pasta.name, destino_base=raiz)
        if manifesto:
            avisos.append(manifesto)
    avisos.sort(key=lambda item: str(item.get("recolhido_em") or ""), reverse=True)
    return avisos


# ---------------------------------------------------------------------------
# Recolha (token/UID → disco → índice)
# ---------------------------------------------------------------------------
def recolher(
    urls: Sequence[str],
    *,
    destino_base: Optional[Path] = None,
    indexar: bool = False,
    extrair: bool = True,
    forcar: bool = False,
    idioma: str = "pt-PT",
    cliente: Optional[requests.Session] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Recolhe as peças de um ou mais avisos: resolve, descarrega, extrai e (se pedido) indexa.

    Aceita URLs da página pública, URLs `contract-notice-view` ou UIDs em cru.
    """
    inicio = time.time()
    raiz = Path(destino_base or DESTINO_DIR)
    sessao = _cliente(cliente)
    avisos: List[Dict[str, Any]] = []
    total_pecas = 0
    total_bytes = 0
    erros: List[str] = []

    for valor in urls:
        token = token_de_url(valor)
        uid = uid_de_url(valor) or (None if token else None)
        informacao: Dict[str, Any] = {"token": token, "idioma": idioma}
        try:
            if token:
                informacao = informacao_aviso(token, idioma=idioma, cliente=sessao)
                uid = informacao.get("uid") or uid
            if not uid:
                erros.append(f"{valor}: não foi possível determinar o UID do aviso")
                continue
            pecas = documentos_do_aviso(str(uid), cliente=sessao)
        except Exception as erro:  # noqa: BLE001
            erros.append(f"{valor}: {type(erro).__name__}: {erro}")
            logger.warning("Vortal: falhou a leitura do aviso %s (%s)", valor, erro)
            continue

        pasta = pasta_do_aviso(str(uid), destino_base=raiz)
        pasta.mkdir(parents=True, exist_ok=True)
        registos: List[Dict[str, Any]] = []
        for peca in pecas:
            registo = descarregar_peca(peca, pasta, cliente=sessao, forcar=forcar)
            if extrair and not registo.get("erro"):
                extraido = extrair_texto(pasta / registo["ficheiro"])
                registo["texto_chars"] = extraido["meta"].get("chars", 0)
                registo["texto_metodo"] = extraido["meta"].get("metodo")
                registo["paginas"] = extraido["meta"].get("paginas")
                if extraido["meta"].get("precisa_ocr"):
                    registo["precisa_ocr"] = True
                registo["texto_ficheiro"] = guardar_texto(extraido["texto"], pasta, registo["ficheiro"])
                if extraido["meta"].get("erro"):
                    registo["texto_erro"] = extraido["meta"]["erro"]
                if extraido["meta"].get("partes"):
                    registo["texto_partes"] = extraido["meta"]["partes"]
            registos.append(registo)
            total_pecas += 1
            total_bytes += int(registo.get("bytes") or 0)
            if registo.get("erro"):
                erros.append(f"{uid}/{registo['ficheiro']}: {registo['erro']}")

        manifesto = {
            "uid": str(uid),
            "token": token,
            "url_aviso": informacao.get("url_aviso"),
            "publicado": informacao.get("publicado"),
            "idioma": idioma,
            "recolhido_em": _agora(),
            "pasta": str(pasta),
            "pecas": registos,
            "totais": {
                "pecas": len(registos),
                "bytes": sum(int(registo.get("bytes") or 0) for registo in registos),
                "com_texto": len([registo for registo in registos if registo.get("texto_chars")]),
                "erros": len([registo for registo in registos if registo.get("erro")]),
            },
        }
        guardar_manifesto(str(uid), manifesto, destino_base=raiz)
        avisos.append(manifesto)

    resultado: Dict[str, Any] = {
        "avisos": len(avisos),
        "pecas": total_pecas,
        "bytes": total_bytes,
        "erros": erros,
        "detalhe": avisos,
        "destino": str(raiz),
        "duracao_s": round(time.time() - inicio, 2),
    }
    if indexar and avisos:
        resultado["indice"] = indexar_pecas(avisos, destino_base=raiz, es=es)
    return resultado


# ---------------------------------------------------------------------------
# Índice Elasticsearch
# ---------------------------------------------------------------------------
def documento_para_indice(peca: Dict[str, Any], aviso: Dict[str, Any], *, destino_base: Optional[Path] = None) -> Tuple[str, Dict[str, Any]]:
    """Documento do índice (`_id`, corpo) de uma peça do manifesto."""
    uid = str(aviso.get("uid") or peca.get("uid") or "")
    chave = str(peca.get("sha256") or peca.get("ficheiro") or "")
    identificador = f"{uid}::{chave[:16] or peca.get('ficheiro')}"
    corpo = {
        "uid": uid,
        "token": aviso.get("token"),
        "url_aviso": aviso.get("url_aviso"),
        "publicado": aviso.get("publicado"),
        "nome": peca.get("nome"),
        "ficheiro": peca.get("ficheiro"),
        "descricao": peca.get("descricao"),
        "extensao": peca.get("extensao"),
        "tipo": peca.get("tipo"),
        "tipo_label": TIPOS_LABEL.get(str(peca.get("tipo")), peca.get("tipo")),
        "doc_id": peca.get("doc_id"),
        "file_id": peca.get("file_id"),
        "url": peca.get("url"),
        "bytes": int(peca.get("bytes") or 0),
        "sha256": peca.get("sha256"),
        "pasta": aviso.get("pasta"),
        "recolhido_em": aviso.get("recolhido_em"),
        "descarregado_em": peca.get("descarregado_em"),
        "texto_chars": int(peca.get("texto_chars") or 0),
        "texto_metodo": peca.get("texto_metodo"),
        "texto_partes": peca.get("texto_partes"),
        "paginas": peca.get("paginas"),
        "precisa_ocr": bool(peca.get("precisa_ocr")),
        "erro": peca.get("erro"),
        "indexado_em": _agora(),
    }
    corpo["texto"] = ler_texto(Path(aviso.get("pasta") or ""), str(peca.get("ficheiro") or "")) if aviso.get("pasta") else ""
    if not corpo["texto"] and destino_base is not None:
        corpo["texto"] = ler_texto(pasta_do_aviso(uid, destino_base=destino_base), str(peca.get("ficheiro") or ""))
    return identificador, {chave_: valor for chave_, valor in corpo.items() if valor is not None}


def indexar_pecas(
    avisos: Optional[Iterable[Dict[str, Any]]] = None,
    *,
    destino_base: Optional[Path] = None,
    es: Optional[Elasticsearch] = None,
    recriar: bool = False,
) -> Dict[str, Any]:
    """Indexa no Elasticsearch as peças dos manifestos indicados (ou todas as de disco).

    Idempotente: o `_id` é `uid::sha256[0:16]`, por isso reindexar substitui a
    mesma peça em vez de a duplicar.
    """
    cliente = es or get_es_client()
    if cliente is None:
        return {"ok": False, "erro": "Elasticsearch indisponível", "indexados": 0}

    raiz = Path(destino_base or DESTINO_DIR)
    lista = list(avisos) if avisos is not None else listar_avisos_em_disco(destino_base=raiz)
    if recriar and cliente.indices.exists(index=VORTAL_PECAS_INDEX):
        cliente.indices.delete(index=VORTAL_PECAS_INDEX)
    ensure_indices(cliente)

    acoes: List[Dict[str, Any]] = []
    for aviso in lista:
        if not aviso.get("pecas"):
            manifesto = ler_manifesto(str(aviso.get("uid")), destino_base=raiz) if aviso.get("uid") else None
            aviso = manifesto or aviso
        for peca in aviso.get("pecas") or []:
            if not peca.get("sha256") and not peca.get("ficheiro"):
                continue
            identificador, corpo = documento_para_indice(peca, aviso, destino_base=raiz)
            acoes.append({"_index": VORTAL_PECAS_INDEX, "_id": identificador, "_source": corpo})

    if not acoes:
        return {"ok": True, "indexados": 0, "avisos": len(lista), "index": VORTAL_PECAS_INDEX}

    try:
        sucesso, erros = bulk(cliente, acoes, refresh=True, stats_only=False)
    except Exception as erro:  # noqa: BLE001
        logger.warning("Vortal: indexação falhou (%s)", erro)
        return {"ok": False, "erro": str(erro), "indexados": 0, "index": VORTAL_PECAS_INDEX}
    return {
        "ok": True,
        "index": VORTAL_PECAS_INDEX,
        "avisos": len(lista),
        "indexados": int(sucesso),
        "falhas": len(erros or []),
        "erros": [str(item)[:200] for item in (erros or [])[:5]],
    }


def indexar_em_disco(*, uid: Optional[str] = None, destino_base: Optional[Path] = None, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Indexa o que já está em disco (um aviso ou todos)."""
    raiz = Path(destino_base or DESTINO_DIR)
    if uid:
        manifesto = ler_manifesto(uid, destino_base=raiz)
        if not manifesto:
            return {"ok": False, "erro": f"aviso {uid} não está em disco", "indexados": 0}
        return indexar_pecas([manifesto], destino_base=raiz, es=es)
    return indexar_pecas(None, destino_base=raiz, es=es)


# ---------------------------------------------------------------------------
# Consulta e estado
# ---------------------------------------------------------------------------
def estado(*, destino_base: Optional[Path] = None, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """O que está em disco e o que está indexado (para a página e para o diagnóstico)."""
    raiz = Path(destino_base or DESTINO_DIR)
    avisos = listar_avisos_em_disco(destino_base=raiz)
    ficheiros = [caminho for caminho in raiz.rglob("*") if caminho.is_file()] if raiz.is_dir() else []
    por_tipo: Dict[str, int] = {}
    pecas = 0
    com_texto = 0
    bytes_totais = 0
    for aviso in avisos:
        for peca in aviso.get("pecas") or []:
            pecas += 1
            bytes_totais += int(peca.get("bytes") or 0)
            com_texto += 1 if peca.get("texto_chars") else 0
            tipo = str(peca.get("tipo") or "outro")
            por_tipo[tipo] = por_tipo.get(tipo, 0) + 1

    cliente = es or get_es_client()
    indice: Dict[str, Any] = {"index": VORTAL_PECAS_INDEX, "disponivel": cliente is not None}
    if cliente is not None:
        try:
            ensure_indices(cliente)
            contagem = cliente.count(index=VORTAL_PECAS_INDEX).get("count")
            indice["documentos"] = int(contagem or 0)
            agregado = cliente.search(
                index=VORTAL_PECAS_INDEX,
                body={"size": 0, "aggs": {"avisos": {"cardinality": {"field": "uid"}}, "bytes": {"sum": {"field": "bytes"}}}},
            )
            indice["avisos"] = int((agregado.get("aggregations", {}).get("avisos", {}) or {}).get("value") or 0)
            indice["bytes"] = int((agregado.get("aggregations", {}).get("bytes", {}) or {}).get("value") or 0)
        except Exception as erro:  # noqa: BLE001
            indice["erro"] = str(erro)
    return {
        "disco": {
            "raiz": str(raiz),
            "ficheiros": len(ficheiros),
            "bytes": sum(caminho.stat().st_size for caminho in ficheiros),
            "avisos": len(avisos),
            "pecas": pecas,
            "com_texto": com_texto,
            "por_tipo": dict(sorted(por_tipo.items(), key=lambda par: par[1], reverse=True)),
        },
        "indice": indice,
        "ultimos": [
            {
                "uid": aviso.get("uid"),
                "url_aviso": aviso.get("url_aviso"),
                "recolhido_em": aviso.get("recolhido_em"),
                "pecas": (aviso.get("totais") or {}).get("pecas"),
                "bytes": (aviso.get("totais") or {}).get("bytes"),
            }
            for aviso in avisos[:10]
        ],
    }


def listar_pecas(*, uid: Optional[str] = None, limite: int = 50, es: Optional[Elasticsearch] = None, destino_base: Optional[Path] = None) -> Dict[str, Any]:
    """Peças indexadas (agrupáveis por aviso) — para a tabela da página."""
    cliente = es or get_es_client()
    if cliente is None:
        return {"itens": [], "total": 0, "erro": "Elasticsearch indisponível"}
    ensure_indices(cliente)
    filtro = {"term": {"uid": uid}} if uid else {"match_all": {}}
    try:
        resposta = cliente.search(
            index=VORTAL_PECAS_INDEX,
            body={
                "size": max(1, min(int(limite), 200)),
                "query": filtro,
                "sort": [{"recolhido_em": {"order": "desc"}}, {"nome.keyword": {"order": "asc", "unmapped_type": "keyword"}}],
                "_source": {"excludes": ["texto"]},
            },
        )
    except Exception as erro:  # noqa: BLE001
        return {"itens": [], "total": 0, "erro": str(erro)}
    total = int(((resposta.get("hits") or {}).get("total") or {}).get("value") or 0)
    itens = [hit.get("_source") or {} for hit in (resposta.get("hits") or {}).get("hits") or []]
    return {"itens": itens, "total": total, "uid": uid}


def pesquisar(texto: str, *, uid: Optional[str] = None, limite: int = 25, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Pesquisa no texto das peças (com trechos destacados) e no nome/tipo."""
    consulta = (texto or "").strip()
    if not consulta:
        return {"itens": [], "total": 0, "termo": ""}
    cliente = es or get_es_client()
    if cliente is None:
        return {"itens": [], "total": 0, "termo": consulta, "erro": "Elasticsearch indisponível"}
    ensure_indices(cliente)
    filtros: List[Dict[str, Any]] = []
    if uid:
        filtros.append({"term": {"uid": uid}})
    corpo = {
        "size": max(1, min(int(limite), 100)),
        "query": {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": consulta,
                            "fields": ["texto", "nome^3", "descricao^2", "tipo_label"],
                            "type": "best_fields",
                        }
                    }
                ],
                "filter": filtros,
            }
        },
        "highlight": {"fields": {"texto": {"fragment_size": 220, "number_of_fragments": 2}}},
        "_source": {"excludes": ["texto"]},
    }
    try:
        resposta = cliente.search(index=VORTAL_PECAS_INDEX, body=corpo)
    except Exception as erro:  # noqa: BLE001
        return {"itens": [], "total": 0, "termo": consulta, "erro": str(erro)}
    itens = []
    for hit in (resposta.get("hits") or {}).get("hits") or []:
        fonte = dict(hit.get("_source") or {})
        fonte["score"] = hit.get("_score")
        fonte["trechos"] = list(((hit.get("highlight") or {}).get("texto") or []))
        itens.append(fonte)
    return {"itens": itens, "total": int(((resposta.get("hits") or {}).get("total") or {}).get("value") or 0), "termo": consulta}


def apagar_aviso(uid: str, *, apagar_disco: bool = False, es: Optional[Elasticsearch] = None, destino_base: Optional[Path] = None) -> Dict[str, Any]:
    """Remove do índice (e, se pedido, do disco) um aviso."""
    cliente = es or get_es_client()
    apagados = 0
    if cliente is not None:
        try:
            ensure_indices(cliente)
            resposta = cliente.delete_by_query(index=VORTAL_PECAS_INDEX, body={"query": {"term": {"uid": uid}}}, refresh=True)
            apagados = int(resposta.get("deleted") or 0)
        except Exception as erro:  # noqa: BLE001
            return {"ok": False, "erro": str(erro), "apagados": 0}
    pasta = pasta_do_aviso(uid, destino_base=destino_base)
    if apagar_disco and pasta.is_dir():
        for caminho in sorted(pasta.rglob("*"), reverse=True):
            try:
                caminho.unlink() if caminho.is_file() else caminho.rmdir()
            except Exception:  # noqa: BLE001
                continue
        try:
            pasta.rmdir()
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "uid": uid, "apagados": apagados, "disco_apagado": bool(apagar_disco and not pasta.is_dir())}


def monitorizacao(*, limite: int = 20, destino_base: Optional[Path] = None, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Vista de monitorização (só administração): estado, avisos, histórico e índice."""
    raiz = Path(destino_base or DESTINO_DIR)
    base = estado(destino_base=raiz, es=es)
    avisos = listar_avisos_em_disco(destino_base=raiz)
    return {
        **base,
        "historico": historico_recolhas(limite=limite, destino_base=raiz),
        "avisos": [
            {
                "uid": aviso.get("uid"),
                "url_aviso": aviso.get("url_aviso"),
                "publicado": aviso.get("publicado"),
                "recolhido_em": aviso.get("recolhido_em"),
                "totais": aviso.get("totais"),
                "pasta": aviso.get("pasta"),
                "pecas": [
                    {
                        "ficheiro": peca.get("ficheiro"),
                        "tipo": peca.get("tipo"),
                        "tipo_label": TIPOS_LABEL.get(str(peca.get("tipo")), peca.get("tipo")),
                        "bytes": peca.get("bytes"),
                        "texto_chars": peca.get("texto_chars"),
                        "erro": peca.get("erro"),
                    }
                    for peca in (aviso.get("pecas") or [])
                ],
            }
            for aviso in avisos[: max(1, int(limite))]
        ],
    }


def pecas_em_memoria(
    url_ou_token: str,
    *,
    limite: int = 8,
    limite_texto: int = 20000,
    idioma: str = "pt-PT",
    cliente: Optional[requests.Session] = None,
) -> Dict[str, Any]:
    """Peças de um aviso **sem tocar no disco** — para a ficha do contrato.

    Resolve o aviso, descarrega até `limite` peças (as primeiras, que são as que
    interessam: caderno de encargos e programa do concurso) e devolve o texto
    extraído de cada uma, para a ficha poder mostrar os valores publicados
    (preço base, caução, prazos…). A recolha completa para disco é outra função
    (`recolher`).

    Uma peça que falhe não impede as outras: vem sem texto e com `erro`.
    """
    sessao = _cliente(cliente)
    token = token_de_url(url_ou_token)
    uid = uid_de_url(url_ou_token)
    informacao: Dict[str, Any] = {}
    if token:
        informacao = informacao_aviso(token, idioma=idioma, cliente=sessao)
        uid = informacao.get("uid") or uid
    if not uid:
        return {"erro": "não foi possível determinar o aviso a partir da ligação", "pecas": []}

    documentos = documentos_do_aviso(str(uid), cliente=sessao)
    pecas: List[Dict[str, Any]] = []
    for peca in documentos[: max(1, int(limite))]:
        item: Dict[str, Any] = {
            "nome": peca.get("nome"),
            "tipo": peca.get("tipo"),
            "tipo_label": TIPOS_LABEL.get(str(peca.get("tipo")), peca.get("tipo")),
            "extensao": peca.get("extensao"),
            "url": peca.get("url"),
            "texto": "",
            "erro": None,
        }
        try:
            blob, meta = descarregar_bytes(str(peca.get("url") or ""), cliente=sessao, maximo=MAX_BYTES)
            extraido = extrair_texto_de_bytes(blob, str(peca.get("nome") or "peca"), limite=limite_texto)
            item["bytes"] = meta.get("bytes")
            item["texto"] = extraido["texto"]
            item["texto_metodo"] = extraido["meta"].get("metodo")
            item["paginas"] = extraido["meta"].get("paginas")
            if extraido["meta"].get("precisa_ocr"):
                item["precisa_ocr"] = True
        except Exception as erro:  # noqa: BLE001
            item["erro"] = f"{type(erro).__name__}: {erro}"
        pecas.append(item)

    publicadas = len(documentos)
    lidas = len(pecas)
    if publicadas == 0:
        if informacao and informacao.get("publicado"):
            nota = (
                f"O aviso {uid} está publicado na plataforma (Vortal) mas não tem peças de acesso público: "
                "é um procedimento por convite, dirigido a fornecedores selecionados. "
                "A ficha fica com os dados do contrato e as ligações oficiais."
            )
        else:
            nota = (
                f"A plataforma (Vortal) não tem peças públicas para o aviso {uid}. "
                "Pode ainda não estar publicado ou ser um procedimento por convite."
            )
    elif lidas < publicadas:
        nota = (
            f"Peças lidas diretamente da plataforma (Vortal): {lidas} de {publicadas} "
            "(as primeiras, caderno de encargos e programa). "
            "A recolha completa para disco e índice faz-se no módulo «Peças do procedimento»."
        )
    else:
        nota = f"Peças lidas diretamente da plataforma (Vortal): {lidas} de {publicadas}."

    return {
        "uid": str(uid),
        "url_aviso": informacao.get("url_aviso") or url_ou_token,
        "publicado": informacao.get("publicado"),
        "total": publicadas,
        "incluidas": lidas,
        "pecas": pecas,
        "nota": nota,
    }


def meta() -> Dict[str, Any]:
    """Metamodelo do módulo (o que faz, de onde vem, limites)."""
    return {
        "modulo": "vortal",
        "titulo": "Peças do procedimento (Vortal) → disco + Elasticsearch",
        "descricao": (
            "Resolve o token público de um aviso da Vortal, lista as peças do procedimento, "
            "descarrega-as para disco, extrai o texto e indexa em `finance_vortal_pecas`."
        ),
        "base": BASE,
        "endpoints_api": [
            "/public/api/PublicTenderDocuments/GetPublicTenderInformation?uniqueIdentifierEncrypted=<token>&languageCode=pt-PT",
            "/public/api/ContractNoticeDetail/GetContractNoticeDocuments?contractNoticeUId=<uid>",
        ],
        "destino": str(DESTINO_DIR),
        "indice": VORTAL_PECAS_INDEX,
        "hosts_permitidos": sorted(HOSTS_PERMITIDOS),
        "tipos": TIPOS_LABEL,
        "extensoes_texto": sorted(EXTENSOES_TEXTO),
        "limites": {
            "bytes_por_peca": MAX_BYTES,
            "chars_por_peca": MAX_TEXTO,
            "timeout_s": TIMEOUT,
        },
        "notas": [
            "A lista de peças é pública: não é preciso sessão na Vortal (validado na sonda).",
            "O `downloadUrl` traz um token próprio e devolve o ficheiro com `Content-Disposition`.",
            "Só se descarrega de anfitriões `*.vortal.biz`.",
            "As peças são dados de terceiros: guardar em disco é a fonte de verdade; o índice serve para pesquisa.",
            "PDF digitalizado (imagem sem camada de texto) fica marcado `pdf-sem-texto`/`precisa_ocr`: a plataforma não faz OCR.",
        ],
    }
