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

import asyncio
import json
import logging
import os
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

from api import scraper_service as scraper

logger = logging.getLogger(__name__)

#: Limite de espera pela proposta da IA. Um modelo local (Ollama, 8B, em CPU) pode
#: levar **minutos** a responder; a sonda não pode ficar presa — quem está a olhar
#: para o botão precisa de uma resposta. Passado o limite vale a análise
#: determinística e a resposta diz porquê (`avisos`).
AI_TIMEOUT_S = float(os.environ.get("SCRAPER_AI_TIMEOUT", "90"))


async def _ia_com_limite(corrotina: Any, segundos: float = AI_TIMEOUT_S) -> Dict[str, Any]:
    """Corre a proposta da IA com prazo: sem isto, um Ollama lento prendia a sonda."""
    try:
        return await asyncio.wait_for(corrotina, timeout=max(5.0, segundos))
    except asyncio.TimeoutError:
        return {
            "definition": None,
            "ai": None,
            "error": f"A IA não respondeu em {int(segundos)} s — apresento a análise determinística.",
        }

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

#: Contentores que *nunca* são uma lista de produtos: o diálogo de cookies, os
#: menus, os rodapés. Sem isto, o contentor do aviso de consentimento (1086
#: «itens» de texto longo) ganhava ao cartão do produto (48 itens com preço) — e
#: a sonda concluía, sem erro nenhum, que a página não tinha preços.
_CHROME_RE = re.compile(
    r"cookie|consent|gdpr|cybot|iab|banner|modal|dialog|popup|overlay|breadcrumb|"
    r"footer|header|navbar|menu|sidebar|skip-link|carousel|swiper|slick",
    re.IGNORECASE,
)


def _chrome_penalty(selector: str) -> float:
    """Fator de castigo para contentores que são «moldura» da página, não conteúdo."""
    return 0.12 if _CHROME_RE.search(selector or "") else 1.0


def _count_penalty(total: int) -> float:
    """Uma listagem de produtos tem dezenas de itens, não milhares.

    Sem isto, um contentor com 1086 nós ganhava por tamanho a um com 48 — mesmo
    com a raiz quadrada a amortecer, a diferença de contagem (33× vs 7×) era
    grande de mais para a qualidade dos itens compensar.
    """
    if total <= 200:
        return 1.0
    return max(0.15, (200 / total) ** 0.9)


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
    com_link = com_texto = com_imagem = com_titulo = com_preco = 0
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
        # Um preço dentro do item é a prova mais forte de que é um produto à
        # venda — e é o que distingue o cartão do produto do resto da página.
        try:
            if _PRICE_RE.search(node.html_content or "") or _PRICE_RE.search(texto):
                com_preco += 1
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
        "price_ratio": round(com_preco / amostra, 2),
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
        * (1 + 0.5 * stats.get("price_ratio", 0.0))
        * _chrome_penalty(stats["selector"])
        * _count_penalty(stats["count"])
    )
    if generic:
        score *= 0.6
    return round(score, 1)


def _product_score(stats: Dict[str, Any]) -> float:
    """Avaliação **para produtos**: aqui o sinal decisivo é haver um preço.

    Numa página de loja há sempre listas «parecidas» (recomendados, vistos
    recentemente, menus): o que distingue o catálogo é a fração de itens com um
    valor monetário.
    """
    return round(
        (stats["count"] ** 0.5)
        * (1 + 3.0 * stats.get("price_ratio", 0.0))
        * (1 + 0.8 * stats["title_ratio"])
        * (1 + 0.5 * stats["image_ratio"])
        * (1 + 0.3 * stats["link_ratio"])
        * _chrome_penalty(stats["selector"])
        * _count_penalty(stats["count"]),
        1,
    )


def _usable(stats: Dict[str, Any]) -> bool:
    """Só serve se cada item tiver texto **e** um título plausível."""
    return stats["text_ratio"] >= 0.5 and stats["title_ratio"] >= 0.5 and stats["link_ratio"] >= 0.4


def _usable_produto(stats: Dict[str, Any]) -> bool:
    """Um item de produto: ligação, texto e — sobretudo — **preço**.

    O `_usable` genérico exige títulos com mais de 25 caracteres (faz sentido em
    notícias), o que exclui listas de produtos com nomes curtos («Cabo HDMI 2 m»)
    e fazia a sonda responder «não há produtos» numa página cheia deles. Aqui
    aceita-se também quem tenha preço na maioria dos itens.
    """
    if stats["link_ratio"] < 0.4 or stats["text_ratio"] < 0.5:
        return False
    return stats.get("price_ratio", 0.0) >= 0.4 or stats["title_ratio"] >= 0.5


def _assinaturas(page: Any) -> Dict[Tuple[str, Tuple[str, ...]], int]:
    """Quantas vezes cada padrão «tag + classes» se repete (a base da análise)."""
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
    return signatures


def analyze_page(page: Any, limit: int = 8) -> List[Dict[str, Any]]:
    """Candidatos a seletor de lista, ordenados por utilidade."""
    signatures = _assinaturas(page)

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


