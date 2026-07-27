# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import ANY

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.object_storage import (
    MASKED_SECRET,
    AliyunOssClient,
    ObjectStorageConfig,
    ObjectStorageStore,
)
from qwenpaw.app.routers import object_storage as object_storage_router


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    store = ObjectStorageStore(tmp_path / "object_storage.json")
    monkeypatch.setattr(object_storage_router, "_store", lambda: store)
    test_app = FastAPI()
    test_app.include_router(object_storage_router.router, prefix="/api/admin")
    return test_app


@pytest.fixture
def api_client(app: FastAPI):
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _payload(**overrides) -> dict:
    data = {
        "enabled": True,
        "endpoint": "oss-cn-hangzhou.aliyuncs.com",
        "bucket": "qwenpaw-aigc",
        "access_key_id": "test-ak",
        "access_key_secret": "test-secret",
        "prefix": "aigc/generated",
        "signed_url_ttl_seconds": 600,
    }
    data.update(overrides)
    return data


async def test_get_default_object_storage_config(api_client: AsyncClient) -> None:
    async with api_client:
        resp = await api_client.get("/api/admin/object-storage/config")

    assert resp.status_code == 200
    body = resp.json()["config"]
    assert body["provider"] == "aliyun_oss"
    assert body["enabled"] is False
    assert body["configured"] is False
    assert body["access_key_secret"] == ""


async def test_put_object_storage_config_masks_and_preserves_secret(
    api_client: AsyncClient,
    tmp_path: Path,
) -> None:
    async with api_client:
        created = await api_client.put(
            "/api/admin/object-storage/config",
            json=_payload(access_key_secret="old-secret"),
        )
        updated = await api_client.put(
            "/api/admin/object-storage/config",
            json=_payload(
                endpoint="https://oss-cn-shanghai.aliyuncs.com/",
                access_key_secret=MASKED_SECRET,
            ),
        )

    assert created.status_code == 200
    assert created.json()["config"]["access_key_secret"] == MASKED_SECRET
    assert updated.status_code == 200
    assert updated.json()["config"]["endpoint"] == "https://oss-cn-shanghai.aliyuncs.com"
    assert updated.json()["config"]["access_key_secret"] == MASKED_SECRET

    raw = json.loads((tmp_path / "object_storage.json").read_text("utf-8"))
    assert raw["access_key_secret"] == "old-secret"


async def test_post_object_storage_test_uploads_probe_object(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploads: list[dict] = []

    class FakeClient:
        def __init__(self, config) -> None:
            self.config = config

        async def upload(self, *, relative_path: str, content: bytes, mime_type: str):
            uploads.append(
                {
                    "relative_path": relative_path,
                    "content": content,
                    "mime_type": mime_type,
                    "bucket": self.config.bucket,
                }
            )
            return {
                "provider": "aliyun_oss",
                "bucket": self.config.bucket,
                "object_key": "aigc/generated/connection-tests/probe.txt",
            }

    monkeypatch.setattr(object_storage_router, "AliyunOssClient", FakeClient)

    async with api_client:
        resp = await api_client.post(
            "/api/admin/object-storage/test",
            json=_payload(),
        )

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "provider": "aliyun_oss",
        "bucket": "qwenpaw-aigc",
        "object_key": "aigc/generated/connection-tests/probe.txt",
    }
    assert uploads == [
        {
            "relative_path": ANY,
            "content": b"qwenpaw object storage test",
            "mime_type": "text/plain",
            "bucket": "qwenpaw-aigc",
        }
    ]
    assert uploads[0]["relative_path"].startswith("connection-tests/")


def test_aliyun_oss_client_uses_custom_domain_without_bucket_prefix() -> None:
    config = ObjectStorageConfig(
        endpoint="https://static.deepmega.cn",
        bucket="dclaw001",
        access_key_id="test-ak",
        access_key_secret="test-secret",
    )

    url = AliyunOssClient(config).object_url("aigc/generated/probe.txt")

    assert url == "https://static.deepmega.cn/aigc/generated/probe.txt"


