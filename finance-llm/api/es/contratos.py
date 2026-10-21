"""Contratos públicos portugueses: indexação, pesquisa, analítica e exportações.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from api.es.core import ROOT, _and_filters, _text_search, get_es_client
from api.es.geo import _region_filter
from api.es.indices import CONTRACTS_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)




# --- Contratos públicos ---

def index_contracts(
    docs: List[Dict[str, Any]],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa documentos de contratos no índice finance_contracts."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    actions = []
    for doc in docs:
        doc_id = str(doc.get("idcontrato") or doc.get("idprocedimento"))
        actions.append({
            "_op_type": "index",
            "_index": CONTRACTS_INDEX,
            "_id": doc_id,
            **doc,
        })

    if not actions:
        return {"indexed_count": 0, "total": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"indexed_count": success, "total": len(actions), "errors": len(errors)}
    except Exception as e:
        return {"error": str(e), "indexed_count": 0, "total": len(actions)}




def bulk_index_contracts_from_jsonl(
    jsonl_path: Path,
    chunk_size: int = 1000,
    max_records: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa um ficheiro JSONL de contratos em chunks."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    total = 0
    success_total = 0
    error_total = 0
    chunk: List[Dict[str, Any]] = []

    try:
        resolved_path = Path(jsonl_path) if not isinstance(jsonl_path, Path) else jsonl_path
        print(f"[bulk_index_contracts] path={resolved_path} exists={resolved_path.exists()} chunk_size={chunk_size} max_records={max_records}")
        with open(resolved_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if max_records and total >= max_records:
                    print(f"[bulk_index_contracts] max_records reached {total}")
                    break
                try:
                    doc = json.loads(line)
                except Exception:
                    continue
                chunk.append(doc)
                total += 1
                if len(chunk) >= chunk_size:
                    res = index_contracts(chunk, client)
                    print(f"[bulk_index_contracts] chunk indexed={res.get('indexed_count')} errors={res.get('errors')} error={res.get('error')}")
                    success_total += res.get("indexed_count", 0)
                    error_total += res.get("errors", 0) or (0 if not res.get("error") else len(chunk))
                    chunk = []
        if chunk:
            res = index_contracts(chunk, client)
            print(f"[bulk_index_contracts] final chunk indexed={res.get('indexed_count')} errors={res.get('errors')} error={res.get('error')}")
            success_total += res.get("indexed_count", 0)
            error_total += res.get("errors", 0) or (0 if not res.get("error") else len(chunk))
        print(f"[bulk_index_contracts] done total={total} success={success_total} errors={error_total}")
        return {"indexed_count": success_total, "total": total, "errors": error_total}
    except Exception as e:
        print(f"[bulk_index_contracts] exception {e}")
        return {"error": str(e), "indexed_count": success_total, "total": total}




def find_contract_ids_by_idcontrato(
    idcontratos: Iterable[str],
    es: Optional[Elasticsearch] = None,
) -> List[str]:
    """Devolve os _id de documentos existentes no índice finance_contracts cujo idcontrato corresponde aos valores fornecidos."""
    client = es or get_es_client()
    if not client or not idcontratos:
        return []

    ids = [str(v).strip() for v in idcontratos if v is not None and str(v).strip()]
    if not ids:
        return []

    existing: set = set()
    batch_size = 1000
    try:
        for i in range(0, len(ids), batch_size):
            batch = ids[i : i + batch_size]
            resp = client.search(
                index=CONTRACTS_INDEX,
                body={
                    "query": {"terms": {"idcontrato": batch}},
                    "_source": False,
                    "size": len(batch),
                },
            )
            for hit in resp.get("hits", {}).get("hits", []):
                existing.add(hit.get("_id"))
    except Exception as e:
        print(f"[find_contract_ids_by_idcontrato] error: {e}")
        return []
    return sorted(existing)




def delete_contracts_by_ids(
    doc_ids: Iterable[str],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Apaga documentos do índice finance_contracts pelos respetivos _id."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "deleted_count": 0}

    ids = [str(v).strip() for v in doc_ids if v is not None and str(v).strip()]
    if not ids:
        return {"deleted_count": 0, "total": 0}

    try:
        resp = client.delete_by_query(
            index=CONTRACTS_INDEX,
            body={"query": {"terms": {"_id": ids}}},
            refresh=True,
        )
        return {"deleted_count": resp.get("deleted", 0), "total": len(ids)}
    except Exception as e:
        return {"error": str(e), "deleted_count": 0, "total": len(ids)}




def _contract_to_flat_dict(source: Dict[str, Any]) -> Dict[str, Any]:
    """Converte documento de contrato num dicionário plano para exportação."""
    def party_str(parties: Any) -> str:
        if not parties:
            return ""
        if isinstance(parties, dict):
            parties = [parties]
        names = []
        for p in parties:
            parsed = p.get("parsed") if isinstance(p, dict) else None
            if isinstance(parsed, list):
                names.extend([x.get("nome", "") for x in parsed if x.get("nome")])
            raw = p.get("raw") if isinstance(p, dict) else None
            if isinstance(raw, list):
                names.extend([str(r) for r in raw])
            elif isinstance(raw, str):
                names.append(raw)
        return "; ".join(names)

    def nif_str(parties: Any) -> str:
        if not parties:
            return ""
        if isinstance(parties, dict):
            parties = [parties]
        nifs = []
        for p in parties:
            parsed = p.get("parsed") if isinstance(p, dict) else None
            if isinstance(parsed, list):
                nifs.extend([x.get("nif", "") for x in parsed if x.get("nif")])
        return "; ".join(nifs)

    def cpv_str(cpv: Any) -> str:
        if not cpv:
            return ""
        if isinstance(cpv, dict):
            cpv = [cpv]
        return "; ".join([f"{x.get('code','')} {x.get('description','')}".strip() for x in cpv])

    return {
        "idcontrato": source.get("idcontrato"),
        "nAnuncio": source.get("nAnuncio"),
        "tipoContrato": source.get("tipoContrato"),
        "tipoprocedimento": source.get("tipoprocedimento"),
        "objectoContrato": source.get("objectoContrato"),
        "descContrato": source.get("descContrato"),
        "adjudicante": party_str(source.get("adjudicantes")),
        "nif_adjudicante": nif_str(source.get("adjudicantes")),
        "adjudicatario": party_str(source.get("adjudicatarios")),
        "nif_adjudicatario": nif_str(source.get("adjudicatarios")),
        "dataPublicacao": source.get("dataPublicacao"),
        "dataCelebracaoContrato": source.get("dataCelebracaoContrato"),
        "precoContratual": source.get("precoContratual"),
        "PrecoTotalEfetivo": source.get("PrecoTotalEfetivo"),
        "precoBaseProcedimento": source.get("precoBaseProcedimento"),
        "cpv": cpv_str(source.get("cpv")),
        "localExecucao": source.get("localExecucao"),
        "Ano": source.get("Ano"),
        "NUTs": source.get("NUTs"),
        "regime": source.get("regime"),
    }




def export_contracts_to_excel(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_records: int = 10000,
    es: Optional[Elasticsearch] = None,
) -> bytes:
    """Exporta contratos filtrados para Excel (bytes)."""
    try:
        import openpyxl
        from openpyxl.styles import Font
    except ImportError as e:
        raise RuntimeError("openpyxl não instalado") from e

    client = es or get_es_client()
    if not client:
        raise RuntimeError("Elasticsearch indisponível")

    # Argumentos por nome: a ordem de `_build_contract_query` inclui `counterparty_nif`
    # e `region` antes do CPV, e a chamada posicional antiga deslocava os filtros
    # (o CPV era aplicado como região, o preço mínimo como CPV…).
    query = _build_contract_query(
        q=q,
        year=year,
        entity=entity,
        nif=nif,
        cpv_code=cpv_code,
        min_price=min_price,
        max_price=max_price,
        start_date=start_date,
        end_date=end_date,
    )
    resp = client.search(
        index=CONTRACTS_INDEX,
        body={
            "query": query,
            "sort": [{"dataPublicacao": {"order": "desc"}}, "_score"],
            "size": min(max_records, 10000),
            "track_scores": False,
        },
    )

    rows = [_contract_to_flat_dict(hit["_source"]) for hit in resp["hits"]["hits"]]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Contratos"
    headers = list(rows[0].keys()) if rows else [
        "idcontrato", "nAnuncio", "tipoContrato", "tipoprocedimento", "objectoContrato",
        "descContrato", "adjudicante", "nif_adjudicante", "adjudicatario", "nif_adjudicatario",
        "dataPublicacao", "dataCelebracaoContrato", "precoContratual", "PrecoTotalEfetivo",
        "precoBaseProcedimento", "cpv", "localExecucao", "Ano", "NUTs", "regime",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    def value_to_excel(v: Any) -> Any:
        if isinstance(v, (list, dict)):
            return json.dumps(v, ensure_ascii=False)
        return v

    for row in rows:
        ws.append([value_to_excel(row.get(h)) for h in headers])
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                val_len = len(str(cell.value))
                if val_len > max_length:
                    max_length = val_length
            except Exception:
                pass
        ws.column_dimensions[column_letter].width = min(max_length + 2, 60)

    from io import BytesIO
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()




def export_contracts_to_pdf(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_records: int = 500,
    es: Optional[Elasticsearch] = None,
) -> bytes:
    """Exporta contratos filtrados para PDF (bytes)."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
    except ImportError as e:
        raise RuntimeError("reportlab não instalado") from e

    client = es or get_es_client()
    if not client:
        raise RuntimeError("Elasticsearch indisponível")

    # Argumentos por nome: ver a nota em `export_contracts_to_excel` (a chamada
    # posicional antiga deslocava CPV/valores/datas para os filtros errados).
    query = _build_contract_query(
        q=q,
        year=year,
        entity=entity,
        nif=nif,
        cpv_code=cpv_code,
        min_price=min_price,
        max_price=max_price,
        start_date=start_date,
        end_date=end_date,
    )
    resp = client.search(
        index=CONTRACTS_INDEX,
        body={
            "query": query,
            "sort": [{"dataPublicacao": {"order": "desc"}}, "_score"],
            "size": min(max_records, 1000),
            "track_scores": False,
        },
    )

    rows = [_contract_to_flat_dict(hit["_source"]) for hit in resp["hits"]["hits"]]
    headers = ["ID", "Ano", "Tipo", "Objecto", "Adjudicante", "Adjudicatário", "Valor", "Publicação"]
    data = [headers]
    for r in rows:
        data.append([
            str(r.get("idcontrato") or ""),
            str(r.get("Ano") or ""),
            str(r.get("tipoContrato") or ""),
            str(r.get("objectoContrato") or "")[:80],
            str(r.get("adjudicante") or "")[:50],
            str(r.get("adjudicatario") or "")[:50],
            f"{r.get('precoContratual') or 0:.2f} €",
            str(r.get("dataPublicacao") or ""),
        ])

    from io import BytesIO
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    elements = []
    styles = getSampleStyleSheet()
    elements.append(Paragraph("Relatório de Contratos Públicos", styles["Title"]))
    elements.append(Paragraph(f"Total exportado: {len(rows)} contratos", styles["Normal"]))
    elements.append(Spacer(1, 12))
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#10a37f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8f9fa")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("WORDWRAP", (0, 0), (-1, -1), True),
    ]))
    elements.append(table)
    doc.build(elements)
    buf.seek(0)
    return buf.read()




