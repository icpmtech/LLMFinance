"""Resumo de um nó de grafo (pessoa, empresa ou site) com IA e pesquisa na web.

Qualquer nó dos grafos do IQ OS — uma pessoa do PessoasIQ, uma empresa, uma
entidade contratual ou um site onde a pessoa aparece — pode ter um resumo:

1. **Factos internos** — ficha do societário/CIRE (cargos, insolvências, co-intervenientes),
   conteúdos sociais já recolhidos e, quando aplicável, a pontuação de risco.
2. **Pesquisa na web** — o nome (com o NIF, para desambiguar homónimos) e leitura
   das páginas mais relevantes, para trazer o que não está nos índices internos.
3. **Resumo redigido** pelo modelo configurado (ou, sem modelo, um resumo factual
   montado com factos e evidência).
4. **Gravação obrigatória** do resultado em `finance_node_summaries` — o texto, a
   evidência e os factos ficam lá, e reabrir o nó volta a mostrar o último resumo
   sem gastar tokens.

O resumo distingue sempre o que vem dos índices do IQ OS (facto) do que vem da
web (indício por confirmar) e diz o que ficou por confirmar.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from api import social_collectors as collectors
from api.elasticsearch_client import (
    cire_person_processes,
    get_es_client,
    get_node_summary,
    get_person_by_nif,
    index_node_summary,
    search_social,
)
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

#: Tipos de nó aceites (o mesmo vocabulário do grafo da UI).
NODE_KINDS = ("person", "company", "entity", "source")

#: Páginas lidas por resumo (a leitura completa é lenta; a evidência da pesquisa chega sempre).
MAX_PAGES = 4
#: Carateres de texto guardados por página lida.
PAGE_TEXT_CHARS = 1200

_SYSTEM = (
    "És analista do IQ OS e escreves resumos curtos, em português de Portugal, sobre pessoas, "
    "empresas e sites. Usa apenas os dados e a evidência fornecidos: não inventes factos, números, "
    "processos, nomes nem ligações. Separa sempre o que vem dos índices internos (facto) do que vem "
    "da web (indício por confirmar) e termina com o que ficou por confirmar. Sé sóbrio: sem adjetivos "
    "de valor, sem juízos sobre a pessoa."
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_node(
    *,
    node_id: Optional[str] = None,
    nif: Optional[str] = None,
    kind: Optional[str] = None,
    name: Optional[str] = None,
) -> Tuple[str, str, str]:
    """Normaliza a referência do nó: devolve `(node_id, nif, kind)`."""
    node_id = str(node_id or "").strip()
    kind = str(kind or "").strip().lower()
    nif = str(nif or "").strip()
    if node_id and ":" in node_id:
        prefix, _, rest = node_id.partition(":")
        prefix = prefix.strip().lower()
        if prefix in NODE_KINDS:
            kind = kind or prefix
            nif = nif or rest.strip()
    if not kind:
        kind = "person" if nif.isdigit() and len(nif) == 9 else ("source" if nif else "person")
    if not node_id:
        node_id = f"{kind}:{nif or (name or '').strip()}"
    return node_id, nif, kind


# ------------------------------------------------------------------ factos
def _social_facts(nif: str, name: str, kind: str) -> Dict[str, Any]:
    """Conteúdos já recolhidos sobre o nó (por pessoa, ou por nome para empresas)."""
    page = search_social(person_nif=nif, size=40, sort="recent") if nif else {"items": [], "total": 0}
    if not (page.get("items") or []) and name:
        page = search_social(q=f'"{name}"', size=20, sort="relevance")
    items = page.get("items") or []
    return {
        "total": page.get("total") or 0,
        "plataformas": page.get("facets", {}).get("platforms") or [],
        "sentimento": page.get("sentiment") or {},
        "imagens": sum(1 for item in items if item.get("image")),
        "videos": sum(1 for item in items if item.get("video")),
        "textos": [
            {
                "plataforma": item.get("platform"),
                "titulo": str(item.get("title") or "")[:200],
                "texto": str(item.get("text") or "")[:300],
                "url": item.get("url"),
                "data": item.get("published_at") or item.get("collected_at"),
                "sentimento": item.get("sentiment"),
            }
            for item in items[:12]
        ],
    }


def gather_facts(node_id: str, nif: str, name: str, kind: str) -> Dict[str, Any]:
    """Factos internos do nó: ficha de pessoa, insolvências, risco e conteúdos sociais."""
    facts: Dict[str, Any] = {
        "identificacao": {"node_id": node_id, "nif": nif or None, "nome": name or None, "tipo": kind},
    }

    person: Dict[str, Any] = {}
    if nif:
        person = get_person_by_nif(nif) or {}
        if person.get("error"):
            person = {}
    if person:
        facts["ficha_pessoas"] = {
            "nome": person.get("name") or name,
            "pessoa_coletiva": bool(person.get("is_company")),
            "fontes": person.get("sources") or ([person.get("source")] if person.get("source") else []),
            "cargos": person.get("roles_count") or len(person.get("roles") or []),
            "empresas": person.get("companies_count") or len(person.get("companies") or []),
            "primeiro_registo": person.get("first_seen"),
            "ultimo_registo": person.get("last_seen"),
        }
        facts["cargos"] = [
            {
                "cargo": role.get("role"),
                "entidade": role.get("company_name"),
                "nif_entidade": role.get("company_nif"),
                "data": role.get("date"),
                "origem": role.get("role_org"),
                "acto": role.get("acto"),
            }
            for role in (person.get("latest_roles") or person.get("roles") or [])[:15]
        ]

    cire: Dict[str, Any] = {}
    if nif:
        cire = cire_person_processes(nif, size=50) or {}
        if cire.get("total") or cire.get("processes"):
            facts["insolvencias"] = {
                "publicacoes": cire.get("total"),
                "papeis": cire.get("by_papel"),
                "comarcas": cire.get("tribunais"),
                "anos": cire.get("years"),
                "processos": [
                    {
                        "processo": process.get("processo"),
                        "especie": process.get("especie"),
                        "tribunal": process.get("tribunal"),
                        "data": process.get("date"),
                        "papeis": process.get("papeis"),
                        "insolvente": process.get("insolvente"),
                    }
                    for process in (cire.get("processes") or [])[:10]
                ],
                "co_intervenientes": [
                    {
                        "nome": entry.get("name"),
                        "nif": entry.get("nif"),
                        "processos": entry.get("processes"),
                        "papeis": [role.get("key") for role in (entry.get("papeis") or [])],
                    }
                    for entry in (cire.get("co_intervenientes") or [])[:10]
                ],
            }

    facts["conteudos_recolhidos"] = _social_facts(nif, name, kind)

    if person and (cire.get("total") or person.get("roles")):
        try:
            from api.people_360 import build_risk  # noqa: PLC0415

            social_bundle = {"total": facts["conteudos_recolhidos"]["total"], "texts": facts["conteudos_recolhidos"]["textos"]}
            facts["risco"] = build_risk(person, cire, social_bundle)
        except Exception as exc:  # pragma: no cover - salvaguarda
            logger.debug("Cálculo de risco falhou no resumo de %s: %s", node_id, exc)
    return facts


# ------------------------------------------------------------------ evidência
def _queries_for(name: str, nif: str, kind: str) -> List[str]:
    """Consultas de pesquisa para o nó (nome + NIF; empresas com insolvência)."""
    name = (name or "").strip()
    if not name:
        return []
    queries = [f'"{name}" {nif}'.strip(), f'"{name}"']
    if kind in ("company", "entity"):
        queries.append(f'"{name}" insolvência')
    else:
        queries.append(f'"{name}" insolvência processo')
    return list(dict.fromkeys(queries))


def _relevant(entry: Dict[str, Any], tokens: Sequence[str]) -> bool:
    """Diz se a evidência fala mesmo do nó (pelo menos dois tokens do nome)."""
    if not tokens:
        return True
    haystack = " ".join([
        str(entry.get("title") or ""),
        str(entry.get("snippet") or ""),
        str(entry.get("page_text") or ""),
    ]).lower()
    if not haystack.strip():
        return False
    hits = sum(1 for token in tokens if token in haystack)
    return hits >= min(2, len(tokens))


def _name_tokens(name: str) -> List[str]:
    """Tokens úteis do nome (sem partículas curtas como «de», «da»)."""
    return [token for token in re.split(r"[^\wÀ-ÿ]+", (name or "").lower()) if len(token) > 2]


def web_evidence(
    name: str,
    nif: str,
    kind: str,
    *,
    limit: int = 6,
    pages: int = 2,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """Pesquisa o nó na web e lê algumas páginas. Devolve `(evidência, consultas, páginas lidas)`."""
    queries = _queries_for(name, nif, kind)
    evidence: List[Dict[str, Any]] = []
    report: List[Dict[str, Any]] = []
    seen: set = set()
    for query in queries:
        outcome = collectors.search_web(query, limit=limit)
        report.append({
            "query": query,
            "engine": outcome.get("engine") or "",
            "items": len(outcome.get("items") or []),
            "error": outcome.get("error") or None,
        })
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
                "page_text": "",
            })

    # Só interessa o que fala do nó: uma pesquisa pelo nome traz páginas
    # genéricas (portais, legislação). Se nada passar o filtro, fica o que veio.
    tokens = _name_tokens(name)
    relevant = [entry for entry in evidence if _relevant(entry, tokens)]
    if relevant:
        evidence = relevant

    pages = max(0, min(int(pages or 0), MAX_PAGES))
    read = 0
    for entry in evidence:
        if read >= pages:
            break
        try:
            post = collectors.collect_web_page(entry["url"], tags=["resumo-no"])
        except collectors.CollectorError:
            continue
        except Exception as exc:  # pragma: no cover - salvaguarda
            logger.debug("Leitura de %s falhou: %s", entry["url"], exc)
            continue
        text = str(post.get("text") or "")[:PAGE_TEXT_CHARS]
        entry["page_text"] = text
        entry["title"] = entry["title"] or str(post.get("title") or "")[:300]
        entry["site"] = (post.get("data") or {}).get("site")
        if post.get("media"):
            entry["media"] = {k: v for k, v in (post.get("media") or {}).items() if v}
        read += 1
    return evidence, report, read


async def reference_evidence(name: str, *, limit: int = 4) -> List[Dict[str, Any]]:
    """Evidência de referência: Wikipédia (PT) e Wikidata.

    Serve de rede de segurança quando o motor de pesquisa está bloqueado por
    ritmo: são fontes abertas, sem chave, que devolvem texto citável.
    """
    name = (name or "").strip()
    if not name:
        return []
    try:
        import httpx  # noqa: PLC0415

        from api import search360_sources as sources  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover
        logger.debug("Fontes de referência indisponíveis: %s", exc)
        return []

    out: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": "IQOS/1.0 (analise de entidades)"}) as client:
            articles = await sources.wikipedia_search(client, name, lang="pt", limit=limit)
            for entry in articles[:2]:
                title = str(entry.get("title") or "")
                if not title:
                    continue
                page = await sources.wikipedia_page(client, title, lang="pt")
                summary = (page.get("summary") or {})
                out.append({
                    "title": f"Wikipédia (PT): {title}",
                    "url": summary.get("url") or entry.get("url"),
                    "snippet": str(summary.get("description") or entry.get("snippet") or "")[:600],
                    "page_text": str(summary.get("extract") or "")[:PAGE_TEXT_CHARS],
                    "engine": "wikipedia",
                    "query": name,
                })
            entities = await sources.wikidata_search(client, name, lang="pt", limit=limit)
            for entry in entities[:2]:
                title = str(entry.get("title") or entry.get("data", {}).get("label") or "")
                if not title:
                    continue
                out.append({
                    "title": f"Wikidata: {title}",
                    "url": entry.get("url"),
                    "snippet": str(entry.get("snippet") or entry.get("subtitle") or "")[:600],
                    "page_text": "",
                    "engine": "wikidata",
                    "query": name,
                })
    except Exception as exc:
        logger.info("Evidência de referência falhou: %s", exc)
    return out


# ------------------------------------------------------------------ resumo
def _prompt(node_id: str, facts: Dict[str, Any], evidence: Sequence[Dict[str, Any]]) -> str:
    lines = [
        "Escreve um **resumo** deste nó de grafo, em Markdown, com as secções:",
        "1. **Quem/o que é** (2–4 linhas);",
        "2. **Presença e papéis** (cargos, empresas, processos de insolvência, se existirem);",
        "3. **O que a web acrescenta** (só o que estiver na evidência, citando [n]);",
        "4. **Sinais de risco** (se houver; cada um com a evidência que o sustenta);",
        "5. **Por confirmar** (o que não ficou esclarecido).",
        "",
        "Máximo: 350 palavras. Se um dado não existir, diz que não foi encontrado.",
        "",
        "Factos dos índices do IQ OS (JSON):",
        json.dumps(facts, ensure_ascii=False, default=str)[:9000],
        "",
        "Evidência da web (JSON, com número para citação):",
        json.dumps(
            [
                {
                    "n": index,
                    "titulo": entry.get("title"),
                    "url": entry.get("url"),
                    "resumo": entry.get("snippet"),
                    "texto_lido": (entry.get("page_text") or "")[:700],
                }
                for index, entry in enumerate(evidence[:12], start=1)
            ],
            ensure_ascii=False,
        )[:9000],
    ]
    return "\n".join(lines)


def factual_summary(name: str, facts: Dict[str, Any], evidence: Sequence[Dict[str, Any]]) -> str:
    """Resumo sem modelo: só factos internos e ligações encontradas."""
    lines: List[str] = [f"# {name or 'Nó do grafo'}", ""]
    identificacao = facts.get("identificacao") or {}
    lines.append(
        f"**{identificacao.get('nome') or name}** — {identificacao.get('tipo') or 'nó do grafo'}"
        + (f" · NIF {identificacao.get('nif')}" if identificacao.get("nif") else "")
    )
    lines.append("")

    ficha = facts.get("ficha_pessoas")
    if ficha:
        lines += ["## Factos nos índices do IQ OS", ""]
        lines.append(
            f"- {ficha.get('cargos', 0)} cargo(s) em {ficha.get('empresas', 0)} empresa(s)"
            + (f" · registos de {ficha.get('primeiro_registo')} a {ficha.get('ultimo_registo')}" if ficha.get("primeiro_registo") else "")
        )
        for cargo in (facts.get("cargos") or [])[:6]:
            lines.append(f"- {cargo.get('cargo') or 'Cargo'} em {cargo.get('entidade') or '—'} ({cargo.get('data') or '—'})")

    insolvencias = facts.get("insolvencias")
    if insolvencias:
        papeis = ", ".join(f"{row['key']}: {row['count']}" for row in (insolvencias.get("papeis") or []))
        lines += ["", "## Processos de insolvência (CIRE)", "", f"- {insolvencias.get('publicacoes')} publicação(ões). Papéis: {papeis or '—'}."]
        for process in (insolvencias.get("processos") or [])[:5]:
            lines.append(f"- {process.get('processo') or '—'} · {process.get('especie') or '—'} · {process.get('tribunal') or '—'} · {process.get('data') or '—'}")

    risco = facts.get("risco")
    if risco:
        lines += ["", "## Risco", "", f"- Pontuação {risco.get('score')}/100 ({risco.get('level')}), confiança {risco.get('confidence')}."]
        for factor in (risco.get("factors") or [])[:5]:
            lines.append(f"- {factor.get('label')}: {factor.get('evidence')}")

    conteudos = facts.get("conteudos_recolhidos") or {}
    if conteudos.get("total"):
        lines += ["", "## Conteúdos recolhidos", "", f"- {conteudos.get('total')} registo(s); {conteudos.get('imagens', 0)} imagem(ns), {conteudos.get('videos', 0)} vídeo(s)."]
        for texto in (conteudos.get("textos") or [])[:5]:
            lines.append(f"- [{texto.get('plataforma') or 'web'}] {str(texto.get('titulo') or texto.get('texto'))[:140]} — {texto.get('url')}")

    if evidence:
        lines += ["", "## O que a web acrescenta", ""]
        for index, entry in enumerate(evidence[:8], start=1):
            lines.append(f"{index}. [{entry.get('title') or entry.get('url')}]({entry.get('url')}) — {str(entry.get('snippet') or entry.get('page_text') or '')[:200]}")
    else:
        lines += ["", "## O que a web acrescenta", "", "- A pesquisa na web não devolveu resultados utilizáveis."]

    lines += ["", f"*Resumo montado sem modelo de IA em {_now()}: apenas factos dos índices e ligações encontradas.*"]
    return "\n".join(lines)


async def node_summary(
    *,
    node_id: Optional[str] = None,
    nif: Optional[str] = None,
    kind: Optional[str] = None,
    name: Optional[str] = None,
    session: Any = None,
    backend: Optional[str] = None,
    limit: int = 6,
    pages: int = 2,
    reuse_hours: float = 0.0,
) -> Dict[str, Any]:
    """Gera (com IA e web) o resumo de um nó e **guarda-o sempre** no Elasticsearch.

    ``reuse_hours`` > 0 reaproveita o último resumo gravado se for mais recente do
    que esse número de horas (sem gastar tokens). Com o valor por omissão (0)
    gera sempre e substitui o anterior.
    """
    node_id, nif, kind = normalize_node(node_id=node_id, nif=nif, kind=kind, name=name)
    person_for_name = await run_in_threadpool(get_person_by_nif, nif) if nif else {}
    if not name:
        name = str((person_for_name or {}).get("name") or "")

    if reuse_hours and reuse_hours > 0:
        previous = await run_in_threadpool(get_node_summary, node_id)
        if previous.get("summary"):
            generated = str(previous.get("generated_at") or "")
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(generated.replace("Z", "+00:00"))).total_seconds() / 3600
            except Exception:
                age = None
            if age is not None and age <= reuse_hours:
                return {**previous, "cached": True, "saved": False, "notes": [f"Resumo gravado há {age:.1f} h (reaproveitado)."]}

    result: Dict[str, Any] = {
        "node_id": node_id,
        "nif": nif,
        "name": name,
        "kind": kind,
        "notes": [],
        "warnings": [],
    }

    # Tudo o que é síncrono (Elasticsearch e leitura de páginas) corre no threadpool:
    # dentro do event loop, a pesquisa web bloquearia a aplicação inteira.
    facts = await run_in_threadpool(gather_facts, node_id, nif, name, kind)
    if not name:
        name = str((facts.get("ficha_pessoas") or {}).get("nome") or "")
        result["name"] = name

    evidence, queries, pages_read = await run_in_threadpool(
        web_evidence, name, nif, kind, limit=limit, pages=pages
    )
    known = {entry.get("url") for entry in evidence if entry.get("url")}
    reference = await reference_evidence(name)
    added = [entry for entry in reference if entry.get("url") and entry["url"] not in known]
    evidence = [*evidence, *added]
    result["queries"] = queries
    result["evidence"] = evidence
    result["pages_read"] = pages_read + sum(1 for entry in added if entry.get("page_text"))
    if added:
        result["notes"].append(f"Evidência de referência acrescentada (Wikipédia/Wikidata): {len(added)} resultado(s).")

    mode = "factual"
    text = ""
    if name:
        try:
            from api.people_360 import resolve_backend  # noqa: PLC0415

            chosen, fallback_note = resolve_backend(session, backend)
        except Exception as exc:  # pragma: no cover
            chosen, fallback_note = {"kind": "unavailable"}, None
            result["warnings"].append(f"IA indisponível ({exc}).")
        if fallback_note:
            result["notes"].append(fallback_note)
        result["backend"] = {"kind": chosen.get("kind"), "provider": chosen.get("provider"), "model": chosen.get("model")}
        if chosen.get("kind") == "cloud":
            try:
                from api import ontology_ai as ai  # noqa: PLC0415

                text = await ai.ask_model(
                    chosen,
                    system=_SYSTEM,
                    prompt=_prompt(node_id, facts, evidence),
                    max_tokens=1200,
                    temperature=0.2,
                )
            except Exception as exc:
                result["warnings"].append(f"A IA falhou ({exc}); resumo factual.")
        elif chosen.get("kind") == "unavailable":
            result["notes"].append(chosen.get("note") or "Sem chave de API para o modelo: resumo factual.")
        else:
            result["notes"].append("Sem modelo configurado: resumo factual.")
    else:
        result["warnings"].append("Nó sem nome: não há o que pesquisar nem resumir.")

    if text:
        mode = "ai"
        summary = text.strip()
        result["notes"].append(
            f"Resumo redigido por {result.get('backend', {}).get('provider')}:{result.get('backend', {}).get('model')} "
            f"a partir dos índices do IQ OS e de {len(evidence)} resultado(s) da web."
        )
    else:
        summary = factual_summary(name, facts, evidence)

    result.update({
        "summary": summary,
        "mode": mode,
        "facts": facts,
        "evidence": evidence,
        "evidence_count": len(evidence),
        "generated_at": _now(),
    })

    saved = await run_in_threadpool(
        index_node_summary,
        {
            "node_id": node_id,
            "nif": nif,
            "name": name,
            "kind": kind,
            "summary": summary,
            "mode": mode,
            "provider": (result.get("backend") or {}).get("provider") or "",
            "model": (result.get("backend") or {}).get("model") or "",
            "queries": [entry.get("query") for entry in queries],
            "evidence": evidence,
            "facts": facts,
            "pages_read": pages_read,
            "generated_at": result["generated_at"],
        },
    )
    result["saved"] = bool(saved.get("saved"))
    result["generations"] = saved.get("generations")
    result["cached"] = False
    if saved.get("error"):
        result["warnings"].append(f"Não foi possível guardar o resumo: {saved['error']}")
    else:
        result["notes"].append("Resumo guardado em `finance_node_summaries` (reabrir o nó volta a mostrá-lo).")
    return result


def saved_summary(
    *,
    node_id: Optional[str] = None,
    nif: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Último resumo gravado de um nó (sem gerar nada)."""
    node_id, nif, _kind = normalize_node(node_id=node_id, nif=nif, name=name)
    stored = get_node_summary(node_id, nif=nif or None, name=name or None)
    if not stored:
        return {"node_id": node_id, "found": False}
    return {**stored, "found": True, "cached": True}
