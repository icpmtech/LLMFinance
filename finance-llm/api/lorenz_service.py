"""Modelo Lorenz 1963 aplicado à contratação pública — **qualquer área**.

O que este motor faz, e o que **não** faz
----------------------------------------
Edward Lorenz (1963) mostrou que, em sistemas determinísticos não lineares,
diferenças mínimas nas condições iniciais podem produzir trajetórias muito
diferentes. O «efeito borboleta» **não** significa que qualquer acontecimento
pequeno provoca uma crise: a amplificação depende da **estrutura** do sistema
(graus, concentração, alternativas) e dos **mecanismos de propagação**.

Por isso este módulo não anuncia catástrofes. Faz três coisas verificáveis:

1. **Estado observado** — por período (ano/trimestre) e por área (prefixos de
   CPV, região, entidade, valores), mede contratos, valor, compradores,
   fornecedores, concentração (`quota_top1`, `hhi`), dispersão de valores
   (`p50/p95/p99`) e taxa de ajuste direto.
2. **Sensibilidade** — (a) um **mapa discreto** ``s_{t+1} = A·s_t + b`` ajustado
   à série observada, com **expoente de Lyapunov empírico** (Benettin: perturba,
   propaga, renormaliza) e as séries de divergência ``D_t``; (b) as equações de
   Lorenz clássicas integradas por Runge-Kutta com parâmetros **análogos medidos
   na estrutura** (σ = oferta/procura, β = dissipação, ρ = ρ_crit·margem), para
   dizer se o regime observado está do lado **amplificador** ou **dissipador** da
   fronteira de instabilidade ρ_crit.
3. **Propagação** — no grafo fornecedor↔comprador: uma perturbação (atraso de
   7/30/60 dias, perda de capacidade de um fornecedor) propaga-se pelos
   compradores conforme a **dependência** (quota), agrava-se com a **dificuldade
   de substituição** (quota do fornecedor no CPV) e, em 2.ª ordem, a realocação
   **desloca a concentração** para outros fornecedores — criando novas
   fragilidades. Cada linha tem **evidência** (contratos reais: nº, data, valor).

O que **não** é: previsão. Sem dados de stocks, prazos de entrega,
substitutibilidade técnica e criticidade clínica, o custo potencial é um
**cenário com hipóteses explícitas** (prémio de urgência configurável), não uma
conta. Todas as hipóteses vêm em `hipoteses` na resposta.

Lições dos dados (contratos PT) que este código respeita
-------------------------------------------------------
- `adjudicantes`/`adjudicatarios` são **objetos** com `parsed` **nested** — para
  agregar por parte é preciso `nested` + `reverse_nested` para voltar ao valor do
  documento.
- `exists` num subcampo nested devolve 0 → usar `nested`+`match_all`.
- `terms` tem teto de 10 000 buckets e o ES recusa ~65 mil: o CPV é agregado
  pelo código completo e a **classe (4 dígitos)** é calculada em Python.
- `from/size` rebenta acima de 10 000 → para o cruzamento comprador→fornecedor
  usa-se **`msearch`** (uma consulta por comprador), que é exato e barato.
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from elasticsearch import Elasticsearch

from api.elasticsearch_client import (
    CONTRACTS_INDEX,
    LORENZ_RUNS_INDEX,
    UNSPECIFIED_LABEL,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuração: áreas de contratação (o «qualquer área» do pedido)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(os.environ.get("LORENZ_CONFIG_PATH") or (ROOT / "data" / "lorenz" / "config.json"))

#: Prefixos de CPV por área. O CPV em PT é `keyword` («33600000-6»), pelo que um
#: prefixo de 2 dígitos cobre a divisão, 3-4 dígitos a classe e 8 o código.
AREAS_DEFAULT: List[Dict[str, Any]] = [
    {
        "id": "todas",
        "label": "Todas as áreas",
        "cpv_prefixos": [],
        "descricao": "Sem filtro de CPV: o universo do escopo escolhido (região, anos, valores).",
    },
    {
        "id": "saude",
        "label": "Saúde (dispositivos, farmácia e serviços)",
        "cpv_prefixos": ["33", "851"],
        "descricao": "Dispositivos médicos e farmacêuticos (div. 33) e serviços de saúde (851*).",
    },
    {
        "id": "medicamentos",
        "label": "Medicamentos e produtos farmacêuticos",
        "cpv_prefixos": ["336"],
        "descricao": "CPV 336* — a classe com maior concentração de valor em Portugal.",
    },
    {
        "id": "dispositivos",
        "label": "Dispositivos e equipamento médico",
        "cpv_prefixos": ["331", "3314", "3319", "3843"],
        "descricao": "Equipamento médico, próteses e material clínico (331*, 3843*).",
    },
    {
        "id": "construcao",
        "label": "Construção e obras públicas",
        "cpv_prefixos": ["45"],
        "descricao": "Obra civil e construção (div. 45) — contratos longos e aditivos frequentes.",
    },
    {
        "id": "ti",
        "label": "Tecnologias de informação",
        "cpv_prefixos": ["30", "48", "72", "73"],
        "descricao": "Hardware (30*), software (48*) e serviços de TI (72*/73*).",
    },
    {
        "id": "energia",
        "label": "Energia e combustíveis",
        "cpv_prefixos": ["09", "31", "65", "425"],
        "descricao": "Combustíveis (09*), eletricidade (31*), utilities (65*), frio/calor (425*).",
    },
    {
        "id": "transportes",
        "label": "Transportes e mobilidade",
        "cpv_prefixos": ["34", "60", "63"],
        "descricao": "Veículos (34*), transportes (60*) e apoio a transportes (63*).",
    },
    {
        "id": "alimentar",
        "label": "Alimentação e catering",
        "cpv_prefixos": ["15", "55"],
        "descricao": "Produtos alimentares (15*) e serviços de restauração (55*).",
    },
    {
        "id": "servicos_publicos",
        "label": "Serviços públicos e socais",
        "cpv_prefixos": ["75", "79", "80", "85"],
        "descricao": "Administração (75*), jurídicos (79*), formação (80*), sociais e saúde (85*).",
    },
    {
        "id": "limpeza_manutencao",
        "label": "Limpeza, manutenção e facility management",
        "cpv_prefixos": ["90", "50", "51", "508", "507"],
        "descricao": "Limpeza e gestão de resíduos (90*), reparação e manutenção (50*/51*).",
    },
]

#: Parâmetros do modelo e hipóteses dos cenários (tudo substituível no ficheiro).
PARAMETROS_DEFAULT: Dict[str, Any] = {
    # --- amostragem / tetos (documentados na resposta em `cobertura` e `limites`)
    "top_compradores": 40,
    "top_cpvs": 24,
    "fornecedores_por_comprador": 25,
    "compradores_por_fornecedor": 25,
    "cpv_por_comprador": 8,
    "top_fornecedores_periodo": 20,
    "limiar_critico": 0.30,
    "limiar_fragil": 0.60,
    # --- série
    "periodos_minimos": 4,
    "serie_max_periodos": 40,
    # --- dinâmica
    "dt": 0.01,
    # 12 000 passos ≈ 0,18 s: com 2 000 o λ do sistema clássico ainda não
    # convergiu (0,35 em vez de ~0,9) e o regime lido ficaria errado.
    "passos_lorenz": 12000,
    "perturbacao": 1e-4,
    "horizonte_mapa": 6,
    "direcoes_perturbacao": 12,
    "semente": 42,
    # Referência da razão fornecedores/compradores para calibrar σ (estrutura típica).
    "razao_referencia": 3.0,
    # --- hipóteses dos cenários de atraso (prémio de urgência por atraso)
    "premio_atraso": [[0, 0.0], [7, 0.02], [30, 0.07], [60, 0.15], [120, 0.25]],
    "perda_capacidade": [0.10, 0.25, 0.50],
}

#: Níveis de atraso dos cenários pedidos no modelo (7 / 30 / 60 dias).
ATRASOS_DIAS: Tuple[int, ...] = (7, 30, 60)

#: Regras de ajuste direto (o `tipoprocedimento` é `text`; conta-se por prefixo).
AJUSTE_DIRETO_PREFIXOS: Tuple[str, ...] = (
    "ajuste direto",
    "consulta previa",
    "contratacao excluida",
    "acordo quadro",  # não é ajuste direto, mas entra no mesmo grupo de baixa competição? não: excluído abaixo
)
AJUSTE_DIRETO_EXCLUIDOS: Tuple[str, ...] = ("acordo quadro",)


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _arredondar(valor: Any, casas: int = 4) -> Any:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return valor
    if not math.isfinite(numero):
        return None
    return round(numero, casas)


def _num(valor: Any, omissao: float = 0.0) -> float:
    """Número tolerante a `None`/`"-"`/grupos absurdos (o ES devolve `None` em somas vazias)."""
    if valor is None:
        return omissao
    if isinstance(valor, (int, float)):
        numero = float(valor)
        return numero if math.isfinite(numero) else omissao
    try:
        texto = str(valor).strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
        if not texto:
            return omissao
        numero = float(texto)
    except (TypeError, ValueError):
        return omissao
    return numero if math.isfinite(numero) else omissao


def _limitar(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(maximo, valor))


def _classe_cpv(codigo: Optional[str]) -> str:
    """Classe CPV de 4 dígitos a partir do código («33600000-6» → «3360»)."""
    if not codigo:
        return UNSPECIFIED_LABEL
    digitos = "".join(ch for ch in str(codigo) if ch.isdigit())
    if len(digitos) < 2:
        return UNSPECIFIED_LABEL
    return digitos[:4] if len(digitos) >= 4 else digitos


def _divisao_cpv(codigo: Optional[str]) -> str:
    digitos = "".join(ch for ch in str(codigo or "") if ch.isdigit())
    return digitos[:2] if len(digitos) >= 2 else UNSPECIFIED_LABEL


def _chave_nif(parte: Dict[str, Any]) -> Optional[str]:
    """NIF da parte, a partir do formato PT (`parsed` nested) ou de listas planas."""
    if not isinstance(parte, dict):
        return None
    parsed = parte.get("parsed")
    if isinstance(parsed, list):
        for entrada in parsed:
            if isinstance(entrada, dict) and entrada.get("nif"):
                return str(entrada["nif"])
    if parte.get("nif"):
        return str(parte["nif"])
    return None


def _nome_parte(parte: Dict[str, Any], omissao: str = "") -> str:
    if not isinstance(parte, dict):
        return omissao
    parsed = parte.get("parsed")
    if isinstance(parsed, list):
        for entrada in parsed:
            if isinstance(entrada, dict) and entrada.get("nome"):
                return str(entrada["nome"])
    if parte.get("nome"):
        return str(parte["nome"])
    return omissao


def _fold(texto: str) -> str:
    """Minúsculas sem acentos (para comparar `tipoprocedimento`)."""
    import unicodedata

    base = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(ch for ch in base if not unicodedata.combining(ch)).lower().strip()


def _nome_do_hit(fonte: Any) -> str:
    """Nome de um `top_hits` — dentro de `nested` o `_source` é o próprio objeto.

    Fora do `nested` o `_source` traz a raiz do documento (`{"adjudicantes": {...}}`);
    dentro, traz o objeto aninhado (`{"nif": ..., "nome": ...}`). Os dois casos
    aparecem neste módulo, por isso a função aceita ambos.
    """
    if not isinstance(fonte, dict):
        return ""
    for campo in ("adjudicantes", "adjudicatarios"):
        if isinstance(fonte.get(campo), dict):
            nome = _nome_parte(fonte[campo])
            if nome:
                return nome
    if fonte.get("nome"):
        return str(fonte["nome"])
    return ""


def _nome_de_hits(bucket: Dict[str, Any]) -> str:
    hits = ((bucket.get("nome") or {}).get("hits") or {}).get("hits") or []
    if not hits:
        return ""
    return _nome_do_hit(hits[0].get("_source"))


def _target_agregavel(campo: str, es: Optional[Elasticsearch] = None) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Campo utilizável em `terms` + `runtime_mappings` quando o mapping o exige.

    Reutiliza o resolvedor do cliente ES: alguns campos declarados `text` estão
    indexados como `keyword` e agregar `campo.keyword` às cegas devolvia vazio.
    """
    cliente = _cliente(es)
    if cliente is None:
        return f"{campo}.keyword", None
    try:
        from api.elasticsearch_client import _resolve_agg_target

        resolvido = _resolve_agg_target(cliente, campo)
        return resolvido.get("field") or f"{campo}.keyword", resolvido.get("runtime")
    except Exception:  # noqa: BLE001 — recuo conservador
        return f"{campo}.keyword", None


