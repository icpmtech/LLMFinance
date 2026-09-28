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
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from elasticsearch import Elasticsearch

from api.elasticsearch_client import (
    CIRE_INDEX,
    CONTRACTS_INDEX,
    CONTRATOS_ES_INDEX,
    CONTRIBUINTES_INDEX,
    PEOPLE_INDEX,
    SCRAPED_INDEX,
    SOCIAL_INDEX,
    get_es_client,
)
from api import padroes_regras as regras

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
        "metodo": "PessoasIQ (órgãos sociais) × contratos",
        "features": ["gerentes", "empresas", "adjudicantes"],
        "descricao": "Empresas que ganham ao mesmo adjudicante e partilham um gerente, ou pessoa com cargos em várias adjudicatárias (só órgãos sociais, não papéis processuais do CIRE).",
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


def catalogo_padroes() -> List[Dict[str, Any]]:
    """Catálogo efetivo: as **regras** guardadas + os padrões não avaliáveis.

    As regras vêm do registo (`padroes_regras`) e são editáveis; os padrões que
    dependem de modelos, do grafo ou das notícias não se expressam por condição
    e ficam como documentação (`editavel: false`).
    """
    try:
        resumo = regras.resumo_regras(regras.listar()["regras"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Regras indisponíveis (%s); a usar o catálogo estático.", exc)
        return list(PADROES)
    saida: List[Dict[str, Any]] = []
    for item in resumo:
        saida.append(
            {
                "id": item["id"],
                "label": item["label"],
                "tipo": "regra",
                "metodo": item["condicao"] or "condição definida pelo utilizador",
                "features": [condicao.get("campo") for condicao in item.get("condicoes") or []],
                "descricao": item.get("descricao") or "",
                "ativo": item["ativo"],
                "severidade": item["severidade"],
                "origem": item.get("origem"),
                "editavel": True,
            }
        )
    for item in regras.PADROES_NAO_AVALIAVEIS:
        saida.append({**item, "ativo": True, "severidade": None, "editavel": False})
    return saida


# ---------------------------------------------------------------------------
# Contexto de um contrato para as regras
# ---------------------------------------------------------------------------
def _contexto_regras(
    row: Dict[str, Any],
    *,
    z: float = 0.0,
    taxa_ajuste_direto_cpv: Optional[float] = None,
    taxa_aditivo_cpv: Optional[float] = None,
    taxa_ajuste_direto_global: Optional[float] = None,
    contratos_do_cpv: Optional[int] = None,
) -> Dict[str, Any]:
    """Campos derivados de um contrato que uma regra pode testar."""
    adjudicataria = next(
        (
            party.get("nome") or party.get("nif")
            for party in (row.get("adjudicatarios") or [])
            if isinstance(party, dict)
        ),
        None,
    )
    return {
        "valor": row.get("valor"),
        "preco_base": row.get("base"),
        "ratio_base": row.get("ratio_base"),
        "ratio_efetivo": row.get("ratio_efetivo"),
        "dias_decisao": row.get("dias_decisao"),
        "dias_assinatura": row.get("dias_assinatura"),
        "dias_publicacao": row.get("dias_publicacao"),
        "prazo_execucao": row.get("prazo_execucao"),
        "n_concorrentes": row.get("n_concorrentes"),
        "ajuste_direto": row.get("ajuste_direto"),
        "ano": row.get("ano"),
        "cpv": row.get("cpv"),
        "cpv_grupo": row.get("cpv_grupo"),
        "procedimento": row.get("procedimento"),
        "adjudicante": row.get("adjudicante_nome") or row.get("adjudicante_nif"),
        "adjudicataria": adjudicataria,
        "z_cpv": z,
        "taxa_ajuste_direto_cpv": taxa_ajuste_direto_cpv,
        "taxa_aditivo_cpv": taxa_aditivo_cpv,
        "taxa_ajuste_direto_global": taxa_ajuste_direto_global,
        "contratos_do_cpv": contratos_do_cpv,
    }


#: Severidades ordenadas (as piores primeiro), para resumos e ordenação.
_SEVERIDADE_ORDEM = {"alerta": 0, "aviso": 1, "info": 2}


def severidade_de(sinais: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Severidade mais grave de um conjunto de sinais (ou `None`)."""
    valores = [str(sinal.get("severidade")) for sinal in sinais if sinal.get("severidade")]
    if not valores:
        return None
    return sorted(valores, key=lambda valor: _SEVERIDADE_ORDEM.get(valor, 9))[0]


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

#: Órgãos sociais que contam como **cargo de gestão**. O índice `finance_people`
#: é dominado por papéis processuais do CIRE («Credor», «Insolvente»,
#: «Administrador da insolvência», …): 600 mil cargos contra poucas dezenas de
#: órgãos sociais. Sem este filtro, o grafo ligava pessoas por serem credoras de
#: várias empresas falidas — ruído, não laço societário.
CARGO_GESTAO_ORGS: Tuple[str, ...] = (
    "Gerência",
    "Conselho De Administração",
    "Administração",
    "Sócios e Quotas",
    "Órgão social",
)


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


def _top_hit_name(agregado: Optional[Dict[str, Any]]) -> Optional[str]:
    """Nome a partir de um `top_hits` (aceita o objeto aninhado ou o pai).

    Dentro de um `nested` o `top_hits` pode devolver o documento aninhado ou o
    documento pai, pelo que a chave é procurada em qualquer nível.
    """
    if not isinstance(agregado, dict):
        return None

    def procurar(no: Any, profundidade: int = 0) -> Optional[str]:
        if profundidade > 3 or not isinstance(no, dict):
            return None
        for chave in ("nome", "name", "adjudicatario_nombre", "organo_nombre"):
            valor = no.get(chave)
            if isinstance(valor, str) and valor.strip():
                return valor.strip()
        for valor in no.values():
            achado = procurar(valor, profundidade + 1)
            if achado:
                return achado
        return None

    for hit in (agregado.get("hits") or {}).get("hits") or []:
        achado = procurar(hit.get("_source"))
        if achado:
            return achado
    return None


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


#: Cache das análises por empresa (independente da amostragem global).
_EMP_CACHE: Dict[Tuple[Any, ...], Tuple[float, Dict[str, Any]]] = {}
_EMP_CACHE_LOCK = threading.Lock()


def _emp_cache_get(key: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
    with _EMP_CACHE_LOCK:
        entry = _EMP_CACHE.get(key)
    if not entry:
        return None
    stamp, payload = entry
    if time.time() - stamp > CACHE_TTL_SECONDS:
        with _EMP_CACHE_LOCK:
            _EMP_CACHE.pop(key, None)
        return None
    return payload


def _emp_cache_put(key: Tuple[Any, ...], payload: Dict[str, Any]) -> None:
    with _EMP_CACHE_LOCK:
        if len(_EMP_CACHE) > 16:
            _EMP_CACHE.clear()
        _EMP_CACHE[key] = (time.time(), payload)


#: Sufixos/palavras que não ajudam a encontrar menções em notícias.
_RUIDO_SOCIETARIO = {
    "lda",
    "sa",
    "s",
    "a",
    "unipessoal",
    "sociedade",
    "empresa",
    "grupo",
    "e",
    "de",
    "da",
    "do",
    "das",
    "dos",
    "portugal",
}


def _nome_curto(nome: str) -> Optional[str]:
    """Marca curta para pesquisar notícias («Cimontubo - Tubagens, Lda» → «cimontubo»)."""
    tokens = [
        token
        for token in re.split(r"[^0-9a-z\u00c0-\u00ff]+", fold(str(nome or "")))
        if len(token) >= 3 and token not in _RUIDO_SOCIETARIO
    ]
    if not tokens:
        return None
    curto = " ".join(tokens[:2])
    completo = fold(str(nome or "")).strip()
    return None if curto == completo else curto


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
    # No Portal BASE `PrecoTotalEfetivo = 0` significa «ainda não há valor
    # efetivo registado» (é assim em ~60 % dos contratos), não «pagou zero».
    if effective is not None and effective <= 0:
        effective = None
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
        "tempos": {},
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
            "tempos": {},
            "error": "scikit-learn indisponível: só regras robustas por CPV",
        }

    scaled = sk["StandardScaler"]().fit_transform(matrix)
    scores: Dict[str, np.ndarray] = {}
    detectors: List[str] = []
    tempos_detetores: Dict[str, float] = {}

    def _lap(nome: str, inicio: float) -> None:
        tempos_detetores[nome] = round(time.time() - inicio, 2)

    contamination = max(0.005, min(0.2, float(contamination)))

    try:
        inicio = time.time()
        forest = sk["IsolationForest"](
            n_estimators=200, contamination=contamination, random_state=seed, n_jobs=-1
        ).fit(scaled)
        scores["isolation_forest"] = _ranks(-forest.score_samples(scaled))
        detectors.append("isolation_forest")
        _lap("isolation_forest", inicio)
    except Exception as exc:  # noqa: BLE001
        logger.warning("IsolationForest falhou: %s", exc)

    try:
        inicio = time.time()
        neighbours = min(20, max(5, n // 20 or 5))
        lof = sk["LocalOutlierFactor"](n_neighbors=neighbours, contamination=contamination)
        lof.fit_predict(scaled)
        scores["lof"] = _ranks(-lof.negative_outlier_factor_)
        detectors.append("lof")
        _lap("lof", inicio)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LOF falhou: %s", exc)

    try:
        inicio = time.time()
        clusters = max(2, min(12, len(set(cpvs)) or 6))
        kmeans = sk["KMeans"](n_clusters=clusters, n_init=10, random_state=seed).fit(scaled)
        distances = np.min(kmeans.transform(scaled), axis=1)
        # O id da chave tem de ser igual ao de `detectors` («kmeans»): se ficar
        # «cluster_distance» a UI mostra o id cru no chip (bug apanhado).
        scores["kmeans"] = _ranks(distances)
        detectors.append("kmeans")
        _lap("kmeans", inicio)
    except Exception as exc:  # noqa: BLE001
        logger.warning("KMeans falhou: %s", exc)

    try:
        # O One-Class SVM é o detetor mais caro (SMO é quadrático no nº de
        # amostras): corre numa sub-amostra de 2000 e só aí produz score.
        inicio = time.time()
        subset_size = min(n, 2000)
        rng = np.random.default_rng(seed)
        subset = rng.choice(n, size=subset_size, replace=False) if subset_size < n else np.arange(n)
        svm = sk["OneClassSVM"](nu=max(0.01, contamination), gamma="scale").fit(scaled[subset])
        partial = -svm.decision_function(scaled[subset])
        full = np.full(n, np.nan)
        full[subset] = partial
        scores["one_class_svm"] = _ranks(full)
        detectors.append("one_class_svm")
        _lap("one_class_svm", inicio)
    except Exception as exc:  # noqa: BLE001
        logger.warning("OneClassSVM falhou: %s", exc)

    noise = np.zeros(n, dtype=int)
    try:
        inicio = time.time()
        # O DBSCAN é o detetor mais caro com `eps` alto (as region queries
        # saturam e o algoritmo aproxima-se de O(n²)): corre numa sub-amostra
        # de 4000 pontos e só aí marca ruído (`noise` = 0 no resto, «não
        # avaliado»), tal como se faz com o One-Class SVM.
        k = min(10, max(4, n // 50 or 4))
        subset_size = min(n, 4000)
        if subset_size < n:
            rng = np.random.default_rng(seed)
            subset = rng.choice(n, size=subset_size, replace=False)
        else:
            subset = np.arange(n)
        sample = scaled[subset]
        neighbours_model = sk["NearestNeighbors"](n_neighbors=min(k + 1, len(sample))).fit(sample)
        distances = neighbours_model.kneighbors(sample, return_distance=True)[0][:, -1]
        eps = float(np.quantile(distances, 0.9))
        dbscan = sk["DBSCAN"](eps=max(eps, 0.5), min_samples=max(4, k)).fit(sample)
        noise[subset] = (dbscan.labels_ == -1).astype(int)
        detectors.append("dbscan")
        _lap("dbscan", inicio)
    except Exception as exc:  # noqa: BLE001
        logger.warning("DBSCAN falhou: %s", exc)

    inicio = time.time()
    z_cpv = _per_cpv_z(matrix, cpvs)
    _lap("z_cpv", inicio)

    continuous = [
        name for name in ("isolation_forest", "lof", "kmeans", "one_class_svm") if name in scores
    ]
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
        "tempos": tempos_detetores,
        "error": None,
    }


# ---------------------------------------------------------------------------
# 3. Regras interpretáveis (razões por contrato)
# ---------------------------------------------------------------------------
def _reasons(row: Dict[str, Any], *, z: float, cpv_rate_ad: Optional[float], global_rate_ad: Optional[float]) -> List[Dict[str, Any]]:
    """Sinais das **regras predefinidas** para um contrato.

    Wrapper de compatibilidade: avalia o conjunto de fábrica
    (`padroes_regras.REGRAS_DEFAULT`) sobre o contexto do contrato. O motor usa
    esta via quando não há regras guardadas ou quando só se quer a régua base.
    """
    contexto = _contexto_regras(
        row,
        z=z,
        taxa_ajuste_direto_cpv=cpv_rate_ad,
        taxa_ajuste_direto_global=global_rate_ad,
    )
    return regras.avaliar(contexto, regras.REGRAS_DEFAULT)


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

    # -- cargos: quem manda nas empresas que ganham aos mesmos adjudicantes --
    # Âncora escolhida: os adjudicantes com **mais fornecedores distintos** (é aí
    # que um gerente partilhado significa conluio). Ancorar nas empresas com
    # maior score de anomalia não encontrava nada — essas são, por definição,
    # casos isolados, e um gerente comum entre dois casos isolados é raro.
    by_company: Dict[str, List[Dict[str, Any]]] = {}
    by_adjudicante: Dict[str, List[Dict[str, Any]]] = {}
    for edge in edges.values():
        if edge["source"].startswith("entity:"):
            by_company.setdefault(edge["target"], []).append(edge)
            by_adjudicante.setdefault(edge["source"], []).append(edge)

    ranked_adjudicantes = sorted(by_adjudicante.items(), key=lambda kv: -len(kv[1]))
    pool_nifs: List[str] = []
    adjudicantes_por_empresa: Dict[str, List[str]] = {}
    for source, list_of_edges in ranked_adjudicantes[:25]:
        for edge in list_of_edges:
            company_nif = edge["target"].split(":", 1)[-1]
            adjudicantes_por_empresa.setdefault(company_nif, []).append(source)
            pool_nifs.append(company_nif)
    # Junta ainda as empresas com maior valor contratado (peso económico) e as
    # que têm mais contratos — é onde faz sentido procurar insolvências.
    top_valor = sorted(entities, key=lambda e: -(e.get("valor_total") or 0))[:200]
    top_contratos = sorted(entities, key=lambda e: -(e.get("contratos") or 0))[:200]
    pool_nifs.extend(str(e["nif"]) for e in [*top_valor, *top_contratos] if e.get("nif"))
    pool_nifs = list(dict.fromkeys(nif for nif in pool_nifs if nif))[:600]

    laços: List[Dict[str, Any]] = []
    people_alerts: List[Dict[str, Any]] = []
    if client is not None and pool_nifs:
        wanted = set(pool_nifs)
        seen_persons: Dict[str, Dict[str, Any]] = {}
        for chunk_start in range(0, len(pool_nifs), 40):
            chunk = pool_nifs[chunk_start : chunk_start + 40]
            body = {
                "size": 500,
                "track_total_hits": False,
                "_source": ["nif", "name", "roles"],
                "query": {
                    "nested": {
                        "path": "roles",
                        "query": {
                            "bool": {
                                "filter": [
                                    {"terms": {"roles.company_nif": chunk}},
                                    {"terms": {"roles.role_org": list(CARGO_GESTAO_ORGS)}},
                                ]
                            }
                        },
                    }
                },
            }
            resp = _search(client, PEOPLE_INDEX, body, timeout=60)
            for hit in _hits(resp):
                src = hit.get("_source") or {}
                person_nif = str(src.get("nif") or hit.get("_id") or "").strip()
                person_name = str(src.get("name") or "").strip()
                cargos: Dict[str, List[str]] = {}
                for role in (src.get("roles") or []):
                    if not isinstance(role, dict):
                        continue
                    company_nif = str(role.get("company_nif") or "").strip()
                    if company_nif not in wanted:
                        continue
                    if str(role.get("role_org") or "") not in CARGO_GESTAO_ORGS:
                        continue
                    cargos.setdefault(company_nif, [])
                    cargo = str(role.get("role") or "cargo")
                    if cargo not in cargos[company_nif]:
                        cargos[company_nif].append(cargo)
                linked = sorted(cargos)
                if not person_nif or len(linked) < 2:
                    continue
                entry = seen_persons.setdefault(
                    person_nif,
                    {"pessoa": person_name or person_nif, "pessoa_nif": person_nif, "empresas_nif": [], "cargos": {}},
                )
                for company_nif in linked:
                    if company_nif not in entry["empresas_nif"]:
                        entry["empresas_nif"].append(company_nif)
                    entry["cargos"][company_nif] = cargos[company_nif]

        for entry in seen_persons.values():
            if len(entry["empresas_nif"]) < 2:
                continue
            p_key = f"person:{entry['pessoa_nif']}"
            add_node(p_key, entry["pessoa"], "person")
            entry["empresas"] = []
            for company_nif in entry["empresas_nif"]:
                c_key = f"company:{company_nif}"
                if c_key not in nodes:
                    add_node(c_key, company_nif, "company")
                entry["empresas"].append(nodes[c_key]["label"])
                edge = edges.setdefault((p_key, c_key), {"source": p_key, "target": c_key, "count": 0, "value": 0.0})
                edge["count"] += 1
            entry["cargos"] = {nif: " / ".join(cargos) for nif, cargos in entry["cargos"].items()}
            entry["tipo"] = "pessoa_ligada_a_varias_adjudicatarias"
            people_alerts.append(entry)
            # Laços concretos: empresas da mesma pessoa que ganham ao MESMO adjudicante.
            for index, first in enumerate(entry["empresas_nif"]):
                for second in entry["empresas_nif"][index + 1 :]:
                    comuns = set(adjudicantes_por_empresa.get(first, [])) & set(adjudicantes_por_empresa.get(second, []))
                    for source in comuns:
                        first_edge = edges.get((source, f"company:{first}"))
                        second_edge = edges.get((source, f"company:{second}"))
                        laços.append(
                            {
                                "tipo": "conluio_potencial",
                                "detalhe": f"«{entry['pessoa']}» liga "
                                f"«{nodes.get(f'company:{first}', {}).get('label') or first}» e "
                                f"«{nodes.get(f'company:{second}', {}).get('label') or second}», que ganharam ambas a "
                                f"«{nodes.get(source, {}).get('label') or source}»",
                                "adjudicante": nodes.get(source, {}).get("label") or source,
                                "empresa": nodes.get(f"company:{first}", {}).get("label") or first,
                                "empresa_2": nodes.get(f"company:{second}", {}).get("label") or second,
                                "pessoa": entry["pessoa"],
                                "contratos": (first_edge or {}).get("count", 0) + (second_edge or {}).get("count", 0),
                                "valor": num(((first_edge or {}).get("value") or 0) + ((second_edge or {}).get("value") or 0)),
                            }
                        )
    # (a deduplicação dos laços faz-se no fim, depois de juntar os do CIRE)

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
    # O índice do CIRE guarda os NIFs em `nifs` (keyword) e o nome do insolvente
    # em `insolvente`; `intervenientes` (nested) tem os restantes intervenientes,
    # incluindo o administrador da insolvência.
    insolventes: List[Dict[str, Any]] = []
    processos: Dict[str, Dict[str, Any]] = {}
    if client is not None and pool_nifs:
        for chunk_start in range(0, len(pool_nifs), 100):
            chunk = pool_nifs[chunk_start : chunk_start + 100]
            body = {
                "size": 500,
                "track_total_hits": False,
                "_source": [
                    "nifs",
                    "insolvente",
                    "especie",
                    "ato",
                    "data_publicacao",
                    "tribunal",
                    "processo_numero",
                    "intervenientes",
                ],
                "query": {"terms": {"nifs": chunk}},
            }
            resp = _search(client, CIRE_INDEX, body, timeout=45)
            for hit in _hits(resp):
                src = hit.get("_source") or {}
                nome = str(src.get("insolvente") or "").strip()
                processo = str(src.get("processo_numero") or src.get("processo") or "").strip()
                # Só o **insolvente** conta como ligação: os credores são
                # centenas (Segurança Social, AT, banca) e ligariam tudo a tudo.
                insolventes_do_processo: List[str] = []
                for entry in (src.get("intervenientes") or []):
                    if not isinstance(entry, dict):
                        continue
                    nif_entry = str(entry.get("nif") or "").strip()
                    if nif_entry and "insolvente" in fold(entry.get("papel")):
                        insolventes_do_processo.append(nif_entry)
                if processo:
                    entry = processos.setdefault(
                        processo,
                        {
                            "processo": processo,
                            "nifs": set(),
                            "empresas": [],
                            "especie": src.get("especie"),
                            "data": src.get("data_publicacao"),
                            "tribunal": src.get("tribunal"),
                            "insolvente": nome,
                        },
                    )
                    entry["nifs"].update(insolventes_do_processo)
                for nif in insolventes_do_processo:
                    if nif not in chunk:
                        continue
                    insolventes.append(
                        {
                            "nif": nif,
                            "nome": nome or None,
                            "especie": src.get("especie"),
                            "ato": src.get("ato"),
                            "data": src.get("data_publicacao"),
                            "tribunal": src.get("tribunal"),
                            "processo": processo or None,
                        }
                    )

    # Empresas adjudicatárias que aparecem no **mesmo processo** — sinal de
    # grupo económico em dificuldade (não é «têm o mesmo administrador de
    # insolvência»: ser administrador de muitos processos é a profissão deles).
    pool_set = set(pool_nifs)
    for entry in processos.values():
        empresas = [nif for nif in entry["nifs"] if nif in pool_set]
        entry["empresas"] = empresas
        if len(empresas) < 2:
            continue
        for index, first in enumerate(empresas):
            for second in empresas[index + 1 :]:
                laços.append(
                    {
                        "tipo": "insolvencia_partilhada",
                        "detalhe": f"as duas adjudicatárias são insolventes no mesmo processo {entry['processo']} "
                        f"({entry.get('especie') or 'insolvência'})",
                        "adjudicante": None,
                        "empresa": nodes.get(f"company:{first}", {}).get("label") or first,
                        "empresa_2": nodes.get(f"company:{second}", {}).get("label") or second,
                        "pessoa": None,
                        "contratos": 0,
                        "valor": None,
                        "processo": entry["processo"],
                        "data": entry.get("data"),
                    }
                )
    insolvente_nifs = {item["nif"] for item in insolventes}
    for entity in entities:
        entity["insolvente"] = bool(entity.get("nif") and str(entity["nif"]) in insolvente_nifs)

    # Deduplicação final dos laços (inclui agora os do CIRE).
    seen = set()
    unique_laços: List[Dict[str, Any]] = []
    for laço in sorted(laços, key=lambda item: -(item.get("valor") or 0)):
        key = (
            laço["tipo"],
            laço.get("pessoa"),
            laço.get("adjudicante"),
            laço.get("empresa"),
            laço.get("empresa_2"),
            laço.get("processo"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_laços.append(laço)

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
    vistos: set = set()
    for label, name in names:
        clean = str(name or "").strip()
        if len(clean) < 4:
            continue
        out.extend(_rss_mentions(label, clean, per_name))
        if client is None:
            continue
        out.extend(_es_mentions(client, SCRAPED_INDEX, label, clean, per_name, date_field="scraped_at", extra=["source_name"]))
        out.extend(_es_mentions(client, SOCIAL_INDEX, label, clean, per_name, date_field="published_at", extra=["platform", "channel_name"]))
    dedupe: List[Dict[str, Any]] = []
    for item in out:
        chave = str(item.get("url") or item.get("titulo") or "").strip().lower()
        if chave and chave in vistos:
            continue
        vistos.add(chave)
        dedupe.append(item)
    dedupe.sort(key=lambda item: str(item.get("data") or ""), reverse=True)
    return dedupe[:80]


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

    # IMPORTANTE: `ratio_efetivo` (valor efetivo / contratual) é a **origem do
    # rótulo**, pelo que não pode ser feature — incluí-la daria AUC = 1,0 por
    # fuga de informação (foi o erro apanhado na primeira validação).
    names_all = list(feature_names)
    keep_columns = [i for i, name in enumerate(names_all) if name != "ratio_efetivo"]
    names = [names_all[i] for i in keep_columns] + ["cpv_frequencia"]
    X = matrix[indexes][:, keep_columns]
    y = np.array(labels)
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
    for position in np.argsort(-full_probabilities)[:200]:
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
    mark = started
    tempos: Dict[str, float] = {}

    def _lap(nome: str) -> None:
        nonlocal mark
        agora = time.time()
        tempos[nome] = round(agora - mark, 2)
        mark = agora

    years = _years_in_index(client, spec)
    if ano_from is None and years:
        ano_from = years[0]
    if ano_to is None:
        ano_to = years[-1] if years else datetime.now().year
    if ano_from and ano_to and ano_from > ano_to:
        ano_from, ano_to = ano_to, ano_from
    _lap("anos")

    rows, coverage = _sample(
        client,
        spec,
        ano_from=ano_from,
        ano_to=ano_to,
        cpv=cpv,
        per_year=per_year,
        years=[y for y in years if ano_from <= y <= ano_to] or None,
    )
    _lap("amostragem")
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
    _lap("deteccao")
    consensus = detection["consensus"]
    votes = detection["votes"]
    z_cpv = detection["z_per_cpv"]

    global_rate_ad = sum(row.get("ajuste_direto") or 0 for row in rows) / len(rows)
    cpv_table = _cpv_table(rows, global_rate_ad)
    _lap("cpv")
    cpv_rate_ad = {item["cpv"]: item["taxa_ajuste_direto"] for item in cpv_table}
    cpv_metricas = {item["cpv"]: item for item in cpv_table}

    # -- regras (editáveis na página) ----------------------------------------
    regras_ativas = regras.regras_ativas()
    contextos: List[Dict[str, Any]] = []
    for index, row in enumerate(rows):
        grupo = row.get("cpv_grupo") or ""
        metricas = cpv_metricas.get(grupo) or {}
        contextos.append(
            _contexto_regras(
                row,
                z=float(z_cpv[index]) if index < z_cpv.size else 0.0,
                taxa_ajuste_direto_cpv=metricas.get("taxa_ajuste_direto"),
                taxa_aditivo_cpv=metricas.get("taxa_aditivo"),
                taxa_ajuste_direto_global=global_rate_ad,
                contratos_do_cpv=metricas.get("contratos"),
            )
        )
    hits_por_contrato: List[List[Dict[str, Any]]] = [regras.avaliar(contexto, regras_ativas) for contexto in contextos]

    # Contratos sinalizados: consenso alto **e** pelo menos dois detectores de acordo.
    threshold = float(np.quantile(consensus, 0.9)) if consensus.size else 1.0
    anomalies: Dict[int, Dict[str, Any]] = {}
    anomaly_list: List[Dict[str, Any]] = []
    for index, row in enumerate(rows):
        score = float(consensus[index])
        if votes[index] < 2 or score < max(threshold, 0.6):
            continue
        reasons = hits_por_contrato[index]
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
            "severidade": severidade_de(reasons),
        }
        anomalies[index] = entry
        anomaly_list.append(entry)
    anomaly_list.sort(key=lambda item: -(item.get("score") or 0))
    _lap("sinalizacao")

    for item in cpv_table:
        item["contratos_sinalizados"] = sum(
            1 for entry in anomaly_list if entry.get("cpv_grupo") == item["cpv"]
        )

    # -- regras: que contratos cumprem cada regra (independente do ML) -------
    contagem_regras: Dict[str, int] = {}
    regras_hits: List[Dict[str, Any]] = []
    for index, hits in enumerate(hits_por_contrato):
        if not hits:
            continue
        for hit in hits:
            identificador = str(hit.get("padrao"))
            contagem_regras[identificador] = contagem_regras.get(identificador, 0) + 1
        row = rows[index]
        regras_hits.append(
            {
                "id": row.get("id"),
                "ano": row.get("ano"),
                "objeto": row.get("objeto"),
                "valor": num(row.get("valor")),
                "cpv": row.get("cpv"),
                "cpv_grupo": row.get("cpv_grupo"),
                "procedimento": row.get("procedimento"),
                "adjudicante": row.get("adjudicante_nome"),
                "adjudicante_nif": row.get("adjudicante_nif"),
                "adjudicataria": next(
                    (party.get("nome") for party in row.get("adjudicatarios") or [] if isinstance(party, dict)),
                    None,
                ),
                "adjudicataria_nif": next(
                    (party.get("nif") for party in row.get("adjudicatarios") or [] if isinstance(party, dict)),
                    None,
                ),
                "severidade": severidade_de(hits),
                "regras": [hit.get("padrao") for hit in hits],
                "rotulos": [hit.get("label") for hit in hits],
                "detalhes": [hit.get("detalhe") for hit in hits][:6],
            }
        )
    regras_hits.sort(
        key=lambda item: (
            _SEVERIDADE_ORDEM.get(str(item.get("severidade")), 9),
            -len(item.get("regras") or []),
            -(item.get("valor") or 0),
        )
    )
    regras_resumo = regras.resumo_regras(regras_ativas)
    for item in regras_resumo:
        item["contratos"] = contagem_regras.get(str(item["id"]), 0)

    entities = _entity_table(rows, anomalies)
    entity_model = _score_entities(entities, seed=seed)
    _lap("entidades")
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
    _lap("relacoes")

    # As entidades insolventes entram no topo da lista (podem ter score baixo e
    # desapareceriam da janela de 300 que a UI mostra).
    top_entities = entities[:300]
    presentes = {entity.get("nif") for entity in top_entities}
    for entity in entities:
        if entity.get("insolvente"):
            entity["motivos"].append("processo de insolvência/PER registado no CIRE")
            if entity.get("nif") not in presentes:
                top_entities.append(entity)
                presentes.add(entity.get("nif"))

    risk = _risk_model(rows, imputed, seed=seed, feature_names=used_features)
    _lap("risco")

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
        "contratos_com_regras": len(regras_hits),
        "taxa_com_regras": num(len(regras_hits) / len(rows)),
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
        "tempos": tempos,
        "overview": overview,
        "cpvs": cpv_table,
        "anomalias": anomaly_list[:400],
        "entidades": top_entities,
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
            "tempos_detetores": detection.get("tempos") or {},
            "nota": "Os scores são percentis [0,1]: 1 é o contrato mais atípico da amostra.",
        },
        "padroes": catalogo_padroes(),
        "regras": {
            "ativas": regras_resumo,
            "total_regras": len(regras.listar()["regras"]),
            "templates": regras.listar()["templates"],
        },
        "regras_hits": regras_hits[:300],
        "modelo_entidades": entity_model,
        "parametros": {"sample_per_year": SAMPLE_PER_YEAR_DEFAULT, "cache_ttl_s": CACHE_TTL_SECONDS},
    }
    if use_cache:
        _cache_put(key, payload)
    return payload


def news_mentions(names: Sequence[Tuple[str, str]], *, per_name: int = 5, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Menções públicas de uma lista de entidades (`(rótulo, nome)`).

    Wrapper público de `_news_for` para as rotas (evita que o router conheça os
    detalhes dos índices e do leitor RSS).
    """
    return _news_for(_client(es), names, per_name=per_name)


def clear_cache() -> int:
    """Esvazia a cache de análises e devolve quantas entradas removeu."""
    with _CACHE_LOCK:
        size = len(_CACHE)
        _CACHE.clear()
    with _EMP_CACHE_LOCK:
        size += len(_EMP_CACHE)
        _EMP_CACHE.clear()
    return size


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
        "padroes": catalogo_padroes(),
        "regras_disponiveis": regras.listar()["regras"],
        "templates": regras.listar()["templates"],
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


def _co_intervenientes_cire(client: Elasticsearch, processos: Sequence[str], nif: str, *, size: int = 20) -> List[Dict[str, Any]]:
    """Quem mais está nos processos do CIRE desta empresa.

    É esta a ligação que interessa a um analista: quem aparece ao lado da empresa
    num processo de insolvência (administradores, credores, outras empresas do
    grupo). Uma só consulta por `terms` nos números de processo.

    O limite é baixo de propósito: cada interveniente é um nó no grafo do
    dossiê e o desenho (simulação de forças no browser) é o passo mais caro da
    página. Com 8 processos chegam 20 nomes para ver quem se cruza.
    """
    numeros = [str(processo).strip() for processo in processos if str(processo or "").strip()]
    numeros = list(dict.fromkeys(numeros))[:8]
    if not numeros:
        return []
    body = {
        "size": 20,
        "track_total_hits": False,
        "_source": ["processo_numero", "intervenientes"],
        "query": {"terms": {"processo_numero": numeros}},
    }
    saida: List[Dict[str, Any]] = []
    vistos: set = set()
    try:
        resp = _search(client, CIRE_INDEX, body, timeout=45)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Intervenientes do CIRE indisponíveis: %s", exc)
        return []
    for hit in _hits(resp):
        src = hit.get("_source") or {}
        processo = str(src.get("processo_numero") or "").strip()
        for pessoa in src.get("intervenientes") or []:
            if not isinstance(pessoa, dict):
                continue
            outro = str(pessoa.get("nif") or "").strip()
            nome = str(pessoa.get("nome") or "").strip()
            if not outro or outro == nif:
                continue
            chave = (processo, outro)
            if chave in vistos:
                continue
            vistos.add(chave)
            saida.append({"processo": processo, "nif": outro, "nome": nome or outro, "papel": pessoa.get("papel")})
            if len(saida) >= size:
                return saida
    return saida


def _dossie_grafo(
    *,
    nif: str,
    label: str,
    contracts: Sequence[Dict[str, Any]],
    adjudicantes: Dict[str, float],
    nomes_adjudicantes: Dict[str, str],
    cargos_sociais: Sequence[Dict[str, Any]],
    intervenientes_cire: Sequence[Dict[str, Any]],
    cire: Sequence[Dict[str, Any]],
    co_intervenientes: Sequence[Dict[str, Any]],
    max_adjudicantes: int = 10,
    max_pessoas: int = 12,
    max_processos: int = 8,
) -> Dict[str, Any]:
    """Grafo do dossiê: empresa ↔ adjudicantes, órgãos sociais e processos do CIRE.

    Segue a forma de `ContractGraphBuildResponse` (a mesma do estúdio de grafos),
    para o dossiê poder desenhar com o `GraphCanvas` sem conversões próprias.

    Os limites são apertados de propósito: um dossiê é uma vista de leitura e o
    desenho é feito no browser — 30 nós dizem o mesmo que 70 e não prendem a
    aplicação. O dossiê traz também as listas completas (contratos, cargos,
    processos e intervenientes), pelo que nada se perde em detalhe.
    """
    centro = f"empresa:{nif}"
    nodes: List[Dict[str, Any]] = [
        {
            "id": centro,
            "key": nif,
            "label": label or nif,
            "dimension": "empresa",
            "type": "entidade",
            "role": "empresa analisada",
            "count": len(contracts),
            "total_value": num(sum((contrato.get("valor") or 0.0) for contrato in contracts)) or 0.0,
        }
    ]
    edges: List[Dict[str, Any]] = []
    ids = {centro}

    # Adjudicantes (quem compra) — é onde está o valor.
    contagens: Dict[str, int] = {}
    for contrato in contracts:
        chave = str(contrato.get("adjudicante_nif") or contrato.get("adjudicante") or "")
        if chave:
            contagens[chave] = contagens.get(chave, 0) + 1
    for chave, valor in sorted(adjudicantes.items(), key=lambda item: -item[1])[:max_adjudicantes]:
        no = f"adjudicante:{chave}"
        if no in ids:
            continue
        ids.add(no)
        nodes.append(
            {
                "id": no,
                "key": str(chave),
                "label": nomes_adjudicantes.get(str(chave)) or str(chave),
                "dimension": "adjudicante",
                "type": "entidade",
                "role": f"compra ({contagens.get(str(chave), 0)} contratos)",
                "count": contagens.get(str(chave), 0),
                "total_value": num(valor) or 0.0,
            }
        )
        edges.append({"source": centro, "target": no, "count": contagens.get(str(chave), 0), "value": num(valor) or 0.0})

    # Órgãos sociais (pessoas com cargo registado).
    for pessoa in cargos_sociais[:max_pessoas]:
        chave = str(pessoa.get("nif") or pessoa.get("nome") or "")
        no = f"pessoa:{chave}"
        if no in ids:
            continue
        ids.add(no)
        cargos = pessoa.get("cargos") or []
        nodes.append(
            {
                "id": no,
                "key": chave,
                "label": pessoa.get("nome") or chave,
                "dimension": "pessoa",
                "type": "pessoa",
                "role": ", ".join(
                    sorted({str(cargo.get("role_org") or cargo.get("role") or "") for cargo in cargos} - {""})
                )[:80],
                "count": len(cargos),
                "total_value": 0.0,
            }
        )
        # A direção aponta para a empresa (quem gere), não o contrário.
        edges.append({"source": no, "target": centro, "count": len(cargos), "value": 0.0})

    # Processos do CIRE e quem mais lá aparece.
    processos = [item for item in cire[:max_processos] if item.get("processo") or item.get("especie")]
    for indice, item in enumerate(processos):
        chave = str(item.get("processo") or f"processo-{indice}")
        no = f"cire:{chave}"
        if no in ids:
            continue
        ids.add(no)
        nodes.append(
            {
                "id": no,
                "key": chave,
                "label": str(item.get("especie") or "processo CIRE")[:60],
                "dimension": "cire",
                "type": "processo",
                "role": f"{item.get('tribunal') or 'tribunal'} · {str(item.get('data') or '')[:10]}",
                "count": 1,
                "total_value": 0.0,
            }
        )
        edges.append({"source": centro, "target": no, "count": 1, "value": 0.0})

    lacos: List[Dict[str, Any]] = []
    for outro in co_intervenientes:
        chave = str(outro.get("nif") or "")
        no = f"interveniente:{chave}"
        if no not in ids:
            ids.add(no)
            nodes.append(
                {
                    "id": no,
                    "key": chave,
                    "label": outro.get("nome") or chave,
                    "dimension": "interveniente",
                    "type": "pessoa" if _parece_pessoa(chave) else "entidade",
                    "role": f"{outro.get('papel') or 'interveniente'} (CIRE)",
                    "count": 1,
                    "total_value": 0.0,
                }
            )
        processo = str(outro.get("processo") or "")
        alvo = f"cire:{processo}"
        if alvo in ids and processo:
            edges.append({"source": alvo, "target": no, "count": 1, "value": 0.0})
        else:
            edges.append({"source": centro, "target": no, "count": 1, "value": 0.0})
        lacos.append(
            {
                "tipo": "processo_partilhado",
                "detalhe": f"{outro.get('nome') or chave} é {outro.get('papel') or 'interveniente'} no processo {processo or '—'}",
                "nif": chave,
                "nome": outro.get("nome"),
                "processo": processo or None,
                "papel": outro.get("papel"),
            }
        )

    # Pessoas com papéis processuais (mas sem cargo social) também contam como ligação.
    for pessoa in intervenientes_cire[:6]:
        chave = str(pessoa.get("nif") or "")
        no = f"pessoa:{chave}"
        if not chave or no in ids:
            continue
        ids.add(no)
        cargos = pessoa.get("cargos") or []
        nodes.append(
            {
                "id": no,
                "key": chave,
                "label": pessoa.get("nome") or chave,
                "dimension": "pessoa",
                "type": "pessoa",
                "role": ", ".join(sorted({str(cargo.get("role") or "") for cargo in cargos} - {""}))[:80] or "papel processual",
                "count": len(cargos),
                "total_value": 0.0,
            }
        )
        edges.append({"source": no, "target": centro, "count": len(cargos) or 1, "value": 0.0})

    n_nodes = len(nodes)
    n_edges = len(edges)
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "dimension_a": "empresa",
            "dimension_b": None,
            "metric": "contratos",
            "mode": "relations",
            "complete": False,
            "scan_capped": True,
            "sample_order": "amostra do dossiê (contratos mais recentes)",
            "sample_limit": len(contracts),
            "documents_scanned": len(contracts),
            "documents_matching": len(contracts),
            "scanned_value": num(sum((contrato.get("valor") or 0.0) for contrato in contracts)) or 0.0,
            "nodes_total": n_nodes,
            "edges_total": n_edges,
            "kept_nodes": n_nodes,
            "kept_edges": n_edges,
            "omitted_edges": 0,
            "coverage_value_share": None,
            "coverage_count_share": None,
            "directed": True,
            "limits": {
                "adjudicantes": max_adjudicantes,
                "pessoas": max_pessoas,
                "processos": max_processos,
                "intervenientes_cire": len(co_intervenientes),
            },
            "notes": [
                "Grafo da amostra do dossiê (não da totalidade do portal).",
                "As ligações a pessoas usam cargos de órgãos sociais; os papéis processuais do CIRE aparecem como intervenientes.",
            ],
            "filters": {"nif": nif},
        },
        "lacos": lacos[:20],
    }


def _parece_pessoa(nif: str) -> bool:
    """NIF de pessoa singular (PT: 1/2/3 + 8 dígitos) vs pessoa coletiva (5/6/7/8/9)."""
    chave = "".join(ch for ch in str(nif or "") if ch.isdigit())
    return len(chave) == 9 and chave[0] in {"1", "2", "3"}


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
        "size": 300,
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
                "cpv_desc": row["cpv_desc"],
                "n_concorrentes": row["n_concorrentes"],
                "adjudicante": row["adjudicante_nome"],
                "adjudicante_nif": row["adjudicante_nif"],
                "dias_decisao": row["dias_decisao"],
                "dias_assinatura": row["dias_assinatura"],
                "dias_publicacao": row["dias_publicacao"],
                "data_publicacao": row["data_publicacao"],
            }
        )

    people: List[Dict[str, Any]] = []
    body_people = {
        "size": 60,
        "track_total_hits": True,
        "_source": ["nif", "name", "roles"],
        "query": {"nested": {"path": "roles", "query": {"term": {"roles.company_nif": nif}}}},
    }
    pessoas_resp = _search(client, PEOPLE_INDEX, body_people, timeout=45)
    pessoas_total = int((((pessoas_resp.get("hits") or {}).get("total") or {}).get("value")) or 0)
    for hit in _hits(pessoas_resp):
        src = hit.get("_source") or {}
        roles = [
            {
                "role": role.get("role"),
                "role_org": role.get("role_org"),
                "acto": role.get("acto"),
                "data": role.get("date"),
                "publicacao": role.get("publication_id"),
            }
            for role in (src.get("roles") or [])
            if isinstance(role, dict) and str(role.get("company_nif") or "") == nif
        ][:10]
        if roles:
            people.append({"nif": src.get("nif"), "nome": src.get("name"), "cargos": roles})

    cire: List[Dict[str, Any]] = []
    cire_body = {
        "size": 50,
        "track_total_hits": True,
        "_source": ["insolvente", "especie", "ato", "data_publicacao", "tribunal", "processo_numero"],
        "query": {"terms": {"nifs": [nif]}},
        "sort": [{"data_publicacao": {"order": "desc", "unmapped_type": "date"}}],
    }
    cire_resp = _search(client, CIRE_INDEX, cire_body, timeout=45)
    cire_total = int((((cire_resp.get("hits") or {}).get("total") or {}).get("value")) or 0)
    for hit in _hits(cire_resp):
        src = hit.get("_source") or {}
        cire.append(
            {
                "especie": src.get("especie"),
                "ato": src.get("ato"),
                "data": src.get("data_publicacao"),
                "tribunal": src.get("tribunal"),
                "processo": src.get("processo_numero"),
            }
        )

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
    nomes_adjudicantes: Dict[str, str] = {}
    for contract in contracts:
        key = contract.get("adjudicante_nif") or contract.get("adjudicante") or "?"
        adjudicantes[key] = adjudicantes.get(key, 0.0) + (contract.get("valor") or 0.0)
        if contract.get("adjudicante"):
            nomes_adjudicantes[str(key)] = str(contract["adjudicante"])
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
        maior = max(adjudicantes, key=adjudicantes.get)
        sinais.append(
            {
                "padrao": "concentracao_fornecedor",
                "detalhe": f"{adjudicantes[maior] / total_valor * 100:.0f}% do valor vem de "
                f"{nomes_adjudicantes.get(str(maior)) or maior}",
            }
        )
    if cire:
        total_cire = cire_total or len(cire)
        detalhe = f"{total_cire} processo(s) no CIRE"
        if len(cire) < total_cire:
            detalhe += f" ({len(cire)} lidos)"
        sinais.append({"padrao": "insolvencia", "detalhe": detalhe, "total": total_cire, "itens": len(cire)})
    cargos_sociais = [
        person for person in people if any(str(c.get("role_org") or "") in CARGO_GESTAO_ORGS for c in person["cargos"])
    ]
    if cargos_sociais:
        sinais.append(
            {
                "padrao": "rede_pessoas",
                "detalhe": f"{len(cargos_sociais)} pessoa(s) com cargo de órgão social registado nesta empresa",
                "total": len(cargos_sociais),
                "itens": len(cargos_sociais),
            }
        )

    noticias = _news_for(client, [(label, label)], per_name=6)

    # -- quem mais aparece nos processos desta empresa ----------------------
    co_intervenientes = _co_intervenientes_cire(client, [item.get("processo") or "" for item in cire], nif)
    intervenientes_cire = [person for person in people if person not in cargos_sociais]
    grafo = _dossie_grafo(
        nif=nif,
        label=label,
        contracts=contracts,
        adjudicantes=adjudicantes,
        nomes_adjudicantes=nomes_adjudicantes,
        cargos_sociais=cargos_sociais,
        intervenientes_cire=intervenientes_cire,
        cire=cire,
        co_intervenientes=co_intervenientes,
    )

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
        "cargos_sociais": cargos_sociais,
        "intervenientes_cire": intervenientes_cire[:20],
        "insolvencias": cire,
        "insolvencias_total": cire_total or len(cire),
        "pessoas_total": pessoas_total or len(people),
        "intervenientes_processos": co_intervenientes,
        "grafo": grafo,
        "lacos": grafo["lacos"],
        "noticias": noticias,
    }

