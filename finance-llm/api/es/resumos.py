"""Resumos de nós e análises de empresa guardadas.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch
from api.es.core import _today, get_es_client
from api.es.indices import ANALISES_EMPRESA_INDEX, NODE_SUMMARIES_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)




def _node_summary_id(node_id: str) -> str:
    return f"{NODE_SUMMARIES_INDEX}:{node_id}"




def index_node_summary(doc: Dict[str, Any], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Guarda (ou substitui) o resumo de um nó de grafo.

    Um documento por nó (`node_id` = `person:<nif>`, `company:<nif>`,
    `source:<host>`), com o texto, a evidência e os factos usados. Cada gravação
    conta em `generations` e atualiza `generated_at`/`ingested_at`, para se saber
    quantas vezes o resumo foi refeito e quando.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "saved": False}
    node_id = str((doc or {}).get("node_id") or "").strip()
    if not node_id:
        return {"error": "Resumo sem `node_id`.", "saved": False}
    ensure_indices(client)

    previous = get_node_summary(node_id, es=client) or {}
    generations = int(previous.get("generations") or 0) + 1
    now = _today()
    payload: Dict[str, Any] = {
        "node_id": node_id,
        "nif": str(doc.get("nif") or "")[:32],
        "name": str(doc.get("name") or "")[:512],
        "kind": str(doc.get("kind") or "")[:32],
        "summary": str(doc.get("summary") or ""),
        "mode": str(doc.get("mode") or "factual")[:32],
        "provider": str(doc.get("provider") or "")[:64],
        "model": str(doc.get("model") or "")[:128],
        "queries": [str(q)[:512] for q in (doc.get("queries") or [])][:12],
        "evidence": (doc.get("evidence") or [])[:40],
        "facts": doc.get("facts") or {},
        "evidence_count": len(doc.get("evidence") or []),
        "pages_read": int(doc.get("pages_read") or 0),
        "generations": generations,
        "generated_at": doc.get("generated_at") or now,
        "ingested_at": now,
    }
    try:
        client.index(index=NODE_SUMMARIES_INDEX, id=_node_summary_id(node_id), document=payload, refresh=True)
        return {"saved": True, "node_id": node_id, "generations": generations, "generated_at": payload["generated_at"]}
    except Exception as exc:
        return {"error": str(exc), "saved": False}




def get_node_summary(
    node_id: Optional[str] = None,
    *,
    nif: Optional[str] = None,
    name: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Resumo já guardado de um nó (por `node_id`, ou por NIF/nome como recurso)."""
    client = es or get_es_client()
    if not client:
        return {}
    ensure_indices(client)
    node_id = str(node_id or "").strip()
    try:
        if node_id:
            resp = client.get(index=NODE_SUMMARIES_INDEX, id=_node_summary_id(node_id), _source=True)
            source = resp.get("_source")
            if isinstance(source, dict):
                return source
            return {}
        query: Dict[str, Any] = {"match_all": {}}
        if nif:
            query = {"term": {"nif": str(nif)}}
        elif name:
            query = {"match": {"name": str(name)}}
        resp = client.search(
            index=NODE_SUMMARIES_INDEX,
            body={"size": 1, "query": query, "sort": [{"generated_at": {"order": "desc"}}]},
        )
        hits = resp.get("hits", {}).get("hits", [])
        return (hits[0].get("_source") if hits else {}) or {}
    except Exception as exc:
        logger.debug("Resumo de nó %s não encontrado: %s", node_id or nif or name, exc)
        return {}




