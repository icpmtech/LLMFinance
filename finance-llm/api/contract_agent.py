"""Agente IA para análise de contratos públicos portugueses.

Suporta múltiplos backends via variável de ambiente:
- Ollama local/cloud: OLLAMA_URL=http://127.0.0.1:11434 (padrão)
- OpenAI-compatível: OPENAI_API_KEY + OPENAI_BASE_URL
- Fallback para os modelos locais do IQ OS via api.agent
"""
import json
import os
import re
from typing import Any, Dict, List, Optional

import requests


def _get_ollama_url() -> str:
    return os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def _get_openai_config() -> Optional[Dict[str, str]]:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    return {
        "api_key": key,
        "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    }


def ollama_list_models() -> List[str]:
    """Lista modelos disponíveis no Ollama configurado."""
    try:
        url = f"{_get_ollama_url()}/api/tags"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        return [m.get("name", m.get("model", "")) for m in data.get("models", [])]
    except Exception:
        return []


def ollama_chat(
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.3,
    max_tokens: int = 1024,
    stream: bool = False,
) -> str:
    """Envia mensagens para o endpoint /api/chat do Ollama."""
    url = f"{_get_ollama_url()}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    r = requests.post(url, json=payload, timeout=180)
    r.raise_for_status()
    if stream:
        # Devolve o iterador de chunks SSE
        return r  # type: ignore[return-value]
    data = r.json()
    return data.get("message", {}).get("content", "")


def _openai_chat(
    messages: List[Dict[str, str]],
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> str:
    cfg = _get_openai_config()
    if not cfg:
        raise RuntimeError("OPENAI_API_KEY não configurada")
    url = f"{cfg['base_url']}/chat/completions"
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    r = requests.post(url, headers=headers, json=payload, timeout=180)
    r.raise_for_status()
    data = r.json()
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


def _local_llm_generate(prompt: str, backend: str = "mistral") -> str:
    """Fallback: usa os modelos locais do IQ OS.

    Nota: os modelos locais (gpt2/mistral) foram fine-tuned para séries financeiras
    (preços/data) e não produzem texto jurídico coerente. Usam-se apenas quando
    Ollama/OpenAI não estão disponíveis, devolvendo uma indicação clara.
    """
    from api.agent import get_inference_model
    try:
        generator = get_inference_model(backend)
        return generator.generate(prompt, max_new_tokens=512, temperature=0.3)
    except Exception as exc:
        return (
            f"[Backend de IA indisponível: não foi possível contactar Ollama/OpenAI "
            f"e o modelo local {backend} não está configurado para análise de texto jurídico "
            f"({exc}). Configura OLLAMA_URL ou OPENAI_API_KEY para obter análises úteis.]"
        )


def _format_money(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.2f} €".replace(",", " ")


def _party_names(contract: Dict[str, Any], role: str) -> List[str]:
    party = contract.get(role)
    if not party:
        return []
    parsed = party.get("parsed", []) if isinstance(party, dict) else []
    return [p.get("nome") for p in parsed if p.get("nome")]


def _party_nifs(contract: Dict[str, Any], role: str) -> List[str]:
    party = contract.get(role)
    if not party:
        return []
    parsed = party.get("parsed", []) if isinstance(party, dict) else []
    return [p.get("nif") for p in parsed if p.get("nif")]


def _format_contract_summary(contract: Dict[str, Any]) -> str:
    """Resume o contrato para o prompt do agente."""
    obj = contract.get("objectoContrato") or "N/A"
    desc = contract.get("descContrato") or "N/A"
    price = _format_money(contract.get("precoContratual") or contract.get("PrecoTotalEfetivo"))
    tipo = ", ".join(contract.get("tipoContrato", [])) if isinstance(contract.get("tipoContrato"), list) else (contract.get("tipoContrato") or "N/A")
    proc = contract.get("tipoprocedimento") or "N/A"
    pub = contract.get("dataPublicacao") or "N/A"
    celeb = contract.get("dataCelebracaoContrato") or "N/A"
    adjudicantes = _party_names(contract, "adjudicantes")
    adjudicatarios = _party_names(contract, "adjudicatarios")
    cpv = [f"{c.get('code')} - {c.get('description')}" for c in contract.get("cpv", []) if isinstance(c, dict)]
    local = contract.get("localExecucao") or []
    nuts = contract.get("NUTs") or []
    return (
        f"ID: {contract.get('idcontrato', 'N/A')}\n"
        f"Objeto: {obj}\n"
        f"Descrição: {desc}\n"
        f"Valor contratual: {price}\n"
        f"Tipo de contrato: {tipo}\n"
        f"Procedimento: {proc}\n"
        f"Data publicação: {pub}\n"
        f"Data celebração: {celeb}\n"
        f"Adjudicantes: {', '.join(adjudicantes) if adjudicantes else 'N/A'}\n"
        f"Adjudicatários: {', '.join(adjudicatarios) if adjudicatarios else 'N/A'}\n"
        f"CPV: {', '.join(cpv) if cpv else 'N/A'}\n"
        f"Local execução: {', '.join(local) if local else 'N/A'}\n"
        f"NUTs: {', '.join(nuts) if nuts else 'N/A'}"
    )


def _gather_context(
    contract: Dict[str, Any],
    question: Optional[str] = None,
    use_web_search: bool = True,
    use_related_contracts: bool = True,
    max_web_results: int = 5,
    max_related: int = 5,
) -> Dict[str, Any]:
    """Recolhe dados complementares: web search, entidades, contratos relacionados."""
    context: Dict[str, Any] = {
        "web_results": [],
        "entities": {},
        "related_contracts": [],
        "tools_used": [],
    }

    # Nomes de entidades para pesquisa
    adjudicante_names = _party_names(contract, "adjudicantes")
    adjudicatario_names = _party_names(contract, "adjudicatarios")
    all_names = list(dict.fromkeys(adjudicante_names + adjudicatario_names))

    # Dados de entidades do Elasticsearch
    try:
        from api.elasticsearch_client import get_company_by_nif, get_company_contracts
        for role in ("adjudicantes", "adjudicatarios"):
            for nif in _party_nifs(contract, role):
                summary = get_company_by_nif(nif)
                if summary and not summary.get("error"):
                    context["entities"][nif] = summary
                    context["tools_used"].append({"tool": "get_company_by_nif", "input": {"nif": nif}, "output": summary})
                contracts = get_company_contracts(nif, size=max_related)
                if isinstance(contracts, dict) and not contracts.get("error"):
                    items = contracts.get("items", [])[:max_related]
                    context["related_contracts"].extend(items)
    except Exception as exc:
        context["tools_used"].append({"tool": "entity_lookup", "input": {}, "output": {"error": str(exc)}})

    # Web search
    if use_web_search:
        try:
            from api.tools import web_search
            queries = []
            if question:
                queries.append(question)
            # Pesquisa por adjudicatários + objeto do contrato
            for name in all_names[:2]:
                queries.append(f"{name} contrato público Portugal")
            if contract.get("objectoContrato"):
                queries.append(f"{contract['objectoContrato']} Portugal contrato público")

            seen_urls = set()
            for q in queries[:3]:
                if not q:
                    continue
                results = web_search(q, max_results=max_web_results)
                for r in results:
                    href = r.get("href", "")
                    if href and href in seen_urls:
                        continue
                    if href:
                        seen_urls.add(href)
                    context["web_results"].append(r)
                context["tools_used"].append({"tool": "web_search", "input": {"query": q}, "output": {"count": len(results)}})
        except Exception as exc:
            context["web_results"].append({"error": str(exc)})

    # Pesquisa por contratos relacionados via CPV/entidade no Elasticsearch
    if use_related_contracts:
        try:
            from api.elasticsearch_client import search_contracts
            terms = []
            if contract.get("objectoContrato"):
                terms.append(contract["objectoContrato"])
            if cpv_codes := [c.get("code") for c in contract.get("cpv", []) if isinstance(c, dict) and c.get("code")]:
                terms.append(" ".join(cpv_codes[:2]))
            if terms:
                related = search_contracts(q=" ".join(terms), size=max_related)
                if isinstance(related, dict) and not related.get("error"):
                    context["related_contracts"].extend(related.get("items", [])[:max_related])
                    context["tools_used"].append({"tool": "search_contracts", "input": {"q": " ".join(terms)}, "output": {"count": related.get("total", 0)}})
        except Exception as exc:
            context["tools_used"].append({"tool": "search_contracts", "input": {}, "output": {"error": str(exc)}})

    return context


def _build_prompt(
    contract: Dict[str, Any],
    question: Optional[str],
    context: Dict[str, Any],
) -> str:
    summary = _format_contract_summary(contract)
    web_results = context.get("web_results", [])
    entities = context.get("entities", {})
    related = context.get("related_contracts", [])

    web_text = "\n".join(
        f"- {r.get('title', 'Sem título')} ({r.get('href', '')}): {r.get('body', '')}"
        for r in web_results[:8]
    ) or "Sem resultados de pesquisa web."

    entity_text = "\n\n".join(
        f"Entidade NIF {nif}:\n" + json.dumps(info, ensure_ascii=False, indent=2, default=str)
        for nif, info in list(entities.items())[:4]
    ) or "Sem dados de entidades."

    related_text = "\n".join(
        f"- {r.get('idcontrato')}: {r.get('objectoContrato')} | {r.get('adjudicantes', {}).get('parsed', [{}])[0].get('nome', 'N/A')} -> {r.get('adjudicatarios', {}).get('parsed', [{}])[0].get('nome', 'N/A')} | {_format_money(r.get('precoContratual'))}"
        for r in related[:6] if isinstance(r, dict)
    ) or "Sem contratos relacionados."

    q = question or "Analisa este contrato de forma jurídico-financeira, assinala riscos, pontos de atenção e comparação com o mercado."

    return f"""És um assistente jurídico-financeiro especializado em contratos públicos portugueses.
Analisa o contrato abaixo e responde de forma factual, concisa e estruturada em português europeu.

### Dados do contrato
{summary}

### Entidades envolvidas
{entity_text}

### Contratos relacionados no índice
{related_text}

### Pesquisa web relevante
{web_text}

### Pergunta do utilizador
{q}

### Instruções de resposta
- Responde em português de Portugal.
- Se usares informação da web, cita as fontes com o título e URL.
- Evita especular; indica claramente quando uma informação é inferida ou não confirmada.
- Estrutura a resposta com bullets ou secções claras quando adequado.
- Foca-te em valor, procedimento, entidades e eventuais riscos/alertas.
"""


def analyze_contract(
    contract: Dict[str, Any],
    question: Optional[str] = None,
    model: str = "llama3.2",
    max_tokens: int = 2048,
    temperature: float = 0.3,
    use_web_search: bool = True,
    use_related_contracts: bool = True,
) -> Dict[str, Any]:
    """Analisa um contrato usando IA (Ollama/OpenAI/local) e ferramentas externas."""
    context = _gather_context(
        contract,
        question=question,
        use_web_search=use_web_search,
        use_related_contracts=use_related_contracts,
    )

    prompt = _build_prompt(contract, question, context)
    messages = [
        {"role": "system", "content": "És um assistente jurídico-financeiro especializado em contratos públicos portugueses. Responde em português de Portugal."},
        {"role": "user", "content": prompt},
    ]

    answer = ""
    backend_used = "unknown"

    # 1) OpenAI-compatible se estiver configurado ou o modelo parecer OpenAI
    openai_cfg = _get_openai_config()
    is_openai_model = bool(openai_cfg) and (not model or model.startswith("gpt-") or model in openai_cfg["model"])
    if openai_cfg and (is_openai_model or (model and "http" in model)):
        try:
            answer = _openai_chat(messages, temperature=temperature, max_tokens=max_tokens)
            backend_used = f"openai:{openai_cfg['model']}"
        except Exception as exc:
            answer = f"[Erro OpenAI: {exc}]"

    # 2) Ollama se não usou OpenAI
    if not answer:
        try:
            models = ollama_list_models()
            # se model estiver vazio ou não existir localmente, usa o primeiro disponível
            chosen_model = model
            if not chosen_model or chosen_model not in models:
                chosen_model = models[0] if models else "gemma4:e4b"
            answer = ollama_chat(chosen_model, messages, temperature=temperature, max_tokens=max_tokens)
            backend_used = f"ollama:{chosen_model}"
        except Exception as exc:
            answer = f"[Erro Ollama: {exc}]"

    # 3) Fallback local (apenas se Ollama/OpenAI não responderam)
    if not answer:
        answer = _local_llm_generate(prompt, backend="mistral")
        backend_used = "local:mistral"

    return {
        "answer": answer,
        "backend_used": backend_used,
        "prompt": prompt,
        "sources": context.get("web_results", []),
        "tools": context.get("tools_used", []),
        "contract_id": contract.get("idcontrato"),
    }
