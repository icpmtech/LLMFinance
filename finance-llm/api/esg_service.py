"""Motor **ESG** por empresa — score, evolução, pares e carteira de fornecedores.

O módulo não inventa indicadores que não tem. Cada componente do score diz de
onde vem, quanto pesa e se está disponível; o global renormaliza pelos
componentes que existem e devolve a **cobertura** e a **confiança**. Sem
contratos nem indicadores declarados, o score é `None` (não é zero).

Camadas:

1. **Dados abertos da plataforma** — contratos do Portal BASE/PLACSP (CPV,
   procedimento, concorrentes, prazos e ``ContratEcologico``), cadastro de
   contribuintes (NIF, país, localização, dívida pública), registo de entidades
   (CAE) e CIRE (insolvências).
2. **Indicadores declarados** — relatórios de sustentabilidade ingeridos em
   ``finance_esg_indicadores`` (GRI/ESRS), normalizados por um catálogo com
   direção e limiares. São a única forma de medir emissões, formação, acidentes,
   diversidade do conselho, etc.; sem eles, esses componentes ficam
   indisponíveis e a cobertura di-lo.
3. **Benchmark de pares** — percentil e medianas face ao mesmo setor (secção
   CAE) e à mesma dimensão de carteira, calculados sobre as fotografias já
   guardadas em ``finance_esg_empresas``.
4. **Carteira de fornecedores** — distribuição dos fornecedores de um
   comprador pelos níveis ESG, com o valor imputado e os sinais de cada um.

Tudo é defensivo: sem Elasticsearch devolve ``{"error": ...}``; uma falha de
uma fonte não derruba as restantes.
"""
from __future__ import annotations

