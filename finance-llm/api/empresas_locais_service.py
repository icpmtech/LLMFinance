"""**Empresas locais** com participação de entidades municipais.

A fonte é o ficheiro `data/municipios-contatos/empresas locais 12_02_2025.xlsx`,
que traz, para cada empresa:

- designação da entidade;
- entidade local participante;
- entidade participante ou que exerce influência dominante;
- participação (%);
- setor de atividade;
- data de constituição;
- observações.

Os dados são normalizados e indexados em `finance_empresas_locais`, com
pesquisa por texto em vários campos (designação, entidade, setor) — estilo
«Google» — e filtros por entidade local e setor.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from elasticsearch.helpers import bulk

from api.elasticsearch_client import (
    EMPRESAS_LOCAIS_INDEX,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "municipios-contatos"
EXCEL_FILE = "empresas locais 12_02_2025.xlsx"
CACHE_FILE = "empresas_locais.json"
FONTE = "empresas locais 12_02_2025.xlsx"

_LOCK = threading.Lock()


def _data_dir() -> Path:
    path = DEFAULT_DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fold(value: str) -> str:
    """Minúsculas sem acentos, para comparar nomes de empresas e entidades."""
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
    "designacao",
    "entidade_local",
    "entidade_dominante",
    "setor",
    "observacoes",
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


def _data_iso(valor: Any) -> str:
    """Converte data Excel/texto para ISO 8601 (YYYY-MM-DD)."""
    if valor is None or str(valor).strip() == "":
        return ""
    s = str(valor).strip()
    # Já vem como YYYY-MM-DD HH:MM:SS do pandas (dtype=str lê o objeto)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # Formato português DD/MM/YYYY
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return s


def _participacao_num(valor: Any) -> Optional[float]:
    """Extrai a percentagem de participação como número."""
    if valor is None:
        return None
    s = re.sub(r"[^0-9.,]", "", str(valor))
    s = s.replace(",", ".")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _linha_para_doc(r: pd.Series) -> Optional[Dict[str, Any]]:
    """Converte uma linha do DataFrame num documento normalizado."""
    designacao = _normalizar_texto(r.get("Designação da entidade"))
    entidade_local = _normalizar_texto(r.get("Entidade local participante"))
    entidade_dominante = _normalizar_texto(r.get("Entidade participante ou que exerce influência dominante"))
    if not designacao:
        return None
    doc_id = _slug(designacao)
    if not doc_id:
        return None
    participacao = _participacao_num(r.get("Participação\n(%)"))
    setor = _normalizar_texto(r.get("Setor de\natividade"))
    data_constituicao = _data_iso(r.get("Data de\nconstituição"))
    observacoes = _normalizar_texto(r.get("Observações"))
    if observacoes.lower() in ("nan", "none", "null"):
        observacoes = ""

    doc = {
        "doc_id": doc_id,
        "designacao": designacao,
        "designacao_keyword": designacao,
        "entidade_local": entidade_local,
        "entidade_local_keyword": entidade_local,
        "entidade_dominante": entidade_dominante,
        "entidade_dominante_keyword": entidade_dominante,
        "participacao_pct": participacao,
        "setor": setor,
        "setor_keyword": setor,
        "data_constituicao": data_constituicao,
        "observacoes": observacoes,
        "observacoes_keyword": observacoes,
        "slug": _slug(designacao),
        "fonte": FONTE,
    }
    for campo in CAMPOS_NORMALIZADOS:
        doc[f"{campo}_fold"] = _sem_acentos(doc.get(campo) or "")
    return doc


def ler_excel(caminho: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Lê o Excel e devolve as empresas locais normalizadas."""
    import pandas as pd

    path = caminho or (_data_dir() / EXCEL_FILE)
    df = pd.read_excel(path, header=2, dtype=str)
    df = df.dropna(how="all")
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
    """Lê o Excel e guarda/normaliza as empresas locais em cache."""
    with _LOCK:
        docs = None if forcar else _ler_cache()
        if docs is None:
            docs = ler_excel()
            _guardar_cache(docs)
    return {"total": len(docs), "fonte": FONTE, "recolhido_em": _now_iso()}


