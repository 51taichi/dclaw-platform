"""Generic JSON-lines contract for trusted sealed package entrypoints."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = "1"
MAX_MESSAGE_BYTES = 1024 * 1024
MAX_JSON_DEPTH = 32
HostCapability = Literal["agent.execute"]


class StrictMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReleaseIdentity(StrictMessage):
    release_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=128)
    content_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class SessionIdentity(StrictMessage):
    conversation_id: str = Field(min_length=1, max_length=512)
    user_id: str = Field(min_length=1, max_length=256)
    channel: str = Field(min_length=1, max_length=256)


class RuntimeInput(StrictMessage):
    role: Literal["user"] = "user"
    content: str = Field(max_length=200_000)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class RuntimeOptions(StrictMessage):
    diagnostics_authorized: bool = False
    capabilities: list[HostCapability] = Field(default_factory=list)


class RuntimeInvoke(StrictMessage):
    type: Literal["runtime.invoke"]
    protocol_version: Literal["1"]
    invocation_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    release: ReleaseIdentity
    session: SessionIdentity
    input: RuntimeInput
    metadata: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    runtime: RuntimeOptions


class RuntimeHandshake(StrictMessage):
    type: Literal["runtime.handshake"]
    protocol_version: Literal["1"]
    invocation_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)


class RuntimeReady(StrictMessage):
    type: Literal["runtime.ready"]
    protocol_version: Literal["1"]
    invocation_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    adapter: Literal["sealed_entrypoint"]
    contract_version: Literal["1"]


class HostCall(StrictMessage):
    type: Literal["host.call"]
    protocol_version: Literal["1"]
    invocation_id: str = Field(min_length=1, max_length=128)
    call_id: str = Field(min_length=1, max_length=128)
    capability: HostCapability
    arguments: dict[str, Any] = Field(default_factory=dict)


class HostResult(StrictMessage):
    type: Literal["host.result"]
    protocol_version: Literal["1"]
    invocation_id: str = Field(min_length=1, max_length=128)
    call_id: str = Field(min_length=1, max_length=128)
    ok: bool
    result: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = Field(default=None, max_length=128)


class RuntimeFinal(StrictMessage):
    type: Literal["runtime.final"]
    protocol_version: Literal["1"]
    invocation_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    reply: str = Field(min_length=1, max_length=500_000)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: dict[str, Any] | None = None


def _json_depth(value: Any, depth: int = 0) -> int:
    if depth > MAX_JSON_DEPTH:
        return depth
    if isinstance(value, dict):
        return max(
            (_json_depth(item, depth + 1) for item in value.values()),
            default=depth,
        )
    if isinstance(value, list):
        return max(
            (_json_depth(item, depth + 1) for item in value),
            default=depth,
        )
    return depth


def validate_protocol_message(encoded: bytes) -> dict[str, Any]:
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ValueError("sealed entrypoint message is too large")
    value = json.loads(encoded)
    if not isinstance(value, dict):
        raise ValueError("sealed entrypoint message must be an object")
    if _json_depth(value) > MAX_JSON_DEPTH:
        raise ValueError("sealed entrypoint message is too deeply nested")
    return value

