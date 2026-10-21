"""Pessoas e cargos (People), pesquisas facetadas e grafos de pessoas.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
import os
import re
from typing import Any, Dict, Iterable, List, Optional

from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.helpers import bulk
from api.es.core import _today, get_es_client
from api.es.entidades import get_company_by_nif
from api.es.indices import CIRE_INDEX, PEOPLE_INDEX, SOCIETARIO_INDEX
from api.es.mappings import ensure_indices
from api.es.societario import company_publicacoes, search_societario

logger = logging.getLogger(__name__)





# --- Pessoas e cargos extraídos do societário ---

# Campos que identificam um cargo, para o deduplicar ao juntar fichas da mesma pessoa.
_PEOPLE_ROLE_KEYS = ("publication_id", "company_nif", "role", "event", "date")




def _person_role_key(role: Dict[str, Any]) -> tuple:
    """Chave de deduplicação de um cargo (publicação + empresa + cargo + evento + data)."""
    return tuple(str(role.get(key) or "") for key in _PEOPLE_ROLE_KEYS)




def _merge_person_docs(
    existing: Optional[Dict[str, Any]],
    incoming: Dict[str, Any],
    drop_company_nif: Optional[str] = None,
    drop_role_org: Optional[str] = None,
) -> Dict[str, Any]:
    """Junta uma ficha guardada com a recém-extraída sem perder cargos de outras empresas.

    A extração é feita **por empresa** (as publicações são pesquisadas por NIF),
    mas o documento `finance_people:{nif}` é único por pessoa: indexar apenas o
    resultado da empresa A substituiria os cargos que a mesma pessoa tem na
    empresa B. Aqui os cargos são acumulados. Quando é uma reingestão
    (``drop_company_nif``) os cargos antigos dessa empresa são descartados; com
    ``drop_role_org`` (ex.: `CIRE`) descartam-se os cargos dessa origem, para não
    deixar registos obsoletos.
    """
    merged: Dict[str, Any] = dict(existing or {})
    merged.update({k: v for k, v in incoming.items() if k not in ("roles", "sources")})

    roles: List[Dict[str, Any]] = list(incoming.get("roles") or [])
    for role in (existing or {}).get("roles") or []:
        if drop_company_nif and str(role.get("company_nif") or "") == str(drop_company_nif):
            continue
        if drop_role_org and str(role.get("role_org") or "") == str(drop_role_org):
            continue
        roles.append(role)

    seen_roles: set = set()
    unique: List[Dict[str, Any]] = []
    for role in roles:
        key = _person_role_key(role)
        if key in seen_roles:
            continue
        seen_roles.add(key)
        unique.append(role)
    unique.sort(key=lambda role: str(role.get("date") or ""), reverse=True)

    companies: List[Dict[str, str]] = []
    seen_companies: set = set()
    latest: Dict[str, Dict[str, Any]] = {}
    for role in unique:
        cnif = role.get("company_nif")
        if cnif and cnif not in seen_companies:
            seen_companies.add(cnif)
            companies.append({"nif": cnif, "name": role.get("company_name") or cnif})
        latest.setdefault(str(cnif or ""), role)

    dates = [str(role["date"]) for role in unique if role.get("date")]
    name = str(merged.get("name") or "")
    if len(str(incoming.get("name") or "")) > len(name):
        name = str(incoming["name"])

    merged.update({
        "name": name,
        "name_keyword": name,
        "roles": unique,
        "companies": companies,
        "companies_count": len(companies),
        "roles_count": len(unique),
        "latest_roles": list(latest.values()),
        "first_seen": min(dates) if dates else merged.get("first_seen"),
        "last_seen": max(dates) if dates else merged.get("last_seen"),
    })
    # Fontes: a ficha pode vir do societário e ser enriquecida pelo CIRE (e vice-versa).
    sources = _person_sources(existing, incoming)
    if sources:
        merged["sources"] = sources
        # `source` fica com a fonte primária (a que criou a ficha).
        merged["source"] = sources[0]
    return merged




def _person_sources(
    existing: Optional[Dict[str, Any]],
    incoming: Optional[Dict[str, Any]],
) -> List[str]:
    """União ordenada das fontes que alimentaram a ficha (`sources` + `source`)."""
    sources: List[str] = []
    for doc in (existing or {}, incoming or {}):
        for value in (doc.get("sources"), doc.get("source")):
            values = [value] if isinstance(value, str) else list(value or [])
            for item in values:
                item = str(item or "").strip()
                if item and item not in sources:
                    sources.append(item)
    return sources




def _fetch_people_docs(
    nifs: Iterable[str],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Dict[str, Any]]:
    """Fichas já indexadas dos NIF indicados (``nif`` -> ``_source``)."""
    client = es or get_es_client()
    wanted = list(dict.fromkeys(str(n).strip() for n in nifs if str(n or "").strip()))
    if not client or not wanted:
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for start in range(0, len(wanted), 500):
        batch = wanted[start : start + 500]
        try:
            resp = client.mget(index=PEOPLE_INDEX, ids=[f"{PEOPLE_INDEX}:{n}" for n in batch])
        except Exception as exc:
            logger.debug("mget de pessoas falhou: %s", exc)
            continue
        for doc in resp.get("docs", []):
            source = doc.get("_source")
            if doc.get("found") and isinstance(source, dict):
                nif = str(source.get("nif") or str(doc.get("_id") or "").split(":")[-1])
                out[nif] = source
    return out




def people_index_presence(nifs: Iterable[str], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Indica quais dos NIF indicados já têm ficha no PessoasIQ (`finance_people`)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "indexed": [], "missing": []}
    ensure_indices(client)

    wanted = list(dict.fromkeys(str(n).strip() for n in nifs if str(n or "").strip()))
    if not wanted:
        return {"total": 0, "indexed": [], "missing": []}

    found = set(_fetch_people_docs(wanted, es=client))
    return {
        "total": len(wanted),
        "indexed": [nif for nif in wanted if nif in found],
        "missing": [nif for nif in wanted if nif not in found],
    }




def index_people(
    people: Iterable[Dict[str, Any]],
    merge: bool = True,
    drop_company_nif: Optional[str] = None,
    drop_role_org: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa fichas de pessoas no `finance_people` (um documento por NIF).

    Com ``merge`` (por omissão) os cargos já indexados são preservados, para que
    processar as publicações de uma empresa não apague os cargos da mesma pessoa
    noutras empresas. ``drop_company_nif`` / ``drop_role_org`` descartam os cargos
    obsoletos da empresa / da origem que está a ser reingerida.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}
    ensure_indices(client)

    docs: List[Dict[str, Any]] = []
    for person in people:
        nif = str((person or {}).get("nif") or "").strip()
        if not nif:
            continue
        doc = {k: v for k, v in person.items() if v is not None}
        doc["nif"] = nif
        doc.setdefault("sources", [doc.get("source")] if doc.get("source") else [])
        docs.append(doc)
    if not docs:
        return {"indexed_count": 0, "total": 0}

    previous = _fetch_people_docs([d["nif"] for d in docs], es=client) if merge else {}
    now = _today()
    actions = []
    for doc in docs:
        base = previous.get(doc["nif"])
        if base:
            doc = _merge_person_docs(
                base,
                doc,
                drop_company_nif=drop_company_nif,
                drop_role_org=drop_role_org,
            )
        doc["ingested_at"] = now
        actions.append({
            "_op_type": "index",
            "_index": PEOPLE_INDEX,
            "_id": f"{PEOPLE_INDEX}:{doc['nif']}",
            **doc,
        })

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"indexed_count": success, "total": len(actions), "errors": len(errors)}
    except Exception as exc:
        return {"error": str(exc), "indexed_count": 0, "total": len(actions)}




def _prune_people_company_roles(
    company_nif: str,
    keep_nifs: Iterable[str],
    es: Optional[Elasticsearch] = None,
) -> int:
    """Remove cargos obsoletos de uma empresa, apagando as fichas que fiquem sem cargos.

    Numa reingestão, as pessoas que já não constam das publicações da empresa
    deixam de ter lá cargos; se não tiverem cargos noutras empresas, a ficha é
    removida (senão ficaria uma pessoa vazia no PessoasIQ).
    """
    client = es or get_es_client()
    if not client or not company_nif:
        return 0
    keep = {str(n) for n in keep_nifs}
    try:
        resp = client.search(
            index=PEOPLE_INDEX,
            body={
                "query": {"nested": {"path": "roles", "query": {"term": {"roles.company_nif": str(company_nif)}}}},
                "size": 2000,
            },
        )
    except Exception as exc:
        logger.debug("prune de pessoas ignorado: %s", exc)
        return 0

    now = _today()
    actions: List[Dict[str, Any]] = []
    to_delete: List[str] = []
    for hit in resp.get("hits", {}).get("hits", []):
        source = hit.get("_source") or {}
        nif = str(source.get("nif") or "")
        if nif in keep:
            continue
        doc = _merge_person_docs(source, {"nif": nif, "roles": []}, drop_company_nif=str(company_nif))
        if not doc.get("roles"):
            to_delete.append(hit["_id"])
            continue
        doc["ingested_at"] = now
        actions.append({"_op_type": "index", "_index": PEOPLE_INDEX, "_id": hit["_id"], **doc})

    if actions:
        try:
            bulk(client, actions, raise_on_error=False, refresh=False)
        except Exception as exc:
            logger.debug("prune de pessoas (update) falhou: %s", exc)
    if to_delete:
        try:
            client.delete_by_query(
                index=PEOPLE_INDEX,
                body={"query": {"terms": {"_id": to_delete}}},
                refresh=False,
            )
        except Exception as exc:
            logger.debug("prune de pessoas (delete) falhou: %s", exc)
    try:
        client.indices.refresh(index=PEOPLE_INDEX)
    except Exception:
        pass
    return len(actions) + len(to_delete)




def _publicacoes_for_people(
    nif: Optional[str],
    es: Optional[Elasticsearch] = None,
) -> List[Dict[str, Any]]:
    """Publicações societárias a usar na extração de pessoas (de uma entidade ou todas)."""
    client = es or get_es_client()
    if not client:
        return []
    if nif:
        return (company_publicacoes(str(nif), size=1000, es=client) or {}).get("items", [])

    items: List[Dict[str, Any]] = []
    offset = 0
    while offset < 20000:
        page = search_societario(size=200, from_=offset, es=client)
        batch = page.get("items", [])
        items.extend(batch)
        if len(batch) < 200:
            break
        offset += len(batch)
    return items




def index_people_from_societario(
    nif: Optional[str] = None,
    replace_for_nif: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa pessoas/cargos extraídos das publicações societárias.

    Se ``nif`` for dado, processa apenas as publicações dessa entidade (caso
    contrário percorre o índice societário completo). Se ``replace_for_nif`` for
    dado, os cargos dessa empresa que já não constem da recolha são removidos —
    os cargos da mesma pessoa noutras empresas são preservados.
    """
    from collectors.people_extractor import extract_from_publicacoes

    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}
    ensure_indices(client)

    target_nif = nif or replace_for_nif
    items = _publicacoes_for_people(str(target_nif) if target_nif else None, es=client)
    if not items:
        return {"indexed_count": 0, "total": 0, "nif": target_nif, "publications": 0}

    people = extract_from_publicacoes(items)
    result = index_people(
        people,
        drop_company_nif=str(replace_for_nif) if replace_for_nif else None,
        es=client,
    )
    result["publications"] = len(items)
    if replace_for_nif:
        result["pruned"] = _prune_people_company_roles(
            str(replace_for_nif), [p.get("nif") for p in people], es=client
        )
    result["nif"] = target_nif
    return result