def _com_runtime(corpo: Dict[str, Any], runtime: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if runtime:
        corpo["runtime_mappings"] = runtime
    return corpo


# ---------------------------------------------------------------------------
# Áreas e parâmetros (ficheiro JSON editável, escrita atómica, cache por mtime)
# ---------------------------------------------------------------------------
_config_cache: Dict[str, Any] = {"mtime": None, "dados": None}
_config_lock = threading.Lock()


def _config_vazia() -> Dict[str, Any]:
    return {"areas": AREAS_DEFAULT, "parametros": PARAMETROS_DEFAULT, "atualizado_em": None}


def _ler_config(forcar: bool = False) -> Dict[str, Any]:
    with _config_lock:
        try:
            mtime = CONFIG_PATH.stat().st_mtime
        except OSError:
            mtime = None
        if not forcar and _config_cache["dados"] is not None and _config_cache["mtime"] == mtime:
            return _config_cache["dados"]
        dados = _config_vazia()
        if mtime is not None:
            try:
                lido = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(lido, dict):
                    if isinstance(lido.get("areas"), list) and lido["areas"]:
                        dados["areas"] = lido["areas"]
                    if isinstance(lido.get("parametros"), dict):
                        dados["parametros"] = {**PARAMETROS_DEFAULT, **lido["parametros"]}
                    dados["atualizado_em"] = lido.get("atualizado_em")
            except (OSError, ValueError) as erro:  # ficheiro corrompido: usa as predefinições
                logger.warning("lorenz: config ilegível (%s) — a usar predefinições", erro)
        _config_cache["mtime"] = mtime
        _config_cache["dados"] = dados
        return dados


def _escrever_config(areas: List[Dict[str, Any]], parametros: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    atual = _ler_config()
    dados = {
        "areas": areas,
        "parametros": {**PARAMETROS_DEFAULT, **(parametros if parametros is not None else atual["parametros"])},
        "atualizado_em": _agora(),
    }
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporario = CONFIG_PATH.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(CONFIG_PATH)
    _config_cache["mtime"] = None
    _config_cache["dados"] = None
    return _ler_config(forcar=True)


def areas() -> List[Dict[str, Any]]:
    """Áreas disponíveis (as predefinidas mais as que o utilizador acrescentar)."""
    return list(_ler_config()["areas"])


def parametros() -> Dict[str, Any]:
    return dict(_ler_config()["parametros"])


def guardar_areas(areas_novas: List[Dict[str, Any]], parametros_novos: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Grava as áreas (valida ids únicos e prefixos CPV de dígitos)."""
    limpas: List[Dict[str, Any]] = []
    vistos: set = set()
    for area in areas_novas:
        identificador = str(area.get("id") or "").strip().lower()
        if not identificador or identificador in vistos:
            continue
        vistos.add(identificador)
        prefixos = [
            str(prefixo).strip()
            for prefixo in (area.get("cpv_prefixos") or [])
            if str(prefixo).strip().isdigit()
        ]
        limpas.append(
            {
                "id": identificador,
                "label": str(area.get("label") or identificador).strip() or identificador,
                "cpv_prefixos": prefixos,
                "descricao": str(area.get("descricao") or "").strip(),
            }
        )
    if not limpas:
        limpas = list(AREAS_DEFAULT)
    return _escrever_config(limpas, parametros_novos)


def _area_por_id(area_id: Optional[str]) -> Dict[str, Any]:
    if not area_id:
        return next((a for a in areas() if a.get("id") == "todas"), AREAS_DEFAULT[0])
    for area in areas():
        if area.get("id") == area_id:
            return area
    return {
        "id": str(area_id),
        "label": f"Área personalizada ({area_id})",
        "cpv_prefixos": [p for p in str(area_id).split(",") if p.strip().isdigit()],
        "descricao": "Área definida por prefixos de CPV no parâmetro `area`.",
    }


# ---------------------------------------------------------------------------
# Escopo (filtros) e consultas
# ---------------------------------------------------------------------------
def escopo(
    *,
    area: Optional[str] = None,
    cpv: Optional[str] = None,
    ano_de: Optional[int] = None,
    ano_ate: Optional[int] = None,
    regiao: Optional[str] = None,
    nif: Optional[str] = None,
    nif_contraparte: Optional[str] = None,
    valor_min: Optional[float] = None,
    valor_max: Optional[float] = None,
    texto: Optional[str] = None,
    ecologico: Optional[bool] = None,
) -> Dict[str, Any]:
    """Constrói os filtros do escopo (área → prefixos CPV; `cpv` sobrepõe-se)."""
    definicao = _area_por_id(area)
    prefixos: List[str] = []
    if cpv:
        prefixos = [p.strip() for p in str(cpv).split(",") if p.strip().isdigit()]
    if not prefixos:
        prefixos = [p for p in (definicao.get("cpv_prefixos") or []) if str(p).isdigit()]
    filtros: List[Dict[str, Any]] = []
    if prefixos:
        filtros.append(
            {
                "bool": {
                    "should": [
                        {"nested": {"path": "cpv", "query": {"wildcard": {"cpv.code": f"{prefixo}*"}}}}
                        for prefixo in prefixos
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if ano_de is not None or ano_ate is not None:
        intervalo: Dict[str, Any] = {}
        if ano_de is not None:
            intervalo["gte"] = int(ano_de)
        if ano_ate is not None:
            intervalo["lte"] = int(ano_ate)
        filtros.append({"range": {"Ano": intervalo}})
    if regiao:
        filtros.append({"term": {"NUTs": regiao}})
    if nif and nif_contraparte:
        filtros.append(
            {
                "bool": {
                    "must": [
                        {"nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": nif}}}},
                        {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": nif_contraparte}}}},
                    ]
                }
            }
        )
    elif nif:
        filtros.append(
            {
                "bool": {
                    "should": [
                        {"nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": nif}}}},
                        {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": nif}}}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if valor_min is not None or valor_max is not None:
        intervalo_valor: Dict[str, Any] = {}
        if valor_min is not None:
            intervalo_valor["gte"] = valor_min
        if valor_max is not None:
            intervalo_valor["lte"] = valor_max
        filtros.append(
            {
                "bool": {
                    "should": [
                        {"range": {"precoContratual": intervalo_valor}},
                        {"range": {"PrecoTotalEfetivo": intervalo_valor}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if ecologico:
        filtros.append({"term": {"ContratEcologico.keyword": "Sim"}})
    if texto:
        filtros.append(
            {
                "multi_match": {
                    "query": texto,
                    "fields": ["objectoContrato^3", "descContrato^2", "adjudicantes.parsed.nome", "adjudicatarios.parsed.nome"],
                    "type": "best_fields",
                    "operator": "and",
                }
            }
        )
    return {
        "area": definicao.get("id"),
        "area_label": definicao.get("label"),
        "cpv_prefixos": prefixos,
        "ano_de": ano_de,
        "ano_ate": ano_ate,
        "regiao": regiao,
        "nif": nif,
        "nif_contraparte": nif_contraparte,
        "valor_min": valor_min,
        "valor_max": valor_max,
        "texto": texto,
        "ecologico": bool(ecologico),
        # Sempre `bool.filter` (mesmo vazio): os outros módulos do ficheiro
        # acrescentam filtros ao escopo e um `match_all` nu rebentava-os com KeyError.
        "query": {"bool": {"filter": filtros}},
    }


def _cliente(es: Optional[Elasticsearch] = None) -> Optional[Elasticsearch]:
    return es if es is not None else get_es_client()


def _pesquisar(corpo: Dict[str, Any], es: Optional[Elasticsearch] = None, index: str = CONTRACTS_INDEX) -> Dict[str, Any]:
    cliente = _cliente(es)
    if cliente is None:
        return {"erro": "Elasticsearch indisponível", "hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}
    try:
        return cliente.search(index=index, body=corpo)
    except Exception as erro:  # noqa: BLE001 — a UI mostra a mensagem
        logger.warning("lorenz: consulta falhou (%s)", erro)
        return {"erro": str(erro), "hits": {"total": {"value": 0}, "hits": []}, "aggregations": {}}


def _msearch(pedidos: List[Dict[str, Any]], es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """`msearch` em blocos (uma consulta por comprador/CPV: exato e sem amostra)."""
    cliente = _cliente(es)
    if cliente is None or not pedidos:
        return []
    respostas: List[Dict[str, Any]] = []
    for inicio in range(0, len(pedidos), 20):
        bloco = pedidos[inicio : inicio + 20]
        corpo: List[Dict[str, Any]] = []
        for pedido in bloco:
            corpo.append({"index": CONTRACTS_INDEX})
            corpo.append(pedido)
        try:
            resposta = cliente.msearch(body=corpo)
            respostas.extend(resposta.get("responses", []) or [])
        except Exception as erro:  # noqa: BLE001
            logger.warning("lorenz: msearch falhou (%s)", erro)
            respostas.extend([{"error": str(erro)} for _ in bloco])
    return respostas


# ---------------------------------------------------------------------------
# 1. Estado observado — série por período
# ---------------------------------------------------------------------------
def _aggs_periodo(caminho_comprador: str, caminho_fornecedor: str, top_fornecedores: int, campo_procedimento: str) -> Dict[str, Any]:
    return {
        "valor": {"sum": {"field": "precoContratual"}},
        "valor_efetivo": {"sum": {"field": "PrecoTotalEfetivo"}},
        "percentis": {"percentiles": {"field": "precoContratual", "percents": [50, 95, 99], "keyed": True}},
        "compradores": {
            "nested": {"path": caminho_comprador},
            "aggs": {"n": {"cardinality": {"field": f"{caminho_comprador}.nif"}}},
        },
        "fornecedores": {
            "nested": {"path": caminho_fornecedor},
            "aggs": {"n": {"cardinality": {"field": f"{caminho_fornecedor}.nif"}}},
        },
        "top_fornecedores": {
            "nested": {"path": caminho_fornecedor},
            "aggs": {
                "por_nif": {
                    "terms": {"field": f"{caminho_fornecedor}.nif", "size": top_fornecedores},
                    "aggs": {"documento": {"reverse_nested": {}, "aggs": {"valor": {"sum": {"field": "precoContratual"}}}}},
                }
            },
        },
        "procedimentos": {"terms": {"field": campo_procedimento, "size": 25}},
    }


def serie(escopo_def: Dict[str, Any], *, granularidade: str = "ano", es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Série por período com o estado observado (contratos, valor, concentração, dispersão)."""
    config = parametros()
    campo_procedimento, runtime = _target_agregavel("tipoprocedimento", es)
    aggs = _aggs_periodo("adjudicantes.parsed", "adjudicatarios.parsed", int(config["top_fornecedores_periodo"]), campo_procedimento)
    corpo = _com_runtime(
        {
            "size": 0,
            "track_total_hits": True,
            "query": escopo_def["query"],
            "aggs": {
                "periodos": {
                    "terms": {
                        "field": "Ano",
                        "size": int(config["serie_max_periodos"]),
                        "order": {"_key": "asc"},
                    },
                    "aggs": aggs,
                }
            },
        },
        runtime,
    )
    if granularidade == "trimestre":
        corpo["aggs"] = {
            "periodos": {
                "date_histogram": {
                    "field": "dataPublicacao",
                    "calendar_interval": "quarter",
                    "min_doc_count": 1,
                },
                "aggs": aggs,
            }
        }
    resposta = _pesquisar(corpo, es=es)
    if resposta.get("erro"):
        return {"erro": resposta["erro"], "periodos": [], "total_documentos": 0}
    buckets = ((resposta.get("aggregations") or {}).get("periodos") or {}).get("buckets") or []
    periodos: List[Dict[str, Any]] = []
    for bucket in buckets:
        if granularidade == "trimestre":
            periodo = (bucket.get("key_as_string") or "")[:7]
        else:
            periodo = str(bucket.get("key"))
        valor = _num(bucket.get("valor", {}).get("value"))
        # `keyed: True` devolve `{"values": {"50.0": …}}` — sem o `values` os
        # percentis vinham a zero e a «cauda» ficava constante (defeito silencioso).
        percentis = bucket.get("percentis") or {}
        if isinstance(percentis.get("values"), dict):
            percentis = percentis["values"]
        p50 = _num(percentis.get("50.0"))
        p95 = _num(percentis.get("95.0"))
        p99 = _num(percentis.get("99.0"))
        tops = ((bucket.get("top_fornecedores") or {}).get("por_nif") or {}).get("buckets") or []
        valores_top = [_num((t.get("documento") or {}).get("valor", {}).get("value")) for t in tops]
        soma_top = sum(valores_top)
        cobertura_top = (soma_top / valor) if valor > 0 else 0.0
        quota_top1 = (valores_top[0] / valor) if valor > 0 and valores_top else 0.0
        hhi_top = sum((v / valor) ** 2 for v in valores_top) if valor > 0 else 0.0
        procedimentos = ((bucket.get("procedimentos") or {}).get("buckets")) or []
        ajuste = sum(
            _num(p.get("doc_count"))
            for p in procedimentos
            if _fold(p.get("key")) not in AJUSTE_DIRETO_EXCLUIDOS
            and any(_fold(p.get("key")).startswith(prefixo) for prefixo in AJUSTE_DIRETO_PREFIXOS)
        )
        contratos = int(_num(bucket.get("doc_count")))
        periodos.append(
            {
                "periodo": periodo,
                "contratos": contratos,
                "valor": valor,
                "valor_efetivo": _num(bucket.get("valor_efetivo", {}).get("value")),
                "p50": p50,
                "p95": p95,
                "p99": p99,
                "cauda": ((p99 - p50) / p50) if p50 > 0 else 0.0,
                "compradores": int(_num((bucket.get("compradores") or {}).get("n", {}).get("value"))),
                "fornecedores": int(_num((bucket.get("fornecedores") or {}).get("n", {}).get("value"))),
                "quota_top1": quota_top1,
                "hhi_top": hhi_top,
                "cobertura_top": cobertura_top,
                "ajuste_direto": ajuste,
                "taxa_ajuste_direto": (ajuste / contratos) if contratos else 0.0,
                "top_fornecedores": [
                    {
                        "nif": t.get("key"),
                        "valor": valores_top[i],
                        "contratos": int(_num(t.get("doc_count"))),
                        "quota": (valores_top[i] / valor) if valor > 0 else 0.0,
                    }
                    for i, t in enumerate(tops)
                ],
            }
        )
    return {
        "granularidade": granularidade,
        "total_documentos": int(_num(((resposta.get("hits") or {}).get("total") or {}).get("value"))),
        "periodos": periodos,
    }


# ---------------------------------------------------------------------------
# 2. Grafo de dependências (comprador→fornecedor e CPV)
# ---------------------------------------------------------------------------
def _topo_por_papel(escopo_def: Dict[str, Any], papel: str, limite: int, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Top de entidades num papel, por valor.

    O `terms` **não** pode ser ordenado pelo valor: a soma vive num
    `reverse_nested` (agregação de um só balde) e o Elasticsearch recusa
    («Invalid aggregation order path»). Ordena-se por `_count` — que é legal e
    barato — e reordena-se por valor em Python, pedindo uma margem maior de
    baldes.
    """
    caminho = "adjudicantes.parsed" if papel == "adjudicante" else "adjudicatarios.parsed"
    corpo = {
        "size": 0,
        "track_total_hits": False,
        "query": escopo_def["query"],
        "aggs": {
            "partes": {
                "nested": {"path": caminho},
                "aggs": {
                    "por_nif": {
                        "terms": {
                            "field": f"{caminho}.nif",
                            "size": int(min(max(limite * 4, 40), 1000)),
                            "missing": UNSPECIFIED_LABEL,
                        },
                        "aggs": {
                            # Sem `_source`: dentro de `nested` o `top_hits` devolve o
                            # objeto aninhado (`{nif, nome}`); com `_source: ["nif","nome"]`
                            # vinha **vazio** (o filtro é aplicado à raiz do documento).
                            "nome": {"top_hits": {"size": 1}},
                            "documento": {"reverse_nested": {}, "aggs": {"valor": {"sum": {"field": "precoContratual"}}}},
                        },
                    }
                },
            }
        },
    }
    resposta = _pesquisar(corpo, es=es)
    buckets = (((resposta.get("aggregations") or {}).get("partes") or {}).get("por_nif") or {}).get("buckets") or []
    partes: List[Dict[str, Any]] = []
    for bucket in buckets:
        nif = bucket.get("key")
        partes.append(
            {
                "nif": None if nif == UNSPECIFIED_LABEL else nif,
                "nome": _nome_de_hits(bucket) or str(nif or UNSPECIFIED_LABEL),
                "valor": _num((bucket.get("documento") or {}).get("valor", {}).get("value")),
                "contratos": int(_num(bucket.get("doc_count"))),
            }
        )
    partes.sort(key=lambda item: item["valor"], reverse=True)
    return partes[:limite]


def _aggs_detalhe_parte(caminho_contraparte: str, limite: int, cpv_limite: int, campo_procedimento: str) -> Dict[str, Any]:
    return {
        "contrapartes": {
            "nested": {"path": caminho_contraparte},
            "aggs": {
                "por_nif": {
                    "terms": {"field": f"{caminho_contraparte}.nif", "size": limite, "missing": UNSPECIFIED_LABEL},
                    "aggs": {
                        # Sem `_source`: dentro de `nested` o `top_hits` devolve o objeto
                        # aninhado (`{nif, nome}`); com `_source: ["nif","nome"]` vinha
                        # **vazio** (o filtro aplica-se à raiz do documento).
                        "nome": {"top_hits": {"size": 1}},
                        "documento": {"reverse_nested": {}, "aggs": {"valor": {"sum": {"field": "precoContratual"}}}},
                    },
                }
            },
        },
        "cpvs": {
            "nested": {"path": "cpv"},
            "aggs": {
                "por_codigo": {
                    "terms": {"field": "cpv.code", "size": max(cpv_limite, 8), "missing": UNSPECIFIED_LABEL},
                    "aggs": {"documento": {"reverse_nested": {}, "aggs": {"valor": {"sum": {"field": "precoContratual"}}}}},
                }
            },
        },
        "procedimentos": {"terms": {"field": campo_procedimento, "size": 10}},
        "valor": {"sum": {"field": "precoContratual"}},
    }


def matriz_dependencia(
    escopo_def: Dict[str, Any],
    *,
    top_compradores: Optional[int] = None,
    fornecedores_por_comprador: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Relações comprador→fornecedor (e mistura de CPV de cada comprador).

    Uma consulta de agregação para escolher os maiores compradores e depois um
    `msearch` (uma consulta por comprador) — exato, sem amostra, e barato porque
    cada sub-consulta é um filtro por NIF.
    """
    config = parametros()
    limite_compradores = int(top_compradores or config["top_compradores"])
    limite_fornecedores = int(fornecedores_por_comprador or config["fornecedores_por_comprador"])
    cpv_por_comprador = int(config["cpv_por_comprador"])
    campo_procedimento, runtime = _target_agregavel("tipoprocedimento", es)
    compradores = _topo_por_papel(escopo_def, "adjudicante", limite_compradores, es=es)
    compradores = [c for c in compradores if c.get("nif")]
    pedidos: List[Dict[str, Any]] = []
    for comprador in compradores:
        filtros = json.loads(json.dumps(escopo_def["query"]))
        filtros["bool"]["filter"] = list(filtros["bool"].get("filter") or []) + [
            {"nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": comprador["nif"]}}}}
        ]
        pedidos.append(
            _com_runtime(
                {
                    "size": 0,
                    "track_total_hits": True,
                    "query": filtros,
                    "aggs": _aggs_detalhe_parte("adjudicatarios.parsed", limite_fornecedores, cpv_por_comprador, campo_procedimento),
                },
                runtime,
            )
        )
    respostas = _msearch(pedidos, es=es)
    arestas: List[Dict[str, Any]] = []
    detalhe_compradores: List[Dict[str, Any]] = []
    for comprador, resposta in zip(compradores, respostas):
        if resposta.get("error"):
            continue
        aggs = resposta.get("aggregations") or {}
        total_comprador = _num(((aggs.get("valor") or {}).get("value")))
        contratos = int(_num(((resposta.get("hits") or {}).get("total") or {}).get("value")))
        fornecedores: List[Dict[str, Any]] = []
        for bucket in ((aggs.get("contrapartes") or {}).get("por_nif") or {}).get("buckets") or []:
            valor = _num((bucket.get("documento") or {}).get("valor", {}).get("value"))
            fornecedores.append(
                {
                    "nif": None if bucket.get("key") == UNSPECIFIED_LABEL else bucket.get("key"),
                    "nome": _nome_de_hits(bucket) or str(bucket.get("key") or UNSPECIFIED_LABEL),
                    "valor": valor,
                    "contratos": int(_num(bucket.get("doc_count"))),
                    "quota": (valor / total_comprador) if total_comprador > 0 else 0.0,
                }
            )
        fornecedores.sort(key=lambda item: item["valor"], reverse=True)
        cpvs: List[Dict[str, Any]] = []
        for bucket in ((aggs.get("cpvs") or {}).get("por_codigo") or {}).get("buckets") or []:
            valor = _num((bucket.get("documento") or {}).get("valor", {}).get("value"))
            cpvs.append(
                {
                    "codigo": bucket.get("key"),
                    "classe": _classe_cpv(bucket.get("key")),
                    "divisao": _divisao_cpv(bucket.get("key")),
                    "valor": valor,
                    "contratos": int(_num(bucket.get("doc_count"))),
                    "quota": (valor / total_comprador) if total_comprador > 0 else 0.0,
                }
            )
        cpvs.sort(key=lambda item: item["valor"], reverse=True)
        procedimentos = ((aggs.get("procedimentos") or {}).get("buckets")) or []
        ajuste = sum(
            _num(p.get("doc_count"))
            for p in procedimentos
            if _fold(p.get("key")) not in AJUSTE_DIRETO_EXCLUIDOS
            and any(_fold(p.get("key")).startswith(prefixo) for prefixo in AJUSTE_DIRETO_PREFIXOS)
        )
        quota_top1 = fornecedores[0]["quota"] if fornecedores else 0.0
        hhi = sum(item["quota"] ** 2 for item in fornecedores)
        cobertura = sum(item["valor"] for item in fornecedores) / total_comprador if total_comprador > 0 else 0.0
        detalhe_compradores.append(
            {
                **comprador,
                "valor": total_comprador,
                "contratos": contratos,
                "quota_top1": quota_top1,
                "hhi_top": hhi,
                "cobertura_top": cobertura,
                "n_fornecedores_top": len(fornecedores),
                "fornecedores": fornecedores,
                "cpvs": cpvs,
                "taxa_ajuste_direto": (ajuste / contratos) if contratos else 0.0,
            }
        )
        for fornecedor in fornecedores:
            arestas.append(
                {
                    "comprador_nif": comprador["nif"],
                    "comprador_nome": comprador["nome"],
                    "fornecedor_nif": fornecedor["nif"],
                    "fornecedor_nome": fornecedor["nome"],
                    "valor": fornecedor["valor"],
                    "contratos": fornecedor["contratos"],
                    "quota_no_comprador": fornecedor["quota"],
                    "quota_no_fornecedor": 0.0,
                }
            )
    # Quota de cada aresta no total do fornecedor (exposição do fornecedor).
    por_fornecedor: Dict[str, float] = {}
    for aresta in arestas:
        chave = str(aresta["fornecedor_nif"])
        por_fornecedor[chave] = por_fornecedor.get(chave, 0.0) + aresta["valor"]
    for aresta in arestas:
        total = por_fornecedor.get(str(aresta["fornecedor_nif"]), 0.0)
        aresta["quota_no_fornecedor"] = (aresta["valor"] / total) if total > 0 else 0.0
    return {
        "compradores": detalhe_compradores,
        "arestas": arestas,
        "totais": {
            "compradores": len(detalhe_compradores),
            "fornecedores": len(por_fornecedor),
            "arestas": len(arestas),
            "valor_coberto": sum(por_fornecedor.values()),
        },
    }


def matriz_cpv(
    escopo_def: Dict[str, Any],
    *,
    top_cpvs: Optional[int] = None,
    fornecedores_por_cpv: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Concentração por classe de CPV (4 dígitos) e por fornecedor dentro do CPV."""
    config = parametros()
    limite_cpvs = int(top_cpvs or config["top_cpvs"])
    limite_fornecedores = int(fornecedores_por_cpv or config["fornecedores_por_comprador"])
    corpo = {
        "size": 0,
        "track_total_hits": True,
        "query": escopo_def["query"],
        "aggs": {
            "cpvs": {
                "nested": {"path": "cpv"},
                "aggs": {
                    "por_codigo": {
                        "terms": {"field": "cpv.code", "size": 2000, "missing": UNSPECIFIED_LABEL},
                        "aggs": {"documento": {"reverse_nested": {}, "aggs": {"valor": {"sum": {"field": "precoContratual"}}}}},
                    }
                },
            }
        },
    }
    resposta = _pesquisar(corpo, es=es)
    buckets = (((resposta.get("aggregations") or {}).get("cpvs") or {}).get("por_codigo") or {}).get("buckets") or []
    total = _num((((resposta.get("hits") or {}).get("total") or {}).get("value")))
    por_classe: Dict[str, Dict[str, Any]] = {}
    for bucket in buckets:
        classe = _classe_cpv(bucket.get("key"))
        valor = _num((bucket.get("documento") or {}).get("valor", {}).get("value"))
        entrada = por_classe.setdefault(
            classe,
            {"classe": classe, "divisao": _divisao_cpv(bucket.get("key")), "valor": 0.0, "contratos": 0, "codigos": []},
        )
        entrada["valor"] += valor
        entrada["contratos"] += int(_num(bucket.get("doc_count")))
        if len(entrada["codigos"]) < 5:
            entrada["codigos"].append({"codigo": bucket.get("key"), "valor": valor, "contratos": int(_num(bucket.get("doc_count")))})
    classes = sorted(por_classe.values(), key=lambda item: item["valor"], reverse=True)[:limite_cpvs]
    pedidos: List[Dict[str, Any]] = []
    for classe in classes:
        filtros = json.loads(json.dumps(escopo_def["query"]))
        filtros["bool"]["filter"] = list(filtros["bool"].get("filter") or []) + [
            {"nested": {"path": "cpv", "query": {"wildcard": {"cpv.code": f"{classe['classe']}*"}}}}
        ]
        pedidos.append(
            {
                "size": 0,
                "track_total_hits": True,
                "query": filtros,
                "aggs": {
                    "fornecedores": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "por_nif": {
                                "terms": {"field": "adjudicatarios.parsed.nif", "size": limite_fornecedores, "missing": UNSPECIFIED_LABEL},
                                "aggs": {
                                    "nome": {"top_hits": {"size": 1}},
                                    "documento": {"reverse_nested": {}, "aggs": {"valor": {"sum": {"field": "precoContratual"}}}},
                                },
                            }
                        },
                    },
                    "compradores": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {"n": {"cardinality": {"field": "adjudicantes.parsed.nif"}}},
                    },
                    "valor": {"sum": {"field": "precoContratual"}},
                },
            }
        )
    respostas = _msearch(pedidos, es=es)
    for classe, resposta in zip(classes, respostas):
        if resposta.get("error"):
            classe["fornecedores"] = []
            continue
        aggs = resposta.get("aggregations") or {}
        total_classe = _num((aggs.get("valor") or {}).get("value"))
        fornecedores: List[Dict[str, Any]] = []
        for bucket in ((aggs.get("fornecedores") or {}).get("por_nif") or {}).get("buckets") or []:
            valor = _num((bucket.get("documento") or {}).get("valor", {}).get("value"))
            fornecedores.append(
                {
                    "nif": None if bucket.get("key") == UNSPECIFIED_LABEL else bucket.get("key"),
                    "nome": _nome_de_hits(bucket) or str(bucket.get("key") or UNSPECIFIED_LABEL),
                    "valor": valor,
                    "contratos": int(_num(bucket.get("doc_count"))),
                    "quota": (valor / total_classe) if total_classe > 0 else 0.0,
                }
            )
        fornecedores.sort(key=lambda item: item["valor"], reverse=True)
        classe.update(
            {
                "valor_msearch": total_classe,
                "contratos_msearch": int(_num(((resposta.get("hits") or {}).get("total") or {}).get("value"))),
                "compradores": int(_num(((aggs.get("compradores") or {}).get("n") or {}).get("value"))),
                "fornecedores": fornecedores,
                "quota_top1": fornecedores[0]["quota"] if fornecedores else 0.0,
                "hhi": sum(item["quota"] ** 2 for item in fornecedores),
                "cobertura_top": (sum(item["valor"] for item in fornecedores) / total_classe) if total_classe > 0 else 0.0,
            }
        )
    return {
        "classes": classes,
        "total_documentos": int(total),
        "notas": [
            "O CPV é agregado pelo código completo e a classe (4 dígitos) é calculada em Python; "
            f"os maiores {limite_cpvs} classes por valor seguem para o cruzamento por fornecedor.",
            "`quota_top1` usa os fornecedores observados no top do CPV (limite "
            f"{limite_fornecedores}) — a cobertura está em `cobertura_top`.",
        ],
    }


# ---------------------------------------------------------------------------
# 3. Dependências, fragilidade e alternativas
# ---------------------------------------------------------------------------
def dependencias(dados: Dict[str, Any], *, limiar_critico: float = 0.30, limiar_fragil: float = 0.60) -> Dict[str, Any]:
    """Fragilidade por comprador, exposição por fornecedor e alertas verificáveis."""
    compradores = dados.get("compradores") or []
    arestas = dados.get("arestas") or []
    por_fornecedor: Dict[str, Dict[str, Any]] = {}
    for aresta in arestas:
        chave = str(aresta.get("fornecedor_nif") or UNSPECIFIED_LABEL)
        entrada = por_fornecedor.setdefault(
            chave,
            {
                "nif": aresta.get("fornecedor_nif"),
                "nome": aresta.get("fornecedor_nome") or chave,
                "valor": 0.0,
                "contratos": 0,
                "compradores": [],
                "quota_max": 0.0,
            },
        )
        entrada["valor"] += _num(aresta.get("valor"))
        entrada["contratos"] += int(_num(aresta.get("contratos")))
        entrada["compradores"].append(
            {
                "nif": aresta.get("comprador_nif"),
                "nome": aresta.get("comprador_nome"),
                "valor": _num(aresta.get("valor")),
                "quota": _num(aresta.get("quota_no_comprador")),
                "contratos": int(_num(aresta.get("contratos"))),
            }
        )
        entrada["quota_max"] = max(entrada["quota_max"], _num(aresta.get("quota_no_comprador")))
    fornecedores = sorted(por_fornecedor.values(), key=lambda item: item["valor"], reverse=True)
    for fornecedor in fornecedores:
        fornecedor["compradores"].sort(key=lambda item: item["quota"], reverse=True)
        fornecedor["n_compradores"] = len(fornecedor["compradores"])
        fornecedor["dependencia_media"] = (
            sum(item["quota"] for item in fornecedor["compradores"]) / len(fornecedor["compradores"])
            if fornecedor["compradores"]
            else 0.0
        )
        fornecedor["criticos"] = [item for item in fornecedor["compradores"] if item["quota"] >= limiar_fragil]

    fragilidade_compradores: List[Dict[str, Any]] = []
    for comprador in compradores:
        fornecedores_comprador = comprador.get("fornecedores") or []
        top = fornecedores_comprador[0] if fornecedores_comprador else None
        quota_top1 = _num(comprador.get("quota_top1"))
        alternativa = _cobertura_alternativa(comprador, top)
        fragilidade = quota_top1 * (1.0 - alternativa) * (1.0 + _num(comprador.get("taxa_ajuste_direto")))
        fragilidade_compradores.append(
            {
                "nif": comprador.get("nif"),
                "nome": comprador.get("nome"),
                "valor": _num(comprador.get("valor")),
                "contratos": int(_num(comprador.get("contratos"))),
                "fornecedores": len(fornecedores_comprador),
                "quota_top1": quota_top1,
                "hhi_top": _num(comprador.get("hhi_top")),
                "cobertura_top": _num(comprador.get("cobertura_top")),
                "top_fornecedor": top,
                "alternativa_top1": alternativa,
                "fragilidade": fragilidade,
                "critico": quota_top1 >= limiar_fragil,
                "acima_limiar_critico": quota_top1 >= limiar_critico,
                "taxa_ajuste_direto": _num(comprador.get("taxa_ajuste_direto")),
            }
        )
    fragilidade_compradores.sort(key=lambda item: item["fragilidade"], reverse=True)
    alertas: List[Dict[str, Any]] = []
    for comprador in fragilidade_compradores:
        if comprador["critico"]:
            alertas.append(
                {
                    "tipo": "dependencia_extrema",
                    "severidade": "alta" if comprador["quota_top1"] >= 0.8 else "média",
                    "entidade": comprador["nome"],
                    "nif": comprador["nif"],
                    "medida": f"{comprador['quota_top1'] * 100:.0f} % do valor do escopo vem de um só fornecedor",
                    "detalhe": (
                        f"alternativa fora desse fornecedor no mesmo CPV: "
                        f"{comprador['alternativa_top1'] * 100:.0f} % do mercado"
                    ),
                    "evidencia": {
                        "fornecedor": (comprador.get("top_fornecedor") or {}).get("nome"),
                        "valor": comprador["valor"],
                        "contratos": comprador["contratos"],
                    },
                }
            )
    for fornecedor in fornecedores[:20]:
        if len(fornecedor["criticos"]) >= 2:
            alertas.append(
                {
                    "tipo": "fornecedor_sistemicamente_critico",
                    "severidade": "alta" if len(fornecedor["criticos"]) >= 4 else "média",
                    "entidade": fornecedor["nome"],
                    "nif": fornecedor["nif"],
                    "medida": (
                        f"é fornecedor >= {limiar_fragil * 100:.0f} % em {len(fornecedor['criticos'])} compradores "
                        f"({fornecedor['valor']:,.0f} € no escopo)"
                    ).replace(",", " "),
                    "detalhe": "uma indisponibilidade propaga-se por todos eles em simultâneo",
                    "evidencia": {
                        "compradores": [
                            {"nome": c["nome"], "quota": c["quota"], "valor": c["valor"]} for c in fornecedor["criticos"][:6]
                        ]
                    },
                }
            )
    return {
        "compradores": fragilidade_compradores,
        "fornecedores": fornecedores,
        "alertas": alertas,
        "limiares": {"critico": limiar_critico, "fragil": limiar_fragil},
    }


def _cobertura_alternativa(comprador: Dict[str, Any], fornecedor: Optional[Dict[str, Any]]) -> float:
    """Quota do comprador que **não** vai para esse fornecedor (limite inferior).

    O cruzamento fornecedor×CPV existe na análise por CPV (ver
    `_dificuldade_substituicao`), que é mais fina. Aqui, sem esse mapa, o melhor
    limite observável é `1 − quota` do próprio fornecedor no comprador: não se
    inventa um valor intermédio.
    """
    if not fornecedor:
        return 1.0
    return _limitar(1.0 - _num(fornecedor.get("quota")), 0.0, 1.0)


def alternativas_por_cpv(classe: Dict[str, Any], *, excluir: Optional[str] = None, topo: int = 3) -> List[Dict[str, Any]]:
    """Fornecedores alternativos num CPV (por quota observada), opcionalmente sem um."""
    alternativas = [f for f in (classe.get("fornecedores") or []) if str(f.get("nif")) != str(excluir)]
    return alternativas[:topo]


# ---------------------------------------------------------------------------
# 4. Dinâmica: mapa discreto, Lorenz, divergência e Lyapunov
# ---------------------------------------------------------------------------
def estado_da_serie(periodos: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Coordenadas do estado (atividade, dependência, cauda) normalizadas (robusto).

    - `atividade`  = log1p(valor / valor mediano da série)
    - `dependencia` = max(quota_top1, hhi_top) — concentração do período
    - `cauda`      = (p99 − p50) / p50 (dispersão relativa do valor)
    Cada coordenada é depois centrada e escalada por mediana/MAD, para que a
    distância euclidiana entre dois cenários tenha significado comparável.
    """
    if not periodos:
        return {"periodos": [], "coordenadas": [], "escala": {"mediana": [], "mad": []}, "cru": []}
    valores = np.array([_num(p.get("valor")) for p in periodos], dtype=float)
    quotas = np.array([max(_num(p.get("quota_top1")), _num(p.get("hhi_top"))) for p in periodos], dtype=float)
    caudas = np.array([_num(p.get("cauda")) for p in periodos], dtype=float)
    mediana_valor = float(np.median(valores)) if valores.size else 0.0
    atividade = np.log1p(valores / mediana_valor) if mediana_valor > 0 else np.zeros_like(valores)
    cru = np.column_stack([atividade, quotas, caudas]) if periodos else np.zeros((0, 3))
    mediana = np.median(cru, axis=0) if cru.size else np.zeros(3)
    desvio = np.median(np.abs(cru - mediana), axis=0) if cru.size else np.ones(3)
    escala = np.where(desvio > 1e-9, desvio * 1.4826, 1.0)
    normalizado = (cru - mediana) / escala if cru.size else cru
    return {
        "periodos": [p.get("periodo") for p in periodos],
        "cru": cru.tolist(),
        "coordenadas": normalizado.tolist(),
        "escala": {"mediana": mediana.tolist(), "mad": desvio.tolist()},
        "rotulos": ["atividade", "dependencia", "cauda"],
    }


def rho_critico(sigma: float, beta: float) -> float:
    """Fronteira de instabilidade do sistema de Lorenz clássico.

    Para ``dx/dt = σ(y−x)``, ``dy/dt = x(ρ−z)−y``, ``dz/dt = xy−βz``, a origem
    perde estabilidade em ``ρ(σ+β+3)/(σ−β−1) = ρ`` (critério de Routh-Hurwitz),
    isto é ``ρ_crit = σ(σ+β+3)/(σ−β−1)`` — as constantes clássicas (σ=10,
    β=8/3) dão 24,74.
    """
    denominador = sigma - beta - 1.0
    if denominador <= 1e-9:
        return float("inf")
    return sigma * (sigma + beta + 3.0) / denominador


def campo_lorenz(estado: Sequence[float], sigma: float, rho: float, beta: float) -> List[float]:
    x, y, z = (float(estado[0]), float(estado[1]), float(estado[2]))
    return [sigma * (y - x), x * (rho - z) - y, x * y - beta * z]


def passo_rk4(estado: Sequence[float], sigma: float, rho: float, beta: float, dt: float) -> List[float]:
    """Um passo de Runge-Kutta de 4.ª ordem (o integrador clássico do sistema)."""
    k1 = campo_lorenz(estado, sigma, rho, beta)
    e2 = [estado[i] + dt * k1[i] / 2.0 for i in range(3)]
    k2 = campo_lorenz(e2, sigma, rho, beta)
    e3 = [estado[i] + dt * k2[i] / 2.0 for i in range(3)]
    k3 = campo_lorenz(e3, sigma, rho, beta)
    e4 = [estado[i] + dt * k3[i] for i in range(3)]
    k4 = campo_lorenz(e4, sigma, rho, beta)
    return [
        estado[i] + dt * (k1[i] + 2.0 * k2[i] + 2.0 * k3[i] + k4[i]) / 6.0
        for i in range(3)
    ]


def integrar(
    estado_inicial: Sequence[float],
    sigma: float,
    rho: float,
    beta: float,
    *,
    passos: int = 2000,
    dt: float = 0.01,
    guardar_cada: int = 10,
) -> List[List[float]]:
    """Trajetória do sistema de Lorenz (subamostrada para não devolver 2000 pontos)."""
    estado = [float(v) for v in estado_inicial]
    trajetoria: List[List[float]] = [list(estado)]
    for indice in range(1, max(int(passos), 1) + 1):
        estado = passo_rk4(estado, sigma, rho, beta, dt)
        if guardar_cada > 0 and indice % guardar_cada == 0:
            trajetoria.append(list(estado))
    return trajetoria


def divergencia(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((float(a[i]) - float(b[i])) ** 2 for i in range(min(len(a), len(b)))))


def lyapunov_maximo(
    estado_inicial: Sequence[float],
    sigma: float,
    rho: float,
    beta: float,
    *,
    perturbacao: float = 1e-4,
    passos: int = 2000,
    dt: float = 0.01,
    renormalizar_cada: int = 10,
) -> Dict[str, Any]:
    """Expoente de Lyapunov máximo por Benettin (perturba, integra, renormaliza).

    ``λ > 0`` ⇒ trajetórias vizinhas divergem exponencialmente (regime sensível);
    ``λ < 0`` ⇒ o sistema contrai as perturbações (regime dissipador).
    """
    base = [float(v) for v in estado_inicial]
    desvio = [perturbacao, 0.0, 0.0]
    vizinho = [base[i] + desvio[i] for i in range(3)]
    registos: List[Dict[str, Any]] = []
    acumulado = 0.0
    intervalos = 0
    for passo in range(1, max(int(passos), 1) + 1):
        base = passo_rk4(base, sigma, rho, beta, dt)
        vizinho = passo_rk4(vizinho, sigma, rho, beta, dt)
        if passo % max(int(renormalizar_cada), 1) == 0:
            distancia = max(divergencia(base, vizinho), 1e-300)
            acumulado += math.log(distancia / perturbacao)
            intervalos += 1
            # Renormaliza na mesma direção, com a norma de volta a `perturbacao`.
            fator = perturbacao / distancia
            vizinho = [base[i] + (vizinho[i] - base[i]) * fator for i in range(3)]
            if intervalos <= 60:
                registos.append({"passo": passo, "distancia": distancia, "lyapunov_acumulado": acumulado / intervalos})
    tempo_total = intervalos * renormalizar_cada * dt
    lam = (acumulado / tempo_total) if tempo_total > 0 else 0.0
    return {
        "lambda": lam,
        "tempo_total": tempo_total,
        "intervalos": intervalos,
        "perturbacao": perturbacao,
        "serie": registos,
        "regime": "sensivel" if lam > 0 else "dissipador",
        "nota": "λ por unidade de tempo adimensional do sistema; compara-se com 0, não com um valor absoluto.",
    }


def ajustar_mapa_linear(coordenadas: Sequence[Sequence[float]]) -> Dict[str, Any]:
    """Ajusta ``s_{t+1} = A·s_t + b`` à série observada (mínimos quadrados).

    É o modelo de transição que o sistema aparenta ter nos dados — não uma lei
    física: serve para medir a **sensibilidade observada** (divergência de duas
    trajetórias vizinhas) com o menor número de hipóteses possível.
    """
    estados = np.asarray(coordenadas, dtype=float)
    if estados.ndim != 2 or estados.shape[0] < 3:
        return {"disponivel": False, "motivo": "série demasiado curta (mínimo 3 períodos)", "pares": 0}
    x = estados[:-1]
    y = estados[1:]
    desenho = np.column_stack([x, np.ones(len(x))])
    try:
        solucao, residuos, _, _ = np.linalg.lstsq(desenho, y, rcond=None)
    except np.linalg.LinAlgError as erro:
        return {"disponivel": False, "motivo": f"ajuste impossível: {erro}", "pares": len(y)}
    previsao = desenho @ solucao
    total = float(np.sum((y - y.mean(axis=0)) ** 2))
    residuo = float(np.sum((y - previsao) ** 2))
    r2 = 1.0 - (residuo / total) if total > 1e-12 else 0.0
    # Raio espectral: > 1 ⇒ o mapa amplifica perturbações na média.
    autovalores = np.linalg.eigvals(solucao[: estados.shape[1], :])
    raio = float(np.max(np.abs(autovalores))) if autovalores.size else 0.0
    return {
        "disponivel": True,
        "A": solucao[: estados.shape[1], :].tolist(),
        "b": solucao[estados.shape[1], :].tolist(),
        "r2": r2,
        "raio_espectral": raio,
        "pares": int(len(y)),
        "nota": "ajustado a poucos períodos anuais (não é um modelo validado fora da amostra).",
    }


def aplicar_mapa(estado: Sequence[float], A: Sequence[Sequence[float]], b: Sequence[float]) -> List[float]:
    matriz = np.asarray(A, dtype=float)
    vetor = np.asarray(estado, dtype=float)
    return (matriz @ vetor + np.asarray(b, dtype=float)).tolist()


def divergencia_mapa(
    estado_inicial: Sequence[float],
    A: Sequence[Sequence[float]],
    b: Sequence[float],
    *,
    perturbacao: float = 1e-3,
    passos: int = 6,
    direcoes: int = 12,
    semente: int = 42,
) -> Dict[str, Any]:
    """Divergência média ``D_t`` entre pares de trajetórias com condições iniciais vizinhas.

    Devolve também o expoente de Lyapunov empírico (crescimento médio de ``log D_t``),
    que é a medida de sensibilidade **dos dados observados**, não das equações.
    """
    aleatorio = random.Random(semente)
    base = [float(v) for v in estado_inicial]
    tamanho = len(base)
    passos_total = max(int(passos), 1)
    series: List[List[float]] = []
    lambdas: List[float] = []
    for _ in range(max(int(direcoes), 1)):
        sentido = np.asarray([aleatorio.gauss(0, 1) for _ in range(tamanho)], dtype=float)
        norma = float(np.linalg.norm(sentido)) or 1.0
        sentido = sentido / norma
        a = list(base)
        c = [base[i] + perturbacao * float(sentido[i]) for i in range(tamanho)]
        distancias: List[float] = [perturbacao]
        # Logaritmo do crescimento **por passo** (fatorial local de expansão): é
        # esta a definição de Benettin. Somar os logaritmos das distâncias
        # absolutas inflacionava o expoente por um fator ~(passos+1)/2.
        acumulado = 0.0
        referencia = perturbacao
        for _passo in range(passos_total):
            a_novo = aplicar_mapa(a, A, b)
            c_novo = aplicar_mapa(c, A, b)
            separacao = max(math.sqrt(sum((a_novo[i] - c_novo[i]) ** 2 for i in range(tamanho))), 1e-300)
            acumulado += math.log(separacao / referencia)
            a, c = a_novo, c_novo
            # Evita saturação numérica: renormaliza a perturbação a cada passo.
            if separacao > 1.0:
                fator = perturbacao / separacao
                c = [a[i] + (c[i] - a[i]) * fator for i in range(tamanho)]
                separacao = perturbacao
            referencia = separacao
            distancias.append(separacao)
        series.append(distancias)
        lambdas.append(acumulado / passos_total)
    media = [
        sum(serie[indice] for serie in series) / len(series)
        for indice in range(min(len(serie) for serie in series))
    ]
    lam = sum(lambdas) / len(lambdas)
    return {
        "disponivel": True,
        "perturbacao_inicial": perturbacao,
        "passos": passos_total,
        "direcoes": len(series),
        "D": media,
        "D_normalizada": [d / max(media[0], 1e-300) for d in media],
        "lambda_empirico": lam,
        "regime": "sensivel" if lam > 0 else "dissipador",
        "nota": "λ estimado no mapa discreto ajustado à série; com poucos períodos é uma indicação, não uma medida precisa.",
    }


def estimar_parametros(periodos: Sequence[Dict[str, Any]], dinheiro: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Parâmetros análogos de Lorenz medidos na estrutura observada.

    - ``sigma`` (σ, oferta/procura) = fornecedores por comprador, relativo a uma
      referência de 3 (calibração de partida), limitado a [6, 20] para o sistema
      ficar no ramo em que ρ_crit existe.
    - ``beta`` (β, dissipação) = memória da série: `8/3 · (2 − ρ₁)`, onde ρ₁ é a
      autocorrelação de ordem 1 do valor (série com memória ⇒ β menor).
    - ``margem`` = dependência do último período sobre a mediana histórica da
      dependência (a «condição inicial» do sistema);
      ``rho = rho_crit(sigma, beta) · margem``.
    """
    if not periodos:
        return {"disponivel": False, "motivo": "sem períodos observados"}
    ultimo = periodos[-1]
    compradores = max(int(_num(ultimo.get("compradores"))), 1)
    fornecedores = int(_num(ultimo.get("fornecedores")))
    razao = fornecedores / compradores if compradores else 0.0
    sigma = _limitar(10.0 * (razao / float(parametros()["razao_referencia"])), 6.0, 20.0)
    valores = np.array([_num(p.get("valor")) for p in periodos], dtype=float)
    if dinheiro is not None and dinheiro.size:
        valores = np.asarray(dinheiro, dtype=float)
    valores = valores[np.isfinite(valores)]
    autocorrelacao = 0.0
    if valores.size >= 3 and float(np.std(valores)) > 1e-9:
        a = valores[:-1] - valores[:-1].mean()
        b = valores[1:] - valores[1:].mean()
        denominador = math.sqrt(float(np.sum(a * a)) * float(np.sum(b * b)))
        autocorrelacao = float(np.sum(a * b) / denominador) if denominador > 0 else 0.0
    beta = _limitar((8.0 / 3.0) * (2.0 - autocorrelacao), 2.2, 4.0)
    criticas = [max(_num(p.get("quota_top1")), _num(p.get("hhi_top"))) for p in periodos]
    mediana_dependencia = float(np.median(criticas)) if criticas else 0.0
    dependencia_atual = criticas[-1] if criticas else 0.0
    margem = _limitar(dependencia_atual / mediana_dependencia, 0.4, 2.5) if mediana_dependencia > 1e-9 else 1.0
    rho_crit = rho_critico(sigma, beta)
    return {
        "disponivel": True,
        "sigma": sigma,
        "beta": beta,
        "rho": rho_crit * margem if math.isfinite(rho_crit) else margem * 100.0,
        "rho_critico": rho_crit,
        "margem": margem,
        "razao_fornecedores_compradores": razao,
        "autocorrelacao_valor": autocorrelacao,
        "dependencia_atual": dependencia_atual,
        "dependencia_mediana": mediana_dependencia,
        "regime": "amplificador" if margem > 1.0 else "dissipador",
        "nota": (
            "σ, β e ρ são análogos medidos na estrutura; ρ_crit é a fronteira de instabilidade do "
            "sistema de Lorenz clássico. «amplificador» significa margem > 1 sobre essa fronteira — "
            "é uma leitura de regime, não uma previsão."
        ),
    }


# ---------------------------------------------------------------------------
# 5. Propagação de perturbações (o «efeito borboleta» com evidência)
# ---------------------------------------------------------------------------
def premio_atraso(dias: float) -> float:
    """Prémio de urgência (hipótese) interpolado nos pontos configurados."""
    pontos = sorted((float(p[0]), float(p[1])) for p in parametros()["premio_atraso"])
    if not pontos:
        return 0.0
    if dias <= pontos[0][0]:
        return pontos[0][1]
    for (d0, v0), (d1, v1) in zip(pontos, pontos[1:]):
        if dias <= d1:
            if d1 - d0 <= 0:
                return v1
            return v0 + (v1 - v0) * (dias - d0) / (d1 - d0)
    return pontos[-1][1]


def propagar(
    dados: Dict[str, Any],
    *,
    fornecedor_nif: Optional[str] = None,
    fornecedor_nome: Optional[str] = None,
    atraso_dias: float = 30.0,
    perda_capacidade: float = 0.25,
    cpvs: Optional[Dict[str, Any]] = None,
    limiar_critico: float = 0.30,
    limiar_fragil: float = 0.60,
) -> Dict[str, Any]:
    """Cascata de uma perturbação num fornecedor, com 1.ª e 2.ª ordem.

    Hipóteses (todas devolvidas em `hipoteses`):
    - a exposição de um comprador é ``valor_do_comprador_no_escopo × quota_do_fornecedor``;
    - a dificuldade de substituição é ``1 −`` quota do fornecedor no CPV (mercado que sobra);
    - o sobrecusto é ``exposição × prémio(atraso) × (0,5 + dificuldade)``;
    - em 2.ª ordem a procura realocada para as alternativas **aumenta a concentração**
      delas, podendo criar novas entidades frágeis.
    """
    dep = dependencias(dados, limiar_critico=limiar_critico, limiar_fragil=limiar_fragil)
    alvo = None
    if fornecedor_nif:
        alvo = next((f for f in dep["fornecedores"] if str(f.get("nif")) == str(fornecedor_nif)), None)
    if alvo is None and fornecedor_nome:
        alvo = next(
            (f for f in dep["fornecedores"] if _fold(f.get("nome") or "").find(_fold(fornecedor_nome)) >= 0),
            None,
        )
    if alvo is None and dep["fornecedores"]:
        alvo = dep["fornecedores"][0]
    if alvo is None:
        return {"disponivel": False, "motivo": "sem fornecedores no escopo escolhido"}

    premio = premio_atraso(atraso_dias)
    perda = _limitar(perda_capacidade, 0.0, 1.0)
    classes = {classe["classe"]: classe for classe in ((cpvs or {}).get("classes") or [])}
    comprador_por_nif = {str(c.get("nif")): c for c in (dados.get("compradores") or [])}

    diretos: List[Dict[str, Any]] = []
    for relacao in alvo["compradores"]:
        comprador = comprador_por_nif.get(str(relacao.get("nif"))) or {}
        quota = _num(relacao.get("quota"))
        exposto = _num(relacao.get("valor")) * (1.0 + perda * quota)
        dificuldade = _dificuldade_substituicao(comprador, classes, alvo.get("nif"))
        sobrecusto = exposto * premio * (0.5 + dificuldade)
        criticidade = quota * (0.5 + dificuldade)
        diretos.append(
            {
                "comprador_nif": relacao.get("nif"),
                "comprador_nome": relacao.get("nome"),
                "quota": quota,
                "valor": _num(relacao.get("valor")),
                "contratos": int(_num(relacao.get("contratos"))),
                "exposto": exposto,
                "dificuldade_substituicao": dificuldade,
                "sobrecusto_estimado": sobrecusto,
                "criticidade": criticidade,
                "critico": quota >= limiar_fragil,
                "alternativas": _alternativas_do_comprador(comprador, classes, alvo.get("nif")),
            }
        )
    diretos.sort(key=lambda item: item["criticidade"], reverse=True)

    # 2.ª ordem: realocação do exposto para as alternativas → nova concentração.
    realocacao: Dict[str, Dict[str, Any]] = {}
    for linha in diretos:
        if linha["quota"] < limiar_critico:
            continue
        disponiveis = linha["alternativas"] or []
        if not disponiveis:
            continue
        pesos = sum(max(a.get("quota", 0.0), 1e-6) for a in disponiveis)
        for alternativa in disponiveis:
            chave = str(alternativa.get("nif") or alternativa.get("nome"))
            entrada = realocacao.setdefault(
                chave,
                {
                    "nif": alternativa.get("nif"),
                    "nome": alternativa.get("nome"),
                    "valor_realocado": 0.0,
                    "compradores": [],
                    "quota_atual": alternativa.get("quota", 0.0),
                },
            )
            acrescimo = linha["exposto"] * (max(alternativa.get("quota", 0.0), 1e-6) / pesos)
            entrada["valor_realocado"] += acrescimo
            entrada["compradores"].append({"nome": linha["comprador_nome"], "acrescimo": acrescimo, "cpv": alternativa.get("cpv")})
    segunda_ordem: List[Dict[str, Any]] = []
    for entrada in sorted(realocacao.values(), key=lambda item: item["valor_realocado"], reverse=True):
        base = entrada["valor_realocado"] / max(1.0 - entrada["quota_atual"], 1e-6)
        nova_quota = _limitar(entrada["quota_atual"] + (entrada["valor_realocado"] / base if base else 0.0), 0.0, 1.0)
        segunda_ordem.append(
            {
                **entrada,
                "nova_quota_estimada": nova_quota,
                "nova_dependencia": nova_quota >= limiar_fragil,
                "n_compradores": len(entrada["compradores"]),
            }
        )
    novos_fragies = [item for item in segunda_ordem if item["nova_dependencia"]]

    impacto_total = sum(linha["sobrecusto_estimado"] for linha in diretos)
    mitigacoes: List[Dict[str, Any]] = []
    for linha in diretos[:6]:
        if not linha["alternativas"]:
            mitigacoes.append(
                {
                    "entidade": linha["comprador_nome"],
                    "acao": "não há alternativa observada no mesmo CPV — negociar acordo-quadro ou stock de segurança antes da rutura",
                    "quota_atual": linha["quota"],
                    "quota_alvo": linha["quota"],
                }
            )
            continue
        reparticao = min(0.5, linha["quota"] / 2.0)
        mitigacoes.append(
            {
                "entidade": linha["comprador_nome"],
                "acao": (
                    "repartir a quota por "
                    f"{1 + len(linha['alternativas'])} fornecedores reduz a dependência de "
                    f"{linha['quota'] * 100:.0f} % para {reparticao * 100:.0f} %"
                ),
                "quota_atual": linha["quota"],
                "quota_alvo": reparticao,
                "alternativas": [
                    {"nome": a.get("nome"), "nif": a.get("nif"), "cpv": a.get("cpv"), "quota_no_cpv": a.get("quota")}
                    for a in linha["alternativas"]
                ],
            }
        )
    return {
        "disponivel": True,
        "origem": {"nif": alvo.get("nif"), "nome": alvo.get("nome"), "valor": alvo.get("valor"), "contratos": alvo.get("contratos")},
        "atraso_dias": atraso_dias,
        "perda_capacidade": perda,
        "premio_urgencia": premio,
        "diretos": diretos,
        "segunda_ordem": segunda_ordem,
        "novos_fragies": novos_fragies,
        "impacto_total_estimado": impacto_total,
        "impacto_por_comprador": [
            {"nome": linha["comprador_nome"], "nif": linha["comprador_nif"], "sobrecusto": linha["sobrecusto_estimado"]}
            for linha in diretos
        ],
        "mitigacoes": mitigacoes,
        "hipoteses": [
            "Exposição = valor do comprador no escopo × quota do fornecedor (histórico observado).",
            f"Prémio de urgência para {atraso_dias:.0f} dias: {premio * 100:.1f} % (interpolação de {parametros()['premio_atraso']}).",
            "Dificuldade de substituição = 1 − quota do fornecedor no CPV (mercado que sobra), agravada se não há alternativa observada.",
            "Sem stocks, prazos de entrega e criticidade técnica não há efeito operacional: o custo é um cenário.",
        ],
    }


def _dificuldade_substituicao(comprador: Dict[str, Any], classes: Dict[str, Dict[str, Any]], fornecedor_nif: Optional[str]) -> float:
    """1 − quota do fornecedor no CPV, ponderada pela mistura de CPV do comprador."""
    cpvs = comprador.get("cpvs") or []
    if not cpvs:
        return 0.5  # sem mapa de CPV: incerteza neutra, não 0 nem 1
    total = sum(_num(cpv.get("quota")) for cpv in cpvs) or 1.0
    acumulado = 0.0
    for cpv in cpvs:
        classe = classes.get(cpv.get("classe"))
        peso = _num(cpv.get("quota")) / total
        if not classe:
            acumulado += peso * 0.5
            continue
        quota_fornecedor = next(
            (_num(f.get("quota")) for f in (classe.get("fornecedores") or []) if str(f.get("nif")) == str(fornecedor_nif)),
            0.0,
        )
        acumulado += peso * (1.0 - quota_fornecedor)
    return _limitar(acumulado, 0.0, 1.0)


def _alternativas_do_comprador(
    comprador: Dict[str, Any],
    classes: Dict[str, Dict[str, Any]],
    fornecedor_nif: Optional[str],
    *,
    topo: int = 3,
) -> List[Dict[str, Any]]:
    """Alternativas reais (fornecedores com contratos no mesmo CPV do comprador)."""
    alternativas: List[Dict[str, Any]] = []
    vistos: set = set()
    for cpv in comprador.get("cpvs") or []:
        classe = classes.get(cpv.get("classe"))
        if not classe:
            continue
        for fornecedor in classe.get("fornecedores") or []:
            chave = str(fornecedor.get("nif"))
            if chave in vistos or chave == str(fornecedor_nif):
                continue
            vistos.add(chave)
            alternativas.append(
                {
                    "nif": fornecedor.get("nif"),
                    "nome": fornecedor.get("nome"),
                    "quota": _num(fornecedor.get("quota")),
                    "cpv": classe.get("classe"),
                    "valor_no_cpv": _num(fornecedor.get("valor")),
                }
            )
    alternativas.sort(key=lambda item: item["quota"], reverse=True)
    return alternativas[:topo]


def cenarios_atraso(
    dados: Dict[str, Any],
    *,
    fornecedor_nif: Optional[str] = None,
    atrasos: Sequence[int] = ATRASOS_DIAS,
    cpvs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compara 7/30/60 dias (e a perda de capacidade) para o mesmo fornecedor."""
    cenarios = []
    for atraso in atrasos:
        resultado = propagar(dados, fornecedor_nif=fornecedor_nif, atraso_dias=float(atraso), cpvs=cpvs)
        if not resultado.get("disponivel"):
            return resultado
        cenarios.append(
            {
                "atraso_dias": atraso,
                "premio": resultado["premio_urgencia"],
                "impacto_total": resultado["impacto_total_estimado"],
                "compradores_afetados": len(resultado["diretos"]),
                "criticos": len([linha for linha in resultado["diretos"] if linha["critico"]]),
                "novos_fragies": len(resultado["novos_fragies"]),
                "origem": resultado["origem"],
            }
        )
    base = cenarios[0]["impacto_total"] if cenarios else 0.0
    for cenario in cenarios:
        cenario["fator_vs_7d"] = (cenario["impacto_total"] / base) if base > 0 else None
    return {"fornecedor": cenarios[0]["origem"] if cenarios else None, "cenarios": cenarios}


def sensibilidade(
    dados: Dict[str, Any],
    *,
    fornecedor_nif: Optional[str] = None,
    cpvs: Optional[Dict[str, Any]] = None,
    perdas: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Elasticidade do impacto à magnitude da perturbação («quão pequeno pode ser o choque»).

    Avalia a cascata para perdas de capacidade crescentes e ajusta a inclinação
    (impacto por ponto de perturbação). Serve para ranquear **quem amplifica**.
    """
    niveis = list(perdas or parametros()["perda_capacidade"])
    pontos: List[Dict[str, Any]] = []
    for nivel in niveis:
        resultado = propagar(dados, fornecedor_nif=fornecedor_nif, atraso_dias=30.0, perda_capacidade=float(nivel), cpvs=cpvs)
        if not resultado.get("disponivel"):
            return resultado
        pontos.append(
            {
                "perda": float(nivel),
                "impacto": resultado["impacto_total_estimado"],
                "afetados": len(resultado["diretos"]),
                "novos_fragies": len(resultado["novos_fragies"]),
                "origem": resultado["origem"],
            }
        )
    xs = np.array([p["perda"] for p in pontos], dtype=float)
    ys = np.array([p["impacto"] for p in pontos], dtype=float)
    inclinacao = 0.0
    if xs.size >= 2 and float(np.ptp(xs)) > 1e-9:
        inclinacao = float(np.polyfit(xs, ys, 1)[0])
    return {
        "pontos": pontos,
        "inclinacao": inclinacao,
        "unidade": "€ de sobrecusto por 1,0 de perda de capacidade (0–1)",
        "nota": "Sem efeitos operacionais (stocks/prazos) a elasticidade é financeira: mede exposição, não rutura física.",
    }


def ranking_amplificadores(
    dados: Dict[str, Any],
    *,
    cpvs: Optional[Dict[str, Any]] = None,
    topo: int = 12,
) -> List[Dict[str, Any]]:
    """Ranque dos fornecedores que mais amplificam (alcance × exposição × dependência).

    ``amplificacao`` = fração de compradores alcançados × fração do valor exposto ×
    dificuldade média de substituição. ``contribuintes`` mostra as relações que
    mais contribuem — é a resposta a «quais condições iniciais amplificam».
    """
    dep = dependencias(dados)
    total_compradores = max(len(dados.get("compradores") or []), 1)
    valor_escopo = sum(_num(f.get("valor")) for f in dep["fornecedores"]) or 1.0
    classes = {classe["classe"]: classe for classe in ((cpvs or {}).get("classes") or [])}
    comprador_por_nif = {str(c.get("nif")): c for c in (dados.get("compradores") or [])}
    linhas: List[Dict[str, Any]] = []
    for fornecedor in dep["fornecedores"][: max(int(topo) * 3, 20)]:
        quantidade = 0
        exposto = 0.0
        dificuldades: List[float] = []
        contribuintes: List[Dict[str, Any]] = []
        for relacao in fornecedor["compradores"]:
            comprador = comprador_por_nif.get(str(relacao.get("nif"))) or {}
            dificuldade = _dificuldade_substituicao(comprador, classes, fornecedor.get("nif"))
            contribuicao = _num(relacao.get("quota")) * (0.5 + dificuldade) * (_num(relacao.get("valor")) / valor_escopo)
            quantidade += 1
            exposto += _num(relacao.get("valor"))
            dificuldades.append(dificuldade)
            contribuintes.append(
                {
                    "comprador": relacao.get("nome"),
                    "nif": relacao.get("nif"),
                    "quota": _num(relacao.get("quota")),
                    "valor": _num(relacao.get("valor")),
                    "dificuldade_substituicao": dificuldade,
                    "contribuicao": contribuicao,
                }
            )
        contribuintes.sort(key=lambda item: item["contribuicao"], reverse=True)
        alcance = quantidade / total_compradores
        exposicao = exposto / valor_escopo
        dificuldade_media = float(np.mean(dificuldades)) if dificuldades else 0.5
        linhas.append(
            {
                "nif": fornecedor.get("nif"),
                "nome": fornecedor.get("nome"),
                "valor": fornecedor.get("valor"),
                "contratos": fornecedor.get("contratos"),
                "compradores": quantidade,
                "alcance": alcance,
                "exposicao": exposicao,
                "quota_max": fornecedor.get("quota_max"),
                "dificuldade_media": dificuldade_media,
                "amplificacao": alcance * exposicao * (0.5 + dificuldade_media),
                "contribuintes": contribuintes[:5],
            }
        )
    linhas.sort(key=lambda item: item["amplificacao"], reverse=True)
    return linhas[:topo]


# ---------------------------------------------------------------------------
# 6. Evidências (contratos reais por trás de cada número)
# ---------------------------------------------------------------------------
def evidencias(
    escopo_def: Dict[str, Any],
    *,
    comprador_nif: Optional[str] = None,
    fornecedor_nif: Optional[str] = None,
    cpv_prefixo: Optional[str] = None,
    limite: int = 12,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Contratos que sustentam uma relação ou um CPV (para verificação)."""
    filtros = json.loads(json.dumps(escopo_def["query"]))
    lista = list(filtros["bool"].get("filter") or [])
    if comprador_nif:
        lista.append({"nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": comprador_nif}}}})
    if fornecedor_nif:
        lista.append({"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": fornecedor_nif}}}})
    if cpv_prefixo:
        lista.append({"nested": {"path": "cpv", "query": {"wildcard": {"cpv.code": f"{cpv_prefixo}*"}}}})
    filtros["bool"]["filter"] = lista
    corpo = {
        "size": int(limite),
        "track_total_hits": True,
        "query": filtros,
        "sort": [{"precoContratual": {"order": "desc"}}],
        "_source": [
            "idcontrato",
            "objectoContrato",
            "precoContratual",
            "PrecoTotalEfetivo",
            "dataCelebracaoContrato",
            "dataPublicacao",
            "Ano",
            "tipoprocedimento",
            "cpv",
            "adjudicantes",
            "adjudicatarios",
        ],
    }
    resposta = _pesquisar(corpo, es=es)
    itens = []
    for hit in ((resposta.get("hits") or {}).get("hits") or []):
        fonte = hit.get("_source") or {}
        cpv = (fonte.get("cpv") or [{}])[0] if isinstance(fonte.get("cpv"), list) else (fonte.get("cpv") or {})
        itens.append(
            {
                "idcontrato": fonte.get("idcontrato") or hit.get("_id"),
                "objeto": fonte.get("objectoContrato"),
                "valor": _num(fonte.get("precoContratual")),
                "valor_efetivo": _num(fonte.get("PrecoTotalEfetivo")),
                "data": fonte.get("dataCelebracaoContrato") or fonte.get("dataPublicacao"),
                "ano": fonte.get("Ano"),
                "procedimento": fonte.get("tipoprocedimento"),
                "cpv": cpv.get("code") if isinstance(cpv, dict) else None,
                "adjudicante": _nome_parte(fonte.get("adjudicantes")),
                "adjudicatario": _nome_parte(fonte.get("adjudicatarios")),
            }
        )
    return {
        "total": int(_num(((resposta.get("hits") or {}).get("total") or {}).get("value"))),
        "itens": itens,
        "erro": resposta.get("erro"),
    }


