# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from qwenpaw.app import web_search as web_search_module
from qwenpaw.app.web_search import (
    ALIYUN_IQS_ENDPOINT,
    ALIYUN_IQS_READ_PAGE_ENDPOINT,
    AliyunIQSClient,
    WebSearchConfig,
    WebSearchConfigStore,
    WebSearchError,
    WebSearchResponse,
    WebSearchResult,
    WebSearchService,
    normalize_public_url,
)


def _config(**overrides) -> WebSearchConfig:
    data = {
        "enabled": True,
        "api_key": "iqs-test-key",
        "default_max_results": 5,
        "timeout_seconds": 8,
        "cache_ttl_seconds": 300,
    }
    data.update(overrides)
    return WebSearchConfig(**data)


def test_config_store_encrypts_and_preserves_masked_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_encrypt(data, _fields):
        return {**data, "api_key": f"ENC:{data['api_key']}"}

    def fake_decrypt(data, _fields):
        api_key = str(data.get("api_key") or "")
        return {
            **data,
            "api_key": api_key.removeprefix("ENC:"),
        }

    monkeypatch.setattr(web_search_module, "encrypt_dict_fields", fake_encrypt)
    monkeypatch.setattr(web_search_module, "decrypt_dict_fields", fake_decrypt)
    store = WebSearchConfigStore(tmp_path / "web_search.json")

    store.save_config(_config(api_key="old-key"))
    updated = store.update_config(
        {
            "enabled": True,
            "api_key": "********",
            "endpoint": ALIYUN_IQS_ENDPOINT,
            "engine_type": "LiteAdvanced",
            "default_max_results": 7,
            "timeout_seconds": 9,
            "cache_ttl_seconds": 120,
        }
    )

    assert updated.api_key == "old-key"
    assert updated.default_max_results == 7
    assert store.get_config().api_key == "old-key"
    raw = json.loads((tmp_path / "web_search.json").read_text("utf-8"))
    assert raw["api_key"] == "ENC:old-key"
    assert (tmp_path / "web_search.json").stat().st_mode & 0o777 == 0o600


def test_config_rejects_non_iqs_endpoint_and_non_lite_engine() -> None:
    with pytest.raises(ValueError, match="IQS endpoint"):
        _config(endpoint="https://example.com/search")

    with pytest.raises(ValueError, match="LiteAdvanced"):
        _config(engine_type="Deep")


@pytest.mark.asyncio
async def test_iqs_client_sends_direct_unified_search_request() -> None:
    calls: list[dict] = []

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc_info):
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict,
            json: dict,
            timeout: float,
        ):
            calls.append(
                {
                    "url": url,
                    "headers": headers,
                    "json": json,
                    "timeout": timeout,
                }
            )
            request = httpx.Request("POST", url)
            return httpx.Response(
                200,
                request=request,
                json={
                    "requestId": "req-1",
                    "pageItems": [
                        {
                            "title": "Alibaba Cloud",
                            "link": "https://www.aliyun.com/",
                            "snippet": "Cloud services",
                            "publishedTime": "2026-07-10T09:00:00+08:00",
                            "mainText": "Detailed page content",
                            "hostname": "阿里云",
                            "rerankScore": 0.98,
                        },
                        {
                            "title": "unsafe",
                            "link": "javascript:alert(1)",
                            "snippet": "ignored",
                        },
                    ],
                    "searchInformation": {"searchTime": 321},
                },
            )

    client = AliyunIQSClient(
        _config(),
        http_client_factory=lambda: FakeAsyncClient(),
    )
    response = await client.search(
        "阿里云",
        max_results=3,
        freshness="week",
        include_content=True,
    )

    assert response.request_id == "req-1"
    assert response.search_time_ms == 321
    assert len(response.results) == 1
    assert response.results[0].content == "Detailed page content"
    assert calls[0]["url"] == ALIYUN_IQS_ENDPOINT
    assert calls[0]["headers"]["Authorization"] == "Bearer iqs-test-key"
    assert calls[0]["timeout"] == 8
    assert calls[0]["json"] == {
        "query": "阿里云",
        "engineType": "LiteAdvanced",
        "timeRange": "OneWeek",
        "contents": {
            "mainText": True,
            "markdownText": False,
            "summary": False,
            "rerankScore": True,
        },
        "advancedParams": {"numResults": "3"},
    }


