"""Citações e notificações editais (CITIUS).

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch
from api.es.core import _fold_text, get_es_client
from api.es.entidades import _bulk_index_docs
from api.es.indices import CITACOES_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)




# --- Citações e notificações editais (CITIUS) -------------------------------

def citacoes_existing_ids(
    pub_ids: List[str],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve quais dos ``pub_ids`` já existem no índice das citações editais.

    Serve para a importação **não reescrever** documentos que já lá estão (uma
    recolha repetida do mesmo nome só acrescenta o que é novo). A consulta é
    feita em blocos (o ``terms`` tem limite prático de 10 000 valores).
    """
    client = es or get_es_client()
    if not client or not pub_ids:
        return {"found": [], "known": 0, "checked": 0, "index": CITACOES_INDEX}

    unique = list(dict.fromkeys(str(item) for item in pub_ids if item))
    found: List[str] = []
    chunk_size = 5000
    try:
        ensure_indices(client)
        for start in range(0, len(unique), chunk_size):
            chunk = unique[start: start + chunk_size]
            resp = client.search(
                index=CITACOES_INDEX,
                body={
                    "size": len(chunk),
                    "track_total_hits": False,
                    "_source": ["pub_id"],
                    "query": {"terms": {"pub_id": chunk}},
                },
            )
            for hit in resp.get("hits", {}).get("hits", []):
                valor = (hit.get("_source") or {}).get("pub_id")
                if not valor:
                    valor = str(hit.get("_id", "")).split(":", 1)[-1]
                found.append(str(valor))
    except Exception as exc:
        return {
            "error": str(exc), "found": [], "known": 0,
            "checked": len(unique), "index": CITACOES_INDEX,
        }

    return {"found": found, "known": len(found), "checked": len(unique), "index": CITACOES_INDEX}




def index_citacoes_items(
    items: List[Dict[str, Any]],
    run_id: Optional[str] = None,
    skip_existing: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa citações/notificações editais no índice ``CITACOES_INDEX``.

    O ``_id`` é o ``pub_id`` (sha1 de referência + processo + data + ato). Com
    ``skip_existing`` (por omissão) os documentos **que já existem no índice são
    ignorados** — recolher de novo o mesmo nome só acrescenta o que é novo
    (o número de ignorados vem em ``skipped_existing``). Use
    ``skip_existing=False`` para forçar a atualização dos existentes.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}

    preparados: List[Dict[str, Any]] = []
    for item in items:
        doc = {k: v for k, v in item.items() if not k.startswith("_") and v is not None}
        if not doc.get("pub_id"):
            continue
        doc["source"] = doc.get("source") or "citius_citacoes"
        if run_id:
            doc["run_id"] = run_id
        preparados.append(doc)

    ignorados: List[str] = []
    if skip_existing and preparados:
        existentes = citacoes_existing_ids([str(d["pub_id"]) for d in preparados], es=client)
        ja_no_indice = set(existentes.get("found") or [])
        ignorados = [str(d["pub_id"]) for d in preparados if str(d["pub_id"]) in ja_no_indice]
        preparados = [d for d in preparados if str(d["pub_id"]) not in ja_no_indice]
        if existentes.get("error"):
            logger.warning("Não foi possível verificar duplicados das citações editais: %s", existentes["error"])

    now = datetime.utcnow().isoformat()
    docs = [{**doc, "ingested_at": now} for doc in preparados]
    result = _bulk_index_docs(CITACOES_INDEX, docs, id_field="pub_id", es=client)
    result["received"] = len(items)
    result["indexed_count"] = result.get("indexed_count", 0)
    result["skipped_existing"] = len(ignorados)
    result["candidates"] = len(preparados)
    return result




