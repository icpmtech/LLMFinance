"""Análise de risco das entidades do Portal da Transparência da ERC.

O portal só publica o que as próprias entidades entregam ao regulador: não tem
incumprimentos, processos judiciais nem ratings externos. Por isso a análise
separa o que consegue medir e não mistura as duas coisas:

- **Transparência** (0-100) — quanto, com que completude e com que actualidade a
  entidade publica;
- **Crédito** (0-100) — o que os números publicados dizem sobre a saúde
  financeira (autonomia, endividamento, resultados, escala);
- **Risco** (0-100, quanto *maior* pior) — falta de solidez financeira somada à
  opacidade, resumida na banda ``baixo``…``critico``.

Cada score devolve os indicadores que o compõem, com pontos e máximo, para o
resultado ser auditável em vez de um número opaco. Nada disto é um rating de
crédito profissional: é uma leitura dos dados autodeclarados ao regulador, sem
verificação independente.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional, Tuple

FONTE = "erc-transparencia"

#: Campos do exercício cuja presença mede a completude da publicação.
CAMPOS_BALANCO = (
    "ativo_total",
    "passivo_total",
    "capital_proprio",
    "rendimentos_totais",
    "resultados_liquidos",
)

AVISO = (
    "Análise calculada apenas com os dados autodeclarados ao Portal da Transparência da ERC "
    "(não inclui incumprimentos, processos, garantias ou ratings externos) e sem verificação "
    "independente das contas."
)

_LIMIARES_TRANSPARENCIA = ((75, "alta"), (50, "media"), (25, "baixa"))
_LIMIARES_CREDITO = ((80, "A"), (65, "B"), (50, "C"), (35, "D"))
_LIMIARES_RISCO = ((75, "critico"), (50, "elevado"), (25, "moderado"))


def _numero(valor: Any) -> Optional[float]:
    """Converte para número aceitando ``None`` e texto já formatado."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace(" ", "").replace("€", "")
    if not texto:
        return None
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    else:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _racio(numerador: Optional[float], denominador: Optional[float]) -> Optional[float]:
    if numerador is None or not denominador:
        return None
    return numerador / denominador


def _faixa(valor: Optional[float], limiares: Tuple[Tuple[float, str], ...], resto: str) -> str:
    if valor is None:
        return "sem dados"
    for limite, nome in limiares:
        if valor >= limite:
            return nome
    return resto


# ---------------------------------------------------------------------------
# Série financeira: rácios por exercício e resumo do último publicado
# ---------------------------------------------------------------------------

