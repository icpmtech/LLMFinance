"""Contactos das **308 câmaras municipais** portuguesas.

A fonte é o ficheiro `data/municipios-contatos/contactos presidente CM 04092026.xlsx`,
que traz, para cada município:

- distrito;
- nome do município;
- código INE (4 dígitos);
- NIF da câmara;
- nome do presidente;
- morada, código postal e localidade;
- e-mail;
- telefone;
- sítio Web.

Os dados são normalizados e indexados em `finance_municipios_contactos`, com
pesquisa por texto em vários campos (nome do município, presidente, e-mail,
morada, distrito) — estilo «Google» — e filtros por distrito e por código INE.

A pesquisa é **insensível a acentos**: cada campo de texto ganha uma versão
dobrada em `*_fold` (ver `CAMPOS_NORMALIZADOS`), porque o `world_folding` do
analisador só actua em campos `text` — um `wildcard` sobre um `keyword` compara
os bytes tal como estão e «alcac» não encontrava «ALCÁCER». É assim que as
pessoas escrevem numa caixa de pesquisa, e é o que faz «evor», «serta» e
«braganca» devolverem o município certo.
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

import httpx
from elasticsearch.helpers import bulk

from api.elasticsearch_client import (
    MUNICIPIOS_CONTACTOS_INDEX,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "municipios-contatos"
EXCEL_FILE = "contactos presidente CM 04092026.xlsx"
CACHE_FILE = "municipios_contactos.json"
FONTE = "Contactos presidente CM 04092026.xlsx"

_LOCK = threading.Lock()

USER_AGENT = "IQOS/1.0 (analise de financas publicas; contacto@icpm.tech)"


def _data_dir() -> Path:
    path = DEFAULT_DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _fold(value: str) -> str:
    """Minúsculas sem acentos, para comparar nomes de pessoas e de concelhos."""
    sem_acentos = unicodedata.normalize("NFKD", value or "")
    sem_acentos = "".join(ch for ch in sem_acentos if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", sem_acentos).strip().lower()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _fold(value)).strip("-")


#: Campos de texto que ganham uma versão **sem acentos** para a pesquisa por
#: fragmento. O `world_folding` do analisador só actua nos campos `text`; um
#: `wildcard` sobre um `keyword` compara os bytes tal como estão, e por isso
#: «alcac» não encontrava «ALCÁCER» nem «evor» encontrava «ÉVORA».
CAMPOS_NORMALIZADOS = (
    "municipio",
    "nome_presidente",
    "distrito",
    "localidade",
    "morada",
    "email",
)


def _sem_acentos(value: str) -> str:
    """Texto em minúsculas, sem acentos e sem pontuação — chave de pesquisa."""
    return re.sub(r"[^a-z0-9@. ]+", " ", _fold(value)).strip()


def _normalizar_texto(s: Any) -> str:
    if s is None:
        return ""
    s = str(s).strip()
    # O ficheiro xlsx declara UTF-8 mas os caracteres acentuados chegam como
    # U+FFFD (substituição). Tentamos recuperar via latin-1 quando possível.
    if "\ufffd" in s:
        try:
            s = s.encode("latin1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass
    return s


def _codigo_ine_4_digitos(valor: Any) -> str:
    """Garante 4 dígitos (ex.: '101' → '0101')."""
    s = re.sub(r"[^0-9]", "", str(valor or ""))
    return s.zfill(4) if s else ""


def _codigo_postal_localidade(cp: str) -> Tuple[str, str]:
    m = re.match(r"(\d{4}-\d{3})\s*(.*)", cp)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", cp.strip()


def _site_url(site: str) -> str:
    """Endereço completo do sítio. A coluna do Excel traz espaços à volta."""
    limpo = str(site or "").strip().rstrip("/")
    if not limpo:
        return ""
    if limpo.startswith("http://") or limpo.startswith("https://"):
        return limpo
    return "https://" + limpo.lstrip("/")


def _linha_para_doc(r: pd.Series) -> Optional[Dict[str, Any]]:
    """Converte uma linha do DataFrame num documento normalizado."""
    distrito = _normalizar_texto(r.iloc[0]).replace("Distrito ", "")
    municipio = _normalizar_texto(r.iloc[1])
    codigo = _codigo_ine_4_digitos(r.iloc[2])
    if not codigo or not municipio:
        return None
    nif = re.sub(r"[^0-9]", "", str(r.iloc[3] or ""))
    presidente = _normalizar_texto(r.iloc[4])
    morada = _normalizar_texto(r.iloc[5])
    cp_raw = _normalizar_texto(r.iloc[6])
    codigo_postal, localidade = _codigo_postal_localidade(cp_raw)
    email = _normalizar_texto(r.iloc[7]).lower()
    telefone = re.sub(r"[^0-9+]", "", str(r.iloc[8] or ""))
    site = _site_url(_normalizar_texto(r.iloc[9]))
    doc = {
        "doc_id": codigo,
        "distrito": distrito,
        "distrito_keyword": distrito,
        "municipio": municipio,
        "municipio_keyword": municipio,
        "codigo_ine": codigo,
        "nif": nif,
        "nome_presidente": presidente,
        "nome_presidente_keyword": presidente,
        "morada": morada,
        "codigo_postal": codigo_postal,
        "localidade": localidade,
        "email": email,
        "telefone": telefone,
        "site": site,
        "site_domain": site.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0] if site else "",
        "slug": _slug(municipio),
        "fonte": FONTE,
    }
    for campo in CAMPOS_NORMALIZADOS:
        doc[f"{campo}_fold"] = _sem_acentos(doc.get(campo) or "")
    return doc


def ler_excel(caminho: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Lê o Excel e devolve os 308 contactos normalizados."""
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
        client.indices.delete(index=MUNICIPIOS_CONTACTOS_INDEX, ignore_unavailable=True)
    except Exception as exc:
        logger.warning("Não foi possível limpar %s: %s", MUNICIPIOS_CONTACTOS_INDEX, exc)


