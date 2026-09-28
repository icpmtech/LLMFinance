"""Motor de **risco por empresa** (ML + IA) — módulo «Empresas & Risco».

Responde a uma pergunta concreta: *que empresas adjudicatárias merecem ser
olhadas primeiro, e porquê?* Junta, num só número de 0 a 100 (com os
componentes que o compõem), o que o IQ OS já sabe sobre cada empresa:

1. **Regras calibradas nos dados** — aditivos financeiros, ajuste direto,
   concentração num só comprador, contratos sem concorrência, transparência
   tardia, valores atípicos para o CPV (σ robusto/MAD). Limiares alinhados com
   as regras do módulo de *deteção de padrões* (`padroes_regras.REGRAS_DEFAULT`),
   para que «risco» signifique o mesmo nos dois módulos.
2. **ML não supervisionado** — `IsolationForest` ajustado à **população de
   referência** (empresas da amostra nacional de contratos) e o **percentil** da
   empresa nessa população: não diz «é má», diz «é fora do padrão das suas
   pares».
3. **ML supervisionado (sinal de aditivo)** — o classificador *Gradient
   Boosting* do módulo de padrões, cujo rótulo é derivado dos próprios dados
   (`PrecoTotalEfetivo > 115 % do contratual`). A taxa observada de aditivos da
   empresa é o que este modelo tenta prever à cabeça.
4. **IA (opcional, à parte do número)** — um parecer em Markdown escrito pelo
   modelo configurado, com os números à frente e recuo factual quando não há
   fornecedor. A IA **não** mexe no `score`: o número é reprodutível, o texto
   é interpretação.

Honestidade do número (importa mais do que a precisão aparente):

- Não existe rótulo de fraude. **Isto não é um juízo sobre a empresa**: é uma
  prioridade de inspeção, construída com dados públicos do portal.
- O `score` é a média **ponderada pelos componentes que existem** e a
  `cobertura` diz quanta informação entrou (uma triagem sem réguas de CPV tem
  cobertura < 1 e confiança menor).
- A triagem percorre só os contratos da empresa (1 consulta por empresa); o
  dossiê acrescenta as réguas do setor e a população de referência.

Tudo é **defensivo**: sem Elasticsearch devolve `{"error": ...}`; sem
`scikit-learn` cai nas regras (o componente de anomalia fica indisponível e o
peso é redistribuído — nunca se inventa um score).
"""
from __future__ import annotations

import logging
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from elasticsearch import Elasticsearch

from api import padroes_service as padroes
from api.elasticsearch_client import get_es_client

logger = logging.getLogger(__name__)

#: Versão do cartão do modelo. Sobe quando os pesos, limiares ou features mudam
#: — o frontend mostra-a para que dois números de datas diferentes não sejam
#: comparados como se fossem o mesmo modelo.
MODELO_VERSAO = "risco-1.0.0"

#: Aviso que acompanha sempre o número (aparece na UI e no relatório).
AVISO_GERAL = (
    "O nível de risco é uma **prioridade de análise** calculada com dados públicos do portal de "
    "contratação, não uma acusação: agrega sinais de aditivos, ajuste direto, concentração, "
    "concorrência e valores atípicos, mais a distância ao padrão das empresas comparáveis. "
    "Serve para decidir o que olhar primeiro."
)

#: Versão humana do método: de onde vêm os dados de cada nível.
METODOS: Dict[str, Dict[str, str]] = {
    "triagem": {
        "label": "Triagem (contratos da empresa)",
        "descricao": (
            "Lê os contratos da empresa (até 200) e cruza com o cadastro. Rápido e comparável entre "
            "empresas; não tem as réguas por CPV."
        ),
    },
    "detalhado": {
        "label": "Dossiê (réguas do setor + população de referência)",
        "descricao": (
            "Acrescenta as réguas de mediana/MAD por CPV e o modelo de anomalia ajustado à amostra "
            "nacional: é o risco mais completo do módulo."
        ),
    },
}

#: Componentes do risco. `peso` é a importância relativa (soma 1,0 quando todos
#: os componentes têm dados); `zero`/`cem` são os pontos da curva linear
#: (`zero` = 0 pontos, `cem` = 100 pontos, saturado).
COMPONENTES: List[Dict[str, Any]] = [
    {
        "id": "insolvencia",
        "label": "Processos de insolvência (CIRE)",
        "peso": 0.20,
        "zero": 0.0,
        "cem": 2.0,
        "unidade": "processos",
        "descricao": "Empresa com processo de insolvência/PER registado a continuar a receber contratos.",
        "metodo": "regra (join por NIF com o CIRE)",
    },
    {
        "id": "aditivos",
        "label": "Aditivos financeiros",
        "peso": 0.16,
        "zero": 0.0,
        "cem": 0.25,
        "unidade": "taxa",
        "descricao": "Parte dos contratos com valor efetivo acima do contratado (>115 %) — desvio orçamental.",
        "metodo": "regra (`ratio_efetivo > 1,15`) · o sinal que o modelo supervisionado prevê",
    },
    {
        "id": "ajuste_direto",
        "label": "Peso do ajuste direto",
        "peso": 0.13,
        "zero": 0.0,
        "cem": 0.80,
        "unidade": "taxa",
        "descricao": "Contratos adjudicados sem concurso público — limita a concorrência por desenho.",
        "metodo": "regra (prefixos de procedimento do portal)",
    },
    {
        "id": "concentracao",
        "label": "Dependência de um só comprador",
        "peso": 0.12,
        "zero": 0.50,
        "cem": 0.90,
        "unidade": "taxa",
        "descricao": "Parte do valor adjudicado que vem do maior comprador (uma só entidade sustenta a empresa).",
        "metodo": "regra (concentração de valor por adjudicante)",
    },
    {
        "id": "concorrencia",
        "label": "Falta de concorrência registada",
        "peso": 0.11,
        "zero": 0.0,
        "cem": 0.50,
        "unidade": "taxa",
        "descricao": "Contratos sem qualquer concorrente registado no portal (ou um só, em contrato relevante).",
        "metodo": "regra (`n_concorrentes`)",
    },
    {
        "id": "prazos",
        "label": "Transparência tardia",
        "peso": 0.08,
        "zero": 0.0,
        "cem": 180.0,
        "unidade": "dias",
        "descricao": "Tempo entre decisão/assinatura e publicação — quanto mais longo, mais difícil é o escrutínio a tempo.",
        "metodo": "regra (medianas de `dias_assinatura` e `dias_publicacao`)",
    },
    {
        "id": "valor_atipico",
        "label": "Valores atípicos para o CPV",
        "peso": 0.12,
        "zero": 0.0,
        "cem": 3.5,
        "unidade": "σ robusto",
        "descricao": "Desvio robusto (MAD) do log do valor face à mediana do próprio CPV — «normal» depende do setor.",
        "metodo": "estatística robusta por CPV (mediana + MAD)",
    },
    {
        "id": "anomalia_ml",
        "label": "Fora do padrão das empresas pares",
        "peso": 0.08,
        "zero": 0.50,
        "cem": 0.99,
        "unidade": "percentil",
        "descricao": "Percentil do IsolationForest ajustado à população de empresas de referência (não supervisionado).",
        "metodo": "ML: IsolationForest sobre features de carteira",
    },
]

#: Faixas do nível de risco. `max` é exclusivo (exceto a última).
NIVEIS: List[Dict[str, Any]] = [
    {"id": "baixo", "label": "Baixo", "max": 20.0, "cor": "#2dd4bf"},
    {"id": "moderado", "label": "Moderado", "max": 40.0, "cor": "#a3e635"},
    {"id": "elevado", "label": "Elevado", "max": 60.0, "cor": "#fbbf24"},
    {"id": "muito_elevado", "label": "Muito elevado", "max": 80.0, "cor": "#fb7185"},
    {"id": "critico", "label": "Crítico", "max": 100.1, "cor": "#ef4444"},
]

COMPONENTE_BY_ID = {item["id"]: item for item in COMPONENTES}

#: Limiar de aditivo partilhado com o módulo de padrões (`ratio_efetivo > 1,15`).
LIMIAR_ADITIVO = 1.15

#: Contratos por ano usados na amostra nacional de referência. Tem de ser o
#: mesmo valor que `padroes.analise_empresa` usa por omissão, para que as duas
#: leituras partilhem a mesma entrada de cache (`analyze` é a fase cara).
PER_YEAR_REFERENCIA = 250

