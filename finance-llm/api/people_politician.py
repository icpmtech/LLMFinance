"""Enriquecimento de políticos: perfil técnico, perfil biográfico, notícias do partido e grafo de eventos.

Este módulo estende o PessoasIQ para deputados e políticos indexados a partir do
Parlamento.pt e da Wikipédia. Para cada pessoa sintetiza:

- **perfil técnico** — atividade parlamentar/cargos, partido, comissões,
  legislaturas e intervenções públicas, a partir dos dados indexados e da web;
- **perfil biográfico** — trajetória pessoal, formação, notoriedade e linha do
tempo, usando factos internos + evidência da web + Wikipédia;
- **notícias do partido** — recolha federada (Search360 + web) sobre o partido
  do político;
- **grafo de relações políticas** — ligações a partido, cargos, colegas do
  mesmo partido e eventos/notícias em que é mencionado.

Tudo é devolvido ao vivo; os textos de perfil podem ser guardados em
`finance_node_summaries` para reutilização.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from starlette.concurrency import run_in_threadpool

from api import search360_service as search360
from api.elasticsearch_client import (
    get_es_client,
    get_node_summary,
    get_person_by_nif,
    index_node_summary,
    search_people,
    search_social,
)

logger = logging.getLogger(__name__)

PROFILE_MAX_TOKENS = 1800

_SYSTEM_TECHNICAL = (
    "És analista político do IQ OS. Escreves um perfil técnico, em português de Portugal, "
    "sobre um político português. Usa apenas os dados e a evidência fornecidos: não inventes "
    "factos, datas, cargos nem processos. Estrutura a resposta em Markdown com: "
    "1. Resumo executivo (3–5 linhas); "
    "2. Atividade parlamentar/política e cargos; "
    "3. Partido e afiliações; "
    "4. Comissões, legislaturas ou eventos relevantes; "
    "5. Posições públicas e notoriedade; "
    "6. Fontes e limitações. "
    "Sé sóbrio, objectivo e citas a web com [n]."
)

_SYSTEM_BIOGRAPHICAL = (
    "És biógrafo institucional do IQ OS. Escreves um perfil biográfico curto, em português de "
    "Portugal, sobre um político português. Usa apenas os dados fornecidos: não inventes datas, "
    "familiares, formações ou eventos. Estrutura em Markdown com: "
    "1. Linha do tempo resumida; "
    "2. Formação e percurso profissional (se existir); "
    "3. Trajetória política; "
    "4. Notoriedade pública; "
    "5. Fontes e o que ficou por confirmar."
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_party(party: Optional[str]) -> Optional[str]:
    if not party:
        return None
    party = str(party).strip()
    if party.lower() in ("independent", "independente", "sem partido", "n/a", "na"):
        return None
    return party


def _person_party(person: Dict[str, Any]) -> Optional[str]:
    """Extrai o partido de vários campos possíveis."""
    for key in ("metadata.party", "party"):
        if "." in key:
            top, sub = key.split(".", 1)
            meta = person.get(top) or {}
            if isinstance(meta, dict) and meta.get(sub):
                return _normalize_party(meta.get(sub))
        elif person.get(key):
            return _normalize_party(person.get(key))
    metadata = person.get("metadata") or {}
    if isinstance(metadata, dict):
        for candidate in (metadata.get("party"), metadata.get("partido")):
            if candidate:
                return _normalize_party(candidate)
    # Tenta extrair de texto biográfico ou de notas.
    biography = str(person.get("biography") or "")
    for line in biography.splitlines():
        low = line.lower()
        if "partido" in low:
            for tok in line.replace(",", " ").replace(".", " ").split():
                if tok and tok[0].isupper() and len(tok) > 2:
                    return _normalize_party(tok)
    return None


def _person_office(person: Dict[str, Any]) -> Optional[str]:
    metadata = person.get("metadata") or {}
    for key in ("office", "cargo", "mandato", "term"):
        if metadata.get(key):
            return str(metadata[key]).strip()
    return None


def _person_legislature(person: Dict[str, Any]) -> Optional[str]:
    metadata = person.get("metadata") or {}
    for key in ("legislature", "legislatura", "term"):
        if metadata.get(key):
            return str(metadata[key]).strip()
    return None


# ---------------------------------------------------------------------------
# Notícias do partido
# ---------------------------------------------------------------------------
def _party_queries(party: str, person_name: Optional[str] = None) -> List[str]:
    """Consultas para notícias sobre o partido (com contexto português)."""
    base = party.strip()
    queries = [
        f"{base} Portugal partido político notícias",
        f"{base} política Portugal",
        f"{base} eleições Portugal",
    ]
    if person_name:
        queries.insert(0, f"{person_name} {base} Portugal")
    return list(dict.fromkeys(queries))


async def party_news(
    party: str,
    *,
    person_name: Optional[str] = None,
    limit: int = 12,
) -> Dict[str, Any]:
    """Notícias e artigos sobre o partido, via Search360 (web + interno + Wikipédia)."""
    if not party:
        return {"party": None, "total": 0, "items": [], "warnings": []}

    # Usa uma consulta abrangente; o Search360 já federará fontes.
    query = f"{party} Portugal partido político"
    if person_name:
        query = f"{person_name} {query}"

    try:
        payload = await search360.search(
            query,
            sources_ids=["internal", "web", "wikipedia_pt"],
            limit=max(6, min(limit, 30)),
        )
    except Exception as exc:
        logger.warning("Search360 falhou para notícias do partido %s: %s", party, exc)
        return {"party": party, "total": 0, "items": [], "warnings": [str(exc)]}

    # Normaliza itens para um formato simples.
    items: List[Dict[str, Any]] = []
    for entry in (payload.get("items") or [])[:limit]:
        items.append({
            "title": entry.get("title") or entry.get("label") or "",
            "url": entry.get("url") or "",
            "snippet": entry.get("snippet") or "",
            "date": entry.get("date") or entry.get("published") or entry.get("year"),
            "source_id": entry.get("source_id") or entry.get("source_family") or "web",
            "kind": entry.get("kind") or "news",
            "score": float(entry.get("score") or 0),
        })

    return {
        "party": party,
        "total": len(items),
        "items": items,
        "facets": payload.get("facets") or {},
        "warnings": payload.get("warnings") or [],
        "query": query,
    }


# ---------------------------------------------------------------------------
# Colegas do mesmo partido
# ---------------------------------------------------------------------------
def _co_party_people(
    party: str,
    exclude_nif: str,
    *,
    size: int = 20,
) -> List[Dict[str, Any]]:
    """Outras pessoas indexadas com o mesmo partido."""
    result = search_people(party=party, size=max(5, min(size, 50)))
    if result.get("error"):
        return []
    out: List[Dict[str, Any]] = []
    for item in result.get("items") or []:
        nif = item.get("nif")
        if not nif or nif == exclude_nif:
            continue
        meta = item.get("metadata") or {}
        out.append({
            "nif": nif,
            "name": item.get("name"),
            "party": _person_party(item),
            "office": meta.get("office") or meta.get("cargo") or None,
            "photo_path": item.get("photo_path") or meta.get("photo_path"),
            "source": item.get("source") or meta.get("source"),
        })
    return out


# ---------------------------------------------------------------------------
# Evidência da web/Wikipédia sobre o político
# ---------------------------------------------------------------------------
def _web_evidence_for_person(person: Dict[str, Any], *, limit: int = 6) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Devolve `(evidência, consultas)` da web para o nome do político."""
    name = str(person.get("name") or "").strip()
    nif = str(person.get("nif") or "").strip()
    if not name:
        return [], []

    try:
        from api import social_collectors as collectors  # noqa: PLC0415
    except Exception as exc:
        logger.debug("social_collectors indisponível: %s", exc)
        return [], []

    queries = list(dict.fromkeys([f'"{name}" Portugal político', f'"{name}" deputado', f'"{name}"']))
    evidence: List[Dict[str, Any]] = []
    report: List[Dict[str, Any]] = []
    seen: set = set()
    for query in queries:
        try:
            outcome = collectors.search_web(query, limit=limit)
        except Exception as exc:
            report.append({"query": query, "error": str(exc)})
            continue
        report.append({"query": query, "engine": outcome.get("engine") or "", "items": len(outcome.get("items") or [])})
        for row in outcome.get("items") or []:
            url = str(row.get("url") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            evidence.append({
                "title": str(row.get("title") or "")[:300],
                "url": url,
                "snippet": str(row.get("snippet") or "")[:600],
                "engine": row.get("engine") or "",
                "query": query,
                "source": "web",
            })
    return evidence, report


async def _wiki_evidence_for_person(person: Dict[str, Any], *, limit: int = 2) -> List[Dict[str, Any]]:
    """Wikipédia PT como fonte de referência para perfil biográfico."""
    name = str(person.get("name") or "").strip()
    if not name:
        return []
    try:
        import httpx  # noqa: PLC0415
        from api import search360_sources as sources  # noqa: PLC0415
    except Exception as exc:
        logger.debug("Fontes de referência indisponíveis: %s", exc)
        return []

    out: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": "IQOS/1.0 (perfil politico)"}) as client:
            articles = await sources.wikipedia_search(client, name, lang="pt", limit=limit)
            for entry in articles[:1]:
                title = str(entry.get("title") or "")
                if not title:
                    continue
                page = await sources.wikipedia_page(client, title, lang="pt")
                summary = page.get("summary") or {}
                out.append({
                    "title": f"Wikipédia (PT): {title}",
                    "url": summary.get("url") or entry.get("url"),
                    "snippet": str(summary.get("description") or entry.get("snippet") or "")[:600],
                    "page_text": str(summary.get("extract") or "")[:1200],
                    "engine": "wikipedia",
                    "query": name,
                    "source": "wikipedia",
                })
    except Exception as exc:
        logger.info("Wikipédia para perfil político falhou: %s", exc)
    return out


# ---------------------------------------------------------------------------
# Perfis com IA
# ---------------------------------------------------------------------------
def _facts_block(person: Dict[str, Any], party: Optional[str]) -> Dict[str, Any]:
    """Bloco de factos internos para os prompts."""
    metadata = person.get("metadata") or {}
    return {
        "nome": person.get("name"),
        "nif": person.get("nif"),
        "partido": party,
        "cargo": _person_office(person),
        "legislatura": _person_legislature(person),
        "fonte": person.get("source") or metadata.get("source"),
        "biografia": (person.get("biography") or "")[:2000],
        "metadados": {k: v for k, v in metadata.items() if not isinstance(v, (list, dict)) or k in ("birth_date", "nationality", "occupation")},
        "cargos": [
            {
                "cargo": role.get("role"),
                "entidade": role.get("company_name"),
                "nif_entidade": role.get("company_nif"),
                "data": role.get("date"),
                "origem": role.get("role_org"),
                "acto": role.get("acto"),
            }
            for role in (person.get("latest_roles") or person.get("roles") or [])[:30]
        ],
    }


def _prompt_technical(facts: Dict[str, Any], evidence: Sequence[Dict[str, Any]], party_news: Sequence[Dict[str, Any]]) -> str:
    return (
        "Escreve o **perfil técnico** deste político português, em Markdown, com as secções indicadas.\n\n"
        "Factos internos (JSON):\n"
        f"{json.dumps(facts, ensure_ascii=False, default=str)[:9000]}\n\n"
        "Evidência da web (com números para citação):\n"
        f"{json.dumps([{'n': i, 'titulo': e.get('title'), 'url': e.get('url'), 'resumo': e.get('snippet')} for i, e in enumerate(evidence[:10], start=1)], ensure_ascii=False)[:7000]}\n\n"
        "Notícias do partido (contexto):\n"
        f"{json.dumps([{'n': i, 'titulo': n.get('title'), 'url': n.get('url'), 'data': n.get('date')} for i, n in enumerate(party_news[:8], start=1)], ensure_ascii=False)[:5000]}\n\n"
        "Máximo 500 palavras. Não inventes factos."
    )


def _prompt_biographical(facts: Dict[str, Any], evidence: Sequence[Dict[str, Any]]) -> str:
    return (
        "Escreve o **perfil biográfico** desta pessoa, em Markdown, com as secções indicadas.\n\n"
        "Factos internos (JSON):\n"
        f"{json.dumps(facts, ensure_ascii=False, default=str)[:9000]}\n\n"
        "Evidência da web/Wikipédia (com números para citação):\n"
        f"{json.dumps([{'n': i, 'titulo': e.get('title'), 'url': e.get('url'), 'resumo': e.get('snippet'), 'texto': e.get('page_text')} for i, e in enumerate(evidence[:10], start=1)], ensure_ascii=False)[:9000]}\n\n"
        "Máximo 450 palavras. Não inventes datas, familiares ou factos não confirmados."
    )


def _resolve_backend(session: Any, backend: Optional[str] = None) -> Tuple[Dict[str, Any], Optional[str]]:
    """Resolve modelo cloud, recuando para o primeiro fornecedor configurado."""
    try:
        from api import ontology_ai as ai  # noqa: PLC0415
        from api import providers_service  # noqa: PLC0415
    except Exception as exc:
        return {"kind": "unavailable", "note": f"IA indisponível ({exc})."}, None

    chosen = ai.available_backend(session, backend)
    if chosen.get("kind") == "cloud" or backend:
        return chosen, None

    user_id = getattr(getattr(session, "user", None), "id", None)
    try:
        catalog = providers_service.provider_catalog(user_id)
    except Exception:
        catalog = {"providers": []}
    for item in catalog.get("providers") or []:
        if item.get("kind") != "cloud" or not item.get("configured"):
            continue
        candidate = ai.available_backend(session, f"{item['id']}:{item.get('default_model') or ''}")
        if candidate.get("kind") == "cloud":
            return candidate, (
                f"O utilizador não tem modelo predefinido: usou-se {item['id']} "
                f"({item.get('key_source') or 'ambiente'})."
            )
    return chosen, None


async def _generate_profile(
    person: Dict[str, Any],
    party: Optional[str],
    evidence: Sequence[Dict[str, Any]],
    party_news: Sequence[Dict[str, Any]],
    *,
    session: Any = None,
    backend: Optional[str] = None,
    technical: bool = True,
) -> Dict[str, Any]:
    """Gera perfil técnico ou biográfico com LLM, ou factual se não houver modelo."""
    facts = _facts_block(person, party)
    outcome: Dict[str, Any] = {"mode": "factual", "text": "", "notes": [], "warnings": []}

    try:
        chosen, fallback_note = _resolve_backend(session, backend)
    except Exception as exc:
        chosen = {"kind": "unavailable"}
        outcome["warnings"].append(f"IA indisponível ({exc}).")

    if fallback_note:
        outcome["notes"].append(fallback_note)
    outcome["backend"] = {"kind": chosen.get("kind"), "provider": chosen.get("provider"), "model": chosen.get("model")}

    if chosen.get("kind") != "cloud":
        note = chosen.get("note") or "Sem modelo configurado: perfil montado só com factos."
        outcome["notes"].append(note)
        outcome["text"] = _factual_profile(person, party, facts, evidence, party_news, technical=technical)
        return outcome

    try:
        from api import ontology_ai as ai  # noqa: PLC0415
    except Exception as exc:
        outcome["warnings"].append(f"IA indisponível ({exc}); perfil factual.")
        outcome["text"] = _factual_profile(person, party, facts, evidence, party_news, technical=technical)
        return outcome

    system = _SYSTEM_TECHNICAL if technical else _SYSTEM_BIOGRAPHICAL
    prompt = _prompt_technical(facts, evidence, party_news) if technical else _prompt_biographical(facts, evidence)
    try:
        text = await ai.ask_model(
            chosen,
            system=system,
            prompt=prompt,
            max_tokens=PROFILE_MAX_TOKENS,
            temperature=0.25,
        )
    except Exception as exc:
        outcome["warnings"].append(f"A IA falhou ({exc}); perfil factual.")
        outcome["text"] = _factual_profile(person, party, facts, evidence, party_news, technical=technical)
        return outcome

    if not text:
        outcome["warnings"].append("A IA devolveu texto vazio; perfil factual.")
        outcome["text"] = _factual_profile(person, party, facts, evidence, party_news, technical=technical)
        return outcome

    outcome["mode"] = "ai"
    outcome["text"] = text
    outcome["notes"].append(f"Perfil redigido por {chosen.get('provider')}:{chosen.get('model')}.")
    return outcome


def _factual_profile(
    person: Dict[str, Any],
    party: Optional[str],
    facts: Dict[str, Any],
    evidence: Sequence[Dict[str, Any]],
    party_news: Sequence[Dict[str, Any]],
    *,
    technical: bool = True,
) -> str:
    """Versão sem IA do perfil."""
    lines: List[str] = [f"# {'Perfil técnico' if technical else 'Perfil biográfico'} — {person.get('name')}", ""]
    lines.append(f"**NIF:** {person.get('nif')}")
    if party:
        lines.append(f"**Partido:** {party}")
    if facts.get("cargo"):
        lines.append(f"**Cargo:** {facts['cargo']}")
    if facts.get("legislatura"):
        lines.append(f"**Legislatura:** {facts['legislatura']}")
    lines.append(f"**Fonte:** {facts.get('fonte') or '—'}")
    lines.append("")

    if technical:
        lines += ["## Atividade e cargos", ""]
        for role in facts.get("cargos") or []:
            if role.get("cargo") or role.get("entidade"):
                lines.append(f"- {role.get('cargo') or 'Cargo'} em {role.get('entidade') or '—'} ({role.get('data') or '—'})")
        if not facts.get("cargos"):
            lines.append("- Sem cargos indexados para este político.")
        lines.append("")
        if party_news:
            lines += ["## Contexto do partido", ""]
            for news in party_news[:6]:
                lines.append(f"- {news.get('title')} ({news.get('date') or '—'})")
            lines.append("")
    else:
        lines += ["## Biografia (factos indexados)", ""]
        bio = person.get("biography") or ""
        if bio:
            lines.append(bio[:1200])
        else:
            lines.append("Sem biografia indexada.")
        lines.append("")

    if evidence:
        lines += ["## Ligações encontradas", ""]
        for i, entry in enumerate(evidence[:6], start=1):
            lines.append(f"{i}. [{entry.get('title') or entry.get('url')}]({entry.get('url')}) — {str(entry.get('snippet') or '')[:160]}")
        lines.append("")

    lines.append(f"*Perfil montado sem modelo de IA em {_now()}.*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Grafo de relações políticas / eventos
# ---------------------------------------------------------------------------
def build_political_graph(
    person: Dict[str, Any],
    party: Optional[str],
    co_party: Sequence[Dict[str, Any]],
    party_news: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Grafo pessoa → partido → colegas → eventos/notícias."""
    nif = str(person.get("nif") or "")
    name = str(person.get("name") or nif)
    person_id = f"person:{nif}"

    nodes: Dict[str, Dict[str, Any]] = {
        person_id: {
            "id": person_id,
            "type": "person",
            "kind": "politician",
            "label": name,
            "nif": nif,
            "party": party,
            "photo_path": person.get("photo_path") or (person.get("metadata") or {}).get("photo_path"),
        }
    }
    edges: List[Dict[str, Any]] = []

    # Partido
    if party:
        party_id = f"party:{party.lower().replace(' ', '_')}"
        nodes[party_id] = {"id": party_id, "type": "party", "kind": "party", "label": party}
        edges.append({
            "source": person_id,
            "target": party_id,
            "label": "membro",
            "relation_label": "membro de",
            "type": "party_membership",
            "count": 1,
        })

    # Cargo/legislatura como nó
    office = _person_office(person)
    legislature = _person_legislature(person)
    if office:
        office_id = f"office:{office.lower().replace(' ', '_')[:40]}"
        nodes[office_id] = {"id": office_id, "type": "office", "kind": "office", "label": office}
        edges.append({
            "source": person_id,
            "target": office_id,
            "label": "ocupa",
            "relation_label": "ocupa cargo",
            "type": "holds_office",
            "count": 1,
        })
    if legislature:
        leg_id = f"legislature:{str(legislature).lower().replace(' ', '_')[:40]}"
        nodes[leg_id] = {"id": leg_id, "type": "legislature", "kind": "legislature", "label": str(legislature)}
        edges.append({
            "source": person_id,
            "target": leg_id,
            "label": "legislatura",
            "relation_label": "na legislatura",
            "type": "in_legislature",
            "count": 1,
        })

    # Colegas do mesmo partido
    for colleague in co_party[:30]:
        cnif = colleague.get("nif")
        cname = colleague.get("name") or cnif
        if not cnif:
            continue
        cid = f"person:{cnif}"
        nodes[cid] = {
            "id": cid,
            "type": "person",
            "kind": "colleague",
            "label": cname,
            "nif": cnif,
            "party": party,
            "photo_path": colleague.get("photo_path"),
        }
        edges.append({
            "source": person_id,
            "target": cid,
            "label": "colega",
            "relation_label": "colega de partido",
            "type": "co_party",
            "count": 1,
        })

    # Eventos/notícias do partido ou que mencionam o político
    for i, news in enumerate(party_news[:20]):
        title = str(news.get("title") or "Notícia")
        url = str(news.get("url") or "")
        event_id = f"event:{i}_{party.lower().replace(' ', '_')[:20] if party else 'news'}"
        nodes[event_id] = {
            "id": event_id,
            "type": "event",
            "kind": "news",
            "label": title[:80],
            "url": url,
            "date": news.get("date"),
            "source_id": news.get("source_id"),
        }
        edges.append({
            "source": person_id,
            "target": event_id,
            "label": "mencionado",
            "relation_label": "contexto / mencionado",
            "type": "mentioned_in_event",
            "count": 1,
        })
        if party:
            party_id = f"party:{party.lower().replace(' ', '_')}"
            edges.append({
                "source": party_id,
                "target": event_id,
                "label": "notícia",
                "relation_label": "notícia sobre",
                "type": "party_news",
                "count": 1,
            })

    return {
        "person_nif": nif,
        "person_name": name,
        "party": party,
        "nodes": list(nodes.values()),
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "meta": {
            "co_party_count": len(co_party),
            "party_news_count": len(party_news),
        },
    }


# ---------------------------------------------------------------------------
# Orquestração principal
# ---------------------------------------------------------------------------
async def enrich_politician(
    nif: str,
    *,
    session: Any = None,
    backend: Optional[str] = None,
    limit_party_news: int = 12,
    max_co_party: int = 20,
    save: bool = True,
    reuse_hours: float = 0.0,
) -> Dict[str, Any]:
    """Devolve perfil técnico, biográfico, notícias do partido e grafo político."""
    nif = str(nif or "").strip()
    if not nif:
        return {"error": "NIF em falta."}

    # Reutilizar resumo gravado se pedido.
    if reuse_hours and reuse_hours > 0:
        node_id = f"person:{nif}"
        previous = await run_in_threadpool(get_node_summary, node_id)
        if previous.get("summary"):
            generated = str(previous.get("generated_at") or "")
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(generated.replace("Z", "+00:00"))).total_seconds() / 3600
            except Exception:
                age = None
            if age is not None and age <= reuse_hours:
                return {
                    "nif": nif,
                    "name": previous.get("name"),
                    "cached": True,
                    "technical_profile": previous.get("facts", {}).get("technical_profile"),
                    "biographical_profile": previous.get("facts", {}).get("biographical_profile"),
                    "party_news": previous.get("facts", {}).get("party_news"),
                    "political_graph": previous.get("facts", {}).get("political_graph"),
                    "generated_at": generated,
                }

    person = await run_in_threadpool(get_person_by_nif, nif)
    if person.get("error") or not person.get("name"):
        return {"error": person.get("error") or f"Pessoa {nif} não encontrada.", "nif": nif}

    party = _person_party(person)

    # Recolhas em paralelo.
    news_task = party_news(party, person_name=person.get("name"), limit=limit_party_news) if party else None
    evidence_task = run_in_threadpool(_web_evidence_for_person, person, limit=6)
    wiki_task = _wiki_evidence_for_person(person, limit=2)
    co_party_task = run_in_threadpool(_co_party_people, party or "", nif, size=max_co_party) if party else None

    party_news_data = await news_task if news_task else {"party": None, "total": 0, "items": []}
    web_evidence, _ = await evidence_task
    wiki_evidence = await wiki_task
    co_party = await co_party_task if co_party_task else []

    evidence = list(dict.fromkeys([e.get("url") for e in [*web_evidence, *wiki_evidence]]))
    evidence = [e for e in [*web_evidence, *wiki_evidence] if e.get("url") in evidence]

    # Perfis (técnico e biográfico) podem correr em paralelo.
    technical_task = _generate_profile(
        person, party, evidence, party_news_data.get("items") or [],
        session=session, backend=backend, technical=True,
    )
    biographical_task = _generate_profile(
        person, party, evidence, party_news_data.get("items") or [],
        session=session, backend=backend, technical=False,
    )
    technical_profile, biographical_profile = await asyncio.gather(technical_task, biographical_task)

    graph = build_political_graph(person, party, co_party, party_news_data.get("items") or [])

    result: Dict[str, Any] = {
        "nif": nif,
        "name": person.get("name"),
        "party": party,
        "generated_at": _now(),
        "technical_profile": technical_profile,
        "biographical_profile": biographical_profile,
        "party_news": party_news_data,
        "political_graph": graph,
        "evidence_count": len(evidence),
        "cached": False,
    }

    if save:
        try:
            await run_in_threadpool(
                index_node_summary,
                {
                    "node_id": f"person:{nif}",
                    "nif": nif,
                    "name": person.get("name"),
                    "kind": "person",
                    "summary": technical_profile.get("text") or biographical_profile.get("text") or "",
                    "mode": technical_profile.get("mode"),
                    "provider": technical_profile.get("backend", {}).get("provider"),
                    "model": technical_profile.get("backend", {}).get("model"),
                    "facts": {
                        "technical_profile": technical_profile,
                        "biographical_profile": biographical_profile,
                        "party_news": party_news_data,
                        "political_graph": graph,
                        "party": party,
                    },
                    "evidence": evidence,
                    "evidence_count": len(evidence),
                    "queries": [party] if party else [],
                    "generated_at": result["generated_at"],
                },
            )
            result["saved"] = True
        except Exception as exc:
            logger.warning("Não foi possível guardar resumo político de %s: %s", nif, exc)
            result["saved"] = False

    return result
