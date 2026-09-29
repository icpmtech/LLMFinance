"""Análise 360 de uma pessoa do PessoasIQ: risco, relações e ficha analítica.

Junta três camadas de informação:

1. **Ficha** — o que o IQ OS já sabe: cargos do societário e participações nos
   processos de insolvência (CIRE), que o `finance_people` já agrega por pessoa.
2. **Social** — imagens, vídeos e textos recolhidos das redes sociais e da
   internet (`finance_social`, ligados por `person_nif`).
3. **Risco** — pontuação **explicável**: cada fator diz quantos pontos dá, de
   onde vem a evidência e em que sentido conta (a favor ou contra).

Tudo sai num só objeto: `risk`, `graph` (grafo de relações), `timeline` e
`analysis` (a ficha analítica em Markdown, redigida por IA quando há modelo
configurado e, sem ele, montada apenas com os factos).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

from api.elasticsearch_client import (
    cire_person_processes,
    get_person_by_nif,
    search_social,
)
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

#: Papéis que colocam a pessoa no lado passivo do processo (risco próprio).
_DEBTOR_PAPEIS = ("Insolvente", "Devedor", "Requerido")
#: Papéis profissionais (a pessoa atua nomeada pelo tribunal, não é parte interessada).
_PROFESSIONAL_PAPEIS = (
    "Administrador Insolvência",
    "Administrador da insolvência",
    "Administrador de insolvência",
    "Administrador da Insolvência",
    "Gestor Judicial",
    "Gestor judicial",
    "Fiduciário",
)


def is_professional_papel(papel: Any) -> bool:
    """Diz se o papel é de nomeação pelo tribunal (administrador/gestor da insolvência).

    O CIRE grava o papel como `Administrador Insolvência`; as fichas do PessoasIQ
    usam `Administrador da insolvência`. A comparação é tolerante para os dois.
    """
    low = str(papel or "").strip().lower()
    if not low:
        return False
    if "insolv" in low and ("administrador" in low or "gestor" in low):
        return True
    return low in ("gestor judicial", "fiduciário", "fiduciario")
#: Palavras que, no que é publicado sobre a pessoa, merecem nota.
_RISK_WORDS = {
    "insolvência": 2, "insolvencia": 2, "penhora": 2, "penhorado": 2,
    "fraude": 3, "fraudulento": 3, "burla": 3, "crime": 3, "arguido": 3,
    "dívida": 1, "dívidas": 1, "incumprimento": 2, "arresto": 2,
    "processo": 1, "tribunal": 1, "execução": 2, "despedimento": 1,
    "falência": 3, "revitalização": 1, "credor": 1, "devedor": 2,
}

#: Limites de saída do grafo (o grafo da UI tem de continuar legível).
MAX_COMPANY_NODES = 40
MAX_CO_INTERVENIENTES = 25
MAX_SOCIAL_NODES = 10

RISK_LEVELS = ((15, "baixo"), (35, "médio"), (60, "alto"), (101, "crítico"))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _level(score: float) -> str:
    for limit, label in RISK_LEVELS:
        if score < limit:
            return label
    return "crítico"


# --------------------------------------------------------------- social
def social_bundle(nif: str, *, size: int = 200) -> Dict[str, Any]:
    """Publicações sociais ligadas à pessoa, com imagens, vídeos e sentimento."""
    page = search_social(person_nif=str(nif), size=size, sort="recent")
    if page.get("error"):
        return {"total": 0, "items": [], "images": [], "videos": [], "by_platform": [], "error": page["error"]}

    items = page.get("items") or []
    images: List[Dict[str, Any]] = []
    videos: List[Dict[str, Any]] = []
    texts: List[Dict[str, Any]] = []
    for item in items:
        url = str(item.get("url") or "")
        title = str(item.get("title") or "")
        text = str(item.get("text") or "")
        entry = {
            "url": url,
            "title": title,
            "text": text,
            "platform": item.get("platform"),
            "kind": item.get("kind"),
            "date": item.get("published_at") or item.get("collected_at"),
            "sentiment": item.get("sentiment"),
            "sentiment_score": item.get("sentiment_score"),
        }
        image = str(item.get("image") or "")
        video = str(item.get("video") or "")
        kind = str(item.get("kind") or "")
        # A imagem de um vídeo é a miniatura: fica com o vídeo, não na galeria.
        if image and kind != "video":
            images.append({**entry, "image": image})
        if video:
            videos.append({**entry, "video": video, "thumbnail": image})
        # Textos: páginas/perfis com conteúdo (as imagens e os vídeos têm as suas listas).
        if (title or text) and kind not in ("image", "video"):
            texts.append(entry)

    return {
        "total": page.get("total") or 0,
        "items": items,
        "images": images[:60],
        "videos": videos[:40],
        "texts": texts[:80],
        "by_platform": page.get("facets", {}).get("platforms") or [],
        "by_sentiment": page.get("facets", {}).get("sentiment") or [],
        "sentiment": page.get("sentiment") or {},
        "last_collected": max((str(item.get("collected_at") or "") for item in items), default="") or None,
    }


def _social_risk(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fatores de risco tirados do que é publicado sobre a pessoa."""
    factors: List[Dict[str, Any]] = []
    items = [item for item in (bundle.get("texts") or []) if item]
    negatives = [item for item in items if str(item.get("sentiment") or "") == "negativo"]
    positives = [item for item in items if str(item.get("sentiment") or "") == "positivo"]
    scores = [float(item.get("sentiment_score") or 0.0) for item in items if item.get("sentiment")]
    media = sum(scores) / len(scores) if scores else 0.0

    if len(items) >= 3 and media <= -0.15:
        points = min(8.0, round(abs(media) * 12, 1))
        factors.append({
            "key": "sentimento_negativo",
            "label": "Publicações com tom negativo",
            "points": points,
            "level": "médio",
            "direction": "risco",
            "evidence": f"{len(negatives)} de {len(items)} textos negativos (polaridade média {media:+.2f}).",
        })

    hits: Dict[str, int] = {}
    for item in items:
        text = f"{item.get('title') or ''} {item.get('text') or ''}".lower()
        for word, weight in _RISK_WORDS.items():
            if word in text:
                hits[word] = hits.get(word, 0) + weight
    if hits:
        points = float(min(6, sum(hits.values()) // 2 or 1))
        top = ", ".join(sorted(hits, key=lambda word: -hits[word])[:5])
        factors.append({
            "key": "palavras_risco",
            "label": "Menções de risco nos conteúdos recolhidos",
            "points": points,
            "level": "médio" if points >= 4 else "baixo",
            "direction": "risco",
            "evidence": f"Palavras encontradas: {top}.",
        })

    if positives and not negatives:
        factors.append({
            "key": "sentimento_positivo",
            "label": "Publicações com tom positivo",
            "points": -3.0,
            "level": "baixo",
            "direction": "atenuante",
            "evidence": f"{len(positives)} textos com tom positivo.",
        })
    return factors


# --------------------------------------------------------------- risco
def _cire_risk(cire: Dict[str, Any], person: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fatores de risco tirados dos processos de insolvência."""
    factors: List[Dict[str, Any]] = []
    by_papel = {str(row["key"]): int(row["count"]) for row in (cire.get("by_papel") or [])}
    debtor = sum(by_papel.get(papel, 0) for papel in _DEBTOR_PAPEIS)
    if debtor:
        points = min(45.0, 22.0 + (debtor - 1) * 8.0)
        factors.append({
            "key": "insolvente",
            "label": "Insolvente/devedor em processos judiciais",
            "points": round(points, 1),
            "level": "alto" if debtor > 1 else "médio",
            "direction": "risco",
            "evidence": f"{debtor} processo(s) em que a pessoa é parte passiva (insolvente, devedor ou requerido).",
        })
    elif int(cire.get("total") or 0) == 0 and not by_papel:
        factors.append({
            "key": "sem_processos",
            "label": "Sem processos de insolvência registados",
            "points": 0.0,
            "level": "informativo",
            "direction": "informativo",
            "evidence": "O NIF não aparece em nenhuma publicação do CIRE indexada.",
        })

    # Empresas da ficha que entram no processo como insolventes/devedoras.
    # Um administrador da insolvência contracena por ofício com empresas
    # insolventes: nesse caso os processos **não** são risco próprio da pessoa.
    insolvent_companies = [
        entry for entry in (cire.get("co_intervenientes") or [])
        if any(str(role.get("key") or "") in _DEBTOR_PAPEIS for role in (entry.get("papeis") or []))
    ]
    role_companies = {str(role.get("company_nif") or "") for role in (person.get("roles") or []) if role.get("company_nif")}
    linked = [entry for entry in insolvent_companies if str(entry.get("nif") or "") in role_companies]

    total_papeis = sum(by_papel.values()) or 1
    professional = sum(count for papel, count in by_papel.items() if is_professional_papel(papel))
    professional_share = professional / total_papeis
    own_side = sum(by_papel.get(papel, 0) for papel in _DEBTOR_PAPEIS)
    appointed_only = professional_share >= 0.6 and own_side == 0

    if linked and not appointed_only:
        names = ", ".join(str(entry.get("name"))[:40] for entry in linked[:3])
        factors.append({
            "key": "empresas_insolventes",
            "label": "Cargos em empresas com processo de insolvência",
            "points": round(min(30.0, 10.0 * len(linked)), 1),
            "level": "alto" if len(linked) > 1 else "médio",
            "direction": "risco",
            "evidence": f"{len(linked)} empresa(s) da ficha são parte passiva nos mesmos processos: {names}.",
        })
    elif linked:
        factors.append({
            "key": "empresas_insolventes_oficio",
            "label": "Contacto com empresas insolventes por função nomeada",
            "points": 0.0,
            "level": "informativo",
            "direction": "informativo",
            "evidence": (
                f"{len(linked)} empresa(s) da ficha constam dos processos em que a pessoa participa como "
                f"administrador/gestor nomeado pelo tribunal — não é risco próprio."
            ),
        })

    credor = by_papel.get("Credor", 0)
    if credor >= 10:
        factors.append({
            "key": "credor_muitos_processos",
            "label": "Credor em muitos processos",
            "points": float(min(10, 2 + credor // 20)),
            "level": "médio" if credor >= 50 else "baixo",
            "direction": "risco",
            "evidence": f"A pessoa é credora em {credor} processo(s) — exposição a incobráveis.",
        })

    professional = sum(count for papel, count in by_papel.items() if is_professional_papel(papel))
    if professional:
        factors.append({
            "key": "administrador_insolvencia",
            "label": "Administrador da insolvência (função profissional)",
            "points": -5.0,
            "level": "informativo",
            "direction": "atenuante",
            "evidence": f"{professional} processo(s) em que participa como administrador/gestor nomeado pelo tribunal.",
        })
    return factors


def _structure_risk(person: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fatores ligados à estrutura societária da pessoa."""
    factors: List[Dict[str, Any]] = []
    roles = person.get("roles") or []
    companies = person.get("companies_count") or len(person.get("companies") or [])
    management = [r for r in roles if any(
        word in str(r.get("role") or "").lower()
        for word in ("gerente", "administrador", "diretor", "presidente", "vogal", "sócio", "socio")
    )]
    if management:
        factors.append({
            "key": "cargos_gestao",
            "label": "Cargos de gestão em empresas",
            "points": float(min(6, len(management) // 2)),
            "level": "baixo",
            "direction": "informativo",
            "evidence": f"{len(management)} cargo(s) de gestão/sociedade em {companies} empresa(s).",
        })
    return factors


def build_risk(person: Dict[str, Any], cire: Dict[str, Any], social: Dict[str, Any]) -> Dict[str, Any]:
    """Pontuação de risco explicável (0–100) com os fatores que a compõem."""
    factors = [
        *_cire_risk(cire, person),
        *_structure_risk(person),
        *_social_risk(social),
    ]
    score = max(0.0, min(100.0, sum(float(f.get("points") or 0.0) for f in factors)))
    positives = [f for f in factors if float(f.get("points") or 0) > 0]
    confidence = "baixa"
    data_points = int(cire.get("total") or 0) + len(person.get("roles") or []) + int(social.get("total") or 0)
    if data_points >= 20:
        confidence = "alta"
    elif data_points >= 5:
        confidence = "média"
    return {
        "score": round(score, 1),
        "level": _level(score),
        "factors": sorted(factors, key=lambda f: -abs(float(f.get("points") or 0))),
        "risk_factors": len(positives),
        "confidence": confidence,
        "data_points": data_points,
        "disclaimer": (
            "Pontuação indicativa, calculada apenas a partir dos dados públicos indexados no IQ OS "
            "(societário, CIRE e conteúdos recolhidos). Não substitui análise de crédito ou jurídica."
        ),
    }


# --------------------------------------------------------------- grafo
def build_relations_graph(
    person: Dict[str, Any],
    cire: Dict[str, Any],
    social: Dict[str, Any],
) -> Dict[str, Any]:
    """Grafo de relações: pessoa ↔ empresas, ↔ co-intervenientes e ↔ presenças digitais."""
    nif = str(person.get("nif") or "")
    name = str(person.get("name") or nif)
    person_id = f"person:{nif}"
    nodes: Dict[str, Dict[str, Any]] = {
        person_id: {"id": person_id, "type": "person", "label": name, "nif": nif, "is_company": bool(person.get("is_company"))}
    }
    edges: List[Dict[str, Any]] = []

    # 1. Empresas onde tem cargos (com o nº de cargos por empresa).
    per_company: Dict[str, Dict[str, Any]] = {}
    for role in person.get("roles") or []:
        cnif = str(role.get("company_nif") or "")
        if not cnif or cnif == nif:
            continue
        entry = per_company.setdefault(cnif, {"name": role.get("company_name") or cnif, "roles": [], "dates": []})
        label = str(role.get("role") or "")
        if label and label not in entry["roles"]:
            entry["roles"].append(label)
        if role.get("date"):
            entry["dates"].append(str(role["date"]))
        if role.get("company_name") and len(str(role["company_name"])) > len(entry["name"]):
            entry["name"] = role["company_name"]

    for cnif, entry in list(per_company.items())[:MAX_COMPANY_NODES]:
        company_id = f"company:{cnif}"
        nodes[company_id] = {
            "id": company_id,
            "type": "company",
            "label": entry["name"],
            "nif": cnif,
            "is_company": True,
        }
        edges.append({
            "source": person_id,
            "target": company_id,
            "label": ", ".join(entry["roles"][:3]) or "Cargo",
            "role": entry["roles"][0] if entry["roles"] else "Cargo",
            "type": "role",
            "count": len(entry["roles"]),
            "date": max(entry["dates"]) if entry["dates"] else None,
        })

    # 2. Co-intervenientes nos processos do CIRE (quem aparece ao lado da pessoa).
    for entry in (cire.get("co_intervenientes") or [])[:MAX_CO_INTERVENIENTES]:
        other = str(entry.get("nif") or "")
        if not other or other == nif:
            continue
        node_id = f"person:{other}"
        papeis = ", ".join(str(role.get("key")) for role in (entry.get("papeis") or [])[:2])
        nodes[node_id] = {
            "id": node_id,
            "type": "person",
            "label": entry.get("name") or other,
            "nif": other,
            "is_company": False,
        }
        edges.append({
            "source": person_id,
            "target": node_id,
            "label": papeis or "Co-interveniente",
            "role": papeis or "Co-interveniente",
            "role_org": "CIRE",
            "type": "process",
            "count": int(entry.get("processes") or 1),
        })

    # 3. Presenças digitais (perfis e páginas onde a pessoa aparece).
    seen_hosts: set = set()
    for item in (social.get("items") or [])[:60]:
        url = str(item.get("url") or "")
        try:
            host = (urlparse(url).netloc or "").lower().removeprefix("www.")
        except Exception:
            host = ""
        if not host or host in seen_hosts or len(seen_hosts) >= MAX_SOCIAL_NODES:
            continue
        seen_hosts.add(host)
        node_id = f"source:{host}"
        nodes[node_id] = {"id": node_id, "type": "source", "label": host, "url": url, "platform": item.get("platform")}
        edges.append({
            "source": person_id,
            "target": node_id,
            "label": str(item.get("platform") or "Internet"),
            "role": str(item.get("kind") or "presença digital"),
            "type": "social",
            "count": 1,
        })

    return {
        "person_nif": nif,
        "person_name": name,
        "nodes": list(nodes.values()),
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "meta": {
            "companies": len(per_company),
            "co_intervenientes": len(cire.get("co_intervenientes") or []),
            "sites": len(seen_hosts),
        },
    }


# --------------------------------------------------------------- ficha
def build_factual_markdown(
    person: Dict[str, Any],
    cire: Dict[str, Any],
    social: Dict[str, Any],
    risk: Dict[str, Any],
    graph: Dict[str, Any],
) -> str:
    """Ficha analítica montada apenas com factos (sem modelo de IA)."""
    nif = str(person.get("nif") or "")
    lines: List[str] = [f"# Ficha analítica — {person.get('name') or nif}", ""]
    lines.append(f"**NIF:** {nif} · **Tipo:** {'pessoa coletiva' if person.get('is_company') else 'pessoa singular'}")
    if person.get("sources") or person.get("source"):
        lines.append(f"**Fontes da ficha:** {', '.join(person.get('sources') or [person.get('source')])}")
    if person.get("first_seen") or person.get("last_seen"):
        lines.append(f"**Período coberto:** {person.get('first_seen') or '—'} → {person.get('last_seen') or '—'}")
    lines.append("")

    lines += ["## 1. Risco", "", f"**{risk['score']:.1f}/100 ({risk['level']})** · confiança {risk['confidence']}", ""]
    for factor in risk["factors"]:
        signal = "+" if float(factor["points"]) > 0 else ""
        lines.append(f"- **{factor['label']}** ({signal}{float(factor['points']):.1f}) — {factor['evidence']}")
    lines.append("")

    lines += ["## 2. Presença societária", ""]
    companies = person.get("companies") or []
    lines.append(f"{len(person.get('roles') or [])} cargos em {len(companies)} empresa(s).")
    for company in companies[:12]:
        lines.append(f"- {company.get('name') or company.get('nif')} ({company.get('nif')})")
    lines.append("")

    lines += ["## 3. Processos de insolvência (CIRE)", ""]
    if int(cire.get("total") or 0):
        papeis = ", ".join(f"{row['key']}: {row['count']}" for row in (cire.get("by_papel") or []))
        lines.append(f"**{cire['total']} publicação(ões)** com este NIF. Papéis: {papeis or '—'}.")
        for process in (cire.get("processes") or [])[:8]:
            lines.append(
                f"- {process.get('processo') or '—'} · {process.get('especie') or '—'} · "
                f"{process.get('tribunal') or '—'} · {process.get('date') or '—'} · "
                f"papel: {', '.join(process.get('papeis') or []) or '—'}"
            )
        if int(cire.get("sampled") or 0) < int(cire.get("total") or 0):
            lines.append(f"- (amostra de {cire['sampled']} de {cire['total']} publicações)")
    else:
        lines.append("Sem registos no CIRE para este NIF.")
    lines.append("")

    lines += ["## 4. Relações", ""]
    graph_meta = graph.get("meta") or {}
    lines.append(
        f"Grafo com {graph['node_count']} nós e {graph['edge_count']} ligações: "
        f"{graph_meta.get('companies', 0)} empresas, {graph_meta.get('co_intervenientes', 0)} co-intervenientes, "
        f"{graph_meta.get('sites', 0)} sites."
    )
    for entry in (cire.get("co_intervenientes") or [])[:8]:
        papeis = ", ".join(str(role.get("key")) for role in (entry.get("papeis") or [])[:2])
        lines.append(f"- {entry.get('name')} ({entry.get('nif')}) — {entry.get('processes')} processo(s) em comum ({papeis})")
    lines.append("")

    lines += ["## 5. Presença digital", ""]
    if int(social.get("total") or 0):
        platforms = ", ".join(f"{row['key']}: {row['count']}" for row in (social.get("by_platform") or []))
        lines.append(
            f"{social['total']} registo(s) recolhido(s) ({platforms or '—'}), "
            f"{len(social.get('images') or [])} imagem(ns) e {len(social.get('videos') or [])} vídeo(s)."
        )
        for item in (social.get("texts") or [])[:8]:
            tone = f" _(tom {item.get('sentiment')})_" if item.get("sentiment") else ""
            lines.append(f"- [{item.get('platform') or 'web'}] {str(item.get('title') or item.get('text'))[:160]}{tone} — {item.get('url')}")
        if social.get("last_collected"):
            lines.append(f"- Última recolha: {social['last_collected']}")
    else:
        lines.append("Ainda não há conteúdos recolhidos: use **Obter dados das redes e da internet**.")
    lines.append("")

    lines += ["## 6. Fontes e limitações", ""]
    lines.append(
        "- Societário e insolvências: publicações oficiais indexadas (MJ/CIRE); "
        "a ficha de pessoas é agregada por NIF."
    )
    lines.append(
        "- Conteúdos das redes sociais e da internet: apenas o que é público. "
        "Perfis que exijam sessão autenticada ficam registados como ligação, sem conteúdo."
    )
    lines.append("- As contagens de co-intervenientes são uma amostra dos processos mais recentes.")
    lines.append("")
    lines.append(f"*Documento gerado em {_now()} pelo IQ OS — texto sem modelo de IA: apenas factos das fontes citadas.*")
    return "\n".join(lines)


_SYSTEM = (
    "És analista de risco do IQ OS. Escreves fichas analíticas em português de Portugal, "
    "sóbrias e verificáveis. Usa apenas os dados fornecidos: não inventes factos, valores, "
    "processos nem nomes. Quando um dado não existir, diz que não foi encontrado. "
    "Quando referires um risco, explica de que evidência vem e qual a limitação da análise."
)


def resolve_backend(session: Any, backend: Optional[str] = None) -> tuple:
    """Modelo a usar: o pedido, o predefinido do utilizador ou o 1.º fornecedor com chave.

    O Chat escolhe o modelo por conversa; aqui (fichas, resumos) não há essa escolha,
    por isso, quando o utilizador não tem modelo predefinido, procura-se o primeiro
    fornecedor cloud configurado (chave do utilizador ou do ambiente) para a análise
    ser redigida por IA em vez de sair em modo factual.
    """
    try:
        from api import ontology_ai as ai  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover
        return {"kind": "unavailable", "note": f"IA indisponível ({exc})."}, None

    chosen = ai.available_backend(session, backend)
    if chosen.get("kind") == "cloud" or backend:
        return chosen, None

    user_id = getattr(getattr(session, "user", None), "id", None)
    try:
        from api import providers_service  # noqa: PLC0415

        catalog = providers_service.provider_catalog(user_id)
    except Exception as exc:  # pragma: no cover
        logger.debug("Catálogo de fornecedores indisponível: %s", exc)
        return chosen, None

    for item in catalog.get("providers") or []:
        if item.get("kind") != "cloud" or not item.get("configured") or not item.get("id"):
            continue
        candidate = ai.available_backend(session, f"{item['id']}:{item.get('default_model') or ''}")
        if candidate.get("kind") == "cloud":
            return candidate, (
                f"O utilizador não tem modelo predefinido: usou-se {item['id']} "
                f"(chave: {item.get('key_source') or 'ambiente'})."
            )
    return chosen, None



def _prompt(person: Dict[str, Any], cire: Dict[str, Any], social: Dict[str, Any], risk: Dict[str, Any]) -> str:
    facts = {
        "pessoa": {
            "nif": person.get("nif"),
            "nome": person.get("name"),
            "pessoa_coletiva": bool(person.get("is_company")),
            "fontes": person.get("sources") or person.get("source"),
            "cargos": [
                {"cargo": r.get("role"), "entidade": r.get("company_name"), "data": r.get("date"), "origem": r.get("role_org")}
                for r in (person.get("roles") or [])[:40]
            ],
        },
        "cire": {
            "publicacoes": cire.get("total"),
            "papeis": cire.get("by_papel"),
            "processos": [
                {"processo": p.get("processo"), "especie": p.get("especie"), "tribunal": p.get("tribunal"), "data": p.get("date"), "papeis": p.get("papeis"), "insolvente": p.get("insolvente")}
                for p in (cire.get("processes") or [])[:15]
            ],
            "co_intervenientes": [
                {"nome": c.get("name"), "nif": c.get("nif"), "processos": c.get("processes"), "papeis": [r.get("key") for r in (c.get("papeis") or [])]}
                for c in (cire.get("co_intervenientes") or [])[:15]
            ],
        },
        "social": {
            "total": social.get("total"),
            "plataformas": social.get("by_platform"),
            "imagens": len(social.get("images") or []),
            "videos": len(social.get("videos") or []),
            "textos": [
                {"plataforma": t.get("platform"), "titulo": t.get("title"), "texto": str(t.get("text") or "")[:400], "url": t.get("url"), "sentimento": t.get("sentiment")}
                for t in (social.get("texts") or [])[:25]
            ],
        },
        "risco_calculado": {
            "pontuacao": risk.get("score"),
            "nivel": risk.get("level"),
            "confianca": risk.get("confidence"),
            "fatores": [{"fator": f.get("label"), "pontos": f.get("points"), "evidencia": f.get("evidence")} for f in (risk.get("factors") or [])],
        },
    }
    import json

    return (
        "Escreve a **ficha analítica** desta pessoa para um analista de risco, em Markdown, com as secções:\n"
        "1. **Síntese** (3–5 linhas, com o essencial e o nível de risco);\n"
        "2. **Perfil e presença societária**;\n"
        "3. **Processos de insolvência** (papel da pessoa em cada um, se houver);\n"
        "4. **Rede de relações** (com quem contracena e em quê);\n"
        "5. **Presença digital** (o que se publicou e o tom);\n"
        "6. **Riscos e sinais de alerta**, cada um com a evidência que o sustenta;\n"
        "7. **Limitações desta análise**.\n\n"
        "Dados (JSON):\n"
        f"{json.dumps(facts, ensure_ascii=False, default=str)[:14000]}"
    )


async def build_ai_markdown(
    person: Dict[str, Any],
    cire: Dict[str, Any],
    social: Dict[str, Any],
    risk: Dict[str, Any],
    graph: Dict[str, Any],
    *,
    session: Any = None,
    backend: Optional[str] = None,
) -> Dict[str, Any]:
    """Ficha analítica redigida por IA (com recuo para a versão factual)."""
    factual = build_factual_markdown(person, cire, social, risk, graph)
    outcome: Dict[str, Any] = {"mode": "factual", "text": factual, "notes": [], "warnings": []}
    try:
        chosen, fallback_note = resolve_backend(session, backend)
    except Exception as exc:  # pragma: no cover
        outcome["warnings"].append(f"IA indisponível ({exc}).")
        return outcome
    if fallback_note:
        outcome["notes"].append(fallback_note)

    outcome["backend"] = {"kind": chosen.get("kind"), "provider": chosen.get("provider"), "model": chosen.get("model")}
    if chosen.get("kind") != "cloud":
        outcome["notes"].append(chosen.get("note") or "Sem modelo configurado: ficha montada só com factos.")
        return outcome
    # `ai` é importado aqui (e não no topo) para evitar ciclos de importação — como
    # em `resolve_backend`. Sem este import o `ai.ask_model` dava `NameError` e a
    # ficha saía sempre em modo factual com o aviso «a IA falhou».
    try:
        from api import ontology_ai as ai  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover
        outcome["warnings"].append(f"IA indisponível ({exc}); ficha factual.")
        return outcome
    try:
        text = await ai.ask_model(
            chosen,
            system=_SYSTEM,
            prompt=_prompt(person, cire, social, risk),
            max_tokens=1800,
            temperature=0.2,
        )
    except Exception as exc:
        outcome["warnings"].append(f"A IA falhou ({exc}); ficha factual.")
        return outcome
    if not text:
        outcome["warnings"].append("A IA devolveu texto vazio; ficha factual.")
        return outcome
    outcome["mode"] = "ai"
    outcome["text"] = text
    outcome["notes"].append(f"Ficha redigida por {chosen.get('provider')}:{chosen.get('model')} a partir dos dados indexados.")
    return outcome


# --------------------------------------------------------------- 360
async def person_360(
    nif: str,
    *,
    session: Any = None,
    backend: Optional[str] = None,
    with_ai: bool = True,
    social_size: int = 200,
    cire_size: int = 200,
) -> Dict[str, Any]:
    """Análise 360 de uma pessoa: ficha, CIRE, social, risco, grafo e ficha analítica."""
    nif = str(nif or "").strip()
    if not nif:
        return {"error": "NIF em falta.", "nif": nif}

    # O Elasticsearch é síncrono: corre no threadpool para não bloquear o event loop
    # (bloquear aqui deixa a aplicação inteira à espera, não só este pedido).
    person = await run_in_threadpool(get_person_by_nif, nif)
    if person.get("error") or not person.get("name"):
        return {"error": person.get("error") or f"A pessoa {nif} não existe no PessoasIQ.", "nif": nif}

    cire = await run_in_threadpool(cire_person_processes, nif, size=cire_size)
    social = await run_in_threadpool(social_bundle, nif, size=social_size)
    risk = build_risk(person, cire, social)
    graph = build_relations_graph(person, cire, social)

    report = {
        "nif": nif,
        "name": person.get("name"),
        "is_company": bool(person.get("is_company")),
        "generated_at": _now(),
        "profile": {
            "nif": nif,
            "name": person.get("name"),
            "is_company": bool(person.get("is_company")),
            "sources": person.get("sources") or ([person.get("source")] if person.get("source") else []),
            "roles_count": person.get("roles_count") or len(person.get("roles") or []),
            "companies_count": person.get("companies_count") or len(person.get("companies") or []),
            "first_seen": person.get("first_seen"),
            "last_seen": person.get("last_seen"),
            "companies": (person.get("companies") or [])[:40],
            "latest_roles": (person.get("latest_roles") or [])[:20],
        },
        "cire": {
            "total": cire.get("total"),
            "sampled": cire.get("sampled"),
            "by_papel": cire.get("by_papel"),
            "processes": cire.get("processes"),
            "co_intervenientes": cire.get("co_intervenientes"),
            "tribunais": cire.get("tribunais"),
            "years": cire.get("years"),
            "error": cire.get("error"),
        },
        "social": {
            "total": social.get("total"),
            "by_platform": social.get("by_platform"),
            "by_sentiment": social.get("by_sentiment"),
            "sentiment": social.get("sentiment"),
            "images": social.get("images"),
            "videos": social.get("videos"),
            "texts": social.get("texts"),
            "last_collected": social.get("last_collected"),
            "error": social.get("error"),
        },
        "risk": risk,
        "graph": graph,
    }

    if with_ai:
        analysis = await build_ai_markdown(person, cire, social, risk, graph, session=session, backend=backend)
    else:
        analysis = {
            "mode": "factual",
            "text": build_factual_markdown(person, cire, social, risk, graph),
            "notes": ["Ficha pedida sem IA (`with_ai=false`)."],
            "warnings": [],
        }
    report["analysis"] = analysis
    return report