def analyze_products(page: Any, limit: int = 8) -> List[Dict[str, Any]]:
    """Candidatos a **lista de produtos**, ordenados pelo preço que trazem.

    Separa-se do `analyze_page` de propósito: uma página de loja tem menus,
    «recomendados» e avisos de cookies que passam o teste genérico; o que
    distingue o catálogo é cada item ter um preço.
    """
    signatures = _assinaturas(page)
    candidatos: Dict[str, Dict[str, Any]] = {}
    for (tag, classes), count in sorted(signatures.items(), key=lambda item: -item[1])[:60]:
        if count < 3 or len(classes) > 4:
            continue
        selector = _node_selector(tag, list(classes))
        if selector in candidatos:
            continue
        stats = _stats_for(page, selector)
        if not stats or not _usable_produto(stats):
            continue
        candidatos[selector] = {**stats, "score": _product_score(stats)}

    # Contentores genéricos (só o `tag`) também podem ser a lista de produtos —
    # por exemplo uma grelha de `<li>` sem classes.
    for tag in _CONTAINER_TAGS:
        if tag in candidatos:
            continue
        stats = _stats_for(page, tag)
        if stats and _usable_produto(stats):
            candidatos[tag] = {**stats, "score": _product_score(stats)}

    ordered = sorted(candidatos.values(), key=lambda c: -c["score"])[: max(1, limit)]
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
    """Escolhe o fornecedor/modelo de IA **configurado na solução**.

    Ordem: o pedido explícito → a predefinição do utilizador → **um fornecedor com
    chave configurada** → só no fim os fornecedores locais sem chave (Ollama).

    O Ollama local tem `key_optional`, por isso era o primeiro a passar o teste e
    ficava sempre escolhido: a sonda esperava 90 s por um modelo de 8B em CPU e
    respondia «IA indisponível», mesmo havendo um fornecedor cloud configurado na
    plataforma. Um fornecedor com chave (do utilizador ou do ambiente) é a prova
    de que alguém o configurou de propósito.
    """
    try:
        from api import providers_service as providers
    except Exception:
        return None, None, None, None

    # Sem utilizador indicado, vale a configuração da plataforma (scripts, CLI).
    user_id = user_id or providers.configured_user_id()

    defaults = (providers.load_user_config(user_id).get("defaults") if user_id else {}) or {}
    ordem: List[str] = []
    if requested:
        ordem.append(requested)
    if defaults.get("provider"):
        ordem.append(str(defaults["provider"]))
    # Depois da predefinição, valem os fornecedores **com chave** (do utilizador ou
    # do ambiente) e só no fim os que não precisam de chave (Ollama local). Não é
    # o mesmo que `key_optional`: o `ollama-cloud` também não exige chave, mas
    # quando está configurado é um modelo remoto — e rápido.
    com_chave: List[str] = []
    sem_chave: List[str] = []
    for spec in providers.PROVIDERS:
        if spec["id"] in ordem:
            continue
        (com_chave if providers.resolve_key(user_id, spec["id"])[0] else sem_chave).append(spec["id"])
    ordem.extend(com_chave)
    ordem.extend(sem_chave)

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
                # Seletor de elemento (sem `::text`/`::attr`) → ler o **texto**,
                # não o HTML: a IA propõe muitas vezes `span.price` e o valor
                # vinha com etiquetas e `data-v-…` (com dígitos) colados.
                "text_only": "::" not in selector,
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
    """Sugere uma definição para um URL: IA primeiro, heurística como rede de segurança.

    Corre num fio próprio: a API síncrona do Playwright recusa ser usada dentro do
    ciclo de eventos do pedido («Sync API inside the asyncio loop»), o que fazia
    falhar os *fetchers* `dynamic` e `stealth` — exatamente os que os sites de
    lojas exigem.
    """
    return await asyncio.to_thread(
        _suggest_source_sync,
        url,
        hint=hint,
        fetcher=fetcher,
        options=options,
        user_id=user_id,
        provider=provider,
        model=model,
        use_ai=use_ai,
        max_pages=max_pages,
    )


