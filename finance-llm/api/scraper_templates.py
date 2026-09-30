"""Templates de sites para a recolha («scraping») do IQ OS.

Cada template é uma **definição de fonte pronta a usar** para um site concreto:
o URL da lista, o seletor dos cartões, os campos a extrair, a paginação, o
agendamento sugerido e — quando o site é de notícias — o seletor do corpo do
artigo, para que a recolha guarde também o **texto integral** (é esse texto que
a pesquisa do módulo e o RAG conseguem ler).

Porquê templates e não só «definir fonte»
-----------------------------------------
Escrever seletores à mão obriga a abrir o inspetor do browser e a perceber a
estrutura de cada site. Os templates trazem esse trabalho feito e verificado
(ver `docs/recolha-scraping.md`): escolhe-se o site, confirma-se o teste e a
recolha fica agendada.

Os seletores são os do HTML publicado, sem `dynamic` sempre que possível: o
fetcher `http` é muito mais rápido e não precisa de browsers. Quando o site
fecha a porta ao HTTP simples (proteção anti-bot), o template pede
`dynamic`/`stealth` e di-lo em `requires`.

Manutenção
----------
Os sites mudam de `class` com os redesenhamos. Quando um template deixar de
trazer itens, basta ajustar aqui o seletor e revalidar com
`python _test_scraper_templates.py` (mostra, por template, itens e cobertura de
cada campo).
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

from api import scraper_service as scraper

logger = logging.getLogger(__name__)

#: Categorias da galeria (a ordem é a que a UI usa).
CATEGORIES = [
    "Imprensa económica (Portugal)",
    "Imprensa económica (Espanha)",
    "Mercados (internacional)",
    "Diretórios de empresas",
    "Sites de exemplo",
]

#: Valores de `requires` que implicam browsers instalados (`scrapling install`).
BROWSER_REQUIREMENTS = ("browser", "dynamic", "stealth")


def _field(
    name: str,
    label: str,
    selector: str,
    *,
    cast: str = "text",
    attr: Optional[str] = None,
    all_: bool = False,
    max_length: int = 2000,
    selectors: Optional[List[str]] = None,
    regex: Optional[str] = None,
) -> Dict[str, Any]:
    """Campo de um template (mesma forma que o módulo de recolha usa).

    `selectors` serve os sites que desenham o mesmo dado de duas maneiras: a
    extração usa o primeiro seletor que devolver valor.

    `regex` aplica-se sobre o valor devolvido pelo seletor (útil para tirar
    um NIF ou ID de um `href` antes de o campo ser devolvido).
    """
    alternativos = [s for s in (selectors or []) if s]
    if selector and selector not in alternativos:
        alternativos.insert(0, selector)
    field: Dict[str, Any] = {
        "name": name,
        "label": label,
        "selector": alternativos[0] if alternativos else selector,
        "type": "css",
        "cast": cast,
        "all": all_,
        "max_length": max_length,
    }
    if len(alternativos) > 1:
        field["selectors"] = alternativos
    if attr:
        field["attr"] = attr
    if regex:
        field["regex"] = regex
    return field


def _detail(selector: str, *, max_items: int = 20, delay: float = 0.6) -> Dict[str, Any]:
    """Bloco do texto integral: o corpo do artigo na página de detalhe."""
    return {
        "enabled": bool(selector),
        "selector": selector,
        "max_items": max_items,
        "delay": delay,
        "max_chars": 20000,
    }


def _sentiment(*, max_items: int = 8, field: str = "text", engine: str = "auto", min_chars: int = 120) -> Dict[str, Any]:
    """Bloco do sentimento por notícia (IA quando houver; léxico local como reserva)."""
    return {
        "enabled": True,
        "engine": engine,
        "provider": "",
        "model": "",
        "max_items": max_items,
        "field": field,
        "min_chars": min_chars,
    }


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------
TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "jornal-economico",
        "name": "Jornal Económico",
        "site": "jornaleconomico.sapo.pt",
        "category": "Imprensa económica (Portugal)",
        "description": "Destaques da primeira página do Jornal Económico, com categoria, título, ligação e imagem.",
        "tags": ["noticias", "economia", "jornal-economico"],
        "requires": "http",
        "notes": "WordPress/Sapo: os cartões são `div.je-article.je-blog-block`. O texto integral vem do maior painel `.uk-panel.uk-margin` da notícia.",
        "source": {
            "name": "Jornal Económico",
            "description": "Destaques da primeira página (categoria, título, ligação, imagem e texto integral).",
            "url": "https://jornaleconomico.sapo.pt/",
            "enabled": False,
            "fetcher": "http",
            "list": {"selector": "div.je-article.je-blog-block", "type": "css"},
            "fields": [
                _field("secao", "Secção", ".je-cat a::text", max_length=120),
                _field("titulo", "Título", "h3 a::text", max_length=400),
                _field("url", "Ligação", "h3 a::attr(href)", max_length=1024),
                _field("imagem", "Imagem", "img::attr(src)", max_length=1024),
            ],
            "pagination": {"selector": "", "type": "css", "attr": "href", "max_pages": 1},
            "options": {"impersonate": "chrome", "timeout": 30},
            "schedule": {"cron": "0 */6 * * *", "timezone": "Europe/Lisbon"},
            "respect_robots": True,
            "tags": ["noticias", "economia", "jornal-economico"],
            "id_fields": ["url"],
            "title_field": "titulo",
            "detail": _detail("div.uk-panel.uk-margin", max_items=15),
            "sentiment": _sentiment(),
        },
    },
    {
        "id": "eco",
        "name": "ECO (Sapo)",
        "site": "eco.sapo.pt",
        "category": "Imprensa económica (Portugal)",
        "description": "Notícias do ECO: título, ligação, data, autor, resumo e texto integral.",
        "tags": ["noticias", "economia", "eco"],
        "requires": "http",
        "notes": "Os cartões (`article.card`) têm a data em `time[datetime]`; o corpo está em `div.entry__content`.",
        "source": {
            "name": "ECO",
            "description": "Destaques do ECO (título, ligação, data, autor, resumo e texto integral).",
            "url": "https://eco.sapo.pt/",
            "enabled": False,
            "fetcher": "http",
            "list": {"selector": "article.card", "type": "css"},
            "fields": [
                _field("titulo", "Título", "h3 a::text", max_length=400),
                _field("url", "Ligação", "h3 a::attr(href)", max_length=1024),
                _field("resumo", "Resumo", "p.card__lead::text", max_length=2000),
                _field("data", "Data", "time::attr(datetime)", cast="date", max_length=60),
                _field("autor", "Autor", ".meta__info::text", max_length=160),
                _field("imagem", "Imagem", "img::attr(src)", max_length=1024),
            ],
            "pagination": {"selector": "", "type": "css", "attr": "href", "max_pages": 1},
            "options": {"impersonate": "chrome", "timeout": 30},
            "schedule": {"cron": "0 */6 * * *", "timezone": "Europe/Lisbon"},
            "respect_robots": True,
            "tags": ["noticias", "economia", "eco"],
            "id_fields": ["url"],
            "title_field": "titulo",
            "summary_field": "resumo",
            "detail": _detail("div.entry__content", max_items=20),
            "sentiment": _sentiment(),
        },
    },
    {
        "id": "dinheiro-vivo",
        "name": "Dinheiro Vivo",
        "site": "dinheirovivo.pt",
        "category": "Imprensa económica (Portugal)",
        "description": "Notícias do Dinheiro Vivo: secção, título, ligação, data e autor.",
        "tags": ["noticias", "economia", "dinheiro-vivo"],
        "requires": "http",
        "notes": "Página de notícia é renderizada no cliente: o template recolhe a lista (sem texto integral).",
        "source": {
            "name": "Dinheiro Vivo",
            "description": "Destaques do Dinheiro Vivo (secção, título, ligação, data e autor).",
            "url": "https://www.dinheirovivo.pt/",
            "enabled": False,
            "fetcher": "http",
            "list": {"selector": "div.arr--default-story-content", "type": "css"},
            "fields": [
                _field("secao", "Secção", ".section-tag::text", max_length=120),
                _field("titulo", "Título", "h3::text", max_length=400),
                _field("url", "Ligação", "div.arr--headline a::attr(href)", max_length=1024),
                _field("data", "Data", "time::attr(datetime)", cast="date", max_length=60),
                _field("autor", "Autor", ".author-name::text", max_length=160),
            ],
            "pagination": {"selector": "", "type": "css", "attr": "href", "max_pages": 1},
            "options": {"impersonate": "chrome", "timeout": 30},
            "schedule": {"cron": "0 */6 * * *", "timezone": "Europe/Lisbon"},
            "respect_robots": True,
            "tags": ["noticias", "economia", "dinheiro-vivo"],
            "id_fields": ["url"],
            "title_field": "titulo",
            "detail": _detail("", max_items=0),
            "sentiment": _sentiment(min_chars=60),
        },
    },
    {
        "id": "observador-economia",
        "name": "Observador · Economia",
        "site": "observador.pt",
        "category": "Imprensa económica (Portugal)",
        "description": "Secção de Economia do Observador: tópico, título, ligação, data, entrada e texto integral.",
        "tags": ["noticias", "economia", "observador"],
        "requires": "http",
        "notes": "Corpo do artigo em `div.article-body-content`.",
        "source": {
            "name": "Observador · Economia",
            "description": "Notícias da secção de Economia do Observador (com texto integral).",
            "url": "https://observador.pt/seccao/economia/",
            "enabled": False,
            "fetcher": "http",
            "list": {"selector": "div.mod.mod-posttype-post.from-blade", "type": "css"},
            "fields": [
                _field("topico", "Tópico", "a.topic::text", max_length=160),
                _field("titulo", "Título", "h1.title a::text", max_length=400),
                _field("url", "Ligação", "h1.title a::attr(href)", max_length=1024),
                _field("data", "Data", "time::attr(datetime)", cast="date", max_length=60),
                _field("resumo", "Entrada", "div.lead::text", max_length=2000),
                _field("imagem", "Imagem", "img::attr(src)", max_length=1024),
            ],
            "pagination": {"selector": "", "type": "css", "attr": "href", "max_pages": 1},
            "options": {"impersonate": "chrome", "timeout": 30},
            "schedule": {"cron": "0 */6 * * *", "timezone": "Europe/Lisbon"},
            "respect_robots": True,
            "tags": ["noticias", "economia", "observador"],
            "id_fields": ["url"],
            "title_field": "titulo",
            "summary_field": "resumo",
            "detail": _detail("div.article-body-content", max_items=20),
            "sentiment": _sentiment(),
        },
    },
    {
        "id": "publico-economia",
        "name": "Público · Economia",
        "site": "publico.pt",
        "category": "Imprensa económica (Portugal)",
        "description": "Destaques de Economia do Público: etiqueta, título, ligação, entrada, autor, data e texto integral.",
        "tags": ["noticias", "economia", "publico"],
        "requires": "http",
        "notes": "Data em `time[datetime]` no formato RFC 822; o corpo está em `div.story__body`.",
        "source": {
            "name": "Público · Economia",
            "description": "Notícias de Economia do Público (com texto integral).",
            "url": "https://www.publico.pt/economia",
            "enabled": False,
            "fetcher": "http",
            "list": {"selector": "li.headline-list__item.media-object", "type": "css"},
            "fields": [
                _field("etiqueta", "Etiqueta", "h5.kicker::text", max_length=160),
                _field("titulo", "Título", "h4.headline::text", max_length=400),
                _field("url", "Ligação", "a::attr(href)", max_length=1024),
                _field("resumo", "Entrada", "p.lead::text", max_length=2000),
                _field("autor", "Autor", "span.byline__name::text", max_length=160),
                _field("data", "Data", "time.dateline::attr(datetime)", cast="date", max_length=60),
            ],
            "pagination": {"selector": "", "type": "css", "attr": "href", "max_pages": 1},
            "options": {"impersonate": "chrome", "timeout": 30},
            "schedule": {"cron": "0 */6 * * *", "timezone": "Europe/Lisbon"},
            "respect_robots": True,
            "tags": ["noticias", "economia", "publico"],
            "id_fields": ["url"],
            "title_field": "titulo",
            "summary_field": "resumo",
            "detail": _detail("div.story__body", max_items=20),
            "sentiment": _sentiment(),
        },
    },
    {
        "id": "jornal-de-negocios",
        "name": "Jornal de Negócios",
        "site": "jornaldenegocios.pt",
        "category": "Imprensa económica (Portugal)",
        "description": "Destaques do Jornal de Negócios: título, ligação, entrada, autor, hora e imagem.",
        "tags": ["noticias", "economia", "jornal-de-negocios"],
        "requires": "browser",
        "notes": "O site fecha o HTTP simples (erro de ligação); precisa do fetcher «Browser dinâmico» e das ligações relativas resolvidas contra o domínio. As imagens usam carregamento preguiçoso (`data-src`).",
        "source": {
            "name": "Jornal de Negócios",
            "description": "Destaques do Jornal de Negócios (recolha com browser).",
            "url": "https://www.jornaldenegocios.pt/",
            "enabled": False,
            "fetcher": "dynamic",
            "list": {"selector": "article.destaque", "type": "css"},
            "fields": [
                _field("titulo", "Título", "h2 a::text", max_length=400),
                _field("url", "Ligação", "h2 a::attr(href)", max_length=1024),
                _field("resumo", "Entrada", "p.lead::text", max_length=2000),
                _field("autor", "Autor", ".data_autor a::text", max_length=160),
                _field("hora", "Hora", "span.time::text", max_length=40),
                # O `src` das imagens é um GIF transparente de 1×1 (carregamento
                # preguiçoso); a imagem real está em `data-src`.
                _field("imagem", "Imagem", "img::attr(data-src)", selectors=["img::attr(data-src)", "img::attr(src)"], max_length=1024),
            ],
            "pagination": {"selector": "", "type": "css", "attr": "href", "max_pages": 1},
            "options": {"headless": True, "network_idle": True, "timeout": 60},
            "schedule": {"cron": "0 */6 * * *", "timezone": "Europe/Lisbon"},
            "respect_robots": True,
            "tags": ["noticias", "economia", "jornal-de-negocios"],
            "id_fields": ["url"],
            "title_field": "titulo",
            "summary_field": "resumo",
            "detail": _detail("", max_items=0),
            "sentiment": _sentiment(min_chars=80),
        },
    },
    {
        "id": "expansion",
        "name": "Expansión",
        "site": "expansion.com",
        "category": "Imprensa económica (Espanha)",
        "description": "Primeira página da Expansión: secção, título, ligação, imagem e texto integral.",
        "tags": ["noticias", "economia", "espanha"],
        "requires": "http",
        "notes": "Corpo do artigo em `div.ue-c-article__body`.",
        "source": {
            "name": "Expansión",
            "description": "Destaques da Expansión (secção, título, ligação, imagem e texto integral).",
            "url": "https://www.expansion.com/",
            "enabled": False,
            "fetcher": "http",
            "list": {"selector": "article.ue-c-cover-content", "type": "css"},
            "fields": [
                _field("secao", "Secção", "span.ue-c-cover-content__kicker::text", max_length=160),
                _field("titulo", "Título", "h2.ue-c-cover-content__headline::text", max_length=400),
                _field("url", "Ligação", "a.ue-c-cover-content__link::attr(href)", max_length=1024),
                _field("imagem", "Imagem", "img.ue-c-cover-content__image::attr(src)", max_length=1024),
            ],
            "pagination": {"selector": "", "type": "css", "attr": "href", "max_pages": 1},
            "options": {"impersonate": "chrome", "timeout": 30},
            "schedule": {"cron": "0 */6 * * *", "timezone": "Europe/Lisbon"},
            "respect_robots": True,
            "tags": ["noticias", "economia", "espanha"],
            "id_fields": ["url"],
            "title_field": "titulo",
            "detail": _detail("div.ue-c-article__body", max_items=15),
            "sentiment": _sentiment(),
        },
    },
    {
        "id": "investing-mercados",
        "name": "Investing.com · Notícias de mercados",
        "site": "investing.com",
        "category": "Mercados (internacional)",
        "description": "Notícias de mercados (ações, matérias-primas, câmbios) em inglês: título, ligação, secção, data e imagem.",
        "tags": ["noticias", "mercados", "internacional"],
        "requires": "http",
        "notes": "A página mistura cartões de destaque (título em `p[title]`) e cartões de lista (título no `a`): o campo `titulo` tem os dois seletores.",
        "source": {
            "name": "Investing.com · Mercados",
            "description": "Notícias de mercados do Investing.com (título, ligação, resumo, secção, data e imagem).",
            "url": "https://www.investing.com/news/stock-market-news",
            "enabled": False,
            "fetcher": "http",
            "list": {"selector": "article", "type": "css"},
            "fields": [
                _field(
                    "titulo",
                    "Título",
                    "p[title]::attr(title)",
                    max_length=400,
                    selectors=["p[title]::attr(title)", 'div[class*="news-analysis-v2_content"] a::text'],
                ),
                _field("url", "Ligação", "a::attr(href)", max_length=1024),
                _field("resumo", "Resumo", 'div[class*="news-analysis-v2_content"] p::text', max_length=2000),
                _field("secao", "Secção", "span::text", max_length=160),
                _field("data", "Data", "time::attr(datetime)", cast="date", max_length=60),
                _field("imagem", "Imagem", "img::attr(src)", max_length=1024),
            ],
            "pagination": {"selector": "", "type": "css", "attr": "href", "max_pages": 1},
            "options": {"impersonate": "chrome", "timeout": 30},
            "schedule": {"cron": "0 */6 * * *", "timezone": "Europe/Lisbon"},
            "respect_robots": True,
            "tags": ["noticias", "mercados", "internacional"],
            "id_fields": ["url"],
            "title_field": "titulo",
            "detail": _detail("", max_items=0),
            "sentiment": _sentiment(min_chars=80),
        },
    },
    {
        "id": "quotes-demo",
        "name": "Quotes to Scrape (exemplo)",
        "site": "quotes.toscrape.com",
        "category": "Sites de exemplo",
        "description": "Site de demonstração, próprio para experimentar o módulo sem incomodar ninguém: 3 páginas, citações e autores.",
        "tags": ["exemplo", "demonstracao"],
        "requires": "http",
        "notes": "Serve para confirmar que o Scrapling, a indexação e a pesquisa funcionam antes de apontar a sites reais.",
        "source": {
            "name": "Quotes to Scrape (exemplo)",
            "description": "Exemplo de definição: lista de citações, autor e etiquetas.",
            "url": "https://quotes.toscrape.com/",
            "enabled": False,
            "fetcher": "http",
            "list": {"selector": ".quote", "type": "css"},
            "fields": [
                _field("citacao", "Citação", ".text::text", max_length=1000),
                _field("autor", "Autor", ".author::text", max_length=200),
                _field("etiquetas", "Etiquetas", ".tag::text", all_=True, max_length=80),
            ],
            "pagination": {"selector": ".next a", "type": "css", "attr": "href", "max_pages": 3},
            "options": {"impersonate": "chrome", "timeout": 30},
            "schedule": {"cron": "0 7 * * *", "timezone": "Europe/Lisbon"},
            "respect_robots": True,
            "tags": ["exemplo", "demonstracao"],
            "id_fields": ["autor", "citacao"],
            "title_field": "citacao",
            "detail": _detail("", max_items=0),
        },
    },
    {
        "id": "iberinform-diretorio",
        "name": "Iberinform · Diretório de empresas (PT)",
        "site": "iberinform.pt",
        "category": "Diretórios de empresas",
        "description": "Diretório de empresas portuguesas do Iberinform, recolhido por distrito e concelho, com detalhe de ficha.",
        "tags": ["empresas", "iberinform", "diretorio", "nif", "caudal"],
        "requires": "http",
        "notes": "Cada linha da tabela `table.table-hover.tabla-directorio-geografico` tem nome, NIF no `href`, distrito e concelho. A paginação usa `a[aria-label='Next']`. O detalhe da empresa fica em `section.section-company-data`.",
        "source": {
            "name": "Iberinform · Diretório de empresas (PT)",
            "description": "Recolha do diretório Iberinform por distrito e concelho, com ficha detalhada de cada empresa.",
            "url": "https://www.iberinform.pt/diretorio/evora/alandroal/pagina/1",
            "enabled": False,
            "fetcher": "http",
            "list": {"selector": "table.table-hover.tabla-directorio-geografico tbody tr", "type": "css"},
            "fields": [
                _field("nome", "Nome", "a h3::text", max_length=400),
                _field("url", "URL", "a::attr(href)", max_length=1024),
                _field("distrito", "Distrito", "td.hidden-xs::text", max_length=120),
                _field("concelho", "Concelho", "td:not(.hidden-xs)::text", max_length=120),
                _field(
                    "nif",
                    "NIF",
                    "a::attr(href)",
                    max_length=20,
                    regex=r"/empresa/(\d+)/",
                ),
            ],
            "pagination": {"selector": "a[aria-label='Next']", "type": "css", "attr": "href", "max_pages": 5},
            "options": {"impersonate": "chrome", "timeout": 30},
            "schedule": {"cron": "0 3 * * 1", "timezone": "Europe/Lisbon"},
            "respect_robots": True,
            "tags": ["empresas", "iberinform", "diretorio"],
            "id_fields": ["nif", "url"],
            "title_field": "nome",
            "summary_field": "nome",
            "detail": _detail("section.section-company-data", max_items=50, delay=1.2),
        },
    },
]

_BY_ID = {entry["id"]: entry for entry in TEMPLATES}


# ------------------------------------------------------------------- leitura
def list_templates(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lista os templates (metadados + a definição que vão criar)."""
    items = TEMPLATES
    if category:
        wanted = category.strip().lower()
        items = [t for t in items if t["category"].lower() == wanted]
    return [summary(t) for t in items]