def _reset_index(client: Any) -> None:
    try:
        client.indices.delete(index=EMPRESAS_LOCAIS_INDEX, ignore_unavailable=True)
    except Exception as exc:
        logger.warning("Não foi possível limpar %s: %s", EMPRESAS_LOCAIS_INDEX, exc)


def indexar(docs: Iterable[Dict[str, Any]], substituir: bool = False) -> Dict[str, Any]:
    """Indexa as empresas locais no Elasticsearch."""
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
            "_index": EMPRESAS_LOCAIS_INDEX,
            "_id": source["doc_id"],
            **source,
        })
    if not actions:
        return {"indexed": 0}
    try:
        indexed, errors = bulk(client, actions, raise_on_error=False)
        client.indices.refresh(index=EMPRESAS_LOCAIS_INDEX)
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
    should: List[Dict[str, Any]] = [
        {"match_phrase": {"designacao": {"query": termo, "boost": 10}}},
        {"match_phrase": {"entidade_local": {"query": termo, "boost": 8}}},
        {"match_phrase": {"entidade_dominante": {"query": termo, "boost": 8}}},
        {"match": {"designacao": {"query": termo, "operator": "and", "boost": 6}}},
        {"match": {"entidade_local": {"query": termo, "operator": "and", "boost": 4}}},
        {"match": {"entidade_dominante": {"query": termo, "operator": "and", "boost": 4}}},
        {"match": {"setor": {"query": termo, "operator": "and", "boost": 3}}},
        {"match": {"observacoes": {"query": termo, "operator": "and", "boost": 1}}},
    ]
    termo_fold = _sem_acentos(termo)
    if termo_fold:
        for campo in CAMPOS_NORMALIZADOS:
            should.append({
                "wildcard": {f"{campo}_fold": {"value": f"*{termo_fold}*", "boost": 2}}
            })
    for field in ("designacao_keyword", "entidade_local_keyword", "entidade_dominante_keyword", "setor_keyword"):
        should.append({"wildcard": {field: {"value": f"*{termo}*", "case_insensitive": True}}})
    return {
        "bool": {
            "should": should,
            "minimum_should_match": 1,
        }
    }


def pesquisar(
    q: Optional[str] = None,
    entidade_local: Optional[str] = None,
    setor: Optional[str] = None,
    size: int = 30,
    page: int = 1,
    es: Optional[Any] = None,
) -> Dict[str, Any]:
    """Pesquisa Google-like no índice `finance_empresas_locais`."""
    client = es or get_es_client()
    if not client:
        return _pesquisar_local(q=q, entidade_local=entidade_local, setor=setor, size=size, page=page)
    ensure_indices(client)

    filters: List[Dict[str, Any]] = []
    text_query = _build_text_query(q)
    if entidade_local:
        filters.append({"wildcard": {"entidade_local.keyword": {"value": f"*{entidade_local}*", "case_insensitive": True}}})
    if setor:
        filters.append({"wildcard": {"setor.keyword": {"value": f"*{setor}*", "case_insensitive": True}}})

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
        "sort": [{"_score": {"order": "desc"}}, {"designacao.keyword": {"order": "asc"}}],
        "track_total_hits": True,
        "aggs": {
            "por_entidade": {"terms": {"field": "entidade_local.keyword", "size": 50}},
            "por_setor": {"terms": {"field": "setor.keyword", "size": 20}},
        },
    }

    try:
        resp = client.search(index=EMPRESAS_LOCAIS_INDEX, body=body)
        total = resp["hits"]["total"]["value"]
        items = [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]]
        entidades = [
            {"key": b["key"], "count": b["doc_count"]}
            for b in (resp.get("aggregations", {}).get("por_entidade", {}) or {}).get("buckets", [])
        ]
        setores = [
            {"key": b["key"], "count": b["doc_count"]}
            for b in (resp.get("aggregations", {}).get("por_setor", {}) or {}).get("buckets", [])
        ]
        return {
            "total": total,
            "page": page,
            "size": size,
            "items": items,
            "entidades": entidades,
            "setores": setores,
            "origem": "elasticsearch",
        }
    except Exception as exc:
        logger.warning("Falha na pesquisa Elasticsearch: %s", exc)
        return _pesquisar_local(q=q, entidade_local=entidade_local, setor=setor, size=size, page=page)


