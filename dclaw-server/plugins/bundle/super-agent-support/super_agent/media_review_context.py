"""Request-local AIGC identity, supplied only after owned-asset resolution.

This is not caller metadata and not evidence of seeing or approving media.
All Python in this process is trusted; this is not a plugin security boundary.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import copy
import hashlib
import json
from typing import Any

from .models import AigcTaskBinding

_REVIEW_INPUT: ContextVar[dict[str, Any] | None] = ContextVar(
    "aigc_review_input",
    default=None,
)


@contextmanager
def bind_review_input(
    *,
    user_id: str,
    binding: AigcTaskBinding,
    asset_id: str,
    media_block: dict[str, Any],
    review_assets: list[dict[str, Any]] | None = None,
    media_blocks: list[dict[str, Any]] | None = None,
    runtime_installation_id: str | None = None,
):
    kind = media_block.get("type")
    if kind not in {"image", "video", "audio", "text"} or not asset_id:
        raise ValueError("invalid review media input")
    digest = hashlib.sha256(
        json.dumps(
            media_block,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode(),
    ).hexdigest()
    value = {
        "user_id": str(user_id),
        "binding": binding.model_dump(mode="json"),
        "schema_version": "dclaw-aigc-review-input-v1",
        "asset_id": asset_id,
        "media_kind": kind,
        "block_digest": "sha256:" + digest,
        "runtime_installation_id": (
            str(runtime_installation_id or binding.installation_id)
        ),
    }
    if review_assets:
        value["review_assets"] = copy.deepcopy(review_assets)

        def block_digest(block):
            encoded = json.dumps(
                block,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
            return "sha256:" + hashlib.sha256(encoded).hexdigest()

        value["review_blocks"] = [
            {"type": block.get("type"), "digest": block_digest(block)}
            for block in (media_blocks or [])
        ]
        value["blocks_digest"] = block_digest(media_blocks)
    token = _REVIEW_INPUT.set(value)
    try:
        yield
    finally:
        _REVIEW_INPUT.reset(token)


def current_review_input(
    *,
    user_id: str,
    installation_id: str,
    conversation_id: str,
) -> dict[str, Any] | None:
    value = _REVIEW_INPUT.get()
    if value is None or value["user_id"] != str(user_id):
        return None
    binding = value["binding"]
    if (
        value["runtime_installation_id"] != installation_id
        or binding["conversation_id"] != conversation_id
    ):
        return None
    return copy.deepcopy(
        {key: item for key, item in value.items() if key != "user_id"},
    )