def _suggest_source_sync(
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
    """Parte síncrona da sonda genérica (corre num fio próprio)."""
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

    # Um 403/429 não é markup: o site recusou o pedido. Dizer isto evita que se
    # ande a mexer em seletores por causa de um bloqueio.
    status, bloqueio = _diagnostico_resposta(page)
    if bloqueio:
        return {
            "ok": False,
            "url": url,
            "error": bloqueio,
            "http_status": status,
            "blocked": True,
            "analysis": [],
        }

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
        proposal = asyncio.run(
            _ia_com_limite(ai_definition(url, page, analysis, hint=hint, user_id=user_id, provider=provider, model=model))
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
                preview = _validate(trial, max_pages, page)
                result["preview"] = preview
                if preview.get("items"):
                    result["definition"] = trial
                    result["origin"] = "ai"

    # 3. Rede de segurança: heurística (validada).
    if result["definition"] is None and heuristic:
        trial = dict(base, **heuristic)
        preview = _validate(trial, max_pages, page)
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


def _diagnostico_resposta(page: Any) -> Tuple[Optional[int], str]:
    """Explica uma resposta que **não serve** (403/429/…), com o que o site diz.

    Um 403 da Fnac aparecia como «não foi possível identificar uma lista de
    produtos», o que aponta para o *markup* — quando o site simplesmente recusou
    o pedido (`x-datadome: protected`). O utilizador ficava a mexer em seletores
    por causa de um bloqueio.
    """
    status = getattr(page, "status", None)
    if not isinstance(status, int) or status < 400:
        return None, ""
    cabecalhos = getattr(page, "headers", None) or {}
    cabecalhos = {str(k).lower(): str(v) for k, v in dict(cabecalhos).items()} if isinstance(cabecalhos, dict) else {}
    fornecedores = []
    if "datadome" in str(cabecalhos.get("x-datadome", "")).lower() or any("datadome" in k for k in cabecalhos):
        fornecedores.append("DataDome")
    if "cloudflare" in str(cabecalhos.get("server", "")).lower() or "cf-mitigated" in cabecalhos:
        fornecedores.append("Cloudflare")
    if "akamai" in str(cabecalhos.get("server", "")).lower():
        fornecedores.append("Akamai")
    texto = ""
    try:
        texto = " ".join((page.get_all_text() or "").split())[:180]
    except Exception:
        texto = ""
    detalhe = f" (proteção {', '.join(fornecedores)})" if fornecedores else ""
    pista = f' A página diz: «{texto}».' if texto else ""
    return status, (
        f"A página respondeu HTTP {status}{detalhe} — o site recusou o pedido, "
        f"não é problema de seletores.{pista}"
    )


def _validate(definition: Dict[str, Any], max_pages: int = 1, page: Any = None) -> Dict[str, Any]:
    """Corre a definição a sério (sem guardar) para confirmar que extrai itens.

    Com `page`, testa na **página já aberta**: evita um segundo download que, em
    listagens dinâmicas, devolvia outro DOM e dava «0 itens» a uma definição
    válida.
    """
    try:
        if page is not None:
            return scraper.preview_on_page(page, definition, limit=3)
        return scraper.preview_source(definition, limit=3, max_pages=max(1, min(max_pages, 3)))
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "items": [], "total": 0, "pages": 0}


# ---------------------------------------------------------------------------
# Sonda de **produtos** (preço, imagem e descrição)
#
# A sonda genérica acima propõe «título, ligação, data e imagem» — serve para
# notícias. Aqui o objetivo é um **produto à venda**: preço, preço antigo,
# marca, EAN/SKU, disponibilidade, imagem e descrição. A deteção é feita primeiro
# de forma determinística (à procura de valores que *parecem* preços e de blocos
# de texto que *parecem* descrições dentro do item) e só depois se pede ajuda ao
# modelo de IA, sempre com validação a sério antes de devolver.
# ---------------------------------------------------------------------------

#: Um valor monetário: 1.299,00 € · 1299.00 EUR · R$ 1.299,90 · £51.77 · € 799 , 99
#:
#: As lojas portuguesas quebram o preço em vários elementos e o texto sai com
#: espaços («€ 799 , 99»): sem os espaços opcionais à volta do separador
#: decimal, o preço da Worten não era reconhecido.
_PRICE_RE = re.compile(
    r"(?:€|EUR|R\$|US\$|\$|£)\s*\d{1,3}(?:[.\s]\d{3})*(?:\s*[.,]\s*\d{1,2})?"
    r"|\d{1,3}(?:[.\s]\d{3})*(?:\s*[.,]\s*\d{1,2})?\s*(?:€|EUR|R\$|US\$|\$|£)",
    re.IGNORECASE,
)
#: Classes que denunciam o campo (usadas só como preferência, nunca como regra).
_PISTAS_PRECO = ("price", "preco", "preço", "precio", "valor", "pvp", "importe", "amount", "current")
_PISTAS_PRECO_ANTIGO = (
    "old",
    "antes",
    "was",
    "strike",
    "before",
    "list",
    "regular",
    "original",
    "compare",
    "scratched",
    "riscado",
    "riscada",
)
#: Nomes de atributo onde as lojas põem o preço em dados estruturados.
_PISTAS_ATRIBUTO_PRECO = ("price", "preco", "preço", "precio", "importe", "amount", "pvp")
_PISTAS_DESCRICAO = ("descri", "description", "resumo", "summary", "sinopse", "detalhe", "detail", "subtitle", "sub")
_PISTAS_MARCA = ("brand", "marca", "fabricante", "manufacturer")
_PISTAS_EAN = ("ean", "gtin", "barcode", "codigo_barras")
_PISTAS_SKU = ("sku", "ref", "referencia", "referência", "mpn", "codigo", "código")
_PISTAS_DISPONIBILIDADE = ("stock", "disponibilidad", "disponibilidade", "availability", "estado")
_ELEMENTOS_BUSCA = "[class], [itemprop], h1, h2, h3, h4, h5, span, p, a, strong, b, li, dd, dt, del, s"


def _selector_do_no(node: Any) -> str:
    """Seletor CSS de um elemento (tag + até 3 classes estáveis).

    **Atenção ao nome do atributo**: o `Selector` do Scrapling expõe `tag`, não
    `tagname`. Ler o nome errado devolvia `''` e deixava a mineração de campos
    **toda** muda (`_minerar_campo` salta quem não tem seletor) — a sonda chegou
    a dizer «não encontrei preços» numa página cheia deles.
    """
    tag = ""
    for atributo in ("tag", "tagname", "name"):
        valor = getattr(node, atributo, None)
        if isinstance(valor, str) and valor.strip():
            tag = valor.strip().lower()
            break
    if not tag:
        return ""
    try:
        classes = [c for c in (node.attrib.get("class") or "").split() if c]
    except Exception:
        classes = []
    return _node_selector(tag, classes) if classes else tag


def _tem_pista(seletor: str, pistas: Tuple[str, ...]) -> bool:
    minusculas = seletor.lower()
    return any(pista in minusculas for pista in pistas)


def _minerar_campo(
    nodes: List[Any],
    *,
    aceita: Any,
    pistas: Tuple[str, ...] = (),
    atributo: str = "",
    minimo: float = 0.5,
    exigir_pista: bool = False,
) -> Optional[Dict[str, Any]]:
    """Procura, dentro dos itens, o seletor que melhor extrai um valor.

    `aceita(valor, seletor)` decide o que serve (ex.: «parece um preço»). Com
    `exigir_pista=True` só conta quem tenha no seletor uma das `pistas` — é o que
    evita tomar o título por «marca» ou um número qualquer por «EAN».
    """
    votos: Dict[str, int] = {}
    amostras: Dict[str, str] = {}
    com_pista: Dict[str, int] = {}
    itens = nodes[:40]
    for node in itens:
        try:
            elementos = node.css(_ELEMENTOS_BUSCA)
        except Exception:
            continue
        vistos_no_item: set[str] = set()
        for elemento in elementos:
            seletor = _selector_do_no(elemento)
            if not seletor or seletor in vistos_no_item:
                continue
            tem_pista = bool(pistas) and _tem_pista(seletor, pistas)
            if exigir_pista and not tem_pista:
                continue
            valor = ""
            try:
                if atributo:
                    valor = (elemento.attrib.get(atributo) or "").strip()
                else:
                    valor = (elemento.get_all_text() or "").strip()
            except Exception:
                valor = ""
            if not valor or not aceita(valor, seletor):
                continue
            vistos_no_item.add(seletor)
            votos[seletor] = votos.get(seletor, 0) + 1
            amostras.setdefault(seletor, valor[:200])
            if tem_pista:
                com_pista[seletor] = com_pista.get(seletor, 0) + 1

    if not votos:
        return None
    total = max(1, len(itens))

    def pontuacao(item: Tuple[str, int]) -> float:
        seletor, votos_seletor = item
        base = votos_seletor / total
        # A pista de classe desempata: `span.price` ganha a `span.texto`.
        return base + (0.25 if com_pista.get(seletor) else 0.0)

    melhor, votos_melhor = max(votos.items(), key=pontuacao)
    cobertura = round(votos_melhor / total, 2)
    if cobertura < minimo:
        return None
    return {"selector": melhor, "coverage": cobertura, "sample": amostras.get(melhor, "")}


def _parece_preco(valor: str, seletor: str = "") -> bool:
    return bool(_PRICE_RE.search(valor or ""))


#: Preço **sem símbolo** («799,99», «1.299,00»): acontece quando o `€` está num
#: elemento à parte. Exige duas decimais (o que separa de percentagens e de
#: «10x sem juros») e uma pista de preço no seletor.
def _parece_preco_sem_simbolo(valor: str, seletor: str = "") -> bool:
    texto = _sem_espacos(str(valor or ""))
    if not re.fullmatch(r"\d{1,3}(?:[.\s]\d{3})*[.,]\d{2}", texto):
        return False
    return bool(pistas_ou_vazio(seletor))


def _sem_espacos(texto: str) -> str:
    return re.sub(r"\s+", "", texto)


def pistas_ou_vazio(seletor: str) -> bool:
    """`True` quando o seletor tem pista de preço (ou não há seletor nenhum)."""
    return not seletor or _tem_pista(seletor, _PISTAS_PRECO)


def _seletor_do_atributo(base: str, atributos: Dict[str, Any], nome: str) -> str:
    """Seletor **específico** para um atributo de preço.

    Sem o atributo que dá a pista, `meta::attr(content)` é ambíguo: num cartão há
    `<meta itemprop="priceCurrency" content="EUR">` **e**
    `<meta itemprop="price" content="799.99">` — e o seletor por tag apanha a
    moeda em vez do preço (foi o que aconteceu na Worten).
    """
    for pista in ("itemprop", "property", "data-price", "data-cnstrc-item-price", "data-product-price"):
        if atributos.get(pista) or (pista.startswith("data-") and pista in atributos):
            if pista in ("itemprop", "property"):
                return f"{base}[{pista}='{atributos[pista]}']::attr({nome})"
            return f"{base}[{pista}]::attr({nome})"
    return f"{base}::attr({nome})"


def _preco_por_atributo(nodes: List[Any], minimo: float = 0.5) -> Optional[Dict[str, Any]]:
    """Preço em **dados estruturados** (itemprop/data-*), quando existir.

    É a via mais fiável: o valor está isolado e no formato certo. Na Worten, por
    exemplo, o cartão traz `data-cnstrc-item-price="799.99"`, enquanto o texto do
    preço vem partido em `€`, `799` e `sup.99`.
    """
    votos: Dict[str, int] = {}
    amostras: Dict[str, str] = {}
    itens = nodes[:40]
    for node in itens:
        vistos_no_item: set[str] = set()
        alvos: List[Any] = []
        try:
            alvos = list(node.css("[itemprop], [data-price], meta, [content]"))
        except Exception:
            alvos = []
        for elemento in alvos:
            try:
                atributos = dict(elemento.attrib or {})
            except Exception:
                continue
            base = _selector_do_no(elemento)
            if not base:
                continue
            # A pista pode estar no nome do atributo (`data-price`), no `itemprop`
            # (`itemprop="price" content="799.99"`) ou na própria classe.
            contexto = " ".join(
                str(valor)
                for chave, valor in atributos.items()
                if chave in ("itemprop", "property", "name", "id", "class")
            )
            for nome, valor in atributos.items():
                if not (_tem_pista(nome, _PISTAS_ATRIBUTO_PRECO) or _tem_pista(contexto, _PISTAS_ATRIBUTO_PRECO)):
                    continue
                texto = str(valor or "").strip()
                # Aceita «799.99», «1299.00», «1.299,00», «1 299,00».
                if not re.fullmatch(r"\d+(?:[.\s]\d{3})*(?:[.,]\d{1,2})?", texto):
                    continue
                if not _preco_positivo(texto):
                    continue
                seletor = _seletor_do_atributo(base, atributos, nome)
                if seletor in vistos_no_item:
                    continue
                vistos_no_item.add(seletor)
                votos[seletor] = votos.get(seletor, 0) + 1
                amostras.setdefault(seletor, texto[:60])
    if not votos:
        return None
    total = max(1, len(itens))
    melhor, contagem = max(votos.items(), key=lambda item: item[1])
    cobertura = round(contagem / total, 2)
    if cobertura < minimo:
        return None
    return {"selector": melhor, "coverage": cobertura, "sample": amostras.get(melhor, "")}


def _preco_positivo(valor: str) -> bool:
    """Um preço a sério não é zero (nem «0,00» de um campo por preencher)."""
    texto = str(valor or "").strip().replace(" ", "")
    if not texto:
        return False
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto) > 0
    except ValueError:
        return False