def search_contracts(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    counterparty_nif: Optional[str] = None,
    region: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    ecological: Optional[bool] = None,
    size: int = 20,
    from_: int = 0,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa contratos por texto, entidades, datas e valores."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    query = _build_contract_query(q, year, entity, nif, counterparty_nif, region, cpv_code, min_price, max_price, start_date, end_date, ecological=ecological)
    sort = _build_contract_sort(sort_by, sort_order, client)

    try:
        body = {
            "query": query,
            "sort": sort,
            "from": from_,
            "size": size,
            "track_scores": True,
            "track_total_hits": True,
        }
        resp = _text_search(client, index=CONTRACTS_INDEX, body=body, q=q)
        items = []
        for hit in resp["hits"]["hits"]:
            source = hit["_source"]
            source["score"] = hit.get("_score")
            source["doc_id"] = hit.get("_id")
            items.append(source)
        return {
            "query": q,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
    except Exception as e:
        return {"error": str(e), "items": []}




def _build_contract_sort(
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    client: Optional[Elasticsearch] = None,
) -> List[Dict[str, Any]]:
    """Ordenação da pesquisa de contratos.

    As partes são ordenadas pelo campo **resolvido no mapping**
    (`_campo_nome_parte`): o `.keyword` fixo deixou de existir depois da migração
    e um sort sobre um campo inexistente falha a pesquisa inteira. Sem cliente
    (função pura), cai no campo direto e usa `unmapped_type` para nunca derrubar a
    pesquisa por causa da ordenação.
    """
    order = sort_order if sort_order in ("asc", "desc") else "desc"
    field = sort_by or "dataPublicacao"
    if field == "relevance":
        return ["_score"]
    if field == "adjudicantes":
        caminho = _campo_nome_parte(client, "adjudicantes") if client is not None else "adjudicantes.parsed.nome"
        return [{caminho: {"order": order, "nested": {"path": "adjudicantes.parsed"}, "unmapped_type": "keyword"}}, "_score"]
    if field == "adjudicatarios":
        caminho = _campo_nome_parte(client, "adjudicatarios") if client is not None else "adjudicatarios.parsed.nome"
        return [{caminho: {"order": order, "nested": {"path": "adjudicatarios.parsed"}, "unmapped_type": "keyword"}}, "_score"]
    if field == "tipoContrato":
        return [{"tipoContrato.keyword": {"order": order}}, "_score"]
    if field == "objectoContrato":
        return [{"objectoContrato.keyword": {"order": order}}, "_score"]
    if field in ("dataPublicacao", "dataCelebracaoContrato"):
        return [{field: {"order": order, "missing": "_last", "unmapped_type": "date"}}, "_score"]
    if field == "precoContratual":
        return [{field: {"order": order, "missing": "_last", "unmapped_type": "float"}}, "_score"]
    return [{"dataPublicacao": {"order": "desc"}}, "_score"]




# Campo do nome das partes por papel (`adjudicantes`/`adjudicatarios`), resolvido no mapping.
_PARTE_NOME_CACHE: Dict[str, str] = {}




def _campo_nome_parte(client: Elasticsearch, papel: str) -> str:
    """Campo agregável do nome da parte (`{papel}.parsed.nome`).

    O mapeamento manda: depois da migração o campo é `keyword` **sem** subcampo
    `.keyword`; antes disso era `text` com `.keyword`. Agregar/consultar o lado
    errado dava 400 («Can only use phrase prefix queries on text fields») e o
    endpoint devolvia 502 (ver `contracts_autocomplete`).
    """
    caminho = f"{papel}.parsed.nome"
    if caminho in _PARTE_NOME_CACHE:
        return _PARTE_NOME_CACHE[caminho]

    destino = caminho
    try:
        mapping = client.indices.get_mapping(index=CONTRACTS_INDEX)
        no: Any = list(mapping.values())[0].get("mappings", {}).get("properties", {})
        partes = caminho.split(".")
        especificacao: Any = {}
        for posicao, parte in enumerate(partes):
            filho = (no or {}).get(parte) or {}
            if posicao == len(partes) - 1:
                especificacao = filho
                break
            # Nos níveis intermédios desce-se pelos `properties` (o campo `parsed`
            # é `nested` com os seus próprios filhos).
            no = filho.get("properties") or {}
        if especificacao.get("type") == "keyword":
            destino = caminho
        elif (especificacao.get("fields") or {}).get("keyword"):
            destino = f"{caminho}.keyword"
    except Exception:
        destino = caminho

    _PARTE_NOME_CACHE[caminho] = destino
    return destino




def contracts_autocomplete(
    q: str,
    size: int = 12,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Sugestões de autocomplete para entidades e CPV.

    Validado no índice real (`contratos`, mapping + sonda):

    - `objectoContrato`/`descContrato` são `text` → `match_phrase_prefix` funciona;
    - as partes são **`keyword`** e **sem** subcampo `.keyword`
      (`adjudicantes.parsed.nome`) → `match_phrase_prefix` dá 400
      («Can only use phrase prefix queries on text fields») e o endpoint devolvia
      **502** ao utilizador; consultar `.keyword` devolvia sempre zero sugestões;
    - `prefix` com `case_insensitive` funciona (o dado está em maiúsculas) e o
      campo é resolvido no mapping (`_campo_nome_parte`), para funcionar quer o
      nome seja `keyword` direto quer `text` com `.keyword`;
    - o `include` da agregação `terms` é inútil neste cluster: a forma com objeto
      é rejeitada («Unknown parameter in Include/Exclude clause») e as formas de
      string (com ou sem `(?i)`) devolvem **zero baldes** — a filtragem do texto
      é feita em Python, depois de o `prefix` já ter restringido os documentos.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "suggestions": []}

    q = q.strip()
    if not q:
        return {"suggestions": []}

    alvo = q.lower()
    campo_adjudicantes = _campo_nome_parte(client, "adjudicantes")
    campo_adjudicatarios = _campo_nome_parte(client, "adjudicatarios")

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "should": [
                            {"match_phrase_prefix": {"objectoContrato": q}},
                            {"match_phrase_prefix": {"descContrato": q}},
                            {
                                "bool": {
                                    "should": [
                                        {
                                            "nested": {
                                                "path": "adjudicantes.parsed",
                                                "query": {"prefix": {campo_adjudicantes: {"value": q, "case_insensitive": True}}},
                                            }
                                        },
                                        {
                                            "nested": {
                                                "path": "adjudicatarios.parsed",
                                                "query": {"prefix": {campo_adjudicatarios: {"value": q, "case_insensitive": True}}},
                                            }
                                        },
                                    ],
                                    "minimum_should_match": 1,
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                },
                # Sem `include`: pede-se um topo maior por grupo e filtra-se o texto
                # em Python (o `include` não funciona neste cluster).
                "aggs": {
                    "adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": campo_adjudicantes,
                                    "size": max(size * 8, 50),
                                    "order": {"_count": "desc"},
                                }
                            }
                        }
                    },
                    "adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": campo_adjudicatarios,
                                    "size": max(size * 8, 50),
                                    "order": {"_count": "desc"},
                                }
                            }
                        }
                    },
                    "cpv_codes": {
                        "nested": {"path": "cpv"},
                        "aggs": {
                            "codes": {
                                "terms": {
                                    "field": "cpv.code",
                                    "size": 40,
                                    "order": {"_count": "desc"},
                                }
                            }
                        }
                    },
                },
            },
        )

        suggestions: List[Dict[str, Any]] = []
        seen = set()
        for agg_key in ("adjudicantes", "adjudicatarios"):
            for bucket in resp["aggregations"][agg_key]["names"]["buckets"]:
                text = bucket["key"]
                # O prefixo já restringiu os documentos: aqui basta o que contém o texto
                # (e o topo por contagem pode trazer nomes que só partilham o documento).
                if not text or alvo not in str(text).lower() or text in seen:
                    continue
                seen.add(text)
                suggestions.append({"text": text, "type": "entity", "count": bucket["doc_count"]})
        for bucket in resp["aggregations"]["cpv_codes"]["codes"]["buckets"]:
            text = bucket["key"]
            if not text or not str(text).lower().startswith(alvo) or text in seen:
                continue
            seen.add(text)
            suggestions.append({"text": text, "type": "cpv", "count": bucket["doc_count"]})

        return {"suggestions": suggestions[:size]}
    except Exception as e:
        return {"error": str(e), "suggestions": []}




