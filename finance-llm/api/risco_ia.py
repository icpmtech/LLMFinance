"""Parecer de risco por **IA** (módulo «Empresas & Risco»).

O motor (`risco_service`) calcula o número; este módulo escreve a **leitura** do
número: o que o puxa para cima, o que o contém, o que não explica e o que se
deve verificar a seguir. Regras de ferro, iguais às do módulo de padrões:

- o texto usa **só** os factos fornecidos (componentes, features, sinais,
  contratos) — nada de contratos, valores ou processos inventados;
- o score **não** é alterado pela IA: o número é reprodutível, o texto é
  interpretação (e vem identificado com o fornecedor/modelo que o escreveu);
- sem modelo configurado devolve-se o parecer **factual** (mesmos números,
  escrita mecânica) — nunca um erro nem um texto vazio.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Sequence

logger = logging.getLogger(__name__)

_SISTEMA = (
    "És analista de risco de contratação pública do IQ OS. Escreves em português de Portugal, "
    "sóbrio e verificável. Usa **apenas** os dados fornecidos no JSON (componentes de risco, "
    "features, sinais, contratos, relações): não inventes valores, contratos, empresas, pessoas nem "
    "datas. Quando um dado não existir, escreve que não foi encontrado. Explica sempre que o nível "
    "de risco é uma **prioridade de análise** calculada com dados públicos, não uma acusação nem "
    "probabilidade de crime. Não dês aconselhamento jurídico nem juízos sobre pessoas."
)

PROMPT = (
    "Escreve o **parecer de risco** desta empresa adjudicatária, em Markdown, com estas secções:\n"
    "1. **Nível de risco** — o score, a faixa e a confiança, numa frase, com a versão do modelo;\n"
    "2. **O que puxa o risco** — os componentes por ordem de contributo, cada um com o número que o "
    "sustenta e um exemplo concreto (contrato, comprador ou processo) quando existir;\n"
    "3. **O que contém o risco** — componentes com pouca pontuação ou sem dados, e porque isso "
    "importa (ausência de sinal não é prova de boa prática);\n"
    "4. **Portefólio em números** — contratos, valor, anos, compradores, CPV principal;\n"
    "5. **Relações e contexto** — pessoas, empresas ligadas, insolvências e menções públicas, se "
    "existirem nos dados;\n"
    "6. **O que verificar a seguir** — 3 a 5 perguntas concretas, cada uma com o dado que a fecha;\n"
    "7. **Limitações** — cobertura do modelo, amostra usada e o que o portal não regista.\n\n"
    "Sê específico e não repitas o mesmo número em várias secções. Se um ponto não tiver dados, diz "
    "«não foi encontrado»."
)


def factos(risco: Dict[str, Any], analise: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Factos compactos que o modelo pode afirmar sem inventar (nada mais é enviado)."""
    risco = risco or {}
    componentes = [
        {
            "id": item.get("id"),
            "label": item.get("label"),
            "peso": item.get("peso_efetivo") or item.get("peso"),
            "pontos": item.get("pontos"),
            "evidencia": item.get("evidencia") or [],
            "disponivel": item.get("disponivel"),
        }
        for item in (risco.get("componentes") or [])
    ]
    dados: Dict[str, Any] = {
        "risco": {
            "score": risco.get("score"),
            "nivel": risco.get("nivel"),
            "nivel_label": risco.get("nivel_label"),
            "faixa": risco.get("faixa"),
            "confianca": risco.get("confianca"),
            "cobertura": risco.get("cobertura"),
            "metodo": risco.get("metodo"),
            "metodo_label": risco.get("metodo_label"),
            "versao_modelo": (risco.get("cartao_modelo") or {}).get("versao"),
            "aviso": (risco.get("cartao_modelo") or {}).get("aviso"),
            "avisos": risco.get("avisos") or [],
        },
        "componentes": componentes,
        "features": risco.get("features") or {},
        "modelo_ml": risco.get("ml"),
        "modelo_supervisionado": risco.get("modelo_supervisionado"),
    }
    if analise:
        resumo = analise.get("resumo") or {}
        dados["empresa"] = {
            "nif": analise.get("nif"),
            "nome": analise.get("nome"),
            "pais": analise.get("pais_label") or analise.get("pais"),
            "anos": analise.get("anos"),
            "contratos_analisados": analise.get("contratos_analisados"),
            "contratos_registados": analise.get("contratos_total"),
        }
        dados["portfolio"] = {
            "valor_total": resumo.get("valor_total"),
            "valor_mediano": resumo.get("valor_mediano"),
            "desvio_mediano_preco_base": resumo.get("desvio_mediano"),
            "taxa_ajuste_direto": resumo.get("taxa_ajuste_direto"),
            "taxa_aditivo": resumo.get("taxa_aditivo"),
            "compradores_distintos": resumo.get("adjudicantes_distintos"),
            "concentracao_no_maior_comprador": resumo.get("concentracao_adjudicante"),
            "contratos_com_sinais": resumo.get("contratos_com_sinais"),
            "contratos_atipicos_no_cpv": resumo.get("contratos_atipicos_cpv"),
            "insolvente_cire": resumo.get("insolvente"),
        }
        dados["por_cpv"] = (analise.get("por_cpv") or [])[:8]
        dados["por_procedimento"] = (analise.get("por_procedimento") or [])[:6]
        dados["compradores"] = (analise.get("adjudicantes") or [])[:10]
        dados["sinais"] = [
            {
                "regra": sinal.get("padrao"),
                "label": sinal.get("label"),
                "severidade": sinal.get("severidade"),
                "contratos": sinal.get("contratos"),
                "exemplo": sinal.get("exemplo") or sinal.get("detail"),
            }
            for sinal in (analise.get("sinais") or [])[:10]
        ]
        relacoes = analise.get("relacoes") or {}
        dados["relacoes"] = {
            "cargos_sociais": (relacoes.get("cargos_sociais") or [])[:8],
            "insolvencias": (relacoes.get("insolvencias") or [])[:6],
            "empresas_ligadas": (relacoes.get("empresas") or [])[:8],
            "noticias": [
                {"titulo": noticia.get("titulo"), "fonte": noticia.get("fonte"), "data": noticia.get("data")}
                for noticia in (relacoes.get("noticias") or [])[:8]
            ],
        }
    return dados