#: Seletores de preço por *parte* do nome da classe: o seletor exato falha porque
#: as lojas juntam classes que variam de cartão para cartão (descontos, tamanhos),
#: ficando `span.price--md.price--mixed.price--B` — que só casa em alguns itens.
#:
#: Sem `::text` de propósito: o preço vem **partido** em elementos filhos
#: (`€<span>799</span><sup>,99</sup>`), por isso é o texto completo do elemento
#: que interessa — o `::text` devolvia só fragmentos como `','`.
_SELETORES_PRECO = (
    "[itemprop='price']",
    "[class*='price__numbers']",
    "[class*='current-price']",
    "[class*='price']",
    "[class*='preco']",
    "[class*='preço']",
    "[class*='precio']",
    "[class*='valor']",
    ".price",
    ".preco",
)
_SELETORES_PRECO_ANTIGO = (
    "[class*='scratched']",
    "[class*='old-price']",
    "[class*='price-old']",
    "[class*='before']",
    "[class*='antes']",
    "[class*='pvp-antes']",
    "s",
    "del",
)


def _valores_do_seletor(node: Any, seletor: str) -> List[str]:
    """Valores textuais de um seletor: `::text`, `::attr(x)` ou o texto completo.

    Um seletor «de elemento» (sem `::`) é lido com `get_all_text()` — é o que
    apanha preços partidos em filhos. Sem esta distinção, o preço da Worten era
    lido como `','`.
    """
    valores: List[str] = []
    try:
        if "::text" in seletor or "::attr(" in seletor:
            valores = [str(v).strip() for v in node.css(seletor).getall() if str(v).strip()]
        else:
            for elemento in node.css(seletor):
                texto = (elemento.get_all_text() or "").strip()
                if texto:
                    valores.append(texto)
    except Exception:
        return []
    return valores


