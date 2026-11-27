# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import ANY
from urllib.parse import parse_qs, urlparse

import pytest

from qwenpaw.app.object_storage import (
    MASKED_SECRET,
    AliyunOssClient,
    ObjectStorageConfig,
    ObjectStorageStore,
)


def _aliyun_config(**overrides) -> ObjectStorageConfig:
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
    return ObjectStorageConfig(**data)


def test_public_config_masks_secret_and_reports_configured() -> None:
    config = _aliyun_config()

    public = config.to_public_dict()

    assert public["enabled"] is True
    assert public["provider"] == "aliyun_oss"
    assert public["access_key_secret"] == MASKED_SECRET
    assert public["configured"] is True


def test_store_update_preserves_secret_when_payload_is_masked(tmp_path: Path) -> None:
    store = ObjectStorageStore(tmp_path / "object_storage.json")
    store.save_config(_aliyun_config(access_key_secret="old-secret"))

    updated = store.update_config(
        {
            "enabled": True,
            "endpoint": "https://oss-cn-shanghai.aliyuncs.com/",
            "bucket": "next-bucket",
            "access_key_id": "next-ak",
            "access_key_secret": MASKED_SECRET,
            "prefix": "/next/prefix/",
            "signed_url_ttl_seconds": 1200,
        }
    )

    assert updated.access_key_secret == "old-secret"
    assert updated.endpoint == "https://oss-cn-shanghai.aliyuncs.com"
    assert updated.prefix == "next/prefix"

    raw = json.loads((tmp_path / "object_storage.json").read_text("utf-8"))
    assert raw["access_key_secret"] == "old-secret"


def test_client_builds_safe_prefixed_object_keys() -> None:
    client = AliyunOssClient(_aliyun_config(prefix="/aigc/generated/"))

    assert (
        client.build_object_key("aigc_studio/canvas-1/job-1/result.png")
        == "aigc/generated/aigc_studio/canvas-1/job-1/result.png"
    )

    with pytest.raises(ValueError, match="outside"):
        client.build_object_key("../secret.txt")


def test_client_generates_signed_get_url_with_bucket_host() -> None:
    client = AliyunOssClient(_aliyun_config(), time_fn=lambda: 1000)

    signed_url = client.signed_get_url(
        "aigc/generated/aigc_studio/canvas-1/job-1/result image.png"
    )

    parsed = urlparse(signed_url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "qwenpaw-aigc.oss-cn-hangzhou.aliyuncs.com"
    assert parsed.path == "/aigc/generated/aigc_studio/canvas-1/job-1/result%20image.png"
    assert query["OSSAccessKeyId"] == ["test-ak"]
    assert query["Expires"] == ["1600"]
    assert query["Signature"][0]


def test_client_generates_signed_put_url_with_content_type() -> None:
    client = AliyunOssClient(_aliyun_config(), time_fn=lambda: 1000)

    signed_url = client.signed_put_url(
        "aigc/generated/aigc_studio/uploads/reference.png",
        "image/png",
    )

    parsed = urlparse(signed_url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "qwenpaw-aigc.oss-cn-hangzhou.aliyuncs.com"
    assert parsed.path == "/aigc/generated/aigc_studio/uploads/reference.png"
    assert query["OSSAccessKeyId"] == ["test-ak"]
    assert query["Expires"] == ["1600"]
    assert query["Signature"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("configured_value", "expected_write_timeout"),
    [
        (None, 600.0),
        ("900", 900.0),
        ("invalid", 600.0),
        ("1", 60.0),
        ("7200", 3600.0),
    ],
)
async def test_default_http_client_uses_configurable_oss_write_timeout(
    monkeypatch: pytest.MonkeyPatch,
    configured_value: str | None,
    expected_write_timeout: float,
) -> None:
    if configured_value is None:
        monkeypatch.delenv("DCLAW_OSS_WRITE_TIMEOUT_SECONDS", raising=False)
    else:
        monkeypatch.setenv("DCLAW_OSS_WRITE_TIMEOUT_SECONDS", configured_value)

    client = AliyunOssClient._default_http_client()
    try:
        assert client.timeout.connect == 15.0
        assert client.timeout.read == 60.0
        assert client.timeout.write == expected_write_timeout
        assert client.timeout.pool == 60.0
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_upload_puts_bytes_to_signed_oss_resource() -> None:
    calls: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc_info):
            return None

        async def put(self, url: str, *, content: bytes, headers: dict[str, str]):
            calls.append({"url": url, "content": content, "headers": headers})
            return FakeResponse()

    client = AliyunOssClient(
        _aliyun_config(),
        http_client_factory=lambda: FakeAsyncClient(),
        date_fn=lambda: "Thu, 25 Jun 2026 00:00:00 GMT",
    )

    stored = await client.upload(
        relative_path="aigc_studio/canvas-1/job-1/result.png",
        content=b"png-bytes",
        mime_type="image/png",
    )

    assert stored["provider"] == "aliyun_oss"
    assert stored["bucket"] == "qwenpaw-aigc"
    assert stored["object_key"] == "aigc/generated/aigc_studio/canvas-1/job-1/result.png"
    assert calls == [
        {
            "url": (
                "https://qwenpaw-aigc.oss-cn-hangzhou.aliyuncs.com/"
                "aigc/generated/aigc_studio/canvas-1/job-1/result.png"
            ),
            "content": b"png-bytes",
            "headers": {
                "Authorization": ANY,
                "Content-Type": "image/png",
                "Date": "Thu, 25 Jun 2026 00:00:00 GMT",
            },
        }
    ]
    assert calls[0]["headers"]["Authorization"].startswith("OSS test-ak:")
