"""Renderização do site público do CMS (`/site/...`).

Converte o modelo do `cms_store` em HTML pronto a servir: páginas por blocos,
artigos de blog, índice do blog (com paginação, categoria e etiqueta), RSS,
sitemap e `robots.txt`.

O HTML é **autónomo** (CSS embutido, sem dependências) para poder ser servido
por qualquer proxy e indexado pelos motores de busca: cada página leva `title`,
`meta description`, canónica, Open Graph e JSON-LD. A aparência vem das
definições do site (`theme`, `accent`, `radius`).
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

import markdown as markdown_lib

from api import cms_store as store

logger = logging.getLogger(__name__)

MD_EXTENSIONS = ["extra", "sane_lists", "nl2br", "toc"]

_THEMES: Dict[str, Dict[str, str]] = {
    "claro": {
        "bg": "#f7f8fa",
        "surface": "#ffffff",
        "text": "#101828",
        "muted": "#5b6472",
        "border": "#e4e7ec",
        "code": "#f1f3f6",
        "shadow": "0 1px 2px rgba(16,24,40,.06), 0 8px 24px rgba(16,24,40,.06)",
    },
    "escuro": {
        "bg": "#0b1020",
        "surface": "#131a2e",
        "text": "#f2f4f8",
        "muted": "#9aa4b8",
        "border": "#26304a",
        "code": "#1b2440",
        "shadow": "0 1px 2px rgba(0,0,0,.4), 0 10px 30px rgba(0,0,0,.35)",
    },
}


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _md(text: str) -> str:
    """Markdown → HTML (com tabelas, listas e código)."""
    if not (text or "").strip():
        return ""
    try:
        return markdown_lib.markdown(text, extensions=MD_EXTENSIONS, output_format="html5")
    except Exception as exc:  # pragma: no cover - markdown robusto
        logger.warning("Falha a converter Markdown (%s); a devolver texto.", exc)
        return f"<p>{_esc(text)}</p>"


def _media_url(media_id: Optional[str]) -> str:
    if not media_id:
        return ""
    try:
        media = store.get_item("media", media_id)
    except KeyError:
        return ""
    return str(media.get("url") or "")


def _absolute(url: str, base_url: str = "") -> str:
    if not url:
        return base_url
    if url.startswith(("http://", "https://")):
        return url
    return f"{base_url.rstrip('/')}{url}" if base_url else url


def _date(value: Optional[str], with_time: bool = False) -> str:
    if not value:
        return ""
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)[:10]
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.strftime("%d/%m/%Y %H:%M") if with_time else stamp.astimezone().strftime("%d/%m/%Y")


def _css(settings: Dict[str, Any]) -> str:
    theme_name = str(settings.get("theme") or "claro")
    if theme_name not in _THEMES:
        theme_name = "claro"
    palette = _THEMES[theme_name]
    accent = str(settings.get("accent") or "#0ea5a4")
    radius = int(settings.get("radius") or 14)
    return f"""
