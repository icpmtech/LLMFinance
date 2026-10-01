"""Rotas do sentimento de mercado (`/sentiment/market/*`).

**Leitura** (público, como o resto da análise de sentimento):

- `GET  /sentiment/market/overview?days=30` — KPIs, série, heatmap ticker × dia e rankings
- `GET  /sentiment/market/series?days=90[&ticker=]` — série diária (mercado ou um ticker)
- `GET  /sentiment/market/ticker/{ticker}?days=90` — série e destaques de um ticker
- `GET  /sentiment/market/state` — volume guardado, cobertura e o que falta construir
- `GET  /sentiment/market/alerts?days=30` — movimentos, viragens, dias extremos e cobertura baixa
- `GET  /sentiment/market/divergence?days=30` — tom vs variação do preço (com `live=1` vai ao Yahoo)
- `GET  /sentiment/market/live?tickers=EDP.LS,AAPL` — **panorama em direto**: cotações do Yahoo,
  notícias com tom, oportunidades e a contraprova de cada cotação (nunca usa a série guardada)
- `GET  /sentiment/market/price/{ticker}?days=90` — tom × preço de um ticker (correlação e divergência)
- `GET  /sentiment/market/tickers?days=30` — tickers seguidos e o estado de cada um
- `GET  /sentiment/market/watchlist` — favoritos guardados (leitura leve, sem índices)
- `GET  /sentiment/market/brief?days=7` — boletim do mercado (Markdown pronto a ler)
- `GET  /sentiment/market/schedule` — estado do agendador
- `GET  /sentiment/market/export?format=csv|md` — descarregar o panorama

**Escrita** (requer sessão — a série e o Office são espaços de trabalho):

- `POST /sentiment/market/build` — (re)construir a série (`{"days": 7, "tickers": ["EDP.LS"]}`)
- `POST /sentiment/market/tickers` — seguir um ticker (traz notícias e cotações e constrói a série)
- `POST /sentiment/market/watchlist` — guardar um ticker nos favoritos (leve: só confirma no Yahoo)
- `DELETE /sentiment/market/watchlist/{ticker}` — retirar dos favoritos
- `DELETE /sentiment/market/tickers/{ticker}` — deixar de seguir (a série guardada mantém-se)
- `POST /sentiment/market/report/office` — guardar o relatório no Office
- `POST /sentiment/market/brief/office` — guardar o boletim no Office
- `PUT  /sentiment/market/schedule` — gravar a agenda e recarregar o job
- `DELETE /sentiment/market/series` — apagar a série (de um ticker ou toda)

Nota: `build` e `report` ficam **antes** das rotas com parâmetros de caminho, para
que «build» nunca seja interpretado como um ticker.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response

from api import sentiment_market as market
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentiment/market", tags=["sentiment"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


def _writer(session: Optional[CurrentSession]) -> CurrentSession:
    if not session:
        raise HTTPException(status_code=401, detail="Entrar na plataforma para alterar a série de sentimento.")
    return session

CSV_COLUMNS: List[tuple] = [
    ("ticker", "Ticker"),
    ("sentiment", "Tom"),
    ("label", "Etiqueta"),
    ("delta", "Variação"),
    ("previous", "Tom anterior"),
    ("news", "Notícias"),
    ("days", "Dias com série"),
    ("coverage", "Cobertura"),
    ("positive_ratio", "Positivas"),
    ("negative_ratio", "Negativas"),
    ("last_date", "Última data"),
]


def _num(value: Any, fallback: int) -> int:
    """Inteiro tolerante: chamadas diretas às rotas passam objetos `Query`."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _float(value: Any, fallback: float) -> float:
    """Decimal tolerante (mesma razão do `_num`)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _flag(value: Any, fallback: bool = False) -> bool:
    """Booleano tolerante (aceita 1/0/true/false e objetos `Query`)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "sim", "yes", "on")
    if isinstance(value, (int, float)):
        return bool(value)
    return fallback


