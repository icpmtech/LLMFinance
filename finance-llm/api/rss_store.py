"""RSS IQ OS — feeds, pastas, artigos, guardados e digest.

O leitor de RSS é o «leitor de jornais» da plataforma: junta **fontes** (feeds
RSS/Atom) agrupadas em **pastas**, **recolhe** os artigos (à mão ou por agenda
cron), guarda-os com os estados **lido**, **favorito** e **guardado**, e leva
qualquer artigo para as outras aplicações (Office, sentimento, CRM, RAG) ou
resume-o com IA.

Tudo vive num único documento JSON (`data/rss/rss.json`) com escrita atómica: o
ficheiro é a fonte de verdade e pode ser versionado. Não há binários.

Entidades (listas dentro do documento):

* `folders`  — pastas de feeds (nome, ordem, cor);
* `feeds`    — fontes RSS/Atom (URL, pasta, etiquetas, estado da última recolha);
* `articles` — artigos recolhidos, deduplicados por `guid`/URL, com `read`,
  `favorite`, `saved` e o `digest` quando a IA é pedida.

A recolha em si (HTTP + `feedparser` + OPML) vive em `api/rss_feed.py`; a
orquestração (recolher, resumir, integrar) em `api/rss_service.py`.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
RSS_DIR = ROOT / "data" / "rss"
RSS_PATH = RSS_DIR / "rss.json"
RSS_VERSION = 1

MAX_ACTIVITY = 300
MAX_SUMMARY_CHARS = 4000
MAX_CONTENT_CHARS = 200_000
MAX_DIGEST_CHARS = 6000
MAX_RULES = 40

FOLDER_COLORS = ("teal", "sky", "violet", "amber", "rose", "emerald", "indigo", "slate")

# Ações que uma regra automática pode aplicar a um artigo novo.
RULE_ACTIONS: Tuple[Dict[str, str], ...] = (
    {"id": "saved", "label": "Guardar"},
    {"id": "favorite", "label": "Marcar como favorito"},
    {"id": "read", "label": "Marcar como lido"},
)
RULE_ACTION_IDS = {action["id"] for action in RULE_ACTIONS}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "auto_fetch": True,
    "cron": "0 * * * *",
    "timezone": "Europe/Lisbon",
    "max_articles_per_feed": 300,
    "retention_days": 0,
    "mark_read_on_open": True,
    "default_tags": [],
    "rules": [],
}

# Estados possíveis da última recolha de uma fonte.
STATUS_LABELS: Dict[str, str] = {
    "nunca": "Nunca recolhido",
    "ok": "Recolha bem-sucedida",
    "sem_novidades": "Sem artigos novos",
    "nao_modificado": "Sem alterações (304)",
    "erro": "Erro na recolha",
}
STATUS_TONES: Dict[str, str] = {
    "nunca": "slate",
    "ok": "emerald",
    "sem_novidades": "sky",
    "nao_modificado": "sky",
    "erro": "rose",
}

_lock = threading.RLock()
_cache: Optional[Dict[str, Any]] = None
_cache_mtime: Optional[int] = None


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def now() -> str:
    """Data/hora atual em ISO 8601 UTC (a mesma usada no documento)."""
    return _now()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _slug(value: str, fallback: str = "pasta") -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return re.sub(r"-+", "-", text)[:72] or fallback


def _clean_text(value: Any, limit: int = MAX_SUMMARY_CHARS) -> str:
    text = str(value or "")
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&apos;", "'")
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def clean_text(value: Any, limit: int = MAX_SUMMARY_CHARS) -> str:
    """Texto simples a partir de HTML/texto (para resumos, integrações e IA)."""
    return _clean_text(value, limit)


def all_articles() -> List[Dict[str, Any]]:
    """Todos os artigos guardados (cópia, para análises agregadas)."""
    return copy.deepcopy(_store()["articles"])


def _clamp(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, number))


def _opt_str(value: Any) -> Optional[str]:
    """Texto opcional: qualquer coisa que não seja texto é «sem filtro»."""
    return value if isinstance(value, str) and value.strip() else None


def _opt_bool(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _as_list(value: Any) -> List[str]:
    if isinstance(value, str):
        parts = re.split(r"[,\n;]", value)
    elif isinstance(value, (list, tuple, set)):
        parts = [str(item) for item in value]
    else:
        return []
    seen: List[str] = []
    for part in parts:
        text = str(part).strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def _parse_date(value: Any) -> Optional[str]:
    """Converte datas vindas do `feedparser` (ISO ou `*_parsed`) em ISO 8601 UTC."""
    if not value:
        return None
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    if isinstance(value, time.struct_time):
        return datetime(*value[:6], tzinfo=timezone.utc).isoformat()
    return None


def _sort_key(article: Dict[str, Any]) -> str:
    return str(article.get("published_at") or article.get("fetched_at") or "")


def fold_text(value: Any) -> str:
    """Texto para comparações: minúsculas e sem acentos (regras e duplicados)."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in text if not unicodedata.combining(char)).lower()


def _normalise_rules(value: Any) -> List[Dict[str, Any]]:
    """Valida as regras automáticas (termo → ações/etiquetas)."""
    if not isinstance(value, (list, tuple)):
        return []
    rules: List[Dict[str, Any]] = []
    for raw in list(value)[:MAX_RULES]:
        if not isinstance(raw, dict):
            continue
        term = str(raw.get("term") or raw.get("contains") or "").strip()
        if len(term) < 2:
            continue
        actions = [str(action) for action in (raw.get("actions") or []) if str(action) in RULE_ACTION_IDS]
        tags = _as_list(raw.get("tags"))[:6]
        if not actions and not tags:
            continue
        rules.append(
            {
                "id": str(raw.get("id") or _new_id("rule")),
                "term": term[:80],
                "actions": sorted(set(actions)),
                "tags": tags,
                "enabled": bool(raw.get("enabled", True)),
                "hits": _clamp(raw.get("hits"), 0, 1_000_000, 0),
                "created_at": str(raw.get("created_at") or _now()),
            }
        )
    return rules


