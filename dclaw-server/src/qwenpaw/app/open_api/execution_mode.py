"""Server-local capability marker for isolated Agent OpenAPI requests."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any

_CAPABILITY_KEY = "_isolated_agent_open_api_capability"
_CAPABILITY_SECRET = secrets.token_bytes(32)


def _capability_digest(meta: dict[str, Any]) -> str:
    bound_fields = {
        key: str(meta.get(key) or "")
        for key in (
            "session_id",
            "publication_id",
            "target_type",
            "target_id",
            "execution_mode",
            "open_invocation_id",
        )
    }
    payload = json.dumps(
        bound_fields,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hmac.new(_CAPABILITY_SECRET, payload, hashlib.sha256).hexdigest()


def bind_isolated_agent_open_api(meta: dict[str, Any]) -> None:
    """Add a JSON-safe capability signed by this server process."""
    meta[_CAPABILITY_KEY] = _capability_digest(meta)


def is_isolated_agent_open_api(meta: object) -> bool:
    """Return whether metadata carries a valid server-local capability."""
    if not isinstance(meta, dict):
        return False
    presented = meta.get(_CAPABILITY_KEY)
    if not isinstance(presented, str):
        return False
    return hmac.compare_digest(presented, _capability_digest(meta))
