from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from api.elasticsearch_client import WORLD_RELATIONS_INDEX, get_es_client
from api.ontology_ai import ask_model, available_backend
from api.tools import web_search

logger = logging.getLogger(__name__)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _entity_query(nif: str, name: Optional[str], query: Optional[str]) -> str:
    if query and query.strip():
        return query.strip()
    return f"{name or nif} empresa Portugal".strip()


def _extract_top_sources(results: List[Dict[str, Any]], limit: int = 6) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in results or []:
        url = str(item.get("href") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        cleaned.append({
            "title": _safe_text(item.get("title") or item.get("name") or ""),
            "url": url,
            "snippet": _safe_text(item.get("body") or item.get("snippet") or ""),
            "source": str(item.get("source") or "web").strip(),
        })
        if len(cleaned) >= limit:
            break
    return cleaned


def _fetch_page_text(url: str, timeout: int = 12) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    text = resp.text or ""
    soup = BeautifulSoup(text, "html.parser")
    body = soup.get_text(" ", strip=True)
    return _safe_text(body)[:8000]


def _local_ollama_model(timeout: int = 3) -> Optional[str]:
    """Modelo local instalado no Ollama (ignora os que correm na cloud).

    Serve de último recurso quando o utilizador não escolheu nenhum fornecedor:
    sem isto a extração estruturada ficava sempre vazia.
    """
    try:
        resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=timeout)
        resp.raise_for_status()
        models = [str(m.get("name") or "") for m in (resp.json().get("models") or [])]
    except Exception:
        return None
    local = [name for name in models if name and not name.endswith(":cloud")]
    return local[0] if local else None