def test_public_page_url_validation_rejects_private_targets() -> None:
    assert normalize_public_url("https://example.com/page#section") == (
        "https://example.com/page"
    )

    for url in (
        "file:///etc/passwd",
        "http://localhost/admin",
        "http://127.0.0.1/private",
        "http://192.168.1.2/private",
        "https://user:pass@example.com/private",
    ):
        with pytest.raises(ValueError):
            normalize_public_url(url)


@pytest.mark.asyncio
async def test_iqs_client_reads_page_with_same_api_key() -> None:
    calls: list[dict] = []

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc_info):
            return None

        async def post(self, url: str, **kwargs):
            calls.append({"url": url, **kwargs})
            request = httpx.Request("POST", url)
            return httpx.Response(
                200,
                request=request,
                json={
                    "requestId": "read-1",
                    "data": {
                        "redirectedUrl": "https://example.com/final",
                        "title": "Example article",
                        "markdown": "# Article\n\nBody",
                        "text": "Article Body",
                        "publishedDate": "2026-07-10T08:00:00+08:00",
                        "lastModified": "2026-07-10T09:00:00+08:00",
                        "author": "Author",
                        "siteName": "Example",
                        "contentType": "text/html",
                        "language": "en",
                        "pageType": "article",
                        "pdfParse": False,
                    },
                },
            )

    client = AliyunIQSClient(
        _config(),
        http_client_factory=lambda: FakeAsyncClient(),
    )
    response = await client.read_page(
        "https://example.com/article#intro",
        max_age_seconds=300,
    )

    assert response.url == "https://example.com/article"
    assert response.final_url == "https://example.com/final"
    assert response.title == "Example article"
    assert response.content == "# Article\n\nBody"
    assert response.request_id == "read-1"
    assert calls[0]["url"] == ALIYUN_IQS_READ_PAGE_ENDPOINT
    assert calls[0]["headers"]["Authorization"] == "Bearer iqs-test-key"
    assert calls[0]["timeout"] == 15.0
    assert calls[0]["json"] == {
        "url": "https://example.com/article",
        "pageTimeout": 8000,
        "formats": ["markdown", "text"],
        "maxAge": 300,
        "readability": {"readabilityMode": "normal"},
        "excludeAllImages": True,
        "excludeAllLinks": False,
    }


@pytest.mark.asyncio
async def test_iqs_client_returns_readable_provider_error() -> None:
    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc_info):
            return None

        async def post(self, url: str, **_kwargs):
            request = httpx.Request("POST", url)
            return httpx.Response(
                403,
                request=request,
                json={
                    "code": "Retrieval.NotAuthorised",
                    "message": "RAM permission is missing",
                },
            )

    client = AliyunIQSClient(
        _config(),
        http_client_factory=lambda: FakeAsyncClient(),
    )

    with pytest.raises(WebSearchError, match="Retrieval.NotAuthorised"):
        await client.search(
            "test",
            max_results=1,
            freshness="no_limit",
            include_content=False,
        )


@pytest.mark.asyncio
async def test_iqs_client_retries_one_transient_http_response() -> None:
    calls = 0

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc_info):
            return None

        async def post(self, url: str, **_kwargs):
            nonlocal calls
            calls += 1
            request = httpx.Request("POST", url)
            if calls == 1:
                return httpx.Response(
                    503,
                    request=request,
                    headers={"Retry-After": "0"},
                )
            return httpx.Response(
                200,
                request=request,
                json={"requestId": "retry-ok", "pageItems": []},
            )

    client = AliyunIQSClient(
        _config(),
        http_client_factory=lambda: FakeAsyncClient(),
    )

    response = await client.search(
        "test",
        max_results=1,
        freshness="no_limit",
        include_content=False,
    )

    assert response.request_id == "retry-ok"
    assert calls == 2


@pytest.mark.asyncio
async def test_service_reuses_short_lived_cache() -> None:
    calls = 0

    class FakeClient:
        async def search(self, query: str, **_kwargs):
            nonlocal calls
            calls += 1
            return WebSearchResponse(
                query=query,
                results=(
                    WebSearchResult(
                        title="Result",
                        url="https://example.com",
                        snippet="Snippet",
                    ),
                ),
            )

    service = WebSearchService(client_factory=lambda _config: FakeClient())
    config = _config(cache_ttl_seconds=300)

    first = await service.search("same query", config=config)
    second = await service.search("same query", config=config)

    assert first.cached is False
    assert second.cached is True
    assert calls == 1
