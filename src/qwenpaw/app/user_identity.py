"""Normalization helpers for customer identity fields."""
from __future__ import annotations

import re

_CN_MOBILE = re.compile(r"1[3-9][0-9]{9}\Z")


def normalize_cn_mobile(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    normalized = normalized.removeprefix("+86")
    if not _CN_MOBILE.fullmatch(normalized):
        raise ValueError("invalid mainland China mobile number")
    return f"+86{normalized}"
