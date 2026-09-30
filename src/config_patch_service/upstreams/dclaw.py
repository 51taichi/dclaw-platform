"""Read-only client for a DClaw configuration participant."""

from __future__ import annotations

import uuid
from urllib.parse import quote, urlsplit

import httpx
from pydantic import ValidationError

from ..models import DclawConfigurationContext, DclawSnapshotArchive
from . import UpstreamContractError, UpstreamNotFoundError, UpstreamUnavailableError


def _validated_base_url(value: str) -> str:
    parsed = urlsplit(str(value or ""))
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise UpstreamContractError("DCLAW_LOCATION_INVALID")
    return value.rstrip("/")


class DclawClient:
    def __init__(
        self,
        *,
        service_secret: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not service_secret:
            raise ValueError("DClaw service secret is required")
        self._service_secret = service_secret
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=2.0, read=20.0, write=20.0, pool=2.0),
            transport=transport,
            trust_env=False,
        )

    def _get(
        self,
        base_url: str,
        path: str,
        *,
        correlation_id: str | None,
    ) -> httpx.Response:
        authority = _validated_base_url(base_url)
        request_id = correlation_id or uuid.uuid4().hex
        try:
            response = self._client.get(
                f"{authority}/{path}",
                headers={
                    "X-DClaw-Config-Patch-Secret": self._service_secret,
                    "X-Correlation-ID": request_id,
                },
            )
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError("DCLAW_UPSTREAM_UNAVAILABLE") from exc
        if response.status_code == 404:
            raise UpstreamNotFoundError("DCLAW_AGENT_NOT_FOUND")
        if not response.is_success:
            raise UpstreamUnavailableError("DCLAW_UPSTREAM_UNAVAILABLE")
        return response

    def get_context(
        self,
        base_url: str,
        agent_id: str,
        *,
        correlation_id: str | None = None,
    ) -> DclawConfigurationContext:
        response = self._get(
            base_url,
            f"api/internal/config-patch/v1/agents/{quote(agent_id, safe='')}/context",
            correlation_id=correlation_id,
        )
        try:
            return DclawConfigurationContext.model_validate(response.json())
        except (ValueError, ValidationError, TypeError) as exc:
            raise UpstreamContractError("DCLAW_UPSTREAM_CONTRACT_INVALID") from exc

    def download_snapshot(
        self,
        base_url: str,
        agent_id: str,
        *,
        correlation_id: str | None = None,
    ) -> DclawSnapshotArchive:
        response = self._get(
            base_url,
            f"api/internal/config-patch/v1/agents/{quote(agent_id, safe='')}/snapshot",
            correlation_id=correlation_id,
        )
        try:
            if not response.content.startswith(b"PK"):
                raise ValueError("snapshot is not a ZIP archive")
            return DclawSnapshotArchive(
                archive=response.content,
                agent_id=response.headers["X-DClaw-Agent-Id"],
                profile_id=response.headers["X-DClaw-Agent-Profile-Id"],
                source_version=response.headers["X-DClaw-Source-Version"],
                agent_digest=response.headers["X-DClaw-Agent-Digest"],
                knowledge_digest=response.headers["X-DClaw-Knowledge-Digest"],
            )
        except (KeyError, ValueError, ValidationError) as exc:
            raise UpstreamContractError("DCLAW_SNAPSHOT_CONTRACT_INVALID") from exc
