"""Short-lived object-storage exchange for sealed Super Agents."""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .session import SessionError, SessionSigner
from .store import StateStore


CAPABILITY_ID = "resource.exchange/1"
RESOURCE_REF_PATTERN = re.compile(r"^res_[0-9a-f]{32}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MIME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.+-]{0,63}/[a-z0-9][a-z0-9.+-]{0,127}$")
PURPOSE_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
MAX_RESOURCE_BYTES = 1_073_741_824


@dataclass(frozen=True)
class TemporaryResourceError(ValueError):
    reason: str

    @property
    def code(self) -> str:
        return f"RESOURCE_EXCHANGE.{self.reason}"

    def __str__(self) -> str:
        return self.code


class TemporaryResourceBroker:
    def __init__(
        self,
        store: StateStore,
        signer: SessionSigner,
        storage_client: Any,
    ) -> None:
        self._store = store
        self._signer = signer
        self._storage = storage_client

    def _storage_required(self) -> Any:
        if self._storage is None:
            raise TemporaryResourceError("STORAGE_UNAVAILABLE")
        return self._storage

    def _identity(self, token: str, capability_id: str = CAPABILITY_ID) -> dict[str, Any]:
        try:
            identity = self._signer.verify(token)
        except SessionError as exc:
            raise TemporaryResourceError("AUTHENTICATION_FAILED") from exc
        if capability_id not in set(identity.get("c") or []):
            raise TemporaryResourceError("NOT_GRANTED")
        return identity

    @staticmethod
    def validate_create(
        mime_type: str,
        max_size_bytes: int,
        purpose: str,
        ttl_seconds: int,
    ) -> None:
        if (
            not isinstance(mime_type, str)
            or MIME_PATTERN.fullmatch(mime_type.lower()) is None
            or type(max_size_bytes) is not int
            or not 1 <= max_size_bytes <= MAX_RESOURCE_BYTES
            or not isinstance(purpose, str)
            or PURPOSE_PATTERN.fullmatch(purpose) is None
            or type(ttl_seconds) is not int
            or not 60 <= ttl_seconds <= 3600
        ):
            raise TemporaryResourceError("INVALID_REQUEST")

    @staticmethod
    def _scope(identity: dict[str, Any]) -> dict[str, str]:
        return {
            "tenant_id": str(identity["t"]),
            "user_id": str(identity["u"]),
            "session_id": str(identity["s"]),
            "agent_id": str(identity["a"]),
            "release_id": str(identity["r"]),
            "installation_id": str(identity["g"]),
            "invocation_id": str(identity["i"]),
        }

    def _record(self, identity: dict[str, Any], resource_ref: str) -> dict[str, Any]:
        if not isinstance(resource_ref, str) or RESOURCE_REF_PATTERN.fullmatch(resource_ref) is None:
            raise TemporaryResourceError("INVALID_REQUEST")
        record = self._store.get_temporary_resource(resource_ref)
        scope = self._scope(identity)
        if record is None or any(record[key] != value for key, value in scope.items()):
            raise TemporaryResourceError("NOT_FOUND")
        if record["revoked_at"] is not None or record["status"] == "revoked":
            raise TemporaryResourceError("REVOKED")
        if int(record["expires_at"]) <= int(time.time()):
            raise TemporaryResourceError("EXPIRED")
        return record

    def create_upload(
        self,
        *,
        dclaw_session_token: str,
        mime_type: str,
        max_size_bytes: int,
        purpose: str,
        ttl_seconds: int = 900,
    ) -> dict[str, Any]:
        identity = self._identity(dclaw_session_token)
        self.validate_create(mime_type, max_size_bytes, purpose, ttl_seconds)
        storage = self._storage_required()
        now = int(time.time())
        resource_ref = f"res_{uuid.uuid4().hex}"
        relative_path = (
            f"super-agent-support/temporary/{identity['t']}/{identity['u']}/"
            f"{identity['a']}/{resource_ref}"
        )
        object_key = storage.build_object_key(relative_path)
        self._store.put_temporary_resource(
            {
                "resource_ref": resource_ref,
                **self._scope(identity),
                "object_key": object_key,
                "mime_type": mime_type.lower(),
                "purpose": purpose,
                "max_size_bytes": max_size_bytes,
                "expires_at": now + ttl_seconds,
                "created_at": now,
            },
        )
        upload_url = storage.signed_put_url(object_key, mime_type.lower())
        host = urlsplit(upload_url).hostname
        if not host:
            raise TemporaryResourceError("STORAGE_UNAVAILABLE")
        return {
            "resource_ref": resource_ref,
            "status": "pending",
            "mime_type": mime_type.lower(),
            "max_size_bytes": max_size_bytes,
            "expires_at": now + ttl_seconds,
            "upload": {
                "url": upload_url,
                "method": "PUT",
                "headers": {"Content-Type": mime_type.lower()},
                "allowed_domains": [host],
                "max_size_bytes": max_size_bytes,
            },
        }

    def complete_upload(
        self,
        *,
        dclaw_session_token: str,
        resource_ref: str,
        size_bytes: int,
        sha256: str,
    ) -> dict[str, Any]:
        identity = self._identity(dclaw_session_token)
        record = self._record(identity, resource_ref)
        if (
            record["status"] != "pending"
            or type(size_bytes) is not int
            or not 1 <= size_bytes <= int(record["max_size_bytes"])
            or not isinstance(sha256, str)
            or SHA256_PATTERN.fullmatch(sha256) is None
        ):
            raise TemporaryResourceError("INVALID_REQUEST")
        if not self._store.complete_temporary_resource(
            resource_ref,
            size_bytes=size_bytes,
            sha256=sha256,
        ):
            raise TemporaryResourceError("STATE_CONFLICT")
        return {
            "resource_ref": resource_ref,
            "status": "ready",
            "mime_type": record["mime_type"],
            "size_bytes": size_bytes,
            "sha256": sha256,
            "expires_at": record["expires_at"],
        }

    def read(
        self,
        *,
        dclaw_session_token: str,
        resource_ref: str,
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        identity = self._identity(dclaw_session_token)
        record = self._record(identity, resource_ref)
        storage = self._storage_required()
        if record["status"] != "ready" or not 60 <= ttl_seconds <= 900:
            raise TemporaryResourceError("INVALID_REQUEST")
        remaining = int(record["expires_at"]) - int(time.time())
        effective_ttl = max(1, min(ttl_seconds, remaining))
        return {
            "resource_ref": resource_ref,
            "status": "ready",
            "read_url": storage.signed_get_url(
                record["object_key"],
                ttl_seconds=effective_ttl,
            ),
            "mime_type": record["mime_type"],
            "size_bytes": record["size_bytes"],
            "sha256": record["sha256"],
            "expires_at": record["expires_at"],
        }

    async def store_bytes(
        self,
        *,
        identity: dict[str, Any],
        content: bytes,
        mime_type: str,
        purpose: str,
        ttl_seconds: int = 900,
    ) -> dict[str, Any]:
        self.validate_create(mime_type, len(content), purpose, ttl_seconds)
        storage = self._storage_required()
        now = int(time.time())
        resource_ref = f"res_{uuid.uuid4().hex}"
        relative_path = (
            f"super-agent-support/temporary/{identity['t']}/{identity['u']}/"
            f"{identity['a']}/{resource_ref}"
        )
        result = await storage.upload(
            relative_path=relative_path,
            content=content,
            mime_type=mime_type,
        )
        digest = hashlib.sha256(content).hexdigest()
        self._store.put_temporary_resource(
            {
                "resource_ref": resource_ref,
                **self._scope(identity),
                "object_key": result["object_key"],
                "mime_type": mime_type,
                "purpose": purpose,
                "max_size_bytes": len(content),
                "expires_at": now + ttl_seconds,
                "created_at": now,
            },
        )
        self._store.complete_temporary_resource(
            resource_ref,
            size_bytes=len(content),
            sha256=digest,
        )
        return {
            "resource_ref": resource_ref,
            "status": "ready",
            "mime_type": mime_type,
            "size_bytes": len(content),
            "sha256": digest,
            "expires_at": now + ttl_seconds,
        }

    def revoke(
        self,
        *,
        dclaw_session_token: str,
        resource_ref: str,
    ) -> dict[str, Any]:
        identity = self._identity(dclaw_session_token)
        self._record(identity, resource_ref)
        if not self._store.revoke_temporary_resource(resource_ref):
            raise TemporaryResourceError("STATE_CONFLICT")
        return {"resource_ref": resource_ref, "status": "revoked"}