# ---------------------------------------------------------------------------
# 7. Orquestradores servidos pela API
# ---------------------------------------------------------------------------
def _grafo_studio(dados: Dict[str, Any], dep: Dict[str, Any], *, limite_fornecedores: int = 40) -> Dict[str, Any]:
    """Grafo comprador↔fornecedor no formato do `GraphCanvas` (nós/arestas + meta)."""
    compradores = dados.get("compradores") or []
    fornecedores = dep.get("fornecedores") or []
    nos: Dict[str, Dict[str, Any]] = {}
    arestas: List[Dict[str, Any]] = []
    for comprador in compradores:
        chave = f"e:{comprador.get('nif') or comprador.get('nome')}"
        nos[chave] = {
            "id": chave,
            "key": str(comprador.get("nif") or comprador.get("nome")),
            "label": comprador.get("nome") or str(comprador.get("nif")),
            "dimension": "comprador",
            "type": "entidade",
            "role": "adjudicante",
            "count": int(_num(comprador.get("contratos"))),
            "total_value": _num(comprador.get("valor")),
            "value": _num(comprador.get("valor")),
        }
    for fornecedor in fornecedores[:limite_fornecedores]:
        chave = f"f:{fornecedor.get('nif') or fornecedor.get('nome')}"
        nos[chave] = {
            "id": chave,
            "key": str(fornecedor.get("nif") or fornecedor.get("nome")),
            "label": fornecedor.get("nome") or str(fornecedor.get("nif")),
            "dimension": "fornecedor",
            "type": "concorrente",
            "role": "adjudicatario",
            "count": int(_num(fornecedor.get("contratos"))),
            "total_value": _num(fornecedor.get("valor")),
            "value": _num(fornecedor.get("valor")),
            "quota_max": fornecedor.get("quota_max"),
        }
    for aresta in dados.get("arestas") or []:
        origem = f"e:{aresta.get('comprador_nif') or aresta.get('comprador_nome')}"
        destino = f"f:{aresta.get('fornecedor_nif') or aresta.get('fornecedor_nome')}"
        if origem in nos and destino in nos:
            arestas.append(
                {
                    "source": origem,
                    "target": destino,
                    "count": int(_num(aresta.get("contratos"))),
                    "value": _num(aresta.get("valor")),
                    "quota": _num(aresta.get("quota_no_comprador")),
                }
            )
    return {
        "nodes": list(nos.values()),
        "edges": arestas,
        "meta": {
            "dimension_a": "comprador",
            "dimension_b": "fornecedor",
            "metric": "valor",
            "documents_scanned": len(compradores),
            "nodes_returned": len(nos),
            "edges_returned": len(arestas),
            "notas": [
                "Compradores = maiores adjudicantes do escopo; fornecedores = top de cada um (por valor).",
                "A aresta traz a quota do fornecedor no comprador — é essa quota que propaga o choque.",
            ],
        },
    }


