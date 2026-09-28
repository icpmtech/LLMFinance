"""Dashboard **global** de padrões — o universo inteiro, por ano, com pesquisa e filtros.

O resto do módulo trabalha sobre **amostras** (rápidas e reprodutíveis). Aqui a
pergunta é outra: *o que dizem os 2,2 M de contratos portugueses e os 4 M
espanhóis, ano a ano?* Para isso usam-se **agregações do Elasticsearch** — que
percorrem o índice todo sem trazer documentos para memória — e o resultado é
materializado em `finance_padroes_global`:

- um documento por **ano** (`pais:ano`) com contratos, valor, mediana, taxa de
  ajuste direto, aditivos, top CPV, top adjudicatárias, top adjudicantes e a
  série mensal;
- um documento de **total** (`pais:_total`) com a soma dos anos e as séries
  temporal (mês), de procedimentos e os topos globais;
- um documento de **meta** (`pais:_meta`) com quando correu, quanto demorou e
  quantos documentos varreu.

Porque materializar? Porque ler isto a cada visita seria varrer o índice outra
vez: a sincronização é um **processo** (corre em segundo plano, com progresso) e
o dashboard lê documentos já prontos. A leitura diz sempre de quando é.

Além das métricas, há a **pesquisa filtrada**: texto livre mais filtros de
período (dia, semana, mês, ano), empresa, contratos, concorrentes, CPV, valor e
adjudicante — com facetas calculadas sobre o universo (não sobre uma amostra).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from api.elasticsearch_client import GLOBAL_PADROES_INDEX, get_es_client
from api import padroes_service as service

logger = logging.getLogger(__name__)

#: Granularidades aceites na série temporal e nos filtros.
GRANULARIDADES: Dict[str, Dict[str, str]] = {
    "dia": {"label": "Dia", "calendar": "1d", "campo": "dia"},
    "semana": {"label": "Semana", "calendar": "1w", "campo": "semana"},
    "mes": {"label": "Mês", "calendar": "1M", "campo": "mes"},
    "ano": {"label": "Ano", "calendar": "1y", "campo": "ano"},
}

#: Quantos valores distintos se pedem por faceta (topos por ano).
TAMANHO_FACETA = 15
#: Anos a processar por omissão (o intervalo útil do portal).
ANOS_PADRAO = 12


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _anos(pais: str, *, anos: Optional[Sequence[int]] = None, es: Any = None) -> List[int]:
    """Anos com contratos no índice (ou os pedidos, filtrados pelo que existe)."""
    spec = service.COUNTRIES[pais]
    client = es or get_es_client()
    if client is None:
        return list(anos or [])
    available = service._years_in_index(client, spec)  # noqa: SLF001
    if anos:
        pedidos = [int(ano) for ano in anos]
        return [ano for ano in pedidos if not available or ano in available]
    limite = sorted(available)[-ANOS_PADRAO:]
    return limite or sorted(available)


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
def _filtro_direct_award(spec: service.CountrySpec) -> Optional[Dict[str, Any]]:
    """Filtro de ajuste direto: prefixos do país (o campo é keyword, sem analisador)."""
    prefixos = spec.direct_award_prefixes
    if not prefixos:
        return None
    return {"bool": {"should": [{"prefix": {spec.procedure_field: prefixo}} for prefixo in prefixos], "minimum_should_match": 1}}


def _runtime_aditivo(spec: service.CountrySpec) -> Dict[str, Any]:
    """Campo calculado «aditivo» (efetivo > 1,15 × contratado).

    O portal não tem um campo «teve aditivo»: tem o valor efetivo e o contratado.
    O runtime field evita indexar um campo novo (e evita reescrever 2,2 M docs),
    pagando o custo do script só nas agregações que o pedem.
    """
    if not spec.effective_field:
        return {}
    return {
        "aditivo": {
            "type": "boolean",
            "script": {
                "source": (
                    f"if (doc['{spec.effective_field}'].size()==0 || doc['{spec.value_field}'].size()==0) return; "
                    f"double e = doc['{spec.effective_field}'].value; double c = doc['{spec.value_field}'].value; "
                    "emit(e > 0 && c > 0 && e > c * 1.15);"
                )
            },
        }
    }


def _classificar_ajuste_direto(spec: service.CountrySpec, baldes: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Parte dos contratos por ajuste direto, a partir dos procedimentos observados.

    Classifica-se pelos prefixos do país (o mesmo critério do motor: `fold`, ou
    seja minúsculas **sem acentos** — o vocabulário do portal escreve «Consulta
    Prévia» e o prefixo é «consulta previa»). «Ajuste Direto Regime Geral»,
    «Consulta Prévia» e «Contratação excluída» contam como ajuste direto.
    """
    total = sum(int(balde.get("doc_count") or 0) for balde in baldes)
    direto = sum(
        int(balde.get("doc_count") or 0)
        for balde in baldes
        if service.fold(balde.get("key")).startswith(spec.direct_award_prefixes)
    )
    valor_direto = sum(
        float(((balde.get("valor") or {}).get("value") or 0.0))
        for balde in baldes
        if service.fold(balde.get("key")).startswith(spec.direct_award_prefixes)
    )
    valor_total = sum(float(((balde.get("valor") or {}).get("value") or 0.0)) for balde in baldes)
    return {
        "contratos": direto,
        "total": total,
        "taxa": service.num(direto / total) if total else None,
        "valor": service.num(valor_direto),
        "taxa_valor": service.num(valor_direto / valor_total) if valor_total else None,
    }


