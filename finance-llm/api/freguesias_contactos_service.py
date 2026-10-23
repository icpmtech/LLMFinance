"""Contactos das **juntas de freguesia** portuguesas.

A fonte é o ficheiro `data/municipios-contatos/Contactos_freguesias.xlsx`, que
traz, para cada freguesia:

- município;
- nome da freguesia;
- código INE (6 dígitos);
- NIF da junta;
- e-mail;
- telefone;
- morada, código postal, localidade e descrição postal;
- presidente.

Os dados são normalizados e indexados em `finance_freguesias_contactos`, com
pesquisa por texto em vários campos (nome, presidente, e-mail, morada,
município) — estilo «Google» — e filtros por município e por código INE.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from elasticsearch.helpers import bulk

from api.elasticsearch_client import (
    FREGUESIAS_CONTACTOS_INDEX,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "municipios-contatos"
EXCEL_FILE = "Contactos_freguesias.xlsx"
CACHE_FILE = "freguesias_contactos.json"
FONTE = "Contactos_freguesias.xlsx"

_LOCK = threading.Lock()


def _data_dir() -> Path:
    path = DEFAULT_DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fold(value: str) -> str:
    """Minúsculas sem acentos, para comparar nomes de pessoas e de freguesias."""
    sem_acentos = unicodedata.normalize("NFKD", value or "")
    sem_acentos = "".join(ch for ch in sem_acentos if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", sem_acentos).strip().lower()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _fold(value)).strip("-")


def _sem_acentos(value: str) -> str:
    """Texto em minúsculas, sem acentos e sem pontuação — chave de pesquisa."""
    return re.sub(r"[^a-z0-9@. ]+", " ", _fold(value)).strip()


#: Campos de texto que ganham uma versão **sem acentos** para a pesquisa por
#: fragmento.
CAMPOS_NORMALIZADOS = (
    "freguesia",
    "nome_presidente",
    "municipio",
    "localidade",
    "morada",
    "email",
    "descricao_postal",
)


def _normalizar_texto(s: Any) -> str:
    if s is None:
        return ""
    s = str(s).strip()
    if "\ufffd" in s:
        try:
            s = s.encode("latin1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
    return s


def _codigo_ine_6_digitos(valor: Any) -> str:
    """Garante 6 dígitos (ex.: '1401' → '001401')."""
    s = re.sub(r"[^0-9]", "", str(valor or ""))
    return s.zfill(6) if s else ""


def _codigo_postal_localidade(cp: str) -> Tuple[str, str]:
    m = re.match(r"(\d{4}-\d{3})\s*(.*)", cp)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", cp.strip()


def _telefone_limpo(valor: Any) -> str:
    s = re.sub(r"[^0-9+/]", "", str(valor or ""))
    # Remove barras, deixa só o primeiro número quando há vários separados por /
    if "/" in s:
        s = s.split("/")[0]
    return s


def _linha_para_doc(r: pd.Series) -> Optional[Dict[str, Any]]:
    """Converte uma linha do DataFrame num documento normalizado."""
    municipio = _normalizar_texto(r.get("MUNICÍPIO"))
    freguesia = _normalizar_texto(r.get("NOME"))
    codigo = _codigo_ine_6_digitos(r.get("Cod.INE"))
    if not codigo or not freguesia:
        return None
    nif = re.sub(r"[^0-9]", "", str(r.get("NIF") or ""))
    email = _normalizar_texto(r.get("EMAIL")).lower()
    telefone = _telefone_limpo(r.get("TELEFONE"))
    morada = _normalizar_texto(r.get("MORADA"))
    cp_raw = _normalizar_texto(r.get("CÓDIGO POSTAL"))
    codigo_postal, localidade = _codigo_postal_localidade(cp_raw)
    descricao_postal = _normalizar_texto(r.get("DESCRIÇÃO POSTAL"))
    presidente = _normalizar_texto(r.get("Presidente"))

    doc = {
        "doc_id": codigo,
        "municipio": municipio,
        "municipio_keyword": municipio,
        "freguesia": freguesia,
        "freguesia_keyword": freguesia,
        "codigo_ine": codigo,
        "nif": nif,
        "nome_presidente": presidente,
        "nome_presidente_keyword": presidente,
        "morada": morada,
        "codigo_postal": codigo_postal,
        "localidade": localidade,
        "localidade_keyword": localidade,
        "descricao_postal": descricao_postal,
        "descricao_postal_keyword": descricao_postal,
        "email": email,
        "telefone": telefone,
        "slug": _slug(freguesia),
        "fonte": FONTE,
    }
    for campo in CAMPOS_NORMALIZADOS:
        doc[f"{campo}_fold"] = _sem_acentos(doc.get(campo) or "")
    return doc


def ler_excel(caminho: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Lê o Excel e devolve os contactos de freguesias normalizados."""
    import pandas as pd

    path = caminho or (_data_dir() / EXCEL_FILE)
    df = pd.read_excel(path, header=2, dtype=str)
    docs: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        doc = _linha_para_doc(row)
        if doc:
            docs.append(doc)
    return docs


