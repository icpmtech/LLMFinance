"""Serviço da **Pesquisa PessoasIQ**.

Agrega resultados de pessoas de várias fontes num formato único, com contagem,
facetase um resultado por origem. Cada fonte mantém a sua forma de pesquisa;
este módulo é só a cola que permite uma experiência «estilo Google».

Fontes incluídas:
- `pessoas`: cadastro `finance_people` (societário + CIRE, excluindo políticos);
- `politicos`: entradas de políticos em `finance_people` (parlamento/wikipédia);
- `devedores`: listas públicas de devedores (Finanças / Segurança Social);
- `municipios`: executivos das câmaras municipais;
- `governo`: membros do Governo;
- `ept`: titulares da Entidade para a Transparência.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from api import devedores_service
from api import entidade_transparencia_service as ept
from api import governo_service
from api import municipio_pessoas_service as municipios
from api.elasticsearch_client import people_autocomplete, search_people
from api.people_politician import _person_party

logger = logging.getLogger(__name__)

#: Fontes conhecidas e a sua ordem padrão no painel.
FONTES: List[Dict[str, Any]] = [
    {"id": "pessoas", "label": "Pessoas", "hint": "Cadastro de pessoas (societário, CIRE)", "icon": "person-standing"},
    {"id": "politicos", "label": "Políticos", "hint": "Deputados e políticos da Wikipédia", "icon": "landmark"},
    {"id": "devedores", "label": "Devedores", "hint": "Listas públicas de devedores", "icon": "alert-triangle"},
    {"id": "municipios", "label": "Municípios", "hint": "Executivos das câmaras municipais", "icon": "university"},
    {"id": "governo", "label": "Governo", "hint": "Membros do Governo", "icon": "building-2"},
    {"id": "ept", "label": "Entidade Transparência", "hint": "Titulares de cargos públicos", "icon": "shield"},
]

_FONTES_POR_ID: Dict[str, Dict[str, Any]] = {f["id"]: f for f in FONTES}
_FONTE_IDS: List[str] = [f["id"] for f in FONTES]

#: Máximo de resultados devolvidos por fonte numa pesquisa «tudo».
_SIZE_POR_FONTE = 8


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _fold(text: str) -> str:
    """Normalização para comparar nomes de forma tolerante."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def _normalizar_nif(termo: str) -> Optional[str]:
    """Devolve um NIF se o termo for exclusivamente 9 dígitos."""
    limpo = re.sub(r"\D", "", termo or "")
    return limpo if re.fullmatch(r"\d{9}", limpo) else None


# ---------------------------------------------------------------------------
# Adaptadores: cada fonte devolve um dicionário com itens + total + facets
# ---------------------------------------------------------------------------


def _pessoas(termo: str, page: int, size: int) -> Dict[str, Any]:
    """Cadastro geral de pessoas, excluindo políticos (têm fonte própria)."""
    result = search_people(
        q=termo or None,
        is_company=False,
        size=size,
        from_=(page - 1) * size,
        sort="relevance",
    )
    items: List[Dict[str, Any]] = []
    for row in result.get("items") or []:
        meta = row.get("metadata") or {}
        tags = row.get("tags") or []
        # Políticos têm fonte própria; evita duplicar aqui.
        if "politica" in tags or "deputados" in tags or meta.get("partido"):
            continue
        items.append({
            "id": row.get("nif") or row.get("doc_id"),
            "nome": row.get("name") or "(sem nome)",
            "nif": row.get("nif"),
            "fonte": "pessoas",
            "subtitulo": _subtitulo_pessoa(row),
            "snippet": row.get("biography") or "",
            "badges": ["Pessoa"],
            "extra": {
                "roles_count": row.get("roles_count") or 0,
                "companies_count": row.get("companies_count") or 0,
                "source": row.get("source"),
                "last_seen": row.get("last_seen"),
            },
            "open": {"view": "pessoas-iq", "arg": row.get("nif")} if row.get("nif") else None,
        })
    return {"total": result.get("total") or 0, "items": items, "facets": {}}


def _subtitulo_pessoa(row: Dict[str, Any]) -> str:
    partes: List[str] = []
    companies = row.get("companies") or []
    if companies:
        nomes = [c.get("name") or c.get("nif") for c in companies[:3]]
        partes.append(", ".join(nomes))
    roles = row.get("roles") or []
    cargos = list({r.get("role") for r in roles if r.get("role")})
    if cargos:
        partes.append(" · ".join(cargos[:3]))
    return " · ".join(partes) or "Ficha de pessoa"


