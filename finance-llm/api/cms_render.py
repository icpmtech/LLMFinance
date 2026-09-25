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
nav.main {{ margin-left: auto; display: flex; gap: 6px; flex-wrap: wrap; }}
nav.main a {{
  color: var(--text); font-size: .92rem; font-weight: 600; padding: 7px 12px; border-radius: 999px;
}}
nav.main a:hover {{ background: var(--code); text-decoration: none; }}
nav.main a[aria-current="page"] {{ background: var(--accent); color: #fff; }}
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
    banner = '<div class="draft-banner">Pré-visualização — este conteúdo ainda não está publicado</div>' if preview else ""
    return (
        banner
        + '<header class="site-header"><div class="wrap">'
        + f'<a class="brand" href="/site">{_esc(settings.get("site_name"))}{tagline}</a>'
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
        '<meta name="twitter:card" content="summary_large_image">',
    ]
    if og_image:
        meta.append(f'<meta property="og:image" content="{_esc(og_image)}">')
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
    favicon = _media_url(settings.get("favicon_id"))
    if favicon:
        meta.append(f'<link rel="icon" href="{_esc(favicon)}">')
    return (
        "<!doctype html><html lang=\""
        + _esc(str(settings.get("language") or "pt-PT"))
        + '"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        + f"<title>{_esc(full_title)}</title>"
        + "".join(meta)
        + f"<style>{_css(settings)}</style></head><body>"
        + _header(settings, current_path=current_path, preview=preview)
        + f"<main><div class=\"wrap\">{body}</div></main>"
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
    path = f"/site/{page.get('path')}" if page.get("path") else "/site"
    json_ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": page.get("title"),
        "description": _page_description(page),
        "url": _absolute(path, str(settings.get("base_url") or "")),
    }
    return _layout(
        title=str(seo.get("title") or page.get("title") or ""),
        description=_page_description(page),
        body=body,
        current_path=path,
        settings=settings,
        canonical=path,
        og_image=_media_url(seo.get("image_id")),
        keywords=seo.get("keywords") or None,
        json_ld=json_ld,
        preview=preview,
        noindex=bool(seo.get("noindex")),
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
    categories = {item.get("id"): item.get("name") for item in store.taxonomy()["categories"]}
    names = [categories.get(cid) for cid in (post.get("category_ids") or [])]
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
    return _layout(
        title=title,
        description=str((category or {}).get("description") or intro),
        body=body,
        current_path=path,
        settings=settings,
        canonical=base_path if page_no == 1 else base_path,
        preview=preview,
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
    for post in store.published_posts(limit=500):
        if (post.get("seo") or {}).get("noindex"):
            continue
        loc = _absolute(f"/site/blog/{post.get('slug')}", base_url)
        lastmod = str(post.get("updated_at") or post.get("published_at") or "")[:10]
        entries.append(f"<url><loc>{_esc(loc)}</loc>{f'<lastmod>{lastmod}</lastmod>' if lastmod else ''}<priority>0.7</priority></url>")
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