# ---------------------------------------------------------------------------
# 9. Análise de uma empresa (pesquisa → análise dos seus contratos e relações)
# ---------------------------------------------------------------------------
def _empresa_query(spec: CountrySpec, nif: str) -> Dict[str, Any]:
    """Filtro dos contratos em que a empresa é adjudicatária.

    No PT o NIF vive num campo aninhado (`adjudicatarios.parsed.nif`, keyword);
    no PLACSP é plano e aparece com capitalizações diferentes (`A28791069` vs
    `a28791069`), pelo que a comparação é insensível a maiúsculas.
    """
    if spec.key == "PT":
        return {"nested": {"path": spec.adjudicatario_path, "query": {"term": {spec.adjudicatario_nif: nif}}}}
    return {"wildcard": {spec.adjudicatario_nif: {"value": nif, "case_insensitive": True}}}


def _nif_puro(texto: str, spec: CountrySpec) -> Optional[str]:
    """Devolve o NIF quando o texto **é** um NIF (e não um nome de empresa)."""
    compacto = re.sub(r"[\s.\-/]", "", texto or "")
    if not compacto or not re.fullmatch(r"[A-Za-z0-9]+", compacto):
        return None
    if len(compacto) < 8 or len(compacto) > 10:
        return None
    digitos = sum(1 for ch in compacto if ch.isdigit())
    if digitos < 6:
        return None
    return compacto.upper() if spec.key == "ES" else compacto


