import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.desktop_version_gate import DesktopVersionGateMiddleware


@pytest.fixture
def app(tmp_path, monkeypatch):
    manifest = tmp_path / "latest.json"
    manifest.write_text(json.dumps({"version": "2.1.0"}), encoding="utf-8")
    monkeypatch.setenv("DCLAW_DESKTOP_LATEST_PATH", str(manifest))
    monkeypatch.setenv("DCLAW_DESKTOP_BRAND_ID", "dclaw")
    instance = FastAPI()
    instance.add_middleware(DesktopVersionGateMiddleware)

    @instance.get("/api/ping")
    async def ping():
        return {"ok": True}

    return instance


@pytest.mark.asyncio
async def test_web_request_is_not_version_gated(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/ping")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_old_desktop_request_gets_426(app):
    headers = {
        "X-DClaw-Desktop-Brand": "dclaw",
        "X-DClaw-Desktop-Version": "2.0.0",
        "X-DClaw-Desktop-Platform": "macos",
        "X-DClaw-Desktop-Arch": "aarch64",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/ping", headers=headers)
    assert response.status_code == 426
    assert response.json()["latest_version"] == "2.1.0"


@pytest.mark.asyncio
async def test_equal_or_newer_desktop_request_is_allowed(app):
    for version in ("2.1.0", "2.2.0"):
        headers = {
            "X-DClaw-Desktop-Brand": "dclaw",
            "X-DClaw-Desktop-Version": version,
            "X-DClaw-Desktop-Platform": "windows",
            "X-DClaw-Desktop-Arch": "x86_64",
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/ping", headers=headers)
        assert response.status_code == 200
