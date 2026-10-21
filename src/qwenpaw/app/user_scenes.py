# -*- coding: utf-8 -*-
"""Serialization helpers for per-user external scene tabs."""
from __future__ import annotations

import hashlib
import json
from typing import Any

DEFAULT_SCENE_ICON = "external-link"
SCENE_ICON_NAMES = frozenset(
    {
        DEFAULT_SCENE_ICON,
        "headset",
        "bot",
        "globe",
        "contact",
        "building",
        "shopping-bag",
        "briefcase",
        "book-open",
        "chart",
        "messages",
        "life-buoy",
    },
)


def scene_icon_or_default(value: Any) -> str:
    icon = str(value or "").strip()
    return icon if icon in SCENE_ICON_NAMES else DEFAULT_SCENE_ICON


def encode_scene_tabs(scene_tabs: list[dict[str, str]]) -> str:
    return json.dumps(scene_tabs, ensure_ascii=False, separators=(",", ":"))


def decode_scene_tabs(
    scene_tabs_json: Any,
    legacy_url: Any = None,
) -> list[dict[str, str]]:
    if scene_tabs_json is None:
        url = str(legacy_url or "").strip()
        return (
            [{"title": "AI客服", "url": url, "icon": DEFAULT_SCENE_ICON}]
            if url
            else []
        )

    try:
        value = json.loads(str(scene_tabs_json))
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []

    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if title and url:
            result.append(
                {
                    "title": title,
                    "url": url,
                    "icon": scene_icon_or_default(item.get("icon")),
                },
            )
    return result


def scene_tabs_for_client(
    scene_tabs_json: Any,
    legacy_url: Any = None,
) -> list[dict[str, str]]:
    if scene_tabs_json is None:
        url = str(legacy_url or "").strip()
        return (
            [
                {
                    "key": "ai-customer-service",
                    "title": "AI客服",
                    "url": url,
                    "icon": DEFAULT_SCENE_ICON,
                },
            ]
            if url
            else []
        )
    result: list[dict[str, str]] = []
    for index, item in enumerate(decode_scene_tabs(scene_tabs_json)):
        digest = hashlib.sha256(
            f"{item['title']}\0{item['url']}".encode("utf-8"),
        ).hexdigest()[:10]
        result.append(
            {
                "key": f"external-{index}-{digest}",
                "title": item["title"],
                "url": item["url"],
                "icon": item["icon"],
            },
        )
    return result
