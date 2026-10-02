"""Chat de IA sobre uma pesquisa da Pesquisa total.

Responde a perguntas sobre **o que aquela pesquisa encontrou**: os resultados são
o contexto entregue ao modelo (numerados, com os valores), e a resposta cita esses
números. Não é um chat genérico — se a resposta não estiver nos resultados (ou nos
números da análise de custos), o modelo é instruído a dizê-lo em vez de inventar.

Fornecedores: os mesmos do resto da plataforma (`providers_service` + chave do
utilizador); sem fornecedor cloud com chave, devolve uma explicação em vez de uma
resposta vazia.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from api.ontology_ai import ask_model, available_backend
from api.search_analysis import contracts_analysis
from api.search_service import parse_filters, unified_search

logger = logging.getLogger(__name__)

#: Contexto entregue ao modelo: resultados + números da análise.
MAX_CONTEXT_ITEMS = 22
MAX_SNIPPET = 220

SYSTEM_PROMPT = (
    "És o analista do IQ OS a responder sobre uma pesquisa concreta. "
    "Usa **apenas** o CONTEXTO fornecido (resultados numerados e a análise de custos). "
    "Cita sempre os itens pelos números entre parênteses, como (3) ou (5, 7). "
    "Se a resposta não estiver no contexto, diz o que falta em vez de inventar. "
    "Valores em euros e datas em formato português. "
    "Responde em português de Portugal, em parágrafos curtos e, quando ajudar, listas com «-». "
    "Não repitas o contexto inteiro: responde à pergunta."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _context_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Resultados da pesquisa, achatados e numerados (o que o modelo pode citar)."""
    items: List[Dict[str, Any]] = []
    for group in payload.get("groups") or []:
        rotulo = group.get("label") or group.get("scope")
        for item in group.get("items") or []:
            if len(items) >= MAX_CONTEXT_ITEMS:
                return items
            extra = item.get("extra") or {}
            valor = extra.get("preco") or extra.get("valor") or item.get("value")
            items.append(
                {
                    "n": len(items) + 1,
                    "scope": group.get("scope"),
                    "tipo": rotulo,
                    "titulo": item.get("title") or "",
                    "subtitulo": item.get("subtitle") or "",
                    "excerto": (item.get("snippet") or "")[:MAX_SNIPPET],
                    "valor": valor if isinstance(valor, (int, float)) else None,
                    "data": item.get("date"),
                    "url": item.get("url") or "",
                    "total_no_ambito": group.get("total"),
                }
            )
    return items


def _analysis_lines(analysis: Dict[str, Any]) -> List[str]:
    """Números da análise de custos, em texto (o modelo soma/relaciona a partir daqui)."""
    totals = analysis.get("totals") or {}
    if not totals.get("contracts"):
        return []
    lines = [
        f"Contratos encontrados: {totals.get('contracts')} · valor total {totals.get('value'):,.2f} €".replace(",", " "),
        f"Portugal: {totals.get('contracts_pt')} contratos · {totals.get('value_pt'):,.2f} €".replace(",", " "),
        f"Espanha: {totals.get('contracts_es')} contratos · {totals.get('value_es'):,.2f} €".replace(",", " "),
        f"Valor médio {totals.get('avg_value'):,.2f} € · maior contrato {totals.get('max_value'):,.2f} €".replace(",", " "),
    ]
    anos = analysis.get("by_year") or []
    if anos:
        lines.append(
            "Por ano: "
            + "; ".join(f"{item.get('key')}={item.get('count')} contratos/{item.get('total_value'):,.0f} €".replace(",", " ") for item in anos[-6:])
        )
    adjudicatarios = analysis.get("top_adjudicatarios") or []
    if adjudicatarios:
        lines.append(
            "Maiores adjudicatários: "
            + "; ".join(
                f"{item.get('description') or item.get('key')} ({item.get('count')} contratos, {item.get('total_value'):,.0f} €)".replace(",", " ")
                for item in adjudicatarios[:6]
            )
        )
    empresas = (analysis.get("linked") or {}).get("companies") or []
    if empresas:
        lines.append(
            "Empresas com ficha: "
            + "; ".join(f"{item.get('name')} (NIF {item.get('nif')}, {item.get('contracts_total')} contratos)".replace(",", " ") for item in empresas[:6])
        )
    pessoas = (analysis.get("linked") or {}).get("people") or []
    if pessoas:
        lines.append(
            "Pessoas ligadas: "
            + "; ".join(f"{item.get('name')} ({item.get('role')} em {item.get('company_name')})" for item in pessoas[:8])
        )
    return lines