def _candidatos_contribuintes(client: Elasticsearch, texto: str, *, size: int = 8) -> List[Dict[str, Any]]:
    """Empresas do cadastro (`finance_contribuintes`) cujo nome casa com o texto.

    Aqui o nome é um campo `text` (analisador próprio, tolerante a acentos e
    ruído), ao contrário do nome nos contratos, que é `keyword`.
    """
    body = {
        "size": size,
        "_source": [
            "nif",
            "name",
            "names",
            "country",
            "location",
            "roles",
            "type",
            "is_company",
            "contracts_count",
            "contracts_value",
            "src_contratos",
        ],
        "query": {
            "bool": {
                "should": [
                    {"match": {"name": {"query": texto, "operator": "and"}}},
                    {"match": {"search_text": {"query": texto, "operator": "and"}}},
                    {"match": {"names": {"query": texto, "operator": "and"}}},
                ],
                "minimum_should_match": 1,
            }
        },
        "sort": [{"contracts_count": {"order": "desc", "unmapped_type": "long"}}],
    }
    try:
        resp = _search(client, CONTRIBUINTES_INDEX, body, timeout=30)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cadastro de contribuintes indisponível (%s).", exc)
        return []
    candidatos: List[Dict[str, Any]] = []
    for hit in _hits(resp):
        src = hit.get("_source") or {}
        nif = str(src.get("nif") or "").strip()
        if not nif:
            continue
        partes = ((src.get("src_contratos") or {}).get("parts") or {}).get("adjudicatario") or {}
        candidatos.append(
            {
                "nif": nif,
                "nome": src.get("name") or nif,
                "alias": (src.get("names") or [])[:3],
                "contratos": as_int(src.get("contracts_count")),
                "valor": num(src.get("contracts_value")),
                "papeis": list(src.get("roles") or []),
                "concelho": (src.get("location") or {}).get("concelho") if isinstance(src.get("location"), dict) else None,
                "fonte": "cadastro",
                "valor_adjudicatario": num(partes.get("value")),
            }
        )
    candidatos.sort(
        key=lambda item: (
            0 if "adjudicatario" in (item.get("papeis") or []) else 1,
            -(item.get("contratos") or 0),
        )
    )
    return candidatos


