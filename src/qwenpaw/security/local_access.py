# -*- coding: utf-8 -*-
"""Per-chat local access policy shared by API and agent execution."""
from __future__ import annotations

from enum import Enum
from typing import Any, Mapping


LOCAL_ACCESS_MODE_META_KEY = "local_access_mode"


class LocalAccessMode(str, Enum):
    ASK_FOR_APPROVAL = "ask_for_approval"
    FULL_ACCESS = "full_access"


DEFAULT_LOCAL_ACCESS_MODE = LocalAccessMode.ASK_FOR_APPROVAL

# New chats opt in to the product default explicitly. The parser fallback above
# stays conservative so legacy chats without metadata are not silently widened.
NEW_CHAT_DEFAULT_LOCAL_ACCESS_MODE = LocalAccessMode.FULL_ACCESS


def parse_local_access_mode(
    value: Any,
    *,
    default: LocalAccessMode | None = DEFAULT_LOCAL_ACCESS_MODE,
) -> LocalAccessMode | None:
    """Parse a stored/request mode without accepting lookalike values."""
    if isinstance(value, LocalAccessMode):
        return value
    if isinstance(value, str):
        try:
            return LocalAccessMode(value.strip())
        except ValueError:
            pass
    return default


def local_access_mode_from_meta(
    meta: Mapping[str, Any] | None,
) -> LocalAccessMode:
    value = meta.get(LOCAL_ACCESS_MODE_META_KEY) if meta else None
    return parse_local_access_mode(value) or DEFAULT_LOCAL_ACCESS_MODE