def _cache_path() -> Path:
    return _data_dir() / CACHE_FILE


def _guardar_cache(docs: List[Dict[str, Any]]) -> Path:
    path = _cache_path()
    payload = {"gerado_em": _now_iso(), "fonte": FONTE, "total": len(docs), "items": docs}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _ler_cache() -> Optional[List[Dict[str, Any]]]:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("items")
    except Exception as exc:
        logger.warning("Cache %s ilegível: %s", path, exc)
        return None


def recolher(forcar: bool = False) -> Dict[str, Any]:
    """Lê o Excel e guarda/normaliza os contactos em cache."""
    with _LOCK:
        docs = None if forcar else _ler_cache()
        if docs is None:
            docs = ler_excel()
            _guardar_cache(docs)
    return {"total": len(docs), "fonte": FONTE, "recolhido_em": _now_iso()}


def _reset_index(client: Any) -> None:
    try:
        client.indices.delete(index=FREGUESIAS_CONTACTOS_INDEX, ignore_unavailable=True)
    except Exception as exc:
        logger.warning("Não foi possível limpar %s: %s", FREGUESIAS_CONTACTOS_INDEX, exc)


def indexar(docs: Iterable[Dict[str, Any]], substituir: bool = False) -> Dict[str, Any]:
    """Indexa os contactos das freguesias no Elasticsearch."""
    client = get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed": 0}
    if substituir:
        _reset_index(client)
    ensure_indices(client)

    now = _now_iso()
    actions = []
    for doc in docs:
        source = dict(doc)
        for campo in CAMPOS_NORMALIZADOS:
            source.setdefault(f"{campo}_fold", _sem_acentos(source.get(campo) or ""))
        source.setdefault("ingested_at", now)
        source.setdefault("updated_at", now)
        actions.append({
            "_op_type": "index",
            "_index": FREGUESIAS_CONTACTOS_INDEX,
            "_id": source["doc_id"],
            **source,
        })
    if not actions:
        return {"indexed": 0}
    try:
        indexed, errors = bulk(client, actions, raise_on_error=False)
        client.indices.refresh(index=FREGUESIAS_CONTACTOS_INDEX)
        return {"indexed": indexed, "errors": len(errors) if errors else 0}
    except Exception as exc:
        return {"error": str(exc), "indexed": 0}


def recolher_e_indexar(forcar: bool = False) -> Dict[str, Any]:
    """Lê o Excel e indexa tudo no Elasticsearch."""
    recolher(forcar=forcar)
    docs = _ler_cache() or ler_excel()
    indexacao = indexar(docs, substituir=True)
    return {
        "recolhido_em": _now_iso(),
        "total": len(docs),
        "indexacao": indexacao,
        "fonte": FONTE,
    }