def _candidatos_contratos_pt(client: Elasticsearch, spec: CountrySpec, texto: str, *, size: int = 6) -> List[Dict[str, Any]]:
    """Último recurso: procurar o nome **dentro** dos contratos (campo `keyword`).

    Usa `wildcard` insensível a maiúsculas sobre o nome da parte e agrega por
    NIF; o `filter` dentro do `nested` garante que os baldes só contêm a parte
    que realmente casou com o texto.
    """
    condicao = {"wildcard": {spec.adjudicatario_nome: {"value": f"*{texto}*", "case_insensitive": True}}}
    body = {
        "size": 0,
        "track_total_hits": False,
        "query": {"nested": {"path": spec.adjudicatario_path, "query": condicao}},
        "aggs": {
            "partes": {
                "nested": {"path": spec.adjudicatario_path},
                "aggs": {
                    "casadas": {
                        "filter": condicao,
                        "aggs": {
                            "nifs": {
                                "terms": {"field": spec.adjudicatario_nif, "size": size},
                                "aggs": {
                                    "nome": {"top_hits": {"size": 1, "_source": [spec.adjudicatario_nome]}},
                                    "valor": {
                                        "reverse_nested": {},
                                        "aggs": {"s": {"sum": {"field": spec.value_field}}},
                                    },
                                },
                            }
                        },
                    }
                },
            }
        },
    }
    try:
        resp = _search(client, spec.index, body, timeout=90)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Pesquisa de empresa nos contratos falhou (%s).", exc)
        return []
    baldes = ((((resp.get("aggregations") or {}).get("partes") or {}).get("casadas") or {}).get("nifs") or {}).get(
        "buckets"
    ) or []
    return [
        {
            "nif": str(balde.get("key") or "").strip(),
            "nome": _top_hit_name(balde.get("nome")) or str(balde.get("key") or ""),
            "contratos": int(balde.get("doc_count") or 0),
            "valor": num(((balde.get("valor") or {}).get("s") or {}).get("value")),
            "papeis": ["adjudicatario"],
            "fonte": "contratos",
        }
        for balde in baldes
        if str(balde.get("key") or "").strip()
    ]


