# -*- coding: utf-8 -*-
"""Normalization helpers for customer identity fields."""
from __future__ import annotations

import re

_CN_MOBILE = re.compile(r"1[3-9][0-9]{9}\Z")


def normalize_cn_mobile(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if normalized.startswith("+86"):
        normalized = normalized[3:]
    if not _CN_MOBILE.fullmatch(normalized):
        raise ValueError("invalid mainland China mobile number")
    return f"+86{normalized}"
