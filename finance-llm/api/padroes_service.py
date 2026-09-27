"""Motor de deteção de padrões em contratos públicos, empresas e pessoas.

Esta camada responde a três perguntas sobre a contratação pública (PT e ES):

1. **O que é atípico?** — aprendizagem **não supervisionada** (sem rótulos de
   fraude) sobre o que se sabe de cada contrato: desvio entre preço base e
   adjudicado, desvio entre valor contratual e valor efetivo (aditivos),
   prazos entre publicação/decisão/celebração, ajuste direto, concorrência e
   valor. Usam-se `IsolationForest`, `LocalOutlierFactor` (LOF), `OneClassSVM`,
   `KMeans` (distância ao centro do grupo) e `DBSCAN` (cluster de ruído), mais
   um z-score robusto (MAD) **por CPV** — porque «normal» depende do setor.
2. **Quem se comporta fora do padrão?** — as mesmas medidas agregadas por
   **empresa adjudicatária** e por **CPV**, com LOF no espaço de features das
   entidades e concentração (parte do valor do mesmo adjudicante).
3. **Há laços entre pessoas, empresas e entidades?** — o grafo de relações
   (PessoasIQ + contratos + insolvências) mostra empresas que partilham
   gerentes, empresas que ganharam ao mesmo adjudicante e pessoas ligadas a
   mais do que uma empresa sinalizada.
4. **As notícias confirmam?** — menções das entidades sinalizadas no leitor RSS,
   na recolha (scraping) e nas redes sociais, com sentimento quando existe.

E ainda um modelo **supervisionado** (Gradient Boosting) que estima a
probabilidade de um contrato sofrer **aditivo financeiro** — o rótulo é
*derivado dos dados* (`PrecoTotalEfetivo > precoContratual`), não é um rótulo de
crime: serve para priorizar inspeção, não para acusar.

Todo o módulo é **defensivo**: sem Elasticsearch devolve `{"error": ...}`; sem
`scikit-learn` degrada para as regras robustas (z-score por CPV).
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from elasticsearch import Elasticsearch

from api.elasticsearch_client import (
    CIRE_INDEX,
    CONTRACTS_INDEX,
    CONTRATOS_ES_INDEX,
    PEOPLE_INDEX,
    SCRAPED_INDEX,
    SOCIAL_INDEX,
    get_es_client,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Catálogo de padrões (o que o motor sabe procurar)
# ---------------------------------------------------------------------------
#: Cada padrão tem um `id` estável (usado nos sinais), um rótulo legível, o
#: método que o deteta e as features que o alimentam.
PADROES: List[Dict[str, Any]] = [
    {
        "id": "desvio_preco_alto",
        "label": "Adjudicação acima do preço base",
        "tipo": "regra",
        "metodo": "z-score robusto (MAD) por CPV",
        "features": ["precoContratual / precoBaseProcedimento"],
        "descricao": "O valor adjudicado fica muito acima do preço base do procedimento.",
    },
    {
        "id": "desvio_preco_baixo",
        "label": "Adjudicação muito abaixo do preço base",
        "tipo": "regra",
        "metodo": "z-score robusto (MAD) por CPV",
        "features": ["precoContratual / precoBaseProcedimento"],
        "descricao": "Proposta anormalmente baixa — risco de incumprimento e de aditivos futuros.",
    },
    {
        "id": "aditivo_valor",
        "label": "Valor efetivo acima do contratual (aditivo)",
        "tipo": "regra",
        "metodo": "z-score robusto (MAD) por CPV",
        "features": ["PrecoTotalEfetivo / precoContratual"],
        "descricao": "O valor pago acabou acima do valor contratado — indicador clássico de desvio orçamental.",
    },
    {
        "id": "publicacao_tardia",
        "label": "Transparência tardia",
        "tipo": "regra",
        "metodo": "janela mínima na publicação",
        "features": ["dataPublicacao − dataCelebracaoContrato", "dataDecisaoAdjudicacao − dataPublicacao"],
        "descricao": "Contrato assinado muito antes de ser publicado (ou publicado antes de ser assinado) — esconde a contratação da concorrência.",
    },
    {
        "id": "assinatura_tardia",
        "label": "Assinatura tardia após a decisão",
        "tipo": "regra",
        "metodo": "janela mínima decisão→assinatura",
        "features": ["dataCelebracaoContrato − dataDecisaoAdjudicacao"],
        "descricao": "Mais de seis meses entre a decisão de adjudicação e a celebração do contrato — tempo para renegociar ou trocar de adjudicatário.",
    },
    {
        "id": "ajuste_direto_atipico",
        "label": "Ajuste direto atípico no CPV",
        "tipo": "regra",
        "metodo": "taxa do CPV vs taxa global",
        "features": ["tipoprocedimento", "CPV"],
        "descricao": "Ajuste direto num CPV onde o concurso público é a norma.",
    },
    {
        "id": "baixa_concorrencia",
        "label": "Baixa concorrência",
        "tipo": "regra",
        "metodo": "nº de concorrentes/ofertas",
        "features": ["concorrentes (NIFs listados)", "num_ofertas"],
        "descricao": "Um só concorrente (ou nenhum registado) em contrato de valor relevante.",
    },
    {
        "id": "valor_atipico",
        "label": "Valor atípico para o CPV",
        "tipo": "não supervisionado",
        "metodo": "Isolation Forest + LOF + KMeans + OneClass SVM + DBSCAN",
        "features": ["log(valor)", "desvio de preço", "prazos", "procedimento", "concorrência"],
        "descricao": "Contrato isolado rapidamente (IForest) ou em zona de densidade anómala (LOF/DBSCAN) face aos seus pares.",
    },
    {
        "id": "concentracao_fornecedor",
        "label": "Concentração no mesmo fornecedor",
        "tipo": "não supervisionado",
        "metodo": "LOF sobre features por entidade (parte do valor no mesmo adjudicante)",
        "features": ["nº de contratos", "níº de adjudicantes distintos", "parte do 1.º adjudicante"],
        "descricao": "Empresa que vende quase sempre ao mesmo adjudicante, muito acima do que é normal no seu setor.",
    },
    {
        "id": "rede_pessoas",
        "label": "Laço societário entre adjudicatárias",
        "tipo": "grafo",
        "metodo": "PessoasIQ (cargos) × contratos",
        "features": ["gerentes", "empresas", "adjudicantes"],
        "descricao": "Empresas que ganham ao mesmo adjudicante e partilham gerente, ou pessoa ligada a várias empresas sinalizadas.",
    },
    {
        "id": "insolvencia",
        "label": "Adjudicatária em insolvência / PER",
        "tipo": "regra",
        "metodo": "join por NIF com o CIRE",
        "features": ["finance_cire"],
        "descricao": "Empresa com processo de insolvência registado a continuar a receber contratos.",
    },
    {
        "id": "noticias_negativas",
        "label": "Menções em notícias",
        "tipo": "texto",
        "metodo": "pesquisa de menções + sentimento",
        "features": ["RSS", "recolha (scraping)", "redes sociais"],
        "descricao": "A entidade sinalizada aparece em notícias recentes, com sentimento negativo quando analisado.",
    },
    {
        "id": "risco_aditivo",
        "label": "Risco de aditivo (modelo supervisionado)",
        "tipo": "supervisionado",
        "metodo": "Gradient Boosting Classifier (scikit-learn)",
        "features": ["valor", "desvio de preço", "prazos", "procedimento", "CPV"],
        "descricao": "Probabilidade estimada de o contrato vir a ter valor efetivo acima do contratado, aprendida dos contratos do passado.",
    },
]

PADRAO_BY_ID = {item["id"]: item for item in PADROES}


# ---------------------------------------------------------------------------
# Adaptadores por país
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CountrySpec:
    """Como ler as mesmas features em cada portal (vocabulários diferentes).

    Nota sobre datas — os dois portais **publicam depois de decidir**, pelo que
    `decisão − publicação` é tipicamente **negativo** (a publicação do contrato
    acontece semanas depois da decisão). O que interessa medir:

    - PT: `assinatura − decisão` (demora a formalizar) e `publicação − assinatura`
      (transparência tardia);
    - ES: só `decisão − publicação` (o PLACSP não publica datas de assinatura
      nem o prazo de candidatura de forma fiável).
    """

    key: str
    label: str
    index: str
    year_field: str
    value_field: str
    base_field: str
    effective_field: Optional[str]
    pub_date: str
    award_date: str
    sign_date: Optional[str]
    procedure_field: str
    bidders_field: str
    #: `True` quando o campo de concorrentes é uma lista de NIFs em texto (PT).
    bidders_is_list: bool
    cpv_path: str
    cpv_code_field: str
    adjudicante_path: str
    adjudicatario_path: str
    adjudicante_nif: str
    adjudicante_nome: str
    adjudicatario_nif: str
    adjudicatario_nome: str
    direct_award_prefixes: Tuple[str, ...]
    #: Campos a pedir ao Elasticsearch (`_source`).
    source_fields: Tuple[str, ...]


PT = CountrySpec(
    key="PT",
    label="Portugal (Portal BASE)",
    index=CONTRACTS_INDEX,
    year_field="Ano",
    value_field="precoContratual",
    base_field="precoBaseProcedimento",
    effective_field="PrecoTotalEfetivo",
    pub_date="dataPublicacao",
    award_date="dataDecisaoAdjudicacao",
    sign_date="dataCelebracaoContrato",
    procedure_field="tipoprocedimento",
    bidders_field="concorrentes",
    bidders_is_list=True,
    cpv_path="cpv",
    cpv_code_field="cpv.code",
    adjudicante_path="adjudicantes.parsed",
    adjudicatario_path="adjudicatarios.parsed",
    adjudicante_nif="adjudicantes.parsed.nif",
    adjudicante_nome="adjudicantes.parsed.nome",
    adjudicatario_nif="adjudicatarios.parsed.nif",
    adjudicatario_nome="adjudicatarios.parsed.nome",
    direct_award_prefixes=("ajuste direto", "consulta previa", "contratacao excluida"),
    source_fields=(
        "idcontrato",
        "objectoContrato",
        "tipoprocedimento",
        "precoContratual",
        "precoBaseProcedimento",
        "PrecoTotalEfetivo",
        "prazoExecucao",
        "dataPublicacao",
        "dataDecisaoAdjudicacao",
        "dataCelebracaoContrato",
        "cpv",
        "adjudicantes",
        "adjudicatarios",
        "concorrentes",
        "NUTs",
        "Ano",
    ),
)

ES = CountrySpec(
    key="ES",
    label="Espanha (PLACSP)",
    index=CONTRATOS_ES_INDEX,
    year_field="ano",
    value_field="valor_adjudicado",
    base_field="valor_base",
    effective_field=None,
    pub_date="fecha_publicacion",
    award_date="fecha_adjudicacion",
    sign_date=None,
    procedure_field="procedimiento_label",
    bidders_field="num_ofertas",
    bidders_is_list=False,
    cpv_path="cpv",
    cpv_code_field="cpv.code",
    adjudicante_path="__flat__",
    adjudicatario_path="__flat__",
    adjudicante_nif="organo_id",
    adjudicante_nome="organo_nombre",
    adjudicatario_nif="adjudicatario_nif",
    adjudicatario_nome="adjudicatario_nombre",
    direct_award_prefixes=("contrato menor", "negociado sin publicidad", "normas internas"),
    source_fields=(
        "id_expediente",
        "objeto",
        "procedimiento_label",
        "valor_adjudicado",
        "valor_base",
        "valor_estimado",
        "num_ofertas",
        "fecha_publicacion",
        "fecha_adjudicacion",
        "fecha_actualizacion",
        "cpv",
        "organo_id",
        "organo_nombre",
        "adjudicatario_nif",
        "adjudicatario_nombre",
        "ano",
        "nuts",
    ),
)

COUNTRIES: Dict[str, CountrySpec] = {"PT": PT, "ES": ES}
PAIS_DEFAULT = "PT"

#: Número de contratos lidos por ano (amostra estratificada; o `_doc` evita
#: pontuar 2,25 M documentos — é uma leitura barata e reprodutível).
SAMPLE_PER_YEAR_DEFAULT = 1200
SAMPLE_TOTAL_CAP = 40000
CACHE_TTL_SECONDS = 900


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
def fold(value: Any) -> str:
    """Minúsculas sem acentos (para comparar vocabulários do portal)."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower().strip()