def contracts_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve contagem total de contratos indexados e anos conhecidos."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "years": []}

    ensure_indices(client)
    try:
        total = client.count(index=CONTRACTS_INDEX).get("count", 0)
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "aggs": {"years": {"terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}}}},
            },
        )
        years = [int(bucket["key"]) for bucket in resp["aggregations"]["years"]["buckets"]]
        return {"total": total, "years": years}
    except Exception as e:
        return {"error": str(e), "total": 0, "years": []}




def contract_years_available() -> List[int]:
    """Anos de contratos com JSONL normalizado disponível."""
    years = []
    if not (ROOT / "data" / "processed" / "contratos").exists():
        return years
    for path in sorted((ROOT / "data" / "processed" / "contratos").glob("contratos_*.jsonl")):
        m = re.search(r"(\d{4})", path.stem)
        if m:
            years.append(int(m.group(1)))
    return sorted(years)




def _build_contract_query(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    counterparty_nif: Optional[str] = None,
    region: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    role: Optional[str] = None,
    ecological: Optional[bool] = None,
) -> Dict[str, Any]:
    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []

    if q:
        must.append({
            "multi_match": {
                "query": q,
                "fields": [
                    "objectoContrato^3",
                    "descContrato^2",
                    "search_text",
                    "adjudicantes.parsed.nome",
                    "adjudicatarios.parsed.nome",
                    "cpv.description",
                    "localExecucao",
                ],
                "type": "best_fields",
            }
        })

    if year:
        filters.append({"term": {"Ano": year}})
    if entity:
        filters.append({
            "bool": {
                "should": [
                    {
                        "nested": {
                            "path": "adjudicantes.parsed",
                            "query": {"match": {"adjudicantes.parsed.nome": entity}},
                        }
                    },
                    {
                        "nested": {
                            "path": "adjudicatarios.parsed",
                            "query": {"match": {"adjudicatarios.parsed.nome": entity}},
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        })
    if nif and not counterparty_nif:
        filters.append({
            "bool": {
                "should": [
                    {
                        "nested": {
                            "path": "adjudicantes.parsed",
                            "query": {"term": {"adjudicantes.parsed.nif": nif}},
                        }
                    },
                    {
                        "nested": {
                            "path": "adjudicatarios.parsed",
                            "query": {"term": {"adjudicatarios.parsed.nif": nif}},
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        })
    elif nif and counterparty_nif:
        filters.append({
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "adjudicantes.parsed",
                            "query": {"term": {"adjudicantes.parsed.nif": nif}},
                        }
                    },
                    {
                        "nested": {
                            "path": "adjudicatarios.parsed",
                            "query": {"term": {"adjudicatarios.parsed.nif": counterparty_nif}},
                        }
                    },
                ]
            }
        })
    if role in ("adjudicante", "adjudicatario"):
        # Restringe aos contratos em que a parte participa nesse papel. Basta um
        # `match_all` dentro do `nested`: o que se testa é ter filhos nesse caminho.
        role_path = "adjudicantes.parsed" if role == "adjudicante" else "adjudicatarios.parsed"
        filters.append({"nested": {"path": role_path, "query": {"match_all": {}}}})
    if region:
        filters.append(_region_filter(region))
    if cpv_code:
        filters.append({
            "nested": {
                "path": "cpv",
                "query": {"wildcard": {"cpv.code": f"{cpv_code}*"}},
            }
        })
    if ecological:
        # Contratação pública com critérios ecológicos (campo do portal BASE).
        # `ContratEcologico` é `text` com subcampo `.keyword`: o termo tem de usar
        # o subcampo, senão o Elasticsearch recusa (`fielddata disabled`).
        filters.append({"term": {"ContratEcologico.keyword": "Sim"}})

    price_range = {}
    if min_price is not None:
        price_range["gte"] = min_price
    if max_price is not None:
        price_range["lte"] = max_price
    if price_range:
        filters.append({
            "bool": {
                "should": [
                    {"range": {"precoContratual": price_range}},
                    {"range": {"PrecoTotalEfetivo": price_range}},
                ],
                "minimum_should_match": 1,
            }
        })

    date_range = {}
    if start_date:
        date_range["gte"] = start_date
    if end_date:
        date_range["lte"] = end_date
    if date_range:
        filters.append({
            "bool": {
                "should": [
                    {"range": {"dataPublicacao": date_range}},
                    {"range": {"dataCelebracaoContrato": date_range}},
                ],
                "minimum_should_match": 1,
            }
        })

    if not must and not filters:
        return {"match_all": {}}

    query: Dict[str, Any] = {"bool": {}}
    if must:
        query["bool"]["must"] = must
    if filters:
        query["bool"]["filter"] = filters
    return query




_AGG_FIELD_CACHE: Dict[str, Dict[str, Any]] = {}




def _resolve_agg_target(client: Elasticsearch, field: str) -> Dict[str, Any]:
    """Descobre como agregar um campo textual: campo direto, subcampo `.keyword` ou campo de execução.

    O mapeamento real do índice manda: alguns campos declarados como `text` acabam
    indexados como `keyword` (e vice-versa), pelo que agregar `campo.keyword` às cegas
    produzia agregações vazias ("N/A" em todos os contratos).
    """
    cached = _AGG_FIELD_CACHE.get(field)
    if cached:
        return cached

    spec: Dict[str, Any] = {}
    try:
        mapping = client.indices.get_mapping(index=CONTRACTS_INDEX)
        props = list(mapping.values())[0].get("mappings", {}).get("properties", {})
        spec = props.get(field) or {}
    except Exception:
        spec = {}

    if spec.get("type") == "keyword":
        resolved = {"field": field, "runtime": None}
    elif (spec.get("fields") or {}).get("keyword"):
        resolved = {"field": f"{field}.keyword", "runtime": None}
    else:
        runtime_name = f"{field}_kw"
        resolved = {
            "field": runtime_name,
            "runtime": {
                runtime_name: {
                    "type": "keyword",
                    "script": {
                        "source": (
                            "def v = params._source == null ? null : params._source.get('"
                            + field
                            + "'); if (v == null) { return; }"
                            " if (v instanceof List) { for (def item : v) { if (item != null) { emit(item); } } }"
                            " else { emit(v); }"
                        )
                    },
                }
            },
        }

    _AGG_FIELD_CACHE[field] = resolved
    return resolved




def _contract_type_filters(
    client: Elasticsearch,
    procedure_type: Optional[str],
    contract_type: Optional[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Filtros `term` por tipo de procedimento/contrato, com os runtime mappings.

    O campo real só é conhecido depois de `_resolve_agg_target` (keyword,
    `.keyword` ou campo de execução), por isso o filtro não pode viver em
    `_build_contract_query`. Devolve `(filters, runtime_mappings)`.
    """
    filters: List[Dict[str, Any]] = []
    runtime: Dict[str, Any] = {}
    if not procedure_type and not contract_type:
        return filters, runtime
    procedure_agg = _resolve_agg_target(client, "tipoprocedimento")
    contract_agg = _resolve_agg_target(client, "tipoContrato")
    for resolved in (procedure_agg, contract_agg):
        if resolved.get("runtime"):
            runtime.update(resolved["runtime"])
    if procedure_type:
        filters.append({"term": {procedure_agg["field"]: procedure_type}})
    if contract_type:
        filters.append({"term": {contract_agg["field"]: contract_type}})
    return filters, runtime




def get_contract_analytics(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    cpv_code: Optional[str] = None,
    procedure_type: Optional[str] = None,
    contract_type: Optional[str] = None,
    role: Optional[str] = None,
    region: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    top_entities: int = 8,
    top_cpv: int = 8,
    value_buckets: int = 7,
    ecological: Optional[bool] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve agregações analíticas para o dashboard de contratos."""
    # Agregações sobre milhões de contratos: 30 s (o prazo por omissão) não chega
    # e o dashboard ficava com 502 «Connection timed out».
    client = es or get_es_client(request_timeout=120)
    if not client:
        return {"error": "Elasticsearch indisponível"}

    base_query = _build_contract_query(
        q, year, entity, nif, region=region, cpv_code=cpv_code,
        min_price=min_price, max_price=max_price, start_date=start_date, end_date=end_date,
        role=role, ecological=ecological,
    )

    procedure_agg = _resolve_agg_target(client, "tipoprocedimento")
    contract_agg = _resolve_agg_target(client, "tipoContrato")
    runtime_mappings: Dict[str, Any] = {}
    for resolved in (procedure_agg, contract_agg):
        if resolved.get("runtime"):
            runtime_mappings.update(resolved["runtime"])

    # Os filtros por tipo só podem ser montados depois de o campo estar resolvido:
    # entram como `filter` sobre a query base, junto dos respectivos runtime mappings.
    type_filters, type_runtime = _contract_type_filters(client, procedure_type, contract_type)
    runtime_mappings.update(type_runtime)
    base_query = _and_filters(base_query, type_filters)

    analytics_body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": base_query,
        "aggs": {
                    "total_value": {"sum": {"field": "precoContratual"}},
                    "avg_value": {"avg": {"field": "precoContratual"}},
                    "max_value": {"max": {"field": "precoContratual"}},
                    "by_year": {
                        "terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}},
                        "aggs": {
                            "total_value": {"sum": {"field": "precoContratual"}},
                            "avg_value": {"avg": {"field": "precoContratual"}},
                        },
                    },
                    "by_month": {
                        "date_histogram": {
                            "field": "dataPublicacao",
                            "calendar_interval": "month",
                            "format": "yyyy-MM",
                            "min_doc_count": 1,
                        }
                    },
                    "value_distribution": {
                        "histogram": {
                            "field": "precoContratual",
                            "interval": 50000,
                            "min_doc_count": 1,
                        }
                    },
                    "top_adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": "adjudicantes.parsed.nif",
                                    "size": top_entities,
                                    "order": {"total_value": "desc"},
                                },
                                "aggs": {
                                    # `*.parsed.nome` é `keyword` e não pode ser agregado;
                                    # os `top_hits` trazem o nome legível de cada NIF.
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicantes.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "top_adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": "adjudicatarios.parsed.nif",
                                    "size": top_entities,
                                    "order": {"total_value": "desc"},
                                },
                                "aggs": {
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "top_cpv": {
                        "nested": {"path": "cpv"},
                        "aggs": {
                            "codes": {
                                "terms": {
                                    "field": "cpv.code",
                                    "size": top_cpv,
                                    "order": {"_count": "desc"},
                                },
                                "aggs": {
                                    # `cpv.description` é `text` (sem `.keyword`): os `top_hits`
                                    # devolvem a descrição legível de cada documento.
                                    "description": {"top_hits": {"size": 1, "_source": ["cpv"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "procedure_types": {
                        "terms": {"field": procedure_agg["field"], "size": 20, "missing": "N/A"}
                    },
                    "contract_types": {
                        "terms": {"field": contract_agg["field"], "size": 20, "missing": "N/A"}
                    },
                    # Universo distinto por papel: cardinalidade (exata) em vez de
                    # `terms`, que truncaria a contagem no tamanho pedido.
                    "distinct_adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {"value": {"cardinality": {"field": "adjudicantes.parsed.nif"}}},
                    },
                    "distinct_adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {"value": {"cardinality": {"field": "adjudicatarios.parsed.nif"}}},
                    },
                    "distinct_cpv": {
                        "nested": {"path": "cpv"},
                        "aggs": {"value": {"cardinality": {"field": "cpv.code"}}},
                    },
        },
    }
    if runtime_mappings:
        analytics_body["runtime_mappings"] = runtime_mappings

    try:
        resp = client.search(index=CONTRACTS_INDEX, body=analytics_body)

        aggs = resp["aggregations"]

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        def entity_rows_from(agg_key: str) -> List[Dict[str, Any]]:
            """Ranking de uma das partes (adjudicantes ou adjudicatários)."""
            rows: List[Dict[str, Any]] = []
            for b in aggs.get(agg_key, {}).get("names", {}).get("buckets", []):
                key = b["key"]
                if not key:
                    continue
                total_value_obj = b.get("total_value", {})
                value = total_value_obj.get("value", {}).get("value") if isinstance(total_value_obj.get("value"), dict) else total_value_obj.get("value")
                rows.append({
                    "key": key,
                    "count": b["doc_count"],
                    "total_value": fmt_money(value),
                    "description": _top_hit_name(b.get("name")),
                })
            return rows

        # Rankings separados por papel (a UI mostra-os em separado) + lista
        # combinada, que continua a ser o que `top_entities` sempre devolveu.
        adjudicantes = entity_rows_from("top_adjudicantes")
        adjudicatarios = entity_rows_from("top_adjudicatarios")

        entity_rows: List[Dict[str, Any]] = []
        seen_entities: set = set()
        for row in adjudicantes + adjudicatarios:
            if row["key"] in seen_entities:
                continue
            seen_entities.add(row["key"])
            entity_rows.append(row)
        entity_rows.sort(key=lambda x: (x.get("total_value") or 0, x.get("count") or 0), reverse=True)
        entity_rows = entity_rows[:top_entities]

        cpv_rows = []
        for b in aggs.get("top_cpv", {}).get("codes", {}).get("buckets", []):
            total_value_obj = b.get("total_value", {})
            value = total_value_obj.get("value", {}).get("value") if isinstance(total_value_obj.get("value"), dict) else total_value_obj.get("value")
            cpv_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(value),
                "description": _cpv_description_from_hits(b.get("description"), b["key"]),
            })

        def agg_count(agg: Optional[Dict[str, Any]]) -> int:
            return int((agg or {}).get("value", {}).get("value") or 0)

        return {
            "total_contracts": resp["hits"]["total"]["value"],
            "total_value": fmt_money(aggs["total_value"].get("value")),
            "avg_value": fmt_money(aggs["avg_value"].get("value")),
            "max_value": fmt_money(aggs["max_value"].get("value")),
            "distinct_adjudicantes": agg_count(aggs.get("distinct_adjudicantes")),
            "distinct_adjudicatarios": agg_count(aggs.get("distinct_adjudicatarios")),
            "distinct_cpv": agg_count(aggs.get("distinct_cpv")),
            "by_year": [
                {
                    "key": str(b["key"]),
                    "count": b["doc_count"],
                    "total_value": fmt_money(b.get("total_value", {}).get("value")),
                    "avg_value": fmt_money(b.get("avg_value", {}).get("value")),
                }
                for b in aggs["by_year"]["buckets"]
            ],
            "by_month": [{"key": b["key_as_string"], "count": b["doc_count"]} for b in aggs["by_month"]["buckets"]],
            # `precoContratual` tem valores negativos (correções/notas de crédito) que
            # caíam nos primeiros escalões do histograma; ignoram-se aqui.
            "value_distribution": [
                {"key": f"{int(b['key'])} - {int(b['key']) + 50000}", "count": b["doc_count"]}
                for b in aggs["value_distribution"]["buckets"]
                if b.get("key") is not None and b["key"] >= 0
            ][:value_buckets],
            "top_entities": entity_rows,
            "top_adjudicantes": adjudicantes,
            "top_adjudicatarios": adjudicatarios,
            "top_cpv": cpv_rows,
            "procedure_types": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["procedure_types"]["buckets"]],
            "contract_types": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["contract_types"]["buckets"]],
            "year": year,
        }
    except Exception as e:
        return {"error": str(e)}




def get_company_contracts(
    nif: Optional[str] = None,
    name: Optional[str] = None,
    role: Optional[str] = "all",
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve contratos onde a entidade aparece como adjudicante/adjudicatário."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}

    should: List[Dict[str, Any]] = []
    if nif:
        if role in ("all", "adjudicante", None):
            should.append({
                "nested": {
                    "path": "adjudicantes.parsed",
                    "query": {"term": {"adjudicantes.parsed.nif": nif}},
                }
            })
        if role in ("all", "adjudicatario", None):
            should.append({
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"term": {"adjudicatarios.parsed.nif": nif}},
                }
            })
    if name:
        if role in ("all", "adjudicante", None):
            should.append({
                "nested": {
                    "path": "adjudicantes.parsed",
                    "query": {"match": {"adjudicantes.parsed.nome": name}},
                }
            })
        if role in ("all", "adjudicatario", None):
            should.append({
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"match": {"adjudicatarios.parsed.nome": name}},
                }
            })

    if not should:
        return {"error": "É necessário indicar NIF ou nome", "total": 0, "items": []}

    query = {
        "bool": {
            "should": should,
            "minimum_should_match": 1,
        }
    }

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": size,
                "from": from_,
                "query": query,
                "sort": [{"dataPublicacao": {"order": "desc"}}, "_score"],
                "track_total_hits": True,
            },
        )
        items = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            src["doc_id"] = hit["_id"]
            src["score"] = hit.get("_score")
            items.append(src)

        return {
            "nif": nif,
            "name": name,
            "role": role,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
    except Exception as e:
        return {"error": str(e), "total": 0, "items": []}




def _top_hit_name(agg: Optional[Dict[str, Any]]) -> str:
    """Nome legível de um bucket a partir de uma agregação `top_hits`.

    `*.parsed.nome` é `keyword` (não agregável), pelo que o nome vem dos
    documentos; o `_source` pode trazer só o campo pedido ou o objeto completo.
    """
    hits = (agg or {}).get("hits", {}).get("hits", []) or []
    for hit in hits:
        source = hit.get("_source") if isinstance(hit, dict) else None
        if not isinstance(source, dict):
            continue
        name = source.get("nome")
        if isinstance(name, str) and name.strip():
            return name.strip()
        parsed = source.get("parsed")
        if isinstance(parsed, dict):
            nested_name = parsed.get("nome")
            if isinstance(nested_name, str) and nested_name.strip():
                return nested_name.strip()
    return ""




def _cpv_description_from_hits(agg: Optional[Dict[str, Any]], code: Any) -> str:
    """Lê a descrição legível de um CPV a partir de uma agregação `top_hits`.

    `cpv.description` está mapeado como `text` (sem `.keyword`), pelo que não
    pode ser agregado. Os `top_hits` trazem `_source.cpv` — que pode vir como a
    lista completa do documento ou já como o próprio objeto do CPV visitado —
    e aqui escolhe-se a entrada cujo `code` corresponde ao do bucket.
    """
    hits = (agg or {}).get("hits", {}).get("hits", []) or []
    fallback = ""
    for hit in hits:
        source = hit.get("_source") if isinstance(hit, dict) else None
        if not isinstance(source, dict):
            continue
        entries = source.get("cpv")
        if entries is None:
            entries = source
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            description = entry.get("description")
            if not description:
                continue
            if code is None or entry.get("code") == code:
                return description
            if not fallback:
                fallback = description
    return fallback




def get_company_analytics(
    nif: Optional[str] = None,
    name: Optional[str] = None,
    role: Optional[str] = "all",
    year: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve analytics para uma empresa específica."""
    client = es or get_es_client(request_timeout=120)
    if not client:
        return {"error": "Elasticsearch indisponível"}

    should: List[Dict[str, Any]] = []
    if nif:
        if role in ("all", "adjudicante", None):
            should.append({
                "nested": {
                    "path": "adjudicantes.parsed",
                    "query": {"term": {"adjudicantes.parsed.nif": nif}},
                }
            })
        if role in ("all", "adjudicatario", None):
            should.append({
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"term": {"adjudicatarios.parsed.nif": nif}},
                }
            })
    if name:
        if role in ("all", "adjudicante", None):
            should.append({
                "nested": {
                    "path": "adjudicantes.parsed",
                    "query": {"match": {"adjudicantes.parsed.nome": name}},
                }
            })
        if role in ("all", "adjudicatario", None):
            should.append({
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"match": {"adjudicatarios.parsed.nome": name}},
                }
            })

    if not should:
        return {"error": "É necessário indicar NIF ou nome"}

    filters: List[Dict[str, Any]] = []
    if year:
        filters.append({"term": {"Ano": year}})

    query = {"bool": {"should": should, "minimum_should_match": 1}}
    if filters:
        query["bool"]["filter"] = filters

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "track_total_hits": True,
                "query": query,
                "aggs": {
                    "total_value": {"sum": {"field": "precoContratual"}},
                    "avg_value": {"avg": {"field": "precoContratual"}},
                    "max_value": {"max": {"field": "precoContratual"}},
                    "by_year": {
                        "terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}},
                        "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
                    },
                    "by_month": {
                        "date_histogram": {
                            "field": "dataPublicacao",
                            "calendar_interval": "month",
                            "format": "yyyy-MM",
                            "min_doc_count": 1,
                        }
                    },
                    "by_cpv": {
                        "nested": {"path": "cpv"},
                        "aggs": {
                            "codes": {
                                "terms": {"field": "cpv.code", "size": 10, "order": {"total_value": "desc"}},
                                "aggs": {
                                    # `cpv.description` é `text` sem subcampo `.keyword`, pelo que
                                    # uma agregação `terms` devolvia sempre vazio; os `top_hits`
                                    # trazem a descrição real do documento.
                                    "description": {"top_hits": {"size": 1, "_source": ["cpv"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "top_partners": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "by_nif": {
                                "terms": {"field": "adjudicatarios.parsed.nif", "size": 8, "order": {"total_value": "desc"}},
                                "aggs": {
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "procedure_types": {
                        "terms": {"field": "tipoprocedimento.keyword", "size": 20, "missing": "N/A"}
                    },
                    "contract_types": {
                        "terms": {"field": "tipoContrato.keyword", "size": 20, "missing": "N/A"}
                    },
                    "by_value_range": {
                        "histogram": {"field": "precoContratual", "interval": 25000, "min_doc_count": 1}
                    },
                },
            },
        )

        aggs = resp["aggregations"]

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        def extract_value(total_value_obj):
            if isinstance(total_value_obj.get("value"), dict):
                return total_value_obj["value"].get("value")
            return total_value_obj.get("value")

        cpv_rows = []
        for b in aggs.get("by_cpv", {}).get("codes", {}).get("buckets", []):
            cpv_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(extract_value(b.get("total_value", {}))),
                "description": _cpv_description_from_hits(b.get("description"), b["key"]),
            })

        partner_rows = []
        for b in aggs.get("top_partners", {}).get("by_nif", {}).get("buckets", []):
            if b["key"] == nif:
                continue
            partner_name_hits = b.get("name", {}).get("hits", {}).get("hits", [])
            partner_name = ""
            if partner_name_hits:
                partner_src = partner_name_hits[0].get("_source", {})
                if isinstance(partner_src, dict):
                    partner_name = partner_src.get("nome", "")
            partner_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(extract_value(b.get("total_value", {}))),
                "description": partner_name,
            })

        company_summary = None
        if nif:
            company_summary = get_company_by_nif(nif, es=client)
            if "error" in company_summary:
                company_summary = None

        return {
            "company": company_summary,
            "total_contracts": resp["hits"]["total"]["value"],
            "total_value": fmt_money(aggs["total_value"].get("value")),
            "avg_value": fmt_money(aggs["avg_value"].get("value")),
            "max_value": fmt_money(aggs["max_value"].get("value")),
            "by_year": [{"key": str(b["key"]), "count": b["doc_count"], "total_value": fmt_money(b.get("total_value", {}).get("value"))} for b in aggs["by_year"]["buckets"]],
            "by_month": [{"key": b["key_as_string"], "count": b["doc_count"]} for b in aggs["by_month"]["buckets"]],
            "by_cpv": cpv_rows,
            "top_partners": partner_rows,
            "by_procedure_type": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["procedure_types"]["buckets"]],
            "by_contract_type": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["contract_types"]["buckets"]],
            "by_value_range": [{"key": f"{int(b['key'])} - {int(b['key']) + 25000}", "count": b["doc_count"]} for b in aggs["by_value_range"]["buckets"][:10]],
            "year": year,
        }
    except Exception as e:
        return {"error": str(e)}




def list_contract_years(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve anos disponíveis e total indexado por ano.

    Em produção os JSONL normalizados podem não existir no disco, mas o
    Elasticsearch já tem os contratos indexados. Nesse caso, os anos
    disponíveis são os anos que constam do índice, para que o dashboard
    mostre o filtro de anos correctamente.
    """
    client = es or get_es_client()
    available = contract_years_available()
    if not client:
        return {"available": available or [], "indexed": []}
    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "by_year": {
                        "terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}},
                    }
                },
            },
        )
        indexed = [{"year": int(bucket["key"]), "count": bucket["doc_count"]} for bucket in resp["aggregations"]["by_year"]["buckets"]]
        # Se não há JSONL no disco, os anos disponíveis são os anos indexados.
        if not available and indexed:
            available = [item["year"] for item in indexed]
        return {"available": available, "indexed": indexed}
    except Exception as e:
        return {"available": available or [], "indexed": [], "error": str(e)}