CACHE_TTL_SECONDS = 1200
_CACHE: Dict[Tuple[Any, ...], Tuple[float, Dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Utilitários puros
# ---------------------------------------------------------------------------
def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _linear(value: Optional[float], zero: float, cem: float) -> Optional[float]:
    """Pontos 0–100 por interpolação linear entre `zero` e `cem` (saturado).

    `zero` pode ser maior do que `cem` (não aqui, mas a função não parte).
    """
    if value is None:
        return None
    if not math.isfinite(float(value)):
        return None
    if cem == zero:
        return 100.0 if value >= cem else 0.0
    return _clamp(100.0 * (float(value) - zero) / (cem - zero))


def _round(value: Optional[float], digits: int = 4) -> Optional[float]:
    if value is None:
        return None
    try:
        número = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(número):
        return None
    return round(número, digits)


def _serializavel(features: Dict[str, Any]) -> Dict[str, Any]:
    """Features prontas para JSON: números arredondados, o resto passa tal como está."""
    saida: Dict[str, Any] = {}
    for chave, valor in features.items():
        if valor is None or isinstance(valor, (str, bool, list, dict)):
            saida[chave] = valor
            continue
        número = _round(valor)
        saida[chave] = valor if número is None else número
    return saida


def _median(values: Sequence[float]) -> Optional[float]:
    valores = [float(item) for item in values if item is not None and math.isfinite(float(item))]
    if not valores:
        return None
    return padroes.median(valores)


def _share(rows: Sequence[Any], predicate) -> Optional[float]:
    """Proporção de linhas que cumprem `predicate`; `None` se **nenhuma** tem o dado."""
    válidos = [row for row in rows if predicate(row) is not None]
    if not válidos:
        return None
    return sum(1 for row in válidos if predicate(row)) / len(válidos)


def nivel_de(score: float) -> Dict[str, Any]:
    """Faixa do nível de risco (rótulo, cor e limites) para um score 0–100."""
    valor = _clamp(float(score or 0.0))
    anterior = 0.0
    for nível in NIVEIS:
        if valor < nível["max"]:
            topo = nível["max"] if nível["max"] <= 100 else 100.0
            return {**nível, "min": anterior, "faixa": f"{anterior:.0f}–{topo:.0f}"}
        anterior = nível["max"]
    último = NIVEIS[-1]
    return {**último, "min": 80.0, "faixa": "80–100"}


# ---------------------------------------------------------------------------
# Pontuação (pura — é isto que os testes exercitam sem Elasticsearch)
# ---------------------------------------------------------------------------
def _pontos_componente(component_id: str, features: Dict[str, Any], ml: Optional[Dict[str, Any]]) -> Tuple[Optional[float], List[str]]:
    """Pontos 0–100 de um componente + evidência legível (vazio quando não há dados)."""
    spec = COMPONENTE_BY_ID[component_id]
    zero, cem = float(spec["zero"]), float(spec["cem"])

    if component_id == "insolvencia":
        processos = features.get("insolvencias")
        if processos is None:
            return None, []
        pontos = _linear(processos, zero, cem) if processos > 0 else 0.0
        label = f"{int(processos)} processo(s) no CIRE" if processos else "sem processos no CIRE"
        return pontos, [label]

    if component_id == "aditivos":
        taxa = features.get("taxa_aditivos")
        if taxa is None:
            return None, []
        return _linear(taxa, zero, cem), [f"{taxa * 100:.1f}% dos contratos com valor efetivo acima do contratual"]

    if component_id == "ajuste_direto":
        taxa = features.get("taxa_ajuste_direto")
        if taxa is None:
            return None, []
        return _linear(taxa, zero, cem), [f"{taxa * 100:.1f}% dos contratos por ajuste direto/consulta prévia"]

    if component_id == "concentracao":
        taxa = features.get("concentracao_comprador")
        if taxa is None:
            return None, []
        evidência = [f"{taxa * 100:.1f}% do valor vem do maior comprador"]
        if features.get("adjudicantes_distintos") is not None:
            evidência.append(f"{int(features['adjudicantes_distintos'])} compradores distintos")
        return _linear(taxa, zero, cem), evidência

    if component_id == "concorrencia":
        sem = features.get("taxa_sem_concorrentes")
        baixa = features.get("taxa_baixa_concorrencia")
        if sem is None and baixa is None:
            return None, []
        # Pior dos dois sinais: é o que a regra do módulo de padrões também faz.
        pontos = max(
            _linear(sem, zero, cem) if sem is not None else 0.0,
            _linear(baixa, zero, cem * 0.8) if baixa is not None else 0.0,
        )
        evidência = []
        if sem is not None:
            evidência.append(f"{sem * 100:.1f}% dos contratos sem concorrentes registados")
        if baixa is not None:
            evidência.append(f"{baixa * 100:.1f}% com ≤1 concorrente em contratos ≥25 000 €")
        return pontos, evidência

    if component_id == "prazos":
        assinatura = features.get("dias_assinatura_mediana")
        publicacao = features.get("dias_publicacao_mediana")
        if assinatura is None and publicacao is None:
            return None, []
        pontos = max(
            _linear(assinatura, zero, cem) if assinatura is not None else 0.0,
            _linear(publicacao, zero, cem) if publicacao is not None else 0.0,
        )
        evidência = []
        if publicacao is not None:
            evidência.append(f"publicação {publicacao:.0f} dias depois da assinatura (mediana)")
        if assinatura is not None:
            evidência.append(f"assinatura {assinatura:.0f} dias depois da decisão (mediana)")
        return pontos, evidência

    if component_id == "valor_atipico":
        z = features.get("z_cpv_mediano")
        if z is None:
            return None, []
        return _linear(z, zero, cem), [f"desvio mediano de {z:.2f}σ face à mediana do CPV (σ robusto)"]

    if component_id == "anomalia_ml":
        if not ml or not ml.get("disponivel"):
            return None, []
        percentil = ml.get("percentil")
        if percentil is None:
            return None, []
        evidência = [
            f"percentil {percentil * 100:.0f} numa população de {ml.get('n_referencia')} empresas comparáveis "
            f"({ml.get('algoritmo')})"
        ]
        return _linear(percentil, zero, cem), evidência

    return None, []


def avaliar(
    features: Dict[str, Any],
    *,
    ml: Optional[Dict[str, Any]] = None,
    metodo: str = "triagem",
    avisos: Optional[Sequence[str]] = None,
    modelo_supervisionado: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Constrói o payload de risco a partir das features (função **pura**).

    O score renormaliza os pesos pelos componentes que têm dados, para que uma
    triagem sem réguas de CPV não seja penalizada por falta de informação — a
    `cobertura` (e a confiança) é que baixam.
    """
    componentes: List[Dict[str, Any]] = []
    for spec in COMPONENTES:
        pontos, evidência = _pontos_componente(spec["id"], features, ml)
        componentes.append(
            {
                "id": spec["id"],
                "label": spec["label"],
                "peso": spec["peso"],
                "descricao": spec["descricao"],
                "metodo": spec["metodo"],
                "unidade": spec["unidade"],
                "pontos": _round(pontos, 2),
                "evidencia": evidência,
                "disponivel": pontos is not None,
            }
        )

    disponíveis = [item for item in componentes if item["disponivel"]]
    peso_total = sum(item["peso"] for item in disponíveis)
    if not disponíveis or peso_total <= 0:
        return {
            "score": None,
            "nivel": None,
            "nivel_label": "Sem dados",
            "cor": "#94a3b8",
            "cobertura": 0.0,
            "confianca": "sem dados",
            "metodo": metodo,
            "metodo_label": METODOS.get(metodo, {}).get("label", metodo),
            "componentes": componentes,
            "fatores": [],
            "features": _serializavel(features),
            "ml": ml,
            "avisos": [*(avisos or []), "Sem dados suficientes para calcular risco (sem contratos ou sem Elasticsearch)."],
            "gerado_em": datetime.now(timezone.utc).isoformat(),
        }

    score = sum(item["peso"] * float(item["pontos"]) for item in disponíveis) / peso_total
    for item in componentes:
        item["peso_efetivo"] = _round(item["peso"] / peso_total, 4) if item["disponivel"] else 0.0
        item["contributo"] = _round((item["pontos"] or 0.0) * (item["peso_efetivo"] or 0.0), 3) if item["disponivel"] else 0.0

    nível = nivel_de(score)
    # «O que puxa o risco»: componentes a partir de metade da escala (uma
    # pontuação de 20/100 num componente não é um fator de risco, é ruído).
    fatores = sorted(
        (item for item in disponíveis if (item["pontos"] or 0) >= 50),
        key=lambda item: -(item["contributo"] or 0.0),
    )[:4]

    if peso_total >= 0.85:
        confianca = "alta"
    elif peso_total >= 0.6:
        confianca = "média"
    else:
        confianca = "baixa"

    saida: Dict[str, Any] = {
        "score": _round(score, 1),
        "nivel": nível["id"],
        "nivel_label": nível["label"],
        "cor": nível["cor"],
        "faixa": nível["faixa"],
        "cobertura": _round(peso_total, 3),
        "confianca": confianca,
        "metodo": metodo,
        "metodo_label": METODOS.get(metodo, {}).get("label", metodo),
        "componentes": componentes,
        "fatores": fatores,
        "features": _serializavel(features),
        "ml": ml,
        "modelo_supervisionado": modelo_supervisionado,
        "cartao_modelo": cartao_modelo(),
        "avisos": list(avisos or []),
        "gerado_em": datetime.now(timezone.utc).isoformat(),
    }
    if peso_total < 0.6:
        saida["avisos"].append(
            "Cobertura baixa: parte dos sinais não tem dados no portal — o número é indicativo, não conclusivo."
        )
    return saida


#: Pontos por severidade dos sinais de regra do contrato (módulo de padrões).
PESO_SEVERIDADE: Dict[str, float] = {"alerta": 55.0, "aviso": 30.0, "info": 15.0}

#: Limiares do risco **por contrato** (documentados no cartão do modelo).
LIMIAR_Z_CPV = 3.5
LIMIAR_DIAS_TRANSPARENCIA = 180


def pontuar_contrato(contrato: Dict[str, Any]) -> Dict[str, Any]:
    """Risco 0–100 de um **contrato** — o que liga os contratos ao risco da empresa.

    Soma transparente de sinais que o módulo de padrões já calcula: severidade das
    regras cumpridas, aditivo financeiro, valor atípico para o CPV, ajuste direto
    sem concorrência e transparência tardia. Serve para ordenar «que contratos
    olhar primeiro» dentro da empresa, não para acusar ninguém.
    """
    razoes: List[str] = []
    pontos = 0.0

    severidade = str(contrato.get("severidade") or "")
    if severidade in PESO_SEVERIDADE:
        pontos += PESO_SEVERIDADE[severidade]
        razoes.append(f"regra de severidade «{severidade}» cumprida")
    elif contrato.get("razoes"):
        pontos += PESO_SEVERIDADE["info"]
        razoes.append("regra informativa cumprida")

    ratio_efetivo = contrato.get("ratio_efetivo")
    if ratio_efetivo is not None and float(ratio_efetivo) > LIMIAR_ADITIVO:
        pontos += 25.0
        razoes.append(f"valor efetivo {float(ratio_efetivo):.2f}× o contratado (aditivo)")

    z = contrato.get("z_cpv")
    if z is not None and abs(float(z)) >= LIMIAR_Z_CPV:
        pontos += 20.0
        razoes.append(f"{abs(float(z)):.1f}σ face à mediana do CPV")

    if contrato.get("ajuste_direto") and (contrato.get("n_concorrentes") or 0) == 0:
        pontos += 15.0
        razoes.append("ajuste direto sem concorrentes registados")

    dias = contrato.get("dias_publicacao")
    if dias is not None and float(dias) > LIMIAR_DIAS_TRANSPARENCIA:
        pontos += 10.0
        razoes.append(f"publicado {int(float(dias))} dias depois da assinatura")

    score = _clamp(pontos)
    nível = nivel_de(score)
    return {
        "score": _round(score, 1),
        "nivel": nível["id"],
        "nivel_label": nível["label"],
        "cor": nível["cor"],
        "razoes": razoes,
    }


def cartao_modelo() -> Dict[str, Any]:
    """Cartão do modelo (o que entra no número, pesos, limiares e avisos)."""
    return {
        "versao": MODELO_VERSAO,
        "rotulo": "prioridade de análise (0–100), não probabilidade de crime",
        "aviso": AVISO_GERAL,
        "limiar_aditivo": LIMIAR_ADITIVO,
        "componentes": [
            {
                "id": item["id"],
                "label": item["label"],
                "peso": item["peso"],
                "limiar_zero": item["zero"],
                "limiar_saturacao": item["cem"],
                "unidade": item["unidade"],
                "metodo": item["metodo"],
                "descricao": item["descricao"],
            }
            for item in COMPONENTES
        ],
        "niveis": [{"id": item["id"], "label": item["label"], "max": item["max"], "cor": item["cor"]} for item in NIVEIS],
        "metodos": METODOS,
        "contrato": {
            "descricao": (
                "Risco por contrato (0–100): severidade das regras cumpridas + aditivo financeiro + valor "
                "atípico para o CPV + ajuste direto sem concorrência + transparência tardia."
            ),
            "pesos_severidade": PESO_SEVERIDADE,
            "pontos_aditivo": 25,
            "pontos_valor_atipico": 20,
            "pontos_ajuste_direto_sem_concorrencia": 15,
            "pontos_transparencia_tardia": 10,
            "limiar_aditivo": LIMIAR_ADITIVO,
            "limiar_z_cpv": LIMIAR_Z_CPV,
            "limiar_dias_transparencia": LIMIAR_DIAS_TRANSPARENCIA,
        },
    }


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------
def features_de_triagem(
    contratos: Sequence[Dict[str, Any]],
    *,
    insolvencias: Optional[int] = None,
) -> Dict[str, Any]:
    """Features a partir dos contratos já normalizados (`padroes._row_from_hit`).

    `insolvencias` vem de fora (e não do cadastro) porque só uma consulta ao CIRE
    com filtro de papel sabe distinguir «insolvente» de «credor».
    """
    total = len(contratos)
    valores = [row.get("valor") for row in contratos if row.get("valor")]
    valor_total = sum(float(valor) for valor in valores) if valores else None

    por_comprador: Dict[str, float] = {}
    for row in contratos:
        chave = str(row.get("adjudicante_nif") or row.get("adjudicante_nome") or "")
        if not chave:
            continue
        por_comprador[chave] = por_comprador.get(chave, 0.0) + float(row.get("valor") or 0.0)
    soma_compradores = sum(por_comprador.values())
    concentracao = (max(por_comprador.values()) / soma_compradores) if soma_compradores > 0 else None

    def tem_concorrentes(row: Dict[str, Any]) -> Optional[bool]:
        n = row.get("n_concorrentes")
        if n is None:
            return None
        return int(n) == 0

    def pouca_concorrencia(row: Dict[str, Any]) -> Optional[bool]:
        n = row.get("n_concorrentes")
        if n is None:
            return None
        # Mesma regra do módulo de padrões: ≤1 concorrente num contrato ≥25 000 €.
        return int(n) <= 1 and float(row.get("valor") or 0.0) >= 25_000

    insolvencias_cadastro = insolvencias

    return {
        "contratos": total,
        "valor_total": _round(valor_total, 2),
        "valor_mediano": _round(_median(valores), 2),
        "taxa_ajuste_direto": _round(
            (sum(1 for row in contratos if row.get("ajuste_direto")) / total) if total else None
        ),
        "taxa_aditivos": _round(
            (sum(1 for row in contratos if (row.get("ratio_efetivo") or 0.0) > LIMIAR_ADITIVO) / total) if total else None
        ),
        "concentracao_comprador": _round(concentracao),
        "adjudicantes_distintos": len(por_comprador) or None,
        "taxa_sem_concorrentes": _round(_share(contratos, tem_concorrentes)),
        "taxa_baixa_concorrencia": _round(_share(contratos, pouca_concorrencia)),
        "dias_assinatura_mediana": _round(_median([row.get("dias_assinatura") for row in contratos]), 1),
        "dias_publicacao_mediana": _round(_median([row.get("dias_publicacao") for row in contratos]), 1),
        "z_cpv_mediano": None,
        "insolvencias": insolvencias_cadastro,
        "anos": sorted({row.get("ano") for row in contratos if row.get("ano")}),
    }


def features_de_analise(analise: Dict[str, Any], *, insolvencias: Optional[int] = None) -> Dict[str, Any]:
    """Features a partir da análise completa (`padroes.analise_empresa`).

    Sem `insolvencias` explícitas, usa o que a análise traz — que vem de uma
    consulta por `nifs` e pode contar **credores** (banca, AT, Segurança Social)
    como processos da empresa. O serviço passa sempre o valor filtrado por papel.
    """
    resumo = analise.get("resumo") or {}
    contratos = analise.get("contratos") or []
    relacoes = analise.get("relacoes") or {}
    features = features_de_triagem(contratos, insolvencias=insolvencias)
    if insolvencias is None:
        lista = relacoes.get("insolvencias")
        if isinstance(lista, list):
            features["insolvencias"] = len(lista) if lista else (1 if resumo.get("insolvente") else 0)
        elif resumo.get("insolvente") is not None:
            features["insolvencias"] = 1 if resumo.get("insolvente") else 0

    # Réguas do setor: só aqui existem (z robusto por CPV).
    zs = [abs(float(row["z_cpv"])) for row in contratos if row.get("z_cpv") is not None]
    features["z_cpv_mediano"] = _round(_median(zs), 2)

    # Os agregados da análise são a fonte de verdade (já ignoram efetivo = 0).
    if resumo.get("taxa_ajuste_direto") is not None:
        features["taxa_ajuste_direto"] = _round(resumo["taxa_ajuste_direto"])
    if resumo.get("taxa_aditivo") is not None:
        features["taxa_aditivos"] = _round(resumo["taxa_aditivo"])
    if resumo.get("concentracao_adjudicante") is not None:
        features["concentracao_comprador"] = _round(resumo["concentracao_adjudicante"])
    if resumo.get("valor_total") is not None:
        features["valor_total"] = _round(resumo["valor_total"], 2)
    if resumo.get("valor_mediano") is not None:
        features["valor_mediano"] = _round(resumo["valor_mediano"], 2)
    if resumo.get("adjudicantes_distintos") is not None:
        features["adjudicantes_distintos"] = int(resumo["adjudicantes_distintos"])
    features["contratos"] = len(contratos) or resumo.get("contratos")
    features["severidade"] = padroes.severidade_de(analise.get("sinais") or [])
    return features


# ---------------------------------------------------------------------------
# ML: anomalia face à população de referência
# ---------------------------------------------------------------------------
#: Features usadas pelo modelo de anomalia (têm de existir nos dois lados).
ML_FEATURES: Tuple[str, ...] = (
    "contratos",
    "valor_total",
    "valor_mediano",
    "adjudicantes_distintos",
    "concentracao_comprador",
    "taxa_ajuste_direto",
    "taxa_aditivos",
)


def _matrix(linhas: Sequence[Dict[str, Any]]) -> Tuple[np.ndarray, List[str]]:
    """Matriz `float` com log dos valores monetários e colunas em falta removidas."""
    nomes = list(ML_FEATURES)
    matriz = np.full((len(linhas), len(nomes)), np.nan, dtype=float)
    for i, linha in enumerate(linhas):
        for j, nome in enumerate(nomes):
            valor = linha.get(nome)
            if valor is None:
                continue
            try:
                número = float(valor)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(número):
                continue
            if nome in {"valor_total", "valor_mediano"}:
                if número <= 0:
                    continue
                número = math.log10(número)
            if nome in {"contratos", "adjudicantes_distintos"}:
                número = math.log1p(max(0.0, número))
            matriz[i, j] = número
    return matriz, nomes


def _impute(matriz: np.ndarray) -> np.ndarray:
    """Preenche NaNs pela mediana da coluna (0 quando a coluna é toda NaN)."""
    saida = matriz.copy()
    for j in range(saida.shape[1]):
        coluna = saida[:, j]
        válidos = coluna[np.isfinite(coluna)]
        valor = float(np.median(válidos)) if válidos.size else 0.0
        coluna[~np.isfinite(coluna)] = valor
    return saida


def anomalia_ml(
    alvo: Dict[str, Any],
    referencia: Sequence[Dict[str, Any]],
    *,
    seed: int = 7,
    min_referencia: int = 60,
) -> Optional[Dict[str, Any]]:
    """Percentil do `alvo` no `IsolationForest` ajustado à população de referência.

    Sem `scikit-learn` ou com referência pequena devolve um bloco com
    `disponivel: False` e o motivo — nunca um número inventado.
    """
    linhas = [linha for linha in referencia if isinstance(linha, dict)]
    if len(linhas) < min_referencia:
        return {
            "disponivel": False,
            "motivo": f"população de referência pequena ({len(linhas)} empresas; mínimo {min_referencia}).",
            "algoritmo": "IsolationForest",
        }
    sklearn = padroes._sklearn()  # noqa: SLF001 — helper partilhado do pacote
    if sklearn is None:
        return {"disponivel": False, "motivo": "scikit-learn indisponível.", "algoritmo": "IsolationForest"}

    matriz_ref, nomes = _matrix(linhas)
    matriz_alvo, _ = _matrix([alvo])
    ref = _impute(matriz_ref)
    alvo_preenchido = matriz_alvo.copy()
    for j in range(alvo_preenchido.shape[1]):
        if not np.isfinite(alvo_preenchido[0, j]):
            válidos = matriz_ref[:, j][np.isfinite(matriz_ref[:, j])]
            alvo_preenchido[0, j] = float(np.median(válidos)) if válidos.size else 0.0
    try:
        modelo = sklearn["IsolationForest"](n_estimators=200, random_state=seed, contamination="auto").fit(ref)
        scores_ref = modelo.score_samples(ref)
        score_alvo = float(modelo.score_samples(alvo_preenchido)[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning("IsolationForest falhou: %s", exc)
        return {"disponivel": False, "motivo": f"treino falhou: {exc}", "algoritmo": "IsolationForest"}

    percentil = float(np.mean(scores_ref >= score_alvo))
    return {
        "disponivel": True,
        "algoritmo": "IsolationForest (não supervisionado)",
        "n_referencia": int(len(linhas)),
        "features": [nome for nome in nomes],
        "score_bruto": _round(score_alvo, 5),
        "percentil": _round(percentil, 4),
        "mediana_referencia": _round(float(np.median(scores_ref)), 5),
        "nota": "Percentil da empresa entre as empresas comparáveis: quanto mais alto, mais fora do padrão.",
    }


# ---------------------------------------------------------------------------
# Elasticsearch
# ---------------------------------------------------------------------------
def _client(es: Optional[Elasticsearch] = None) -> Optional[Elasticsearch]:
    return es or get_es_client(request_timeout=90)


#: O cadastro (`finance_contribuintes.country`) guarda o **nome** do país
#: («Portugal», «Espanha»), não o código do portal — a normalização é aqui para
#: que a pesquisa e as rotas aceitem as duas formas.
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


def tokens_do_pedido(texto: str) -> List[str]:
    """Palavras úteis do pedido (sem acentos, com 3+ caracteres) para medir a relevância."""
    return [token for token in re.split(r"\W+", padroes.fold(texto or "")) if len(token) >= 3]


#: Palavras que **não** identificam uma empresa (formas societárias e ligações).
#: «CLARANET, S.A.» tem de procurar `claranet` — com `s.a` no filtro estrito,
#: o `and` casava também «IGNÍT PEOPLE, S.A.» e afins.
RUIDO_FORMAS: frozenset = frozenset(
    {"lda", "ldas", "sld", "slda", "slu", "unipessoal", "eireli", "cia", "soc", "sociedade", "empresa"}
)


def tokens_significativos(texto: str) -> List[str]:
    """Tokens que identificam a empresa (sem formas societárias nem ligações)."""
    return [token for token in tokens_do_pedido(texto) if token not in RUIDO_FORMAS]


def _nif_pesquisa(texto: str) -> Optional[str]:
    """Devolve o texto quando **é** um NIF (8–10 caracteres com 6+ dígitos), em maiúsculas."""
    compacto = re.sub(r"[\s.\-/]", "", texto or "")
    if not compacto or not re.fullmatch(r"[A-Za-z0-9]+", compacto):
        return None
    if not 8 <= len(compacto) <= 10:
        return None
    if sum(1 for ch in compacto if ch.isdigit()) < 6:
        return None
    return compacto.upper()


def consulta_cadastro(texto: str, *, estrito: bool = True) -> Optional[Dict[str, Any]]:
    """Consulta sobre `finance_contribuintes` para resolver um nome (ou NIF).

    `estrito=True` exige **todas** as palavras significativas (precisão: escrever
    «CLARANET, S.A.» encontra a Claranet e não os maiores contratantes do país).
    `estrito=False` acrescenta uma cláusula de recuo (`ou`) para não devolver
    vazio — quem a usa tem de dizer que os resultados são parciais.
    """
    tokens = tokens_significativos(texto)
    frase = " ".join(tokens)
    should: List[Dict[str, Any]] = []
    nif = _nif_pesquisa(texto)
    if nif:
        should.append({"terms": {"nif": [nif, nif.lower()], "boost": 12}})
    if frase:
        should.append({"match_phrase": {"name": {"query": frase, "boost": 8}}})
        should.append(
            {
                "multi_match": {
                    "query": frase,
                    "fields": ["name^4", "search_text^2"],
                    "type": "best_fields",
                    "operator": "and",
                    "boost": 5,
                }
            }
        )
        should.append({"match": {"name.autocomplete": {"query": frase, "operator": "and", "boost": 3}}})
    if not estrito and frase:
        should.append(
            {
                "multi_match": {
                    "query": frase,
                    "fields": ["name^2", "name.autocomplete", "search_text"],
                    "type": "best_fields",
                    "operator": "or",
                }
            }
        )
    if not should:
        return None
    return {"bool": {"should": should, "minimum_should_match": 1}}


#: Campos do cadastro que o módulo mostra/soma (`_source`).
CAMPOS_CADASTRO: Tuple[str, ...] = (
    "nif",
    "name",
    "names",
    "type",
    "roles",
    "location",
    "sources",
    "source_labels",
    "country",
    "contracts_count",
    "contracts_value",
    "contratos_es_count",
    "contratos_es_value",
    "cire_count",
)


def _procurar_cadastro(texto: str, *, size: int, estrito: bool) -> Tuple[List[Dict[str, Any]], int]:
    """Pesquisa o cadastro e devolve `(documentos, total)` **por relevância**.

    A ordenação é `_score` primeiro e só depois o volume de contratos: ordenar só
    por contratos fazia uma pesquisa com recuo (`ou`) devolver os maiores
    contratantes do país em vez da empresa escrita.
    """
    client = get_es_client(request_timeout=45)
    consulta = consulta_cadastro(texto, estrito=estrito)
    if client is None or consulta is None:
        return [], 0
    body = {
        "size": max(1, min(int(size), 50)),
        "track_total_hits": True,
        "query": consulta,
        "sort": ["_score", {"contracts_count": {"order": "desc", "missing": 0}}],
        "_source": [*CAMPOS_CADASTRO, "contracts_count"],
    }
    resp = _search(client, padroes.CONTRIBUINTES_INDEX, body, timeout=45)
    hits = (resp.get("hits") or {}).get("hits") or []
    total = (((resp.get("hits") or {}).get("total") or {}) or {}).get("value")
    documentos = [{**(hit.get("_source") or {}), "_score": hit.get("_score")} for hit in hits]
    return documentos, int(total or len(documentos))


def _contem_sequencia(palavras: Sequence[str], alvo: Sequence[str]) -> bool:
    """`True` se `alvo` aparece como sequência contígua em `palavras`.

    Compara **tokens**, não texto: «mota engil» tem de casar com «MOTA-ENGIL»
    (o hífen não existe depois de `fold`+split) e a ordem conta.
    """
    n = len(alvo)
    if not n or n > len(palavras):
        return False
    return any(list(palavras[i : i + n]) == list(alvo) for i in range(len(palavras) - n + 1))


def ordem_candidato(doc: Dict[str, Any], *, frase: str, tokens: Sequence[str]) -> Tuple[int, int, int, int, float]:
    """Ordem de relevância de uma empresa do cadastro face ao pedido (menor = melhor).

    O BM25 sozinho não chega: em «águas do norte» dava a *Águas do Norte
    Alentejano* (nome curto) à frente da *Águas do Norte, SA*. Critérios, por
    esta ordem:

    1. o nome contém a frase pedida, como sequência de palavras;
    2. a empresa tem contratos registados (a que se procura costuma tê-los);
    3. menos palavras a mais no nome face ao pedido (**0 a 2**);
    4. mais contratos (a empresa maior é, em regra, a que se procura);
    5. o `_score` do Elasticsearch (desempate final).
    """
    nome = padroes.fold(str(doc.get("name") or ""))
    palavras = [token for token in tokens_do_pedido(nome) if token not in RUIDO_FORMAS]
    alvo = list(tokens)
    contém_frase = 0 if alvo and _contem_sequencia(palavras, alvo) else 1
    contratos = int(doc.get("contracts_count") or doc.get("contratos_es_count") or 0)
    sem_contratos = 0 if contratos > 0 else 1
    extras = min(len(set(palavras) - set(alvo)), 2)
    score = float(doc.get("_score") or 0.0)
    return (contém_frase, sem_contratos, extras, -contratos, -score)


def _item_de_cadastro(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza um documento do cadastro no item que a UI consome."""
    return {
        "nif": doc.get("nif"),
        "nome": doc.get("name") or doc.get("nif"),
        "names": (doc.get("names") or [])[:3],
        "pais": pais_codigo(doc.get("country")),
        "tipo": doc.get("type"),
        "roles": doc.get("roles") or [],
        "local": doc.get("location") or {},
        "contratos": doc.get("contracts_count") or doc.get("contratos_es_count"),
        "valor": doc.get("contracts_value") or doc.get("contratos_es_value"),
        "fontes": doc.get("source_labels") or doc.get("sources") or [],
    }


def pais_codigo(valor: Optional[str]) -> str:
    """Código do portal (`PT`/`ES`) a partir do código ou do nome do país."""
    chave = padroes.fold(str(valor or ""))
    return PAIS_ALIASES.get(chave, str(valor or padroes.PAIS_DEFAULT).upper())


def _search(client: Elasticsearch, index: str, body: Dict[str, Any], *, timeout: int = 60) -> Dict[str, Any]:
    try:
        return client.search(index=index, body=body, request_timeout=timeout) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falha de pesquisa em %s: %s", index, exc)
        return {"error": str(exc)}


def _spec(pais: Optional[str]):
    return padroes.COUNTRIES.get(pais_codigo(pais))


def _contratos_da_empresa(
    client: Elasticsearch,
    spec: Any,
    nif: str,
    *,
    limit: int = 200,
    ano_from: Optional[int] = None,
    ano_to: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Contratos em que `nif` é adjudicatário (normalizados) + total registado."""
    filtros: List[Dict[str, Any]] = [padroes._empresa_query(spec, nif)]  # noqa: SLF001
    if ano_from is not None or ano_to is not None:
        rng: Dict[str, Any] = {}
        if ano_from is not None:
            rng["gte"] = int(ano_from)
        if ano_to is not None:
            rng["lte"] = int(ano_to)
        filtros.append({"range": {spec.year_field: rng}})
    body = {
        "size": max(10, min(int(limit), 1000)),
        "track_total_hits": True,
        "query": {"bool": {"filter": filtros}},
        "sort": [{spec.pub_date: {"order": "desc", "unmapped_type": "date"}}],
        "_source": list(spec.source_fields),
    }
    resp = _search(client, spec.index, body, timeout=90)
    total = (((resp.get("hits") or {}).get("total") or {}) or {}).get("value")
    rows = [padroes._row_from_hit(spec, hit) for hit in (resp.get("hits") or {}).get("hits") or []]  # noqa: SLF001
    return rows, int(total) if total is not None else None


#: Papel que conta como insolvência **da empresa**. O índice do CIRE lista em
#: `nifs` todos os intervenientes do processo — bancos, AT e Segurança Social
#: incluídos, na qualidade de **credores**. Sem este filtro, a Caixa Económica
#: Montepio Geral aparecia com 100 pontos de insolvência por cobrar dívidas.
PAPEL_INSOLVENTE = "insolvente"


def insolvencias_da_empresa(client: Elasticsearch, nif: str, *, size: int = 20) -> List[Dict[str, Any]]:
    """Processos do CIRE em que `nif` é **a insolvente** (não credor)."""
    body = {
        "size": max(1, min(int(size), 50)),
        "track_total_hits": False,
        "_source": ["insolvente", "especie", "ato", "data_publicacao", "tribunal", "processo_numero", "intervenientes"],
        "query": {"terms": {"nifs": [str(nif)]}},
        "sort": [{"data_publicacao": {"order": "desc", "unmapped_type": "date"}}],
    }
    resp = _search(client, padroes.CIRE_INDEX, body, timeout=45)
    saida: List[Dict[str, Any]] = []
    for hit in (resp.get("hits") or {}).get("hits") or []:
        src = hit.get("_source") or {}
        intervenientes = [iv for iv in (src.get("intervenientes") or []) if isinstance(iv, dict)]
        papéis = [
            padroes.fold(str(iv.get("papel") or ""))
            for iv in intervenientes
            if str(iv.get("nif") or "") == str(nif)
        ]
        if not any(PAPEL_INSOLVENTE in papel for papel in papéis):
            continue
        saida.append(
            {
                "especie": src.get("especie"),
                "ato": src.get("ato"),
                "data": src.get("data_publicacao"),
                "tribunal": src.get("tribunal"),
                "processo": src.get("processo_numero"),
                "papel": next((papel for papel in papéis if PAPEL_INSOLVENTE in papel), PAPEL_INSOLVENTE),
            }
        )
    return saida


def _cadastro(client: Elasticsearch, nif: str) -> Dict[str, Any]:
    """Documento do cadastro (`finance_contribuintes`) para métricas estruturais."""
    resp = _search(
        client,
        padroes.CONTRIBUINTES_INDEX,
        {
            "size": 1,
            "track_total_hits": False,
            "query": {"term": {"nif": str(nif)}},
            "_source": {
                "includes": [
                    "nif",
                    "name",
                    "names",
                    "country",
                    "type",
                    "roles",
                    "location",
                    "sources",
                    "contracts_count",
                    "contracts_value",
                    "contracts_as_adjudicante",
                    "contracts_as_adjudicatario",
                    "contracts_first_date",
                    "contracts_last_date",
                    "contratos_es_count",
                    "contratos_es_value",
                    "cire_count",
                    "societario_count",
                    "people_roles_count",
                    "people_companies_count",
                    "firmas_count",
                    "trademarks_count",
                    "records_total",
                    "first_seen",
                    "last_seen",
                ]
            },
        },
        timeout=30,
    )
    hits = (resp.get("hits") or {}).get("hits") or []
    return (hits[0].get("_source") or {}) if hits else {}


def _resolver_candidatos(q: str, *, size: int = 12) -> Dict[str, Any]:
    """Empresas do cadastro que casam com o texto (estrito; recuo parcial se vazio).

    Devolve `{itens, total, parcial}`: `parcial=True` significa que nenhuma empresa
    casou com **todas** as palavras do pedido e o que vem são correspondências
    aproximadas — a rota tem de o dizer, não apresentá-las como resultados.
    """
    texto = str(q or "").strip()
    if len(texto) < 2:
        return {"itens": [], "total": 0, "disponiveis": 0, "parcial": False}
    tokens = tokens_significativos(texto)
    frase = " ".join(tokens)

    def _mapear(documentos: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ordenados = sorted(documentos, key=lambda doc: ordem_candidato(doc, frase=frase, tokens=tokens))
        return [_item_de_cadastro(doc) for doc in ordenados]

    docs, total = _procurar_cadastro(texto, size=size, estrito=True)
    if docs:
        itens = _mapear(docs)
        return {"itens": itens, "total": total, "disponiveis": len(itens), "parcial": False}
    docs, total = _procurar_cadastro(texto, size=size, estrito=False)
    itens = _mapear(docs)
    return {"itens": itens, "total": total, "disponiveis": len(itens), "parcial": True}


# ---------------------------------------------------------------------------
# Risco: triagem e dossiê
# ---------------------------------------------------------------------------
def risco_empresa(
    *,
    nif: Optional[str] = None,
    nome: Optional[str] = None,
    pais: str = padroes.PAIS_DEFAULT,
    ano_from: Optional[int] = None,
    ano_to: Optional[int] = None,
    detalhado: bool = False,
    max_contratos: int = 200,
    use_cache: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Risco de uma empresa. `detalhado` acrescenta réguas de CPV e o modelo de anomalia.

    Sem `detalhado` faz **uma** consulta aos contratos da empresa (triagem, rápido e
    comparável entre empresas). Com `detalhado` reutiliza a análise completa do
    módulo de padrões (cache) e a população de referência do `analyze()`.
    """
    spec = _spec(pais)
    if spec is None:
        return {"error": f"país desconhecido: {pais}", "paises": list(padroes.COUNTRIES)}
    client = _client(es)
    if client is None:
        return {"error": "Elasticsearch indisponível"}

    chave = (spec.key, nif or f"nome:{nome}", ano_from, ano_to, bool(detalhado), int(max_contratos))
    if use_cache:
        with _CACHE_LOCK:
            entrada = _CACHE.get(chave)
        if entrada and time.time() - entrada[0] < CACHE_TTL_SECONDS:
            return {**entrada[1], "cache": True}

    if detalhado:
        payload = _risco_detalhado(
            client, spec, nif=nif, nome=nome, ano_from=ano_from, ano_to=ano_to, max_contratos=max_contratos
        )
    else:
        payload = _risco_triagem(client, spec, nif=nif, nome=nome, ano_from=ano_from, ano_to=ano_to, max_contratos=max_contratos)

    if use_cache and not payload.get("error"):
        with _CACHE_LOCK:
            _CACHE[chave] = (time.time(), payload)
    return payload


def _risco_triagem(
    client: Elasticsearch,
    spec: Any,
    *,
    nif: Optional[str],
    nome: Optional[str],
    ano_from: Optional[int],
    ano_to: Optional[int],
    max_contratos: int,
) -> Dict[str, Any]:
    candidatos: List[Dict[str, Any]] = []
    if not nif:
        resolvido = padroes.resolver_empresa(str(nome or ""), pais=spec.key, es=client)
        if resolvido.get("error"):
            return resolvido
        nif = resolvido.get("nif")
        candidatos = resolvido.get("candidatos") or []
    nif = str(nif or "").strip()
    if not nif:
        return {"error": "NIF em falta"}

    contratos, total = _contratos_da_empresa(client, spec, nif, limit=max_contratos, ano_from=ano_from, ano_to=ano_to)
    cadastro = _cadastro(client, nif) if spec.key == "PT" else {}
    insolvencias = insolvencias_da_empresa(client, nif)
    nome_final = cadastro.get("name") or (candidatos[0].get("nome") if candidatos else None)
    if not nome_final:
        for row in contratos:
            match = next((p for p in row.get("adjudicatarios") or [] if str(p.get("nif")) == nif), None)
            if match and match.get("nome"):
                nome_final = match["nome"]
                break

    if not contratos:
        risco = avaliar({}, metodo="triagem", avisos=["Nenhum contrato encontrado para esta empresa nos filtros dados."])
        return {
            "pais": spec.key,
            "nif": nif,
            "nome": nome_final or nif,
            "contratos_total": int(total or 0),
            "contratos_analisados": 0,
            "cadastro": cadastro or None,
            "insolvencias": insolvencias,
            "risco": risco,
            "cache": False,
        }

    features = features_de_triagem(contratos, insolvencias=len(insolvencias))
    avisos: List[str] = []
    if total and total > len(contratos):
        avisos.append(
            f"Triagem sobre {len(contratos)} de {total} contratos registados (os mais recentes)."
        )
    risco = avaliar(features, metodo="triagem", avisos=avisos)
    anos = features.get("anos") or []
    return {
        "pais": spec.key,
        "pais_label": spec.label,
        "nif": nif,
        "nome": nome_final or nif,
        "contratos_total": int(total or len(contratos)),
        "contratos_analisados": len(contratos),
        # Mesma convenção da análise completa: [primeiro ano, último ano].
        "anos": [anos[0], anos[-1]] if anos else None,
        "cadastro": cadastro or None,
        "insolvencias": insolvencias,
        "risco": risco,
        "cache": False,
    }


def _contratos_com_risco(analise: Dict[str, Any], *, limite: int = 400) -> List[Dict[str, Any]]:
    """Contratos da empresa com o índice de risco de cada um (o que olhar primeiro)."""
    saida: List[Dict[str, Any]] = []
    for contrato in (analise.get("contratos") or [])[:limite]:
        avaliação = pontuar_contrato(contrato)
        saida.append(
            {
                "id": contrato.get("id"),
                "ano": contrato.get("ano"),
                "data_publicacao": contrato.get("data_publicacao"),
                "objeto": str(contrato.get("objeto") or "")[:180],
                "valor": contrato.get("valor"),
                "valor_efetivo": contrato.get("valor_efetivo"),
                "ratio_base": contrato.get("ratio_base"),
                "ratio_efetivo": contrato.get("ratio_efetivo"),
                "procedimento": contrato.get("procedimento"),
                "ajuste_direto": bool(contrato.get("ajuste_direto")),
                "cpv": contrato.get("cpv"),
                "cpv_desc": contrato.get("cpv_desc"),
                "n_concorrentes": contrato.get("n_concorrentes"),
                "dias_assinatura": contrato.get("dias_assinatura"),
                "dias_publicacao": contrato.get("dias_publicacao"),
                "z_cpv": contrato.get("z_cpv"),
                "adjudicante": contrato.get("adjudicante"),
                "adjudicante_nif": contrato.get("adjudicante_nif"),
                "severidade": contrato.get("severidade"),
                "sinais": [razao.get("padrao") for razao in (contrato.get("razoes") or [])],
                "risco": avaliação,
            }
        )
    saida.sort(key=lambda item: -float((item.get("risco") or {}).get("score") or 0.0))
    return saida


def _risco_detalhado(
    client: Elasticsearch,
    spec: Any,
    *,
    nif: Optional[str],
    nome: Optional[str],
    ano_from: Optional[int],
    ano_to: Optional[int],
    max_contratos: int,
) -> Dict[str, Any]:
    analise = padroes.analise_empresa(
        nif=nif,
        nome=nome,
        pais=spec.key,
        ano_from=ano_from,
        ano_to=ano_to,
        max_contratos=max(int(max_contratos), 200),
        use_cache=True,
        es=client,
    )
    if analise.get("error"):
        # Sem análise completa (p.ex. empresa sem contratos) cai na triagem —
        # e diz que o fez, em vez de devolver um risco sem base.
        triagem = _risco_triagem(
            client, spec, nif=nif, nome=nome, ano_from=ano_from, ano_to=ano_to, max_contratos=max_contratos
        )
        if not triagem.get("error"):
            triagem["risco"]["avisos"].append(
                "Análise detalhada indisponível: " + str(analise.get("error")) + " — risco calculado em triagem."
            )
            triagem["risco"]["metodo"] = "triagem"
            triagem["risco"]["metodo_label"] = METODOS["triagem"]["label"]
        return triagem

    insolvencias = insolvencias_da_empresa(client, str(analise.get("nif") or nif or ""))
    features = features_de_analise(analise, insolvencias=len(insolvencias))
    contratos = _contratos_com_risco(analise, limite=int(max(max_contratos, 200)))
    # População de referência: a mesma amostra nacional que a análise já usou
    # (chave de cache idêntica ⇒ sem custo extra).
    base = padroes.analyze(
        pais=spec.key,
        ano_from=ano_from,
        ano_to=ano_to,
        per_year=PER_YEAR_REFERENCIA,
        use_cache=True,
        es=client,
    )
    referência = base.get("entidades") or []
    ml = anomalia_ml(features, referência, seed=7)
    risco_supervisionado = (base.get("risco_aditivo") or {}) if isinstance(base.get("risco_aditivo"), dict) else {}
    avisos = []
    if analise.get("aviso"):
        avisos.append(analise["aviso"])
    risco = avaliar(
        features,
        ml=ml,
        metodo="detalhado",
        avisos=avisos,
        modelo_supervisionado={
            "disponivel": bool(risco_supervisionado.get("disponivel")),
            "auc": risco_supervisionado.get("auc"),
            "lift_top_decile": risco_supervisionado.get("lift_top_decile"),
            "rotulo": risco_supervisionado.get("rotulo"),
            "aviso": risco_supervisionado.get("aviso"),
            "contratos": risco_supervisionado.get("contratos"),
        },
    )
    return {
        "pais": spec.key,
        "pais_label": spec.label,
        "nif": analise.get("nif"),
        "nome": analise.get("nome"),
        "ficha": analise.get("ficha"),
        "contratos_total": analise.get("contratos_total"),
        "contratos_analisados": analise.get("contratos_analisados"),
        "anos": analise.get("anos"),
        "risco": risco,
        "resumo": analise.get("resumo"),
        "insolvencias": insolvencias,
        "sinais": analise.get("sinais"),
        "por_cpv": analise.get("por_cpv"),
        "por_procedimento": analise.get("por_procedimento"),
        "relacoes": analise.get("relacoes"),
        "adjudicantes": analise.get("adjudicantes"),
        "contratos": contratos,
        "contratos_resumo": {
            "total": len(contratos),
            "por_nivel": {
                nível["id"]: sum(1 for item in contratos if (item.get("risco") or {}).get("nivel") == nível["id"])
                for nível in NIVEIS
            },
            "mais_50": sum(1 for item in contratos if float((item.get("risco") or {}).get("score") or 0.0) >= 50),
        },
        "analise": padroes._linha_conjunto(analise),  # noqa: SLF001 — mesma forma usada na comparação
        "cache": False,
    }


# ---------------------------------------------------------------------------
# Pesquisa tipo motor de busca
# ---------------------------------------------------------------------------
def pesquisa(
    q: str,
    *,
    pais: Optional[str] = None,
    nivel: Optional[str] = None,
    ordenar: str = "relevancia",
    size: int = 10,
    from_: int = 0,
    detalhado: bool = False,
    max_workers: int = 6,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa de empresas com **nível de risco**.

    `ordenar` é a **ordem da lista**: `relevancia` (por omissão, como num motor de
    busca — foi o que fazia «CLARANET, S.A.» dar a Claranet), `risco`, `valor` ou
    `contratos`. A relevância é sempre o que escolhe *que* empresas entram na
    página; a ordenação pedida aplica-se dentro dela.

    O risco de cada empresa é calculado em paralelo (e fica em cache): a página
    devolve no máximo `size` empresas pontuadas por pedido, para que a resposta
    não dependa de centenas de análises.
    """
    client = _client(es)
    if client is None:
        return {"error": "Elasticsearch indisponível", "itens": [], "total": 0}
    texto = str(q or "").strip()
    if not texto:
        return {
            "itens": [],
            "total": 0,
            "query": "",
            "sugestoes": sugestoes("", size=6).get("itens") or [],
            "cartao_modelo": cartao_modelo(),
        }

    size = max(1, min(int(size or 10), 30))
    alvo = from_ + size
    # Traz folga para a paginação: o que não for pontuado nesta página continua
    # disponível nas seguintes, sem repetir a resolução do cadastro.
    limite_cadastro = min(max(alvo + 20, 30), 60)
    resolucao = _resolver_candidatos(texto, size=limite_cadastro)
    candidatos = resolucao["itens"]
    if pais:
        chave = pais_codigo(pais)
        candidatos = [item for item in candidatos if str(item.get("pais") or "").upper() == chave]
    if not candidatos:
        return {
            "itens": [],
            "total": 0,
            "query": texto,
            "avisos": ["Nenhuma empresa do cadastro casou com o texto (nem por correspondência parcial)."],
            "cartao_modelo": cartao_modelo(),
        }

    # A relevância decide *que* empresas entram na página; a ordenação pedida
    # aplica-se a essa página (ordem de lista, como em qualquer motor de busca).
    janela = candidatos[from_:alvo]

    def _pontuar(item: Dict[str, Any]) -> Dict[str, Any]:
        try:
            risco = risco_empresa(
                nif=item.get("nif"),
                pais=item.get("pais") or padroes.PAIS_DEFAULT,
                detalhado=detalhado,
                use_cache=True,
                es=client,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Risco falhou para %s: %s", item.get("nif"), exc)
            return {**item, "risco": None, "erro": str(exc)}
        if risco.get("error"):
            return {**item, "risco": None, "erro": risco["error"]}
        return {
            **item,
            "pais": risco.get("pais") or item.get("pais"),
            "pais_label": risco.get("pais_label"),
            "nome": risco.get("nome") or item.get("nome"),
            "contratos_total": risco.get("contratos_total"),
            "contratos_analisados": risco.get("contratos_analisados"),
            "anos": risco.get("anos"),
            "risco": risco.get("risco"),
            "erro": None,
        }

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 8))) as pool:
        itens = list(pool.map(_pontuar, janela))

    if nivel:
        alvo_nivel = str(nivel).lower()
        itens = [item for item in itens if ((item.get("risco") or {}).get("nivel") == alvo_nivel)]

    if ordenar == "risco":
        itens.sort(key=lambda item: -(((item.get("risco") or {}).get("score")) or -1))
    elif ordenar == "valor":
        itens.sort(key=lambda item: -(float(item.get("valor") or 0.0)))
    elif ordenar == "contratos":
        itens.sort(key=lambda item: -(int(item.get("contratos_total") or 0)))
    # `relevancia`: mantém a ordem da resolução do cadastro (nome mais próximo primeiro).

    # Facetas por nível sobre a página atual (leitura rápida do conjunto).
    facetas: Dict[str, int] = {}
    for item in itens:
        chave = (item.get("risco") or {}).get("nivel") or "sem_dados"
        facetas[chave] = facetas.get(chave, 0) + 1

    # O cadastro pesquisa também com `ou` (recall alto, precisão baixa): quando
    # nenhuma empresa casa com **todas** as palavras do pedido, é preciso dizê-lo
    # — senão o utilizador lê os maiores contratantes do país como resultado.
    avisos: List[str] = []
    if resolucao["parcial"]:
        avisos.append(
            f"Nenhuma empresa casou com «{texto}» (todas as palavras): os resultados são correspondências "
            "aproximadas, por relevância. Experimente só a parte distintiva do nome ou o NIF."
        )

    return {
        "query": texto,
        "total": resolucao["total"] or len(candidatos),
        "disponiveis": len(candidatos),
        "from": from_,
        "size": size,
        "ordenar": ordenar,
        "nivel": nivel,
        "detalhado": bool(detalhado),
        "parcial": resolucao["parcial"],
        "itens": itens,
        "avisos": avisos,
        "facetas": [
            {"nivel": nível["id"], "label": nível["label"], "cor": nível["cor"], "total": facetas.get(nível["id"], 0)}
            for nível in NIVEIS
        ],
        "cartao_modelo": cartao_modelo(),
    }


def sugestoes(q: str, *, size: int = 8) -> Dict[str, Any]:
    """Sugestões de empresas para a caixa de pesquisa (nome ou NIF).

    Usa a **mesma** resolução da pesquisa (por relevância), para que o que aparece
    nas sugestões seja o que a pesquisa encontra.
    """
    texto = str(q or "").strip()
    if len(texto) < 2:
        return {"itens": [], "query": texto}
    from api import contribuintes_service as contribuintes  # noqa: PLC0415

    resolucao = _resolver_candidatos(texto, size=max(1, min(int(size), 20)))
    return {
        "query": texto,
        "parcial": resolucao["parcial"],
        "itens": [
            {
                "nif": item.get("nif"),
                "nome": item.get("nome"),
                "tipo": item.get("tipo"),
                "tipo_label": contribuintes.TYPE_LABELS.get(item.get("tipo"), ""),
                "contratos": item.get("contratos") or 0,
                "fontes": item.get("fontes") or [],
            }
            for item in resolucao["itens"]
        ],
    }


# ---------------------------------------------------------------------------
# Comparação e grafos 360
# ---------------------------------------------------------------------------
def comparar(
    *,
    nifs: Optional[Sequence[str]] = None,
    nomes: Optional[Sequence[str]] = None,
    pais: str = padroes.PAIS_DEFAULT,
    ano_from: Optional[int] = None,
    ano_to: Optional[int] = None,
    detalhado: bool = True,
    max_empresas: int = 12,
    max_workers: int = 4,
) -> Dict[str, Any]:
    """Risco de várias empresas lado a lado, com cruzamentos e rede.

    Reutiliza `padroes.analise_empresas` para os cruzamentos e o grafo (que já
    lê a mesma cache das análises) e acrescenta o risco por empresa — a peça que
    faltava para se comparar «quem olhar primeiro» e não só «quem é maior».
    """
    caminho = [str(valor).strip() for valor in (nifs or []) if str(valor or "").strip()]
    pedidos = list(nomes or [])
    if len(caminho) + len(pedidos) > max_empresas:
        caminho, pedidos = caminho[:max_empresas], pedidos[: max(0, max_empresas - len(caminho))]
    if not caminho and not pedidos:
        return {"error": "Indique pelo menos uma empresa (NIF ou nome)."}

    base = padroes.analise_empresas(
        nifs=caminho or None,
        nomes=pedidos or None,
        pais=pais,
        ano_from=ano_from,
        ano_to=ano_to,
        max_empresas=max_empresas,
    )
    if base.get("error") and not base.get("empresas"):
        return base

    linhas = base.get("empresas") or []
    client = _client()
    pais_efetivo = pais_codigo(base.get("pais") or pais)
    spec = _spec(pais_efetivo)

    def _risco(linha: Dict[str, Any]) -> Dict[str, Any]:
        nif = str(linha.get("nif") or "")
        if not nif or client is None:
            return {"nif": nif, "risco": None}
        try:
            return {"nif": nif, **risco_empresa(nif=nif, pais=pais_efetivo, ano_from=ano_from, ano_to=ano_to, detalhado=detalhado, use_cache=True, es=client)}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Risco falhou para %s: %s", nif, exc)
            return {"nif": nif, "risco": None, "erro": str(exc)}

    if linhas:
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 6))) as pool:
            riscos = {item["nif"]: item for item in pool.map(_risco, linhas)}
    else:
        riscos = {}

    for linha in linhas:
        extra = riscos.get(str(linha.get("nif"))) or {}
        linha["risco"] = extra.get("risco")
        contagem = ((extra.get("risco") or {}).get("features") or {}).get("insolvencias")
        if isinstance(contagem, (int, float)):
            linha["insolvencias"] = int(contagem)
            # O `resumo.insolvente` da análise vem de uma consulta por `nifs`
            # (conta credores); aqui vale a contagem filtrada por papel.
            if isinstance(linha.get("resumo"), dict):
                linha["resumo"]["insolvente"] = bool(contagem)
        linha["erro"] = linha.get("erro") or extra.get("erro")

    ordenadas = sorted(
        linhas,
        key=lambda linha: -(((linha.get("risco") or {}).get("score")) if (linha.get("risco") or {}).get("score") is not None else -1),
    )
    scores = [(linha.get("risco") or {}).get("score") for linha in linhas]
    scores = [score for score in scores if score is not None]
    return {
        **base,
        "empresas": ordenadas,
        "ranking": [{"nif": linha.get("nif"), "nome": linha.get("nome"), "risco": linha.get("risco")} for linha in ordenadas],
        "risco_resumo": {
            "empresas": len(linhas),
            "com_risco": len(scores),
            "score_medio": _round(sum(scores) / len(scores), 1) if scores else None,
            "score_maximo": _round(max(scores), 1) if scores else None,
            "por_nivel": {
                nível["id"]: sum(1 for linha in linhas if ((linha.get("risco") or {}).get("nivel") == nível["id"]))
                for nível in NIVEIS
            },
            "criticas": [
                {"nif": linha.get("nif"), "nome": linha.get("nome"), "score": (linha.get("risco") or {}).get("score")}
                for linha in ordenadas
                if ((linha.get("risco") or {}).get("nivel") in {"muito_elevado", "critico"})
            ],
        },
        "cartao_modelo": cartao_modelo(),
    }


def grafo360(*, nif: str, pais: str = padroes.PAIS_DEFAULT, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Grafo analítico 360 de uma empresa (contratos, compradores, pessoas, CIRE).

    Separa **insolvências da empresa** (papel «Insolvente») das **menções em
    processos de terceiros** (credor, requerente, interveniente). A distinção é
    material: um banco aparece em milhares de processos por cobrar dívidas — o
    grafo mostra-os como relação, mas não são insolvências dele.
    """
    spec = _spec(pais)
    if spec is None:
        return {"error": f"país desconhecido: {pais}", "paises": list(padroes.COUNTRIES)}
    client = _client(es)
    dossier = padroes.entity_dossier(str(nif), pais=spec.key, es=client)
    if dossier.get("error"):
        return dossier
    grafo = dossier.get("grafo") or {}
    insolvencias = insolvencias_da_empresa(client, str(nif)) if client is not None else []
    mencionados = dossier.get("insolvencias") or []
    sinais = [sinal for sinal in (dossier.get("sinais") or []) if sinal.get("padrao") != "insolvencia"]
    if insolvencias:
        sinais.insert(
            0,
            {
                "padrao": "insolvencia",
                "detalhe": f"{len(insolvencias)} processo(s) em que a empresa é a insolvente",
                "total": len(insolvencias),
                "itens": len(insolvencias),
            },
        )
    return {
        "nif": dossier.get("nif"),
        "nome": dossier.get("nome"),
        "pais": dossier.get("pais"),
        "grafo": grafo,
        "lacos": dossier.get("lacos") or [],
        "resumo": dossier.get("resumo") or {},
        "sinais": sinais,
        "insolvencias": insolvencias,
        "processos_cire": mencionados,
        "cargos_sociais": dossier.get("cargos_sociais") or [],
        "intervenientes_processos": dossier.get("intervenientes_processos") or [],
        "noticias": dossier.get("noticias") or [],
        "contratos_total": dossier.get("contratos_total"),
        "nota": (
            f"A empresa aparece em {len(mencionados)} processo(s) do CIRE (como insolvente, requerente, "
            f"credor ou interveniente); destes, {len(insolvencias)} são processos em que é **a insolvente**. "
            "As ligações a processos no grafo usam todas as menções, para mostrar as relações."
            if mencionados
            else "A empresa não aparece em processos do CIRE."
        ),
    }


def clear_cache() -> int:
    """Limpa a cache de risco (útil depois de mexer nas regras/limiares)."""
    with _CACHE_LOCK:
        total = len(_CACHE)
        _CACHE.clear()
    return total


def meta() -> Dict[str, Any]:
    """Estado do módulo: cartão do modelo, fontes e dependências."""
    sklearn = padroes._sklearn()  # noqa: SLF001
    return {
        "modulo": "risco",
        "versao": MODELO_VERSAO,
        "cartao_modelo": cartao_modelo(),
        "metodos": METODOS,
        "ml": {
            "disponivel": sklearn is not None,
            "algoritmos": ["IsolationForest (anomalia)", "Gradient Boosting (sinal de aditivo, do módulo de padrões)"],
            "biblioteca": "scikit-learn" if sklearn is not None else None,
            "features": list(ML_FEATURES),
        },
        "fontes": [
            "Portal BASE (contratos PT)",
            "PLACSP (contratos ES)",
            "Finance Contribuintes (cadastro, contratos agregados)",
            "CIRE (insolvências)",
            "PessoasIQ (órgãos sociais)",
            "RSS + recolha + redes sociais (menções)",
        ],
        "cache": {"ttl_segundos": CACHE_TTL_SECONDS, "entradas": len(_CACHE)},
    }
