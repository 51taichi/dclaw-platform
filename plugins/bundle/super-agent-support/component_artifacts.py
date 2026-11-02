"""Direct object-storage uploads for plugin-owned public Components."""

from __future__ import annotations

import base64
import re
import time
import uuid
from typing import Any, Callable
from urllib.parse import quote, urlsplit

import httpx

from .store import StateStore


ID = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
HEX_32 = re.compile(r"^[0-9a-f]{32}$")
UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_BYTES = 2_147_483_648


class ComponentArtifactError(ValueError):
    pass


class ComponentArtifactUnavailable(ComponentArtifactError):
    pass


class ComponentArtifactManager:
    def __init__(
        self, store: StateStore, storage: Any,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
        public_base_url: str | None = None,
    ) -> None:
        self._store = store
        self._storage = storage
        self._http_client_factory = http_client_factory or (
            lambda: httpx.AsyncClient(timeout=30, follow_redirects=False)
        )
        if public_base_url:
            parsed = urlsplit(public_base_url)
            if (
                parsed.scheme != "https" or not parsed.netloc or parsed.username
                or parsed.query or parsed.fragment
            ):
                raise ComponentArtifactError("public Component CDN base URL is invalid")
        self._public_base_url = public_base_url.rstrip("/") if public_base_url else None

    def _storage_required(self) -> Any:
        if self._storage is None:
            raise ComponentArtifactUnavailable("object storage is unavailable")
        return self._storage

    def create(
        self, *, component_id: str, platform: str,
        component_version: str, size_bytes: int, sha256: str,
        md5: str, created_by: str,
    ) -> dict[str, Any]:
        if (
            not isinstance(component_id, str) or not ID.fullmatch(component_id)
            or platform not in {"windows-x64", "windows-arm64", "macos-arm64", "macos-x64"}
            or not isinstance(component_version, str)
            or not VERSION.fullmatch(component_version)
            or type(size_bytes) is not int or not 1 <= size_bytes <= MAX_BYTES
            or not isinstance(sha256, str) or not HEX_64.fullmatch(sha256)
            or not isinstance(md5, str) or not HEX_32.fullmatch(md5)
        ):
            raise ComponentArtifactError("invalid component artifact upload request")
        storage = self._storage_required()
        upload_id = uuid.uuid4().hex
        object_key = storage.build_object_key(
            f"super-agent-support/components/{component_id}/{platform}/"
            f"{component_version}/{upload_id}.zip",
        )
        artifact_url = (
            self._public_base_url + "/" + quote(object_key, safe="/")
            if self._public_base_url else storage.object_url(object_key)
        )
        upload_url = storage.signed_put_url(object_key, "application/zip")
        if any(
            urlsplit(url).scheme != "https" or not urlsplit(url).netloc
            for url in (artifact_url, upload_url)
        ):
            raise ComponentArtifactError("component storage must use HTTPS")
        expires_at = int(time.time()) + min(
            int(storage.config.signed_url_ttl_seconds), 900,
        )
        self._store.create_public_component_upload({
            "upload_id": upload_id,
            "component_id": component_id,
            "platform": platform,
            "component_version": component_version,
            "object_key": object_key,
            "artifact_url": artifact_url,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "md5": md5,
            "created_by": created_by,
            "expires_at": expires_at,
        })
        return {
            "upload_id": upload_id,
            "artifact_url": artifact_url,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "expires_at": expires_at,
            "upload": {
                "method": "PUT",
                "url": upload_url,
                "headers": {
                    "Content-Type": "application/zip",
                    "Content-MD5": base64.b64encode(
                        bytes.fromhex(md5),
                    ).decode("ascii"),
                },
            },
        }

    async def complete(self, upload_id: str, *, actor: str) -> dict[str, Any]:
        if not UPLOAD_ID.fullmatch(upload_id):
            raise ComponentArtifactError("invalid upload ID")
        record = self._store.get_public_component_upload(upload_id)
        if record is None or record["created_by"] != actor:
            raise ComponentArtifactError("upload not found")
        if record["completed_at"] is not None:
            return self._receipt(record)
        if record["expires_at"] <= int(time.time()):
            raise ComponentArtifactError("upload expired")
        storage = self._storage_required()
        signed_url = storage.signed_get_url(record["object_key"], ttl_seconds=60)
        # Both reads are bounded to one byte: integrity at the origin, then
        # unauthenticated reachability through the URL the Runner will use.
        try:
            async with self._http_client_factory() as client:
                for target_url in (signed_url, record["artifact_url"]):
                    async with client.stream(
                        "GET", target_url, headers={"Range": "bytes=0-0"},
                    ) as response:
                        if response.status_code != 206:
                            raise ComponentArtifactError(
                                "component artifact is not range-readable",
                            )
                        content_range = response.headers.get("content-range", "")
                        etag = response.headers.get("etag", "").strip('"').lower()
                        if (
                            content_range != f"bytes 0-0/{record['size_bytes']}"
                            or etag != record["md5"]
                        ):
                            raise ComponentArtifactError(
                                "uploaded object size or MD5 does not match",
                            )
        except httpx.HTTPError as exc:
            raise ComponentArtifactUnavailable("storage verification failed") from exc
        if not self._store.complete_public_component_upload(upload_id):
            raise ComponentArtifactError("upload completion conflict")
        return self._receipt(self._store.get_public_component_upload(upload_id))

    @staticmethod
    def _receipt(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "upload_id": record["upload_id"],
            "status": "verified",
            "artifact_url": record["artifact_url"],
            "sha256": record["sha256"],
            "size_bytes": record["size_bytes"],
        }

    def require_verified_descriptor(self, descriptor: dict[str, Any]) -> str | None:
        artifact = descriptor.get("artifact")
        if not isinstance(artifact, dict):
            return None
        url = artifact.get("url")
        if not isinstance(url, str):
            return None
        storage = self._storage
        if storage is None:
            return None
        prefix_key = storage.build_object_key(
            "super-agent-support/components/",
        )
        prefix = (
            self._public_base_url + "/" + quote(prefix_key, safe="/")
            if self._public_base_url else storage.object_url(prefix_key)
        ).rstrip("/") + "/"
        if not url.startswith(prefix):
            return None
        record = self._store.get_public_component_upload_by_url(url)
        if record is None or record["completed_at"] is None:
            raise ComponentArtifactError("managed component artifact is not verified")
        if any((
            record["component_id"] != descriptor.get("component_id"),
            record["platform"] != descriptor.get("platform"),
            record["component_version"] != descriptor.get("component_version"),
            record["sha256"] != artifact.get("sha256"),
            record["size_bytes"] != artifact.get("size_bytes"),
        )):
            raise ComponentArtifactError("managed artifact does not match descriptor")
        return record["upload_id"]