def get_contract_by_id(idcontrato: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve um contrato pelo identificador publicado no portal."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    try:
        response = client.search(
            index=CONTRACTS_INDEX,
            body={"size": 1, "query": {"term": {"idcontrato": idcontrato}}},
        )
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return {"error": "Contrato não encontrado", "status_code": 404}
        source = dict(hits[0].get("_source", {}))
        source["doc_id"] = hits[0].get("_id")
        return source
    except Exception as exc:
        return {"error": str(exc)}




def get_contract_regional_analytics(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    cpv_code: Optional[str] = None,
    procedure_type: Optional[str] = None,
    contract_type: Optional[str] = None,
    role: Optional[str] = None,
    region: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    ecological: Optional[bool] = None,
    size: int = 30,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Agrega volume e valor contratual por NUTS, com os mesmos filtros da análise.

    Aceitava apenas `year`, o que desalinhava a distribuição regional do resto do
    dashboard (uma pesquisa por CPV ou entidade não mexia nas regiões). Passou a
    usar `_build_contract_query`, pelo que responde a todos os filtros.
    """
    client = es or get_es_client(request_timeout=120)
    if not client:
        return {"error": "Elasticsearch indisponível", "regions": []}
    query = _build_contract_query(
        q, year, entity, nif, region=region, cpv_code=cpv_code,
        min_price=min_price, max_price=max_price, start_date=start_date, end_date=end_date,
        role=role, ecological=ecological,
    )
    type_filters, runtime_mappings = _contract_type_filters(client, procedure_type, contract_type)
    query = _and_filters(query, type_filters)
    try:
        body: Dict[str, Any] = {
            "track_total_hits": True,
            "size": 0,
            "query": query,
            "aggs": {
                "regions": {
                    "terms": {"field": "NUTs", "size": size, "missing": "Não especificado"},
                    "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
                },
                # Contagem exata de regiões distintas: a lista é truncada por `size`,
                # a cardinalidade não (alimenta o KPI «Regiões com Contratos»).
                "region_count": {"cardinality": {"field": "NUTs"}},
                "total_value": {"sum": {"field": "precoContratual"}},
            },
        }
        if runtime_mappings:
            body["runtime_mappings"] = runtime_mappings
        response = client.search(index=CONTRACTS_INDEX, body=body)
        aggs = response.get("aggregations", {})
        regions = [
            {"key": bucket["key"], "count": bucket["doc_count"], "total_value": bucket.get("total_value", {}).get("value")}
            for bucket in aggs.get("regions", {}).get("buckets", [])
        ]
        distinct = int(aggs.get("region_count", {}).get("value") or 0)
        # A cardinalidade conta apenas documentos com `NUTs`; os que não têm caem
        # no grupo «Não especificado», que também é uma região da lista.
        if any(row["key"] == "Não especificado" for row in regions):
            distinct += 1
        return {
            "total_contracts": response.get("hits", {}).get("total", {}).get("value", 0),
            "total_value": aggs.get("total_value", {}).get("value"),
            "region_count": distinct,
            "regions": regions,
        }
    except Exception as exc:
        return {"error": str(exc), "regions": []}




def _match_pair_query(nif: Optional[str] = None, counterparty_nif: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Returns nested must query for adjudicante/adjudicatario pair when both provided."""
    if nif and counterparty_nif:
        return {
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "adjudicantes.parsed",
                            "query": {"term": {"adjudicantes.parsed.nif": nif}},
                        }
                    },
                    {
                        "nested": {
                            "path": "adjudicatarios.parsed",
                            "query": {"term": {"adjudicatarios.parsed.nif": counterparty_nif}},
                        }
                    },
                ]
            }
        }
    return None