def _context_text(query: str, items: List[Dict[str, Any]], analysis: Dict[str, Any]) -> str:
    linhas = [f"PESQUISA: {query}"]
    if items:
        linhas.append("\nRESULTADOS (numeração citação):")
        for item in items:
            partes = [f"[{item['n']}] ({item['tipo']}) {item['titulo']}"]
            if item.get("subtitulo"):
                partes.append(item["subtitulo"])
            if item.get("data"):
                partes.append(str(item["data"])[:10])
            if item.get("valor"):
                partes.append(f"{item['valor']:,.2f} €".replace(",", " "))
            if item.get("excerto"):
                partes.append(item["excerto"])
            linhas.append(" · ".join(partes))
    else:
        linhas.append("\nRESULTADOS: (nenhum)")
    analise = _analysis_lines(analysis)
    if analise:
        linhas.append("\nANÁLISE DE CONTRATOS E CUSTOS:")
        linhas.extend(f"- {linha}" for linha in analise)
    return "\n".join(linhas)


async def ask_search(
    question: str,
    *,
    query: str,
    scope: str = "all",
    filters: Optional[Dict[str, str]] = None,
    history: Optional[List[Dict[str, str]]] = None,
    include_analysis: bool = True,
    backend: Optional[str] = None,
    session: Any = None,
) -> Dict[str, Any]:
    """Responde a uma pergunta sobre a pesquisa, com citação dos resultados."""
    pergunta = (question or "").strip()
    termo = (query or "").strip()
    if not pergunta:
        return {"error": "Escreva a pergunta."}
    if not termo:
        return {"error": "Faça primeiro uma pesquisa: o chat responde sobre os resultados dela."}

    filtros = filters or {}
    payload = unified_search(termo, scope=scope, size=12, filters=parse_filters(",".join(f"{k}:{v}" for k, v in filtros.items()) if filtros else None))
    items = _context_items(payload)
    analysis: Dict[str, Any] = {}
    if include_analysis:
        try:
            analysis = contracts_analysis(termo)
        except Exception as exc:  # a análise é contexto extra, não é obrigatória
            logger.info("Análise para o chat indisponível: %s", exc)

    resolvido = available_backend(session, backend)
    if resolvido.get("kind") != "cloud" or not resolvido.get("api_key"):
        return {
            "question": pergunta,
            "answer": None,
            "error": resolvido.get("note")
            or "Sem fornecedor de IA configurado. Defina a chave de um fornecedor (OpenAI, DeepSeek, …) nas Definições de IA.",
            "context_items": len(items),
        }

    historico: List[str] = []
    for entry in (history or [])[-6:]:
        papel = "Utilizador" if str(entry.get("role")) == "user" else "Assistente"
        historico.append(f"{papel}: {str(entry.get('content') or '')[:600]}")
    prompt = "\n\n".join(
        parte
        for parte in [
            _context_text(termo, items, analysis),
            ("CONVERSA ANTERIOR:\n" + "\n".join(historico)) if historico else "",
            f"PERGUNTA: {pergunta}",
        ]
        if parte
    )

    try:
        answer = await ask_model(resolvido, system=SYSTEM_PROMPT, prompt=prompt, max_tokens=900, temperature=0.2)
    except Exception as exc:
        logger.exception("Chat da pesquisa falhou: %s", exc)
        return {"question": pergunta, "answer": None, "error": f"Falha do fornecedor de IA: {exc}"}

    return {
        "question": pergunta,
        "answer": answer,
        "provider": resolvido.get("provider"),
        "model": resolvido.get("model"),
        "generated_at": _now(),
        "sources": [
            {
                "n": item["n"],
                "title": item["titulo"],
                "subtitle": item["subtitulo"],
                "scope": item["scope"],
                "url": item["url"],
                "value": item["valor"],
            }
            for item in items
        ],
        "context_items": len(items),
        "analysis_included": bool(analysis.get("totals", {}).get("contracts")),
        "caveats": [
            "A resposta é do modelo sobre os resultados desta pesquisa; confirme nos documentos originais antes de decidir.",
        ],
    }