def _docs_disponiveis() -> List[Dict[str, Any]]:
    cache = _ler_cache()
    if cache is not None:
        return cache
    docs = ler_excel()
    _guardar_cache(docs)
    return docs


def _build_text_query(q: Optional[str]) -> Optional[Dict[str, Any]]:
    termo = str(q or "").strip()
    if not termo:
        return None
    termos = [t for t in re.split(r"[\s\-_/,.;:()]+", termo) if len(t) >= 2]
    should: List[Dict[str, Any]] = [
        {"match_phrase": {"freguesia": {"query": termo, "boost": 10}}},
        {"match_phrase": {"nome_presidente": {"query": termo, "boost": 8}}},
        {"match": {"freguesia": {"query": termo, "operator": "and", "boost": 6}}},
        {"match": {"nome_presidente": {"query": termo, "operator": "and", "boost": 4}}},
        {"match": {"municipio": {"query": termo, "operator": "and", "boost": 4}}},
        {"match": {"morada": {"query": termo, "operator": "and", "boost": 2}}},
        {"match": {"localidade": {"query": termo, "operator": "and", "boost": 2}}},
        {"match": {"descricao_postal": {"query": termo, "operator": "and", "boost": 1}}},
        {"match": {"email": {"query": termo, "operator": "and", "boost": 3}}},
    ]
    termo_fold = _sem_acentos(termo)
    if termo_fold:
        for campo in CAMPOS_NORMALIZADOS:
            should.append({
                "wildcard": {f"{campo}_fold": {"value": f"*{termo_fold}*", "boost": 2}}
            })
    for field in ("freguesia_keyword", "nome_presidente_keyword", "codigo_ine"):
        should.append({"wildcard": {field: {"value": f"*{termo}*", "case_insensitive": True}}})
    digitos = re.sub(r"[^0-9]", "", termo)
    if digitos:
        for field in ("telefone", "codigo_ine", "nif", "codigo_postal"):
            should.append({"wildcard": {field: {"value": f"*{digitos}*"}}})
    return {
        "bool": {
            "should": should,
            "minimum_should_match": 1,
        }
    }


def pesquisar(
    q: Optional[str] = None,
    municipio: Optional[str] = None,
    codigo_ine: Optional[str] = None,
    size: int = 30,
    page: int = 1,
    es: Optional[Any] = None,
) -> Dict[str, Any]:
    """Pesquisa Google-like no índice `finance_freguesias_contactos`."""
    client = es or get_es_client()
    if not client:
        return _pesquisar_local(q=q, municipio=municipio, codigo_ine=codigo_ine, size=size, page=page)
    ensure_indices(client)

    filters: List[Dict[str, Any]] = []
    text_query = _build_text_query(q)
    if municipio:
        filters.append({"wildcard": {"municipio.keyword": {"value": f"*{municipio}*", "case_insensitive": True}}})
    if codigo_ine:
        filters.append({"term": {"codigo_ine": re.sub(r"[^0-9]", "", codigo_ine)}})

    bool_query: Dict[str, Any] = {}
    if text_query:
        bool_query["must"] = text_query
    if filters:
        bool_query["filter"] = filters
    query = {"bool": bool_query} if bool_query else {"match_all": {}}

    from_ = max(0, (max(1, page) - 1) * max(1, size))
    body = {
        "query": query,
        "from": from_,
        "size": max(1, min(size, 500)),
        "sort": [{"_score": {"order": "desc"}}, {"freguesia.keyword": {"order": "asc"}}],
        "track_total_hits": True,
        "aggs": {
            "por_municipio": {"terms": {"field": "municipio.keyword", "size": 50}},
        },
    }

    try:
        resp = client.search(index=FREGUESIAS_CONTACTOS_INDEX, body=body)
        total = resp["hits"]["total"]["value"]
        items = [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]]
        municipios = [
            {"key": b["key"], "count": b["doc_count"]}
            for b in (resp.get("aggregations", {}).get("por_municipio", {}) or {}).get("buckets", [])
        ]
        return {
            "total": total,
            "page": page,
            "size": size,
            "items": items,
            "municipios": municipios,
            "origem": "elasticsearch",
        }
    except Exception as exc:
        logger.warning("Falha na pesquisa Elasticsearch: %s", exc)
        return _pesquisar_local(q=q, municipio=municipio, codigo_ine=codigo_ine, size=size, page=page)


