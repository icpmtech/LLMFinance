"""Removed ads cannot return or unregister either PWA."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import cms_render, cms_routes


def test_legacy_worker_is_retired_with_restricted_scope():
    app = FastAPI()
    app.include_router(cms_routes.router)
    with TestClient(app) as client:
        response = client.get("/site/monetag/sw.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["service-worker-allowed"] == "/site/monetag/"
    assert response.headers["cache-control"] == "no-cache, must-revalidate"
    assert "self.registration.unregister()" in response.text
    assert "self.skipWaiting()" in response.text
    assert "importScripts" not in response.text
    assert "3nbf4.com" not in response.text


def test_public_layout_registers_separate_workers_but_preview_does_not():
    args = dict(title="Test", description="", body="", current_path="/site/",
                settings={"site_name": "Test"})
    public = cms_render._layout(**args)
    preview = cms_render._layout(**args, preview=True)
    assert 'register("/site/sw.js")' in public
    assert 'register("/site/monetag/sw.js",' not in public
    assert 'registration.scope===location.origin+"/site/monetag/"' in public
    assert "registration.unregister()" in public
    assert "requestPermission" not in public
    assert "/site/monetag/" not in preview
    verification = '<meta name="monetag" content="5c7c1e6c97c42b0d781e64713443053b">'
    assert verification not in public
    assert verification not in preview
    ad_script = '<script src="https://quge5.com/88/tag.min.js" data-zone="308607" async data-cfasync="false"></script>'
    assert ad_script not in public
    assert "quge5.com" not in preview


def test_offline_workers_do_not_import_monetag():
    root = Path(__file__).resolve().parents[1]
    app_worker = (root / "chat-ui" / "public" / "sw.js").read_text(encoding="utf-8")
    site_worker = cms_render.render_service_worker({"site_name": "Test"})
    for worker in (app_worker, site_worker):
        assert "3nbf4.com" not in worker
        assert "12235494" not in worker


def test_root_html_excludes_monetag():
    root = Path(__file__).resolve().parents[1]
    html = (root / "chat-ui" / "index.html").read_text(encoding="utf-8")
    head = html.split("</head>", 1)[0]
    assert 'name="monetag"' not in head
    assert "/site/monetag/sw.js" not in html
    assert "quge5.com" not in html
