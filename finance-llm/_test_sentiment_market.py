"""Teste da série de sentimento de mercado em processo: agregação, construção,
panorama, heatmap, relatório e rotas.

Não usa Elasticsearch: os acessos ao índice são substituídos por um armazém em
memória (`_search_news`, `_search_daily`, `_index_daily`, `_list_*`), mas o motor
de sentimento é o real (`api.sentiment_service`), para o teste exercer o léxico.

**As definições são escritas num diretório temporário** (`tempfile`): apontar
para `data/sentiment_market/settings.json` faria o teste reescrever a agenda do
utilizador.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import HTTPException  # noqa: E402

from api import sentiment_market as market  # noqa: E402

# Antes de tudo: definições e lista de tickers num diretório temporário.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="iqos_market_test_"))
market.SETTINGS_DIR = _TMP_DIR
market.SETTINGS_PATH = _TMP_DIR / "settings.json"
market.WATCHLIST_PATH = _TMP_DIR / "tickers.json"

from api import sentiment_market_scheduler as scheduler  # noqa: E402
from api import sentiment_market_routes as routes  # noqa: E402

ok = 0


def check(label: str, condition: bool, detail: object = "") -> None:
    global ok
    if condition:
        ok += 1
        print(f"  OK  {label}")
    else:
        print(f" FAIL {label} :: {detail}")
        raise SystemExit(1)


class _FakeUser:
    id = "usr_teste"
    email = "teste@iqos.local"
    role = "admin"


class _FakeSession:
    user = _FakeUser()


SESSION = _FakeSession()

# --------------------------------------------------------------------------
# Armazém em memória (substitui o Elasticsearch)
# --------------------------------------------------------------------------
TODAY = datetime.now(timezone.utc).date()


def day(offset: int) -> str:
    """Dia ISO a `offset` dias de hoje (0 = hoje)."""
    return (TODAY - timedelta(days=offset)).isoformat()


NEWS: dict = {}
DAILY: dict = {}
PRICES: dict = {}
LIVE_PRICES: dict = {}
FLAGS = {
    "news_error": False,
    "daily_error": False,
    "index_error": False,
    "prices_error": False,
    "prices_index_error": False,
    "ingest_error": False,
}
CALLS: list = []


def _in_range(value: str, start: str | None, end: str | None) -> bool:
    text = str(value or "")[:10]
    if start and text < str(start)[:10]:
        return False
    if end and text > str(end)[:10]:
        return False
    return True


def news_item(ticker, title, summary, published, **extra):
    item = {
        "ticker": ticker,
        "title": title,
        "summary": summary,
        "published": published,
        "publisher": extra.pop("publisher", "Jornal de Teste"),
        "url": extra.pop("url", f"https://exemplo.pt/{ticker.lower()}/{published}"),
    }
    item.update(extra)
    return item


def fake_search_news(ticker, *, q=None, start_date=None, end_date=None, size=100, es=None):
    CALLS.append(("news", str(ticker), start_date, end_date))
    if FLAGS["news_error"]:
        return {"error": "índice de notícias indisponível", "items": []}
    items = [
        item
        for item in NEWS.get(str(ticker).upper(), [])
        if _in_range(item.get("published"), start_date, end_date)
    ]
    return {"items": items[:size], "total": len(items)}


def fake_search_daily(*, ticker=None, start_date=None, end_date=None, size=3000, es=None):
    if FLAGS["daily_error"]:
        return {"error": "índice da série indisponível", "items": []}
    items = [
        document
        for document in DAILY.values()
        if (not ticker or str(document.get("ticker")).upper() == str(ticker).upper())
        and _in_range(document.get("date"), start_date, end_date)
    ]
    items.sort(key=lambda document: str(document.get("date")), reverse=True)
    return {"items": items[:size], "total": len(items)}


def fake_index_daily(rows, *, es=None):
    if FLAGS["index_error"]:
        return {"indexed": 0, "errors": len(rows), "error": "bulk recusado"}
    for row in rows:
        DAILY[f"{row['ticker']}|{row['date']}"] = row
    return {"indexed": len(rows), "errors": 0, "total": len(rows)}


def fake_list_news_tickers(es=None):
    items = [{"ticker": ticker, "news": len(rows)} for ticker, rows in NEWS.items()]
    return {"total": len(items), "items": sorted(items, key=lambda entry: -entry["news"])}


def fake_list_daily_tickers(es=None):
    per: dict = {}
    for document in DAILY.values():
        code = document["ticker"]
        date = str(document["date"])[:10]
        entry = per.setdefault(
            code, {"ticker": code, "documents": 0, "first_date": date, "last_date": date, "news": 0}
        )
        entry["documents"] += 1
        entry["news"] += int(document.get("news_count") or 0)
        entry["first_date"] = min(entry["first_date"], date)
        entry["last_date"] = max(entry["last_date"], date)
    return {"total": len(DAILY), "items": list(per.values())}


def fake_list_price_tickers(es=None):
    return {"total": 1, "items": [{"ticker": "SPCX"}]}


def fake_search_prices(ticker, start_date=None, end_date=None, size=1000, es=None):
    """Substitui `search_prices` (cotações guardadas na plataforma)."""
    code = str(ticker).upper()
    if FLAGS["prices_error"]:
        return {"ticker": code, "error": "índice de preços indisponível", "points": []}
    rows = [row for row in PRICES.get(code, []) if _in_range(row.get("date"), start_date, end_date)]
    return {"ticker": code, "total": len(rows), "points": rows[:size]}


def fake_live_price_rows(ticker: str, days: int):
    """Substitui a ida ao Yahoo Finance (nada de rede nos testes)."""
    return LIVE_PRICES.get(str(ticker).upper(), [])


STORED_PRICES: list = []
DELETED_DAILY: list = []
INGESTED: list = []


class _FakeIngestResult:
    def __init__(self, indexed=0, total=0, analyzed=0, error=None):
        self.indexed_count = indexed
        self.total_items = total
        self.analyzed_count = analyzed
        self.error = error


async def fake_ingest_news(ticker, backend="heuristic", auto_analyze=True):
    """Substitui a recolha de notícias do Yahoo (nada de rede nos testes)."""
    INGESTED.append({"ticker": ticker, "backend": backend, "auto_analyze": auto_analyze})
    if FLAGS["ingest_error"]:
        throw = RuntimeError("Yahoo indisponível")
        raise throw
    if not NEWS.get(str(ticker).upper()):
        return _FakeIngestResult(indexed=0, total=0)
    return _FakeIngestResult(indexed=len(NEWS[str(ticker).upper()]), total=len(NEWS[str(ticker).upper()]), analyzed=2)


def fake_delete_daily(ticker=None, dates=None, es=None):
    """Substitui a eliminação de dias da série (limpeza de dias obsoletos)."""
    wanted = [str(day_value)[:10] for day_value in (dates or []) if day_value]
    DELETED_DAILY.append({"ticker": str(ticker or "").upper(), "dates": wanted})
    removed = 0
    for key in list(DAILY):
        code, _, day_value = key.partition("|")
        if ticker and code != str(ticker).upper():
            continue
        if wanted and day_value not in wanted:
            continue
        del DAILY[key]
        removed += 1
    return {"ok": True, "deleted": removed}


def fake_index_prices(ticker, points, period="1y", es=None):
    """Substitui a gravação das cotações na plataforma."""
    if FLAGS["prices_index_error"]:
        return {"ticker": str(ticker).upper(), "error": "índice de preços recusou", "indexed_count": 0}
    STORED_PRICES.append({"ticker": str(ticker).upper(), "points": [dict(point) for point in points], "period": period})
    return {"ticker": str(ticker).upper(), "indexed_count": len(points), "total_points": len(points), "errors": 0}


market._search_news = fake_search_news  # type: ignore[assignment]
market._search_daily = fake_search_daily  # type: ignore[assignment]
market._index_daily = fake_index_daily  # type: ignore[assignment]
market._list_news_tickers = fake_list_news_tickers  # type: ignore[assignment]
market._list_daily_tickers = fake_list_daily_tickers  # type: ignore[assignment]
market._list_price_tickers = fake_list_price_tickers  # type: ignore[assignment]
market._search_prices = fake_search_prices  # type: ignore[assignment]
market._live_price_rows = fake_live_price_rows  # type: ignore[assignment]
market._index_prices = fake_index_prices  # type: ignore[assignment]
market._delete_daily = fake_delete_daily  # type: ignore[assignment]
market._ingest_news_async = fake_ingest_news  # type: ignore[assignment]

POS = "A empresa apresentou um lucro recorde com forte crescimento e um resultado excelente no trimestre."
NEG = "A empresa registou um prejuizo enorme, com uma queda acentuada e problemas de suspensao nas obras."
NEU = "A empresa realizou uma reuniao com os fornecedores sobre a manutencao das instalacoes industriais."

NEWS["EDP.LS"] = [
    news_item("EDP.LS", "EDP com lucro recorde", POS, f"{day(0)}T09:00:00Z", topics=["energia"]),
    news_item("EDP.LS", "EDP reune fornecedores", NEU, f"{day(0)}T11:30:00Z", topics=["energia", "gestao"]),
    news_item("EDP.LS", "EDP com prejuizo e queda das vendas", NEG, f"{day(1)}T08:15:00Z", topics=["energia"]),
    news_item("EDP.LS", "EDP com prejuizo no trimestre anterior", NEG, f"{day(40)}T08:15:00Z", topics=["energia"]),
]
NEWS["GALP.LS"] = [news_item("GALP.LS", "Galp reune conselho", NEU, f"{day(0)}T10:00:00Z")]
NEWS["CTT.LS"] = [news_item("CTT.LS", "CTT com crescimento forte", POS, f"{day(2)}T10:00:00Z")]
NEWS["SONAE.LS"] = [news_item("SONAE.LS", "Sonae com lucro", POS, f"{day(3)}T10:00:00Z")]

# --------------------------------------------------------------------------
print("== análise das notícias e agregação diária ==")
rows = market.analyze_news_items(NEWS["EDP.LS"], engine="lexicon")
check("uma linha por notícia", len(rows) == 4, len(rows))
check("texto positivo dá etiqueta e evidência", rows[0]["label"] == "positivo" and rows[0]["hits"] >= 3, rows[0])
check("texto negativo dá etiqueta negativa", rows[2]["label"] == "negativo" and rows[2]["polarity"] < -0.5, rows[2])
check("texto sem léxico fica neutro e sem evidência", rows[1]["hits"] == 0 and rows[1]["polarity"] == 0.0, rows[1])
check("dia derivado da data de publicação", rows[0]["day"] == day(0) and rows[2]["day"] == day(1), rows[0])
check("tópicos preservados", rows[0]["topics"] == ["energia"], rows[0]["topics"])
check("motor registado na linha", rows[0]["engine"] == "lexicon" and rows[1]["engine"] == "lexicon", rows[0]["engine"])
check("sem texto escrito não há dia", market.analyze_news_items([{"title": ""}])[0]["day"] is None)

stored = market.analyze_news_items([{"title": "", "sentiment": "positivo", "ticker": "X"}])
check("notícia sem texto aproveita o rótulo gravado", stored[0]["engine"] == "stored" and stored[0]["polarity"] == 0.5, stored[0])
check("rótulo gravado desconhecido cai em neutro", market.analyze_news_items([{"title": "", "sentiment": "???"}])[0]["polarity"] == 0.0)
check("linhas não dicionário são ignoradas", market.analyze_news_items(["texto solto", None]) == [])

daily = market.aggregate_day("edp.ls", day(0), rows)
check("documento diário com ticker em maiúsculas", daily["ticker"] == "EDP.LS", daily["ticker"])
check("contagem de notícias do dia", daily["news_count"] == 2, daily["news_count"])
check("média simples do dia", daily["sentiment_mean"] == 0.5, daily["sentiment_mean"])
check("sinal só conta documentos com evidência", daily["sentiment_signal"] == 1.0, daily["sentiment_signal"])
check("cobertura = 1/2 sem evidência", daily["coverage"] == 0.5, daily["coverage"])
check("documentos com sinal", daily["documents_with_signal"] == 1, daily["documents_with_signal"])
check("positivas e negativas contadas", daily["positive_count"] == 1 and daily["negative_count"] == 0, daily)
check("etiqueta do dia pelo sinal", daily["label"] == "positivo", daily["label"])
check("desvio-padrão populacional", daily["sentiment_std"] == 0.5, daily["sentiment_std"])
check("tópicos e fontes do dia", daily["topics"] == ["energia", "gestao"] and daily["sources"] == ["Jornal de Teste"], daily)
check("destaques 3 melhores + 3 piores", len(daily["highlights"]) == 4, len(daily["highlights"]))
check("melhor destaque à frente", daily["highlights"][0]["polarity"] == 1.0, daily["highlights"][0])
check("dia sem notícias não gera documento", market.aggregate_day("EDP.LS", day(9), rows) is None)

# Notícias repetidas (a mesma história em vários sítios) não podem valer por várias.
check(
    "chave de história normaliza acentos e pontuação",
    market.title_key("EDP: Lucros sobem 20 % no trimestre!")
    == market.title_key("edp lucros sobem 20 no trimestre")
    == market.title_key("  EDP  LUCROS sobem 20 no TRIMESTRE "),
    market.title_key("EDP: Lucros sobem 20 % no trimestre!"),
)
check("chave de história sem título fica vazia", market.title_key("") == "" and market.title_key(None) == "")
_long_title = " ".join(f"palavra{index}" for index in range(20))
check(
    "chave de história usa só o início do título",
    len(market.title_key(_long_title).split()) == market.DEDUPE_PREFIX_TOKENS,
    market.title_key(_long_title),
)
_duplicated = market.analyze_news_items(
    [
        news_item("EDP.LS", "EDP com lucro recorde", POS, f"{day(5)}T09:00:00Z"),
        news_item("EDP.LS", "EDP com lucro recorde", POS, f"{day(5)}T11:00:00Z", publisher="Outro Jornal"),
        news_item("EDP.LS", "EDP com prejuizo e queda", NEG, f"{day(5)}T12:00:00Z"),
    ]
)
_dup_day = market.aggregate_day("EDP.LS", day(5), _duplicated)
check("contagem de notícias mantém o total", _dup_day["news_count"] == 3, _dup_day)
check("histórias distintas contadas à parte", _dup_day["unique_articles"] == 2 and _dup_day["duplicates"] == 1, _dup_day)
check(
    "história repetida não dobra o tom",
    _dup_day["sentiment_mean"] == 0.0 and _dup_day["positive_count"] == 1 and _dup_day["negative_count"] == 1,
    _dup_day,
)
check(
    "a história repetida fica com o primeiro representante",
    {item["title"] for item in _dup_day["highlights"]} == {"EDP com lucro recorde", "EDP com prejuizo e queda"},
    _dup_day["highlights"],
)
check(
    "as fontes continuam a contar todas as notícias",
    _dup_day["sources"] == ["Jornal de Teste", "Outro Jornal"],
    _dup_day["sources"],
)
_distinct_day = market.aggregate_day(
    "EDP.LS",
    day(5),
    market.analyze_news_items(
        [news_item("EDP.LS", "Título um", NEU, f"{day(5)}T09:00:00Z"), news_item("EDP.LS", "Título dois", NEU, f"{day(5)}T10:00:00Z")]
    ),
)
check(
    "sem títulos repetidos não há repetições",
    _distinct_day["unique_articles"] == 2 and _distinct_day["duplicates"] == 0,
    _distinct_day,
)

sat = market.analyze_news_items(
    [
        {"title": "Empresa com queda, prejuizo e crise", "summary": "", "published": f"{day(5)}T09:00:00Z"},
        {"title": "Empresa com lucro", "summary": "", "published": f"{day(5)}T10:00:00Z"},
    ]
)
sat_daily = market.aggregate_day("SAT.LS", day(5), sat)
check(
    "peso da evidência pende para a notícia com mais termos",
    sat_daily["sentiment_signal"] < sat_daily["sentiment_mean"],
    (sat_daily["sentiment_signal"], sat_daily["sentiment_mean"]),
)
check("sinal fica saturado em 3 acertos (peso 1.0)", sat_daily["coverage"] == 1.0, sat_daily["coverage"])

# --------------------------------------------------------------------------
print("== construção da série (idempotente) ==")
check(
    "tickers conhecidos (notícias + mercado)",
    market.known_tickers() == ["EDP.LS", "GALP.LS", "CTT.LS", "SONAE.LS", "SPCX"],
    market.known_tickers(),
)

single = market.build_ticker("EDP.LS", day(1), day(0))
check("constrói um documento por dia com notícias", len(single["documents"]) == 2, single["documents"])
check("notícias contadas no intervalo", single["news"] == 3, single["news"])
check("dias listados", single["days"] == [day(1), day(0)], single["days"])
check("nada saltado sem `existing`", single["skipped"] == 0, single["skipped"])

skipped = market.build_ticker("EDP.LS", day(1), day(0), existing={f"EDP.LS|{day(0)}"})
check("dia já construído é saltado", skipped["skipped"] == 1 and len(skipped["documents"]) == 1, skipped)

FLAGS["news_error"] = True
errored = market.build_ticker("EDP.LS", day(1), day(0))
check("erro de índice devolvido por ticker", "error" in errored and errored["documents"] == [], errored)
FLAGS["news_error"] = False

result = market.build(days=30)
check("janela da construção", result["window"]["days"] == 30 and result["window"]["end"] == day(0), result["window"])
check("tickers considerados", result["tickers"] == 5 and result["tickers_with_news"] == 4, result)
check("notícias somadas", result["news"] == 6, result["news"])
check("um documento por ticker/dia com notícias", result["documents"] == 5, result["documents"])
check("sem erros na construção", result["errors"] == [], result["errors"])
check("detalhe ordenado por notícias", result["details"][0]["ticker"] == "EDP.LS", result["details"][:2])
check("armazém com 5 documentos", len(DAILY) == 5, sorted(DAILY))
check("`only_missing` salta tudo na segunda corrida", market.build(days=30, only_missing=True)["skipped"] == 5, DAILY)
check("segunda corrida não duplica documentos", len(DAILY) == 5, sorted(DAILY))

filtered = market.build(days=30, tickers=["galp.ls"])
check("ticker pedido normalizado para maiúsculas", filtered["tickers"] == 1 and filtered["documents"] == 1, filtered)
check("chave do documento é ticker|dia", f"GALP.LS|{day(0)}" in DAILY, sorted(DAILY))

FLAGS["news_error"] = True
NEWS_BACKUP = dict(NEWS)
NEWS.clear()
_price_backup = market._list_price_tickers  # type: ignore[attr-defined]
market._list_price_tickers = lambda es=None: {"total": 0, "items": []}  # type: ignore[assignment]
no_tickers = market.build(days=30)
market._list_price_tickers = _price_backup  # type: ignore[assignment]
NEWS.update(NEWS_BACKUP)
check("sem tickers conhecidos devolve aviso", no_tickers["tickers"] == 0 and "Sem tickers" in no_tickers["errors"][0], no_tickers)
FLAGS["news_error"] = False

# Documento da janela anterior (para testar a variação e a viragem de sinal).
# Leva duas notícias: uma viragem precisa de evidência nos dois lados.
previous_rows = market.analyze_news_items(
    [
        news_item("EDP.LS", "EDP com prejuizo e crise", NEG, f"{day(40)}T08:15:00Z"),
        news_item("EDP.LS", "EDP registou queda com crise no trimestre", NEG, f"{day(40)}T16:40:00Z"),
    ]
)
market._index_daily([market.aggregate_day("EDP.LS", day(40), previous_rows)])
check("documento da janela anterior gravado", f"EDP.LS|{day(40)}" in DAILY, sorted(DAILY))

FLAGS["index_error"] = True
failed = market.build(days=30, tickers=["CTT.LS"])
check("erro de gravação reportado", failed["documents"] == 0 and failed["errors"], failed)
FLAGS["index_error"] = False

# --------------------------------------------------------------------------
print("== série diária ==")
series = market.series(days=30)
check("série do mercado com 4 dias", series["days"] == 4, series["items"])
check(
    "dias em ordem",
    [item["day"] for item in series["items"]] == [day(3), day(2), day(1), day(0)],
    series["items"],
)
check("série sem ticker", series["ticker"] is None, series["ticker"])
by_day = {item["day"]: item for item in series["items"]}
check("dia com duas fontes ponderado pelas notícias", by_day[day(0)]["sentiment"] == 0.6667, by_day[day(0)])
check("notícias somadas no dia", by_day[day(0)]["news"] == 3 and by_day[day(0)]["tickers"] == 2, by_day[day(0)])
check("cobertura ponderada no dia", by_day[day(0)]["coverage"] == 0.3333, by_day[day(0)])
check("etiqueta da série", by_day[day(2)]["label"] == "positivo" and by_day[day(1)]["label"] == "negativo", series["items"])

edp_series = market.series(ticker="edp.ls", days=30)
check("série de um ticker normaliza o código", edp_series["ticker"] == "EDP.LS", edp_series["ticker"])
check("série do ticker com 2 dias", edp_series["days"] == 2, edp_series["items"])
check("série do ticker ignora a janela anterior", [item["day"] for item in edp_series["items"]] == [day(1), day(0)], edp_series["items"])

FLAGS["daily_error"] = True
check("erro de leitura devolvido na série", "error" in market.series(days=30), market.series(days=30))
FLAGS["daily_error"] = False

# --------------------------------------------------------------------------
print("== panorama, heatmap e rankings ==")
overview = market.overview(days=30, limit=2)
kpis = overview["kpis"]
check("janela e janela anterior", overview["window"]["start"] == day(29) and overview["window"]["previous_end"] == day(30), overview["window"])
check("4 tickers com série", kpis["tickers"] == 4, kpis)
check("6 notícias na janela", kpis["news"] == 6, kpis)
check("tom do mercado ponderado pelas notícias", kpis["sentiment"] == 0.5, kpis)
check("etiqueta do mercado", kpis["label"] == "positivo", kpis)
check("cobertura do mercado", kpis["coverage"] == 0.6667, kpis)
check(
    "rácios de positivas e negativas",
    kpis["positive_ratio"] == 0.5 and abs(kpis["negative_ratio"] - 1 / 6) < 0.001,
    kpis,
)
check("tendência média das variações", kpis["trend"] == 1.3333 and kpis["tickers_with_delta"] == 1, kpis)
check("última data com série", kpis["last_date"] == day(0), kpis)

tickers = {item["ticker"]: item for item in overview["tickers"]}
check(
    "tickers ordenados por notícias",
    [item["ticker"] for item in overview["tickers"]] == ["EDP.LS", "GALP.LS", "CTT.LS", "SONAE.LS"],
    overview["tickers"],
)
check("nível de tom por ticker", tickers["EDP.LS"]["sentiment"] == 0.3333, tickers["EDP.LS"])
check("variação contra a janela anterior", tickers["EDP.LS"]["delta"] == 1.3333 and tickers["EDP.LS"]["previous"] == -1.0, tickers["EDP.LS"])
check("critério do ticker com histórico", tickers["EDP.LS"]["basis"] == "delta", tickers["EDP.LS"])
check("sem histórico não há variação", tickers["GALP.LS"]["delta"] is None and tickers["GALP.LS"]["basis"] == "nivel", tickers["GALP.LS"])
check("ticker só com notícias neutras", tickers["GALP.LS"]["coverage"] == 0.0 and tickers["GALP.LS"]["label"] == "neutro", tickers["GALP.LS"])

check(
    "heatmap com todos os dias da janela",
    overview["heatmap"]["days"] == [day(3), day(2), day(1), day(0)],
    overview["heatmap"]["days"],
)
check("heatmap limitado por `limit`", len(overview["heatmap"]["rows"]) == 2, overview["heatmap"]["rows"])
check("heatmap começa pelo ticker com mais notícias", overview["heatmap"]["rows"][0]["ticker"] == "EDP.LS", overview["heatmap"]["rows"][0])
cells = overview["heatmap"]["rows"][0]["cells"]
check("célula de dia sem notícias é nula", cells[0]["day"] == day(3) and cells[0]["value"] is None, cells[0])
check("célula de dia negativo", cells[2]["value"] == -1.0 and cells[2]["news"] == 1, cells[2])
check("célula com cobertura", cells[3]["value"] == 1.0 and cells[3]["coverage"] == 0.5, cells[3])
check("critério do ranking", overview["ranking"]["basis"] == "delta", overview["ranking"])
check("subidas lideradas pela variação", [item["ticker"] for item in overview["ranking"]["up"]] == ["EDP.LS"], overview["ranking"]["up"])
check("té­mas agregados", overview["topics"][0]["term"] == "energia" and overview["topics"][0]["news"] == 2, overview["topics"])
check("fontes agregadas", overview["sources"] == [{"source": "Jornal de Teste", "news": 5}], overview["sources"])
check("estado incluído no panorama", overview["state"]["documents"] == 6, overview["state"])
check("série do panorama", len(overview["series"]) == 4, overview["series"])

no_previous = market.overview(days=3)
check("janela curta sem histórico anterior", no_previous["ranking"]["basis"] == "nivel", no_previous["ranking"])
check("ranking por nível usa o tom", [item["ticker"] for item in no_previous["ranking"]["up"]][0] == "CTT.LS", no_previous["ranking"]["up"])

FLAGS["daily_error"] = True
check("erro de leitura devolvido no panorama", "error" in market.overview(days=30), "sem error")
FLAGS["daily_error"] = False

# --------------------------------------------------------------------------
print("== detalhe do ticker, estado e cobertura ==")
NEWS["REN.LS"] = [news_item("REN.LS", "REN com lucro forte", POS, f"{day(4)}T10:00:00Z")]
detail = market.ticker_detail("edp.ls", days=30)
check("detalhe normaliza o ticker", detail["ticker"] == "EDP.LS", detail["ticker"])
check("estatísticas do ticker", detail["stats"]["days"] == 2 and detail["stats"]["news"] == 3, detail["stats"])
check("itens da série do ticker", [item["day"] for item in detail["items"]] == [day(1), day(0)], detail["items"])
check("melhor e pior dia", detail["best"]["value"] == 1.0 and detail["worst"]["value"] == -1.0, (detail["best"], detail["worst"]))
check("destaques com motivo", {item["reason"] for item in detail["highlights"]} == {"melhor dia", "pior dia"}, detail["highlights"])
check("destaques trazem dia", all(item["day"] in (day(0), day(1)) for item in detail["highlights"]), detail["highlights"])
check("média e cobertura por dia no detalhe", detail["items"][1]["mean"] == 0.5 and detail["items"][1]["coverage"] == 0.5, detail["items"][1])

empty = market.ticker_detail("ZZZ.LS", days=30)
check("ticker sem série devolve mensagem", empty["items"] == [] and "Sem série" in empty["message"], empty)

# Um só dia com série: os destaques não podem aparecer como melhor *e* pior dia.
single = market.ticker_detail("GALP.LS", days=30)
check("um só dia não repete destaques", {item["reason"] for item in single["highlights"]} == {"único dia com série"}, single["highlights"])
try:
    market.ticker_detail("   ", days=30)
    raise SystemExit("ticker vazio devia falhar")
except KeyError:
    check("ticker vazio levanta KeyError", True)

state = market.state()
check("estado: documentos na série", state["documents"] == 6, state)
check("estado: tickers com série", state["tickers"] == 4, state)
check("estado: primeira e última data", state["first_date"] == day(40) and state["last_date"] == day(0), state)
check("estado: notícias cobertas", state["covered_news"] == 8, state)
check("estado: índice usado", state["index"] == "finance_sentiment_daily", state)
check("estado: os mais ativos à frente", state["top"][0]["ticker"] == "EDP.LS", state["top"])

coverage = market.coverage()
check("cobertura: tickers com notícias", coverage["with_news"] == 5, coverage)
check("cobertura: tickers construídos", coverage["built"] == 4, coverage)
check("cobertura: o que falta construir", coverage["missing"] == ["REN.LS"] and coverage["missing_total"] == 1, coverage)

# --------------------------------------------------------------------------
print("== alertas de movimentos ==")
alerts = market.alerts(days=30)
check("alertas com critérios à vista", alerts["thresholds"]["min_delta"] == 0.25 and alerts["thresholds"]["min_news"] == 2, alerts["thresholds"])
check("alertas: três leituras para o EDP", alerts["total"] == 3, alerts["items"])
check(
    "alertas: tipos presentes",
    {item["kind"] for item in alerts["items"]} == {"subida", "viragem", "extremo"},
    alerts["items"],
)
check(
    "alertas: contagem por tipo",
    {item["kind"]: item["count"] for item in alerts["counts"]} == {"subida": 1, "viragem": 1, "extremo": 1},
    alerts["counts"],
)
first = alerts["items"][0]
check("alerta de subida com variação", first["ticker"] == "EDP.LS" and first["kind"] == "subida" and first["delta"] == 1.3333, first)
check("alerta de subida com severidade e rótulo", first["severity"] == "alta" and first["kind_label"] == "Movimento em alta", first)
check("alerta de subida com tom anterior", first["previous"] == -1.0 and first["news"] == 3, first)
viragem = [item for item in alerts["items"] if item["kind"] == "viragem"][0]
check("alerta de viragem com leitura antes e depois", "«negativo»" in viragem["detail"] and "«positivo»" in viragem["detail"], viragem)
extremo = [item for item in alerts["items"] if item["kind"] == "extremo"][0]
check("alerta de dia extremo com dia e valor", extremo["ticker"] == "EDP.LS" and extremo["day"] == day(0) and extremo["value"] == 1.0, extremo)
check("alerta de dia extremo explica-se", "Dia muito positivo" in extremo["detail"], extremo["detail"])
check("alertas respeitam o mínimo de notícias", not any(item["ticker"] in ("GALP.LS", "CTT.LS", "SONAE.LS") for item in alerts["items"]), alerts["items"])
no_alerts = market.alerts(days=30, min_news=4)
check("mínimo de notícias mais alto silencia os alertas", no_alerts["total"] == 0 and no_alerts["items"] == [], no_alerts)
check("sem alertas a contagem fica vazia", no_alerts["counts"] == [], no_alerts["counts"])
strict = market.alerts(days=30, min_delta=9)
check(
    "variação mínima truncada ao máximo e movimento forte mantido",
    strict["thresholds"]["min_delta"] == 1.0
    and {item["kind"] for item in strict["items"]} == {"subida", "viragem", "extremo"},
    strict["items"],
)
check("variação mínima baixa não inventa alertas", market.alerts(days=30, min_delta=0.05)["total"] == 3, None)
FLAGS["daily_error"] = True
check("erro de leitura devolvido nos alertas", market.alerts(days=30).get("error") and market.alerts(days=30)["items"] == [], None)
FLAGS["daily_error"] = False

# --------------------------------------------------------------------------
print("== limpeza de dias obsoletos ==")


def _stale_doc(ticker: str = "SONAE.LS", day_value: str | None = None):
    """Documento de série sintético (para simular um dia que perdeu as notícias)."""
    return {
        "ticker": ticker,
        "date": day_value or day(8),
        "news_count": 4,
        "unique_articles": 4,
        "duplicates": 0,
        "sentiment_signal": 0.5,
        "sentiment_mean": 0.5,
        "coverage": 1.0,
        "label": "positivo",
        "positive_count": 3,
        "negative_count": 1,
        "topics": [],
        "sources": [],
        "articles": 4,
    }


# Um dia com série mas sem notícias na janela deixa de fazer sentido e é apagado.
market._index_daily([_stale_doc()])
check("dia obsoleto gravado", f"SONAE.LS|{day(8)}" in DAILY, sorted(DAILY))
pruned_run = market.build(days=30, tickers=["SONAE.LS"])
check("dia obsoleto é apagado", pruned_run["pruned"] == 1 and f"SONAE.LS|{day(8)}" not in DAILY, pruned_run)
check("dia com notícias mantém-se", f"SONAE.LS|{day(3)}" in DAILY, sorted(DAILY))
check("limpeza pedida ao índice certo", DELETED_DAILY[-1] == {"ticker": "SONAE.LS", "dates": [day(8)]}, DELETED_DAILY[-1])
market._index_daily([_stale_doc()])
kept_run = market.build(days=30, tickers=["SONAE.LS"], prune=False)
check(
    "sem `prune` nada é apagado",
    kept_run["pruned"] == 0 and f"SONAE.LS|{day(8)}" in DAILY,
    kept_run,
)
# Um ticker cuja pesquisa de notícias falhou não pode ver a série apagada.
market._index_daily([_stale_doc("EDP.LS"), _stale_doc("SONAE.LS")])
FLAGS["news_error"] = True
failed_run = market.build(days=30, tickers=["EDP.LS"])
FLAGS["news_error"] = False
check(
    "ticker com erro não perde a série",
    failed_run["pruned"] == 0 and f"EDP.LS|{day(8)}" in DAILY and bool(failed_run["errors"]),
    failed_run,
)
market._delete_daily("EDP.LS", dates=[day(8)])
market._delete_daily("SONAE.LS", dates=[day(8)])
check("fixtures de limpeza removidos", f"EDP.LS|{day(8)}" not in DAILY and f"SONAE.LS|{day(8)}" not in DAILY, sorted(DAILY))

# --------------------------------------------------------------------------
print("== boletim do mercado ==")
brief = market.brief(days=7)
check("boletim com a janela pedida", brief["window"]["days"] == 7, brief["window"])
check("boletim com KPIs", brief["kpis"]["news"] == 6 and brief["kpis"]["tickers"] == 4, brief["kpis"])
check("boletim com melhor e pior dia", brief["best"]["sentiment"] == 1.0 and brief["worst"]["day"] == day(1), (brief["best"], brief["worst"]))
check(
    "boletim com movimentos (nível de tom sem histórico)",
    brief["movers"]["basis"] == "nivel" and [item["ticker"] for item in brief["movers"]["up"]] == ["CTT.LS", "SONAE.LS", "EDP.LS", "GALP.LS"],
    brief["movers"],
)
check("boletim com alertas", brief["alerts"]["total"] == 1 and brief["alerts"]["items"][0]["kind"] == "extremo", brief["alerts"]["items"])
check("boletim com temas", brief["topics"][0]["term"] == "energia", brief["topics"])
markdown = brief["markdown"]
check("boletim com título", markdown.startswith("# Boletim de sentimento de mercado"), markdown[:60])
check("boletim com resumo", "## Resumo" in markdown and "**Tom ponderado do mercado:** +0.500 (positivo)" in markdown, markdown)
check(
    "boletim com movimentos",
    "## Movimentos" in markdown and "_Critério: nível de tom (sem histórico anterior)." in markdown and "| EDP.LS | +0.333 | — | 3 |" in markdown,
    markdown,
)
check("boletim com alertas", "## Alertas" in markdown and "[Alta]" in markdown, markdown)
check("boletim com temas", "## Temas mais frequentes" in markdown and "**energia**" in markdown, markdown)
check("boletim explica o método", "diluição como neutralidade" in markdown, markdown)
brief30 = market.brief(days=30)
check("boletim de 30 dias com variações", brief30["movers"]["basis"] == "delta" and brief30["movers"]["up"][0]["delta"] == 1.3333, brief30["movers"])
check("boletim de 30 dias mostra a variação na tabela", "+1.333" in brief30["markdown"], brief30["markdown"])
FLAGS["daily_error"] = True
check("erro de leitura devolvido no boletim", market.brief(days=7).get("error") is not None, None)
FLAGS["daily_error"] = False

# --------------------------------------------------------------------------
print("== relatório e exportação ==")
markdown = market.report_markdown(overview, title="Sentimento de mercado — teste")
check("relatório com título", markdown.startswith("# Sentimento de mercado — teste"), markdown[:60])
check("relatório com janela", f"**Janela:** {day(29)} a {day(0)}" in markdown, markdown[:400])
check("relatório com indicadores", "| Tom ponderado | +0.500 (positivo) |" in markdown, markdown)
check("relatório com tendência", "| Tendência vs janela anterior | +1.333 |" in markdown, markdown)
check("relatório com critério do ranking", "variação vs janela anterior" in markdown, markdown)
check("relatório com heatmap", "## Heatmap (ticker × dia)" in markdown and "| EDP.LS |" in markdown, markdown)
check(
    "relatório com cabeçalho de dias",
    "| Ticker | " + " | ".join(item[5:] for item in overview["heatmap"]["days"]) + " |" in markdown,
    markdown,
)
check("relatório com temas", "## Temas mais frequentes" in markdown and "- **energia**" in markdown, markdown)
check("relatório explica o método", "idempotente por `ticker|dia`" in markdown, markdown)
check("relatório sem ranking não rebenta", market.report_markdown({"kpis": {}, "window": {}}).startswith("# Sentimento de mercado"), "")

rows_export = market.export_rows(overview)
check("uma linha por ticker", len(rows_export) == 4, rows_export)
check("colunas do CSV", set(rows_export[0]) == {"ticker", "sentiment", "label", "delta", "previous", "news", "days", "coverage", "positive_ratio", "negative_ratio", "last_date"}, rows_export[0])
check("valores do CSV", rows_export[0]["ticker"] == "EDP.LS" and rows_export[0]["delta"] == 1.3333, rows_export[0])
check("variação ausente fica vazia", rows_export[1]["delta"] is None, rows_export[1])

# --------------------------------------------------------------------------
print("== definições e agenda ==")
check("definições por omissão", market.settings()["cron"] == "30 6 * * *" and market.settings()["days"] == 3, market.settings())
saved = market.save_settings({"cron": "15 5 * * 1-5", "timezone": "Europe/Lisbon", "days": 7, "max_news_per_ticker": 500, "engine": "AUTO"}, "teste@iqos.local")
check("agenda gravada no ficheiro", (_TMP_DIR / "settings.json").exists(), saved)
check("cron e dias gravados", saved["cron"] == "15 5 * * 1-5" and saved["days"] == 7, saved)
check("motor normalizado", saved["engine"] == "auto", saved)
check("limite de notícias truncado ao máximo", saved["max_news_per_ticker"] == market.MAX_NEWS_PER_TICKER, saved)
market.save_settings({"days": 900, "engine": "inventado"}, "teste")
check("dias truncados ao máximo", market.settings()["days"] == 90, market.settings())
check("motor inválido cai em léxico", market.settings()["engine"] == "lexicon", market.settings())
check("desligar a agenda", market.save_settings({"enabled": False}, "teste")["enabled"] is False, market.settings())

status = scheduler.status()
check("estado da agenda com as chaves esperadas", {"running", "scheduled", "cron", "next_run_at", "last_run_at", "last_result", "days"} <= set(status), list(status))
check("agenda desligada não fica marcada", status["scheduled"] is False, status)
market.save_settings({"enabled": True, "days": 3}, "teste")
check("estado da agenda com as definições", scheduler.status()["days"] == 3, scheduler.status())
check("recarregar sem agendador arrancado", scheduler.reload_jobs()["running"] is False, scheduler.reload_jobs())

run = scheduler.run_now(days=3)
check("corrida manual devolve resultado", run["window"]["days"] == 3 and run["documents"] >= 1, run)
check("corrida manual registada no estado", scheduler.status()["last_run_at"] and scheduler.status()["last_result"]["documents"] >= 1, scheduler.status())
check("agendador para sem erro", scheduler.shutdown() is None)

# --------------------------------------------------------------------------
print("== rotas ==")
route_overview = routes.sentiment_market_overview(days=30, limit=24)
check("rota do panorama traz agenda", route_overview["kpis"]["tickers"] == 4 and "schedule" in route_overview, route_overview.get("kpis"))
check("rota do panorama com parâmetros por omissão", routes.sentiment_market_overview()["window"]["days"] == 30, routes.sentiment_market_overview()["window"])
check("rota da série", routes.sentiment_market_series(days=30)["days"] == 4, routes.sentiment_market_series(days=30))
check("rota da série de um ticker", routes.sentiment_market_series(days=30, ticker="EDP.LS")["ticker"] == "EDP.LS")
check("rota da série com parâmetros por omissão", routes.sentiment_market_series()["ticker"] is None, routes.sentiment_market_series()["ticker"])
check("rota do estado", routes.sentiment_market_state()["state"]["documents"] == 6, routes.sentiment_market_state()["state"])
check("rota da agenda", "cron" in routes.sentiment_market_schedule(), routes.sentiment_market_schedule())
check("rota do detalhe do ticker", routes.sentiment_market_ticker("EDP.LS", days=30)["stats"]["news"] == 3, "")
check("rota dos alertas", routes.sentiment_market_alerts(days=30)["total"] == 3, routes.sentiment_market_alerts(days=30))
check("rota dos alertas com parâmetros por omissão", routes.sentiment_market_alerts()["thresholds"]["min_news"] == 2, routes.sentiment_market_alerts())
check("rota dos alertas com limiar próprio", routes.sentiment_market_alerts(days=30, min_delta=0.5, min_news=4)["total"] == 0, None)
route_brief = routes.sentiment_market_brief(days=7)
check("rota do boletim", route_brief["window"]["days"] == 7 and route_brief["markdown"].startswith("# Boletim"), route_brief.get("window"))
check("rota do boletim com parâmetros por omissão", routes.sentiment_market_brief()["window"]["days"] == 7, None)
try:
    routes.sentiment_market_ticker("   ", days=30)
    raise SystemExit("ticker vazio devia devolver 422")
except HTTPException as exc:
    check("detalhe com ticker vazio devolve 422", exc.status_code == 422, exc)

check("rota de construção", routes.sentiment_market_build({"days": 3}, session=SESSION)["documents"] >= 1, "")
check(
    "construção manual fica registada como última corrida",
    scheduler.status()["last_run_at"] is not None and (scheduler.status()["last_result"] or {}).get("documents") is not None,
    scheduler.status().get("last_result"),
)
check("construção só de um ticker", routes.sentiment_market_build({"days": 3, "tickers": ["SONAE.LS"], "only_missing": True}, session=SESSION)["tickers"] == 1, "")
try:
    routes.sentiment_market_build({"days": 3}, session=None)
    raise SystemExit("construção sem sessão devia devolver 401")
except HTTPException as exc:
    check("construção exige sessão (401)", exc.status_code == 401, exc)

csv_route = routes.sentiment_market_export(format="csv", days=30, limit=24)
body = csv_route.body.decode("utf-8-sig")
check("exportação CSV com BOM e ponto e vírgula", csv_route.body.startswith(b"\xef\xbb\xbf"), csv_route.body[:8])
check("CSV com cabeçalho em português", "Ticker;Tom;Etiqueta;Variação" in body, body.splitlines()[:4])
check("CSV com uma linha por ticker", sum(1 for line in body.strip().splitlines() if line.startswith(("EDP.LS", "GALP.LS", "CTT.LS"))) >= 3, body)
check("CSV com janela anotada", f"# Janela;{day(29)} a {day(0)}" in body, body.splitlines()[:3])
check("CSV com decimais com ponto", ";1.3333;" in body, body)
md_route = routes.sentiment_market_export(format="md", days=30)
check("exportação Markdown", md_route.body.decode("utf-8").startswith("# Sentimento de mercado"), md_route.body[:40])
check("exportação com parâmetros por omissão", routes.sentiment_market_export().body.startswith(b"\xef\xbb\xbf"), "")

saved_schedule = routes.sentiment_market_save_schedule({"cron": "0 7 * * *", "days": 5}, session=SESSION)
check("rota grava a agenda", saved_schedule["settings"]["cron"] == "0 7 * * *" and saved_schedule["settings"]["days"] == 5, saved_schedule)
try:
    routes.sentiment_market_save_schedule({"cron": "0 7 * * *"}, session=None)
    raise SystemExit("agenda sem sessão devia devolver 401")
except HTTPException as exc:
    check("agenda exige sessão (401)", exc.status_code == 401, exc)
try:
    routes.sentiment_market_reload(session=None)
    raise SystemExit("recarregar sem sessão devia devolver 401")
except HTTPException as exc:
    check("recarregar exige sessão (401)", exc.status_code == 401, exc)
try:
    routes.sentiment_market_brief_office({}, session=None)
    raise SystemExit("boletim sem sessão devia devolver 401")
except HTTPException as exc:
    check("boletim no Office exige sessão (401)", exc.status_code == 401, exc)

# --------------------------------------------------------------------------
print("== alerta de cobertura: sem tom vs diluição ==")
# A cobertura zero e a cobertura parcial dizem coisas diferentes: a primeira é
# ausência de tom, a segunda é diluição — a redação tem de o refletir.
zero_coverage = [
    item for item in market.alerts(days=30, min_news=1)["items"] if item["kind"] == "cobertura"
]
check("cobertura zero lê-se como «sem tom»", any("sem tom" in item["detail"] for item in zero_coverage), [item["detail"] for item in zero_coverage])
market._index_daily(
    [
        {
            **market.aggregate_day(
                "MIX.LS", day(20), market.analyze_news_items([news_item("MIX.LS", "MIX com lucro forte", POS, f"{day(20)}T09:00:00Z")])
            ),
            "news_count": 5,
            "coverage": 0.2,
        }
    ]
)
diluted = [
    item
    for item in market.alerts(days=30, min_news=1)["items"]
    if item["kind"] == "cobertura" and item["ticker"] == "MIX.LS"
]
check("cobertura parcial lê-se como diluição", len(diluted) == 1 and "diluição" in diluted[0]["detail"], diluted)

# --------------------------------------------------------------------------
print("== preço, correlação e divergência ==")
# Fixture: 10 dias com tom variado e variação de fecho igual a metade do tom
# (correlação perfeita, r = 1) — e um segundo ticker com tom positivo e preço a
# descer (divergência). O primeiro dia serve de fecho de referência, sem variação.
CORR_SENTIMENT = [0.6, 0.1, -0.2, 0.4, 0.8, -0.5, 0.3, 0.7, -0.1, 0.5]
CORR_DAYS = [day(offset) for offset in range(19, 9, -1)]
_corr_closes = [100.0]
for _value in CORR_SENTIMENT[1:]:
    _corr_closes.append(round(_corr_closes[-1] * (1 + (_value * 0.5) / 100), 4))
PRICES["CORR.LS"] = [
    {"date": CORR_DAYS[index], "close": close, "volume": 1000 + index} for index, close in enumerate(_corr_closes)
]
PRICES["DIVG.LS"] = [{"date": CORR_DAYS[index], "close": round(100.0 * (0.99 ** index), 4)} for index in range(10)]


def _daily_doc(ticker, day_value, sentiment_value, news=3):
    return {
        "ticker": ticker,
        "date": day_value,
        "news_count": news,
        "sentiment_signal": sentiment_value,
        "sentiment_mean": sentiment_value,
        "coverage": 1.0,
        "label": market.tone_of(sentiment_value),
        "positive_count": news if sentiment_value > 0 else 0,
        "negative_count": news if sentiment_value < 0 else 0,
        "topics": [],
        "sources": [],
        "articles": news,
    }


market._index_daily(
    [_daily_doc("CORR.LS", CORR_DAYS[index], value) for index, value in enumerate(CORR_SENTIMENT)]
    + [_daily_doc("DIVG.LS", CORR_DAYS[index], 0.7) for index in range(10)]
)

rows_price = market._price_rows(
    [
        {"date": f"{CORR_DAYS[0]}T00:00:00Z", "close": 10.0},
        {"date": CORR_DAYS[0], "close": 11.0},
        {"date": CORR_DAYS[1], "close": float("nan")},
        {"date": CORR_DAYS[2], "close": "12.5"},
        {"date": None, "close": 9.0},
        "não é dicionário",
    ]
)
check("pontos de preço normalizados e por ordem", [row["date"] for row in rows_price] == [CORR_DAYS[0], CORR_DAYS[2]], rows_price)
check("fecho repetido fica com o último valor", rows_price[0]["close"] == 11.0, rows_price[0])
check("fecho em texto é aceite", rows_price[1]["close"] == 12.5, rows_price[1])
check("Pearson perfeita positiva", market._pearson([(1.0, 2.0), (2.0, 4.0), (3.0, 6.0)]) == 1.0, None)
check("Pearson perfeita negativa", market._pearson([(1.0, -2.0), (2.0, -4.0), (3.0, -6.0)]) == -1.0, None)
check("Pearson sem variação devolve None", market._pearson([(1.0, 5.0), (1.0, 6.0), (1.0, 7.0)]) is None, None)
check("Pearson com poucos pares devolve None", market._pearson([(1.0, 2.0)]) is None, None)
check("posições com empates pela média", market._ranks([10.0, 20.0, 20.0, 30.0]) == [1.0, 2.5, 2.5, 4.0], market._ranks([10.0, 20.0, 20.0, 30.0]))
check(
    "força da correlação por escalões",
    (market._strength(0.8), market._strength(0.5), market._strength(0.3), market._strength(0.1), market._strength(None))
    == ("forte", "moderada", "fraca", "sem relação aparente", "indeterminada"),
    None,
)
check("significância com t acima de 2", market._significance(0.9, 12)["significant"] is True, market._significance(0.9, 12))
check("correlação perfeita não testa significância", market._significance(1.0, 12)["t"] is None, None)

points = market.price_points("corr.ls", days=30)
check("preços vêm da plataforma", points["source"] == "plataforma" and points["total"] == 10, points)
check("preços normalizam o ticker", points["ticker"] == "CORR.LS", points["ticker"])
check("janela de preços devolvida", points["window"]["days"] == 30 and points["window"]["start"] == day(29), points["window"])
empty_points = market.price_points("ZZZ.LS", days=30)
check("sem cotações há mensagem", empty_points["points"] == [] and "Sem cotações" in empty_points["message"], empty_points)
LIVE_PRICES["LIVE.LS"] = [{"date": day(1), "close": 4.0}, {"date": day(0), "close": 5.0}]
live_points = market.price_points("LIVE.LS", days=30, live=True)
check("cotações em falta vão ao Yahoo quando pedido", live_points["source"] == "yahoo" and live_points["total"] == 2, live_points)
check("cotações obtidas ficam guardadas", live_points["stored"]["indexed"] == 2 and len(STORED_PRICES) == 1, live_points["stored"])
check(
    "cotações guardadas com ticker e pontos",
    STORED_PRICES[0]["ticker"] == "LIVE.LS" and len(STORED_PRICES[0]["points"]) == 2,
    STORED_PRICES[0],
)
check(
    "pontos guardados no formato do índice",
    {"date", "open", "high", "low", "close", "volume"} <= set(STORED_PRICES[0]["points"][0]),
    STORED_PRICES[0]["points"][0],
)
no_persist = market.price_points("LIVE.LS", days=30, live=True, persist=False)
check("sem `persist` não se grava", no_persist["total"] == 2 and len(STORED_PRICES) == 1, no_persist["stored"])
FLAGS["prices_index_error"] = True
failed_store = market.price_points("LIVE.LS", days=30, live=True)
check(
    "falha ao guardar não perde as cotações",
    failed_store["total"] == 2 and failed_store["stored"]["indexed"] == 0 and bool(failed_store["stored"].get("error")),
    failed_store["stored"],
)
FLAGS["prices_index_error"] = False
check("sem `live` não se vai ao Yahoo", market.price_points("LIVE.LS", days=30)["source"] is None, None)
FLAGS["prices_error"] = True
check("erro do índice de preços é devolvido", market.price_points("CORR.LS", days=30).get("error"), None)
FLAGS["prices_error"] = False

corr = market.correlation("corr.ls", days=30)
check("correlação alinha tom e variação", corr["pairs"] == 9 and corr["price_days"] == 10, corr)
check("correlação no mesmo dia é perfeita", corr["same_day"]["r"] == 1.0 and corr["same_day"]["n"] == 9, corr["same_day"])
check("correlação de Spearman acompanha", corr["same_day"]["spearman"] == 1.0, corr["same_day"])
check(
    "direção e força da correlação",
    corr["same_day"]["direction"] == "positiva" and corr["same_day"]["strength"] == "forte",
    corr["same_day"],
)
check("correlação com um dia de avanço", corr["lag1"]["n"] == 8 and corr["lag1"]["r"] is not None, corr["lag1"])
check(
    "janela com tom e variação coerentes",
    corr["window_move"]["change_pct"] > 0
    and corr["window_move"]["reading"] in ("alinhado", "tom_acima_do_preco", "preco_acima_do_tom"),
    corr["window_move"],
)
check("amostra suficiente marcada", corr["enough_data"] is True and corr["min_pairs"] == 8, corr)
check("aviso de causalidade sempre presente", "causalidade" in corr["caveat"], corr["caveat"])
check(
    "série alinhada para o gráfico",
    len(corr["series"]) == 9 and {"day", "sentiment", "change_pct"} <= set(corr["series"][0]),
    corr["series"][0],
)
check("fonte do preço registada", corr["price_source"] == "plataforma", corr["price_source"])
short = market.correlation("EDP.LS", days=30)
check(
    "amostra curta é dita como tal",
    short["pairs"] < 8 and short["enough_data"] is False and short["window_move"]["reading"] == "amostra_insuficiente",
    short["window_move"],
)
check("sem cotações a correlação explica-se", bool(short["price_message"]), short["price_message"])
try:
    market.correlation("   ", days=30)
    raise SystemExit("ticker vazio devia falhar")
except KeyError:
    check("ticker vazio na correlação levanta KeyError", True)

divergence = market.divergences(days=30)
check("divergência inclui o ticker com preço a descer", any(item["ticker"] == "DIVG.LS" for item in divergence["items"]), divergence["items"])
top_gap = divergence["items"][0]
check(
    "o maior desalinhamento fica à frente",
    top_gap["ticker"] == "DIVG.LS" and top_gap["reading"] == "tom_acima_do_preco",
    top_gap,
)
check("divergência com a variação da janela", top_gap["change_pct"] < 0 and top_gap["normalized_change"] == -1.0, top_gap)
check(
    "divergência conta tickers com e sem cotações",
    divergence["with_prices"] == 2 and divergence["tickers_with_series"] >= 4,
    divergence,
)
check("divergência com referência declarada", divergence["reference_move"] == 5.0, divergence["reference_move"])
check("divergência com aviso de causalidade", "causalidade" in divergence["caveat"], divergence["caveat"])
without_prices = market.divergences(days=7)
check(
    "janela sem cotações explica-se",
    without_prices["with_prices"] == 0 and "Yahoo" in (without_prices.get("message") or ""),
    without_prices.get("message"),
)
# Com cotações em falta, a divergência vai ao Yahoo e **guarda** o que recebeu.
LIVE_PRICES["EDP.LS"] = [{"date": day(3), "close": 3.8}, {"date": day(1), "close": 4.0}, {"date": day(0), "close": 4.1}]
STORED_PRICES.clear()
live_divergence = market.divergences(days=7, live=True)
check(
    "divergência ao vivo usa e guarda as cotações",
    live_divergence["with_prices"] == 1 and live_divergence["stored"] == 3,
    (live_divergence["with_prices"], live_divergence["stored"]),
)
live_row = [item for item in live_divergence["items"] if item["ticker"] == "EDP.LS"][0]
check(
    "divergência ao vivo marca a fonte e a variação",
    live_row["price_source"] == "yahoo" and live_row["price_days"] == 3 and live_row["change_pct"] > 0,
    live_row,
)
FLAGS["daily_error"] = True
check("erro de leitura devolvido na divergência", market.divergences(days=30).get("error"), None)
FLAGS["daily_error"] = False

check("rota do preço", routes.sentiment_market_price("CORR.LS", days=30)["same_day"]["r"] == 1.0, None)
check("rota do preço com parâmetros por omissão", routes.sentiment_market_price("CORR.LS")["ticker"] == "CORR.LS", None)
check("rota da divergência", routes.sentiment_market_divergence(days=30)["items"][0]["ticker"] == "DIVG.LS", None)
check(
    "rota da divergência com parâmetros por omissão",
    routes.sentiment_market_divergence()["window"]["days"] == 30,
    None,
)
try:
    routes.sentiment_market_price("   ")
    raise SystemExit("ticker vazio devia devolver 422")
except HTTPException as exc:
    check("ticker vazio no preço devolve 422", exc.status_code == 422, exc)

# --------------------------------------------------------------------------
print("== tickers seguidos (análise dinâmica) ==")
check("lista começa vazia", market.watchlist() == [], market.watchlist())
check("adicionar normaliza o símbolo", market.add_ticker(" edp.ls ", "teste") == ["EDP.LS"], market.watchlist())
check("adicionar outra vez não duplica", market.add_ticker("EDP.LS", "teste") == ["EDP.LS"], market.watchlist())
check("lista gravada no ficheiro", (_TMP_DIR / "tickers.json").exists(), sorted(item.name for item in _TMP_DIR.iterdir()))
check("segundo ticker entra no fim", market.add_ticker("nvda", "teste") == ["EDP.LS", "NVDA"], market.watchlist())
check(
    "validação do formato do símbolo",
    market.normalise_ticker("brk-b") == "BRK-B" and market.normalise_ticker("^gspc") == "^GSPC",
    market.normalise_ticker("brk-b"),
)
for bad in ("", "   ", "AA PL", "muito-longeeeeeeeeeeeeee"):
    try:
        market.normalise_ticker(bad)
        raise SystemExit(f"{bad!r} devia ser recusado")
    except KeyError:
        pass
check("símbolos inválidos recusados", True)
check("tickers seguidos vêm primeiro", market.known_tickers()[:2] == ["EDP.LS", "NVDA"], market.known_tickers())
check("seguido sem notícias continua a ser considerado", "NVDA" in market.known_tickers(), market.known_tickers())
market.remove_ticker("NVDA", "teste")
check("retirar da lista", market.watchlist() == ["EDP.LS"], market.watchlist())

# Seguir um ticker traz notícias, cotações e a série — tudo reportado.
INGESTED.clear()
followed = market.follow_ticker("SONAE.LS", actor="teste", days=30)
check("seguir acrescenta à lista", followed["ticker"] == "SONAE.LS" and "SONAE.LS" in followed["watchlist"], followed["watchlist"])
check("notícias recolhidas a pedido", INGESTED[-1] == {"ticker": "SONAE.LS", "backend": "heuristic", "auto_analyze": True}, INGESTED[-1])
check("resultado das notícias reportado", followed["news"]["indexed"] == 1 and followed["news"]["analyzed"] == 2, followed["news"])
check("série construída já", followed["series"]["days"] == 1 and followed["series"]["news"] == 1, followed["series"])
check("sem cotações para este ticker fica dito", followed["prices"]["points"] == 0, followed["prices"])
check("sem erros neste caso", followed["errors"] == [], followed["errors"])
check("sem sugestões quando há notícias", followed["suggestions"] == [], followed["suggestions"])

# Símbolo que não devolve nada: sugestões do Yahoo em vez de silêncio.
market._suggest_tickers = lambda query, limit=5: [{"ticker": "NVDA", "name": "NVIDIA", "exchange": "NMS"}]  # type: ignore[assignment]
nothing = market.follow_ticker("XXYY", actor="teste", days=30)
check(
    "símbolo sem dados devolve sugestões",
    nothing["suggestions"][0]["ticker"] == "NVDA" and nothing["errors"] == [],
    nothing,
)
market._suggest_tickers = lambda query, limit=5: []  # type: ignore[assignment]
nothing_at_all = market.follow_ticker("ZZQQ", actor="teste", days=30)
check(
    "sem sugestões explica-se o que faltou",
    any("confirme o código" in error for error in nothing_at_all["errors"]),
    nothing_at_all["errors"],
)
FLAGS["ingest_error"] = True
failed_ingest = market.follow_ticker("SONAE.LS", actor="teste", days=30, ingest_prices=False)
FLAGS["ingest_error"] = False
check(
    "falha na recolha de notícias é reportada sem rebentar",
    any("Yahoo indisponível" in error for error in failed_ingest["errors"]) and failed_ingest["series"]["days"] == 1,
    failed_ingest["errors"],
)

status = market.tickers_status(days=30)
check("estado por ticker inclui os seguidos", status["watchlist"] == market.watchlist(), status["watchlist"])
check("estado lista os seguidos primeiro", status["items"][0]["ticker"] in status["watchlist"], status["items"][0])
sonae_status = [item for item in status["items"] if item["ticker"] == "SONAE.LS"][0]
check(
    "estado com série, notícias e histórias",
    sonae_status["documents"] == 1 and sonae_status["news"] == 1 and sonae_status["stories"] == 1,
    sonae_status,
)
check("estado marca quem é seguido", sonae_status["followed"] is True, sonae_status)
edp_status = [item for item in status["items"] if item["ticker"] == "EDP.LS"][0]
check("estado conta as cotações guardadas", edp_status["price_points"] == 0, edp_status)

unfollowed = market.unfollow_ticker("SONAE.LS", actor="teste")
check("deixar de seguir retira da lista", unfollowed["removed"] is True and "SONAE.LS" not in unfollowed["watchlist"], unfollowed)
check("a série guardada mantém-se", f"SONAE.LS|{day(3)}" in DAILY, sorted(DAILY))
try:
    market.unfollow_ticker("nao valido!")
    raise SystemExit("símbolo inválido devia falhar")
except KeyError:
    check("deixar de seguir valida o símbolo", True)
check("rota dos tickers", routes.sentiment_market_tickers(days=30)["watchlist"] == market.watchlist(), None)
route_follow = routes.sentiment_market_follow({"ticker": "SONAE.LS", "ingest_prices": False}, session=SESSION)
check("rota de seguir ticker", route_follow["ok"] is True and route_follow["ticker"] == "SONAE.LS", route_follow)
try:
    routes.sentiment_market_follow({"ticker": "NAO VALE!"}, session=SESSION)
    raise SystemExit("símbolo inválido devia devolver 422")
except HTTPException as exc:
    check("rota recusa símbolo inválido (422)", exc.status_code == 422, exc)
try:
    routes.sentiment_market_follow({"ticker": "EDP.LS"}, session=None)
    raise SystemExit("seguir sem sessão devia devolver 401")
except HTTPException as exc:
    check("seguir exige sessão (401)", exc.status_code == 401, exc)
check("rota de deixar de seguir", routes.sentiment_market_unfollow("SONAE.LS", session=SESSION)["removed"] is True, None)

# --------------------------------------------------------------------------
# Corpus de notícias por ticker (é o que liga o motor de sentimento à série).
# --------------------------------------------------------------------------
print("== corpus de notícias por ticker ==")
from api import sentiment_service as sentiment  # noqa: E402
from api import elasticsearch_client as es_client  # noqa: E402


class _FakeNewsClient:
    def __init__(self) -> None:
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "hits": {
                "hits": [
                    {
                        "_id": "news-1",
                        "_source": {
                            "ticker": "EDP.LS",
                            "title": "EDP com lucro recorde",
                            "summary": "A produtora registou forte crescimento no trimestre.",
                            "published": f"{day(0)}T09:00:00Z",
                            "url": "https://exemplo.pt/edp",
                            "publisher": "Jornal de Teste",
                            "topics": ["energia"],
                        },
                    }
                ]
            }
        }


_news_client = _FakeNewsClient()
_get_es_backup = es_client.get_es_client
_ensure_backup = es_client.ensure_indices
es_client.get_es_client = lambda *args, **kwargs: _news_client  # type: ignore[assignment]
es_client.ensure_indices = lambda *args, **kwargs: None  # type: ignore[assignment]
corpus = sentiment.corpus_from_news(ticker="edp.ls", start_date=day(2), end_date=day(0), limit=10)
check("corpus de notícias traz o ticker pedido", len(corpus) == 1, corpus)
check("corpus de notícias usa o título", corpus[0]["title"] == "EDP com lucro recorde", corpus[0])
check("corpus de notícias junta título e resumo no texto", "crescimento" in corpus[0]["text"], corpus[0]["text"])
check("corpus de notícias acrescenta o ticker às etiquetas", corpus[0]["tags"] == ["energia", "EDP.LS"], corpus[0]["tags"])
check("corpus de notícias identifica a fonte", corpus[0]["source"] == "Jornal de Teste · EDP.LS", corpus[0]["source"])
check("corpus de notícias guarda a data e o endereço", corpus[0]["date"] == f"{day(0)}T09:00:00Z" and corpus[0]["url"].endswith("/edp"), corpus[0])
query = (_news_client.calls[-1]["body"].get("query") or {}).get("bool") or {}
check(
    "corpus de notícias filtra por ticker e janela",
    {"term": {"ticker": "EDP.LS"}} in (query.get("must") or []) and any("range" in clause for clause in query.get("must") or []),
    query,
)
empty_client = _FakeNewsClient()
empty_client.search = lambda **kwargs: {"hits": {"hits": []}}  # type: ignore[assignment]
es_client.get_es_client = lambda *args, **kwargs: empty_client  # type: ignore[assignment]
check("corpus de notícias sem resultados devolve lista vazia", sentiment.corpus_from_news(ticker="ZZZ.LS") == [], None)
es_client.get_es_client = lambda *args, **kwargs: None  # type: ignore[assignment]
check("corpus de notícias sem Elasticsearch não falha", sentiment.corpus_from_news(ticker="EDP.LS") == [], None)
es_client.get_es_client = _get_es_backup  # type: ignore[assignment]
es_client.ensure_indices = _ensure_backup  # type: ignore[assignment]

print(f"\n{ok} verificações passaram.")