def indexar(docs: Iterable[Dict[str, Any]], substituir: bool = False) -> Dict[str, Any]:
    """Indexa os contactos no Elasticsearch.

    Com `substituir=True` o índice é apagado primeiro, para evitar duplicados
    ou registos obsoletos.
    """
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
        # Uma cache antiga pode não trazer os campos sem acentos: calculam-se
        # aqui para o índice ficar sempre pesquisável por fragmentos.
        for campo in CAMPOS_NORMALIZADOS:
            source.setdefault(f"{campo}_fold", _sem_acentos(source.get(campo) or ""))
        source.setdefault("ingested_at", now)
        source.setdefault("updated_at", now)
        actions.append({
            "_op_type": "index",
            "_index": MUNICIPIOS_CONTACTOS_INDEX,
            "_id": source["doc_id"],
            **source,
        })
    if not actions:
        return {"indexed": 0}
    try:
        indexed, errors = bulk(client, actions, raise_on_error=False)
        client.indices.refresh(index=MUNICIPIOS_CONTACTOS_INDEX)
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
    """Constrói a parte de pesquisa por texto livre estilo Google.

    - Frase exacta ganha boost;
    - Depois match em todos os termos (AND);
    - Se o utilizador procurar por um único termo, também casamos em substrings
      (wildcard) no nome, presidente, e-mail, morada, telefone e distrito.
    """
    termo = str(q or "").strip()
    if not termo:
        return None
    termos = [t for t in re.split(r"[\s\-_/,.;:()]+", termo) if len(t) >= 2]
    should: List[Dict[str, Any]] = [
        {"match_phrase": {"municipio": {"query": termo, "boost": 10}}},
        {"match_phrase": {"nome_presidente": {"query": termo, "boost": 8}}},
        {"match": {"municipio": {"query": termo, "operator": "and", "boost": 6}}},
        {"match": {"nome_presidente": {"query": termo, "operator": "and", "boost": 4}}},
        {"match": {"morada": {"query": termo, "operator": "and", "boost": 2}}},
        {"match": {"localidade": {"query": termo, "operator": "and", "boost": 2}}},
        {"match": {"distrito": {"query": termo, "operator": "and", "boost": 2}}},
        {"match": {"email": {"query": termo, "operator": "and", "boost": 3}}},
    ]
    # Wildcards sobre os campos **sem acentos**: é o que faz «alcac» encontrar
    # «ALCÁCER» e «evor» encontrar «ÉVORA». Os `keyword` originais continuam a
    # apanhar o texto tal como foi escrito («ÁGUEDA»).
    termo_fold = _sem_acentos(termo)
    if termo_fold:
        for campo in CAMPOS_NORMALIZADOS:
            should.append({
                "wildcard": {f"{campo}_fold": {"value": f"*{termo_fold}*", "boost": 2}}
            })
    for field in ("municipio_keyword", "nome_presidente_keyword", "codigo_ine"):
        should.append({"wildcard": {field: {"value": f"*{termo}*", "case_insensitive": True}}})
    # Telefone e código INE são só dígitos: um wildcard apanha o prefixo.
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
    distrito: Optional[str] = None,
    codigo_ine: Optional[str] = None,
    size: int = 30,
    page: int = 1,
    es: Optional[Any] = None,
) -> Dict[str, Any]:
    """Pesquisa Google-like no índice `finance_municipios_contactos`."""
    client = es or get_es_client()
    if not client:
        # Fallback em memória (os 308 cabem facilmente)
        return _pesquisar_local(q=q, distrito=distrito, codigo_ine=codigo_ine, size=size, page=page)
    ensure_indices(client)

    filters: List[Dict[str, Any]] = []
    text_query = _build_text_query(q)
    if distrito:
        filters.append({"wildcard": {"distrito.keyword": {"value": f"*{distrito}*", "case_insensitive": True}}})
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
        "sort": [{"_score": {"order": "desc"}}, {"municipio.keyword": {"order": "asc"}}],
        "track_total_hits": True,
        "aggs": {
            "por_distrito": {"terms": {"field": "distrito.keyword", "size": 30}},
        },
    }

    try:
        resp = client.search(index=MUNICIPIOS_CONTACTOS_INDEX, body=body)
        total = resp["hits"]["total"]["value"]
        items = [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]]
        distritos = [
            {"key": b["key"], "count": b["doc_count"]}
            for b in (resp.get("aggregations", {}).get("por_distrito", {}) or {}).get("buckets", [])
        ]
        return {
            "total": total,
            "page": page,
            "size": size,
            "items": items,
            "distritos": distritos,
            "origem": "elasticsearch",
        }
    except Exception as exc:
        logger.warning("Falha na pesquisa Elasticsearch: %s", exc)
        return _pesquisar_local(q=q, distrito=distrito, codigo_ine=codigo_ine, size=size, page=page)