def _melhor_seletor_com_valor(
    nodes: List[Any],
    candidatos: Tuple[str, ...],
    aceita: Any,
    minimo: float = 0.5,
) -> Optional[Dict[str, Any]]:
    """Seletor com melhor cobertura **entre candidatos fixos**, já validado.

    Ao contrário de `_minerar_campo` (que infere o seletor a partir do que existe
    em cada item), aqui testam-se seletores conhecidos por nome de classe e
    escolhe-se o que cobre mais itens com um valor que passa no `aceita`.
    """
    melhor = ""
    melhor_cobertura = 0.0
    amostra = ""
    itens = nodes[:40]
    for seletor in candidatos:
        ok = 0
        exemplo = ""
        for node in itens:
            valor = next((v for v in _valores_do_seletor(node, seletor) if aceita(v, seletor)), "")
            if valor:
                ok += 1
                exemplo = exemplo or valor
        cobertura = ok / max(1, len(itens))
        if cobertura > melhor_cobertura:
            melhor, melhor_cobertura, amostra = seletor, cobertura, exemplo
    if not melhor or melhor_cobertura < minimo:
        return None
    return {"selector": melhor, "coverage": round(melhor_cobertura, 2), "sample": amostra}


def _parece_descricao(valor: str, seletor: str = "") -> bool:
    texto = (valor or "").strip()
    if len(texto) < 40 or _parece_preco(texto):
        return False
    return len(texto) <= 1200