def _politicos(termo: str, page: int, size: int) -> Dict[str, Any]:
    """Políticos: usa a mesma função de pesquisa do PessoasIQ com filtro de partido/tag."""
    result = search_people(
        q=termo or None,
        is_company=False,
        tag="politica",
        size=size * 2,
        from_=(page - 1) * size,
        sort="relevance",
    )
    items: List[Dict[str, Any]] = []
    for row in result.get("items") or []:
        meta = row.get("metadata") or {}
        partido = meta.get("partido") or meta.get("party") or _person_party(row)
        circulo = meta.get("circulo_eleitoral") or meta.get("circulo")
        cargo = meta.get("office") or meta.get("cargo")
        badges = ["Político"]
        if partido:
            badges.append(partido)
        if circulo:
            badges.append(circulo)
        items.append({
            "id": row.get("nif") or row.get("doc_id"),
            "nome": row.get("name") or "(sem nome)",
            "nif": row.get("nif"),
            "fonte": "politicos",
            "subtitulo": " · ".join(p for p in [cargo, partido, circulo] if p) or "Político",
            "snippet": row.get("biography") or "",
            "badges": badges,
            "extra": {
                "partido": partido,
                "circulo": circulo,
                "cargo": cargo,
                "source": row.get("source"),
            },
            "open": {"view": "pessoas-iq", "arg": row.get("nif")} if row.get("nif") else None,
        })
        if len(items) >= size:
            break
    return {"total": min(len(items), result.get("total") or 0), "items": items, "facets": {}}


def _devedores(termo: str, page: int, size: int) -> Dict[str, Any]:
    """Listas públicas de devedores (Finanças / Segurança Social)."""
    nif = _normalizar_nif(termo)
    result = devedores_service.search(
        q=termo if not nif else None,
        nif=nif,
        page=page,
        size=size,
        sort="relevancia",
        order="desc",
    )
    items: List[Dict[str, Any]] = []
    for row in result.get("items") or []:
        badges = ["Devedor"]
        entidade = row.get("entidade_label") or row.get("entidade")
        if entidade:
            badges.append(entidade)
        items.append({
            "id": row.get("nif"),
            "nome": row.get("nome") or f"NIF {row.get('nif')}",
            "nif": row.get("nif"),
            "fonte": "devedores",
            "subtitulo": f"{row.get('escalao') or ''} · {entidade or ''}".strip(" ·"),
            "snippet": f"Lista atualizada em {row.get('lista_atualizada_em') or '-'}, recolhida em {row.get('collected_at') or '-'}.",
            "badges": badges,
            "extra": {
                "entidade": row.get("entidade"),
                "tipo": row.get("tipo"),
                "escalao": row.get("escalao"),
                "ficheiro": row.get("ficheiro"),
                "lista_atualizada_em": row.get("lista_atualizada_em"),
            },
            "open": {"view": "pessoas-iq", "arg": row.get("nif")} if row.get("nif") else None,
        })
    return {"total": result.get("total") or 0, "items": items, "facets": result.get("facets") or {}}


def _municipios(termo: str, page: int, size: int) -> Dict[str, Any]:
    """Executivos municipais."""
    result = municipios.search_municipio_pessoas(q=termo or None, page=page, size=size)
    items: List[Dict[str, Any]] = []
    for row in result.get("items") or []:
        badges = ["Executivo municipal"]
        if row.get("party"):
            badges.append(row.get("party"))
        items.append({
            "id": row.get("doc_id") or row.get("id"),
            "nome": row.get("name") or "(sem nome)",
            "nif": row.get("nif"),
            "fonte": "municipios",
            "subtitulo": f"{row.get('role') or ''} · {row.get('concelho') or ''}".strip(" ·"),
            "snippet": row.get("pelouros") or "",
            "badges": badges,
            "extra": {
                "cargo": row.get("role"),
                "concelho": row.get("concelho"),
                "distrito": row.get("district"),
                "partido": row.get("party"),
                "eleicao": row.get("eleicao"),
                "mandato": row.get("mandato"),
                "pelouros": row.get("pelouros") or [],
                "email": row.get("email"),
                "photo_url": row.get("photo_url"),
                "profile_url": row.get("profile_url"),
                "curriculo_url": row.get("curriculo_url"),
            },
            "open": {"view": "pessoas-iq", "arg": row.get("nif")} if row.get("nif") else None,
        })
    return {"total": result.get("total") or 0, "items": items, "facets": {}}


