"""Recolha do diretório de empresas do Racius (script local, independente da API).

Serve de **alternativa autónoma** à fonte «Racius · Diretório de empresas (PT)»
do módulo de recolha do IQ OS (`POST /scraper/sources/racius-diretorio/run`):
não precisa da API nem de sessão, recolhe a lista de empresas de uma pesquisa e
a **ficha** de cada uma (morada, forma jurídica, capital social, CAE…), grava o
resultado em **JSONL** e indexa-o no **Elasticsearch**.

Uso:
    python -m collectors.racius --q galp --pages 2
    python -m collectors.racius --q "" --pages 5 --limit 100
    python -m collectors.racius --q "construcao" --no-elastic --out data/racius/construcao.jsonl

Notas:
- A lista usa `https://www.racius.com/pesquisa/empresas/?q=<termo>` e pagina com
  o parâmetro `page` (`?q=<termo>&page=2`); o `robots.txt` do site permite o
  acesso (`User-agent: * / Allow: /`).
- Cada ficha é um pedido extra: `--delay` espaça os pedidos (cortesia) e
  `--limit` limita quantas fichas são abertas por execução.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LIST_URL = "https://www.racius.com/pesquisa/empresas/"
BASE_URL = "https://www.racius.com"
INDEX = "finance_racius"
#: Fonte do módulo de recolha do IQ OS que alimenta o mesmo índice.
SOURCE_ID = "racius-diretorio"
SINK_DIR = ROOT / "data" / "racius"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

logger = logging.getLogger("racius")

#: Rótulos conhecidos da ficha da empresa → nome do campo normalizado.
LABELS = {
    "morada": "morada",
    "forma jurídica": "forma_juridica",
    "capital social": "capital_social",
    "atividade": "atividade",
    "acerca da empresa": "acerca",
    "cae": "cae",
    "estado de atividade": "estado",
    "data de constituição": "constituicao",
    "telefone": "telefone",
    "email": "email",
    "site": "site",
}

_NIF_RE = re.compile(r"(\d{9})")
_MONEY_RE = re.compile(r"([\d.]+(?:,\d+)?)")
#: Prefixo do ícone de localização que o `get_text()` da lista arrasta («ico-gps»).
_ICON_RE = re.compile(r"^ico-[a-z-]+\s*", re.I)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _parse_money(value: str) -> Optional[float]:
    """Converte «€ 1.000.000,00» no número 1000000.0."""
    if not value:
        return None
    match = _MONEY_RE.search(value)
    if not match:
        return None
    raw = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "pt-PT,pt;q=0.9"})
    return session


def fetch(session: requests.Session, url: str, *, timeout: int = 30, retries: int = 2) -> str:
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.text
        except Exception as exc:  # noqa: BLE001 — a recolha segue sem este item
            last_exc = exc
            if attempt < retries:
                time.sleep(1.0 + attempt)
    raise RuntimeError(f"Falha ao obter {url}: {last_exc}")


def parse_list(html: str) -> List[Dict[str, str]]:
    """Extrai as empresas de uma página de resultados."""
    soup = BeautifulSoup(html, "lxml")
    items: List[Dict[str, str]] = []
    for link in soup.select("a.results__col-link"):
        nome = _clean(link.select_one("p.results__name").get_text() if link.select_one("p.results__name") else "")
        atividade = link.select_one("p.results__activity")
        atividade_txt = _clean(atividade.get_text()) if atividade else ""
        local = link.select_one("div.results__col-location")
        local_txt = _ICON_RE.sub("", _clean(local.get_text()) if local else "")
        nif_match = _NIF_RE.search(atividade_txt)
        href = link.get("href") or ""
        if not nome and not nif_match:
            continue
        items.append(
            {
                "nome": nome,
                "nif": nif_match.group(1) if nif_match else "",
                "localizacao": local_txt,
                "url": href if href.startswith("http") else f"{BASE_URL}{href}",
            }
        )
    return items


def parse_detail(html: str) -> Dict[str, Any]:
    """Extrai a ficha da empresa (pares rótulo/valor) da página de detalhe."""
    soup = BeautifulSoup(html, "lxml")
    pairs: List[Tuple[str, str]] = []
    for li in soup.select("li.detail__detail"):
        keys = [_clean(p.get_text()) for p in li.select("p.detail__key-info")]
        values = [_clean(p.get_text()) for p in li.select("p.t--d-blue")]
        for key, value in zip(keys, values):
            if key and value:
                pairs.append((key, value))

    ficha: Dict[str, str] = {}
    for key, value in pairs:
        ficha.setdefault(key, value)

    doc: Dict[str, Any] = {"ficha": ficha}
    for key, value in ficha.items():
        field = LABELS.get(key.strip().lower())
        if field:
            doc[field] = value
    capital = _parse_money(doc.get("capital_social", ""))
    if capital is not None:
        doc["capital_social_eur"] = capital
    # O segundo par do bloco da morada tem rótulo variável: é o concelho, e o
    # valor é o distrito (ex.: "Santarém": "Santarém").
    for index, (key, value) in enumerate(pairs):
        if key.strip().lower() == "morada" and index + 1 < len(pairs):
            localidade, distrito = pairs[index + 1]
            if localidade.strip().lower() not in LABELS:
                doc["concelho"] = localidade
                doc["distrito"] = distrito
            break
    return doc


def collect(
    q: str,
    *,
    pages: int = 1,
    limit: Optional[int] = None,
    with_detail: bool = True,
    delay: float = 1.0,
    timeout: int = 30,
) -> Iterator[Dict[str, Any]]:
    """Percorre as páginas de resultados e devolve as empresas (com ficha)."""
    session = make_session()
    emitted = 0
    for page in range(1, max(1, pages) + 1):
        params: Dict[str, Any] = {"q": q}
        if page > 1:
            params["page"] = page
        url = f"{LIST_URL}?{urlencode(params)}"
        html = fetch(session, url, timeout=timeout)
        rows = parse_list(html)
        logger.info("Página %s: %s empresas", page, len(rows))
        if not rows:
            break
        for row in rows:
            if limit is not None and emitted >= limit:
                return
            doc = dict(row)
            if with_detail and row["url"]:
                try:
                    time.sleep(delay)
                    doc.update(parse_detail(fetch(session, row["url"], timeout=timeout)))
                except Exception as exc:  # noqa: BLE001 — segue sem ficha
                    logger.warning("Ficha de %s falhou: %s", row["url"], exc)
            emitted += 1
            yield doc


def write_jsonl(items: Iterable[Dict[str, Any]], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            written += 1
    return written


def ensure_index(client: Any) -> None:
    """Cria `finance_racius` com o mapeamento partilhado dos diretórios."""
    from api.elasticsearch_client import ensure_directory_index

    ensure_directory_index(client, INDEX, ("ficha",))


def index_items(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Indexa as empresas no índice de diretório `finance_racius`.

    Usa o indexador do IQ OS (`index_directory_items`), para os documentos
    ficarem com a mesma forma quer venham deste script quer da recolha da API.
    """
    from api.elasticsearch_client import index_directory_items

    return index_directory_items(
        INDEX,
        source_id=SOURCE_ID,
        source_name="Racius · Diretório de empresas (PT)",
        run_id=time.strftime("%Y%m%dT%H%M%S", time.gmtime()),
        items=[_as_item(doc) for doc in items],
        trigger="script",
        flattened_fields=("ficha",),
    )