def get_contract_relationships(
    limit: int = 1000,
    region: Optional[str] = None,
    nif: Optional[str] = None,
    counterparty_nif: Optional[str] = None,
    role: Optional[str] = "all",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Constrói relações adjudicante -> adjudicatário a partir dos contratos recentes."""
    client = es or get_es_client(request_timeout=120)
    if not client:
        return {"error": "Elasticsearch indisponível", "relations": []}
    filters: List[Dict[str, Any]] = []
    if region:
        filters.append(_region_filter(region))
    pair_query = _match_pair_query(nif, counterparty_nif)
    if pair_query:
        filters.append(pair_query)
    elif nif:
        # Include any contract where this NIF appears (adjudicante or adjudicatario)
        filters.append({
            "bool": {
                "should": [
                    {"nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": nif}}}},
                    {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": nif}}}},
                ],
                "minimum_should_match": 1,
            }
        })
    query: Dict[str, Any] = {"bool": {"filter": filters}} if filters else {"match_all": {}}
    try:
        response = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": limit,
                "_source": ["adjudicantes.parsed", "adjudicatarios.parsed", "precoContratual", "Ano"],
                "query": query,
                "sort": [{"Ano": {"order": "desc", "unmapped_type": "integer"}}],
            },
        )
        pairs: Dict[str, Dict[str, Any]] = {}
        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            buyers = source.get("adjudicantes", {}).get("parsed", [])
            suppliers = source.get("adjudicatarios", {}).get("parsed", [])
            value = source.get("precoContratual") or 0
            for buyer in buyers:
                for supplier in suppliers:
                    buyer_id = buyer.get("nif") or buyer.get("nome")
                    supplier_id = supplier.get("nif") or supplier.get("nome")
                    if not buyer_id or not supplier_id:
                        continue
                    # Apply role filter after the fact when only one NIF provided
                    if nif and not pair_query:
                        if role == "adjudicante" and buyer_id != nif:
                            continue
                        if role == "adjudicatario" and supplier_id != nif:
                            continue
                    key = f"{buyer_id}|{supplier_id}"
                    pair = pairs.setdefault(key, {
                        "source": buyer_id, "source_name": buyer.get("nome") or buyer_id,
                        "target": supplier_id, "target_name": supplier.get("nome") or supplier_id,
                        "count": 0, "total_value": 0.0,
                    })
                    pair["count"] += 1
                    pair["total_value"] += value
        relations = sorted(pairs.values(), key=lambda item: item["total_value"], reverse=True)[:100]
        for relation in relations:
            relation["total_value"] = round(relation["total_value"], 2)
        return {"relations": relations}
    except Exception as exc:
        return {"error": str(exc), "relations": []}




def get_contract_network(
    limit: int = 500,
    region: Optional[str] = None,
    nif: Optional[str] = None,
    role: Optional[str] = "all",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve nós e ligações para uma visualização de rede de entidades."""
    result = get_contract_relationships(limit=limit, region=region, nif=nif, role=role, es=es)
    if result.get("error"):
        return result
    nodes: Dict[str, Dict[str, Any]] = {}
    edges = []
    for relation in result.get("relations", []):
        for node_id, name, node_type in (
            (relation["source"], relation["source_name"], "adjudicante"),
            (relation["target"], relation["target_name"], "adjudicatario"),
        ):
            nodes.setdefault(node_id, {"id": node_id, "label": name, "type": node_type})
        edges.append({"source": relation["source"], "target": relation["target"], "count": relation["count"], "value": relation["total_value"]})
    return {"nodes": list(nodes.values()), "edges": edges}

# Importações no fim do módulo: evitam ciclos de importação
# (os nomes já estão definidos quando estes módulos são carregados).
from api.es.entidades import get_company_by_nif  # noqa: E402
