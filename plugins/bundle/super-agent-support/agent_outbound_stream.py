"""Restricted streaming HTTPS and WebSocket transport for sealed Agents."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
import websockets

from .agent_outbound import (
    _CREDENTIAL_REF_PATTERN,
    _CREDENTIAL_SLOT_PATTERN,
    _SAFE_AGENT_HEADERS,
    _SCOPE_PATTERN,
    _domain_allowed,
    _public_hostname,
)
from .credentials import CredentialBroker, CredentialError
from .session import SessionError, SessionSigner
from .temporary_resources import TemporaryResourceBroker, TemporaryResourceError


CAPABILITY_ID = "agent.outbound.stream/1"
MAX_REQUEST_BYTES = 1_048_576
MAX_OUTPUT_BYTES = 33_554_432
_STREAM_HEADERS = _SAFE_AGENT_HEADERS | {"origin"}


def _json_pointer(document: Any, pointer: str) -> Any:
    if (
        not isinstance(pointer, str)
        or not 1 <= len(pointer) <= 512
        or not pointer.startswith("/")
    ):
        raise AgentOutboundStreamError("TRANSFORM_FAILED")
    current = document
    for encoded in pointer[1:].split("/"):
        index = 0
        token: list[str] = []
        while index < len(encoded):
            if encoded[index] != "~":
                token.append(encoded[index])
                index += 1
                continue
            if (
                index + 1 >= len(encoded)
                or encoded[index + 1] not in {"0", "1"}
            ):
                raise AgentOutboundStreamError("TRANSFORM_FAILED")
            token.append("~" if encoded[index + 1] == "0" else "/")
            index += 2
        key = "".join(token)
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and key.isdigit() and int(key) < len(current):
            current = current[int(key)]
        else:
            raise AgentOutboundStreamError("TRANSFORM_FAILED")
    return current


def _transform_https_response(
    content: bytes,
    content_type: str,
    response_transform: dict[str, Any] | None,
    max_output_bytes: int,
) -> bytes:
    if response_transform is None:
        return content
    if (
        not isinstance(response_transform, dict)
        or set(response_transform) != {"type", "json_pointer"}
        or response_transform.get("type") != "json_base64"
    ):
        raise AgentOutboundStreamError("INVALID_REQUEST")
    media_type = content_type.partition(";")[0].strip().lower()
    if media_type != "application/json" and not media_type.endswith("+json"):
        raise AgentOutboundStreamError("TRANSFORM_FAILED")
    try:
        document = json.loads(content.decode("utf-8"))
        encoded = _json_pointer(document, response_transform.get("json_pointer"))
        if not isinstance(encoded, str):
            raise AgentOutboundStreamError("TRANSFORM_FAILED")
        transformed = base64.b64decode(encoded, validate=True)
    except AgentOutboundStreamError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, binascii.Error) as exc:
        raise AgentOutboundStreamError("TRANSFORM_FAILED") from exc
    if len(transformed) > max_output_bytes:
        raise AgentOutboundStreamError("OUTPUT_TOO_LARGE")
    return transformed


@dataclass(frozen=True)
class AgentOutboundStreamError(ValueError):
    reason: str

    @property
    def code(self) -> str:
        return f"AGENT_OUTBOUND_STREAM.{self.reason}"

    def __str__(self) -> str:
        return self.code


def _validated_stream_url(value: str, protocol: str) -> tuple[str, str]:
    if not isinstance(value, str) or len(value) > 4096:
        raise AgentOutboundStreamError("URL_NOT_ALLOWED")
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise AgentOutboundStreamError("URL_NOT_ALLOWED") from exc
    expected = "wss" if protocol == "wss" else "https"
    if (
        parsed.scheme != expected
        or not _public_hostname(parsed.hostname)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise AgentOutboundStreamError("URL_NOT_ALLOWED")
    return str(parsed.hostname).rstrip(".").lower(), value


class AgentOutboundStreamManager:
    def __init__(
        self,
        credentials: CredentialBroker,
        signer: SessionSigner,
        resources: TemporaryResourceBroker,
        *,
        http_transport: httpx.AsyncBaseTransport | None = None,
        websocket_connect: Callable[..., Any] | None = None,
    ) -> None:
        self._credentials = credentials
        self._signer = signer
        self._resources = resources
        self._http_transport = http_transport
        self._websocket_connect = websocket_connect or websockets.connect

    def _identity(self, token: str) -> dict[str, Any]:
        try:
            identity = self._signer.verify(token)
        except SessionError as exc:
            raise AgentOutboundStreamError("AUTHENTICATION_FAILED") from exc
        if CAPABILITY_ID not in set(identity.get("c") or []):
            raise AgentOutboundStreamError("NOT_GRANTED")
        return identity

    def _policy(
        self,
        *,
        identity: dict[str, Any],
        credential_scope: str,
        credential_ref: str | None,
        credential_slot: str | None,
        hostname: str,
        method: str,
    ) -> dict[str, str]:
        if (
            not isinstance(credential_scope, str)
            or _SCOPE_PATTERN.fullmatch(credential_scope) is None
            or (credential_ref is None) == (credential_slot is None)
            or (
                credential_ref is not None
                and (
                    not isinstance(credential_ref, str)
                    or _CREDENTIAL_REF_PATTERN.fullmatch(credential_ref) is None
                )
            )
            or (
                credential_slot is not None
                and (
                    not isinstance(credential_slot, str)
                    or _CREDENTIAL_SLOT_PATTERN.fullmatch(credential_slot) is None
                )
            )
        ):
            raise AgentOutboundStreamError("INVALID_REQUEST")
        try:
            if credential_slot is not None:
                envelope = self._credentials.resolve_slot(
                    credential_slot,
                    tenant_id=identity["t"],
                    user_id=identity["u"],
                    agent_id=identity["a"],
                    release_id=identity["r"],
                    installation_id=identity["g"],
                    required_scope=credential_scope,
                )
            else:
                envelope = self._credentials.resolve(
                    str(credential_ref),
                    user_id=identity["u"],
                    agent_id=identity["a"],
                    installation_id=identity["g"],
                    required_scope=credential_scope,
                )
        except CredentialError as exc:
            raise AgentOutboundStreamError("CREDENTIAL_DENIED") from exc
        if envelope.get("_dclaw_agent_outbound") != 1:
            raise AgentOutboundStreamError("CREDENTIAL_INCOMPATIBLE")
        domains = envelope.get("allowed_domains")
        methods = envelope.get("allowed_methods")
        if (
            not isinstance(domains, list)
            or not isinstance(methods, list)
            or method not in methods
            or not _domain_allowed(hostname, domains)
        ):
            raise AgentOutboundStreamError("POLICY_DENIED")
        authorization = envelope.get("authorization")
        if authorization == {"type": "none"}:
            return {}
        if not isinstance(authorization, dict):
            raise AgentOutboundStreamError("CREDENTIAL_INCOMPATIBLE")
        if authorization.get("type") == "bearer" and isinstance(
            authorization.get("value"), str
        ):
            return {"authorization": f"Bearer {authorization['value']}"}
        if (
            authorization.get("type") == "header"
            and isinstance(authorization.get("name"), str)
            and isinstance(authorization.get("value"), str)
        ):
            return {authorization["name"].lower(): authorization["value"]}
        raise AgentOutboundStreamError("CREDENTIAL_INCOMPATIBLE")

    @staticmethod
    def _headers(value: dict[str, str] | None) -> dict[str, str]:
        if not isinstance(value or {}, dict) or len(value or {}) > 8:
            raise AgentOutboundStreamError("INVALID_REQUEST")
        result: dict[str, str] = {}
        for name, item in (value or {}).items():
            lowered = str(name).lower()
            if (
                lowered not in _STREAM_HEADERS
                or lowered in result
                or not isinstance(item, str)
                or len(item) > 2048
                or "\r" in item
                or "\n" in item
            ):
                raise AgentOutboundStreamError("INVALID_REQUEST")
            result[lowered] = item
        return result

    async def request(
        self,
        *,
        dclaw_session_token: str,
        protocol: str,
        url: str,
        credential_scope: str,
        output_mime_type: str,
        purpose: str,
        credential_ref: str | None = None,
        credential_slot: str | None = None,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        text_body: str | None = None,
        send_frames: list[dict[str, Any]] | None = None,
        completion_text: str | None = None,
        binary_filter_contains: str | None = None,
        binary_strip_through: str | None = None,
        response_transform: dict[str, Any] | None = None,
        timeout_seconds: int = 60,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
    ) -> dict[str, Any]:
        identity = self._identity(dclaw_session_token)
        if (
            protocol not in {"https", "wss"}
            or type(timeout_seconds) is not int
            or not 1 <= timeout_seconds <= 300
            or type(max_output_bytes) is not int
            or not 1 <= max_output_bytes <= MAX_OUTPUT_BYTES
        ):
            raise AgentOutboundStreamError("INVALID_REQUEST")
        try:
            self._resources.validate_create(
                output_mime_type,
                max_output_bytes,
                purpose,
                900,
            )
        except TemporaryResourceError as exc:
            raise AgentOutboundStreamError(exc.reason) from exc
        normalized_method = str(method).upper()
        if protocol == "wss" and normalized_method != "GET":
            raise AgentOutboundStreamError("INVALID_REQUEST")
        if protocol != "https" and response_transform is not None:
            raise AgentOutboundStreamError("INVALID_REQUEST")
        if normalized_method not in {"GET", "POST", "PUT", "PATCH"}:
            raise AgentOutboundStreamError("INVALID_REQUEST")
        hostname, target = _validated_stream_url(url, protocol)
        request_headers = self._headers(headers)
        injected = self._policy(
            identity=identity,
            credential_scope=credential_scope,
            credential_ref=credential_ref,
            credential_slot=credential_slot,
            hostname=hostname,
            method=normalized_method,
        )
        if set(request_headers) & set(injected):
            raise AgentOutboundStreamError("INVALID_REQUEST")
        request_headers.update(injected)
        try:
            if protocol == "https":
                content = await self._https(
                    method=normalized_method,
                    url=target,
                    headers=request_headers,
                    json_body=json_body,
                    text_body=text_body,
                    response_transform=response_transform,
                    timeout_seconds=timeout_seconds,
                    max_output_bytes=max_output_bytes,
                )
            else:
                content = await self._wss(
                    url=target,
                    headers=request_headers,
                    send_frames=send_frames,
                    completion_text=completion_text,
                    binary_filter_contains=binary_filter_contains,
                    binary_strip_through=binary_strip_through,
                    timeout_seconds=timeout_seconds,
                    max_output_bytes=max_output_bytes,
                )
            if not content:
                raise AgentOutboundStreamError("EMPTY_OUTPUT")
            return await self._resources.store_bytes(
                identity=identity,
                content=content,
                mime_type=output_mime_type,
                purpose=purpose,
            )
        except AgentOutboundStreamError:
            raise
        except TemporaryResourceError as exc:
            raise AgentOutboundStreamError(exc.reason) from exc
        except (OSError, httpx.HTTPError, websockets.WebSocketException) as exc:
            raise AgentOutboundStreamError("UPSTREAM_FAILED") from exc

    async def _https(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: Any | None,
        text_body: str | None,
        response_transform: dict[str, Any] | None,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> bytes:
        if json_body is not None and text_body is not None:
            raise AgentOutboundStreamError("INVALID_REQUEST")
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode()
            headers.setdefault("content-type", "application/json")
        else:
            body = (text_body or "").encode()
        if len(body) > MAX_REQUEST_BYTES:
            raise AgentOutboundStreamError("REQUEST_TOO_LARGE")
        chunks: list[bytes] = []
        size = 0
        response_content_type = ""
        async with httpx.AsyncClient(
            transport=self._http_transport,
            follow_redirects=False,
            timeout=float(timeout_seconds),
        ) as client:
            async with client.stream(
                method,
                url,
                headers=headers,
                content=body or None,
            ) as response:
                if 300 <= response.status_code < 400:
                    raise AgentOutboundStreamError("REDIRECT_REJECTED")
                if response.status_code >= 400:
                    raise AgentOutboundStreamError("UPSTREAM_REJECTED")
                response_content_type = response.headers.get("content-type", "")
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_output_bytes:
                        raise AgentOutboundStreamError("OUTPUT_TOO_LARGE")
                    chunks.append(chunk)
        return _transform_https_response(
            b"".join(chunks),
            response_content_type,
            response_transform,
            max_output_bytes,
        )

    async def _wss(
        self,
        *,
        url: str,
        headers: dict[str, str],
        send_frames: list[dict[str, Any]] | None,
        completion_text: str | None,
        binary_filter_contains: str | None,
        binary_strip_through: str | None,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> bytes:
        frames = send_frames or []
        if not frames or len(frames) > 16:
            raise AgentOutboundStreamError("INVALID_REQUEST")
        total_request = 0
        encoded_frames: list[str | bytes] = []
        for frame in frames:
            if not isinstance(frame, dict) or set(frame) != {"kind", "data"}:
                raise AgentOutboundStreamError("INVALID_REQUEST")
            kind, data = frame["kind"], frame["data"]
            try:
                if kind == "text" and isinstance(data, str):
                    encoded: str | bytes = data
                elif kind == "json":
                    encoded = json.dumps(data, separators=(",", ":"))
                elif kind == "binary_base64" and isinstance(data, str):
                    encoded = base64.b64decode(data, validate=True)
                else:
                    raise AgentOutboundStreamError("INVALID_REQUEST")
            except (ValueError, TypeError) as exc:
                raise AgentOutboundStreamError("INVALID_REQUEST") from exc
            total_request += len(encoded.encode() if isinstance(encoded, str) else encoded)
            encoded_frames.append(encoded)
        if total_request > MAX_REQUEST_BYTES:
            raise AgentOutboundStreamError("REQUEST_TOO_LARGE")
        if any(
            value is not None and (not isinstance(value, str) or len(value) > 256)
            for value in (completion_text, binary_filter_contains, binary_strip_through)
        ):
            raise AgentOutboundStreamError("INVALID_REQUEST")
        connector = self._websocket_connect(
            url,
            additional_headers=headers,
            open_timeout=min(timeout_seconds, 30),
            proxy=None,
            max_size=min(max_output_bytes, 4_194_304),
        )
        if hasattr(connector, "process_redirect"):
            connector.process_redirect = lambda exc: exc
        output: list[bytes] = []
        size = 0
        async def exchange() -> None:
            nonlocal size
            async with connector as websocket:
                for frame in encoded_frames:
                    await websocket.send(frame)
                async for message in websocket:
                    if isinstance(message, str):
                        if completion_text is not None and completion_text in message:
                            break
                        continue
                    chunk = bytes(message)
                    if binary_filter_contains is not None and binary_filter_contains.encode() not in chunk:
                        continue
                    if binary_strip_through is not None:
                        delimiter = binary_strip_through.encode()
                        position = chunk.find(delimiter)
                        if position < 0:
                            continue
                        chunk = chunk[position + len(delimiter) :]
                    size += len(chunk)
                    if size > max_output_bytes:
                        raise AgentOutboundStreamError("OUTPUT_TOO_LARGE")
                    output.append(chunk)
        try:
            await asyncio.wait_for(exchange(), timeout=float(timeout_seconds))
        except asyncio.TimeoutError as exc:
            raise AgentOutboundStreamError("UPSTREAM_TIMEOUT") from exc
        if not output:
            raise AgentOutboundStreamError("EMPTY_OUTPUT")
        return b"".join(output)
