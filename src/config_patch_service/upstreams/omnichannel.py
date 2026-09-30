"""Read-only client for the AI customer-service configuration participant."""

from __future__ import annotations

import uuid
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from ..models import OmnichannelBotSnapshot, OmnichannelBotSummary
from . import UpstreamContractError, UpstreamNotFoundError, UpstreamUnavailableError


class OmnichannelClient:
    def __init__(
        self,
        *,
        base_url: str,
        service_secret: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url or not service_secret:
            raise ValueError("omnichannel base URL and service secret are required")
        self._base_url = base_url.rstrip("/") + "/"
        self._service_secret = service_secret
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=httpx.Timeout(connect=2.0, read=10.0, write=10.0, pool=2.0),
            transport=transport,
            trust_env=False,
        )

    def _get(self, path: str, *, correlation_id: str | None) -> httpx.Response:
        request_id = correlation_id or uuid.uuid4().hex
        try:
            response = self._client.get(
                path,
                headers={
                    "X-Omnichannel-Config-Patch-Secret": self._service_secret,
                    "X-Correlation-ID": request_id,
                },
            )
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError("OMNICHANNEL_UPSTREAM_UNAVAILABLE") from exc
        if response.status_code == 404:
            raise UpstreamNotFoundError("CONFIG_PATCH_BOT_NOT_FOUND")
        if not response.is_success:
            raise UpstreamUnavailableError("OMNICHANNEL_UPSTREAM_UNAVAILABLE")
        return response

    def list_bots(
        self,
        *,
        correlation_id: str | None = None,
    ) -> list[OmnichannelBotSummary]:
        response = self._get(
            "internal/config-patch/v1/bots",
            correlation_id=correlation_id,
        )
        try:
            payload = response.json()
            if (
                not isinstance(payload, dict)
                or payload.get("ok") is not True
                or not isinstance(payload.get("bots"), list)
            ):
                raise ValueError("invalid list envelope")
            return [OmnichannelBotSummary.model_validate(item) for item in payload["bots"]]
        except (ValueError, ValidationError, TypeError) as exc:
            raise UpstreamContractError("OMNICHANNEL_UPSTREAM_CONTRACT_INVALID") from exc

    def get_bot_snapshot(
        self,
        bot_id: str,
        *,
        correlation_id: str | None = None,
    ) -> OmnichannelBotSnapshot:
        response = self._get(
            f"internal/config-patch/v1/bots/{quote(bot_id, safe='')}/snapshot",
            correlation_id=correlation_id,
        )
        try:
            payload = response.json()
            if (
                not isinstance(payload, dict)
                or payload.get("ok") is not True
                or not isinstance(payload.get("snapshot"), dict)
            ):
                raise ValueError("invalid snapshot envelope")
            return OmnichannelBotSnapshot.model_validate(payload["snapshot"])
        except (ValueError, ValidationError, TypeError) as exc:
            raise UpstreamContractError("OMNICHANNEL_UPSTREAM_CONTRACT_INVALID") from exc