def _alertas_combinados(
    dep: Dict[str, Any],
    dep_cpvs: Dict[str, Any],
    amplificadores: Sequence[Dict[str, Any]],
    *,
    limiar_amplificacao: float = 0.05,
) -> List[Dict[str, Any]]:
    """Alerta único da página: dependência, CPV com um só fornecedor e amplificadores.

    Cada alerta traz `evidencia` (contratos/fornecedores) para verificação e
    `origem` para a UI agrupar. Num mercado muito disperso (ex.: medicamentos com
    500 fornecedores) **não há** dependência por comprador — o sinal está no CPV e
    na exposição do fornecedor, por isso as três famílias são necessárias.
    """
    alertas: List[Dict[str, Any]] = [{**alerta, "origem": "dependencia"} for alerta in dep.get("alertas", [])]
    for classe in dep_cpvs.get("classes") or []:
        if not classe.get("single_source"):
            continue
        quota = _num(classe.get("quota_top1"))
        dominante = classe.get("dominante") or {}
        alertas.append(
            {
                "origem": "cpv",
                "tipo": "cpv_dependente_de_um_fornecedor",
                "severidade": "alta" if quota >= 0.75 else "média",
                "entidade": f"CPV {classe.get('classe')}",
                "nif": dominante.get("nif"),
                "medida": (
                    f"{quota * 100:.0f} % do valor desta classe vem de {dominante.get('nome') or 'um fornecedor'}"
                ),
                "detalhe": (
                    f"{classe.get('contratos')} contratos · {classe.get('fornecedores')} fornecedores · "
                    f"alternativas fora do dominante cobrem {100 - quota * 100:.0f} %"
                ),
                "evidencia": {
                    "valor": classe.get("valor"),
                    "hhi": classe.get("hhi"),
                    "alternativas": [
                        {"nome": f.get("nome"), "nif": f.get("nif"), "quota": f.get("quota")}
                        for f in (classe.get("alternativas") or [])
                    ],
                },
            }
        )
    for linha in amplificadores:
        if _num(linha.get("amplificacao")) < limiar_amplificacao:
            continue
        alertas.append(
            {
                "origem": "amplificacao",
                "tipo": "fornecedor_amplificador",
                "severidade": "alta" if _num(linha.get("amplificacao")) >= 0.12 else "média",
                "entidade": linha.get("nome"),
                "nif": linha.get("nif"),
                "medida": (
                    f"amplificação {_num(linha.get('amplificacao')):.3f} — {linha.get('compradores')} compradores, "
                    f"{100 * _num(linha.get('exposicao')):.1f} % do valor do escopo"
                ),
                "detalhe": (
                    "contribuintes: "
                    + "; ".join(
                        f"{c.get('comprador')} ({100 * _num(c.get('quota')):.0f} %)"
                        for c in (linha.get("contribuintes") or [])[:3]
                    )
                ),
                "evidencia": {"contribuintes": linha.get("contribuintes")},
            }
        )
    ordem = {"alta": 0, "média": 1, "baixa": 2}
    alertas.sort(key=lambda item: ordem.get(item.get("severidade"), 3))
    return alertas