def _pesquisar_local(
    q: Optional[str] = None,
    distrito: Optional[str] = None,
    codigo_ine: Optional[str] = None,
    size: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    docs = _docs_disponiveis()
    alvo = _fold(q) if q else ""
    d = _fold(distrito) if distrito else ""
    cod = re.sub(r"[^0-9]", "", codigo_ine or "")
    itens: List[Dict[str, Any]] = []
    for doc in docs:
        if cod and doc.get("codigo_ine") != cod:
            continue
        if d and d not in _fold(doc.get("distrito") or ""):
            continue
        if alvo:
            campos = " ".join([
                doc.get("municipio") or "",
                doc.get("nome_presidente") or "",
                doc.get("email") or "",
                doc.get("morada") or "",
                doc.get("localidade") or "",
                doc.get("distrito") or "",
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
        "distritos": [],
        "origem": "json-local",
    }


def ficha(codigo_ine: str) -> Dict[str, Any]:
    """Devolve a ficha completa de um município pelo código INE."""
    cod = re.sub(r"[^0-9]", "", codigo_ine).zfill(4)
    client = get_es_client()
    if client:
        ensure_indices(client)
        try:
            resp = client.get(index=MUNICIPIOS_CONTACTOS_INDEX, id=cod, ignore=404)
            if resp.get("found"):
                return {**resp["_source"], "doc_id": resp["_id"]}
        except Exception as exc:
            logger.warning("Falha a ler ficha do Elasticsearch: %s", exc)
    for doc in _docs_disponiveis():
        if doc.get("codigo_ine") == cod:
            return doc
    return {"error": f"Município com código INE «{codigo_ine}» não encontrado."}


def stats(es: Optional[Any] = None) -> Dict[str, Any]:
    """Resumo do índice de contactos municipais."""
    client = es or get_es_client()
    if not client:
        docs = _docs_disponiveis()
        distritos: Dict[str, int] = {}
        for d in docs:
            distritos[d["distrito"]] = distritos.get(d["distrito"], 0) + 1
        return {
            "index": MUNICIPIOS_CONTACTOS_INDEX,
            "documents": len(docs),
            "por_distrito": [{"key": k, "count": v} for k, v in sorted(distritos.items())],
            "origem": "json-local",
        }
    ensure_indices(client)
    try:
        count = client.count(index=MUNICIPIOS_CONTACTOS_INDEX).get("count", 0)
        resp = client.search(
            index=MUNICIPIOS_CONTACTOS_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "por_distrito": {"terms": {"field": "distrito.keyword", "size": 30}},
                },
            },
        )
        return {
            "index": MUNICIPIOS_CONTACTOS_INDEX,
            "documents": count,
            "por_distrito": [
                {"key": b["key"], "count": b["doc_count"]}
                for b in (resp.get("aggregations", {}).get("por_distrito", {}) or {}).get("buckets", [])
            ],
            "origem": "elasticsearch",
        }
    except Exception as exc:
        return {"error": str(exc)}
