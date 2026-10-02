"""Análise de contratos e custos de uma pesquisa — e quem está por trás dela.

A Pesquisa total devolve listas; este módulo responde às perguntas que se fazem a
seguir: **quanto vale** o conjunto encontrado, **como se distribui** (ano, CPV,
procedimento), **quem ganha** esses contratos e **que empresas e pessoas** estão
associadas a eles.

Decisões:

- A análise corre sobre o **conjunto filtrado inteiro** (agregações do
  Elasticsearch), não sobre a página de resultados: «energia» vale 8,2 mil
  milhões em Portugal e 32,9 mil milhões em Espanha, não o valor dos 8 cartões.
- Portugal e Espanha têm esquemas diferentes (`precoContratual` vs
  `valor_adjudicado`/`valor_base`, `Ano` vs `ano`), pelo que a análise é
  construída por país e só depois somada numa forma comum.
- As empresas e pessoas associadas vêm das **fichas** (índice de entidades e
  `finance_people`, ligadas por NIF/`roles.company_nif`), não dos nomes soltos
  que aparecem no contrato — assim o resultado abre a ficha certa.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from api.elasticsearch_client import (
    get_company_by_nif,
    get_contract_analytics,
    get_contratos_es_analytics,
    search_people_faceted,
)

logger = logging.getLogger(__name__)

MAX_LINKED_COMPANIES = 6
MAX_LINKED_PEOPLE = 12


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _merge_buckets(*sources: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Soma baldes com a mesma chave (ano, CPV, procedimento) de várias fontes."""
    totals: Dict[str, Dict[str, Any]] = {}
    for buckets in sources:
        for bucket in buckets or []:
            key = str(bucket.get("key") or "").strip()
            if not key:
                continue
            entry = totals.setdefault(key, {"key": key, "count": 0, "total_value": 0.0})
            entry["count"] += int(bucket.get("count") or 0)
            entry["total_value"] += _num(bucket.get("total_value"))
            if bucket.get("description") and not entry.get("description"):
                entry["description"] = bucket["description"]
    return sorted(totals.values(), key=lambda item: item["total_value"], reverse=True)