def panorama(
    escopo_def: Dict[str, Any],
    *,
    es: Optional[Elasticsearch] = None,
    incluir_grafo: bool = False,
    progresso: Optional[Any] = None,
) -> Dict[str, Any]:
    """Visão de conjunto: estado, parâmetros, regime, dependências, CPV e alertas."""
    inicio = time.time()
    tempos: Dict[str, float] = {}

    marca = time.time()
    serie_dados = serie(escopo_def, es=es)
    tempos["serie"] = time.time() - marca
    if serie_dados.get("erro"):
        return {"erro": serie_dados["erro"], "escopo": escopo_def}

    if progresso:
        progresso("matriz de dependência")
    marca = time.time()
    dados = matriz_dependencia(escopo_def, es=es)
    tempos["dependencia"] = time.time() - marca

    if progresso:
        progresso("concentração por CPV")
    marca = time.time()
    cpvs = matriz_cpv(escopo_def, es=es)
    tempos["cpv"] = time.time() - marca

    marca = time.time()
    dep = dependencias(dados)
    dep_cpvs = _dependencia_cpv(cpvs)
    estado = estado_da_serie(serie_dados["periodos"])
    parametros_est = estimar_parametros(serie_dados["periodos"])
    mapa = ajustar_mapa_linear(estado["coordenadas"]) if len(estado["coordenadas"]) >= 3 else {"disponivel": False}
    divergencia_dados = (
        divergencia_mapa(
            estado["coordenadas"][-1],
            mapa["A"],
            mapa["b"],
            perturbacao=float(parametros()["perturbacao"]) * 10,
            passos=int(parametros()["horizonte_mapa"]),
            direcoes=int(parametros()["direcoes_perturbacao"]),
            semente=int(parametros()["semente"]),
        )
        if mapa.get("disponivel")
        else {"disponivel": False, "motivo": mapa.get("motivo")}
    )
    tempos["dinamica"] = time.time() - marca

    lorenz = None
    if parametros_est.get("disponivel"):
        marca = time.time()
        ultimo = estado["cru"][-1] if estado["cru"] else [1.0, 0.2, 1.0]
        semente_lorenz = [
            _limitar(float(ultimo[0]), 0.5, 3.0),
            _limitar(float(ultimo[1]) * 10.0, 0.1, 5.0),
            _limitar(float(ultimo[2]), 0.5, 3.0),
        ]
        trajetoria = integrar(
            semente_lorenz,
            parametros_est["sigma"],
            parametros_est["rho"],
            parametros_est["beta"],
            passos=int(parametros()["passos_lorenz"]),
            dt=float(parametros()["dt"]),
            guardar_cada=max(int(parametros()["passos_lorenz"]) // 60, 1),
        )
        lyap = lyapunov_maximo(
            semente_lorenz,
            parametros_est["sigma"],
            parametros_est["rho"],
            parametros_est["beta"],
            perturbacao=float(parametros()["perturbacao"]),
            passos=int(parametros()["passos_lorenz"]),
            dt=float(parametros()["dt"]),
        )
        lorenz = {
            "parametros": parametros_est,
            "semente": semente_lorenz,
            "trajetoria": trajetoria,
            "lyapunov": lyap,
        }
        tempos["lorenz"] = time.time() - marca

    amplificadores = ranking_amplificadores(dados, cpvs=cpvs, topo=12)
    alertas = _alertas_combinados(dep, dep_cpvs, amplificadores)
    top_fornecedor = amplificadores[0] if amplificadores else None
    cenarios = (
        cenarios_atraso(dados, fornecedor_nif=top_fornecedor.get("nif"), cpvs=cpvs) if top_fornecedor else {"cenarios": []}
    )
    kpis = _kpis(serie_dados["periodos"], dep, dep_cpvs, estado, parametros_est, divergencia_dados, lorenz)
    resultado = {
        "escopo": {chave: valor for chave, valor in escopo_def.items() if chave != "query"},
        "gerado_em": _agora(),
        "kpis": kpis,
        "serie": serie_dados,
        "estado": estado,
        "dinamica": {
            "mapa": mapa,
            "divergencia": divergencia_dados,
            "lorenz": lorenz,
        },
        "dependencias": {
            "compradores": dep["compradores"][:30],
            "fornecedores": dep["fornecedores"][:30],
            "alertas": alertas[:30],
            "alertas_por_origem": {
                origem: len([alerta for alerta in alertas if alerta.get("origem") == origem])
                for origem in ("dependencia", "cpv", "amplificacao")
            },
            "limiares": dep["limiares"],
        },
        "cpvs": dep_cpvs,
        "amplificadores": amplificadores,
        "cenarios_atraso": cenarios.get("cenarios", []),
        "cobertura": {
            "documentos_escopo": serie_dados.get("total_documentos"),
            "compradores_analisados": dados["totais"]["compradores"],
            "fornecedores_analisados": dados["totais"]["fornecedores"],
            "valor_coberto": dados["totais"]["valor_coberto"],
            "cpvs_analisados": len(cpvs.get("classes") or []),
            "top_compradores": parametros()["top_compradores"],
            "top_cpvs": parametros()["top_cpvs"],
        },
        "hipoteses": _hipoteses(escopo_def),
        "tempos": {chave: round(valor, 2) for chave, valor in tempos.items()},
        "duracao_s": round(time.time() - inicio, 2),
        "notas": [
            "O cruzamento comprador→fornecedor é exato para os maiores compradores do escopo (msearch por NIF), não uma amostra aleatória.",
            "«Amplificação» mede exposição financeira e dependência estrutural — não prevê ruturas operacionais.",
        ],
    }
    if incluir_grafo:
        resultado["grafo"] = _grafo_studio(dados, dep)
    return resultado


def _kpis(
    periodos: Sequence[Dict[str, Any]],
    dep: Dict[str, Any],
    dep_cpvs: Dict[str, Any],
    estado: Dict[str, Any],
    parametros_est: Dict[str, Any],
    divergencia_dados: Dict[str, Any],
    lorenz: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    contratos = sum(int(_num(p.get("contratos"))) for p in periodos)
    valor = sum(_num(p.get("valor")) for p in periodos)
    compradores = dep.get("compradores") or []
    fragies = [c for c in compradores if c.get("critico")]
    top = dep.get("fornecedores") or []
    return {
        "periodos": len(periodos),
        "primeiro_periodo": periodos[0]["periodo"] if periodos else None,
        "ultimo_periodo": periodos[-1]["periodo"] if periodos else None,
        "contratos": contratos,
        "valor": valor,
        "valor_medio": (valor / contratos) if contratos else 0.0,
        "taxa_ajuste_direto": (
            sum(int(_num(p.get("ajuste_direto"))) for p in periodos) / contratos if contratos else 0.0
        ),
        "compradores_analisados": len(compradores),
        "compradores_fragies": len(fragies),
        "quota_top1_media": (
            sum(_num(c.get("quota_top1")) for c in compradores) / len(compradores) if compradores else 0.0
        ),
        "hhi_medio": (sum(_num(c.get("hhi_top")) for c in compradores) / len(compradores)) if compradores else 0.0,
        "fornecedor_mais_exposto": (
            {
                "nome": top[0].get("nome"),
                "nif": top[0].get("nif"),
                "valor": top[0].get("valor"),
                "quota_max": top[0].get("quota_max"),
                "compradores": top[0].get("n_compradores"),
            }
            if top
            else None
        ),
        "cpvs_single_source": dep_cpvs.get("single_source"),
        "cpvs_analisados": len(dep_cpvs.get("classes") or []),
        "dependencia_media": (
            sum(max(_num(p.get("quota_top1")), _num(p.get("hhi_top"))) for p in periodos) / len(periodos)
            if periodos
            else 0.0
        ),
        "regime_dados": divergencia_dados.get("regime") if divergencia_dados.get("disponivel") else None,
        "lambda_empirico": divergencia_dados.get("lambda_empirico") if divergencia_dados.get("disponivel") else None,
        "regime_lorenz": parametros_est.get("regime"),
        "margem_caos": parametros_est.get("margem"),
        "lambda_lorenz": (lorenz or {}).get("lyapunov", {}).get("lambda") if lorenz else None,
        "coordenadas": estado.get("coordenadas", [])[-1] if estado.get("coordenadas") else None,
    }


def _dependencia_cpv(cpvs: Dict[str, Any]) -> Dict[str, Any]:
    """Fragilidade por CPV: fornecedor dominante, alternativas e exposição."""
    classes: List[Dict[str, Any]] = []
    single_source = 0
    for classe in cpvs.get("classes") or []:
        fornecedores = classe.get("fornecedores") or []
        quota = _num(classe.get("quota_top1"))
        alternativas = fornecedores[1:4]
        cobertura_alternativa = sum(_num(f.get("quota")) for f in alternativas)
        fragilidade = quota * (1.0 - _limitar(cobertura_alternativa, 0.0, 1.0))
        registo = {
            "classe": classe.get("classe"),
            "divisao": classe.get("divisao"),
            "valor": _num(classe.get("valor")),
            "contratos": int(_num(classe.get("contratos"))),
            "fornecedores": len(fornecedores),
            "compradores": int(_num(classe.get("compradores"))),
            "quota_top1": quota,
            "hhi": _num(classe.get("hhi")),
            "cobertura_top": _num(classe.get("cobertura_top")),
            "dominante": (fornecedores[0] if fornecedores else None),
            "alternativas": alternativas,
            "fragilidade": fragilidade,
            "single_source": quota >= 0.6,
        }
        if registo["single_source"]:
            single_source += 1
        classes.append(registo)
    classes.sort(key=lambda item: item["valor"], reverse=True)
    return {
        "classes": classes,
        "single_source": single_source,
        "notas": cpvs.get("notas", []),
    }


def _hipoteses(escopo_def: Dict[str, Any]) -> List[str]:
    return [
        "Os valores usam `precoContratual` (valor contratado); `PrecoTotalEfetivo` é trazido em paralelo quando existe.",
        "A concentração é medida nos maiores fornecedores observados por comprador/CPV (limites em `cobertura`).",
        "Fragilidade = quota do maior fornecedor × (1 − cobertura das alternativas no mesmo CPV).",
        "O prémio de urgência e a dificuldade de substituição são hipóteses explícitas, configuráveis em `data/lorenz/config.json`.",
        f"Escopo: área «{escopo_def.get('area_label')}»"
        + (f", anos {escopo_def.get('ano_de')}–{escopo_def.get('ano_ate')}" if escopo_def.get("ano_de") or escopo_def.get("ano_ate") else "")
        + (f", região {escopo_def.get('regiao')}" if escopo_def.get("regiao") else "")
        + (f", NIF {escopo_def.get('nif')}" if escopo_def.get("nif") else "")
        + ".",
    ]


def propagacao(
    escopo_def: Dict[str, Any],
    *,
    fornecedor_nif: Optional[str] = None,
    fornecedor_nome: Optional[str] = None,
    atraso_dias: float = 30.0,
    es: Optional[Elasticsearch] = None,
    top_compradores: Optional[int] = None,
) -> Dict[str, Any]:
    """Cenário de propagação para um fornecedor (com evidências dos contratos)."""
    dados = matriz_dependencia(escopo_def, top_compradores=top_compradores, es=es)
    cpvs = matriz_cpv(escopo_def, es=es)
    resultado = propagar(
        dados,
        fornecedor_nif=fornecedor_nif,
        fornecedor_nome=fornecedor_nome,
        atraso_dias=atraso_dias,
        cpvs=cpvs,
    )
    if not resultado.get("disponivel"):
        return resultado
    origem = resultado["origem"]
    resultado["evidencias"] = evidencias(
        escopo_def,
        fornecedor_nif=origem.get("nif"),
        limite=12,
        es=es,
    )
    resultado["sensibilidade"] = sensibilidade(dados, fornecedor_nif=origem.get("nif"), cpvs=cpvs)
    resultado["cenarios"] = cenarios_atraso(dados, fornecedor_nif=origem.get("nif"), cpvs=cpvs).get("cenarios", [])
    return resultado


def meta(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Metamodelo: arquitetura, áreas, parâmetros, limiares e estado do índice."""
    cliente = _cliente(es)
    disponivel = cliente is not None
    total = None
    if disponivel:
        try:
            total = int(cliente.count(index=CONTRACTS_INDEX)["count"])
        except Exception:  # noqa: BLE001
            total = None
    return {
        "modulo": "lorenz",
        "titulo": "Lorenz 1963 · dinâmica da contratação pública",
        "descricao": (
            "Sensibilidade às condições iniciais, propagação de perturbações e cenários alternativos "
            "sobre o grafo comprador↔fornecedor — para qualquer área (CPV), região, entidade ou período."
        ),
        "arquitetura": [
            {"camada": "dados", "label": "Camada de dados", "detalhe": "Contratos (PT · ES · FR), entidades, saúde, eventos"},
            {"camada": "grafo", "label": "Grafo de conhecimento", "detalhe": "Quem contrata quem, quanto, quando e com que dependências"},
            {"camada": "relacoes", "label": "Motor de relações", "detalhe": "Concentração (quota_top1, HHI), centralidade por valor, propagação"},
            {"camada": "dinamica", "label": "Motor dinâmico", "detalhe": "Mapa discreto s(t+1)=A·s(t)+b, Lorenz, divergência e Lyapunov"},
            {"camada": "world", "label": "World Model", "detalhe": "Estado → eventos → simulações → cenários → evidências"},
        ],
        "areas": areas(),
        "parametros": parametros(),
        "atrasos_dias": list(ATRASOS_DIAS),
        "ambitos": [
            {"id": "area", "label": "Área (prefixos CPV)", "detalhe": "Qualquer setor: saúde, construção, TI, energia… ou «todas»"},
            {"id": "cpv", "label": "CPV personalizado", "detalhe": "Prefixo de CPV livre (ex.: 336, 45, 302)"},
            {"id": "regiao", "label": "Região (NUTs)"},
            {"id": "anos", "label": "Intervalo de anos"},
            {"id": "entidade", "label": "Entidade (NIF)"},
            {"id": "valores", "label": "Intervalo de valor"},
        ],
        "indices": {"contratos": CONTRACTS_INDEX, "execucoes": LORENZ_RUNS_INDEX},
        "documentos": total,
        "limites": {
            "top_compradores": parametros()["top_compradores"],
            "top_cpvs": parametros()["top_cpvs"],
            "nota": "O crowssamento é feito por `msearch` (uma consulta por comprador/CPV), por isso é exato dentro destes topos.",
        },
        "notas": [
            "O efeito borboleta **não** diz que qualquer acontecimento pequeno gera uma crise: a amplificação depende da estrutura.",
            "Sem stocks, prazos e criticidade técnica, o custo potencial é um cenário com hipóteses explícitas.",
            "Cada alerta traz contratos verificáveis em `evidencias`.",
        ],
    }


# ---------------------------------------------------------------------------
# 8. Execuções guardadas (índice próprio, leitura por id)
# ---------------------------------------------------------------------------
def guardar_execucao(
    escopo_def: Dict[str, Any],
    resultado: Dict[str, Any],
    *,
    autor: Optional[str] = None,
    titulo: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    cliente = _cliente(es)
    if cliente is None:
        return {"erro": "Elasticsearch indisponível"}
    ensure_indices(cliente)
    identificador = f"lz-{int(time.time() * 1000)}"
    documento = {
        "run_id": identificador,
        "created_at": _agora(),
        "titulo": titulo or f"Lorenz · {escopo_def.get('area_label')}",
        "area": escopo_def.get("area"),
        "cpv_prefixos": escopo_def.get("cpv_prefixos"),
        "ano_de": escopo_def.get("ano_de"),
        "ano_ate": escopo_def.get("ano_ate"),
        "regiao": escopo_def.get("regiao"),
        "nif": escopo_def.get("nif"),
        "autor": autor,
        "kpis": resultado.get("kpis"),
        "regime": (resultado.get("kpis") or {}).get("regime_lorenz"),
        "lambda_empirico": (resultado.get("kpis") or {}).get("lambda_empirico"),
        "resultado": resultado,
    }
    cliente.index(index=LORENZ_RUNS_INDEX, id=identificador, document=documento, refresh="wait_for")
    return {"ok": True, "run_id": identificador, "titulo": documento["titulo"]}


def listar_execucoes(*, limite: int = 20, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    cliente = _cliente(es)
    if cliente is None:
        return []
    ensure_indices(cliente)
    try:
        resposta = cliente.search(
            index=LORENZ_RUNS_INDEX,
            body={
                "size": int(limite),
                "sort": [{"created_at": {"order": "desc"}}],
                "query": {"match_all": {}},
                "_source": [
                    "run_id",
                    "created_at",
                    "titulo",
                    "area",
                    "cpv_prefixos",
                    "ano_de",
                    "ano_ate",
                    "regiao",
                    "nif",
                    "autor",
                    "kpis",
                    "regime",
                    "lambda_empirico",
                ],
            },
        )
    except Exception as erro:  # noqa: BLE001
        logger.warning("lorenz: listagem falhou (%s)", erro)
        return []
    return [hit.get("_source") or {} for hit in ((resposta.get("hits") or {}).get("hits") or [])]


def obter_execucao(run_id: str, *, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    cliente = _cliente(es)
    if cliente is None:
        return None
    try:
        resposta = cliente.get(index=LORENZ_RUNS_INDEX, id=run_id)
        return resposta.get("_source")
    except Exception:  # noqa: BLE001
        return None
