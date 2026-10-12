"""Decisão — os números que sustentam uma decisão sobre uma empresa.

A descoberta recolhe tudo (`api.descoberta_service`); este módulo transforma essa
recolha naquilo que se olha **antes de decidir**:

- **evolução** — valor e número de contratos por ano, e quantos adjudicantes
  novos apareceram (a carteira está a crescer, a estagnar ou a concentrar-se?);
- **concentração** — top de adjudicantes, curva de Pareto e índice HHI (de que
  depende a empresa?);
- **onde atua** — peso de cada CPV e o mix de procedimentos (concurso vs ajuste
  direto);
- **como contrata** — escalões de valor, preço face ao base, concorrência
  registada e prazos de publicação;
- **risco** — o cartão do módulo de risco, componente a componente;
- **perfil** — seis dimensões normalizadas de 0 a 100 (100 = melhor) para ler a
  empresa de uma vez;
- **pontos de atenção** — as regras que disparam, com o que verificar a seguir.

Tudo é cálculo determinístico sobre a recolha: nenhuma conclusão vem de um
modelo. As regras e os limiares estão no topo do módulo, para poderem ser
discutidos e afinados.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Limiares das regras (auditáveis: estão todos aqui)
# ---------------------------------------------------------------------------
#: Escalões de valor dos contratos (mesmos cortes do módulo de padrões).
ESCALOES: Tuple[Tuple[str, float, float], ...] = (
    ("≤ 20 mil €", 0.0, 20_000.0),
    ("20–100 mil €", 20_000.0, 100_000.0),
    ("100–500 mil €", 100_000.0, 500_000.0),
    ("500 mil–1 M €", 500_000.0, 1_000_000.0),
    ("> 1 M €", 1_000_000.0, math.inf),
)

#: Faixas do preço adjudicado face ao preço base (1,0 = sem desvio).
FAIXAS_PRECO: Tuple[Tuple[str, float, float], ...] = (
    ("< 0,95 (desconto)", 0.0, 0.95),
    ("0,95–1,05 (alinhado)", 0.95, 1.05),
    ("1,05–1,15", 1.05, 1.15),
    ("> 1,15 (acima do base)", 1.15, math.inf),
)

#: Faixas de concorrentes registados por contrato.
FAIXAS_CONCORRENCIA: Tuple[Tuple[str, float, float], ...] = (
    ("0 (sem registo)", 0.0, 1.0),
    ("1", 1.0, 2.0),
    ("2–3", 2.0, 4.0),
    ("4+", 4.0, math.inf),
)

#: Limiares usados nos pontos de atenção.
LIMIAR_CONCENTRACAO_ALERTA = 50.0
LIMIAR_CONCENTRACAO_AVISO = 35.0
LIMIAR_HHI_AVISO = 2_500.0
LIMIAR_AJUSTE_ALERTA = 60.0
LIMIAR_AJUSTE_AVISO = 40.0
LIMIAR_ADITIVOS_AVISO = 20.0
LIMIAR_PRECO_AVISO = 10.0
LIMIAR_PRECO_ALERTA = 15.0
LIMIAR_PUBLICACAO_DIAS = 180.0
#: Aditivo financeiro: valor efetivo acima do contratual (mesmo limiar do módulo
#: de padrões e do risco — `ratio_efetivo > 1,15`).
LIMIAR_ADITIVO = 1.15
#: Sinais do motor de padrões que as regras daqui já cobrem: não se repetem.
SINAIS_COBERTOS_POR_REGRA = frozenset(
    {"insolvencia", "aditivo_valor", "ajuste_direto_atipico", "desvio_preco_alto", "concentracao_fornecedor"}
)
LIMIAR_ADJUDICANTES_UNICO = 1
LIMIAR_QUEDA_VALOR = 0.5
LIMIAR_RISCO_ALERTA = 60.0

#: Tetos de desenho (as listas completas vivem nas secções da recolha).
MAX_BARRAS = 8
MAX_CURVA = 10

#: Ordem de severidade dos pontos de atenção.
SEVERIDADE = {"alerta": 0, "aviso": 1, "info": 2}

# Extremos das normalizações do perfil (a escala é logarítmica para não achatar
# a leitura: uma empresa de 1 M€ e outra de 100 M€ não estão no mesmo planeta).
PERFIL_VALOR_MAX = 200_000_000.0
PERFIL_ADJUDICANTES_MAX = 200.0
PERFIL_CONCORRENTES_MAX = 5.0
PERFIL_DIAS_MAX = 180.0
PERFIL_DESVIO_PRECO = 0.15


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------
def _numero(valor: Any) -> Optional[float]:
    try:
        convertido = float(valor)
    except (TypeError, ValueError):
        return None
    return convertido if math.isfinite(convertido) else None


def _soma(valores: Iterable[float]) -> float:
    return round(sum(valores), 2)


def _mediana(valores: Sequence[float]) -> Optional[float]:
    limpos = sorted(valor for valor in valores if valor is not None and math.isfinite(valor))
    if not limpos:
        return None
    meio = len(limpos) // 2
    if len(limpos) % 2:
        return round(limpos[meio], 4)
    return round((limpos[meio - 1] + limpos[meio]) / 2, 4)


def _quota(parte: float, total: float) -> float:
    return round((parte / total) * 100, 2) if total else 0.0


def _contratos(recolha: Dict[str, Any]) -> List[Dict[str, Any]]:
    secao = (recolha.get("secoes") or {}).get("contratos") or {}
    return [item for item in (secao.get("contratos") or []) if isinstance(item, dict)]


def _adjudicantes(contratos: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    agregado: Dict[str, Dict[str, Any]] = {}
    for contrato in contratos:
        nome = str(contrato.get("adjudicante") or "").strip()
        nif = str(contrato.get("adjudicante_nif") or "").strip()
        chave = nif or nome
        if not chave:
            continue
        entrada = agregado.setdefault(chave, {"nif": nif, "nome": nome or chave, "contratos": 0, "valor": 0.0})
        entrada["contratos"] += 1
        entrada["valor"] += _numero(contrato.get("valor")) or 0.0
        if nome and entrada["nome"] == chave:
            entrada["nome"] = nome
    for entrada in agregado.values():
        entrada["valor"] = round(entrada["valor"], 2)
    return agregado


def _euros(valor: Any) -> str:
    """Valor em euros legível (espaço fino como separador de milhares)."""
    numero = _numero(valor) or 0.0
    return f"{numero:,.0f}".replace(",", " ")


def _buckets(
    pares: Sequence[Tuple[float, float]], faixas: Sequence[Tuple[str, float, float]]
) -> List[Dict[str, Any]]:
    """Distribui pares `(chave, valor)` pelas faixas e conta contratos e valor."""
    itens = [{"faixa": rotulo, "contratos": 0, "valor": 0.0, "quota": 0.0} for rotulo, _, _ in faixas]
    total = len(pares)
    for chave, valor in pares:
        for indice, (_, minimo, maximo) in enumerate(faixas):
            if minimo <= chave < maximo:
                itens[indice]["contratos"] += 1
                itens[indice]["valor"] += valor
                break
    for item in itens:
        item["valor"] = round(item["valor"], 2)
        item["quota"] = _quota(item["contratos"], total)
    return itens


# ---------------------------------------------------------------------------
# Blocos do painel de decisão
# ---------------------------------------------------------------------------
def evolucao(contratos: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Valor, contratos e adjudicantes por ano (a carteira ao longo do tempo)."""
    por_ano: Dict[int, Dict[str, Any]] = {}
    vistos_anos: Dict[int, set] = {}
    for contrato in contratos:
        ano = _numero(contrato.get("ano"))
        if ano is None:
            continue
        ano = int(ano)
        entrada = por_ano.setdefault(ano, {"ano": ano, "contratos": 0, "valor": 0.0, "_adjudicantes": set()})
        entrada["contratos"] += 1
        entrada["valor"] += _numero(contrato.get("valor")) or 0.0
        chave = str(contrato.get("adjudicante_nif") or contrato.get("adjudicante") or "").strip()
        if chave:
            entrada["_adjudicantes"].add(chave)
        vistos_anos.setdefault(ano, set()).add(chave)

    anteriores: set = set()
    linhas: List[Dict[str, Any]] = []
    for ano in sorted(por_ano):
        entrada = por_ano[ano]
        atuais = entrada.pop("_adjudicantes")
        linhas.append(
            {
                "ano": ano,
                "contratos": entrada["contratos"],
                "valor": round(entrada["valor"], 2),
                "adjudicantes": len(atuais),
                "novos_adjudicantes": len(atuais - anteriores),
            }
        )
        anteriores |= atuais
    return linhas


