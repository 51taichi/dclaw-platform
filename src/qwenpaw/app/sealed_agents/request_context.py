"""Strict separation of trusted runtime identity and caller metadata."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_METADATA_BYTES = 64 * 1024
MAX_METADATA_DEPTH = 16
MAX_METADATA_KEYS = 256


class SealedRequestMetadataError(ValueError):
    pass


def normalize_untrusted_metadata(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SealedRequestMetadataError("request metadata must be an object")
    key_count = 0

    def normalize(item: object, depth: int) -> Any:
        nonlocal key_count
        if depth > MAX_METADATA_DEPTH:
            raise SealedRequestMetadataError("request metadata is too deeply nested")
        if item is None or isinstance(item, (str, bool, int, float)):
            return item
        if isinstance(item, list):
            return [normalize(child, depth + 1) for child in item]
        if isinstance(item, dict):
            result: dict[str, Any] = {}
            for key, child in item.items():
                if not isinstance(key, str):
                    raise SealedRequestMetadataError("request metadata keys must be strings")
                key_count += 1
                if key_count > MAX_METADATA_KEYS:
                    raise SealedRequestMetadataError("request metadata has too many keys")
                result[key] = normalize(child, depth + 1)
            return result
        raise SealedRequestMetadataError("request metadata contains a non-JSON value")

    normalized = normalize(value, 0)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    if len(encoded) > MAX_METADATA_BYTES:
        raise SealedRequestMetadataError("request metadata is too large")
    return copy.deepcopy(normalized)


@dataclass(frozen=True)
class SealedAdapterRequest:
    messages: tuple[Any, ...]
    trusted_context: dict[str, Any]
    metadata: dict[str, Any]
    session_root: Path | None = None
    diagnostics_authorized: bool = False
