#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recolha manual de deputados do Parlamento.pt para o PessoasIQ.

Pipeline:
1. Usa o template `parlamento-deputados` (postback pagination + detalhe XPath).
2. Guarda os itens crus em `data/deputados/deputados.json`.
3. Descarrega fotos para `data/deputados/fotos/<bid>.jpg`.
4. Transforma cada deputado num documento `finance_people` e indexa.

Utilização:
    cd C:\\LLMFinance\\finance-llm
    C:\\LLMFinance\\.venv\\Scripts\\python.exe _collect_deputados.py
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin
import argparse

# Garante que a raiz do projeto está no path para `api.*`
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.scraper_templates import build_source
from api.scraper_service import _walk_source
from api.elasticsearch_client import index_people

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("collect_deputados")

DATA_DIR = ROOT / "data" / "deputados"
FOTOS_DIR = DATA_DIR / "fotos"
RESULT_FILE = DATA_DIR / "deputados.json"

PHOTO_BASE = "https://app.parlamento.pt/webutils/getimage.aspx"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FOTOS_DIR.mkdir(parents=True, exist_ok=True)


def build_people_doc(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Converte item do scraper em documento finance_people."""
    data = item.get("data") or {}
    nome = str(data.get("nome") or item.get("title") or "").strip()
    bid = str(data.get("bid") or "").strip()
    if not nome or not bid:
        return None

    # Usamos o BID como NIF sintético (identificador único do Parlamento).
    nif = f"PT-AR-BID:{bid}"

    biografia = str(item.get("text") or "").strip()
    circulo = str(data.get("circulo") or "").strip()

    partido = str(data.get("partido") or "").strip()

    doc: Dict[str, Any] = {
        "nif": nif,
        "name": nome,
        "source": "parlamento.pt/deputados",
        "sources": ["parlamento.pt/deputados"],
        "biography": biografia,
        "tags": list(item.get("tags") or []),
        "metadata": {
            "bid": bid,
            "circulo_eleitoral": circulo,
            "partido": partido,
            "url_biografia": data.get("url"),
            "url_atividade": data.get("url_atividade"),
            "url_presencas": data.get("url_presencas"),
            "url_interesses": data.get("url_interesses"),
            "scraped_at": item.get("scraped_at"),
        },
    }

    # Sempre referenciar a foto (mesmo que o download ainda não tenha corrido,
    # o ficheiro é criado durante a recolha).
    foto_path = FOTOS_DIR / f"{bid}.jpg"
    doc["photo_path"] = str(foto_path.relative_to(ROOT).as_posix())
    doc["photo_url"] = f"{PHOTO_BASE}?id={bid}&type=deputado"

    return doc


def download_photo(bid: str, session: Optional[Any], options: Dict[str, Any]) -> Optional[Path]:
    """Descarrega foto do deputado via Scrapling Fetcher.get (HTTP simples)."""
    from scrapling.fetchers import Fetcher

    url = f"{PHOTO_BASE}?id={bid}&type=deputado"
    path = FOTOS_DIR / f"{bid}.jpg"
    if path.exists() and path.stat().st_size > 0:
        return path
    try:
        kwargs: Dict[str, Any] = {"stealthy_headers": True}
        timeout = options.get("timeout")
        if timeout:
            kwargs["timeout"] = timeout
        # Manter HTTP/1.1 para evitar stalls no app.parlamento.pt
        if options.get("http_version"):
            kwargs["http_version"] = options["http_version"]
        resp = Fetcher.get(url, **kwargs)
        content = getattr(resp, "content", None)
        if content is None:
            content = getattr(resp, "body", b"")
            if isinstance(content, str):
                content = content.encode("latin-1", errors="ignore")
        if content and len(content) > 128:
            path.write_bytes(content)
            logger.debug("Foto %s descarregada (%d bytes)", bid, len(content))
            return path
    except Exception as exc:
        logger.debug("Foto %s falhou: %s", bid, exc)
    return None


def collect_deputados(*, max_pages: int = 20, download_photos: bool = True, with_detail: bool = False) -> Dict[str, Any]:
    """Executa recolha completa e indexação."""
    ensure_dirs()

    source = build_source("parlamento-deputados", overrides={"pagination": {"max_pages": max_pages}})
    # Aumentar timeout e retentativas para o Parlamento.pt, que é lento.
    source.setdefault("options", {})
    source["options"].setdefault("timeout", 120)
    source["options"].setdefault("retries", 3)
    source["options"].setdefault("retry_delay", 2.0)
    # O detalhe (biografia) é lento e pode falhar; por defeito recolhe-se só a lista.
    if with_detail:
        source.setdefault("detail", {})
        source["detail"]["enabled"] = True
        source["detail"].setdefault("retries", 2)
        source["detail"].setdefault("retry_delay", 1.0)
        source["detail"].setdefault("timeout", 25)
    else:
        source.setdefault("detail", {})
        source["detail"]["enabled"] = False
    logger.info("Fonte: %s (%s)", source["name"], source["url"])
    logger.info("Detalhe (biografias): %s", "ligado" if with_detail else "desligado")

    items: List[Dict[str, Any]] = []
    stats: Dict[str, int] = {}
    foto_count = 0

    # _walk_source devolve iterador (page_number, page, page_items).
    for page_number, page, page_items in _walk_source(source, stats=stats):
        logger.info("Página %d: %d itens", page_number, len(page_items))
        if download_photos:
            for item in page_items:
                bid = str((item.get("data") or {}).get("bid") or "").strip()
                if bid:
                    if download_photo(bid, None, source.get("options", {})):
                        foto_count += 1
        items.extend(page_items)

    logger.info("Total de itens: %d | Fotos descarregadas: %d", len(items), foto_count)
    logger.info("Stats scraper: %s", stats)

    # Guardar JSON local
    RESULT_FILE.write_text(
        json.dumps({"count": len(items), "items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("JSON guardado em %s", RESULT_FILE)

    # Transformar e indexar pessoas
    people = [p for p in (build_people_doc(i) for i in items) if p]
    logger.info("Documentos finance_people: %d", len(people))
    if people:
        result = index_people(people, merge=True)
        logger.info("Indexação: %s", result)
    else:
        result = {"indexed_count": 0, "total": 0}

    return {
        "items": len(items),
        "photos": foto_count,
        "people": len(people),
        "indexed": result.get("indexed_count") or 0,
        "stats": stats,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recolha manual de deputados do Parlamento.pt")
    parser.add_argument("--max-pages", type=int, default=200, help="Máximo de páginas a percorrer (padrão: 200)")
    parser.add_argument("--no-photos", action="store_true", help="Não descarregar fotos")
    parser.add_argument("--with-detail", action="store_true", help="Tentar obter biografias (mais lento, pode falhar)")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout HTTP por pedido (padrão: 30s)")
    parser.add_argument("--retries", type=int, default=2, help="Retentativas por URL (padrão: 2)")
    args = parser.parse_args()
    summary = collect_deputados(
        max_pages=args.max_pages,
        download_photos=not args.no_photos,
        with_detail=args.with_detail,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