def concentracao(contratos: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Top de adjudicantes, curva de Pareto e HHI (dependência de quem compra)."""
    agregado = _adjudicantes(contratos)
    total = sum(item["valor"] for item in agregado.values())
    ordenados = sorted(agregado.items(), key=lambda item: -item[1]["valor"])

    top = [
        {**dados, "quota": _quota(dados["valor"], total)}
        for _, dados in ordenados[:MAX_BARRAS]
    ]

    curva: List[Dict[str, Any]] = []
    acumulado = 0.0
    for posicao, (_, dados) in enumerate(ordenados[:MAX_CURVA], start=1):
        acumulado += dados["valor"]
        curva.append(
            {
                "ordem": posicao,
                "nome": dados["nome"],
                "valor": dados["valor"],
                "quota": _quota(dados["valor"], total),
                "quota_acumulada": _quota(acumulado, total),
            }
        )

    hhi = round(sum((_quota(item["valor"], total)) ** 2 for item in agregado.values()), 1) if total else None
    quotas = [item["quota"] for item in top]
    return {
        "adjudicantes": len(agregado),
        "valor_total": _soma(item["valor"] for item in agregado.values()),
        "top": top,
        "curva": curva,
        "hhi": hhi,
        "top1": round(quotas[0], 2) if quotas else None,
        "top3": round(sum(quotas[:3]), 2) if quotas else None,
    }


def cpv_mix(contratos: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Peso de cada classificação CPV (onde está o valor da empresa)."""
    agregado: Dict[str, Dict[str, Any]] = {}
    for contrato in contratos:
        codigo = str(contrato.get("cpv") or "").strip()
        if not codigo:
            continue
        entrada = agregado.setdefault(
            codigo,
            {"cpv": codigo, "descricao": str(contrato.get("cpv_desc") or ""), "contratos": 0, "valor": 0.0},
        )
        entrada["contratos"] += 1
        entrada["valor"] += _numero(contrato.get("valor")) or 0.0
        if not entrada["descricao"] and contrato.get("cpv_desc"):
            entrada["descricao"] = str(contrato["cpv_desc"])
    total = sum(item["valor"] for item in agregado.values())
    linhas = [
        {**dados, "valor": round(dados["valor"], 2), "quota": _quota(dados["valor"], total)}
        for dados in agregado.values()
    ]
    linhas.sort(key=lambda item: -item["valor"])
    return linhas[:MAX_BARRAS]


def procedimentos(contratos: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Mix de procedimento: concurso, ajuste direto e o que a plataforma não diz."""
    agregado: Dict[str, Dict[str, Any]] = {}
    for contrato in contratos:
        rotulo = str(contrato.get("procedimento") or "Não especificado").strip() or "Não especificado"
        entrada = agregado.setdefault(rotulo, {"procedimento": rotulo, "contratos": 0, "valor": 0.0})
        entrada["contratos"] += 1
        entrada["valor"] += _numero(contrato.get("valor")) or 0.0
    total_contratos = len(contratos)
    total_valor = sum(item["valor"] for item in agregado.values())
    itens = [
        {
            **dados,
            "valor": round(dados["valor"], 2),
            "quota": _quota(dados["contratos"], total_contratos),
            "quota_valor": _quota(dados["valor"], total_valor),
            "ajuste_direto": "ajuste" in dados["procedimento"].lower()
            or "direct" in dados["procedimento"].lower(),
        }
        for dados in agregado.values()
    ]
    itens.sort(key=lambda item: -item["contratos"])
    diretos = [contrato for contrato in contratos if contrato.get("ajuste_direto")]
    return {
        "taxa_ajuste_direto": round(len(diretos) / total_contratos, 4) if total_contratos else None,
        "itens": itens[:MAX_BARRAS],
    }


def escaloes(contratos: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Distribuição dos contratos por escalão de valor (tamanho típico)."""
    valores = [_numero(contrato.get("valor")) or 0.0 for contrato in contratos]
    itens = []
    total = len(valores)
    for rotulo, minimo, maximo in ESCALOES:
        dentro = [valor for valor in valores if minimo <= valor < maximo]
        itens.append(
            {
                "escalao": rotulo,
                "contratos": len(dentro),
                "valor": _soma(dentro),
                "quota": _quota(len(dentro), total),
            }
        )
    return itens


def precos(contratos: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Preço adjudicado face ao base (desconto, alinhado, acima) e aditivos."""
    pares: List[Tuple[float, float]] = []
    for contrato in contratos:
        ratio = _numero(contrato.get("ratio_base"))
        if ratio is not None:
            pares.append((ratio, _numero(contrato.get("valor")) or 0.0))
    efetivos = [valor for valor in (_numero(contrato.get("ratio_efetivo")) for contrato in contratos) if valor is not None]
    aditivos = [valor for valor in efetivos if valor > LIMIAR_ADITIVO]
    return {
        "mediana": _mediana([chave for chave, _ in pares]),
        "itens": _buckets(pares, FAIXAS_PRECO),
        "com_ratio": len(pares),
        "taxa_aditivo": round(len(aditivos) / len(efetivos), 4) if efetivos else None,
        "mediana_efetiva": _mediana(efetivos),
    }


def concorrencia(contratos: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Concorrência registada por contrato (sem concorrentes é um sinal forte)."""
    pares: List[Tuple[float, float]] = []
    for contrato in contratos:
        concorrentes = _numero(contrato.get("n_concorrentes"))
        if concorrentes is not None:
            pares.append((concorrentes, _numero(contrato.get("valor")) or 0.0))
    valores = [chave for chave, _ in pares]
    return {
        "mediana": _mediana(valores),
        "media": round(sum(valores) / len(valores), 2) if valores else None,
        "itens": _buckets(pares, FAIXAS_CONCORRENCIA),
        "com_dados": len(valores),
    }


def prazos(contratos: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Prazos medianos (dias) do procedimento: até ficar público e entre atos.

    `dias_decisao` é medido entre a adjudicação e a publicação (é negativo quando
    a adjudicação precede a publicação, que é o caso normal), por isso conta-se o
    **valor absoluto**: o que interessa a quem decide é quantos dias a contratação
    demorou a ficar visível.
    """
    decisao = sorted(
        abs(valor) for valor in (_numero(contrato.get("dias_decisao")) for contrato in contratos) if valor is not None
    )
    assinatura = [_numero(contrato.get("dias_assinatura")) for contrato in contratos]
    publicacao = [_numero(contrato.get("dias_publicacao")) for contrato in contratos]
    return {
        "itens": [
            {"fase": "Decisão → publicação", "dias": _mediana(decisao), "campo": "dias_decisao"},
            {"fase": "Adjudicação → assinatura", "dias": _mediana(assinatura), "campo": "dias_assinatura"},
            {"fase": "Assinatura → publicação", "dias": _mediana(publicacao), "campo": "dias_publicacao"},
        ],
        "mediana_decisao_publicacao": _mediana(decisao),
        "mediana_publicacao": _mediana(publicacao),
        "com_dados": len(decisao),
    }


def perfil(dados: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Seis dimensões de 0 a 100 (100 = melhor) para ler a empresa de uma vez.

    A escala é uma heurística auditável: o detalhe mostra sempre o número cru que
    a originou, para a barra nunca substituir o dado.
    """

    def escala(valor: Optional[float], maximo: float) -> Optional[float]:
        if valor is None or valor <= 0:
            return 0.0
        return round(min(1.0, math.log10(1 + valor) / math.log10(1 + maximo)) * 100, 1)

    def linear(valor: Optional[float], maximo: float) -> Optional[float]:
        if valor is None:
            return None
        return round(max(0.0, min(1.0, valor / maximo)) * 100, 1)

    risco = dados.get("risco") or {}
    resumo = dados.get("resumo") or {}
    concentracao_dados = dados.get("concentracao") or {}
    precos_dados = dados.get("precos") or {}
    prazos_dados = dados.get("prazos") or {}
    concorrencia_dados = dados.get("concorrencia") or {}
    procedimento_dados = dados.get("procedimento") or {}

    taxa_ajuste = procedimento_dados.get("taxa_ajuste_direto")
    mediana_publicacao = prazos_dados.get("mediana_decisao_publicacao")
    mediana_preco = precos_dados.get("mediana")

    dimensoes = [
        {
            "id": "escala",
            "label": "Escala",
            "valor": escala(resumo.get("valor_total"), PERFIL_VALOR_MAX),
            "detalhe": f"{_euros(resumo.get('valor_total'))} € em contratos lidos",
        },
        {
            "id": "diversificacao",
            "label": "Diversificação",
            "valor": escala(concentracao_dados.get("adjudicantes"), PERFIL_ADJUDICANTES_MAX),
            "detalhe": f"{concentracao_dados.get('adjudicantes') or 0} adjudicantes distintos",
        },
        {
            "id": "concorrencia",
            "label": "Concorrência",
            "valor": linear(concorrencia_dados.get("mediana"), PERFIL_CONCORRENTES_MAX),
            "detalhe": f"mediana de {concorrencia_dados.get('mediana')} concorrente(s) por contrato",
        },
        {
            "id": "transparencia",
            "label": "Transparência",
            "valor": round((1 - taxa_ajuste) * 100, 1) if taxa_ajuste is not None else None,
            "detalhe": f"{round((taxa_ajuste or 0) * 100)}% dos contratos por ajuste direto",
        },
        {
            "id": "celeridade",
            "label": "Rapidez",
            "valor": round((1 - min(1.0, mediana_publicacao / PERFIL_DIAS_MAX)) * 100, 1)
            if mediana_publicacao is not None
            else None,
            "detalhe": f"decisão a publicação em {mediana_publicacao} dia(s)"
            if mediana_publicacao is not None
            else "sem datas de publicação",
        },
        {
            "id": "preco",
            "label": "Preço alinhado",
            "valor": round((1 - min(1.0, abs(mediana_preco - 1.0) / PERFIL_DESVIO_PRECO)) * 100, 1)
            if mediana_preco is not None
            else None,
            "detalhe": f"adjudicado/base com mediana {mediana_preco}"
            if mediana_preco is not None
            else "sem preço base comparável",
        },
    ]
    # O risco entra como dimensão invertida (100 = risco baixo), para o radar
    # se ler todo na mesma direção: quanto mais cheio, melhor.
    if risco.get("score") is not None:
        dimensoes.append(
            {
                "id": "risco",
                "label": "Risco contido",
                "valor": round(max(0.0, 100 - float(risco["score"])), 1),
                "detalhe": f"risco {risco.get('nivel_label') or risco.get('nivel')} ({risco.get('score')}/100)",
            }
        )
    return dimensoes


def pontos_de_atencao(dados: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Regras que disparam, ordenadas por severidade — o que verificar a seguir."""
    itens: List[Dict[str, Any]] = []

    def juntar(severidade: str, titulo: str, detalhe: str, verificar: str) -> None:
        itens.append({"severidade": severidade, "titulo": titulo, "detalhe": detalhe, "verificar": verificar})

    resumo = dados.get("resumo") or {}
    concentracao_dados = dados.get("concentracao") or {}
    precos_dados = dados.get("precos") or {}
    concorrencia_dados = dados.get("concorrencia") or {}
    prazos_dados = dados.get("prazos") or {}
    risco = dados.get("risco") or {}
    evolucao_dados = dados.get("evolucao") or []

    contratos = resumo.get("contratos") or 0
    if not contratos:
        juntar(
            "info",
            "Sem contratos lidos",
            "Não há contratos desta empresa na amostra recolhida — a leitura de contratação não se aplica.",
            "Confirmar o NIF e, se for adjudicante, usar a vista por papel de adjudicante.",
        )

    insolvencias = resumo.get("insolvencias") or 0
    if insolvencias:
        juntar(
            "alerta",
            f"{insolvencias} processo(s) no CIRE",
            "Há processos de insolvência, PER, PEAP ou PEVE publicados no CITIUS.",
            "Ler o processo mais recente e confirmar a situação atual antes de contratar ou pagar.",
        )

    top1 = concentracao_dados.get("top1")
    if top1 is not None and top1 >= LIMIAR_CONCENTRACAO_ALERTA:
        juntar(
            "alerta",
            f"Concentração de {top1}% num só comprador",
            "Mais de metade do valor vem de um único adjudicante: a carteira depende dele.",
            "Identificar o contrato-quadro e o que acontece à empresa se essa entidade parar de comprar.",
        )
    elif top1 is not None and top1 >= LIMIAR_CONCENTRACAO_AVISO:
        juntar(
            "aviso",
            f"Maior comprador com {top1}% do valor",
            "A carteira está inclinada para um comprador.",
            "Ver se há outros compradores a crescer nos últimos anos.",
        )

    hhi = concentracao_dados.get("hhi")
    if hhi is not None and hhi >= LIMIAR_HHI_AVISO:
        juntar(
            "aviso",
            f"HHI de {hhi} (carteira concentrada)",
            "O índice de concentração de Herfindahl-Schwartz está acima do limiar de carteira concentrada.",
            "Comparar com os pares do mesmo CPV para saber se é o setor ou a empresa.",
        )

    ajuste = resumo.get("taxa_ajuste_direto")
    if ajuste is not None and ajuste * 100 >= LIMIAR_AJUSTE_ALERTA:
        juntar(
            "alerta",
            f"{round(ajuste * 100)}% dos contratos por ajuste direto",
            "O ajuste direto dispensa concurso: é o principal sinal de transparência.",
            "Olhar os contratos de maior valor por ajuste direto e o respetivo fundamento.",
        )
    elif ajuste is not None and ajuste * 100 >= LIMIAR_AJUSTE_AVISO:
        juntar(
            "aviso",
            f"{round(ajuste * 100)}% dos contratos por ajuste direto",
            "Peso de ajuste direto acima do habitual.",
            "Comparar com a mediana do CPV no módulo de padrões.",
        )

    taxa_aditivo = precos_dados.get("taxa_aditivo")
    if taxa_aditivo is not None and taxa_aditivo * 100 >= LIMIAR_ADITIVOS_AVISO:
        juntar(
            "aviso",
            f"{round(taxa_aditivo * 100)}% dos contratos com valor efetivo acima do contratual",
            "Trabalho a mais pago por aditivo: muda o valor final face ao adjudicado.",
            "Ver a lista de contratos com ratio efetivo acima de 1,15.",
        )

    mediana_preco = precos_dados.get("mediana")
    if mediana_preco is not None and (mediana_preco - 1) * 100 >= LIMIAR_PRECO_ALERTA:
        juntar(
            "alerta",
            f"Adjudicado {round((mediana_preco - 1) * 100)}% acima do preço base",
            "A mediana do preço adjudicado está acima do preço base dos procedimentos.",
            "Rever os procedimentos com preço base e comparar com o mercado do CPV.",
        )
    elif mediana_preco is not None and (mediana_preco - 1) * 100 >= LIMIAR_PRECO_AVISO:
        juntar(
            "aviso",
            f"Adjudicado {round((mediana_preco - 1) * 100)}% acima do preço base",
            "Desvio positivo face ao base, mas dentro do que se vê no mercado.",
            "Confirmar se o desvio está nos contratos de maior valor.",
        )

    mediana_concorrentes = concorrencia_dados.get("mediana")
    if mediana_concorrentes is not None and mediana_concorrentes < 1:
        juntar(
            "aviso",
            "Sem concorrentes registados na maioria dos contratos",
            "A plataforma não regista concorrência: pode ser ajuste direto ou falta de dados.",
            "Confirmar no portal base os contratos com 0 concorrentes.",
        )

    mediana_publicacao = prazos_dados.get("mediana_decisao_publicacao")
    if mediana_publicacao is not None and mediana_publicacao > LIMIAR_PUBLICACAO_DIAS:
        juntar(
            "aviso",
            f"{round(mediana_publicacao)} dias entre a decisão e a publicação",
            "A contratação demora a ficar visível: a transparência chega tarde.",
            "Ver os contratos com maior atraso entre adjudicação e publicação.",
        )

    adjudicantes = concentracao_dados.get("adjudicantes")
    if adjudicantes is not None and adjudicantes <= LIMIAR_ADJUDICANTES_UNICO and contratos >= 5:
        juntar(
            "alerta",
            "Um único adjudicante para todos os contratos lidos",
            "Toda a contratação lida vem de um comprador: não há carteira diversificada.",
            "Procurar contratos noutros anos e noutros papéis antes de tirar conclusões.",
        )

    # Tendência: comparar o último ano com a média dos anteriores.
    if len(evolucao_dados) >= 3:
        valores = [linha.get("valor") or 0.0 for linha in evolucao_dados]
        ultimo = valores[-1]
        anteriores = valores[:-1]
        media = sum(anteriores) / len(anteriores) if anteriores else 0.0
        if media > 0 and ultimo / media < LIMIAR_QUEDA_VALOR:
            juntar(
                "aviso",
                f"Valor de {evolucao_dados[-1]['ano']} caiu para {round(ultimo / media * 100)}% da média anterior",
                "Queda abrupta face aos anos anteriores — pode ser o ano a meio ou a perda de um comprador.",
                "Confirmar se o ano está completo e que comprador deixou de contratar.",
            )

    if risco.get("score") is not None and float(risco["score"]) >= LIMIAR_RISCO_ALERTA:
        juntar(
            "alerta",
            f"Risco {risco.get('nivel_label') or risco.get('nivel')} ({risco['score']}/100)",
            "O motor de risco coloca a empresa na faixa alta; os componentes explicam porquê.",
            "Abrir o cartão de risco e atacar os componentes com mais contributo.",
        )

    for sinal in ((dados.get("sinais") or [])[:6]):
        padrao = str(sinal.get("padrao") or "sinal")
        if padrao in SINAIS_COBERTOS_POR_REGRA:
            # Já existe uma regra daqui com o mesmo sinal: não se repete.
            continue
        juntar(
            "info",
            padrao,
            str(sinal.get("detalhe") or ""),
            "Sinal do motor de padrões; confirmar contrato a contrato.",
        )

    itens.sort(key=lambda item: (SEVERIDADE.get(item["severidade"], 9), item["titulo"]))
    return itens


def leitura(dados: Dict[str, Any]) -> str:
    """Frase de síntese (determinística) do que os números dizem para decidir."""
    resumo = dados.get("resumo") or {}
    concentracao_dados = dados.get("concentracao") or {}
    risco = dados.get("risco") or {}
    contratos = resumo.get("contratos") or 0
    if not contratos:
        return (
            "Sem contratos lidos na amostra: a leitura de contratação não se aplica. "
            "Usar as restantes secções (cadastro, registos, insolvências) para decidir."
        )

    partes = [
        f"{contratos} contratos lidos, {_euros(resumo.get('valor_total'))} €",
        f"{concentracao_dados.get('adjudicantes') or 0} adjudicantes",
    ]
    top1 = concentracao_dados.get("top1")
    if top1 is not None:
        partes.append(f"maior comprador com {top1}% do valor")
    ajuste = resumo.get("taxa_ajuste_direto")
    if ajuste is not None:
        partes.append(f"{round(ajuste * 100)}% por ajuste direto")
    if risco.get("nivel_label"):
        partes.append(f"risco {risco['nivel_label']} ({risco.get('score')}/100)")

    atencao = dados.get("atencao") or []
    alertas = [item for item in atencao if item["severidade"] == "alerta"]
    conclusao = (
        f"{len(alertas)} ponto(s) de atenção graves a resolver primeiro."
        if alertas
        else "Sem alertas graves: a decisão pode assentar nos números acima."
    )
    return f"{'; '.join(partes)}. {conclusao}"


def decisao(recolha: Dict[str, Any]) -> Dict[str, Any]:
    """Payload do painel de decisão, calculado só a partir da recolha."""
    contratos = _contratos(recolha)
    risco_secao = ((recolha.get("secoes") or {}).get("risco") or {}).get("risco") or {}
    kpis = recolha.get("kpis") or {}

    componentes_risco = [
        {
            "id": item.get("id"),
            "label": item.get("label"),
            "pontos": item.get("pontos"),
            "peso": item.get("peso_efetivo", item.get("peso")),
            "contributo": item.get("contributo"),
            "disponivel": bool(item.get("disponivel")),
            "unidade": item.get("unidade"),
            "evidencia": item.get("evidencia") or [],
        }
        for item in (risco_secao.get("componentes") or [])
    ]

    concentracao_dados = concentracao(contratos)
    precos_dados = precos(contratos)
    concorrencia_dados = concorrencia(contratos)
    prazos_dados = prazos(contratos)
    evolucao_dados = evolucao(contratos)
    procedimento_dados = procedimentos(contratos)

    dados: Dict[str, Any] = {
        "nif": str(recolha.get("nif") or ""),
        "nome": str(recolha.get("nome") or ""),
        "resumo": {
            "contratos": int(kpis.get("contratos") or len(contratos)),
            "contratos_lidos": len(contratos),
            "valor_total": kpis.get("valor_total") or concentracao_dados["valor_total"],
            "adjudicantes": concentracao_dados["adjudicantes"],
            "anos": [linha["ano"] for linha in evolucao_dados],
            "taxa_ajuste_direto": procedimento_dados["taxa_ajuste_direto"],
            "hhi": concentracao_dados["hhi"],
            "insolvencias": kpis.get("insolvencias") or 0,
            "confianca_risco": risco_secao.get("confianca"),
            "cobertura_risco": risco_secao.get("cobertura"),
        },
        "evolucao": evolucao_dados,
        "concentracao": concentracao_dados,
        "cpv": cpv_mix(contratos),
        "procedimento": procedimento_dados,
        "escaloes": escaloes(contratos),
        "precos": precos_dados,
        "concorrencia": concorrencia_dados,
        "prazos": prazos_dados,
        "risco": {
            "score": risco_secao.get("score"),
            "nivel": risco_secao.get("nivel"),
            "nivel_label": risco_secao.get("nivel_label"),
            "cor": risco_secao.get("cor"),
            "confianca": risco_secao.get("confianca"),
            "cobertura": risco_secao.get("cobertura"),
            "metodo_label": risco_secao.get("metodo_label"),
            "componentes": componentes_risco,
            "fatores": risco_secao.get("fatores") or [],
        },
        "sinais": kpis.get("sinais") or [],
    }
    dados["perfil"] = perfil(dados)
    dados["atencao"] = pontos_de_atencao(dados)
    dados["leitura"] = leitura(dados)
    return dados


__all__ = ["decisao", "concentracao", "escaloes", "evolucao", "perfil", "pontos_de_atencao", "precos"]
