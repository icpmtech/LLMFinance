"""CMS IQ OS — páginas, conteúdos, blog, media, menus e publicação.

O CMS é a oficina do **site** da plataforma: constrói páginas por **blocos**,
escreve **artigos de blog** com taxonomia (categorias e etiquetas), guarda
**media**, reutiliza **conteúdos** (blocos com nome, para não repetir o mesmo
texto em várias páginas), define **menus** e **aparência**, e **publica** —
imediatamente ou agendado.

Tudo vive num único documento JSON (`data/cms/cms.json`) com escrita atómica: o
ficheiro é a fonte de verdade e pode ser versionado. Os binários dos media ficam
em `data/cms/media/`.

Estados de publicação (`status`):

* `rascunho` — só visível na plataforma;
* `agendado` — publica sozinho quando `scheduled_at` chega (ver `_apply_schedule`,
  chamado a cada leitura: não é preciso um processo à parte);
* `publicado` — visível no site público (`/site/...`);
* `arquivado` — fora do site, guardado no arquivo.

Toda a escrita passa por `save_item`/`publish_item`, que registam **revisão**
(histórico com restauro) e **atividade** (auditoria legível).
"""
from __future__ import annotations

import base64
import binascii
import copy
import json
import logging
import re
import threading
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
CMS_DIR = ROOT / "data" / "cms"
CMS_PATH = CMS_DIR / "cms.json"
MEDIA_DIR = CMS_DIR / "media"
CMS_VERSION = 1

# Entidades do CMS: as listas dentro do documento.
ENTITIES: Tuple[str, ...] = ("pages", "posts", "contents", "media", "categories", "templates", "menus")
SINGULAR: Dict[str, str] = {entity: entity.rstrip("s") if entity not in ("media",) else "media" for entity in ENTITIES}
SINGULAR["categories"] = "categoria"

STATUSES: Tuple[str, ...] = ("rascunho", "agendado", "publicado", "arquivado")
STATUS_LABELS: Dict[str, str] = {
    "rascunho": "Rascunho",
    "agendado": "Agendado",
    "publicado": "Publicado",
    "arquivado": "Arquivado",
}
STATUS_STYLE: Dict[str, str] = {
    "rascunho": "slate",
    "agendado": "amber",
    "publicado": "emerald",
    "arquivado": "zinc",
}

# Tipos de bloco que o editor de páginas sabe desenhar (e o site sabe renderizar).
BLOCK_TYPES: List[Dict[str, Any]] = [
    {"id": "hero", "label": "Destaque (hero)", "hint": "Título grande, subtítulo, imagem e botão", "icon": "Sparkles"},
    {"id": "texto", "label": "Texto", "hint": "Parágrafos em Markdown", "icon": "AlignLeft"},
    {"id": "imagem", "label": "Imagem", "hint": "Uma imagem com legenda", "icon": "Image"},
    {"id": "galeria", "label": "Galeria", "hint": "Conjunto de imagens em grelha", "icon": "Images"},
    {"id": "destaques", "label": "Cartões", "hint": "Cartões de destaque em grelha", "icon": "LayoutGrid"},
    {"id": "cta", "label": "Chamada à ação", "hint": "Faixa com botão", "icon": "MousePointerClick"},
    {"id": "faq", "label": "Perguntas frequentes", "hint": "Perguntas e respostas", "icon": "HelpCircle"},
    {"id": "passos", "label": "Passos", "hint": "Sequência numerada", "icon": "ListOrdered"},
    {"id": "tabela", "label": "Tabela", "hint": "Tabela de dados simples", "icon": "Table"},
    {"id": "citacao", "label": "Citação", "hint": "Frase destacada com autor", "icon": "Quote"},
    {"id": "aviso", "label": "Aviso", "hint": "Nota, atenção ou sucesso", "icon": "AlertTriangle"},
    {"id": "codigo", "label": "Código", "hint": "Bloco de código ou comando", "icon": "Code2"},
    {"id": "contactos", "label": "Contactos", "hint": "Email, telefone e morada", "icon": "Phone"},
    {"id": "blog", "label": "Últimos artigos", "hint": "Lista os artigos publicados", "icon": "Newspaper"},
    {"id": "conteudo", "label": "Conteúdo reutilizado", "hint": "Insere um conteúdo guardado no CMS", "icon": "Recycle"},
    {"id": "divisor", "label": "Divisor", "hint": "Linha de separação", "icon": "Minus"},
]
BLOCK_IDS = {block["id"] for block in BLOCK_TYPES}

# Tipos de conteúdo reutilizável («conteúdos»).
CONTENT_KINDS: List[Dict[str, str]] = [
    {"id": "texto", "label": "Texto"},
    {"id": "hero", "label": "Destaque"},
    {"id": "cta", "label": "Chamada à ação"},
    {"id": "faq", "label": "Perguntas frequentes"},
    {"id": "aviso", "label": "Aviso"},
    {"id": "citacao", "label": "Citação"},
    {"id": "tabela", "label": "Tabela"},
    {"id": "contactos", "label": "Contactos"},
    {"id": "rodape", "label": "Rodapé"},
]
CONTENT_KIND_IDS = {kind["id"] for kind in CONTENT_KINDS}

TEMPLATES_KINDS: List[Dict[str, str]] = [
    {"id": "page", "label": "Página"},
    {"id": "post", "label": "Artigo de blog"},
]

MENU_LOCATIONS: List[Dict[str, str]] = [
    {"id": "header", "label": "Cabeçalho"},
    {"id": "footer", "label": "Rodapé"},
]

MAX_MEDIA_BYTES = 12 * 1024 * 1024
MAX_REVISIONS = 30
MAX_ACTIVITY = 400

MIME_EXT: Dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/avif": ".avif",
    "application/pdf": ".pdf",
    "video/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "text/plain": ".txt",
}
EXT_MIME: Dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".avif": "image/avif",
    ".pdf": "application/pdf",
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
    ".txt": "text/plain",
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "site_name": "IQ OS",
    "tagline": "Inteligência financeira e contratual",
    "description": "Plataforma de inteligência financeira: contratos públicos, empresas, mercado e investigação assistida.",
    "base_url": "",
    "language": "pt-PT",
    "home_page_id": "",
    "blog_page_id": "",
    "posts_per_page": 9,
    "theme": "claro",
    "accent": "#0ea5a4",
    "radius": 14,
    "footer_text": "© IQ OS — todos os direitos reservados.",
    "logo_id": None,
    "favicon_id": None,
    "social": {"email": "", "linkedin": "", "x": "", "github": ""},
    "seo": {"title": "", "description": "", "image_id": None, "keywords": []},
    "robots": "index, follow",
    "analytics_id": "",
}

_lock = threading.RLock()
_cache: Optional[Dict[str, Any]] = None
_cache_mtime: Optional[int] = None


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _slug(value: str, fallback: str = "conteudo") -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    text = re.sub(r"-+", "-", text)
    return text[:72] or fallback


def _keywords(value: Any) -> List[str]:
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,\n;]", value) if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def _words(text: str) -> int:
    plain = re.sub(r"[#*`>_\-\[\]()!|]", " ", text or "")
    return len([word for word in re.split(r"\s+", plain) if word.strip()])


def reading_minutes(text: str) -> int:
    """Tempo de leitura estimado (200 palavras por minuto, mínimo 1)."""
    return max(1, round(_words(text) / 200))


def _excerpt(text: str, limit: int = 220) -> str:
    plain = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    plain = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", plain)
    plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain)
    plain = re.sub(r"[#*`>_|]", " ", plain)
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain[:limit]


def _empty_settings() -> Dict[str, Any]:
    return copy.deepcopy(DEFAULT_SETTINGS)


def _empty_store() -> Dict[str, Any]:
    store: Dict[str, Any] = {"version": CMS_VERSION}
    for entity in ENTITIES:
        store[entity] = []
    store["revisions"] = []
    store["activity"] = []
    store["settings"] = _empty_settings()
    store["updated_at"] = _now()
    return store