def _pesquisar_local(
    q: Optional[str] = None,
    municipio: Optional[str] = None,
    codigo_ine: Optional[str] = None,
    size: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    docs = _docs_disponiveis()
    alvo = _fold(q) if q else ""
    m = _fold(municipio) if municipio else ""
    cod = re.sub(r"[^0-9]", "", codigo_ine or "")
    itens: List[Dict[str, Any]] = []
    for doc in docs:
        if cod and doc.get("codigo_ine") != cod:
            continue
        if m and m not in _fold(doc.get("municipio") or ""):
            continue
        if alvo:
            campos = " ".join([
                doc.get("freguesia") or "",
                doc.get("nome_presidente") or "",
                doc.get("email") or "",
                doc.get("morada") or "",
                doc.get("localidade") or "",
                doc.get("municipio") or "",
                doc.get("descricao_postal") or "",
                doc.get("telefone") or "",
                doc.get("codigo_ine") or "",
            ])
            if alvo not in _fold(campos):
                continue
        itens.append(doc)
    inicio = max(0, (max(1, page) - 1) * max(1, size))
    return {
        "total": len(itens),
        "page": page,
        "size": size,
        "items": itens[inicio : inicio + size],
        "municipios": [],
        "origem": "json-local",
    }


def ficha(codigo_ine: str) -> Dict[str, Any]:
    """Devolve a ficha completa de uma freguesia pelo código INE."""
    cod = re.sub(r"[^0-9]", "", codigo_ine).zfill(6)
    client = get_es_client()
    if client:
        ensure_indices(client)
        try:
            resp = client.get(index=FREGUESIAS_CONTACTOS_INDEX, id=cod, ignore=404)
            if resp.get("found"):
                return {**resp["_source"], "doc_id": resp["_id"]}
        except Exception as exc:
            logger.warning("Falha a ler ficha do Elasticsearch: %s", exc)
    for doc in _docs_disponiveis():
        if doc.get("codigo_ine") == cod:
            return doc
    return {"error": f"Freguesia com código INE «{codigo_ine}» não encontrada."}


def stats(es: Optional[Any] = None) -> Dict[str, Any]:
    """Resumo do índice de contactos de freguesias."""
    client = es or get_es_client()
    if not client:
        docs = _docs_disponiveis()
        municipios: Dict[str, int] = {}
        for d in docs:
            municipios[d["municipio"]] = municipios.get(d["municipio"], 0) + 1
        return {
            "index": FREGUESIAS_CONTACTOS_INDEX,
            "documents": len(docs),
            "por_municipio": [{"key": k, "count": v} for k, v in sorted(municipios.items())],
            "origem": "json-local",
        }
    ensure_indices(client)
    try:
        count = client.count(index=FREGUESIAS_CONTACTOS_INDEX).get("count", 0)
        resp = client.search(
            index=FREGUESIAS_CONTACTOS_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "por_municipio": {"terms": {"field": "municipio.keyword", "size": 50}},
                },
            },
        )
        return {
            "index": FREGUESIAS_CONTACTOS_INDEX,
            "documents": count,
            "por_municipio": [
                {"key": b["key"], "count": b["doc_count"]}
                for b in (resp.get("aggregations", {}).get("por_municipio", {}) or {}).get("buckets", [])
            ],
            "origem": "elasticsearch",
        }
    except Exception as exc:
        return {"error": str(exc)}