def _article_matches_rule(article: Dict[str, Any], term: str) -> bool:
    needle = fold_text(term)
    if not needle:
        return False
    haystack = fold_text(
        " ".join(
            [
                str(article.get("title") or ""),
                str(article.get("summary") or ""),
                " ".join(str(value) for value in article.get("categories") or []),
            ]
        )
    )
    return needle in haystack


def _apply_rules_to(article: Dict[str, Any], rules: List[Dict[str, Any]]) -> List[str]:
    """Aplica as regras a um artigo. Devolve as etiquetas/regras que tocaram nele."""
    touched: List[str] = []
    for rule in rules:
        if not rule.get("enabled"):
            continue
        if not _article_matches_rule(article, str(rule.get("term") or "")):
            continue
        rule["hits"] = int(rule.get("hits") or 0) + 1
        touched.append(str(rule.get("term")))
        for action in rule.get("actions") or []:
            if action == "saved":
                article["saved"] = True
            elif action == "favorite":
                article["favorite"] = True
            elif action == "read":
                article["read"] = True
                article["read_at"] = _now()
        for tag in rule.get("tags") or []:
            article.setdefault("tags", [])
            if tag not in article["tags"]:
                article["tags"].append(tag)
    return touched


def _empty_store() -> Dict[str, Any]:
    return {
        "version": RSS_VERSION,
        "folders": [],
        "feeds": [],
        "articles": [],
        "activity": [],
        "settings": copy.deepcopy(DEFAULT_SETTINGS),
        "updated_at": _now(),
    }


