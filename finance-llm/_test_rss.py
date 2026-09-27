"""Teste do leitor de RSS em processo: modelo, parser, recolha, OPML e rotas.

Não usa rede: o `fetch_and_parse`/`discover` são substituídos por respostas fixas
e a IA é substituída por um resumo de exemplo. As integrações com o Office são
exercidas a sério (documento criado e logo apagado).

**O documento do leitor é escrito num diretório temporário** (`tempfile`): se
apontasse para `data/rss/rss.json`, correr o teste apagava as fontes e os artigos
do utilizador.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import rss_store as store  # noqa: E402

# Antes de tudo: apontar o leitor a um ficheiro temporário.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="iqos_rss_test_"))
store.RSS_DIR = _TMP_DIR
store.RSS_PATH = _TMP_DIR / "rss.json"
store.reset_store()

from api import rss_feed as feed_tools  # noqa: E402
from api import rss_routes as routes  # noqa: E402
from api import rss_service as service  # noqa: E402

ok = 0


def check(label: str, condition: bool, detail: object = "") -> None:
    global ok
    if condition:
        ok += 1
        print(f"  OK  {label}")
    else:
        print(f" FAIL {label} :: {detail}")
        raise SystemExit(1)


SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>Jornal de Teste</title>
    <link>https://exemplo.pt</link>
    <description>Notícias de teste</description>
    <language>pt-PT</language>
    <image><url>https://exemplo.pt/logo.png</url><title>Jornal de Teste</title><link>https://exemplo.pt</link></image>
    <item>
      <title>BCE sobe juros em 25 pontos base</title>
      <link>https://exemplo.pt/artigo/1</link>
      <guid>tag:exemplo.pt,2025:1</guid>
      <pubDate>Tue, 23 Sep 2025 09:30:00 GMT</pubDate>
      <author>Ana Silva</author>
      <category>Economia</category>
      <description>&lt;p&gt;O Banco Central Europeu decidiu subir as taxas de juro.&lt;/p&gt;</description>
      <media:content url="https://exemplo.pt/img/1.jpg" />
    </item>
    <item>
      <title>Lisboa aprova novo plano de habitação</title>
      <link>https://exemplo.pt/artigo/2</link>
      <guid>tag:exemplo.pt,2025:2</guid>
      <pubDate>Mon, 22 Sep 2025 18:00:00 GMT</pubDate>
      <description>&lt;p&gt;O município aprovou o plano com 1.200 fogos.&lt;/p&gt;</description>
    </item>
    <item>
      <title>Empresa de tecnologia capta 12 milhões</title>
      <link>https://exemplo.pt/artigo/3</link>
      <pubDate>Sun, 21 Sep 2025 11:15:00 GMT</pubDate>
      <description>&lt;p&gt;Ronda liderada por um fundo europeu.&lt;/p&gt;</description>
    </item>
  </channel>
</rss>
"""

SAMPLE_OPML = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head><title>Lista de teste</title></head>
  <body>
    <outline text="Economia">
      <outline type="rss" text="Feed A" title="Feed A" xmlUrl="https://a.exemplo/rss" htmlUrl="https://a.exemplo"/>
      <outline type="rss" text="Feed B" title="Feed B" xmlUrl="https://b.exemplo/rss" htmlUrl="https://b.exemplo"/>
    </outline>
    <outline type="rss" text="Feed C" title="Feed C" xmlUrl="https://c.exemplo/rss" htmlUrl="https://c.exemplo"/>
  </body>
