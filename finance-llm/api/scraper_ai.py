"""Sugestão assistida por IA das definições de recolha («obter os scraper»).

Dado um URL, este módulo:

1. **Analisa a página** de forma determinística — procura contentores repetidos
   (com ligação e texto), mede a cobertura de cada candidato e extrai uma
   amostra de HTML do melhor contentor.
2. **Pede a um modelo de IA** (o fornecedor configurado em *Definições →
   Fornecedores de IA*) que escolha o seletor da lista e os campos, devolvendo
   apenas JSON.
3. **Valida** a proposta executando-a de verdade (`preview_source`); se o modelo
   falhar, não responder ou devolver algo que não extrai nada, cai na
   **heurística** determinística — o utilizador nunca fica sem proposta.

Sem chave configurada, a análise determinística continua a ser devolvida, com
uma nota a explicar como ligar a IA.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from api import scraper_service as scraper

logger = logging.getLogger(__name__)

# Elementos que podem ser «um item de uma lista» numa página.
_CONTAINER_TAGS = ("article", "li", "div", "section", "tr", "figure")
# Seletores usados para confirmar que um item tem um título plausível e para o
# propor. A ordem define a preferência: cabeçalhos primeiro, depois classes com
# nome de título/texto e, por fim, elementos de texto genéricos (essencial para
# páginas onde o "título" é um `<span class="text">` ou uma ligação longa).
_TITLE_SELECTORS = (
    "h1 a::text",
    "h2 a::text",
    "h3 a::text",
    "h4 a::text",
    "h1::text",
    "h2::text",
    "h3::text",
    "h4::text",
    "[class*=title]::text",
    "[class*=titulo]::text",
    "[class*=nome]::text",
    "[class*=name]::text",
    "[class*=text]::text",
    "[class*=resumo]::text",
    "[class*=descri]::text",
    "[class*=objeto]::text",
    "strong::text",
    "b::text",
    "p::text",
    "a::text",
)
_MIN_TITLE_CHARS = 25
_MAX_HTML_SAMPLE = 3000


# ------------------------------------------------------------------ análise
def _node_selector(tag: str, classes: List[str]) -> str:
    if not classes:
        return tag
    return f"{tag}." + ".".join(classes[:3])


def _stats_for(page: Any, selector: str) -> Optional[Dict[str, Any]]:
    """Mede um seletor de lista: quantos itens, quantos com título/ligação/texto/imagem."""
    try:
        nodes = page.css(selector)
    except Exception:
        return None
    total = len(nodes)
    if total < 3 or total > 2000:
        return None
    com_link = com_texto = com_imagem = com_titulo = 0
    titulos: List[str] = []
    exemplo = None
    for node in nodes[:60]:
        link = None
        try:
            link = node.css("a::attr(href)").get()
        except Exception:
            link = None
        texto = ""
        try:
            texto = (node.get_all_text() or "").strip()
        except Exception:
            texto = ""
        titulo = ""
        for cand in _TITLE_SELECTORS:
            try:
                values = [str(v).strip() for v in node.css(cand).getall() if str(v).strip()]
            except Exception:
                continue
            if any(len(v) > _MIN_TITLE_CHARS for v in values):
                titulo = next(v for v in values if len(v) > _MIN_TITLE_CHARS)
                break
        if link:
            com_link += 1
        if len(texto) > 25:
            com_texto += 1
        if titulo:
            com_titulo += 1
            if len(titulos) < 3 and titulo not in titulos:
                titulos.append(titulo[:120])
        try:
            if node.css("img"):
                com_imagem += 1
        except Exception:
            pass
        if exemplo is None:
            exemplo = node
    amostra = min(60, total)
    return {
        "selector": selector,
        "count": total,
        "link_ratio": round(com_link / amostra, 2),
        "text_ratio": round(com_texto / amostra, 2),
        "title_ratio": round(com_titulo / amostra, 2),
        "image_ratio": round(com_imagem / amostra, 2),
        "samples": titulos,
        "node": exemplo,
    }


def _score(stats: Dict[str, Any], *, generic: bool = False) -> float:
    """Qualidade do candidato: a raiz quadrada do total evita que contentores
    genéricos (centenas de `div`s) ganhem só por serem numerosos."""
    score = (
        (stats["count"] ** 0.5)
        * (1 + 1.5 * stats["title_ratio"])
        * (1 + stats["text_ratio"])
        * (1 + 0.3 * stats["link_ratio"])
        * (1 + 0.2 * stats["image_ratio"])
    )
    if generic:
        score *= 0.6
    return round(score, 1)


def _usable(stats: Dict[str, Any]) -> bool:
    """Só serve se cada item tiver texto **e** um título plausível."""
    return stats["text_ratio"] >= 0.5 and stats["title_ratio"] >= 0.5 and stats["link_ratio"] >= 0.4


def analyze_page(page: Any, limit: int = 8) -> List[Dict[str, Any]]:
    """Candidatos a seletor de lista, ordenados por utilidade."""
    signatures: Dict[Tuple[str, Tuple[str, ...]], int] = defaultdict(int)
    for tag in _CONTAINER_TAGS:
        try:
            elements = page.css(tag)
        except Exception:
            continue
        for element in elements:
            classes = tuple(sorted(c for c in (element.attrib.get("class") or "").split() if c))
            signatures[(tag, classes)] += 1
            if len(classes) > 3:  # variantes longas: interessa a parte estável
                signatures[(tag, classes[:2])] += 1

    candidatos: Dict[str, Dict[str, Any]] = {}
    for (tag, classes), count in sorted(signatures.items(), key=lambda item: -item[1])[:40]:
        if count < 3 or len(classes) > 4:
            continue
        selector = _node_selector(tag, list(classes))
        if selector in candidatos:
            continue
        stats = _stats_for(page, selector)
        if not stats or not _usable(stats):
            continue
        candidates = dict(stats)
        candidates["score"] = _score(stats, generic=not classes)
        candidatos[selector] = candidates

    # Um seletor genérico (só o `tag`) só interessa se cobrir mais itens que o melhor
    # com classe e mantiver a qualidade — caso contrário só traria ruído
    # (menus, rodapés, publicidade).
    melhor_classe = max([c["count"] for c in candidatos.values()], default=0)
    for tag in _CONTAINER_TAGS:
        stats = _stats_for(page, tag)
        if stats and _usable(stats) and stats["count"] > melhor_classe * 1.2:
            entry = dict(stats)
            entry["score"] = _score(stats, generic=True)
            candidatos.setdefault(tag, entry)

    ordered = sorted(candidatos.values(), key=lambda c: -c["score"])[: max(1, limit)]
    # O nó do melhor candidato é preciso para a amostra de HTML enviada à IA;
    # nos restantes só pesaria na memória e nas respostas da API.
    for index, entry in enumerate(ordered):
        if index > 0:
            entry.pop("node", None)
    return ordered


def _best_selector(page: Any, candidates: List[str], nodes: List[Any]) -> Optional[str]:
    """Escolhe o seletor com melhor cobertura dentro dos itens da lista."""
    melhor: Optional[str] = None
    melhor_valor = 0.0
    for selector in candidates:
        ok = 0
        for node in nodes[:40]:
            try:
                values = [str(v).strip() for v in node.css(selector).getall() if str(v).strip()]
            except Exception:
                continue
            if any(len(v) > 3 for v in values):
                ok += 1
        ratio = ok / max(1, min(40, len(nodes)))
        if ratio > melhor_valor:
            melhor_valor = ratio
            melhor = selector
    return melhor if melhor_valor >= 0.5 else None


def heuristic_definition(url: str, page: Any, analysis: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Definição determinística a partir da melhor candidata da análise."""
    if not analysis:
        return {}
    best = analysis[0]
    list_selector = best["selector"]
    try:
        nodes = list(page.css(list_selector))
    except Exception:
        nodes = []
    if not nodes:
        return {}

    campo_titulo = _best_selector(page, list(_TITLE_SELECTORS), nodes)
    campo_url = _best_selector(page, ["h3 a::attr(href)", "h2 a::attr(href)", "h1 a::attr(href)", "a::attr(href)"], nodes)
    campo_imagem = _best_selector(page, ["img::attr(src)", "img::attr(data-src)", "source::attr(srcset)"], nodes)

    def nome_para(selector: Optional[str]) -> str:
        return "titulo" if (selector or "").startswith(("h1", "h2", "h3", "h4")) else "texto"

    fields: List[Dict[str, Any]] = []
    if campo_titulo:
        fields.append({"name": nome_para(campo_titulo), "label": "Título", "selector": campo_titulo, "type": "css", "max_length": 500})
    if campo_url:
        fields.append({"name": "url", "label": "Ligação", "selector": campo_url, "type": "css", "max_length": 1000})
    if campo_imagem:
        fields.append({"name": "imagem", "label": "Imagem", "selector": campo_imagem, "type": "css", "max_length": 1000})
    if not fields:
        fields.append({"name": "texto", "label": "Texto", "selector": "a::text", "type": "css", "all": False})
    titulo_field = next((f["name"] for f in fields if f["name"] == "titulo"), fields[0]["name"] if fields else "")

    return {
        "name": _title_for(url, page),
        "url": url,
        "list": {"selector": list_selector, "type": "css"},
        "fields": fields,
        "pagination": {"selector": "", "type": "css", "attr": "href", "max_pages": 1},
        "id_fields": ["url"] if campo_url else [],
        "title_field": titulo_field,
    }


