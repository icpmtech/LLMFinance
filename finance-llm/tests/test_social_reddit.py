"""Testes do coletor do Reddit (feed Atom como alternativa ao JSON bloqueado)."""
from __future__ import annotations

import pytest

from api import social_collectors as sc


ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>r/investimentos</title>
  <entry>
    <author><name>/u/analista</name><uri>https://www.reddit.com/user/analista</uri></author>
    <category term="investimentos" label="r/investimentos"/>
    <category term="Banca" label="Banca"/>
    <content type="html">&lt;table&gt;&lt;tr&gt;&lt;td&gt;&lt;a href="https://www.reddit.com/r/investimentos/comments/1abc23/titulo/"&gt;[link]&lt;/a&gt;&lt;/td&gt;&lt;td&gt;Texto do post sobre a EDP.&lt;/td&gt;&lt;/tr&gt;&lt;/table&gt;</content>
    <id>t3_1abc23</id>
    <link href="https://www.reddit.com/r/investimentos/comments/1abc23/titulo/"/>
    <updated>2026-10-04T18:30:00+00:00</updated>
    <published>2026-10-04T18:30:00+00:00</published>
    <title>Será que a EDP vai subir?</title>
  </entry>
</feed>
"""

EMPTY_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>r/vazio</title></feed>
"""


def test_reddit_rss_posts_normaliza_entradas() -> None:
    posts = sc._reddit_rss_posts(ATOM_FEED, "investimentos", "subreddit")

    assert len(posts) == 1
    post = posts[0]
    assert post["platform"] == "reddit"
    assert post["post_id"] == "1abc23"
    assert post["title"] == "Será que a EDP vai subir?"
    assert post["author"] == "analista"
    assert post["community"] == "r/investimentos"
    assert post["published_at"] == "2026-10-04T18:30:00+00:00"
    assert "EDP" in post["text"]
    assert "<" not in post["text"]
    assert "Banca" in post["tags"]
    assert post["data"]["source"] == "rss"


def test_reddit_rss_posts_feed_invalido() -> None:
    assert sc._reddit_rss_posts("não é xml", "investimentos", "subreddit") == []
    assert sc._reddit_rss_posts(EMPTY_FEED, "vazio", "subreddit") == []


def _blocked(url: str, options=None, **kwargs):
    raise sc.CollectorError(f"recusado a {url}", status="blocked")


def test_collect_reddit_usa_feed_quando_json_esta_bloqueado(monkeypatch) -> None:
    chamadas: list[str] = []

    def fake_get(url: str, **kwargs):
        chamadas.append(url)
        if url.endswith(".rss"):
            return ATOM_FEED
        raise sc.CollectorError(f"403 em {url}", status="blocked")

    monkeypatch.setattr(sc, "_http_get", fake_get)
    monkeypatch.setattr(sc, "_fetch_html", _blocked)
    # Sem credenciais: não deve tentar OAuth.
    monkeypatch.setattr(sc, "_reddit_token", lambda options: "")

    result = sc.collect_reddit({"target": "investimentos", "kind": "subreddit", "options": {}})

    assert [p["post_id"] for p in result["items"]] == ["1abc23"]
    assert any(".rss" in url for url in chamadas)
    assert any("hot.json" in url for url in chamadas)
    assert any("feed público" in note for note in result["notes"])


def test_collect_reddit_todos_os_enderecos_bloqueados(monkeypatch) -> None:
    monkeypatch.setattr(sc, "_http_get", _blocked)
    monkeypatch.setattr(sc, "_fetch_html", _blocked)
    monkeypatch.setattr(sc, "_reddit_token", lambda options: "")

    with pytest.raises(sc.CollectorError) as info:
        sc.collect_reddit({"target": "investimentos", "kind": "subreddit", "options": {}})

    assert info.value.status == "blocked"
    assert "proxy" in (info.value.hint or "")


def test_collect_reddit_pesquisa_sem_credenciais_usa_feed(monkeypatch) -> None:
    def fake_get(url: str, **kwargs):
        if url.endswith("search.rss"):
            return ATOM_FEED
        raise sc.CollectorError("403", status="blocked")

    monkeypatch.setattr(sc, "_http_get", fake_get)
    monkeypatch.setattr(sc, "_reddit_token", lambda options: "")

    result = sc.collect_reddit({"target": "edp", "kind": "search", "options": {}})

    assert len(result["items"]) == 1
    assert any("Sem credenciais OAuth" in note for note in result["notes"])


def test_collect_reddit_usa_oauth_na_listagem(monkeypatch) -> None:
    payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "id": "xyz9",
                        "permalink": "/r/investimentos/comments/xyz9/post/",
                        "title": "Título",
                        "selftext": "corpo",
                        "author": "quem",
                        "subreddit": "investimentos",
                        "created_utc": 1_700_000_000,
                        "score": 10,
                        "num_comments": 2,
                    }
                }
            ]
        }
    }

    def fake_get(url: str, **kwargs):
        assert url.startswith("https://oauth.reddit.com/r/investimentos/")
        assert kwargs["headers"]["Authorization"] == "Bearer token-123"
        return payload

    monkeypatch.setattr(sc, "_http_get", fake_get)
    monkeypatch.setattr(sc, "_reddit_token", lambda options: "token-123")

    result = sc.collect_reddit({"target": "investimentos", "kind": "subreddit", "options": {}})

    assert [p["post_id"] for p in result["items"]] == ["xyz9"]
    assert any("OAuth" in note for note in result["notes"])