def product_heuristic_definition(url: str, page: Any, analysis: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Definição determinística de **produto**, a partir do melhor contentor.

    Devolve também `campos` — o resumo do que foi encontrado (para a interface
    mostrar o que a sonda viu antes de guardar seja o que for).

    A escolha do contentor é feita com `_product_score` (pesa o preço em cada
    item), e não pela ordem genérica da análise: numa página de loja, a lista
    «mais repetida» é muitas vezes um menu ou o aviso de cookies, e escolhê-la
    dava uma sonda que «não encontrava preços» numa página cheia deles.
    """
    if not analysis:
        return {}
    ordenados = sorted(analysis, key=_product_score, reverse=True)
    best = ordenados[0]
    seletor_lista = best["selector"]
    try:
        nodes = list(page.css(seletor_lista))
    except Exception:
        nodes = []
    if not nodes:
        return {}

    titulo = _best_selector(page, list(_TITLE_SELECTORS), nodes)
    link = _best_selector(
        page,
        ["h3 a::attr(href)", "h2 a::attr(href)", "a[itemprop='url']::attr(href)", "h1 a::attr(href)", "a::attr(href)"],
        nodes,
    )
    imagem = _best_selector(
        page,
        [
            "img::attr(src)",
            "img::attr(data-src)",
            "img::attr(data-original)",
            "img::attr(srcset)",
            "source::attr(srcset)",
            "[itemprop='image']::attr(src)",
        ],
        nodes,
    )
    preco = _melhor_seletor_com_valor(nodes, _SELETORES_PRECO, aceita=_parece_preco)
    if preco is None:
        preco = _minerar_campo(nodes, aceita=_parece_preco, pistas=_PISTAS_PRECO)
    if preco is None:
        # Segunda passagem: sem símbolo monetário (o «€» está noutro elemento),
        # mas com duas decimais e uma classe que diz «price». Só agora, para o
        # símbolo continuar a ser a prova preferida.
        preco = _melhor_seletor_com_valor(nodes, _SELETORES_PRECO, aceita=_parece_preco_sem_simbolo)
    if preco is None:
        preco = _minerar_campo(nodes, aceita=_parece_preco_sem_simbolo, pistas=_PISTAS_PRECO)
    if preco is None:
        # Último recurso: o preço em dados estruturados. Vem **antes** de
        # ser um número isolado, mas o seletor por tag (`meta::attr(content)`)
        # tanto apanha o preço como a moeda («EUR») — por isso não decide.
        preco = _preco_por_atributo(nodes)
    antigo = _melhor_seletor_com_valor(nodes, _SELETORES_PRECO_ANTIGO, aceita=_parece_preco)
    if antigo is None:
        antigo = _minerar_campo(
            nodes,
            aceita=lambda valor, seletor: _parece_preco(valor) and _tem_pista(seletor, _PISTAS_PRECO_ANTIGO),
            pistas=_PISTAS_PRECO_ANTIGO,
            minimo=0.3,
        )
    descricao = _minerar_campo(nodes, aceita=_parece_descricao, pistas=_PISTAS_DESCRICAO, minimo=0.4)
    marca = _minerar_campo(
        nodes, aceita=lambda v, s: 1 < len(v) < 60, pistas=_PISTAS_MARCA, minimo=0.3, exigir_pista=True
    )
    ean = _minerar_campo(
        nodes,
        aceita=lambda v, s: bool(re.fullmatch(r"[0-9\-\s]{8,14}", v.strip())),
        pistas=_PISTAS_EAN,
        minimo=0.3,
        exigir_pista=True,
    )
    sku = _minerar_campo(
        nodes, aceita=lambda v, s: 2 < len(v) < 60, pistas=_PISTAS_SKU, minimo=0.3, exigir_pista=True
    )
    disponibilidade = _minerar_campo(
        nodes,
        aceita=lambda v, s: 3 < len(v) < 60,
        pistas=_PISTAS_DISPONIBILIDADE,
        minimo=0.3,
        exigir_pista=True,
    )

    fields: List[Dict[str, Any]] = []
    if titulo:
        fields.append(
            {"name": "titulo", "label": "Título", "selector": titulo, "type": "css", "max_length": 500, "text_only": True}
        )
    if preco:
        fields.append(
            {
                "name": "preco",
                "label": "Preço",
                "selector": preco["selector"],
                "type": "css",
                "max_length": 40,
                "text_only": True,
            }
        )
    if antigo:
        fields.append(
            {
                "name": "preco_antigo",
                "label": "Preço antes",
                "selector": antigo["selector"],
                "type": "css",
                "max_length": 40,
                "text_only": True,
            }
        )
    if link:
        fields.append({"name": "url", "label": "Ligação", "selector": link, "type": "css", "max_length": 1000})
    if imagem:
        fields.append({"name": "imagem", "label": "Imagem", "selector": imagem, "type": "css", "max_length": 1000})
    if descricao:
        fields.append(
            {
                "name": "descricao",
                "label": "Descrição",
                "selector": descricao["selector"],
                "type": "css",
                "max_length": 1200,
                "text_only": True,
            }
        )
    if marca:
        fields.append(
            {"name": "marca", "label": "Marca", "selector": marca["selector"], "type": "css", "max_length": 120, "text_only": True}
        )
    if ean:
        fields.append(
            {"name": "ean", "label": "EAN", "selector": ean["selector"], "type": "css", "max_length": 40, "text_only": True}
        )
    if sku:
        fields.append(
            {
                "name": "sku",
                "label": "Referência",
                "selector": sku["selector"],
                "type": "css",
                "max_length": 80,
                "text_only": True,
            }
        )
    if disponibilidade:
        fields.append(
            {
                "name": "disponibilidade",
                "label": "Disponibilidade",
                "selector": disponibilidade["selector"],
                "type": "css",
                "max_length": 120,
                "text_only": True,
            }
        )
    if not fields:
        return {}

    definicao = {
        "name": _title_for(url, page),
        "url": url,
        "list": {"selector": seletor_lista, "type": "css"},
        "fields": fields,
        "pagination": {"selector": "", "type": "css", "attr": "href", "max_pages": 1},
        "id_fields": ["url"] if link else (["titulo"] if titulo else []),
        "title_field": "titulo" if titulo else fields[0]["name"],
    }
    return {
        **definicao,
        "campos": {
            "preco": preco,
            "preco_antigo": antigo,
            "descricao": descricao,
            "imagem": {"selector": imagem} if imagem else None,
            "titulo": {"selector": titulo} if titulo else None,
        },
    }


def _product_prompt(url: str, page_title: str, analysis: List[Dict[str, Any]], sample: str, hint: str) -> str:
    """Prompt orientado a **produto** (preço, imagem e descrição são obrigatórios)."""
    candidatos = [
        {k: c[k] for k in ("selector", "count", "text_ratio", "link_ratio", "image_ratio", "samples") if k in c}
        for c in analysis[:6]
    ]
    return (
        "És um especialista em web scraping de lojas online. Vais analisar uma página de listagem de "
        "produtos e devolver a definição de extração em JSON.\n\n"
        f"URL: {url}\nTítulo da página: {page_title}\n"
        f"Objetivo: {hint or 'recolher os produtos desta listagem com preço, imagem e descrição'}\n\n"
        "Candidatos a contentor de produto (já medidos; text_ratio/link_ratio = fração com texto/ligação):\n"
        f"{json.dumps(candidatos, ensure_ascii=False, indent=1)}\n\n"
        "Amostra do HTML de UM produto (usa-a para descobrir a estrutura interna):\n"
        f"{sample}\n\n"
        "Obrigatório: encontra o preço, a imagem e a descrição. Se a descrição não existir no item, "
        "usa o subtítulo ou a categoria como descrição curta.\n\n"
        "Devolve APENAS este JSON:\n"
        "{\n"
        '  "list": {"selector": "<css do item de produto>", "type": "css"},\n'
        '  "fields": [\n'
        '    {"name": "titulo", "label": "Título", "selector": "<css relativo ao item>", "type": "css"},\n'
        '    {"name": "preco", "label": "Preço", "selector": "<css>", "type": "css"},\n'
        '    {"name": "preco_antigo", "label": "Preço antes", "selector": "<css>", "type": "css"},\n'
        '    {"name": "imagem", "label": "Imagem", "selector": "<css>", "type": "css"},\n'
        '    {"name": "descricao", "label": "Descrição", "selector": "<css>", "type": "css"},\n'
        '    {"name": "url", "label": "Ligação", "selector": "<css>", "type": "css"},\n'
        '    {"name": "marca", "label": "Marca", "selector": "<css>", "type": "css"},\n'
        '    {"name": "ean", "label": "EAN", "selector": "<css>", "type": "css"},\n'
        '    {"name": "disponibilidade", "label": "Disponibilidade", "selector": "<css>", "type": "css"}\n'
        "  ],\n"
        '  "id_fields": ["url"],\n'
        '  "title_field": "titulo",\n'
        '  "pagination": {"selector": "<css do botão seguinte>", "type": "css", "attr": "href", "max_pages": 1},\n'
        '  "notes": "<o que assumiste e o que pode falhar>"\n'
        "}\n\n"
        "Regras: só CSS; `::text` para texto e `::attr(nome)` para atributos; os seletores dos campos são "
        "relativos ao item; o preço tem de ser o **preço atual** (não o antigo); omite os campos que não existam."
    )


async def _product_ai_definition(
    url: str,
    page: Any,
    analysis: List[Dict[str, Any]],
    *,
    hint: str = "",
    user_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Pede a definição de produto ao modelo (mesmo mecanismo da sonda genérica)."""
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
    prompt = _product_prompt(url, page_title, analysis, _sample_html(best) if best else "", hint)
    try:
        answer = await cloud_chat.complete_answer(
            provider=provider_id,
            spec=spec,
            model=model_id or spec.get("default_model") or "",
            messages=[{"role": "user", "content": prompt}],
            api_key=key,
            temperature=0.1,
            max_tokens=1400,
        )
    except Exception as exc:
        logger.warning("Sonda de produtos: IA falhou (%s): %s", provider_id, exc)
        return {"definition": None, "ai": None, "error": f"{type(exc).__name__}: {exc}"}

    data = _parse_json(answer)
    if not data:
        return {"definition": None, "ai": None, "error": "A IA não devolveu JSON válido.", "raw": (answer or "")[:500]}
    definicao: Dict[str, Any] = {
        "list": data.get("list") or {},
        "fields": data.get("fields") or [],
        "pagination": data.get("pagination") or {"selector": "", "type": "css", "attr": "href", "max_pages": 1},
    }
    if data.get("id_fields"):
        definicao["id_fields"] = data["id_fields"]
    if data.get("title_field"):
        definicao["title_field"] = data["title_field"]
    return {
        "definition": definicao,
        "ai": {
            "provider": provider_id,
            "provider_label": spec.get("label") or provider_id,
            "model": model_id,
            "notes": str(data.get("notes") or "").strip(),
        },
        "error": None,
    }


async def suggest_product_source(
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
    """Sonda uma **página de produtos**: preço, imagem e descrição.

    Ordem: análise determinística → proposta da IA (se pedida e configurada) →
    validação a sério de cada proposta; a heurística de produto é a rede de
    segurança, para a sonda nunca devolver «nada encontrado» sem explicação.
    Corre num fio próprio (ver `suggest_source`) por causa da API do Playwright.
    """
    return await asyncio.to_thread(
        _suggest_product_source_sync,
        url,
        hint=hint,
        fetcher=fetcher,
        options=options,
        user_id=user_id,
        provider=provider,
        model=model,
        use_ai=use_ai,
        max_pages=max_pages,
    )


def _suggest_product_source_sync(
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
    """Parte síncrona da sonda de produtos (corre num fio próprio)."""
    base: Dict[str, Any] = {
        "url": url,
        "fetcher": fetcher or "http",
        "enabled": False,
        # Nos fetchers de browser, esperar pela rede parada: muitas lojas só
        # escrevem o preço depois de o JavaScript dele carregar.
        "options": options or ({"network_idle": True} if (fetcher or "http") != "http" else {}),
        "respect_robots": True,
        "schedule": {"cron": "", "timezone": "Europe/Lisbon"},
        "tags": [],
    }
    try:
        with scraper._open_session(base["fetcher"], base["options"]) as session:
            page = scraper._session_fetch(session, base["fetcher"], url, base["options"])
        if page is None:
            raise RuntimeError("A página não devolveu conteúdo (pode estar protegida ou exigir JavaScript).")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}", "analysis": []}

    # Um 403/429 não é markup: o site recusou o pedido (Fnac = DataDome).
    status, bloqueio = _diagnostico_resposta(page)
    if bloqueio:
        return {
            "ok": False,
            "url": url,
            "error": bloqueio,
            "http_status": status,
            "blocked": True,
            "analysis": [],
        }

    analysis = analyze_products(page, limit=8)
    if not analysis:
        # Rede de segurança: páginas sem preço (catálogos «a pedir orçamento»)
        # ainda podem ter uma lista que vale a pena propor.
        analysis = analyze_page(page, limit=8)
    if not analysis:
        return {
            "ok": False,
            "url": url,
            "error": "Não foi possível identificar uma lista de produtos nesta página.",
            "analysis": [],
        }
    # Ordenar por utilidade **para produtos** antes de tudo o resto: é esta a
    # ordem que a IA vê nos candidatos e o HTML de amostra que lhe é enviado.
    analysis = sorted(analysis, key=_product_score, reverse=True)

    heuristic = product_heuristic_definition(url, page, analysis)
    resultado: Dict[str, Any] = {
        "ok": True,
        "url": url,
        "title": _title_for(url, page),
        "analysis": [{k: v for k, v in c.items() if k != "node"} for c in analysis],
        "heuristic": {k: v for k, v in heuristic.items() if k != "campos"},
        "heuristic_fields": heuristic.get("campos") or {},
        "definition": None,
        "origin": None,
        "ai": None,
        "ai_error": None,
        "preview": None,
        "tried": [],
    }

    if use_ai:
        proposta = asyncio.run(
            _ia_com_limite(
                _product_ai_definition(url, page, analysis, hint=hint, user_id=user_id, provider=provider, model=model)
            )
        )
        resultado["ai"] = proposta.get("ai")
        resultado["ai_error"] = proposta.get("error")
        candidata = proposta.get("definition")
        if candidata:
            fields = _clean_ai_fields(candidata)
            seletor_lista = str((candidata.get("list") or {}).get("selector") or "").strip()
            if seletor_lista and fields:
                ensaio = {
                    **base,
                    "name": _title_for(url, page),
                    "list": {"selector": seletor_lista, "type": str((candidata.get("list") or {}).get("type") or "css")},
                    "fields": fields,
                    "pagination": candidata.get("pagination") or {"max_pages": 1},
                    "id_fields": candidata.get("id_fields") or ["url"],
                    "title_field": candidata.get("title_field") or fields[0]["name"],
                }
                previsao = _validate(ensaio, max_pages, page)
                resultado["tried"].append({"origin": "ia", "items": len(previsao.get("items") or [])})
                resultado["preview"] = previsao
                if previsao.get("items"):
                    resultado["definition"] = ensaio
                    resultado["origin"] = "ia"

    if resultado["definition"] is None:
        ensaio = {**base, **heuristic}
        ensaio.pop("campos", None)
        if ensaio.get("list", {}).get("selector") and ensaio.get("fields"):
            previsao = _validate(ensaio, max_pages, page)
            resultado["tried"].append({"origin": "heuristica", "items": len(previsao.get("items") or [])})
            if resultado["preview"] is None or previsao.get("items"):
                resultado["preview"] = previsao
            if previsao.get("items"):
                resultado["definition"] = ensaio
                resultado["origin"] = "heuristica"
        if resultado["definition"] is None and not resultado.get("error"):
            resultado["ok"] = False
            resultado["error"] = (
                resultado["preview"].get("error")
                if isinstance(resultado.get("preview"), dict) and resultado["preview"].get("error")
                else "Nenhuma proposta extraiu produtos desta página (pode estar protegida ou precisar de browser)."
            )

    return resultado

