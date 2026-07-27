# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app import web_search as web_search_module
from qwenpaw.app.routers import web_search as web_search_router
from qwenpaw.app.routers import router as api_router
from qwenpaw.app.web_search import (
    WebSearchConfigStore,
    WebSearchResponse,
    WebSearchResult,
)


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    store = WebSearchConfigStore(tmp_path / "web_search.json")
    monkeypatch.setattr(web_search_router, "_store", lambda: store)
    monkeypatch.setattr(
        web_search_module,
        "encrypt_dict_fields",
        lambda data, _fields: dict(data),
    )
    monkeypatch.setattr(
        web_search_module,
        "decrypt_dict_fields",
        lambda data, _fields: dict(data),
    )

    class FakeCacheService:
        async def clear_cache(self):
            return None

    monkeypatch.setattr(
        web_search_router,
        "get_web_search_service",
        lambda: FakeCacheService(),
    )
    test_app = FastAPI()
    test_app.include_router(web_search_router.router, prefix="/api/admin")
    return test_app


@pytest.fixture
def api_client(app: FastAPI):
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )


def _payload(**overrides) -> dict:
    data = {
        "enabled": True,
        "api_key": "iqs-test-key",
        "endpoint": "https://cloud-iqs.aliyuncs.com/search/unified",
        "engine_type": "LiteAdvanced",
        "default_max_results": 5,
        "timeout_seconds": 8,
        "cache_ttl_seconds": 300,
    }
    data.update(overrides)
    return data


def test_web_search_routes_are_mounted_in_admin_namespace() -> None:
    routes = {
        route.path: route
        for route in api_router.routes
        if hasattr(route, "path")
    }

    assert "/admin/web-search/config" in routes
    assert "/admin/web-search/test" in routes
    assert routes["/admin/web-search/config"].dependencies


@pytest.mark.asyncio
async def test_get_default_config_is_disabled(api_client: AsyncClient) -> None:
    async with api_client:
        response = await api_client.get("/api/admin/web-search/config")

    assert response.status_code == 200
    config = response.json()["config"]
    assert config["provider"] == "aliyun_iqs"
    assert config["enabled"] is False
    assert config["configured"] is False
    assert config["api_key"] == ""


@pytest.mark.asyncio
async def test_put_config_masks_and_preserves_api_key(
    api_client: AsyncClient,
) -> None:
    async with api_client:
        created = await api_client.put(
            "/api/admin/web-search/config",
            json=_payload(api_key="saved-key"),
        )
        updated = await api_client.put(
            "/api/admin/web-search/config",
            json=_payload(api_key="********", default_max_results=8),
        )

    assert created.status_code == 200
    assert created.json()["config"]["api_key"] == "********"
    assert created.json()["config"]["available"] is True
    assert updated.status_code == 200
    assert updated.json()["config"]["default_max_results"] == 8
    assert web_search_router._store().get_config().api_key == "saved-key"


@pytest.mark.asyncio
async def test_put_config_rejects_enabled_provider_without_api_key(
    api_client: AsyncClient,
) -> None:
    async with api_client:
        response = await api_client.put(
            "/api/admin/web-search/config",
            json=_payload(api_key=""),
        )

    assert response.status_code == 400
    assert "API Key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_connection_test_uses_unsaved_config(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = {}

    class FakeService:
        async def clear_cache(self):
            return None

        async def search(self, query: str, **kwargs):
            seen.update({"query": query, **kwargs})
            return WebSearchResponse(
                query=query,
                request_id="req-test",
                search_time_ms=10,
                results=(
                    WebSearchResult(
                        title="Aliyun",
                        url="https://www.aliyun.com",
                        snippet="Alibaba Cloud",
                    ),
                ),
            )

    monkeypatch.setattr(
        web_search_router,
        "get_web_search_service",
        lambda: FakeService(),
    )

    async with api_client:
        response = await api_client.post(
            "/api/admin/web-search/test",
            json=_payload(enabled=False),
        )

    assert response.status_code == 200
    assert response.json()["sample_title"] == "Aliyun"
    assert seen["query"] == "阿里云"
    assert seen["require_enabled"] is False
    assert seen["use_cache"] is False