def _citacoes_query(
    *,
    q: Optional[str] = None,
    referencia: Optional[str] = None,
    processo: Optional[str] = None,
    tribunal: Optional[str] = None,
    tribunal_comarca: Optional[str] = None,
    comarca_judicial: Optional[str] = None,
    tipo: Optional[str] = None,
    ato: Optional[str] = None,
    especie: Optional[str] = None,
    citado: Optional[str] = None,
    nome: Optional[str] = None,
    nomes: Optional[List[str]] = None,
    papel: Optional[str] = None,
    nif: Optional[str] = None,
    modelo: Optional[str] = None,
    titulo: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    has_documento: Optional[bool] = None,
    has_texto: Optional[bool] = None,
) -> Dict[str, Any]:
    """Cláusulas de pesquisa dos éditos — **uma só** definição, para a pesquisa e as entidades.

    Fica aqui (e não em cada função) para que «pesquisar éditos» e «pesquisar
    entidades nos éditos» filtrem exatamente o mesmo conjunto: se divergissem, as
    contagens por entidade não explicariam a lista de éditos.
    """
    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    if q:
        # `intervenientes.nome` é `nested`: o `multi_match` sozinho não o alcança
        # (uma pesquisa por nome de uma parte devolvia zero), pelo que a pesquisa
        # livre junta as duas vias — campos planos e intervenientes.
        must.append(
            {
                "bool": {
                    "should": [
                        {
                            "multi_match": {
                                "query": q,
                                "fields": [
                                    "citado^3",
                                    "referencia^3",
                                    "processo^2",
                                    "processo_numero^2",
                                    "tribunal^2",
                                    "ato^2",
                                    "especie",
                                    "texto",
                                ],
                                "operator": "and",
                            }
                        },
                        {
                            "nested": {
                                "path": "intervenientes",
                                "query": {
                                    "match": {"intervenientes.nome": {"query": q, "operator": "and"}}
                                },
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if nome:
        filters.append(
            {"nested": {"path": "intervenientes", "query": {"match": {"intervenientes.nome": nome}}}}
        )
    if nomes:
        # Várias grafias da **mesma** entidade (a pesquisa de entidades agrupa-as):
        # o filtro tem de aceitar todas, senão a contagem do grupo não explicava a lista.
        clean = [str(item).strip() for item in nomes if str(item).strip()]
        if clean:
            filters.append(
                {
                    "nested": {
                        "path": "intervenientes",
                        "query": {"terms": {"intervenientes.nome.keyword": clean}},
                    }
                }
            )
    if referencia:
        filters.append({"term": {"referencia": str(referencia)}})
    if processo:
        filters.append({"match_phrase": {"processo": processo}})
    if tribunal:
        filters.append({"match_phrase": {"tribunal": tribunal}})
    if tribunal_comarca:
        filters.append({"term": {"tribunal_comarca": tribunal_comarca}})
    if comarca_judicial:
        filters.append({"term": {"comarca_judicial": comarca_judicial}})
    if tipo:
        filters.append({"term": {"tipo": tipo}})
    if ato:
        filters.append({"match_phrase": {"ato": ato}})
    if especie:
        filters.append({"match_phrase": {"especie": especie}})
    if citado:
        filters.append({"match_phrase": {"citado": citado}})
    if papel:
        filters.append({"term": {"papeis": papel}})
    if nif:
        filters.append(
            {
                "bool": {
                    "should": [
                        {"term": {"documento_nifs": str(nif)}},
                        {
                            "nested": {
                                "path": "intervenientes",
                                "query": {"term": {"intervenientes.nif": str(nif)}},
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if modelo:
        filters.append({"term": {"documento_modelo": modelo}})
    if titulo:
        filters.append({"term": {"documento_titulo": titulo}})
    if has_documento is not None:
        filters.append({"term": {"has_documento": bool(has_documento)}})
    if has_texto is not None:
        filters.append({"term": {"has_texto": bool(has_texto)}})
    if data_from or data_to:
        interval: Dict[str, str] = {}
        if data_from:
            interval["gte"] = data_from
        if data_to:
            interval["lte"] = data_to
        filters.append({"range": {"data_publicacao": interval}})

    if must or filters:
        query: Dict[str, Any] = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filters:
            query["bool"]["filter"] = filters
        return query
    return {"match_all": {}}




def search_citacoes(
    q: Optional[str] = None,
    referencia: Optional[str] = None,
    processo: Optional[str] = None,
    tribunal: Optional[str] = None,
    tribunal_comarca: Optional[str] = None,
    comarca_judicial: Optional[str] = None,
    tipo: Optional[str] = None,
    ato: Optional[str] = None,
    especie: Optional[str] = None,
    citado: Optional[str] = None,
    nome: Optional[str] = None,
    nomes: Optional[List[str]] = None,
    papel: Optional[str] = None,
    nif: Optional[str] = None,
    modelo: Optional[str] = None,
    titulo: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    has_documento: Optional[bool] = None,
    has_texto: Optional[bool] = None,
    with_texto: bool = True,
    size: int = 20,
    from_: int = 0,
    search_after: Optional[List[Any]] = None,
    scan: bool = False,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa citações e notificações editais já indexadas.

    ``q`` procura em texto livre (interveniente, tribunal, processo, ato e o
    **texto extraído do PDF**); ``nome`` restringe ao nome de um interveniente
    (qualquer papel), ``nomes`` aceita várias grafias da mesma designação e
    ``papel`` ao papel exato desse interveniente.
    ``nif`` procura nos NIF dos intervenientes (da lista e do documento) e
    ``modelo``/``titulo`` no que foi analisado do PDF. ``with_texto=False``
    omite o texto integral da resposta (listas mais leves).

    Com ``search_after`` (cursor devolvido em ``next``) a pesquisa entra em
    **modo de varredura**: sem agregações, ordenada por data+`pub_id`, para
    percorrer o índice inteiro em páginas (usado pelo grafo e pelo mapa).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    query = _citacoes_query(
        q=q,
        referencia=referencia,
        processo=processo,
        tribunal=tribunal,
        tribunal_comarca=tribunal_comarca,
        comarca_judicial=comarca_judicial,
        tipo=tipo,
        ato=ato,
        especie=especie,
        citado=citado,
        nome=nome,
        nomes=nomes,
        papel=papel,
        nif=nif,
        modelo=modelo,
        titulo=titulo,
        data_from=data_from,
        data_to=data_to,
        has_documento=has_documento,
        has_texto=has_texto,
    )

    body: Dict[str, Any] = {
        "query": query,
        "from": max(0, from_),
        "size": max(1, min(size, 200)),
        "track_total_hits": True,
        "sort": [{"data_publicacao": {"order": "desc", "missing": "_last"}}, "_score"],
        "aggs": {
            "by_tipo": {"terms": {"field": "tipo", "size": 10}},
            "by_comarca": {"terms": {"field": "tribunal_comarca", "size": 25}},
            "by_comarca_judicial": {"terms": {"field": "comarca_judicial", "size": 25}},
            "by_tribunal": {"terms": {"field": "tribunal.keyword", "size": 25}},
            "by_ato": {"terms": {"field": "ato.keyword", "size": 20}},
            "by_especie": {"terms": {"field": "especie.keyword", "size": 15}},
            "by_papel": {"terms": {"field": "papeis", "size": 20}},
            "by_modelo": {"terms": {"field": "documento_modelo", "size": 15}},
            "by_assunto": {"terms": {"field": "documento_assunto", "size": 15}},
            "by_ano": {
                "date_histogram": {"field": "data_publicacao", "calendar_interval": "year", "format": "yyyy"}
            },
            "by_mes": {
                "date_histogram": {"field": "data_publicacao", "calendar_interval": "month", "format": "yyyy-MM"}
            },
            "valor_total": {"sum": {"field": "documento_valor"}},
            "valor_medio": {"avg": {"field": "documento_valor"}},
            "com_texto": {"filter": {"term": {"has_texto": True}}},
        },
    }

    if scan or search_after:
        # Modo de varredura: ordem estável (data + `pub_id`) e sem agregações.
        body["sort"] = [
            {"data_publicacao": {"order": "desc", "missing": "_last"}},
            {"pub_id": {"order": "asc"}},
        ]
        body["size"] = max(1, min(size, 1000))
        body.pop("from", None)
        body.pop("aggs", None)
        # O Elasticsearch recusa `search_after` vazio (é o início da varredura).
        if search_after:
            body["search_after"] = list(search_after)

    try:
        resp = client.search(index=CITACOES_INDEX, body=body)
        aggs = resp.get("aggregations", {})

        def _buckets(name: str) -> List[Dict[str, Any]]:
            return [
                {"key": b["key"], "count": b["doc_count"]}
                for b in aggs.get(name, {}).get("buckets", [])
            ]

        items: List[Dict[str, Any]] = []
        for hit in resp["hits"]["hits"]:
            source = dict(hit["_source"])
            source["doc_id"] = hit["_id"]
            # `texto`/`documento_partes` são pesados: saem só quando interessa.
            if not with_texto:
                source.pop("texto", None)
                source.pop("documento_partes", None)
            items.append(source)

        total = aggs.get("com_texto", {}).get("doc_count", 0)
        resposta: Dict[str, Any] = {
            "query": q,
            "total": resp["hits"]["total"]["value"] if isinstance(resp["hits"]["total"], dict) else resp["hits"]["total"],
            "items": items,
            "from": from_,
            "size": size,
            "with_texto": total,
            "valor_total": round(float(aggs.get("valor_total", {}).get("value") or 0.0), 2),
            "valor_medio": (
                round(float(aggs["valor_medio"]["value"]), 2)
                if isinstance(aggs.get("valor_medio", {}).get("value"), (int, float))
                else None
            ),
            "facets": {
                "tipo": _buckets("by_tipo"),
                "tribunal_comarca": _buckets("by_comarca"),
                "comarca_judicial": _buckets("by_comarca_judicial"),
                "tribunal": _buckets("by_tribunal"),
                "ato": _buckets("by_ato"),
                "especie": _buckets("by_especie"),
                "papel": _buckets("by_papel"),
                "modelo": _buckets("by_modelo"),
                "assunto": _buckets("by_assunto"),
                "ano": [
                    {"key": b.get("key_as_string"), "count": b["doc_count"]}
                    for b in aggs.get("by_ano", {}).get("buckets", [])
                ],
                "mes": [
                    {"key": b.get("key_as_string"), "count": b["doc_count"]}
                    for b in aggs.get("by_mes", {}).get("buckets", [])
                ],
            },
        }
        # Cursor da página seguinte (modo de varredura) — ver `scan_citacoes`.
        hits = resp["hits"]["hits"]
        if scan or search_after:
            resposta["next"] = hits[-1].get("sort") if hits else None
        return resposta
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}




def _entidade_key(value: Optional[str]) -> str:
    """Chave de agrupamento de grafias da **mesma** designação.

    Normaliza caixa, acentos, pontuação e abreviaturas escritas letra a letra
    («INSTITUTO DA SEGURANÇA SOCIAL - I P» ≡ «… SOCIAL IP», «S A» ≡ «SA»). É a
    diferença entre a mesma entidade escrita de duas formas e duas entidades
    diferentes: nomes que não coincidam depois desta limpeza ficam **separados** —
    agrupar por heurística ligaria de mais, e no domínio judicial isso é pior do
    que ligar de menos.
    """
    text = re.sub(r"[^0-9A-Za-z]+", " ", _fold_text(value or ""))
    text = " ".join(text.split()).upper()
    # Sequências de letras isoladas são abreviaturas: «I P» → «IP».
    return re.sub(r"\b([A-Z])(?: ([A-Z]))+\b", lambda m: m.group(0).replace(" ", ""), text)




def search_citacoes_entidades(
    q: Optional[str] = None,
    papel: Optional[str] = None,
    tipo: Optional[str] = None,
    tribunal: Optional[str] = None,
    tribunal_comarca: Optional[str] = None,
    comarca_judicial: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    has_texto: Optional[bool] = None,
    size: int = 25,
    min_editais: int = 1,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """As **entidades** (intervenientes) dos éditos, agregadas por nome.

    É a pesquisa ao contrário da lista de éditos: em vez de documentos, devolve
    **quem** aparece neles — nome, nº de éditos, papéis exercidos e NIF/NIPC
    conhecidos. Com ``q`` procura no nome; os restantes filtros restringem os
    éditos considerados (tipo, tribunal, comarca, papel, datas), pelo que as
    contagens acompanham os filtros da pesquisa.

    **Grafias da mesma designação são agrupadas**: o índice escreve «CAIXA
    ECONÓMICA MONTEPIO GERAL» e «Caixa Económica Montepio Geral» como duas
    entradas distintas e o mesmo acontece com quem é citado com o nome completo e
    abreviado. O agrupamento é feito apenas por caixa/acentos/pontuação (não se
    inventam equivalências) e cada grupo devolve as suas ``variants`` — é com
    elas que a lista de éditos é depois filtrada (``nomes``).

    Contagens: ``editais`` = éditos distintos (via ``reverse_nested``, portanto
    sem contar duas vezes quem aparece duas vezes no mesmo édito) e ``mentions``
    = entradas de interveniente encontradas.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "entities": [], "total_editais": 0}

    ensure_indices(client)

    # Traz-se mais grafias do que as pedidas: o agrupamento acontece depois da
    # agregação e é preciso ver as variantes antes de cortar a lista final.
    fetch = max(50, min(int(size) * 8, 400))
    body = {
        "size": 0,
        "track_total_hits": True,
        "query": _citacoes_query(
            # O nome da entidade é pesquisado **no nested dos intervenientes**;
            # os outros filtros são os mesmos da pesquisa de éditos.
            q=None,
            nome=q or None,
            papel=papel,
            tipo=tipo,
            tribunal=tribunal,
            tribunal_comarca=tribunal_comarca,
            comarca_judicial=comarca_judicial,
            data_from=data_from,
            data_to=data_to,
            has_texto=has_texto,
        ),
        "aggs": {
            "por_entidade": {
                "nested": {"path": "intervenientes"},
                "aggs": {
                    "nomes": {
                        "terms": {
                            "field": "intervenientes.nome.keyword",
                            "size": fetch,
                            "order": {"_count": "desc"},
                        },
                        "aggs": {
                            # Volta ao édito: conta documentos e não entradas.
                            "editais": {
                                "reverse_nested": {},
                                "aggs": {
                                    # NIF/NIPC do documento (extraídos do PDF): é o que
                                    # liga a entidade às outras fontes da plataforma.
                                    "documento_nifs": {"terms": {"field": "documento_nifs", "size": 5}},
                                    "tribunais": {"terms": {"field": "tribunal_comarca", "size": 3}},
                                },
                            },
                            "papeis": {"terms": {"field": "intervenientes.papel", "size": 8}},
                            "nifs": {"terms": {"field": "intervenientes.nif", "size": 5}},
                        },
                    }
                },
            }
        },
    }
    try:
        resp = client.search(index=CITACOES_INDEX, body=body)
    except Exception as exc:
        return {"error": str(exc), "entities": [], "total_editais": 0}

    aggs = resp.get("aggregations") or {}
    buckets = ((aggs.get("por_entidade") or {}).get("nomes") or {}).get("buckets") or []
    minimum = max(1, int(min_editais))

    def _pairs(container: Optional[Dict[str, Any]], size: int = 8) -> List[Dict[str, Any]]:
        return [
            {"key": item["key"], "count": item["doc_count"]}
            for item in (container or {}).get("buckets", [])[:size]
        ]

    # Agrupa variantes da mesma designação (caixa, acentos e pontuação).
    groups: Dict[str, Dict[str, Any]] = {}
    for bucket in buckets:
        name = str(bucket.get("key") or "").strip()
        if not name:
            continue
        key = _entidade_key(name)
        if not key:
            continue
        editais_block = bucket.get("editais") or {}
        editais = int(editais_block.get("doc_count") or 0)
        mentions = int(bucket.get("doc_count") or 0)
        group = groups.setdefault(
            key,
            {
                "variants": [],
                "editais": 0,
                "mentions": 0,
                "papeis": {},
                "nifs": {},
                "documento_nifs": {},
                "tribunais": {},
            },
        )
        group["variants"].append({"name": name, "editais": editais, "mentions": mentions})
        group["editais"] += editais
        group["mentions"] += mentions
        for field, block in (
            ("papeis", bucket.get("papeis")),
            ("nifs", bucket.get("nifs")),
            ("documento_nifs", editais_block.get("documento_nifs")),
            ("tribunais", editais_block.get("tribunais")),
        ):
            for item in (block or {}).get("buckets", []):
                group[field][item["key"]] = group[field].get(item["key"], 0) + item["doc_count"]

    entities: List[Dict[str, Any]] = []
    for group in groups.values():
        if group["editais"] < minimum:
            continue
        group["variants"].sort(key=lambda item: (-item["editais"], item["name"]))
        entities.append(
            {
                # Nome de apresentação = grafia com mais éditos.
                "name": group["variants"][0]["name"],
                "editais": group["editais"],
                "mentions": group["mentions"],
                "variants": group["variants"],
                "nomes": [item["name"] for item in group["variants"]],
                "papeis": [
                    {"key": key, "count": count}
                    for key, count in sorted(group["papeis"].items(), key=lambda item: -item[1])[:8]
                ],
                "nifs": [
                    {"key": key, "count": count}
                    for key, count in sorted(group["nifs"].items(), key=lambda item: -item[1])[:5]
                ],
                "documento_nifs": [
                    {"key": key, "count": count}
                    for key, count in sorted(group["documento_nifs"].items(), key=lambda item: -item[1])[:5]
                ],
                "tribunais": [
                    {"key": key, "count": count}
                    for key, count in sorted(group["tribunais"].items(), key=lambda item: -item[1])[:3]
                ],
            }
        )
    entities.sort(key=lambda item: (-item["editais"], item["name"]))
    nomes_agg = (aggs.get("por_entidade") or {}).get("nomes") or {}
    total_hits = resp.get("hits", {}).get("total")
    return {
        "query": q,
        "entities": entities[: max(1, int(size))],
        "total_editais": int(total_hits.get("value") if isinstance(total_hits, dict) else (total_hits or 0)),
        "truncated": int(nomes_agg.get("sum_other_doc_count") or 0) > 0,
        "min_editais": minimum,
        "note": (
            "Contagens de éditos distintos; os filtros aplicados restringem os éditos considerados. "
            "As variantes de grafia da mesma designação contam para o grupo, por isso um édito que "
            "cite duas grafias é contado nas duas."
        ),
    }




def scan_citacoes(
    *,
    max_docs: int = 20_000,
    page_size: int = 500,
    fields: Optional[List[str]] = None,
    **filters: Any,
) -> Dict[str, Any]:
    """Percorre (por `search_after`) os éditos que correspondem aos filtros.

    Serve o grafo e o mapa, que precisam do conjunto inteiro — não de uma página.
    Devolve ``{items, scanned, total, truncated, error}``: ``total`` é o total que
    o Elasticsearch conta para os filtros e ``truncated`` diz se o teto de
    ``max_docs`` cortou a varredura.
    """
    items: List[Dict[str, Any]] = []
    cursor: Optional[List[Any]] = None
    total = 0
    truncated = False
    try:
        while len(items) < max_docs:
            size = max(1, min(page_size, max_docs - len(items)))
            kwargs: Dict[str, Any] = {"with_texto": False, "size": size, "scan": True}
            if cursor:
                kwargs["search_after"] = cursor
            res = search_citacoes(**{**filters, **kwargs})
            if res.get("error"):
                return {"items": items, "scanned": len(items), "total": total, "truncated": truncated, "error": res["error"]}
            lote = res.get("items") or []
            total = int(res.get("total") or total)
            items.extend(lote)
            cursor = res.get("next")
            if not lote or not cursor:
                break
        truncated = len(items) >= max_docs and total > len(items)
    except Exception as exc:  # noqa: BLE001
        return {"items": items, "scanned": len(items), "total": total, "truncated": truncated, "error": str(exc)}
    return {"items": items, "scanned": len(items), "total": total, "truncated": truncated}




def citacoes_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice das citações editais (documentos, datas e distribuições)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        count = client.count(index=CITACOES_INDEX).get("count", 0)
        out: Dict[str, Any] = {"index": CITACOES_INDEX, "documents": count}
        if not count:
            return out
        resp = client.search(
            index=CITACOES_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "referencias": {"cardinality": {"field": "referencia"}},
                    "processos": {"cardinality": {"field": "processo_numero"}},
                    "tribunais": {"cardinality": {"field": "tribunal.keyword"}},
                    "citados": {"cardinality": {"field": "citado.keyword"}},
                    "nifs": {"cardinality": {"field": "documento_nifs"}},
                    "min_date": {"min": {"field": "data_publicacao"}},
                    "max_date": {"max": {"field": "data_publicacao"}},
                    "by_tipo": {"terms": {"field": "tipo", "size": 10}},
                    "by_comarca": {"terms": {"field": "tribunal_comarca", "size": 15}},
                    "by_comarca_judicial": {"terms": {"field": "comarca_judicial", "size": 15}},
                    "by_tribunal": {"terms": {"field": "tribunal.keyword", "size": 15}},
                    "by_ato": {"terms": {"field": "ato.keyword", "size": 15}},
                    "by_papel": {"terms": {"field": "papeis", "size": 15}},
                    "by_modelo": {"terms": {"field": "documento_modelo", "size": 10}},
                    "by_assunto": {"terms": {"field": "documento_assunto", "size": 10}},
                    "by_ano": {
                        "date_histogram": {
                            "field": "data_publicacao", "calendar_interval": "year", "format": "yyyy"
                        }
                    },
                    "by_mes": {
                        "date_histogram": {
                            "field": "data_publicacao", "calendar_interval": "month", "format": "yyyy-MM"
                        }
                    },
                    "com_documento": {"filter": {"term": {"has_documento": True}}},
                    "com_texto": {"filter": {"term": {"has_texto": True}}},
                    "com_valor": {
                        "filter": {"exists": {"field": "documento_valor"}},
                        "aggs": {
                            "total": {"sum": {"field": "documento_valor"}},
                            "medio": {"avg": {"field": "documento_valor"}},
                            "maximo": {"max": {"field": "documento_valor"}},
                        },
                    },
                },
            },
        )
        aggs = resp.get("aggregations", {})

        def _buckets(name: str) -> List[Dict[str, Any]]:
            return [
                {"key": b["key"], "count": b["doc_count"]}
                for b in aggs.get(name, {}).get("buckets", [])
            ]

        out["referencias"] = aggs.get("referencias", {}).get("value", 0)
        out["processos"] = aggs.get("processos", {}).get("value", 0)
        out["tribunais"] = aggs.get("tribunais", {}).get("value", 0)
        out["citados"] = aggs.get("citados", {}).get("value", 0)
        out["nifs"] = aggs.get("nifs", {}).get("value", 0)
        out["min_date"] = (aggs.get("min_date", {}) or {}).get("value_as_string")
        out["max_date"] = (aggs.get("max_date", {}) or {}).get("value_as_string")
        out["with_documento"] = aggs.get("com_documento", {}).get("doc_count", 0)
        out["with_texto"] = aggs.get("com_texto", {}).get("doc_count", 0)
        valor = aggs.get("com_valor", {}) or {}
        out["with_valor"] = valor.get("doc_count", 0)
        out["valor_total"] = round(float((valor.get("total") or {}).get("value") or 0.0), 2)
        out["valor_medio"] = (
            round(float((valor.get("medio") or {}).get("value")), 2)
            if isinstance((valor.get("medio") or {}).get("value"), (int, float))
            else None
        )
        out["valor_maximo"] = round(float((valor.get("maximo") or {}).get("value") or 0.0), 2) or None
        out["by_tipo"] = _buckets("by_tipo")
        out["top_comarcas"] = _buckets("by_comarca")
        out["top_comarcas_judiciais"] = _buckets("by_comarca_judicial")
        out["top_tribunais"] = _buckets("by_tribunal")
        out["top_actos"] = _buckets("by_ato")
        out["by_papel"] = _buckets("by_papel")
        out["top_modelos"] = _buckets("by_modelo")
        out["top_assuntos"] = _buckets("by_assunto")
        out["by_ano"] = [
            {"key": b.get("key_as_string"), "count": b["doc_count"]}
            for b in aggs.get("by_ano", {}).get("buckets", [])
        ]
        out["by_mes"] = [
            {"key": b.get("key_as_string"), "count": b["doc_count"]}
            for b in aggs.get("by_mes", {}).get("buckets", [])
        ]
        return out
    except Exception as exc:
        return {"error": str(exc)}




def get_citacao(pub_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve um édito pelo ``pub_id`` (documento completo, com o texto extraído)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    try:
        resp = client.get(index=CITACOES_INDEX, id=f"{CITACOES_INDEX}:{pub_id}")
    except Exception as exc:  # noqa: BLE001
        return {"pub_id": pub_id, "error": str(exc)}
    source = dict(resp.get("_source") or {})
    source["doc_id"] = resp.get("_id")
    return source




def delete_citacoes_run(run_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove do índice todos os éditos de uma recolha (``run_id``)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        resp = client.delete_by_query(
            index=CITACOES_INDEX,
            body={"query": {"term": {"run_id": run_id}}},
            refresh=True,
            conflicts="proceed",
        )
        return {"run_id": run_id, "deleted": resp.get("deleted", 0)}
    except Exception as exc:  # noqa: BLE001
        return {"run_id": run_id, "error": str(exc)}




def citacoes_runs_summary(run_ids: List[str], es: Optional[Elasticsearch] = None) -> Dict[str, int]:
    """Número de documentos indexados por ``run_id`` (para a lista de recolhas)."""
    client = es or get_es_client()
    if not client or not run_ids:
        return {}
    try:
        resp = client.search(
            index=CITACOES_INDEX,
            body={
                "size": 0,
                "query": {"terms": {"run_id": run_ids}},
                "aggs": {"by_run": {"terms": {"field": "run_id", "size": len(run_ids)}}},
            },
        )
        return {
            b["key"]: b["doc_count"]
            for b in resp.get("aggregations", {}).get("by_run", {}).get("buckets", [])
        }
    except Exception:
        return {}