def _read_store() -> Dict[str, Any]:
    if not CMS_PATH.exists():
        return _empty_store()
    try:
        raw = json.loads(CMS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ficheiro do CMS ilegível (%s); a recomeçar.", exc)
        return _empty_store()
    if not isinstance(raw, dict):
        return _empty_store()
    store = _empty_store()
    for entity in ENTITIES + ("revisions", "activity"):
        value = raw.get(entity)
        if isinstance(value, list):
            store[entity] = [item for item in value if isinstance(item, dict)]
    settings = raw.get("settings")
    if isinstance(settings, dict):
        store["settings"].update({key: value for key, value in settings.items() if value is not None})
    return store


def _write_store(store: Dict[str, Any]) -> None:
    global _cache, _cache_mtime
    store["version"] = CMS_VERSION
    store["updated_at"] = _now()
    CMS_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(store, ensure_ascii=False, indent=2, default=str)
    tmp = CMS_PATH.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(CMS_PATH)
    _cache = store
    _cache_mtime = _file_mtime()


def _file_mtime() -> Optional[int]:
    """Data de alteração do ficheiro (para detetar escritas de outros processos)."""
    try:
        return CMS_PATH.stat().st_mtime_ns
    except OSError:
        return None


def _load() -> Dict[str, Any]:
    """Documento do CMS, com publicação automática dos agendamentos vencidos.

    Se o ficheiro mudou fora deste processo (CLI, testes, edição manual), a
    cópia em memória é descartada — sem isto, a próxima escrita repunha dados
    antigos por cima dos novos.
    """
    global _cache, _cache_mtime
    stamp = _file_mtime()
    if _cache is not None and stamp != _cache_mtime:
        _cache = None
    if _cache is None:
        _cache = _read_store()
        if not _cache["pages"] and not _cache["posts"] and not _cache["templates"]:
            _seed(_cache)
            _write_store(_cache)
        else:
            _cache_mtime = _file_mtime()
    if _apply_schedule(_cache):
        _write_store(_cache)
    return _cache


def _store() -> Dict[str, Any]:
    return _load()


# --------------------------------------------------------------------------
# Revisões e atividade
# --------------------------------------------------------------------------
def _snapshot(store: Dict[str, Any], entity: str, doc: Dict[str, Any], author: str = "", note: str = "") -> None:
    revision = {
        "id": _new_id("rev"),
        "entity": entity,
        "entity_id": doc.get("id") or "",
        "title": doc.get("title") or doc.get("name") or "",
        "snapshot": copy.deepcopy(doc),
        "author": author or doc.get("updated_by") or "",
        "note": note,
        "at": _now(),
    }
    revisions = store["revisions"]
    revisions.insert(0, revision)
    same = [item for item in revisions if item.get("entity") == entity and item.get("entity_id") == revision["entity_id"]]
    for extra in same[MAX_REVISIONS:]:
        revisions.remove(extra)


def _log(store: Dict[str, Any], action: str, entity: str, doc: Dict[str, Any], actor: str = "", detail: str = "") -> None:
    store["activity"].insert(
        0,
        {
            "id": _new_id("act"),
            "at": _now(),
            "action": action,
            "entity": entity,
            "entity_id": doc.get("id") or "",
            "label": doc.get("title") or doc.get("name") or "",
            "actor": actor or "plataforma",
            "detail": detail,
        },
    )
    del store["activity"][MAX_ACTIVITY:]


def activity(limit: int = 40) -> List[Dict[str, Any]]:
    return _load()["activity"][: max(1, min(limit, MAX_ACTIVITY))]


def revisions_of(entity: str, entity_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    _check_entity(entity)
    store = _load()
    items = [rev for rev in store["revisions"] if rev.get("entity") == entity and rev.get("entity_id") == entity_id]
    return [
        {key: value for key, value in item.items() if key != "snapshot"} | {"fields": sorted((item.get("snapshot") or {}).keys())}
        for item in items[:limit]
    ]


def get_revision(revision_id: str) -> Dict[str, Any]:
    store = _load()
    for revision in store["revisions"]:
        if revision.get("id") == revision_id:
            return revision
    raise KeyError(f"Revisão {revision_id} não encontrada.")


def restore_revision(revision_id: str, author: str = "") -> Dict[str, Any]:
    store = _load()
    revision = get_revision(revision_id)
    entity = revision["entity"]
    entity_id = revision["entity_id"]
    current = _find(store, entity, entity_id)
    if current is None:
        raise KeyError(f"{entity}/{entity_id} já não existe.")
    _snapshot(store, entity, current, author, note=f"antes de restaurar {revision_id}")
    restored = copy.deepcopy(revision["snapshot"])
    restored["id"] = entity_id
    restored["updated_at"] = _now()
    restored["updated_by"] = author
    index = store[entity].index(current)
    store[entity][index] = restored
    _after_write(store, entity, restored)
    _log(store, "restaurar", entity, restored, author, f"revisão {revision_id}")
    _write_store(store)
    return restored


# --------------------------------------------------------------------------
# Índices e normalização
# --------------------------------------------------------------------------
def _check_entity(entity: str) -> None:
    if entity not in ENTITIES:
        raise KeyError(f"Entidade desconhecida: {entity}. Válidas: {', '.join(ENTITIES)}.")


def _find(store: Dict[str, Any], entity: str, item_id: str) -> Optional[Dict[str, Any]]:
    _check_entity(entity)
    for item in store[entity]:
        if item.get("id") == item_id:
            return item
    return None


def _unique(store: Dict[str, Any], entity: str, slug: str, ignore_id: Optional[str] = None) -> str:
    taken = {item.get("slug") for item in store[entity] if item.get("id") != ignore_id}
    candidate = slug
    index = 2
    while candidate in taken:
        candidate = f"{slug}-{index}"
        index += 1
    return candidate


def _normalise_blocks(value: Any) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    if not isinstance(value, list):
        return blocks
    for raw in value:
        if not isinstance(raw, dict):
            continue
        block_type = str(raw.get("type") or "texto").strip()
        if block_type not in BLOCK_IDS:
            block_type = "texto"
        data = raw.get("data")
        blocks.append(
            {
                "id": str(raw.get("id") or _new_id("blk")),
                "type": block_type,
                "hidden": bool(raw.get("hidden")),
                "data": copy.deepcopy(data) if isinstance(data, dict) else {},
            }
        )
    return blocks


def _normalise_seo(value: Any) -> Dict[str, Any]:
    seo = value if isinstance(value, dict) else {}
    return {
        "title": str(seo.get("title") or "").strip(),
        "description": str(seo.get("description") or "").strip(),
        "keywords": _keywords(seo.get("keywords")),
        "image_id": seo.get("image_id") or None,
        "noindex": bool(seo.get("noindex")),
    }


def _status(value: Any, fallback: str = "rascunho") -> str:
    status = str(value or fallback).strip().lower()
    return status if status in STATUSES else fallback


def _page_path(store: Dict[str, Any], doc: Dict[str, Any]) -> str:
    """Caminho de uma página: os slugs dos ascendentes + o próprio.

    A página registada em `settings.home_page_id` vive na **raiz** do site
    (`/site`), pelo que o seu slug não entra no caminho.
    """
    home_id = str((store.get("settings") or {}).get("home_page_id") or "")
    parts: List[str] = []
    seen = set()
    current: Optional[Dict[str, Any]] = doc
    while current is not None:
        is_home = bool(home_id) and current.get("id") == home_id
        slug = "" if is_home else str(current.get("slug") or "").strip()
        if slug:
            parts.insert(0, slug)
        parent_id = current.get("parent_id")
        if not parent_id or parent_id in seen:
            break
        seen.add(parent_id)
        current = _find(store, "pages", str(parent_id))
    return "/".join(parts)


def _refresh_page_paths(store: Dict[str, Any]) -> None:
    for page in store["pages"]:
        path = _page_path(store, page)
        if page.get("path") != path:
            page["path"] = path


def _after_write(store: Dict[str, Any], entity: str, doc: Dict[str, Any]) -> None:
    """Ajustes derivados depois de gravar (caminhos das páginas, uso dos conteúdos)."""
    if entity == "pages":
        _refresh_page_paths(store)
        # Uma página pode passar a usar (ou deixar de usar) um conteúdo reutilizável.
        _refresh_content_usage(store)
    if entity == "contents":
        _refresh_content_usage(store)


def _refresh_content_usage(store: Dict[str, Any]) -> None:
    usage: Dict[str, int] = {item.get("id") or "": 0 for item in store["contents"]}
    for page in store["pages"]:
        for block in page.get("blocks") or []:
            if block.get("type") == "conteudo":
                content_id = str((block.get("data") or {}).get("content_id") or "")
                if content_id in usage:
                    usage[content_id] += 1
    for content in store["contents"]:
        content["uses"] = usage.get(content.get("id") or "", 0)


# --------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------
def _summary(entity: str, doc: Dict[str, Any]) -> Dict[str, Any]:
    """Versão leve de um documento para listagens."""
    item = {key: value for key, value in doc.items() if key not in ("blocks", "markdown", "data")}
    # `entity_label` e não `kind`: nos conteúdos e nos media `kind` é um campo real.
    item["entity"] = entity
    item["entity_label"] = "página" if entity == "pages" else "artigo" if entity == "posts" else entity
    if entity == "pages":
        item["blocks_count"] = len(doc.get("blocks") or [])
    if entity == "posts":
        item["reading_minutes"] = doc.get("reading_minutes") or reading_minutes(doc.get("markdown") or "")
        item["markdown_words"] = _words(doc.get("markdown") or "")
        item["has_markdown"] = bool(doc.get("markdown"))
    if entity == "contents":
        item["preview"] = _excerpt(doc.get("body") or "")
    return item


def list_items(
    entity: str,
    status: Optional[str] = None,
    query: Optional[str] = None,
    category_id: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 200,
    with_blocks: bool = True,
) -> Dict[str, Any]:
    """Lista uma entidade, com filtros por estado, pesquisa, categoria e etiqueta."""
    _check_entity(entity)
    store = _load()
    items: List[Dict[str, Any]] = list(store[entity])

    if status and status != "all":
        wanted = {part.strip() for part in status.split(",") if part.strip()}
        items = [item for item in items if str(item.get("status")) in wanted]

    if category_id:
        items = [item for item in items if category_id in (item.get("category_ids") or [])]

    if tag:
        items = [item for item in items if tag in (item.get("tags") or [])]

    if query:
        needle = query.strip().lower()
        def matches(item: Dict[str, Any]) -> bool:
            haystack = " ".join(
                str(item.get(field) or "")
                for field in ("title", "name", "slug", "path", "excerpt", "markdown", "body", "alt", "filename", "description")
            )
            haystack += " " + " ".join(str(tag) for tag in (item.get("tags") or []))
            return needle in haystack.lower()
        items = [item for item in items if matches(item)]

    items.sort(key=lambda item: (str(item.get("updated_at") or item.get("created_at") or "")), reverse=True)
    total = len(items)
    items = items[: max(1, min(limit, 500))]

    if with_blocks:
        payload_items = [copy.deepcopy(item) for item in items]
        # As listagens não levam o corpo dos artigos: quem abre um artigo pede-o
        # por `get_item` (o Markdown de 200 artigos não faz sentido num índice).
        if entity == "posts":
            for item in payload_items:
                item.pop("markdown", None)
        if entity == "pages":
            # O número de blocos é o que a listagem mostra; `_summary` só o conta
            # nas listagens leves.
            for item in payload_items:
                item["blocks_count"] = len(item.get("blocks") or [])
    else:
        payload_items = [_summary(entity, item) for item in items]

    return {"total": total, "count": len(payload_items), "items": payload_items}


def get_item(entity: str, item_id: str) -> Dict[str, Any]:
    _check_entity(entity)
    store = _load()
    doc = _find(store, entity, item_id)
    if doc is None:
        raise KeyError(f"{SINGULAR.get(entity, entity)} {item_id} não encontrado.")
    return copy.deepcopy(doc)


def resolve_page_by_path(path: str, published_only: bool = True) -> Optional[Dict[str, Any]]:
    store = _load()
    wanted = (path or "").strip("/").lower()
    for page in store["pages"]:
        if published_only and page.get("status") != "publicado":
            continue
        if str(page.get("path") or "").lower() == wanted or (not wanted and str(page.get("path") or "").lower() == ""):
            return copy.deepcopy(page)
    return None


def resolve_post_by_slug(slug: str, published_only: bool = True) -> Optional[Dict[str, Any]]:
    store = _load()
    wanted = (slug or "").strip().lower()
    for post in store["posts"]:
        if published_only and post.get("status") != "publicado":
            continue
        if str(post.get("slug") or "").lower() == wanted:
            return copy.deepcopy(post)
    return None


def published_pages() -> List[Dict[str, Any]]:
    store = _load()
    items = [page for page in store["pages"] if page.get("status") == "publicado"]
    items.sort(key=lambda item: (int(item.get("menu_order") or 0), str(item.get("title") or "").lower()))
    return copy.deepcopy(items)


def published_posts(category_id: Optional[str] = None, tag: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    store = _load()
    items = [post for post in store["posts"] if post.get("status") == "publicado"]
    if category_id:
        items = [item for item in items if category_id in (item.get("category_ids") or [])]
    if tag:
        items = [item for item in items if tag in (item.get("tags") or [])]
    items.sort(key=lambda item: str(item.get("published_at") or item.get("created_at") or ""), reverse=True)
    return copy.deepcopy(items[:limit])


def category_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    store = _load()
    for category in store["categories"]:
        if str(category.get("slug") or "").lower() == (slug or "").lower():
            return copy.deepcopy(category)
    return None


def media_url(media_id: Optional[str]) -> str:
    return f"/cms/media/{media_id}/raw" if media_id else ""


# --------------------------------------------------------------------------
# Escrita
# --------------------------------------------------------------------------
def _normalise(entity: str, payload: Dict[str, Any], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Campos conhecidos de cada entidade (o resto é ignorado)."""
    existing = existing or {}
    doc: Dict[str, Any] = copy.deepcopy(existing)

    def pick(field: str, default: Any = None) -> Any:
        return payload[field] if field in payload else existing.get(field, default)

    if entity in ("pages", "posts"):
        title = str(pick("title") or "").strip()
        doc["title"] = title
        doc["slug"] = _slug(str(pick("slug") or title))
        doc["status"] = _status(pick("status"))
        doc["scheduled_at"] = pick("scheduled_at") or None
        doc["updated_by"] = payload.get("updated_by") or existing.get("updated_by") or ""
        doc["seo"] = _normalise_seo(pick("seo"))

    if entity == "pages":
        doc["parent_id"] = pick("parent_id") or None
        doc["template"] = str(pick("template") or "pagina-padrao")
        doc["blocks"] = _normalise_blocks(pick("blocks", []))
        doc["show_in_menu"] = bool(pick("show_in_menu", True))
        doc["menu_order"] = int(pick("menu_order", 0) or 0)
        doc["menu_label"] = str(pick("menu_label") or "")
        doc["excerpt"] = str(pick("excerpt") or "") or _excerpt(_blocks_text(doc["blocks"]))
        doc["path"] = str(existing.get("path") or "")

    if entity == "posts":
        doc["excerpt"] = str(pick("excerpt") or "")
        doc["markdown"] = str(pick("markdown") or "")
        if not doc["excerpt"]:
            doc["excerpt"] = _excerpt(doc["markdown"])
        doc["cover_id"] = pick("cover_id") or None
        doc["category_ids"] = [str(item) for item in (pick("category_ids", []) or []) if item]
        doc["tags"] = _keywords(pick("tags", []))
        doc["author"] = str(pick("author") or existing.get("author") or "")
        doc["featured"] = bool(pick("featured", False))
        doc["blocks"] = _normalise_blocks(pick("blocks", []))
        doc["reading_minutes"] = reading_minutes(doc["markdown"])

    if entity == "contents":
        doc["title"] = str(pick("title") or "").strip()
        kind = str(pick("kind") or "texto").strip()
        doc["kind"] = kind if kind in CONTENT_KIND_IDS else "texto"
        doc["body"] = str(pick("body") or "")
        data = pick("data", {})
        doc["data"] = copy.deepcopy(data) if isinstance(data, dict) else {}
        doc["tags"] = _keywords(pick("tags", []))
        doc["notes"] = str(pick("notes") or "")

    if entity == "categories":
        name = str(pick("name") or "").strip()
        doc["name"] = name
        doc["slug"] = _slug(str(pick("slug") or name), "categoria")
        doc["description"] = str(pick("description") or "")
        doc["parent_id"] = pick("parent_id") or None
        doc["color"] = str(pick("color") or "")

    if entity == "templates":
        name = str(pick("name") or "").strip()
        doc["name"] = name
        doc["kind"] = str(pick("kind") or "page") if str(pick("kind") or "page") in {"page", "post"} else "page"
        doc["description"] = str(pick("description") or "")
        doc["blocks"] = _normalise_blocks(pick("blocks", []))
        doc["builtin"] = bool(existing.get("builtin", False))

    if entity == "media":
        doc["title"] = str(pick("title") or existing.get("title") or "")
        doc["alt"] = str(pick("alt") or "")
        doc["caption"] = str(pick("caption") or "")
        doc["credit"] = str(pick("credit") or "")
        doc["tags"] = _keywords(pick("tags", []))

    if entity == "menus":
        doc["name"] = str(pick("name") or "Menu principal").strip()
        doc["location"] = str(pick("location") or "header")
        if doc["location"] not in {item["id"] for item in MENU_LOCATIONS}:
            doc["location"] = "header"
        doc["items"] = _normalise_menu_items(pick("items", []))

    return doc


def _normalise_menu_items(value: Any, depth: int = 0) -> List[Dict[str, Any]]:
    if not isinstance(value, list) or depth > 2:
        return []
    items: List[Dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()
        href = str(raw.get("href") or "").strip()
        page_id = raw.get("page_id") or None
        if not label and not href and not page_id:
            continue
        item: Dict[str, Any] = {
            "id": str(raw.get("id") or _new_id("mi")),
            "label": label,
            "href": href,
            "page_id": page_id,
            "new_tab": bool(raw.get("new_tab")),
        }
        children = _normalise_menu_items(raw.get("children"), depth + 1)
        if children:
            item["children"] = children
        items.append(item)
    return items


def _blocks_text(blocks: Iterable[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for block in blocks or []:
        data = block.get("data") or {}
        for key in ("title", "subtitle", "text", "body", "markdown", "quote", "text_value"):
            value = data.get(key)
            if isinstance(value, str) and value:
                parts.append(value)
        for item in data.get("items") or []:
            if isinstance(item, dict):
                parts.extend(str(item.get(key) or "") for key in ("title", "text", "question", "answer"))
    return " ".join(parts)


def save_item(entity: str, payload: Dict[str, Any], author: str = "") -> Dict[str, Any]:
    """Cria ou altera um documento do CMS (com revisão e registo de atividade)."""
    _check_entity(entity)
    store = _load()
    item_id = payload.get("id")
    existing = _find(store, entity, str(item_id)) if item_id else None
    if item_id and existing is None:
        raise KeyError(f"{SINGULAR.get(entity, entity)} {item_id} não encontrado.")

    doc = _normalise(entity, {**payload, "updated_by": author or payload.get("updated_by")}, existing)
    if entity in ("pages", "posts") and not doc.get("title"):
        raise ValueError("O título é obrigatório.")
    if entity == "contents" and not doc.get("title"):
        raise ValueError("O nome do conteúdo é obrigatório.")
    if entity == "categories" and not doc.get("name"):
        raise ValueError("O nome da categoria é obrigatório.")
    if entity == "templates" and not doc.get("name"):
        raise ValueError("O nome do modelo é obrigatório.")
    if entity == "menus" and not doc.get("name"):
        raise ValueError("O nome do menu é obrigatório.")

    if entity in ("pages", "posts"):
        ignore = str(existing.get("id")) if existing else None
        doc["slug"] = _unique(store, entity, doc["slug"], ignore_id=ignore)

    if entity == "pages":
        if doc.get("parent_id") and doc.get("id") and str(doc["parent_id"]) == str(doc["id"]):
            raise ValueError("Uma página não pode ser sua própria ascendente.")
        if doc.get("parent_id") and _is_descendant(store, str(doc.get("id") or ""), str(doc["parent_id"])):
            raise ValueError("Não é possível mover uma página para dentro de uma sua descendente.")

    if entity == "categories":
        ignore = str(existing.get("id")) if existing else None
        doc["slug"] = _unique(store, entity, doc["slug"], ignore_id=ignore)

    if existing:
        _snapshot(store, entity, existing, author, note="antes de guardar")
        doc["id"] = existing["id"]
        doc["created_at"] = existing.get("created_at") or _now()
        doc["updated_at"] = _now()
        store[entity][store[entity].index(existing)] = doc
        action = "alterar"
    else:
        doc["id"] = doc.get("id") or _new_id(_id_prefix(entity))
        doc["created_at"] = _now()
        doc["updated_at"] = _now()
        if entity in ("pages", "posts"):
            doc["published_at"] = existing.get("published_at") if existing else None  # type: ignore[union-attr]
            if doc.get("status") == "publicado":
                doc["published_at"] = _now()
        store[entity].insert(0, doc)
        action = "criar"

    _after_write(store, entity, doc)
    _log(store, action, entity, doc, author)
    _write_store(store)
    return copy.deepcopy(doc)


def _id_prefix(entity: str) -> str:
    return {
        "pages": "pag",
        "posts": "post",
        "contents": "ctd",
        "media": "med",
        "categories": "cat",
        "templates": "tpl",
        "menus": "menu",
    }.get(entity, "item")


def _is_descendant(store: Dict[str, Any], page_id: str, candidate_parent: str) -> bool:
    """Verdadeiro se `candidate_parent` estiver dentro da subárvore de `page_id`."""
    if not page_id or not candidate_parent:
        return False
    stack = [candidate_parent]
    seen = set()
    while stack:
        current = stack.pop()
        if current == page_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        parent = _find(store, "pages", current)
        if parent and parent.get("parent_id"):
            stack.append(str(parent["parent_id"]))
    return False


def delete_item(entity: str, item_id: str, author: str = "") -> Dict[str, Any]:
    _check_entity(entity)
    store = _load()
    doc = _find(store, entity, item_id)
    if doc is None:
        raise KeyError(f"{SINGULAR.get(entity, entity)} {item_id} não encontrado.")
    _snapshot(store, entity, doc, author, note="antes de apagar")
    store[entity].remove(doc)
    if entity == "pages":
        for page in store["pages"]:
            if page.get("parent_id") == item_id:
                page["parent_id"] = None
        _refresh_page_paths(store)
    if entity == "categories":
        for post in store["posts"]:
            if item_id in (post.get("category_ids") or []):
                post["category_ids"] = [value for value in post["category_ids"] if value != item_id]
    if entity == "media":
        target = _media_file(doc)
        try:
            if target.exists():
                target.unlink()
        except OSError as exc:  # pragma: no cover - disco
            logger.warning("Não foi possível apagar o ficheiro do media %s (%s)", item_id, exc)
    if entity == "menus":
        pass
    settings = store["settings"]
    for key in ("home_page_id", "blog_page_id"):
        if settings.get(key) == item_id:
            settings[key] = ""
    for key in ("logo_id", "favicon_id"):
        if settings.get(key) == item_id:
            settings[key] = None
    if (settings.get("seo") or {}).get("image_id") == item_id:
        settings["seo"]["image_id"] = None
    _refresh_content_usage(store)
    _log(store, "apagar", entity, doc, author)
    _write_store(store)
    return {"deleted": True, "id": item_id}


def duplicate_item(entity: str, item_id: str, author: str = "") -> Dict[str, Any]:
    _check_entity(entity)
    store = _load()
    doc = _find(store, entity, item_id)
    if doc is None:
        raise KeyError(f"{SINGULAR.get(entity, entity)} {item_id} não encontrado.")
    clone = copy.deepcopy(doc)
    clone["id"] = _new_id(_id_prefix(entity))
    clone["created_at"] = _now()
    clone["updated_at"] = _now()
    clone["updated_by"] = author
    if entity in ("pages", "posts"):
        base = str(doc.get("title") or "")
        clone["title"] = f"{base} (cópia)"
        clone["slug"] = _unique(store, entity, _slug(f"{doc.get('slug') or base}-copia"), ignore_id=None)
        clone["status"] = "rascunho"
        clone["published_at"] = None
        clone["scheduled_at"] = None
    if entity == "pages":
        clone["show_in_menu"] = False
        clone["path"] = ""
    if entity in ("categories", "templates", "contents"):
        base = str(doc.get("name") or doc.get("title") or "")
        if entity == "contents":
            clone["title"] = f"{base} (cópia)"
        else:
            clone["name"] = f"{base} (cópia)"
        if entity == "categories":
            clone["slug"] = _unique(store, entity, _slug(f"{doc.get('slug') or base}-copia"), ignore_id=None)
    store[entity].insert(0, clone)
    _after_write(store, entity, clone)
    _log(store, "duplicar", entity, clone, author, f"a partir de {item_id}")
    _write_store(store)
    return copy.deepcopy(clone)


# --------------------------------------------------------------------------
# Publicação
# --------------------------------------------------------------------------
def _apply_schedule(store: Dict[str, Any]) -> bool:
    """Publica tudo o que está agendado e já venceu. Devolve True se mudou algo."""
    now = datetime.now(timezone.utc)
    changed = False
    for entity in ("pages", "posts"):
        for doc in store[entity]:
            if doc.get("status") != "agendado":
                continue
            stamp = doc.get("scheduled_at")
            if not stamp:
                continue
            try:
                when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when <= now:
                doc["status"] = "publicado"
                doc["published_at"] = doc.get("published_at") or _now()
                doc["updated_at"] = _now()
                _log(store, "publicar (agendado)", entity, doc, "agendador")
                changed = True
    if changed:
        _refresh_page_paths(store)
    return changed


def publish_item(entity: str, item_id: str, author: str = "", at: Optional[str] = None) -> Dict[str, Any]:
    """Publica agora, ou agenda para `at` (ISO 8601)."""
    _check_entity(entity)
    if entity not in ("pages", "posts"):
        raise ValueError("Só páginas e artigos têm estado de publicação.")
    store = _load()
    doc = _find(store, entity, item_id)
    if doc is None:
        raise KeyError(f"{SINGULAR.get(entity, entity)} {item_id} não encontrado.")
    _snapshot(store, entity, doc, author, note="antes de publicar")
    if at:
        doc["status"] = "agendado"
        doc["scheduled_at"] = at
        action = "agendar"
    else:
        doc["status"] = "publicado"
        doc["scheduled_at"] = None
        doc["published_at"] = doc.get("published_at") or _now()
        action = "publicar"
    doc["updated_at"] = _now()
    doc["updated_by"] = author
    _refresh_page_paths(store)
    _log(store, action, entity, doc, author, f"para {at}" if at else "")
    _write_store(store)
    return copy.deepcopy(doc)


def unpublish_item(entity: str, item_id: str, author: str = "") -> Dict[str, Any]:
    _check_entity(entity)
    if entity not in ("pages", "posts"):
        raise ValueError("Só páginas e artigos têm estado de publicação.")
    store = _load()
    doc = _find(store, entity, item_id)
    if doc is None:
        raise KeyError(f"{SINGULAR.get(entity, entity)} {item_id} não encontrado.")
    doc["status"] = "rascunho"
    doc["scheduled_at"] = None
    doc["updated_at"] = _now()
    doc["updated_by"] = author
    _log(store, "despublicar", entity, doc, author)
    _write_store(store)
    return copy.deepcopy(doc)


def set_status(entity: str, item_id: str, status: str, author: str = "") -> Dict[str, Any]:
    value = _status(status)
    if value == "publicado":
        return publish_item(entity, item_id, author)
    if value == "agendado":
        store = _load()
        doc = _find(store, entity, item_id)
        if doc is None:
            raise KeyError(f"{SINGULAR.get(entity, entity)} {item_id} não encontrado.")
        return publish_item(entity, item_id, author, at=str(doc.get("scheduled_at") or _now()))
    if value == "arquivado":
        _check_entity(entity)
        store = _load()
        doc = _find(store, entity, item_id)
        if doc is None:
            raise KeyError(f"{SINGULAR.get(entity, entity)} {item_id} não encontrado.")
        doc["status"] = "arquivado"
        doc["updated_at"] = _now()
        _log(store, "arquivar", entity, doc, author)
        _write_store(store)
        return copy.deepcopy(doc)
    return unpublish_item(entity, item_id, author)


# --------------------------------------------------------------------------
# Media
# --------------------------------------------------------------------------
def _media_file(doc: Dict[str, Any]) -> Path:
    extension = str(doc.get("extension") or "")
    return MEDIA_DIR / f"{doc.get('id')}{extension}"


def media_file(item_id: str) -> Tuple[Path, str]:
    doc = get_item("media", item_id)
    path = _media_file(doc)
    if not path.is_file():
        raise KeyError(f"Ficheiro do media {item_id} não encontrado no disco.")
    return path, str(doc.get("mime") or "application/octet-stream")


def save_media(payload: Dict[str, Any], author: str = "") -> Dict[str, Any]:
    """Guarda um ficheiro (imagem, PDF, …) enviado em base64 ou por URL externo."""
    store = _load()
    item_id = payload.get("id")
    existing = _find(store, "media", str(item_id)) if item_id else None
    if item_id and existing is None:
        raise KeyError(f"Media {item_id} não encontrado.")

    data = str(payload.get("data") or "")
    external_url = str(payload.get("url") or "").strip()
    doc: Dict[str, Any] = copy.deepcopy(existing) if existing else {}

    if data:
        if "," in data[:80] and data.strip().startswith("data:"):
            header, _, data = data.partition(",")
            if not payload.get("mime"):
                payload["mime"] = header[5:].split(";")[0]
        try:
            blob = base64.b64decode(data)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"Conteúdo base64 inválido: {exc}") from exc
        if len(blob) > MAX_MEDIA_BYTES:
            raise ValueError(f"Ficheiro demasiado grande (máximo {MAX_MEDIA_BYTES // (1024 * 1024)} MB).")
        filename = str(payload.get("filename") or existing.get("filename") if existing else payload.get("filename") or "ficheiro")
        mime = str(payload.get("mime") or (existing or {}).get("mime") or EXT_MIME.get(Path(filename).suffix.lower(), ""))
        extension = MIME_EXT.get(mime) or Path(filename).suffix.lower() or ".bin"
        media_id = (existing or {}).get("id") or _new_id("med")
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        target = MEDIA_DIR / f"{media_id}{extension}"
        target.write_bytes(blob)
        doc.update(
            {
                "id": media_id,
                "filename": Path(filename).name,
                "mime": mime or "application/octet-stream",
                "extension": extension,
                "size": len(blob),
                "storage": "ficheiro",
                "url": f"/cms/media/{media_id}/raw",
            }
        )
    elif external_url:
        doc.update(
            {
                "id": (existing or {}).get("id") or _new_id("med"),
                "filename": Path(external_url.split("?")[0]).name or external_url,
                "mime": str(payload.get("mime") or "image/*"),
                "extension": "",
                "size": 0,
                "storage": "externo",
                "url": external_url,
            }
        )
    else:
        raise ValueError("É preciso enviar o ficheiro (`data` em base64) ou um `url` externo.")

    doc["title"] = str(payload.get("title") or doc.get("title") or doc.get("filename") or "")
    doc["alt"] = str(payload.get("alt") or doc.get("alt") or "")
    doc["caption"] = str(payload.get("caption") or doc.get("caption") or "")
    doc["credit"] = str(payload.get("credit") or doc.get("credit") or "")
    doc["tags"] = _keywords(payload.get("tags") if "tags" in payload else doc.get("tags") or [])
    doc["kind"] = "imagem" if str(doc.get("mime") or "").startswith("image/") else "documento"
    doc["updated_at"] = _now()
    doc["updated_by"] = author
    if existing:
        doc["created_at"] = existing.get("created_at") or _now()
        store["media"][store["media"].index(existing)] = doc
        action = "alterar"
    else:
        doc["created_at"] = _now()
        store["media"].insert(0, doc)
        action = "carregar"
    _log(store, action, "media", doc, author)
    _write_store(store)
    return copy.deepcopy(doc)


def media_usage(media_id: str) -> List[Dict[str, str]]:
    """Onde é que este media é usado (páginas, artigos e definições)."""
    store = _load()
    usage: List[Dict[str, str]] = []
    for page in store["pages"]:
        for block in page.get("blocks") or []:
            data = block.get("data") or {}
            if data.get("media_id") == media_id or media_id in (data.get("media_ids") or []):
                usage.append({"entity": "pages", "id": page["id"], "title": page.get("title") or "", "where": "bloco"})
                break
        if page.get("seo", {}).get("image_id") == media_id:
            usage.append({"entity": "pages", "id": page["id"], "title": page.get("title") or "", "where": "SEO"})
    for post in store["posts"]:
        if post.get("cover_id") == media_id or post.get("seo", {}).get("image_id") == media_id:
            usage.append({"entity": "posts", "id": post["id"], "title": post.get("title") or "", "where": "capa/SEO"})
    if (store["settings"].get("seo") or {}).get("image_id") == media_id:
        usage.append({"entity": "settings", "id": "settings", "title": "Definições do site", "where": "imagem"})
    return usage


# --------------------------------------------------------------------------
# Menus, aparência e catálogo
# --------------------------------------------------------------------------
def get_settings() -> Dict[str, Any]:
    store = _load()
    settings = copy.deepcopy(store["settings"])
    for key, value in DEFAULT_SETTINGS.items():
        settings.setdefault(key, copy.deepcopy(value))
    return settings


def save_settings(payload: Dict[str, Any], author: str = "") -> Dict[str, Any]:
    store = _load()
    settings = store["settings"]
    for key in DEFAULT_SETTINGS:
        if key not in payload:
            continue
        value = payload[key]
        if value is None:
            continue
        settings[key] = copy.deepcopy(value)
    settings["posts_per_page"] = max(1, min(int(settings.get("posts_per_page") or 9), 48))
    settings["language"] = str(settings.get("language") or "pt-PT")
    settings["theme"] = str(settings.get("theme") or "claro")
    settings["accent"] = str(settings.get("accent") or DEFAULT_SETTINGS["accent"])
    settings["radius"] = max(0, min(int(settings.get("radius") or 14), 32))
    settings["robots"] = str(settings.get("robots") or "index, follow")
    if not isinstance(settings.get("social"), dict):
        settings["social"] = copy.deepcopy(DEFAULT_SETTINGS["social"])
    if not isinstance(settings.get("seo"), dict):
        settings["seo"] = copy.deepcopy(DEFAULT_SETTINGS["seo"])
    settings["seo"]["keywords"] = _keywords((settings.get("seo") or {}).get("keywords"))
    settings["updated_at"] = _now()
    settings["updated_by"] = author
    # A página inicial vive na raiz: mudar a escolha muda os caminhos públicos.
    _refresh_page_paths(store)
    _log(store, "alterar", "settings", {"id": "settings", "title": "Definições do site"}, author)
    _write_store(store)
    return get_settings()


def list_menus() -> List[Dict[str, Any]]:
    """Menus guardados (cabeçalho, rodapé, …), tal como estão no documento."""
    return copy.deepcopy(_load()["menus"])


def get_menu(menu_id: str) -> Dict[str, Any]:
    """Um menu pelo identificador."""
    store = _load()
    for menu in store["menus"]:
        if menu.get("id") == menu_id:
            return copy.deepcopy(menu)
    raise KeyError(f"Menu {menu_id} não encontrado.")


def menu_for(location: str = "header") -> Dict[str, Any]:
    """Menu de um local (`header`/`footer`), resolvido: as páginas viram links."""
    store = _load()
    menus = [menu for menu in store["menus"] if menu.get("location") == location]
    pages_by_id = {page.get("id"): page for page in store["pages"]}
    if menus:
        menu = copy.deepcopy(menus[0])
    else:
        menu = {
            "id": f"menu-{location}",
            "name": "Menu principal" if location == "header" else "Menu de rodapé",
            "location": location,
            "items": _default_menu_items(store, location),
        }
    resolved: List[Dict[str, Any]] = []

    def walk(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for item in items or []:
            page = pages_by_id.get(item.get("page_id"))
            if page and page.get("status") != "publicado":
                continue
            href = item.get("href") or (f"/site/{page.get('path')}" if page else "")
            label = item.get("label") or (page.get("menu_label") or page.get("title") if page else "")
            if not label or not href:
                continue
            out.append(
                {
                    "label": label,
                    "href": href,
                    "new_tab": bool(item.get("new_tab")),
                    "page_id": item.get("page_id"),
                    "children": walk(item.get("children") or []),
                }
            )
        return out

    menu["items"] = walk(menu.get("items") or [])
    return menu


def _default_menu_items(store: Dict[str, Any], location: str) -> List[Dict[str, Any]]:
    if location == "footer":
        return [
            {"id": _new_id("mi"), "label": "Blog", "href": "/site/blog", "page_id": None, "new_tab": False},
        ]
    items: List[Dict[str, Any]] = []
    pages = sorted(
        [page for page in store["pages"] if page.get("status") == "publicado" and page.get("show_in_menu")],
        key=lambda item: (int(item.get("menu_order") or 0), str(item.get("title") or "").lower()),
    )
    for page in pages[:6]:
        items.append(
            {
                "id": _new_id("mi"),
                "label": page.get("menu_label") or page.get("title") or "",
                "href": "",
                "page_id": page.get("id"),
                "new_tab": False,
            }
        )
    # O blog só entra uma vez: a página «Blog» (se existir e estiver no menu) já
    # traz o seu próprio link.
    blog_page_id = (store.get("settings") or {}).get("blog_page_id")
    if not any(item.get("page_id") == blog_page_id for item in items):
        items.append({"id": _new_id("mi"), "label": "Blog", "href": "/site/blog", "page_id": None, "new_tab": False})
    return items


def page_tree(published_only: bool = False) -> List[Dict[str, Any]]:
    """Árvore de páginas (ascendentes → descendentes)."""
    store = _load()
    pages = [
        copy.deepcopy(page)
        for page in store["pages"]
        if not published_only or page.get("status") == "publicado"
    ]
    by_id = {page.get("id"): page for page in pages}
    for page in pages:
        page["children"] = []
    roots: List[Dict[str, Any]] = []
    for page in pages:
        parent = by_id.get(page.get("parent_id"))
        if parent is not None and parent is not page:
            parent["children"].append(page)
        else:
            roots.append(page)

    def sort(nodes: List[Dict[str, Any]]) -> None:
        nodes.sort(key=lambda item: (int(item.get("menu_order") or 0), str(item.get("title") or "").lower()))
        for node in nodes:
            sort(node["children"])

    sort(roots)
    return roots


def taxonomy() -> Dict[str, Any]:
    """Categorias e etiquetas com contagem de artigos publicados."""
    store = _load()
    published = [post for post in store["posts"] if post.get("status") == "publicado"]
    categories = []
    for category in sorted(store["categories"], key=lambda item: str(item.get("name") or "").lower()):
        count = len([post for post in published if category.get("id") in (post.get("category_ids") or [])])
        categories.append({**copy.deepcopy(category), "posts": count})
    tags: Dict[str, int] = {}
    for post in published:
        for tag in post.get("tags") or []:
            tags[tag] = tags.get(tag, 0) + 1
    return {
        "categories": categories,
        "tags": [{"tag": tag, "posts": count} for tag, count in sorted(tags.items(), key=lambda item: (-item[1], item[0]))],
    }


def catalogue() -> Dict[str, Any]:
    """Tudo o que o frontend precisa para desenhar o editor."""
    store = _load()
    settings = get_settings()
    return {
        "block_types": BLOCK_TYPES,
        "content_kinds": CONTENT_KINDS,
        "template_kinds": TEMPLATES_KINDS,
        "menu_locations": MENU_LOCATIONS,
        "statuses": [{"id": item, "label": STATUS_LABELS[item], "style": STATUS_STYLE[item]} for item in STATUSES],
        "entities": list(ENTITIES),
        "pages_index": [
            {"id": page.get("id"), "title": page.get("title"), "path": page.get("path"), "status": page.get("status"), "parent_id": page.get("parent_id")}
            for page in store["pages"]
        ],
        "categories_index": [
            {"id": category.get("id"), "name": category.get("name"), "slug": category.get("slug")}
            for category in sorted(store["categories"], key=lambda item: str(item.get("name") or "").lower())
        ],
        "media_index": [
            {
                "id": media.get("id"),
                "title": media.get("title") or media.get("filename"),
                "url": media.get("url"),
                "kind": media.get("kind"),
                "mime": media.get("mime"),
                "size": media.get("size"),
                "storage": media.get("storage"),
            }
            for media in store["media"]
        ],
        "contents_index": [
            {"id": content.get("id"), "title": content.get("title"), "kind": content.get("kind")}
            for content in store["contents"]
        ],
        "templates_index": [
            {"id": template.get("id"), "name": template.get("name"), "kind": template.get("kind"), "builtin": template.get("builtin")}
            for template in store["templates"]
        ],
        "blog_url": "/site/blog",
        "site_url": "/site",
        "home_page_id": settings.get("home_page_id") or "",
        "blog_page_id": settings.get("blog_page_id") or "",
    }


def overview() -> Dict[str, Any]:
    """Panorama do CMS: contagens, publicações recentes e atividade."""
    store = _load()

    def counts(entity: str) -> Dict[str, int]:
        by_status: Dict[str, int] = {status: 0 for status in STATUSES}
        for item in store[entity]:
            status = str(item.get("status") or "rascunho")
            if status in by_status:
                by_status[status] += 1
        return by_status

    pages = counts("pages")
    posts = counts("posts")
    published_pages = [page for page in store["pages"] if page.get("status") == "publicado"]
    published_posts = [post for post in store["posts"] if post.get("status") == "publicado"]
    scheduled = [
        {
            "id": item.get("id"),
            "entity": "pages" if entity == "pages" else "posts",
            "title": item.get("title"),
            "slug": item.get("slug"),
            "at": item.get("scheduled_at"),
        }
        for entity in ("pages", "posts")
        for item in store[entity]
        if item.get("status") == "agendado"
    ]
    scheduled.sort(key=lambda item: str(item.get("at") or ""))
    recent = sorted(
        [
            {"id": page.get("id"), "entity": "pages", "title": page.get("title"), "slug": page.get("slug"), "at": page.get("updated_at"), "status": page.get("status"), "by": page.get("updated_by")}
            for page in store["pages"]
        ]
        + [
            {"id": post.get("id"), "entity": "posts", "title": post.get("title"), "slug": post.get("slug"), "at": post.get("updated_at"), "status": post.get("status"), "by": post.get("updated_by")}
            for post in store["posts"]
        ],
        key=lambda item: str(item.get("at") or ""),
        reverse=True,
    )[:8]
    words = sum(_words(post.get("markdown") or "") for post in store["posts"])
    return {
        "pages": {"total": len(store["pages"]), "by_status": pages, "published": pages["publicado"]},
        "posts": {"total": len(store["posts"]), "by_status": posts, "published": posts["publicado"]},
        "contents": len(store["contents"]),
        "media": {"total": len(store["media"]), "bytes": sum(int(item.get("size") or 0) for item in store["media"])},
        "categories": len(store["categories"]),
        "templates": len(store["templates"]),
        "words": words,
        "scheduled": scheduled,
        "recent": recent,
        "activity": store["activity"][:12],
        "site": {
            "home": next((page.get("path") for page in published_pages if page.get("id") == store["settings"].get("home_page_id")), ""),
            "pages": len(published_pages),
            "posts": len(published_posts),
            "settings": get_settings(),
        },
    }


def search(query: str, limit: int = 30) -> Dict[str, Any]:
    """Pesquisa global no CMS (páginas, artigos, conteúdos, media e categorias)."""
    needle = (query or "").strip().lower()
    if not needle:
        return {"query": query, "total": 0, "items": []}
    store = _load()
    hits: List[Dict[str, Any]] = []
    for entity in ("pages", "posts", "contents", "media", "categories", "templates"):
        for doc in store[entity]:
            haystack = " ".join(
                str(doc.get(field) or "")
                for field in ("title", "name", "slug", "path", "excerpt", "markdown", "body", "description", "alt", "filename", "notes")
            ).lower()
            if needle not in haystack:
                continue
            hits.append(
                {
                    "entity": entity,
                    "id": doc.get("id"),
                    "title": doc.get("title") or doc.get("name") or "",
                    "subtitle": doc.get("path") or doc.get("slug") or doc.get("filename") or "",
                    "status": doc.get("status") or "",
                    "updated_at": doc.get("updated_at") or doc.get("created_at") or "",
                }
            )
    hits.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return {"query": query, "total": len(hits), "items": hits[:limit]}


# --------------------------------------------------------------------------
# Sementes (primeiro arranque)
# --------------------------------------------------------------------------
def _seed(store: Dict[str, Any]) -> None:
    """Conteúdo inicial para o CMS não aparecer vazio."""
    now = _now()
    home_id = "pag_inicio"
    sobre_id = "pag_sobre"
    blog_id = "pag_blog"
    store["pages"] = [
        {
            "id": home_id,
            "title": "Início",
            "slug": "inicio",
            "path": "",
            "parent_id": None,
            "template": "pagina-inicial",
            "status": "publicado",
            "published_at": now,
            "scheduled_at": None,
            "show_in_menu": True,
            "menu_order": 1,
            "menu_label": "Início",
            "excerpt": "O IQ OS junta contratos públicos, empresas, mercado e investigação assistida numa só plataforma.",
            "blocks": [
                {
                    "id": "blk_seed_hero",
                    "type": "hero",
                    "data": {
                        "title": "Inteligência financeira e contratual, num só sítio",
                        "subtitle": "Contratos públicos de Portugal e Espanha, cadastro de empresas, mercado e investigação com evidências citadas.",
                        "cta_label": "Explorar o blog",
                        "cta_href": "/site/blog",
                        "align": "centro",
                    },
                },
                {
                    "id": "blk_seed_texto",
                    "type": "texto",
                    "data": {
                        "title": "O que é o IQ OS",
                        "markdown": "O **IQ OS** reúne recolha de dados abertos, ontologia de entidades e assistentes de investigação.\n\nTudo o que se escreve aqui é publicado por blocos: páginas, artigos de blog, media e menus — com rascunho, agendamento e histórico de revisões.",
                    },
                },
                {
                    "id": "blk_seed_cards",
                    "type": "destaques",
                    "data": {
                        "title": "Por onde começar",
                        "items": [
                            {"title": "Contratos públicos", "text": "Pesquise adjudicantes, adjudicatários e valores por região."},
                            {"title": "Empresas", "text": "Cadastro, relações societárias e sinais de risco."},
                            {"title": "Investigação", "text": "Perguntas com resposta citada e grafo de evidências."},
                        ],
                    },
                },
                {"id": "blk_seed_blog", "type": "blog", "data": {"title": "Últimos artigos", "limit": 3}},
            ],
            "seo": {"title": "IQ OS — inteligência financeira e contratual", "description": "Contratos públicos, empresas, mercado e investigação assistida.", "keywords": [], "image_id": None, "noindex": False},
            "created_at": now,
            "updated_at": now,
            "updated_by": "sistema",
        },
        {
            "id": sobre_id,
            "title": "Sobre",
            "slug": "sobre",
            "path": "sobre",
            "parent_id": None,
            "template": "pagina-padrao",
            "status": "publicado",
            "published_at": now,
            "scheduled_at": None,
            "show_in_menu": True,
            "menu_order": 2,
            "menu_label": "",
            "excerpt": "Como trabalhamos os dados abertos e o que pode esperar da plataforma.",
            "blocks": [
                {"id": "blk_seed_sobre_hero", "type": "hero", "data": {"title": "Sobre o IQ OS", "subtitle": "Dados abertos, ontologia e assistentes de investigação.", "align": "esquerda"}},
                {
                    "id": "blk_seed_sobre_texto",
                    "type": "texto",
                    "data": {
                        "markdown": "## Princípios\n\n- **Fonte aberta** — todo o dado bruto vem de fontes públicas.\n- **Rasto** — cada resposta cita a evidência que a sustenta.\n- **Reutilização** — o mesmo conteúdo serve a plataforma, o site e o blog.",
                    },
                },
                {"id": "blk_seed_sobre_cta", "type": "cta", "data": {"title": "Tem uma pergunta?", "text": "Use o Hermes para investigar com evidências citadas.", "button_label": "Abrir o Hermes", "button_href": "/hermes"}},
            ],
            "seo": {"title": "Sobre o IQ OS", "description": "Princípios e métodos da plataforma.", "keywords": [], "image_id": None, "noindex": False},
            "created_at": now,
            "updated_at": now,
            "updated_by": "sistema",
        },
        {
            "id": blog_id,
            "title": "Blog",
            "slug": "blog",
            "path": "blog",
            "parent_id": None,
            "template": "lista-de-artigos",
            "status": "publicado",
            "published_at": now,
            "scheduled_at": None,
            "show_in_menu": True,
            "menu_order": 3,
            "menu_label": "Blog",
            "excerpt": "Análises, notas de método e novidades da plataforma.",
            "blocks": [
                {"id": "blk_seed_blog_hero", "type": "hero", "data": {"title": "Blog", "subtitle": "Análises, método e novidades.", "align": "esquerda"}},
                {"id": "blk_seed_blog_list", "type": "blog", "data": {"title": "", "limit": 12}},
            ],
            "seo": {"title": "Blog", "description": "Análises, notas de método e novidades da plataforma.", "keywords": [], "image_id": None, "noindex": False},
            "created_at": now,
            "updated_at": now,
            "updated_by": "sistema",
        },
    ]

    analytics_id = "cat_analises"
    market_id = "cat_mercado"
    product_id = "cat_produto"
    store["categories"] = [
        {"id": analytics_id, "name": "Análises", "slug": "analises", "description": "Leituras de dados e tendências.", "parent_id": None, "color": "#0ea5a4", "created_at": now, "updated_at": now},
        {"id": market_id, "name": "Mercado", "slug": "mercado", "description": "Empresas, setores e mercado.", "parent_id": None, "color": "#6366f1", "created_at": now, "updated_at": now},
        {"id": product_id, "name": "Produto", "slug": "produto", "description": "Novidades da plataforma.", "parent_id": None, "color": "#f59e0b", "created_at": now, "updated_at": now},
    ]

    store["posts"] = [
        {
            "id": "post_bemvindo",
            "title": "Bem-vindo ao blog do IQ OS",
            "slug": "bem-vindo-ao-blog",
            "excerpt": "O que vai encontrar aqui: análises de contratos públicos, notas sobre empresas e o método por detrás dos números.",
            "markdown": (
                "## Porquê um blog\n\n"
                "Os dados só valem quando se sabe **de onde vêm** e **o que dizem**. Aqui escrevemos as duas coisas: a leitura dos números e o método que a sustenta.\n\n"
                "### O que vai encontrar\n\n"
                "1. **Análises** de contratos públicos em Portugal e Espanha.\n"
                "2. **Notas de mercado** sobre empresas, setores e concentração.\n"
                "3. **Novidades do produto**, sempre com exemplos reais.\n\n"
                "> Cada artigo pode citar contratos, empresas e dossiês da plataforma.\n\n"
                "Se procura um tema, comece pela pesquisa 360."
            ),
            "blocks": [],
            "cover_id": None,
            "category_ids": [analytics_id],
            "tags": ["contratos públicos", "método"],
            "author": "Equipa IQ OS",
            "status": "publicado",
            "published_at": now,
            "scheduled_at": None,
            "featured": True,
            "reading_minutes": 3,
            "seo": {"title": "", "description": "", "keywords": [], "image_id": None, "noindex": False},
            "created_at": now,
            "updated_at": now,
            "updated_by": "sistema",
        },
        {
            "id": "post_contratos_2026",
            "title": "Contratos públicos em 2026: o que os dados mostram",
            "slug": "contratos-publicos-2026",
            "excerpt": "Volume, valor e concentração nos contratos já publicados este ano — e as três leituras que interessam.",
            "markdown": (
                "Os dados de 2026 ainda estão a fechar, mas já deixam ver três padrões.\n\n"
                "## 1. O valor concentra-se em poucos adjudicatários\n\n"
                "A cauda longa é grande, mas o valor não: os primeiros adjudicatários levam a maior fatia.\n\n"
                "## 2. O procedimento explica o preço\n\n"
                "Ajuste direto e concurso público não competem em pé de igualdade.\n\n"
                "## 3. O território pesa\n\n"
                "Distrito de execução continua a ser a melhor chave para ler o mercado local.\n\n"
                "_Em preparação: a análise por CPV._"
            ),
            "blocks": [],
            "cover_id": None,
            "category_ids": [analytics_id, market_id],
            "tags": ["contratos públicos", "2026", "mercado"],
            "author": "Equipa IQ OS",
            "status": "publicado",
            "published_at": (datetime.now(timezone.utc) - timedelta(days=4)).isoformat(),
            "scheduled_at": None,
            "featured": False,
            "reading_minutes": 4,
            "seo": {"title": "", "description": "", "keywords": [], "image_id": None, "noindex": False},
            "created_at": now,
            "updated_at": now,
            "updated_by": "sistema",
        },
    ]

    store["templates"] = [
        {
            "id": "tpl_pagina_padrao",
            "name": "Página padrão",
            "kind": "page",
            "description": "Hero, texto, cartões e chamada à ação.",
            "builtin": True,
            "blocks": [
                {"id": "t1", "type": "hero", "data": {"title": "Título da página", "subtitle": "Uma frase que diz o essencial.", "align": "esquerda"}},
                {"id": "t2", "type": "texto", "data": {"title": "Secção", "markdown": "Escreva aqui o corpo da página em Markdown."}},
                {"id": "t3", "type": "cta", "data": {"title": "Próximo passo", "text": "Explique o que o leitor deve fazer.", "button_label": "Saber mais", "button_href": "#"}},
            ],
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "tpl_landing",
            "name": "Landing de captação",
            "kind": "page",
            "description": "Hero, cartões de valor, prova e chamada à ação.",
            "builtin": True,
            "blocks": [
                {"id": "l1", "type": "hero", "data": {"title": "Uma promessa clara", "subtitle": "Para quem é e o que resolve.", "cta_label": "Começar", "cta_href": "#", "align": "centro"}},
                {"id": "l2", "type": "destaques", "data": {"title": "Porque é diferente", "items": [{"title": "Ponto 1", "text": "Explicação curta."}, {"title": "Ponto 2", "text": "Explicação curta."}, {"title": "Ponto 3", "text": "Explicação curta."}]}},
                {"id": "l3", "type": "faq", "data": {"title": "Perguntas frequentes", "items": [{"question": "Pergunta?", "answer": "Resposta."}]}},
                {"id": "l4", "type": "cta", "data": {"title": "Pronto para começar?", "text": "", "button_label": "Falar connosco", "button_href": "#"}},
            ],
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "tpl_artigo",
            "name": "Artigo de blog",
            "kind": "post",
            "description": "Estrutura de um artigo com introdução, secções e fecho.",
            "builtin": True,
            "blocks": [],
            "created_at": now,
            "updated_at": now,
        },
    ]

    store["contents"] = [
        {
            "id": "ctd_rodape",
            "title": "Rodapé institucional",
            "kind": "rodape",
            "body": "**IQ OS** — inteligência financeira e contratual.\n\nDados de fontes abertas, com rasto e evidência.",
            "data": {},
            "tags": ["institucional"],
            "notes": "Usado nos rodapés das páginas.",
            "uses": 0,
            "created_at": now,
            "updated_at": now,
        },
        {
            "id": "ctd_contactos",
            "title": "Contactos gerais",
            "kind": "contactos",
            "body": "Fale connosco para propostas, dados ou imprensa.",
            "data": {"email": "geral@iqos.pt", "phone": "", "address": ""},
            "tags": ["institucional"],
            "notes": "",
            "uses": 0,
            "created_at": now,
            "updated_at": now,
        },
    ]

    store["settings"].update(
        {
            "home_page_id": home_id,
            "blog_page_id": blog_id,
            "site_name": "IQ OS",
            "tagline": "Inteligência financeira e contratual",
        }
    )

    store["menus"] = [
        {"id": "menu_header", "name": "Menu principal", "location": "header", "items": _default_menu_items(store, "header"), "created_at": now, "updated_at": now},
        {"id": "menu_footer", "name": "Menu de rodapé", "location": "footer", "items": _default_menu_items(store, "footer"), "created_at": now, "updated_at": now},
    ]

    store["activity"] = [
        {
            "id": _new_id("act"),
            "at": now,
            "action": "criar",
            "entity": "settings",
            "entity_id": "settings",
            "label": "Site inicial",
            "actor": "sistema",
            "detail": "conteúdo de exemplo do CMS",
        }
    ]


def reset_seed() -> Dict[str, Any]:
    """Repõe o conteúdo de exemplo (usado nos testes)."""
    global _cache
    with _lock:
        store = _empty_store()
        _seed(store)
        _refresh_page_paths(store)
        _write_store(store)
    return overview()