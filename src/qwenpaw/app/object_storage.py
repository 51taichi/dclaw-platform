# -*- coding: utf-8 -*-
"""Object storage configuration and Aliyun OSS helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import posixpath
import time
from dataclasses import dataclass, field
from email.utils import formatdate
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlencode, urlparse, urlunparse

import httpx

from ..constant import SECRET_DIR

MASKED_SECRET = "********"
DEFAULT_CONFIG_PATH = SECRET_DIR / "object_storage.json"
DEFAULT_OSS_WRITE_TIMEOUT_SECONDS = 600.0


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _normalize_endpoint(value: str) -> str:
    cleaned = _clean(value).rstrip("/")
    if not cleaned:
        return ""
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"
    return cleaned.rstrip("/")


def _normalize_prefix(value: str) -> str:
    cleaned = _clean(value).replace("\\", "/").strip("/")
    if not cleaned:
        return ""
    normalized = posixpath.normpath(cleaned).strip("/")
    if normalized in {"", "."} or normalized.startswith("../") or normalized == "..":
        return ""
    return normalized


def _normalize_ttl(value: Any) -> int:
    try:
        ttl = int(value)
    except (TypeError, ValueError):
        ttl = 900
    return max(60, min(ttl, 604800))


def _oss_write_timeout_seconds() -> float:
    raw = os.environ.get("DCLAW_OSS_WRITE_TIMEOUT_SECONDS")
    try:
        timeout = float(raw) if raw is not None else DEFAULT_OSS_WRITE_TIMEOUT_SECONDS
    except (TypeError, ValueError):
        timeout = DEFAULT_OSS_WRITE_TIMEOUT_SECONDS
    return max(60.0, min(timeout, 3600.0))


def _is_aliyun_oss_endpoint(host: str) -> bool:
    normalized = host.lower().strip(".")
    return normalized == "aliyuncs.com" or normalized.endswith(".aliyuncs.com")


@dataclass
class ObjectStorageConfig:
    """Aliyun OSS storage settings."""

    enabled: bool = False
    endpoint: str = ""
    bucket: str = ""
    access_key_id: str = ""
    access_key_secret: str = ""
    prefix: str = "aigc/generated"
    signed_url_ttl_seconds: int = 900
    provider: str = "aliyun_oss"
    updated_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        self.endpoint = _normalize_endpoint(self.endpoint)
        self.bucket = _clean(self.bucket)
        self.access_key_id = _clean(self.access_key_id)
        self.access_key_secret = _clean(self.access_key_secret)
        self.prefix = _normalize_prefix(self.prefix)
        self.signed_url_ttl_seconds = _normalize_ttl(self.signed_url_ttl_seconds)
        self.provider = "aliyun_oss"

    @property
    def configured(self) -> bool:
        return bool(
            self.endpoint
            and self.bucket
            and self.access_key_id
            and self.access_key_secret
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "ObjectStorageConfig":
        raw = raw or {}
        return cls(
            enabled=bool(raw.get("enabled", False)),
            endpoint=str(raw.get("endpoint") or ""),
            bucket=str(raw.get("bucket") or ""),
            access_key_id=str(raw.get("access_key_id") or ""),
            access_key_secret=str(raw.get("access_key_secret") or ""),
            prefix=str(raw.get("prefix") or "aigc/generated"),
            signed_url_ttl_seconds=raw.get("signed_url_ttl_seconds", 900),
            updated_at=str(raw.get("updated_at") or _utc_now()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "endpoint": self.endpoint,
            "bucket": self.bucket,
            "access_key_id": self.access_key_id,
            "access_key_secret": self.access_key_secret,
            "prefix": self.prefix,
            "signed_url_ttl_seconds": self.signed_url_ttl_seconds,
            "updated_at": self.updated_at,
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "endpoint": self.endpoint,
            "bucket": self.bucket,
            "access_key_id": self.access_key_id,
            "access_key_secret": MASKED_SECRET if self.access_key_secret else "",
            "prefix": self.prefix,
            "signed_url_ttl_seconds": self.signed_url_ttl_seconds,
            "configured": bool(self.enabled and self.configured),
            "updated_at": self.updated_at,
        }


class ObjectStorageStore:
    """JSON-backed object storage configuration store."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or DEFAULT_CONFIG_PATH)

    def get_config(self) -> ObjectStorageConfig:
        if not self.path.is_file():
            return ObjectStorageConfig()
        try:
            raw = json.loads(self.path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = {}
        if isinstance(raw, dict) and "aliyun_oss" in raw:
            raw = raw.get("aliyun_oss") or {}
        return ObjectStorageConfig.from_dict(raw if isinstance(raw, dict) else {})

    def save_config(self, config: ObjectStorageConfig) -> ObjectStorageConfig:
        config.updated_at = _utc_now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
            "utf-8",
        )
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        return config

    def update_config(self, payload: dict[str, Any]) -> ObjectStorageConfig:
        existing = self.get_config()
        access_key_secret = payload.get("access_key_secret")
        if access_key_secret is None or access_key_secret == MASKED_SECRET:
            access_key_secret = existing.access_key_secret
        config = ObjectStorageConfig(
            enabled=bool(payload.get("enabled", False)),
            endpoint=str(payload.get("endpoint") or ""),
            bucket=str(payload.get("bucket") or ""),
            access_key_id=str(payload.get("access_key_id") or ""),
            access_key_secret=str(access_key_secret or ""),
            prefix=str(payload.get("prefix") or ""),
            signed_url_ttl_seconds=payload.get("signed_url_ttl_seconds", 900),
        )
        return self.save_config(config)


