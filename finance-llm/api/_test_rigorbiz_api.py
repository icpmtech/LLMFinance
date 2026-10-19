"""Testes rápidos para o módulo RigorBiz."""
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_meta():
    r = client.get("/rigorbiz/meta")
    assert r.status_code == 200
    data = r.json()
    assert "local_count" in data
    assert "index" in data


def test_search():
    r = client.get("/rigorbiz/search?q=018+design")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert data["total"] >= 0


def test_detail_found():
    r = client.get("/rigorbiz/509802176")
    assert r.status_code == 200
    data = r.json()
    assert data.get("nif") == "509802176"


def test_detail_not_found():
    r = client.get("/rigorbiz/000000000")
    assert r.status_code == 404


def test_collect_status():
    r = client.get("/rigorbiz/collect/status")
    assert r.status_code == 200
    data = r.json()
    assert "runner" in data
    assert "prefixes" in data
    assert "meta" in data


def test_collect_log():
    r = client.get("/rigorbiz/collect/log?lines=20")
    assert r.status_code == 200
    assert "lines" in r.json()