def _title_for(url: str, page: Any) -> str:
    titulo = ""
    try:
        titulo = (page.css("title::text").get() or "").strip()
    except Exception:
        titulo = ""
    if not titulo:
        titulo = re.sub(r"^https?://", "", url).split("/")[0]
    return titulo[:80]


# ----------------------------------------------------------------------- IA
def _sample_html(best: Optional[Dict[str, Any]]) -> str:
    """Amostra compacta do melhor contentor (é o que o modelo precisa de ver)."""
    if not best:
        return ""
    try:
        node = (best or {}).get("node")
        if node is None:
            return ""
        html = node.html_content if hasattr(node, "html_content") else str(node)
    except Exception:
        return ""
    html = re.sub(r">\s+<", "><", re.sub(r"\s+", " ", html))
    return html[:_MAX_HTML_SAMPLE]


def _prompt(url: str, page_title: str, analysis: List[Dict[str, Any]], sample: str, hint: str) -> str:
    candidatos = [
        {k: c[k] for k in ("selector", "count", "text_ratio", "link_ratio", "image_ratio", "samples") if k in c}
        for c in analysis[:6]
    ]
    return (
        "És um especialista em web scraping. Analisa a página e devolve a definição de extração em JSON.\n\n"
        f"URL: {url}\nTítulo da página: {page_title}\n"
        f"Objetivo do utilizador: {hint or 'recolher a lista de itens repetidos desta página'}\n\n"
        "Candidatos a contentor de item (já medidos; `text_ratio`/`link_ratio` = fração com texto/ligação):\n"
        f"{json.dumps(candidatos, ensure_ascii=False, indent=1)}\n\n"
        "Amostra do HTML de UM item (usa-a para descobrir a estrutura interna):\n"
        f"{sample}\n\n"
        "Devolve APENAS este JSON, sem texto à volta:\n"
        "{\n"
        '  "list": {"selector": "<css do item>", "type": "css"},\n'
        '  "fields": [\n'
        '    {"name": "titulo", "label": "Título", "selector": "<css relativo ao item>", "type": "css"},\n'
        '    {"name": "url", "label": "Ligação", "selector": "<css>", "type": "css"},\n'
        '    {"name": "data", "label": "Data", "selector": "<css>", "type": "css"},\n'
        '    {"name": "imagem", "label": "Imagem", "selector": "<css>", "type": "css"}\n'
        "  ],\n"
        '  "id_fields": ["url"],\n'
        '  "title_field": "titulo",\n'
        '  "pagination": {"selector": "", "type": "css", "attr": "href", "max_pages": 1},\n'
        '  "notes": "<o que assumiste e o que pode falhar>"\n'
        "}\n\n"
        "Regras: usa apenas CSS; para texto usa `::text` e para atributos `::attr(nome)`; "
        "os seletores dos campos são relativos ao item; omite campos que não existam na página."
    )


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Extrai o primeiro objeto JSON da resposta (tolerante a cercas de código)."""
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?|```$", "", cleaned, flags=re.MULTILINE).strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    return None


def _ollama_models(timeout: float = 4.0) -> List[str]:
    """Modelos instalados no Ollama local (lista vazia se não estiver acessível)."""
    import os
    import urllib.request

    base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "ignore"))
        return [str(m.get("name") or "") for m in (payload.get("models") or []) if m.get("name")]
    except Exception:
        return []


def _resolve_model(provider_id: str, model: str) -> str:
    """Com o Ollama local, usa um modelo que exista de facto na máquina."""
    if provider_id != "ollama":
        return model
    instalados = _ollama_models()
    if not instalados:
        return model
    if model in instalados:
        return model
    # Prefere um modelo local (não `:cloud`, que exige sessão no Ollama).
    locais = [m for m in instalados if ":cloud" not in m]
    escolhido = (locais or instalados)[0]
    logger.info("Ollama: modelo %r não instalado; a usar %r.", model, escolhido)
    return escolhido


def pick_provider(
    user_id: Optional[str],
    requested: Optional[str] = None,
    requested_model: Optional[str] = None,
) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """Escolhe o fornecedor/modelo de IA utilizável (predefinição do utilizador primeiro)."""
    try:
        from api import providers_service as providers
    except Exception:
        return None, None, None, None

    defaults = (providers.load_user_config(user_id).get("defaults") if user_id else {}) or {}
    ordem: List[str] = []
    if requested:
        ordem.append(requested)
    if defaults.get("provider"):
        ordem.append(str(defaults["provider"]))
    ordem.extend(spec["id"] for spec in providers.PROVIDERS)

    vistos = set()
    for provider_id in ordem:
        if not provider_id or provider_id in vistos:
            continue
        vistos.add(provider_id)
        spec = providers.PROVIDERS_BY_ID.get(provider_id)
        if not spec:
            continue
        key, _source = providers.resolve_key(user_id, provider_id)
        if not key and not spec.get("key_optional"):
            continue
        model = requested_model or ""
        if not model and provider_id == defaults.get("provider"):
            model = str(defaults.get("model") or "")
        return provider_id, spec, _resolve_model(provider_id, model or spec.get("default_model") or ""), key
    return None, None, None, None


async def ai_definition(
    url: str,
    page: Any,
    analysis: List[Dict[str, Any]],
    *,
    hint: str = "",
    user_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Pede a um modelo de IA a definição de extração. Devolve `{definition, ai, error}`."""
    provider_id, spec, model_id, key = pick_provider(user_id, provider, model)
    if not provider_id or not spec:
        return {
            "definition": None,
            "ai": None,
            "error": "Nenhum fornecedor de IA configurado. Defina uma chave em Definições → Fornecedores de IA.",
        }

    from api import cloud_chat

    best = analysis[0] if analysis else None
    page_title = ""
    try:
        page_title = (page.css("title::text").get() or "").strip()
    except Exception:
        page_title = ""
    prompt = _prompt(url, page_title, analysis, _sample_html(best) if best else "", hint)
    try:
        answer = await cloud_chat.complete_answer(
            provider=provider_id,
            spec=spec,
            model=model_id or spec.get("default_model") or "",
            messages=[{"role": "user", "content": prompt}],
            api_key=key,
            temperature=0.1,
            max_tokens=1200,
        )
    except Exception as exc:
        logger.warning("Sugestão por IA falhou (%s): %s", provider_id, exc)
        return {"definition": None, "ai": None, "error": f"{type(exc).__name__}: {exc}"}

    data = _parse_json(answer)
    if not data:
        return {"definition": None, "ai": None, "error": "A IA não devolveu JSON válido.", "raw": answer[:500]}

    notes = str(data.get("notes") or "").strip()
    definition: Dict[str, Any] = {
        "list": data.get("list") or {},
        "fields": data.get("fields") or [],
        "pagination": data.get("pagination") or {"selector": "", "type": "css", "attr": "href", "max_pages": 1},
    }
    if data.get("id_fields"):
        definition["id_fields"] = data["id_fields"]
    if data.get("title_field"):
        definition["title_field"] = data["title_field"]
    if data.get("tags_field"):
        definition["tags_field"] = data["tags_field"]
    return {
        "definition": definition,
        "ai": {"provider": provider_id, "provider_label": spec.get("label") or provider_id, "model": model_id, "notes": notes},
        "error": None,
    }