def _candidatos_contratos_es(client: Elasticsearch, spec: CountrySpec, *, texto: Optional[str], nif: Optional[str], size: int = 6) -> List[Dict[str, Any]]:
    """Empresas adjudicatárias no PLACSP (nome é `text`; NIF agrupado em maiúsculas)."""
    if nif:
        filtro: Dict[str, Any] = {"wildcard": {spec.adjudicatario_nif: {"value": nif, "case_insensitive": True}}}
    else:
        filtro = {"match": {spec.adjudicatario_nome: {"query": texto, "operator": "and"}}}
    body = {
        "size": 0,
        "track_total_hits": False,
        "query": filtro,
        "aggs": {
            "nifs": {
                "terms": {"field": spec.adjudicatario_nif, "size": 20},
                "aggs": {
                    "nome": {"top_hits": {"size": 3, "_source": [spec.adjudicatario_nome]}},
                    "valor": {"sum": {"field": spec.value_field}},
                },
            }
        },
    }
    resp = _search(client, spec.index, body, timeout=90)
    baldes = ((resp.get("aggregations") or {}).get("nifs") or {}).get("buckets") or []
    agrupado: Dict[str, Dict[str, Any]] = {}
    for balde in baldes:
        chave = str(balde.get("key") or "").strip()
        if not chave:
            continue
        registo = agrupado.setdefault(
            chave.upper(),
            {"nif": chave.upper(), "contratos": 0, "valor": 0.0, "nomes": Counter()},
        )
        registo["contratos"] += int(balde.get("doc_count") or 0)
        registo["valor"] += float(((balde.get("valor") or {}).get("value") or 0.0))
        for hit in ((balde.get("nome") or {}).get("hits") or {}).get("hits") or []:
            nome = (hit.get("_source") or {}).get(spec.adjudicatario_nome)
            if isinstance(nome, str) and nome.strip():
                registo["nomes"][nome.strip()] += int(balde.get("doc_count") or 0)
    candidatos = []
    for registo in sorted(agrupado.values(), key=lambda item: -(item.get("contratos") or 0))[:size]:
        nome = registo["nomes"].most_common(1)
        candidatos.append(
            {
                "nif": registo["nif"],
                "nome": nome[0][0] if nome else registo["nif"],
                "alias": [item[0] for item in registo["nomes"].most_common(4)[1:]],
                "contratos": registo["contratos"],
                "valor": num(registo["valor"]),
                "papeis": ["adjudicatario"],
                "fonte": "contratos",
            }
        )
    return candidatos