# --------------------------------------------------------------------------
# Persistência
# --------------------------------------------------------------------------
def _read_store() -> Dict[str, Any]:
    if not RSS_PATH.exists():
        return _empty_store()
    try:
        raw = json.loads(RSS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ficheiro do RSS ilegível (%s); a recomeçar.", exc)
        return _empty_store()
    if not isinstance(raw, dict):
        return _empty_store()
    store = _empty_store()
    for key in ("folders", "feeds", "articles", "activity"):
        value = raw.get(key)
        if isinstance(value, list):
            store[key] = [item for item in value if isinstance(item, dict)]
    settings = raw.get("settings")
    if isinstance(settings, dict):
        store["settings"].update({key: value for key, value in settings.items() if value is not None})
    return store


def _write_store(store: Dict[str, Any]) -> None:
    global _cache, _cache_mtime
    store["version"] = RSS_VERSION
    store["updated_at"] = _now()
    RSS_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(store, ensure_ascii=False, indent=2, default=str)
    tmp = RSS_PATH.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    # No Windows, o antivírus ou o indexador podem segurar o ficheiro uns
    # milissegundos logo após a criação: tenta-se algumas vezes antes de desistir.
    last: Optional[OSError] = None
    for attempt in range(5):
        try:
            tmp.replace(RSS_PATH)
            break
        except PermissionError as exc:  # pragma: no cover - depende do sistema
            last = exc
            time.sleep(0.08 * (attempt + 1))
    else:  # pragma: no cover - depende do sistema
        raise last if last else OSError(f"Não foi possível gravar {RSS_PATH}.")
    _cache = store
    _cache_mtime = _file_mtime()


def _file_mtime() -> Optional[int]:
    try:
        return RSS_PATH.stat().st_mtime_ns
    except OSError:
        return None


def _load() -> Dict[str, Any]:
    """Documento do leitor, descartando a cópia em memória se o ficheiro mudou.

    Sem isto, uma escrita feita por outro processo (CLI, testes) seria reposta
    pela cópia em memória na escrita seguinte.
    """
    global _cache, _cache_mtime
    stamp = _file_mtime()
    if _cache is not None and stamp != _cache_mtime:
        _cache = None
    if _cache is None:
        _cache = _read_store()
        _cache_mtime = _file_mtime()
    return _cache


def _store() -> Dict[str, Any]:
    return _load()


def reset_store() -> Dict[str, Any]:
    """Repõe o leitor vazio (usado pelos testes)."""
    store = _empty_store()
    _write_store(store)
    return copy.deepcopy(store)


# --------------------------------------------------------------------------
# Atividade
# --------------------------------------------------------------------------
def _log(store: Dict[str, Any], action: str, subject: str, actor: str = "", detail: str = "") -> None:
    store.setdefault("activity", []).insert(
        0,
        {
            "id": _new_id("act"),
            "action": action,
            "subject": subject,
            "actor": actor,
            "detail": detail,
            "at": _now(),
        },
    )
    del store["activity"][MAX_ACTIVITY:]


def activity(limit: int = 40) -> List[Dict[str, Any]]:
    store = _store()
    return copy.deepcopy(store.get("activity", [])[: max(1, min(limit, MAX_ACTIVITY))])


# --------------------------------------------------------------------------
# Pastas
# --------------------------------------------------------------------------
def _folder_view(store: Dict[str, Any], folder: Dict[str, Any]) -> Dict[str, Any]:
    feeds = [feed for feed in store["feeds"] if feed.get("folder_id") == folder["id"]]
    unread = 0
    feed_ids = {feed["id"] for feed in feeds}
    for article in store["articles"]:
        if not article.get("read") and article.get("feed_id") in feed_ids:
            unread += 1
    return {**folder, "feeds": len(feeds), "unread": unread}


def list_folders() -> List[Dict[str, Any]]:
    store = _store()
    folders = [_folder_view(store, folder) for folder in store["folders"]]
    folders.sort(key=lambda item: (int(item.get("order") or 0), str(item.get("name") or "")))
    return folders


def get_folder(folder_id: str) -> Dict[str, Any]:
    store = _store()
    for folder in store["folders"]:
        if folder.get("id") == folder_id:
            return _folder_view(store, folder)
    raise KeyError(f"A pasta «{folder_id}» não existe.")


def save_folder(payload: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
    name = str(payload.get("name") or payload.get("title") or "").strip()
    if not name:
        raise ValueError("A pasta precisa de um nome.")
    folder_id = str(payload.get("id") or "").strip()
    with _lock:
        store = _load()
        existing = next((item for item in store["folders"] if item.get("id") == folder_id), None)
        if folder_id and existing is None:
            raise KeyError(f"A pasta «{folder_id}» não existe.")
        color = str(payload.get("color") or "").strip()
        if color and color not in FOLDER_COLORS:
            color = ""
        body = {
            "id": existing["id"] if existing else _new_id("fold"),
            "name": name,
            "color": color or (existing or {}).get("color") or "teal",
            "order": _clamp(payload.get("order"), 0, 999, int((existing or {}).get("order") or 0)),
            "updated_at": _now(),
        }
        if existing:
            existing.update(body)
            folder = existing
        else:
            body["created_at"] = _now()
            store["folders"].append(body)
            folder = body
        _log(store, "pasta.criada" if existing is None else "pasta.alterada", name, actor)
        _write_store(store)
        return _folder_view(store, folder)


def delete_folder(folder_id: str, actor: str = "") -> Dict[str, Any]:
    with _lock:
        store = _load()
        folder = next((item for item in store["folders"] if item.get("id") == folder_id), None)
        if folder is None:
            raise KeyError(f"A pasta «{folder_id}» não existe.")
        store["folders"] = [item for item in store["folders"] if item.get("id") != folder_id]
        # Os feeds da pasta não se perdem: ficam sem pasta.
        moved = 0
        for feed in store["feeds"]:
            if feed.get("folder_id") == folder_id:
                feed["folder_id"] = None
                feed["updated_at"] = _now()
                moved += 1
        _log(store, "pasta.apagada", str(folder.get("name") or ""), actor, f"{moved} feed(s) sem pasta")
        _write_store(store)
        return {"deleted": True, "id": folder_id, "feeds_moved": moved}


# --------------------------------------------------------------------------
# Feeds
# --------------------------------------------------------------------------
def _feed_view(store: Dict[str, Any], feed: Dict[str, Any], *, with_content: bool = False) -> Dict[str, Any]:
    articles = [article for article in store["articles"] if article.get("feed_id") == feed["id"]]
    unread = sum(1 for article in articles if not article.get("read"))
    view = {
        **feed,
        "articles": len(articles),
        "unread": unread,
        "folder_name": next((item.get("name") for item in store["folders"] if item.get("id") == feed.get("folder_id")), ""),
        "status_label": STATUS_LABELS.get(str(feed.get("last_status") or "nunca"), ""),
        "status_tone": STATUS_TONES.get(str(feed.get("last_status") or "nunca"), "slate"),
    }
    if not with_content:
        view.pop("last_content", None)
    return view


def list_feeds(folder_id: Optional[str] = None, query: Optional[str] = None) -> List[Dict[str, Any]]:
    store = _store()
    feeds = [_feed_view(store, feed) for feed in store["feeds"]]
    folder_filter = _opt_str(folder_id)
    if folder_id is not None:
        wanted = None if folder_filter in ("all", "todas") else ("__root__" if folder_filter == "root" else folder_filter)
        if wanted == "__root__":
            feeds = [feed for feed in feeds if not feed.get("folder_id")]
        elif wanted:
            feeds = [feed for feed in feeds if feed.get("folder_id") == wanted]
    needle = (_opt_str(query) or "").lower()
    if needle:
        feeds = [
            feed
            for feed in feeds
            if needle in str(feed.get("title") or "").lower()
            or needle in str(feed.get("url") or "").lower()
            or any(needle in str(tag).lower() for tag in (feed.get("tags") or []))
        ]
    feeds.sort(key=lambda item: (-int(item.get("unread") or 0), str(item.get("title") or "").lower()))
    return feeds


def get_feed(feed_id: str) -> Dict[str, Any]:
    store = _store()
    for feed in store["feeds"]:
        if feed.get("id") == feed_id:
            return _feed_view(store, feed, with_content=True)
    raise KeyError(f"A fonte «{feed_id}» não existe.")


def find_feed_by_url(url: str) -> Optional[Dict[str, Any]]:
    needle = (url or "").strip().rstrip("/").lower()
    if not needle:
        return None
    store = _store()
    for feed in store["feeds"]:
        if str(feed.get("url") or "").strip().rstrip("/").lower() == needle:
            return _feed_view(store, feed)
    return None


def save_feed(payload: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
    """Cria ou altera uma fonte. `url` é obrigatório nas criações."""
    url = str(payload.get("url") or "").strip()
    feed_id = str(payload.get("id") or "").strip()
    with _lock:
        store = _load()
        existing = next((item for item in store["feeds"] if item.get("id") == feed_id), None)
        if feed_id and existing is None:
            raise KeyError(f"A fonte «{feed_id}» não existe.")
        if not existing:
            if not url:
                raise ValueError("A fonte precisa de um URL de feed.")
            if not re.match(r"^https?://", url, re.I):
                raise ValueError("O URL do feed tem de começar por http:// ou https://.")
            duplicate = next(
                (item for item in store["feeds"] if str(item.get("url") or "").strip().rstrip("/").lower() == url.rstrip("/").lower()),
                None,
            )
            if duplicate:
                raise ValueError(f"Esse feed já está subscrito («{duplicate.get('title') or duplicate['url']}»).")
        folder_id = payload.get("folder_id", (existing or {}).get("folder_id"))
        if folder_id and not any(item.get("id") == folder_id for item in store["folders"]):
            folder_id = None
        tags = payload.get("tags")
        body: Dict[str, Any] = {
            "id": (existing or {}).get("id") or _new_id("feed"),
            "url": url or str((existing or {}).get("url") or ""),
            "folder_id": folder_id,
            "updated_at": _now(),
        }
        if existing is None:
            body.update(
                {
                    "title": str(payload.get("title") or "").strip() or body["url"],
                    "site_url": str(payload.get("site_url") or "").strip(),
                    "description": _clean_text(payload.get("description"), 600),
                    "language": str(payload.get("language") or "").strip(),
                    "icon_url": str(payload.get("icon_url") or "").strip(),
                    "enabled": bool(payload.get("enabled", True)),
                    "tags": _as_list(tags) or _as_list(store["settings"].get("default_tags")),
                    "last_fetch_at": None,
                    "last_status": "nunca",
                    "last_error": "",
                    "added_by": actor,
                    "created_at": _now(),
                }
            )
            store["feeds"].append(body)
            feed = body
        else:
            if "title" in payload:
                body["title"] = str(payload.get("title") or "").strip() or existing.get("title") or body["url"]
            for optional in ("site_url", "description", "language", "icon_url"):
                if optional in payload:
                    body[optional] = _clean_text(payload.get(optional), 600) if optional == "description" else str(payload.get(optional) or "").strip()
            if "enabled" in payload:
                body["enabled"] = bool(payload.get("enabled"))
            if tags is not None:
                body["tags"] = _as_list(tags)
            existing.update(body)
            feed = existing
        _log(store, "fonte.criada" if existing is None else "fonte.alterada", str(feed.get("title") or ""), actor, str(feed.get("url") or ""))
        _write_store(store)
        return _feed_view(store, feed, with_content=True)


def feed_state(feed_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Atualiza o estado da última recolha (etag, data, erro)."""
    with _lock:
        store = _load()
        feed = next((item for item in store["feeds"] if item.get("id") == feed_id), None)
        if feed is None:
            raise KeyError(f"A fonte «{feed_id}» não existe.")
        allowed = {
            "etag",
            "last_modified",
            "last_fetch_at",
            "last_status",
            "last_error",
            "title",
            "site_url",
            "description",
            "language",
            "icon_url",
        }
        for key, value in (patch or {}).items():
            if key in allowed:
                feed[key] = value
        feed["updated_at"] = _now()
        _write_store(store)
        return _feed_view(store, feed, with_content=True)


def delete_feed(feed_id: str, actor: str = "") -> Dict[str, Any]:
    with _lock:
        store = _load()
        feed = next((item for item in store["feeds"] if item.get("id") == feed_id), None)
        if feed is None:
            raise KeyError(f"A fonte «{feed_id}» não existe.")
        store["feeds"] = [item for item in store["feeds"] if item.get("id") != feed_id]
        removed = len([article for article in store["articles"] if article.get("feed_id") == feed_id])
        store["articles"] = [article for article in store["articles"] if article.get("feed_id") != feed_id]
        _log(store, "fonte.apagada", str(feed.get("title") or ""), actor, f"{removed} artigo(s) removidos")
        _write_store(store)
        return {"deleted": True, "id": feed_id, "articles_removed": removed}


# --------------------------------------------------------------------------
# Artigos
# --------------------------------------------------------------------------
def _article_summary(article: Dict[str, Any], feed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    view = {
        key: article.get(key)
        for key in (
            "id",
            "feed_id",
            "guid",
            "title",
            "url",
            "author",
            "summary",
            "published_at",
            "fetched_at",
            "image_url",
            "categories",
            "read",
            "favorite",
            "saved",
            "reading_minutes",
            "has_content",
            "tags",
            "digest_at",
        )
    }
    view["has_digest"] = bool(article.get("digest"))
    if feed is not None:
        view["feed_title"] = feed.get("title") or ""
        view["feed_icon"] = feed.get("icon_url") or ""
        view["folder_id"] = feed.get("folder_id")
    return view


def _article_full(article: Dict[str, Any], store: Dict[str, Any]) -> Dict[str, Any]:
    feed = next((item for item in store["feeds"] if item.get("id") == article.get("feed_id")), None)
    view = _article_summary(article, feed)
    view["content"] = article.get("content") or article.get("summary") or ""
    view["digest"] = article.get("digest") or ""
    view["feed_url"] = (feed or {}).get("url") or ""
    view["feed_site_url"] = (feed or {}).get("site_url") or ""
    view["feed_tags"] = list((feed or {}).get("tags") or [])
    view["tags"] = list(article.get("tags") or [])
    return view


def _read_filters(
    *,
    feed_id: Optional[str],
    folder_id: Optional[str],
    q: Optional[str],
    unread: Optional[bool],
    favorite: Optional[bool],
    saved: Optional[bool],
    tag: Optional[str],
    since: Optional[str],
) -> Any:
    needle = (_opt_str(q) or "").lower()
    tag_needle = (_opt_str(tag) or "").lower()
    since_iso = _parse_date(since) if _opt_str(since) else None
    feed_filter = _opt_str(feed_id)
    folder_filter = _opt_str(folder_id)
    unread_filter = _opt_bool(unread)
    favorite_filter = _opt_bool(favorite)
    saved_filter = _opt_bool(saved)

    def matches(article: Dict[str, Any], feed: Optional[Dict[str, Any]]) -> bool:
        if feed_filter and article.get("feed_id") != feed_filter:
            return False
        if folder_id is not None and folder_filter is not None:
            folder = None if folder_filter in ("all", "todas") else ("__root__" if folder_filter == "root" else folder_filter)
            if folder == "__root__":
                if (feed or {}).get("folder_id"):
                    return False
            elif folder and (feed or {}).get("folder_id") != folder:
                return False
        if unread_filter is not None and bool(article.get("read")) == unread_filter:
            return False
        if favorite_filter is not None and bool(article.get("favorite")) != favorite_filter:
            return False
        if saved_filter is not None and bool(article.get("saved")) != saved_filter:
            return False
        if tag_needle:
            haystack = [fold_text(value) for value in (feed or {}).get("tags") or []]
            haystack += [fold_text(value) for value in article.get("tags") or []]
            haystack += [fold_text(value) for value in article.get("categories") or []]
            if not any(tag_needle in value for value in haystack):
                return False
        if since_iso and _sort_key(article) < since_iso:
            return False
        if needle:
            haystack = " ".join(
                [
                    str(article.get("title") or ""),
                    str(article.get("summary") or ""),
                    str(article.get("author") or ""),
                    " ".join(str(value) for value in article.get("categories") or []),
                    str((feed or {}).get("title") or ""),
                ]
            ).lower()
            if needle not in haystack and needle not in str(article.get("content") or "").lower():
                return False
        return True

    return matches


def list_articles(
    *,
    feed_id: Optional[str] = None,
    folder_id: Optional[str] = None,
    q: Optional[str] = None,
    unread: Optional[bool] = None,
    favorite: Optional[bool] = None,
    saved: Optional[bool] = None,
    tag: Optional[str] = None,
    since: Optional[str] = None,
    order: str = "desc",
    limit: int = 40,
    offset: int = 0,
) -> Dict[str, Any]:
    """Lista artigos (resumos), com contagens por fonte e totais."""
    store = _store()
    feeds = {feed["id"]: feed for feed in store["feeds"]}
    matches = _read_filters(
        feed_id=feed_id,
        folder_id=folder_id,
        q=q,
        unread=unread,
        favorite=favorite,
        saved=saved,
        tag=tag,
        since=since,
    )
    selected = [article for article in store["articles"] if matches(article, feeds.get(article.get("feed_id")))]
    selected.sort(key=_sort_key, reverse=(order != "asc"))
    total = len(selected)
    size = _clamp(limit, 1, 200, 40)
    start = max(0, offset if isinstance(offset, int) else 0)
    page = selected[start : start + size]
    unread_by_feed: Dict[str, int] = {}
    for article in store["articles"]:
        if not article.get("read"):
            unread_by_feed[article["feed_id"]] = unread_by_feed.get(article["feed_id"], 0) + 1
    return {
        "total": total,
        "offset": start,
        "limit": size,
        "has_more": start + size < total,
        "unread": sum(unread_by_feed.values()),
        "unread_by_feed": unread_by_feed,
        "items": [_article_summary(article, feeds.get(article.get("feed_id"))) for article in page],
    }


def get_article(article_id: str, *, mark_read: bool = False) -> Dict[str, Any]:
    with _lock:
        store = _load()
        article = next((item for item in store["articles"] if item.get("id") == article_id), None)
        if article is None:
            raise KeyError(f"O artigo «{article_id}» não existe.")
        if mark_read and not article.get("read"):
            article["read"] = True
            article["read_at"] = _now()
            _write_store(store)
        return _article_full(article, store)


def update_article(article_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Altera os estados do artigo (`read`, `favorite`, `saved`) e o `digest`."""
    with _lock:
        store = _load()
        article = next((item for item in store["articles"] if item.get("id") == article_id), None)
        if article is None:
            raise KeyError(f"O artigo «{article_id}» não existe.")
        for key in ("read", "favorite", "saved"):
            if key in patch:
                article[key] = bool(patch[key])
                if key == "read":
                    article["read_at"] = _now() if article[key] else None
        if "digest" in patch:
            article["digest"] = str(patch.get("digest") or "")[:MAX_DIGEST_CHARS]
            article["digest_at"] = _now() if article["digest"] else None
        if "categories" in patch:
            article["categories"] = _as_list(patch.get("categories"))
        if "tags" in patch:
            article["tags"] = _as_list(patch.get("tags"))[:12]
        article["updated_at"] = _now()
        _write_store(store)
        return _article_full(article, store)


def mark_all_read(
    *,
    feed_id: Optional[str] = None,
    folder_id: Optional[str] = None,
    q: Optional[str] = None,
    actor: str = "",
) -> Dict[str, Any]:
    with _lock:
        store = _load()
        feeds = {feed["id"]: feed for feed in store["feeds"]}
        matches = _read_filters(
            feed_id=feed_id,
            folder_id=folder_id,
            q=q,
            unread=True,
            favorite=None,
            saved=None,
            tag=None,
            since=None,
        )
        now = _now()
        changed = 0
        for article in store["articles"]:
            if article.get("read"):
                continue
            if matches(article, feeds.get(article.get("feed_id"))):
                article["read"] = True
                article["read_at"] = now
                changed += 1
        if changed:
            _log(store, "artigos.lidos", f"{changed} artigo(s)", actor, "marcados como lidos")
            _write_store(store)
        return {"updated": changed}


def purge_read(feed_id: Optional[str] = None, actor: str = "") -> Dict[str, Any]:
    """Remove os artigos já lidos (nunca os favoritos ou guardados)."""
    with _lock:
        store = _load()
        keep: List[Dict[str, Any]] = []
        removed = 0
        for article in store["articles"]:
            removable = (
                article.get("read")
                and not article.get("favorite")
                and not article.get("saved")
                and (not feed_id or article.get("feed_id") == feed_id)
            )
            if removable:
                removed += 1
            else:
                keep.append(article)
        if removed:
            store["articles"] = keep
            _log(store, "artigos.limpos", f"{removed} artigo(s)", actor, "artigos lidos removidos")
            _write_store(store)
        return {"removed": removed}


# --------------------------------------------------------------------------
# Recolha (persistência dos artigos recolhidos)
# --------------------------------------------------------------------------
def store_articles(feed_id: str, entries: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Guarda os artigos de uma recolha, sem duplicar (por `guid`/URL).

    Devolve `{"added", "updated", "total"}`. Um artigo que reaparece com o corpo
    completo (feeds que só publicam o resumo primeiro) é enriquecido, não
    duplicado.
    """
    with _lock:
        store = _load()
        if not any(feed.get("id") == feed_id for feed in store["feeds"]):
            raise KeyError(f"A fonte «{feed_id}» não existe.")
        articles = [article for article in store["articles"] if article.get("feed_id") == feed_id]
        others = [article for article in store["articles"] if article.get("feed_id") != feed_id]
        by_guid = {str(article.get("guid") or "").lower(): article for article in articles if article.get("guid")}
        by_url = {str(article.get("url") or "").lower(): article for article in articles if article.get("url")}
        added = 0
        updated = 0
        now = _now()
        rules = list(store["settings"].get("rules") or [])
        rule_hits = 0
        for entry in entries:
            title = _clean_text(entry.get("title"), 500) or "(sem título)"
            url = str(entry.get("url") or "").strip()
            guid = str(entry.get("guid") or url or title).strip()
            summary = _clean_text(entry.get("summary"))
            content = str(entry.get("content") or "")[:MAX_CONTENT_CHARS]
            existing = by_guid.get(guid.lower()) or by_url.get(url.lower())
            if existing is not None:
                changed = False
                for key, value in (("summary", summary), ("content", content)):
                    if value and len(str(value)) > len(str(existing.get(key) or "")):
                        existing[key] = value
                        changed = True
                if entry.get("image_url") and not existing.get("image_url"):
                    existing["image_url"] = entry["image_url"]
                    changed = True
                if url and not existing.get("url"):
                    existing["url"] = url
                    changed = True
                if changed:
                    existing["has_content"] = bool(existing.get("content"))
                    existing["updated_at"] = now
                    updated += 1
                continue
            article = {
                "id": _new_id("art"),
                "feed_id": feed_id,
                "guid": guid,
                "title": title,
                "url": url,
                "author": _clean_text(entry.get("author"), 200),
                "summary": summary,
                "content": content,
                "published_at": entry.get("published_at"),
                "fetched_at": now,
                "image_url": str(entry.get("image_url") or "").strip(),
                "categories": _as_list(entry.get("categories")),
                "read": False,
                "favorite": False,
                "saved": False,
                "tags": [],
                "reading_minutes": int(entry.get("reading_minutes") or 1),
                "has_content": bool(content),
                "digest": "",
                "digest_at": None,
                "created_at": now,
                "updated_at": now,
            }
            if rules and _apply_rules_to(article, rules):
                rule_hits += 1
            articles.append(article)
            if guid:
                by_guid[guid.lower()] = article
            if url:
                by_url[url.lower()] = article
            added += 1
        if added or updated:
            # Os artigos desta fonte (enriquecidos em cima) voltam ao documento a
            # par dos das outras fontes — sem isto, uma recolha sem novidades
            # apagava o que já estava guardado.
            store["articles"] = others + articles
            _prune(store, feed_id)
            _write_store(store)
        return {"added": added, "updated": updated, "total": len(articles), "rule_hits": rule_hits}


def _prune(store: Dict[str, Any], feed_id: str) -> None:
    """Aplica o limite por fonte e a retenção, sem tocar em favoritos/guardados."""
    settings = store["settings"]
    per_feed = _clamp(settings.get("max_articles_per_feed"), 20, 5000, 300)
    retention = _clamp(settings.get("retention_days"), 0, 3650, 0)
    cutoff = None
    if retention:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention)).isoformat()

    def protected(article: Dict[str, Any]) -> bool:
        return bool(article.get("favorite") or article.get("saved"))

    mine = [article for article in store["articles"] if article.get("feed_id") == feed_id]
    mine.sort(key=_sort_key, reverse=True)
    drop: set = set()
    kept = 0
    for article in mine:
        if protected(article):
            continue
        kept += 1
        if kept > per_feed:
            drop.add(article["id"])
            continue
        if cutoff and _sort_key(article) and _sort_key(article) < cutoff:
            drop.add(article["id"])
    if drop:
        store["articles"] = [article for article in store["articles"] if article["id"] not in drop]


# --------------------------------------------------------------------------
# Panorama, catálogo e pesquisa
# --------------------------------------------------------------------------
def settings() -> Dict[str, Any]:
    return copy.deepcopy(_store()["settings"])


def save_settings(payload: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
    with _lock:
        store = _load()
        current = store["settings"]
        if "auto_fetch" in payload:
            current["auto_fetch"] = bool(payload.get("auto_fetch"))
        if "mark_read_on_open" in payload:
            current["mark_read_on_open"] = bool(payload.get("mark_read_on_open"))
        if "cron" in payload:
            current["cron"] = str(payload.get("cron") or "").strip()
        if "timezone" in payload:
            current["timezone"] = str(payload.get("timezone") or "Europe/Lisbon").strip() or "Europe/Lisbon"
        if "max_articles_per_feed" in payload:
            current["max_articles_per_feed"] = _clamp(payload.get("max_articles_per_feed"), 20, 5000, 300)
        if "retention_days" in payload:
            current["retention_days"] = _clamp(payload.get("retention_days"), 0, 3650, 0)
        if "default_tags" in payload:
            current["default_tags"] = _as_list(payload.get("default_tags"))
        if "rules" in payload:
            current["rules"] = _normalise_rules(payload.get("rules"))
        _log(store, "definicoes.alteradas", "Agenda e recolha", actor)
        _write_store(store)
        return copy.deepcopy(current)


def rules() -> List[Dict[str, Any]]:
    """Regras automáticas guardadas (termo → guardar/favorito/lido e etiquetas)."""
    return copy.deepcopy(_store()["settings"].get("rules") or [])


def save_rules(value: Any, actor: str = "", *, apply_now: bool = False) -> Dict[str, Any]:
    """Grava as regras e, a pedido, aplica-as já aos artigos existentes."""
    with _lock:
        store = _load()
        store["settings"]["rules"] = _normalise_rules(value)
        changed = 0
        touched = 0
        if apply_now:
            for article in store["articles"]:
                if article.get("read") and not article.get("saved") and not article.get("favorite"):
                    # Artigos já lidos e sem marca não voltam a ser tratados.
                    continue
                before = (bool(article.get("saved")), bool(article.get("favorite")), bool(article.get("read")), tuple(article.get("tags") or []))
                if _apply_rules_to(article, store["settings"]["rules"]):
                    touched += 1
                after = (bool(article.get("saved")), bool(article.get("favorite")), bool(article.get("read")), tuple(article.get("tags") or []))
                if before != after:
                    changed += 1
        _log(store, "regras.alteradas", f"{len(store['settings']['rules'])} regra(s)", actor, f"{changed} artigo(s) alterados" if apply_now else "")
        _write_store(store)
        return {"rules": copy.deepcopy(store["settings"]["rules"]), "applied": changed, "matched": touched}


def apply_rules(actor: str = "", *, only_unread: bool = True) -> Dict[str, Any]:
    """Aplica as regras atuais aos artigos já guardados."""
    with _lock:
        store = _load()
        current = store["settings"].get("rules") or []
        changed = 0
        matched = 0
        for article in store["articles"]:
            if only_unread and article.get("read") and not article.get("saved") and not article.get("favorite"):
                continue
            before = (bool(article.get("saved")), bool(article.get("favorite")), bool(article.get("read")), tuple(article.get("tags") or []))
            if _apply_rules_to(article, current):
                matched += 1
            after = (bool(article.get("saved")), bool(article.get("favorite")), bool(article.get("read")), tuple(article.get("tags") or []))
            if before != after:
                changed += 1
        if changed or matched:
            _log(store, "regras.aplicadas", f"{changed} artigo(s)", actor, f"{matched} correspondência(s)")
            _write_store(store)
        return {"applied": changed, "matched": matched}


def overview() -> Dict[str, Any]:
    """Panorama do leitor: contagens, série diária, fontes, temas e últimos artigos."""
    store = _store()
    articles = store["articles"]
    feeds = store["feeds"]
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week = (now - timedelta(days=7)).isoformat()
    last_fetch = max((str(feed.get("last_fetch_at") or "") for feed in feeds), default="")
    per_feed = [_feed_view(store, feed) for feed in feeds]
    per_feed.sort(key=lambda item: (-int(item.get("unread") or 0), str(item.get("title") or "").lower()))
    recent = sorted(articles, key=_sort_key, reverse=True)[:8]
    # Série dos últimos 14 dias (para o gráfico do painel).
    series: List[Dict[str, Any]] = []
    buckets: Dict[str, int] = {}
    for article in articles:
        day = _sort_key(article)[:10]
        if day:
            buckets[day] = buckets.get(day, 0) + 1
    for offset in range(13, -1, -1):
        day = (now - timedelta(days=offset)).date().isoformat()
        series.append({"day": day, "articles": buckets.get(day, 0)})
    # Fontes ordenadas por volume (o painel mostra só as principais).
    top_feeds = sorted((_feed_view(store, feed) for feed in feeds), key=lambda item: -int(item.get("articles") or 0))[:8]
    return {
        "feeds": {
            "total": len(feeds),
            "enabled": sum(1 for feed in feeds if feed.get("enabled")),
            "with_error": sum(1 for feed in feeds if feed.get("last_status") == "erro"),
            "last_fetch_at": last_fetch or None,
        },
        "folders": len(store["folders"]),
        "articles": {
            "total": len(articles),
            "unread": sum(1 for article in articles if not article.get("read")),
            "favorite": sum(1 for article in articles if article.get("favorite")),
            "saved": sum(1 for article in articles if article.get("saved")),
            "tagged": sum(1 for article in articles if article.get("tags")),
            "today": sum(1 for article in articles if _sort_key(article) >= today),
            "week": sum(1 for article in articles if _sort_key(article) >= week),
        },
        "series": series,
        "top_feeds": top_feeds,
        "rules": copy.deepcopy(store["settings"].get("rules") or []),
        "per_feed": per_feed,
        "recent": [_article_summary(article) for article in recent],
        "activity": copy.deepcopy(store.get("activity", [])[:12]),
        "settings": copy.deepcopy(store["settings"]),
    }


def catalogue() -> Dict[str, Any]:
    """Tudo o que os ecrãs precisam: pastas, fontes, etiquetas, estados e limites."""
    store = _store()
    tags: List[str] = []
    for feed in store["feeds"]:
        for tag in feed.get("tags") or []:
            if tag not in tags:
                tags.append(tag)
    for article in store["articles"]:
        for tag in article.get("tags") or []:
            if tag not in tags:
                tags.append(tag)
    return {
        "folders": list_folders(),
        "feeds": list_feeds(),
        "tags": sorted(tags, key=str.lower),
        "status_labels": STATUS_LABELS,
        "status_tones": STATUS_TONES,
        "colors": list(FOLDER_COLORS),
        "rule_actions": [dict(action) for action in RULE_ACTIONS],
        "settings": copy.deepcopy(store["settings"]),
        "defaults": copy.deepcopy(DEFAULT_SETTINGS),
        "limits": {
            "max_articles_per_feed": 300,
            "retention_days": 3650,
            "summary_chars": MAX_SUMMARY_CHARS,
            "rules": MAX_RULES,
        },
        "totals": {
            "feeds": len(store["feeds"]),
            "folders": len(store["folders"]),
            "articles": len(store["articles"]),
            "unread": sum(1 for article in store["articles"] if not article.get("read")),
            "favorite": sum(1 for article in store["articles"] if article.get("favorite")),
            "saved": sum(1 for article in store["articles"] if article.get("saved")),
        },
    }


def search(query: str, limit: int = 30) -> Dict[str, Any]:
    """Pesquisa em artigos e fontes (para a caixa de pesquisa do cabeçalho)."""
    needle = (_opt_str(query) or "").lower()
    size = _clamp(limit, 1, 100, 30)
    if len(needle) < 2:
        return {"query": query, "items": []}
    store = _store()
    feeds = {feed["id"]: feed for feed in store["feeds"]}
    hits: List[Dict[str, Any]] = []
    for feed in store["feeds"]:
        haystack = f"{feed.get('title') or ''} {feed.get('url') or ''} {' '.join(feed.get('tags') or [])}".lower()
        if needle in haystack:
            hits.append(
                {
                    "kind": "feed",
                    "id": feed["id"],
                    "title": feed.get("title") or feed.get("url") or "",
                    "subtitle": feed.get("url") or "",
                    "unread": sum(1 for article in store["articles"] if article.get("feed_id") == feed["id"] and not article.get("read")),
                }
            )
    articles = [
        article
        for article in store["articles"]
        if needle
        in f"{article.get('title') or ''} {article.get('summary') or ''} {article.get('author') or ''}".lower()
    ]
    articles.sort(key=_sort_key, reverse=True)
    for article in articles[:size]:
        hits.append(
            {
                "kind": "article",
                "id": article["id"],
                "title": article.get("title") or "",
                "subtitle": (feeds.get(article.get("feed_id")) or {}).get("title") or "",
                "published_at": article.get("published_at"),
                "read": bool(article.get("read")),
            }
        )
    return {"query": query, "items": hits[: size * 2]}


def tags() -> List[Dict[str, Any]]:
    """Etiquetas usadas nas fontes e nos artigos, com contagens."""
    store = _store()
    counts: Dict[str, Dict[str, int]] = {}
    for feed in store["feeds"]:
        for tag in feed.get("tags") or []:
            counts.setdefault(tag, {"feeds": 0, "articles": 0})["feeds"] += 1
    for article in store["articles"]:
        for tag in article.get("tags") or []:
            counts.setdefault(tag, {"feeds": 0, "articles": 0})["articles"] += 1
    return [
        {"tag": tag, "feeds": value["feeds"], "articles": value["articles"]}
        for tag, value in sorted(counts.items(), key=lambda item: (-(item[1]["feeds"] + item[1]["articles"]), item[0].lower()))
    ]


def _keywords_of(article: Dict[str, Any], limit: int = 14) -> set:
    """Palavras significativas do título e das categorias (para os relacionados)."""
    stop = {
        "para", "com", "como", "mais", "menos", "sobre", "depois", "ainda", "pelo", "pela",
        "dos", "das", "uma", "que", "não", "the", "and", "for", "with", "its", "from",
    }
    words = re.findall(r"[a-zA-ZÀ-ÿ]{4,}", fold_text(f"{article.get('title') or ''} {' '.join(article.get('categories') or [])}"))
    picked: List[str] = []
    for word in words:
        if word in stop or word in picked:
            continue
        picked.append(word)
        if len(picked) >= limit:
            break
    return set(picked)


def related_articles(article_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Artigos do mesmo tema (categorias e palavras do título em comum)."""
    store = _store()
    feeds = {feed["id"]: feed for feed in store["feeds"]}
    target = next((article for article in store["articles"] if article.get("id") == article_id), None)
    if target is None:
        raise KeyError(f"O artigo «{article_id}» não existe.")
    categories = {fold_text(value) for value in (target.get("categories") or []) if value}
    keywords = _keywords_of(target)
    scored: List[tuple] = []
    for article in store["articles"]:
        if article.get("id") == article_id:
            continue
        shared_categories = categories & {fold_text(value) for value in (article.get("categories") or []) if value}
        shared_words = keywords & _keywords_of(article)
        score = len(shared_categories) * 3 + len(shared_words)
        if score < 2:
            continue
        scored.append((score, _sort_key(article), article))
    # Ordenação estável dupla: mais parecidos primeiro e, entre iguais, os mais recentes.
    scored.sort(key=lambda item: item[1], reverse=True)
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {**_article_summary(article, feeds.get(article.get("feed_id"))), "score": score}
        for score, _stamp, article in scored[: _clamp(limit, 1, 20, 5)]
    ]


def export_articles(
    *,
    feed_id: Optional[str] = None,
    folder_id: Optional[str] = None,
    q: Optional[str] = None,
    unread: Optional[bool] = None,
    favorite: Optional[bool] = None,
    saved: Optional[bool] = None,
    tag: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Artigos completos que correspondem aos filtros (para CSV/Markdown)."""
    store = _store()
    feeds = {feed["id"]: feed for feed in store["feeds"]}
    matches = _read_filters(
        feed_id=feed_id,
        folder_id=folder_id,
        q=q,
        unread=unread,
        favorite=favorite,
        saved=saved,
        tag=tag,
        since=since,
    )
    selected = [article for article in store["articles"] if matches(article, feeds.get(article.get("feed_id")))]
    selected.sort(key=_sort_key, reverse=True)
    rows: List[Dict[str, Any]] = []
    for article in selected[: _clamp(limit, 1, 5000, 500)]:
        feed = feeds.get(article.get("feed_id")) or {}
        rows.append(
            {
                "id": article["id"],
                "title": article.get("title") or "",
                "feed": feed.get("title") or "",
                "author": article.get("author") or "",
                "published_at": article.get("published_at") or "",
                "url": article.get("url") or "",
                "read": bool(article.get("read")),
                "favorite": bool(article.get("favorite")),
                "saved": bool(article.get("saved")),
                "tags": " | ".join(str(value) for value in article.get("tags") or []),
                "categories": " | ".join(str(value) for value in article.get("categories") or []),
                "reading_minutes": int(article.get("reading_minutes") or 1),
                "summary": _clean_text(article.get("summary"), 600),
                "has_digest": bool(article.get("digest")),
                "digest": article.get("digest") or "",
                "content": _clean_text(article.get("content"), 20_000),
            }
        )
    return rows


# --------------------------------------------------------------------------
# Exportação (Office, RAG, OPML, digest)
# --------------------------------------------------------------------------
def article_markdown(article: Dict[str, Any]) -> str:
    """Markdown do artigo, pronto para o Office, o RAG ou um PDF."""
    store = _store()
    feed = next((item for item in store["feeds"] if item.get("id") == article.get("feed_id")), None)
    lines = [f"# {article.get('title') or '(sem título)'}", ""]
    meta: List[str] = []
    if feed:
        meta.append(f"**Fonte:** {feed.get('title') or feed.get('url')}")
    if article.get("author"):
        meta.append(f"**Autor:** {article['author']}")
    if article.get("published_at"):
        meta.append(f"**Publicado:** {article['published_at']}")
    meta.append(f"**Original:** {article.get('url') or ''}")
    lines.extend(["  \n".join(meta), ""])
    if article.get("digest"):
        lines.extend(["## Resumo (IA)", "", article["digest"], ""])
    body = article.get("content") or ""
    if body and re.search(r"<[a-z][^>]*>", body, re.I):
        body = _clean_text(body, MAX_CONTENT_CHARS)
    lines.extend(["## Texto", "", body.strip() or str(article.get("summary") or ""), ""])
    categories = article.get("categories") or []
    if categories:
        lines.extend(["---", "", "**Categorias:** " + ", ".join(str(value) for value in categories), ""])
    return "\n".join(lines).strip() + "\n"


def digest_markdown(articles: List[Dict[str, Any]], *, title: str = "Digest de notícias", note: str = "") -> str:
    """Markdown com o resumo de vários artigos (lista + sinopse de cada um)."""
    store = _store()
    feeds = {feed["id"]: feed for feed in store["feeds"]}
    lines = [f"# {title}", "", f"_{len(articles)} artigo(s)_", ""]
    if note:
        lines.extend([note, ""])
    for article in articles:
        feed = feeds.get(article.get("feed_id")) or {}
        lines.append(f"## [{article.get('title') or '(sem título)'}]({article.get('url') or '#'})")
        details = [str(feed.get("title") or "")]
        if article.get("published_at"):
            details.append(str(article["published_at"])[:10])
        lines.append("_" + " · ".join(part for part in details if part) + "_")
        lines.append("")
        text = article.get("digest") or article.get("summary") or ""
        lines.extend([str(text).strip(), ""])
    return "\n".join(lines).strip() + "\n"