def _opt_str(value: Any) -> Optional[str]:
    """Texto de um parâmetro de consulta (qualquer outra coisa = «sem valor»)."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _csv(rows: List[Dict[str, Any]], *, note: str = "") -> Dict[str, Any]:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(["# Sentimento de mercado — IQ OS"])
    writer.writerow(["# Janela", note or "—"])
    writer.writerow(["# Gerado em", market.now()])
    writer.writerow([label for _key, label in CSV_COLUMNS])
    for row in rows:
        values = []
        for key, _label in CSV_COLUMNS:
            value = row.get(key)
            if isinstance(value, float):
                values.append(f"{value:.4f}")
            elif value is None:
                values.append("")
            else:
                values.append(str(value))
        writer.writerow(values)
    return {
        "content": ("\ufeff" + buffer.getvalue()).encode("utf-8"),
        "media_type": "text/csv; charset=utf-8",
        "filename": f"sentimento-mercado_{market.now()[:10]}.csv",
    }


# ==========================================================================
# Construção (literal: tem de vir antes de `/ticker/{ticker}`)
# ==========================================================================
@router.post("/build")
def sentiment_market_build(payload: Dict[str, Any] = Body(default={}), session: Session = None) -> Dict[str, Any]:
    """(Re)constrói a série diária a partir das notícias indexadas.

    `days` limita a janela (1–90), `tickers` restringe a lista, `only_missing`
    salta os dias que já têm documento e `prune` (por omissão ligado) apaga os
    dias da janela que deixaram de ter notícias.
    """
    _writer(session)
    result = market.build(
        days=payload.get("days"),
        tickers=payload.get("tickers"),
        only_missing=bool(payload.get("only_missing")),
        engine=payload.get("engine"),
        max_news=payload.get("max_news"),
        prune=payload.get("prune", True) is not False,
    )
    # Uma construção pedida na interface também é «última corrida» do agendador.
    try:
        from api import sentiment_market_scheduler as scheduler

        scheduler.record_run(result)
    except Exception:  # pragma: no cover - agendador indisponível
        pass
    return {"ok": not result.get("errors"), **result}


@router.post("/report/office")
def sentiment_market_report(payload: Dict[str, Any] = Body(default={}), session: Session = None) -> Dict[str, Any]:
    """Gera o relatório do panorama e guarda-o no Office como relatório."""
    session = _writer(session)
    days = payload.get("days") or 30
    overview = market.overview(days=_num(days, 30), limit=_num(payload.get("limit"), market.MAX_HEATMAP_TICKERS))
    if overview.get("error"):
        raise HTTPException(status_code=502, detail=overview["error"])
    markdown = market.report_markdown(overview, title=str(payload.get("title") or "Sentimento de mercado"))
    try:
        from api import office_store

        document = office_store.save_document(
            {
                "title": str(payload.get("title") or f"Sentimento de mercado — {overview['window']['start']} a {overview['window']['end']}"),
                "kind": "relatorio",
                "markdown": markdown,
                "tags": ["sentimento", "mercado"],
                "source": {"kind": "sentiment_market", "days": days, "window": overview.get("window")},
            },
            author=session.user.email,
        )
    except Exception as exc:  # pragma: no cover - Office/store
        logger.warning("Relatório de sentimento para o Office falhou: %s", exc)
        raise HTTPException(status_code=502, detail=f"Office: {exc}")
    return {"ok": True, "document": document, "document_id": document.get("id"), "markdown": markdown}


@router.get("/tickers")
def sentiment_market_tickers(days: int = Query(30, ge=3, le=180)) -> Dict[str, Any]:
    """Tickers seguidos e o estado de cada um nesta janela."""
    return market.tickers_status(days=_num(days, 30))


@router.post("/tickers")
def sentiment_market_follow(payload: Dict[str, Any] = Body(default={}), session: Session = None) -> Dict[str, Any]:
    """Segue um ticker: acrescenta à lista, traz notícias e cotações e constrói a série."""
    session = _writer(session)
    try:
        report = market.follow_ticker(
            str(payload.get("ticker") or ""),
            actor=session.user.email,
            ingest_news=payload.get("ingest_news", True) is not False,
            ingest_prices=payload.get("ingest_prices", True) is not False,
            days=payload.get("days"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": not report.get("errors"), **report}


@router.delete("/tickers/{ticker}")
def sentiment_market_unfollow(ticker: str, session: Session = None) -> Dict[str, Any]:
    """Deixa de seguir um ticker (a série guardada mantém-se)."""
    session = _writer(session)
    try:
        return market.unfollow_ticker(str(ticker), actor=session.user.email)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/watchlist")
def sentiment_market_watchlist() -> Dict[str, Any]:
    """Favoritos guardados, com o que ainda falta sugerir (leitura leve)."""
    return market.watchlist_state()


@router.post("/watchlist")
def sentiment_market_watchlist_add(
    payload: Dict[str, Any] = Body(default={}),
    session: Session = None,
) -> Dict[str, Any]:
    """Guarda um ticker nos favoritos, depois de o confirmar no Yahoo Finance."""
    session = _writer(session)
    try:
        return market.add_favourite(str(payload.get("ticker") or ""), actor=session.user.email)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/watchlist/{ticker}")
def sentiment_market_watchlist_remove(ticker: str, session: Session = None) -> Dict[str, Any]:
    """Retira um ticker dos favoritos (a série já construída mantém-se)."""
    session = _writer(session)
    try:
        return market.unfollow_ticker(str(ticker), actor=session.user.email)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/schedule/reload")
def sentiment_market_reload(session: Session = None) -> Dict[str, Any]:
    """Recarrega o agendador com as definições guardadas."""
    _writer(session)
    from api import sentiment_market_scheduler as scheduler

    return scheduler.reload_jobs()


# ==========================================================================
# Leitura
# ==========================================================================
@router.get("/overview")
def sentiment_market_overview(
    days: int = Query(30, ge=3, le=180, description="Janela em dias (a comparação usa a janela anterior)."),
    limit: int = Query(market.MAX_HEATMAP_TICKERS, ge=1, le=40, description="Tickers no heatmap."),
) -> Dict[str, Any]:
    """KPIs, série, heatmap (ticker × dia) e rankings de variação."""
    from api import sentiment_market_scheduler as scheduler

    payload = market.overview(days=_num(days, 30), limit=_num(limit, market.MAX_HEATMAP_TICKERS))
    payload["schedule"] = scheduler.status()
    return payload


@router.get("/series")
def sentiment_market_series(
    days: int = Query(90, ge=3, le=365),
    ticker: Optional[str] = Query(None, description="Série de um ticker (por omissão, o mercado todo)."),
) -> Dict[str, Any]:
    """Série diária do mercado (ou de um ticker)."""
    return market.series(ticker=_opt_str(ticker), days=_num(days, 90))


@router.get("/state")
def sentiment_market_state() -> Dict[str, Any]:
    """Volume guardado, cobertura e o que falta construir."""
    from api import sentiment_market_scheduler as scheduler

    return {"state": market.state(), "coverage": market.coverage(), "schedule": scheduler.status()}


@router.get("/alerts")
def sentiment_market_alerts(
    days: int = Query(30, ge=3, le=180),
    min_delta: float = Query(0.25, ge=0.05, le=1.0, description="Variação mínima do tom (janela vs anterior)."),
    min_news: int = Query(2, ge=1, le=50, description="Notícias mínimas para o movimento contar."),
    limit: int = Query(12, ge=1, le=60),
) -> Dict[str, Any]:
    """Alertas de movimentos do mercado (critérios incluídos na resposta)."""
    return market.alerts(
        days=_num(days, 30),
        min_delta=_float(min_delta, 0.25),
        min_news=_num(min_news, 2),
        limit=_num(limit, 12),
    )


@router.get("/brief")
def sentiment_market_brief(days: int = Query(7, ge=1, le=30)) -> Dict[str, Any]:
    """Boletim do mercado: resumo, movimentos, alertas e temas (com o Markdown)."""
    payload = market.brief(days=_num(days, 7))
    if payload.get("error"):
        raise HTTPException(status_code=502, detail=payload["error"])
    return payload


@router.post("/brief/office")
def sentiment_market_brief_office(payload: Dict[str, Any] = Body(default={}), session: Session = None) -> Dict[str, Any]:
    """Gera o boletim do mercado e guarda-o no Office como relatório."""
    session = _writer(session)
    days = _num(payload.get("days"), 7)
    brief = market.brief(days=days)
    if brief.get("error"):
        raise HTTPException(status_code=502, detail=brief["error"])
    window = brief.get("window") or {}
    title = str(payload.get("title") or f"Boletim de mercado — {window.get('start')} a {window.get('end')}")
    try:
        from api import office_store

        document = office_store.save_document(
            {
                "title": title,
                "kind": "relatorio",
                "markdown": brief.get("markdown") or "",
                "tags": ["sentimento", "mercado", "boletim"],
                "source": {"kind": "sentiment_market_brief", "days": days, "window": window},
            },
            author=session.user.email,
        )
    except Exception as exc:  # pragma: no cover - Office/store
        logger.warning("Boletim de sentimento para o Office falhou: %s", exc)
        raise HTTPException(status_code=502, detail=f"Office: {exc}")
    return {"ok": True, "document": document, "document_id": document.get("id"), "markdown": brief.get("markdown"), "alerts": brief.get("alerts")}


@router.get("/schedule")
def sentiment_market_schedule() -> Dict[str, Any]:
    """Estado do agendador da série."""
    from api import sentiment_market_scheduler as scheduler

    return scheduler.status()


@router.put("/schedule")
def sentiment_market_save_schedule(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Grava a agenda (`cron`, `timezone`, `enabled`, `days`) e recarrega o job."""
    session = _writer(session)
    from api import sentiment_market_scheduler as scheduler

    saved = market.save_settings(payload, session.user.email)
    return {"saved": True, "settings": saved, "schedule": scheduler.reload_jobs()}