def _nome_contribuinte(client: Elasticsearch, nif: str) -> Optional[Dict[str, Any]]:
    """Ficha do cadastro para um NIF (nome, contratos, concelho)."""
    try:
        resp = _search(
            client,
            CONTRIBUINTES_INDEX,
            {"size": 1, "query": {"term": {"nif": nif}}, "_source": ["nif", "name", "names", "roles", "location", "contracts_count", "contracts_value"]},
            timeout=20,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cadastro indisponível para %s (%s).", nif, exc)
        return None
    hits = _hits(resp)
    if not hits:
        return None
    src = hits[0].get("_source") or {}
    local = src.get("location") if isinstance(src.get("location"), dict) else {}
    return {
        "nif": str(src.get("nif") or nif),
        "nome": src.get("name"),
        "alias": (src.get("names") or [])[:3],
        "papeis": list(src.get("roles") or []),
        "contratos": as_int(src.get("contracts_count")),
        "valor": num(src.get("contracts_value")),
        "concelho": local.get("concelho"),
    }


def resolver_empresa(
    query: str,
    *,
    pais: str = PAIS_DEFAULT,
    es: Optional[Elasticsearch] = None,
    size: int = 6,
) -> Dict[str, Any]:
    """Nome **ou** NIF → empresa(s) com contratos, para alimentar a análise.

    Ordem de resolução (PT): cadastro de contribuintes → nomes dentro dos
    contratos (`wildcard`); (ES): índice de contratos espanhol. Devolve sempre
    uma lista de candidatos: quem digita «psg» tem de escolher entre oito PSG.
    """
    spec = COUNTRIES.get(str(pais or "").upper())
    if spec is None:
        return {"error": f"país desconhecido: {pais}", "paises": list(COUNTRIES)}
    client = _client(es)
    if client is None:
        return {"error": "Elasticsearch indisponível"}
    texto = str(query or "").strip()
    if not texto:
        return {"error": "pesquisa vazia"}
    nif = _nif_puro(texto, spec)

    candidatos: List[Dict[str, Any]] = []
    if spec.key == "ES":
        candidatos = _candidatos_contratos_es(client, spec, texto=None if nif else texto, nif=nif)
    elif nif:
        ficha = _nome_contribuinte(client, nif)
        if ficha:
            candidatos = [{**ficha, "fonte": "cadastro"}]
        if not candidatos:
            candidatos = _candidatos_contratos_pt(client, spec, texto)
    else:
        candidatos = _candidatos_contribuintes(client, texto)
        if not candidatos:
            candidatos = _candidatos_contratos_pt(client, spec, texto)

    candidatos = [item for item in candidatos if item.get("nif")]
    if not candidatos:
        return {"error": "sem empresa para essa pesquisa", "query": texto, "candidatos": []}
    principal = candidatos[0]
    return {"pais": spec.key, "query": texto, "nif_detetado": bool(nif), **principal, "candidatos": candidatos[1 : size + 1]}


def _baselines_cpv(
    client: Elasticsearch,
    spec: CountrySpec,
    grupos: Sequence[str],
    *,
    ano_from: Optional[int],
    ano_to: Optional[int],
    size: int = 400,
) -> Dict[str, Dict[str, Any]]:
    """Régua de cada CPV (mediana/MAD do log do valor e taxas) na amostra.

    Serve para dizer se um contrato da empresa é atípico **para o seu setor** —
    sem isto, um contrato grande de obras seria sempre «anómalo».
    """
    saida: Dict[str, Dict[str, Any]] = {}
    for grupo in grupos:
        query = _base_query(spec, ano_from, ano_to, grupo)
        body = {
            "size": max(50, min(size, 1000)),
            "track_total_hits": False,
            "query": query,
            "sort": ["_doc"],
            "_source": list(spec.source_fields),
        }
        resp = _search(client, spec.index, body, timeout=90)
        linhas = [_row_from_hit(spec, hit) for hit in _hits(resp)]
        if not linhas:
            continue
        valores = [math.log10(row["valor"]) for row in linhas if row.get("valor") and row["valor"] > 0]
        ratios = [row["ratio_base"] for row in linhas if row.get("ratio_base") is not None]
        mediana_valor = median(valores)
        mad_valor = median([abs(valor - mediana_valor) for valor in valores]) if mediana_valor is not None else None
        saida[grupo] = {
            "contratos": len(linhas),
            "mediana_log_valor": mediana_valor,
            "mad_log_valor": mad_valor,
            "desvio_mediano": median(ratios),
            "taxa_ajuste_direto": sum(row.get("ajuste_direto") or 0 for row in linhas) / len(linhas),
            "taxa_aditivo": sum(1 for row in linhas if (row.get("ratio_efetivo") or 0) > 1.15) / len(linhas),
            "valor_mediano": median([row["valor"] for row in linhas if row.get("valor")]),
        }
    return saida


def _z_valor(valor: Optional[float], baseline: Optional[Dict[str, Any]]) -> float:
    """σ robusto do log do valor face ao CPV (0 quando não há régua)."""
    if not valor or valor <= 0 or not baseline:
        return 0.0
    mediana = baseline.get("mediana_log_valor")
    mad = baseline.get("mad_log_valor")
    if mediana is None:
        return 0.0
    escala = 1.4826 * mad if mad else 0.0
    if not escala or escala <= 1e-9:
        return 0.0
    return abs((math.log10(valor) - mediana) / escala)


def _agregar(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Agregados do portefólio de uma empresa."""
    valores = [row["valor"] for row in rows if row.get("valor")]
    por_ano: Dict[int, Dict[str, Any]] = {}
    por_cpv: Dict[str, Dict[str, Any]] = {}
    por_procedimento: Dict[str, Dict[str, Any]] = {}
    adjudicantes: Dict[str, Dict[str, Any]] = {}
    escaloes = {"<10k": 0, "10k-100k": 0, "100k-1M": 0, ">1M": 0}

    for row in rows:
        valor = row.get("valor") or 0.0
        ano = row.get("ano")
        if ano:
            entrada = por_ano.setdefault(int(ano), {"ano": int(ano), "contratos": 0, "valor": 0.0})
            entrada["contratos"] += 1
            entrada["valor"] += valor
        grupo = row.get("cpv_grupo") or "??"
        if grupo not in por_cpv:
            por_cpv[grupo] = {
                "cpv": grupo,
                "descricao": row.get("cpv_desc"),
                "contratos": 0,
                "valor": 0.0,
                "ajuste_direto": 0,
                "aditivos": 0,
                "ratios": [],
            }
        bloco = por_cpv[grupo]
        bloco["contratos"] += 1
        bloco["valor"] += valor
        bloco["ajuste_direto"] += 1 if row.get("ajuste_direto") else 0
        bloco["aditivos"] += 1 if (row.get("ratio_efetivo") or 0) > 1.15 else 0
        if row.get("ratio_base") is not None:
            bloco["ratios"].append(row["ratio_base"])

        procedimento = row.get("procedimento") or "—"
        proc = por_procedimento.setdefault(procedimento, {"procedimento": procedimento, "contratos": 0, "valor": 0.0})
        proc["contratos"] += 1
        proc["valor"] += valor

        chave = row.get("adjudicante_nif") or row.get("adjudicante_nome") or "?"
        adj = adjudicantes.setdefault(
            str(chave),
            {"nif": row.get("adjudicante_nif"), "nome": row.get("adjudicante_nome"), "contratos": 0, "valor": 0.0},
        )
        adj["contratos"] += 1
        adj["valor"] += valor

        if valor < 10_000:
            escaloes["<10k"] += 1
        elif valor < 100_000:
            escaloes["10k-100k"] += 1
        elif valor < 1_000_000:
            escaloes["100k-1M"] += 1
        else:
            escaloes[">1M"] += 1

    for bloco in por_cpv.values():
        bloco["desvio_mediano"] = num(median(bloco.pop("ratios")))
        bloco["taxa_ajuste_direto"] = num(bloco["ajuste_direto"] / bloco["contratos"]) if bloco["contratos"] else None
        bloco["taxa_aditivo"] = num(bloco["aditivos"] / bloco["contratos"]) if bloco["contratos"] else None
        bloco["valor"] = num(bloco["valor"])
        bloco["relevancia"] = num(bloco["valor"] or 0)

    valor_total = sum(valores)
    return {
        "por_ano": [por_ano[chave] for chave in sorted(por_ano)],
        "por_cpv": sorted(por_cpv.values(), key=lambda item: -(item["valor"] or 0))[:12],
        "por_procedimento": sorted(por_procedimento.values(), key=lambda item: -item["contratos"])[:10],
        "adjudicantes": sorted(adjudicantes.values(), key=lambda item: -(item["valor"] or 0))[:12],
        "escaloes": escaloes,
        "valor_total": num(valor_total),
        "valor_mediano": num(median(valores)),
        "concentracao_adjudicante": num(
            (max((item["valor"] for item in adjudicantes.values()), default=0.0) / valor_total) if valor_total else None
        ),
    }


def analise_empresa(
    *,
    nif: Optional[str] = None,
    nome: Optional[str] = None,
    pais: str = PAIS_DEFAULT,
    ano_from: Optional[int] = None,
    ano_to: Optional[int] = None,
    max_contratos: int = 400,
    per_year_baseline: int = 250,
    use_cache: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Análise de **uma empresa**: portefólio, CPV, regras cumpridas e relações.

    Aceita `nif` ou `nome` (o nome é resolvido para o NIF pelo cadastro/índice de
    contratos). As réguas por CPV (mediana/MAD) vêm de uma amostra do próprio
    CPV, para que «atípico» signifique atípico **no setor**.
    """
    spec = COUNTRIES.get(str(pais or "").upper())
    if spec is None:
        return {"error": f"país desconhecido: {pais}", "paises": list(COUNTRIES)}
    client = _client(es)
    if client is None:
        return {"error": "Elasticsearch indisponível"}

    candidatos: List[Dict[str, Any]] = []
    if not nif:
        resolvido = resolver_empresa(str(nome or ""), pais=spec.key, es=client)
        if resolvido.get("error"):
            return resolvido
        nif = resolvido["nif"]
        candidatos = resolvido.get("candidatos") or []
    nif = str(nif).strip()

    chave: Tuple[Any, ...] = (
        spec.key,
        nif,
        ano_from,
        ano_to,
        int(max_contratos),
        int(per_year_baseline),
    )
    if use_cache:
        guardado = _emp_cache_get(chave)
        if guardado is not None:
            saida = dict(guardado)
            saida["candidatos"] = candidatos or saida.get("candidatos") or []
            saida["cache"] = True
            return saida

    ficha = _nome_contribuinte(client, nif) if spec.key == "PT" else None

    filtros: List[Dict[str, Any]] = [_empresa_query(spec, nif)]
    if ano_from is not None or ano_to is not None:
        rng: Dict[str, Any] = {}
        if ano_from is not None:
            rng["gte"] = int(ano_from)
        if ano_to is not None:
            rng["lte"] = int(ano_to)
        filtros.append({"range": {spec.year_field: rng}})
    query = {"bool": {"filter": filtros}}

    body = {
        "size": max(10, min(max_contratos, 2000)),
        "track_total_hits": True,
        "query": query,
        "sort": [{spec.pub_date: {"order": "desc", "unmapped_type": "date"}}],
        "_source": list(spec.source_fields),
    }
    resp = _search(client, spec.index, body, timeout=120)
    total = ((resp.get("hits") or {}).get("total") or {}).get("value")
    rows = [_row_from_hit(spec, hit) for hit in _hits(resp)]
    if not rows:
        return {"error": "sem contratos para esta empresa", "nif": nif, "pais": spec.key}

    nome_empresa = (ficha or {}).get("nome")
    if not nome_empresa:
        for row in rows:
            for party in row.get("adjudicatarios") or []:
                if str(party.get("nif")) == nif and party.get("nome"):
                    nome_empresa = party["nome"]
                    break
            if nome_empresa:
                break

    # -- réguas do setor (por CPV) e baseline global -------------------------
    grupos = [row.get("cpv_grupo") for row in rows if row.get("cpv_grupo")]
    principais = [grupo for grupo, _ in Counter(grupos).most_common(6)]
    baselines = _baselines_cpv(client, spec, principais, ano_from=ano_from, ano_to=ano_to)
    base = analyze(pais=spec.key, ano_from=ano_from, ano_to=ano_to, per_year=per_year_baseline, use_cache=True)
    global_ad = (base.get("overview") or {}).get("taxa_ajuste_direto")
    cpv_metricas = {item["cpv"]: item for item in base.get("cpvs") or []}

    # -- regras aplicadas aos contratos desta empresa -----------------------
    regras_ativas = regras.regras_ativas()
    contratos: List[Dict[str, Any]] = []
    contagem: Dict[str, int] = {}
    for row in rows:
        grupo = row.get("cpv_grupo") or ""
        regua = baselines.get(grupo) or {}
        global_cpv = cpv_metricas.get(grupo) or {}
        z = _z_valor(row.get("valor"), regua)
        contexto = _contexto_regras(
            row,
            z=z,
            taxa_ajuste_direto_cpv=regua.get("taxa_ajuste_direto"),
            taxa_aditivo_cpv=regua.get("taxa_aditivo"),
            taxa_ajuste_direto_global=(global_cpv.get("taxa_ajuste_direto") or global_ad),
            contratos_do_cpv=regua.get("contratos"),
        )
        hits = regras.avaliar(contexto, regras_ativas)
        for hit in hits:
            contagem[str(hit.get("padrao"))] = contagem.get(str(hit.get("padrao")), 0) + 1
        contratos.append(
            {
                "id": row.get("id"),
                "ano": row.get("ano"),
                "data_publicacao": row.get("data_publicacao"),
                "objeto": row.get("objeto"),
                "valor": num(row.get("valor")),
                "preco_base": num(row.get("base")),
                "valor_efetivo": num(row.get("efetivo")),
                "ratio_base": num(row.get("ratio_base")),
                "ratio_efetivo": num(row.get("ratio_efetivo")),
                "procedimento": row.get("procedimento"),
                "ajuste_direto": bool(row.get("ajuste_direto")),
                "cpv": row.get("cpv"),
                "cpv_grupo": row.get("cpv_grupo"),
                "cpv_desc": row.get("cpv_desc"),
                "n_concorrentes": row.get("n_concorrentes"),
                "dias_decisao": row.get("dias_decisao"),
                "dias_assinatura": row.get("dias_assinatura"),
                "dias_publicacao": row.get("dias_publicacao"),
                "adjudicante": row.get("adjudicante_nome"),
                "adjudicante_nif": row.get("adjudicante_nif"),
                "z_cpv": num(z),
                "severidade": severidade_de(hits),
                "razoes": hits,
            }
        )
    contratos.sort(key=lambda item: (_SEVERIDADE_ORDEM.get(str(item.get("severidade")), 9), -(item.get("valor") or 0)))

    reguas_resumo = [
        {"cpv": grupo, **{chave: num(valor) if isinstance(valor, float) else valor for chave, valor in regua.items()}}
        for grupo, regua in baselines.items()
    ]

    # -- relações: quem mais ganha aos mesmos adjudicantes ------------------
    agregados = _agregar(rows)
    top_adjudicantes = [item for item in agregados["adjudicantes"][:5] if item.get("nif")]
    pares: Dict[str, Dict[str, Any]] = {}
    for adjudicante in top_adjudicantes:
        pares.update(_pares_no_adjudicante(client, spec, str(adjudicante["nif"]), nif, excluir=set(pares)))
    relacoes_empresas = sorted(pares.values(), key=lambda item: -(item.get("contratos") or 0))[:15]

    pessoas = _pessoas_da_empresa(client, nif)
    cargos_sociais = [
        person for person in pessoas if any(str(cargo.get("role_org") or "") in CARGO_GESTAO_ORGS for cargo in person["cargos"])
    ]
    insolvencias = _insolvencias_da_empresa(client, nif)
    alvo_noticias = nome_empresa or nif
    curto = _nome_curto(alvo_noticias)
    nomes_noticias = [(alvo_noticias, alvo_noticias)]
    if curto:
        nomes_noticias.append((alvo_noticias, curto))
    noticias = _news_for(client, nomes_noticias, per_name=6)

    sinais = []
    for regra in regras_ativas:
        identificador = str(regra.get("id"))
        quantidade = contagem.get(identificador, 0)
        if not quantidade:
            continue
        sinais.append(
            {
                "padrao": identificador,
                "label": regra.get("label"),
                "severidade": regra.get("severidade"),
                "descricao": regra.get("descricao"),
                "contratos": quantidade,
                "taxa": num(quantidade / len(contratos)),
                "exemplos": [
                    {
                        "id": item["id"],
                        "objeto": item["objeto"],
                        "ano": item["ano"],
                        "valor": item["valor"],
                        "detalhe": next((hit["detalhe"] for hit in item["razoes"] if hit.get("padrao") == identificador), None),
                    }
                    for item in contratos
                    if any(hit.get("padrao") == identificador for hit in item["razoes"])
                ][:3],
            }
        )
    sinais.sort(key=lambda item: (_SEVERIDADE_ORDEM.get(str(item.get("severidade")), 9), -item["contratos"]))

    anos = sorted({row["ano"] for row in rows if row.get("ano")})
    payload = {
        "pais": spec.key,
        "pais_label": spec.label,
        "nif": nif,
        "nome": nome_empresa or nif,
        "candidatos": candidatos,
        "ficha": ficha,
        "filtros": {"ano_from": ano_from, "ano_to": ano_to},
        "contratos_total": int(total or len(rows)),
        "contratos_analisados": len(rows),
        "anos": [anos[0], anos[-1]] if anos else None,
        "resumo": {
            **{chave: agregados[chave] for chave in ("valor_total", "valor_mediano", "escaloes", "concentracao_adjudicante")},
            "contratos": len(rows),
            "taxa_ajuste_direto": num(sum(1 for row in rows if row.get("ajuste_direto")) / len(rows)),
            "taxa_aditivo": num(sum(1 for row in rows if (row.get("ratio_efetivo") or 0) > 1.15) / len(rows)),
            "desvio_mediano": num(median([row["ratio_base"] for row in rows if row.get("ratio_base") is not None])),
            "adjudicantes_distintos": len({row.get("adjudicante_nif") or row.get("adjudicante_nome") for row in rows}),
            "cpvs": len({row.get("cpv_grupo") for row in rows if row.get("cpv_grupo")}),
            "contratos_com_sinais": sum(1 for item in contratos if item["razoes"]),
            "contratos_atipicos_cpv": sum(1 for item in contratos if (item.get("z_cpv") or 0) > 3.5),
            "insolvente": bool(insolvencias),
        },
        "por_ano": agregados["por_ano"],
        "por_cpv": agregados["por_cpv"],
        "por_procedimento": agregados["por_procedimento"],
        "adjudicantes": agregados["adjudicantes"],
        "sinais": sinais,
        "contratos": contratos,
        "reguas_cpv": reguas_resumo,
        "relacoes": {
            "empresas": relacoes_empresas,
            "cargos_sociais": cargos_sociais,
            "intervenientes_cire": [person for person in pessoas if person not in cargos_sociais][:15],
            "insolvencias": insolvencias,
            "noticias": noticias,
        },
        "regras_ativas": regras.resumo_regras(regras_ativas),
        "aviso": (
            "Análise a partir de uma amostra dos contratos desta empresa (até "
            f"{len(rows)} de {int(total or len(rows))}). As réguas por CPV vêm de uma amostra do próprio setor."
        ),
    }
    if use_cache:
        _emp_cache_put(chave, payload)
    return payload


def _pares_no_adjudicante(
    client: Elasticsearch,
    spec: CountrySpec,
    adjudicante_nif: str,
    empresa_nif: str,
    *,
    excluir: Optional[set] = None,
) -> Dict[str, Dict[str, Any]]:
    """Outras empresas que ganharam ao mesmo adjudicante (relação observada)."""
    if spec.key == "PT":
        query: Dict[str, Any] = {
            "nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": adjudicante_nif}}}
        }
        aggs = {
            "partes": {
                "nested": {"path": "adjudicatarios.parsed"},
                "aggs": {
                    "nifs": {
                        "terms": {"field": "adjudicatarios.parsed.nif", "size": 30},
                        "aggs": {
                            "nome": {"top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}},
                            "valor": {"reverse_nested": {}, "aggs": {"s": {"sum": {"field": "precoContratual"}}}},
                        },
                    }
                },
            }
        }
    else:
        query = {"term": {"organo_id": adjudicante_nif}}
        aggs = {
            "nifs": {
                "terms": {"field": "adjudicatario_nif", "size": 30},
                "aggs": {
                    "nome": {"top_hits": {"size": 1, "_source": ["adjudicatario_nombre"]}},
                    "valor": {"sum": {"field": "valor_adjudicado"}},
                },
            }
        }
    resp = _search(client, spec.index, {"size": 0, "query": query, "aggs": aggs}, timeout=90)
    aggs_resp = resp.get("aggregations") or {}
    buckets = (aggs_resp.get("partes") or aggs_resp).get("nifs", {}).get("buckets") if spec.key == "PT" else aggs_resp.get("nifs", {}).get("buckets")
    saida: Dict[str, Dict[str, Any]] = {}
    for bucket in buckets or []:
        outro = str(bucket.get("key") or "").strip()
        if not outro or outro == empresa_nif or (excluir and outro in excluir):
            continue
        saida[outro] = {
            "nif": outro,
            "nome": _top_hit_name(bucket.get("nome")),
            "adjudicante": adjudicante_nif,
            "contratos": int(bucket.get("doc_count") or 0),
            "valor": num(((bucket.get("valor") or {}).get("s") or {}).get("value") or (bucket.get("valor") or {}).get("value")),
        }
    return saida


def _pessoas_da_empresa(client: Elasticsearch, nif: str) -> List[Dict[str, Any]]:
    body = {
        "size": 40,
        "track_total_hits": False,
        "_source": ["nif", "name", "roles"],
        "query": {"nested": {"path": "roles", "query": {"term": {"roles.company_nif": nif}}}},
    }
    pessoas: List[Dict[str, Any]] = []
    for hit in _hits(_search(client, PEOPLE_INDEX, body, timeout=45)):
        src = hit.get("_source") or {}
        cargos = [
            {
                "role": cargo.get("role"),
                "role_org": cargo.get("role_org"),
                "acto": cargo.get("acto"),
                "data": cargo.get("date"),
            }
            for cargo in (src.get("roles") or [])
            if isinstance(cargo, dict) and str(cargo.get("company_nif") or "") == nif
        ][:10]
        if cargos:
            pessoas.append({"nif": src.get("nif"), "nome": src.get("name"), "cargos": cargos})
    return pessoas


def _insolvencias_da_empresa(client: Elasticsearch, nif: str) -> List[Dict[str, Any]]:
    body = {
        "size": 20,
        "track_total_hits": False,
        "_source": ["insolvente", "especie", "ato", "data_publicacao", "tribunal", "processo_numero"],
        "query": {"terms": {"nifs": [nif]}},
    }
    saida: List[Dict[str, Any]] = []
    for hit in _hits(_search(client, CIRE_INDEX, body, timeout=45)):
        src = hit.get("_source") or {}
        saida.append(
            {
                "especie": src.get("especie"),
                "ato": src.get("ato"),
                "data": src.get("data_publicacao"),
                "tribunal": src.get("tribunal"),
                "processo": src.get("processo_numero"),
            }
        )
    return saida


# ---------------------------------------------------------------------------
# 10. Análise de **várias empresas** (comparação, cruzamentos e rede)
# ---------------------------------------------------------------------------
#: Quantas empresas se podem comparar de uma vez. Cada empresa custa as suas
#: consultas (contratos + réguas por CPV), pelo que o teto é explícito.
MAX_EMPRESAS_CONJUNTO = 12
#: Contratos lidos por empresa no modo de comparação (o detalhe é o do dossiê).
CONTRATOS_POR_EMPRESA = 120


def _severidade_de_sinais(sinais: Sequence[Dict[str, Any]]) -> Optional[str]:
    valores = [str(sinal.get("severidade") or "") for sinal in sinais]
    return severidade_de([{"severidade": valor} for valor in valores if valor])


def _linha_conjunto(analise: Dict[str, Any], *, top_adjudicantes: int = 12, top_cpv: int = 6) -> Dict[str, Any]:
    """Uma linha comparável por empresa (sem os contratos, que pesam muito).

    A comparação precisa de números alinhados: contratos, valor, desvio mediano,
    ajuste direto, aditivos, adjudicantes, concentração e contagem de sinais. O
    detalhe por contrato fica no dossiê — aqui não se copiam 300 contratos por
    empresa para a resposta.
    """
    resumo = analise.get("resumo") or {}
    sinais = [
        {
            "padrao": sinal.get("padrao"),
            "label": sinal.get("label"),
            "severidade": sinal.get("severidade"),
            "contratos": sinal.get("contratos"),
            "taxa": sinal.get("taxa"),
            "exemplo": ((sinal.get("exemplos") or [{}])[0].get("objeto") if sinal.get("exemplos") else None),
            "detalhe": ((sinal.get("exemplos") or [{}])[0].get("detalhe") if sinal.get("exemplos") else None),
        }
        for sinal in analise.get("sinais") or []
    ]
    relacoes = analise.get("relacoes") or {}
    return {
        "nif": analise.get("nif"),
        "nome": analise.get("nome"),
        "pais": analise.get("pais"),
        "pais_label": analise.get("pais_label"),
        "ficha": analise.get("ficha"),
        "anos": analise.get("anos"),
        "contratos_total": analise.get("contratos_total"),
        "contratos_analisados": analise.get("contratos_analisados"),
        "resumo": {
            "contratos": resumo.get("contratos"),
            "valor_total": resumo.get("valor_total"),
            "valor_mediano": resumo.get("valor_mediano"),
            "desvio_mediano": resumo.get("desvio_mediano"),
            "taxa_ajuste_direto": resumo.get("taxa_ajuste_direto"),
            "taxa_aditivo": resumo.get("taxa_aditivo"),
            "adjudicantes_distintos": resumo.get("adjudicantes_distintos"),
            "concentracao_adjudicante": resumo.get("concentracao_adjudicante"),
            "contratos_com_sinais": resumo.get("contratos_com_sinais"),
            "contratos_atipicos_cpv": resumo.get("contratos_atipicos_cpv"),
            "insolvente": bool(resumo.get("insolvente")),
        },
        "severidade": _severidade_de_sinais(sinais),
        "sinais": sinais,
        "adjudicantes": (analise.get("adjudicantes") or [])[:top_adjudicantes],
        "por_cpv": (analise.get("por_cpv") or [])[:top_cpv],
        "por_procedimento": (analise.get("por_procedimento") or [])[:5],
        "por_ano": analise.get("por_ano") or [],
        "relacoes": {
            "cargos_sociais": relacoes.get("cargos_sociais") or [],
            "insolvencias": relacoes.get("insolvencias") or [],
            "noticias": (relacoes.get("noticias") or [])[:8],
            "empresas": (relacoes.get("empresas") or [])[:10],
        },
        "aviso": analise.get("aviso"),
        "erro": None,
    }


def _cruzamentos(linhas: Sequence[Dict[str, Any]], *, minimo: int = 2) -> Dict[str, Any]:
    """Onde é que as empresas do conjunto se tocam.

    Três perguntas concretas, todas sobre dados já presentes nas linhas:

    - **adjudicantes comuns** — vendem ao mesmo comprador (concorrência no mesmo
      cliente, o que pode ser normal ou não);
    - **pessoas comuns** — o mesmo gerente em duas empresas do conjunto (ligação
      societária que o grafo de uma só empresa não mostra);
    - **processos comuns** — as duas aparecem no mesmo processo do CIRE.

    Só se devolvem ligações com **duas ou mais** empresas: o que se cruza com uma
    só não é um cruzamento.
    """
    adjudicantes: Dict[str, Dict[str, Any]] = {}
    pessoas: Dict[str, Dict[str, Any]] = {}
    processos: Dict[str, Dict[str, Any]] = {}
    cpvs: Dict[str, Dict[str, Any]] = {}
    proprietarios = {str(linha.get("nif")): linha for linha in linhas if linha.get("nif")}

    def _marca(alvo: Dict[str, Any], nif: str) -> None:
        empresas = alvo.setdefault("empresas", [])
        if nif not in empresas:
            empresas.append(nif)

    for linha in linhas:
        nif = str(linha.get("nif") or "")
        if not nif:
            continue
        for adjudicante in linha.get("adjudicantes") or []:
            chave = str(adjudicante.get("nif") or adjudicante.get("nome") or "")
            if not chave:
                continue
            registo = adjudicantes.setdefault(
                chave,
                {
                    "nif": adjudicante.get("nif"),
                    "nome": adjudicante.get("nome") or chave,
                    "empresas": [],
                    "contratos": 0,
                    "valor": 0.0,
                },
            )
            _marca(registo, nif)
            registo["contratos"] += int(adjudicante.get("contratos") or 0)
            registo["valor"] += float(adjudicante.get("valor") or 0.0)

        for pessoa in (linha.get("relacoes") or {}).get("cargos_sociais") or []:
            chave = str(pessoa.get("nif") or pessoa.get("nome") or "")
            if not chave:
                continue
            registo = pessoas.setdefault(
                chave,
                {"nif": pessoa.get("nif"), "nome": pessoa.get("nome") or chave, "empresas": [], "cargos": []},
            )
            _marca(registo, nif)
            for cargo in pessoa.get("cargos") or []:
                papel = str(cargo.get("role_org") or cargo.get("role") or "").strip()
                if papel and papel not in registo["cargos"]:
                    registo["cargos"].append(papel)

        for processo in (linha.get("relacoes") or {}).get("insolvencias") or []:
            chave = str(processo.get("processo") or f"{processo.get('especie')}-{processo.get('data')}")
            registo = processos.setdefault(
                chave,
                {
                    "processo": processo.get("processo"),
                    "especie": processo.get("especie"),
                    "tribunal": processo.get("tribunal"),
                    "data": processo.get("data"),
                    "empresas": [],
                },
            )
            _marca(registo, nif)

        for cpv in linha.get("por_cpv") or []:
            chave = str(cpv.get("cpv") or "")
            if not chave:
                continue
            registo = cpvs.setdefault(
                chave,
                {"cpv": chave, "descricao": cpv.get("descricao"), "empresas": [], "contratos": 0, "valor": 0.0},
            )
            _marca(registo, nif)
            registo["contratos"] += int(cpv.get("contratos") or 0)
            registo["valor"] += float(cpv.get("valor") or 0.0)

    def _nome(nif: str) -> str:
        return str((proprietarios.get(nif) or {}).get("nome") or nif)

    def _empacotar(registo: Dict[str, Any]) -> Dict[str, Any]:
        registo["empresas_nome"] = [_nome(nif) for nif in registo["empresas"]]
        registo["n_empresas"] = len(registo["empresas"])
        registo["valor"] = num(registo.get("valor"))
        return registo

    comuns = lambda mapa: [  # noqa: E731 - a regra de corte é a mesma para os quatro mapas
        _empacotar(registo) for registo in mapa.values() if len(registo.get("empresas") or []) >= minimo
    ]
    return {
        "adjudicantes": sorted(comuns(adjudicantes), key=lambda item: (-item["n_empresas"], -(item["valor"] or 0)))[:40],
        "pessoas": sorted(comuns(pessoas), key=lambda item: -item["n_empresas"])[:40],
        "processos": sorted(comuns(processos), key=lambda item: -item["n_empresas"])[:40],
        "cpvs": sorted(comuns(cpvs), key=lambda item: (-item["n_empresas"], -(item["valor"] or 0)))[:40],
    }


def _grafo_conjunto(
    linhas: Sequence[Dict[str, Any]],
    cruzamentos: Dict[str, Any],
    *,
    max_adjudicantes: int = 18,
    max_pessoas: int = 12,
    max_processos: int = 8,
    max_cpvs: int = 10,
) -> Dict[str, Any]:
    """Rede do conjunto: as empresas ligadas pelo comprador, pelo mercado, pelo gerente e pelo processo.

    Responde à pergunta que motiva a comparação — **como é que estas empresas se
    ligam entre si?** — e mostra também *com quem cada uma contata*:

    - **CPV comum** (lilás): competem no mesmo mercado;
    - **adjudicante** (verde): o mesmo comprador, ou o maior comprador de cada uma;
    - **pessoa** (rosa): o mesmo gerente em duas empresas do conjunto;
    - **processo** (azul): as duas aparecem no mesmo processo do CIRE.

    As ligações partilhadas aparecem primeiro e dizem quantas empresas tocam; os
    nós extra (compradores individuais) existem para o grafo não ficar vazio
    quando as empresas não se cruzam em nada.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    ids: set = set()

    for linha in linhas:
        nif = str(linha.get("nif") or "")
        if not nif:
            continue
        resumo = linha.get("resumo") or {}
        no = f"empresa:{nif}"
        ids.add(no)
        nodes.append(
            {
                "id": no,
                "key": nif,
                "label": linha.get("nome") or nif,
                "dimension": "empresa",
                "type": "entidade",
                "role": "empresa comparada",
                "count": int(linha.get("contratos_analisados") or 0),
                "total_value": float(resumo.get("valor_total") or 0.0),
            }
        )

    def _acrescentar(prefixo: str, chave: str, rotulo: str, tipo: str, papel: str, dimensao: str, *, count: int = 1, valor: float = 0.0) -> str:
        no = f"{prefixo}:{chave}"
        if no not in ids:
            ids.add(no)
            nodes.append(
                {
                    "id": no,
                    "key": chave,
                    "label": rotulo,
                    "dimension": dimensao,
                    "type": tipo,
                    "role": papel[:80],
                    "count": count,
                    "total_value": float(valor or 0.0),
                }
            )
        return no

    # Mercado partilhado: o mesmo CPV em duas ou mais empresas do conjunto.
    for item in (cruzamentos.get("cpvs") or [])[:max_cpvs]:
        chave = str(item.get("cpv"))
        no = _acrescentar(
            "cpv",
            chave,
            f"CPV {chave}",
            "cpv",
            f"{(item.get('descricao') or 'mercado')[:60]} · {item['n_empresas']} empresas",
            "cpv",
            count=int(item.get("contratos") or 0),
            valor=item.get("valor") or 0.0,
        )
        for linha in linhas:
            nif = str(linha.get("nif") or "")
            meu = next((cpv for cpv in linha.get("por_cpv") or [] if str(cpv.get("cpv")) == chave), None)
            if not meu:
                continue
            edges.append(
                {
                    "source": f"empresa:{nif}",
                    "target": no,
                    "count": int(meu.get("contratos") or 0),
                    "value": float(meu.get("valor") or 0.0),
                }
            )

    # Compradores partilhados (primeiro) e, se sobrar espaço, os maiores de cada uma.
    usados: set = set()
    for item in cruzamentos.get("adjudicantes") or []:
        if len(usados) >= max_adjudicantes:
            break
        chave = str(item.get("nif") or item.get("nome"))
        usados.add(chave)
        no = _acrescentar(
            "adjudicante",
            chave,
            item.get("nome") or chave,
            "entidade",
            f"compra a {item['n_empresas']} empresas do conjunto",
            "adjudicante",
            count=int(item.get("contratos") or 0),
            valor=item.get("valor") or 0.0,
        )
        for nif in item["empresas"]:
            edges.append({"source": f"empresa:{nif}", "target": no, "count": int(item.get("contratos") or 0), "value": float(item.get("valor") or 0.0)})

    for linha in linhas:
        nif = str(linha.get("nif") or "")
        for adjudicante in (linha.get("adjudicantes") or [])[:4]:
            if len(usados) >= max_adjudicantes:
                break
            chave = str(adjudicante.get("nif") or adjudicante.get("nome") or "")
            if not chave or chave in usados:
                continue
            usados.add(chave)
            no = _acrescentar(
                "adjudicante",
                chave,
                adjudicante.get("nome") or chave,
                "entidade",
                "comprador",
                "adjudicante",
                count=int(adjudicante.get("contratos") or 0),
                valor=adjudicante.get("valor") or 0.0,
            )
            edges.append(
                {
                    "source": f"empresa:{nif}",
                    "target": no,
                    "count": int(adjudicante.get("contratos") or 0),
                    "value": float(adjudicante.get("valor") or 0.0),
                }
            )

    for item in (cruzamentos.get("pessoas") or [])[:max_pessoas]:
        chave = str(item.get("nif") or item.get("nome"))
        no = _acrescentar(
            "pessoa",
            chave,
            item.get("nome") or chave,
            "pessoa",
            f"{', '.join(item.get('cargos') or []) or 'órgão social'} · {item['n_empresas']} empresas",
            "pessoa",
            count=len(item["empresas"]),
        )
        for nif in item["empresas"]:
            edges.append({"source": no, "target": f"empresa:{nif}", "count": 1, "value": 0.0})

    for item in (cruzamentos.get("processos") or [])[:max_processos]:
        chave = str(item.get("processo") or item.get("especie"))
        no = _acrescentar(
            "cire",
            chave,
            item.get("especie") or "processo CIRE",
            "processo",
            f"{item.get('tribunal') or 'tribunal'} · {str(item.get('data') or '')[:10]}",
            "cire",
        )
        for nif in item["empresas"]:
            edges.append({"source": f"empresa:{nif}", "target": no, "count": 1, "value": 0.0})

    n_nodes = len(nodes)
    n_edges = len(edges)
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "dimension_a": "empresa",
            "dimension_b": None,
            "metric": "valor",
            "mode": "relations",
            "complete": False,
            "scan_capped": True,
            "sample_order": "empresas escolhidas pelo utilizador",
            "sample_limit": len(linhas),
            "documents_scanned": sum(int(linha.get("contratos_analisados") or 0) for linha in linhas),
            "documents_matching": sum(int(linha.get("contratos_analisados") or 0) for linha in linhas),
            "scanned_value": num(sum(float((linha.get("resumo") or {}).get("valor_total") or 0.0) for linha in linhas)) or 0.0,
            "nodes_total": n_nodes,
            "edges_total": n_edges,
            "kept_nodes": n_nodes,
            "kept_edges": n_edges,
            "omitted_edges": 0,
            "coverage_value_share": None,
            "coverage_count_share": None,
            "directed": True,
            "limits": {"empresas": len(linhas), "adjudicantes_comuns": len(cruzamentos.get("adjudicantes") or [])},
            "notes": [
                "Rede das empresas comparadas: liga-as pelo comprador, pelo gerente e pelo processo.",
                "Só aparecem adjudicantes, pessoas e processos partilhados por duas ou mais empresas do conjunto.",
            ],
            "filters": {},
        },
    }


def analise_empresas(
    *,
    nifs: Optional[Sequence[str]] = None,
    nomes: Optional[Sequence[str]] = None,
    pais: str = PAIS_DEFAULT,
    ano_from: Optional[int] = None,
    ano_to: Optional[int] = None,
    max_contratos: int = CONTRATOS_POR_EMPRESA,
    max_empresas: int = 6,
    per_year_baseline: int = 250,
    use_cache: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Compara **várias empresas**: números alinhados, cruzamentos e rede.

    Cada empresa corre a análise normal (`analise_empresa`, com cache), mas a
    resposta devolve só o que serve para comparar — as linhas, os cruzamentos
    (adjudicantes, pessoas e processos partilhados), a distribuição por CPV e o
    grafo do conjunto. Os contratos ficam de fora: estão no dossiê de cada uma.
    """
    spec = COUNTRIES.get(str(pais or "").upper())
    if spec is None:
        return {"error": f"país desconhecido: {pais}", "paises": list(COUNTRIES)}
    client = _client(es)
    if client is None:
        return {"error": "Elasticsearch indisponível"}

    pedidos: List[Dict[str, Optional[str]]] = []
    for valor in list(nifs or []) + list(nomes or []):
        texto = str(valor or "").strip()
        if not texto:
            continue
        chave = _nif_puro(texto, spec)
        pedido = {"nif": chave, "nome": None if chave else texto}
        if pedido not in pedidos:
            pedidos.append(pedido)
    if not pedidos:
        return {"error": "sem empresas para comparar"}
    limite = max(2, min(int(max_empresas or 6), MAX_EMPRESAS_CONJUNTO))
    if len(pedidos) > limite:
        pedidos = pedidos[:limite]

    linhas: List[Dict[str, Any]] = []
    avisos: List[str] = []
    for pedido in pedidos:
        analise = analise_empresa(
            nif=pedido.get("nif"),
            nome=pedido.get("nome"),
            pais=spec.key,
            ano_from=ano_from,
            ano_to=ano_to,
            max_contratos=max_contratos,
            per_year_baseline=per_year_baseline,
            use_cache=use_cache,
            es=client,
        )
        if analise.get("error"):
            rotulo = pedido.get("nif") or pedido.get("nome") or "?"
            avisos.append(f"{rotulo}: {analise['error']}")
            continue
        linhas.append(_linha_conjunto(analise))

    if not linhas:
        return {"error": "nenhuma das empresas foi analisada", "avisos": avisos, "pais": spec.key}

    cruzamentos = _cruzamentos(linhas)
    grafo = _grafo_conjunto(linhas, cruzamentos)

    # Distribuição por CPV do conjunto (soma dos top de cada empresa).
    por_cpv: Dict[str, Dict[str, Any]] = {}
    for linha in linhas:
        for cpv in linha.get("por_cpv") or []:
            chave = str(cpv.get("cpv") or "")
            registo = por_cpv.setdefault(
                chave,
                {"cpv": chave, "descricao": cpv.get("descricao"), "contratos": 0, "valor": 0.0, "empresas": 0},
            )
            registo["contratos"] += int(cpv.get("contratos") or 0)
            registo["valor"] += float(cpv.get("valor") or 0.0)
            registo["empresas"] += 1

    valor_total = sum(float((linha.get("resumo") or {}).get("valor_total") or 0.0) for linha in linhas)
    contratos_total = sum(int((linha.get("resumo") or {}).get("contratos") or 0) for linha in linhas)
    return {
        "pais": spec.key,
        "pais_label": spec.label,
        "filtros": {"ano_from": ano_from, "ano_to": ano_to, "max_contratos": max_contratos},
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "empresas": linhas,
        "totais": {
            "empresas": len(linhas),
            "empresas_pedidas": len(pedidos),
            "contratos": contratos_total,
            "contratos_total_portal": sum(int(linha.get("contratos_total") or 0) for linha in linhas),
            "valor_total": num(valor_total),
            "valor_mediano": num(median([float((linha.get("resumo") or {}).get("valor_total") or 0.0) for linha in linhas])),
            "insolventes": sum(1 for linha in linhas if (linha.get("resumo") or {}).get("insolvente")),
            "com_sinais": sum(1 for linha in linhas if (linha.get("resumo") or {}).get("contratos_com_sinais")),
            "adjudicantes_comuns": len(cruzamentos["adjudicantes"]),
            "pessoas_comuns": len(cruzamentos["pessoas"]),
            "processos_comuns": len(cruzamentos["processos"]),
            "cpvs_comuns": len(cruzamentos["cpvs"]),
        },
        "cruzamentos": cruzamentos,
        "por_cpv": [
            {**item, "valor": num(item["valor"])}
            for item in sorted(por_cpv.values(), key=lambda item: -(item.get("valor") or 0.0))[:15]
        ],
        "grafo": grafo,
        "avisos": avisos,
        "aviso": (
            "Comparação a partir de uma amostra dos contratos de cada empresa. Os cruzamentos usam apenas "
            "adjudicantes, cargos de órgãos sociais e processos do CIRE presentes nessas amostras."
        ),
    }