def get_template(template_id: str) -> Optional[Dict[str, Any]]:
    entry = _BY_ID.get(template_id)
    return summary(entry) if entry else None


def summary(template: Dict[str, Any]) -> Dict[str, Any]:
    """Metadados do template (sem a definição completa)."""
    source = template["source"]
    detail = source.get("detail") or {}
    return {
        "id": template["id"],
        "name": template["name"],
        "site": template["site"],
        "category": template["category"],
        "description": template["description"],
        "tags": list(template.get("tags") or []),
        "requires": template.get("requires", "http"),
        "requires_browser": template.get("requires") in BROWSER_REQUIREMENTS,
        "notes": template.get("notes", ""),
        "url": source["url"],
        "fetcher": source["fetcher"],
        "cron": (source.get("schedule") or {}).get("cron", ""),
        "fields": [f["name"] for f in source.get("fields", [])],
        "detail": bool(detail.get("enabled")),
        "detail_selector": detail.get("selector", "") if detail.get("enabled") else "",
        "sentiment": bool((source.get("sentiment") or {}).get("enabled")),
        "sentiment_engine": (source.get("sentiment") or {}).get("engine", ""),
    }


def build_source(template_id: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Definição de fonte pronta a guardar, a partir do template.

    Aceita ajustes pontuais (`overrides`): `name`, `enabled`, `schedule.cron`,
    `pagination.max_pages`, `tags`, `detail.max_items`, … O resultado é validado
    e normalizado pelo `scraper_service`, pelo que é exatamente o que o
    `upsert_source` espera.
    """
    template = _BY_ID.get(template_id)
    if not template:
        raise KeyError(template_id)

    payload: Dict[str, Any] = copy.deepcopy(template["source"])
    overrides = dict(overrides or {})
    # O `id` nunca vem do template: quem guarda decide-o (ou o serviço gera-o).
    overrides.pop("id", None)

    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(payload.get(key), dict):
            merged = dict(payload[key])
            merged.update({k: v for k, v in value.items() if v not in (None, "")})
            payload[key] = merged
        elif value not in (None, ""):
            payload[key] = value

    payload.setdefault("name", template["name"])
    payload.setdefault("description", template["description"])
    source = scraper.normalize_source(payload)
    source["template_id"] = template_id
    return source


def template_for_source(source: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Template de origem de uma fonte guardada (se ainda o souber)."""
    template_id = str(source.get("template_id") or "").strip()
    entry = _BY_ID.get(template_id)
    if entry:
        return summary(entry)
    # Fontes criadas antes de existir `template_id`: reconhece-se pelo URL.
    url = str(source.get("url") or "").strip().rstrip("/")
    for candidate in TEMPLATES:
        if candidate["source"]["url"].rstrip("/") == url:
            return summary(candidate)
    return None


def refresh_source(source: Dict[str, Any], template_id: Optional[str] = None) -> Dict[str, Any]:
    """Reconstrói a definição de uma fonte a partir do seu template.

    Os sites mudam de `class` e os templates são corrigidos aqui; sem isto, uma
    fonte criada há semanas continuava a recolher com os seletores antigos. A
    identidade da fonte, o **nome**, o **interruptor**, a **agenda** e as
    **etiquetas** são preservados — só a parte técnica (URL, seletores, campos,
    paginação e texto integral) é que vem do template atual.
    """
    chosen = template_id.strip() if isinstance(template_id, str) else ""
    if not chosen:
        chosen = str(source.get("template_id") or "").strip()
    if not chosen:
        found = template_for_source(source)
        if not found:
            raise KeyError(str(source.get("id") or ""))
        chosen = found["id"]

    keep = {
        "id": source.get("id"),
        "name": source.get("name"),
        "enabled": source.get("enabled", False),
        "schedule": source.get("schedule") or {},
        "tags": source.get("tags") or [],
    }
    fresh = build_source(chosen, {k: v for k, v in keep.items() if v not in (None, "")})
    # `build_source` não deixa o `id` vir do template (quem guarda decide-o); aqui a
    # fonte já existe e a sua identidade não pode mudar no meio da reaplicação.
    fresh["id"] = keep["id"] or fresh["id"]
    fresh["created_at"] = source.get("created_at")
    fresh["template_id"] = chosen
    return scraper.normalize_source(fresh, source)