class AliyunOssClient:
    """Minimal Aliyun OSS REST client using V1 signatures."""

    def __init__(
        self,
        config: ObjectStorageConfig,
        *,
        http_client_factory: Callable[[], Any] | None = None,
        date_fn: Callable[[], str] | None = None,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self.config = config
        self._http_client_factory = http_client_factory or self._default_http_client
        self._date_fn = date_fn or (lambda: formatdate(usegmt=True))
        self._time_fn = time_fn or time.time

    def build_object_key(self, relative_path: str) -> str:
        cleaned = _clean(relative_path).replace("\\", "/").lstrip("/")
        normalized = posixpath.normpath(cleaned)
        if (
            not cleaned
            or normalized in {"", "."}
            or normalized.startswith("../")
            or normalized == ".."
        ):
            raise ValueError("Object key is outside the configured prefix.")
        if self.config.prefix:
            return f"{self.config.prefix}/{normalized}"
        return normalized

    async def upload(
        self,
        *,
        relative_path: str,
        content: bytes | str,
        mime_type: str,
    ) -> dict[str, Any]:
        self._ensure_configured()
        object_key = self.build_object_key(relative_path)
        body = content.encode("utf-8") if isinstance(content, str) else content
        content_type = mime_type or "application/octet-stream"
        date = self._date_fn()
        headers = {
            "Authorization": self._authorization(
                method="PUT",
                object_key=object_key,
                content_type=content_type,
                date_or_expires=date,
            ),
            "Content-Type": content_type,
            "Date": date,
        }
        async with self._http_client_factory() as client:
            response = await client.put(
                self.object_url(object_key),
                content=body,
                headers=headers,
            )
            response.raise_for_status()
        return {
            "provider": "aliyun_oss",
            "bucket": self.config.bucket,
            "endpoint": self.config.endpoint,
            "object_key": object_key,
            "size": len(body),
        }

    async def download(self, object_key: str) -> tuple[bytes, str]:
        self._ensure_configured()
        async with self._http_client_factory() as client:
            response = await client.get(self.signed_get_url(object_key))
            response.raise_for_status()
        return (
            response.content,
            response.headers.get("content-type", "application/octet-stream"),
        )

    def signed_get_url(self, object_key: str, ttl_seconds: int | None = None) -> str:
        self._ensure_configured()
        ttl = (
            self.config.signed_url_ttl_seconds
            if ttl_seconds is None
            else _normalize_ttl(ttl_seconds)
        )
        expires = int(self._time_fn()) + ttl
        signature = self._signature(
            method="GET",
            object_key=object_key,
            content_type="",
            date_or_expires=str(expires),
        )
        query = urlencode(
            {
                "OSSAccessKeyId": self.config.access_key_id,
                "Expires": str(expires),
                "Signature": signature,
            }
        )
        return f"{self.object_url(object_key)}?{query}"

    def signed_put_url(self, object_key: str, mime_type: str) -> str:
        self._ensure_configured()
        content_type = mime_type or "application/octet-stream"
        expires = int(self._time_fn()) + self.config.signed_url_ttl_seconds
        signature = self._signature(
            method="PUT",
            object_key=object_key,
            content_type=content_type,
            date_or_expires=str(expires),
        )
        query = urlencode(
            {
                "OSSAccessKeyId": self.config.access_key_id,
                "Expires": str(expires),
                "Signature": signature,
            }
        )
        return f"{self.object_url(object_key)}?{query}"

    def object_url(self, object_key: str) -> str:
        parsed = urlparse(self.config.endpoint)
        scheme = parsed.scheme or "https"
        host = parsed.netloc or parsed.path
        if _is_aliyun_oss_endpoint(host) and not host.startswith(f"{self.config.bucket}."):
            host = f"{self.config.bucket}.{host}"
        path = "/" + quote(object_key, safe="/")
        return urlunparse((scheme, host, path, "", "", ""))

    @staticmethod
    def _default_http_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(
                60.0,
                connect=15.0,
                write=_oss_write_timeout_seconds(),
            ),
            follow_redirects=True,
        )

    def _authorization(
        self,
        *,
        method: str,
        object_key: str,
        content_type: str,
        date_or_expires: str,
    ) -> str:
        return f"OSS {self.config.access_key_id}:{self._signature(method=method, object_key=object_key, content_type=content_type, date_or_expires=date_or_expires)}"

    def _signature(
        self,
        *,
        method: str,
        object_key: str,
        content_type: str,
        date_or_expires: str,
    ) -> str:
        string_to_sign = "\n".join(
            [
                method,
                "",
                content_type,
                date_or_expires,
                f"/{self.config.bucket}/{object_key}",
            ]
        )
        digest = hmac.new(
            self.config.access_key_secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        return base64.b64encode(digest).decode("ascii")

    def _ensure_configured(self) -> None:
        if not self.config.configured:
            raise RuntimeError("Aliyun OSS storage is not fully configured.")


def get_object_storage_client(
    *,
    require_enabled: bool = True,
    store: ObjectStorageStore | None = None,
) -> AliyunOssClient | None:
    config = (store or ObjectStorageStore()).get_config()
    if require_enabled and not config.enabled:
        return None
    if config.configured:
        return AliyunOssClient(config)
    if config.enabled:
        raise RuntimeError("Aliyun OSS storage is enabled but incomplete.")
    return None