@router.get("/export")
def sentiment_market_export(
    format: str = Query("csv", pattern="^(csv|md)$"),
    days: int = Query(30, ge=3, le=180),
    limit: int = Query(market.MAX_HEATMAP_TICKERS, ge=1, le=40),
) -> Response:
    """Exporta o panorama (CSV para Excel, Markdown para ler)."""
    overview = market.overview(days=_num(days, 30), limit=_num(limit, market.MAX_HEATMAP_TICKERS))
    if overview.get("error"):
        raise HTTPException(status_code=502, detail=overview["error"])
    window = overview.get("window") or {}
    note = f"{window.get('start')} a {window.get('end')}"
    if _opt_str(format) == "md":
        return Response(
            content=market.report_markdown(overview),
            media_type="text/markdown; charset=utf-8",
            headers={"content-disposition": 'attachment; filename="sentimento-mercado.md"'},
        )
    payload = _csv(market.export_rows(overview), note=note)
    return Response(
        content=payload["content"],
        media_type=payload["media_type"],
        headers={"content-disposition": f'attachment; filename="{payload["filename"]}"'},
    )


@router.get("/ticker/{ticker}")
def sentiment_market_ticker(ticker: str, days: int = Query(90, ge=3, le=365)) -> Dict[str, Any]:
    """Série diária e destaques de um ticker."""
    try:
        return market.ticker_detail(str(ticker), days=_num(days, 90))
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/price/{ticker}")
def sentiment_market_price(
    ticker: str,
    days: int = Query(90, ge=3, le=365),
    live: bool = Query(False, description="Ir buscar cotações ao Yahoo Finance quando faltam na plataforma."),
) -> Dict[str, Any]:
    """Relação entre o tom das notícias e a variação do preço de um ticker."""
    try:
        return market.correlation(str(ticker), days=_num(days, 90), live=_flag(live))
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/divergence")
def sentiment_market_divergence(
    days: int = Query(30, ge=3, le=180),
    limit: int = Query(12, ge=1, le=30),
    live: bool = Query(False, description="Ir buscar cotações ao Yahoo Finance quando faltam na plataforma."),
) -> Dict[str, Any]:
    """Ranking de divergência entre o tom e a variação do preço."""
    return market.divergences(days=_num(days, 30), limit=_num(limit, 12), live=_flag(live))


