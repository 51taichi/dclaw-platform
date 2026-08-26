"""Server-side buffering and filtering helpers for sealed responses."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .output_policy import SealedOutputPolicy


def build_release_output_policy(source_root: Path) -> SealedOutputPolicy:
    protected: list[str] = []
    root = Path(source_root).resolve()
    total = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            if path.stat().st_size > 1024 * 1024:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        total += len(text)
        if total > 8 * 1024 * 1024:
            break
        for block in text.split("\n\n"):
            if len(" ".join(block.split())) >= 20:
                protected.append(block)
    return SealedOutputPolicy(protected_texts=protected, canaries=[])


def sanitize_message(message: Any, policy: SealedOutputPolicy) -> Any:
    """Return a copied message with every user-visible text leaf filtered."""
    sanitized = copy.deepcopy(message)
    _sanitize_value(sanitized, policy)
    return sanitized


def _sanitize_value(value: Any, policy: SealedOutputPolicy) -> None:
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if key == "text" and isinstance(item, str):
                value[key] = policy.evaluate(item).public_text
            else:
                _sanitize_value(item, policy)
        return
    if isinstance(value, list):
        for item in value:
            _sanitize_value(item, policy)
        return
    if hasattr(value, "text") and isinstance(value.text, str):
        value.text = policy.evaluate(value.text).public_text
    content = getattr(value, "content", None)
    if content is not None and content is not value:
        _sanitize_value(content, policy)