#: Campos do CIRE necessários para extrair pessoas.
_CIRE_PEOPLE_FIELDS = (
    "pub_id",
    "data_publicacao",
    "processo",
    "processo_numero",
    "especie",
    "ato",
    "tribunal_comarca",
    "tribunal",
    "insolvente",
    "intervenientes",
)




def _iter_cire_publications(
    client: Elasticsearch,
    *,
    limit: Optional[int] = None,
    page_size: int = 2000,
    progress: Optional[Dict[str, Any]] = None,
) -> Any:
    """Percorre as publicações do CIRE (com intervenientes), com `search_after`."""
    body: Dict[str, Any] = {
        "size": page_size,
        # `intervenientes` é `nested`: um `exists` direto não encontra nada.
        "query": {"nested": {"path": "intervenientes", "query": {"match_all": {}}}},
        "_source": list(_CIRE_PEOPLE_FIELDS),
        "sort": [{"pub_id": "asc"}],
    }
    emitted = 0
    search_after: Optional[List[Any]] = None
    while True:
        if search_after:
            body["search_after"] = search_after
        try:
            resp = client.search(index=CIRE_INDEX, body=body)
        except Exception as exc:
            logger.warning("Leitura do CIRE para pessoas falhou: %s", exc)
            break
        hits = resp.get("hits", {}).get("hits", [])
        if not hits:
            break
        for hit in hits:
            yield hit.get("_source") or {}
            emitted += 1
            if limit and emitted >= limit:
                if progress is not None:
                    progress["publications"] = emitted
                return
        search_after = hits[-1].get("sort")
        if progress is not None:
            progress["publications"] = emitted
        if not search_after or len(hits) < page_size:
            break




