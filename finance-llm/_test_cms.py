"""Teste do CMS em processo: armazém, publicação, media e renderização do site."""
from __future__ import annotations

import base64
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))

from api import cms_render as render  # noqa: E402
from api import cms_store as store  # noqa: E402

ok = 0


def check(label: str, condition: bool, detail: object = "") -> None:
    global ok
    if condition:
        ok += 1
        print(f"  OK  {label}")
    else:
        print(f" FAIL {label} :: {detail}")
        raise SystemExit(1)


print("== semente e panorama ==")
overview = store.reset_seed()
check("3 páginas semeadas", overview["pages"]["total"] == 3, overview["pages"])
check("2 artigos semeados", overview["posts"]["total"] == 2, overview["posts"])
check("publicadas = 3", overview["pages"]["published"] == 3)
check("categorias = 3", overview["categories"] == 3)
check("modelos = 3", overview["templates"] == 3)
check("atividade registada", len(overview["activity"]) >= 1)

print("== páginas ==")
page = store.save_item(
    "pages",
    {
        "title": "Serviços de Dados",
        "parent_id": "pag_sobre",
        "blocks": [
            {"type": "hero", "data": {"title": "Dados", "subtitle": "Recolha e tratamento"}},
            {"type": "conteudo", "data": {"content_id": "ctd_contactos"}},
        ],
        "show_in_menu": False,
    },
    author="teste@iqos.pt",
)
check("slug gerado", page["slug"] == "servicos-de-dados", page["slug"])
check("caminho com ascendente", page["path"] == "sobre/servicos-de-dados", page["path"])
check("conteúdo conta utilização", store.get_item("contents", "ctd_contactos")["uses"] == 1)

published = store.publish_item("pages", page["id"], "teste@iqos.pt")
check("publicada", published["status"] == "publicado")
check("resolvida por caminho", (store.resolve_page_by_path("sobre/servicos-de-dados") or {}).get("id") == page["id"])
check("não publicada invisível", store.resolve_page_by_path("sobre/servicos-de-dados", published_only=True) is not None)

draft = store.save_item("pages", {"title": "Rascunho Oculto"}, author="teste@iqos.pt")
check("rascunho não resolve no site", store.resolve_page_by_path(draft["path"]) is None)

print("== agendamento ==")
past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
scheduled = store.save_item("posts", {"title": "Agendado Vencido", "markdown": "corpo"}, author="teste@iqos.pt")
scheduled = store.publish_item("posts", scheduled["id"], "teste@iqos.pt", at=past)
check("estado agendado", scheduled["status"] == "agendado")
store._cache = None  # força releitura do ficheiro (dispara o agendador)
check("agendado vencido publicou sozinho", store.get_item("posts", scheduled["id"])["status"] == "publicado")
posts = store.published_posts()
check("blog ordenado por data", posts[0]["id"] == scheduled["id"], [p["id"] for p in posts])
futuro = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
scheduled2 = store.publish_item("posts", scheduled["id"], "teste@iqos.pt", at=futuro)
check("futuro continua agendado", scheduled2["status"] == "agendado")
check("agendado fora do blog", scheduled["id"] not in [p["id"] for p in store.published_posts()])

print("== blog, taxonomia e revisões ==")
taxonomy = store.taxonomy()
check("taxonomia com etiquetas", any(tag["tag"] == "2026" for tag in taxonomy["tags"]), taxonomy["tags"])
post = store.save_item("posts", {"title": "Artigo Editável", "markdown": "linha um", "tags": ["a", "b"]}, author="teste@iqos.pt")
store.save_item("posts", {"id": post["id"], "markdown": "linha um\nlinha dois"}, author="teste@iqos.pt")
revisions = store.revisions_of("posts", post["id"])
check("revisão antes de guardar", len(revisions) >= 1, revisions)
restored = store.restore_revision(revisions[0]["id"], "teste@iqos.pt")
check("restauro devolve o corpo antigo", "linha um" in restored["markdown"] and "linha dois" not in restored["markdown"], restored["markdown"])

print("== media ==")
tiny_png = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c6300010000050001"
        "0d0a2db40000000049454e44ae426082"
    )
).decode("ascii")
media = store.save_media({"filename": "pixel.png", "mime": "image/png", "data": tiny_png, "alt": "pixel"}, author="teste@iqos.pt")
check("media guardado", media["kind"] == "imagem" and media["size"] > 0, media)
path, mime = store.media_file(media["id"])
check("ficheiro no disco", path.is_file() and mime == "image/png", str(path))
store.save_item("pages", {"id": page["id"], "title": "Serviços de Dados", "blocks": [{"type": "imagem", "data": {"media_id": media["id"]}}]}, author="teste@iqos.pt")
usage = store.media_usage(media["id"])
check("uso do media detetado", any(item["id"] == page["id"] for item in usage), usage)

print("== menus e definições ==")
settings = store.save_settings({"site_name": "IQ OS Teste", "accent": "#123456", "posts_per_page": 2}, "teste@iqos.pt")
check("definições guardadas", settings["site_name"] == "IQ OS Teste" and settings["accent"] == "#123456")
header = store.menu_for("header")
check("menu cabeçalho com links", all(item["href"] for item in header["items"]) and len(header["items"]) >= 3, header["items"])
check("rascunho/arquivado fora do menu", all("Rascunho Oculto" != item["label"] for item in header["items"]))

print("== renderização ==")
home = render.render_page(store.get_item("pages", "pag_inicio"))
check("HTML da inicial com blocos", "<h1>" in home and "Últimos artigos" in home and "site-footer" in home, home[:200])
check("CSS com o accent", "#123456" in home)
check("RSS/OG presentes", "og:title" in home and "application/ld+json" in home)
check("bloco de imagem renderiza", "/cms/media/" in render.render_page(store.get_item("pages", page["id"])))
post_html = render.render_post(store.get_item("posts", "post_bemvindo"))
check("artigo com JSON-LD", "BlogPosting" in post_html and "<h1>" in post_html)
blog_html = render.render_blog(page_no=1)
check("blog paginado", "pager" in blog_html and "post-card" in blog_html)
check("categoria filtra", "Bem-vindo" in render.render_blog(category=store.category_by_slug("analises")))
check("etiqueta filtra", "Contratos públicos em 2026" in render.render_blog(tag="mercado"))
check("404 próprio", "404" in render.render_not_found())
rss = render.render_rss()
check("RSS com itens", rss.startswith("<?xml") and "<item>" in rss and "BlogPosting" not in rss)
sitemap = render.render_sitemap()
check("sitemap com páginas e artigos", "<urlset" in sitemap and "/site/blog/bem-vindo-ao-blog" in sitemap)
check("robots bloqueia /cms", "Disallow: /cms/" in render.render_robots())
check("pré-visualização marcada", "Pré-visualização" in render.render_post(store.get_item("posts", post["id"]), preview=True))

print("== apagar ==")
store.delete_item("media", media["id"], "teste@iqos.pt")
check("ficheiro do media apagado", not path.exists())
store.delete_item("pages", "pag_sobre", "teste@iqos.pt")
check("filhos reenraizados", store.get_item("pages", page["id"])["parent_id"] is None)

print(f"\n{ok} verificações OK")