def node_summaries_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice de resumos (total, por tipo de nó e por modo)."""
    client = es or get_es_client()
    if not client:
        return {"available": False, "total": 0}
    ensure_indices(client)
    try:
        count = int(client.count(index=NODE_SUMMARIES_INDEX).get("count", 0) or 0)
        out: Dict[str, Any] = {"available": True, "index": NODE_SUMMARIES_INDEX, "total": count}
        if count:
            resp = client.search(
                index=NODE_SUMMARIES_INDEX,
                body={
                    "size": 0,
                    "aggs": {
                        "kinds": {"terms": {"field": "kind", "size": 10}},
                        "modes": {"terms": {"field": "mode", "size": 10}},
                        "latest": {"max": {"field": "generated_at"}},
                    },
                },
            )
            aggs = resp.get("aggregations", {})
            out["kinds"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("kinds", {}).get("buckets", [])]
            out["modes"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("modes", {}).get("buckets", [])]
            out["latest"] = aggs.get("latest", {}).get("value_as_string")
        return out
    except Exception as exc:
        return {"available": False, "error": str(exc), "total": 0}





# ---------------------------------------------------------------------------
# Análises de padrões por empresa (`finance_analises_empresa`)
#
# O módulo «Deteção de padrões» produz uma análise pesada (amostra de contratos,
# réguas por CPV, regras, relações). Guardá-la serve três coisas: comparar a
# mesma empresa em datas diferentes, ter a ficha de IA com proveniência e poder
# emitir o relatório mais tarde sem recalcular nada.
#
# O documento guarda a **fotografia completa** (`analise`, não indexada) e os
# campos que interessam para listar e filtrar (nome, NIF, valor, severidade,
# sinais, modelo de IA). `doc_id` é `<pais>:<nif>`, pelo que voltar a guardar a
# mesma empresa **substitui** a análise anterior em vez de acumular duplicados.
# ---------------------------------------------------------------------------
def _analise_doc_id(pais: str, nif: str) -> str:
    """Id estável de uma análise (`PT:503439800`) — evita duplicados por empresa."""
    return f"{(pais or 'PT').upper()}:{str(nif or '').strip()}"




def save_analise_empresa(payload: Dict[str, Any], *, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Guarda (ou substitui) a análise de uma empresa.

    `payload` aceita a análise devolvida por `padroes_service.analise_empresa` ou
    um dicionário já preparado (`nif`, `nome`, `analise`, `ficha_ia`, ...).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    nif = str(payload.get("nif") or "").strip()
    if not nif:
        return {"error": "NIF em falta"}
    pais = str(payload.get("pais") or "PT").upper()
    analise = payload.get("analise") if isinstance(payload.get("analise"), dict) else payload
    resumo = (analise.get("resumo") or {}) if isinstance(analise, dict) else {}
    sinais = [str(item.get("padrao")) for item in (analise.get("sinais") or []) if isinstance(item, dict)]
    severidades = [str(item.get("severidade")) for item in (analise.get("sinais") or []) if isinstance(item, dict)]
    ordem = {"alerta": 0, "aviso": 1, "info": 2}
    severidade = sorted(severidades, key=lambda item: ordem.get(item, 9))[0] if severidades else None
    ia = payload.get("ia") if isinstance(payload.get("ia"), dict) else {}
    browser = payload.get("browser") if isinstance(payload.get("browser"), list) else []

    ensure_indices(client)
    now = _today()
    doc_id = _analise_doc_id(pais, nif)
    doc = {
        "doc_id": doc_id,
        "nif": nif,
        "nome": str(payload.get("nome") or analise.get("nome") or nif)[:512],
        "pais": pais,
        "titulo": str(payload.get("titulo") or f"Análise de padrões · {analise.get('nome') or nif}")[:512],
        "notas": str(payload.get("notas") or "")[:8000],
        "criado_em": str(payload.get("criado_em") or now),
        "atualizado_em": now,
        "autor": str(payload.get("autor") or "")[:128],
        "autor_email": str(payload.get("autor_email") or "")[:256],
        "anos": [int(ano) for ano in (analise.get("anos") or []) if isinstance(ano, (int, float))][:8],
        "contratos_total": int(analise.get("contratos_total") or 0),
        "contratos_analisados": int(analise.get("contratos_analisados") or 0),
        "valor_total": float(resumo.get("valor_total") or 0.0),
        "severidade": severidade or "",
        "sinais": sinais[:40],
        "regras": [str(regra.get("id")) for regra in (analise.get("regras_ativas") or []) if isinstance(regra, dict)][:60],
        "insolvente": bool(resumo.get("insolvente")),
        "ia": bool(ia),
        "ia_modelo": str(ia.get("model") or "")[:128],
        "ia_provider": str(ia.get("provider") or "")[:64],
        "resumo": str(payload.get("resumo") or "")[:20000],
        "ficha_ia": str(payload.get("ficha_ia") or ia.get("text") or "")[:200000],
        "analise": analise,
        "browser": browser[:40],
        "fontes": [str(fonte) for fonte in (payload.get("fontes") or [])][:40],
    }
    try:
        client.index(index=ANALISES_EMPRESA_INDEX, id=doc_id, document=doc, refresh=True)
    except Exception as exc:
        return {"error": str(exc)}
    return {"saved": True, "doc_id": doc_id, "index": ANALISES_EMPRESA_INDEX, "atualizado_em": now}




def list_analises_empresa(
    *,
    nif: Optional[str] = None,
    nome: Optional[str] = None,
    pais: Optional[str] = None,
    limit: int = 50,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Análises guardadas (mais recentes primeiro), sem a fotografia completa."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    ensure_indices(client)
    filtros: List[Dict[str, Any]] = []
    if nif:
        filtros.append({"term": {"nif": str(nif).strip()}})
    if pais:
        filtros.append({"term": {"pais": str(pais).upper()}})
    if nome:
        filtros.append({"match": {"nome": {"query": str(nome), "operator": "and"}}})
    body = {
        "size": max(1, min(int(limit or 50), 200)),
        "track_total_hits": True,
        "query": {"bool": {"filter": filtros}} if filtros else {"match_all": {}},
        "sort": [{"atualizado_em": {"order": "desc", "missing": "_last"}}],
        "_source": {
            "excludes": ["analise", "browser", "ficha_ia", "regras"],
        },
    }
    try:
        resp = client.search(index=ANALISES_EMPRESA_INDEX, body=body)
    except Exception as exc:
        return {"error": str(exc), "items": []}
    items = []
    for hit in (resp.get("hits") or {}).get("hits") or []:
        src = dict(hit.get("_source") or {})
        src.pop("resumo", None)
        items.append(src)
    total = ((resp.get("hits") or {}).get("total") or {}).get("value")
    return {"items": items, "total": total if total is not None else len(items)}




def get_analise_empresa(doc_id: str, *, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Análise guardada por id (`<pais>:<nif>`), com a fotografia completa."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    chave = str(doc_id or "").strip()
    if not chave:
        return {"error": "Id em falta"}
    ensure_indices(client)
    try:
        resp = client.get(index=ANALISES_EMPRESA_INDEX, id=chave)
    except Exception as exc:
        return {"error": "não encontrada", "detail": str(exc), "doc_id": chave}
    return {"doc_id": chave, **(resp.get("_source") or {})}




def delete_analise_empresa(doc_id: str, *, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Apaga uma análise guardada."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    chave = str(doc_id or "").strip()
    if not chave:
        return {"error": "Id em falta"}
    ensure_indices(client)
    try:
        client.delete(index=ANALISES_EMPRESA_INDEX, id=chave, refresh=True)
    except Exception as exc:
        return {"error": "não encontrada", "detail": str(exc)}
    return {"apagada": chave}