def index_people_from_cire(
    *,
    limit: Optional[int] = None,
    include_companies: bool = False,
    papeis: Optional[Iterable[str]] = None,
    write_chunk: int = 1000,
    progress: Optional[Dict[str, Any]] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa no PessoasIQ as pessoas que constam dos processos do CIRE.

    Percorre `finance_cire` (publicações com intervenientes), transforma cada
    interveniente pessoa singular num cargo (`role_org = CIRE`) e junta-o à ficha
    da pessoa em `finance_people`. Os cargos do CIRE já indexados são substituídos
    (``drop_role_org``), mas os cargos do societário são preservados.

    ``papeis`` filtra os papéis a considerar (ex.: `["Insolvente", "Administrador
    da insolvência"]`); ``include_companies`` inclui pessoas coletivas (por
    omissão só entram pessoas singulares).
    """
    from collectors.cire_people import (
        CIRE_ROLE_ORG,
        aggregate_cire_people,
        extract_people_from_cire,
    )

    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}
    ensure_indices(client)

    if progress is not None:
        progress.setdefault("phase", "a ler o CIRE")
    records: List[Dict[str, Any]] = []
    publications = 0
    for pub in _iter_cire_publications(client, limit=limit, progress=progress):
        publications += 1
        records.extend(
            extract_people_from_cire(pub, papeis=papeis, include_companies=include_companies)
        )

    if progress is not None:
        progress["phase"] = "a agregar por pessoa"
        progress["intervenientes"] = len(records)

    people = aggregate_cire_people(records)
    if not people:
        return {
            "indexed_count": 0,
            "total": 0,
            "publications": publications,
            "intervenientes": len(records),
            "message": "Sem pessoas a indexar a partir do CIRE.",
        }

    if progress is not None:
        progress["phase"] = "a indexar"
        progress["people"] = len(people)

    indexed = 0
    errors = 0
    chunk = max(1, int(write_chunk or 1000))
    for start in range(0, len(people), chunk):
        batch = people[start : start + chunk]
        result = index_people(batch, drop_role_org=CIRE_ROLE_ORG, es=client)
        indexed += int(result.get("indexed_count") or 0)
        errors += int(result.get("errors") or 0)
        if progress is not None:
            progress["indexed"] = indexed
            progress["errors"] = errors
        if result.get("error"):
            logger.warning("Indexação de pessoas do CIRE falhou: %s", result["error"])
            return {
                "error": result["error"],
                "indexed_count": indexed,
                "total": len(people),
                "publications": publications,
                "intervenientes": len(records),
                "errors": errors,
            }

    return {
        "indexed_count": indexed,
        "total": len(people),
        "publications": publications,
        "intervenientes": len(records),
        "errors": errors,
        "source": CIRE_ROLE_ORG.lower(),
    }




def _person_from_publications(nif: str, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Reconstrói a ficha de uma pessoa a partir das publicações que a mencionam.

    Rede de segurança para pessoas que aparecem no societário mas cujas
    publicações ainda não foram processadas para o índice `finance_people`.
    """
    from collectors.people_extractor import extract_from_publicacoes

    client = es or get_es_client()
    if not client:
        return None
    try:
        resp = client.search(
            index=SOCIETARIO_INDEX,
            body={
                "query": {
                    "bool": {
                        "should": [
                            {"match_phrase": {"texto": str(nif)}},
                            {"term": {"nif": str(nif)}},
                            {"match": {"requerente": str(nif)}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "size": 500,
            },
        )
        items = [hit.get("_source") or {} for hit in resp.get("hits", {}).get("hits", [])]
    except Exception as exc:
        logger.debug("Ficha de %s a partir das publicações falhou: %s", nif, exc)
        return None

    for person in extract_from_publicacoes(items):
        if str(person.get("nif")) == str(nif):
            return person
    return None




def get_person_by_nif(nif: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve ficha de uma pessoa pelo NIF.

    Se ainda não estiver em `finance_people` (o índice é alimentado pelas
    publicações societárias processadas), a ficha é reconstruída a partir das
    publicações que mencionam o NIF e fica indexada — abrir uma pessoa a partir
    do dossiê de uma empresa não deve falhar por falta de ingestão.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    nif = str(nif).strip()
    try:
        resp = client.get(index=PEOPLE_INDEX, id=f"{PEOPLE_INDEX}:{nif}", _source=True)
        return {**resp.get("_source", {}), "doc_id": resp.get("_id")}
    except NotFoundError:
        pass
    except Exception as exc:
        return {"nif": nif, "error": str(exc)}

    person = _person_from_publications(nif, es=client)
    if not person:
        return {"nif": nif, "error": "Pessoa não encontrada nas publicações societárias indexadas"}

    index_people([person], es=client)
    stored = _fetch_people_docs([nif], es=client).get(nif)
    return {**(stored or person), "doc_id": f"{PEOPLE_INDEX}:{nif}", "derived": True}




def search_people(
    q: Optional[str] = None,
    nif: Optional[str] = None,
    company_nif: Optional[str] = None,
    role: Optional[str] = None,
    is_company: Optional[bool] = None,
    origin: Optional[str] = None,
    source: Optional[str] = None,
    party: Optional[str] = None,
    tag: Optional[str] = None,
    min_roles: Optional[int] = None,
    min_companies: Optional[int] = None,
    sort: str = "relevance",
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa no índice finance_people (com filtros).

    - ``q``: nome (frase/termos) ou NIF;
    - ``role``: cargo/papel (contém, sem distinguir maiúsculas) — ex.: `Credor`;
    - ``company_nif``: tem de ter um cargo nessa empresa;
    - ``origin``: `cire` (papéis do CIRE) ou `societario` (cargos das publicações do MJ);
    - ``source``: filtra por substring do campo `source` (ex.: `parlamento`, `wikipedia`);
    - ``party``: filtra por partido político (substring, sem distinção de maiúsculas);
    - ``min_roles`` / ``min_companies``: nº mínimo de cargos/empresas na ficha;
    - ``sort``: `relevance` (por omissão, com mais cargos primeiro), `roles`, `recent`, `name`.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    nested_filters: List[Dict[str, Any]] = []

    if q:
        # Sem `operator: and` (e sem a frase completa) uma pesquisa por nome
        # completo devolvia quase todo o índice — os nomes partilham termos.
        must.append({
            "bool": {
                "should": [
                    {"term": {"nif": str(q)}},
                    {"match_phrase": {"name": {"query": q, "boost": 6}}},
                    {"match": {"name": {"query": q, "operator": "and", "boost": 3}}},
                    {"match": {"name.autocomplete": {"query": q, "operator": "and"}}},
                ],
                "minimum_should_match": 1,
            }
        })
    if nif:
        filters.append({"term": {"nif": str(nif)}})
    if is_company is not None:
        filters.append({"term": {"is_company": bool(is_company)}})
    if min_roles is not None:
        filters.append({"range": {"roles_count": {"gte": int(min_roles)}}})
    if min_companies is not None:
        filters.append({"range": {"companies_count": {"gte": int(min_companies)}}})
    if company_nif:
        nested_filters.append({
            "nested": {
                "path": "roles",
                "query": {"term": {"roles.company_nif": str(company_nif)}},
            }
        })
    if role:
        nested_filters.append({
            "nested": {
                "path": "roles",
                # `wildcard` sem `case_insensitive` não encontra cargos com maiúsculas
                # (o campo é keyword e mantém o texto original).
                "query": {
                    "wildcard": {
                        "roles.role": {"value": f"*{role}*", "case_insensitive": True},
                    }
                },
            }
        })
    if origin:
        wanted = str(origin).strip().lower()
        if wanted in ("cire", "societario", "societário"):
            # CIRE = cargos com `role_org = CIRE`; societário = todos os outros.
            condition = {"term": {"roles.role_org": "CIRE"}}
            nested_filters.append({
                "nested": {
                    "path": "roles",
                    "query": condition if wanted == "cire" else {"bool": {"must_not": [condition]}},
                }
            })
    if source:
        filters.append({"wildcard": {"source": {"value": f"*{source}*", "case_insensitive": True}}})
    if party:
        filters.append({
            "bool": {
                "should": [
                    {"wildcard": {"metadata.party": {"value": f"*{party}*", "case_insensitive": True}}},
                    {"wildcard": {"metadata.partido": {"value": f"*{party}*", "case_insensitive": True}}},
                    {"wildcard": {"party": {"value": f"*{party}*", "case_insensitive": True}}},
                ],
                "minimum_should_match": 1,
            }
        })
    if tag:
        filters.append({
            "terms": {
                "tags.keyword": [tag] if isinstance(tag, str) else list(tag),
            }
        })

    bool_query: Dict[str, Any] = {}
    if must:
        bool_query["must"] = must
    if filters:
        bool_query["filter"] = filters
    if nested_filters:
        bool_query.setdefault("filter", []).extend(nested_filters)

    query = {"bool": bool_query} if bool_query else {"match_all": {}}

    sort_spec: List[Any]
    if sort == "roles":
        sort_spec = [{"roles_count": {"order": "desc"}}, {"last_seen": {"order": "desc"}}, "_score"]
    elif sort == "recent":
        sort_spec = [{"last_seen": {"order": "desc"}}, {"roles_count": {"order": "desc"}}]
    elif sort == "name":
        sort_spec = [{"name.keyword": {"order": "asc"}}]
    else:
        sort_spec = [{"_score": {"order": "desc"}}, {"roles_count": {"order": "desc"}}]

    body = {
        "query": query,
        "from": max(0, from_),
        "size": max(1, min(size, 200)),
        "sort": sort_spec,
        "track_total_hits": True,
    }

    try:
        resp = client.search(index=PEOPLE_INDEX, body=body)
        total = resp["hits"]["total"]["value"]
        return {
            "total": total,
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]],
            "from": from_,
            "size": size,
            "filters": {
                "q": q or None,
                "role": role or None,
                "company_nif": company_nif or None,
                "origin": origin or None,
                "source": source or None,
                "party": party or None,
                "is_company": is_company,
                "min_roles": min_roles,
                "min_companies": min_companies,
                "sort": sort,
            },
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}




def _people_facet_agg(field: str, size: int = 12) -> Dict[str, Any]:
    """Agregação para uma faceta de pessoas (campos `roles.*` são `nested`).

    Nos `nested` conta-se **pessoas** e não cargos: um `reverse_nested` sobe ao
    documento, senão «CIRE» aparecia com 31 118 (o número de papéis) em vez dos
    milhares de pessoas com esse papel — e o filtro devolve pessoas.
    """
    if field.startswith("roles."):
        return {
            "nested": {"path": "roles"},
            "aggs": {"values": {"terms": {"field": field, "size": size}, "aggs": {"pessoas": {"reverse_nested": {}}}}},
        }
    return {"terms": {"field": field, "size": size}}




def _people_facet_values(agg: Dict[str, Any], field: str) -> List[Dict[str, Any]]:
    """Valores de uma faceta, desembrulhando a agregação `nested` quando existe."""
    buckets = agg.get("values", {}).get("buckets", []) if field.startswith("roles.") else agg.get("buckets", [])
    return [
        {
            "key": b["key"],
            "count": int((b.get("pessoas") or {}).get("doc_count") or b["doc_count"]),
        }
        for b in buckets
        if b.get("key") not in (None, "")
    ]




def _people_filter_clause(field: str, value: str) -> Dict[str, Any]:
    """Cláusula de filtro por um campo de pessoas (com `nested` em `roles.*`)."""
    if field.startswith("roles."):
        return {"nested": {"path": "roles", "query": {"term": {field: value}}}}
    return {"term": {field: value}}




def search_people_faceted(
    q: Optional[str] = None,
    *,
    base_query: Optional[Dict[str, Any]] = None,
    match_fields: Optional[List[str]] = None,
    filters: Optional[Dict[str, str]] = None,
    facet_fields: Optional[Dict[str, str]] = None,
    size: int = 20,
    from_: int = 0,
    sort: str = "relevance",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa `finance_people` com filtros por campo e facetas contadas.

    Serve os âmbitos **Pessoas** e **Políticos** da Pesquisa total:

    - `base_query` restringe o universo (ex.: só políticos com ficha);
    - `match_fields` acrescenta campos ao texto pesquisado (cargo, partido,
      círculo) — sem eles, «deputado» não encontrava ninguém, porque a pesquisa
      de pessoas só olha ao nome;
    - `filters` aplica as facetas escolhidas (`{campo_es: valor}`);
    - `facet_fields` (`{nome: campo_es}`) devolve as contagens para o painel de
      filtros — incluindo os `nested` de `roles.*` (cargos, origem CIRE).

    As facetas são contadas **sobre o resultado filtrado**, para os números
    acompanharem sempre o que está no ecrã.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": [], "facets": {}}
    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    if q:
        # Mesma afinidade de `search_people`: frase/palavras do nome, `nif` exato
        # e o analisador de autocompletar. Sem `operator: and` nos `match`, uma
        # pesquisa por nome próprio devolvia quase todo o índice.
        should: List[Dict[str, Any]] = [
            {"term": {"nif": str(q)}},
            {"match_phrase": {"name": {"query": q, "boost": 6}}},
            {"match": {"name": {"query": q, "operator": "and", "boost": 3}}},
            {"match": {"name.autocomplete": {"query": q, "operator": "and"}}},
        ]
        for field in match_fields or []:
            should.append({"match": {field: {"query": q, "operator": "and"}}})
        must.append({"bool": {"should": should, "minimum_should_match": 1}})
    if base_query:
        must.append(base_query)
    clause_filters: List[Dict[str, Any]] = [
        _people_filter_clause(field, str(value))
        for field, value in (filters or {}).items()
        if field and value
    ]

    bool_query: Dict[str, Any] = {"must": must or [{"match_all": {}}]}
    if clause_filters:
        bool_query["filter"] = clause_filters

    if sort == "name":
        sort_spec: List[Any] = [{"name.keyword": {"order": "asc"}}]
    elif q and sort == "relevance":
        sort_spec = [{"_score": {"order": "desc"}}, {"name.keyword": {"order": "asc"}}]
    else:
        sort_spec = [{"name.keyword": {"order": "asc"}}]

    body: Dict[str, Any] = {
        "query": {"bool": bool_query},
        "from": max(0, int(from_)),
        "size": max(1, min(int(size), 200)),
        "sort": sort_spec,
        "track_total_hits": True,
        "aggs": {
            name: _people_facet_agg(field, 12) for name, field in (facet_fields or {}).items() if field
        },
    }
    try:
        resp = client.search(index=PEOPLE_INDEX, body=body)
    except Exception as exc:
        return {"error": str(exc), "total": 0, "items": [], "facets": {}}

    total = resp.get("hits", {}).get("total", 0)
    total_value = total.get("value", 0) if isinstance(total, dict) else total
    aggs = resp.get("aggregations", {}) or {}
    return {
        "total": int(total_value or 0),
        "items": [hit.get("_source") or {} for hit in resp.get("hits", {}).get("hits", [])],
        "facets": {
            name: _people_facet_values(aggs.get(name) or {}, field)
            for name, field in (facet_fields or {}).items()
            if field
        },
    }




def people_autocomplete(
    q: str,
    *,
    limit: int = 8,
    is_company: Optional[bool] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Sugestões de pessoas/entidades para o autocomplete (nome, NIF e cargo).

    Usa o analisador de prefixo (`name.autocomplete`) para sugerir enquanto se
    escreve, com o nome, o NIF, o nº de cargos/empresas e um cargo recente — o
    suficiente para escolher a pessoa certa sem fazer a pesquisa completa.
    """
    client = es or get_es_client()
    term = str(q or "").strip()
    if not client or len(term) < 2:
        return {"q": term, "items": []}
    ensure_indices(client)

    should: List[Dict[str, Any]] = [
        {"term": {"nif": {"value": term, "boost": 8}}},
        {"match_phrase_prefix": {"name": {"query": term, "boost": 5, "max_expansions": 30}}},
        {"match": {"name.autocomplete": {"query": term, "operator": "and", "boost": 2}}},
    ]
    body: Dict[str, Any] = {
        "size": max(1, min(int(limit or 8), 25)),
        "query": {"bool": {"should": should, "minimum_should_match": 1}},
        "_source": ["nif", "name", "name_keyword", "is_company", "roles_count", "companies_count", "latest_roles", "sources", "last_seen"],
        "sort": ["_score", {"roles_count": {"order": "desc"}}],
    }
    if is_company is not None:
        body["query"]["bool"]["filter"] = [{"term": {"is_company": bool(is_company)}}]

    try:
        resp = client.search(index=PEOPLE_INDEX, body=body)
    except Exception as exc:
        return {"q": term, "items": [], "error": str(exc)}

    items: List[Dict[str, Any]] = []
    for hit in resp.get("hits", {}).get("hits", []):
        source = hit.get("_source") or {}
        latest = (source.get("latest_roles") or [])
        role = latest[0] if latest and isinstance(latest[0], dict) else {}
        items.append({
            "nif": source.get("nif"),
            "name": source.get("name_keyword") or source.get("name") or "",
            "is_company": bool(source.get("is_company")),
            "roles_count": int(source.get("roles_count") or 0),
            "companies_count": int(source.get("companies_count") or 0),
            "role": role.get("role"),
            "company_name": role.get("company_name"),
            "origin": (source.get("sources") or [None])[0] if source.get("sources") else None,
            "last_seen": source.get("last_seen"),
        })
    return {"q": term, "items": items}




def companies_with_people(
    q: Optional[str] = None,
    *,
    size: int = 20,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Empresas com pessoas/cargos registados no PessoasIQ.

    Agrega `roles.company_nif` (campo `nested`) e conta as pessoas distintas por
    empresa. Serve a pesquisa **por empresa**: uma empresa que não tenha ficha
    própria em `finance_people` (o caso comum) aparece na mesma, porque o vínculo
    é o cargo da pessoa nessa empresa.

    ``q`` aceita um NIF/NIPC (9 dígitos, correspondência exata) ou texto
    (firma/denominação da empresa, ou o nome de quem lá tem cargos).
    """
    client = es or get_es_client()
    term = str(q or "").strip()
    if not client:
        return {"total": 0, "items": [], "error": "Elasticsearch indisponível"}
    if len(term) < 2:
        # Sem termo a agregação corria sobre os ~135 mil documentos (400 cargos cada)
        # e estourava o *circuit breaker* do Elasticsearch (429): exige-se pesquisa.
        return {
            "total": 0,
            "items": [],
            "note": "Indique a firma, o NIF/NIPC da empresa ou o nome de quem lá tem cargos.",
        }
    ensure_indices(client)

    query: Optional[Dict[str, Any]] = None
    if term:
        if re.fullmatch(r"\d{9}", term):
            query = {"nested": {"path": "roles", "query": {"term": {"roles.company_nif": term}}}}
        else:
            query = {
                "bool": {
                    "should": [
                        {"nested": {"path": "roles", "query": {"match": {"roles.company_name": term}}}},
                        {"nested": {"path": "companies", "query": {"match": {"companies.name": term}}}},
                        {"match": {"name": term}},
                        {"term": {"nif": term}},
                    ],
                    "minimum_should_match": 1,
                }
            }

    body: Dict[str, Any] = {
        "size": 0,
        "aggs": {
            "roles": {
                "nested": {"path": "roles"},
                "aggs": {
                    "por_empresa": {
                        # Ordem por omissão (`_count` = nº de cargos): ordenar por
                        # `pessoas.distintas` não é permitido (agg de um só bucket).
                        "terms": {
                            "field": "roles.company_nif",
                            "size": max(1, min(int(size or 20), 100)),
                        },
                        "aggs": {
                            # `nif` é do documento pai: dentro do agg `nested` só se lá
                            # chega com `reverse_nested` (sem isso a contagem fica a 0).
                            "pessoas": {
                                "reverse_nested": {},
                                "aggs": {"distintas": {"cardinality": {"field": "nif"}}},
                            },
                            "cargos": {"value_count": {"field": "roles.publication_id"}},
                        },
                    }
                },
            }
        },
    }
    if query:
        body["query"] = query

    try:
        resp = client.search(index=PEOPLE_INDEX, body=body)
    except Exception as exc:
        logger.warning("Listagem de empresas com pessoas falhou: %s", exc)
        return {"total": 0, "items": [], "error": str(exc)}

    buckets = (
        ((resp.get("aggregations") or {}).get("roles") or {}).get("por_empresa") or {}
    ).get("buckets", [])
    items: List[Dict[str, Any]] = []
    for bucket in buckets:
        nif = str(bucket.get("key") or "").strip()
        if not nif:
            continue
        items.append({
            "nif": nif,
            "name": None,
            "people_count": int((((bucket.get("pessoas") or {}).get("distintas") or {}).get("value")) or 0),
            "roles_count": int(((bucket.get("cargos") or {}).get("value")) or 0),
        })
    if not items:
        return {"total": 0, "items": []}

    # Nomes: um `top_hits` dentro do agg `nested` reservava centenas de MB e
    # estourava o circuit breaker (429); resolve-se com uma pesquisa leve pelos
    # NIF encontrados e, no que faltar, com o cadastro de contratos.
    nomes = _company_names_from_roles(client, [item["nif"] for item in items])
    for item in items:
        item["name"] = nomes.get(item["nif"])
        if item["name"]:
            continue
        try:
            empresa = get_company_by_nif(item["nif"], es=client) or {}
            if not empresa.get("error") and empresa.get("name"):
                item["name"] = empresa["name"]
        except Exception:  # noqa: BLE001 - enriquecimento best-effort
            continue
    return {"total": len(items), "items": items}




def _company_names_from_roles(
    client: Elasticsearch,
    nifs: List[str],
) -> Dict[str, str]:
    """Firma das empresas a partir do `company_name` dos cargos já indexados."""
    alvo = {str(nif) for nif in nifs if nif}
    if not alvo:
        return {}
    body: Dict[str, Any] = {
        "size": min(200, max(10, len(alvo) * 4)),
        "query": {"nested": {"path": "roles", "query": {"terms": {"roles.company_nif": list(alvo)}}}},
        "_source": ["roles.company_nif", "roles.company_name"],
    }
    try:
        resp = client.search(index=PEOPLE_INDEX, body=body)
    except Exception as exc:
        logger.debug("Nomes das empresas (cargos) falhou: %s", exc)
        return {}
    nomes: Dict[str, str] = {}
    for hit in resp.get("hits", {}).get("hits", []):
        for role in (hit.get("_source") or {}).get("roles") or []:
            cnif = str(role.get("company_nif") or "")
            if cnif in alvo and cnif not in nomes and role.get("company_name"):
                nomes[cnif] = str(role["company_name"])
    return nomes




def company_people_from_index(
    company_nif: str,
    *,
    size: int = 200,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Ficha de empresa no PessoasIQ: pessoas com cargos nessa empresa.

    Lê `finance_people` pelos documentos que têm um cargo na empresa indicada e
    devolve, por pessoa, os cargos **nessa empresa** (o mais recente primeiro),
    além do nome da empresa tal como aparece nas publicações. Cada cargo traz o
    que distingue um cargo de outro (`quota`, `causa`, `tribunal`) e cada pessoa
    traz `outras_empresas` — onde mais tem cargos, sem as do pedido — para se ver
    a rede da pessoa sem uma segunda consulta.
    """
    client = es or get_es_client()
    nif = str(company_nif or "").strip()
    if not client:
        return {"nif": nif, "total": 0, "people": [], "error": "Elasticsearch indisponível"}
    if not nif:
        return {"nif": nif, "total": 0, "people": [], "error": "NIF da empresa em falta."}
    ensure_indices(client)

    body: Dict[str, Any] = {
        "size": max(1, min(int(size or 200), 500)),
        "query": {"nested": {"path": "roles", "query": {"term": {"roles.company_nif": nif}}}},
        "_source": [
            "nif", "name", "name_keyword", "is_company", "roles", "roles_count",
            "companies", "companies_count", "source", "sources", "ingested_at",
            "first_seen", "last_seen",
        ],
        "sort": [{"roles_count": {"order": "desc"}}, {"nif": "asc"}],
    }
    try:
        resp = client.search(index=PEOPLE_INDEX, body=body)
    except Exception as exc:
        logger.warning("Ficha de empresa %s no PessoasIQ falhou: %s", nif, exc)
        return {"nif": nif, "total": 0, "people": [], "error": str(exc)}

    total = int((resp.get("hits", {}).get("total") or {}).get("value") or 0)
    people: List[Dict[str, Any]] = []
    company_name: Optional[str] = None
    for hit in resp.get("hits", {}).get("hits", []):
        source = hit.get("_source") or {}
        roles = [
            role for role in (source.get("roles") or [])
            if str(role.get("company_nif") or "") == nif
        ]
        if not roles:
            continue
        roles.sort(key=lambda role: str(role.get("date") or role.get("publication_date") or ""), reverse=True)
        if not company_name:
            for role in roles:
                if role.get("company_name"):
                    company_name = str(role["company_name"])
                    break
        latest = roles[0]
        people.append({
            "nif": source.get("nif"),
            "name": source.get("name_keyword") or source.get("name") or "",
            "is_company": bool(source.get("is_company")),
            "cargos_empresa": len(roles),
            "cargo": latest.get("role"),
            "role_org": latest.get("role_org"),
            "event": latest.get("event"),
            "date": latest.get("date"),
            "acto": latest.get("acto"),
            "publication_id": latest.get("publication_id"),
            "roles_total": int(source.get("roles_count") or 0),
            "companies_total": int(source.get("companies_count") or 0),
            "first_seen": source.get("first_seen"),
            "last_seen": source.get("last_seen"),
            "origin": (source.get("sources") or [None])[0] if source.get("sources") else source.get("source"),
            "origens": list(source.get("sources") or ([source["source"]] if source.get("source") else [])),
            "outras_empresas": [
                {"nif": str(empresa.get("nif") or ""), "nome": str(empresa.get("name") or "")}
                for empresa in (source.get("companies") or [])
                if isinstance(empresa, dict) and str(empresa.get("nif") or "") not in ("", nif)
            ],
            "roles": [
                {
                    "role": role.get("role"),
                    "role_org": role.get("role_org"),
                    "event": role.get("event"),
                    "date": role.get("date"),
                    "acto": role.get("acto"),
                    "publication_id": role.get("publication_id"),
                    "quota": role.get("quota"),
                    "causa": role.get("causa"),
                    "tribunal": role.get("tribunal"),
                    "nacionalidade": role.get("nacionalidade"),
                }
                for role in roles[:20]
            ],
        })
    return {"nif": nif, "name": company_name, "total": total, "people": people}




def people_filters(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Facetas para os filtros da pesquisa de pessoas (cargos, origens e tipos)."""
    client = es or get_es_client()
    if not client:
        return {"available": False}
    ensure_indices(client)
    try:
        resp = client.search(
            index=PEOPLE_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "roles": {"nested": {"path": "roles"}, "aggs": {"top": {"terms": {"field": "roles.role", "size": 40}}}},
                    "origins": {"terms": {"field": "source", "size": 10}},
                    "types": {"terms": {"field": "is_company", "size": 5}},
                    "with_cire": {
                        "nested": {"path": "roles"},
                        "aggs": {"cire": {"filter": {"term": {"roles.role_org": "CIRE"}}}},
                    },
                },
            },
        )
    except Exception as exc:
        return {"available": False, "error": str(exc)}

    aggs = resp.get("aggregations", {})
    return {
        "available": True,
        "roles": [
            {"key": bucket["key"], "count": bucket["doc_count"]}
            for bucket in aggs.get("roles", {}).get("top", {}).get("buckets", [])
        ],
        "origins": [
            {"key": bucket["key"], "count": bucket["doc_count"]}
            for bucket in aggs.get("origins", {}).get("buckets", [])
        ],
        "types": [
            {"key": "company" if bucket["key"] else "person", "count": bucket["doc_count"]}
            for bucket in aggs.get("types", {}).get("buckets", [])
        ],
        "with_cire": aggs.get("with_cire", {}).get("cire", {}).get("doc_count", 0),
    }




def cire_person_processes(
    nif: str,
    *,
    size: int = 200,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Processos do CIRE em que um NIF participa, com papéis e co-intervenientes.

    Serve a análise 360 de uma pessoa: quantos processos tem, em que papéis
    (insolvente, devedor, credor, administrador da insolvência…) e com quem
    contracena. A lista de processos é limitada a ``size`` (os mais recentes),
    pelo que a contagem de co-intervenientes é uma **amostra** — o `total` de
    processos vem do próprio Elasticsearch.
    """
    client = es or get_es_client()
    nif = str(nif or "").strip()
    empty: Dict[str, Any] = {
        "total": 0,
        "sampled": 0,
        "processes": [],
        "by_papel": [],
        "co_intervenientes": [],
        "tribunais": [],
        "years": [],
    }
    if not client or not nif:
        return empty
    ensure_indices(client)

    try:
        resp = client.search(
            index=CIRE_INDEX,
            body={
                "size": max(1, min(int(size), 1000)),
                "query": {"term": {"nifs": nif}},
                "_source": [
                    "pub_id",
                    "data_publicacao",
                    "processo",
                    "processo_numero",
                    "especie",
                    "tipo",
                    "ato",
                    "tribunal",
                    "tribunal_comarca",
                    "insolvente",
                    "intervenientes",
                    "has_documento",
                    "documento_url",
                ],
                "sort": [{"data_publicacao": {"order": "desc", "missing": "_last"}}],
            },
        )
    except Exception as exc:
        return {**empty, "error": str(exc)}

    hits = resp.get("hits", {}).get("hits", []) or []
    total = resp.get("hits", {}).get("total", 0)
    total_value = int((total.get("value", 0) if isinstance(total, dict) else total) or 0)

    from collections import Counter

    papeis: Counter = Counter()
    comarcas: Counter = Counter()
    anos: Counter = Counter()
    co: Dict[str, Dict[str, Any]] = {}
    processes: List[Dict[str, Any]] = []

    for hit in hits:
        source = hit.get("_source") or {}
        intervenientes = [i for i in (source.get("intervenientes") or []) if isinstance(i, dict)]
        meus = []
        seen_papeis: set = set()
        for item in intervenientes:
            if str(item.get("nif") or "").strip() == nif:
                papel = str(item.get("papel") or "").strip() or "Interveniente"
                # Uma publicação conta uma vez por papel (o mesmo NIF pode aparecer
                # repetido na lista de intervenientes).
                if papel not in seen_papeis:
                    seen_papeis.add(papel)
                    papeis[papel] += 1
                if papel not in meus:
                    meus.append(papel)
        data = source.get("data_publicacao") or ""
        if data[:4].isdigit():
            anos[data[:4]] += 1
        comarca = str(source.get("tribunal_comarca") or "").strip()
        if comarca:
            comarcas[comarca] += 1

        outros = []
        for item in intervenientes:
            outro_nif = str(item.get("nif") or "").strip()
            if not outro_nif or outro_nif == nif:
                continue
            entry = co.setdefault(outro_nif, {"nif": outro_nif, "name": "", "papeis": Counter(), "processes": 0})
            nome = str(item.get("nome") or "").strip()
            if nome and (not entry["name"] or len(nome) > len(entry["name"])):
                entry["name"] = nome
            entry["papeis"][str(item.get("papel") or "Interveniente").strip()] += 1
            entry["processes"] += 1
            outros.append({"nif": outro_nif, "name": nome, "papel": str(item.get("papel") or "")})

        processes.append({
            "pub_id": source.get("pub_id") or str(hit.get("_id", "")).split(":")[-1],
            "processo": source.get("processo_numero") or source.get("processo") or "",
            "especie": source.get("especie") or source.get("tipo") or "",
            "tribunal": source.get("tribunal_comarca") or source.get("tribunal") or "",
            "date": data or None,
            "insolvente": source.get("insolvente") or "",
            "papeis": meus,
            "intervenientes": len(intervenientes),
            "co_intervenientes": outros[:12],
            "has_documento": bool(source.get("has_documento")),
        })

    co_intervenientes = [
        {
            "nif": entry["nif"],
            "name": entry["name"] or entry["nif"],
            "processes": entry["processes"],
            "papeis": [{"key": key, "count": value} for key, value in entry["papeis"].most_common(3)],
        }
        for entry in sorted(co.values(), key=lambda item: -item["processes"])
    ]

    return {
        "total": total_value,
        "sampled": len(processes),
        "processes": processes,
        "by_papel": [{"key": key, "count": value} for key, value in papeis.most_common(20)],
        "co_intervenientes": co_intervenientes[:60],
        "tribunais": [{"key": key, "count": value} for key, value in comarcas.most_common(10)],
        "years": [{"key": key, "count": value} for key, value in sorted(anos.items(), reverse=True)[:12]],
    }




#: Limites dos grafos de pessoas: com centenas de cargos o grafo fica ilegível (e o
#: browser lento), por isso agrega-se **uma aresta por empresa** e mostra-se só o
#: topo por número de cargos/atividade recente.
PEOPLE_GRAPH_MAX_COMPANIES = int(os.getenv("PEOPLE_GRAPH_MAX_COMPANIES", "60"))


PEOPLE_GRAPH_MAX_PEOPLE = int(os.getenv("PEOPLE_GRAPH_MAX_PEOPLE", "60"))




def people_graph_for_person(nif: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Constrói grafo pessoa->empresas a partir dos cargos (agregado por empresa).

    Uma aresta por empresa (com o total de cargos e o cargo mais recente) e apenas
    as `PEOPLE_GRAPH_MAX_COMPANIES` empresas com mais cargos — é o que mantém o
    grafo legível e rápido mesmo para quem tem centenas de processos.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "nodes": [], "edges": []}
    ensure_indices(client)

    person = get_person_by_nif(str(nif), es=client)
    if person.get("error"):
        return {"error": person["error"], "nodes": [], "edges": []}

    nodes: Dict[str, Dict[str, Any]] = {}
    person_id = f"person:{nif}"
    nodes[person_id] = {
        "id": person_id,
        "type": "person",
        "label": person.get("name", nif),
        "nif": nif,
        "is_company": person.get("is_company", False),
    }

    by_company: Dict[str, Dict[str, Any]] = {}
    for role in person.get("roles", []):
        cnif = str(role.get("company_nif") or "")
        if not cnif:
            continue
        entry = by_company.setdefault(cnif, {
            "name": role.get("company_name") or cnif,
            "count": 0,
            "roles": [],
            "latest": None,
        })
        entry["count"] += 1
        label = str(role.get("role") or "")
        if label and label not in entry["roles"]:
            entry["roles"].append(label)
        if role.get("company_name") and len(str(role["company_name"])) > len(str(entry["name"])):
            entry["name"] = role["company_name"]
        if role.get("date") and (not entry["latest"] or str(role["date"]) > str(entry["latest"].get("date") or "")):
            entry["latest"] = role

    edges: List[Dict[str, Any]] = []
    ranked = sorted(by_company.items(), key=lambda kv: (-kv[1]["count"], str(kv[1]["name"])))[:PEOPLE_GRAPH_MAX_COMPANIES]
    for cnif, entry in ranked:
        company_id = f"company:{cnif}"
        nodes[company_id] = {
            "id": company_id,
            "type": "company",
            "label": entry["name"],
            "nif": cnif,
            "is_company": True,
        }
        latest = entry["latest"] or {}
        edges.append({
            "source": person_id,
            "target": company_id,
            "label": latest.get("role", "") or (entry["roles"][0] if entry["roles"] else ""),
            "type": "role",
            "role": latest.get("role", "") or (entry["roles"][0] if entry["roles"] else ""),
            "role_org": latest.get("role_org", ""),
            "event": latest.get("event", ""),
            "date": latest.get("date"),
            "acto": latest.get("acto", ""),
            "quota": latest.get("quota"),
            # Cargos não são euros: `count` é o nº de cargos nessa empresa e é o
            # que engrossa a aresta. `value` fica a 0 (só contratos têm valor).
            "count": entry["count"],
            "value": 0.0,
        })

    return {
        "person_nif": nif,
        "person_name": person.get("name"),
        "nodes": list(nodes.values()),
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "meta": {
            "companies_total": len(by_company),
            "companies_shown": len(ranked),
            "grouped": True,
        },
    }




def people_graph_for_company(company_nif: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Constrói grafo de todas as pessoas ligadas a uma empresa (uma aresta por pessoa)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "nodes": [], "edges": []}
    ensure_indices(client)

    try:
        resp = client.search(
            index=PEOPLE_INDEX,
            body={
                "query": {
                    "nested": {
                        "path": "roles",
                        "query": {"term": {"roles.company_nif": str(company_nif)}},
                    }
                },
                "size": 500,
            },
        )
        people = [hit["_source"] for hit in resp["hits"]["hits"]]
    except Exception as exc:
        return {"error": str(exc), "nodes": [], "edges": []}

    company_id = f"company:{company_nif}"
    nodes: Dict[str, Dict[str, Any]] = {
        company_id: {
            "id": company_id,
            "type": "company",
            "label": company_nif,
            "nif": company_nif,
            "is_company": True,
        }
    }
    edges: List[Dict[str, Any]] = []
    ranked: List[tuple] = []

    for person in people:
        pnif = person.get("nif")
        if not pnif:
            continue
        relevant = [role for role in person.get("roles", []) if role.get("company_nif") == company_nif]
        if not relevant:
            continue
        latest = max(relevant, key=lambda role: str(role.get("date") or ""))
        ranked.append((len(relevant), person, latest))

    ranked.sort(key=lambda item: -item[0])
    for count, person, latest in ranked[:PEOPLE_GRAPH_MAX_PEOPLE]:
        pnif = person.get("nif")
        person_id = f"person:{pnif}"
        company = nodes[company_id]
        if company["label"] in (company_nif, ""):
            company["label"] = latest.get("company_name") or company_nif
        nodes[person_id] = {
            "id": person_id,
            "type": "person",
            "label": person.get("name", pnif),
            "nif": pnif,
            "is_company": person.get("is_company", False),
        }
        edges.append({
            "source": person_id,
            "target": company_id,
            "label": latest.get("role", ""),
            "type": "role",
            "role": latest.get("role", ""),
            "role_org": latest.get("role_org", ""),
            "event": latest.get("event", ""),
            "date": latest.get("date"),
            "acto": latest.get("acto", ""),
            "quota": latest.get("quota"),
            # `count` = nº de cargos (não euros).
            "count": count,
            "value": 0.0,
        })

    return {
        "company_nif": company_nif,
        "nodes": list(nodes.values()),
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "meta": {"people_total": len(ranked), "people_shown": min(len(ranked), PEOPLE_GRAPH_MAX_PEOPLE), "grouped": True},
    }




def people_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria rápida do índice de pessoas/cargos."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        count = client.count(index=PEOPLE_INDEX).get("count", 0)
        out: Dict[str, Any] = {"index": PEOPLE_INDEX, "documents": count}
        if count:
            resp = client.search(
                index=PEOPLE_INDEX,
                body={
                    "size": 0,
                    "aggs": {
                        "is_company": {"terms": {"field": "is_company", "size": 5}},
                        "companies_stats": {"sum": {"field": "companies_count"}},
                        "by_source": {"terms": {"field": "source", "size": 10}},
                        "top_roles": {
                            "nested": {"path": "roles"},
                            "aggs": {"roles": {"terms": {"field": "roles.role", "size": 15}}},
                        },
                    },
                },
            )
            aggs = resp.get("aggregations", {})
            out["is_company"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("is_company", {}).get("buckets", [])]
            out["total_company_links"] = int(aggs.get("companies_stats", {}).get("value", 0))
            out["by_source"] = [{"key": str(b["key"]), "count": b["doc_count"]} for b in aggs.get("by_source", {}).get("buckets", [])]
            out["top_roles"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("top_roles", {}).get("roles", {}).get("buckets", [])]
        return out
    except Exception as exc:
        return {"error": str(exc)}