def _pesquisar_local(
    q: Optional[str] = None,
    entidade_local: Optional[str] = None,
    setor: Optional[str] = None,
    size: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    docs = _docs_disponiveis()
    alvo = _fold(q) if q else ""
    ent = _fold(entidade_local) if entidade_local else ""
    set = _fold(setor) if setor else ""
    itens: List[Dict[str, Any]] = []
    for doc in docs:
        if ent and ent not in _fold(doc.get("entidade_local") or ""):
            continue
        if set and set not in _fold(doc.get("setor") or ""):
            continue
        if alvo:
            campos = " ".join([
                doc.get("designacao") or "",
                doc.get("entidade_local") or "",
                doc.get("entidade_dominante") or "",
                doc.get("setor") or "",
                doc.get("observacoes") or "",
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
        "entidades": [],
        "setores": [],
        "origem": "json-local",
    }


def ficha(doc_id: str) -> Dict[str, Any]:
    """Devolve a ficha completa de uma empresa local pelo doc_id/slug."""
    slug = _slug(doc_id)
    client = get_es_client()
    if client:
        ensure_indices(client)
        try:
            resp = client.get(index=EMPRESAS_LOCAIS_INDEX, id=slug, ignore=404)
            if resp.get("found"):
                return {**resp["_source"], "doc_id": resp["_id"]}
        except Exception as exc:
            logger.warning("Falha a ler ficha do Elasticsearch: %s", exc)
    for doc in _docs_disponiveis():
        if doc.get("doc_id") == slug:
            return doc
    return {"error": f"Empresa local «{doc_id}» não encontrada."}


def stats(es: Optional[Any] = None) -> Dict[str, Any]:
    """Resumo do índice de empresas locais."""
    client = es or get_es_client()
    if not client:
        docs = _docs_disponiveis()
        entidades: Dict[str, int] = {}
        setores: Dict[str, int] = {}
        for d in docs:
            entidades[d["entidade_local"]] = entidades.get(d["entidade_local"], 0) + 1
            setores[d["setor"]] = setores.get(d["setor"], 0) + 1
        return {
            "index": EMPRESAS_LOCAIS_INDEX,
            "documents": len(docs),
            "por_entidade": [{"key": k, "count": v} for k, v in sorted(entidades.items())],
            "por_setor": [{"key": k, "count": v} for k, v in sorted(setores.items())],
            "origem": "json-local",
        }
    ensure_indices(client)
    try:
        count = client.count(index=EMPRESAS_LOCAIS_INDEX).get("count", 0)
        resp = client.search(
            index=EMPRESAS_LOCAIS_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "por_entidade": {"terms": {"field": "entidade_local.keyword", "size": 50}},
                    "por_setor": {"terms": {"field": "setor.keyword", "size": 20}},
                },
            },
        )
        return {
            "index": EMPRESAS_LOCAIS_INDEX,
            "documents": count,
            "por_entidade": [
                {"key": b["key"], "count": b["doc_count"]}
                for b in (resp.get("aggregations", {}).get("por_entidade", {}) or {}).get("buckets", [])
            ],
            "por_setor": [
                {"key": b["key"], "count": b["doc_count"]}
                for b in (resp.get("aggregations", {}).get("por_setor", {}) or {}).get("buckets", [])
            ],
            "origem": "elasticsearch",
        }
    except Exception as exc:
        return {"error": str(exc)}