# ---------------------------------------------------------------------------
# Agregações sobre o universo
# ---------------------------------------------------------------------------
def _agregacoes_ano(spec: service.CountrySpec) -> Dict[str, Any]:
    """Agregações pedidas para cada ano (uma só ida ao índice serve todos)."""
    aggs: Dict[str, Any] = {
        "valor": {"stats": {"field": spec.value_field}},
        "valor_base": {"stats": {"field": spec.base_field}},
        "mediana": {"percentiles": {"field": spec.value_field, "percents": [50]}},
        "procedimentos": {
            "terms": {"field": spec.procedure_field, "size": 50},
            "aggs": {"valor": {"sum": {"field": spec.value_field}}},
        },
        "meses": {
            "date_histogram": {"field": spec.pub_date, "calendar_interval": "1M", "min_doc_count": 1},
            "aggs": {"valor": {"sum": {"field": spec.value_field}}},
        },
        "cpvs": {
            "nested": {"path": spec.cpv_path},
            "aggs": {
                "codigos": {
                    "terms": {"field": spec.cpv_code_field, "size": TAMANHO_FACETA},
                    "aggs": {"valor": {"reverse_nested": {}, "aggs": {"s": {"sum": {"field": spec.value_field}}}}},
                }
            },
        },
    }
    if spec.key == "PT":
        # Adjudicatárias e adjudicantes vivem em `nested` no Portal BASE.
        for chave, caminho, campo_nif, campo_nome in (
            ("adjudicatarias", "adjudicatarios.parsed", "adjudicatarios.parsed.nif", "adjudicatarios.parsed.nome"),
            ("adjudicantes", "adjudicantes.parsed", "adjudicantes.parsed.nif", "adjudicantes.parsed.nome"),
        ):
            aggs[chave] = {
                "nested": {"path": caminho},
                "aggs": {
                    "nifs": {
                        "terms": {"field": campo_nif, "size": TAMANHO_FACETA},
                        "aggs": {
                            "nome": {"top_hits": {"size": 1, "_source": [campo_nome]}},
                            "valor": {"reverse_nested": {}, "aggs": {"s": {"sum": {"field": spec.value_field}}}},
                        },
                    }
                },
            }
        aggs["sem_concorrentes"] = {
            "filter": {
                "bool": {
                    # O campo existe em quase todos os documentos, muitas vezes
                    # **vazio**: «sem concorrentes» tem de contar os vazios também
                    # (só o `exists` dava zero e escondia 58 % dos casos).
                    "should": [
                        {"term": {f"{spec.bidders_field}.keyword": ""}},
                        {"bool": {"must_not": [{"exists": {"field": spec.bidders_field}}]}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        }
        aggs["aditivos"] = {"filter": {"term": {"aditivo": True}}, "aggs": {"valor": {"sum": {"field": spec.effective_field}}}}
    else:
        aggs["adjudicatarias"] = {
            "terms": {"field": spec.adjudicatario_nif, "size": TAMANHO_FACETA},
            "aggs": {
                "nome": {"top_hits": {"size": 1, "_source": [spec.adjudicatario_nome]}},
                "valor": {"sum": {"field": spec.value_field}},
            },
        }
        aggs["adjudicantes"] = {
            "terms": {"field": spec.adjudicante_nif, "size": TAMANHO_FACETA},
            "aggs": {
                "nome": {"top_hits": {"size": 1, "_source": [spec.adjudicante_nome]}},
                "valor": {"sum": {"field": spec.value_field}},
            },
        }
        aggs["ofertas"] = {"stats": {"field": spec.bidders_field}}
        aggs["sem_concorrentes"] = {
            "filter": {"bool": {"must_not": [{"exists": {"field": spec.bidders_field}}]}}
        }
    return aggs


def _top_hits_nome(agregado: Any) -> Optional[str]:
    return service._top_hit_name(agregado)  # noqa: SLF001


def _partes_ano(balde: Dict[str, Any], chave: str) -> List[Dict[str, Any]]:
    """Lista de partes (adjudicatárias ou adjudicantes) de um ano.

    Portugal guarda as partes em `nested` (com `top_hits` para o nome e
    `reverse_nested` para o valor); Espanha tem campos planos, com o nome no
    próprio balde e a soma directa. As duas formas produzem a mesma lista.
    """
    agregado = balde.get(chave) or {}
    baldes = ((agregado.get("nifs") or {}).get("buckets") if "nifs" in agregado else agregado.get("buckets")) or []
    partes: List[Dict[str, Any]] = []
    for item in baldes:
        valor = item.get("valor") or {}
        if "s" in valor or "value" in valor:
            numero = (valor.get("s") or {}).get("value")
            if numero is None:
                numero = valor.get("value")
        else:
            numero = valor.get("value")
        partes.append(
            {
                "nif": item.get("key"),
                "nome": _top_hits_nome(item.get("nome")) or item.get("key"),
                "contratos": int(item.get("doc_count") or 0),
                "valor": service.num(numero) or 0.0,
            }
        )
    return partes


def _linha_ano(pais: str, ano: int, balde: Dict[str, Any]) -> Dict[str, Any]:
    """Converte o balde de agregação de um ano no documento que fica guardado."""
    spec = service.COUNTRIES[pais]
    procedimentos = (balde.get("procedimentos") or {}).get("buckets") or []
    valor = balde.get("valor") or {}
    mediana = ((balde.get("mediana") or {}).get("values") or {}).get("50.0")
    cpvs = [item for item in (((balde.get("cpvs") or {}).get("codigos") or {}).get("buckets") or [])]
    aditivos = balde.get("aditivos") or {}
    meses = [
        {
            "data": balde_mes.get("key_as_string"),
            "contratos": int(balde_mes.get("doc_count") or 0),
            "valor": service.num(((balde_mes.get("valor") or {}).get("value"))),
        }
        for balde_mes in ((balde.get("meses") or {}).get("buckets") or [])
    ]
    documento: Dict[str, Any] = {
        "pais": pais,
        "ano": int(ano),
        "contratos": int(balde.get("doc_count") or 0),
        "valor": service.num(valor.get("sum")),
        "valor_medio": service.num(valor.get("avg")),
        "valor_mediano": service.num(mediana),
        "valor_maximo": service.num(valor.get("max")),
        "valor_base": service.num((balde.get("valor_base") or {}).get("sum")),
        "contratos_com_base": int((balde.get("valor_base") or {}).get("count") or 0),
        "ajuste_direto": _classificar_ajuste_direto(spec, procedimentos),
        "procedimentos": [
            {
                "procedimento": item.get("key"),
                "contratos": int(item.get("doc_count") or 0),
                "valor": service.num(((item.get("valor") or {}).get("value"))),
            }
            for item in procedimentos[:TAMANHO_FACETA]
        ],
        "cpvs": [
            {
                "cpv": item.get("key"),
                "contratos": int(item.get("doc_count") or 0),
                "valor": service.num(((item.get("valor") or {}).get("s") or {}).get("value")),
            }
            for item in cpvs
        ],
        "adjudicatarias": _partes_ano(balde, "adjudicatarias"),
        "adjudicantes": _partes_ano(balde, "adjudicantes"),
        "meses": meses,
    }
    if spec.key == "PT":
        # Num `filter` agg o resultado é `doc_count` (não `count`): ler a chave
        # errada devolvia sempre zero aditivos.
        documento["aditivos"] = int(aditivos.get("doc_count") or 0)
        documento["valor_aditivos"] = service.num(((aditivos.get("valor") or {}).get("value")))
        documento["taxa_aditivo"] = service.num(documento["aditivos"] / documento["contratos"]) if documento["contratos"] else None
        documento["sem_concorrentes"] = int(((balde.get("sem_concorrentes") or {}).get("doc_count") or 0))
        documento["taxa_sem_concorrentes"] = (
            service.num(documento["sem_concorrentes"] / documento["contratos"]) if documento["contratos"] else None
        )
    else:
        ofertas = balde.get("ofertas") or {}
        documento["ofertas_media"] = service.num(ofertas.get("avg"))
        documento["ofertas_mediana"] = service.num(ofertas.get("50.0"))
        documento["sem_ofertas"] = int(((balde.get("sem_concorrentes") or {}).get("doc_count") or 0))
    return documento


def metricas_universo(
    pais: str = "PT",
    *,
    anos: Optional[Sequence[int]] = None,
    es: Any = None,
) -> Dict[str, Any]:
    """Agrega o **universo inteiro** do país, ano a ano (sem amostra).

    Uma única consulta ao índice serve todos os anos: o Elasticsearch percorre os
    documentos e devolve só os agregados (contagens, somas, medianas por
    percentis, topos e a série mensal). É a base do dashboard global.
    """
    spec = service.COUNTRIES.get(str(pais or "").upper())
    if spec is None:
        return {"error": f"país desconhecido: {pais}", "paises": list(service.COUNTRIES)}
    client = es or get_es_client()
    if client is None:
        return {"error": "Elasticsearch indisponível"}

    alvo = _anos(spec.key, anos=anos, es=client)
    if not alvo:
        return {"error": "sem anos para analisar", "pais": spec.key}
    inicio = time.perf_counter()
    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"filter": [{"range": {spec.year_field: {"gte": min(alvo), "lte": max(alvo)}}}]}},
        "aggs": {
            "anos": {
                "terms": {"field": spec.year_field, "size": 60, "order": {"_key": "asc"}},
                "aggs": _agregacoes_ano(spec),
            },
            "meses": {
                "date_histogram": {"field": spec.pub_date, "calendar_interval": "1M", "min_doc_count": 1},
                "aggs": {"valor": {"sum": {"field": spec.value_field}}},
            },
            "procedimentos": {
                "terms": {"field": spec.procedure_field, "size": 50},
                "aggs": {"valor": {"sum": {"field": spec.value_field}}},
            },
            "top_cpv": {
                "nested": {"path": spec.cpv_path},
                "aggs": {
                    "codigos": {
                        "terms": {"field": spec.cpv_code_field, "size": TAMANHO_FACETA},
                        "aggs": {"valor": {"reverse_nested": {}, "aggs": {"s": {"sum": {"field": spec.value_field}}}}},
                    }
                },
            },
        },
    }
    runtime = _runtime_aditivo(spec)
    if runtime:
        body["runtime_mappings"] = runtime
    try:
        resposta = service._search(client, spec.index, body, timeout=600)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        logger.warning("Agregação global de %s falhou: %s", spec.key, exc)
        return {"error": f"falha na agregação global: {exc}"}
    if not resposta:
        # `_search` engole o erro de rede e devolve vazio: sem isto, o dashboard
        # mostraria zeros em vez de dizer que não conseguiu ler.
        return {"error": "falha na agregação global: sem resposta do Elasticsearch"}

    baldes = ((resposta.get("aggregations") or {}).get("anos") or {}).get("buckets") or []
    linhas = [_linha_ano(spec.key, int(balde.get("key")), balde) for balde in baldes]
    procedimentos = [
        {
            "procedimento": item.get("key"),
            "contratos": int(item.get("doc_count") or 0),
            "valor": service.num(((item.get("valor") or {}).get("value"))),
        }
        for item in (((resposta.get("aggregations") or {}).get("procedimentos") or {}).get("buckets") or [])[:TAMANHO_FACETA]
    ]
    meses = [
        {
            "data": item.get("key_as_string"),
            "contratos": int(item.get("doc_count") or 0),
            "valor": service.num(((item.get("valor") or {}).get("value"))),
        }
        for item in (((resposta.get("aggregations") or {}).get("meses") or {}).get("buckets") or [])
    ]
    cpvs = [
        {
            "cpv": item.get("key"),
            "contratos": int(item.get("doc_count") or 0),
            "valor": service.num(((item.get("valor") or {}).get("s") or {}).get("value")),
        }
        for item in ((((resposta.get("aggregations") or {}).get("top_cpv") or {}).get("codigos") or {}).get("buckets") or [])
    ]
    return {
        "pais": spec.key,
        "pais_label": spec.label,
        "indice": spec.index,
        "anos": linhas,
        "meses": meses,
        "procedimentos": procedimentos,
        "top_cpv": cpvs,
        "documentos": int(((resposta.get("hits") or {}).get("total") or {}).get("value") or 0),
        "duracao_s": round(time.perf_counter() - inicio, 2),
        "gerado_em": _agora(),
    }


# ---------------------------------------------------------------------------
# Sincronização (o «processo» que percorre o universo e materializa)
# ---------------------------------------------------------------------------
_ESTADO: Dict[str, Any] = {"a_correr": False, "pais": None, "progresso": None, "inicio": None, "fim": None, "resultado": None, "erro": None}
_ESTADO_LOCK = threading.Lock()


def estado() -> Dict[str, Any]:
    """Estado do processo de sincronização (para a página poder acompanhar)."""
    with _ESTADO_LOCK:
        return dict(_ESTADO)


def _publicar(**campos: Any) -> None:
    with _ESTADO_LOCK:
        _ESTADO.update(campos)


def _documentos(pais: str, metricas: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """Documentos a guardar: um por ano, o total e a meta."""
    linhas = metricas.get("anos") or []
    spec = service.COUNTRIES[pais]
    total: Dict[str, Any] = {
        "pais": pais,
        "ano": None,
        "contratos": sum(int(linha.get("contratos") or 0) for linha in linhas),
        "valor": service.num(sum(float(linha.get("valor") or 0.0) for linha in linhas)),
        "valor_mediano": service.num(service.median([float(linha.get("valor_mediano") or 0.0) for linha in linhas if linha.get("valor_mediano")])),
        "contratos_com_base": sum(int(linha.get("contratos_com_base") or 0) for linha in linhas),
        "valor_base": service.num(sum(float(linha.get("valor_base") or 0.0) for linha in linhas)),
        "aditivos": sum(int(linha.get("aditivos") or 0) for linha in linhas),
        "valor_aditivos": service.num(sum(float(linha.get("valor_aditivos") or 0.0) for linha in linhas)),
        "anos": [linha.get("ano") for linha in linhas],
        "meses": metricas.get("meses") or [],
        "procedimentos": metricas.get("procedimentos") or [],
        "cpvs": metricas.get("top_cpv") or [],
        "documentos": metricas.get("documentos"),
        "gerado_em": metricas.get("gerado_em") or _agora(),
    }
    if total["contratos"]:
        total["taxa_aditivo"] = service.num(total["aditivos"] / total["contratos"])
        total["valor_medio"] = service.num(total["valor"] / total["contratos"])
    # Topos globais: somar por chave os topos de cada ano (é uma aproximação
    # declarada — o topo de cada ano pode não conter todos os que somam no total).
    somados: Dict[str, Dict[str, Any]] = {}
    for linha in linhas:
        for cpv in linha.get("cpvs") or []:
            registo = somados.setdefault(str(cpv.get("cpv")), {"cpv": cpv.get("cpv"), "contratos": 0, "valor": 0.0})
            registo["contratos"] += int(cpv.get("contratos") or 0)
            registo["valor"] += float(cpv.get("valor") or 0.0)
    total["cpvs_somados"] = [
        {**item, "valor": service.num(item["valor"])}
        for item in sorted(somados.values(), key=lambda item: -(item.get("valor") or 0.0))[:TAMANHO_FACETA]
    ]
    adjudicatarias: Dict[str, Dict[str, Any]] = {}
    for linha in linhas:
        for empresa in linha.get("adjudicatarias") or []:
            chave = str(empresa.get("nif"))
            registo = adjudicatarias.setdefault(chave, {"nif": empresa.get("nif"), "nome": empresa.get("nome"), "contratos": 0, "valor": 0.0})
            registo["contratos"] += int(empresa.get("contratos") or 0)
            registo["valor"] += float(empresa.get("valor") or 0.0)
            if empresa.get("nome"):
                registo["nome"] = empresa["nome"]
    total["adjudicatarias"] = [
        {**item, "valor": service.num(item["valor"])}
        for item in sorted(adjudicatarias.values(), key=lambda item: -item["valor"])[:TAMANHO_FACETA]
    ]
    meta = {
        "pais": pais,
        "pais_label": spec.label,
        "indice": spec.index,
        "anos": [linha.get("ano") for linha in linhas],
        "documentos": metricas.get("documentos"),
        "duracao_s": metricas.get("duracao_s"),
        "gerado_em": metricas.get("gerado_em") or _agora(),
        "versao": 1,
    }
    # Um documento por ano + o total + a meta. (A lista tem de ser construída a
    # partir de `linhas` — sem a compreensão, a variável `linha` seria a sobra do
    # último ciclo e só o último ano seria gravado.)
    documentos: List[Tuple[str, Dict[str, Any]]] = [
        (f"{pais}:{linha['ano']}", {"kind": "ano", **linha}) for linha in linhas
    ]
    documentos.append((f"{pais}:_total", {"kind": "total", **total}))
    documentos.append((f"{pais}:_meta", {"kind": "meta", **meta}))
    return documentos


def _indexar(pais: str, documentos: Sequence[Tuple[str, Dict[str, Any]]], es: Any = None) -> int:
    client = es or get_es_client()
    if client is None:
        return 0
    escritos = 0
    for doc_id, documento in documentos:
        try:
            client.index(index=GLOBAL_PADROES_INDEX, id=doc_id, document=documento, refresh=False)
            escritos += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Não foi possível indexar %s: %s", doc_id, exc)
    try:
        client.indices.refresh(index=GLOBAL_PADROES_INDEX)
    except Exception as exc:  # noqa: BLE001
        logger.debug("refresh ignorado: %s", exc)
    return escritos


def sincronizar(
    pais: str = "PT",
    *,
    anos: Optional[Sequence[int]] = None,
    es: Any = None,
) -> Dict[str, Any]:
    """Corre a agregação do universo e **materializa** o resultado (síncrono).

    Devolve `{pais, anos, documentos, indexados, duracao_s, gerado_em}`. É esta a
    função que o processo em segundo plano chama; também pode ser corrida à mão
    (é o que os testes e a manutenção fazem).
    """
    metricas = metricas_universo(pais, anos=anos, es=es)
    if metricas.get("error"):
        return {"error": metricas["error"]}
    documentos = _documentos(str(pais).upper(), metricas)
    indexados = _indexar(str(pais).upper(), documentos, es=es)
    return {
        "pais": str(pais).upper(),
        "anos": [documento.get("ano") for _, documento in documentos if documento.get("kind") == "ano"],
        "documentos": len(documentos),
        "indexados": indexados,
        "duracao_s": metricas.get("duracao_s"),
        "gerado_em": metricas.get("gerado_em"),
        "indice": GLOBAL_PADROES_INDEX,
    }


def iniciar_sincronizacao(pais: str = "PT", *, anos: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """Arranca o processo em segundo plano (uma sincronização de cada vez)."""
    with _ESTADO_LOCK:
        if _ESTADO["a_correr"]:
            return {"a_correr": True, "pais": _ESTADO["pais"], "inicio": _ESTADO["inicio"], "aviso": "Já há uma sincronização a correr."}
        _ESTADO.update({"a_correr": True, "pais": str(pais).upper(), "progresso": "a agregação do universo começou", "inicio": _agora(), "fim": None, "resultado": None, "erro": None})

    def correr() -> None:
        try:
            resultado = sincronizar(pais, anos=anos)
            if resultado.get("error"):
                _publicar(a_correr=False, fim=_agora(), erro=str(resultado["error"]))
                return
            _publicar(a_correr=False, fim=_agora(), resultado=resultado, progresso="concluído")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Sincronização global falhou")
            _publicar(a_correr=False, fim=_agora(), erro=str(exc))

    threading.Thread(target=correr, name="padroes-global", daemon=True).start()
    return {"a_correr": True, "pais": str(pais).upper(), "inicio": _ESTADO["inicio"]}


# ---------------------------------------------------------------------------
# Leitura do dashboard
# ---------------------------------------------------------------------------
def _ler_documento(client: Any, doc_id: str) -> Optional[Dict[str, Any]]:
    try:
        return dict(client.get(index=GLOBAL_PADROES_INDEX, id=doc_id).get("_source") or {})
    except Exception as exc:  # noqa: BLE001
        logger.debug("Documento %s ausente: %s", doc_id, exc)
        return None


def dashboard(
    pais: str = "PT",
    *,
    granularidade: str = "mes",
    ano_from: Optional[int] = None,
    ano_to: Optional[int] = None,
    es: Any = None,
) -> Dict[str, Any]:
    """Dashboard global: lê o que está materializado (rápido) e recorta pela janela pedida."""
    spec = service.COUNTRIES.get(str(pais or "").upper())
    if spec is None:
        return {"error": f"país desconhecido: {pais}", "paises": list(service.COUNTRIES)}
    granularidade = granularidade if granularidade in GRANULARIDADES else "mes"
    client = es or get_es_client()
    if client is None:
        return {"error": "Elasticsearch indisponível"}

    meta = _ler_documento(client, f"{spec.key}:_meta")
    total = _ler_documento(client, f"{spec.key}:_total")
    if not meta or not total:
        return {
            "pais": spec.key,
            "pais_label": spec.label,
            "indice": spec.index,
            "vazio": True,
            "granularidade": granularidade,
            "granularidades": [{"id": chave, "label": valor["label"]} for chave, valor in GRANULARIDADES.items()],
            "estado": estado(),
            "aviso": (
                "Ainda não há métricas do universo materializadas. Corra a sincronização "
                "(percorre o índice todo por ano) para o dashboard ficar instantâneo."
            ),
        }

    anos = [int(ano) for ano in meta.get("anos") or []]
    if ano_from:
        anos = [ano for ano in anos if ano >= int(ano_from)]
    if ano_to:
        anos = [ano for ano in anos if ano <= int(ano_to)]
    linhas: List[Dict[str, Any]] = []
    for ano in anos:
        documento = _ler_documento(client, f"{spec.key}:{ano}")
        if documento:
            linhas.append(documento)
    linhas.sort(key=lambda item: int(item.get("ano") or 0))

    if granularidade == "ano":
        serie = [
            {"periodo": str(linha.get("ano")), "contratos": int(linha.get("contratos") or 0), "valor": service.num(linha.get("valor"))}
            for linha in linhas
        ]
    elif granularidade == "mes":
        serie = [
            {"periodo": str(item.get("data") or "")[:7], "contratos": int(item.get("contratos") or 0), "valor": service.num(item.get("valor"))}
            for item in total.get("meses") or []
            if (not ano_from or int(str(item.get("data") or "0000")[:4] or 0) >= int(ano_from))
            and (not ano_to or int(str(item.get("data") or "0000")[:4] or 0) <= int(ano_to))
        ]
    else:
        # Dia e semana são recortes finos: calculam-se na pesquisa filtrada (o
        # dashboard mostra o mês, que é a granularidade com leitura imediata).
        serie = [
            {"periodo": str(item.get("data") or "")[:7], "contratos": int(item.get("contratos") or 0), "valor": service.num(item.get("valor"))}
            for item in total.get("meses") or []
        ]

    contratos = sum(int(linha.get("contratos") or 0) for linha in linhas)
    valor = service.num(sum(float(linha.get("valor") or 0.0) for linha in linhas))
    aditivos = sum(int(linha.get("aditivos") or 0) for linha in linhas)
    ajuste = {
        "contratos": sum(int((linha.get("ajuste_direto") or {}).get("contratos") or 0) for linha in linhas),
        "valor": service.num(sum(float((linha.get("ajuste_direto") or {}).get("valor") or 0.0) for linha in linhas)),
    }
    ajuste["taxa"] = service.num(ajuste["contratos"] / contratos) if contratos else None
    ajuste["taxa_valor"] = service.num(ajuste["valor"] / valor) if valor else None

    return {
        "pais": spec.key,
        "pais_label": spec.label,
        "indice": spec.index,
        "vazio": False,
        "granularidade": granularidade,
        "granularidades": [{"id": chave, "label": valor_["label"]} for chave, valor_ in GRANULARIDADES.items()],
        "meta": meta,
        "estado": estado(),
        "filtros": {"ano_from": ano_from, "ano_to": ano_to},
        "totais": {
            "contratos": contratos,
            "documentos_universo": meta.get("documentos"),
            "valor": valor,
            "valor_medio": service.num(valor / contratos) if contratos else None,
            "valor_mediano": service.num(service.median([float(linha.get("valor_mediano") or 0.0) for linha in linhas if linha.get("valor_mediano")])),
            "valor_base": service.num(sum(float(linha.get("valor_base") or 0.0) for linha in linhas)),
            "contratos_com_base": sum(int(linha.get("contratos_com_base") or 0) for linha in linhas),
            "aditivos": aditivos,
            "taxa_aditivo": service.num(aditivos / contratos) if contratos else None,
            "valor_aditivos": service.num(sum(float(linha.get("valor_aditivos") or 0.0) for linha in linhas)),
            "sem_concorrentes": sum(int(linha.get("sem_concorrentes") or 0) for linha in linhas),
            "taxa_sem_concorrentes": service.num(
                sum(int(linha.get("sem_concorrentes") or 0) for linha in linhas) / contratos
            )
            if contratos
            else None,
            "ajuste_direto": ajuste,
            "anos": [linha.get("ano") for linha in linhas],
        },
        "serie": serie,
        "por_ano": linhas,
        "top_cpv": total.get("cpvs_somados") or total.get("cpvs") or [],
        "top_adjudicatarias": total.get("adjudicatarias") or [],
        "procedimentos": total.get("procedimentos") or [],
        "aviso": (
            "Métricas calculadas por agregação sobre o índice inteiro (sem amostra) e materializadas em "
            f"{GLOBAL_PADROES_INDEX}. O recorte por dia/semana faz-se na pesquisa filtrada."
        ),
        "gerado_em": total.get("gerado_em"),
    }


# ---------------------------------------------------------------------------
# Pesquisa filtrada (o «Google» do dashboard, com filtros de período e entidades)
# ---------------------------------------------------------------------------
def _filtro_periodo(spec: service.CountrySpec, *, data_from: Optional[str], data_to: Optional[str], campo: str = "publicacao") -> Optional[Dict[str, Any]]:
    campo_data = {"publicacao": spec.pub_date, "decisao": spec.award_date, "assinatura": spec.sign_date}.get(campo) or spec.pub_date
    intervalo: Dict[str, Any] = {}
    if data_from:
        intervalo["gte"] = data_from
    if data_to:
        intervalo["lte"] = data_to
    if not intervalo:
        return None
    return {"range": {campo_data: {**intervalo, "format": "yyyy-MM-dd"}}}


def _filtro_parte(spec: service.CountrySpec, valor: str) -> Optional[Dict[str, Any]]:
    """Empresa (adjudicatária) ou adjudicante: por NIF (exato) ou por nome contido."""
    texto = str(valor or "").strip()
    if not texto:
        return None
    nif = service._nif_puro(texto, spec)  # noqa: SLF001
    if spec.key == "PT":
        if nif:
            return {"nested": {"path": spec.adjudicatario_path, "query": {"term": {spec.adjudicatario_nif: nif}}}}
        return {"nested": {"path": spec.adjudicatario_path, "query": {"wildcard": {spec.adjudicatario_nome: {"value": f"*{texto.upper()}*", "case_insensitive": True}}}}}
    if nif:
        return {"wildcard": {spec.adjudicatario_nif: {"value": nif, "case_insensitive": True}}}
    return {"match": {spec.adjudicatario_nome: {"query": texto, "operator": "and"}}}


def pesquisa(
    pais: str = "PT",
    *,
    q: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    campo_data: str = "publicacao",
    ano_from: Optional[int] = None,
    ano_to: Optional[int] = None,
    empresa: Optional[str] = None,
    adjudicante: Optional[str] = None,
    cpv: Optional[str] = None,
    procedimento: Optional[str] = None,
    valor_min: Optional[float] = None,
    valor_max: Optional[float] = None,
    concorrentes_min: Optional[int] = None,
    concorrentes_max: Optional[int] = None,
    so_aditivo: bool = False,
    so_ajuste_direto: bool = False,
    granularidade: str = "mes",
    size: int = 25,
    from_: int = 0,
    es: Any = None,
) -> Dict[str, Any]:
    """Pesquisa de contratos no **universo** com filtros e facetas.

    Devolve os contratos que cumprem os filtros, os KPIs do conjunto filtrado
    (valor, mediana, ajuste direto, aditivos) e as facetas (série temporal na
    granularidade pedida, top CPV, top adjudicatárias, top adjudicantes e
    procedimentos) — todas calculadas por agregação, não por amostra.
    """
    spec = service.COUNTRIES.get(str(pais or "").upper())
    if spec is None:
        return {"error": f"país desconhecido: {pais}", "paises": list(service.COUNTRIES)}
    client = es or get_es_client()
    if client is None:
        return {"error": "Elasticsearch indisponível"}
    granularidade = granularidade if granularidade in GRANULARIDADES else "mes"

    filtros: List[Dict[str, Any]] = []
    if q:
        filtros.append(
            {
                "simple_query_string": {
                    "query": str(q),
                    "fields": ["objectoContrato^3", "descContrato^2", "search_text", "adjudicatarios.raw^2", "adjudicantes.raw"]
                    if spec.key == "PT"
                    else [
                        "objeto^3",
                        "descripcion^2",
                        "search_text",
                        f"{spec.adjudicatario_nome}^2",
                        spec.adjudicante_nome,
                    ],
                    "default_operator": "and",
                    "lenient": True,
                }
            }
        )
    periodo = _filtro_periodo(spec, data_from=data_from, data_to=data_to, campo=campo_data)
    if periodo:
        filtros.append(periodo)
    if ano_from or ano_to:
        intervalo = {}
        if ano_from:
            intervalo["gte"] = int(ano_from)
        if ano_to:
            intervalo["lte"] = int(ano_to)
        filtros.append({"range": {spec.year_field: intervalo}})
    empresa_filtro = _filtro_parte(spec, empresa or "")
    if empresa_filtro:
        filtros.append(empresa_filtro)
    if adjudicante:
        texto = str(adjudicante).strip()
        nif = service._nif_puro(texto, spec)  # noqa: SLF001
        if spec.key == "PT":
            filtros.append(
                {"nested": {"path": spec.adjudicante_path, "query": {"term": {spec.adjudicante_nif: nif}}}}
                if nif
                else {"nested": {"path": spec.adjudicante_path, "query": {"wildcard": {spec.adjudicante_nome: {"value": f"*{texto.upper()}*", "case_insensitive": True}}}}}
            )
        else:
            filtros.append({"terms": {spec.adjudicante_nif: [nif]}} if nif else {"match": {spec.adjudicante_nome: {"query": texto, "operator": "and"}}})
    if cpv:
        prefixo = "".join(ch for ch in str(cpv) if ch.isdigit())
        if prefixo:
            filtros.append(
                {
                    "nested": {
                        "path": spec.cpv_path,
                        "query": {"wildcard": {spec.cpv_code_field: {"value": f"{prefixo}*", "case_insensitive": True}}}
                        if spec.key == "ES"
                        else {"prefix": {spec.cpv_code_field: prefixo}},
                    }
                }
            )
    if procedimento:
        filtros.append({"wildcard": {spec.procedure_field: {"value": f"*{str(procedimento).lower()}*", "case_insensitive": True}}})
    if valor_min is not None or valor_max is not None:
        intervalo_valor: Dict[str, float] = {}
        if valor_min is not None:
            intervalo_valor["gte"] = float(valor_min)
        if valor_max is not None:
            intervalo_valor["lte"] = float(valor_max)
        filtros.append({"range": {spec.value_field: intervalo_valor}})
    if so_ajuste_direto:
        direto = _filtro_direct_award(spec)
        if direto:
            filtros.append(direto)
    if not spec.bidders_is_list and (concorrentes_min is not None or concorrentes_max is not None):
        intervalo_ofertas: Dict[str, int] = {}
        if concorrentes_min is not None:
            intervalo_ofertas["gte"] = int(concorrentes_min)
        if concorrentes_max is not None:
            intervalo_ofertas["lte"] = int(concorrentes_max)
        filtros.append({"range": {spec.bidders_field: intervalo_ofertas}})

    query: Dict[str, Any] = {"bool": {"filter": filtros}} if filtros else {"match_all": {}}
    if so_aditivo and spec.effective_field:
        query = {"bool": {"must": [query], "filter": [{"term": {"aditivo": True}}]}}

    aggs: Dict[str, Any] = {
        "valor": {"stats": {"field": spec.value_field}},
        "mediana": {"percentiles": {"field": spec.value_field, "percents": [50]}},
        "serie": {
            "date_histogram": {"field": spec.pub_date, "calendar_interval": GRANULARIDADES[granularidade]["calendar"], "min_doc_count": 0},
            "aggs": {"valor": {"sum": {"field": spec.value_field}}},
        },
        "procedimentos": {
            "terms": {"field": spec.procedure_field, "size": TAMANHO_FACETA},
            "aggs": {"valor": {"sum": {"field": spec.value_field}}},
        },
        "cpvs": {
            "nested": {"path": spec.cpv_path},
            "aggs": {
                "codigos": {
                    "terms": {"field": spec.cpv_code_field, "size": TAMANHO_FACETA},
                    "aggs": {"valor": {"reverse_nested": {}, "aggs": {"s": {"sum": {"field": spec.value_field}}}}},
                }
            },
        },
        "adjudicatarias": {
            "nested": {"path": spec.adjudicatario_path},
            "aggs": {
                "nifs": {
                    "terms": {"field": spec.adjudicatario_nif, "size": TAMANHO_FACETA},
                    "aggs": {
                        "nome": {"top_hits": {"size": 1, "_source": [spec.adjudicatario_nome]}},
                        "valor": {"reverse_nested": {}, "aggs": {"s": {"sum": {"field": spec.value_field}}}},
                    },
                }
            },
        },
        "adjudicantes": {
            "nested": {"path": spec.adjudicante_path},
            "aggs": {
                "nifs": {
                    "terms": {"field": spec.adjudicante_nif, "size": TAMANHO_FACETA},
                    "aggs": {
                        "nome": {"top_hits": {"size": 1, "_source": [spec.adjudicante_nome]}},
                        "valor": {"reverse_nested": {}, "aggs": {"s": {"sum": {"field": spec.value_field}}}},
                    },
                }
            },
        },
    }
    if spec.key == "PT":
        aggs["aditivos"] = {"filter": {"term": {"aditivo": True}}, "aggs": {"valor": {"sum": {"field": spec.effective_field}}}}
        aggs["sem_concorrentes"] = {
            "filter": {
                "bool": {
                    "should": [
                        {"term": {f"{spec.bidders_field}.keyword": ""}},
                        {"bool": {"must_not": [{"exists": {"field": spec.bidders_field}}]}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        }
    else:
        aggs["ofertas"] = {"stats": {"field": spec.bidders_field}}
        aggs["sem_concorrentes"] = {
            "filter": {"bool": {"must_not": [{"exists": {"field": spec.bidders_field}}]}}
        }

    body: Dict[str, Any] = {
        "size": max(1, min(int(size), 100)),
        "from": max(0, int(from_)),
        "track_total_hits": True,
        "query": query,
        "sort": [{spec.pub_date: {"order": "desc", "unmapped_type": "date"}}, "_score"],
        "_source": list(spec.source_fields),
        "aggs": aggs,
    }
    runtime = _runtime_aditivo(spec)
    if runtime:
        body["runtime_mappings"] = runtime
    try:
        resposta = service._search(client, spec.index, body, timeout=300)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        logger.warning("Pesquisa global falhou: %s", exc)
        return {"error": f"falha na pesquisa: {exc}"}
    if not resposta:
        return {"error": "falha na pesquisa: sem resposta do Elasticsearch"}

    agregados = resposta.get("aggregations") or {}
    itens = []
    for hit in service._hits(resposta):  # noqa: SLF001
        linha = service._row_from_hit(spec, hit)  # noqa: SLF001
        itens.append(
            {
                "id": linha.get("id"),
                "ano": linha.get("ano"),
                "data_publicacao": linha.get("data_publicacao"),
                "objeto": linha.get("objeto"),
                "cpv": linha.get("cpv"),
                "cpv_grupo": linha.get("cpv_grupo"),
                "cpv_desc": linha.get("cpv_desc"),
                "valor": service.num(linha.get("valor")),
                "preco_base": service.num(linha.get("base")),
                "valor_efetivo": service.num(linha.get("efetivo")),
                "ratio_base": service.num(linha.get("ratio_base")),
                "ratio_efetivo": service.num(linha.get("ratio_efetivo")),
                "procedimento": linha.get("procedimento"),
                "ajuste_direto": bool(linha.get("ajuste_direto")),
                "n_concorrentes": linha.get("n_concorrentes"),
                "adjudicante": linha.get("adjudicante_nome"),
                "adjudicante_nif": linha.get("adjudicante_nif"),
                "adjudicataria": next(
                    (parte.get("nome") for parte in linha.get("adjudicatarios") or [] if parte.get("nome")),
                    None,
                ),
                "adjudicataria_nif": next(
                    (parte.get("nif") for parte in linha.get("adjudicatarios") or [] if parte.get("nif")),
                    None,
                ),
                "dias_assinatura": linha.get("dias_assinatura"),
                "dias_publicacao": linha.get("dias_publicacao"),
            }
        )

    valor = agregados.get("valor") or {}
    aditivos = agregados.get("aditivos") or {}
    procedimentos = (agregados.get("procedimentos") or {}).get("buckets") or []
    ajuste = _classificar_ajuste_direto(spec, procedimentos)
    total = int(((resposta.get("hits") or {}).get("total") or {}).get("value") or 0)
    return {
        "pais": spec.key,
        "pais_label": spec.label,
        "granularidade": granularidade,
        "granularidades": [{"id": chave, "label": valor_["label"]} for chave, valor_ in GRANULARIDADES.items()],
        "total": total,
        "items": itens,
        "filtros": {
            "q": q,
            "data_from": data_from,
            "data_to": data_to,
            "campo_data": campo_data,
            "ano_from": ano_from,
            "ano_to": ano_to,
            "empresa": empresa,
            "adjudicante": adjudicante,
            "cpv": cpv,
            "procedimento": procedimento,
            "valor_min": valor_min,
            "valor_max": valor_max,
            "concorrentes_min": concorrentes_min,
            "concorrentes_max": concorrentes_max,
            "so_aditivo": so_aditivo,
            "so_ajuste_direto": so_ajuste_direto,
        },
        "kpis": {
            "contratos": total,
            "valor": service.num(valor.get("sum")),
            "valor_medio": service.num(valor.get("avg")),
            "valor_mediano": service.num((agregados.get("mediana") or {}).get("values", {}).get("50.0")),
            "valor_maximo": service.num(valor.get("max")),
            "ajuste_direto": ajuste,
            "aditivos": int(aditivos.get("doc_count") or 0) if aditivos else None,
            "valor_aditivos": service.num(((aditivos.get("valor") or {}).get("value"))) if aditivos else None,
            "taxa_aditivo": service.num((aditivos.get("doc_count") or 0) / total) if aditivos and total else None,
            "sem_concorrentes": int(((agregados.get("sem_concorrentes") or {}).get("doc_count") or 0)),
            "ofertas_media": service.num(((agregados.get("ofertas") or {}).get("avg"))) if agregados.get("ofertas") else None,
        },
        "serie": [
            {"periodo": item.get("key_as_string"), "contratos": int(item.get("doc_count") or 0), "valor": service.num(((item.get("valor") or {}).get("value")))}
            for item in ((agregados.get("serie") or {}).get("buckets") or [])
        ],
        "facetas": {
            "cpvs": [
                {
                    "cpv": item.get("key"),
                    "contratos": int(item.get("doc_count") or 0),
                    "valor": service.num(((item.get("valor") or {}).get("s") or {}).get("value")),
                }
                for item in (((agregados.get("cpvs") or {}).get("codigos") or {}).get("buckets") or [])
            ],
            "adjudicatarias": [
                {
                    "nif": item.get("key"),
                    "nome": _top_hits_nome(item.get("nome")) or item.get("key"),
                    "contratos": int(item.get("doc_count") or 0),
                    "valor": service.num(((item.get("valor") or {}).get("s") or {}).get("value")),
                }
                for item in (((agregados.get("adjudicatarias") or {}).get("nifs") or {}).get("buckets") or [])
            ],
            "adjudicantes": [
                {
                    "nif": item.get("key"),
                    "nome": _top_hits_nome(item.get("nome")) or item.get("key"),
                    "contratos": int(item.get("doc_count") or 0),
                    "valor": service.num(((item.get("valor") or {}).get("s") or {}).get("value")),
                }
                for item in (((agregados.get("adjudicantes") or {}).get("nifs") or {}).get("buckets") or [])
            ],
            "procedimentos": [
                {
                    "procedimento": item.get("key"),
                    "contratos": int(item.get("doc_count") or 0),
                    "valor": service.num(((item.get("valor") or {}).get("value"))),
                }
                for item in procedimentos[:TAMANHO_FACETA]
            ],
        },
        "pagina": {"size": int(size), "from": int(from_)},
        "gerado_em": _agora(),
    }


def meta(pais: str = "PT") -> Dict[str, Any]:
    """Estado e catálogo do dashboard global (para a página e diagnóstico)."""
    spec = service.COUNTRIES.get(str(pais or "").upper())
    if spec is None:
        return {"error": f"país desconhecido: {pais}", "paises": list(service.COUNTRIES)}
    client = get_es_client()
    documentos = None
    guardado: Optional[Dict[str, Any]] = None
    if client is not None:
        try:
            documentos = int(client.count(index=GLOBAL_PADROES_INDEX).get("count") or 0)
        except Exception:  # noqa: BLE001
            documentos = None
        guardado = _ler_documento(client, f"{spec.key}:_meta")
    return {
        "pais": spec.key,
        "pais_label": spec.label,
        "indice": spec.index,
        "indice_materializado": GLOBAL_PADROES_INDEX,
        "documentos": documentos,
        "guardado": bool(guardado),
        "materializado_em": (guardado or {}).get("gerado_em"),
        "anos": (guardado or {}).get("anos") or [],
        "documentos_universo": (guardado or {}).get("documentos"),
        "duracao_s": (guardado or {}).get("duracao_s"),
        "estado": estado(),
        "granularidades": [{"id": chave, "label": valor["label"]} for chave, valor in GRANULARIDADES.items()],
        "anos_padrao": ANOS_PADRAO,
        "aviso": (
            "A sincronização agrega o índice inteiro (2,2 M de contratos PT; 4 M ES) e pode demorar. "
            "Corre em segundo plano: a página acompanha o estado e usa o último resultado."
        ),
    }