def _governo(termo: str, page: int, size: int) -> Dict[str, Any]:
    """Membros do Governo."""
    result = governo_service.list_members(q=termo or "", size=size, offset=(page - 1) * size)
    items: List[Dict[str, Any]] = []
    for row in result.get("items") or []:
        badges = ["Governo"]
        if row.get("grupo"):
            badges.append(row.get("grupo"))
        items.append({
            "id": row.get("id"),
            "nome": row.get("nome") or row.get("nome_oficial") or "(sem nome)",
            "nif": row.get("nif"),
            "fonte": "governo",
            "subtitulo": " · ".join(p for p in [row.get("cargo"), row.get("area_nome")] if p) or "Membro do Governo",
            "snippet": row.get("biografia") or "",
            "badges": badges,
            "extra": {
                "cargo": row.get("cargo"),
                "area": row.get("area_nome"),
                "area_slug": row.get("area_slug"),
                "grupo": row.get("grupo"),
                "periodo_inicio": row.get("periodo_inicio"),
            },
            "open": {"view": "governo-ficha", "arg": row.get("id")} if row.get("id") else None,
        })
    return {"total": result.get("total") or 0, "items": items, "facets": {}}


def _ept(termo: str, page: int, size: int) -> Dict[str, Any]:
    """Titulares da Entidade para a Transparência."""
    result = ept.search_titulares(q=termo or None, page=page, size=size)
    items: List[Dict[str, Any]] = []
    for row in result.get("items") or []:
        entidades = row.get("entidades") or []
        cargos = row.get("cargos") or []
        badges = ["EPT"]
        if entidades:
            badges.append(entidades[0])
        items.append({
            "id": row.get("titular_id") or row.get("doc_id"),
            "nome": row.get("nome") or "(sem nome)",
            "nif": row.get("nif"),
            "fonte": "ept",
            "subtitulo": " · ".join(p for p in [", ".join(cargos[:2]), ", ".join(entidades[:2])] if p),
            "snippet": f"{row.get('declaracoes_total') or 0} declarações indexadas.",
            "badges": badges,
            "extra": {
                "entidades": entidades,
                "cargos": cargos,
                "orgaos": row.get("orgaos"),
                "declaracoes_total": row.get("declaracoes_total"),
            },
            "open": {"view": "entidade-transparencia", "arg": row.get("titular_id")} if row.get("titular_id") else None,
        })
    return {"total": result.get("total") or 0, "items": items, "facets": result.get("facetas") or {}}


#: Mapeamento fonte -> função de pesquisa.
_PESQUISA_POR_FONTE: Dict[str, Callable[[str, int, int], Dict[str, Any]]] = {
    "pessoas": _pessoas,
    "politicos": _politicos,
    "devedores": _devedores,
    "municipios": _municipios,
    "governo": _governo,
    "ept": _ept,
}


def _pesquisar_fonte(fonte_id: str, termo: str, page: int, size: int) -> Dict[str, Any]:
    """Executa a pesquisa numa fonte, envolvendo tudo num try/except."""
    try:
        return _PESQUISA_POR_FONTE[fonte_id](termo, page, size)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Pesquisa PessoasIQ falhou na fonte %s", fonte_id)
        return {
            "fonte": fonte_id,
            "total": 0,
            "items": [],
            "error": str(exc),
            "facets": {},
        }


