"""Reprocessa páginas de debug MJ guardadas em disco e recria JSON de publicações.

Lê os HTML de debug_mj/{nif}/, extrai a grelha de resultados e os detalhes, e
grava debug_mj/{nif}/reprocessado.json com os dados estruturados.
"""
from __future__ import annotations

import glob
import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from collectors.publicacoes_mj import (
    PublicacaoMJ,
    PublicacoesMjClient,
    _fix_mojibake,
    parse_detalhe,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _find_nif_dirs(base_dir: str = "debug_mj") -> List[str]:
    """Devolve os caminhos das pastas que têm nome de NIF (apenas dígitos)."""
    if not os.path.isdir(base_dir):
        return []
    return [
        os.path.join(base_dir, d)
        for d in os.listdir(base_dir)
        if os.path.isdir(os.path.join(base_dir, d)) and re.fullmatch(r"\d+", d)
    ]


def _read_html(path: str) -> str:
    """Lê uma página de debug e corrige mojibake de descodificação CP1252."""
    with open(path, "r", encoding="utf-8") as fh:
        return _fix_mojibake(fh.read())


def _page_key(path: str) -> Optional[tuple[str, int, str]]:
    """Devolve ``(kind, page_number, timestamp)`` de um nome de ficheiro de debug."""
    name = os.path.basename(path)
    m = re.match(r"(search|next_page)_(\d{3})_(\d{8}_\d{6})\.html$", name)
    if not m:
        return None
    return (m.group(1), int(m.group(2)), m.group(3))


def _load_search_pages(nif_dir: str) -> List[str]:
    """Carrega a primeira tentativa completa da grelha de resultados.

    Cada tentativa grava um ``search_001_<ts>`` e vários ``next_page_<n>_<ts>``,
    com timestamps distintos por pedido. Para não misturar tentativas, agrupamos
    cronologicamente e reconstruímos a sequência: para cada número de página
    (1 = ``search_001``, 2 = ``next_page_001``, …) usamos a primeira ocorrência
    da primeira tentativa que a produziu. Só as páginas da **mesma tentativa**
    são combinadas.
    """
    files = sorted(
        glob.glob(os.path.join(nif_dir, "search_*.html"))
        + glob.glob(os.path.join(nif_dir, "next_page_*.html")),
        key=lambda f: (_page_key(f) or ("", 0, ""))[2],
    )
    if not files:
        return []

    # Agrupa em tentativas: uma tentativa começa num search_001 e inclui as
    # next_page seguintes até ao próximo search_001.
    attempts: List[List[str]] = []
    current: List[str] = []
    for f in files:
        if os.path.basename(f).startswith("search_001"):
            if current:
                attempts.append(current)
            current = [f]
        elif current:
            current.append(f)
    if current:
        attempts.append(current)

    chosen: Optional[List[str]] = None
    for attempt in attempts:
        pages: Dict[int, str] = {}
        for f in attempt:
            key = _page_key(f)
            if not key:
                continue
            kind, number, _ts = key
            page_index = 1 if kind == "search" else number + 1
            pages.setdefault(page_index, f)
        if 1 in pages:
            chosen = [pages[i] for i in sorted(pages)]
            break

    if not chosen:
        logger.warning("NIF %s: não encontrou tentativa com search_001", nif_dir)
        return []

    logger.info("NIF %s: %d páginas de resultados na tentativa escolhida", nif_dir, len(chosen))
    return [_read_html(f) for f in chosen]


def _load_detalhe_pages(nif_dir: str, limit: Optional[int] = None) -> List[str]:
    """Carrega detalhe_*.html por número de página, desduplicando por conteúdo.

    Cada detalhe é guardado várias vezes (uma por tentativa); mantemos a
    primeira ocorrência de cada número de página, por ordem cronológica.
    """
    files = sorted(glob.glob(os.path.join(nif_dir, "detalhe_*.html")))
    by_number: Dict[int, str] = {}
    for f in files:
        m = re.match(r"detalhe_(\d{3})_", os.path.basename(f))
        if not m:
            continue
        by_number.setdefault(int(m.group(1)), f)
    ordered = [by_number[k] for k in sorted(by_number)]
    if limit is not None:
        ordered = ordered[:limit]
    logger.info("NIF %s: %d detalhes distintos", nif_dir, len(ordered))
    return [_read_html(f) for f in ordered]


def reprocess_nif(nif_dir: str, nif: str) -> List[Dict[str, Any]]:
    """Reprocessa uma pasta de debug e devolve publicações como dicts."""
    search_pages = _load_search_pages(nif_dir)
    if not search_pages:
        logger.warning("Pasta %s sem páginas de pesquisa", nif_dir)
        return []

    detalhe_pages = _load_detalhe_pages(nif_dir)

    client = PublicacoesMjClient(min_interval=0)
    page_rows: List[List[PublicacaoMJ]] = []
    for html in search_pages:
        rows = client.parse_results(html, search_nif=nif, search_term=None, tipo="0")
        if rows:
            page_rows.append(rows)

    collected: List[PublicacaoMJ] = [row for page in page_rows for row in page]
    logger.info("NIF %s: %d páginas, %d publicações", nif, len(page_rows), len(collected))

    # Desduplica, mantendo a primeira ocorrência (a ordem cronológica dos
    # ficheiros preserva a sequência de publicação).
    seen: set[str] = set()
    unique: List[PublicacaoMJ] = []
    for row in collected:
        pid = row.pub_id
        if pid not in seen:
            seen.add(pid)
            unique.append(row)
    logger.info("NIF %s: %d publicações após desduplicação", nif, len(unique))

    # Associa detalhes pela ordem (grelha linha a linha, página a página).
    det_idx = 0
    for row in unique:
        if det_idx < len(detalhe_pages):
            try:
                for key, value in parse_detalhe(detalhe_pages[det_idx]).items():
                    if value and hasattr(row, key):
                        setattr(row, key, value)
                row.detail_fetched = True
            except Exception as exc:
                logger.warning("Falha ao parse detalhe %s: %s", row.pub_id, exc)
            det_idx += 1

    return [p.to_dict() for p in unique]


def main(base_dir: str = "debug_mj") -> None:
    for nif_dir in _find_nif_dirs(base_dir):
        nif = os.path.basename(nif_dir)
        pubs = reprocess_nif(nif_dir, nif)
        out_path = os.path.join(nif_dir, "reprocessado.json")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(pubs, fh, ensure_ascii=False, indent=2)
        logger.info("Guardado %s com %d publicações", out_path, len(pubs))


if __name__ == "__main__":
    main()