def as_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def as_int(value: Any) -> Optional[int]:
    """Inteiro pequeno a partir de um campo que pode ser texto livre.

    O campo «concorrentes» do Portal BASE é texto e pode conter descrições
    longas (números de processo); só se aceitam grupos de 1 a 3 dígitos, senão
    uma contagem absurda contaminaria a matriz de features.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        number = int(value)
        return number if 0 <= number <= 9999 else None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text) if len(text) <= 4 else None
    for chunk in re.findall(r"\d+", text):
        if len(chunk) <= 3:
            return int(chunk)
    return None


def as_date(value: Any) -> Optional[datetime]:
    """Data a partir de ISO/epoch, **rejeitando datas fora do razoável**.

    Os portais têm gralhas (ex.: um `IssueDate=0018-03-02` no PLACSP): uma data
    dessas produziria intervalos de centenas de milhares de dias e contaminaria
    todo o motor, pelo que se descarta tudo o que não caia em [1900, hoje+1].
    """
    parsed: Optional[datetime] = None
    if value is None or value == "":
        parsed = None
    elif isinstance(value, (int, float)) and value > 10_000_000:
        try:
            parsed = datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            parsed = None
    else:
        text = str(value).strip().replace("Z", "+00:00")
        for fmt in (None, "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%d/%m/%Y"):
            try:
                parsed = datetime.fromisoformat(text) if fmt is None else datetime.strptime(text[: len(fmt) + 2].strip(), fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if not (1900 <= parsed.year <= datetime.now().year + 1):
        return None
    return parsed


def num(value: Any) -> Optional[float]:
    """Número JSON-safe (NaN/inf → `None`)."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, 4)


