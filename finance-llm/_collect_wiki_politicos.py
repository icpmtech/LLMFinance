#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Recolha de políticos de Portugal a partir da Wikipédia PT.

Pipeline:
1. Lista membros da categoria `Categoria:Políticos de Portugal` (e subcategorias
   opcionais) via MediaWiki API.
2. Para cada página obtém wikitext, imagens e categorias.
3. Extrai infobox (Info/Político, Info/Pessoa, etc.), resumo e imagem principal.
4. Descarrega a foto para `data/politicos_portugal/fotos/<slug>.jpg`.
5. Guarda `data/politicos_portugal/politicos.json`.
6. Indexa documentos `finance_people` (NIF sintético `PT-WIKI-PT:<pageid>`).
7. Guarda relações (partido, cargos, cargos públicos) em `finance_world_relations`
   e nós em `finance_network_state` para o grafo.

Utilização:
    C:\LLMFinance\.venv\Scripts\python.exe _collect_wiki_politicos.py
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, unquote, urljoin

import requests

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import (
    NETWORK_STATE_INDEX,
    PEOPLE_INDEX,
    WORLD_RELATIONS_INDEX,
    ensure_indices,
    get_es_client,
    index_people,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("collect_wiki_politicos")

DATA_DIR = ROOT / "data" / "politicos_portugal"
FOTOS_DIR = DATA_DIR / "fotos"
RESULT_FILE = DATA_DIR / "politicos.json"

API_URL = "https://pt.wikipedia.org/w/api.php"
USER_AGENT = "IQOS/1.0 (pedro.mourao.martins@example.com)"

DEFAULT_CATEGORIES = [
    "Categoria:Políticos de Portugal",
]

RETRY_STATUS = {429, 500, 502, 503, 504}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FOTOS_DIR.mkdir(parents=True, exist_ok=True)


def _slugify(value: str) -> str:
    s = value.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")[:80]


def api_get(params: Dict[str, Any], *, retries: int = 3) -> Optional[Dict[str, Any]]:
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(retries):
        try:
            resp = requests.get(
                API_URL,
                params=params,
                headers=headers,
                timeout=30,
            )
            if resp.status_code in RETRY_STATUS:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("API falhou (tentativa %d): %s", attempt + 1, exc)
            time.sleep(2 ** attempt)
    return None


def list_category_members(category: str, cmtype: str = "page|subcat", limit: int = 500) -> List[Dict[str, Any]]:
    """Devolve todos os membros de uma categoria via paginação da API."""
    members: List[Dict[str, Any]] = []
    cmcontinue: Optional[str] = None
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmtype": cmtype,
            "cmlimit": limit,
            "format": "json",
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue
        data = api_get(params)
        if not data or "query" not in data:
            break
        members.extend(data["query"]["categorymembers"])
        cmcontinue = data.get("continue", {}).get("cmcontinue")
        if not cmcontinue:
            break
    return members


def parse_page(title: str) -> Optional[Dict[str, Any]]:
    """Obtém wikitext, imagens e categorias de uma página."""
    params = {
        "action": "parse",
        "page": title,
        "prop": "text|wikitext|images|categories|properties",
        "format": "json",
        "redirects": 1,
    }
    data = api_get(params)
    if not data or "parse" not in data:
        return None
    return data["parse"]


def _strip_wiki_markup(value: str) -> str:
    """Limpa markup wiki, HTML residual e templates aninhados."""
    from bs4 import BeautifulSoup

    # Remover templates aninhados {{...}}
    value = re.sub(r"\{\{.*?\}\}", "", value, flags=re.DOTALL)
    # Remover markup wiki [[Alvo|texto]] -> texto
    value = re.sub(r"\[\[(?:[^]|]+\|)?([^]|]+)\]\]", r"\1", value)
    # Remover tags HTML (caso existam)
    value = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    # Remover referências [1], [2], etc.
    value = re.sub(r"\[\d+\]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _extract_infobox(wikitext: str) -> Dict[str, str]:
    """Extrai campos do primeiro template Infobox/Info encontrado."""
    result: Dict[str, str] = {}
    # Procurar por {{Info/... ou {{Infobox ... (primeiro nível, não nested)
    match = re.search(
        r"\{\{(?:Info|Infobox)[^}|\n]*\n(.*?)\n\}\}",
        wikitext,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return result
    body = match.group(1)
    for line in body.split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        line = line[1:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        value = _strip_wiki_markup(value)
        if value and value not in {"-", "—", "?"}:
            result[key] = value
    return result


def _find_main_image(images: List[str], title: str) -> Optional[str]:
    """Heurística para escolher a foto principal (evitar ícones/flags)."""
    skip_prefixes = {
        "flag_", "bandeira_", "flag_of_", "coat_of_arms", "brasão", "increase", "decrease",
        "question_", "commons-", "wikimedia", "signature", "assinatura", "portal",
        "stub", "esboço", "icone", "icon", "logo",
    }
    candidates: List[str] = []
    for img in images:
        name_lower = img.lower()
        if any(name_lower.startswith(p) or (p in name_lower and p != "") for p in skip_prefixes):
            continue
        candidates.append(img)
    # Preferir imagem cujo nome contenha parte do título
    title_parts = set(_slugify(title).split("_"))
    for img in candidates:
        img_parts = set(_slugify(Path(img).stem).split("_"))
        if title_parts & img_parts:
            return img
    return candidates[0] if candidates else None


def _image_url(filename: str, width: int = 300) -> Optional[str]:
    """Devolve URL direto da imagem via API de imagem."""
    params = {
        "action": "query",
        "titles": f"File:{filename}",
        "prop": "imageinfo",
        "iiprop": "url|size",
        "iiurlwidth": width,
        "format": "json",
        "redirects": 1,
    }
    data = api_get(params)
    if not data or "query" not in data:
        return None
    pages = data["query"].get("pages", {})
    for page in pages.values():
        if "imageinfo" in page and page["imageinfo"]:
            info = page["imageinfo"][0]
            return info.get("thumburl") or info.get("url")
    return None


def _clean_summary(text: str) -> str:
    """Converte HTML renderizado da Wikipédia em texto limpo.

    Remove scripts, estilos, caixas de navegação e extrai apenas o texto
    dos parágrafos principais.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(text, "html.parser")
    # Remover elementos de navegação/estilo
    for tag in soup.find_all(["script", "style", "nav", "table", "sup"]):
        tag.decompose()
    for cls in ("mw-editsection", "navbox", "metadata", "toc", "mw-empty-elt"):
        for el in soup.find_all(class_=cls):
            el.decompose()

    # O HTML da API vem dentro de <div class="mw-parser-output">; usá-lo como corpo.
    body = soup.find("div", class_="mw-parser-output") or soup

    # Extrair parágrafos com texto real
    paragraphs: List[str] = []
    for p in body.find_all("p"):
        txt = p.get_text(" ", strip=True)
        # Ignorar linhas vazias ou de navegação residual
        if len(txt) < 30:
            continue
        if any(txt.lower().startswith(s) for s in {"ir para o conteúdo", "menu principal", "navegação", "colaboração"}):
            continue
        paragraphs.append(txt)

    return "\n\n".join(paragraphs).strip()


def extract_politician(parse_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Transforma parse da Wikipédia num documento de político normalizado."""
    title = parse_data.get("title", "")
    pageid = parse_data.get("pageid")
    if not title or not pageid:
        return None
    wikitext = parse_data.get("wikitext", {}).get("*", "")
    rendered = parse_data.get("text", {}).get("*", "")
    infobox = _extract_infobox(wikitext)

    # Resumo: primeiro parágrafo significativo do texto renderizado
    summary = _clean_summary(parse_data.get("text", {}).get("*", ""))
    # Tentar isolar primeiro parágrafo com conteúdo real
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", summary) if p.strip()]
    first_para = ""
    for p in paragraphs:
        if len(p) > 60 and not p.startswith(("[", "{", "|")):
            first_para = p
            break
    if not first_para and paragraphs:
        first_para = paragraphs[0]

    # Campos do infobox
    nome = infobox.get("nome") or infobox.get("nome_completo") or title
    nascimento = infobox.get("nascimento") or infobox.get("data_nascimento") or ""
    morte = infobox.get("morte") or infobox.get("data_morte") or ""
    nacionalidade = infobox.get("nacionalidade") or ""
    ocupacao = infobox.get("ocupação") or infobox.get("profissão") or ""
    partido = infobox.get("partido") or infobox.get("partido_político") or ""
    cargo = infobox.get("título") or infobox.get("cargo") or ""
    mandato = infobox.get("mandato") or ""
    imagem_nome = _find_main_image(parse_data.get("images", []), title)

    categories = [c.get("*", "") for c in parse_data.get("categories", [])]

    doc: Dict[str, Any] = {
        "pageid": pageid,
        "title": title,
        "wiki_url": f"https://pt.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
        "name": nome,
        "summary": first_para,
        "full_text": summary,
        "infobox": infobox,
        "birth_date": nascimento,
        "death_date": morte,
        "nationality": nacionalidade,
        "occupation": ocupacao,
        "party": partido,
        "office": cargo,
        "term": mandato,
        "categories": categories,
        "image_filename": imagem_nome,
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return doc


def download_photo(filename: str, slug: str) -> Optional[Path]:
    """Descarrega a imagem principal da Wikipédia."""
    if not filename:
        return None
    ext = Path(filename).suffix.lower() or ".jpg"
    path = FOTOS_DIR / f"{slug}{ext}"
    if path.exists() and path.stat().st_size > 128:
        return path
    url = _image_url(filename)
    if not url:
        return None
    for attempt in range(3):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            resp.raise_for_status()
            if resp.content and len(resp.content) > 128:
                path.write_bytes(resp.content)
                return path
        except Exception as exc:
            logger.debug("Download foto %s falhou (tentativa %d): %s", filename, attempt + 1, exc)
            time.sleep(2 ** attempt)
    return None


def build_people_doc(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Converte item Wikipédia em documento finance_people."""
    pageid = item.get("pageid")
    name = item.get("name") or item.get("title")
    if not pageid or not name:
        return None
    nif = f"PT-WIKI-PT:{pageid}"
    photo_path = item.get("photo_path")
    photo_url = item.get("photo_url")
    doc: Dict[str, Any] = {
        "nif": nif,
        "name": name,
        "source": "pt.wikipedia.org",
        "sources": ["pt.wikipedia.org"],
        "biography": item.get("summary", ""),
        "tags": ["politicos", "portugal", "wikipedia", "pessoas"],
        "metadata": {
            "pageid": pageid,
            "wiki_url": item.get("wiki_url"),
            "birth_date": item.get("birth_date"),
            "death_date": item.get("death_date"),
            "nationality": item.get("nationality"),
            "occupation": item.get("occupation"),
            "party": item.get("party"),
            "office": item.get("office"),
            "term": item.get("term"),
            "categories": item.get("categories", []),
            "scraped_at": item.get("scraped_at"),
        },
    }
    if photo_path:
        doc["photo_path"] = photo_path
    if photo_url:
        doc["photo_url"] = photo_url
    return doc


def index_relations(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Indexa nós (network_state) e arestas (world_relations) para o grafo."""
    client = get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    for item in items:
        person_nif = f"PT-WIKI-PT:{item['pageid']}"
        person_name = item.get("name") or item["title"]
        # Nó pessoa
        nodes.append({
            "_index": NETWORK_STATE_INDEX,
            "_id": f"{NETWORK_STATE_INDEX}:{person_nif}",
            "_op_type": "index",
            "entity_id": person_nif,
            "name": person_name,
            "kind": "person",
            "source": "pt.wikipedia.org",
            "tags": ["politicos", "portugal", "pessoa"],
            "photo_url": item.get("photo_url"),
            "first_seen": now,
            "last_seen": now,
        })

        # Aresta partido
        party = (item.get("party") or "").strip()
        if party:
            party_id = f"partido:{_slugify(party)}"
            nodes.append({
                "_index": NETWORK_STATE_INDEX,
                "_id": f"{NETWORK_STATE_INDEX}:{party_id}",
                "_op_type": "index",
                "entity_id": party_id,
                "name": party,
                "kind": "party",
                "source": "pt.wikipedia.org",
                "tags": ["partido", "portugal"],
                "first_seen": now,
                "last_seen": now,
            })
            edges.append({
                "_index": WORLD_RELATIONS_INDEX,
                "_id": f"{WORLD_RELATIONS_INDEX}:{person_nif}->{party_id}",
                "_op_type": "index",
                "source_id": person_nif,
                "source_kind": "person",
                "source_name": person_name,
                "target_id": party_id,
                "target_kind": "party",
                "target_name": party,
                "relation": "MEMBER_OF",
                "relation_label": "membro de",
                "weight": 1,
                "first_seen": now,
                "last_seen": now,
                "evidence": [item.get("wiki_url")],
            })

        # Aresta cargo
        office = (item.get("office") or "").strip()
        if office:
            office_id = f"cargo:{_slugify(office)}"
            nodes.append({
                "_index": NETWORK_STATE_INDEX,
                "_id": f"{NETWORK_STATE_INDEX}:{office_id}",
                "_op_type": "index",
                "entity_id": office_id,
                "name": office,
                "kind": "office",
                "source": "pt.wikipedia.org",
                "tags": ["cargo", "portugal"],
                "first_seen": now,
                "last_seen": now,
            })
            edges.append({
                "_index": WORLD_RELATIONS_INDEX,
                "_id": f"{WORLD_RELATIONS_INDEX}:{person_nif}->{office_id}",
                "_op_type": "index",
                "source_id": person_nif,
                "source_kind": "person",
                "source_name": person_name,
                "target_id": office_id,
                "target_kind": "office",
                "target_name": office,
                "relation": "HOLDS_OFFICE",
                "relation_label": "ocupa/detém",
                "weight": 1,
                "period": item.get("term", ""),
                "first_seen": now,
                "last_seen": now,
                "evidence": [item.get("wiki_url")],
            })

    from elasticsearch.helpers import bulk
    node_res = {"success": 0, "failed": 0}
    edge_res = {"success": 0, "failed": 0}
    try:
        node_stats = bulk(client, nodes, raise_on_error=False)
        node_res = {"success": node_stats[0], "failed": len(node_stats[1])}
    except Exception as exc:
        logger.exception("Falha ao indexar nós: %s", exc)
        node_res = {"success": 0, "failed": len(nodes), "error": str(exc)}
    try:
        edge_stats = bulk(client, edges, raise_on_error=False)
        edge_res = {"success": edge_stats[0], "failed": len(edge_stats[1])}
    except Exception as exc:
        logger.exception("Falha ao indexar arestas: %s", exc)
        edge_res = {"success": 0, "failed": len(edges), "error": str(exc)}

    try:
        client.indices.refresh(index=NETWORK_STATE_INDEX)
        client.indices.refresh(index=WORLD_RELATIONS_INDEX)
    except Exception:
        pass

    return {"nodes": node_res, "edges": edge_res}


def _save_progress(items: List[Dict[str, Any]], errors: List[str], photo_count: int) -> None:
    """Guarda ficheiro parcial para evitar perder todo o trabalho num crash."""
    RESULT_FILE.write_text(
        json.dumps(
            {"count": len(items), "photos": photo_count, "errors": len(errors), "items": items},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def collect_wiki_politicos(
    *,
    categories: Optional[List[str]] = None,
    max_pages: Optional[int] = None,
    download_photos: bool = True,
    save_every: int = 20,
    resume: bool = True,
) -> Dict[str, Any]:
    """Executa a recolha completa e indexação."""
    ensure_dirs()
    categories = categories or DEFAULT_CATEGORIES

    # 1. Listar páginas únicas
    seen_titles: set[str] = set()
    pages: List[Tuple[int, str]] = []  # (pageid, title)
    for cat in categories:
        logger.info("A listar categoria: %s", cat)
        members = list_category_members(cat, cmtype="page")
        for m in members:
            if m["ns"] != 0:
                continue
            title = m["title"]
            if title in seen_titles:
                continue
            seen_titles.add(title)
            pages.append((m["pageid"], title))
        logger.info("  -> %d páginas até agora", len(pages))
        if max_pages and len(pages) >= max_pages:
            pages = pages[:max_pages]
            break

    # 2. Tentar continuar a partir de progresso anterior
    items: List[Dict[str, Any]] = []
    errors: List[str] = []
    photo_count = 0
    processed_titles: set[str] = set()
    if resume and RESULT_FILE.exists():
        try:
            previous = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
            if isinstance(previous, dict):
                for it in previous.get("items", []):
                    if it.get("title") and it["title"] not in processed_titles:
                        items.append(it)
                        processed_titles.add(it["title"])
                photo_count = previous.get("photos", photo_count)
                logger.info("Resumido a partir de %s: %d itens já processados", RESULT_FILE, len(items))
        except Exception as exc:
            logger.warning("Não foi possível resumir progresso: %s", exc)

    # 3. Processar cada página
    for idx, (pageid, title) in enumerate(pages, start=1):
        if title in processed_titles:
            logger.info("[%d/%d] Já processado: %s", idx, len(pages), title)
            continue
        logger.info("[%d/%d] A processar: %s", idx, len(pages), title)
        try:
            parse_data = parse_page(title)
            if not parse_data:
                errors.append(f"parse vazio: {title}")
                continue
            item = extract_politician(parse_data)
            if not item:
                errors.append(f"extração vazia: {title}")
                continue
            slug = _slugify(item["title"])
            if download_photos and item.get("image_filename"):
                photo_path = download_photo(item["image_filename"], slug)
                if photo_path:
                    item["photo_path"] = str(photo_path.relative_to(ROOT).as_posix())
                    item["photo_url"] = f"https://pt.wikipedia.org/wiki/{quote(item['title'].replace(' ', '_'))}#/media/File:{quote(item['image_filename'].replace(' ', '_'))}"
                    photo_count += 1
            items.append(item)
            processed_titles.add(title)
        except Exception as exc:
            logger.exception("Erro a processar %s: %s", title, exc)
            errors.append(f"{title}: {exc}")

        if save_every > 0 and idx % save_every == 0:
            _save_progress(items, errors, photo_count)
            logger.info("  -> progresso guardado: %d itens, %d fotos", len(items), photo_count)

    # 4. Guardar JSON final
    _save_progress(items, errors, photo_count)
    logger.info("JSON guardado em %s (%d itens)", RESULT_FILE, len(items))

    # 4. Indexar pessoas
    people = [p for p in (build_people_doc(i) for i in items) if p]
    logger.info("Documentos finance_people: %d", len(people))
    people_result = {"indexed_count": 0, "total": 0}
    if people:
        people_result = index_people(people, merge=True)
        logger.info("Indexação pessoas: %s", people_result)

    # 5. Indexar grafo
    graph_result = index_relations(items)
    logger.info("Indexação grafo: %s", graph_result)

    return {
        "items": len(items),
        "photos": photo_count,
        "people_indexed": people_result.get("indexed_count") or 0,
        "errors": len(errors),
        "graph": graph_result,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Recolha de políticos de Portugal na Wikipédia PT")
    parser.add_argument("--max-pages", type=int, default=None, help="Limite de páginas a processar")
    parser.add_argument("--no-photos", action="store_true", help="Não descarregar fotos")
    parser.add_argument("--categories", nargs="+", default=None, help="Categorias adicionais")
    parser.add_argument("--no-resume", action="store_true", help="Não continuar progresso anterior")
    parser.add_argument("--save-every", type=int, default=20, help="Guardar progresso a cada N páginas")
    args = parser.parse_args()
    cats = args.categories or DEFAULT_CATEGORIES
    summary = collect_wiki_politicos(
        categories=cats,
        max_pages=args.max_pages,
        download_photos=not args.no_photos,
        save_every=args.save_every,
        resume=not args.no_resume,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
