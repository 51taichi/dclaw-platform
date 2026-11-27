"""Describe native request transport, never model observations or review PASS.

Only the trusted candidate executor calls this after a successful native model
request. URLs and media bytes are hashed, not copied into the receipt.
"""
from __future__ import annotations

from collections import Counter
import base64
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

MEDIA_TYPES = frozenset({"image", "video", "audio"})


def _media_block_parts(
    block: Any,
) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    """Return kind, source and a stable serializable block shape."""
    if isinstance(block, dict):
        kind = block.get("type")
        source = block.get("source")
        if kind in MEDIA_TYPES and isinstance(source, dict):
            return kind, source, block
        return None
    if getattr(block, "type", None) != "data":
        return None
    source_obj = getattr(block, "source", None)
    media_type = str(getattr(source_obj, "media_type", "") or "")
    kind = media_type.partition("/")[0]
    if kind not in MEDIA_TYPES or source_obj is None:
        return None
    source = source_obj.model_dump(mode="json")
    stable = {
        "type": kind,
        "source": source,
        "name": getattr(block, "name", None),
    }
    return kind, source, stable


def media_input_manifest(messages: list[Any]) -> list[dict[str, Any]]:
    result = []
    for message_index, message in enumerate(messages):
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            continue
        for block_index, block in enumerate(content):
            parts = _media_block_parts(block)
            if parts is None:
                continue
            kind, _source, stable = parts
            digest = hashlib.sha256(
                json.dumps(
                    stable,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode(),
            ).hexdigest()
            result.append(
                {
                    "message_index": message_index,
                    "block_index": block_index,
                    "kind": kind,
                    "block_digest": "sha256:" + digest,
                },
            )
    return result


def _identity(value: Any, *, local: bool = False) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("data:"):
        header, _, payload = value.partition(",")
        if not header.endswith(";base64"):
            return None
        try:
            return (
                "bytes:"
                + hashlib.sha256(
                    base64.b64decode(payload, validate=True),
                ).hexdigest()
            )
        except (ValueError, TypeError):
            return None
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return "url:" + hashlib.sha256(value.encode()).hexdigest()
    if local and parsed.scheme in {"", "file"}:
        try:
            path = Path(
                unquote(parsed.path) if parsed.scheme == "file" else value,
            )
            return "bytes:" + hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError):
            return None
    return None


def _source_identity(source: Any, *, local: bool = False) -> str | None:
    if not isinstance(source, dict):
        return None
    if source.get("type") == "base64" and isinstance(source.get("data"), str):
        return _identity(
            "data:application/octet-stream;base64," + source["data"],
        )
    return _identity(source.get("url"), local=local)


def media_input_identities(
    messages: list[Any],
) -> list[tuple[str, str | None]]:
    """Private pre-format snapshot, including local bytes before any mutation.

    Never publish source URLs/bytes. Missing/unrecognized inputs stay unbound.
    """
    identities: list[tuple[str, str | None]] = []
    for message in messages:
        if not isinstance(getattr(message, "content", None), list):
            continue
        for block in message.content:
            parts = _media_block_parts(block)
            if parts is None:
                continue
            kind, source, _stable = parts
            identities.append((kind, _source_identity(source, local=True)))
    return identities


def _native_counts(prompt: Any) -> Counter:
    counts: Counter = Counter()
    # Traverse only formatter message/part containers, never text or arbitrary
    # tool arguments that happen to contain a media-shaped dictionary.
    if isinstance(prompt, list):
        for message in prompt:
            if hasattr(message, "model_dump"):
                message = message.model_dump(exclude_none=True)
            elif not isinstance(message, dict) and isinstance(
                getattr(message, "content", None),
                list,
            ):
                # AgentScope calls the selected chat model with native Msg
                # objects.  This is the model transport boundary for that
                # adapter, before it encodes local files for the provider.
                message = {"content": message.content}
            if not isinstance(message, dict):
                continue
            blocks = message.get("content", message.get("parts", []))
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                typ = block.get("type")
                kind = None
                identity = None
                if typ in {"image_url", "video_url"}:
                    value = block.get(typ)
                    if isinstance(value, dict):
                        value = value.get("url")
                    if isinstance(value, str) and value:
                        kind = typ.removesuffix("_url")
                        identity = _identity(value, local=True)
                elif typ == "input_audio":
                    value = block.get("input_audio")
                    if isinstance(value, dict) and value.get("data"):
                        kind = "audio"
                        identity = _identity(
                            "data:audio/base64;base64," + value["data"],
                        )
                elif typ == "data":
                    source = block.get("source")
                    if isinstance(source, dict):
                        kind = str(source.get("media_type", "")).partition(
                            "/",
                        )[0]
                        identity = _source_identity(source, local=True)
                elif typ in MEDIA_TYPES:
                    source = block.get("source")
                    if isinstance(source, dict) and (
                        source.get("data") or source.get("url")
                    ):
                        kind = (
                            str(source.get("media_type", "")).partition("/")[0]
                            or typ
                        )
                        identity = _source_identity(source, local=True)
                    else:
                        # Some provider adapters keep the media type and put
                        # the encoded value directly under `image`, `video`,
                        # or `audio` instead of using an OpenAI-style source.
                        value = block.get(typ, block.get(f"{typ}_url"))
                        if isinstance(value, dict):
                            value = value.get("url")
                        if isinstance(value, str) and value:
                            kind = typ
                            identity = _identity(value, local=True)
                else:
                    # DashScope emits provider-native blocks such as
                    # {"image": "data:image/jpeg;base64,..."} without a
                    # separate `type` field.
                    for media_kind in MEDIA_TYPES:
                        value = block.get(media_kind)
                        if isinstance(value, str) and value:
                            kind = media_kind
                            identity = _identity(value, local=True)
                            break
                    if kind is None:
                        # Gemini formatter emits native parts.
                        value = block.get(
                            "inline_data",
                            block.get("file_data"),
                        )
                        if isinstance(value, dict) and (
                            value.get("data") or value.get("file_uri")
                        ):
                            kind = str(value.get("mime_type", "")).partition(
                                "/",
                            )[0]
                            identity = (
                                _identity(
                                    "data:application/octet-stream;base64,"
                                    + value["data"],
                                )
                                if isinstance(value.get("data"), str)
                                else _identity(value.get("file_uri"))
                            )
                if kind in MEDIA_TYPES and identity is not None:
                    counts[kind, identity] += 1
    return counts


def build_media_delivery(
    manifest: list[dict[str, Any]],
    prompt: Any,
    model_response_id: str,
    *,
    input_identities: list[tuple[str, str | None]] | None = None,
) -> dict[str, Any]:
    if not manifest:
        return {}
    expected = Counter(input_identities or [])
    kinds = {item["kind"] for item in manifest}
    native = _native_counts(prompt)
    delivered = sorted(
        kind
        for kind in kinds
        if sum(
            count
            for (item_kind, _), count in expected.items()
            if item_kind == kind
        )
        == sum(item["kind"] == kind for item in manifest)
        and all(
            identity is not None and native[item_kind, identity] >= count
            for (item_kind, identity), count in expected.items()
            if item_kind == kind
        )
    )
    digest = hashlib.sha256(
        json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
    ).hexdigest()
    return {
        "schema_version": "dclaw-media-delivery-v1",
        "input_digest": "sha256:" + digest,
        "model_response_id": str(model_response_id or "")[:200],
        "media_inputs": manifest,
        "delivered_modalities": delivered,
        "unavailable_modalities": sorted(kinds - set(delivered)),
    }