def _as_item(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Converte uma empresa no item da recolha (`data` + `item_id`).

    O `item_id` segue a mesma fórmula do motor de recolha
    (`<fonte>::<campo>=<valor>::…`, com `id_fields: ["nif", "url"]`), para o
    mesmo NIF recolhido pela API e por este script **atualizar** o mesmo
    documento em vez de o duplicar.
    """
    body = {k: v for k, v in doc.items() if k not in ("item_id", "scraped_at")}
    parts = [f"{key}={doc[key]}" for key in ("nif", "url") if doc.get(key) not in (None, "")]
    digest = hashlib.sha1(f"{SOURCE_ID}::{'::'.join(parts)}".encode("utf-8")).hexdigest()[:24]
    return {
        "item_id": f"{SOURCE_ID}:{digest}",
        "title": doc.get("nome") or "",
        "url": doc.get("url") or "",
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data": body,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Recolha do diretório de empresas do Racius.")
    parser.add_argument("--q", default="", help="Termo de pesquisa (vazio = todas as empresas).")
    parser.add_argument("--pages", type=int, default=1, help="Nº de páginas de resultados (15 empresas por página).")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de empresas a recolher.")
    parser.add_argument("--no-detail", action="store_true", help="Não abrir a ficha de cada empresa.")
    parser.add_argument("--delay", type=float, default=0.8, help="Pausa entre pedidos de ficha (segundos).")
    parser.add_argument("--out", default=str(SINK_DIR / "racius_empresas.jsonl"), help="Ficheiro JSONL de saída.")
    parser.add_argument("--no-elastic", action="store_true", help="Não indexar no Elasticsearch.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    items = list(
        collect(
            args.q,
            pages=args.pages,
            limit=args.limit,
            with_detail=not args.no_detail,
            delay=args.delay,
        )
    )
    if not items:
        logger.warning("Sem empresas recolhidas.")
        return 1
    out = Path(args.out)
    written = write_jsonl(items, out)
    logger.info("JSONL: %s empresas em %s", written, out)
    if not args.no_elastic:
        try:
            result = index_items(items)
            logger.info("Elasticsearch: %s indexadas, %s erros (%s)", result["indexed_count"], result["error_count"], INDEX)
        except Exception as exc:  # noqa: BLE001 — o JSONL já está gravado
            logger.error("Indexação no Elasticsearch falhou: %s", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