:root {{
  --bg: {palette['bg']}; --surface: {palette['surface']}; --text: {palette['text']};
  --muted: {palette['muted']}; --border: {palette['border']}; --code: {palette['code']};
  --shadow: {palette['shadow']}; --accent: {accent}; --radius: {radius}px;
}}
*, *::before, *::after {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0; background: var(--bg); color: var(--text);
  font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif;
  line-height: 1.65; font-size: 17px;
}}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.wrap {{ max-width: 1100px; margin: 0 auto; padding: 0 20px; }}
.site-header {{
  position: sticky; top: 0; z-index: 20; backdrop-filter: blur(10px);
  background: color-mix(in srgb, var(--surface) 88%, transparent);
  border-bottom: 1px solid var(--border);
}}
.site-header .wrap {{ display: flex; align-items: center; gap: 16px; min-height: 64px; }}
.brand {{ font-weight: 800; font-size: 1.05rem; color: var(--text); letter-spacing: -.01em; }}
.brand small {{ display: block; font-weight: 500; font-size: .72rem; color: var(--muted); letter-spacing: 0; }}
.brand .brand-mark {{ display: block; height: 34px; width: auto; }}
nav.main {{ margin-left: auto; display: flex; gap: 6px; flex-wrap: wrap; }}
nav.main a {{
  color: var(--text); font-size: .92rem; font-weight: 600; padding: 7px 12px; border-radius: 999px;
}}
nav.main a:hover {{ background: var(--code); text-decoration: none; }}
nav.main a[aria-current="page"] {{ background: var(--accent); color: #fff; }}
.breadcrumb {{ margin: 0 0 18px; font-size: .88rem; }}
.breadcrumb ol {{ display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; margin: 0; padding: 0; list-style: none; }}
.breadcrumb li {{ display: flex; align-items: center; gap: 10px; color: var(--muted); }}
.breadcrumb li + li::before {{ content: "›"; color: var(--muted); opacity: .7; }}
.breadcrumb a {{ color: var(--muted); }}
.breadcrumb a:hover {{ color: var(--accent); }}
.breadcrumb [aria-current="page"] {{ color: var(--text); font-weight: 600; }}
main {{ padding: 32px 0 72px; }}
.card {{
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  box-shadow: var(--shadow); padding: 28px;
}}
.section + .section {{ margin-top: 28px; }}
h1 {{ font-size: clamp(1.8rem, 4vw, 2.6rem); line-height: 1.15; letter-spacing: -.02em; margin: 0 0 12px; }}
h2 {{ font-size: 1.45rem; letter-spacing: -.01em; margin: 34px 0 10px; }}
h3 {{ font-size: 1.12rem; margin: 24px 0 8px; }}
p {{ margin: 0 0 14px; }}
.lead {{ font-size: 1.1rem; color: var(--muted); }}
.hero {{ padding: 46px 32px; border-radius: var(--radius); border: 1px solid var(--border); background: var(--surface); box-shadow: var(--shadow); }}
.hero .actions {{ margin-top: 20px; display: flex; gap: 10px; flex-wrap: wrap; }}
.hero.centro {{ text-align: center; }}
.hero .cover {{ margin: 24px 0 0; }}
.btn {{
  display: inline-block; padding: 11px 20px; border-radius: 999px; font-weight: 700;
  background: var(--accent); color: #fff; border: 1px solid transparent;
}}
.btn.ghost {{ background: transparent; color: var(--accent); border-color: var(--border); }}
.btn:hover {{ text-decoration: none; filter: brightness(1.05); }}
.grid {{ display: grid; gap: 18px; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }}
.tile {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; box-shadow: var(--shadow); }}
.tile h3 {{ margin: 0 0 6px; font-size: 1rem; }}
.tile p {{ margin: 0; color: var(--muted); font-size: .94rem; }}
figure {{ margin: 22px 0; }}
figure img, .prose img {{ max-width: 100%; height: auto; border-radius: calc(var(--radius) - 4px); display: block; }}
figcaption {{ color: var(--muted); font-size: .86rem; margin-top: 8px; }}
.prose {{ max-width: 760px; }}
.prose ul, .prose ol {{ padding-left: 22px; }}
.prose blockquote {{
  margin: 20px 0; padding: 6px 18px; border-left: 3px solid var(--accent); color: var(--muted); font-style: italic;
}}
.prose code {{ background: var(--code); padding: 2px 6px; border-radius: 6px; font-size: .9em; }}
.prose pre {{ background: var(--code); padding: 16px; border-radius: var(--radius); overflow: auto; }}
.prose pre code {{ background: none; padding: 0; }}
.prose table {{ width: 100%; border-collapse: collapse; font-size: .93rem; }}
.prose th, .prose td {{ border: 1px solid var(--border); padding: 8px 10px; text-align: left; }}
.prose th {{ background: var(--code); }}
.cta {{
  display: flex; gap: 16px; align-items: center; justify-content: space-between; flex-wrap: wrap;
  padding: 26px 28px; border-radius: var(--radius); border: 1px solid var(--border);
  background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 14%, var(--surface)), var(--surface));
  box-shadow: var(--shadow);
}}
.cta h2 {{ margin: 0 0 4px; }}
.aviso {{ border-left: 4px solid var(--accent); background: var(--code); padding: 14px 18px; border-radius: 8px; }}
.aviso.amber {{ border-color: #f59e0b; }}
.aviso.red {{ border-color: #ef4444; }}
.aviso.green {{ border-color: #10b981; }}
.faq details {{ border: 1px solid var(--border); border-radius: 10px; padding: 12px 16px; margin-bottom: 10px; background: var(--surface); }}
.faq summary {{ font-weight: 600; cursor: pointer; }}
.pill {{
  display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: .78rem; font-weight: 700;
  background: color-mix(in srgb, var(--accent) 16%, transparent); color: var(--accent);
}}
.meta {{ color: var(--muted); font-size: .9rem; display: flex; gap: 14px; flex-wrap: wrap; align-items: center; }}
.posts {{ display: grid; gap: 20px; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }}
.post-card {{ display: flex; flex-direction: column; overflow: hidden; padding: 0; }}
.post-card img {{ width: 100%; aspect-ratio: 16/9; object-fit: cover; }}
.post-card .body {{ padding: 18px 20px 22px; display: flex; flex-direction: column; gap: 8px; flex: 1; }}
.post-card h3 {{ margin: 0; font-size: 1.08rem; }}
.post-card p {{ margin: 0; color: var(--muted); font-size: .93rem; }}
.pager {{ display: flex; gap: 8px; justify-content: center; margin-top: 28px; }}
.pager a, .pager span {{ padding: 8px 14px; border-radius: 10px; border: 1px solid var(--border); background: var(--surface); color: var(--text); font-weight: 600; }}
.pager span.current {{ background: var(--accent); color: #fff; border-color: transparent; }}
.hr {{ height: 1px; background: var(--border); margin: 30px 0; border: 0; }}
.contactos {{ display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }}
.contactos div {{ padding: 14px 16px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }}
.steps {{ counter-reset: step; display: grid; gap: 14px; }}
.steps .step {{ position: relative; padding-left: 52px; }}
.steps .step::before {{
  counter-increment: step; content: counter(step);
  position: absolute; left: 0; top: 0; width: 34px; height: 34px; border-radius: 50%;
  background: var(--accent); color: #fff; display: grid; place-items: center; font-weight: 700; font-size: .9rem;
}}
.site-footer {{ border-top: 1px solid var(--border); background: var(--surface); padding: 30px 0; color: var(--muted); font-size: .9rem; }}
.site-footer .wrap {{ display: flex; gap: 18px; flex-wrap: wrap; align-items: center; justify-content: space-between; }}
.site-footer nav {{ display: flex; gap: 14px; flex-wrap: wrap; }}
.site-footer a {{ color: var(--muted); }}
.kpis {{ display: grid; gap: 14px; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); }}
.kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px 18px; }}
.kpi span {{ display: block; color: var(--muted); font-size: .78rem; text-transform: uppercase; letter-spacing: .05em; }}
.kpi strong {{ display: block; margin-top: 6px; font-size: 1.32rem; letter-spacing: -.02em; }}
.kpi small {{ display: block; margin-top: 4px; color: var(--muted); font-size: .8rem; }}
.draft-banner {{
  position: sticky; top: 0; z-index: 30; background: #f59e0b; color: #1f2937;
  text-align: center; font-size: .85rem; font-weight: 700; padding: 6px 12px;
}}
@media print {{ .site-header, .site-footer, .draft-banner {{ display: none; }} body {{ background: #fff; }} }}
"""


# --------------------------------------------------------------------------
# Blocos
# --------------------------------------------------------------------------
def _render_content_block(content_id: str) -> str:
    try:
        content = store.get_item("contents", content_id)
    except KeyError:
        return ""
    kind = content.get("kind")
    body = _md(str(content.get("body") or ""))
    data = content.get("data") or {}
    if kind == "cta":
        return (
            f'<div class="cta"><div><h2>{_esc(data.get("title") or content.get("title"))}</h2>'
            f'<p>{_esc(data.get("text") or "")}</p></div>'
            f'<a class="btn" href="{_esc(data.get("button_href") or "#")}">{_esc(data.get("button_label") or "Saber mais")}</a></div>'
        )
    if kind == "hero":
        return (
            f'<div class="hero"><h1>{_esc(data.get("title") or content.get("title"))}</h1>'
            f'<p class="lead">{_esc(data.get("subtitle") or "")}</p></div>'
        )
    if kind == "aviso":
        return f'<div class="aviso {_esc(data.get("tone") or "")}">{body}</div>'
    if kind == "contactos":
        parts = []
        if data.get("email"):
            parts.append(f'<div><strong>Email</strong><br><a href="mailto:{_esc(data["email"])}">{_esc(data["email"])}</a></div>')
        if data.get("phone"):
            parts.append(f'<div><strong>Telefone</strong><br>{_esc(data["phone"])}</div>')
        if data.get("address"):
            parts.append(f'<div><strong>Morada</strong><br>{_esc(data["address"])}</div>')
        return f'<div class="section"><div class="contactos">{"".join(parts)}</div></div>'
    if kind == "rodape":
        return f'<div class="prose">{body}</div>'
    return f'<div class="prose">{body}</div>'


def _render_blog_block(data: Dict[str, Any], *, preview: bool) -> str:
    limit = int(data.get("limit") or 3)
    category_id = data.get("category_id") or None
    posts = store.published_posts(category_id=str(category_id) if category_id else None, limit=limit)
    if preview and not posts:
        posts = [post for post in (store.list_items("posts", limit=limit)["items"]) if not post.get("markdown")]
    title = str(data.get("title") or "")
    head = f"<h2>{_esc(title)}</h2>" if title else ""
    if not posts:
        return f'<div class="section">{head}<p class="lead">Ainda não há artigos publicados.</p></div>'
    cards = "".join(_post_card(post) for post in posts)
    return f'<div class="section">{head}<div class="posts">{cards}</div></div>'


def _render_block(block: Dict[str, Any], *, preview: bool = False) -> str:
    if block.get("hidden"):
        return ""
    block_type = str(block.get("type") or "texto")
    data = block.get("data") or {}

    if block_type == "hero":
        title = _esc(data.get("title") or "")
        subtitle = _esc(data.get("subtitle") or "")
        image = _media_url(data.get("image_id"))
        cover = f'<figure class="cover"><img src="{_esc(image)}" alt=""></figure>' if image else ""
        actions = ""
        if data.get("cta_label"):
            actions = (
                f'<div class="actions"><a class="btn" href="{_esc(data.get("cta_href") or "#")}">'
                f'{_esc(data.get("cta_label"))}</a></div>'
            )
        align = "centro" if str(data.get("align") or "") == "centro" else ""
        heading = f"<h1>{title}</h1>" if title else ""
        return f'<div class="hero {align}">{heading}<p class="lead">{subtitle}</p>{actions}{cover}</div>'

    if block_type == "texto":
        title = f"<h2>{_esc(data.get('title'))}</h2>" if data.get("title") else ""
        return f'<div class="section prose">{title}{_md(str(data.get("markdown") or data.get("body") or ""))}</div>'

    if block_type == "imagem":
        url = _media_url(data.get("media_id")) or str(data.get("url") or "")
        if not url:
            return ""
        caption = f"<figcaption>{_esc(data.get('caption'))}</figcaption>" if data.get("caption") else ""
        return f'<figure><img src="{_esc(url)}" alt="{_esc(data.get("alt"))}" loading="lazy">{caption}</figure>'

    if block_type == "galeria":
        urls = [_media_url(item) for item in (data.get("media_ids") or [])]
        urls = [url for url in urls if url]
        if not urls:
            return ""
        images = "".join(f'<img src="{_esc(url)}" alt="" loading="lazy">' for url in urls)
        return f'<div class="grid">{images}</div>'

    if block_type == "destaques":
        items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
        if not items:
            return ""
        tiles = "".join(
            f'<div class="tile"><h3>{_esc(item.get("title"))}</h3><p>{_esc(item.get("text"))}</p></div>'
            for item in items
        )
        title = f"<h2>{_esc(data.get('title'))}</h2>" if data.get("title") else ""
        return f'<div class="section">{title}<div class="grid">{tiles}</div></div>'

    if block_type == "numeros":
        items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
        if not items:
            return ""
        cartoes = "".join(
            f'<div class="kpi"><span>{_esc(item.get("label"))}</span><strong>{_esc(item.get("value"))}</strong>'
            + (f'<small>{_esc(item.get("note"))}</small>' if item.get("note") else "")
            + "</div>"
            for item in items
        )
        title = f"<h2>{_esc(data.get('title'))}</h2>" if data.get("title") else ""
        return f'<div class="section">{title}<div class="kpis">{cartoes}</div></div>'

    if block_type == "cta":
        return (
            f'<div class="section cta"><div><h2>{_esc(data.get("title"))}</h2>'
            f'<p>{_esc(data.get("text") or "")}</p></div>'
            f'<a class="btn" href="{_esc(data.get("button_href") or "#")}">{_esc(data.get("button_label") or "Saber mais")}</a></div>'
        )

    if block_type == "faq":
        items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
        details = "".join(
            f'<details><summary>{_esc(item.get("question") or item.get("title"))}</summary>'
            f'<div>{_md(str(item.get("answer") or item.get("text") or ""))}</div></details>'
            for item in items
        )
        title = f"<h2>{_esc(data.get('title'))}</h2>" if data.get("title") else ""
        return f'<div class="section faq">{title}{details}</div>'

    if block_type == "passos":
        items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
        steps = "".join(
            f'<div class="step"><h3>{_esc(item.get("title"))}</h3>{_md(str(item.get("text") or ""))}</div>'
            for item in items
        )
        title = f"<h2>{_esc(data.get('title'))}</h2>" if data.get("title") else ""
        return f'<div class="section">{title}<div class="steps">{steps}</div></div>'

    if block_type == "tabela":
        head = [str(cell) for cell in (data.get("head") or [])]
        rows = [row for row in (data.get("rows") or []) if isinstance(row, list)]
        if not head and not rows:
            return ""
        thead = f"<tr>{''.join(f'<th>{_esc(cell)}</th>' for cell in head)}</tr>" if head else ""
        tbody = "".join(f"<tr>{''.join(f'<td>{_esc(cell)}</td>' for cell in row)}</tr>" for row in rows)
        title = f"<h2>{_esc(data.get('title'))}</h2>" if data.get("title") else ""
        return f'<div class="section prose">{title}<table><thead>{thead}</thead><tbody>{tbody}</tbody></table></div>'

    if block_type == "citacao":
        author = f"<footer>— {_esc(data.get('author'))}</footer>" if data.get("author") else ""
        return f'<blockquote>{_esc(data.get("quote") or "")}{author}</blockquote>'

    if block_type == "aviso":
        tone = str(data.get("tone") or "")
        tone = f" {tone}" if tone in ("amber", "red", "green") else ""
        return f'<div class="aviso{tone}">{_md(str(data.get("text") or ""))}</div>'

    if block_type == "codigo":
        language = _esc(data.get("language") or "")
        code = html.escape(str(data.get("code") or ""))
        return f'<pre><code class="language-{language}">{code}</code></pre>'

    if block_type == "contactos":
        parts = []
        if data.get("email"):
            parts.append(f'<div><strong>Email</strong><br><a href="mailto:{_esc(data["email"])}">{_esc(data["email"])}</a></div>')
        if data.get("phone"):
            parts.append(f'<div><strong>Telefone</strong><br>{_esc(data["phone"])}</div>')
        if data.get("address"):
            parts.append(f'<div><strong>Morada</strong><br>{_esc(data["address"])}</div>')
        title = f"<h2>{_esc(data.get('title'))}</h2>" if data.get("title") else ""
        return f'<div class="section">{title}<div class="contactos">{"".join(parts)}</div></div>'

    if block_type == "conteudo":
        return f'<div class="section">{_render_content_block(str(data.get("content_id") or ""))}</div>'

    if block_type == "blog":
        return _render_blog_block(data, preview=preview)

    if block_type == "divisor":
        return '<hr class="hr">'

    return ""


def blocks_to_html(blocks: Iterable[Dict[str, Any]], *, preview: bool = False) -> str:
    return "".join(_render_block(block, preview=preview) for block in (blocks or []))


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------
def _header(settings: Dict[str, Any], *, current_path: str, preview: bool = False) -> str:
    menu = store.menu_for("header")
    links = []
    for item in menu.get("items") or []:
        active = ' aria-current="page"' if item.get("href") in (current_path, f"/site{current_path}") else ""
        target = ' target="_blank" rel="noopener"' if item.get("new_tab") else ""
        links.append(f'<a href="{_esc(item.get("href"))}"{active}{target}>{_esc(item.get("label"))}</a>')
    tagline = f'<small>{_esc(settings.get("tagline"))}</small>' if settings.get("tagline") else ""
    # Com logótipo na biblioteca, o cabeçalho mostra a imagem (que já traz o
    # nome); sem ele, fica o nome em texto, como antes.
    logo = _media_url(settings.get("logo_id"))
    if logo:
        brand = (
            f'<img class="brand-mark" src="{_esc(logo)}" alt="{_esc(settings.get("site_name"))}" width="320" height="72">'
            + tagline
        )
    else:
        brand = f'{_esc(settings.get("site_name"))}{tagline}'
    banner = '<div class="draft-banner">Pré-visualização — este conteúdo ainda não está publicado</div>' if preview else ""
    return (
        banner
        + '<header class="site-header"><div class="wrap">'
        + f'<a class="brand" href="/site">{brand}</a>'
        + f'<nav class="main">{"".join(links)}</nav>'
        + "</div></header>"
    )


def _social_links(settings: Dict[str, Any]) -> str:
    labels = {"email": "Email", "linkedin": "LinkedIn", "x": "X", "github": "GitHub"}
    parts = []
    for key, label in labels.items():
        value = str((settings.get("social") or {}).get(key) or "").strip()
        if not value:
            continue
        href = f"mailto:{value}" if key == "email" else value
        parts.append(f'<a href="{_esc(href)}">{label}</a>')
    return "".join(parts)


def _footer(settings: Dict[str, Any]) -> str:
    menu = store.menu_for("footer")
    links = "".join(f'<a href="{_esc(item.get("href"))}">{_esc(item.get("label"))}</a>' for item in menu.get("items") or [])
    footer_text = _esc(settings.get("footer_text") or "")
    site_name = _esc(settings.get("site_name") or "")
    return (
        '<footer class="site-footer"><div class="wrap">'
        f'<div><strong>{site_name}</strong><br>{footer_text}</div>'
        f'<nav>{links}{_social_links(settings)}</nav>'
        "</div></footer>"
    )


def _breadcrumb(dados: Optional[List[Dict[str, str]]]) -> str:
    """Trilha de navegação («Início › Secção › Página»).

    O último passo é sempre o texto da página (sem link); os anteriores levam a
    `href` quando existe (uma secção sem índice próprio, como «Municípios», não
    leva).
    """
    if not dados or len(dados) < 2:
        return ""
    passos: List[str] = []
    for posicao, passo in enumerate(dados, start=1):
        etiqueta = _esc(str(passo.get("label") or ""))
        href = str(passo.get("href") or "").strip()
        if href and posicao < len(dados):
            passos.append(f'<li><a href="{_esc(href)}">{etiqueta}</a></li>')
        else:
            passos.append(f'<li><span aria-current="page">{etiqueta}</span></li>')
    return f'<nav class="breadcrumb" aria-label="Caminho"><ol>{"".join(passos)}</ol></nav>'


def _breadcrumb_json_ld(dados: List[Dict[str, str]], base_url: str) -> Dict[str, Any]:
    """A mesma trilha em `BreadcrumbList`, para os motores de busca."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": posicao,
                "name": str(passo.get("label") or ""),
                **({"item": _absolute(str(passo["href"]), base_url)} if passo.get("href") else {}),
            }
            for posicao, passo in enumerate(dados, start=1)
        ],
    }


def _layout(
    *,
    title: str,
    description: str,
    body: str,
    current_path: str,
    settings: Dict[str, Any],
    canonical: str = "",
    og_type: str = "website",
    og_image: str = "",
    keywords: Optional[List[str]] = None,
    json_ld: Optional[Dict[str, Any]] = None,
    preview: bool = False,
    noindex: bool = False,
    extra_css: str = "",
    breadcrumb: Optional[List[Dict[str, str]]] = None,
) -> str:
    base_url = str(settings.get("base_url") or "")
    site_name = _esc(settings.get("site_name") or "Site")
    full_title = title if title and site_name in title else f"{title} · {site_name}" if title else site_name
    canonical_url = _absolute(canonical or current_path, base_url)
    robots = "noindex, nofollow" if (noindex or preview) else str(settings.get("robots") or "index, follow")
    meta = [
        f'<meta name="description" content="{_esc(description)}">',
        f'<meta name="robots" content="{_esc(robots)}">',
        f'<link rel="canonical" href="{_esc(canonical_url or "/")}">',
        f'<link rel="alternate" type="application/rss+xml" title="{site_name} — RSS" href="/site/rss.xml">',
        f'<meta property="og:type" content="{_esc(og_type)}">',
        f'<meta property="og:site_name" content="{site_name}">',
        f'<meta property="og:title" content="{_esc(full_title)}">',
        f'<meta property="og:description" content="{_esc(description)}">',
        f'<meta property="og:url" content="{_esc(canonical_url or "/")}">',
        f'<meta property="og:locale" content="{_esc(str(settings.get("language") or "pt-PT").replace("-", "_"))}">',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{_esc(full_title)}">',
        f'<meta name="twitter:description" content="{_esc(description)}">',
    ]
    if og_image:
        # Open Graph e Twitter só aceitam URLs absolutos: um caminho relativo
        # (`/cms/media/...`) é ignorado e a partilha fica sem imagem.
        imagem = _absolute(og_image, base_url)
        meta.append(f'<meta property="og:image" content="{_esc(imagem)}">')
        meta.append(f'<meta name="twitter:image" content="{_esc(imagem)}">')
    if keywords:
        meta.append(f'<meta name="keywords" content="{_esc(", ".join(keywords))}">')
    analytics = str(settings.get("analytics_id") or "").strip()
    if analytics and not preview:
        meta.append(
            "<script async src=\"https://www.googletagmanager.com/gtag/js?id="
            + _esc(analytics)
            + '"></script><script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag("js",new Date());gtag("config","'
            + _esc(analytics)
            + '");</script>'
        )
    if json_ld:
        meta.append(f'<script type="application/ld+json">{json.dumps(json_ld, ensure_ascii=False)}</script>')
    if breadcrumb and len(breadcrumb) >= 2:
        meta.append(
            f'<script type="application/ld+json">'
            f'{json.dumps(_breadcrumb_json_ld(breadcrumb, base_url), ensure_ascii=False)}</script>'
        )
    favicon = _media_url(settings.get("favicon_id"))
    if favicon:
        meta.append(f'<link rel="icon" href="{_esc(favicon)}">')
    return (
        "<!doctype html><html lang=\""
        + _esc(str(settings.get("language") or "pt-PT"))
        + '"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        + f"<title>{_esc(full_title)}</title>"
        + "".join(meta)
        + f"<style>{_css(settings)}{extra_css}</style></head><body>"
        + _header(settings, current_path=current_path, preview=preview)
        + f"<main><div class=\"wrap\">{_breadcrumb(breadcrumb)}{body}</div></main>"
        + _footer(settings)
        + "</body></html>"
    )


# --------------------------------------------------------------------------
# Páginas, artigos e blog
# --------------------------------------------------------------------------
def _page_description(page: Dict[str, Any]) -> str:
    seo = page.get("seo") or {}
    return str(seo.get("description") or page.get("excerpt") or _plain_excerpt(page))


def _plain_excerpt(doc: Dict[str, Any]) -> str:
    text = doc.get("excerpt") or doc.get("markdown") or ""
    plain = re.sub(r"[#*`>_|]", " ", str(text))
    return re.sub(r"\s+", " ", plain).strip()[:200]


def _trilha_da_pagina(page: Dict[str, Any]) -> List[Dict[str, str]]:
    """«Início › Secção › Página»: sobe pelos ascendentes da página.

    A página inicial não leva trilha (é o próprio «Início»).
    """
    settings = store.get_settings()
    if page.get("id") and str(page.get("id")) == str(settings.get("home_page_id") or ""):
        return []
    trilha: List[Dict[str, str]] = [{"label": "Início", "href": "/site"}]
    acima: List[Dict[str, str]] = []
    parent_id = page.get("parent_id")
    vistos: set = set()
    while parent_id and parent_id not in vistos:
        vistos.add(parent_id)
        try:
            pai = store.get_item("pages", str(parent_id))
        except KeyError:
            break
        caminho = str(pai.get("path") or "")
        acima.insert(
            0,
            {
                "label": str(pai.get("menu_label") or pai.get("title") or ""),
                "href": f"/site/{caminho}" if caminho else "/site",
            },
        )
        parent_id = pai.get("parent_id")
    trilha.extend(acima)
    if page.get("title"):
        trilha.append({"label": str(page["title"])})
    return trilha


def _site_home_url(settings: Dict[str, Any]) -> str:
    """O endereço da página inicial (serve de base aos `@id` do JSON-LD)."""
    return _absolute("/site", str(settings.get("base_url") or ""))


def _organization_json_ld(settings: Dict[str, Any]) -> Dict[str, Any]:
    """A entidade por trás do site, para o grafo de conhecimento dos motores.

    Os perfis das definições entram como `sameAs`: é assim que as redes sociais
    e o Google ligam o site às páginas oficiais da marca.
    """
    base_url = str(settings.get("base_url") or "")
    casa = _site_home_url(settings)
    dados: Dict[str, Any] = {
        "@type": "Organization",
        "@id": f"{casa}#organizacao",
        "name": str(settings.get("site_name") or ""),
        "url": casa,
    }
    descricao = str(settings.get("description") or (settings.get("seo") or {}).get("description") or "")
    if descricao:
        dados["description"] = descricao
    logo = _media_url(settings.get("logo_id"))
    if logo:
        dados["logo"] = {"@type": "ImageObject", "url": _absolute(logo, base_url)}
    perfis = [
        str(valor).strip()
        for chave, valor in (settings.get("social") or {}).items()
        if chave != "email" and str(valor or "").strip()
    ]
    if perfis:
        dados["sameAs"] = perfis
    return dados


def _website_json_ld(settings: Dict[str, Any]) -> Dict[str, Any]:
    casa = _site_home_url(settings)
    return {
        "@type": "WebSite",
        "@id": f"{casa}#site",
        "name": str(settings.get("site_name") or ""),
        "url": casa,
        "inLanguage": str(settings.get("language") or "pt-PT"),
        "publisher": {"@id": f"{casa}#organizacao"},
    }


def _faq_json_ld(blocks: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """`FAQPage` a partir do bloco de perguntas frequentes (dá rich results)."""
    perguntas: List[Dict[str, Any]] = []
    for block in blocks or []:
        if str(block.get("type") or "") != "faq" or block.get("hidden"):
            continue
        for item in (block.get("data") or {}).get("items") or []:
            if not isinstance(item, dict):
                continue
            pergunta = str(item.get("question") or item.get("title") or "").strip()
            resposta = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _md(str(item.get("answer") or item.get("text") or "")))).strip()
            if pergunta and resposta:
                perguntas.append(
                    {
                        "@type": "Question",
                        "name": pergunta,
                        "acceptedAnswer": {"@type": "Answer", "text": resposta},
                    }
                )
    if not perguntas:
        return None
    return {"@type": "FAQPage", "mainEntity": perguntas}


def render_page(
    page: Dict[str, Any],
    *,
    preview: bool = False,
    settings: Optional[Dict[str, Any]] = None,
    blog_post_count: int = 0,
) -> str:
    settings = settings or store.get_settings()
    seo = page.get("seo") or {}
    body = blocks_to_html(page.get("blocks") or [], preview=preview)
    if not body.strip():
        body = f'<div class="section prose">{_md(str(page.get("markdown") or page.get("excerpt") or ""))}</div>' or ""
    base_url = str(settings.get("base_url") or "")
    path = f"/site/{page.get('path')}" if page.get("path") else "/site"
    casa = _site_home_url(settings)
    imagem = _media_url(seo.get("image_id")) or _media_url((settings.get("seo") or {}).get("image_id"))
    # Bloco «@graph»: além da página, o site e a organização que o publica. O
    # motor passa a ter a marca ligada ao domínio, e não só uma página solta.
    grafo: List[Dict[str, Any]] = [_website_json_ld(settings), _organization_json_ld(settings)]
    pagina_ld: Dict[str, Any] = {
        "@type": "WebPage",
        "@id": f"{_absolute(path, base_url)}#pagina",
        "name": page.get("title"),
        "description": _page_description(page),
        "url": _absolute(path, base_url),
        "inLanguage": str(settings.get("language") or "pt-PT"),
        "isPartOf": {"@id": f"{casa}#site"},
        "publisher": {"@id": f"{casa}#organizacao"},
    }
    if imagem:
        pagina_ld["primaryImageOfPage"] = {
            "@type": "ImageObject",
            "url": _absolute(imagem, base_url),
        }
    if page.get("updated_at"):
        pagina_ld["dateModified"] = page.get("updated_at")
    grafo.append(pagina_ld)
    faq = _faq_json_ld(page.get("blocks") or [])
    if faq:
        grafo.append(faq)
    json_ld: Dict[str, Any] = {"@context": "https://schema.org", "@graph": grafo}
    return _layout(
        title=str(seo.get("title") or page.get("title") or ""),
        description=_page_description(page),
        body=body,
        current_path=path,
        settings=settings,
        canonical=path,
        og_image=imagem,
        keywords=seo.get("keywords") or (settings.get("seo") or {}).get("keywords") or None,
        json_ld=json_ld,
        preview=preview,
        noindex=bool(seo.get("noindex")),
        breadcrumb=_trilha_da_pagina(page),
    )


# --------------------------------------------------------------------------
# Ficha pública de um município
# --------------------------------------------------------------------------
def _euros(valor: Any) -> str:
    """Valor em euros à portuguesa («317 577 000 €»)."""
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        numero = 0.0
    return f"{numero:,.0f}".replace(",", " ") + " €"


def _euros_curto(valor: Any) -> str:
    """Valor em euros compacto, para os destaques («317,6 M€»)."""
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        numero = 0.0
    if abs(numero) >= 1_000_000:
        return f"{numero / 1_000_000:.1f}".replace(".", ",") + " M€"
    if abs(numero) >= 1_000:
        return f"{numero / 1_000:.0f} mil €"
    return _euros(numero)


def _numero(valor: Any) -> str:
    try:
        return f"{int(valor or 0):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def _para_float(valor: Any) -> float:
    """Converte para número sem rebentar (o que chega pode ser nulo ou texto)."""
    try:
        return float(valor or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _tabela(titulo: str, cabecalho: List[str], linhas: List[List[str]]) -> str:
    if not linhas:
        return ""
    head = "".join(f"<th>{_esc(celula)}</th>" for celula in cabecalho)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(celula)}</td>" for celula in linha) + "</tr>"
        for linha in linhas
    )
    return (
        f'<div class="section prose"><h2>{_esc(titulo)}</h2>'
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _kpis_do_municipio(dados: Dict[str, Any]) -> str:
    ano = dados.get("ano_despesas")
    contratos = dados.get("contratos") or {}
    cartoes = [
        ("Despesa total", _euros_curto(dados.get("despesas_total")), f"Execução de {ano}" if ano else ""),
        ("Despesas correntes", _euros_curto(dados.get("despesas_correntes")), "Funcionamento corrente"),
        ("Despesas de capital", _euros_curto(dados.get("despesas_capital")), "Investimento e outros"),
        ("Despesa com pessoal", _euros_curto(dados.get("despesas_pessoal")), "Rubrica D11"),
        ("Bens e serviços", _euros_curto(dados.get("despesas_bens_servicos")), "Rubrica D12"),
    ]
    if contratos.get("total"):
        cartoes.append((
            "Contratos celebrados",
            _numero(contratos.get("total")),
            f"{_euros_curto(contratos.get('valor'))} em aquisições",
        ))
    abertos = "".join(
        f'<div class="kpi"><span>{_esc(titulo)}</span><strong>{_esc(valor)}</strong>'
        + (f"<small>{_esc(nota)}</small>" if nota else "")
        + "</div>"
        for titulo, valor, nota in cartoes
    )
    return f'<div class="section kpis">{abertos}</div>'


def _corpo_do_municipio(dados: Dict[str, Any], doc: Dict[str, Any], *, preview: bool) -> str:
    """Blocos editoriais + os dados oficiais que os sustentam."""
    corpo: List[str] = [_kpis_do_municipio(dados), blocks_to_html(doc.get("blocks") or [], preview=preview)]

    classificadores = dados.get("por_classificador") or []
    if classificadores:
        corpo.append(_tabela(
            f"Despesa por classificador económico ({dados.get('ano_despesas')})",
            ["Classificador", "Valor"],
            [[item.get("etiqueta") or item.get("codigo") or "", _euros(item.get("valor"))] for item in classificadores],
        ))

    contratos = dados.get("contratos") or {}
    por_ano = contratos.get("por_ano") or {}
    if por_ano:
        linhas = [
            [str(ano), _numero((valores or {}).get("contratos")), _euros((valores or {}).get("valor"))]
            for ano, valores in sorted(por_ano.items())
            if isinstance(valores, dict)
        ]
        corpo.append(_tabela(
            "Contratação pública por ano (Portal BASE)",
            ["Ano", "Contratos", "Valor"],
            list(reversed(linhas)),
        ))

    fornecedores = contratos.get("fornecedores") or []
    if fornecedores:
        corpo.append(_tabela(
            "Principais fornecedores",
            ["Fornecedor", "Contratos", "Valor"],
            [[item.get("nome") or "", _numero(item.get("contratos")), _euros(item.get("valor"))] for item in fornecedores],
        ))

    fontes = [fonte.get("documento") for fonte in (dados.get("fontes") or []) if fonte.get("documento")]
    if fontes:
        recolhido = _date(dados.get("recolhido_em")) if dados.get("recolhido_em") else ""
        nota = " · ".join(fontes)
        if recolhido:
            nota += f" · dados recolhidos a {recolhido}"
        corpo.append(f'<div class="section aviso">{_esc(nota)}</div>')

    return "".join(bloco for bloco in corpo if bloco)


def render_municipio(
    doc: Dict[str, Any],
    *,
    preview: bool = False,
    settings: Optional[Dict[str, Any]] = None,
) -> str:
    """Ficha pública de um município: texto editorial e os números oficiais."""
    settings = settings or store.get_settings()
    seo = doc.get("seo") or {}
    dados = doc.get("dados") if isinstance(doc.get("dados"), dict) else {}
    municipio = str(doc.get("municipio") or dados.get("municipio") or doc.get("title") or "")
    path = f"/site/municipio/{doc.get('slug')}" if doc.get("slug") else "/site"
    base_url = str(settings.get("base_url") or "")
    descricao = str(seo.get("description") or doc.get("excerpt") or "").strip() or (
        f"Despesa e contratação pública da Câmara Municipal de {municipio}."
    )
    json_ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": doc.get("title") or municipio,
        "description": descricao,
        "url": _absolute(path, base_url),
        "about": {"@type": "GovernmentOrganization", "name": f"Câmara Municipal de {municipio}"},
        "isBasedOn": [fonte.get("url") for fonte in (dados.get("fontes") or []) if fonte.get("url")],
    }
    return _layout(
        title=str(seo.get("title") or doc.get("title") or municipio),
        description=descricao,
        body=_corpo_do_municipio(dados, doc, preview=preview),
        current_path=path,
        settings=settings,
        canonical=path,
        og_image=_media_url(seo.get("image_id")),
        keywords=seo.get("keywords") or None,
        json_ld=json_ld,
        preview=preview,
        noindex=bool(seo.get("noindex")),
        breadcrumb=[
            {"label": "Início", "href": "/site"},
            {"label": "Municípios"},
            {"label": municipio},
        ],
    )


# --------------------------------------------------------------------------
# Página de uma pesquisa (entidade `pesquisas`)
# --------------------------------------------------------------------------
_CSS_PESQUISA = """
.pesquisa-marca { display: flex; align-items: center; gap: 14px; margin: 0 0 16px; }
.pesquisa-marca img { max-height: 54px; width: auto; }
.pesquisa-capa { margin: 0 0 22px; }
.pesquisa-capa img { width: 100%; border-radius: var(--radius); border: 1px solid var(--border); }
.pesquisa-tabela { overflow-x: auto; }
.pesquisa-tabela th, .pesquisa-tabela td { white-space: nowrap; }
.pesquisa-anos { color: var(--muted); font-size: .85rem; }
.grafico { margin: 0 0 26px; }
.grafico h3 { margin: 0 0 2px; font-size: 1rem; }
.grafico p.sub { margin: 0 0 12px; color: var(--muted); font-size: .82rem; }
.barras { list-style: none; margin: 0; padding: 0; display: grid; gap: 7px; }
.barras li { display: grid; grid-template-columns: minmax(90px, 190px) 1fr auto; align-items: center; gap: 10px; font-size: .88rem; }
.barras .rotulo { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.barras .barra { background: color-mix(in srgb, var(--muted) 22%, transparent); border-radius: 999px; height: 9px; }
.barras .barra i { display: block; height: 9px; border-radius: 999px; background: var(--accent); min-width: 2px; }
.barras .valor { font-variant-numeric: tabular-nums; font-weight: 600; white-space: nowrap; }
.barras .valor small { display: block; color: var(--muted); font-weight: 400; font-size: .78rem; }
"""


def _com_ano_despesas(ano: Any) -> str:
    return f"Despesa {ano}" if ano else "Despesa"


def _marca_da_pesquisa(doc: Dict[str, Any]) -> str:
    """Logótipo e imagem de capa **da página** (não das definições do site)."""
    partes: List[str] = []
    logo = _media_url(doc.get("logo_id"))
    if logo:
        partes.append(
            f'<div class="pesquisa-marca"><img src="{_esc(logo)}" '
            f'alt="{_esc(str(doc.get("title") or "Logótipo"))}"></div>'
        )
    capa = _media_url(doc.get("capa_id"))
    if capa:
        partes.append(
            f'<figure class="pesquisa-capa"><img src="{_esc(capa)}" '
            f'alt="{_esc(str(doc.get("title") or ""))}"></figure>'
        )
    return "".join(partes)


def _kpis_da_pesquisa(dados: Dict[str, Any]) -> str:
    ano = dados.get("ano_contratos")
    cartoes = [
        ("Municípios no filtro", _numero(dados.get("total")), "depois dos filtros aplicados"),
        (
            "Despesa somada",
            _euros_curto(dados.get("despesas_somadas")),
            f"INE · ano {dados.get('ano_despesas')}" if dados.get("ano_despesas") else "INE",
        ),
        ("Contratado", _euros_curto(dados.get("contratos_somados")), "Portal BASE · 2012→hoje"),
    ]
    if ano:
        cartoes.append(
            (
                f"Contratado em {ano}",
                _euros_curto(dados.get("contratos_ano_somados")),
                f"{_numero(dados.get('contratos_ano_total_somados'))} contratos",
            )
        )
    abertos = "".join(
        f'<div class="kpi"><span>{_esc(titulo)}</span><strong>{_esc(valor)}</strong>'
        + (f"<small>{_esc(nota)}</small>" if nota else "")
        + "</div>"
        for titulo, valor, nota in cartoes
    )
    return f'<div class="section kpis">{abertos}</div>'


def _tabela_da_pesquisa(dados: Dict[str, Any]) -> str:
    itens = dados.get("itens") or []
    if not itens:
        return '<div class="section aviso">Nenhum município com estes filtros.</div>'
    ano = dados.get("ano_contratos")
    ano_despesas = dados.get("ano_despesas")
    cabecalho = ["Município", "Distrito", _com_ano_despesas(ano_despesas), "Contratado (total)", "Anos recentes"]
    if ano:
        cabecalho = [
            "Município",
            "Distrito",
            _com_ano_despesas(ano_despesas),
            f"Contratos {ano}",
            f"Contratado {ano}",
            "Anos recentes",
        ]
    linhas: List[List[str]] = []
    for item in itens:
        anos_recentes = " · ".join(
            str(registro.get("ano") or "") for registro in (item.get("anos_recentes") or [])[:5]
        )
        linha = [
            str(item.get("nome") or ""),
            str(item.get("distrito") or "—"),
            _euros_curto(item.get("despesas_total")),
        ]
        if ano:
            linha += [_numero(item.get("contratos_ano_total")), _euros_curto(item.get("contratos_ano_valor"))]
        else:
            linha += [_euros_curto(item.get("contratos_valor"))]
        linha.append(anos_recentes)
        linhas.append(linha)
    tabela = _tabela("Municípios do filtro", cabecalho, linhas)
    nota = f"{_numero(dados.get('linhas'))} de {_numero(dados.get('total'))} municípios"
    return (
        f'<div class="pesquisa-tabela">{tabela}</div>'
        f'<div class="section"><p class="meta">{_esc(nota)} · '
        f'{_esc(str(dados.get("descricao") or ""))}</p></div>'
    )


def _corpo_da_pesquisa(dados: Dict[str, Any], doc: Dict[str, Any], *, preview: bool) -> str:
    """Marca + texto editorial + os números que a pesquisa devolveu."""
    partes: List[str] = [_marca_da_pesquisa(doc)]
    if doc.get("intro"):
        partes.append(f'<div class="section prose">{_md(str(doc["intro"]))}</div>')
    if dados.get("descricao"):
        partes.append(
            f'<div class="section"><p class="pill">{_esc(str(dados["descricao"]))}</p></div>'
        )
    partes.append(_kpis_da_pesquisa(dados))
    partes.append(blocks_to_html(doc.get("blocks") or [], preview=preview))
    partes.append(_graficos_da_pesquisa(dados))
    partes.append(_tabela_da_pesquisa(dados))
    partes.append(_adjudicatarios_da_pesquisa(dados))

    fontes = [fonte.get("documento") for fonte in (dados.get("fontes") or []) if fonte.get("documento")]
    if fontes:
        nota = " · ".join(fontes)
        recolhido = _date(dados.get("gerado_em")) if dados.get("gerado_em") else ""
        if recolhido:
            nota += f" · valores lidos a {recolhido}"
        partes.append(f'<div class="section aviso">{_esc(nota)}</div>')
    return "".join(parte for parte in partes if parte)


def _barra_de_valor(valor: float, maximo: float) -> int:
    """A largura da barra, em percentagem do maior valor da série."""
    if maximo <= 0 or valor <= 0:
        return 0
    return max(2, int(round(100 * valor / maximo)))


def _barras(itens: List[Dict[str, Any]], *, unidade: Optional[str] = None) -> str:
    """Gráfico de barras em HTML/CSS.

    Não é uma imagem nem um canvas: o valor e o rótulo ficam **em texto**, por
    isso o gráfico lê-se (e imprime-se) sem cor, e o que está escrito é o mesmo
    número que a tabela mostra.
    """
    valores = [_para_float(item.get("valor")) for item in itens]
    maximo = max(valores) if valores else 0.0
    linhas = []
    for item, valor in zip(itens, valores):
        nota = str(item.get("nota") or "")
        texto = _numero(valor) if unidade == "contratos" else _euros_curto(valor)
        linhas.append(
            f'<li><span class="rotulo">{_esc(item.get("rotulo"))}</span>'
            f'<span class="barra"><i style="width:{_barra_de_valor(valor, maximo)}%"></i></span>'
            f'<span class="valor">{_esc(texto)}'
            + (f"<small>{_esc(nota)}</small>" if nota else "")
            + "</span></li>"
        )
    return f'<ul class="barras">{"".join(linhas)}</ul>'


def _graficos_da_pesquisa(dados: Dict[str, Any]) -> str:
    """As séries da pesquisa (municípios do topo, contratado e despesa por ano)."""
    partes = []
    for grafico in dados.get("graficos") or []:
        itens = grafico.get("itens") or []
        if not itens:
            continue
        partes.append(
            f'<section class="section grafico"><h3>{_esc(grafico.get("titulo"))}</h3>'
            f'<p class="sub">{_esc(grafico.get("subtitulo") or "")}</p>'
            f'{_barras(itens, unidade=grafico.get("unidade"))}</section>'
        )
    return "".join(partes)


def _adjudicatarios_da_pesquisa(dados: Dict[str, Any]) -> str:
    """Os maiores adjudicatários do filtro: barras por cima, tabela por baixo."""
    bloco = dados.get("adjudicatarios") or {}
    itens = bloco.get("itens") or []
    if not itens:
        return ""
    ano = bloco.get("ano")
    titulo = "Principais adjudicatários" + (f" em {ano}" if ano else "")
    considerados = _numero(bloco.get("municipios"))
    subtitulo = (
        f"{_numero(bloco.get('total'))} adjudicatários"
        + (f" nos contratos dos {considerados} municípios considerados" if bloco.get("municipios") else "")
        + f" · {_euros_curto(bloco.get('valor'))} adjudicados · "
        "um contrato com vários adjudicatários conta em cada um"
    )
    cabecalho = ["Adjudicatário", "Contratos", "Valor"]
    linhas = [
        [str(item.get("nome") or ""), _numero(item.get("contratos")), _euros_curto(item.get("valor"))]
        for item in itens
    ]
    barras = [
        {
            "rotulo": item.get("nome"),
            "valor": _para_float(item.get("valor")),
            "nota": f"{_numero(item.get('contratos'))} contratos",
        }
        for item in itens[:12]
    ]
    return (
        '<section class="section grafico"><h3>'
        + _esc(titulo)
        + f'</h3><p class="sub">{_esc(subtitulo)}</p>'
        + _barras(barras)
        + "</section>"
        + _tabela(titulo, cabecalho, linhas)
    )


def render_pesquisa(
    doc: Dict[str, Any],
    *,
    preview: bool = False,
    settings: Optional[Dict[str, Any]] = None,
) -> str:
    """Página pública de uma pesquisa de despesas municipais (filtros congelados)."""
    settings = settings or store.get_settings()
    seo = doc.get("seo") or {}
    dados = doc.get("dados") if isinstance(doc.get("dados"), dict) else {}
    titulo = str(doc.get("title") or "Pesquisa de despesas municipais")
    path = f"/site/pesquisa/{doc.get('slug')}" if doc.get("slug") else "/site"
    base_url = str(settings.get("base_url") or "")
    descricao = str(seo.get("description") or doc.get("excerpt") or "").strip() or (
        f"{titulo}: {dados.get('descricao') or 'despesa e contratação dos municípios'}"
        f" (INE e Portal BASE)."
    )
    cor = str(doc.get("cor") or "").strip()
    extra_css = _CSS_PESQUISA + (f":root {{ --accent: {cor}; }}" if cor else "")
    json_ld = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": titulo,
        "description": descricao,
        "url": _absolute(path, base_url),
        "spatialCoverage": {"@type": "Place", "name": "Portugal"},
        "creator": {"@type": "Organization", "name": str(settings.get("site_name") or "")},
        "isBasedOn": [fonte.get("url") for fonte in (dados.get("fontes") or []) if fonte.get("url")],
    }
    if dados.get("ano_contratos") or dados.get("ano_despesas"):
        json_ld["temporalCoverage"] = str(dados.get("ano_contratos") or dados.get("ano_despesas"))
    return _layout(
        title=str(seo.get("title") or titulo),
        description=descricao,
        body=_corpo_da_pesquisa(dados, doc, preview=preview),
        current_path=path,
        settings=settings,
        canonical=path,
        og_image=_media_url(seo.get("image_id") or doc.get("capa_id")),
        keywords=seo.get("keywords") or None,
        json_ld=json_ld,
        preview=preview,
        noindex=bool(seo.get("noindex")),
        extra_css=extra_css,
        breadcrumb=[
            {"label": "Início", "href": "/site"},
            {"label": "Pesquisas"},
            {"label": titulo},
        ],
    )


def _post_card(post: Dict[str, Any]) -> str:
    href = f"/site/blog/{post.get('slug')}"
    cover = _media_url(post.get("cover_id"))
    image = f'<img src="{_esc(cover)}" alt="" loading="lazy">' if cover else ""
    category = ""
    return (
        f'<article class="card post-card">{image}<div class="body">'
        + (f'<span class="pill">{_esc(post.get("category"))}</span>' if post.get("category") else "")
        + f'<h3><a href="{_esc(href)}">{_esc(post.get("title"))}</a></h3>'
        + f'<p>{_esc(post.get("excerpt") or _plain_excerpt(post))}</p>'
        + '<div class="meta">'
        + (f"<span>{_esc(_date(post.get('published_at')))}</span>" if post.get("published_at") else "")
        + (f"<span>{int(post.get('reading_minutes') or 1)} min de leitura</span>" if post.get("reading_minutes") else "")
        + "</div></div></article>"
    )


def _posts_with_meta(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    categories = {item.get("id"): item.get("name") for item in store.taxonomy()["categories"]}
    enriched = []
    for post in posts:
        item = dict(post)
        names = [categories.get(cid) for cid in (post.get("category_ids") or [])]
        item["category"] = ", ".join(name for name in names if name)
        enriched.append(item)
    return enriched


def render_post(post: Dict[str, Any], *, preview: bool = False, settings: Optional[Dict[str, Any]] = None) -> str:
    settings = settings or store.get_settings()
    seo = post.get("seo") or {}
    categorias = store.taxonomy()["categories"]
    por_id = {item.get("id"): item for item in categorias}
    names = [str((por_id.get(cid) or {}).get("name") or "") for cid in (post.get("category_ids") or [])]
    names = [name for name in names if name]
    cover = _media_url(post.get("cover_id"))
    hero = ""
    if cover:
        hero = f'<figure><img src="{_esc(cover)}" alt="" ></figure>'
    tags = "".join(f'<a class="pill" href="/site/etiqueta/{quote(tag)}">{_esc(tag)}</a> ' for tag in (post.get("tags") or []))
    meta_bits = []
    if post.get("author"):
        meta_bits.append(f'<span>{_esc(post.get("author"))}</span>')
    if post.get("published_at"):
        meta_bits.append(f'<span>{_esc(_date(post.get("published_at")))}</span>')
    if post.get("reading_minutes"):
        meta_bits.append(f"<span>{int(post['reading_minutes'])} min de leitura</span>")
    for name in names:
        meta_bits.append(f'<span class="pill">{_esc(name)}</span>')
    body = (
        '<article class="section">'
        f'<h1>{_esc(post.get("title"))}</h1>'
        f'<div class="meta">{"".join(meta_bits)}</div>'
        f'{hero}'
        f'<div class="prose">{_md(str(post.get("markdown") or ""))}</div>'
        + blocks_to_html(post.get("blocks") or [], preview=preview)
        + (f'<div class="meta" style="margin-top:22px">{tags}</div>' if tags else "")
        + "</article>"
    )
    path = f"/site/blog/{post.get('slug')}"
    base_url = str(settings.get("base_url") or "")
    json_ld = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post.get("title"),
        "description": post.get("excerpt") or _plain_excerpt(post),
        "datePublished": post.get("published_at"),
        "dateModified": post.get("updated_at") or post.get("published_at"),
        "author": {"@type": "Organization" if not post.get("author") else "Person", "name": post.get("author") or settings.get("site_name")},
        "publisher": {"@type": "Organization", "name": settings.get("site_name")},
        "mainEntityOfPage": _absolute(path, base_url),
        "url": _absolute(path, base_url),
    }
    if cover:
        json_ld["image"] = _absolute(cover, base_url)
    trilha: List[Dict[str, str]] = [
        {"label": "Início", "href": "/site"},
        {"label": "Blog", "href": "/site/blog"},
    ]
    primeira = next((item for item in categorias if item.get("name") == names[0]), None) if names else None
    if primeira and primeira.get("slug"):
        trilha.append({"label": names[0], "href": f"/site/categoria/{primeira['slug']}"})
    trilha.append({"label": str(post.get("title") or "")})
    return _layout(
        title=str(seo.get("title") or post.get("title") or ""),
        description=str(seo.get("description") or post.get("excerpt") or _plain_excerpt(post)),
        body=body,
        current_path=path,
        settings=settings,
        canonical=path,
        og_type="article",
        og_image=_media_url(seo.get("image_id")) or cover,
        keywords=(seo.get("keywords") or post.get("tags") or None),
        json_ld=json_ld,
        preview=preview,
        noindex=bool(seo.get("noindex")),
        breadcrumb=trilha,
    )


def render_blog(
    *,
    page_no: int = 1,
    category: Optional[Dict[str, Any]] = None,
    tag: Optional[str] = None,
    preview: bool = False,
    settings: Optional[Dict[str, Any]] = None,
) -> str:
    settings = settings or store.get_settings()
    per_page = int(settings.get("posts_per_page") or 9)
    posts = store.published_posts(
        category_id=str(category.get("id")) if category else None,
        tag=tag,
    )
    total_pages = max(1, (len(posts) + per_page - 1) // per_page)
    page_no = max(1, min(page_no, total_pages))
    window = _posts_with_meta(posts[(page_no - 1) * per_page : page_no * per_page])

    if category:
        title = f'Blog · {category.get("name")}'
    elif tag:
        title = f"Blog · {tag}"
    else:
        title = "Blog"
    intro = str((category or {}).get("description") or "") or (
        f"Artigos com a etiqueta «{tag}»." if tag else "Análises, método e novidades da plataforma."
    )

    base_path = "/site/blog"
    if category:
        base_path = f"/site/categoria/{category.get('slug')}"
    elif tag:
        base_path = f"/site/etiqueta/{quote(tag)}"

    taxonomy = store.taxonomy()
    filters = ""
    if taxonomy["categories"] or taxonomy["tags"]:
        chips = [
            f'<a class="pill" href="/site/categoria/{_esc(item.get("slug"))}">{_esc(item.get("name"))} · {item.get("posts")}</a>'
            for item in taxonomy["categories"]
        ]
        chips += [
            f'<a class="pill" href="/site/etiqueta/{quote(item.get("tag"))}">{_esc(item.get("tag"))} · {item.get("posts")}</a>'
            for item in taxonomy["tags"][:12]
        ]
        filters = f'<div class="meta" style="flex-wrap:wrap;gap:8px">{ " ".join(chips) }</div>'

    if window:
        cards = f'<div class="posts">{"".join(_post_card(post) for post in window)}</div>'
    else:
        cards = '<p class="lead">Ainda não há artigos publicados.</p>'

    pager = ""
    if total_pages > 1:
        links = []
        for number in range(1, total_pages + 1):
            href = base_path + (f"?page={number}" if number > 1 else "")
            if number == page_no:
                links.append(f"<span class=\"current\">{number}</span>")
            else:
                links.append(f'<a href="{_esc(href)}">{number}</a>')
        pager = f'<div class="pager">{"".join(links)}</div>'

    body = (
        f'<section class="section"><h1>{_esc(title)}</h1><p class="lead">{_esc(intro)}</p>{filters}</section>'
        f'<section class="section">{cards}</section>{pager}'
    )
    path = base_path + (f"?page={page_no}" if page_no > 1 else "")
    trilha: List[Dict[str, str]] = [{"label": "Início", "href": "/site"}]
    if category or tag:
        trilha.append({"label": "Blog", "href": "/site/blog"})
        trilha.append({"label": str((category or {}).get("name") or tag or "")})
    else:
        trilha.append({"label": "Blog"})
    return _layout(
        title=title,
        description=str((category or {}).get("description") or intro),
        body=body,
        current_path=path,
        settings=settings,
        canonical=base_path if page_no == 1 else base_path,
        preview=preview,
        breadcrumb=trilha,
    )


def render_index(*, preview: bool = False, settings: Optional[Dict[str, Any]] = None) -> str:
    """Página de entrada quando ainda não há página inicial definida."""
    settings = settings or store.get_settings()
    pages = store.published_pages()
    posts = _posts_with_meta(store.published_posts(limit=6))
    tiles = "".join(
        f'<div class="tile"><h3><a href="/site/{_esc(page.get("path"))}">{_esc(page.get("title"))}</a></h3>'
        f'<p>{_esc(page.get("excerpt") or "")}</p></div>'
        for page in pages
        if page.get("path")
    )
    body = (
        f'<section class="section hero"><h1>{_esc(settings.get("site_name"))}</h1>'
        f'<p class="lead">{_esc(settings.get("description"))}</p></section>'
        + (f'<section class="section"><h2>Páginas</h2><div class="grid">{tiles}</div></section>' if tiles else "")
        + f'<section class="section"><h2>Blog</h2><div class="posts">{"".join(_post_card(post) for post in posts)}</div></section>'
    )
    return _layout(
        title=str(settings.get("site_name") or "Site"),
        description=str(settings.get("description") or ""),
        body=body,
        current_path="/site",
        settings=settings,
        preview=preview,
    )


def render_not_found(*, settings: Optional[Dict[str, Any]] = None) -> str:
    settings = settings or store.get_settings()
    body = (
        '<section class="section hero centro"><h1>404</h1>'
        '<p class="lead">Esta página não existe ou ainda não foi publicada.</p>'
        '<div class="actions" style="justify-content:center"><a class="btn" href="/site">Voltar ao início</a></div></section>'
    )
    return _layout(
        title="Página não encontrada",
        description="Conteúdo inexistente ou não publicado.",
        body=body,
        current_path="/site/404",
        settings=settings,
        noindex=True,
    )


# --------------------------------------------------------------------------
# RSS, sitemap e robots
# --------------------------------------------------------------------------
def render_rss(settings: Optional[Dict[str, Any]] = None) -> str:
    settings = settings or store.get_settings()
    base_url = str(settings.get("base_url") or "").rstrip("/")
    posts = store.published_posts(limit=50)
    items = []
    for post in posts:
        link = _absolute(f"/site/blog/{post.get('slug')}", base_url)
        items.append(
            "<item>"
            f"<title>{_esc(post.get('title'))}</title>"
            f"<link>{_esc(link)}</link>"
            f"<guid isPermaLink=\"true\">{_esc(link)}</guid>"
            + (f"<pubDate>{_esc(_rfc822(post.get('published_at')))}</pubDate>" if post.get("published_at") else "")
            + f"<description>{_esc(post.get('excerpt') or _plain_excerpt(post))}</description>"
            + "".join(f"<category>{_esc(tag)}</category>" for tag in (post.get("tags") or []))
            + "</item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
        f"<title>{_esc(settings.get('site_name'))}</title>"
        f"<link>{_esc(base_url or '/site')}</link>"
        f"<description>{_esc(settings.get('description'))}</description>"
        f"<language>{_esc(str(settings.get('language') or 'pt-PT'))}</language>"
        + (f'<atom:link href="{_esc(_absolute("/site/rss.xml", base_url))}" rel="self" type="application/rss+xml"/>' if base_url else "")
        + "".join(items)
        + "</channel></rss>"
    )


def _rfc822(value: Optional[str]) -> str:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return ""
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def render_sitemap(settings: Optional[Dict[str, Any]] = None) -> str:
    settings = settings or store.get_settings()
    base_url = str(settings.get("base_url") or "").rstrip("/")
    entries: List[str] = []
    for page in store.published_pages():
        if (page.get("seo") or {}).get("noindex"):
            continue
        loc = _absolute(f"/site/{page.get('path')}" if page.get("path") else "/site", base_url)
        lastmod = str(page.get("updated_at") or "")[:10]
        entries.append(f"<url><loc>{_esc(loc)}</loc>{f'<lastmod>{lastmod}</lastmod>' if lastmod else ''}<priority>0.9</priority></url>")
    entries.append(f"<url><loc>{_esc(_absolute('/site/blog', base_url))}</loc></url>")
    for municipio in store.published_municipios():
        if (municipio.get("seo") or {}).get("noindex"):
            continue
        slug = str(municipio.get("slug") or "")
        if not slug:
            continue
        loc = _absolute(f"/site/municipio/{slug}", base_url)
        lastmod = str(municipio.get("updated_at") or municipio.get("published_at") or "")[:10]
        entries.append(f"<url><loc>{_esc(loc)}</loc>{f'<lastmod>{lastmod}</lastmod>' if lastmod else ''}<priority>0.8</priority></url>")
    for post in store.published_posts(limit=500):
        if (post.get("seo") or {}).get("noindex"):
            continue
        loc = _absolute(f"/site/blog/{post.get('slug')}", base_url)
        lastmod = str(post.get("updated_at") or post.get("published_at") or "")[:10]
        entries.append(f"<url><loc>{_esc(loc)}</loc>{f'<lastmod>{lastmod}</lastmod>' if lastmod else ''}<priority>0.7</priority></url>")
    for pesquisa in store.published_pesquisas():
        if (pesquisa.get("seo") or {}).get("noindex"):
            continue
        slug = str(pesquisa.get("slug") or "")
        if not slug:
            continue
        loc = _absolute(f"/site/pesquisa/{slug}", base_url)
        lastmod = str(pesquisa.get("updated_at") or pesquisa.get("published_at") or "")[:10]
        entries.append(f"<url><loc>{_esc(loc)}</loc>{f'<lastmod>{lastmod}</lastmod>' if lastmod else ''}<priority>0.8</priority></url>")
    return '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(entries) + "</urlset>"


def render_robots(settings: Optional[Dict[str, Any]] = None) -> str:
    settings = settings or store.get_settings()
    base_url = str(settings.get("base_url") or "").rstrip("/")
    lines = [
        "User-agent: *",
        "Allow: /site/",
        "Disallow: /cms/",
        "",
    ]
    if base_url:
        lines.append(f"Sitemap: {base_url}/site/sitemap.xml")
    return "\n".join(lines) + "\n"
