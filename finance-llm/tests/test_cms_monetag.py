"""Monetag stays separate from the public site and application PWA workers."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import cms_render, cms_routes


def test_monetag_worker_is_served_with_restricted_scope():
    app = FastAPI()
    app.include_router(cms_routes.router)
    with TestClient(app) as client:
        response = client.get("/site/monetag/sw.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["service-worker-allowed"] == "/site/monetag/"
    assert response.headers["cache-control"] == "no-cache, must-revalidate"
    assert '"zoneId": 12235494' in response.text
    assert "https://3nbf4.com/act/files/service-worker.min.js?r=sw" in response.text


def test_public_layout_registers_separate_workers_but_preview_does_not():
    args = dict(title="Test", description="", body="", current_path="/site/",
                settings={"site_name": "Test"})
    public = cms_render._layout(**args)
    preview = cms_render._layout(**args, preview=True)
    assert 'register("/site/sw.js")' in public
    assert 'register("/site/monetag/sw.js",' in public
    assert 'scope:"/site/monetag/"' in public
    assert "requestPermission" not in public
    assert "monetag/sw.js" not in preview


def test_offline_workers_do_not_import_monetag():
    root = Path(__file__).resolve().parents[1]
    app_worker = (root / "chat-ui" / "public" / "sw.js").read_text(encoding="utf-8")
    site_worker = cms_render.render_service_worker({"site_name": "Test"})
    for worker in (app_worker, site_worker):
        assert "3nbf4.com" not in worker
        assert "12235494" not in worker