def _formatar_euro(valor: Any) -> str:
    if not isinstance(valor, (int, float)):
        return "não disponível"
    # pt-PT: milhares com espaço, decimais com vírgula (mesma convenção do
    # relatório de contribuintes, para o texto poder ser copiado para PDF/Excel).
    return f"{valor:,.2f}".replace(",", " ").replace(".", ",") + " €"


def factual_markdown(risco: Dict[str, Any], analise: Optional[Dict[str, Any]] = None) -> str:
    """Parecer **sem IA**: os mesmos números e o mesmo aviso, escrita mecânica."""
    risco = risco or {}
    dados_empresa = (analise or {}).get("nome") or (analise or {}).get("nif") or "empresa"
    linhas: List[str] = [
        f"# Parecer de risco · {dados_empresa}",
        "",
        f"- **Nível:** {risco.get('nivel_label') or 'sem dados'}"
        + (f" ({risco.get('score')}/100, faixa {risco.get('faixa')})" if risco.get("score") is not None else ""),
        f"- **Confiança:** {risco.get('confianca')} · cobertura dos componentes: "
        f"{(risco.get('cobertura') or 0) * 100:.0f}%",
        f"- **Método:** {(risco.get('metodo_label') or risco.get('metodo') or '—')} · modelo "
        f"{(risco.get('cartao_modelo') or {}).get('versao') or '—'}",
        "",
        "## Componentes (peso × pontos)",
        "",
    ]
    for item in risco.get("componentes") or []:
        pontos = item.get("pontos")
        peso = (item.get("peso_efetivo") or item.get("peso") or 0) * 100
        if not item.get("disponivel"):
            linhas.append(f"- **{item.get('label')}** — sem dados no portal")
            continue
        evidência = "; ".join(item.get("evidencia") or []) or "sem detalhe"
        linhas.append(f"- **{item.get('label')}** — {pontos}/100 (peso {peso:.0f}%): {evidência}")

    ml = risco.get("ml") or {}
    if ml:
        linhas += ["", "## Modelo de anomalia (ML)", ""]
        if ml.get("disponivel"):
            linhas.append(
                f"- {ml.get('algoritmo')} sobre {ml.get('n_referencia')} empresas comparáveis: "
                f"percentil {(ml.get('percentil') or 0) * 100:.0f}."
            )
        else:
            linhas.append(f"- Indisponível: {ml.get('motivo') or 'sem modelo'}.")

    supervisionado = risco.get("modelo_supervisionado") or {}
    if supervisionado.get("disponivel"):
        linhas.append(
            f"- Sinal de aditivo (supervisionado): AUC {supervisionado.get('auc')}, "
            f"lift no decil superior {supervisionado.get('lift_top_decile')} · rótulo «{supervisionado.get('rotulo')}»."
        )

    if analise:
        resumo = analise.get("resumo") or {}
        linhas += [
            "",
            "## Portefólio",
            "",
            f"- **Contratos:** {analise.get('contratos_analisados')} analisados de {analise.get('contratos_total')} registados",
            f"- **Valor adjudicado (amostra):** {_formatar_euro(resumo.get('valor_total'))}",
            f"- **Ajuste direto:** {((resumo.get('taxa_ajuste_direto') or 0) * 100):.1f}% · "
            f"**aditivos:** {((resumo.get('taxa_aditivo') or 0) * 100):.1f}%",
            f"- **Compradores distintos:** {resumo.get('adjudicantes_distintos')} · **concentração no maior:** "
            f"{((resumo.get('concentracao_adjudicante') or 0) * 100):.1f}%",
        ]
        sinais = analise.get("sinais") or []
        if sinais:
            linhas += ["", "## Sinais de regra", ""]
            for sinal in sinais[:10]:
                linhas.append(
                    f"- **{sinal.get('label') or sinal.get('padrao')}** ({sinal.get('severidade')}): "
                    f"{sinal.get('contratos')} contratos"
                )
    linhas += [
        "",
        "## Limitações",
        "",
        (risco.get("cartao_modelo") or {}).get("aviso") or "",
        "Parecer montado apenas com factos do IQ OS, sem modelo de IA configurado.",
    ]
    for aviso in risco.get("avisos") or []:
        linhas.append(f"- {aviso}")
    return "\n".join(linha for linha in linhas if linha is not None)