def enriquecer_serie(serie: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Ordena a série (mais recente primeiro) e acrescenta os rácios de cada ano.

    O crescimento dos rendimentos é calculado contra o exercício publicado
    imediatamente anterior — que pode não ser o ano civil anterior, porque há
    entidades que falham anos.
    """
    limpa: List[Dict[str, Any]] = []
    for item in serie or []:
        if not isinstance(item, dict):
            continue
        try:
            ano = int(item.get("ano"))
        except (TypeError, ValueError):
            continue
        limpa.append({**item, "ano": ano})
    limpa.sort(key=lambda d: d["ano"], reverse=True)

    for i, item in enumerate(limpa):
        ativo = _numero(item.get("ativo_total"))
        item["autonomia_financeira"] = _racio(_numero(item.get("capital_proprio")), ativo)
        item["endividamento"] = _racio(_numero(item.get("passivo_total")) or _numero(item.get("passivos_totais")), ativo)
        item["margem_liquida"] = _racio(_numero(item.get("resultados_liquidos")), _numero(item.get("rendimentos_totais")))
        anterior = limpa[i + 1] if i + 1 < len(limpa) else None
        rendimentos = _numero(item.get("rendimentos_totais"))
        rendimentos_ano_anterior = _numero(anterior.get("rendimentos_totais")) if anterior else None
        if rendimentos is not None and rendimentos_ano_anterior:
            item["crescimento_rendimentos"] = (rendimentos - rendimentos_ano_anterior) / abs(rendimentos_ano_anterior)
            item["ano_comparacao"] = anterior["ano"]
        else:
            item["crescimento_rendimentos"] = None
            item["ano_comparacao"] = None
    return limpa


def resumo_financeiro(serie: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Indicadores de topo da série (para ordenação e agregação no índice)."""
    limpa = enriquecer_serie(serie)
    if not limpa:
        return {
            "n_anos_financeiro": 0,
            "primeiro_ano_financeiro": None,
            "ultimo_ano_financeiro": None,
            "ultimo_ativo": None,
            "ultimo_passivo": None,
            "ultimo_capital_proprio": None,
            "ultimo_rendimentos": None,
            "ultimo_resultados": None,
            "ultimo_autonomia": None,
            "ultimo_endividamento": None,
            "anos_resultados_positivos": 0,
            "anos_resultados_negativos": 0,
            "confidencialidade": False,
            "financeiro_atualizado_em": None,
        }
    ultimo = limpa[0]
    positivos = sum(1 for a in limpa if (_numero(a.get("resultados_liquidos")) or 0) > 0)
    negativos = sum(1 for a in limpa if (_numero(a.get("resultados_liquidos")) or 0) < 0)
    return {
        "n_anos_financeiro": len(limpa),
        "primeiro_ano_financeiro": limpa[-1]["ano"],
        "ultimo_ano_financeiro": ultimo["ano"],
        "ultimo_ativo": _numero(ultimo.get("ativo_total")),
        "ultimo_passivo": _numero(ultimo.get("passivo_total")) or _numero(ultimo.get("passivos_totais")),
        "ultimo_capital_proprio": _numero(ultimo.get("capital_proprio")),
        "ultimo_rendimentos": _numero(ultimo.get("rendimentos_totais")),
        "ultimo_resultados": _numero(ultimo.get("resultados_liquidos")),
        "ultimo_autonomia": ultimo.get("autonomia_financeira"),
        "ultimo_endividamento": ultimo.get("endividamento"),
        "ultimo_crescimento_rendimentos": ultimo.get("crescimento_rendimentos"),
        "anos_resultados_positivos": positivos,
        "anos_resultados_negativos": negativos,
        "confidencialidade": any(bool(a.get("confidencialidade")) for a in limpa),
        "financeiro_atualizado_em": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------

def _indicadores_transparencia(entidade: Dict[str, Any], serie: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ano_atual = _dt.date.today().year
    ultimo = serie[0] if serie else None
    contabilidade = entidade.get("contabilidade_organizada")
    if contabilidade is True:
        pontos_contabilidade = 10
    elif contabilidade is False:
        pontos_contabilidade = 0
    else:
        pontos_contabilidade = 3

    if not serie:
        pontos_anos = 0
    elif len(serie) == 1:
        pontos_anos = 5
    elif len(serie) == 2:
        pontos_anos = 8
    elif len(serie) == 3:
        pontos_anos = 11
    elif len(serie) == 4:
        pontos_anos = 13
    else:
        pontos_anos = 15

    if ultimo:
        distancia = max(0, (ano_atual - 1) - int(ultimo["ano"]))
        pontos_atualidade = (10, 8, 5, 3)[distancia] if distancia < 4 else 1
        presentes = sum(1 for campo in CAMPOS_BALANCO if _numero(ultimo.get(campo)) is not None)
        pontos_completude = round(10 * presentes / len(CAMPOS_BALANCO), 1)
    else:
        distancia = None
        pontos_atualidade = 0
        pontos_completude = 0
        presentes = 0

    n_ocs = int(entidade.get("n_ocs") or 0)
    if n_ocs:
        pontos_ocs = 10
    elif entidade.get("detem_ocs") is False:
        pontos_ocs = 6
    else:
        pontos_ocs = 0

    n_pessoas = int(entidade.get("n_pessoas") or 0)
    n_estrutura = int(entidade.get("n_detentores") or 0) + int(entidade.get("n_detidas") or 0)
    return [
        {"chave": "contabilidade_organizada", "nome": "Contabilidade organizada", "maximo": 10,
         "valor": contabilidade, "pontos": pontos_contabilidade},
        {"chave": "financeiro_publicado", "nome": "Publica dados financeiros", "maximo": 25,
         "valor": len(serie) > 0, "pontos": 25 if serie else 0},
        {"chave": "exercicios_publicados", "nome": "Exercícios publicados", "maximo": 15,
         "valor": len(serie), "pontos": pontos_anos},
        {"chave": "atualidade", "nome": "Actualidade do último exercício", "maximo": 10,
         "valor": ultimo["ano"] if ultimo else None, "pontos": pontos_atualidade},
        {"chave": "completude_balanco", "nome": "Completude do balanço", "maximo": 10,
         "valor": f"{presentes}/{len(CAMPOS_BALANCO)} campos", "pontos": pontos_completude},
        {"chave": "ocs_declarados", "nome": "OCS declarados", "maximo": 10,
         "valor": n_ocs, "pontos": pontos_ocs},
        {"chave": "orgaos_sociais", "nome": "Órgãos sociais publicados", "maximo": 10,
         "valor": n_pessoas, "pontos": 10 if n_pessoas else 0},
        {"chave": "estrutura_capital", "nome": "Estrutura de capital publicada", "maximo": 5,
         "valor": n_estrutura, "pontos": 5 if n_estrutura else 0},
        {"chave": "capital_social", "nome": "Capital social declarado", "maximo": 5,
         "valor": entidade.get("capital_social_eur") is not None or bool(entidade.get("capital_social")),
         "pontos": 5 if (entidade.get("capital_social_eur") is not None or entidade.get("capital_social")) else 0},
    ]


def _indicadores_credito(resumo: Dict[str, Any], serie: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ultimo_resultado = resumo.get("ultimo_resultados")
    if ultimo_resultado is None:
        pontos_resultado = 0
    elif ultimo_resultado > 0:
        pontos_resultado = 25
    elif ultimo_resultado == 0:
        pontos_resultado = 10
    else:
        pontos_resultado = 0

    anos_com_resultado = resumo["anos_resultados_positivos"] + resumo["anos_resultados_negativos"]
    pontos_consistencia = round(20 * resumo["anos_resultados_positivos"] / anos_com_resultado, 1) if anos_com_resultado else 0

    autonomia = resumo.get("ultimo_autonomia")
    if autonomia is None:
        pontos_autonomia = 0
    elif autonomia >= 0.5:
        pontos_autonomia = 20
    elif autonomia >= 0.35:
        pontos_autonomia = 15
    elif autonomia >= 0.2:
        pontos_autonomia = 9
    elif autonomia >= 0.1:
        pontos_autonomia = 4
    else:
        pontos_autonomia = 0

    endividamento = resumo.get("ultimo_endividamento")
    if endividamento is None:
        pontos_endividamento = 0
    elif endividamento <= 0.4:
        pontos_endividamento = 15
    elif endividamento <= 0.6:
        pontos_endividamento = 11
    elif endividamento <= 0.8:
        pontos_endividamento = 6
    else:
        pontos_endividamento = 0

    crescimento = serie[0].get("crescimento_rendimentos") if serie else None
    if crescimento is None:
        pontos_tendencia = 5 if len(serie) == 1 else 0
    elif crescimento >= 0.05:
        pontos_tendencia = 10
    elif crescimento >= -0.05:
        pontos_tendencia = 6
    else:
        pontos_tendencia = 0

    rendimentos = resumo.get("ultimo_rendimentos")
    if rendimentos is None:
        pontos_escala = 0
    elif rendimentos >= 1_000_000:
        pontos_escala = 10
    elif rendimentos >= 250_000:
        pontos_escala = 7
    elif rendimentos >= 50_000:
        pontos_escala = 4
    else:
        pontos_escala = 2

    return [
        {"chave": "resultado_liquido", "nome": "Resultado líquido do último exercício", "maximo": 25,
         "valor": ultimo_resultado, "pontos": pontos_resultado},
        {"chave": "consistencia", "nome": "Exercícios com resultado positivo", "maximo": 20,
         "valor": f"{resumo['anos_resultados_positivos']}/{anos_com_resultado}", "pontos": pontos_consistencia},
        {"chave": "autonomia_financeira", "nome": "Autonomia financeira (capital próprio / activo)", "maximo": 20,
         "valor": autonomia, "pontos": pontos_autonomia},
        {"chave": "endividamento", "nome": "Endividamento (passivo / activo)", "maximo": 15,
         "valor": endividamento, "pontos": pontos_endividamento},
        {"chave": "tendencia_rendimentos", "nome": "Tendência dos rendimentos", "maximo": 10,
         "valor": crescimento, "pontos": pontos_tendencia},
        {"chave": "escala", "nome": "Escala de rendimentos", "maximo": 10,
         "valor": rendimentos, "pontos": pontos_escala},
    ]


def _componentes_risco(
    transparencia: int,
    credito: Optional[int],
    resumo: Dict[str, Any],
    serie: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    componentes: List[Dict[str, Any]] = []
    if credito is None:
        componentes.append({"chave": "solidez", "nome": "Sem dados financeiros", "maximo": 25, "pontos": 25,
                            "detalhe": "A entidade não publicou nenhum exercício"})
    else:
        pontos = round((100 - credito) / 100 * 40, 1)
        componentes.append({"chave": "solidez", "nome": "Défice de solidez financeira", "maximo": 40,
                            "pontos": pontos, "detalhe": f"Score de crédito {credito}/100"})
    componentes.append({"chave": "opacidade", "nome": "Défice de transparência", "maximo": 20,
                        "pontos": round((100 - transparencia) / 100 * 20, 1),
                        "detalhe": f"Score de transparência {transparencia}/100"})

    ultimo = serie[0] if serie else None
    ultimo_resultado = resumo.get("ultimo_resultados")
    if ultimo_resultado is not None and ultimo_resultado < 0:
        componentes.append({"chave": "resultado_negativo", "nome": "Prejuízo no último exercício", "maximo": 10,
                            "pontos": 10, "detalhe": f"{ultimo['ano']}: {ultimo_resultado:,.0f} €".replace(",", " ")})
        if resumo["anos_resultados_negativos"] >= 2:
            componentes.append({"chave": "prejuizos_repetidos", "nome": "Prejuízos repetidos", "maximo": 10,
                                "pontos": 10, "detalhe": f"{resumo['anos_resultados_negativos']} exercícios com prejuízo"})
    autonomia = resumo.get("ultimo_autonomia")
    if autonomia is not None and autonomia < 0.1:
        componentes.append({"chave": "capital_proprio_baixo", "nome": "Capital próprio quase nulo", "maximo": 10,
                            "pontos": 10, "detalhe": f"Autonomia financeira {autonomia:.0%}"})
    endividamento = resumo.get("ultimo_endividamento")
    if endividamento is not None and endividamento > 0.9:
        componentes.append({"chave": "endividamento_critico", "nome": "Endividamento crítico", "maximo": 8,
                            "pontos": 8, "detalhe": f"Passivo/activo {endividamento:.0%}"})
    if resumo.get("confidencialidade"):
        anos_nota = [str(a["ano"]) for a in serie if a.get("nota")]
        detalhe = (
            f"Exceção de divulgação deferida em {', '.join(anos_nota)}"
            if anos_nota
            else "Há exercícios marcados como confidenciais no portal"
        )
        componentes.append({"chave": "confidencialidade", "nome": "Confidencialidade pedida", "maximo": 7,
                            "pontos": 7, "detalhe": detalhe})
    if not int(resumo.get("n_anos_financeiro") or 0):
        componentes.append({"chave": "sem_contas", "nome": "Sem contas publicadas", "maximo": 8,
                            "pontos": 8, "detalhe": "Nenhum exercício financeiro publicado"})
    return componentes


def _alertas(transparencia: int, credito: Optional[int], resumo: Dict[str, Any], serie: List[Dict[str, Any]]) -> List[str]:
    alertas: List[str] = []
    ultimo_resultado = resumo.get("ultimo_resultados")
    if not serie:
        alertas.append("Não publicou qualquer exercício financeiro no portal.")
    else:
        if ultimo_resultado is not None and ultimo_resultado < 0:
            alertas.append(f"Prejuízo no exercício {serie[0]['ano']} ({ultimo_resultado:,.0f} €).".replace(",", " "))
        if resumo["anos_resultados_negativos"] >= 2:
            alertas.append(f"{resumo['anos_resultados_negativos']} exercícios com resultado negativo.")
        autonomia = resumo.get("ultimo_autonomia")
        if autonomia is not None and autonomia < 0.1:
            alertas.append("Capital próprio abaixo de 10% do activo.")
        endividamento = resumo.get("ultimo_endividamento")
        if endividamento is not None and endividamento > 0.9:
            alertas.append("Passivo acima de 90% do activo.")
        ano_atual = _dt.date.today().year
        if int(resumo.get("ultimo_ano_financeiro") or 0) <= ano_atual - 3:
            alertas.append(f"O exercício mais recente é {resumo['ultimo_ano_financeiro']}.")
        if resumo.get("confidencialidade"):
            anos_nota = [str(a["ano"]) for a in serie if a.get("nota")]
            if anos_nota:
                alertas.append(f"Exceção de divulgação deferida pela ERC em {', '.join(anos_nota)}.")
            else:
                alertas.append("Pediu confidencialidade em pelo menos um exercício.")
    if not int(resumo.get("n_anos_financeiro") or 0):
        alertas.append("Sem contas publicadas: a análise de crédito não é possível.")
    if transparencia < 40:
        alertas.append("Publicação mínima face ao que o portal permite declarar.")
    if credito is not None and credito < 35:
        alertas.append("Indicadores financeiros no nível mais baixo da escala.")
    return alertas


def analisar(entidade: Dict[str, Any]) -> Dict[str, Any]:
    """Calcula transparência, crédito e risco de uma entidade do portal."""
    serie = enriquecer_serie(entidade.get("financeiro"))
    resumo = resumo_financeiro(serie)

    indicadores_t = _indicadores_transparencia(entidade, serie)
    transparencia = int(round(sum(i["pontos"] for i in indicadores_t)))
    indicadores_c = _indicadores_credito(resumo, serie)
    credito = int(round(sum(i["pontos"] for i in indicadores_c))) if serie else None

    componentes = _componentes_risco(transparencia, credito, resumo, serie)
    risco = min(100, int(round(sum(c["pontos"] for c in componentes))))

    return {
        "transparencia": {
            "score": transparencia,
            "nivel": _faixa(transparencia, _LIMIARES_TRANSPARENCIA, "muito_baixa"),
            "indicadores": indicadores_t,
        },
        "credito": {
            "score": credito,
            "nivel": _faixa(credito, _LIMIARES_CREDITO, "E") if credito is not None else "sem dados",
            "disponivel": credito is not None,
            "indicadores": indicadores_c,
        },
        "risco": {
            "score": risco,
            "banda": _faixa(risco, _LIMIARES_RISCO, "baixo"),
            "componentes": componentes,
        },
        "alertas": _alertas(transparencia, credito, resumo, serie),
        "cobertura": {
            "anos_financeiros": resumo["n_anos_financeiro"],
            "primeiro_ano": resumo["primeiro_ano_financeiro"],
            "ultimo_ano": resumo["ultimo_ano_financeiro"],
            "confidencialidade": resumo["confidencialidade"],
        },
        "limitacoes": AVISO,
        "fonte": FONTE,
        "atualizado_em": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def aplicar(entidade: Dict[str, Any]) -> Dict[str, Any]:
    """Enriquece a série financeira e acrescenta o resumo e a análise ao documento."""
    doc = dict(entidade)
    doc["financeiro"] = enriquecer_serie(doc.get("financeiro"))
    doc.update(resumo_financeiro(doc["financeiro"]))
    doc["analise"] = analisar(doc)
    return doc
