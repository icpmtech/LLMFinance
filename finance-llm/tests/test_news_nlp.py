"""Testes para NLP e endpoints Elasticsearch de notícias.

Como executar:
    cd c:\\LLMFinance\\finance-llm
    PYTHONPATH=c:\\LLMFinance\\finance-llm c:\\LLMFinance\\.venv\\Scripts\\python.exe -m pytest tests/test_news_nlp.py -v
"""
import pytest
from api.news_nlp import (
    _detect_language,
    _extract_entities,
    _extract_topics,
    _heuristic_sentiment,
    _summarize_pt,
    _translate_simple,
    analyze_news_item,
    build_news_entity_graph,
)


def test_detect_language_english():
    assert _detect_language("Apple stock surges after earnings") == "en"


def test_detect_language_portuguese():
    assert _detect_language("A Apple lança novo iPhone em Portugal") == "pt"


def test_heuristic_sentiment_positive():
    assert _heuristic_sentiment("Apple gains on strong revenue", "") == "positivo"


def test_heuristic_sentiment_negative():
    assert _heuristic_sentiment("Apple falls on weak demand", "") == "negativo"


def test_translate_simple_basic():
    pt = _translate_simple("Apple unveils new iPhone models")
    assert "Apple" in pt
    assert "iPhone" in pt
    assert any(w in pt.lower() for w in ("revela", "apresenta", "lança"))


def test_summarize_pt_ends_with_sentiment():
    s = _summarize_pt("Apple launches iPhone 18", "The new phone has AI features", "positivo")
    assert s.endswith(".")
    assert "positivo" in s or "positivo" in s.lower()


def test_extract_entities_aapl():
    entities = _extract_entities(
        "Apple's iPhone Duo Threatens iPad Sales",
        "Analysts say the foldable iPhone could drive revenue growth",
        ticker="AAPL",
    )
    names = {e["name"].lower() for e in entities}
    assert "aapl" in names
    assert any("iphone" in n for n in names)
    assert any("ipad" in n for n in names)


def test_extract_topics_contains_ai_or_hardware():
    topics = _extract_topics("Apple unveils AI features in new iPhone", "The phone uses artificial intelligence")
    assert any(t in ("inteligência artificial", "hardware") for t in topics)


def test_analyze_news_item_returns_entities_and_topics():
    result = analyze_news_item(
        title="Apple launches iPhone 18 Pro",
        summary="Analysts say sales could surge",
        backend="gpt2",
        ticker="AAPL",
    )
    assert result.sentiment in ("positivo", "negativo", "neutro")
    assert result.language
    assert result.summary_pt
    assert len(result.entities) > 0
    assert len(result.topics) > 0


def test_build_news_entity_graph():
    items = [
        {
            "title": "Apple launches iPhone",
            "translated_title": "Apple lança iPhone",
            "sentiment": "positivo",
            "published": "2026-09-10T10:00:00Z",
            "url": "http://example.com/1",
            "entities": [{"name": "AAPL", "type": "ticker"}, {"name": "iPhone", "type": "produto"}],
            "topics": ["hardware"],
        },
        {
            "title": "iPhone sales boost revenue",
            "translated_title": "Vendas do iPhone impulsionam receita",
            "sentiment": "positivo",
            "published": "2026-09-10T11:00:00Z",
            "url": "http://example.com/2",
            "entities": [{"name": "AAPL", "type": "ticker"}, {"name": "iPhone", "type": "produto"}],
            "topics": ["resultados financeiros"],
        },
    ]
    graph = build_news_entity_graph("AAPL", items)
    assert graph["ticker"] == "AAPL"
    assert len(graph["nodes"]) > 2
    assert len(graph["edges"]) > 0
    assert any(n["type"] == "entidade" for n in graph["nodes"])


@pytest.mark.skipif(True, reason="Requer backend FastAPI em execução")
def test_api_elastic_ingest_news():
    import requests
    r = requests.post("http://127.0.0.1:8003/elastic/ingest/news/AAPL", params={"auto_analyze": True, "backend": "gpt2"})
    assert r.status_code == 200
    data = r.json()
    assert data["indexed_count"] > 0
    assert data["analyzed_count"] == data["indexed_count"]


@pytest.mark.skipif(True, reason="Requer backend FastAPI em execução")
def test_api_elastic_graph_news():
    import requests
    requests.post("http://127.0.0.1:8003/elastic/ingest/news/AAPL", params={"auto_analyze": True, "backend": "gpt2"})
    r = requests.get("http://127.0.0.1:8003/elastic/graph/news/AAPL", params={"source": "es"})
    assert r.status_code == 200
    data = r.json()
    assert data["node_count"] > 0
    assert data["edge_count"] >= data["node_count"] - 1