def _merge_years(*sources: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Anos somados e ordenados cronologicamente (é uma série, não um ranking)."""
    years = _merge_buckets(*sources)
    return sorted(years, key=lambda item: item["key"])


def _linked_people(nifs: List[str], per_company: int = 3) -> List[Dict[str, Any]]:
    """Pessoas ligadas às empresas (por `roles.company_nif`, a ligação do registo)."""
    people: Dict[str, Dict[str, Any]] = {}
    for nif in nifs:
        result = search_people_faceted(filters={"roles.company_nif": str(nif)}, size=per_company, sort="name")
        for row in result.get("items") or []:
            person_nif = str(row.get("nif") or "")
            if not person_nif or person_nif in people:
                continue
            role = next((entry for entry in (row.get("roles") or []) if str(entry.get("company_nif")) == str(nif)), {})
            people[person_nif] = {
                "nif": person_nif,
                "name": row.get("name") or "",
                "role": role.get("role") or role.get("acto") or "",
                "company_nif": str(nif),
                "company_name": role.get("company_name") or "",
                "source": row.get("source") or "",
            }
            if len(people) >= MAX_LINKED_PEOPLE:
                return list(people.values())
    return list(people.values())


def _linked_companies(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fichas das empresas com mais valor no conjunto encontrado.

    `entities` são os baldes `top_adjudicatarios`/`top_adjudicantes` de Portugal,
    cuja chave é o **NIF** — é isso que permite ir buscar a ficha e as pessoas.
    """
    companies: List[Dict[str, Any]] = []
    for entry in entities[:MAX_LINKED_COMPANIES]:
        nif = str(entry.get("key") or "").strip()
        if not nif.isdigit():
            continue
        try:
            card = get_company_by_nif(nif) or {}
        except Exception as exc:  # a ficha é um extra: não derruba a análise
            logger.info("Ficha da empresa %s indisponível: %s", nif, exc)
            card = {}
        companies.append(
            {
                "nif": nif,
                "name": card.get("name") or entry.get("description") or nif,
                "contracts_total": card.get("contracts_total"),
                "total_value": card.get("total_value") if card.get("total_value") is not None else entry.get("total_value"),
                "contracts_in_search": int(entry.get("count") or 0),
                "value_in_search": _num(entry.get("total_value")),
                "adjudicante": bool(card.get("adjudicante")),
                "adjudicatario": bool(card.get("adjudicatario")),
            }
        )
    return companies


def contracts_analysis(
    query: str,
    *,
    year: Optional[int] = None,
    top: int = 8,
    with_links: bool = True,
    include_spain: bool = True,
) -> Dict[str, Any]:
    """Análise de custos dos contratos que casam com a pesquisa."""
    term = (query or "").strip()
    if not term:
        return {
            "query": "",
            "generated_at": _now(),
            "totals": {"contracts": 0, "value": 0.0},
            "caveats": ["Sem termo de pesquisa não há análise: escreva o que quer analisar."],
        }

    caveats: List[str] = []
    pt: Dict[str, Any] = {}
    es: Dict[str, Any] = {}
    try:
        pt = get_contract_analytics(q=term, year=year, top_entities=top, top_cpv=top) or {}
    except Exception as exc:
        caveats.append(f"Contratos de Portugal indisponíveis: {exc}")
    if include_spain:
        try:
            es = get_contratos_es_analytics(q=term, ano=year, top_organs=top, top_adjudicatarios=top, top_cpv=top) or {}
        except Exception as exc:
            caveats.append(f"Contratos de Espanha indisponíveis: {exc}")

    contracts_pt = int(pt.get("total_contracts") or 0)
    contracts_es = int(es.get("total_contracts") or 0)
    value_pt = _num(pt.get("total_value"))
    value_es = _num(es.get("total_value"))
    total_contracts = contracts_pt + contracts_es
    total_value = value_pt + value_es

    adjudicatarios = _merge_buckets(pt.get("top_adjudicatarios") or [], es.get("top_adjudicatarios") or [])
    adjudicantes = _merge_buckets(pt.get("top_adjudicantes") or [], es.get("top_organs") or [])
    companies = _linked_companies(_merge_buckets(pt.get("top_adjudicatarios") or [])) if with_links else []
    people = _linked_people([company["nif"] for company in companies]) if with_links else []
    if with_links and companies and not people:
        caveats.append("Não há pessoas ligadas a estas empresas no registo (CIRE/societário).")

    return {
        "query": term,
        "generated_at": _now(),
        "year": year,
        "totals": {
            "contracts": total_contracts,
            "value": round(total_value, 2),
            "contracts_pt": contracts_pt,
            "value_pt": round(value_pt, 2),
            "contracts_es": contracts_es,
            "value_es": round(value_es, 2),
            "avg_value": round(total_value / total_contracts, 2) if total_contracts else 0.0,
            "max_value": max(_num(pt.get("max_value")), _num(es.get("max_value"))),
            "distinct_adjudicantes": int(pt.get("distinct_adjudicantes") or 0),
            "distinct_adjudicatarios": int(pt.get("distinct_adjudicatarios") or 0),
        },
        "by_year": _merge_years(pt.get("by_year") or [], es.get("by_year") or []),
        "by_cpv": _merge_buckets(pt.get("top_cpv") or [], es.get("top_cpv") or [])[:top],
        "value_distribution": _merge_buckets(
            pt.get("value_distribution") or [], es.get("value_distribution") or []
        ),
        "procedure_types": _merge_buckets(pt.get("procedure_types") or [], es.get("procedure_types") or [])[:top],
        "contract_types": _merge_buckets(pt.get("contract_types") or [], es.get("contract_types") or [])[:top],
        "top_adjudicatarios": adjudicatarios[:top],
        "top_adjudicantes": adjudicantes[:top],
        "pt": {
            "index": "contratos",
            "value_field": "precoContratual",
            "contracts": contracts_pt,
            "value": round(value_pt, 2),
            "error": pt.get("error"),
        },
        "es": {
            "index": "contratos_es",
            "value_field": "max(valor_adjudicado, valor_base)",
            "contracts": contracts_es,
            "value": round(value_es, 2),
            "error": es.get("error"),
        },
        "linked": {"companies": companies, "people": people},
        "caveats": caveats
        + [
            "Valores em euros, tal como publicados (não incluem adendas fora do contrato).",
            "Espanha usa o maior de `valor_adjudicado`/`valor_base`; as chaves de adjudicatário em Espanha são nomes, não NIF.",
        ],
    }
