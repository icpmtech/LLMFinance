"""Estado do utilizador: favoritos, pesquisas guardadas e workspace.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import json
import logging
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch
from api.es.core import _today, get_es_client
from api.es.indices import TICKER_TRANSLATIONS_INDEX, USER_STATE_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)



# --- Preferências do utilizador (favoritos, pastas e histórico do EmpresasIQ) ---
# Um único índice guarda o estado que antes vivia apenas no browser. Favoritos e pastas
# têm um documento por item (permite marcar/remover de forma isolada); o histórico é
# um documento único com a lista completa.

def _user_state_index() -> str:
    return USER_STATE_INDEX




#: Tipos de favorito aceites: os âmbitos da Pesquisa total, além das fichas que
#: já existiam (`entity`, `contract`). Sem esta lista, favoritar um artigo de
#: imprensa ou uma pessoa morria num 400.
FAVORITE_KINDS = {
    "entity",
    "contract",
    "contracts_es",
    "entities_es",
    "companies",
    "pessoas",
    "politicos",
    "wikipedia",
    "news",
    "imprensa",
    "scraped",
    "social",
    "trademarks",
    "firmas",
    "market",
}




def _owner_clause(owner: Optional[str]) -> Optional[Dict[str, Any]]:
    """Filtro por dono que **também** mostra os registos antigos (sem dono).

    Sem isto, tudo o que foi guardado antes de existir `owner_id` desaparecia.
    """
    email = str(owner or "").strip()
    if not email:
        return None
    return {
        "bool": {
            "should": [
                {"term": {"owner_id": email}},
                {"bool": {"must_not": {"exists": {"field": "owner_id"}}}},
            ],
            "minimum_should_match": 1,
        }
    }




def _with_owner(query: Dict[str, Any], owner: Optional[str]) -> Dict[str, Any]:
    """Junta o filtro de dono a uma query já existente."""
    clause = _owner_clause(owner)
    if not clause:
        return query
    return {"bool": {"must": [query, clause]}}




def list_favorites(owner: Optional[str] = None, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Lista os favoritos guardados no Elasticsearch (mais recentes primeiro)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    ensure_indices(client)
    try:
        resp = client.search(
            index=USER_STATE_INDEX,
            body={
                "query": _with_owner({"term": {"kind": "favorite"}}, owner),
                "size": 1000,
                "sort": [{"added_at": {"order": "desc", "missing": "_last"}}],
            },
        )
        items = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            # No índice `kind` identifica o tipo de documento ("favorite"/"folder"/"history");
            # na resposta o campo `kind` é o tipo de ficha ("entity"/"imprensa"/…).
            items.append(
                {
                    "kind": src.get("entry_kind"),
                    "id": src.get("id"),
                    "label": src.get("label") or src.get("id"),
                    "sublabel": src.get("sublabel"),
                    "value": src.get("value"),
                    "parties": src.get("parties") or [],
                    "url": src.get("url"),
                    "open": src.get("open"),
                    "owner_id": src.get("owner_id"),
                    "added_at": src.get("added_at"),
                    "doc_id": hit["_id"],
                }
            )
        return {"items": items, "total": len(items)}
    except Exception as exc:
        return {"error": str(exc), "items": []}




def save_favorite(doc: Dict[str, Any], owner: Optional[str] = None, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Guarda (ou substitui) um favorito. O id do documento é ``kind:id``.

    `kind` é o âmbito do resultado na Pesquisa total (`entity`/`contract` para as
    fichas antigas, `imprensa`, `pessoas`, `politicos`, `wikipedia`, … para os
    resultados da pesquisa) — ver `FAVORITE_KINDS`.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    kind = str(doc.get("kind") or "").strip()
    item_id = str(doc.get("id") or "").strip()
    if kind not in FAVORITE_KINDS or not item_id:
        return {"error": f"Favorito inválido: kind tem de ser um de {sorted(FAVORITE_KINDS)} e id não pode ser vazio"}

    email = str(owner or doc.get("owner_id") or "").strip()
    source = {
        "kind": "favorite",
        "entry_kind": kind,
        "id": item_id,
        "label": doc.get("label") or item_id,
        "sublabel": doc.get("sublabel"),
        "value": doc.get("value"),
        "parties": doc.get("parties") or [],
        "url": doc.get("url"),
        "open": doc.get("open"),
        "added_at": doc.get("added_at") or _today(),
    }
    if email:
        source["owner_id"] = email
    try:
        client.index(index=USER_STATE_INDEX, id=f"favorite:{kind}:{item_id}", document=source, refresh=True)
        return {"ok": True, "id": item_id, "kind": kind}
    except Exception as exc:
        return {"error": str(exc)}




def delete_favorite(kind: str, item_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove um favorito."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    try:
        client.delete(index=USER_STATE_INDEX, id=f"favorite:{kind}:{item_id}", ignore=[404], refresh=True)
        return {"ok": True}
    except Exception as exc:
        return {"error": str(exc)}




# ---------------------------------------------------------------------------
# Portfólio: pesquisas guardadas (consulta + âmbito + filtros)
# ---------------------------------------------------------------------------
def _search_slug(name: str, query: str, scope: str, filters: Optional[Dict[str, Any]]) -> str:
    """Id estável de uma pesquisa guardada (o mesmo pedido atualiza, não duplica)."""
    import hashlib

    raw = json.dumps(
        {"name": (name or "").strip().lower(), "q": (query or "").strip().lower(), "scope": scope or "all", "filters": filters or {}},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]




def list_saved_searches(owner: Optional[str] = None, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Pesquisas guardadas no portfólio (mais recentes primeiro)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    ensure_indices(client)
    try:
        resp = client.search(
            index=USER_STATE_INDEX,
            body={
                "query": _with_owner({"term": {"kind": "search"}}, owner),
                "size": 500,
                "sort": [{"updated_at": {"order": "desc", "missing": "_last"}}],
            },
        )
        items = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            items.append(
                {
                    "id": src.get("id") or hit["_id"],
                    "name": src.get("name") or src.get("query") or "Pesquisa",
                    "query": src.get("query") or "",
                    "scope": src.get("scope") or "all",
                    "filters": src.get("filters") or {},
                    "description": src.get("description") or "",
                    "results_total": src.get("results_total"),
                    "owner_id": src.get("owner_id"),
                    "created_at": src.get("created_at"),
                    "last_run_at": src.get("last_run_at"),
                    "doc_id": hit["_id"],
                }
            )
        return {"items": items, "total": len(items)}
    except Exception as exc:
        return {"error": str(exc), "items": []}




def save_search(doc: Dict[str, Any], owner: Optional[str] = None, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Guarda uma pesquisa no portfólio (consulta + âmbito + filtros).

    Guarda-se **a pergunta**, não os resultados: refazer a pesquisa devolve o que
    existe hoje. O `id` é derivado da consulta+âmbito+filtros+apelido, pelo que
    guardar duas vezes o mesmo pedido atualiza a entrada em vez de duplicar.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    query = str(doc.get("query") or "").strip()
    if not query:
        return {"error": "Pesquisa inválida: falta o texto a pesquisar"}
    scope = str(doc.get("scope") or "all").strip() or "all"
    filters = doc.get("filters") or {}
    name = str(doc.get("name") or query).strip()[:200]
    search_id = str(doc.get("id") or "").strip() or _search_slug(name, query, scope, filters)
    email = str(owner or doc.get("owner_id") or "").strip()
    now = _today()

    source: Dict[str, Any] = {
        "kind": "search",
        "id": search_id,
        "name": name,
        "query": query,
        "scope": scope,
        "filters": filters,
        "description": doc.get("description") or "",
        "results_total": doc.get("results_total"),
        "created_at": doc.get("created_at") or now,
        "updated_at": now,
        "last_run_at": doc.get("last_run_at") or now,
    }
    if email:
        source["owner_id"] = email
    try:
        client.index(index=USER_STATE_INDEX, id=f"search:{search_id}", document=source, refresh=True)
        return {"ok": True, "id": search_id, "name": name}
    except Exception as exc:
        return {"error": str(exc)}




def delete_search(search_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove uma pesquisa do portfólio."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    try:
        client.delete(index=USER_STATE_INDEX, id=f"search:{search_id}", ignore=[404], refresh=True)
        return {"ok": True}
    except Exception as exc:
        return {"error": str(exc)}




def clear_favorites(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove todos os favoritos."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    try:
        resp = client.delete_by_query(
            index=USER_STATE_INDEX,
            body={"query": {"term": {"kind": "favorite"}}},
            refresh=True,
            conflicts="proceed",
        )
        return {"ok": True, "deleted": resp.get("deleted", 0)}
    except Exception as exc:
        return {"error": str(exc)}




def get_workspace(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve o dossier (pastas) e o histórico guardados."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "folders": [], "history": []}

    ensure_indices(client)
    try:
        resp = client.search(
            index=USER_STATE_INDEX,
            body={"query": {"terms": {"kind": ["folder", "history"]}}, "size": 1000},
        )
        folders = []
        history = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            if src.get("kind") == "folder":
                folders.append(
                    {
                        "id": src.get("folder_id") or hit["_id"],
                        "name": src.get("name") or "Pasta",
                        "createdAt": src.get("created_at"),
                        "items": src.get("items") or [],
                    }
                )
            elif src.get("kind") == "history":
                history = src.get("items") or []
        folders.sort(key=lambda folder: folder.get("createdAt") or "")
        return {"folders": folders, "history": history}
    except Exception as exc:
        return {"error": str(exc), "folders": [], "history": []}




def save_folder(folder: Dict[str, Any], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Guarda (ou substitui) uma pasta do dossier com as suas fichas."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    folder_id = str(folder.get("id") or "").strip()
    if not folder_id:
        return {"error": "Pasta inválida: falta o id"}

    source = {
        "kind": "folder",
        "folder_id": folder_id,
        "name": folder.get("name") or "Pasta",
        "created_at": folder.get("createdAt") or _today(),
        "items": folder.get("items") or [],
        "updated_at": _today(),
    }
    try:
        client.index(index=USER_STATE_INDEX, id=f"folder:{folder_id}", document=source, refresh=True)
        return {"ok": True, "id": folder_id}
    except Exception as exc:
        return {"error": str(exc)}




def delete_folder(folder_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove uma pasta do dossier."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    try:
        client.delete(index=USER_STATE_INDEX, id=f"folder:{folder_id}", ignore=[404], refresh=True)
        return {"ok": True}
    except Exception as exc:
        return {"error": str(exc)}




def save_history(items: List[Dict[str, Any]], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Guarda o histórico de fichas consultadas (documento único)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    try:
        client.index(
            index=USER_STATE_INDEX,
            id="history",
            document={"kind": "history", "items": items, "updated_at": _today()},
            refresh=True,
        )
        return {"ok": True, "count": len(items)}
    except Exception as exc:
        return {"error": str(exc)}




def save_ticker_translation(
    ticker: str,
    original_text: str,
    translated_text: str,
    target_language: str = "pt-PT",
    backend: str = "",
    model: str = "",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Guarda ou atualiza a tradução de um resumo de ticker no Elasticsearch."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    now = _today()
    source = {
        "ticker": ticker.upper(),
        "original_text": original_text,
        "translated_text": translated_text,
        "target_language": target_language,
        "backend": backend,
        "model": model,
        "updated_at": now,
    }
    try:
        # Verifica se já existe para preservar created_at original.
        try:
            resp = client.get(index=TICKER_TRANSLATIONS_INDEX, id=ticker.upper())
            existing = resp.get("_source") or {}
            source["created_at"] = existing.get("created_at") or now
        except Exception:
            source["created_at"] = now

        client.index(
            index=TICKER_TRANSLATIONS_INDEX,
            id=ticker.upper(),
            document=source,
            refresh=True,
        )
        return {"ticker": ticker.upper(), "saved": True}
    except Exception as exc:
        return {"error": str(exc)}




def load_ticker_translation(ticker: str, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Carrega a tradução guardada de um ticker, se existir."""
    client = es or get_es_client()
    if not client:
        return None
    ensure_indices(client)
    try:
        resp = client.get(index=TICKER_TRANSLATIONS_INDEX, id=ticker.upper())
        return resp.get("_source")
    except Exception:
        return None
