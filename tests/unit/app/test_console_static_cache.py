# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi.testclient import TestClient

from qwenpaw.app._app import app


def test_console_spa_index_disables_browser_cache():
    response = TestClient(app).get("/agent-config")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert response.headers.get("cache-control") == "no-store, max-age=0"
    assert response.headers.get("pragma") == "no-cache"