async def parecer(
    risco: Dict[str, Any],
    *,
    analise: Optional[Dict[str, Any]] = None,
    session: Any = None,
    backend: Optional[str] = None,
    max_tokens: int = 1600,
) -> Dict[str, Any]:
    """Parecer de risco (IA quando há modelo configurado; senão, factual)."""
    factos_json = factos(risco, analise)
    saida: Dict[str, Any] = {
        "mode": "factual",
        "text": factual_markdown(risco, analise),
        "backend": None,
        "notes": [],
        "warnings": [],
        "factos": factos_json,
    }
    if not risco or risco.get("score") is None:
        saida["warnings"].append("Sem risco calculado: parecer factual com os dados disponíveis.")
        return saida
    try:
        from api import ontology_ai as ai  # noqa: PLC0415
        from api import people_360  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        saida["warnings"].append(f"IA indisponível ({exc}).")
        return saida
    try:
        escolhido, nota = people_360.resolve_backend(session, backend)
    except Exception as exc:  # noqa: BLE001
        saida["warnings"].append(f"IA indisponível ({exc}).")
        return saida
    if nota:
        saida["notes"].append(nota)
    saida["backend"] = {
        "kind": escolhido.get("kind"),
        "provider": escolhido.get("provider"),
        "model": escolhido.get("model"),
    }
    if escolhido.get("kind") != "cloud":
        saida["notes"].append(escolhido.get("note") or "Sem modelo configurado: parecer montado só com factos.")
        return saida
    try:
        texto = await ai.ask_model(
            escolhido,
            system=_SISTEMA,
            prompt=PROMPT + "\n\nDADOS (JSON):\n" + json.dumps(factos_json, ensure_ascii=False, default=str)[:14000],
            max_tokens=max_tokens,
            temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001
        saida["warnings"].append(f"A IA falhou ({exc}); parecer factual.")
        return saida
    if not texto:
        saida["warnings"].append("A IA devolveu texto vazio; parecer factual.")
        return saida
    saida["mode"] = "ai"
    saida["text"] = texto
    saida["notes"].append(
        f"Parecer redigido por {escolhido.get('provider')}:{escolhido.get('model')} a partir dos componentes de risco."
    )
    return saida


def disponivel() -> Dict[str, Any]:
    """Estado do módulo de IA (para o `/meta` e diagnóstico)."""
    estado: Dict[str, Any] = {"modulo": "risco-ia"}
    try:
        from api import ontology_ai as ai  # noqa: PLC0415

        estado["ontology_ai"] = True
        estado["max_tokens_default"] = 1600
        estado["ask_model"] = callable(getattr(ai, "ask_model", None))
    except Exception as exc:  # noqa: BLE001
        estado["ontology_ai"] = False
        estado["erro"] = str(exc)
    return estado