def day_diff(later: Optional[datetime], earlier: Optional[datetime]) -> Optional[int]:
    if later is None or earlier is None:
        return None
    return int((later - earlier).total_seconds() // 86400)


def median(values: Sequence[float]) -> Optional[float]:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not clean:
        return None
    return float(np.median(clean))


def quantile(values: Sequence[float], q: float) -> Optional[float]:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not clean:
        return None
    return float(np.quantile(clean, q))


def _client(es: Optional[Elasticsearch] = None) -> Optional[Elasticsearch]:
    return es or get_es_client()


def _search(client: Elasticsearch, index: str, body: Dict[str, Any], timeout: int = 90) -> Dict[str, Any]:
    try:
        return client.search(index=index, body=body, request_timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Leitura de %s falhou: %s", index, str(exc)[:300])
        return {}


def _hits(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    return ((resp.get("hits") or {}).get("hits")) or []


# ---------------------------------------------------------------------------
# 1. Amostragem estratificada por ano
# ---------------------------------------------------------------------------
_CACHE: Dict[Tuple[Any, ...], Tuple[float, Dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()


def _cache_get(key: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
    if not entry:
        return None
    stamp, payload = entry
    if time.time() - stamp > CACHE_TTL_SECONDS:
        with _CACHE_LOCK:
            _CACHE.pop(key, None)
        return None
    return payload


def _cache_put(key: Tuple[Any, ...], payload: Dict[str, Any]) -> None:
    with _CACHE_LOCK:
        if len(_CACHE) > 24:
            _CACHE.clear()
        _CACHE[key] = (time.time(), payload)


def _cpv_filter(spec: CountrySpec, cpv: Optional[str]) -> Optional[Dict[str, Any]]:
    prefix = "".join(ch for ch in str(cpv or "") if ch.isdigit())
    if not prefix:
        return None
    return {
        "nested": {
            "path": spec.cpv_path,
            "query": {"prefix": {spec.cpv_code_field: prefix}},
        }
    }


def _base_query(spec: CountrySpec, ano_from: Optional[int], ano_to: Optional[int], cpv: Optional[str]) -> Dict[str, Any]:
    filters: List[Dict[str, Any]] = [{"exists": {"field": spec.value_field}}]
    if ano_from is not None or ano_to is not None:
        rng: Dict[str, Any] = {}
        if ano_from is not None:
            rng["gte"] = int(ano_from)
        if ano_to is not None:
            rng["lte"] = int(ano_to)
        filters.append({"range": {spec.year_field: rng}})
    cpv_filter = _cpv_filter(spec, cpv)
    if cpv_filter:
        filters.append(cpv_filter)
    return {"bool": {"filter": filters}}


def _years_in_index(client: Elasticsearch, spec: CountrySpec) -> List[int]:
    resp = _search(
        client,
        spec.index,
        {"size": 0, "aggs": {"anos": {"terms": {"field": spec.year_field, "size": 40}}}},
        timeout=60,
    )
    buckets = ((resp.get("aggregations") or {}).get("anos") or {}).get("buckets") or []
    years = sorted(int(b["key"]) for b in buckets if isinstance(b.get("key"), (int, float)))
    return [y for y in years if 1900 <= y <= datetime.now().year + 1]


def _sample(
    client: Elasticsearch,
    spec: CountrySpec,
    *,
    ano_from: Optional[int],
    ano_to: Optional[int],
    cpv: Optional[str],
    per_year: int,
    years: Optional[Sequence[int]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Lê contratos de forma estratificada por ano (barato e reprodutível)."""
    query = _base_query(spec, ano_from, ano_to, cpv)
    try:
        matching = int(client.count(index=spec.index, body={"query": query}).get("count") or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Contagem em %s falhou: %s", spec.index, exc)
        matching = 0

    span = list(years or [y for y in range(int(ano_from or 2015), int(ano_to or datetime.now().year) + 1)])
    rows: List[Dict[str, Any]] = []
    budget = max(1, min(per_year, SAMPLE_TOTAL_CAP))
    if not span:
        body = {
            "size": min(per_year, SAMPLE_TOTAL_CAP),
            "track_total_hits": False,
            "query": query,
            "sort": ["_doc"],
            "_source": list(spec.source_fields),
        }
        resp = _search(client, spec.index, body, timeout=120)
        rows.extend(_row_from_hit(spec, hit) for hit in _hits(resp))
    else:
        budget = max(1, min(per_year, SAMPLE_TOTAL_CAP // max(1, len(span))))
        for year in span:
            year_query = {"bool": {"filter": [query, {"term": {spec.year_field: int(year)}}]}}
            body = {
                "size": budget,
                "track_total_hits": False,
                "query": year_query,
                "sort": ["_doc"],
                "_source": list(spec.source_fields),
            }
            resp = _search(client, spec.index, body, timeout=120)
            for hit in _hits(resp):
                rows.append(_row_from_hit(spec, hit))
            if len(rows) >= SAMPLE_TOTAL_CAP:
                break

    coverage = {
        "documents_matching": matching,
        "documents_sampled": len(rows),
        "coverage": round(len(rows) / matching, 4) if matching else 0.0,
        "anos": [int(y) for y in span],
        "por_ano": budget if span else per_year,
    }
    return rows, coverage


def _row_from_hit(spec: CountrySpec, hit: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza um documento de contrato nas features comuns aos dois países."""
    src = hit.get("_source") or {}
    value = as_float(src.get(spec.value_field)) or None
    base = as_float(src.get(spec.base_field))
    effective = as_float(src.get(spec.effective_field)) if spec.effective_field else None
    procedure = str(src.get(spec.procedure_field) or "")

    pub = as_date(src.get(spec.pub_date))
    award = as_date(src.get(spec.award_date))
    sign = as_date(src.get(spec.sign_date)) if spec.sign_date else None
    adjudicantes = _parties(src, spec.adjudicante_path, spec.adjudicante_nif, spec.adjudicante_nome)
    adjudicatarios = _parties(src, spec.adjudicatario_path, spec.adjudicatario_nif, spec.adjudicatario_nome)
    cpvs = _cpvs(src, spec)
    concorrentes = _bidders(src, spec)

    # Intervalos relevantes (com proteção contra gralhas de datas).
    dias_decisao = day_diff(award, pub)
    if dias_decisao is not None and abs(dias_decisao) > 3650:
        dias_decisao = None
    dias_assinatura = day_diff(sign, award)
    if dias_assinatura is not None and not (-365 <= dias_assinatura <= 3650):
        dias_assinatura = None
    dias_publicacao = day_diff(pub, sign)
    if dias_publicacao is not None and not (-365 <= dias_publicacao <= 3650):
        dias_publicacao = None

    return {
        "id": str(hit.get("_id") or src.get("idcontrato") or src.get("id_expediente") or ""),
        "pais": spec.key,
        "ano": as_int(src.get(spec.year_field)),
        "objeto": str(src.get("objectoContrato") or src.get("objeto") or "")[:400],
        "valor": value,
        "base": base,
        "efetivo": effective,
        "ratio_base": (value / base) if (value and base and base > 0) else None,
        "ratio_efetivo": (effective / value) if (effective and value and value > 0) else None,
        "prazo_execucao": as_float(src.get("prazoExecucao")),
        "dias_decisao": dias_decisao,
        "dias_assinatura": dias_assinatura,
        "dias_publicacao": dias_publicacao,
        "data_publicacao": pub.date().isoformat() if pub else None,
        "procedimento": procedure,
        "ajuste_direto": int(any(fold(procedure).startswith(p) for p in spec.direct_award_prefixes)),
        "n_concorrentes": concorrentes,
        "cpv": cpvs[0]["code"] if cpvs else None,
        "cpv_grupo": (cpvs[0]["code"] or "")[:2] if cpvs else None,
        "cpv_desc": cpvs[0].get("label") if cpvs else None,
        "adjudicante_nif": adjudicantes[0]["nif"] if adjudicantes else None,
        "adjudicante_nome": adjudicantes[0]["nome"] if adjudicantes else None,
        "adjudicatarios": adjudicatarios,
        "n_adjudicantes": len(adjudicantes),
        "nut": (src.get("NUTs") or [None])[0] if isinstance(src.get("NUTs"), list) else src.get("nuts"),
    }


def _bidders(src: Dict[str, Any], spec: CountrySpec) -> Optional[int]:
    """Número de concorrentes/ofertas.

    Em Portugal o campo `concorrentes` é uma **lista de NIFs em texto**
    («504663909-Nome, 513503773-Nome, …»), pelo que se contam os NIFs distintos;
    em Espanha é o inteiro `num_ofertas`.
    """
    if not spec.bidders_is_list:
        return as_int(src.get(spec.bidders_field))
    text = str(src.get(spec.bidders_field) or "")
    if not text.strip():
        return None
    nifs = re.findall(r"(?<!\d)\d{8,9}(?!\d)", text)
    if nifs:
        return len(set(nifs))
    # Fallback: conta blocos separados por vírgula com algum conteúdo.
    parts = [part.strip() for part in text.split(",") if part.strip()]
    return len(parts) or None


def _parties(src: Dict[str, Any], path: str, nif_field: str, nome_field: str) -> List[Dict[str, str]]:
    """Extrai as partes (NIF + nome) de um contrato, plano (ES) ou nested (PT).

    No Portal BASE `adjudicantes`/`adjudicatarios` é um **objeto**
    `{"raw": [...], "parsed": [{nif, nome}]}` (não uma lista) — era esta a razão
    de a primeira versão não encontrar adjudicatários nenhuns.
    """
    if path == "__flat__":
        nif = str(src.get(nif_field) or "").strip()
        nome = str(src.get(nome_field) or "").strip()
        return [{"nif": nif, "nome": nome}] if (nif or nome) else []
    node = src.get(path.split(".")[0])
    entries: List[Any] = []
    if isinstance(node, dict):
        entries = [node]
    elif isinstance(node, list):
        entries = node
    out: List[Dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        parsed_list = entry.get("parsed")
        parsed_entries = parsed_list if isinstance(parsed_list, list) else ([parsed_list] if isinstance(parsed_list, dict) else [entry])
        for parsed in parsed_entries:
            if not isinstance(parsed, dict):
                continue
            nif = str(parsed.get("nif") or "").strip()
            nome = str(parsed.get("nome") or "").strip()
            if nif or nome:
                out.append({"nif": nif, "nome": nome})
    return out


def _cpvs(src: Dict[str, Any], spec: CountrySpec) -> List[Dict[str, str]]:
    node = src.get(spec.cpv_path) or []
    out: List[Dict[str, str]] = []
    for entry in node if isinstance(node, list) else []:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip()
        label = str(entry.get("description") or entry.get("nombre") or "").strip()
        if code:
            out.append({"code": code, "label": label})
    if not out and spec.key == "ES":
        code = str(src.get("cpv_code") or "").strip()
        if code:
            out.append({"code": code, "label": ""})
    return out


# ---------------------------------------------------------------------------
# 2. Features e deteção não supervisionada
# ---------------------------------------------------------------------------
FEATURE_NAMES = [
    "log_valor",
    "ratio_base",
    "ratio_efetivo",
    "dias_decisao",
    "dias_assinatura",
    "dias_publicacao",
    "log_prazo",
    "ajuste_direto",
    "n_concorrentes",
]


def _feature_matrix(rows: Sequence[Dict[str, Any]]) -> Tuple[np.ndarray, List[str], List[str]]:
    """Matriz de features (NaN onde não há dado) + nomes + CPVs de cada linha."""
    columns: List[List[float]] = [[] for _ in FEATURE_NAMES]
    cpvs: List[str] = []
    for row in rows:
        valor = row.get("valor")
        base_ratio = row.get("ratio_base")
        efetivo_ratio = row.get("ratio_efetivo")
        columns[0].append(math.log10(valor) if valor and valor > 0 else np.nan)
        columns[1].append(min(4.0, max(0.0, base_ratio)) if base_ratio is not None else np.nan)
        columns[2].append(min(4.0, max(0.0, efetivo_ratio)) if efetivo_ratio is not None else np.nan)
        columns[3].append(_clip(row.get("dias_decisao")))
        columns[4].append(_clip(row.get("dias_assinatura")))
        columns[5].append(_clip(row.get("dias_publicacao")))
        prazo = row.get("prazo_execucao")
        columns[6].append(math.log1p(prazo) if prazo and prazo > 0 else np.nan)
        columns[7].append(float(row.get("ajuste_direto") or 0))
        conc = row.get("n_concorrentes")
        columns[8].append(float(conc) if conc is not None else np.nan)
        cpvs.append(row.get("cpv_grupo") or "??")
    matrix = np.array(columns, dtype=float).T if columns else np.zeros((0, len(FEATURE_NAMES)))
    return matrix, list(FEATURE_NAMES), cpvs


def _clip(value: Any, limit: float = 720.0) -> float:
    """Intervalo de dias limitado e sem valores em falta → NaN."""
    if value is None:
        return float("nan")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float("nan")
    if not math.isfinite(number):
        return float("nan")
    return float(min(limit, max(-limit, number)))


def _impute(matrix: np.ndarray) -> np.ndarray:
    """Preenche NaN com a mediana da coluna (os detectores não aceitam NaN)."""
    if matrix.size == 0:
        return matrix
    filled = matrix.copy()
    for col in range(filled.shape[1]):
        column = filled[:, col]
        mask = ~np.isfinite(column)
        if mask.all():
            filled[:, col] = 0.0
            continue
        if mask.any():
            filled[mask, col] = float(np.median(column[~mask]))
    return filled


def _ranks(scores: np.ndarray) -> np.ndarray:
    """Converte qualquer score em percentil [0,1] (1 = mais anómalo).

    Valores não finitos (dado em falta) ficam a `0`: não se sinaliza o que não
    se mediu, para não confundir ausência de dado com anomalia.
    """
    if scores.size == 0:
        return scores
    out = np.zeros(scores.size, dtype=float)
    mask = np.isfinite(scores)
    if mask.sum() < 2:
        return out
    order = np.argsort(np.argsort(scores[mask]))
    out[mask] = order / max(1, int(mask.sum()) - 1)
    return out


def _robust_z(values: np.ndarray) -> np.ndarray:
    """z-score robusto (mediana/MAD); 0 onde não há dispersão."""
    if values.size == 0:
        return values
    finite = values[np.isfinite(values)]
    if finite.size < 4:
        return np.zeros_like(values)
    med = float(np.median(finite))
    mad = float(np.median(np.abs(finite - med)))
    if mad <= 1e-9:
        std = float(np.std(finite))
        if std <= 1e-9:
            return np.zeros_like(values)
        return (values - med) / std
    return (values - med) / (1.4826 * mad)


def _per_cpv_z(matrix: np.ndarray, cpvs: Sequence[str], min_group: int = 40) -> np.ndarray:
    """|z| máximo por linha, medido **dentro do grupo CPV** (o setor é a régua)."""
    out = np.zeros(matrix.shape[0], dtype=float)
    groups: Dict[str, List[int]] = {}
    for index, code in enumerate(cpvs):
        groups.setdefault(code, []).append(index)
    for indexes in groups.values():
        if len(indexes) < min_group:
            continue
        block = matrix[indexes, :]
        local = np.zeros(block.shape[0], dtype=float)
        for col in range(block.shape[1]):
            column = block[:, col]
            if not np.isfinite(column).any():
                continue
            z = np.abs(_robust_z(column))
            local = np.maximum(local, np.nan_to_num(z, nan=0.0))
        out[indexes] = local
    return out


def _sklearn():
    """Importa o scikit-learn uma só vez (mantém o arranque leve)."""
    try:
        from sklearn.cluster import DBSCAN, KMeans  # noqa: PLC0415
        from sklearn.ensemble import GradientBoostingClassifier, IsolationForest  # noqa: PLC0415
        from sklearn.metrics import average_precision_score, roc_auc_score  # noqa: PLC0415
        from sklearn.model_selection import train_test_split  # noqa: PLC0415
        from sklearn.neighbors import LocalOutlierFactor, NearestNeighbors  # noqa: PLC0415
        from sklearn.preprocessing import StandardScaler  # noqa: PLC0415
        from sklearn.svm import OneClassSVM  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        logger.warning("scikit-learn indisponível: %s", exc)
        return None
    return {
        "DBSCAN": DBSCAN,
        "KMeans": KMeans,
        "GradientBoostingClassifier": GradientBoostingClassifier,
        "IsolationForest": IsolationForest,
        "average_precision_score": average_precision_score,
        "roc_auc_score": roc_auc_score,
        "train_test_split": train_test_split,
        "LocalOutlierFactor": LocalOutlierFactor,
        "NearestNeighbors": NearestNeighbors,
        "StandardScaler": StandardScaler,
        "OneClassSVM": OneClassSVM,
    }


def _detect(matrix: np.ndarray, cpvs: Sequence[str], *, seed: int, contamination: float) -> Dict[str, Any]:
    """Corre os detectores e devolve scores normalizados por contrato."""
    n = matrix.shape[0]
    empty = {
        "scores": {},
        "consensus": np.zeros(n),
        "votes": np.zeros(n, dtype=int),
        "detectors": [],
        "z_per_cpv": np.zeros(n),
        "error": None,
    }
    if n == 0:
        return {**empty, "error": "sem amostra"}
    sk = _sklearn()
    if sk is None:
        z = _per_cpv_z(matrix, cpvs)
        consensus = _ranks(np.nan_to_num(z, nan=0.0))
        return {
            "scores": {},
            "consensus": consensus,
            "votes": (z > 3.5).astype(int),
            "detectors": ["z_cpv"],
            "z_per_cpv": z,
            "error": "scikit-learn indisponível: só regras robustas por CPV",
        }

    scaled = sk["StandardScaler"]().fit_transform(matrix)
    scores: Dict[str, np.ndarray] = {}
    detectors: List[str] = []

    contamination = max(0.005, min(0.2, float(contamination)))

    try:
        forest = sk["IsolationForest"](
            n_estimators=300, contamination=contamination, random_state=seed, n_jobs=-1
        ).fit(scaled)
        scores["isolation_forest"] = _ranks(-forest.score_samples(scaled))
        detectors.append("isolation_forest")
    except Exception as exc:  # noqa: BLE001
        logger.warning("IsolationForest falhou: %s", exc)

    try:
        neighbours = min(20, max(5, n // 20 or 5))
        lof = sk["LocalOutlierFactor"](n_neighbors=neighbours, contamination=contamination)
        lof.fit_predict(scaled)
        scores["lof"] = _ranks(-lof.negative_outlier_factor_)
        detectors.append("lof")
    except Exception as exc:  # noqa: BLE001
        logger.warning("LOF falhou: %s", exc)

    try:
        clusters = max(2, min(12, len(set(cpvs)) or 6))
        kmeans = sk["KMeans"](n_clusters=clusters, n_init=10, random_state=seed).fit(scaled)
        distances = np.min(kmeans.transform(scaled), axis=1)
        scores["cluster_distance"] = _ranks(distances)
        detectors.append("kmeans")
    except Exception as exc:  # noqa: BLE001
        logger.warning("KMeans falhou: %s", exc)

    try:
        if n <= 4000:
            svm_scores = sk["OneClassSVM"](nu=contamination, gamma="scale").fit(scaled).decision_function(scaled)
            scores["one_class_svm"] = _ranks(-svm_scores)
            detectors.append("one_class_svm")
        else:
            rng = np.random.default_rng(seed)
            subset = rng.choice(n, size=4000, replace=False)
            svm = sk["OneClassSVM"](nu=contamination, gamma="scale").fit(scaled[subset])
            partial = -svm.decision_function(scaled[subset])
            full = np.full(n, np.nan)
            full[subset] = partial
            scores["one_class_svm"] = _ranks(full)
            detectors.append("one_class_svm")
    except Exception as exc:  # noqa: BLE001
        logger.warning("OneClassSVM falhou: %s", exc)

    noise = np.zeros(n, dtype=int)
    try:
        # `eps` a partir da distância ao k-ésimo vizinho (heurística clássica),
        # medida numa sub-amostra para não construir uma matriz n×n gigante.
        k = min(10, max(4, n // 50 or 4))
        sample = scaled[: min(n, 3000)]
        neighbours_model = sk["NearestNeighbors"](n_neighbors=min(k + 1, len(sample))).fit(sample)
        distances = neighbours_model.kneighbors(sample, return_distance=True)[0][:, -1]
        eps = float(np.quantile(distances, 0.9))
        dbscan = sk["DBSCAN"](eps=max(eps, 0.5), min_samples=max(4, k)).fit(scaled)
        labels = dbscan.labels_
        noise = (labels == -1).astype(int)
        detectors.append("dbscan")
    except Exception as exc:  # noqa: BLE001
        logger.warning("DBSCAN falhou: %s", exc)

    z_cpv = _per_cpv_z(matrix, cpvs)

    continuous = [name for name in ("isolation_forest", "lof", "cluster_distance", "one_class_svm") if name in scores]
    if continuous:
        consensus = np.nanmean(np.vstack([scores[name] for name in continuous]), axis=0)
    else:
        consensus = np.zeros(n)
    consensus = np.nan_to_num(consensus, nan=0.0)

    votes = np.zeros(n, dtype=int)
    for name in continuous:
        column = scores[name]
        finite = column[np.isfinite(column)]
        if finite.size == 0:
            continue
        threshold = float(np.quantile(finite, 1.0 - contamination))
        votes += (np.nan_to_num(column, nan=-1.0) >= threshold).astype(int)
    votes += noise
    votes += (z_cpv > 3.5).astype(int)

    return {
        "scores": scores,
        "consensus": consensus,
        "votes": votes,
        "detectors": detectors,
        "z_per_cpv": z_cpv,
        "error": None,
    }


# ---------------------------------------------------------------------------
# 3. Regras interpretáveis (razões por contrato)
# ---------------------------------------------------------------------------
def _reasons(row: Dict[str, Any], *, z: float, cpv_rate_ad: Optional[float], global_rate_ad: Optional[float]) -> List[Dict[str, Any]]:
    """Lista de sinais legíveis que explicam porque o contrato foi sinalizado."""
    reasons: List[Dict[str, Any]] = []
    ratio_base = row.get("ratio_base")
    ratio_efetivo = row.get("ratio_efetivo")
    dias_assinatura = row.get("dias_assinatura")
    dias_publicacao = row.get("dias_publicacao")
    dias_decisao = row.get("dias_decisao")
    conc = row.get("n_concorrentes")
    valor = row.get("valor") or 0

    if ratio_base is not None and ratio_base > 1.2:
        reasons.append({"padrao": "desvio_preco_alto", "detalhe": f"adjudicado {ratio_base * 100 - 100:.0f}% acima do preço base"})
    if ratio_base is not None and 0 < ratio_base < 0.75:
        reasons.append({"padrao": "desvio_preco_baixo", "detalhe": f"adjudicado {100 - ratio_base * 100:.0f}% abaixo do preço base"})
    if ratio_efetivo is not None and ratio_efetivo > 1.15:
        reasons.append({"padrao": "aditivo_valor", "detalhe": f"valor efetivo {ratio_efetivo * 100 - 100:.0f}% acima do contratual"})
    if dias_publicacao is not None and dias_publicacao > 180:
        reasons.append({"padrao": "publicacao_tardia", "detalhe": f"contrato publicado {dias_publicacao} dias depois de ser assinado"})
    elif dias_publicacao is not None and dias_publicacao < 0:
        reasons.append({"padrao": "publicacao_tardia", "detalhe": f"publicado {abs(dias_publicacao)} dias antes de ser assinado"})
    if dias_assinatura is not None and dias_assinatura > 180:
        reasons.append({"padrao": "assinatura_tardia", "detalhe": f"assinado {dias_assinatura} dias depois da decisão de adjudicação"})
    if dias_decisao is not None and dias_decisao < -180:
        reasons.append({"padrao": "publicacao_tardia", "detalhe": f"decisão publicada {abs(dias_decisao)} dias depois"})
    if row.get("ajuste_direto") and cpv_rate_ad is not None and global_rate_ad is not None and cpv_rate_ad < global_rate_ad * 0.6:
        reasons.append(
            {
                "padrao": "ajuste_direto_atipico",
                "detalhe": f"ajuste direto num CPV onde só {cpv_rate_ad * 100:.0f}% dos contratos o usam",
            }
        )
    if conc is not None and conc <= 1 and valor >= 25000:
        reasons.append({"padrao": "baixa_concorrencia", "detalhe": f"{conc} concorrente(s) em contrato de {valor:,.0f} €"})
    elif conc is not None and conc == 0:
        reasons.append({"padrao": "baixa_concorrencia", "detalhe": "nenhum concorrente registado"})
    if z > 3.5:
        reasons.append({"padrao": "valor_atipico", "detalhe": f"{z:.1f}σ face à mediana do seu CPV"})
    return reasons


# ---------------------------------------------------------------------------
# 4. Tabelas agregadas
# ---------------------------------------------------------------------------
def _cpv_table(rows: Sequence[Dict[str, Any]], global_rate_ad: Optional[float]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row.get("cpv_grupo") or "??", []).append(row)
    out: List[Dict[str, Any]] = []
    for code, items in groups.items():
        valores = [r["valor"] for r in items if r.get("valor")]
        ratios = [r["ratio_base"] for r in items if r.get("ratio_base") is not None]
        aditivos = [r for r in items if (r.get("ratio_efetivo") or 0) > 1.15]
        dias = [r["dias_decisao"] for r in items if r.get("dias_decisao") is not None]
        rate_ad = sum(r.get("ajuste_direto") or 0 for r in items) / len(items) if items else None
        rate_aditivo = len(aditivos) / len(items) if items else None
        out.append(
            {
                "cpv": code,
                "descricao": next((r.get("cpv_desc") for r in items if r.get("cpv_desc")), None),
                "contratos": len(items),
                "valor_total": num(sum(valores)),
                "valor_mediano": num(median(valores)),
                "desvio_mediano": num(median(ratios)),
                "taxa_ajuste_direto": num(rate_ad),
                "taxa_aditivo": num(rate_aditivo),
                "dias_ate_decisao_mediano": num(median(dias)),
                "contratos_sinalizados": 0,
                "relevancia": None,
            }
        )
    # Relevância = combinação robusta do que foge à média nacional.
    for item in out:
        score = 0.0
        if item["taxa_ajuste_direto"] is not None and global_rate_ad is not None:
            score += max(0.0, item["taxa_ajuste_direto"] - global_rate_ad) * 3
        if item["taxa_aditivo"]:
            score += item["taxa_aditivo"] * 2
        if item["desvio_mediano"] is not None:
            score += max(0.0, item["desvio_mediano"] - 1.0) * 2
        item["relevancia"] = num(score)
    out.sort(key=lambda item: (-(item["relevancia"] or 0), -(item["valor_total"] or 0)))
    return out


def _entity_table(rows: Sequence[Dict[str, Any]], anomalies: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Nome preferido: o que aparece mais vezes nos contratos dessa entidade.
    nomes: Dict[str, Dict[str, int]] = {}
    groups: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    for index, row in enumerate(rows):
        for party in row.get("adjudicatarios") or []:
            nif = party.get("nif") or party.get("nome")
            if not nif:
                continue
            key = str(nif)
            groups.setdefault(key, []).append((index, row))
            nome = str(party.get("nome") or "").strip()
            if nome:
                nomes.setdefault(key, {})
                nomes[key][nome] = nomes[key].get(nome, 0) + 1

    out: List[Dict[str, Any]] = []
    for nif, items in groups.items():
        valores = [row["valor"] for _, row in items if row.get("valor")]
        adjudicantes: Dict[str, float] = {}
        for _, row in items:
            key = row.get("adjudicante_nif") or row.get("adjudicante_nome") or "?"
            adjudicantes[key] = adjudicantes.get(key, 0.0) + (row.get("valor") or 0.0)
        total = sum(adjudicantes.values()) or 0.0
        top_share = (max(adjudicantes.values()) / total) if total > 0 else None
        flagged = [index for index, _ in items if index in anomalies]
        variantes = nomes.get(nif) or {}
        out.append(
            {
                "nif": nif,
                "nome": max(variantes.items(), key=lambda kv: kv[1])[0] if variantes else None,
                "contratos": len(items),
                "valor_total": num(sum(valores)),
                "valor_mediano": num(median(valores)),
                "adjudicantes_distintos": len(adjudicantes),
                "parte_do_maior_adjudicante": num(top_share),
                "taxa_ajuste_direto": num(sum(row.get("ajuste_direto") or 0 for _, row in items) / len(items)),
                "desvio_mediano": num(median([row["ratio_base"] for _, row in items if row.get("ratio_base") is not None])),
                "contratos_sinalizados": len(flagged),
                "taxa_sinalizacao": num(len(flagged) / len(items)) if items else None,
                "anos": sorted({row.get("ano") for _, row in items if row.get("ano")}),
                "score": None,
                "motivos": [],
                "insolvente": False,
                "cpv_principal": _top_cpv(items),
            }
        )
    return out


def _top_cpv(items: Sequence[Tuple[int, Dict[str, Any]]]) -> Optional[str]:
    counts: Dict[str, int] = {}
    for _, row in items:
        code = row.get("cpv_grupo")
        if code:
            counts[code] = counts.get(code, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _score_entities(entities: List[Dict[str, Any]], *, seed: int) -> Dict[str, Any]:
    """LOF + z-score robusto no espaço de features das empresas adjudicatárias."""
    pool = [e for e in entities if (e.get("contratos") or 0) >= 3]
    if len(pool) < 20:
        for entity in entities:
            entity["score"] = 0.0
        return {"n": len(pool), "metricas": {}, "error": "amostra insuficiente para o LOF de entidades"}

    matrix = np.array(
        [
            [
                math.log10(max(1.0, e.get("contratos") or 1)),
                math.log10(max(1.0, e.get("valor_total") or 1.0)),
                e.get("taxa_ajuste_direto") or 0.0,
                e.get("parte_do_maior_adjudicante") or 0.0,
                e.get("desvio_mediano") or 1.0,
                math.log10(1 + (e.get("contratos_sinalizados") or 0)),
            ]
            for e in pool
        ],
        dtype=float,
    )
    sk = _sklearn()
    if sk is None:
        for entity in entities:
            entity["score"] = 0.0
        return {"n": len(pool), "metricas": {}, "error": "scikit-learn indisponível"}

    scaled = sk["StandardScaler"]().fit_transform(matrix)
    neighbours = min(15, max(5, len(pool) // 10))
    lof = sk["LocalOutlierFactor"](n_neighbors=neighbours, contamination=0.05).fit(scaled)
    outlier_scores = _ranks(-lof.negative_outlier_factor_)
    dispersion = np.zeros(len(pool))
    for col in range(scaled.shape[1]):
        dispersion = np.maximum(dispersion, np.abs(_robust_z(scaled[:, col])))
    dispersion_score = _ranks(dispersion)

    for position, entity in enumerate(pool):
        entity["score"] = num(0.6 * outlier_scores[position] + 0.4 * dispersion_score[position])
    for entity in entities:
        if entity.get("score") is None:
            entity["score"] = 0.0

    return {
        "n": len(pool),
        "metricas": {
            "features": [
                "log(nº contratos)",
                "log(valor)",
                "taxa ajuste direto",
                "parte do maior adjudicante",
                "desvio mediano",
                "log(1+contratos sinalizados)",
            ],
            "vizinhos": neighbours,
            "contaminacao": 0.05,
        },
    }


# ---------------------------------------------------------------------------
# 5. Relações (pessoas ↔ empresas ↔ entidades)
# ---------------------------------------------------------------------------
def _relations(
    client: Optional[Elasticsearch],
    rows: Sequence[Dict[str, Any]],
    entities: Sequence[Dict[str, Any]],
    *,
    top_entities: int = 120,
) -> Dict[str, Any]:
    """Grafo adjudicante→adjudicatário enriquecido com cargos (PessoasIQ) e CIRE."""
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def add_node(key: str, label: str, kind: str, count: int = 0, value: float = 0.0) -> None:
        node = nodes.get(key)
        if node is None:
            nodes[key] = {
                "id": key,
                "key": key.split(":", 1)[-1],
                "label": label or key,
                "dimension": kind,
                "type": kind,
                "count": count,
                "total_value": num(value),
            }
        else:
            node["count"] += count
            node["total_value"] = num((node.get("total_value") or 0) + value)

    for row in rows:
        valor = row.get("valor") or 0.0
        adjudicante = row.get("adjudicante_nif") or row.get("adjudicante_nome")
        if not adjudicante:
            continue
        a_key = f"entity:{adjudicante}"
        add_node(a_key, row.get("adjudicante_nome") or str(adjudicante), "entity", 1, valor)
        for party in row.get("adjudicatarios") or []:
            nif = party.get("nif") or party.get("nome")
            if not nif:
                continue
            c_key = f"company:{nif}"
            add_node(c_key, party.get("nome") or str(nif), "company", 1, valor)
            edge = edges.setdefault((a_key, c_key), {"source": a_key, "target": c_key, "count": 0, "value": 0.0})
            edge["count"] += 1
            edge["value"] += valor

    # -- cargos: pessoas ligadas às empresas mais relevantes -----------------
    laços: List[Dict[str, Any]] = []
    top = sorted(entities, key=lambda e: -(e.get("score") or 0))[:top_entities]
    top_nifs = [str(e["nif"]) for e in top if e.get("nif")][:top_entities]
    people_alerts: List[Dict[str, Any]] = []
    if client is not None and top_nifs:
        for chunk_start in range(0, len(top_nifs), 40):
            chunk = top_nifs[chunk_start : chunk_start + 40]
            body = {
                "size": 400,
                "track_total_hits": False,
                "_source": ["nif", "name", "roles", "companies"],
                "query": {
                    "nested": {
                        "path": "companies",
                        "query": {"terms": {"companies.nif": chunk}},
                    }
                },
            }
            resp = _search(client, PEOPLE_INDEX, body, timeout=60)
            for hit in _hits(resp):
                src = hit.get("_source") or {}
                person_nif = str(src.get("nif") or hit.get("_id") or "").strip()
                person_name = str(src.get("name") or "").strip()
                companies = src.get("companies") or []
                linked = [str((c or {}).get("nif") or "").strip() for c in companies if isinstance(c, dict)]
                linked = [c for c in linked if c in set(top_nifs)]
                if not person_nif or len(linked) < 2:
                    continue
                p_key = f"person:{person_nif}"
                add_node(p_key, person_name or person_nif, "person")
                for company_nif in linked:
                    c_key = f"company:{company_nif}"
                    node = nodes.get(c_key)
                    if node is None:
                        add_node(c_key, company_nif, "company")
                        node = nodes[c_key]
                    edge = edges.setdefault((p_key, c_key), {"source": p_key, "target": c_key, "count": 0, "value": 0.0})
                    edge["count"] += 1
                names = [nodes.get(f"company:{c}", {}).get("label") or c for c in linked]
                people_alerts.append(
                    {
                        "pessoa": person_name or person_nif,
                        "pessoa_nif": person_nif,
                        "empresas": names,
                        "empresas_nif": linked,
                        "tipo": "pessoa_ligada_a_varias_adjudicatarias",
                    }
                )

    # -- empresas que partilham pessoa e ganham ao mesmo adjudicante ---------
    # Índice `empresa → arestas de adjudicante` para não varrer todas as arestas
    # por cada pessoa (era quadrático e o grafo tem dezenas de milhares).
    by_company: Dict[str, List[Dict[str, Any]]] = {}
    for edge in edges.values():
        if edge["source"].startswith("entity:"):
            by_company.setdefault(edge["target"], []).append(edge)

    for alert in people_alerts:
        for company_nif in alert["empresas_nif"]:
            for edge in by_company.get(f"company:{company_nif}", []):
                laços.append(
                    {
                        "tipo": "conluio_potencial",
                        "detalhe": f"«{alert['pessoa']}» liga {len(alert['empresas'])} adjudicatárias; uma delas recebe de "
                        f"«{nodes.get(edge['source'], {}).get('label') or edge['source']}»",
                        "adjudicante": nodes.get(edge["source"], {}).get("label") or edge["source"],
                        "empresa": nodes.get(f"company:{company_nif}", {}).get("label") or company_nif,
                        "pessoa": alert["pessoa"],
                        "contratos": edge["count"],
                        "valor": num(edge["value"]),
                    }
                )
    # Deduplica laços (a leitura acima repete por cada empresa da pessoa).
    seen = set()
    unique_laços = []
    for laço in sorted(laços, key=lambda item: -(item.get("valor") or 0)):
        key = (laço["tipo"], laço["pessoa"], laço["adjudicante"], laço["empresa"])
        if key in seen:
            continue
        seen.add(key)
        unique_laços.append(laço)

    # -- concentração: empresas que dominam um adjudicante -------------------
    concentration: List[Dict[str, Any]] = []
    per_adjudicante: Dict[str, List[Dict[str, Any]]] = {}
    for edge in edges.values():
        if not edge["source"].startswith("entity:"):
            continue
        per_adjudicante.setdefault(edge["source"], []).append(edge)
    for source, list_of_edges in per_adjudicante.items():
        total = sum(edge["value"] for edge in list_of_edges) or 0.0
        count = sum(edge["count"] for edge in list_of_edges)
        if count < 10 or total <= 0:
            continue
        best = max(list_of_edges, key=lambda edge: edge["value"])
        share = best["value"] / total
        if share < 0.5:
            continue
        concentration.append(
            {
                "adjudicante": nodes.get(source, {}).get("label") or source,
                "empresa": nodes.get(best["target"], {}).get("label") or best["target"],
                "empresa_nif": best["target"].split(":", 1)[-1],
                "parte_do_valor": num(share),
                "contratos": best["count"],
                "valor": num(best["value"]),
                "contratos_do_adjudicante": count,
            }
        )
    concentration.sort(key=lambda item: -(item.get("parte_do_valor") or 0))

    # -- insolvências (join por NIF) -----------------------------------------
    insolventes: List[Dict[str, Any]] = []
    if client is not None and top_nifs:
        for chunk_start in range(0, len(top_nifs), 200):
            chunk = top_nifs[chunk_start : chunk_start + 200]
            body = {
                "size": 200,
                "track_total_hits": False,
                "_source": ["*"],
                "query": {"terms": {"nif": chunk}},
            }
            resp = _search(client, CIRE_INDEX, body, timeout=45)
            for hit in _hits(resp):
                src = hit.get("_source") or {}
                nif = str(src.get("nif") or "").strip()
                if not nif:
                    continue
                insolventes.append(
                    {
                        "nif": nif,
                        "nome": src.get("nome") or src.get("name") or src.get("company_name"),
                        "tipo": src.get("tipo") or src.get("kind"),
                        "data": src.get("data") or src.get("publication_date"),
                    }
                )
    insolvente_nifs = {item["nif"] for item in insolventes}
    for entity in entities:
        entity["insolvente"] = bool(entity.get("nif") and str(entity["nif"]) in insolvente_nifs)

    edge_list = [
        {"source": edge["source"], "target": edge["target"], "count": int(edge["count"]), "value": num(edge["value"]) or 0.0}
        for edge in edges.values()
    ]
    node_list = list(nodes.values())
    for node in node_list:
        node["total_value"] = num(node.get("total_value"))
    node_list.sort(key=lambda node: -(node.get("count") or 0))

    meta = {
        "dimension_a": "adjudicante",
        "dimension_b": "adjudicatário / pessoa",
        "metric": "valor",
        "mode": "relations",
        "complete": False,
        "scan_capped": True,
        "sample_order": "amostra estratificada por ano (sort _doc)",
        "sample_limit": len(rows),
        "documents_scanned": len(rows),
        "documents_matching": len(rows),
        "scanned_value": num(sum(row.get("valor") or 0.0 for row in rows)) or 0.0,
        "nodes_total": len(node_list),
        "edges_total": len(edge_list),
        "kept_nodes": len(node_list),
        "kept_edges": len(edge_list),
        "omitted_edges": 0,
        "coverage_value_share": None,
        "coverage_count_share": None,
        "directed": True,
        "limits": {"nodes": len(node_list), "edges": len(edge_list)},
        "notes": [
            "Grafo construído a partir da amostra analisada (não da totalidade do índice).",
            "As ligações pessoa→empresa vêm dos cargos publicados (PessoasIQ).",
        ],
        "filters": {},
    }

    return {
        "nodes": node_list,
        "edges": edge_list,
        "meta": meta,
        "lacos": unique_laços[:60],
        "concentracao": concentration[:40],
        "insolventes": insolventes[:60],
        "pessoas": people_alerts[:60],
    }


# ---------------------------------------------------------------------------
# 6. Notícias (menções)
# ---------------------------------------------------------------------------
def _news_for(client: Optional[Elasticsearch], names: Sequence[Tuple[str, str]], *, per_name: int = 5) -> List[Dict[str, Any]]:
    """Menções das entidades em RSS, recolha (scraping) e redes sociais."""
    out: List[Dict[str, Any]] = []
    for label, name in names:
        clean = str(name or "").strip()
        if len(clean) < 4:
            continue
        out.extend(_rss_mentions(label, clean, per_name))
        if client is None:
            continue
        out.extend(_es_mentions(client, SCRAPED_INDEX, label, clean, per_name, date_field="scraped_at", extra=["source_name"]))
        out.extend(_es_mentions(client, SOCIAL_INDEX, label, clean, per_name, date_field="published_at", extra=["platform", "channel_name"]))
    out.sort(key=lambda item: str(item.get("data") or ""), reverse=True)
    return out[:80]


def _rss_mentions(label: str, name: str, limit: int) -> List[Dict[str, Any]]:
    try:
        from api import rss_store  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return []
    try:
        result = rss_store.search(name, limit=limit) or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("Pesquisa RSS falhou: %s", exc)
        return []
    items = result.get("articles") or result.get("items") or []
    out: List[Dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        out.append(
            {
                "entidade": label,
                "entidade_nome": name,
                "fonte": item.get("feed_title") or item.get("source") or "RSS",
                "canal": "rss",
                "titulo": item.get("title"),
                "url": item.get("link") or item.get("url"),
                "data": item.get("published_at") or item.get("published"),
                "sentimento": item.get("sentiment"),
                "resumo": (item.get("summary") or "")[:280],
            }
        )
    return out


def _es_mentions(
    client: Elasticsearch,
    index: str,
    label: str,
    name: str,
    limit: int,
    *,
    date_field: str,
    extra: Sequence[str] = (),
) -> List[Dict[str, Any]]:
    body = {
        "size": max(1, min(limit, 20)),
        "track_total_hits": False,
        "query": {
            "query_string": {
                "query": f'"{name}"',
                "fields": ["title^3", "summary^2", "text", "data.*"],
                "lenient": True,
                "default_operator": "and",
            }
        },
        "_source": ["title", "summary", "text", "url", "sentiment", "sentiment_score", date_field, *extra],
        "sort": [{date_field: {"order": "desc", "unmapped_type": "date"}}],
    }
    resp = _search(client, index, body, timeout=30)
    out: List[Dict[str, Any]] = []
    for hit in _hits(resp):
        src = hit.get("_source") or {}
        out.append(
            {
                "entidade": label,
                "entidade_nome": name,
                "fonte": src.get("source_name") or src.get("channel_name") or src.get("platform") or index,
                "canal": "scraping" if index == SCRAPED_INDEX else "social",
                "titulo": src.get("title"),
                "url": src.get("url"),
                "data": src.get(date_field),
                "sentimento": src.get("sentiment"),
                "sentimento_score": num(src.get("sentiment_score")),
                "resumo": (src.get("summary") or src.get("text") or "")[:280],
            }
        )
    return out


# ---------------------------------------------------------------------------
# 7. Modelo supervisionado (risco de aditivo)
# ---------------------------------------------------------------------------
def _risk_model(rows: Sequence[Dict[str, Any]], matrix: np.ndarray, *, seed: int, feature_names: Sequence[str]) -> Dict[str, Any]:
    """Gradient Boosting com rótulo derivado: houve aditivo financeiro?"""
    labels: List[int] = []
    indexes: List[int] = []
    for index, row in enumerate(rows):
        ratio = row.get("ratio_efetivo")
        if ratio is None:
            continue
        labels.append(1 if ratio > 1.15 else 0)
        indexes.append(index)
    if len(indexes) < 400:
        return {"disponivel": False, "motivo": "amostra insuficiente com valor efetivo (aditivos)."}
    positives = sum(labels)
    if positives < 25 or positives > len(labels) - 25:
        return {
            "disponivel": False,
            "motivo": f"rótulo desequilibrado demais ({positives} aditivos em {len(labels)} contratos).",
        }

    sk = _sklearn()
    if sk is None:
        return {"disponivel": False, "motivo": "scikit-learn indisponível."}

    X = matrix[indexes]
    y = np.array(labels)
    names = list(feature_names) + ["cpv_frequencia"]
    cpv_freq: Dict[str, float] = {}
    for row in rows:
        if row.get("cpv_grupo"):
            cpv_freq[row["cpv_grupo"]] = cpv_freq.get(row["cpv_grupo"], 0.0) + 1.0
    total_cpv = sum(cpv_freq.values()) or 1.0
    extra = np.array(
        [[cpv_freq.get(rows[index].get("cpv_grupo") or "", 0.0) / total_cpv] for index in indexes], dtype=float
    )
    X = np.hstack([X, extra])

    try:
        X_train, X_test, y_train, y_test = sk["train_test_split"](
            X, y, test_size=0.3, random_state=seed, stratify=y
        )
        model = sk["GradientBoostingClassifier"](
            n_estimators=250, max_depth=3, learning_rate=0.08, subsample=0.9, random_state=seed
        ).fit(X_train, y_train)
        probabilities = model.predict_proba(X_test)[:, 1]
        auc = float(sk["roc_auc_score"](y_test, probabilities))
        ap = float(sk["average_precision_score"](y_test, probabilities))
        order = np.argsort(-probabilities)
        top_decile = max(1, len(order) // 10)
        lift = float(np.mean(y_test[order[:top_decile]])) / max(1e-9, float(np.mean(y_test)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Modelo de risco falhou: %s", exc)
        return {"disponivel": False, "motivo": f"treino falhou: {exc}"}

    full_probabilities = model.predict_proba(X)[:, 1]
    top_contracts = []
    for position in np.argsort(-full_probabilities)[:40]:
        row = rows[indexes[int(position)]]
        top_contracts.append(
            {
                "id": row.get("id"),
                "objeto": row.get("objeto"),
                "adjudicatario": next((p.get("nome") for p in row.get("adjudicatarios") or []), None),
                "adjudicatario_nif": next((p.get("nif") for p in row.get("adjudicatarios") or []), None),
                "adjudicante": row.get("adjudicante_nome"),
                "ano": row.get("ano"),
                "cpv": row.get("cpv"),
                "valor": num(row.get("valor")),
                "probabilidade": num(full_probabilities[int(position)]),
                "teve_aditivo": bool((row.get("ratio_efetivo") or 0) > 1.15),
            }
        )

    importances = [
        {"feature": names[position], "importancia": num(score)}
        for position, score in enumerate(model.feature_importances_)
    ]
    importances.sort(key=lambda item: -(item["importancia"] or 0))

    return {
        "disponivel": True,
        "rotulo": "valor efetivo > 115% do valor contratual (aditivo registado no portal)",
        "aviso": "Rótulo derivado dos dados do portal (aditivo), não é um rótulo de crime.",
        "contratos": int(len(y)),
        "positivos": int(positives),
        "prevalencia": num(float(np.mean(y))),
        "auc": num(auc),
        "average_precision": num(ap),
        "lift_top_decile": num(lift),
        "importancias": importances,
        "top_contratos": top_contracts,
        "validacao": "30% de teste, estratificado",
    }


# ---------------------------------------------------------------------------
# 8. Análise completa + cache
# ---------------------------------------------------------------------------
def analyze(
    *,
    pais: str = PAIS_DEFAULT,
    ano_from: Optional[int] = None,
    ano_to: Optional[int] = None,
    cpv: Optional[str] = None,
    per_year: int = SAMPLE_PER_YEAR_DEFAULT,
    contamination: float = 0.02,
    seed: int = 42,
    es: Optional[Elasticsearch] = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """Corre a análise inteira e devolve um payload pronto a servir por rota."""
    spec = COUNTRIES.get(str(pais or "").upper())
    if spec is None:
        return {"error": f"país desconhecido: {pais}", "paises": list(COUNTRIES)}

    key = (spec.key, ano_from, ano_to, str(cpv or ""), int(per_year), float(contamination), int(seed))
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    client = _client(es)
    if client is None:
        return {"error": "Elasticsearch indisponível"}

    started = time.time()
    years = _years_in_index(client, spec)
    if ano_from is None and years:
        ano_from = years[0]
    if ano_to is None:
        ano_to = years[-1] if years else datetime.now().year
    if ano_from and ano_to and ano_from > ano_to:
        ano_from, ano_to = ano_to, ano_from

    rows, coverage = _sample(
        client,
        spec,
        ano_from=ano_from,
        ano_to=ano_to,
        cpv=cpv,
        per_year=per_year,
        years=[y for y in years if ano_from <= y <= ano_to] or None,
    )
    if not rows:
        return {
            "error": "sem contratos para os filtros pedidos",
            "pais": spec.key,
            "filtros": {"ano_from": ano_from, "ano_to": ano_to, "cpv": cpv},
        }

    matrix, feature_names, cpvs = _feature_matrix(rows)
    # Só entram no motor as features com dado suficiente (o PLACSP não publica
    # data de assinatura nem valor efetivo, pelo que essas colunas ficariam
    # constantes e só acrescentariam ruído).
    minimum = max(20, int(0.3 * matrix.shape[0]))
    keep = [i for i in range(len(feature_names)) if int(np.isfinite(matrix[:, i]).sum()) >= minimum]
    dropped = [name for i, name in enumerate(feature_names) if i not in keep]
    if not keep:
        keep = [0]
        dropped = feature_names[1:]
    used_features = [feature_names[i] for i in keep]
    matrix = matrix[:, keep]

    imputed = _impute(matrix)
    detection = _detect(imputed, cpvs, seed=seed, contamination=contamination)
    consensus = detection["consensus"]
    votes = detection["votes"]
    z_cpv = detection["z_per_cpv"]

    global_rate_ad = sum(row.get("ajuste_direto") or 0 for row in rows) / len(rows)
    cpv_table = _cpv_table(rows, global_rate_ad)
    cpv_rate_ad = {item["cpv"]: item["taxa_ajuste_direto"] for item in cpv_table}

    # Contratos sinalizados: consenso alto **e** pelo menos dois detectores de acordo.
    threshold = float(np.quantile(consensus, 0.9)) if consensus.size else 1.0
    anomalies: Dict[int, Dict[str, Any]] = {}
    anomaly_list: List[Dict[str, Any]] = []
    for index, row in enumerate(rows):
        score = float(consensus[index])
        if votes[index] < 2 or score < max(threshold, 0.6):
            continue
        reasons = _reasons(
            row,
            z=float(z_cpv[index]),
            cpv_rate_ad=cpv_rate_ad.get(row.get("cpv_grupo") or ""),
            global_rate_ad=global_rate_ad,
        )
        entry = {
            "id": row.get("id"),
            "pais": row.get("pais"),
            "ano": row.get("ano"),
            "objeto": row.get("objeto"),
            "cpv": row.get("cpv"),
            "cpv_grupo": row.get("cpv_grupo"),
            "cpv_desc": row.get("cpv_desc"),
            "valor": num(row.get("valor")),
            "preco_base": num(row.get("base")),
            "valor_efetivo": num(row.get("efetivo")),
            "ratio_base": num(row.get("ratio_base")),
            "ratio_efetivo": num(row.get("ratio_efetivo")),
            "procedimento": row.get("procedimento"),
            "ajuste_direto": bool(row.get("ajuste_direto")),
            "n_concorrentes": row.get("n_concorrentes"),
            "dias_decisao": row.get("dias_decisao"),
            "dias_assinatura": row.get("dias_assinatura"),
            "dias_publicacao": row.get("dias_publicacao"),
            "adjudicante": row.get("adjudicante_nome"),
            "adjudicante_nif": row.get("adjudicante_nif"),
            "adjudicatarios": row.get("adjudicatarios"),
            "score": num(score),
            "z_cpv": num(float(z_cpv[index])),
            "votos": int(votes[index]),
            "detetores": [
                name
                for name, column in detection["scores"].items()
                if np.isfinite(column[index]) and column[index] >= 0.85
            ],
            "razoes": reasons,
        }
        anomalies[index] = entry
        anomaly_list.append(entry)
    anomaly_list.sort(key=lambda item: -(item.get("score") or 0))

    for item in cpv_table:
        item["contratos_sinalizados"] = sum(
            1 for entry in anomaly_list if entry.get("cpv_grupo") == item["cpv"]
        )

    entities = _entity_table(rows, anomalies)
    entity_model = _score_entities(entities, seed=seed)
    for entity in entities:
        if (entity.get("score") or 0) > 0.85:
            entity["motivos"].append("fora do padrão face às suas pares (LOF)")
        if (entity.get("parte_do_maior_adjudicante") or 0) > 0.8 and (entity.get("adjudicantes_distintos") or 0) <= 3:
            entity["motivos"].append("quase todo o valor vem de poucos adjudicantes")
            entity["padrao"] = "concentracao_fornecedor"
        if (entity.get("taxa_sinalizacao") or 0) > 0.25:
            entity["motivos"].append("mais de um quarto dos contratos sinalizados")
    entities.sort(key=lambda item: (-(item.get("score") or 0), -(item.get("valor_total") or 0)))

    relations = _relations(client, rows, entities)

    risk = _risk_model(rows, imputed, seed=seed, feature_names=used_features)

    valores = [row["valor"] for row in rows if row.get("valor")]
    aditivos = [row for row in rows if (row.get("ratio_efetivo") or 0) > 1.15]
    overview = {
        "pais": spec.key,
        "pais_label": spec.label,
        "indice": spec.index,
        "contratos_analisados": len(rows),
        "valor_analisado": num(sum(valores)),
        "valor_mediano": num(median(valores)),
        "anos": [min(r["ano"] for r in rows if r.get("ano")), max(r["ano"] for r in rows if r.get("ano"))]
        if any(r.get("ano") for r in rows)
        else None,
        "taxa_ajuste_direto": num(global_rate_ad),
        "desvio_mediano": num(median([row["ratio_base"] for row in rows if row.get("ratio_base") is not None])),
        "contratos_com_aditivo": len(aditivos),
        "taxa_aditivo": num(len(aditivos) / len(rows)),
        "dias_ate_decisao_mediano": num(median([row["dias_decisao"] for row in rows if row.get("dias_decisao") is not None])),
        "contratos_sinalizados": len(anomaly_list),
        "taxa_sinalizacao": num(len(anomaly_list) / len(rows)),
        "entidades": len(entities),
        "entidades_sinalizadas": sum(1 for entity in entities if (entity.get("score") or 0) > 0.85),
        "cpvs": len({row.get("cpv_grupo") for row in rows if row.get("cpv_grupo")}),
        "cobertura": coverage,
    }

    payload = {
        "pais": spec.key,
        "pais_label": spec.label,
        "paises": {key: value.label for key, value in COUNTRIES.items()},
        "filtros": {"ano_from": ano_from, "ano_to": ano_to, "cpv": cpv, "per_year": per_year},
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "duracao_s": num(time.time() - started),
        "overview": overview,
        "cpvs": cpv_table,
        "anomalias": anomaly_list[:400],
        "entidades": entities[:300],
        "relacoes": relations,
        "risco_aditivo": risk,
        "deteccao": {
            "algoritmos": detection["detectors"],
            "contaminacao": contamination,
            "semente": seed,
            "limiar_consenso": num(threshold),
            "aviso": detection["error"],
            "features": used_features,
            "features_excluidas": dropped,
            "nota": "Os scores são percentis [0,1]: 1 é o contrato mais atípico da amostra.",
        },
        "padroes": PADROES,
        "modelo_entidades": entity_model,
        "parametros": {"sample_per_year": SAMPLE_PER_YEAR_DEFAULT, "cache_ttl_s": CACHE_TTL_SECONDS},
    }
    if use_cache:
        _cache_put(key, payload)
    return payload


def meta() -> Dict[str, Any]:
    """Catálogo do módulo: padrões, algoritmos, fontes e parâmetros."""
    client = _client()
    fontes = []
    for key, spec in COUNTRIES.items():
        total = None
        anos: List[int] = []
        if client is not None:
            try:
                total = int(client.count(index=spec.index).get("count") or 0)
                anos = _years_in_index(client, spec)
            except Exception:  # noqa: BLE001
                total = None
        fontes.append(
            {
                "pais": key,
                "label": spec.label,
                "indice": spec.index,
                "documentos": total,
                "anos": [anos[0], anos[-1]] if anos else None,
            }
        )
    return {
        "padroes": PADROES,
        "algoritmos": {
            "nao_supervisionado": [
                {"id": "isolation_forest", "label": "Isolation Forest", "uso": "isola contratos atípicos em árvores de decisão"},
                {"id": "lof", "label": "Local Outlier Factor", "uso": "densidade local face aos vizinhos do mesmo setor"},
                {"id": "kmeans", "label": "K-Means (distância ao centro)", "uso": "contratos longe do centro do seu grupo"},
                {"id": "dbscan", "label": "DBSCAN", "uso": "cluster de ruído (contratos isolados)"},
                {"id": "one_class_svm", "label": "One-Class SVM", "uso": "fronteira do comportamento normal"},
                {"id": "z_cpv", "label": "z-score robusto (MAD) por CPV", "uso": "desvio face à mediana do próprio CPV"},
            ],
            "supervisionado": [
                {"id": "gradient_boosting", "label": "Gradient Boosting", "uso": "probabilidade de aditivo (rótulo derivado do portal)"}
            ],
            "grafo": [{"id": "cargos", "label": "PessoasIQ × contratos", "uso": "laços entre adjudicatárias e gerentes"}],
            "texto": [{"id": "mencoes", "label": "RSS + recolha + redes sociais", "uso": "menções e sentimento"}],
        },
        "fontes": fontes,
        "indices": {"contratos": CONTRACTS_INDEX, "contratos_es": CONTRATOS_ES_INDEX, "pessoas": PEOPLE_INDEX, "cire": CIRE_INDEX, "scraping": SCRAPED_INDEX, "social": SOCIAL_INDEX},
        "params": {
            "sample_per_year": SAMPLE_PER_YEAR_DEFAULT,
            "contaminacao": 0.02,
            "cache_ttl_s": CACHE_TTL_SECONDS,
        },
        "aviso": (
            "Os padrões são sinais estatísticos para priorizar inspeção. Não são prova de ilícito: "
            "um desvio pode ter justificação legal (ex.: ajuste direto por urgência imperiosa)."
        ),
    }


def entity_dossier(nif: str, *, pais: str = PAIS_DEFAULT, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Ficha de uma entidade: contratos, sinais, relações e notícias."""
    spec = COUNTRIES.get(str(pais or "").upper(), PT)
    client = _client(es)
    if client is None:
        return {"error": "Elasticsearch indisponível"}
    nif = str(nif or "").strip()
    if not nif:
        return {"error": "NIF em falta"}

    contracts: List[Dict[str, Any]] = []
    if spec.key == "PT":
        query: Dict[str, Any] = {
            "nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": nif}}}
        }
    else:
        query = {"term": {"adjudicatario_nif": nif}}
    body = {
        "size": 60,
        "track_total_hits": True,
        "query": query,
        "sort": [{spec.pub_date: {"order": "desc", "unmapped_type": "date"}}],
        "_source": list(spec.source_fields),
    }
    resp = _search(client, spec.index, body, timeout=60)
    total = (resp.get("hits") or {}).get("total") or {}
    for hit in _hits(resp):
        row = _row_from_hit(spec, hit)
        contracts.append(
            {
                "id": row["id"],
                "ano": row["ano"],
                "objeto": row["objeto"],
                "valor": num(row["valor"]),
                "preco_base": num(row["base"]),
                "ratio_base": num(row["ratio_base"]),
                "ratio_efetivo": num(row["ratio_efetivo"]),
                "procedimento": row["procedimento"],
                "ajuste_direto": bool(row["ajuste_direto"]),
                "cpv": row["cpv"],
                "adjudicante": row["adjudicante_nome"],
                "adjudicante_nif": row["adjudicante_nif"],
                "dias_decisao": row["dias_decisao"],
                "dias_assinatura": row["dias_assinatura"],
                "dias_publicacao": row["dias_publicacao"],
            }
        )

    people: List[Dict[str, Any]] = []
    body_people = {
        "size": 40,
        "track_total_hits": False,
        "_source": ["nif", "name", "roles", "companies"],
        "query": {"nested": {"path": "companies", "query": {"term": {"companies.nif": nif}}}},
    }
    for hit in _hits(_search(client, PEOPLE_INDEX, body_people, timeout=45)):
        src = hit.get("_source") or {}
        roles = [
            {"role": role.get("role"), "acto": role.get("acto"), "data": role.get("date")}
            for role in (src.get("roles") or [])
            if isinstance(role, dict)
        ][:8]
        people.append({"nif": src.get("nif"), "nome": src.get("name"), "cargos": roles})

    cire: List[Dict[str, Any]] = []
    for hit in _hits(_search(client, CIRE_INDEX, {"size": 20, "query": {"term": {"nif": nif}}, "_source": ["*"]}, timeout=45)):
        src = hit.get("_source") or {}
        cire.append({"tipo": src.get("tipo") or src.get("kind"), "data": src.get("data"), "tribunal": src.get("tribunal")})

    name = None
    label = nif
    # Nome a partir da amostra nacional (barato: uma pesquisa por termo).
    name_body = {
        "size": 1,
        "track_total_hits": False,
        "_source": [spec.adjudicatario_nome if spec.key == "ES" else "adjudicatarios"],
        "query": query,
    }
    for hit in _hits(_search(client, spec.index, name_body, timeout=30)):
        src = hit.get("_source") or {}
        if spec.key == "ES":
            label = src.get("adjudicatario_nombre") or nif
        else:
            parties = _parties(src, spec.adjudicatario_path, spec.adjudicatario_nif, spec.adjudicatario_nome)
            match = next((p for p in parties if p["nif"] == nif), None)
            label = (match or {}).get("nome") or nif
        break

    sinais: List[Dict[str, Any]] = []
    valores = [c["valor"] for c in contracts if c.get("valor")]
    ratios = [c["ratio_base"] for c in contracts if c.get("ratio_base") is not None]
    efetivos = [c for c in contracts if (c.get("ratio_efetivo") or 0) > 1.15]
    adjudicantes: Dict[str, float] = {}
    for contract in contracts:
        key = contract.get("adjudicante_nif") or contract.get("adjudicante") or "?"
        adjudicantes[key] = adjudicantes.get(key, 0.0) + (contract.get("valor") or 0.0)
    total_valor = sum(adjudicantes.values()) or 0
    taxa_ad = sum(1 for c in contracts if c.get("ajuste_direto")) / len(contracts) if contracts else 0
    mediana = median(ratios)

    if mediana is not None and mediana > 1.1:
        sinais.append({"padrao": "desvio_preco_alto", "detalhe": f"mediana adjudicado/base de {mediana:.2f}"})
    if efetivos:
        sinais.append({"padrao": "aditivo_valor", "detalhe": f"{len(efetivos)} de {len(contracts)} contratos com valor efetivo acima do contratual"})
    if taxa_ad > 0.6 and len(contracts) >= 5:
        sinais.append({"padrao": "ajuste_direto_atipico", "detalhe": f"{taxa_ad * 100:.0f}% dos contratos por ajuste direto"})
    if total_valor > 0 and len(adjudicantes) <= 3 and len(contracts) >= 5:
        sinais.append(
            {
                "padrao": "concentracao_fornecedor",
                "detalhe": f"{max(adjudicantes.values()) / total_valor * 100:.0f}% do valor vem de "
                f"{max(adjudicantes, key=adjudicantes.get)}",
            }
        )
    if cire:
        sinais.append({"padrao": "insolvencia", "detalhe": f"{len(cire)} processo(s) no CIRE"})
    if people and len(people) > 0:
        sinais.append({"padrao": "rede_pessoas", "detalhe": f"{len(people)} pessoa(s) com cargo registado nesta empresa"})

    noticias = _news_for(client, [(label, label)], per_name=6)

    return {
        "nif": nif,
        "nome": label,
        "pais": spec.key,
        "contratos_total": int(total.get("value") or len(contracts)),
        "contratos": contracts,
        "resumo": {
            "valor_total": num(sum(valores)),
            "valor_mediano": num(median(valores)),
            "desvio_mediano": num(mediana),
            "taxa_ajuste_direto": num(taxa_ad),
            "adjudicantes_distintos": len(adjudicantes),
            "taxa_aditivo": num(len(efetivos) / len(contracts)) if contracts else None,
            "anos": sorted({c["ano"] for c in contracts if c.get("ano")}),
        },
        "sinais": sinais,
        "pessoas": people,
        "insolvencias": cire,
        "noticias": noticias,
    }