# ---------------------------------------------------------------- orquestração
def _clean_ai_fields(definition: Dict[str, Any]) -> List[Dict[str, Any]]:
    fields: List[Dict[str, Any]] = []
    for raw in (definition.get("fields") or []):
        if not isinstance(raw, dict):
            continue
        selector = str(raw.get("selector") or "").strip()
        name = str(raw.get("name") or "").strip()
        if not selector or not name:
            continue
        fields.append(
            {
                "name": name,
                "label": str(raw.get("label") or name),
                "selector": selector,
                "type": str(raw.get("type") or "css"),
                "attr": raw.get("attr"),
                "all": bool(raw.get("all", False)),
                "cast": raw.get("cast") or "text",
                "max_length": int(raw.get("max_length") or 1000),
            }
        )
    return fields


async def suggest_source(
    url: str,
    *,
    hint: str = "",
    fetcher: str = "http",
    options: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    use_ai: bool = True,
    max_pages: int = 1,
) -> Dict[str, Any]:
    """Sugere uma definição para um URL: IA primeiro, heurística como rede de segurança."""
    base = {
        "url": url,
        "fetcher": fetcher or "http",
        "enabled": False,
        "options": options or {},
        "respect_robots": True,
        "schedule": {"cron": "", "timezone": "Europe/Lisbon"},
        "tags": [],
    }
    # 1. Abrir a página uma única vez e analisá-la.
    try:
        page = None
        with scraper._open_session(base["fetcher"], base["options"]) as session:
            page = scraper._session_fetch(session, base["fetcher"], url, base["options"])
        if page is None:
            raise RuntimeError("A página não devolveu conteúdo.")
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "analysis": []}

    analysis = analyze_page(page, limit=8)
    heuristic = heuristic_definition(url, page, analysis)

    result: Dict[str, Any] = {
        "ok": True,
        "url": url,
        "title": _title_for(url, page),
        "analysis": analysis,
        "heuristic": heuristic,
        "definition": None,
        "origin": None,
        "ai": None,
        "ai_error": None,
        "preview": None,
    }

    # 2. IA (quando pedida e configurada).
    if use_ai:
        proposal = await ai_definition(
            url, page, analysis, hint=hint, user_id=user_id, provider=provider, model=model
        )
        result["ai"] = proposal.get("ai")
        result["ai_error"] = proposal.get("error")
        candidate = proposal.get("definition")
        if candidate:
            fields = _clean_ai_fields(candidate)
            list_selector = str((candidate.get("list") or {}).get("selector") or "").strip()
            if list_selector and fields:
                trial = {
                    **base,
                    "name": _title_for(url, page),
                    "list": {"selector": list_selector, "type": str((candidate.get("list") or {}).get("type") or "css")},
                    "fields": fields,
                    "pagination": candidate.get("pagination")
                    or {"selector": "", "type": "css", "attr": "href", "max_pages": 1},
                    "id_fields": candidate.get("id_fields") or ([fields[0]["name"]] if fields else []),
                    "title_field": candidate.get("title_field") or fields[0]["name"],
                    "tags_field": candidate.get("tags_field") or "",
                }
                preview = _validate(trial, max_pages)
                result["preview"] = preview
                if preview.get("items"):
                    result["definition"] = trial
                    result["origin"] = "ai"

    # 3. Rede de segurança: heurística (validada).
    if result["definition"] is None and heuristic:
        trial = dict(base, **heuristic)
        preview = _validate(trial, max_pages)
        result["preview"] = preview
        if preview.get("items"):
            result["definition"] = trial
            result["origin"] = "heuristica"
        elif result["origin"] is None:
            result["error"] = preview.get("error") or "Não foi possível extrair itens desta página."

    if result["definition"] is None and not result.get("error"):
        result["ok"] = False
        result["error"] = "Não foi possível identificar a lista de itens desta página."

    result.pop("analysis", None)
    result["analysis"] = [{k: v for k, v in c.items() if k != "node"} for c in analysis]
    return result


def _validate(definition: Dict[str, Any], max_pages: int = 1) -> Dict[str, Any]:
    """Corre a definição a sério (sem guardar) para confirmar que extrai itens."""
    try:
        return scraper.preview_source(definition, limit=3, max_pages=max(1, min(max_pages, 3)))
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "items": [], "total": 0, "pages": 0}