async def _ask_structured_fields(name: str, sources: List[Dict[str, Any]], nif: str, session: Any = None) -> Dict[str, Any]:
    backend = available_backend(session)
    if backend.get("kind") != "cloud":
        # Sem fornecedor escolhido nas Configurações: tenta o Ollama local, se existir.
        model = _local_ollama_model()
        if model:
            local_backend = available_backend(session, backend=f"ollama:{model}")
            if local_backend.get("kind") == "cloud":
                backend = local_backend
    if backend.get("kind") != "cloud":
        note = (
            "Sem fornecedor de IA configurado: escolha um modelo cloud nas Configurações "
            "(ou arranque o Ollama local) para a extração estruturada."
            if backend.get("kind") == "local"
            else "Fornecedor de IA indisponível (sem chave de API)."
        )
        return {
            "entity_name": name,
            "nif": nif,
            "country": "Portugal",
            "status": "unknown",
            "description": "",
            "contacts": [],
            "addresses": [],
            "brands": [],
            "parent_company": None,
            "related_entities": [],
            "notes": [note],
        }

    prompt = f"""
    A partir das fontes abaixo, extrai um JSON válido com estes campos:
    - entity_name (string)
    - legal_name (string ou null)
    - country (string)
    - status (string: active, unknown, inactive)
    - description (string)
    - contacts (lista de strings)
    - addresses (lista de strings)
    - brands (lista de strings)
    - parent_company (string ou null)
    - related_entities (lista de objetos com {{"name": string, "kind": string, "evidence": string}})
    - notes (lista de strings)

    Atenção: não inventes dados. Se não houver informação explícita, usa [] ou null.

    Empresa: {name}
    NIF: {nif}
    Fontes:
    {json.dumps(sources, ensure_ascii=False, indent=2)[:12000]}
    """
    raw = await ask_model(
        backend,
        system="És um analista de empresas. Devolves apenas JSON válido em português de Portugal.",
        prompt=prompt,
        max_tokens=2000,
        temperature=0.1,
    )
    text = str(raw or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidate = text[start : end + 1]
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {
        "entity_name": name,
        "nif": nif,
        "country": "Portugal",
        "status": "unknown",
        "description": "",
        "contacts": [],
        "addresses": [],
        "brands": [],
        "parent_company": None,
        "related_entities": [],
        "notes": [],
    }


def _save_entity_doc(nif: str, name: str, payload: Dict[str, Any], summary: Dict[str, Any]) -> bool:
    from api.elasticsearch_client import ENTITIES_INDEX, ensure_indices

    doc = {
        "nif": nif,
        "name": name,
        "enrichment_web": payload,
        "enrichment_last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "enrichment_summary": summary,
    }
    client = get_es_client(request_timeout=30)
    if client is None:
        return False
    try:
        ensure_indices(client)
    except Exception:
        pass
    # O cadastro de entidades usa IDs no formato "finance_entities:<nif>".
    doc_id = f"{ENTITIES_INDEX}:{nif}"
    try:
        client.update(index=ENTITIES_INDEX, id=doc_id, body={"doc": doc, "doc_as_upsert": True}, refresh=True)
        return True
    except Exception:
        try:
            client.index(index=ENTITIES_INDEX, id=doc_id, document=doc, refresh=True)
            return True
        except Exception:
            return False


def _canonical_kind(kind: Any) -> str:
    """Normaliza o tipo de relação para um vocabulário fixo da ontologia.

    O LLM devolve rótulos livres («Divisão/Subsidiária», «empresa-mãe»); sem isto
    a mesma relação aparecia com dois nomes e duplicava o grafo.
    """
    raw = _safe_text(kind).lower()
    if not raw:
        return "related"
    slug = re.sub(r"[^a-z0-9]+", "_", raw.replace("ã", "a").replace("ç", "c").replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")).strip("_")
    aliases = {
        "parent": "parent_company",
        "parent_company": "parent_company",
        "empresa_mae": "parent_company",
        "grupo": "parent_company",
        "grupo_empresa_mae": "parent_company",
        "holding": "parent_company",
        "mother_company": "parent_company",
        "subsidiary": "subsidiary",
        "subsidiaria": "subsidiary",
        "divisao_subsidiaria": "subsidiary",
        "divisao": "subsidiary",
        "filial": "subsidiary",
        "division": "subsidiary",
        "supplier": "supplier",
        "fornecedor": "supplier",
        "customer": "customer",
        "cliente": "customer",
        "shareholder": "shareholder",
        "socio": "shareholder",
        "acionista": "shareholder",
        "partner": "partner",
        "parceiro": "partner",
        "joint_venture": "partner",
        "person": "person",
        "pessoa": "person",
        "gerente": "person",
        "administrador": "person",
    }
    return aliases.get(slug, slug or "related")


def _save_relations(nif: str, name: str, links: List[Dict[str, Any]]) -> int:
    from api.elasticsearch_client import ensure_indices

    client = get_es_client(request_timeout=30)
    if client is None or not links:
        return 0
    try:
        ensure_indices(client)
    except Exception:
        pass
    saved = 0
    for link in links:
        source_name = str(link.get("source_name") or name)
        source_ref = str(link.get("source_ref") or nif)
        target_ref = str(link.get("target_ref") or "")
        target_name = str(link.get("target_name") or link.get("target") or "")
        if not target_ref or source_ref == target_ref:
            continue
        relation_id = f"{link.get('kind','related')}:{source_ref}>{target_ref}"
        evidence = [str(link.get("evidence") or "")]
        # A mesma aresta pode voltar noutra recolha: junta as provas em vez de as trocar.
        try:
            previous = client.get(index=WORLD_RELATIONS_INDEX, id=relation_id)["_source"]
            for item in previous.get("evidence") or []:
                if item and item not in evidence:
                    evidence.append(str(item))
        except Exception:
            pass
        doc = {
            "relation_id": relation_id,
            "kind": str(link.get("kind") or "related"),
            "source_ref": source_ref,
            "source_name": source_name,
            "source_type": str(link.get("source_type") or "empresa"),
            "target_ref": target_ref,
            "target_name": target_name,
            "target_type": str(link.get("target_type") or "entidade"),
            "evidence": evidence,
            "country": str(link.get("country") or "Portugal"),
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        try:
            client.index(index=WORLD_RELATIONS_INDEX, id=relation_id, document=doc, refresh=True)
            saved += 1
        except Exception:
            continue
    return saved


def _generate_pdf_report(nif: str, name: str, payload: Dict[str, Any]) -> Optional[str]:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except Exception:
        return None

    out_dir = Path(__file__).resolve().parents[1] / "data" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"entity_{nif}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.pdf"
    path = out_dir / file_name

    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle(f"Relatório da entidade {name}")
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, 800, f"Entidade: {name}")
    c.setFont("Helvetica", 11)
    c.drawString(50, 780, f"NIF: {nif}")
    y = 750
    facts = payload.get("summary") or payload.get("facts") or {}
    lines = [
        f"País: {facts.get('country') or 'N/D'}",
        f"Status: {facts.get('status') or 'N/D'}",
        f"Parent company: {facts.get('parent_company') or 'N/D'}",
        f"Fontes: {facts.get('source_count') or 0}",
    ]
    for line in lines:
        if y < 80:
            c.showPage()
            y = 780
        c.drawString(50, y, line[:120])
        y -= 18
    c.save()
    return str(path)


async def enrich_entity(nif: str, payload: Optional[Dict[str, Any]] = None, session: Any = None) -> Dict[str, Any]:
    """Enriquece uma entidade com web, scraping e IA, guardando resultado no Elasticsearch.

    `session` (opcional) identifica o utilizador para resolver o fornecedor de IA
    configurado; sem ela a extração estruturada cai no caminho sem LLM.
    """
    data = dict(payload or {})
    entity_name = str(data.get("entity_name") or "").strip()
    query = str(data.get("query") or "").strip()
    max_results = max(1, min(12, int(data.get("max_results") or 6)))
    max_pages = max(1, min(8, int(data.get("max_pages") or 3)))
    use_web = bool(data.get("use_web", True))
    use_scraper = bool(data.get("use_scraper", True))
    save_relations = bool(data.get("save_relations", True))
    generate_pdf = bool(data.get("generate_pdf", False))

    # Neste ponto a ficha da entidade existe no cadastro. Se o código do chamador só tiver o NIF,
    # tentamos recuperar o nome no Elasticsearch para produzir uma pesquisa útil.
    base_name = entity_name or ""
    if not base_name:
        from api.elasticsearch_client import get_entity_by_nif

        entity = get_entity_by_nif(nif)
        base_name = str((entity or {}).get("name") or "")

    search_query = _entity_query(nif, base_name, query)
    summary: Dict[str, Any] = {"query": search_query, "source_count": 0, "links": []}
    search_results: List[Dict[str, Any]] = []

    if use_web:
        try:
            web_results = web_search(search_query, max_results=max_results)
            search_results = _extract_top_sources(web_results, limit=max_results)
            summary["links"] = search_results
            summary["source_count"] = len(search_results)
        except Exception as exc:
            logger.warning("Falha ao pesquisar web para %s: %s", nif, exc)

    page_texts: List[str] = []
    if use_scraper and search_results:
        for item in search_results[:max_pages]:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            try:
                page_texts.append(_fetch_page_text(url))
            except Exception as exc:
                logger.warning("Falha ao raspar %s: %s", url, exc)

    facts = await _ask_structured_fields(base_name or nif, search_results, nif, session=session)
    facts.setdefault("entity_name", base_name or nif)
    facts.setdefault("nif", nif)
    facts.setdefault("country", "Portugal")
    facts.setdefault("status", "unknown")
    facts.setdefault("description", "")
    facts.setdefault("contacts", [])
    facts.setdefault("addresses", [])
    facts.setdefault("brands", [])
    facts.setdefault("parent_company", None)
    facts.setdefault("related_entities", [])
    facts.setdefault("notes", [])

    combined = {
        "entity_name": facts.get("entity_name") or base_name or nif,
        "nif": nif,
        "country": facts.get("country") or "Portugal",
        "status": facts.get("status") or "unknown",
        "description": facts.get("description") or "",
        "contacts": facts.get("contacts") or [],
        "addresses": facts.get("addresses") or [],
        "brands": facts.get("brands") or [],
        "parent_company": facts.get("parent_company"),
        "related_entities": facts.get("related_entities") or [],
        "notes": facts.get("notes") or [],
        "sources": search_results,
        "page_text_chars": sum(len(text) for text in page_texts),
        "pages_scraped": len(page_texts),
        "enriched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if page_texts:
        combined["page_text_preview"] = " ".join(page_texts[:3])[:2000]

    summary.update({
        "country": combined.get("country"),
        "status": combined.get("status"),
        "parent_company": combined.get("parent_company"),
        "contact_count": len(combined.get("contacts") or []),
        "address_count": len(combined.get("addresses") or []),
        "brand_count": len(combined.get("brands") or []),
        "related_count": len(combined.get("related_entities") or []),
    })
    combined["summary"] = summary

    saved = _save_entity_doc(nif, base_name or nif, combined, summary)

    relations: List[Dict[str, Any]] = []
    if save_relations:
        for rel in facts.get("related_entities") or []:
            target_name = str(rel.get("name") or "").strip()
            target_ref = str(rel.get("nif") or rel.get("ref") or target_name).strip()
            if not target_ref:
                continue
            relations.append({
                "kind": _canonical_kind(rel.get("kind") or "related"),
                "source_ref": nif,
                "source_name": base_name or nif,
                "source_type": "empresa",
                "target_ref": target_ref,
                "target_name": target_name,
                "target_type": "entidade",
                "evidence": str(rel.get("evidence") or ""),
                "country": combined.get("country") or "Portugal",
            })
        if combined.get("parent_company"):
            relations.append({
                "kind": "parent_company",
                "source_ref": nif,
                "source_name": base_name or nif,
                "source_type": "empresa",
                "target_ref": str(combined["parent_company"]).strip(),
                "target_name": str(combined["parent_company"]).strip(),
                "target_type": "empresa",
                "evidence": "Parent company mentioned in online sources",
                "country": combined.get("country") or "Portugal",
            })

    relation_count = _save_relations(nif, base_name or nif, relations) if save_relations else 0

    report = None
    if generate_pdf:
        pdf_path = _generate_pdf_report(nif, base_name or nif, combined)
        if pdf_path:
            report = {
                "generated": True,
                "path": pdf_path,
                "title": f"Relatório da entidade {base_name or nif}",
                "size_bytes": Path(pdf_path).stat().st_size if Path(pdf_path).exists() else None,
            }

    fields_added: Dict[str, Any] = {
        "country": combined.get("country"),
        "status": combined.get("status"),
        "description": combined.get("description"),
        "contacts_count": len(combined.get("contacts") or []),
        "addresses_count": len(combined.get("addresses") or []),
        "brands_count": len(combined.get("brands") or []),
        "parent_company": combined.get("parent_company"),
        "related_entities_count": len(combined.get("related_entities") or []),
        "sources_count": len(search_results),
        "pages_scraped": len(page_texts),
    }
    return {
        "nif": nif,
        "name": base_name or nif,
        "query": search_query,
        "status": "ok",
        "saved": saved,
        "enriched_at": combined.get("enriched_at"),
        "fields_added": fields_added,
        "source_count": len(search_results),
        "relation_count": relation_count,
        "summary": summary,
        "report": report,
        "message": f"Entidade {nif} enriquecida — {len(search_results)} fontes, {relation_count} relações."
                    + (" Relatório PDF gerado." if report else ""),
        "error": None,
    }
