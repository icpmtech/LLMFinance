"""Recolha do diretório de empresas do Racius (script local, independente da API).

Serve de **alternativa autónoma** à fonte «Racius · Diretório de empresas (PT)»
do módulo de recolha do IQ OS (`POST /scraper/sources/racius-diretorio/run`):
não precisa da API nem de sessão, recolhe a lista de empresas de uma pesquisa e
a **ficha** de cada uma (morada, forma jurídica, capital social, CAE…), grava o
resultado em **JSONL** e indexa-o no **Elasticsearch**.

Uso:
    python -m collectors.racius --q galp --pages 2
    python -m collectors.racius --q "" --pages 5 --limit 100
    python -m collectors.racius --distrito porto --pages 10
    python -m collectors.racius --q "construcao" --no-elastic --out data/racius/construcao.jsonl

Notas:
- A lista usa `https://www.racius.com/pesquisa/empresas/?q=<termo>` e pagina com
  o parâmetro `page` (`?q=<termo>&page=2`); com `--distrito` a lista é a do
  diretório geográfico (`/empresas-em-portugal/distrito-<distrito>/`). O
  `robots.txt` do site permite o acesso (`User-agent: * / Allow: /`).
- O site devolve no máximo **3.000 resultados por consulta** (200 páginas de 15);
  `--sort` (relevância/mais recentes/mais antigas) é a forma de alargar a
  cobertura de um distrito grande.
- Cada ficha é um pedido extra: `--delay` espaça os pedidos (cortesia) e
  `--limit` limita quantas fichas são abertas por execução.
- Além do JSONL (`--out`), a recolha é gravada em JSON com o mesmo nome e
  extensão `.json`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LIST_URL = "https://www.racius.com/pesquisa/empresas/"
#: Lista do diretório geográfico: um distrito por URL (`/distrito-porto/`).
DISTRICT_URL = "https://www.racius.com/empresas-em-portugal/distrito-{slug}/"
BASE_URL = "https://www.racius.com"
INDEX = "finance_racius"
#: Fonte do módulo de recolha do IQ OS que alimenta o mesmo índice.
SOURCE_ID = "racius-diretorio"
SINK_DIR = ROOT / "data" / "racius"
#: Tabela oficial concelho → distrito (os 308 concelhos), usada para validar a
#: geografia da ficha — ver `resolve_geo`.
GEO_FILE = ROOT / "data" / "geo" / "concelhos_distritos.json"
#: Ordenações da lista (`sort` do Racius). Variar a ordenação alarga a cobertura:
#: o site não devolve mais de 3.000 resultados por consulta.
SORT_PARAMS = {"relevance": "score", "recent": "-id", "oldest": "id"}
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


def _fold(value: str) -> str:
    """Chave de comparação de nomes geográficos: sem acentos nem caixa."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in decomposed if not unicodedata.combining(char)).strip().lower()


def _slug(value: str) -> str:
    """Segmento do URL do Racius (`Viana do Castelo` → `viana-do-castelo`)."""
    return re.sub(r"[^a-z0-9]+", "-", _fold(_clean(value))).strip("-")


