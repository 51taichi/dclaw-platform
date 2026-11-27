from types import SimpleNamespace

import httpx
import pytest

from qwenpaw.app.routers import aigc_studio


@pytest.mark.asyncio
@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("cdn", ["https://cdn1.ttapi.io/grok/result.mp4", "", None])
async def test_grok_query_prefers_cdn_video_url(monkeypatch, wrapped, cdn):
    original = "https://vidgen.x.ai/result.mp4"
    data = {
        "status": "completed",
        "video_url": original,
        "rawResponse": {"status": "done", "video": {"url": original, "cdn_video_url": cdn}},
    }
    payload = {"code": 200, "data": data} if wrapped else data

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **kwargs):
            return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", Client)
    provider = SimpleNamespace(api_key="test-only", base_url="https://provider.example")
    status, url, result = await aigc_studio._mxapi_grok_query_task(provider, "test-task")
    assert status == "completed"
    assert url == (cdn or original)
    assert result == payload