import csv
import io
import logging
import math
import re
import threading
import time
import uuid
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from api import esg_sources as tax
from api import esg_taxonomy as tax_eu
from api import padroes_service as padroes
from api.elasticsearch_client import (
    CIRE_INDEX,
    CONTRIBUINTES_INDEX,
    ENTITIES_INDEX,
    ESG_EMPRESAS_INDEX,
    ESG_INDICADORES_INDEX,
    ESG_RECOLHAS_INDEX,
    FIRMAS_INDEX,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 900
MAX_CONTRATOS = 1_000
MAX_CONTRATOS_ANO = 400
MAX_FORNECEDORES = 400
MIN_INDICADORES_CONFIANCA = 3

_CACHE: Dict[Tuple[Any, ...], Tuple[float, Dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()
_INDICES_GARANTIDOS = False
_INDICES_LOCK = threading.Lock()

#: Serviços que contam como ambientais/economia circular na taxonomia CPV.
SERVICOS_AMBIENTAIS = frozenset({1, 2, 3, 41, 65, 71, 73, 77, 90, 91})

#: Valores que o cadastro guarda em `location.distrito` quando não sabe o
#: distrito. Não são regiões: o mapa não os pode posicionar.
DISTRITOS_NAO_GEOGRAFICOS = frozenset(
    padroes.fold(valor) for valor in ("Portugal", "Portugal Continental", "Portugal Insular")
)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def _to_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        numero = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numero):
        return None
    return numero


def _to_int(value: Any) -> Optional[int]:
    numero = _to_float(value)
    return None if numero is None else int(round(numero))


def _median(values: Sequence[Optional[float]]) -> Optional[float]:
    limpos = sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    if not limpos:
        return None
    meio = len(limpos) // 2
    if len(limpos) % 2:
        return limpos[meio]
    return (limpos[meio - 1] + limpos[meio]) / 2.0


def _percentil(values: Sequence[float], valor: float) -> Optional[float]:
    limpos = [float(v) for v in values if v is not None]
    if not limpos:
        return None
    abaixo = sum(1 for v in limpos if v < valor)
    iguais = sum(1 for v in limpos if v == valor)
    return _clamp(((abaixo + 0.5 * iguais) / len(limpos)) * 100.0)


def _normalize(value: Optional[float], pior: float, melhor: float) -> Optional[float]:
    """Reta entre o pior e o melhor ponto (funciona nos dois sentidos)."""
    if value is None or melhor == pior:
        return None
    if melhor > pior:
        return _clamp(((float(value) - pior) / (melhor - pior)) * 100.0)
    return _clamp(((pior - float(value)) / (pior - melhor)) * 100.0)


def _share(rows: Sequence[Dict[str, Any]], predicate, *, weights: bool = True) -> Optional[float]:
    """Fatia (por valor, ou por contagem quando não há valor) das linhas que casam."""
    if not rows:
        return None
    matching = [row for row in rows if predicate(row)]
    if weights:
        total = sum(max(0.0, _to_float(row.get("valor")) or 0.0) for row in rows)
        if total > 0:
            return sum(max(0.0, _to_float(row.get("valor")) or 0.0) for row in matching) / total
    return len(matching) / len(rows)


def _fmt_pct(value: Optional[float]) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _fmt_num(value: Optional[float], digits: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}".replace(",", " ")


def _fmt_dias(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.0f} dias"


def _client(es: Optional[Elasticsearch] = None) -> Optional[Elasticsearch]:
    return es or get_es_client(request_timeout=90)


def _garantir_indices(client: Elasticsearch) -> None:
    global _INDICES_GARANTIDOS
    if _INDICES_GARANTIDOS:
        return
    with _INDICES_LOCK:
        if _INDICES_GARANTIDOS:
            return
        try:
            ensure_indices(client)
            _INDICES_GARANTIDOS = True
        except Exception as exc:  # noqa: BLE001
            logger.debug("ESG: não foi possível garantir os índices: %s", exc)


def _search(client: Elasticsearch, index: str, body: Dict[str, Any], *, timeout: int = 60) -> Dict[str, Any]:
    try:
        return client.search(index=index, body=body, request_timeout=timeout) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("ESG: falha de pesquisa em %s: %s", index, exc)
        return {"error": str(exc)}


def _index_existe(client: Elasticsearch, index: str) -> bool:
    try:
        return bool(client.indices.exists(index=index))
    except Exception:  # noqa: BLE001
        return False


def _hits(response: Any) -> List[Dict[str, Any]]:
    # O cliente devolve `ObjectApiResponse`, que tem `.get` mas **não** é um
    # `dict` nem está registado como `Mapping`: testar o tipo perdia todas as
    # respostas reais.
    try:
        return list((response.get("hits") or {}).get("hits") or [])
    except (AttributeError, TypeError):
        return []


def _total(response: Any) -> int:
    try:
        total = (response.get("hits") or {}).get("total") or {}
    except (AttributeError, TypeError):
        return 0
    if isinstance(total, Mapping):
        return int(total.get("value") or 0)
    return int(total or 0)


#: O cadastro guarda o **nome** do país; as rotas e o frontend usam o código.
PAIS_ALIASES: Dict[str, str] = {
    "pt": "PT",
    "prt": "PT",
    "portugal": "PT",
    "es": "ES",
    "esp": "ES",
    "espanha": "ES",
    "espana": "ES",
    "spain": "ES",
}


def pais_codigo(valor: Optional[str]) -> str:
    chave = padroes.fold(str(valor or ""))
    return PAIS_ALIASES.get(chave, str(valor or padroes.PAIS_DEFAULT).upper())


def _spec(pais: Optional[str]):
    return padroes.COUNTRIES.get(pais_codigo(pais))


def _nif_limpo(valor: Any) -> str:
    return re.sub(r"[\s.\-/]", "", str(valor or "")).upper()


# ---------------------------------------------------------------------------
# Leitura das fontes
# ---------------------------------------------------------------------------
def _cadastro(client: Elasticsearch, nif: str) -> Dict[str, Any]:
    """Documento do cadastro de contribuintes (com os sinais de dívida)."""
    nif_limpo = _nif_limpo(nif)
    resposta = _search(
        client,
        CONTRIBUINTES_INDEX,
        {
            "size": 1,
            "track_total_hits": False,
            "query": {"terms": {"nif": [nif_limpo, nif_limpo.lower(), str(nif)]}},
            "_source": {
                "includes": [
                    "nif",
                    "name",
                    "names",
                    "type",
                    "is_company",
                    "country",
                    "roles",
                    "location",
                    "sources",
                    "source_labels",
                    "contracts_count",
                    "contracts_as_adjudicante",
                    "contracts_as_adjudicatario",
                    "contracts_value",
                    "contracts_first_date",
                    "contracts_last_date",
                    "contratos_es_count",
                    "contratos_es_value",
                    "cire_count",
                    "societario_count",
                    "people_roles_count",
                    "devedor",
                    "devedores_count",
                    "devedores_escalao",
                    "devedores_entidade",
                    "devedores_lista",
                ]
            },
        },
        timeout=30,
    )
    hits = _hits(resposta)
    return (hits[0].get("_source") or {}) if hits else {}


def _cae(client: Elasticsearch, nif: str) -> Dict[str, Any]:
    """CAE principal/secundários a partir do registo de entidades (ou firmas)."""
    nif_limpo = _nif_limpo(nif)
    resposta = _search(
        client,
        ENTITIES_INDEX,
        {
            "size": 1,
            "track_total_hits": False,
            "query": {"terms": {"nif": [nif_limpo, nif_limpo.lower()]}},
            "_source": ["nif", "name", "cae_principal", "caes_secundarios", "country_code"],
        },
        timeout=30,
    )
    hits = _hits(resposta)
    if hits:
        doc = hits[0].get("_source") or {}
        if doc.get("cae_principal"):
            return {
                "cae_principal": str(doc.get("cae_principal")),
                "caes_secundarios": doc.get("caes_secundarios") or [],
                "fonte": "entidades",
            }
    # Recuo: registo de firmas (RNPC), que guarda o CAE no NIPC.
    resposta = _search(
        client,
        FIRMAS_INDEX,
        {
            "size": 1,
            "track_total_hits": False,
            "query": {"bool": {"should": [{"term": {"nipc": nif_limpo}}, {"term": {"company_nif": nif_limpo}}], "minimum_should_match": 1}},
            "_source": ["nipc", "company_nif", "cae_principal", "nome"],
        },
        timeout=30,
    )
    hits = _hits(resposta)
    if hits:
        doc = hits[0].get("_source") or {}
        if doc.get("cae_principal"):
            return {"cae_principal": str(doc.get("cae_principal")), "caes_secundarios": [], "fonte": "firmas"}
    return {"cae_principal": "", "caes_secundarios": [], "fonte": ""}


def _insolvencias(client: Elasticsearch, nif: str) -> List[Dict[str, Any]]:
    """Processos do CIRE em que a empresa é **insolvente** (não credora)."""
    nif_limpo = _nif_limpo(nif)
    resposta = _search(
        client,
        CIRE_INDEX,
        {
            "size": 20,
            "track_total_hits": False,
            "_source": ["insolvente", "especie", "ato", "data_publicacao", "tribunal", "processo_numero", "intervenientes"],
            "query": {"terms": {"nifs": [nif_limpo]}},
            "sort": [{"data_publicacao": {"order": "desc", "unmapped_type": "date"}}],
        },
        timeout=45,
    )
    saida: List[Dict[str, Any]] = []
    for hit in _hits(resposta):
        src = hit.get("_source") or {}
        papeis = [
            padroes.fold(str(item.get("papel") or ""))
            for item in (src.get("intervenientes") or [])
            if isinstance(item, dict) and str(item.get("nif") or "") == nif_limpo
        ]
        if not any("insolvente" in papel for papel in papeis):
            continue
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


def _contracts(
    client: Elasticsearch,
    spec: Any,
    nif: str,
    *,
    role: str = "fornecedor",
    limit: int = MAX_CONTRATOS,
    ano_from: Optional[int] = None,
    ano_to: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Contratos da empresa como fornecedor (adjudicatário) ou comprador (adjudicante)."""
    if role == "comprador":
        if spec.key == "PT":
            filtro: Dict[str, Any] = {
                "nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": _nif_limpo(nif)}}}
            }
        else:
            filtro = {"wildcard": {spec.adjudicante_nif: {"value": _nif_limpo(nif), "case_insensitive": True}}}
    else:
        filtro = padroes._empresa_query(spec, _nif_limpo(nif))  # noqa: SLF001

    filtros: List[Dict[str, Any]] = [filtro]
    if ano_from is not None or ano_to is not None:
        intervalo: Dict[str, Any] = {}
        if ano_from is not None:
            intervalo["gte"] = int(ano_from)
        if ano_to is not None:
            intervalo["lte"] = int(ano_to)
        filtros.append({"range": {spec.year_field: intervalo}})

    campos = list(dict.fromkeys([*spec.source_fields, "ContratEcologico", "localExecucao"]))
    body = {
        "size": max(10, min(int(limit), 2_000)),
        "track_total_hits": True,
        "query": {"bool": {"filter": filtros}},
        "sort": [{spec.pub_date: {"order": "desc", "unmapped_type": "date"}}],
        "_source": campos,
    }
    resposta = _search(client, spec.index, body, timeout=120)
    total = _total(resposta) if resposta and "error" not in resposta else None
    rows: List[Dict[str, Any]] = []
    for hit in _hits(resposta):
        row = padroes._row_from_hit(spec, hit)  # noqa: SLF001
        src = hit.get("_source") or {}
        row["ecologico"] = padroes.fold(str(src.get("ContratEcologico") or "")) in {"sim", "s", "yes", "true", "1"}
        row["contrat_ecologico"] = src.get("ContratEcologico")
        row["local"] = src.get("localExecucao") or src.get("nuts")
        rows.append(row)
    return rows, total


# ---------------------------------------------------------------------------
# Features ESG
# ---------------------------------------------------------------------------
def _cpv_divisao(code: Any) -> Optional[int]:
    digitos = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(digitos) < 2:
        return None
    try:
        return int(digitos[:2])
    except ValueError:
        return None


def features_de_contratos(
    rows: Sequence[Dict[str, Any]],
    *,
    insolvencias: int = 0,
    devedor: bool = False,
    devedores_escalao: Optional[str] = None,
) -> Dict[str, Any]:
    """Features comuns às duas fontes de contratos (PT/ES) e aos dois papéis."""
    linhas = list(rows)
    valores = [max(0.0, _to_float(row.get("valor")) or 0.0) for row in linhas]
    total_valor = sum(valores)
    denominador = total_valor if total_valor > 0 else len(linhas)

    def _div(row: Dict[str, Any]) -> Optional[int]:
        return _cpv_divisao(row.get("cpv"))

    def _partilha(predicado) -> Optional[float]:
        if not linhas:
            return None
        if total_valor > 0:
            return sum(valor for valor, row in zip(valores, linhas) if predicado(row)) / total_valor
        return sum(1 for row in linhas if predicado(row)) / len(linhas)

    compradores: Dict[str, float] = {}
    for valor, row in zip(valores, linhas):
        chave = str(row.get("adjudicante_nif") or padroes.fold(str(row.get("adjudicante_nome") or "")) or "?")
        compradores[chave] = compradores.get(chave, 0.0) + (valor if total_valor > 0 else 1.0)

    cpv_valor: Dict[int, float] = {}
    cpv_contagem: Dict[int, int] = {}
    for valor, row in zip(valores, linhas):
        divisao = _div(row)
        if divisao is None:
            continue
        cpv_valor[divisao] = cpv_valor.get(divisao, 0.0) + (valor if total_valor > 0 else 0.0)
        cpv_contagem[divisao] = cpv_contagem.get(divisao, 0) + 1

    cpv_top = []
    for divisao, valor in sorted(cpv_valor.items(), key=lambda item: item[1], reverse=True)[:6]:
        item = tax.CPV_ESG.get(divisao) or {}
        cpv_top.append(
            {
                "divisao": f"{divisao:02d}",
                "label": item.get("label") or f"CPV {divisao:02d}",
                "valor": _round(valor, 2),
                "peso": _round(valor / total_valor, 4) if total_valor > 0 else None,
                "contratos": cpv_contagem.get(divisao, 0),
            }
        )

    por_ano: Dict[int, Dict[str, Any]] = {}
    for valor, row in zip(valores, linhas):
        ano = _to_int(row.get("ano"))
        if ano is None:
            continue
        entrada = por_ano.setdefault(ano, {"ano": ano, "contratos": 0, "valor": 0.0})
        entrada["contratos"] += 1
        entrada["valor"] += valor

    concorrentes = [row.get("n_concorrentes") for row in linhas if row.get("n_concorrentes") is not None]
    dias_pub = [row.get("dias_publicacao") for row in linhas if row.get("dias_publicacao") is not None]
    dias_assin = [row.get("dias_assinatura") for row in linhas if row.get("dias_assinatura") is not None]
    dias_transparencia = dias_pub or dias_assin

    return {
        "contratos": len(linhas),
        "valor_total": _round(total_valor, 2),
        "valor_com_valor": sum(1 for valor in valores if valor > 0),
        "adjudicantes_distintos": len(compradores),
        "concentracao_comprador": _round((max(compradores.values()) / sum(compradores.values())) if compradores and sum(compradores.values()) > 0 else None, 4),
        "taxa_ajuste_direto": _round(_partilha(lambda row: bool(row.get("ajuste_direto"))), 4),
        "taxa_ecologicos": _round(_partilha(lambda row: bool(row.get("ecologico"))), 4),
        "mediana_concorrentes": _round(_median(concorrentes), 2),
        "media_concorrentes": _round(sum(float(v) for v in concorrentes) / len(concorrentes), 2) if concorrentes else None,
        "taxa_sem_concorrentes": _round(
            (sum(1 for v in concorrentes if v is not None and v <= 1) / len(concorrentes)) if concorrentes else None, 4
        ),
        "dias_assinatura_mediana": _round(_median(dias_assin), 1),
        "dias_publicacao_mediana": _round(_median(dias_transparencia), 1),
        "share_verde": _round(_partilha(lambda row: (_div(row) in tax.CPV_VERDE)), 4),
        "share_marrom": _round(_partilha(lambda row: (_div(row) in tax.CPV_MARROM)), 4),
        "share_social": _round(_partilha(lambda row: (_div(row) in tax.CPV_SOCIAL)), 4),
        "share_circular": _round(_partilha(lambda row: (_div(row) in tax.CPV_CIRCULAR)), 4),
        "share_servicos_ambientais": _round(_partilha(lambda row: (_div(row) in SERVICOS_AMBIENTAIS)), 4),
        "exposicao_verde": _round(
            ((_partilha(lambda row: (_div(row) in tax.CPV_VERDE)) or 0.0) - (_partilha(lambda row: (_div(row) in tax.CPV_MARROM)) or 0.0)),
            4,
        ),
        "cpv_top": cpv_top,
        "por_ano": [por_ano[ano] for ano in sorted(por_ano)],
        "insolvencias": int(insolvencias or 0),
        "devedor": 1 if devedor else 0,
        "devedores_escalao": devedores_escalao,
        "denominador": _round(denominador, 2),
    }


def _indicador_normalizado(item: Dict[str, Any], valor: float) -> Optional[float]:
    pior = item.get("pior")
    melhor = item.get("melhor")
    if not item.get("pontuavel") or pior is None or melhor is None:
        return None
    return _normalize(valor, float(pior), float(melhor))


def indicadores_score(valores: Dict[str, float]) -> Dict[str, Dict[str, Any]]:
    """Índice 0–1 por pilar, com encolhimento quando há poucos indicadores.

    Três indicadores não valem o mesmo que doze. A média é puxada para 50 %
    (`0,5 + (média−0,5) × n/(n+3)`) até haver evidência suficiente, e o número de
    indicadores fica sempre visível na UI.
    """
    por_pilar: Dict[str, List[Dict[str, Any]]] = {pilar["id"]: [] for pilar in tax.PILARES}
    for codigo, valor in (valores or {}).items():
        item = tax.INDICADOR_BY_CODIGO.get(codigo)
        if not item:
            continue
        numero = _to_float(valor)
        if numero is None:
            continue
        normalizado = _indicador_normalizado(item, numero)
        if normalizado is None:
            continue
        por_pilar.setdefault(str(item["pilar"]), []).append(
            {
                "codigo": codigo,
                "label": item["label"],
                "grupo": item.get("grupo"),
                "valor": numero,
                "unidade": item.get("unidade"),
                "pontos": _round(normalizado, 1),
            }
        )
    saida: Dict[str, Dict[str, Any]] = {}
    for pilar, itens in por_pilar.items():
        n = len(itens)
        if not n:
            saida[pilar] = {"score": None, "n": 0, "detalhes": []}
            continue
        media = sum(float(item["pontos"] or 0.0) for item in itens) / n / 100.0
        fator = n / (n + MIN_INDICADORES_CONFIANCA)
        ajustado = 0.5 + (media - 0.5) * fator
        saida[pilar] = {
            "score": _round(_clamp(ajustado * 100.0), 2),
            "n": n,
            "detalhes": sorted(itens, key=lambda item: item["codigo"]),
        }
    return saida


# ---------------------------------------------------------------------------
# Avaliação (pura, testável sem Elasticsearch)
# ---------------------------------------------------------------------------
def _evidencia(componente: Dict[str, Any], features: Dict[str, Any], indice: Optional[Dict[str, Any]]) -> List[str]:
    cid = componente["id"]
    if cid == "compras_ecologicas":
        return [f"{_fmt_pct(features.get('taxa_ecologicos'))} do valor com critérios ecológicos"]
    if cid == "exposicao_verde":
        return [
            f"verde {_fmt_pct(features.get('share_verde'))} · carbónico {_fmt_pct(features.get('share_marrom'))}",
            f"saldo {_fmt_pct(features.get('exposicao_verde'))}",
        ]
    if cid == "intensidade_carbono":
        return [f"{_fmt_pct(features.get('share_marrom'))} do valor em CPV de maior intensidade carbónica"]
    if cid == "servicos_ambientais":
        return [f"{_fmt_pct(features.get('share_servicos_ambientais'))} em resíduos, água, energia, agricultura e reparação"]
    if cid == "exposicao_social":
        return [f"{_fmt_pct(features.get('share_social'))} em saúde, educação, ação social e cultura"]
    if cid == "concorrencia":
        return [f"mediana de {_fmt_num(features.get('mediana_concorrentes'), 1)} concorrentes"]
    if cid == "diversidade_compradores":
        return [f"{_fmt_num(features.get('adjudicantes_distintos'))} compradores distintos"]
    if cid == "transparencia":
        return [f"mediana de {_fmt_dias(features.get('dias_publicacao_mediana'))} entre assinatura e publicação"]
    if cid == "ajuste_direto":
        return [f"{_fmt_pct(features.get('taxa_ajuste_direto'))} do valor em ajuste direto"]
    if cid == "concentracao":
        return [f"maior comprador = {_fmt_pct(features.get('concentracao_comprador'))} do valor"]
    if cid == "insolvencia":
        return [f"{_fmt_num(features.get('insolvencias'))} processo(s) no CIRE"]
    if cid == "divida_publica":
        return ["consta nas listas públicas de devedores" if features.get("devedor") else "sem registo nas listas públicas"]
    if cid in {"indicadores_ambientais", "indicadores_sociais", "indicadores_governacao"}:
        n = int((indice or {}).get("n") or 0)
        grupos = sorted({str(item.get("grupo") or "") for item in (indice or {}).get("detalhes") or [] if item.get("grupo")})
        return [f"{n} indicador(es) declarado(s)" + (f" · {', '.join(grupos[:4])}" if grupos else "")]
    return []


def _valor_componente(cid: str, features: Dict[str, Any], indices: Dict[str, Dict[str, Any]]) -> Optional[float]:
    mapa = {
        "compras_ecologicas": "taxa_ecologicos",
        "exposicao_verde": "exposicao_verde",
        "intensidade_carbono": "share_marrom",
        "servicos_ambientais": "share_servicos_ambientais",
        "exposicao_social": "share_social",
        "concorrencia": "mediana_concorrentes",
        "diversidade_compradores": "adjudicantes_distintos",
        "transparencia": "dias_publicacao_mediana",
        "ajuste_direto": "taxa_ajuste_direto",
        "concentracao": "concentracao_comprador",
        "insolvencia": "insolvencias",
        "divida_publica": "devedor",
    }
    if cid in {"indicadores_ambientais", "indicadores_sociais", "indicadores_governacao"}:
        pilar = {"indicadores_ambientais": "e", "indicadores_sociais": "s", "indicadores_governacao": "g"}[cid]
        score = (indices.get(pilar) or {}).get("score")
        return None if score is None else float(score) / 100.0
    return _to_float(features.get(mapa.get(cid, "")))


def avaliar(
    features: Dict[str, Any],
    *,
    indicadores: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Calcula o score ESG a partir das features e dos indicadores declarados.

    Devolve sempre os componentes (mesmo indisponíveis), a cobertura, a
    confiança e os avisos. Nunca inventa um score quando não há dados.
    """
    indices = indicadores or {}
    componentes: List[Dict[str, Any]] = []
    por_pilar: Dict[str, List[Dict[str, Any]]] = {pilar["id"]: [] for pilar in tax.PILARES}
    total_peso = sum(float(item["peso"]) * float(tax.PILAR_BY_ID[item["pilar"]]["peso"]) for item in tax.COMPONENTES)
    peso_disponivel = 0.0

    for definicao in tax.COMPONENTES:
        valor = _valor_componente(definicao["id"], features, indices)
        if definicao["id"] in {"indicadores_ambientais", "indicadores_sociais", "indicadores_governacao"}:
            indice = indices.get(definicao["pilar"]) or {}
            disponivel = indice.get("score") is not None
        else:
            indice = None
            disponivel = valor is not None
        pontos = _normalize(valor, float(definicao["pior"]), float(definicao["melhor"])) if disponivel else None
        componente = {
            "id": definicao["id"],
            "pilar": definicao["pilar"],
            "label": definicao["label"],
            "peso": float(definicao["peso"]),
            "peso_efetivo": 0.0,
            "contributo": None,
            "valor": _round(valor, 4),
            "unidade": definicao["unidade"],
            "descricao": definicao["descricao"],
            "metodo": definicao["metodo"],
            "pontos": _round(pontos, 1) if pontos is not None else None,
            "disponivel": bool(disponivel),
            "evidencia": _evidencia(definicao, features, indice) if disponivel else [],
        }
        if disponivel and pontos is not None:
            por_pilar[definicao["pilar"]].append(componente)
            peso_disponivel += float(definicao["peso"]) * float(tax.PILAR_BY_ID[definicao["pilar"]]["peso"])
        componentes.append(componente)

    pilares_detalhe: List[Dict[str, Any]] = []
    for pilar in tax.PILARES:
        itens = por_pilar.get(pilar["id"], [])
        peso_pilar = float(pilar["peso"])
        if itens:
            soma_pesos = sum(float(item["peso"]) for item in itens)
            score_pilar = sum(float(item["pontos"]) * float(item["peso"]) for item in itens) / soma_pesos
            cobertura_pilar = soma_pesos
        else:
            score_pilar = None
            cobertura_pilar = 0.0
        for item in itens:
            item["peso_efetivo"] = _round(float(item["peso"]) / soma_pesos, 4) if itens else 0.0
            item["contributo"] = _round(
                (float(item["pontos"]) - 50.0) * (float(item["peso"]) / soma_pesos) * peso_pilar, 2
            ) if itens else None
        pilares_detalhe.append(
            {
                "id": pilar["id"],
                "label": pilar["label"],
                "peso": peso_pilar,
                "cor": pilar["cor"],
                "descricao": pilar["descricao"],
                "score": _round(score_pilar, 2) if score_pilar is not None else None,
                "cobertura": _round(cobertura_pilar, 4),
                "componentes": itens,
            }
        )

    pilares_com_dados = [item for item in pilares_detalhe if item["score"] is not None]
    if pilares_com_dados:
        soma_pesos = sum(float(item["peso"]) for item in pilares_com_dados)
        score = sum(float(item["score"]) * float(item["peso"]) for item in pilares_com_dados) / soma_pesos
        cobertura = peso_disponivel / total_peso if total_peso else 0.0
    else:
        score = None
        cobertura = 0.0

    if cobertura >= 0.80:
        confianca = "alta"
    elif cobertura >= 0.55:
        confianca = "média"
    elif cobertura >= 0.30:
        confianca = "baixa"
    elif cobertura > 0:
        confianca = "muito baixa"
    else:
        confianca = "sem dados"

    nivel = tax.nivel_de(score)
    avisos: List[str] = []
    if score is None:
        avisos.append("Sem contratos nem indicadores declarados: não há score ESG para esta empresa (não é zero).")
    elif cobertura < 0.50:
        avisos.append(
            f"Cobertura de {cobertura * 100:.0f}%: o score usa apenas os componentes com dados e não deve ser lido como nota final."
        )
    if int(indicadores_n := sum(int((indices.get(p) or {}).get("n") or 0) for p in ("e", "s", "g"))) == 0:
        avisos.append("Sem indicadores de relatórios de sustentabilidade: faltam emissões, formação, acidentes e governance declarada.")
    if not features.get("contratos"):
        avisos.append("Sem contratos públicos registados: a leitura fica limitada aos indicadores declarados.")
    if features.get("devedor"):
        avisos.append("A empresa consta de uma lista pública de devedores (AT/Segurança Social).")
    if int(features.get("insolvencias") or 0) > 0:
        avisos.append("Há processos de insolvência em que a empresa é a insolvente.")

    fatores = sorted(
        [item for item in componentes if item["contributo"] is not None],
        key=lambda item: abs(float(item["contributo"] or 0.0)),
        reverse=True,
    )

    return {
        "score": _round(score, 2),
        "nivel": nivel["id"] if score is not None else None,
        "nivel_label": nivel["label"],
        "cor": nivel["cor"],
        "cobertura": _round(cobertura, 4),
        "confianca": confianca,
        "pilares": {item["id"]: item["score"] for item in pilares_detalhe},
        "pilares_detalhe": pilares_detalhe,
        "componentes": componentes,
        "fatores": fatores[:8],
        "features": features,
        "indicadores_score": indices,
        "n_indicadores": indicadores_n,
        "avisos": avisos,
        "modelo_versao": tax.MODELO_VERSAO,
        "gerado_em": _now(),
    }


# ---------------------------------------------------------------------------
# Indicadores declarados
# ---------------------------------------------------------------------------
def _docs_indicadores(client: Elasticsearch, nif: str, pais: str) -> List[Dict[str, Any]]:
    if not _index_existe(client, ESG_INDICADORES_INDEX):
        return []
    resposta = _search(
        client,
        ESG_INDICADORES_INDEX,
        {
            "size": 100,
            "track_total_hits": False,
            "query": {"bool": {"filter": [{"term": {"nif": _nif_limpo(nif)}}, {"term": {"pais": pais}}]}},
            "sort": [{"ano": {"order": "desc"}}, {"atualizado_em": {"order": "desc", "unmapped_type": "date"}}],
        },
        timeout=45,
    )
    return [hit.get("_source") or {} for hit in _hits(resposta)]


def _valores_indicadores(docs: Sequence[Dict[str, Any]], ano: Optional[int]) -> Tuple[Dict[str, float], List[Dict[str, Any]], List[str]]:
    """Valores por código para um ano, com precedência para verificação externa."""
    candidatos = [doc for doc in docs if ano is None or _to_int(doc.get("ano")) == ano]
    if not candidatos:
        return {}, [], []
    # Preferir o documento verificado externamente; depois o mais recente.
    # Estável: os documentos já vêm do mais recente para o mais antigo; só se
    # promove a verificação externa, sem perder essa ordem dentro de cada grupo.
    candidatos = sorted(candidatos, key=lambda doc: 0 if str(doc.get("verificacao") or "") == "externa" else 1)
    valores: Dict[str, float] = {}
    detalhes: List[Dict[str, Any]] = []
    fontes: List[str] = []
    for doc in candidatos:
        fonte = str(doc.get("fonte") or "")
        if fonte and fonte not in fontes:
            fontes.append(fonte)
        for item in doc.get("indicadores") or []:
            if not isinstance(item, dict):
                continue
            codigo = str(item.get("codigo") or "")
            numero = _to_float(item.get("valor"))
            if not codigo or numero is None or codigo in valores:
                continue
            valores[codigo] = numero
            detalhes.append(
                {
                    "codigo": codigo,
                    "label": item.get("label"),
                    "pilar": item.get("pilar"),
                    "unidade": item.get("unidade"),
                    "valor": numero,
                    "ano": doc.get("ano"),
                    "fonte": fonte,
                    "verificacao": doc.get("verificacao"),
                }
            )
    return valores, detalhes, fontes


# ---------------------------------------------------------------------------
# Cálculo por empresa
# ---------------------------------------------------------------------------
def _resolver_cadastro(client: Elasticsearch, q: str, *, size: int = 12, estrito: bool = True) -> List[Dict[str, Any]]:
    """Candidatos do cadastro por nome/NIF, com relevância em Python."""
    texto = str(q or "").strip()
    if len(texto) < 2:
        return []
    tokens = [token for token in re.split(r"\W+", padroes.fold(texto)) if len(token) >= 3]
    frase = " ".join(tokens)
    should: List[Dict[str, Any]] = []
    nif = _nif_limpo(texto)
    if nif and 6 <= len(nif) <= 12 and sum(1 for ch in nif if ch.isdigit()) >= 6:
        should.append({"term": {"nif": nif}})
    if frase:
        should.append({"match_phrase": {"name": {"query": frase, "boost": 8}}})
        should.append(
            {
                "multi_match": {
                    "query": frase,
                    "fields": ["name^4", "name.autocomplete^2", "search_text"],
                    "operator": "and" if estrito else "or",
                    "type": "best_fields",
                }
            }
        )
    if not should:
        return []
    resposta = _search(
        client,
        CONTRIBUINTES_INDEX,
        {
            "size": max(1, min(int(size), 30)),
            "track_total_hits": False,
            "query": {"bool": {"should": should, "minimum_should_match": 1}},
            "sort": ["_score", {"contracts_value": {"order": "desc", "missing": 0}}],
            "_source": [
                "nif",
                "name",
                "names",
                "country",
                "type",
                "is_company",
                "location",
                "contracts_count",
                "contracts_value",
                "roles",
            ],
        },
        timeout=45,
    )
    hits = _hits(resposta)
    if not hits and estrito:
        return _resolver_cadastro(client, q, size=size, estrito=False)

    def _ordem(doc: Dict[str, Any]) -> Tuple[int, int, float]:
        nome = padroes.fold(str(doc.get("name") or ""))
        palavras = [token for token in re.split(r"\W+", nome) if token]
        contem = 0 if frase and frase in nome else 1
        extras = min(len(set(palavras) - set(tokens)), 2) if tokens else 0
        return (contem, extras, -float(doc.get("contracts_value") or 0))

    docs = sorted((hit.get("_source") or {} for hit in hits), key=_ordem)
    return [
        {
            "nif": doc.get("nif"),
            "nome": doc.get("name") or doc.get("nif"),
            "pais": pais_codigo(doc.get("country")),
            "tipo": doc.get("type"),
            "local": doc.get("location") or {},
            "contratos": doc.get("contracts_count"),
            "valor": doc.get("contracts_value"),
        }
        for doc in docs
        if doc.get("nif")
    ]


def _empresa_base(doc_cadastro: Dict[str, Any], nif: str, nome: Optional[str], pais: str) -> Dict[str, Any]:
    nome_final = str(nome or doc_cadastro.get("name") or nif)
    return {
        "nif": _nif_limpo(nif),
        "nome": nome_final,
        "names": doc_cadastro.get("names") or [],
        "pais": pais,
        "tipo": doc_cadastro.get("type"),
        "is_company": doc_cadastro.get("is_company"),
        "local": doc_cadastro.get("location") or {},
        "contratos_cadastro": doc_cadastro.get("contracts_count"),
        "valor_cadastro": doc_cadastro.get("contracts_value"),
        "fontes_cadastro": doc_cadastro.get("source_labels") or doc_cadastro.get("sources") or [],
    }


def _setor_e_dimensao(
    client: Elasticsearch,
    nif: str,
    cae_info: Dict[str, Any],
    features: Dict[str, Any],
) -> Dict[str, Any]:
    cae = str(cae_info.get("cae_principal") or "")
    setor, setor_label = tax.setor_de_cae(cae)
    fonte = "CAE" if setor else ""
    if not setor:
        # Sem CAE: o CPV dominante é a proxy — diz-se que é proxy.
        top = (features.get("cpv_top") or [{}])[0]
        divisao = _cpv_divisao(top.get("divisao"))
        setor = tax.CPV_CAE_SECAO.get(divisao, "") if divisao is not None else ""
        setor_label = tax.CAE_SECOES.get(setor, {}).get("label", "") if setor else ""
        fonte = "CPV (proxy)" if setor else ""
    dimensao = tax.dimensao_de(features.get("valor_total"))
    return {
        "cae_principal": cae,
        "cae_label": cae_info.get("cae_label") or (tax.setor_de_cae(cae)[1] if cae else ""),
        "setor": setor,
        "setor_label": setor_label,
        "setor_fonte": fonte,
        "dimensao": dimensao["id"],
        "dimensao_label": dimensao["label"],
    }


def _indicadores_presentes(valores: Dict[str, Any], codigos: Sequence[str]) -> List[str]:
    presentes: List[str] = []
    for codigo in codigos:
        if _to_float((valores or {}).get(codigo)) is not None:
            presentes.append(codigo)
    return presentes


def taxonomia_de_empresa(
    *,
    cae: Optional[str],
    setor: Optional[str],
    valores: Optional[Dict[str, Any]] = None,
    cpv_top: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Liga a empresa à Taxonomia UE sem declarar alinhamento.

    A empresa é **elegível** quando o CAE/NACE coincide com atividades do
    Compass. O alinhamento exige três coisas que os dados abertos raramente
    provam: critérios técnicos, ausência de prejuízo significativo (DNSH) e
    salvaguardas sociais mínimas. Por isso o estado máximo é
    ``elegivel_nao_verificado``; os indicadores declarados só reduzem a
    incerteza, nunca substituem a avaliação oficial.
    """
    valores = valores or {}
    secao = tax_eu.secao_de_cae(cae) or str(setor or "").upper()
    nace = tax_eu.nace_de_cae(cae)
    atividades = tax_eu.atividades_por_nace(cae)
    match = "nace"
    if not atividades and secao:
        atividades = tax_eu.atividades_por_secao(secao)
        match = "setor"
    total_atividades = len(atividades)
    atividades = atividades[:16]

    objetivos: Dict[int, Dict[str, Any]] = {}
    for atividade in atividades:
        for objetivo in atividade.get("objetivos") or []:
            oid = int(objetivo["id"])
            definicao = tax_eu.OBJETIVO_BY_ID.get(oid) or {}
            entrada = objetivos.setdefault(
                oid,
                {
                    "id": oid,
                    "label": definicao.get("label") or f"Objetivo {oid}",
                    "curto": definicao.get("curto") or f"Objetivo {oid}",
                    "cor": definicao.get("cor") or "#94a3b8",
                    "n_atividades": 0,
                    "tipos": set(),
                    "atividades": [],
                },
            )
            entrada["n_atividades"] += 1
            entrada["tipos"].add(str(objetivo.get("tipo") or "Contribui significativamente"))
            if len(entrada["atividades"]) < 5:
                entrada["atividades"].append({"id": atividade["id"], "nome": atividade["nome"]})

    dnsh: List[Dict[str, Any]] = []
    for criterio in tax_eu.DNSH:
        definicao = tax_eu.OBJETIVO_BY_ID.get(int(criterio["objetivo"])) or {}
        presentes = _indicadores_presentes(valores, criterio.get("indicadores") or [])
        dnsh.append(
            {
                "objetivo": criterio["objetivo"],
                "label": definicao.get("curto") or f"Objetivo {criterio['objetivo']}",
                "cor": definicao.get("cor") or "#94a3b8",
                "indicadores": presentes,
                "status": "com indicador" if presentes else "sem evidência",
            }
        )

    salvaguardas: List[Dict[str, Any]] = []
    for requisito in tax_eu.SALVAGUARDAS:
        presentes = _indicadores_presentes(valores, requisito.get("indicadores") or [])
        if len(presentes) >= 2:
            estado = "evidência parcial"
        elif presentes:
            estado = "evidência limitada"
        else:
            estado = "sem evidência"
        salvaguardas.append(
            {
                "id": requisito["id"],
                "label": requisito["label"],
                "descricao": requisito["descricao"],
                "fonte": requisito.get("fonte"),
                "indicadores": presentes,
                "status": estado,
            }
        )

    n_dnsh = sum(1 for item in dnsh if item["status"] == "com indicador")
    n_salv = sum(1 for item in salvaguardas if item["status"] != "sem evidência")
    cobertura_verificacao = (n_dnsh + n_salv) / float(len(dnsh) + len(salvaguardas) or 1)

    if not cae and not secao:
        estado = "sem_dados"
    elif not atividades:
        estado = "nao_elegivel"
    else:
        estado = "elegivel_nao_verificado"

    grupos_indicadores = {
        str((tax.INDICADOR_BY_CODIGO.get(codigo) or {}).get("grupo") or "")
        for codigo in valores
        if _to_float(valores.get(codigo)) is not None
    }
    ods: List[Dict[str, Any]] = []
    for objetivo in tax_eu.ODS:
        coincidencias = sorted(set(objetivo.get("grupos") or []) & grupos_indicadores)
        if coincidencias:
            ods.append(
                {
                    "id": objetivo["id"],
                    "label": objetivo["label"],
                    "cor": objetivo.get("cor"),
                    "grupos": coincidencias,
                }
            )
    ods.sort(key=lambda item: (-len(item["grupos"]), item["id"]))

    temas = list(tax_eu.MATERIALIDADE.get(secao, []))
    for item in (cpv_top or [])[:3]:
        label = str(item.get("label") or "").strip()
        if label and label not in temas:
            temas.append(label)
    materialidade = [
        {"tema": tema, "relevancia": "alta" if index < 4 else "média", "origem": "setor/CPV"}
        for index, tema in enumerate(temas[:6])
    ]

    objetivos_lista = []
    for oid in sorted(objetivos):
        entrada = objetivos[oid]
        entrada["tipos"] = sorted(entrada["tipos"])
        objetivos_lista.append(entrada)

    elegivel = bool(atividades)
    avisos = [
        "Elegibilidade não é alinhamento: os critérios técnicos, o DNSH e as salvaguardas mínimas têm de ser documentados e verificados.",
    ]
    if elegivel and cobertura_verificacao < 0.5:
        avisos.append(
            "A empresa tem atividades elegíveis, mas faltam indicadores declarados para verificar DNSH e salvaguardas mínimas."
        )
    if not cae:
        avisos.append("Sem CAE: a ligação às atividades usa o setor/CPV como proxy (menor confiança).")

    return {
        "fonte": tax_eu.FONTE,
        "nace": nace,
        "secao": secao,
        "match": match if atividades else None,
        "elegivel": elegivel,
        "alinhamento": estado,
        "alinhamento_label": {
            "sem_dados": "Sem dados para avaliar",
            "nao_elegivel": "Sem atividade elegível identificada",
            "elegivel_nao_verificado": "Elegível — alinhamento por verificar",
        }.get(estado, estado),
        "cobertura_verificacao": _round(cobertura_verificacao, 4),
        "n_atividades": total_atividades,
        "atividades": [
            {
                **atividade,
                "url": tax_eu.url_atividade(atividade["id"]),
                "objetivos": [
                    {
                        **objetivo,
                        "label": (tax_eu.OBJETIVO_BY_ID.get(int(objetivo["id"])) or {}).get("label"),
                        "curto": (tax_eu.OBJETIVO_BY_ID.get(int(objetivo["id"])) or {}).get("curto"),
                        "cor": (tax_eu.OBJETIVO_BY_ID.get(int(objetivo["id"])) or {}).get("cor"),
                    }
                    for objetivo in atividade.get("objetivos") or []
                ],
            }
            for atividade in atividades
        ],
        "objetivos": objetivos_lista,
        "dnsh": dnsh,
        "salvaguardas": salvaguardas,
        "ods": ods[:8],
        "materialidade": materialidade,
        "avisos": avisos,
        "url_compass": tax_eu.FONTE["url"],
    }


def taxonomia_panorama() -> Dict[str, Any]:
    """Visão estática da Taxonomia UE, com contagens oficiais por objetivo."""
    objetivos = []
    for objetivo in tax_eu.OBJETIVOS:
        atividades = tax_eu.atividades_por_objetivo(objetivo["id"])
        objetivos.append(
            {
                **objetivo,
                "n_atividades": len(atividades),
                "atividades": [{"id": item["id"], "nome": item["nome"]} for item in atividades[:8]],
            }
        )
    setores: Dict[str, int] = {}
    for atividade in tax_eu.ATIVIDADES:
        setores[atividade["setor"]] = setores.get(atividade["setor"], 0) + 1
    return {
        "fonte": tax_eu.FONTE,
        "objetivos": objetivos,
        "total_atividades": len(tax_eu.ATIVIDADES),
        "setores": [{"setor": nome, "n": n} for nome, n in sorted(setores.items(), key=lambda item: (-item[1], item[0]))],
        "salvaguardas": [dict(item) for item in tax_eu.SALVAGUARDAS],
        "dnsh": [dict(item) for item in tax_eu.DNSH],
        "normas_relato": [dict(item) for item in tax_eu.NORMAS_RELATO],
        "ods": [dict(item) for item in tax_eu.ODS],
        "passos": [dict(item) for item in tax_eu.PASSOS],
        "materialidade": {chave: list(valor) for chave, valor in tax_eu.MATERIALIDADE.items()},
    }


def taxonomia_atividades(
    *,
    q: Optional[str] = None,
    setor: Optional[str] = None,
    objetivo: Optional[int] = None,
    nace: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
) -> Dict[str, Any]:
    """Pesquisa as atividades oficiais do Compass (sem rede)."""
    texto = padroes.fold(str(q or ""))
    alvo_nace = tax_eu.nace_de_cae(nace) if nace else ""
    itens = []
    for atividade in tax_eu.ATIVIDADES:
        if setor and atividade["setor"].lower() != str(setor).lower():
            continue
        if objetivo is not None and not any(int(item["id"]) == int(objetivo) for item in atividade.get("objetivos") or []):
            continue
        if alvo_nace and not any(
            (prefixo := tax_eu.normalizar_nace(codigo)) and alvo_nace.startswith(prefixo)
            for codigo in atividade.get("nace") or []
        ):
            continue
        if texto and texto not in padroes.fold(f"{atividade['nome']} {atividade['setor']} {' '.join(atividade.get('nace') or [])}"):
            continue
        itens.append(
            {
                **atividade,
                "url": tax_eu.url_atividade(atividade["id"]),
                "objetivos": [
                    {
                        **objetivo_item,
                        "label": (tax_eu.OBJETIVO_BY_ID.get(int(objetivo_item["id"])) or {}).get("label"),
                        "curto": (tax_eu.OBJETIVO_BY_ID.get(int(objetivo_item["id"])) or {}).get("curto"),
                        "cor": (tax_eu.OBJETIVO_BY_ID.get(int(objetivo_item["id"])) or {}).get("cor"),
                    }
                    for objetivo_item in atividade.get("objetivos") or []
                ],
            }
        )
    itens.sort(key=lambda item: (item["setor"], item["nome"]))
    total = len(itens)
    inicio = max(0, int(from_))
    return {"total": total, "itens": itens[inicio : inicio + max(1, min(int(size), 100))], "filtros": {"q": q, "setor": setor, "objetivo": objetivo, "nace": nace}}


def taxonomia_empresa(*, nif: str, pais: str = "PT") -> Dict[str, Any]:
    """Taxonomia da empresa a partir da fotografia ESG (calculada ao vivo)."""
    doc = calcular_empresa(nif=nif, pais=pais, indexar=False, incluir_benchmark=False, incluir_fornecedores=False)
    if doc.get("error"):
        return doc
    return {
        "empresa": doc.get("empresa") or {"nif": nif, "nome": doc.get("name")},
        "ano": doc.get("ano"),
        "taxonomia": doc.get("taxonomia") or {},
        "avisos": (doc.get("taxonomia") or {}).get("avisos") or [],
        "cartao_modelo": {"versao": tax.MODELO_VERSAO, "aviso": tax.AVISO_GERAL},
    }


def _benchmark(
    client: Elasticsearch,
    *,
    nif: str,
    setor: str,
    dimensao: str,
    score: Optional[float],
    pilares: Dict[str, Optional[float]],
    anos: Sequence[int],
) -> Dict[str, Any]:
    """Percentil e medianas face a pares do mesmo setor e dimensão."""
    if not setor or score is None:
        return {"disponivel": False, "motivo": "Sem setor ou score para comparar.", "n_pares": 0}
    if not _index_existe(client, ESG_EMPRESAS_INDEX):
        return {"disponivel": False, "motivo": "Ainda não há fotografias ESG no índice.", "n_pares": 0}
    filtros = [{"term": {"setor": setor}}, {"term": {"dimensao": dimensao}}]
    resposta = _search(
        client,
        ESG_EMPRESAS_INDEX,
        {
            "size": tax.MAX_PARES,
            "track_total_hits": False,
            "query": {"bool": {"filter": filtros, "must_not": [{"term": {"nif": _nif_limpo(nif)}}]}},
            "_source": ["nif", "name", "score", "pilares", "dimensao", "setor", "historico"],
        },
        timeout=60,
    )
    docs = [hit.get("_source") or {} for hit in _hits(resposta)]
    n_pares = len(docs)
    if n_pares < tax.MIN_PARES:
        return {
            "disponivel": False,
            "motivo": f"Amostra insuficiente: {n_pares} empresa(s) comparável(is); mínimo {tax.MIN_PARES}.",
            "n_pares": n_pares,
            "minimo": tax.MIN_PARES,
        }
    scores = [float(doc["score"]) for doc in docs if _to_float(doc.get("score")) is not None]
    percentil = _percentil(scores, float(score))
    mediana = _median(scores)
    # Quartis reais
    ordenados = sorted(scores)
    def _quartil(frac: float) -> float:
        posicao = (len(ordenados) - 1) * frac
        base = int(math.floor(posicao))
        resto = posicao - base
        if base + 1 < len(ordenados):
            return ordenados[base] * (1 - resto) + ordenados[base + 1] * resto
        return ordenados[base]

    mediana_pilares: Dict[str, Optional[float]] = {}
    for pilar in ("e", "s", "g"):
        mediana_pilares[pilar] = _round(_median([_to_float((doc.get("pilares") or {}).get(pilar)) for doc in docs]), 2)

    historico_pares: Dict[int, Optional[float]] = {}
    for ano in anos:
        valores = []
        for doc in docs:
            for entrada in doc.get("historico") or []:
                if _to_int(entrada.get("ano")) == int(ano) and _to_float(entrada.get("score")) is not None:
                    valores.append(float(entrada["score"]))
        historico_pares[int(ano)] = _round(_median(valores), 2)

    if percentil is not None and percentil >= 90:
        posicao = "Top 10%"
    elif percentil is not None and percentil >= 75:
        posicao = "Quartil superior"
    elif percentil is not None and percentil >= 50:
        posicao = "Acima da mediana"
    elif percentil is not None and percentil >= 25:
        posicao = "Abaixo da mediana"
    else:
        posicao = "Quartil inferior"

    return {
        "disponivel": True,
        "n_pares": n_pares,
        "percentil": _round(percentil, 1),
        "posicao": posicao,
        "mediana": _round(mediana, 2),
        "media": _round(sum(scores) / len(scores), 2),
        "p25": _round(_quartil(0.25), 2),
        "p75": _round(_quartil(0.75), 2),
        "mediana_pilares": mediana_pilares,
        "historico_pares": historico_pares,
        "setor": setor,
        "dimensao": dimensao,
        "nota": (
            f"Comparação com {n_pares} empresas do mesmo setor (CAE) e dimensão de carteira. "
            "O percentil é a posição do score dentro desse grupo (100 = melhor)."
        ),
    }


def calcular_empresa(
    *,
    nif: Optional[str] = None,
    nome: Optional[str] = None,
    pais: str = "PT",
    ano: Optional[int] = None,
    historico_anos: int = 3,
    max_contratos: int = MAX_CONTRATOS,
    indexar: bool = True,
    incluir_benchmark: bool = True,
    incluir_fornecedores: bool = False,
    use_cache: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Score, pilares, evolução, benchmark e evidências de uma empresa."""
    spec = _spec(pais)
    if spec is None:
        return {"error": f"país desconhecido: {pais}", "paises": list(padroes.COUNTRIES)}
    client = _client(es)
    if client is None:
        return {"error": "Elasticsearch indisponível"}

    nif_limpo = _nif_limpo(nif) if nif else ""
    if not nif_limpo and nome:
        candidatos = _resolver_cadastro(client, nome, size=1)
        if candidatos:
            nif_limpo = _nif_limpo(candidatos[0]["nif"])
    if not nif_limpo:
        return {"error": "Indique um NIF (ou um nome que resolva para uma empresa)."}

    chave = (spec.key, nif_limpo, ano, int(historico_anos), int(max_contratos), bool(incluir_benchmark), bool(incluir_fornecedores))
    if use_cache:
        with _CACHE_LOCK:
            entrada = _CACHE.get(chave)
        if entrada and time.time() - entrada[0] < CACHE_TTL_SECONDS:
            return {**entrada[1], "cache": True}

    cadastro = _cadastro(client, nif_limpo)
    empresa = _empresa_base(cadastro, nif_limpo, nome, spec.key)
    cae_info = _cae(client, nif_limpo)
    insolvencias = _insolvencias(client, nif_limpo)
    devedor = bool(cadastro.get("devedor"))

    ano_atual = datetime.now(timezone.utc).year
    anos_janela = max(1, min(int(historico_anos), 5))
    # Uma janela com um ano extra: se o ano de referência for o último com
    # contratos (e não o ano civil corrente), a série de 3 anos continua cheia.
    ano_to = int(ano) if ano else ano_atual
    ano_from = ano_to - anos_janela
    rows, total_contratos = _contracts(
        client,
        spec,
        nif_limpo,
        role="fornecedor",
        limit=max(50, min(int(max_contratos), MAX_CONTRATOS)),
        ano_from=ano_from,
        ano_to=ano_to,
    )

    anos_disponiveis = sorted({int(row["ano"]) for row in rows if row.get("ano") is not None}, reverse=True)
    ano_ref = int(ano) if ano else (anos_disponiveis[0] if anos_disponiveis else ano_atual)
    rows_ref = [row for row in rows if _to_int(row.get("ano")) == ano_ref]
    if not rows_ref:
        rows_ref = rows
        if rows:
            logger.debug("ESG: sem contratos em %s para %s; a usar a janela completa.", ano_ref, nif_limpo)

    features = features_de_contratos(
        rows_ref,
        insolvencias=len(insolvencias),
        devedor=devedor,
        devedores_escalao=cadastro.get("devedores_escalao"),
    )
    setor_info = _setor_e_dimensao(client, nif_limpo, cae_info, features)
    empresa.update(
        {
            "cae_principal": setor_info["cae_principal"],
            "cae_label": setor_info["cae_label"],
            "setor": setor_info["setor"],
            "setor_label": setor_info["setor_label"],
            "setor_fonte": setor_info["setor_fonte"],
            "dimensao": setor_info["dimensao"],
            "dimensao_label": setor_info["dimensao_label"],
            "roles": cadastro.get("roles") or [],
            "devedor": devedor,
            "devedores_escalao": cadastro.get("devedores_escalao"),
            "insolvencias": len(insolvencias),
            "contratos_registados": total_contratos,
        }
    )

    docs_indicadores = _docs_indicadores(client, nif_limpo, spec.key)
    valores_ref, detalhes_ref, fontes_ind = _valores_indicadores(docs_indicadores, ano_ref)
    indices_ref = indicadores_score(valores_ref)
    avaliacao = avaliar(features, indicadores=indices_ref)
    taxonomia = taxonomia_de_empresa(
        cae=setor_info.get("cae_principal"),
        setor=setor_info.get("setor"),
        valores=valores_ref,
        cpv_top=features.get("cpv_top"),
    )
    if rows and not any(_to_int(row.get("ano")) == ano_ref for row in rows):
        avaliacao["avisos"].append(
            f"Não há contratos em {ano_ref}; a leitura usa a janela de {anos_janela} anos e o ano de referência é indicativo."
        )

    # Série de 3 anos: a mesma função, com os contratos e indicadores do ano.
    historico: List[Dict[str, Any]] = []
    for ano_item in range(ano_ref, ano_ref - anos_janela, -1):
        rows_ano = [row for row in rows if _to_int(row.get("ano")) == ano_item]
        feats_ano = features_de_contratos(
            rows_ano,
            insolvencias=len(insolvencias),
            devedor=devedor,
            devedores_escalao=cadastro.get("devedores_escalao"),
        )
        valores_ano, _, _ = _valores_indicadores(docs_indicadores, ano_item)
        aval_ano = avaliar(feats_ano, indicadores=indicadores_score(valores_ano))
        historico.append(
            {
                "ano": ano_item,
                "score": aval_ano["score"],
                "nivel": aval_ano["nivel"],
                "nivel_label": aval_ano["nivel_label"],
                "cobertura": aval_ano["cobertura"],
                "pilares": aval_ano["pilares"],
                "contratos": feats_ano["contratos"],
                "valor": feats_ano["valor_total"],
                "n_indicadores": aval_ano["n_indicadores"],
            }
        )

    benchmark = (
        _benchmark(
            client,
            nif=nif_limpo,
            setor=setor_info["setor"],
            dimensao=setor_info["dimensao"],
            score=avaliacao["score"],
            pilares=avaliacao["pilares"],
            anos=[item["ano"] for item in historico],
        )
        if incluir_benchmark
        else {"disponivel": False, "motivo": "Benchmark não pedido."}
    )

    # Evidências: o que sustenta o número (amostra dos maiores contratos).
    evidencias = {
        "contratos": [
            {
                "id": row.get("id"),
                "ano": row.get("ano"),
                "objeto": row.get("objeto"),
                "valor": row.get("valor"),
                "data": row.get("data_publicacao"),
                "adjudicante": row.get("adjudicante_nome"),
                "cpv": row.get("cpv"),
                "cpv_desc": row.get("cpv_desc"),
                "procedimento": row.get("procedimento"),
                "ajuste_direto": bool(row.get("ajuste_direto")),
                "ecologico": bool(row.get("ecologico")),
                "n_concorrentes": row.get("n_concorrentes"),
                "dias_publicacao": row.get("dias_publicacao"),
            }
            for row in sorted(rows_ref, key=lambda item: float(item.get("valor") or 0), reverse=True)[:12]
        ],
        "cpv_top": features.get("cpv_top") or [],
        "compradores": _top_compradores(rows_ref),
        "insolvencias": insolvencias,
        "por_ano": features.get("por_ano") or [],
    }

    fornecedores = None
    if incluir_fornecedores:
        # A carteira de fornecedores vem dos contratos em que a empresa é
        # **compradora** — não dos contratos em que é adjudicatária.
        rows_comprador, _ = _contracts(
            client,
            spec,
            nif_limpo,
            role="comprador",
            limit=500,
            ano_from=ano_atual - 3,
            ano_to=ano_atual,
        )
        fornecedores = _fornecedores_de_rows(
            client,
            rows_comprador,
            nif=nif_limpo,
            nome=empresa["nome"],
            pais=spec.key,
            calcular_em_falta=False,
        )

    doc = {
        "nif": nif_limpo,
        "name": empresa["nome"],
        "name_keyword": empresa["nome"],
        "names": empresa.get("names") or [],
        "pais": spec.key,
        "cae_principal": empresa.get("cae_principal"),
        "cae_label": empresa.get("cae_label"),
        "setor": empresa.get("setor"),
        "setor_label": empresa.get("setor_label"),
        "setor_fonte": empresa.get("setor_fonte"),
        "dimensao": empresa.get("dimensao"),
        "dimensao_label": empresa.get("dimensao_label"),
        "score": avaliacao["score"],
        "nivel": avaliacao["nivel"],
        "nivel_label": avaliacao["nivel_label"],
        "cor": avaliacao["cor"],
        "cobertura": avaliacao["cobertura"],
        "confianca": avaliacao["confianca"],
        "pilares": avaliacao["pilares"],
        "contratos": features["contratos"],
        "valor": features["valor_total"],
        "adjudicantes": features["adjudicantes_distintos"],
        "fornecedores_count": (fornecedores or {}).get("resumo", {}).get("n_fornecedores") if fornecedores else None,
        "ano": ano_ref,
        "anos": anos_janela,
        "modelo_versao": tax.MODELO_VERSAO,
        "gerado_em": avaliacao["gerado_em"],
        "atualizado_em": _now(),
        "fontes": list(dict.fromkeys(["portal_base" if spec.key == "PT" else "placcp", "contribuintes", "entidades_cae", "cire", *fontes_ind])),
        "avisos": avaliacao["avisos"],
        "location": empresa.get("local") or {},
        "search_text": " ".join(
            filter(None, [empresa["nome"], empresa.get("cae_label"), empresa.get("setor_label"), nif_limpo, " ".join(empresa.get("names") or [])])
        ),
        "empresa": empresa,
        "score_detalhe": avaliacao,
        "pilares_detalhe": avaliacao["pilares_detalhe"],
        "componentes": avaliacao["componentes"],
        "historico": historico,
        "benchmark": benchmark,
        "indicadores": {
            "ano": ano_ref,
            "valores": detalhes_ref,
            "fontes": fontes_ind,
            "score": indices_ref,
            "catalogo_versao": tax.MODELO_VERSAO,
        },
        "evidencias": evidencias,
        "fornecedores": fornecedores,
        "taxonomia": taxonomia,
        "taxonomia_elegivel": bool(taxonomia.get("elegivel")),
        "taxonomia_alinhamento": taxonomia.get("alinhamento"),
        "taxonomia_nace": taxonomia.get("nace"),
        "taxonomia_objetivos": [int(item["id"]) for item in taxonomia.get("objetivos") or []],
        "taxonomia_atividades": [int(item["id"]) for item in taxonomia.get("atividades") or []],
        "taxonomia_cobertura_verificacao": taxonomia.get("cobertura_verificacao"),
        "ods": [int(item["id"]) for item in taxonomia.get("ods") or []],
    }

    if indexar:
        _garantir_indices(client)
        try:
            client.index(index=ESG_EMPRESAS_INDEX, id=f"{spec.key}-{nif_limpo}", document=doc, refresh=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ESG: não foi possível indexar %s: %s", nif_limpo, exc)
            doc["aviso_indexacao"] = str(exc)

    if use_cache:
        with _CACHE_LOCK:
            _CACHE[chave] = (time.time(), doc)

    return doc


def _top_compradores(rows: Sequence[Dict[str, Any]], limite: int = 8) -> List[Dict[str, Any]]:
    agregado: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        chave = str(row.get("adjudicante_nif") or row.get("adjudicante_nome") or "?")
        entrada = agregado.setdefault(
            chave,
            {"nif": row.get("adjudicante_nif"), "nome": row.get("adjudicante_nome"), "contratos": 0, "valor": 0.0},
        )
        entrada["contratos"] += 1
        entrada["valor"] += max(0.0, float(row.get("valor") or 0))
    total = sum(entrada["valor"] for entrada in agregado.values()) or 1.0
    return [
        {**entrada, "valor": _round(entrada["valor"], 2), "peso": _round(entrada["valor"] / total, 4)}
        for entrada in sorted(agregado.values(), key=lambda item: item["valor"], reverse=True)[:limite]
    ]


# ---------------------------------------------------------------------------
# Pesquisa, ranking e analítica
# ---------------------------------------------------------------------------
def _filtros_esg(
    *,
    q: Optional[str] = None,
    pais: Optional[str] = None,
    setor: Optional[str] = None,
    dimensao: Optional[str] = None,
    nivel: Optional[str] = None,
    ano: Optional[int] = None,
    score_min: Optional[float] = None,
    score_max: Optional[float] = None,
) -> List[Dict[str, Any]]:
    filtros: List[Dict[str, Any]] = []
    if pais:
        filtros.append({"term": {"pais": pais_codigo(pais)}})
    if setor:
        filtros.append({"term": {"setor": setor.upper()}})
    if dimensao:
        filtros.append({"term": {"dimensao": dimensao}})
    if nivel:
        filtros.append({"term": {"nivel": nivel}})
    if ano:
        filtros.append({"term": {"ano": int(ano)}})
    if score_min is not None or score_max is not None:
        intervalo: Dict[str, Any] = {}
        if score_min is not None:
            intervalo["gte"] = float(score_min)
        if score_max is not None:
            intervalo["lte"] = float(score_max)
        filtros.append({"range": {"score": intervalo}})
    if q and str(q).strip():
        texto = str(q).strip()
        filtros.append(
            {
                "bool": {
                    "should": [
                        {"term": {"nif": _nif_limpo(texto)}},
                        {"match_phrase": {"name": {"query": texto, "boost": 4}}},
                        {"multi_match": {"query": texto, "fields": ["name^3", "name_keyword^2", "search_text"], "type": "best_fields"}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    return filtros


def _ordenar_esg(ordenar: str, pilar: Optional[str] = None) -> List[Dict[str, Any]]:
    if ordenar in {"score", "pontuacao", "esg"}:
        return [{"score": {"order": "desc", "missing": "_last"}}, {"name_keyword": {"order": "asc", "missing": "_last"}}]
    if ordenar in {"score_asc", "pior"}:
        return [{"score": {"order": "asc", "missing": "_last"}}]
    if pilar in {"e", "s", "g"}:
        return [{f"pilares.{pilar}": {"order": "desc", "missing": "_last"}}, {"score": {"order": "desc", "missing": "_last"}}]
    if ordenar in {"valor", "contratos", "nome", "nome_asc"}:
        campo = {"valor": "valor", "contratos": "contratos", "nome": "name_keyword", "nome_asc": "name_keyword"}[ordenar]
        return [{campo: {"order": "desc" if campo != "name_keyword" else "asc", "missing": "_last"}}]
    return [{"_score": {"order": "desc"}}, {"score": {"order": "desc", "missing": "_last"}}]


def pesquisa(
    q: str,
    *,
    pais: Optional[str] = None,
    setor: Optional[str] = None,
    dimensao: Optional[str] = None,
    nivel: Optional[str] = None,
    ordenar: str = "relevancia",
    pilar: Optional[str] = None,
    size: int = 10,
    from_: int = 0,
    incluir_nao_indexadas: bool = True,
) -> Dict[str, Any]:
    """Pesquisa empresas no índice ESG; se faltarem, calcula as candidatas do cadastro."""
    client = _client()
    if client is None:
        return {"error": "Elasticsearch indisponível", "itens": [], "total": 0}
    texto = str(q or "").strip()
    if len(texto) < 2:
        return {"itens": [], "total": 0, "origem": "indice", "parcial": False}

    if _index_existe(client, ESG_EMPRESAS_INDEX):
        filtros = _filtros_esg(q=texto, pais=pais, setor=setor, dimensao=dimensao, nivel=nivel)
        corpo = {
            "size": max(1, min(int(size), 50)),
            "from": max(0, int(from_)),
            "track_total_hits": True,
            "query": {"bool": {"filter": filtros}},
            "sort": _ordenar_esg(ordenar, pilar),
            "_source": {
                "includes": ["nif", "name", "pais", "setor", "setor_label", "dimensao", "dimensao_label", "score", "nivel", "nivel_label", "cor", "cobertura", "confianca", "pilares", "contratos", "valor", "benchmark", "ano", "taxonomia_elegivel", "taxonomia_alinhamento", "taxonomia_objetivos", "ods"],
                "excludes": ["historico", "componentes", "evidencias", "fornecedores", "score_detalhe", "pilares_detalhe", "indicadores"],
            },
        }
        resposta = _search(client, ESG_EMPRESAS_INDEX, corpo, timeout=45)
        hits = _hits(resposta)
        if hits:
            itens = [_item_lista(hit.get("_source") or {}) for hit in hits]
            return {"itens": itens, "total": _total(resposta), "origem": "indice", "parcial": False}

    # Sem fotografia: resolver no cadastro e calcular ao vivo (limitado).
    if not incluir_nao_indexadas:
        return {"itens": [], "total": 0, "origem": "indice", "parcial": False, "motivo": "Sem fotografia ESG para esta pesquisa."}
    candidatos = _resolver_cadastro(client, texto, size=max(8, min(int(size) * 3, 24)))
    if pais:
        candidatos = [item for item in candidatos if item.get("pais") == pais_codigo(pais)]
    itens: List[Dict[str, Any]] = []
    for candidato in candidatos:
        if len(itens) >= max(1, min(int(size), 20)):
            break
        doc = calcular_empresa(
            nif=candidato["nif"],
            nome=candidato["nome"],
            pais=candidato.get("pais") or pais or "PT",
            historico_anos=3,
            indexar=True,
            incluir_benchmark=True,
            incluir_fornecedores=False,
            use_cache=True,
            es=client,
        )
        if doc.get("error"):
            continue
        if nivel and doc.get("nivel") != nivel:
            continue
        if setor and doc.get("setor") != setor.upper():
            continue
        if dimensao and doc.get("dimensao") != dimensao:
            continue
        itens.append(_item_lista(doc))
    itens.sort(key=lambda item: _ordem_item(item, ordenar, pilar))
    return {
        "itens": itens,
        "total": len(itens),
        "origem": "calculado",
        "parcial": len(candidatos) > len(itens),
        "nota": "Sem fotografia no índice: as empresas foram calculadas agora e guardadas para as próximas consultas.",
    }


def _item_lista(src: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "nif": src.get("nif"),
        "nome": src.get("name"),
        "pais": src.get("pais"),
        "setor": src.get("setor"),
        "setor_label": src.get("setor_label"),
        "dimensao": src.get("dimensao"),
        "dimensao_label": src.get("dimensao_label"),
        "score": src.get("score"),
        "nivel": src.get("nivel"),
        "nivel_label": src.get("nivel_label"),
        "cor": src.get("cor"),
        "cobertura": src.get("cobertura"),
        "confianca": src.get("confianca"),
        "pilares": src.get("pilares") or {},
        "contratos": src.get("contratos"),
        "valor": src.get("valor"),
        "ano": src.get("ano"),
        "benchmark": src.get("benchmark"),
        "taxonomia_elegivel": src.get("taxonomia_elegivel"),
        "taxonomia_alinhamento": src.get("taxonomia_alinhamento"),
        "taxonomia_objetivos": src.get("taxonomia_objetivos") or [],
        "ods": src.get("ods") or [],
    }


def _ordem_item(item: Dict[str, Any], ordenar: str, pilar: Optional[str]) -> Any:
    if ordenar in {"score", "score_asc", "pior"}:
        valor = item.get("score")
        return (valor is None, valor if ordenar != "score_asc" else -(valor or 0))
    if pilar in {"e", "s", "g"}:
        valor = (item.get("pilares") or {}).get(pilar)
        return (valor is None, -(valor or 0))
    if ordenar == "valor":
        return (item.get("valor") is None, -(item.get("valor") or 0))
    if ordenar == "contratos":
        return (item.get("contratos") is None, -(item.get("contratos") or 0))
    if ordenar in {"nome", "nome_asc"}:
        return str(item.get("nome") or "").lower()
    return -(item.get("score") or 0)


def sugestoes(q: str, *, size: int = 8) -> Dict[str, Any]:
    client = _client()
    if client is None:
        return {"error": "Elasticsearch indisponível", "sugestoes": []}
    if len(str(q or "").strip()) < 2:
        return {"sugestoes": []}
    candidatos = _resolver_cadastro(client, q, size=size)
    return {"sugestoes": candidatos}


def ranking(
    *,
    pais: Optional[str] = None,
    setor: Optional[str] = None,
    dimensao: Optional[str] = None,
    nivel: Optional[str] = None,
    ano: Optional[int] = None,
    ordenar: str = "score",
    pilar: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
) -> Dict[str, Any]:
    client = _client()
    if client is None:
        return {"error": "Elasticsearch indisponível", "itens": [], "total": 0}
    if not _index_existe(client, ESG_EMPRESAS_INDEX):
        return {"itens": [], "total": 0, "motivo": "Ainda não há fotografias ESG no índice."}
    filtros = _filtros_esg(pais=pais, setor=setor, dimensao=dimensao, nivel=nivel, ano=ano)
    corpo = {
        "size": max(1, min(int(size), 100)),
        "from": max(0, int(from_)),
        "track_total_hits": True,
        "query": {"bool": {"filter": filtros}},
        "sort": _ordenar_esg(ordenar, pilar),
        "_source": {
            "includes": ["nif", "name", "pais", "setor", "setor_label", "dimensao", "dimensao_label", "score", "nivel", "nivel_label", "cor", "cobertura", "confianca", "pilares", "contratos", "valor", "ano", "benchmark", "taxonomia_elegivel", "taxonomia_alinhamento", "taxonomia_objetivos", "ods"],
            "excludes": ["historico", "componentes", "evidencias", "fornecedores", "score_detalhe", "pilares_detalhe", "indicadores"],
        },
    }
    resposta = _search(client, ESG_EMPRESAS_INDEX, corpo, timeout=45)
    itens = [_item_lista(hit.get("_source") or {}) for hit in _hits(resposta)]
    base = max(0, int(from_))
    for indice, item in enumerate(itens):
        item["posicao"] = base + indice + 1
    return {
        "itens": itens,
        "total": _total(resposta),
        "ordenar": ordenar,
        "pilar": pilar,
        "filtros": {"pais": pais, "setor": setor, "dimensao": dimensao, "nivel": nivel, "ano": ano},
    }


def analitica(
    *,
    pais: Optional[str] = None,
    setor: Optional[str] = None,
    dimensao: Optional[str] = None,
    nivel: Optional[str] = None,
    ano: Optional[int] = None,
    q: Optional[str] = None,
) -> Dict[str, Any]:
    client = _client()
    if client is None:
        return {"error": "Elasticsearch indisponível", "disponivel": False}
    if not _index_existe(client, ESG_EMPRESAS_INDEX):
        return {
            "disponivel": False,
            "total": 0,
            "motivo": "Ainda não há empresas no índice ESG.",
            "como_popular": "Pesquise uma empresa em «Empresas» ou execute o cálculo em lote (POST /esg/calcular).",
        }
    filtros = _filtros_esg(q=q, pais=pais, setor=setor, dimensao=dimensao, nivel=nivel, ano=ano)
    corpo = {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"filter": filtros}},
        "aggs": {
            "media_score": {"avg": {"field": "score"}},
            "media_cobertura": {"avg": {"field": "cobertura"}},
            "media_e": {"avg": {"field": "pilares.e"}},
            "media_s": {"avg": {"field": "pilares.s"}},
            "media_g": {"avg": {"field": "pilares.g"}},
            "ultima": {"max": {"field": "gerado_em"}},
            "niveis": {"terms": {"field": "nivel", "size": 10}, "aggs": {"score": {"avg": {"field": "score"}}}},
            "setores": {
                "terms": {"field": "setor_label", "size": 15},
                "aggs": {"score": {"avg": {"field": "score"}}, "cobertura": {"avg": {"field": "cobertura"}}},
            },
            "dimensoes": {"terms": {"field": "dimensao_label", "size": 10}, "aggs": {"score": {"avg": {"field": "score"}}}},
            "distritos": {"terms": {"field": "location.distrito", "size": 15}, "aggs": {"score": {"avg": {"field": "score"}}}},
            "anos": {"terms": {"field": "ano", "size": 10}, "aggs": {"score": {"avg": {"field": "score"}}}},
            "taxonomia_alinhamento": {"terms": {"field": "taxonomia_alinhamento", "size": 10}},
            "taxonomia_objetivos": {"terms": {"field": "taxonomia_objetivos", "size": 10}},
            "taxonomia_elegivel": {"terms": {"field": "taxonomia_elegivel", "size": 2}},
            "ods": {"terms": {"field": "ods", "size": 17}},
        },
    }
    resposta = _search(client, ESG_EMPRESAS_INDEX, corpo, timeout=60)
    if resposta.get("error"):
        return {"disponivel": False, "motivo": resposta.get("error"), "total": 0}
    total = _total(resposta)
    if total == 0:
        return {
            "disponivel": False,
            "total": 0,
            "motivo": "Ainda não há empresas no índice ESG.",
            "como_popular": "Pesquise uma empresa em «Empresas» ou execute o cálculo em lote (POST /esg/calcular).",
        }
    aggs = resposta.get("aggregations") or {}

    def _buckets(nome: str) -> List[Dict[str, Any]]:
        return list(((aggs.get(nome) or {}).get("buckets") or []))

    media_score = (aggs.get("media_score") or {}).get("value")
    destaques_positivos = ranking(pais=pais, setor=setor, dimensao=dimensao, nivel=nivel, ano=ano, ordenar="score", size=8)["itens"] if total else []
    destaques_negativos = ranking(pais=pais, setor=setor, dimensao=dimensao, nivel=nivel, ano=ano, ordenar="score_asc", size=8)["itens"] if total else []

    alinhamento_buckets = _buckets("taxonomia_alinhamento")
    avaliadas = sum(int(bucket.get("doc_count") or 0) for bucket in alinhamento_buckets)
    mapa_alinhamento = {
        "sem_dados": "Sem dados para avaliar",
        "nao_elegivel": "Sem atividade elegível identificada",
        "elegivel_nao_verificado": "Elegível — alinhamento por verificar",
    }
    objetivos_buckets = _buckets("taxonomia_objetivos")
    ods_buckets = _buckets("ods")
    taxonomia = {
        "avaliadas": avaliadas,
        "sem_dados": max(0, total - avaliadas),
        "elegiveis": next(
            (int(bucket.get("doc_count") or 0) for bucket in _buckets("taxonomia_elegivel") if bucket.get("key") in (True, 1, "true")),
            0,
        ),
        "alinhamento": [
            {
                "id": bucket.get("key"),
                "label": mapa_alinhamento.get(str(bucket.get("key")), str(bucket.get("key"))),
                "n": bucket.get("doc_count"),
            }
            for bucket in alinhamento_buckets
        ],
        "objetivos": [
            {
                "id": int(bucket.get("key")),
                "label": (tax_eu.OBJETIVO_BY_ID.get(int(bucket.get("key"))) or {}).get("label") or f"Objetivo {bucket.get('key')}",
                "curto": (tax_eu.OBJETIVO_BY_ID.get(int(bucket.get("key"))) or {}).get("curto") or f"Objetivo {bucket.get('key')}",
                "cor": (tax_eu.OBJETIVO_BY_ID.get(int(bucket.get("key"))) or {}).get("cor") or "#94a3b8",
                "n": bucket.get("doc_count"),
            }
            for bucket in objetivos_buckets
            if str(bucket.get("key")).isdigit()
        ],
        "ods": [
            {
                "id": int(bucket.get("key")),
                "label": next((item["label"] for item in tax_eu.ODS if item["id"] == int(bucket.get("key"))), f"ODS {bucket.get('key')}"),
                "cor": next((item.get("cor") for item in tax_eu.ODS if item["id"] == int(bucket.get("key"))), "#94a3b8"),
                "n": bucket.get("doc_count"),
            }
            for bucket in ods_buckets
            if str(bucket.get("key")).isdigit()
        ],
        "fonte": tax_eu.FONTE,
    }

    return {
        "disponivel": True,
        "total": total,
        "media_score": _round(media_score, 2),
        "media_cobertura": _round((aggs.get("media_cobertura") or {}).get("value"), 4),
        "media_pilares": {
            "e": _round((aggs.get("media_e") or {}).get("value"), 2),
            "s": _round((aggs.get("media_s") or {}).get("value"), 2),
            "g": _round((aggs.get("media_g") or {}).get("value"), 2),
        },
        "ultima_atualizacao": (aggs.get("ultima") or {}).get("value_as_string"),
        "niveis": [
            {
                "id": bucket.get("key"),
                "label": next((item["label"] for item in tax.NIVEIS if item["id"] == bucket.get("key")), bucket.get("key")),
                "cor": next((item["cor"] for item in tax.NIVEIS if item["id"] == bucket.get("key")), "#94a3b8"),
                "n": bucket.get("doc_count"),
                "score_medio": _round((bucket.get("score") or {}).get("value"), 2),
            }
            for bucket in _buckets("niveis")
        ],
        "setores": [
            {
                "setor": bucket.get("key"),
                "n": bucket.get("doc_count"),
                "score_medio": _round((bucket.get("score") or {}).get("value"), 2),
                "cobertura_media": _round((bucket.get("cobertura") or {}).get("value"), 4),
            }
            for bucket in _buckets("setores")
        ],
        "dimensoes": [
            {"dimensao": bucket.get("key"), "n": bucket.get("doc_count"), "score_medio": _round((bucket.get("score") or {}).get("value"), 2)}
            for bucket in _buckets("dimensoes")
        ],
        "distritos": [
            {"distrito": bucket.get("key"), "n": bucket.get("doc_count"), "score_medio": _round((bucket.get("score") or {}).get("value"), 2)}
            for bucket in _buckets("distritos")
        ],
        "anos": [
            {"ano": bucket.get("key"), "n": bucket.get("doc_count"), "score_medio": _round((bucket.get("score") or {}).get("value"), 2)}
            for bucket in _buckets("anos")
        ],
        "destaques_positivos": destaques_positivos,
        "destaques_negativos": destaques_negativos,
        "taxonomia": taxonomia,
        "filtros": {"pais": pais, "setor": setor, "dimensao": dimensao, "nivel": nivel, "ano": ano, "q": q},
    }


def _agregar_mapa(docs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Converte fotografias ESG em pontos por empresa e agregados por região.

    Função pura (sem Elasticsearch), para poder ser testada. A região é o
    `location.distrito` do cadastro — o mesmo campo que o painel agrega. Uma
    empresa sem distrito conta para `sem_localizacao`: nunca é colocada num sítio
    inventado (tal como os mapas de contratos, que só marcam posições conhecidas).
    """
    empresas: List[Dict[str, Any]] = []
    regioes: Dict[tuple, Dict[str, Any]] = {}
    sem_localizacao = 0

    for doc in docs:
        local = doc.get("location") or {}
        if not isinstance(local, Mapping):
            local = {}
        nif = str(doc.get("nif") or "").strip()
        if not nif:
            continue
        distrito = str(local.get("distrito") or "").strip()
        concelho = str(local.get("concelho") or "").strip()
        if padroes.fold(distrito) in DISTRITOS_NAO_GEOGRAFICOS:
            distrito = ""
        pais = pais_codigo(doc.get("pais") or local.get("pais") or "PT")
        score = _to_float(doc.get("score"))
        cobertura = _to_float(doc.get("cobertura"))
        empresa = {
            "nif": nif,
            "nome": doc.get("name") or nif,
            "pais": pais,
            "distrito": distrito or None,
            "concelho": concelho or None,
            "score": _round(score),
            "nivel": doc.get("nivel"),
            "nivel_label": doc.get("nivel_label"),
            "cor": doc.get("cor"),
            "cobertura": _round(cobertura),
            "setor_label": doc.get("setor_label"),
            "dimensao_label": doc.get("dimensao_label"),
            "valor": _to_float(doc.get("valor")),
            "contratos": _to_int(doc.get("contratos")),
        }
        empresas.append(empresa)
        if not distrito:
            sem_localizacao += 1
            continue

        chave = (pais, distrito)
        regiao = regioes.get(chave)
        if regiao is None:
            regiao = {
                "pais": pais,
                "distrito": distrito,
                "n": 0,
                "soma_score": 0.0,
                "com_score": 0,
                "soma_cobertura": 0.0,
                "com_cobertura": 0,
                "valor": 0.0,
                "niveis": {},
                "empresas": [],
            }
            regioes[chave] = regiao
        regiao["n"] += 1
        regiao["empresas"].append(nif)
        regiao["valor"] += empresa["valor"] or 0.0
        if score is not None:
            regiao["soma_score"] += score
            regiao["com_score"] += 1
        if cobertura is not None:
            regiao["soma_cobertura"] += cobertura
            regiao["com_cobertura"] += 1
        if empresa["nivel"]:
            atual = regiao["niveis"].setdefault(
                empresa["nivel"], {"id": empresa["nivel"], "label": empresa["nivel_label"] or empresa["nivel"], "cor": empresa["cor"], "n": 0}
            )
            atual["n"] += 1

    lista_regioes: List[Dict[str, Any]] = []
    for regiao in regioes.values():
        n = regiao["n"]
        niveis = sorted(regiao["niveis"].values(), key=lambda item: (-item["n"], item["id"]))
        dominante = niveis[0] if niveis else None
        lista_regioes.append(
            {
                "pais": regiao["pais"],
                "distrito": regiao["distrito"],
                "n": n,
                "score_medio": _round(regiao["soma_score"] / regiao["com_score"]) if regiao["com_score"] else None,
                "cobertura_media": _round(regiao["soma_cobertura"] / regiao["com_cobertura"], 4) if regiao["com_cobertura"] else None,
                "valor": _round(regiao["valor"], 2),
                "nivel": dominante["id"] if dominante else None,
                "nivel_label": dominante["label"] if dominante else None,
                "cor": dominante["cor"] if dominante else "#94a3b8",
                "niveis": niveis,
                "empresas": regiao["empresas"],
            }
        )
    lista_regioes.sort(key=lambda item: (-item["n"], -(item["score_medio"] or 0)))

    return {
        "empresas": empresas,
        "regioes": lista_regioes,
        "com_localizacao": len(empresas) - sem_localizacao,
        "sem_localizacao": sem_localizacao,
    }


def mapa(
    *,
    pais: Optional[str] = None,
    setor: Optional[str] = None,
    dimensao: Optional[str] = None,
    nivel: Optional[str] = None,
    ano: Optional[int] = None,
    q: Optional[str] = None,
    limite: int = 1_000,
) -> Dict[str, Any]:
    """Pontos por empresa (score e nível) e agregado por região, para o mapa."""
    client = _client()
    if client is None:
        return {"error": "Elasticsearch indisponível", "disponivel": False}
    if not _index_existe(client, ESG_EMPRESAS_INDEX):
        return {
            "disponivel": False,
            "total": 0,
            "motivo": "Ainda não há empresas no índice ESG.",
            "como_popular": "Pesquise uma empresa em «Empresas» ou execute o cálculo em lote (POST /esg/calcular).",
        }
    filtros = _filtros_esg(q=q, pais=pais, setor=setor, dimensao=dimensao, nivel=nivel, ano=ano)
    corpo = {
        "size": max(1, min(int(limite), 3_000)),
        "track_total_hits": True,
        "query": {"bool": {"filter": filtros}},
        "sort": [{"score": {"order": "desc", "missing": "_last"}}],
        "_source": {
            "includes": [
                "nif",
                "name",
                "pais",
                "score",
                "nivel",
                "nivel_label",
                "cor",
                "cobertura",
                "location",
                "setor_label",
                "dimensao_label",
                "valor",
                "contratos",
            ],
            "excludes": [
                "historico",
                "componentes",
                "evidencias",
                "fornecedores",
                "score_detalhe",
                "pilares_detalhe",
                "indicadores",
                "empresa",
                "search_text",
            ],
        },
    }
    resposta = _search(client, ESG_EMPRESAS_INDEX, corpo, timeout=60)
    if resposta.get("error"):
        return {"disponivel": False, "motivo": resposta.get("error"), "total": 0}
    total = _total(resposta)
    agregado = _agregar_mapa([hit.get("_source") or {} for hit in _hits(resposta)])
    return {
        "disponivel": total > 0,
        "total": total,
        "motivo": None if total else "Ainda não há empresas no índice ESG.",
        "truncado": total > len(agregado["empresas"]),
        **agregado,
        "filtros": {"pais": pais, "setor": setor, "dimensao": dimensao, "nivel": nivel, "ano": ano, "q": q},
    }


def empresa_detalhe(
    *,
    nif: str,
    pais: str = "PT",
    ano: Optional[int] = None,
    historico_anos: int = 3,
    incluir_fornecedores: bool = True,
    indexar: bool = True,
) -> Dict[str, Any]:
    doc = calcular_empresa(
        nif=nif,
        pais=pais,
        ano=ano,
        historico_anos=historico_anos,
        indexar=indexar,
        incluir_benchmark=True,
        incluir_fornecedores=incluir_fornecedores,
    )
    if doc.get("error"):
        return doc
    doc["cartao_modelo"] = tax.cartao_modelo()
    return doc


def historico_empresa(*, nif: str, pais: str = "PT", anos: int = 3) -> Dict[str, Any]:
    doc = calcular_empresa(nif=nif, pais=pais, historico_anos=anos, indexar=True, incluir_benchmark=True)
    if doc.get("error"):
        return doc
    return {
        "empresa": doc.get("empresa"),
        "ano": doc.get("ano"),
        "historico": doc.get("historico") or [],
        "benchmark": doc.get("benchmark") or {},
        "pilares": doc.get("pilares") or {},
        "score": doc.get("score"),
        "nivel": doc.get("nivel"),
        "nivel_label": doc.get("nivel_label"),
        "cobertura": doc.get("cobertura"),
        "confianca": doc.get("confianca"),
        "avisos": doc.get("avisos") or [],
        "cartao_modelo": tax.cartao_modelo(),
    }


# ---------------------------------------------------------------------------
# Carteira de fornecedores
# ---------------------------------------------------------------------------
def _fornecedores_de_rows(
    client: Elasticsearch,
    rows: Sequence[Dict[str, Any]],
    *,
    nif: str,
    nome: Optional[str],
    pais: str = "PT",
    calcular_em_falta: bool = True,
    max_calcular: int = 12,
) -> Dict[str, Any]:
    """Agrega os fornecedores dos contratos em que a empresa é compradora."""
    agregado: Dict[str, Dict[str, Any]] = {}
    valor_total = 0.0
    for row in rows:
        fornecedores = [item for item in (row.get("adjudicatarios") or []) if isinstance(item, dict)]
        fornecedores = [item for item in fornecedores if item.get("nif") or item.get("nome")]
        if not fornecedores:
            continue
        valor = max(0.0, float(row.get("valor") or 0))
        valor_total += valor
        valor_imputado = valor / len(fornecedores)
        for item in fornecedores:
            chave = _nif_limpo(item.get("nif")) or padroes.fold(str(item.get("nome") or "?"))
            entrada = agregado.setdefault(
                chave,
                {
                    "nif": _nif_limpo(item.get("nif")) or None,
                    "nome": item.get("nome") or item.get("nif") or "Fornecedor sem nome",
                    "contratos": 0,
                    "valor": 0.0,
                    "ultima_data": None,
                    "cpvs": {},
                    "ecologicos": 0,
                    "ajuste_direto": 0,
                    "sociais": 0,
                },
            )
            entrada["contratos"] += 1
            entrada["valor"] += valor_imputado
            data = row.get("data_publicacao")
            if data and (entrada["ultima_data"] is None or str(data) > str(entrada["ultima_data"])):
                entrada["ultima_data"] = data
            cpv = row.get("cpv")
            if cpv:
                entrada["cpvs"][str(cpv)] = entrada["cpvs"].get(str(cpv), 0) + 1
            if row.get("ecologico"):
                entrada["ecologicos"] += 1
            if row.get("ajuste_direto"):
                entrada["ajuste_direto"] += 1
            divisao = _cpv_divisao(cpv)
            if divisao in tax.CPV_SOCIAL:
                entrada["sociais"] += 1

    fornecedores = sorted(agregado.values(), key=lambda item: item["valor"], reverse=True)[:MAX_FORNECEDORES]
    # Fotografias ESG já existentes.
    nifs = [item["nif"] for item in fornecedores if item.get("nif")]
    snapshots: Dict[str, Dict[str, Any]] = {}
    if nifs and _index_existe(client, ESG_EMPRESAS_INDEX):
        resposta = _search(
            client,
            ESG_EMPRESAS_INDEX,
            {
                "size": min(len(nifs), 500),
                "track_total_hits": False,
                "query": {"terms": {"nif": nifs}},
                "_source": ["nif", "score", "nivel", "nivel_label", "cor", "pilares", "cobertura", "dimensao", "dimensao_label", "setor", "setor_label", "ano"],
            },
            timeout=45,
        )
        snapshots = {str(hit.get("_source", {}).get("nif")): hit.get("_source") or {} for hit in _hits(resposta)}

    em_falta = [item for item in fornecedores if item.get("nif") and str(item["nif"]) not in snapshots]
    if calcular_em_falta and em_falta:
        alvos_fornecedores = em_falta[: max(0, min(int(max_calcular), 30))]

        def _calcular_fornecedor(item: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
            doc = calcular_empresa(
                nif=item["nif"],
                nome=item["nome"],
                pais=pais,
                historico_anos=1,
                indexar=True,
                incluir_benchmark=False,
                incluir_fornecedores=False,
                use_cache=True,
                es=client,
            )
            return str(item["nif"]), doc

        # Em paralelo: uma carteira de 12 fornecedores não pode custar 12
        # consultas sequenciais (o pedido ficava com dezenas de segundos).
        with ThreadPoolExecutor(max_workers=6) as pool:
            futuros = {pool.submit(_calcular_fornecedor, item): item for item in alvos_fornecedores}
            for futuro in as_completed(futuros):
                item = futuros[futuro]
                try:
                    chave, doc = futuro.result()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("ESG: fornecedor %s não calculado: %s", item.get("nif"), exc)
                    continue
                if not doc.get("error"):
                    snapshots[chave] = doc

    for item in fornecedores:
        snap = snapshots.get(str(item.get("nif"))) or {}
        item["score"] = snap.get("score")
        item["nivel"] = snap.get("nivel")
        item["nivel_label"] = snap.get("nivel_label")
        item["cor"] = snap.get("cor")
        item["pilares"] = snap.get("pilares") or {}
        item["cobertura"] = snap.get("cobertura")
        item["dimensao"] = snap.get("dimensao")
        item["dimensao_label"] = snap.get("dimensao_label")
        item["setor"] = snap.get("setor")
        item["setor_label"] = snap.get("setor_label")
        item["ano"] = snap.get("ano")
        item["cpv_principal"] = max(item["cpvs"].items(), key=lambda pair: pair[1])[0] if item["cpvs"] else None
        item["cpvs"] = [
            {"cpv": code, "contratos": n}
            for code, n in sorted(item["cpvs"].items(), key=lambda pair: pair[1], reverse=True)[:5]
        ]
        item["peso"] = _round(item["valor"] / valor_total, 4) if valor_total else None
        item["valor"] = _round(item["valor"], 2)
        item["tem_score"] = item["score"] is not None
        item["taxa_ecologicos"] = _round(item["ecologicos"] / item["contratos"], 4) if item["contratos"] else None
        item["taxa_ajuste_direto"] = _round(item["ajuste_direto"] / item["contratos"], 4) if item["contratos"] else None
        item["taxa_sociais"] = _round(item["sociais"] / item["contratos"], 4) if item["contratos"] else None

    # Distribuições
    distribuicao_nivel: Dict[str, Dict[str, Any]] = {}
    for item in fornecedores:
        chave = item.get("nivel") or "sem_score"
        entrada = distribuicao_nivel.setdefault(
            chave,
            {
                "id": chave,
                "label": item.get("nivel_label") or ("Sem score" if chave == "sem_score" else chave),
                "cor": item.get("cor") or "#94a3b8",
                "n": 0,
                "valor": 0.0,
            },
        )
        entrada["n"] += 1
        entrada["valor"] += float(item.get("valor") or 0)
    total_fornecedores = len(fornecedores)
    for entrada in distribuicao_nivel.values():
        entrada["peso_n"] = _round(entrada["n"] / total_fornecedores, 4) if total_fornecedores else None
        entrada["peso_valor"] = _round(entrada["valor"] / valor_total, 4) if valor_total else None
        entrada["valor"] = _round(entrada["valor"], 2)

    valores_com_score = [float(item["valor"] or 0) for item in fornecedores if item.get("score") is not None]
    score_medio = (
        sum(float(item["score"]) * float(item["valor"] or 0) for item in fornecedores if item.get("score") is not None)
        / sum(valores_com_score)
        if valores_com_score
        else None
    )
    top10 = sum(float(item.get("valor") or 0) for item in fornecedores[:10])
    sem_score = sum(1 for item in fornecedores if item.get("score") is None)
    fracos = [item for item in fornecedores if item.get("nivel") in {"inicial", "fraco"}]

    resumo = {
        "n_fornecedores": total_fornecedores,
        "valor_total": _round(valor_total, 2),
        "valor_com_score": _round(sum(valores_com_score), 2),
        "cobertura_score": _round(sum(valores_com_score) / valor_total, 4) if valor_total else None,
        "score_medio_ponderado": _round(score_medio, 2),
        "top10_peso": _round(top10 / valor_total, 4) if valor_total else None,
        "n_sem_score": sem_score,
        "n_fracos": len(fracos),
    }
    alertas: List[str] = []
    if total_fornecedores == 0:
        alertas.append("A empresa não tem contratos como comprador (ou os fornecedores não estão identificados no portal).")
    elif resumo["top10_peso"] and resumo["top10_peso"] > 0.6:
        alertas.append(f"Concentração elevada: os 10 maiores fornecedores valem {resumo['top10_peso'] * 100:.0f}% do valor.")
    if sem_score:
        alertas.append(f"{sem_score} fornecedor(es) ainda sem score ESG (calcule-os no dossiê ou no lote).")
    if fracos:
        alertas.append(f"{len(fracos)} fornecedor(es) em nível Inicial/Frágil — prioridade de diálogo ESG.")

    return {
        "comprador": {"nif": _nif_limpo(nif), "nome": nome},
        "resumo": resumo,
        "distribuicao": {"niveis": sorted(distribuicao_nivel.values(), key=lambda item: item["n"])},
        "fornecedores": fornecedores[:100],
        "alertas": alertas,
        "metodologia": (
            "O valor de cada contrato é repartido igualmente pelos fornecedores identificados; "
            "o score de cada fornecedor vem da fotografia ESG mais recente (ou é calculado a pedido). "
            "Sem score, o fornecedor entra na distribuição como «sem score» — não como zero."
        ),
        "gerado_em": _now(),
    }


def fornecedores_da_empresa(
    *,
    nif: str,
    pais: str = "PT",
    limite: int = 500,
    calcular_em_falta: bool = True,
    max_calcular: int = 12,
) -> Dict[str, Any]:
    spec = _spec(pais)
    if spec is None:
        return {"error": f"país desconhecido: {pais}"}
    client = _client()
    if client is None:
        return {"error": "Elasticsearch indisponível"}
    cadastro = _cadastro(client, nif)
    rows, total = _contracts(
        client,
        spec,
        nif,
        role="comprador",
        limit=max(20, min(int(limite), 2_000)),
        ano_from=datetime.now(timezone.utc).year - 3,
    )
    payload = _fornecedores_de_rows(
        client,
        rows,
        nif=nif,
        nome=cadastro.get("name") or nif,
        pais=spec.key,
        calcular_em_falta=calcular_em_falta,
        max_calcular=max_calcular,
    )
    payload["contratos_lidos"] = len(rows)
    payload["contratos_registados"] = total
    payload["cache"] = False
    return payload


def carteira_analise(
    *,
    nifs: Sequence[str] = (),
    nomes: Sequence[str] = (),
    pais: str = "PT",
    calcular_em_falta: bool = True,
) -> Dict[str, Any]:
    client = _client()
    if client is None:
        return {"error": "Elasticsearch indisponível", "itens": []}
    alvos: List[Dict[str, Any]] = []
    for nif in nifs:
        if _nif_limpo(nif):
            alvos.append({"nif": _nif_limpo(nif), "nome": None, "pais": pais})
    for nome in nomes:
        candidatos = _resolver_cadastro(client, nome, size=1)
        if candidatos:
            alvos.append({"nif": candidatos[0]["nif"], "nome": candidatos[0]["nome"], "pais": candidatos[0].get("pais") or pais})
    # Remover duplicados
    vistos: set = set()
    alvos = [item for item in alvos if not (item["nif"] in vistos or vistos.add(item["nif"]))][:50]
    if not alvos:
        return {"itens": [], "resumo": {"n": 0}, "alertas": ["Indique NIFs ou nomes de fornecedores."]}

    def _calcular(alvo: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return calcular_empresa(
                nif=alvo["nif"],
                nome=alvo.get("nome"),
                pais=alvo.get("pais") or pais,
                historico_anos=1,
                indexar=True,
                incluir_benchmark=False,
                incluir_fornecedores=False,
                use_cache=True,
                es=client,
            )
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "nif": alvo["nif"]}

    itens: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futuros = {pool.submit(_calcular, alvo): alvo for alvo in alvos}
        for futuro in as_completed(futuros):
            doc = futuro.result()
            if doc.get("error"):
                itens.append({"nif": futuros[futuro]["nif"], "nome": futuros[futuro].get("nome"), "erro": doc["error"], "score": None})
                continue
            itens.append(
                {
                    "nif": doc.get("nif"),
                    "nome": doc.get("name"),
                    "pais": doc.get("pais"),
                    "setor": doc.get("setor"),
                    "setor_label": doc.get("setor_label"),
                    "dimensao": doc.get("dimensao"),
                    "dimensao_label": doc.get("dimensao_label"),
                    "score": doc.get("score"),
                    "nivel": doc.get("nivel"),
                    "nivel_label": doc.get("nivel_label"),
                    "cor": doc.get("cor"),
                    "pilares": doc.get("pilares"),
                    "cobertura": doc.get("cobertura"),
                    "confianca": doc.get("confianca"),
                    "contratos": doc.get("contratos"),
                    "valor": doc.get("valor"),
                }
            )

    itens.sort(key=lambda item: (item.get("score") is None, -(item.get("score") or 0)))
    com_score = [item for item in itens if item.get("score") is not None]
    media = sum(float(item["score"]) for item in com_score) / len(com_score) if com_score else None
    distribuicao: Dict[str, int] = {}
    for item in itens:
        chave = item.get("nivel") or "sem_score"
        distribuicao[chave] = distribuicao.get(chave, 0) + 1
    alertas = []
    if len(itens) < len(alvos):
        alertas.append("Alguns fornecedores não puderam ser calculados (ver a coluna de erro).")
    if any(item.get("nivel") in {"inicial", "fraco"} for item in itens):
        alertas.append("Há fornecedores em nível Inicial/Frágil — prioridade de diálogo ESG.")
    return {
        "itens": itens,
        "resumo": {
            "n": len(itens),
            "com_score": len(com_score),
            "score_medio": _round(media, 2),
            "cobertura_media": _round(sum(float(item.get("cobertura") or 0) for item in com_score) / len(com_score), 4) if com_score else None,
            "distribuicao": [
                {
                    "id": chave,
                    "label": next((nivel["label"] for nivel in tax.NIVEIS if nivel["id"] == chave), "Sem score"),
                    "cor": next((nivel["cor"] for nivel in tax.NIVEIS if nivel["id"] == chave), "#94a3b8"),
                    "n": n,
                }
                for chave, n in sorted(distribuicao.items(), key=lambda pair: pair[1], reverse=True)
            ],
        },
        "alertas": alertas,
        "gerado_em": _now(),
        "metodologia": "Cada fornecedor é pontuado com o mesmo motor ESG do dossiê (dados abertos + indicadores declarados).",
    }


# ---------------------------------------------------------------------------
# Ingestão de indicadores e cálculo em lote
# ---------------------------------------------------------------------------
def _registar_recolha(client: Elasticsearch, recolha: Dict[str, Any]) -> None:
    _garantir_indices(client)
    try:
        client.index(index=ESG_RECOLHAS_INDEX, id=recolha["run_id"], document=recolha, refresh=False)
    except Exception as exc:  # noqa: BLE001
        logger.debug("ESG: não foi possível registar a execução: %s", exc)


def ingerir_indicadores(payload: Dict[str, Any], *, user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Guarda os indicadores declarados de um relatório (valida códigos e valores)."""
    client = _client()
    if client is None:
        return {"error": "Elasticsearch indisponível"}
    nif = _nif_limpo(payload.get("nif"))
    if not nif:
        return {"error": "Indique o NIF da empresa."}
    pais = pais_codigo(payload.get("pais"))
    ano = _to_int(payload.get("ano"))
    if ano is None or not (2000 <= ano <= 2100):
        return {"error": "Indique um ano válido (2000–2100)."}
    fonte = str(payload.get("fonte") or "relatorios_sustentabilidade").strip()[:120]
    verificacao = str(payload.get("verificacao") or "declarada").strip().lower()
    if verificacao not in {"declarada", "externa"}:
        return {"error": "`verificacao` deve ser `declarada` ou `externa`."}

    entrada = payload.get("indicadores")
    if isinstance(entrada, dict):
        pares = list(entrada.items())
    elif isinstance(entrada, list):
        pares = [
            (item.get("codigo"), item.get("valor"))
            for item in entrada
            if isinstance(item, dict) and item.get("codigo")
        ]
    else:
        return {"error": "`indicadores` deve ser um objeto {codigo: valor} ou uma lista de {codigo, valor}."}

    validos: List[Dict[str, Any]] = []
    invalidos: List[Dict[str, Any]] = []
    for codigo, valor in pares:
        codigo = str(codigo or "").strip()
        item = tax.INDICADOR_BY_CODIGO.get(codigo)
        numero = _to_float(valor)
        if not item:
            invalidos.append({"codigo": codigo, "erro": "código desconhecido"})
            continue
        if numero is None:
            invalidos.append({"codigo": codigo, "erro": "valor não numérico"})
            continue
        validos.append(
            {
                "codigo": codigo,
                "label": item["label"],
                "pilar": item["pilar"],
                "valor": numero,
                "unidade": item.get("unidade"),
                "direcao": "menor_melhor" if (item.get("melhor") is not None and item.get("pior") is not None and item["melhor"] < item["pior"]) else "maior_melhor",
            }
        )
    if not validos:
        return {"error": "Nenhum indicador válido.", "invalidos": invalidos}

    cadastro = _cadastro(client, nif)
    doc = {
        "nif": nif,
        "pais": pais,
        "empresa_nome": cadastro.get("name") or payload.get("nome") or nif,
        "ano": ano,
        "fonte": fonte,
        "fonte_label": next((item["label"] for item in tax.FONTES if item["id"] == fonte), fonte),
        "url": str(payload.get("url") or "")[:1000],
        "verificacao": verificacao,
        "origem": str(payload.get("origem") or "manual")[:64],
        "pilares": sorted({item["pilar"] for item in validos}),
        "codigos": sorted({item["codigo"] for item in validos}),
        "n_indicadores": len(validos),
        "atualizado_em": _now(),
        "indicadores": validos,
    }
    _garantir_indices(client)
    doc_id = f"{pais}-{nif}-{ano}-{re.sub(r'[^a-zA-Z0-9_-]+', '-', fonte)[:60]}"
    try:
        client.index(index=ESG_INDICADORES_INDEX, id=doc_id, document=doc, refresh=True)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Falha ao guardar os indicadores: {exc}"}

    recolha = {
        "run_id": uuid.uuid4().hex,
        "tipo": "indicadores",
        "estado": "concluido",
        "pais": pais,
        "iniciado_em": _now(),
        "concluido_em": _now(),
        "duracao_s": 0.0,
        "total": 1,
        "processados": 1,
        "erros": len(invalidos),
        "mensagem": f"{len(validos)} indicador(es) guardados para {ano}.",
        "user_id": str((user or {}).get("id") or ""),
        "user_email": str((user or {}).get("email") or ""),
        "parametros": {"nif": nif, "ano": ano, "fonte": fonte},
        "detalhes": {"invalidos": invalidos},
    }
    _registar_recolha(client, recolha)

    resultado: Dict[str, Any] = {
        "nif": nif,
        "ano": ano,
        "fonte": fonte,
        "n_indicadores": len(validos),
        "invalidos": invalidos,
        "doc_id": doc_id,
    }
    if payload.get("recalcular", True):
        doc_empresa = calcular_empresa(nif=nif, pais=pais, ano=ano, historico_anos=3, indexar=True, use_cache=False)
        if not doc_empresa.get("error"):
            resultado["score"] = doc_empresa.get("score")
            resultado["nivel"] = doc_empresa.get("nivel")
            resultado["nivel_label"] = doc_empresa.get("nivel_label")
            resultado["cobertura"] = doc_empresa.get("cobertura")
            resultado["confianca"] = doc_empresa.get("confianca")
    return resultado


def indicadores_empresa(*, nif: str, pais: str = "PT", ano: Optional[int] = None) -> Dict[str, Any]:
    client = _client()
    if client is None:
        return {"error": "Elasticsearch indisponível", "itens": []}
    docs = _docs_indicadores(client, nif, pais_codigo(pais))
    if ano is not None:
        docs = [doc for doc in docs if _to_int(doc.get("ano")) == int(ano)]
    itens = []
    for doc in docs:
        itens.append(
            {
                "ano": doc.get("ano"),
                "fonte": doc.get("fonte"),
                "fonte_label": doc.get("fonte_label"),
                "verificacao": doc.get("verificacao"),
                "url": doc.get("url"),
                "n_indicadores": doc.get("n_indicadores"),
                "atualizado_em": doc.get("atualizado_em"),
                "indicadores": doc.get("indicadores") or [],
            }
        )
    return {"nif": _nif_limpo(nif), "pais": pais_codigo(pais), "itens": itens, "total": len(itens)}


def _alvos_lote(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    client = _client()
    if client is None:
        return []
    explicitos = payload.get("nifs") or []
    alvos = [{"nif": _nif_limpo(nif), "nome": None, "pais": pais_codigo(payload.get("pais"))} for nif in explicitos if _nif_limpo(nif)]
    if alvos:
        return alvos[: int(payload.get("limite") or 100)]
    limite = max(1, min(int(payload.get("limite") or 50), 500))
    min_contratos = max(0, int(payload.get("min_contratos") or 1))
    filtros: List[Dict[str, Any]] = [
        {"term": {"is_company": True}},
        {"range": {"contracts_count": {"gte": min_contratos}}},
    ]
    if payload.get("pais"):
        filtros.append({"term": {"country": "Portugal" if pais_codigo(payload.get("pais")) == "PT" else "Espanha"}})
    resposta = _search(
        client,
        CONTRIBUINTES_INDEX,
        {
            "size": limite,
            "track_total_hits": False,
            "query": {"bool": {"filter": filtros}},
            "sort": [{"contracts_value": {"order": "desc", "missing": 0}}],
            "_source": ["nif", "name", "country"],
        },
        timeout=60,
    )
    return [
        {"nif": _nif_limpo(hit.get("_source", {}).get("nif")), "nome": hit.get("_source", {}).get("name"), "pais": pais_codigo(hit.get("_source", {}).get("country"))}
        for hit in _hits(resposta)
    ]


def calcular_lote(payload: Dict[str, Any], *, user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Calcula e indexa um conjunto de empresas (lote limitado e registado)."""
    client = _client()
    if client is None:
        return {"error": "Elasticsearch indisponível"}
    alvos = _alvos_lote(payload)
    if not alvos:
        return {"error": "Nenhuma empresa para calcular.", "detalhes": ["Indique `nifs` ou confirme que o cadastro tem empresas com contratos."]}
    anos = max(1, min(int(payload.get("anos") or 3), 5))
    max_contratos = max(50, min(int(payload.get("max_contratos") or 600), MAX_CONTRATOS))
    run_id = uuid.uuid4().hex
    inicio = time.time()
    recolha = {
        "run_id": run_id,
        "tipo": "calculo",
        "estado": "a_correr",
        "pais": pais_codigo(payload.get("pais")),
        "iniciado_em": _now(),
        "total": len(alvos),
        "processados": 0,
        "erros": 0,
        "user_id": str((user or {}).get("id") or ""),
        "user_email": str((user or {}).get("email") or ""),
        "parametros": {"anos": anos, "max_contratos": max_contratos, "nifs_explicitos": bool(payload.get("nifs"))},
    }
    _registar_recolha(client, recolha)

    resultados: List[Dict[str, Any]] = []
    erros: List[Dict[str, Any]] = []

    def _calcular(alvo: Dict[str, Any]) -> Dict[str, Any]:
        return calcular_empresa(
            nif=alvo["nif"],
            nome=alvo.get("nome"),
            pais=alvo.get("pais") or "PT",
            historico_anos=anos,
            max_contratos=max_contratos,
            indexar=False,
            incluir_benchmark=False,
            incluir_fornecedores=False,
            use_cache=False,
            es=client,
        )

    docs: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futuros = {pool.submit(_calcular, alvo): alvo for alvo in alvos}
        for futuro in as_completed(futuros):
            alvo = futuros[futuro]
            try:
                doc = futuro.result()
            except Exception as exc:  # noqa: BLE001
                doc = {"error": str(exc)}
            if doc.get("error"):
                erros.append({"nif": alvo["nif"], "erro": doc["error"]})
                continue
            docs.append(doc)
            resultados.append({"nif": doc.get("nif"), "nome": doc.get("name"), "score": doc.get("score"), "nivel": doc.get("nivel")})
    if docs:
        _garantir_indices(client)
        acoes = [
            {"_index": ESG_EMPRESAS_INDEX, "_id": f"{doc.get('pais')}-{doc.get('nif')}", "_source": doc}
            for doc in docs
        ]
        try:
            bulk(client, acoes, refresh=False, raise_on_error=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ESG: bulk falhou: %s", exc)

    recolha.update(
        {
            "estado": "concluido" if not erros else ("parcial" if docs else "falhou"),
            "concluido_em": _now(),
            "duracao_s": _round(time.time() - inicio, 2),
            "processados": len(docs),
            "erros": len(erros),
            "detalhes": {"erros": erros[:50], "resultados": resultados[:100]},
        }
    )
    _registar_recolha(client, recolha)
    return {
        "run_id": run_id,
        "total": len(alvos),
        "calculados": len(docs),
        "erros": erros,
        "resultados": sorted(resultados, key=lambda item: (item.get("score") is None, -(item.get("score") or 0))),
        "duracao_s": recolha["duracao_s"],
    }


# ---------------------------------------------------------------------------
# Estado, meta e exportação
# ---------------------------------------------------------------------------
def status() -> Dict[str, Any]:
    client = _client()
    if client is None:
        return {"disponivel": False, "motivo": "Elasticsearch indisponível", "indices": {}}
    indices: Dict[str, Any] = {}
    for nome in (ESG_EMPRESAS_INDEX, ESG_INDICADORES_INDEX, ESG_RECOLHAS_INDEX):
        try:
            existe = bool(client.indices.exists(index=nome))
            total = int(client.count(index=nome).get("count") or 0) if existe else 0
        except Exception as exc:  # noqa: BLE001
            indices[nome] = {"existe": False, "total": 0, "erro": str(exc)}
            continue
        indices[nome] = {"existe": existe, "total": total}
    ultima = None
    try:
        resposta = client.search(
            index=ESG_EMPRESAS_INDEX,
            body={"size": 0, "track_total_hits": False, "aggs": {"ultima": {"max": {"field": "gerado_em"}}}},
        )
        ultima = (((resposta.get("aggregations") or {}).get("ultima") or {}).get("value_as_string"))
    except Exception:  # noqa: BLE001
        pass
    execucoes: List[Dict[str, Any]] = []
    try:
        resposta = client.search(
            index=ESG_RECOLHAS_INDEX,
            body={"size": 5, "query": {"match_all": {}}, "sort": [{"iniciado_em": {"order": "desc", "unmapped_type": "date"}}]},
        )
        execucoes = [hit.get("_source") or {} for hit in _hits(resposta)]
    except Exception:  # noqa: BLE001
        pass
    return {
        "disponivel": True,
        "indices": indices,
        "ultima_atualizacao": ultima,
        "ultimas_execucoes": execucoes,
        "modelo_versao": tax.MODELO_VERSAO,
    }


def meta() -> Dict[str, Any]:
    cartao = tax.cartao_modelo()
    return {
        "cartao_modelo": cartao,
        "status": status(),
        "setores": [{"id": chave, **valor} for chave, valor in tax.CAE_SECOES.items()],
        "cpv_taxonomia": [
            {"divisao": f"{codigo:02d}", **valor}
            for codigo, valor in sorted(tax.CPV_ESG.items())
        ],
        "indicadores": [dict(item) for item in tax.INDICADORES],
        "fontes": [dict(item) for item in tax.FONTES],
        "taxonomia": taxonomia_panorama(),
        "aviso": tax.AVISO_GERAL,
    }


def exportar_csv(
    *,
    pais: Optional[str] = None,
    setor: Optional[str] = None,
    dimensao: Optional[str] = None,
    nivel: Optional[str] = None,
    ano: Optional[int] = None,
    ordenar: str = "score",
    limite: int = 500,
) -> str:
    dados = ranking(
        pais=pais,
        setor=setor,
        dimensao=dimensao,
        nivel=nivel,
        ano=ano,
        ordenar=ordenar,
        size=max(1, min(int(limite), 1_000)),
    )
    buffer = io.StringIO()
    escritor = csv.writer(buffer)
    escritor.writerow(["posicao", "nif", "nome", "pais", "setor", "dimensao", "score", "nivel", "pilares_e", "pilares_s", "pilares_g", "cobertura", "confianca", "contratos", "valor", "ano", "taxonomia_elegivel", "taxonomia_alinhamento", "taxonomia_objetivos", "ods"])
    for item in dados.get("itens") or []:
        pilares = item.get("pilares") or {}
        escritor.writerow(
            [
                item.get("posicao"),
                item.get("nif"),
                item.get("nome"),
                item.get("pais"),
                item.get("setor_label"),
                item.get("dimensao_label"),
                item.get("score"),
                item.get("nivel_label"),
                pilares.get("e"),
                pilares.get("s"),
                pilares.get("g"),
                item.get("cobertura"),
                item.get("confianca"),
                item.get("contratos"),
                item.get("valor"),
                item.get("ano"),
                item.get("taxonomia_elegivel"),
                item.get("taxonomia_alinhamento"),
                ";".join(str(oid) for oid in item.get("taxonomia_objetivos") or []),
                ";".join(str(oid) for oid in item.get("ods") or []),
            ]
        )
    return buffer.getvalue()