@lru_cache(maxsize=1)
def _geo_tables() -> Tuple[Dict[str, str], Dict[str, str]]:
    """Concelho → distrito e distrito → grafia canónica, a partir de `GEO_FILE`.

    Sem a tabela o coletor continua a funcionar: `resolve_geo` devolve o que a
    ficha disser, sem validar.
    """
    try:
        data = json.loads(GEO_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # noqa: BLE001 — a ficha ainda serve
        logger.warning("Tabela geográfica indisponível (%s): %s", GEO_FILE, exc)
        return {}, {}
    concelhos = {_fold(nome): distrito for nome, distrito in (data.get("concelhos") or {}).items()}
    distritos = {_fold(nome): nome for nome in data.get("distritos") or []}
    return concelhos, distritos


def resolve_geo(label: str, value: str) -> Dict[str, str]:
    """Concelho e distrito a partir do par geográfico da ficha do Racius.

    O bloco da morada mostra o par «concelho, distrito» (ex.: «Alcobaça»,
    «Leiria»), mas nas cidades mostra a **freguesia** no rótulo (ex.: «Sé»,
    «Funchal») — daí validar o par contra a tabela dos 308 concelhos:

    - rótulo é concelho e o valor é o seu distrito → concelho = rótulo;
    - rótulo não é concelho mas o valor é → concelho = valor, rótulo fica em
      `localidade`;
    - caso contrário guarda-se o distrito (se conhecido) sem inventar concelho.
    """
    concelhos, distritos = _geo_tables()
    label, value = _clean(label), _clean(value)
    label_distrito = concelhos.get(_fold(label))
    value_distrito = concelhos.get(_fold(value))

    if label_distrito and (value_distrito is None or value_distrito == label_distrito):
        return {"concelho": label, "distrito": label_distrito}
    if value_distrito:
        return {"localidade": label, "concelho": value, "distrito": value_distrito}
    value_distrito = distritos.get(_fold(value))
    if value_distrito:
        return {"localidade": label, "distrito": value_distrito}
    return {}


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
    # O par seguinte ao «Morada» é a geografia da empresa (concelho/distrito ou
    # freguesia/concelho): o `resolve_geo` diz qual dos dois é o concelho.
    for index, (key, value) in enumerate(pairs):
        if key.strip().lower() == "morada" and index + 1 < len(pairs):
            label, valor = pairs[index + 1]
            if label.strip().lower() not in LABELS:
                doc.update(resolve_geo(label, valor))
            break
    return doc


def _geo_from_localizacao(localizacao: str) -> Dict[str, str]:
    """Geografia a partir da linha da lista («Samora Correia, Benavente»).

    Só é usada quando a ficha não trouxe o par da morada: a lista dá a
    localidade e o concelho, nunca o distrito.
    """
    parts = [part.strip() for part in (localizacao or "").split(",") if part.strip()]
    if not parts:
        return {}
    if len(parts) == 1:
        return resolve_geo(parts[0], parts[0])
    return resolve_geo(parts[0], parts[-1])


def collect(
    q: str,
    *,
    distrito: Optional[str] = None,
    sort: str = "relevance",
    pages: int = 1,
    limit: Optional[int] = None,
    with_detail: bool = True,
    delay: float = 1.0,
    page_delay: float = 0.2,
    timeout: int = 30,
) -> Iterator[Dict[str, Any]]:
    """Percorre as páginas de resultados e devolve as empresas (com ficha).

    Com `distrito`, a lista é a do diretório geográfico desse distrito
    (`/empresas-em-portugal/distrito-<slug>/`) em vez da pesquisa por termo.
    O site devolve no máximo 3.000 resultados por consulta (200 páginas de 15),
    pelo que variar `sort` é a forma de alargar a cobertura.
    """
    session = make_session()
    emitted = 0
    base = DISTRICT_URL.format(slug=_slug(distrito)) if distrito else LIST_URL
    for page in range(1, max(1, pages) + 1):
        params: Dict[str, Any] = {"q": q, "sort": SORT_PARAMS.get(sort, "score")}
        if page > 1:
            params["page"] = page
        url = f"{base}?{urlencode(params)}"
        if page > 1 and page_delay:
            time.sleep(page_delay)
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
            if not doc.get("distrito"):
                doc.update(_geo_from_localizacao(doc.get("localizacao", "")))
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


def write_json(items: Iterable[Dict[str, Any]], path: Path) -> int:
    """Grava a recolha como um único array JSON (além do JSONL)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(items)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(rows)


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
    parser.add_argument(
        "--distrito",
        default=None,
        help="Recolher a lista de um distrito (ex.: porto, lisboa, viana-do-castelo).",
    )
    parser.add_argument("--pages", type=int, default=1, help="Nº de páginas de resultados (15 empresas por página).")
    parser.add_argument(
        "--sort",
        choices=sorted(SORT_PARAMS),
        default="relevance",
        help="Ordenação da lista (variar a ordenação alarga a cobertura; o site limita a 200 páginas).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Máximo de empresas a recolher.")
    parser.add_argument("--no-detail", action="store_true", help="Não abrir a ficha de cada empresa.")
    parser.add_argument("--delay", type=float, default=0.8, help="Pausa entre pedidos de ficha (segundos).")
    parser.add_argument("--page-delay", type=float, default=0.2, help="Pausa entre páginas da lista (segundos).")
    parser.add_argument("--out", default=str(SINK_DIR / "racius_empresas.jsonl"), help="Ficheiro JSONL de saída.")
    parser.add_argument("--no-elastic", action="store_true", help="Não indexar no Elasticsearch.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    items = list(
        collect(
            args.q,
            distrito=args.distrito,
            sort=args.sort,
            pages=args.pages,
            limit=args.limit,
            with_detail=not args.no_detail,
            delay=args.delay,
            page_delay=args.page_delay,
        )
    )
    if not items:
        logger.warning("Sem empresas recolhidas.")
        return 1
    out = Path(args.out)
    written = write_jsonl(items, out)
    logger.info("JSONL: %s empresas em %s", written, out)
    out_json = out.with_suffix(".json")
    logger.info("JSON: %s empresas em %s", write_json(items, out_json), out_json)
    if not args.no_elastic:
        try:
            result = index_items(items)
            logger.info("Elasticsearch: %s indexadas, %s erros (%s)", result["indexed_count"], result["error_count"], INDEX)
        except Exception as exc:  # noqa: BLE001 — o JSONL já está gravado
            logger.error("Indexação no Elasticsearch falhou: %s", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
