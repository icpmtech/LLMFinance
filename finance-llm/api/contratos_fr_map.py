"""Mapa dos contratos de França (DECP) — agregação e posições.

Os contratos do DECP não têm coordenadas: trazem o **local de execução** em duas
peças — `lieu_execution_code` e `lieu_execution_type` — com níveis diferentes:

| `lieu_execution_type` | Exemplo | Nível | Tratamento |
| --- | --- | --- | --- |
| `Code département` | `35` | Departamento | posição exata (código) |
| `Code postal` | `43190` | Departamento | agrupa pelo **prefixo** (43 = Haute-Loire) |
| `Code commune` | `2A004` | Departamento | agrupa pelo prefixo INSEE (2A) |
| `Code région` | `76` | Região | posição exata (código INSEE de região) |
| `Code pays` | `FR` | País | centroide do país |
| `Code canton` / `Code arrondissement` | `57` | — | sem posição (listados) |

Onde isto importa: **`Code région` e `Code département` partilham códigos** («76» é
Occitanie como região e Seine-Maritime como departamento). Por isso a agregação
filtra sempre por **tipo *e* código** — nunca só pelo código.

Como no mapa ibérico, nada é inventado: o que não tem posição conhecida sai em
`not_plotted` (com contagem e valor) e é apresentado à parte na página. Os
departamentos de **ultramar** vêm marcados (`offshore`) porque não cabem no
enquadramento da França metropolitana.

Toda a agregação é feita com uma **única** `filters` ag, com filtros disjuntos por
construção (tipo+código, ou tipo+prefixo) — a soma das parcelas é o total, sem
truncagens de *terms* de topo.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from api import fr_geo
from api.elasticsearch_client import (
    CONTRATOS_FR_INDEX,
    _build_contratos_fr_query,
    _contratos_fr_value_source,
    get_es_client,
)

logger = logging.getLogger(__name__)

NIVEL_DEPARTAMENTO = "departamento"
NIVEL_REGIAO = "regiao"
NIVEL_PAIS = "pais"

NOMES_NIVEL = {
    NIVEL_DEPARTAMENTO: "Departamento",
    NIVEL_REGIAO: "Região",
    NIVEL_PAIS: "País",
}

#: Tipos cujo código é (ou começa por) um departamento.
TIPOS_DEPARTAMENTO = ("Code département",)
TIPOS_PREFIXO = ("Code postal", "Code commune")

OUTROS_TIPOS = {
    "Code canton": "Cantão",
    "Code arrondissement": "Arrondissement",
}

#: Chave do filtro que recolhe tudo o que não tem posição conhecida.
CHAVE_RESTO = "outros:resto"

#: Códigos INSEE das regiões de ultramar (colidem com departamentos metropolitanos
#: — «01» é Guadeloupe como região e Ain como departamento).
REGIOES_ULTRAMAR = {"01", "02", "03", "04", "06"}


def _buckets() -> Dict[str, Dict[str, Any]]:
    """Filtros disjuntos: um por departamento (código + prefixo) e os restantes níveis."""
    buckets: Dict[str, Dict[str, Any]] = {}
    departamentos = {**fr_geo.FR_DEPARTMENT_CENTROIDS, **fr_geo.FR_OVERSEAS_CENTROIDS}
    for codigo in departamentos:
        buckets[f"dep:{codigo}"] = {
            "bool": {
                "filter": [
                    {"term": {"lieu_execution_code": codigo}},
                    {"terms": {"lieu_execution_type": list(TIPOS_DEPARTAMENTO)}},
                ]
            }
        }
        buckets[f"pre:{codigo}"] = {
            "bool": {
                "filter": [
                    {"terms": {"lieu_execution_type": list(TIPOS_PREFIXO)}},
                    {"prefix": {"lieu_execution_code": codigo}},
                ]
            }
        }
    buckets["regiao"] = {"term": {"lieu_execution_type": "Code région"}}
    buckets["pais"] = {"term": {"lieu_execution_type": "Code pays"}}
    for tipo in OUTROS_TIPOS:
        buckets[f"outros:{tipo}"] = {"term": {"lieu_execution_type": tipo}}
    return buckets


def _posicao(codigo: str) -> Optional[Dict[str, Any]]:
    """Posição de um departamento (metropolitano ou de ultramar)."""
    if codigo in fr_geo.FR_DEPARTMENT_CENTROIDS:
        info = fr_geo.FR_DEPARTMENT_CENTROIDS[codigo]
        return {
            "code": codigo,
            "label": info["nom"],
            "level": NIVEL_DEPARTAMENTO,
            "precision": "centroide" if codigo != "20" else "grupo-postal",
            "lat": info["lat"],
            "lon": info["lon"],
            "offshore": False,
        }
    if codigo in fr_geo.FR_OVERSEAS_CENTROIDS:
        info = fr_geo.FR_OVERSEAS_CENTROIDS[codigo]
        return {
            "code": codigo,
            "label": info["nom"],
            "level": NIVEL_DEPARTAMENTO,
            "precision": "prefeitura",
            "lat": info["lat"],
            "lon": info["lon"],
            "offshore": True,
        }
    return None


def _regiao(codigo: str, contratos: int, valor: float) -> Dict[str, Any]:
    """Região: posição pelo centro de massa (ou listada, se o código for inválido)."""
    info = fr_geo.FR_REGION_CENTROIDS.get(codigo)
    base = {"code": codigo, "contracts": contratos, "value": valor}
    if not info:
        base.update({"label": f"Região «{codigo}» (código não reconhecido)", "kind": "região"})
        return base
    base.update(
        {
            "label": info["nom"],
            "level": NIVEL_REGIAO,
            "precision": "centroide",
            "lat": info["lat"],
            "lon": info["lon"],
            "offshore": codigo in REGIOES_ULTRAMAR,
        }
    )
    return base


def _pais(codigo: str, contratos: int, valor: float) -> Dict[str, Any]:
    if codigo.upper() == "FR":
        info = fr_geo.FR_COUNTRY_CENTROID
        return {
            "code": "FR",
            "label": info["nom"],
            "level": NIVEL_PAIS,
            "precision": "centroide-pais",
            "lat": info["lat"],
            "lon": info["lon"],
            "contracts": contratos,
            "value": valor,
            "offshore": False,
        }
    return {"code": codigo, "label": f"País «{codigo}»", "kind": "país", "contracts": contratos, "value": valor}


def get_contratos_fr_map(
    q: Optional[str] = None,
    ano: Optional[int] = None,
    nature: Optional[str] = None,
    procedure: Optional[str] = None,
    acheteur: Optional[str] = None,
    acheteur_id: Optional[str] = None,
    adjudicatario: Optional[str] = None,
    adjudicatario_id: Optional[str] = None,
    cpv_code: Optional[str] = None,
    lieu_execution_code: Optional[str] = None,
    lieu_execution_type: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_field: Optional[str] = None,
    es: Any = None,
) -> Dict[str, Any]:
    """Contratos de França agregados por local de execução, com posições."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    query = _build_contratos_fr_query(
        q=q,
        ano=ano,
        nature=nature,
        procedure=procedure,
        acheteur=acheteur,
        acheteur_id=acheteur_id,
        adjudicatario=adjudicatario,
        adjudicatario_id=adjudicatario_id,
        cpv_code=cpv_code,
        lieu_execution_code=lieu_execution_code,
        lieu_execution_type=lieu_execution_type,
        min_value=min_value,
        max_value=max_value,
        start_date=start_date,
        end_date=end_date,
        date_field=date_field,
    )

    valor = _contratos_fr_value_source("montant")
    aggs: Dict[str, Any] = {
        "local": {
            "filters": {
                "other_bucket": True,
                "other_bucket_key": CHAVE_RESTO,
                "filters": _buckets(),
            },
            "aggs": {"valor": {"sum": valor}},
        },
        "por_regiao": {
            "filter": {"term": {"lieu_execution_type": "Code région"}},
            "aggs": {
                "codigos": {
                    "terms": {"field": "lieu_execution_code", "size": 100, "order": {"valor": "desc"}},
                    "aggs": {"valor": {"sum": valor}},
                }
            },
        },
        "por_pais": {
            "filter": {"term": {"lieu_execution_type": "Code pays"}},
            "aggs": {
                "codigos": {
                    "terms": {"field": "lieu_execution_code", "size": 50, "order": {"valor": "desc"}},
                    "aggs": {"valor": {"sum": valor}},
                }
            },
        },
        "valor": {"sum": valor},
        "valor_conhecido": {
            "filter": {"script": {"script": "doc['montant'].size() != 0 || doc['montant_estime'].size() != 0"}}
        },
        # O DECP traz valores indicativos (plafonds, «99999999999999») que dominam
        # qualquer soma. Contam-se à parte para a página poder avisar em vez de
        # apresentar um total de valor inutilizável.
        "valores_indicativos": {
            "filter": {"script": {"script": "doc['montant'].size() != 0 && doc['montant'].value >= 1.0e12"}},
            "aggs": {"valor": {"sum": valor}},
        },
    }

    body: Dict[str, Any] = {"query": query, "size": 0, "track_total_hits": True, "aggs": aggs}

    try:
        resp = client.search(index=CONTRATOS_FR_INDEX, body=body)
    except Exception as exc:  # pragma: no cover - ES em baixo
        return {"error": str(exc)}

    total = int(resp["hits"]["total"]["value"])
    aggs_resp = resp.get("aggregations", {})
    local = aggs_resp.get("local", {})
    parcelas: Dict[str, Dict[str, Any]] = local.get("buckets", {})
    if isinstance(parcelas, list):  # outras versões devolvem lista
        parcelas = {item.get("key"): item for item in parcelas}

    departamentos: Dict[str, Dict[str, Any]] = {}
    not_plotted: List[Dict[str, Any]] = []

    for chave, dados in parcelas.items():
        contratos = int(dados.get("doc_count") or 0)
        valor_parcela = float((dados.get("valor") or {}).get("value") or 0.0)
        if not contratos or chave is None:
            continue
        prefixo, _, codigo = chave.partition(":")
        if prefixo in ("dep", "pre"):
            posicao = _posicao(codigo)
            if posicao is not None:
                # Código direto (dep:) e prefixo postal (pre:) somam-se no mesmo
                # departamento: um contrato cai em exatamente um dos dois filtros.
                atual = departamentos.setdefault(codigo, {**posicao, "contracts": 0, "value": 0.0})
                atual["contracts"] += contratos
                atual["value"] += valor_parcela
            continue
        if chave in ("regiao", "pais"):
            continue  # tratados abaixo, com o código dentro do sub-agg
        tipo = chave.partition(":")[2] or "sem localização"
        not_plotted.append(
            {
                "code": tipo,
                "label": OUTROS_TIPOS.get(tipo, "Sem localização conhecida"),
                "kind": OUTROS_TIPOS.get(tipo, "sem localização"),
                "contracts": contratos,
                "value": valor_parcela,
            }
        )

    regioes: List[Dict[str, Any]] = []
    for entrada in aggs_resp.get("por_regiao", {}).get("codigos", {}).get("buckets", []):
        item = _regiao(
            str(entrada.get("key")),
            int(entrada.get("doc_count") or 0),
            float((entrada.get("valor") or {}).get("value") or 0.0),
        )
        if item.get("lat") is None:
            not_plotted.append(item)
        else:
            regioes.append(item)

    paises: List[Dict[str, Any]] = []
    for entrada in aggs_resp.get("por_pais", {}).get("codigos", {}).get("buckets", []):
        item = _pais(
            str(entrada.get("key")),
            int(entrada.get("doc_count") or 0),
            float((entrada.get("valor") or {}).get("value") or 0.0),
        )
        (paises if item.get("lat") is not None else not_plotted).append(item)

    # Departamentos metropolitanos + regiões no mesmo mapa; ultramar à parte
    # (não cabe no enquadramento da França metropolitana, como as ilhas no mapa ibérico).
    metro = [item for item in departamentos.values() if not item["offshore"]]
    fora = [item for item in departamentos.values() if item["offshore"]]
    regioes_metro = [item for item in regioes if not item.get("offshore")]
    regioes_fora = [item for item in regioes if item.get("offshore")]

    regioes = sorted(metro + regioes_metro, key=lambda item: item["value"], reverse=True)
    offshore = sorted(fora + regioes_fora, key=lambda item: item["value"], reverse=True)
    not_plotted.sort(key=lambda item: item["value"], reverse=True)

    valor_total = float((aggs_resp.get("valor") or {}).get("value") or 0.0)
    com_valor = int((aggs_resp.get("valor_conhecido") or {}).get("doc_count") or 0)
    indicativos = aggs_resp.get("valores_indicativos") or {}
    conta_parcelas = sum(int(d.get("doc_count") or 0) for d in parcelas.values())
    warnings: List[str] = []
    if conta_parcelas != total:
        warnings.append(
            "As parcelas somam "
            f"{conta_parcelas:,} de {total:,} contratos: há documentos com localização mas sem posição conhecida.".replace(",", " ")
        )
    if (indicativos.get("doc_count") or 0) > 0:
        warnings.append(
            f"{(indicativos.get('doc_count') or 0):,} contratos têm valor indicativo (≥ 1 000 G€) do DECP "
            "e dominam a soma por valor.".replace(",", " ")
        )

    return {
        "total": total,
        "value": valor_total,
        "value_docs": com_valor,
        "value_outliers": {
            "contracts": int(indicativos.get("doc_count") or 0),
            "value": float((indicativos.get("valor") or {}).get("value") or 0.0),
        },
        "regions": regioes,
        "offshore": offshore,
        "countries": paises,
        "not_plotted": not_plotted,
        "levels": {
            "departamento": len([item for item in regioes if item["level"] == NIVEL_DEPARTAMENTO]),
            "regiao": len([item for item in regioes if item["level"] == NIVEL_REGIAO]),
        },
        "warnings": warnings,
    }
