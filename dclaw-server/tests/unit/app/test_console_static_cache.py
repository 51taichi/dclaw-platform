# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.app import _app as app_module


def test_console_spa_index_disables_browser_cache(tmp_path, monkeypatch):
    index = tmp_path / "index.html"
    index.write_text("<!doctype html><title>DClaw</title>", encoding="utf-8")
    monkeypatch.setattr(app_module, "_CONSOLE_INDEX", index)

    response = app_module._console_index_response()

    assert response.status_code == 200
    assert response.media_type == "text/html"
    assert response.headers.get("cache-control") == "no-store, max-age=0"
    assert response.headers.get("pragma") == "no-cache"