@router.get("/live")
def sentiment_market_live(
    tickers: Optional[str] = Query(None, description="Tickers separados por vírgula; sem valor, usa os seguidos."),
    news: int = Query(5, ge=0, le=20, description="Notícias a analisar por ticker."),
    verify: bool = Query(True, description="Confirmar cada cotação contra um segundo caminho do Yahoo."),
    translate: bool = Query(False, description="Traduzir as manchetes EN→PT (leitura mais fina, muito mais lenta)."),
) -> Dict[str, Any]:
    """Panorama **em direto**: cotações do Yahoo, notícias com tom e oportunidades.

    Não usa a série guardada: lê o Yahoo Finance a cada pedido e devolve, para
    cada cotação, o resultado da contraprova — para o painel mostrar de onde veio
    cada número e se bate com a fonte.
    """
    codes = [part.strip() for part in (tickers or "").replace(";", ",").split(",") if part.strip()]
    return market.live_snapshot(
        codes or None,
        news_per_ticker=_num(news, 5),
        verify=_flag(verify, True),
        translate=_flag(translate, False),
    )


@router.delete("/series")
def sentiment_market_delete(
    ticker: Optional[str] = Query(None, description="Apaga só este ticker; sem valor, apaga tudo."),
    session: Session = None,
) -> Dict[str, Any]:
    """Apaga a série guardada (ticker ou toda)."""
    _writer(session)
    from api.elasticsearch_client import delete_sentiment_daily

    return delete_sentiment_daily(_opt_str(ticker))
