"""Provider-neutral outbound transport for sealed Super Agents."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from .credentials import CredentialBroker, CredentialError
from .session import SessionError, SessionSigner


CAPABILITY_ID = "agent.outbound/1"
MAX_REQUEST_BYTES = 1_048_576
MAX_RESPONSE_BYTES = 1_048_576
_CREDENTIAL_REF_PATTERN = re.compile(r"^cred_[0-9a-f]{32}$")
_CREDENTIAL_SLOT_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_SCOPE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$")
_SAFE_AGENT_HEADERS = {
    "accept",
    "content-type",
    "idempotency-key",
    "user-agent",
    "x-request-id",
}
_FORBIDDEN_INJECTED_HEADERS = {
    "accept",
    "authorization",
    "connection",
    "content-length",
    "content-type",
    "cookie",
    "host",
    "idempotency-key",
    "proxy-authenticate",
    "proxy-authorization",
    "set-cookie",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "user-agent",
    "x-request-id",
}


@dataclass
class AgentOutboundError(ValueError):
    reason: str

    @property
    def code(self) -> str:
        return f"AGENT_OUTBOUND.{self.reason}"

    def __str__(self) -> str:
        return self.code


def _public_hostname(hostname: str | None, *, resolve: bool = True) -> bool:
    if not hostname:
        return False
    lowered = hostname.rstrip(".").lower()
    if (
        lowered in {"localhost", "localhost.localdomain"}
        or lowered.endswith(
            (".local", ".localhost", ".test", ".example", ".invalid"),
        )
    ):
        return False
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        if "." not in lowered:
            return False
        if not resolve:
            return True
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(
                    lowered,
                    443,
                    type=socket.SOCK_STREAM,
                )
            }
        except (OSError, socket.gaierror):
            return False
        return bool(addresses) and all(
            ipaddress.ip_address(address).is_global for address in addresses
        )
    return address.is_global


def _validated_https_url(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or len(value) > 2048:
        raise AgentOutboundError("URL_NOT_ALLOWED")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise AgentOutboundError("URL_NOT_ALLOWED") from exc
    if (
        parsed.scheme != "https"
        or not _public_hostname(parsed.hostname)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise AgentOutboundError("URL_NOT_ALLOWED")
    path = parsed.path or "/"
    if (
        "%" in path
        or "\\" in path
        or "//" in path
        or any(part in {".", ".."} for part in path.split("/"))
    ):
        raise AgentOutboundError("URL_NOT_ALLOWED")
    hostname = str(parsed.hostname).rstrip(".").lower()
    host_literal = f"[{hostname}]" if ":" in hostname else hostname
    origin = f"https://{host_literal}"
    if port and port != 443:
        origin += f":{port}"
    return hostname, origin


def _validated_domain_pattern(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 253:
        raise AgentOutboundError("INVALID_CREDENTIAL_POLICY")
    pattern = value.rstrip(".").lower()
    base = pattern[2:] if pattern.startswith("*.") else pattern
    if "*" in base or not _public_hostname(base, resolve=False):
        raise AgentOutboundError("INVALID_CREDENTIAL_POLICY")
    return pattern


def _domain_allowed(hostname: str, patterns: list[str]) -> bool:
    return any(
        hostname == pattern
        or (
            pattern.startswith("*.")
            and hostname.endswith("." + pattern[2:])
            and hostname != pattern[2:]
        )
        for pattern in patterns
    )


def _json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AgentOutboundError("INVALID_REQUEST") from exc


def _safe_header_value(value: Any, *, maximum: int = 8192) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or "\r" in value
        or "\n" in value
    ):
        raise AgentOutboundError("INVALID_CREDENTIAL_POLICY")
    return value


class AgentOutboundManager:
    """Validate Agent requests and inject installation credentials at transport."""

    def __init__(
        self,
        credentials: CredentialBroker,
        signer: SessionSigner,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._credentials = credentials
        self._signer = signer
        self._transport = transport

    def bind_credential(
        self,
        *,
        tenant_id: str = "local",
        user_id: str,
        provider: str,
        authorization: dict[str, Any],
        scopes: list[str],
        agent_ids: list[str],
        installation_ids: list[str],
        release_ids: list[str] | None = None,
        credential_slot: str | None = None,
        allowed_domains: list[str],
        allowed_methods: list[str],
    ) -> str:
        if (
            not isinstance(provider, str)
            or not _PROVIDER_PATTERN.fullmatch(provider)
            or not isinstance(scopes, list)
            or not scopes
            or len(scopes) > 64
            or not all(
                isinstance(item, str) and _SCOPE_PATTERN.fullmatch(item)
                for item in scopes
            )
            or len(set(scopes)) != len(scopes)
            or not isinstance(agent_ids, list)
            or not agent_ids
            or len(agent_ids) > 64
            or not all(
                isinstance(item, str) and 1 <= len(item) <= 128
                for item in agent_ids
            )
            or len(set(agent_ids)) != len(agent_ids)
            or not isinstance(installation_ids, list)
            or not installation_ids
            or len(installation_ids) > 64
            or not all(
                isinstance(item, str) and 1 <= len(item) <= 128
                for item in installation_ids
            )
            or len(set(installation_ids)) != len(installation_ids)
            or (
                credential_slot is not None
                and (
                    not isinstance(credential_slot, str)
                    or not _CREDENTIAL_SLOT_PATTERN.fullmatch(credential_slot)
                    or not isinstance(release_ids, list)
                    or not release_ids
                    or len(release_ids) > 64
                    or not all(
                        isinstance(item, str) and 1 <= len(item) <= 128
                        for item in release_ids
                    )
                    or len(set(release_ids)) != len(release_ids)
                )
            )
            or not isinstance(allowed_domains, list)
            or not allowed_domains
            or len(allowed_domains) > 32
            or not all(isinstance(item, str) for item in allowed_domains)
            or len(set(allowed_domains)) != len(allowed_domains)
            or not isinstance(allowed_methods, list)
            or not all(isinstance(item, str) for item in allowed_methods)
            or len(set(allowed_methods)) != len(allowed_methods)
        ):
            raise AgentOutboundError("INVALID_CREDENTIAL_POLICY")
        domains = sorted({_validated_domain_pattern(item) for item in allowed_domains})
        methods = sorted({str(item).upper() for item in allowed_methods})
        if (
            not methods
            or len(methods) > 5
            or any(
                item not in {"GET", "POST", "PUT", "PATCH", "DELETE"}
                for item in methods
            )
        ):
            raise AgentOutboundError("INVALID_CREDENTIAL_POLICY")
        auth = self._validated_authorization(authorization)
        reference = self._credentials.bind(
            user_id=user_id,
            provider=provider,
            secret={
                "_dclaw_agent_outbound": 1,
                "authorization": auth,
                "allowed_domains": domains,
                "allowed_methods": methods,
            },
            scopes=scopes,
            agent_ids=agent_ids,
            installation_ids=installation_ids,
        )
        if credential_slot is not None:
            self._credentials.bind_slot(
                credential_ref=reference,
                tenant_id=tenant_id,
                user_id=user_id,
                agent_ids=agent_ids,
                release_ids=list(release_ids or []),
                installation_ids=installation_ids,
                scopes=scopes,
                credential_slot=credential_slot,
            )
        return reference

    @staticmethod
    def _validated_authorization(value: dict[str, Any]) -> dict[str, str]:
        if not isinstance(value, dict):
            raise AgentOutboundError("INVALID_CREDENTIAL_POLICY")
        auth_type = value.get("type")
        if auth_type == "none" and set(value) == {"type"}:
            return {"type": "none"}
        secret_value = _safe_header_value(value.get("value"))
        if auth_type == "bearer" and set(value) == {"type", "value"}:
            return {"type": "bearer", "value": secret_value}
        if auth_type == "header" and set(value) == {"type", "name", "value"}:
            name = value.get("name")
            if not isinstance(name, str) or not _HEADER_NAME_PATTERN.fullmatch(name):
                raise AgentOutboundError("INVALID_CREDENTIAL_POLICY")
            lowered = name.lower()
            if lowered in _FORBIDDEN_INJECTED_HEADERS:
                raise AgentOutboundError("INVALID_CREDENTIAL_POLICY")
            return {"type": "header", "name": lowered, "value": secret_value}
        raise AgentOutboundError("INVALID_CREDENTIAL_POLICY")

    def _identity(self, token: str) -> dict[str, Any]:
        try:
            identity = self._signer.verify(token)
        except SessionError as exc:
            raise AgentOutboundError("AUTHENTICATION_FAILED") from exc
        if CAPABILITY_ID not in set(identity.get("c") or []):
            raise AgentOutboundError("NOT_GRANTED")
        return identity

    async def request(
        self,
        *,
        dclaw_session_token: str,
        credential_scope: str,
        credential_ref: str | None = None,
        credential_slot: str | None = None,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        text_body: str | None = None,
        timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        identity = self._identity(dclaw_session_token)
        if (
            not isinstance(credential_scope, str)
            or not _SCOPE_PATTERN.fullmatch(credential_scope)
            or (credential_ref is None) == (credential_slot is None)
            or (
                credential_ref is not None
                and (
                    not isinstance(credential_ref, str)
                    or not _CREDENTIAL_REF_PATTERN.fullmatch(credential_ref)
                )
            )
            or (
                credential_slot is not None
                and (
                    not isinstance(credential_slot, str)
                    or not _CREDENTIAL_SLOT_PATTERN.fullmatch(credential_slot)
                )
            )
        ):
            raise AgentOutboundError("INVALID_REQUEST")
        normalized_method = str(method).upper()
        if normalized_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise AgentOutboundError("INVALID_REQUEST")
        if json_body is not None and text_body is not None:
            raise AgentOutboundError("INVALID_REQUEST")
        if (
            not isinstance(timeout_seconds, int)
            or isinstance(timeout_seconds, bool)
            or not 1 <= timeout_seconds <= 60
        ):
            raise AgentOutboundError("INVALID_REQUEST")
        hostname, _origin = _validated_https_url(url)
        body = (
            _json_bytes(json_body)
            if json_body is not None
            else (text_body or "").encode("utf-8")
        )
        if len(body) > MAX_REQUEST_BYTES:
            raise AgentOutboundError("REQUEST_TOO_LARGE")
        request_headers: dict[str, str] = {}
        if not isinstance(headers or {}, dict) or len(headers or {}) > 8:
            raise AgentOutboundError("INVALID_REQUEST")
        for name, value in (headers or {}).items():
            lowered = str(name).lower()
            if (
                lowered not in _SAFE_AGENT_HEADERS
                or lowered in request_headers
                or not isinstance(value, str)
                or len(value) > 2048
                or "\r" in value
                or "\n" in value
            ):
                raise AgentOutboundError("INVALID_REQUEST")
            request_headers[lowered] = value
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
            raise AgentOutboundError("CREDENTIAL_DENIED") from exc
        if envelope.get("_dclaw_agent_outbound") != 1:
            raise AgentOutboundError("CREDENTIAL_INCOMPATIBLE")
        domains = envelope.get("allowed_domains")
        methods = envelope.get("allowed_methods")
        if (
            not isinstance(domains, list)
            or not all(isinstance(item, str) for item in domains)
            or not isinstance(methods, list)
            or normalized_method not in methods
            or not _domain_allowed(hostname, domains)
        ):
            raise AgentOutboundError("POLICY_DENIED")
        authorization = self._validated_authorization(envelope.get("authorization"))
        if authorization["type"] == "bearer":
            injected_name = "authorization"
            injected_value = f"Bearer {authorization['value']}"
        elif authorization["type"] == "header":
            injected_name = authorization["name"]
            injected_value = authorization["value"]
        else:
            injected_name = None
            injected_value = None
        if injected_name is not None:
            if injected_name in request_headers:
                raise AgentOutboundError("INVALID_REQUEST")
            request_headers[injected_name] = str(injected_value)
        if json_body is not None:
            request_headers.setdefault("content-type", "application/json")
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                follow_redirects=False,
                timeout=float(timeout_seconds),
            ) as client:
                async with client.stream(
                    normalized_method,
                    url,
                    headers=request_headers,
                    content=body or None,
                ) as response:
                    if 300 <= response.status_code < 400:
                        raise AgentOutboundError("REDIRECT_REJECTED")
                    declared = response.headers.get("content-length")
                    if declared is not None:
                        try:
                            if int(declared) > MAX_RESPONSE_BYTES:
                                raise AgentOutboundError("RESPONSE_TOO_LARGE")
                        except ValueError as exc:
                            raise AgentOutboundError("UPSTREAM_FAILED") from exc
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            raise AgentOutboundError("RESPONSE_TOO_LARGE")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    status_code = response.status_code
                    content_type = response.headers.get("content-type", "")[:255]
        except AgentOutboundError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise AgentOutboundError("UPSTREAM_FAILED") from exc
        secret_bytes = authorization.get("value", "").encode("utf-8")
        if secret_bytes and secret_bytes in content:
            content = content.replace(secret_bytes, b"[REDACTED]")
        result: dict[str, Any] = {
            "status_code": status_code,
            "content_type": content_type,
        }
        if "json" in content_type.lower():
            try:
                result["body_json"] = json.loads(content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                result["body_text"] = content.decode("utf-8", errors="replace")
        else:
            result["body_text"] = content.decode("utf-8", errors="replace")
        return result