def test_aliyun_oss_client_keeps_bucket_prefix_for_aliyun_endpoint() -> None:
    config = ObjectStorageConfig(
        endpoint="https://oss-cn-hangzhou.aliyuncs.com",
        bucket="dclaw001",
        access_key_id="test-ak",
        access_key_secret="test-secret",
    )

    url = AliyunOssClient(config).object_url("aigc/generated/probe.txt")

    assert url == "https://dclaw001.oss-cn-hangzhou.aliyuncs.com/aigc/generated/probe.txt"


async def test_post_object_storage_test_preserves_masked_secret_from_store(
    api_client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ObjectStorageStore(tmp_path / "object_storage.json").save_config(
        ObjectStorageConfig(
            enabled=True,
            endpoint="https://static.deepmega.cn",
            bucket="dclaw001",
            access_key_id="test-ak",
            access_key_secret="saved-secret",
            prefix="aigc/generated",
        )
    )
    seen_secret = ""

    class FakeClient:
        def __init__(self, config) -> None:
            nonlocal seen_secret
            seen_secret = config.access_key_secret

        async def upload(self, *, relative_path: str, content: bytes, mime_type: str):
            return {
                "provider": "aliyun_oss",
                "bucket": "dclaw001",
                "object_key": "aigc/generated/connection-tests/probe.txt",
            }

    monkeypatch.setattr(object_storage_router, "AliyunOssClient", FakeClient)

    async with api_client:
        resp = await api_client.post(
            "/api/admin/object-storage/test",
            json=_payload(
                endpoint="https://static.deepmega.cn",
                bucket="dclaw001",
                access_key_id="test-ak",
                access_key_secret=MASKED_SECRET,
            ),
        )

    assert resp.status_code == 200
    assert seen_secret == "saved-secret"


async def test_post_object_storage_test_returns_readable_error_on_oss_failure(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, config) -> None:
            self.config = config

        async def upload(self, *, relative_path: str, content: bytes, mime_type: str):
            request = httpx.Request("PUT", "https://static.deepmega.cn/probe.txt")
            response = httpx.Response(
                403,
                request=request,
                text="<Error><Code>AccessDenied</Code><Message>Access denied.</Message></Error>",
            )
            raise httpx.HTTPStatusError(
                "Forbidden",
                request=request,
                response=response,
            )

    monkeypatch.setattr(object_storage_router, "AliyunOssClient", FakeClient)

    async with api_client:
        resp = await api_client.post(
            "/api/admin/object-storage/test",
            json=_payload(endpoint="https://static.deepmega.cn", bucket="dclaw001"),
        )

    assert resp.status_code == 400
    assert resp.json()["detail"] == (
        "Aliyun OSS test upload failed: HTTP 403 AccessDenied: Access denied."
    )


async def test_post_object_storage_test_explains_custom_domain_bucket_mismatch(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, config) -> None:
            self.config = config

        async def upload(self, *, relative_path: str, content: bytes, mime_type: str):
            request = httpx.Request("PUT", "https://static.deepmega.cn/probe.txt")
            response = httpx.Response(
                403,
                request=request,
                text=(
                    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
                    "<Error>"
                    "<Code>SignatureDoesNotMatch</Code>"
                    "<Message>The request signature we calculated does not match.</Message>"
                    "<StringToSign>PUT\n\ntext/plain\nSat, 27 Jun 2026 04:12:29 GMT\n"
                    "/deepmega-applet/aigc/generated/probe.txt</StringToSign>"
                    "</Error>"
                ),
            )
            raise httpx.HTTPStatusError(
                "Forbidden",
                request=request,
                response=response,
            )

    monkeypatch.setattr(object_storage_router, "AliyunOssClient", FakeClient)

    async with api_client:
        resp = await api_client.post(
            "/api/admin/object-storage/test",
            json=_payload(endpoint="https://static.deepmega.cn", bucket="dclaw001"),
        )

    assert resp.status_code == 400
    assert "SignatureDoesNotMatch" in resp.json()["detail"]
    assert "deepmega-applet" in resp.json()["detail"]
    assert "Bucket 与自定义域名绑定关系" in resp.json()["detail"]