</opml>
"""


def _fake_fetch(url, *, etag=None, last_modified=None):
    if etag == "etag-igual":
        return {"status": "not_modified", "feed": None, "error": None, "etag": etag, "last_modified": "", "url": url}
    if "falha" in url:
        return {"status": "error", "feed": None, "error": "HTTP 500", "url": url}
    if "sem-itens" in url:
        return {"status": "ok", "feed": feed_tools.parse_feed("<rss version='2.0'><channel><title>Vazio</title></channel></rss>"), "error": None, "etag": "e1", "last_modified": "", "url": url}
    parsed = feed_tools.parse_feed(SAMPLE)
    parsed["title"] = parsed["title"] if "a.exemplo" not in url else "Feed A"
    return {"status": "ok", "feed": parsed, "error": None, "etag": "etag-1", "last_modified": "Wed, 24 Sep 2025 10:00:00 GMT", "url": url}


def _fake_discover(url):
    if "sem-feed" in url:
        return {"feed_url": None, "candidates": ["https://x.exemplo/feed"], "error": "Não foi encontrado nenhum feed RSS/Atom nesse endereço."}
    return {"feed_url": "https://exemplo.pt/rss", "candidates": ["https://exemplo.pt/rss"], "error": None}


feed_tools.fetch_and_parse = _fake_fetch  # type: ignore[assignment]
feed_tools.discover = _fake_discover  # type: ignore[assignment]
feed_tools.sleep = lambda _seconds: None  # type: ignore[assignment]


def _fake_complete(prompt, *, user_id=None, provider=None, model=None, max_tokens=900):
    return {"ok": True, "digest": "- Ponto um\n- Ponto dois", "ai": {"provider": "fake", "model": "fake"}}


service._complete = _fake_complete  # type: ignore[assignment]


class _FakeUser:
    id = "usr_teste"
    email = "teste@iqos.local"
    role = "admin"


class _FakeSession:
    user = _FakeUser()


SESSION = _FakeSession()

print("== modelo: pastas, fontes e artigos ==")
store.reset_store()
check("catalogue vazio", store.catalogue()["totals"]["articles"] == 0)
panorama = store.overview()
check("panorama sem feeds", panorama["feeds"]["total"] == 0 and panorama["articles"]["total"] == 0)

folder = store.save_folder({"name": "Economia", "color": "teal"})
check("pasta criada com id", str(folder["id"]).startswith("fold_"), folder)
check("pasta com cor validada", folder["color"] == "teal", folder)
bad_color = store.save_folder({"name": "Sem cor válida", "color": "cor-inventada"})
check("cor inválida cai no valor por omissão", bad_color["color"] == "teal", bad_color)
store.delete_folder(bad_color["id"])

feed = store.save_feed({"url": "https://exemplo.pt/rss", "title": "Jornal de Teste", "folder_id": folder["id"], "tags": ["economia"]})
check("fonte criada", str(feed["id"]).startswith("feed_"), feed)
check("fonte na pasta", feed["folder_id"] == folder["id"], feed)
check("estado inicial «nunca»", feed["last_status"] == "nunca", feed)

try:
    store.save_feed({"url": "https://exemplo.pt/rss", "title": "Duplicado"})
    check("feed duplicado é recusado", False)
except ValueError as exc:
    check("feed duplicado é recusado", "já está subscrito" in str(exc), exc)

try:
    store.save_feed({"url": "ftp://exemplo.pt/rss"})
    check("URL inválido é recusado", False)
except ValueError as exc:
    check("URL inválido é recusado", "http://" in str(exc), exc)

print("== parser de RSS ==")
parsed = feed_tools.parse_feed(SAMPLE)
check("título do feed", parsed["title"] == "Jornal de Teste", parsed["title"])
check("site do feed", parsed["site_url"] == "https://exemplo.pt", parsed["site_url"])
check("idioma", parsed["language"] == "pt-pt", parsed["language"])
check("ícone", parsed["icon_url"] == "https://exemplo.pt/logo.png", parsed["icon_url"])
check("3 artigos", len(parsed["entries"]) == 3, len(parsed["entries"]))
first = parsed["entries"][0]
check("guid do artigo", first["guid"] == "tag:exemplo.pt,2025:1", first["guid"])
check("data normalizada em ISO", str(first["published_at"]).startswith("2025-09-23T09:30"), first["published_at"])
check("resumo sem HTML", "<p>" not in first["summary"] and "Banco Central" in first["summary"], first["summary"])
check("imagem do media:content", first["image_url"] == "https://exemplo.pt/img/1.jpg", first["image_url"])
check("autor", first["author"] == "Ana Silva", first["author"])
check("categoria", first["categories"] == ["Economia"], first["categories"])
check("tempo de leitura calculado", first["reading_minutes"] >= 1, first["reading_minutes"])

print("== recolha e deduplicação ==")
result = service.refresh_feed(feed["id"])
check("recolha ok", result["status"] == "ok", result)
check("3 artigos guardados", result["added"] == 3, result)
check("etag guardado", store.get_feed(feed["id"])["etag"] == "etag-1", store.get_feed(feed["id"]))
again = service.refresh_feed(feed["id"])
check("segunda recolha não duplica", again["added"] == 0, again)
check("segunda recolha fica «sem novidades»", again["status"] == "sem_novidades", again)

store.feed_state(feed["id"], {"etag": "etag-igual"})
not_modified = service.refresh_feed(feed["id"])
check("304 tratado como sem alterações", not_modified["status"] == "nao_modificado", not_modified)

listing = store.list_articles()
check("3 artigos listados", listing["total"] == 3, listing)
check("3 não lidos", listing["unread"] == 3, listing["unread"])
check("não lidos por fonte", listing["unread_by_feed"][feed["id"]] == 3, listing["unread_by_feed"])
check("resumo traz a fonte", listing["items"][0]["feed_title"] == "Jornal de Teste", listing["items"][0])
check("ordem descendente pela data", listing["items"][0]["title"].startswith("BCE"), listing["items"][0]["title"])
ascending = store.list_articles(order="asc")
check("ordem ascendente", ascending["items"][0]["title"].startswith("Empresa"), ascending["items"][0]["title"])

print("== estados dos artigos ==")
article = store.get_article(listing["items"][0]["id"], mark_read=True)
check("abrir marca como lido", article["read"] is True, article["read"])
check("artigo traz conteúdo", "Banco Central" in article["content"], article["content"][:80])
check("2 não lidos depois de ler um", store.list_articles(unread=True)["total"] == 2)
store.update_article(article["id"], {"favorite": True})
check("favorito guardado", store.list_articles(favorite=True)["total"] == 1)
third = store.list_articles(order="asc")["items"][0]
store.update_article(third["id"], {"saved": True})
check("guardado", store.list_articles(saved=True)["total"] == 1)
check("pesquisa por texto", store.search("habitação")["items"][0]["title"].startswith("Lisboa"), store.search("habitação"))
check("pesquisa curta não devolve nada", store.search("a")["items"] == [])
mark = store.mark_all_read()
check("marcar tudo como lido", mark["updated"] == 2, mark)
check("nada não lido", store.list_articles(unread=True)["total"] == 0)
purge = store.purge_read()
check("limpar lidos preserva favorito e guardado", purge["removed"] == 1, purge)
check("ficaram 2 artigos", store.list_articles()["total"] == 2, store.list_articles()["total"])

print("== pastas e fed ==")
folder_view = store.get_folder(folder["id"])
check("pasta conta feeds", folder_view["feeds"] == 1, folder_view)
check("pasta conta não lidos", folder_view["unread"] == 0, folder_view)
new_folder = store.save_folder({"name": "Mercados", "order": 1})
moved = store.save_feed({"id": feed["id"], "folder_id": new_folder["id"], "tags": ["mercados", "europa"]})
check("fonte muda de pasta", moved["folder_id"] == new_folder["id"], moved)
check("etiquetas atualizadas", moved["tags"] == ["mercados", "europa"], moved["tags"])
check("etiquetas agregadas", {item["tag"] for item in store.tags()} == {"mercados", "europa"}, store.tags())
removed = store.delete_folder(new_folder["id"])
check("apagar pasta devolve a fonte", removed["feeds_moved"] == 1, removed)
check("fonte ficou sem pasta", store.get_feed(feed["id"])["folder_id"] is None, store.get_feed(feed["id"]))

print("== exportação ==")
markdown = store.article_markdown(store.get_article(store.list_articles()["items"][0]["id"]))
check("markdown com título", markdown.startswith("# "), markdown[:40])
check("markdown com a fonte", "**Fonte:** Jornal de Teste" in markdown, markdown[:200])
check("markdown com ligação original", "https://exemplo.pt/artigo/" in markdown, markdown[:300])
opml = feed_tools.build_opml(store.list_feeds(), store.list_folders())
check("OPML com a fonte", "xmlUrl=\"https://exemplo.pt/rss\"" in opml, opml[:200])
round_trip = feed_tools.parse_opml(opml)
check("OPML relido", round_trip["feeds"][0]["url"] == "https://exemplo.pt/rss", round_trip)
check("OPML sem erros", round_trip["error"] is None, round_trip)

print("== subscrição, OPML e sugestões ==")
store.reset_store()
subscribed = service.subscribe("https://exemplo.pt", discover=True)
check("descoberta do feed numa página", subscribed["ok"] and subscribed["feed_url"] == "https://exemplo.pt/rss", subscribed)
check("3 artigos na subscrição", subscribed["added"] == 3, subscribed)
check("título aprendido do feed", subscribed["feed"]["title"] == "Jornal de Teste", subscribed["feed"]["title"])
duplicate = service.subscribe("https://exemplo.pt/rss", discover=False)
check("subscrever duas vezes é recusado", duplicate["ok"] is False and "já está subscrito" in duplicate["error"], duplicate)
no_feed = service.subscribe("https://sem-feed.exemplo", discover=True)
check("página sem feed explica o motivo", no_feed["ok"] is False and "Não foi encontrado" in no_feed["error"], no_feed)

with_failure = service.subscribe("https://falha.exemplo/rss", discover=False)
check("subscrever um feed que falha mantém a fonte", with_failure["ok"] is True, with_failure)
failure_refresh = service.refresh_feed(with_failure["feed"]["id"])
check("recolha com erro registada", failure_refresh["status"] == "erro" and failure_refresh["feed"]["last_status"] == "erro", failure_refresh)
check("panorama conta fontes com erro", store.overview()["feeds"]["with_error"] == 1, store.overview()["feeds"])

store.reset_store()
imported = service.import_opml(SAMPLE_OPML, fetch_limit=2)
check("importação cria pastas", imported["folders_created"] == 1, imported)
check("importação cria 3 fontes", imported["feeds_created"] == 3, imported)
check("importação recolhe só o limite", imported["fetched"] == 2, imported)
check("importação deixa pendentes", imported["pending"] == 1, imported)
check("fonte importada na pasta", any(feed["folder_name"] == "Economia" for feed in store.list_feeds()), store.list_feeds())
check("importar de novo não duplica", service.import_opml(SAMPLE_OPML)["feeds_created"] == 0)
bad_opml = service.import_opml("<opml>sem feeds</opml>")
check("OPML sem feeds é recusado", bad_opml["ok"] is False, bad_opml)

refreshed = service.refresh_all()
check("recolher todas completa as pendentes", refreshed["feeds"] == 3 and refreshed["added"] == 3, refreshed)

suggestions = service.suggestions()
check("catálogo de sugestões", suggestions["total"] >= 20, suggestions["total"])
check("categorias presentes", "Portugal" in suggestions["categories"], suggestions["categories"])
check("sugestões por subscrever", all(not item["subscribed"] for item in suggestions["items"]))
check("temas mais frequentes", isinstance(service.trending_terms(), list))

print("== digest por IA (motor substituído) ==")
article_id = store.list_articles()["items"][0]["id"]
digest = service.digest_article(article_id)
check("artigo resumido", digest["ok"] and "Ponto um" in digest["digest"], digest)
check("resumo guardado no artigo", "Ponto um" in store.get_article(article_id)["digest"], store.get_article(article_id)["digest"])
bulletin = service.digest_collection(limit=3, unread=None)
check("boletim de vários artigos", bulletin.get("ok") and bulletin["articles"] >= 1, bulletin)
check("boletim em markdown", "Digest de notícias" in bulletin["markdown"], bulletin["markdown"][:200])
empty_bulletin = service.digest_collection(q="coisa-que-nao-existe", unread=None)
check("boletim sem artigos explica", empty_bulletin["ok"] is False, empty_bulletin)

print("== integrações ==")
sentiment = service.analyze_sentiment(article_id)
check("análise de sentimento do artigo", sentiment["ok"] and "label" in sentiment["analysis"], sentiment)
office = service.to_office(article_id, author="teste@iqos.local")
check("artigo enviado para o Office", office["ok"] and office["document_id"], office)
check("markdown do Office traz a fonte", "**Fonte:** Feed A" in str(office["document"]["markdown"]), office["document"]["markdown"][:200])
check("artigo marcado como guardado", store.get_article(article_id)["saved"] is True)
from api import office_store  # noqa: E402

office_store.delete_document(office["document_id"])
remaining = {item["id"] for item in office_store.list_documents().get("items", [])}
check("documento de teste removido do Office", office["document_id"] not in remaining, remaining)

saved_digest = service.save_digest_to_office(bulletin["markdown"], title="Digest de teste")
check("boletim guardado no Office", saved_digest["ok"] and saved_digest["document"]["kind"] == "relatorio", saved_digest)
office_store.delete_document(saved_digest["document_id"])

missing = service.to_office("art_inexistente")
check("integração com id inválido devolve erro claro", missing["ok"] is False and "não existe" in missing["error"], missing)

print("== rotas ==")
store.reset_store()
folder = routes.rss_create_folder({"name": "Rotas"}, session=SESSION)["folder"]
created = routes.rss_create_feed({"url": "https://exemplo.pt", "folder_id": folder["id"]}, session=SESSION)
check("rota de subscrição descobre o feed", created["ok"] and created["added"] == 3, created)
from fastapi import HTTPException  # noqa: E402

try:
    routes.rss_create_feed({"url": "https://exemplo.pt/rss", "discover": False}, session=SESSION)
    check("rota recusa duplicado", False)
except HTTPException as exc:
    check("rota recusa duplicado com 422", exc.status_code == 422, exc)
try:
    routes.rss_create_feed({"url": "https://exemplo.pt/rss"}, session=None)
    check("escrita exige sessão", False)
except HTTPException as exc:
    check("escrita exige sessão (401)", exc.status_code == 401, exc)

listing = routes.rss_list_articles(limit=10)
check("rota de artigos", listing["total"] == 3, listing)
feed_id = created["feed"]["id"]
check("rota de fontes", routes.rss_list_feeds(folder_id="all")["total"] == 1)
check("rota de fonte individual", routes.rss_get_feed(feed_id)["feed"]["id"] == feed_id)
overview = routes.rss_overview()
check("rota de panorama", "trending" in overview and "schedule" in overview and overview["articles"]["unread"] == 3, overview["articles"])
catalogue = routes.rss_catalogue()
check("rota de catálogo", catalogue["totals"]["unread"] == 3, catalogue["totals"])
check("rota de pesquisa", routes.rss_search(q="BCE")["items"][0]["title"].startswith("BCE"), routes.rss_search(q="BCE"))
check("rota de sugestões", routes.rss_suggestions()["total"] >= 20)
subs = routes.rss_subscribe_suggestions({"ids": ["eco"]}, session=SESSION)
check("subscrever sugestão", subs["subscribed"] == 1, subs)
marked_suggestion = next(item for item in service.suggestions()["items"] if item["id"] == "eco")
check("sugestão subscrita marcada", marked_suggestion["subscribed"] is True, marked_suggestion)
repeated = routes.rss_subscribe_suggestions({"ids": ["eco"]}, session=SESSION)
check("repetir a subscrição falha com motivo", repeated["subscribed"] == 0 and "já está subscrito" in repeated["failed"][0], repeated)

article_id = listing["items"][0]["id"]
check("rota marca favorito", routes.rss_patch_article(article_id, {"favorite": True}, session=SESSION)["article"]["favorite"] is True)
marked = routes.rss_read_all({}, session=SESSION)
check("rota marca lidos", marked["updated"] == 6, marked)
purged = routes.rss_purge_read({}, session=SESSION)
check("rota limpa lidos e preserva o favorito", purged["removed"] == 5 and store.list_articles()["total"] == 1, purged)
check("rota de recolha de uma fonte", routes.rss_fetch_feed(feed_id, force=True, session=SESSION)["status"] == "ok")
all_feeds = routes.rss_fetch_all(force=False, session=SESSION)
check("rota de recolha de todas", all_feeds["feeds"] == 2, all_feeds)
check("rota de digest do artigo", routes.rss_digest_article(article_id, {}, session=SESSION)["ok"] is True)
check("rota de digest de vários", routes.rss_articles_digest({"limit": 2}, session=SESSION)["articles"] >= 1)
check("rota de sentimento", routes.rss_to_sentiment(article_id)["ok"] is True)
check("rota de OPML", routes.rss_export_opml().body.decode("utf-8").count("https://") >= 1)
imported_route = routes.rss_import_opml({"opml": SAMPLE_OPML, "fetch_limit": 0}, session=SESSION)
check("rota de importação OPML", imported_route["feeds_created"] == 3, imported_route)

schedule = routes.rss_save_schedule({"cron": "*/30 * * * *", "auto_fetch": True, "max_articles_per_feed": 120}, session=SESSION)
check("agenda gravada", schedule["saved"] and schedule["settings"]["cron"] == "*/30 * * * *", schedule["settings"])
check("agenda visível no estado", routes.rss_schedule()["cron"] == "*/30 * * * *", routes.rss_schedule())
check("limites validados", store.settings()["max_articles_per_feed"] == 120, store.settings())
try:
    routes.rss_save_schedule({"cron": "x"}, session=None)
    check("agenda exige sessão", False)
except HTTPException as exc:
    check("agenda exige sessão (401)", exc.status_code == 401, exc)

removed_feed = routes.rss_delete_feed(feed_id, session=SESSION)
check("apagar fonte remove artigos", removed_feed["articles_removed"] == 3, removed_feed)
check("fonte apagada deixou de existir", all(item["id"] != feed_id for item in store.list_feeds()))
check("pasta apagada", routes.rss_delete_folder(folder["id"], session=SESSION)["deleted"] is True)

print("== regras automáticas ==")
store.reset_store()
folder = store.save_folder({"name": "Tecnologia"})
feed = store.save_feed({"url": "https://exemplo.pt/rss", "title": "Jornal de Teste", "folder_id": folder["id"]})
saved_rules = store.save_rules(
    [
        {"term": "juros", "actions": ["saved", "favorite"], "tags": ["macroeconomia"]},
        {"term": "habitação", "actions": ["saved"], "tags": ["imobiliário", "portugal"]},
        {"term": "inexistente-xyz", "actions": ["read"]},
        {"term": "a", "actions": ["read"]},
        {"term": "sem ações"},
    ]
)
check("regras válidas guardadas", len(saved_rules["rules"]) == 3, saved_rules)
check("termo demasiado curto descartado", all(rule["term"] != "a" for rule in saved_rules["rules"]), saved_rules)
check("regra sem ações descartada", all(rule["term"] != "sem ações" for rule in saved_rules["rules"]), saved_rules)

refreshed = service.refresh_feed(feed["id"])
check("recolha aplica as regras", refreshed["added"] == 3 and refreshed["rule_hits"] == 2, refreshed)
listing = store.list_articles()
bce = next(item for item in listing["items"] if item["title"].startswith("BCE"))
hab = next(item for item in listing["items"] if item["title"].startswith("Lisboa"))
tec = next(item for item in listing["items"] if item["title"].startswith("Empresa"))
check("regra guardou e favoritou o artigo dos juros", bce["saved"] and bce["favorite"], bce)
check("regra etiquetou o artigo dos juros", bce["tags"] == ["macroeconomia"], bce["tags"])
check("regra etiquetou o artigo da habitação", set(hab["tags"]) == {"imobiliário", "portugal"}, hab["tags"])
check("artigo sem regra ficou intacto", not tec["saved"] and not tec["favorite"] and tec["tags"] == [], tec)
check("contador de ocorrências por regra", [rule["hits"] for rule in store.rules()] == [1, 1, 0], store.rules())

check("etiquetas agregadas", {item["tag"] for item in store.tags()} >= {"macroeconomia", "imobiliário", "portugal"}, store.tags())
check("filtro por etiqueta do artigo", store.list_articles(tag="macro")["total"] == 1, store.list_articles(tag="macro"))
check("filtro por etiqueta sem acentos", store.list_articles(tag="imobiliario")["total"] == 1, store.list_articles(tag="imobiliario"))

related = store.related_articles(hab["id"], limit=5)
check("relacionados devolvem pontuação", isinstance(related, list) and all("score" in item for item in related), related)
check("relacionados não incluem o próprio artigo", hab["id"] not in {item["id"] for item in related}, related)

store.update_article(bce["id"], {"tags": ["juros", "bce"]})
check("etiquetas editáveis no artigo", store.get_article(bce["id"])["tags"] == ["juros", "bce"], store.get_article(bce["id"])["tags"])
check("etiquetas das fontes separadas das do artigo", store.get_article(bce["id"])["feed_tags"] == [], store.get_article(bce["id"])["feed_tags"])

overview = store.overview()
check("série de 14 dias", len(overview["series"]) == 14, len(overview["series"]))
check("série termina hoje", overview["series"][-1]["day"] == store.now()[:10], overview["series"][-1])
check("série ignora artigos fora da janela", sum(item["articles"] for item in overview["series"]) == 0, overview["series"])
check("fontes por volume", overview["top_feeds"][0]["title"] == "Jornal de Teste", overview["top_feeds"])
check("panorama traz as regras", len(overview["rules"]) == 3, overview["rules"])
check("panorama conta etiquetados", overview["articles"]["tagged"] == 2, overview["articles"])
reapplied = store.apply_rules()
check("aplicar regras de novo volta a juntar a etiqueta da regra", reapplied["applied"] == 1 and reapplied["matched"] == 2, reapplied)
check("etiquetas juntam a regra e a edição manual", set(store.get_article(bce["id"])["tags"]) == {"juros", "bce", "macroeconomia"}, store.get_article(bce["id"])["tags"])

print("== exportação ==")
rows = store.export_articles(limit=50)
check("exportação traz os artigos", len(rows) == 3, len(rows))
check("exportação traz as etiquetas", any(row["tags"] for row in rows), rows[0])
csv_payload = service.export_articles_csv(rows, note="teste")
csv_text = csv_payload["content"].decode("utf-8-sig")
check("CSV com separador «;»", ";" in csv_text, csv_text[:120])
check("CSV com BOM para o Excel", csv_payload["content"].startswith(b"\xef\xbb\xbf"), csv_payload["content"][:8])
check("CSV com cabeçalho em português", "Título;Fonte" in csv_text, csv_text.splitlines()[4][:80])
check("CSV com uma linha por artigo", len([line for line in csv_text.splitlines() if line and not line.startswith("#")]) == 4, len(csv_text.splitlines()))
markdown = service.export_articles_markdown(rows, note="teste")
check("Markdown com os três artigos", markdown.count("## [") == 3, markdown[:120])
check("Markdown com a nota de filtros", "teste" in markdown.splitlines()[2], markdown.splitlines()[2])
check("exportação respeita o filtro de etiqueta", len(store.export_articles(tag="macro")) == 1, store.export_articles(tag="macro"))

print("== rotas das funcionalidades novas ==")
check("rota de regras", routes.rss_list_rules()["total"] == 3, routes.rss_list_rules())
check("rota de regras traz as ações", len(routes.rss_list_rules()["actions"]) == 3, routes.rss_list_rules()["actions"])
updated_rules = routes.rss_save_rules({"rules": [{"term": "tecnologia", "actions": ["favorite"], "tags": ["tech"]}]}, session=SESSION)
check("rota grava regras", len(updated_rules["rules"]) == 1 and updated_rules["rules"][0]["term"] == "tecnologia", updated_rules)
applied = routes.rss_apply_rules({"only_unread": False}, session=SESSION)
check("rota aplica as regras", applied["applied"] == 1 and applied["matched"] == 1, applied)
tech_article = store.get_article(tec["id"])
check("artigo de tecnologia ficou favorito e etiquetado", tech_article["favorite"] and tech_article["tags"] == ["tech"], tech_article)
check("rota de etiquetas", any(item["tag"] == "tech" for item in routes.rss_tags()["items"]), routes.rss_tags())
check("rota do artigo traz relacionados", "related" in routes.rss_get_article(hab["id"]))
check("rota de relacionados", routes.rss_related(hab["id"])["total"] >= 0)
csv_route = routes.rss_export(format="csv", limit=10)
check("rota de exportação CSV", csv_route.media_type.startswith("text/csv") and len(csv_route.body) > 100, len(csv_route.body))
md_route = routes.rss_export(format="md", limit=10, unread=True)
check("rota de exportação Markdown", md_route.body.decode("utf-8").count("## [") >= 1, md_route.body[:60])
try:
    routes.rss_save_rules({"rules": []}, session=None)
    check("regras exigem sessão", False)
except HTTPException as exc:
    check("regras exigem sessão (401)", exc.status_code == 401, exc)

print("== série diária com um artigo de hoje ==")
store.store_articles(
    feed["id"],
    [{"guid": "hoje-1", "title": "Notícia de hoje", "url": "https://exemplo.pt/hoje", "summary": "Resumo de hoje", "content": "Texto", "published_at": store.now()}],
)
today_overview = store.overview()
check("série conta o artigo de hoje", today_overview["series"][-1]["articles"] == 1, today_overview["series"][-1])
check("panorama conta os artigos de hoje", today_overview["articles"]["today"] == 1, today_overview["articles"])
check("exportação inclui o artigo novo", len(store.export_articles()) == 4, len(store.export_articles()))

print(f"\n{ok} verificações concluídas sem falhas.")