def pesquisar(q: str, *, fonte: str = "todas", page: int = 1, size: int = 20) -> Dict[str, Any]:
    """Pesquisa unificada de pessoas.

    Devolve um grupo por fonte, com itens normalizados, total e facets.
    Quando `fonte` é `todas`, cada fonte devolve `_SIZE_POR_FONTE` itens; numa
    fonte específica, devolve `size` itens dessa fonte.
    """
    termo = (q or "").strip()
    fonte_limpa = (fonte or "todas").strip().lower()

    if fonte_limpa not in ("todas", *_FONTE_IDS):
        raise ValueError(f"Fonte desconhecida: {fonte}. Use uma de: {', '.join(['todas', *_FONTE_IDS])}.")

    fontes_a_pesquisar = [fonte_limpa] if fonte_limpa != "todas" else _FONTE_IDS
    size_por_fonte = size if fonte_limpa != "todas" else min(size, _SIZE_POR_FONTE)

    resultados: Dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=min(len(fontes_a_pesquisar), 6)) as executor:
        futures = {
            executor.submit(_pesquisar_fonte, f_id, termo, page, size_por_fonte): f_id
            for f_id in fontes_a_pesquisar
        }
        for future in as_completed(futures):
            f_id = futures[future]
            try:
                resultados[f_id] = future.result()
            except Exception as exc:  # noqa: BLE001
                resultados[f_id] = {
                    "fonte": f_id,
                    "total": 0,
                    "items": [],
                    "error": str(exc),
                    "facets": {},
                }

    grupos: List[Dict[str, Any]] = []
    total_geral = 0
    for f_id in fontes_a_pesquisar:
        info = _FONTES_POR_ID.get(f_id, {})
        res = resultados.get(f_id) or {"total": 0, "items": [], "facets": {}, "error": None}
        grupo = {
            "id": f_id,
            "label": info.get("label", f_id),
            "hint": info.get("hint", ""),
            "icon": info.get("icon", "person-standing"),
            "total": res.get("total") or 0,
            "items": res.get("items") or [],
            "facets": res.get("facets") or {},
            "error": res.get("error"),
        }
        grupos.append(grupo)
        total_geral += grupo["total"]

    return {
        "q": termo,
        "fonte": fonte_limpa,
        "page": page,
        "size": size,
        "total": total_geral,
        "grupos": grupos,
        "fontes_disponiveis": FONTES,
        "timestamp": _now_iso(),
    }


def suggest(q: str, *, limit: int = 8) -> Dict[str, Any]:
    """Sugestões de pessoas a partir do cadastro e políticos.

    Combina o autocomplete de `finance_people` com os membros do Governo e
    executivos municipais, dando prioridade a nomes exactos.
    """
    termo = (q or "").strip()
    if not termo:
        raise ValueError("A sugestão precisa de um termo de pesquisa.")

    itens: List[Dict[str, Any]] = []

    # 1. Autocomplete do cadastro de pessoas.
    try:
        auto = people_autocomplete(termo, limit=limit, is_company=False)
        for row in (auto.get("items") or [])[:limit]:
            itens.append({
                "text": row.get("name"),
                "fonte": "pessoas",
                "arg": row.get("nif"),
                "hint": row.get("role") or f"{row.get('roles_count') or 0} cargos",
            })
    except Exception as exc:  # noqa: BLE001
        logger.debug("Autocomplete de pessoas falhou: %s", exc)

    # 2. Membros do Governo (se o termo casar).
    try:
        gov = governo_service.list_members(q=termo, size=limit)
        for row in (gov.get("items") or [])[:limit]:
            itens.append({
                "text": row.get("nome") or row.get("nome_oficial"),
                "fonte": "governo",
                "arg": row.get("id"),
                "hint": f"{row.get('cargo') or ''} · {row.get('area_nome') or ''}".strip(" ·"),
            })
    except Exception as exc:  # noqa: BLE001
        logger.debug("Sugestão do Governo falhou: %s", exc)

    # 3. Executivos municipais.
    try:
        mun = municipios.search_municipio_pessoas(q=termo, size=limit)
        for row in (mun.get("items") or [])[:limit]:
            itens.append({
                "text": row.get("name"),
                "fonte": "municipios",
                "arg": row.get("nif"),
                "hint": f"{row.get('role') or ''} · {row.get('concelho') or ''}".strip(" ·"),
            })
    except Exception as exc:  # noqa: BLE001
        logger.debug("Sugestão de municípios falhou: %s", exc)

    # Remove duplicados por NIF/nome e prioriza nome exacto.
    vistos: set = set()
    unicos: List[Dict[str, Any]] = []
    termo_fold = _fold(termo)
    for item in itens:
        chave = _fold(item.get("arg") or item.get("text") or "")
        if not chave or chave in vistos:
            continue
        vistos.add(chave)
        item["exacto"] = termo_fold in chave or chave.startswith(termo_fold)
        unicos.append(item)

    unicos.sort(key=lambda x: (not x.pop("exacto"), len(x.get("text") or "")))
    return {"q": termo, "items": unicos[:limit]}
