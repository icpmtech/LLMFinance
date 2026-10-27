"""Testes da leitura **em direto** do sentimento de mercado (`live_snapshot`).

O que aqui se fixa é a regra do módulo: uma manchete sem vocabulário reconhecido
é «sem tom», não «neutra». A média do painel usa só as manchetes lidas, e as
outras vão contadas à parte (`unread`) — contar zeros como neutralidade fazia um
mercado inteiro parecer «neutro» só porque o léxico não leu nada.

Correr com:

    c:\\LLMFinance\\.venv\\Scripts\\python.exe -m pytest tests/test_sentiment_market_live.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import sentiment_market as market  # noqa: E402


def _article(ticker: str, title: str, label: str, polarity: float, hits: int) -> dict:
    return {
        "ticker": ticker,
        "title": title,
        "title_pt": None,
        "url": "",
        "source": "Teste",
        "published": "2026-01-02T10:00:00Z",
        "day": "2026-01-02",
        "polarity": polarity,
        "label": label,
        "hits": hits,
        "material": "lexico-pt" if hits else "sem-texto",
    }


def _snapshot(monkeypatch, articles: list[dict]) -> dict:
    quotes = [
        {"ticker": "AAA", "price": 10.0, "previous_close": 9.9, "change_pct": 1.0},
        {"ticker": "BBB", "price": 20.0, "previous_close": 20.4, "change_pct": -2.0},
    ]
    monkeypatch.setattr(market, "_live_ticker", lambda code, limit, verify: dict(quotes[0 if code == "AAA" else 1]))
    monkeypatch.setattr(market, "_live_articles", lambda rows, translate=False: [dict(item) for item in articles])
    return market.live_snapshot(["AAA", "BBB"], news_per_ticker=4, verify=False)


def test_unread_headlines_are_not_neutral(monkeypatch) -> None:
    articles = [
        _article("AAA", "Lucros recorde impulsionam as ações", "positivo", 0.5, 2),
        _article("AAA", "Empresa anuncia nova fábrica em Aveiro", "neutro", 0.0, 0),
        _article("BBB", "Hynix Jumps 6% as Asia Buys Back Into AI", "positivo", 0.5, 1),
        _article("BBB", "Resultados caem e a procura enfraquece", "negativo", -0.5, 2),
    ]
    summary = _snapshot(monkeypatch, articles)["summary"]

    assert summary["news"] == 4
    assert summary["positive"] == 2
    assert summary["negative"] == 1
    # O rótulo bruto mantém-se (a manchete sem vocabulário é «neutra» no léxico)…
    assert summary["neutral"] == 1
    # …mas a leitura separa-a: nenhuma neutra «a sério» e uma sem tom.
    assert summary["covered"] == 3
    assert summary["unread"] == 1
    assert summary["neutral_read"] == 0
    assert summary["coverage"] == pytest.approx(0.75)


def test_tone_is_the_mean_of_read_headlines(monkeypatch) -> None:
    articles = [
        _article("AAA", "Lucros recorde impulsionam as ações", "positivo", 0.5, 2),
        _article("AAA", "Empresa anuncia nova fábrica em Aveiro", "neutro", 0.0, 0),
        _article("BBB", "Hynix Jumps 6% as Asia Buys Back Into AI", "positivo", 0.5, 1),
        _article("BBB", "Resultados caem e a procura enfraquece", "negativo", -0.5, 2),
        _article("BBB", "Reunião da administração em Lisboa", "neutro", 0.0, 0),
    ]
    summary = _snapshot(monkeypatch, articles)["summary"]

    # As duas sem vocabulário não diluem a média das lidas.
    read_mean = (0.5 + 0.5 - 0.5) / 3
    assert summary["sentiment_read"] == pytest.approx(round(read_mean, 4))
    assert summary["label_read"] == market.tone_of(read_mean)
    # A média de todas (a que diluía) continua à vista, mas já não é a leitura.
    assert summary["sentiment"] == pytest.approx(round((0.5 + 0.5 - 0.5) / 5, 4))
    assert summary["label"] == market.tone_of(summary["sentiment"])


def test_no_vocabulary_is_a_missing_reading_not_neutral(monkeypatch) -> None:
    articles = [
        _article("AAA", "Oppenheimer Revamps Microsoft Price Target", "neutro", 0.0, 0),
        _article("BBB", "Apple introduces the new MacBook Pro", "neutro", 0.0, 0),
    ]
    snapshot = _snapshot(monkeypatch, articles)
    summary = snapshot["summary"]

    assert summary["covered"] == 0
    assert summary["unread"] == 2
    assert summary["neutral_read"] == 0
    assert summary["sentiment_read"] is None
    assert summary["label_read"] is None
    assert summary["coverage"] == 0
    # A leitura bruta fica «neutro» por ausência de tom — nunca como positivo/negativo.
    assert summary["label"] == "neutro"
