# -*- coding: utf-8 -*-
# pylint: disable=too-many-lines
"""Build editable PPTX decks with service-native layout and asset QA.

The Codex presentations skill uses a private artifact-tool runtime. This tool
implements the same service-facing contract in QwenPaw's backend: structured
slide specs, native PPT shapes, image placement guarantees, layout selection,
theme control, and package-level QA without depending on a local Codex runtime.
"""

from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from agentscope.message import DataBlock, TextBlock, URLSource
from agentscope.tool import ToolResponse
from PIL import Image, ImageDraw, UnidentifiedImageError

from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR
from .file_io import _resolve_file_path
from .send_file import _path_to_file_url

EMU_PER_INCH = 914400
SLIDE_WIDTH_IN = 13.333333
SLIDE_HEIGHT_IN = 7.5
SLIDE_WIDTH_EMU = int(round(SLIDE_WIDTH_IN * EMU_PER_INCH))
SLIDE_HEIGHT_EMU = int(round(SLIDE_HEIGHT_IN * EMU_PER_INCH))

PML_CT = (
    "application/vnd.openxmlformats-officedocument."
    "presentationml.presentation.main+xml"
)
SLIDE_CT = (
    "application/vnd.openxmlformats-officedocument."
    "presentationml.slide+xml"
)
SLIDE_LAYOUT_CT = (
    "application/vnd.openxmlformats-officedocument."
    "presentationml.slideLayout+xml"
)
SLIDE_MASTER_CT = (
    "application/vnd.openxmlformats-officedocument."
    "presentationml.slideMaster+xml"
)
THEME_CT = "application/vnd.openxmlformats-officedocument.theme+xml"
CORE_CT = "application/vnd.openxmlformats-package.core-properties+xml"
APP_CT = (
    "application/vnd.openxmlformats-officedocument."
    "extended-properties+xml"
)

LINE_WIDTH_PT = 12700
IMAGE_ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

LAYOUT_CATALOG: list[dict[str, Any]] = [
    {
        "layout": "image_hero",
        "family": "image-led",
        "use_when": "A single visual should carry the opening or thesis.",
        "slots": ["title", "subtitle", "images"],
        "density": "sparse",
    },
    {
        "layout": "section",
        "family": "divider",
        "use_when": "Introduce a new chapter or narrative beat.",
        "slots": ["kicker", "title", "subtitle"],
        "density": "sparse",
    },
    {
        "layout": "cards",
        "family": "grid",
        "use_when": "Show 2-4 sibling ideas, offers, benefits, or modules.",
        "slots": ["title", "items"],
        "density": "moderate",
    },
    {
        "layout": "process",
        "family": "sequence",
        "use_when": "Show steps, workflow, method, or timeline.",
        "slots": ["title", "steps"],
        "density": "moderate",
    },
    {
        "layout": "metrics",
        "family": "evidence",
        "use_when": "Show KPI callouts or quantified evidence.",
        "slots": ["title", "metrics"],
        "density": "moderate",
    },
    {
        "layout": "table",
        "family": "evidence",
        "use_when": "Show structured comparison or service matrix.",
        "slots": ["title", "table"],
        "density": "dense",
    },
    {
        "layout": "two_column",
        "family": "comparison",
        "use_when": "Show paired narrative or two balanced content regions.",
        "slots": ["title", "columns"],
        "density": "moderate",
    },
    {
        "layout": "agenda",
        "family": "navigation",
        "use_when": "Show agenda, contents, or executive-read sections.",
        "slots": ["title", "items"],
        "density": "sparse",
    },
    {
        "layout": "comparison",
        "family": "comparison",
        "use_when": "Show before/after, option A/B, or old/new contrast.",
        "slots": ["title", "columns", "items"],
        "density": "moderate",
    },
    {
        "layout": "roadmap",
        "family": "sequence",
        "use_when": "Show phases, dates, implementation path, or milestones.",
        "slots": ["title", "steps"],
        "density": "moderate",
    },
    {
        "layout": "quote",
        "family": "editorial",
        "use_when": "Show one dominant claim, quote, or judgment.",
        "slots": ["title", "body", "footer"],
        "density": "sparse",
    },
    {
        "layout": "architecture",
        "family": "system",
        "use_when": "Show platform, operating model, modules, or capability map.",
        "slots": ["title", "items"],
        "density": "moderate",
    },
    {
        "layout": "content",
        "family": "narrative",
        "use_when": "Fallback for simple editable narrative content.",
        "slots": ["title", "body", "bullets", "images"],
        "density": "moderate",
    },
]

CODEX_GRID_TEMPLATE_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "template_use": "process",
        "layout_family": "two-column-content",
        "canonical_layout": "process",
        "count": 36,
        "density": "moderate",
        "max_text_tokens": 6,
        "use_when": "Use for steps, workflow, timeline, methods, or sequenced narrative.",
    },
    {
        "template_use": "two-column",
        "layout_family": "two-column-content",
        "canonical_layout": "two_column",
        "count": 14,
        "density": "moderate",
        "max_text_tokens": 7,
        "use_when": "Use for paired arguments, comparisons, problem-solution, or balanced regions.",
    },
    {
        "template_use": "metrics",
        "layout_family": "metric-led",
        "canonical_layout": "metrics",
        "count": 8,
        "density": "moderate",
        "max_text_tokens": 8,
        "use_when": "Use for KPI callouts, quantified evidence, scorecards, or business impact.",
    },
    {
        "template_use": "image-hero",
        "layout_family": "split-image-text",
        "canonical_layout": "image_hero",
        "count": 5,
        "density": "sparse",
        "max_text_tokens": 4,
        "asset_slots": 1,
        "use_when": "Use when one generated or user-provided image should carry the slide.",
    },
    {
        "template_use": "image-hero",
        "layout_family": "full-bleed-image",
        "canonical_layout": "image_hero",
        "count": 2,
        "density": "sparse",
        "max_text_tokens": 3,
        "asset_slots": 1,
        "use_when": "Use when the visual direction should read as a full-canvas opening.",
    },
    {
        "template_use": "agenda",
        "layout_family": "agenda-list",
        "canonical_layout": "agenda",
        "count": 5,
        "density": "sparse",
        "max_text_tokens": 6,
        "use_when": "Use for agenda, contents, chapter navigation, or executive-read sections.",
    },
    {
        "template_use": "data-table",
        "layout_family": "table-evidence",
        "canonical_layout": "table",
        "count": 5,
        "density": "dense",
        "max_text_tokens": 10,
        "use_when": "Use for structured evidence, service matrices, comparison tables, or audit rows.",
    },
    {
        "template_use": "cover",
        "layout_family": "cover-image-field",
        "canonical_layout": "image_hero",
        "count": 2,
        "density": "sparse",
        "max_text_tokens": 3,
        "asset_slots": 1,
        "use_when": "Use for title slides or section openers that need a dominant visual field.",
    },
    {
        "template_use": "chart",
        "layout_family": "chart-evidence",
        "canonical_layout": "metrics",
        "count": 2,
        "density": "moderate",
        "max_text_tokens": 8,
        "use_when": "Use for chart-led evidence with a short interpretation rail.",
    },
    {
        "template_use": "content",
        "layout_family": "multi-region-content",
        "canonical_layout": "content",
        "count": 1,
        "density": "moderate",
        "max_text_tokens": 12,
        "use_when": "Use as a controlled fallback when no stronger layout role fits.",
    },
)


def _registry_slots(canonical_layout: str) -> list[dict[str, Any]]:
    base_slots: list[dict[str, Any]] = [
        {
            "name": "title",
            "role": "title",
            "source": "content-token",
            "required": True,
            "textRole": "title",
        },
    ]
    if canonical_layout == "image_hero":
        return base_slots + [
            {
                "name": "subtitle",
                "role": "body",
                "source": "content-token",
                "required": False,
                "textRole": "body",
            },
            {
                "name": "hero",
                "role": "hero",
                "source": "asset",
                "required": False,
                "assetRole": "hero",
            },
        ]
    if canonical_layout in {"process", "roadmap"}:
        return base_slots + [
            {
                "name": f"step_{index}",
                "role": "body",
                "source": "content-token",
                "required": index <= 3,
                "textRole": "body",
            }
            for index in range(1, 6)
        ]
    if canonical_layout == "two_column":
        return base_slots + [
            {
                "name": "left_column",
                "role": "body",
                "source": "content-token",
                "required": True,
                "textRole": "body",
            },
            {
                "name": "right_column",
                "role": "body",
                "source": "content-token",
                "required": True,
                "textRole": "body",
            },
        ]
    if canonical_layout in {"metrics", "chart"}:
        return base_slots + [
            {
                "name": f"metric_{index}",
                "role": "stat",
                "source": "content-token",
                "required": index <= 3,
                "textRole": "stat",
            }
            for index in range(1, 5)
        ]
    if canonical_layout == "agenda":
        return base_slots + [
            {
                "name": f"agenda_item_{index}",
                "role": "label",
                "source": "content-token",
                "required": index <= 3,
                "textRole": "label",
            }
            for index in range(1, 6)
        ]
    if canonical_layout == "table":
        return base_slots + [
            {
                "name": "table",
                "role": "body",
                "source": "table",
                "required": True,
                "textRole": "body",
            },
        ]
    return base_slots + [
        {
            "name": "body",
            "role": "body",
            "source": "content-token",
            "required": False,
            "textRole": "body",
        },
    ]


def _build_codex_grid_template_registry() -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    for group in CODEX_GRID_TEMPLATE_GROUPS:
        for _ in range(group["count"]):
            slide_number = len(templates) + 1
            canonical_layout = group["canonical_layout"]
            asset_slot_count = int(group.get("asset_slots", 0))
            template_id = f"codex-grid-layout-library#slide-{slide_number:02d}"
            templates.append(
                {
                    "templateId": template_id,
                    "slideNumber": slide_number,
                    "templateUse": group["template_use"],
                    "useWhen": group["use_when"],
                    "avoidWhen": (
                        "Avoid when required content exceeds the density, "
                        "image, table, or chart budget for this layout."
                    ),
                    "layoutFamily": group["layout_family"],
                    "canonicalLayout": canonical_layout,
                    "contentRoles": sorted(
                        {
                            slot["role"]
                            for slot in _registry_slots(canonical_layout)
                            if slot["role"] != "region"
                        },
                    ),
                    "slots": _registry_slots(canonical_layout),
                    "densityBudget": {
                        "level": group["density"],
                        "maxTextTokens": group["max_text_tokens"],
                        "maxImageSlots": asset_slot_count,
                        "guidance": (
                            "Split or choose another registry entry before "
                            "shrinking text below the typography budget."
                        ),
                    },
                    "typographyBudget": {
                        "titleMinPx": 33,
                        "bodyMinPx": 14,
                        "preferredBodyPxRange": [17, 23],
                        "tableBodyMinPx": 12,
                        "sourceFootnoteMinPx": 9,
                    },
                    "assetSlots": [
                        {
                            "name": "hero",
                            "role": "hero",
                            "required": False,
                            "description": "Generated or user-provided visual direction image.",
                        }
                    ]
                    if asset_slot_count
                    else [],
                    "previewPng": (
                        "presentation-builder/codex-grid/previews/"
                        f"slide-{slide_number:02d}.png"
                    ),
                    "component": {
                        "module": "qwenpaw.agents.tools.presentation_builder",
                        "exportName": f"buildSlide{slide_number:02d}",
                        "authoringMode": "qwenpaw-pptx-compose",
                        "canonicalLayout": canonical_layout,
                    },
                    "textFlows": [
                        {
                            "kind": "layout-family",
                            "tokenIds": [
                                slot["name"]
                                for slot in _registry_slots(canonical_layout)
                                if slot.get("textRole")
                            ],
                        },
                    ],
                    "majorRegions": [
                        {
                            "role": group["layout_family"],
                            "frame": {
                                "left": 0,
                                "top": 0,
                                "width": 1280,
                                "height": 720,
                            },
                        },
                    ],
                },
            )
    return templates


CODEX_GRID_TEMPLATE_REGISTRY = _build_codex_grid_template_registry()
CODEX_GRID_TEMPLATE_BY_ID = {
    template["templateId"].lower(): template for template in CODEX_GRID_TEMPLATE_REGISTRY
}


def _build_layout_aliases() -> dict[str, str]:
    aliases = {
        "3-column": "cards",
        "3_column": "cards",
        "cover": "image_hero",
        "cover_page": "image_hero",
        "cover-page": "image_hero",
        "data-table": "table",
        "data_table": "table",
        "divider": "section",
        "image-hero": "image_hero",
        "imagehero": "image_hero",
        "section-divider": "section",
        "section_divider": "section",
        "three-column": "cards",
        "three_column": "cards",
        "two-column": "two_column",
        "two_columns": "two_column",
    }
    for template in CODEX_GRID_TEMPLATE_REGISTRY:
        slide_number = int(template["slideNumber"])
        canonical_layout = str(template["canonicalLayout"])
        slide_dash = f"slide-{slide_number:02d}"
        slide_us = f"slide_{slide_number:02d}"
        template_id = str(template["templateId"]).lower()
        for key in {
            template_id,
            template_id.replace("-", "_"),
            f"codex-grid#{slide_dash}",
            f"codex_grid#{slide_us}",
            f"qwenpaw-grid#{slide_dash}",
            f"qwenpaw_grid#{slide_us}",
            slide_dash,
            slide_us,
        }:
            aliases[key] = canonical_layout
    return aliases


LAYOUT_ALIASES = _build_layout_aliases()


def presentation_layout_catalog() -> dict[str, Any]:
    """Return the service-native presentation route and layout catalog."""
    return {
        "route_modes": [
            "template_following",
            "custom_compose",
            "codex_grid",
        ],
        "layouts": LAYOUT_CATALOG,
        "templates": CODEX_GRID_TEMPLATE_REGISTRY,
        "template_count": len(CODEX_GRID_TEMPLATE_REGISTRY),
        "layout_registry": {
            "name": "Codex Grid Layout Library compatible registry",
            "slide_size": {"width": 1280, "height": 720},
            "template_count": len(CODEX_GRID_TEMPLATE_REGISTRY),
            "authoring_mode": "qwenpaw-pptx-compose",
        },
        "qa_contract": {
            "embedded_media": "required-assets-must-map",
            "weak_slides": "warn-or-fail",
            "overlap": "warn-or-fail",
            "layout_variety": "reported",
            "compose_manifest": "optional-service-native-source-ledger",
            "delivery_pdf": "final-delivery-exports-user-facing-pdf",
            "delivery_mode": "auto-defaults-to-final-with-distinct-prototype-checkpoint",
            "visual_assets": "requires-mapped-assets-when-enabled",
            "visual_route_continuity": "imagegen-selected-direction-requires-custom-compose",
            "expected_slide_count": "optional-hard-count-contract",
            "render_qa": "requires-soffice-and-pdftoppm-when-enabled",
            "template_audit": "reported-when-template_path-is-used",
            "template_following": {
                "requires": ["template_path", "template_frame_map"],
                "mode": "clone_edit",
                "edit_targets": ["rewrite", "replace-image"],
                "selectors": ["shapeName", "shapeId", "matchText", "placeholderType"],
            },
            "custom_compose": {
                "requires": ["compose_spec.slides[].layers"],
                "mode": "exact-layer-authoring",
                "layer_types": ["text", "shape", "line", "image"],
                "semantic_qa": [
                    "required_layer_names",
                    "required_text",
                    "layer_type_counts",
                    "semantic_group_counts",
                ],
            },
        },
    }


@dataclass
class ThemeSpec:
    mode: str = "light"
    canvas: str = "FFFFFF"
    ink: str = "111827"
    body: str = "374151"
    muted: str = "6B7280"
    panel: str = "F3F4F6"
    panel_alt: str = "E5E7EB"
    rule: str = "D1D5DB"
    accent: str = "2563EB"
    accent_soft: str = "DBEAFE"
    font_family: str = "Microsoft YaHei"


@dataclass
class ImagePlacement:
    path: Path
    role: str = "hero"
    label: str = ""
    purpose: str = ""
    usage_mode: str = "direct-raster"
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None


@dataclass
class SlideSpec:
    title: str = ""
    subtitle: str = ""
    body: str = ""
    kicker: str = ""
    layout: str = "auto"
    bullets: list[str] = field(default_factory=list)
    images: list[ImagePlacement] = field(default_factory=list)
    items: list[dict[str, str]] = field(default_factory=list)
    steps: list[dict[str, str]] = field(default_factory=list)
    metrics: list[dict[str, str]] = field(default_factory=list)
    table: dict[str, Any] = field(default_factory=dict)
    columns: list[dict[str, str]] = field(default_factory=list)
    footer: str = ""
    archetype: str = ""
    custom_layers: list[dict[str, Any]] = field(default_factory=list)
    expected_content: dict[str, Any] = field(default_factory=dict)


def _text_response(text: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _file_block(path: Path) -> DataBlock:
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return DataBlock(
        source=URLSource(
            url=_path_to_file_url(str(path)),
            media_type=media_type,
        ),
        name=path.name,
    )


def _as_list(value: Any, field_name: str) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} must be a list or JSON list.") from exc
        value = parsed
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list.")
    return value


def _as_dict(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} must be an object or JSON object.") from exc
        value = parsed
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object.")
    return value


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return _clean_text(value).lower() in {"1", "true", "yes", "y", "on"}


def _as_bool_or_auto(value: Any) -> bool | str:
    if isinstance(value, bool):
        return value
    raw = _clean_text(value).lower()
    if not raw or raw == "auto":
        return "auto"
    return raw in {"1", "true", "yes", "y", "on"}


def _normalize_delivery_mode(value: Any, output_path: Path) -> str:
    raw = _clean_text(value).lower().replace("_", "-")
    if not raw or raw == "auto":
        env_mode = _clean_text(
            os.environ.get("QWENPAW_PRESENTATION_DELIVERY_MODE"),
        ).lower().replace("_", "-")
        if env_mode:
            raw = env_mode
        else:
            raw = "final"
    if raw in {"client", "client-ready", "clientready", "final", "delivery"}:
        return "final"
    if raw in {"prototype", "prototype-checkpoint", "prototype_checkpoint"}:
        if not _is_internal_preview_output(output_path):
            raise ValueError(
                "delivery_mode=prototype requires an output_path under a "
                "prototype/ or prototypes/ preview directory so it cannot be "
                "mistaken for a final deliverable.",
            )
        return "prototype"
    if raw in {"draft", "preview", "dev"}:
        if _is_workspace_root_deliverable(output_path):
            raise ValueError(
                "delivery_mode=draft is blocked for workspace-root deliverable "
                "PPTX outputs. Use delivery_mode=final with render QA, PDF, "
                "compose manifest, and mapped visual assets, or write true "
                "drafts under a draft/preview subdirectory for internal "
                "preview only.",
            )
        if _is_session_deliverable_output(output_path):
            raise ValueError(
                "delivery_mode=draft is blocked for session deliverable PPTX "
                "outputs. Use delivery_mode=final with render QA, PDF, compose "
                "manifest, and mapped visual assets, or write true drafts under "
                "a draft/preview subdirectory for internal preview only.",
            )
        return "draft"
    raise ValueError("delivery_mode must be auto, draft, prototype, or final.")


def _normalize_route_mode(
    value: Any,
    *,
    has_template_frame_map: bool,
    has_compose_spec: bool,
) -> str:
    raw = _clean_text(value).lower().replace("-", "_")
    aliases = {
        "": "auto",
        "auto": "auto",
        "template": "template_following",
        "template_following": "template_following",
        "custom": "custom_compose",
        "custom_formatting": "custom_compose",
        "custom_compose": "custom_compose",
        "freeform": "custom_compose",
        "grid": "codex_grid",
        "codex_grid": "codex_grid",
    }
    normalized = aliases.get(raw)
    if not normalized:
        raise ValueError(
            "route_mode must be auto, template_following, custom_compose, or codex_grid.",
        )
    inferred = (
        "template_following"
        if has_template_frame_map
        else "custom_compose"
        if has_compose_spec
        else "codex_grid"
    )
    if normalized == "auto":
        return inferred
    if normalized == "template_following" and not has_template_frame_map:
        raise ValueError("route_mode=template_following requires template_frame_map.")
    if normalized == "custom_compose" and not has_compose_spec:
        raise ValueError("route_mode=custom_compose requires compose_spec.")
    if normalized != inferred and inferred != "codex_grid":
        raise ValueError(
            f"route_mode={normalized} conflicts with the provided {inferred} inputs.",
        )
    return normalized


def _normalize_label_items(value: Any, field_name: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for entry in _as_list(value, field_name):
        if isinstance(entry, str):
            text = _clean_text(entry)
            if text:
                items.append({"title": text, "body": ""})
            continue
        if not isinstance(entry, dict):
            raise ValueError(f"{field_name} entries must be strings or objects.")
        title = _clean_text(
            entry.get("title")
            or entry.get("label")
            or entry.get("name")
            or entry.get("value"),
        )
        body = _clean_text(
            entry.get("body")
            or entry.get("caption")
            or entry.get("description")
            or entry.get("content"),
        )
        value_text = _clean_text(entry.get("value"))
        if title or body or value_text:
            normalized = {"title": title, "body": body}
            if value_text:
                normalized["value"] = value_text
            items.append(normalized)
    return items


def _split_label_body(text: str) -> dict[str, str]:
    cleaned = _clean_text(text)
    if not cleaned:
        return {"title": "", "body": ""}
    match = re.match(r"^(Phase\s*\d+)\s*[：:]\s*(.+)$", cleaned, flags=re.I)
    if match:
        return {
            "title": re.sub(r"\s+", " ", match.group(1)).strip(),
            "body": match.group(2).strip(),
        }
    match = re.match(r"^([^：:\n]{2,18})[：:]\s*(.+)$", cleaned)
    if match:
        return {
            "title": match.group(1).strip(),
            "body": match.group(2).strip(),
        }
    return {"title": cleaned, "body": ""}


def _items_from_bullets(bullets: list[str], limit: int | None = None) -> list[dict[str, str]]:
    selected = bullets[:limit] if limit else bullets
    return [
        item
        for item in (_split_label_body(bullet) for bullet in selected)
        if item["title"] or item["body"]
    ]


def _resolve_path(path: str | Path) -> Path:
    return Path(_resolve_file_path(str(path)))


def _resolve_output_path(output_path: str) -> Path:
    cleaned = _clean_text(output_path)
    if not cleaned:
        raise ValueError("output_path is required.")
    resolved = _resolve_path(cleaned)
    if resolved.suffix.lower() != ".pptx":
        raise ValueError("output_path must end with .pptx.")
    return resolved


def _workspace_root_from_path(path: Path) -> Path:
    resolved = path.resolve()
    parts = resolved.parts
    if "sessions_data" in parts:
        idx = parts.index("sessions_data")
        return Path(*parts[:idx])
    return resolved if resolved.is_dir() else resolved.parent


def _is_workspace_root_deliverable(output_path: Path) -> bool:
    resolved_output = output_path.resolve()
    workspace_dir = get_current_workspace_dir()
    if workspace_dir:
        workspace_root = _workspace_root_from_path(
            Path(workspace_dir).expanduser().resolve(),
        ).resolve()
        return resolved_output.parent == workspace_root

    try:
        workspaces_root = (WORKING_DIR / "workspaces").resolve()
        relative = resolved_output.relative_to(workspaces_root)
    except ValueError:
        return False
    return len(relative.parts) == 2


def _is_within_path(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _current_workspace_root() -> Path | None:
    workspace_dir = get_current_workspace_dir()
    if not workspace_dir:
        return None
    return _workspace_root_from_path(Path(workspace_dir).expanduser().resolve()).resolve()


def _is_internal_preview_output(output_path: Path) -> bool:
    preview_dirs = {"draft", "preview", "prototype", "prototypes"}
    resolved_output = output_path.resolve()
    workspace_dir = get_current_workspace_dir()
    if workspace_dir:
        workspace_root = _workspace_root_from_path(
            Path(workspace_dir).expanduser().resolve(),
        ).resolve()
        try:
            relative = resolved_output.relative_to(workspace_root)
        except ValueError:
            return False
        return any(part in preview_dirs for part in relative.parts[:-1])

    try:
        workspaces_root = (WORKING_DIR / "workspaces").resolve()
        relative = resolved_output.relative_to(workspaces_root)
    except ValueError:
        return False
    return len(relative.parts) > 2 and any(
        part in preview_dirs for part in relative.parts[1:-1]
    )


def _is_session_deliverable_output(output_path: Path) -> bool:
    session_id = _current_session_id()
    workspace_root = _current_workspace_root()
    if not session_id or not workspace_root:
        return False

    session_dir = workspace_root / "sessions_data" / session_id
    try:
        relative = output_path.resolve().relative_to(session_dir.resolve())
    except ValueError:
        return False
    if not relative.parts:
        return False
    return not _is_internal_preview_output(output_path)


def _current_session_id() -> str:
    try:
        from ...app.agent_context import get_current_session_id

        return _clean_text(get_current_session_id())
    except Exception:
        return ""


def _session_presentation_artifacts_dir() -> Path | None:
    session_id = _current_session_id()
    workspace_root = _current_workspace_root()
    if not session_id or not workspace_root:
        return None
    return workspace_root / "sessions_data" / session_id / "artifacts" / "presentation"


def _session_isolated_final_output_path(output_path: Path) -> Path:
    """Keep service final deliverables inside the active chat sandbox."""
    artifacts_dir = _session_presentation_artifacts_dir()
    workspace_root = _current_workspace_root()
    if not artifacts_dir or not workspace_root:
        return output_path

    resolved_output = output_path.resolve()
    if not _is_within_path(resolved_output, workspace_root):
        return output_path

    session_dir = artifacts_dir.parent.parent
    if _is_within_path(resolved_output, session_dir):
        return output_path

    return artifacts_dir / output_path.name


def _current_session_imagegen_assets(output_path: Path) -> list[Path]:
    session_id = _current_session_id()
    candidate_dirs: set[Path] = set()

    workspace_dir = get_current_workspace_dir()
    if workspace_dir:
        workspace_path = Path(workspace_dir).expanduser().resolve()
        candidate_dirs.add(workspace_path / "media" / "imagegen")
        if session_id:
            candidate_dirs.add(
                _workspace_root_from_path(workspace_path)
                / "sessions_data"
                / session_id
                / "media"
                / "imagegen",
            )

    if session_id:
        candidate_dirs.add(
            _workspace_root_from_path(output_path.parent)
            / "sessions_data"
            / session_id
            / "media"
            / "imagegen",
        )

    assets: list[Path] = []
    seen: set[Path] = set()
    for directory in candidate_dirs:
        if not directory.exists() or not directory.is_dir():
            continue
        for path in sorted(directory.glob("imagegen_*")):
            if path.suffix.lower() not in IMAGE_ASSET_SUFFIXES:
                continue
            resolved = path.resolve()
            if resolved in seen or not resolved.is_file():
                continue
            seen.add(resolved)
            assets.append(resolved)
    return assets


def _imagegen_presentation_context(asset_path: Path) -> dict[str, Any]:
    """Return presentation provenance recorded beside an imagegen asset."""
    sidecar = asset_path.with_suffix(".imagegen.json")
    if not sidecar.is_file():
        return {}
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    context = payload.get("presentationContext")
    return context if isinstance(context, dict) else {}


def _referenced_visual_direction_records(
    referenced_assets: set[Path],
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for asset_path in sorted(referenced_assets):
        context = _imagegen_presentation_context(asset_path)
        stage = _clean_text(context.get("stage")).lower()
        direction_name = _clean_text(context.get("direction_name"))
        if stage != "visual_asset" or not direction_name:
            continue
        records.append(
            {
                "asset_path": str(asset_path),
                "stage": stage,
                "direction_name": direction_name,
                "asset_type": _clean_text(context.get("asset_type")),
                "output_role": _clean_text(context.get("output_role")),
            },
        )
    return records


def _entry_asset_path(entry: dict[str, Any]) -> str:
    for key in ("asset_path", "image_path", "path", "file_path"):
        value = _clean_text(entry.get(key))
        if value:
            return value
    return ""


def _text_sequence(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    texts: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = _clean_text(
                item.get("title")
                or item.get("label")
                or item.get("body")
                or item.get("content")
                or item.get("value"),
            )
        else:
            text = _clean_text(item)
        if text:
            texts.append(text)
    return texts


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected a numeric placement value, got {value!r}.") from exc


def _optional_positive_int(value: Any, field_name: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer.") from exc
    if normalized <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return normalized


def _normalize_custom_layer(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize common layer aliases before strict custom-compose QA."""
    layer = dict(value)
    if layer.get("text") in (None, "") and layer.get("content") not in (None, ""):
        layer["text"] = layer.get("content")
    if not _clean_text(layer.get("font_face") or layer.get("font_family")):
        font_value = _clean_text(layer.get("font"))
        if font_value:
            layer["font_face"] = font_value
    if layer.get("font_size") in (None, "") and layer.get("size") not in (None, ""):
        layer["font_size"] = layer.get("size")
    if layer.get("bold") in (None, ""):
        weight = _clean_text(layer.get("font_weight") or layer.get("weight")).lower()
        if weight:
            layer["bold"] = weight in {"bold", "semibold", "semi-bold", "600", "700", "800", "900"}
    if layer.get("line") in (None, "") and layer.get("stroke") not in (None, ""):
        layer["line"] = layer.get("stroke")
    if layer.get("line_width") in (None, "") and layer.get("stroke_width") not in (None, ""):
        layer["line_width"] = layer.get("stroke_width")
    return layer


def _placement_from_value(value: Any) -> ImagePlacement:
    if isinstance(value, str):
        return ImagePlacement(path=_resolve_path(value))
    if not isinstance(value, dict):
        raise ValueError("slide images must be strings or objects.")
    asset_path = _entry_asset_path(value)
    if not asset_path:
        raise ValueError("slide image object must include asset_path or path.")
    return ImagePlacement(
        path=_resolve_path(asset_path),
        role=_clean_text(value.get("role")) or "hero",
        label=_clean_text(value.get("label") or value.get("name")),
        purpose=_clean_text(
            _first_present(
                value,
                "purpose",
                "usage_reason",
                "usageReason",
                "reason",
                "narrative_role",
                "narrativeRole",
            ),
        ),
        usage_mode=_clean_text(
            _first_present(value, "usage_mode", "usageMode", "fit", "mode"),
        )
        or "direct-raster",
        x=_optional_float(value.get("x")),
        y=_optional_float(value.get("y")),
        w=_optional_float(value.get("w") or value.get("width")),
        h=_optional_float(value.get("h") or value.get("height")),
    )


def _normalize_table(value: Any) -> dict[str, Any]:
    table = _as_dict(value, "slide.table")
    if not table:
        return {}
    headers = [_clean_text(item) for item in _as_list(table.get("headers"), "table.headers")]
    rows = []
    for row in _as_list(table.get("rows"), "table.rows"):
        if not isinstance(row, list):
            raise ValueError("table.rows entries must be lists.")
        rows.append([_clean_text(cell) for cell in row])
    return {"headers": headers, "rows": rows}


def _slide_from_value(value: Any) -> SlideSpec:
    if isinstance(value, str):
        return SlideSpec(title=value)
    if not isinstance(value, dict):
        raise ValueError("slides must contain objects.")
    raw_body = value.get("body") if value.get("body") is not None else value.get("content")
    body_items = _text_sequence(raw_body)
    bullets = [
        _clean_text(item)
        for item in _as_list(value.get("bullets"), "slide.bullets")
        if _clean_text(item)
    ]
    bullets.extend(body_items)
    custom_layers = [
        _normalize_custom_layer(item)
        for item in _as_list(value.get("layers"), "slide.layers")
        if isinstance(item, dict)
    ]
    if len(custom_layers) != len(_as_list(value.get("layers"), "slide.layers")):
        raise ValueError("slide.layers entries must be objects.")
    images = [
        _placement_from_value(item)
        for item in _as_list(value.get("images"), "slide.images")
    ]
    for layer in custom_layers:
        if _clean_text(layer.get("type")).lower() != "image":
            continue
        image_value = dict(layer)
        image_value.setdefault("role", "custom-layer")
        image_value.setdefault("label", _clean_text(layer.get("name")))
        images.append(_placement_from_value(image_value))
    return SlideSpec(
        title=_clean_text(value.get("title")),
        subtitle=_clean_text(value.get("subtitle")),
        body="" if body_items else _clean_text(raw_body),
        kicker=_clean_text(value.get("kicker") or value.get("eyebrow")),
        layout=_clean_text(value.get("layout") or value.get("type")) or "auto",
        bullets=bullets,
        images=images,
        items=_normalize_label_items(value.get("items"), "slide.items"),
        steps=_normalize_label_items(value.get("steps"), "slide.steps"),
        metrics=_normalize_label_items(value.get("metrics"), "slide.metrics"),
        table=_normalize_table(value.get("table")),
        columns=_normalize_label_items(value.get("columns"), "slide.columns"),
        footer=_clean_text(value.get("footer")),
        archetype=_clean_text(value.get("archetype") or value.get("page_archetype")),
        custom_layers=custom_layers,
        expected_content=_as_dict(
            value.get("expected_content"),
            "slide.expected_content",
        ),
    )


def _slide_index_from_entry(entry: dict[str, Any]) -> int:
    for key in ("slide_index", "slide_number", "slide"):
        value = entry.get(key)
        if value not in (None, ""):
            try:
                return int(value) - 1
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must be a 1-based integer.") from exc
    raise ValueError("asset_usage_matrix entry must include slide_index.")


def _normalize_slides(
    slides: list[Any] | str | None,
    asset_usage_matrix: list[Any] | str | None,
) -> list[SlideSpec]:
    normalized = [_slide_from_value(item) for item in _as_list(slides, "slides")]
    if not normalized:
        normalized = [SlideSpec(title="Untitled Presentation")]

    for item in _as_list(asset_usage_matrix, "asset_usage_matrix"):
        if not isinstance(item, dict):
            raise ValueError("asset_usage_matrix entries must be objects.")
        index = _slide_index_from_entry(item)
        if index < 0 or index >= len(normalized):
            raise ValueError(
                "asset_usage_matrix slide_index is outside the slides range.",
            )
        normalized[index].images.append(_placement_from_value(item))
    return normalized


def _normalize_required_assets(
    required_image_assets: list[str] | str | None,
) -> list[Path]:
    return [
        _resolve_path(_clean_text(item))
        for item in _as_list(required_image_assets, "required_image_assets")
        if _clean_text(item)
    ]


def _first_present(entry: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = entry.get(key)
        if value not in (None, ""):
            return value
    return None


def _one_based_int(value: Any, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a 1-based integer.") from exc
    if parsed < 1:
        raise ValueError(f"{field_name} must be a 1-based integer.")
    return parsed


def _normalize_edit_targets(value: Any, field_name: str) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for index, raw_target in enumerate(_as_list(value, field_name), start=1):
        if not isinstance(raw_target, dict):
            raise ValueError(f"{field_name} entries must be objects.")
        action = _clean_text(raw_target.get("action") or "rewrite")
        action = action.lower().replace("_", "-")
        if action not in {"rewrite", "replace-image"}:
            raise ValueError(
                f"{field_name}[{index}].action must be rewrite or replace-image.",
            )
        target: dict[str, Any] = {
            "action": action,
            "shape_name": _clean_text(
                _first_present(raw_target, "shapeName", "shape_name", "name"),
            ),
            "match_text": _clean_text(
                _first_present(raw_target, "matchText", "match_text"),
            ),
            "placeholder_type": _clean_text(
                _first_present(
                    raw_target,
                    "placeholderType",
                    "placeholder_type",
                ),
            ),
        }
        shape_id = _first_present(raw_target, "shapeId", "shape_id", "id")
        if shape_id not in (None, ""):
            target["shape_id"] = _one_based_int(shape_id, f"{field_name}[{index}].shapeId")
        if action == "rewrite":
            text_value = _first_present(raw_target, "text", "value", "content")
            if text_value is None:
                raise ValueError(f"{field_name}[{index}].text is required.")
            target["text"] = _clean_text(text_value)
        else:
            asset_path = _clean_text(_first_present(raw_target, "asset_path", "path"))
            if not asset_path:
                raise ValueError(
                    f"{field_name}[{index}].asset_path is required for replace-image.",
                )
            target["asset_path"] = _resolve_path(asset_path)
        if not any(
            target.get(key)
            for key in ("shape_name", "match_text", "placeholder_type", "shape_id")
        ):
            raise ValueError(
                f"{field_name}[{index}] must include shapeName, matchText, "
                "placeholderType, or shapeId.",
            )
        targets.append(target)
    return targets


def _normalize_template_frame_map(
    template_frame_map: list[dict[str, Any]] | dict[str, Any] | str | None,
    source_slide_count: int,
) -> list[dict[str, Any]]:
    if template_frame_map in (None, ""):
        return []
    raw: Any = template_frame_map
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return []
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError("template_frame_map must be a list or JSON object.") from exc
    if isinstance(raw, dict):
        raw = raw.get("outputSlides") or raw.get("slides") or []
    if not isinstance(raw, list):
        raise ValueError("template_frame_map must be a list or object with outputSlides.")

    normalized: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(raw, start=1):
        if not isinstance(raw_entry, dict):
            raise ValueError("template_frame_map entries must be objects.")
        output_slide = _one_based_int(
            _first_present(raw_entry, "outputSlide", "output_slide") or index,
            f"template_frame_map[{index}].outputSlide",
        )
        source_slide = _one_based_int(
            _first_present(raw_entry, "sourceSlide", "source_slide"),
            f"template_frame_map[{index}].sourceSlide",
        )
        if source_slide > source_slide_count:
            raise ValueError(
                "template_frame_map sourceSlide is outside the template slide range.",
            )
        normalized.append(
            {
                "output_slide": output_slide,
                "source_slide": source_slide,
                "narrative_role": _clean_text(
                    _first_present(raw_entry, "narrativeRole", "narrative_role"),
                ),
                "reuse_mode": _clean_text(
                    _first_present(raw_entry, "reuseMode", "reuse_mode"),
                )
                or "duplicate-slide",
                "edit_targets": _normalize_edit_targets(
                    _first_present(raw_entry, "editTargets", "edit_targets"),
                    f"template_frame_map[{index}].editTargets",
                ),
            },
        )
    normalized.sort(key=lambda item: item["output_slide"])
    expected = list(range(1, len(normalized) + 1))
    actual = [item["output_slide"] for item in normalized]
    if actual != expected:
        raise ValueError("template_frame_map outputSlide values must be contiguous.")
    return normalized


def _referenced_assets(slides: list[SlideSpec]) -> set[Path]:
    return {placement.path for slide in slides for placement in slide.images}


def _referenced_template_assets(frame_map: list[dict[str, Any]]) -> set[Path]:
    assets: set[Path] = set()
    for entry in frame_map:
        for target in entry["edit_targets"]:
            if target["action"] == "replace-image":
                assets.add(target["asset_path"])
    return assets


def _validate_required_assets(
    required_assets: list[Path],
    referenced_assets: set[Path],
) -> None:
    missing = [path for path in required_assets if path not in referenced_assets]
    if missing:
        formatted = ", ".join(str(path) for path in missing)
        raise ValueError(
            "required image assets were not mapped to slides: "
            f"{formatted}. Provide asset_usage_matrix entries for every "
            "generated image that must appear in the PPTX.",
        )


DIRECT_RASTER_ASSET_ROLES = {
    "background",
    "diagram",
    "figure",
    "full-bleed",
    "hero",
    "thumb",
    "thumbnail",
    "wide",
    "banner",
}


NON_DIRECT_RASTER_ASSET_ROLES = {
    "asset",
    "badge-sheet",
    "component",
    "component-sheet",
    "connector-sheet",
    "decoration",
    "decorative",
    "icon-sheet",
    "kit",
    "module-sheet",
    "moodboard",
    "reference",
    "reference-only",
    "sticker",
    "style-reference",
    "visual-language",
}


def _normalize_asset_role(role: str) -> str:
    return (_clean_text(role) or "hero").lower().replace("_", "-")


def _normalize_usage_mode(value: str) -> str:
    return (_clean_text(value) or "direct-raster").lower().replace("_", "-")


def _validate_final_visual_asset_placements(
    slides: list[SlideSpec],
    *,
    final_visual_assets_active: bool,
) -> None:
    if not final_visual_assets_active:
        return

    for slide_no, slide in enumerate(slides, start=1):
        direct_images: list[ImagePlacement] = []
        for placement in slide.images:
            role = _normalize_asset_role(placement.role)
            usage_mode = _normalize_usage_mode(placement.usage_mode)
            if usage_mode not in {"direct-raster", "hybrid"}:
                raise ValueError(
                    "visual asset QA failed: asset_usage_matrix is only for "
                    "direct raster placements. Translate reference-only "
                    "generated assets into native PPT components and keep "
                    "them out of required_image_assets.",
                )
            if role in NON_DIRECT_RASTER_ASSET_ROLES:
                raise ValueError(
                    "visual asset QA failed: slide "
                    f"{slide_no} maps generated asset as role "
                    f"'{placement.role}', which is a component/reference role "
                    "rather than a direct slide placement. Translate component "
                    "sheets into native PPT components or omit them from "
                    "required_image_assets.",
                )
            if role not in DIRECT_RASTER_ASSET_ROLES:
                raise ValueError(
                    "visual asset QA failed: slide "
                    f"{slide_no} uses unsupported direct raster role "
                    f"'{placement.role}'. Use hero, background, wide, "
                    "thumbnail, figure, or diagram for direct image "
                    "placements; use native PPT components for generated kits.",
                )
            direct_images.append(placement)

        if len(direct_images) > 2:
            raise ValueError(
                "visual asset QA failed: too many direct raster images on "
                f"slide {slide_no} ({len(direct_images)}). Use at most 2 "
                "direct raster images per slide and redraw repeated kit "
                "elements as native PPT components.",
            )


def _ensure_image(path: Path) -> tuple[bytes, int, int]:
    if not path.exists():
        raise ValueError(f"Image asset does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"Image asset is not a file: {path}")
    try:
        with Image.open(path) as image:
            width, height = image.size
            converted = image.convert("RGBA" if image.mode == "RGBA" else "RGB")
            output = io.BytesIO()
            converted.save(output, format="PNG")
            return output.getvalue(), width, height
    except UnidentifiedImageError as exc:
        raise ValueError(f"Image asset is not a readable image: {path}") from exc


def _resolve_layout_name(value: str) -> str:
    """Return a canonical editable layout for explicit names or registry ids."""
    raw = _clean_text(value).lower()
    if not raw:
        return ""
    normalized = raw.replace("-", "_")
    return LAYOUT_ALIASES.get(raw) or LAYOUT_ALIASES.get(normalized) or normalized


def _resolve_template_id(value: str) -> str:
    """Return the Codex Grid-compatible template id represented by a layout value."""
    raw = _clean_text(value).lower()
    if not raw or raw == "auto":
        return ""
    normalized = raw.replace("_", "-")
    for template in CODEX_GRID_TEMPLATE_REGISTRY:
        slide_number = int(template["slideNumber"])
        template_id = str(template["templateId"])
        candidates = {
            template_id.lower(),
            template_id.lower().replace("_", "-"),
            f"codex-grid#slide-{slide_number:02d}",
            f"qwenpaw-grid#slide-{slide_number:02d}",
            f"slide-{slide_number:02d}",
        }
        if raw in candidates or normalized in candidates:
            return template_id
    return ""


def _resolve_template_slide_number(value: str) -> int | None:
    template_id = _resolve_template_id(value)
    if not template_id:
        return None
    match = re.search(r"slide-(\d+)$", template_id)
    return int(match.group(1)) if match else None


def _template_ids_for_registry_target(
    canonical_layout: str,
    *,
    template_use: str = "",
) -> list[str]:
    ids: list[str] = []
    for template in CODEX_GRID_TEMPLATE_REGISTRY:
        if template_use and str(template.get("templateUse")) != template_use:
            continue
        if str(template.get("canonicalLayout")) != canonical_layout:
            continue
        ids.append(str(template["templateId"]))
    return ids


def _auto_codex_grid_template_id(
    slide: SlideSpec,
    slide_no: int,
    counters: dict[tuple[str, str], int],
) -> str:
    raw_layout = _clean_text(slide.layout).lower().replace("_", "-")
    inferred_layout = _infer_layout(slide, slide_no)
    registry_layout = inferred_layout
    preferred_use = ""

    if raw_layout in {"cover", "cover-page", "title", "title-page"}:
        registry_layout = "image_hero"
        preferred_use = "cover"
    elif inferred_layout in {"roadmap", "timeline"}:
        registry_layout = "process"
    elif inferred_layout in {"comparison"}:
        registry_layout = "two_column"
    elif inferred_layout == "chart":
        registry_layout = "metrics"
        preferred_use = "chart"
    elif inferred_layout == "section" and slide_no == 1:
        registry_layout = "image_hero"
        preferred_use = "cover"
    elif inferred_layout in {"section", "quote"}:
        return ""
    elif inferred_layout == "architecture":
        registry_layout = "process"
    elif inferred_layout == "cards":
        return ""

    template_ids = _template_ids_for_registry_target(
        registry_layout,
        template_use=preferred_use,
    )
    if not template_ids and preferred_use:
        template_ids = _template_ids_for_registry_target(registry_layout)
    if not template_ids:
        return ""

    key = (registry_layout, preferred_use)
    index = counters.get(key, 0)
    counters[key] = index + 1
    return template_ids[index % len(template_ids)]


def _apply_final_delivery_codex_grid_templates(
    slides: list[SlideSpec],
    *,
    output: Path,
    final_delivery: bool,
    frame_map: list[dict[str, Any]],
) -> None:
    if not final_delivery or frame_map:
        return
    counters: dict[tuple[str, str], int] = {}
    for slide_no, slide in enumerate(slides, start=1):
        if _resolve_template_id(slide.layout):
            continue
        template_id = _auto_codex_grid_template_id(slide, slide_no, counters)
        if template_id:
            slide.layout = template_id


def _emu(value_in_inches: float) -> int:
    return int(round(value_in_inches * EMU_PER_INCH))


def _fit_contain(
    img_width: int,
    img_height: int,
    x: float,
    y: float,
    w: float,
    h: float,
) -> tuple[float, float, float, float]:
    if img_width <= 0 or img_height <= 0:
        return x, y, w, h
    image_ratio = img_width / img_height
    box_ratio = w / h
    if image_ratio > box_ratio:
        fitted_w = w
        fitted_h = w / image_ratio
    else:
        fitted_h = h
        fitted_w = h * image_ratio
    return x + (w - fitted_w) / 2, y + (h - fitted_h) / 2, fitted_w, fitted_h


def _default_box(
    placement: ImagePlacement,
    image_size: tuple[int, int],
    layout: str = "content",
) -> tuple[int, int, int, int]:
    if all(
        value is not None
        for value in (placement.x, placement.y, placement.w, placement.h)
    ):
        x, y, w, h = (
            float(placement.x),
            float(placement.y),
            float(placement.w),
            float(placement.h),
        )
    elif placement.role in {"background", "full_bleed", "full-bleed"}:
        x, y, w, h = 0.0, 0.0, SLIDE_WIDTH_IN, SLIDE_HEIGHT_IN
    elif layout in {"image_hero", "image-hero"} or placement.role == "hero":
        x, y, w, h = 7.15, 0.85, 5.45, 5.9
    elif placement.role in {"wide", "banner"}:
        x, y, w, h = 0.72, 4.55, 11.9, 2.25
    elif placement.role in {"thumbnail", "thumb"}:
        x, y, w, h = 9.6, 5.0, 2.9, 1.65
    else:
        x, y, w, h = 6.55, 1.15, 6.1, 5.4

    if (
        placement.role not in {"background", "full_bleed", "full-bleed"}
        and placement.usage_mode not in {"stretch", "fill", "cover"}
    ):
        x, y, w, h = _fit_contain(image_size[0], image_size[1], x, y, w, h)
    return _emu(x), _emu(y), _emu(w), _emu(h)


def _xml_text(value: str) -> str:
    return escape(value, {'"': "&quot;"})


def _hex_color(value: Any, fallback: str) -> str:
    cleaned = _clean_text(value).lstrip("#").upper()
    if re.fullmatch(r"[0-9A-F]{6}", cleaned):
        return cleaned
    return fallback


def _normalize_theme(theme: dict[str, Any] | str | None) -> ThemeSpec:
    if isinstance(theme, str):
        theme = {"mode": theme}
    raw = _as_dict(theme, "theme") if theme is not None else {}
    mode = _clean_text(raw.get("mode") or raw.get("name") or "light").lower()
    if mode in {"dark", "midnight"}:
        spec = ThemeSpec(
            mode="dark",
            canvas="0F172A",
            ink="FFFFFF",
            body="E2E8F0",
            muted="94A3B8",
            panel="1E293B",
            panel_alt="334155",
            rule="475569",
            accent="60A5FA",
            accent_soft="1E3A8A",
        )
    else:
        spec = ThemeSpec()
    spec.canvas = _hex_color(raw.get("canvas") or raw.get("background"), spec.canvas)
    spec.ink = _hex_color(raw.get("ink") or raw.get("text"), spec.ink)
    spec.body = _hex_color(raw.get("body"), spec.body)
    spec.muted = _hex_color(raw.get("muted"), spec.muted)
    spec.panel = _hex_color(raw.get("panel"), spec.panel)
    spec.panel_alt = _hex_color(raw.get("panel_alt"), spec.panel_alt)
    spec.rule = _hex_color(raw.get("rule"), spec.rule)
    spec.accent = _hex_color(raw.get("accent") or raw.get("brand"), spec.accent)
    spec.accent_soft = _hex_color(raw.get("accent_soft"), spec.accent_soft)
    font_family = _clean_text(raw.get("font_family") or raw.get("font"))
    if font_family:
        spec.font_family = font_family
    return spec


def _installed_font_families() -> set[str]:
    executable = shutil.which("fc-list")
    if not executable:
        return set()
    result = subprocess.run(
        [executable, "--format=%{family}\n"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return set()
    families: set[str] = set()
    for line in result.stdout.splitlines():
        for family in line.split(","):
            cleaned = family.strip().casefold()
            if cleaned:
                families.add(cleaned)
    return families


def _resolve_custom_compose_font(
    compose_data: dict[str, Any],
    theme: ThemeSpec,
    slides: list[SlideSpec],
) -> dict[str, Any]:
    raw_theme = _as_dict(compose_data.get("theme"), "compose_spec.theme")
    candidates = [theme.font_family]
    candidates.extend(
        _clean_text(item)
        for item in _as_list(
            raw_theme.get("font_fallbacks"),
            "compose_spec.theme.font_fallbacks",
        )
        if _clean_text(item)
    )
    installed = _installed_font_families()
    selected = next(
        (candidate for candidate in candidates if candidate.casefold() in installed),
        "",
    )
    if not selected:
        if _as_bool(raw_theme.get("require_installed_font")):
            raise ValueError(
                "custom_compose font QA failed: none of the declared font families "
                f"is installed ({', '.join(candidates)}).",
            )
        selected = theme.font_family
    original = theme.font_family
    theme.font_family = selected
    for slide in slides:
        for layer in slide.custom_layers:
            explicit = _clean_text(layer.get("font_face") or layer.get("font_family"))
            if explicit and explicit == original:
                layer["font_face"] = selected
    return {
        "requested": original,
        "fallbacks": candidates[1:],
        "selected": selected,
        "verifiedInstalled": selected.casefold() in installed,
    }


def _has_explicit_visual_theme(theme: dict[str, Any] | str | None) -> bool:
    if not isinstance(theme, dict):
        return False
    design_keys = {
        "accent",
        "brand",
        "canvas",
        "background",
        "ink",
        "text",
        "body",
        "muted",
        "panel",
        "panel_alt",
        "rule",
        "accent_soft",
        "font_family",
        "font",
    }
    return any(_clean_text(theme.get(key)) for key in design_keys)


def _extract_theme_color(theme_xml: str, token: str) -> str:
    pattern = (
        rf"<a:{token}>.*?<a:srgbClr[^>]+val=\"([0-9A-Fa-f]{{6}})\""
    )
    match = re.search(pattern, theme_xml, flags=re.S)
    return match.group(1).upper() if match else ""


def _extract_theme_font(theme_xml: str) -> str:
    match = re.search(r'<a:majorFont>.*?<a:latin[^>]+typeface="([^"]+)"', theme_xml, flags=re.S)
    if match:
        return match.group(1)
    match = re.search(r'<a:latin[^>]+typeface="([^"]+)"', theme_xml, flags=re.S)
    return match.group(1) if match else ""


def _inspect_template_pptx(template_path: str | None) -> dict[str, Any]:
    if not template_path:
        return {}
    path = _resolve_path(template_path)
    if not path.exists():
        raise ValueError(f"template_path does not exist: {path}")
    if path.suffix.lower() != ".pptx":
        raise ValueError("template_path must point to a .pptx file.")
    with zipfile.ZipFile(path) as deck:
        names = deck.namelist()
        slide_count = sum(
            1
            for name in names
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )
        media_count = sum(1 for name in names if name.startswith("ppt/media/"))
        placeholder_count = 0
        for name in names:
            if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                xml = deck.read(name).decode("utf-8", errors="ignore")
                placeholder_count += xml.count("<p:ph")
        theme_xml = ""
        if "ppt/theme/theme1.xml" in names:
            theme_xml = deck.read("ppt/theme/theme1.xml").decode(
                "utf-8",
                errors="ignore",
            )
    canvas = _extract_theme_color(theme_xml, "lt1")
    ink = _extract_theme_color(theme_xml, "dk1")
    body = _extract_theme_color(theme_xml, "dk2")
    panel = _extract_theme_color(theme_xml, "lt2")
    accent = _extract_theme_color(theme_xml, "accent1")
    font_family = _extract_theme_font(theme_xml)
    return {
        "path": str(path),
        "source_slide_count": slide_count,
        "media_count": media_count,
        "placeholder_count": placeholder_count,
        "theme": {
            "canvas": canvas,
            "ink": ink,
            "body": body,
            "panel": panel,
            "accent": accent,
            "font_family": font_family,
        },
    }


def _theme_from_template(template_info: dict[str, Any]) -> ThemeSpec:
    raw = template_info.get("theme") or {}
    if not raw:
        return ThemeSpec()
    canvas = _hex_color(raw.get("canvas"), ThemeSpec.canvas)
    ink = _hex_color(raw.get("ink"), ThemeSpec.ink)
    is_dark = int(canvas[:2], 16) + int(canvas[2:4], 16) + int(canvas[4:], 16) < 320
    spec = _normalize_theme("dark" if is_dark else "light")
    spec.canvas = canvas
    spec.ink = ink
    spec.body = _hex_color(raw.get("body"), spec.body)
    spec.panel = _hex_color(raw.get("panel"), spec.panel)
    spec.accent = _hex_color(raw.get("accent"), spec.accent)
    font_family = _clean_text(raw.get("font_family"))
    if font_family:
        spec.font_family = font_family
    return spec


def _solid_fill(color: str | None) -> str:
    if not color:
        return "<a:noFill/>"
    return f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'


def _line(color: str | None, width_pt: float = 1.0) -> str:
    if not color:
        return "<a:ln><a:noFill/></a:ln>"
    return (
        f'<a:ln w="{int(width_pt * LINE_WIDTH_PT)}">'
        f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill></a:ln>'
    )


def _paragraph(
    text: str,
    *,
    size_pt: int,
    color: str,
    font_face: str,
    bold: bool = False,
) -> str:
    bold_attr = ' b="1"' if bold else ""
    return (
        '<a:p><a:r><a:rPr lang="zh-CN" sz="'
        f'{size_pt * 100}"{bold_attr}><a:solidFill><a:srgbClr val="{color}"/>'
        f'</a:solidFill><a:latin typeface="{_xml_text(font_face)}"/>'
        f'<a:ea typeface="{_xml_text(font_face)}"/>'
        "</a:rPr><a:t>"
        f"{_xml_text(text)}</a:t></a:r></a:p>"
    )


def _text_box(
    shape_id: int,
    name: str,
    x: float,
    y: float,
    w: float,
    h: float,
    paragraphs: list[str],
    *,
    fill: str | None = None,
    line: str | None = None,
    margin: float = 0.06,
    geometry: str = "rect",
) -> str:
    inset = _emu(margin)
    return f"""
<p:sp>
  <p:nvSpPr>
    <p:cNvPr id="{shape_id}" name="{_xml_text(name)}"/>
    <p:cNvSpPr txBox="1"/>
    <p:nvPr/>
  </p:nvSpPr>
  <p:spPr>
    <a:xfrm><a:off x="{_emu(x)}" y="{_emu(y)}"/><a:ext cx="{_emu(w)}" cy="{_emu(h)}"/></a:xfrm>
    <a:prstGeom prst="{geometry}"><a:avLst/></a:prstGeom>
    {_solid_fill(fill)}
    {_line(line)}
  </p:spPr>
  <p:txBody>
    <a:bodyPr wrap="square" anchor="t" lIns="{inset}" tIns="{inset}" rIns="{inset}" bIns="{inset}"/>
    <a:lstStyle/>
    {''.join(paragraphs)}
  </p:txBody>
</p:sp>"""


def _shape_box(
    shape_id: int,
    name: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: str | None,
    line: str | None = None,
    geometry: str = "rect",
    line_width_pt: float = 1.0,
) -> str:
    return f"""
<p:sp>
  <p:nvSpPr>
    <p:cNvPr id="{shape_id}" name="{_xml_text(name)}"/>
    <p:cNvSpPr/>
    <p:nvPr/>
  </p:nvSpPr>
  <p:spPr>
    <a:xfrm><a:off x="{_emu(x)}" y="{_emu(y)}"/><a:ext cx="{_emu(w)}" cy="{_emu(h)}"/></a:xfrm>
    <a:prstGeom prst="{geometry}"><a:avLst/></a:prstGeom>
    {_solid_fill(fill)}
    {_line(line, line_width_pt)}
  </p:spPr>
</p:sp>"""


def _compose_paragraph(
    text: str,
    *,
    size_pt: float,
    color: str,
    font_face: str,
    bold: bool = False,
    italic: bool = False,
    align: str = "left",
) -> str:
    align_value = {
        "left": "l",
        "center": "ctr",
        "right": "r",
        "justify": "just",
    }.get(align, "l")
    bold_attr = ' b="1"' if bold else ""
    italic_attr = ' i="1"' if italic else ""
    return (
        f'<a:p><a:pPr algn="{align_value}"/><a:r><a:rPr lang="zh-CN" '
        f'sz="{int(round(size_pt * 100))}"{bold_attr}{italic_attr}>'
        f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
        f'<a:latin typeface="{_xml_text(font_face)}"/>'
        f'<a:ea typeface="{_xml_text(font_face)}"/>'
        f'</a:rPr><a:t>{_xml_text(text)}</a:t></a:r></a:p>'
    )


def _compose_text_box(
    shape_id: int,
    layer: dict[str, Any],
    theme: ThemeSpec,
) -> str:
    text = _clean_text(layer.get("text"))
    font_face = _clean_text(layer.get("font_face") or layer.get("font_family")) or theme.font_family
    size_pt = _optional_float(layer.get("font_size") or layer.get("size")) or 20.0
    color = _hex_color(layer.get("color"), theme.ink)
    align = _clean_text(layer.get("align")).lower() or "left"
    valign = {
        "top": "t",
        "middle": "ctr",
        "center": "ctr",
        "bottom": "b",
    }.get(_clean_text(layer.get("valign")).lower(), "t")
    margin = _optional_float(layer.get("margin"))
    inset = _emu(0.04 if margin is None else margin)
    fill = _hex_color(layer.get("fill"), "") or None
    line_color = _hex_color(layer.get("line"), "") or None
    geometry = _clean_text(layer.get("geometry")) or "rect"
    paragraphs = [
        _compose_paragraph(
            line,
            size_pt=size_pt,
            color=color,
            font_face=font_face,
            bold=_as_bool(layer.get("bold")),
            italic=_as_bool(layer.get("italic")),
            align=align,
        )
        for line in (text.splitlines() or [""])
    ]
    return f"""
<p:sp>
  <p:nvSpPr>
    <p:cNvPr id="{shape_id}" name="{_xml_text(_clean_text(layer.get('name')))}"/>
    <p:cNvSpPr txBox="1"/>
    <p:nvPr/>
  </p:nvSpPr>
  <p:spPr>
    <a:xfrm><a:off x="{_emu(float(layer['x']))}" y="{_emu(float(layer['y']))}"/><a:ext cx="{_emu(float(layer['w']))}" cy="{_emu(float(layer['h']))}"/></a:xfrm>
    <a:prstGeom prst="{_xml_text(geometry)}"><a:avLst/></a:prstGeom>
    {_solid_fill(fill)}
    {_line(line_color, _optional_float(layer.get('line_width')) or 1.0)}
  </p:spPr>
  <p:txBody>
    <a:bodyPr wrap="square" anchor="{valign}" lIns="{inset}" tIns="{inset}" rIns="{inset}" bIns="{inset}"/>
    <a:lstStyle/>
    {''.join(paragraphs)}
  </p:txBody>
</p:sp>"""


def _compose_layer_float(layer: dict[str, Any], key: str) -> float:
    value = _optional_float(layer.get(key))
    if value is None:
        raise ValueError(
            f"custom layer {_clean_text(layer.get('name'))!r} requires numeric {key}.",
        )
    return value


def _validate_custom_layers(slides: list[SlideSpec]) -> None:
    allowed_types = {"text", "shape", "line", "image"}
    allowed_geometries = {
        "rect",
        "roundRect",
        "ellipse",
        "chevron",
        "trapezoid",
        "triangle",
        "diamond",
        "hexagon",
        "parallelogram",
    }
    for slide_no, slide in enumerate(slides, start=1):
        if not slide.custom_layers:
            raise ValueError(
                f"custom_compose slide {slide_no} must include a non-empty layers list.",
            )
        names: set[str] = set()
        type_counts: dict[str, int] = {}
        group_counts: dict[str, int] = {}
        visible_text: list[str] = []
        custom_image_count = sum(
            1
            for layer in slide.custom_layers
            if _clean_text(layer.get("type")).lower() == "image"
        )
        if len(slide.images) != custom_image_count:
            raise ValueError(
                "custom_compose slides must declare images only as image layers; "
                f"slide {slide_no} has {custom_image_count} image layer(s) and "
                f"{len(slide.images)} normalized image placement(s).",
            )
        for layer_no, layer in enumerate(slide.custom_layers, start=1):
            layer_type = _clean_text(layer.get("type")).lower()
            if layer_type not in allowed_types:
                raise ValueError(
                    f"custom layer {slide_no}.{layer_no} has unsupported type {layer_type!r}.",
                )
            name = _clean_text(layer.get("name"))
            if not name:
                raise ValueError(f"custom layer {slide_no}.{layer_no} requires name.")
            if name in names:
                raise ValueError(f"custom layer name must be unique per slide: {name}.")
            names.add(name)
            x = _compose_layer_float(layer, "x")
            y = _compose_layer_float(layer, "y")
            w = _compose_layer_float(layer, "w")
            h = _compose_layer_float(layer, "h")
            if x < 0 or y < 0 or w <= 0 or h <= 0:
                raise ValueError(f"custom layer {name!r} has invalid bounds.")
            if x + w > SLIDE_WIDTH_IN + 0.001 or y + h > SLIDE_HEIGHT_IN + 0.001:
                raise ValueError(f"custom layer {name!r} is outside the 16:9 canvas.")
            geometry = _clean_text(layer.get("geometry")) or "rect"
            if geometry not in allowed_geometries:
                raise ValueError(f"custom layer {name!r} has unsupported geometry {geometry!r}.")
            if layer_type == "text":
                text = _clean_text(layer.get("text"))
                if not text:
                    raise ValueError(f"custom text layer {name!r} must not be empty.")
                visible_text.append(text)
            if layer_type == "image" and not _entry_asset_path(layer):
                raise ValueError(f"custom image layer {name!r} requires asset_path or path.")
            type_counts[layer_type] = type_counts.get(layer_type, 0) + 1
            group = _clean_text(layer.get("semantic_group"))
            if group:
                group_counts[group] = group_counts.get(group, 0) + 1

        expected = slide.expected_content
        for required_name in _as_list(
            expected.get("required_layer_names"),
            "expected_content.required_layer_names",
        ):
            if _clean_text(required_name) not in names:
                raise ValueError(
                    f"custom slide {slide_no} is missing required layer {_clean_text(required_name)!r}.",
                )
        joined_text = "\n".join(visible_text)
        for required_text in _as_list(
            expected.get("required_text"),
            "expected_content.required_text",
        ):
            required = _clean_text(required_text)
            if required and required not in joined_text:
                raise ValueError(
                    f"custom slide {slide_no} is missing required text {required!r}.",
                )
        expected_types = _as_dict(
            expected.get("layer_type_counts"),
            "expected_content.layer_type_counts",
        )
        for layer_type, expected_count in expected_types.items():
            if type_counts.get(layer_type, 0) != int(expected_count):
                raise ValueError(
                    f"custom slide {slide_no} expected {expected_count} {layer_type} layer(s), "
                    f"got {type_counts.get(layer_type, 0)}.",
                )
        expected_groups = _as_dict(
            expected.get("semantic_group_counts"),
            "expected_content.semantic_group_counts",
        )
        for group, expected_count in expected_groups.items():
            if group_counts.get(group, 0) != int(expected_count):
                raise ValueError(
                    f"custom slide {slide_no} expected {expected_count} {group!r} layer(s), "
                    f"got {group_counts.get(group, 0)}.",
                )


def _background_shape(shape_id: int, theme: ThemeSpec) -> str:
    return _shape_box(
        shape_id,
        "Background",
        0,
        0,
        SLIDE_WIDTH_IN,
        SLIDE_HEIGHT_IN,
        fill=theme.canvas,
        line=None,
    )


def _picture(
    shape_id: int,
    rel_id: str,
    name: str,
    descr: str,
    box: tuple[int, int, int, int],
) -> str:
    x, y, w, h = box
    return f"""
<p:pic>
  <p:nvPicPr>
    <p:cNvPr id="{shape_id}" name="{_xml_text(name)}" descr="{_xml_text(descr)}"/>
    <p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>
    <p:nvPr/>
  </p:nvPicPr>
  <p:blipFill>
    <a:blip r:embed="{rel_id}"/>
    <a:stretch><a:fillRect/></a:stretch>
  </p:blipFill>
  <p:spPr>
    <a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>
    <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
  </p:spPr>
</p:pic>"""


def _infer_layout(slide: SlideSpec, slide_no: int) -> str:
    layout = _resolve_layout_name(slide.layout)
    if layout and layout != "auto":
        return layout
    searchable = "\n".join(
        [
            slide.title,
            slide.subtitle,
            slide.body,
            *slide.bullets,
        ],
    ).lower()
    if slide.table:
        return "table"
    if slide.metrics:
        return "metrics"
    if slide.steps:
        if re.search(r"路线|路徑|roadmap|milestone|里程碑|阶段|phase|第\s*\d+", searchable):
            return "roadmap"
        return "process"
    if slide.items:
        return "cards"
    if slide.columns:
        return "two_column"
    if slide.images and slide_no == 1:
        return "image_hero"
    has_detail_content = bool(slide.body or slide.bullets)
    if not has_detail_content:
        return "section"
    if re.search(
        r"实施路线|路线图|roadmap|timeline|milestone|里程碑|阶段|phase\s*\d+|第\s*\d+\s*[-~至到]?\s*\d*\s*周",
        searchable,
    ):
        return "roadmap"
    if re.search(r"资源|团队|配置|风险|策略|矩阵|清单|验收|标准", searchable):
        return "cards"
    if slide_no == 1:
        return "section"
    if 2 <= len(slide.bullets) <= 4:
        return "cards"
    if slide.bullets:
        return "process"
    return "content"


def _add_title_block(
    shapes: list[str],
    shape_id: int,
    slide: SlideSpec,
    theme: ThemeSpec,
    *,
    x: float = 0.62,
    y: float = 0.48,
    w: float = 11.9,
    title_size: int = 36,
) -> int:
    if slide.kicker:
        shapes.append(
            _text_box(
                shape_id,
                "Kicker",
                x,
                y,
                w,
                0.34,
                [
                    _paragraph(
                        slide.kicker.upper(),
                        size_pt=12,
                        color=theme.accent,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        y += 0.35
    if slide.title:
        shapes.append(
            _text_box(
                shape_id,
                "Title",
                x,
                y,
                w,
                0.86,
                [
                    _paragraph(
                        slide.title,
                        size_pt=title_size,
                        color=theme.ink,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        y += 0.82
    if slide.subtitle:
        shapes.append(
            _text_box(
                shape_id,
                "Subtitle",
                x,
                y,
                min(w, 8.9),
                0.48,
                [
                    _paragraph(
                        slide.subtitle,
                        size_pt=17,
                        color=theme.muted,
                        font_face=theme.font_family,
                    ),
                ],
            ),
        )
        shape_id += 1
    shapes.append(
        _shape_box(
            shape_id,
            "Header Rule",
            x,
            1.64,
            min(w, 11.9),
            0.02,
            fill=theme.rule,
            line=None,
        ),
    )
    return shape_id + 1


def _body_paragraphs(slide: SlideSpec, theme: ThemeSpec) -> list[str]:
    paragraphs: list[str] = []
    if slide.body:
        paragraphs.append(
            _paragraph(
                slide.body,
                size_pt=17,
                color=theme.body,
                font_face=theme.font_family,
            ),
        )
    paragraphs.extend(
        _paragraph(
            f"- {bullet}",
            size_pt=16,
            color=theme.body,
            font_face=theme.font_family,
        )
        for bullet in slide.bullets
    )
    return paragraphs


def _layout_image_hero(
    shapes: list[str],
    shape_id: int,
    slide: SlideSpec,
    theme: ThemeSpec,
    *,
    variant: str = "split",
) -> int:
    if variant == "cover_field":
        shapes.append(
            _shape_box(
                shape_id,
                "Cover Field Frame",
                0.42,
                0.44,
                12.5,
                6.54,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Cover Title Lockup",
                0.92,
                4.26,
                7.38,
                1.76,
                fill=theme.canvas,
                line=theme.rule,
            ),
        )
        shape_id += 1
        if slide.kicker:
            shapes.append(
                _text_box(
                    shape_id,
                    "Cover Kicker",
                    1.24,
                    4.48,
                    6.66,
                    0.24,
                    [
                        _paragraph(
                            slide.kicker.upper(),
                            size_pt=10,
                            color=theme.accent,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        if slide.title:
            shapes.append(
                _text_box(
                    shape_id,
                    "Cover Title",
                    1.24,
                    4.78,
                    6.72,
                    0.62,
                    [
                        _paragraph(
                            slide.title,
                            size_pt=28,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        if slide.subtitle:
            shapes.append(
                _text_box(
                    shape_id,
                    "Cover Subtitle",
                    1.24,
                    5.48,
                    6.72,
                    0.3,
                    [
                        _paragraph(
                            slide.subtitle,
                            size_pt=13,
                            color=theme.muted,
                            font_face=theme.font_family,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "cover_masthead":
        shapes.append(
            _shape_box(
                shape_id,
                "Cover Masthead Band",
                0,
                0,
                SLIDE_WIDTH_IN,
                2.18,
                fill=theme.accent,
                line=None,
            ),
        )
        shape_id += 1
        if slide.title:
            shapes.append(
                _text_box(
                    shape_id,
                    "Cover Masthead Title",
                    0.72,
                    0.76,
                    8.4,
                    0.72,
                    [
                        _paragraph(
                            slide.title,
                            size_pt=30,
                            color="FFFFFF",
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        if slide.subtitle:
            shapes.append(
                _text_box(
                    shape_id,
                    "Cover Masthead Subtitle",
                    0.76,
                    1.46,
                    7.8,
                    0.32,
                    [
                        _paragraph(
                            slide.subtitle,
                            size_pt=13,
                            color="FFFFFF",
                            font_face=theme.font_family,
                        ),
                    ],
                ),
            )
            shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Cover Media Strip",
                0.72,
                2.72,
                11.88,
                2.88,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        paragraphs = _body_paragraphs(slide, theme)
        if paragraphs:
            shapes.append(
                _text_box(
                    shape_id,
                    "Cover Summary",
                    0.82,
                    5.84,
                    7.8,
                    0.44,
                    paragraphs,
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "full_bleed":
        shapes.append(
            _shape_box(
                shape_id,
                "Hero Full Bleed Frame",
                0.42,
                0.48,
                12.48,
                6.44,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Hero Overlay Panel",
                0.78,
                4.72,
                6.68,
                1.48,
                fill=theme.canvas,
                line=theme.rule,
            ),
        )
        shape_id += 1
        if slide.kicker:
            shapes.append(
                _text_box(
                    shape_id,
                    "Hero Overlay Kicker",
                    1.06,
                    4.94,
                    5.9,
                    0.24,
                    [
                        _paragraph(
                            slide.kicker.upper(),
                            size_pt=10,
                            color=theme.accent,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        if slide.title:
            shapes.append(
                _text_box(
                    shape_id,
                    "Hero Overlay Title",
                    1.06,
                    5.16,
                    5.9,
                    0.54,
                    [
                        _paragraph(
                            slide.title,
                            size_pt=24,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        if slide.subtitle:
            shapes.append(
                _text_box(
                    shape_id,
                    "Hero Overlay Subtitle",
                    1.06,
                    5.7,
                    5.9,
                    0.28,
                    [
                        _paragraph(
                            slide.subtitle,
                            size_pt=12,
                            color=theme.muted,
                            font_face=theme.font_family,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "band":
        shape_id = _add_title_block(
            shapes,
            shape_id,
            slide,
            theme,
            x=0.72,
            y=0.58,
            w=11.88,
            title_size=32,
        )
        shapes.append(
            _shape_box(
                shape_id,
                "Hero Band Media Frame",
                0.72,
                2.08,
                11.88,
                2.72,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Hero Caption Band",
                0.72,
                5.02,
                11.88,
                1.05,
                fill=theme.accent_soft,
                line=None,
            ),
        )
        shape_id += 1
        paragraphs = _body_paragraphs(slide, theme)
        if paragraphs:
            shapes.append(
                _text_box(
                    shape_id,
                    "Hero Band Caption",
                    1.02,
                    5.24,
                    11.18,
                    0.52,
                    paragraphs,
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "mosaic":
        shape_id = _add_title_block(
            shapes,
            shape_id,
            slide,
            theme,
            x=0.72,
            y=0.56,
            w=6.1,
            title_size=34,
        )
        paragraphs = _body_paragraphs(slide, theme)
        if paragraphs:
            shapes.append(
                _text_box(shape_id, "Body", 0.78, 2.16, 4.8, 1.56, paragraphs),
            )
            shape_id += 1
        frames = [
            (5.96, 1.96, 3.06, 2.16),
            (9.28, 1.96, 3.02, 2.16),
            (5.96, 4.38, 6.34, 1.62),
        ]
        for idx, (x, y, w, h) in enumerate(frames, start=1):
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Hero Mosaic Frame {idx}",
                    x,
                    y,
                    w,
                    h,
                    fill=theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "poster":
        shapes.append(
            _shape_box(
                shape_id,
                "Hero Poster Frame",
                0.58,
                0.54,
                12.18,
                6.22,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Hero Poster Title Block",
                1.02,
                1.12,
                5.68,
                4.78,
                fill=theme.canvas,
                line=theme.rule,
            ),
        )
        shape_id += 1
        if slide.kicker:
            shapes.append(
                _text_box(
                    shape_id,
                    "Hero Poster Kicker",
                    1.36,
                    1.48,
                    4.8,
                    0.28,
                    [
                        _paragraph(
                            slide.kicker.upper(),
                            size_pt=10,
                            color=theme.accent,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        if slide.title:
            shapes.append(
                _text_box(
                    shape_id,
                    "Hero Poster Title",
                    1.36,
                    1.96,
                    4.86,
                    1.26,
                    [
                        _paragraph(
                            slide.title,
                            size_pt=34,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        if slide.subtitle:
            shapes.append(
                _text_box(
                    shape_id,
                    "Hero Poster Subtitle",
                    1.38,
                    3.42,
                    4.72,
                    0.46,
                    [
                        _paragraph(
                            slide.subtitle,
                            size_pt=15,
                            color=theme.muted,
                            font_face=theme.font_family,
                        ),
                    ],
                ),
            )
            shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Hero Poster Accent Panel",
                7.08,
                1.08,
                4.86,
                4.9,
                fill=theme.accent,
                line=None,
            ),
        )
        shape_id += 1
        return shape_id

    if variant == "device":
        shape_id = _add_title_block(
            shapes,
            shape_id,
            slide,
            theme,
            x=0.72,
            y=0.66,
            w=5.4,
            title_size=34,
        )
        paragraphs = _body_paragraphs(slide, theme)
        if paragraphs:
            shapes.append(
                _text_box(shape_id, "Body", 0.78, 2.48, 4.9, 1.24, paragraphs),
            )
            shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Hero Device Frame",
                6.38,
                1.02,
                5.9,
                4.84,
                fill=theme.ink,
                line=theme.rule,
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Hero Device Screen",
                6.68,
                1.34,
                5.3,
                4.2,
                fill=theme.canvas,
                line=None,
            ),
        )
        shape_id += 1
        for idx in range(3):
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Hero Device UI Row {idx + 1}",
                    7.02,
                    1.76 + idx * 0.9,
                    4.62,
                    0.42,
                    fill=theme.panel_alt if idx % 2 else theme.accent_soft,
                    line=None,
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "gallery":
        shape_id = _add_title_block(
            shapes,
            shape_id,
            slide,
            theme,
            x=0.72,
            y=0.54,
            w=10.8,
            title_size=32,
        )
        shapes.append(
            _shape_box(
                shape_id,
                "Hero Gallery Strip",
                0.72,
                2.02,
                11.88,
                3.68,
                fill=theme.panel_alt,
                line=None,
            ),
        )
        shape_id += 1
        frames = [
            (1.02, 2.36, 2.82, 2.58),
            (4.04, 2.2, 3.18, 2.9),
            (7.42, 2.36, 2.82, 2.58),
            (10.44, 2.56, 1.86, 2.18),
        ]
        for idx, (x, y, w, h) in enumerate(frames, start=1):
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Hero Gallery Frame {idx}",
                    x,
                    y,
                    w,
                    h,
                    fill=theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
        return shape_id

    shape_id = _add_title_block(
        shapes,
        shape_id,
        slide,
        theme,
        x=0.7,
        y=0.72,
        w=5.75,
        title_size=38,
    )
    paragraphs = _body_paragraphs(slide, theme)
    if paragraphs:
        shapes.append(
            _text_box(shape_id, "Body", 0.76, 2.56, 5.55, 2.48, paragraphs),
        )
        shape_id += 1
    shapes.append(
        _shape_box(
            shape_id,
            "Hero Media Frame",
            7.02,
            0.72,
            5.7,
            6.05,
            fill=theme.panel,
            line=theme.rule,
        ),
    )
    return shape_id + 1


def _layout_cards(
    shapes: list[str],
    shape_id: int,
    slide: SlideSpec,
    theme: ThemeSpec,
) -> int:
    shape_id = _add_title_block(shapes, shape_id, slide, theme)
    items = slide.items or _items_from_bullets(slide.bullets, 4)
    if not items and slide.body:
        items = [{"title": slide.body, "body": ""}]
    count = min(max(len(items), 1), 4)
    gap = 0.24
    x0 = 0.72
    total_w = 11.88
    card_w = (total_w - gap * (count - 1)) / count
    for idx, item in enumerate(items[:count], start=1):
        x = x0 + (idx - 1) * (card_w + gap)
        shapes.append(
            _shape_box(
                shape_id,
                f"Card {idx}",
                x,
                2.18,
                card_w,
                3.95,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                f"Card Accent {idx}",
                x,
                2.18,
                card_w,
                0.08,
                fill=theme.accent,
                line=None,
            ),
        )
        shape_id += 1
        shapes.append(
            _text_box(
                shape_id,
                f"Card Title {idx}",
                x + 0.24,
                2.54,
                card_w - 0.48,
                0.62,
                [
                    _paragraph(
                        item.get("title", ""),
                        size_pt=20,
                        color=theme.ink,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        if item.get("body"):
            shapes.append(
                _text_box(
                    shape_id,
                    f"Card Body {idx}",
                    x + 0.24,
                    3.28,
                    card_w - 0.48,
                    1.9,
                    [
                        _paragraph(
                            item["body"],
                            size_pt=15,
                            color=theme.body,
                            font_face=theme.font_family,
                        ),
                    ],
                ),
            )
            shape_id += 1
    return shape_id


PROCESS_ADVANCED_VARIANTS: dict[str, tuple[str, str]] = {
    "milestone": ("Process Milestone Track", "milestone"),
    "ladder": ("Process Ladder Rail", "ladder"),
    "kanban": ("Process Kanban Column", "kanban"),
    "funnel": ("Process Funnel Stage", "funnel"),
    "pyramid": ("Process Pyramid Tier", "pyramid"),
    "loopback": ("Process Loopback Rail", "loopback"),
    "sprint": ("Process Sprint Lane", "sprint"),
    "dependency": ("Process Dependency Node", "dependency"),
    "gate": ("Process Gate Checkpoint", "gate"),
    "wave": ("Process Wave Segment", "wave"),
    "ribbon": ("Process Ribbon Segment", "ribbon"),
    "orbit": ("Process Orbit Ring", "orbit"),
    "scorecard": ("Process Scorecard Row", "scorecard"),
    "timeline_cards": ("Process Timeline Card", "timeline_cards"),
    "cascade": ("Process Cascade Card", "cascade"),
    "quadrant": ("Process Quadrant Stage", "quadrant"),
    "bridge": ("Process Bridge Deck", "bridge"),
    "conveyor": ("Process Conveyor Track", "conveyor"),
    "decision_tree": ("Process Decision Diamond", "decision_tree"),
    "matrix": ("Process Matrix Cell", "matrix"),
    "layered_timeline": ("Process Layered Timeline Rail", "layered_timeline"),
    "compass": ("Process Compass Hub", "compass"),
    "map_route": ("Process Map Route", "map_route"),
    "pulse": ("Process Pulse Node", "pulse"),
    "cluster": ("Process Cluster Node", "cluster"),
    "evidence": ("Process Evidence Rail", "evidence"),
    "calendar": ("Process Calendar Slot", "calendar"),
    "handoff": ("Process Handoff Lane", "handoff"),
}


def _layout_advanced_process(
    shapes: list[str],
    shape_id: int,
    slide: SlideSpec,
    theme: ThemeSpec,
    steps: list[dict[str, str]],
    count: int,
    variant: str,
) -> int | None:
    config = PROCESS_ADVANCED_VARIANTS.get(variant)
    if not config:
        return None
    marker, style = config
    active_steps = steps[:count]

    def step_title(step: dict[str, str], idx: int) -> str:
        return step.get("title") or f"Step {idx}"

    def step_body(step: dict[str, str]) -> str:
        return step.get("body") or ""

    def label(
        name: str,
        x: float,
        y: float,
        w: float,
        h: float,
        text: str,
        *,
        size_pt: int = 13,
        color: str | None = None,
        bold: bool = False,
    ) -> None:
        nonlocal shape_id
        if not text:
            return
        shapes.append(
            _text_box(
                shape_id,
                name,
                x,
                y,
                w,
                h,
                [
                    _paragraph(
                        text,
                        size_pt=size_pt,
                        color=color or theme.ink,
                        font_face=theme.font_family,
                        bold=bold,
                    ),
                ],
            ),
        )
        shape_id += 1

    if style == "milestone":
        shapes.append(
            _shape_box(
                shape_id,
                marker,
                0.94,
                4.06,
                11.42,
                0.08,
                fill=theme.rule,
                line=None,
            ),
        )
        shape_id += 1
        gap = 11.0 / max(count - 1, 1)
        for idx, step in enumerate(active_steps, start=1):
            x = 1.08 + (idx - 1) * gap
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Milestone Node {idx}",
                    x,
                    3.72,
                    0.72,
                    0.72,
                    fill=theme.accent,
                    line=None,
                    geometry="ellipse",
                ),
            )
            shape_id += 1
            label(
                f"Process Milestone Label {idx}",
                x - 0.34,
                4.72,
                1.4,
                0.36,
                step_title(step, idx),
                bold=True,
            )
        return shape_id

    if style == "ladder":
        shapes.append(
            _shape_box(
                shape_id,
                marker,
                2.1,
                2.08,
                0.08,
                4.28,
                fill=theme.accent,
                line=None,
            ),
        )
        shape_id += 1
        for idx, step in enumerate(active_steps, start=1):
            y = 2.12 + (idx - 1) * 0.82
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Ladder Rung {idx}",
                    2.1,
                    y,
                    9.34,
                    0.06,
                    fill=theme.rule,
                    line=None,
                ),
            )
            shape_id += 1
            label(
                f"Process Ladder Label {idx}",
                2.58,
                y - 0.14,
                3.2,
                0.34,
                step_title(step, idx),
                bold=True,
            )
        return shape_id

    if style == "kanban":
        column_w = 3.62
        for idx, step in enumerate(active_steps[:3], start=1):
            x = 0.88 + (idx - 1) * 3.86
            shapes.append(
                _shape_box(
                    shape_id,
                    f"{marker} {idx}",
                    x,
                    2.08,
                    column_w,
                    4.32,
                    fill=theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            label(
                f"Process Kanban Header {idx}",
                x + 0.22,
                2.34,
                column_w - 0.44,
                0.34,
                step_title(step, idx),
                bold=True,
            )
            for card_idx in range(2):
                shapes.append(
                    _shape_box(
                        shape_id,
                        f"Process Kanban Card {idx}-{card_idx + 1}",
                        x + 0.22,
                        3.0 + card_idx * 1.02,
                        column_w - 0.44,
                        0.74,
                        fill=theme.canvas,
                        line=theme.rule,
                    ),
                )
                shape_id += 1
        return shape_id

    if style == "funnel":
        for idx, step in enumerate(active_steps, start=1):
            w = 10.4 - (idx - 1) * 1.18
            x = 6.66 - w / 2
            y = 2.12 + (idx - 1) * 0.76
            shapes.append(
                _shape_box(
                    shape_id,
                    f"{marker} {idx}",
                    x,
                    y,
                    w,
                    0.56,
                    fill=theme.accent if idx == 1 else theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            label(
                f"Process Funnel Label {idx}",
                x + 0.28,
                y + 0.12,
                w - 0.56,
                0.24,
                step_title(step, idx),
                color="FFFFFF" if idx == 1 else theme.ink,
                bold=True,
            )
        return shape_id

    if style == "pyramid":
        for idx, step in enumerate(active_steps, start=1):
            w = 3.0 + (count - idx) * 1.24
            x = 6.66 - w / 2
            y = 2.28 + (idx - 1) * 0.72
            shapes.append(
                _shape_box(
                    shape_id,
                    f"{marker} {idx}",
                    x,
                    y,
                    w,
                    0.62,
                    fill=theme.accent if idx == 1 else theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            label(
                f"Process Pyramid Label {idx}",
                x + 0.24,
                y + 0.16,
                w - 0.48,
                0.22,
                step_title(step, idx),
                color="FFFFFF" if idx == 1 else theme.ink,
                bold=True,
            )
        return shape_id

    if style == "loopback":
        shapes.append(
            _shape_box(
                shape_id,
                marker,
                1.02,
                3.1,
                10.76,
                0.08,
                fill=theme.accent,
                line=None,
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Process Loopback Return Rail",
                2.02,
                5.34,
                8.78,
                0.08,
                fill=theme.rule,
                line=None,
            ),
        )
        shape_id += 1
        for idx, step in enumerate(active_steps, start=1):
            x = 1.12 + (idx - 1) * (10.0 / max(count - 1, 1))
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Loopback Node {idx}",
                    x,
                    2.72,
                    0.78,
                    0.78,
                    fill=theme.panel,
                    line=theme.accent,
                    geometry="ellipse",
                ),
            )
            shape_id += 1
            label(f"Process Loopback Label {idx}", x - 0.24, 3.7, 1.26, 0.32, step_title(step, idx), bold=True)
        return shape_id

    if style == "sprint":
        for idx, step in enumerate(active_steps, start=1):
            y = 2.16 + (idx - 1) * 0.9
            shapes.append(
                _shape_box(
                    shape_id,
                    f"{marker} {idx}",
                    0.92,
                    y,
                    11.46,
                    0.64,
                    fill=theme.panel if idx % 2 else theme.accent_soft,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Sprint Progress {idx}",
                    3.22,
                    y + 0.2,
                    7.46 * idx / count,
                    0.18,
                    fill=theme.accent,
                    line=None,
                ),
            )
            shape_id += 1
            label(f"Process Sprint Label {idx}", 1.18, y + 0.14, 1.72, 0.3, step_title(step, idx), bold=True)
        return shape_id

    if style == "dependency":
        positions = [(1.0, 2.46), (4.26, 3.36), (7.52, 2.46), (4.26, 5.0), (10.1, 4.8)]
        for idx, step in enumerate(active_steps, start=1):
            x, y = positions[idx - 1]
            if idx > 1:
                shapes.append(
                    _shape_box(
                        shape_id,
                        f"Process Dependency Connector {idx - 1}",
                        min(positions[idx - 2][0] + 1.2, x + 1.2),
                        min(positions[idx - 2][1] + 0.44, y + 0.44),
                        abs(x - positions[idx - 2][0]) + 0.04,
                        0.04,
                        fill=theme.rule,
                        line=None,
                    ),
                )
                shape_id += 1
            shapes.append(
                _shape_box(
                    shape_id,
                    f"{marker} {idx}",
                    x,
                    y,
                    2.18,
                    0.88,
                    fill=theme.panel,
                    line=theme.rule,
                    geometry="roundRect",
                ),
            )
            shape_id += 1
            label(f"Process Dependency Label {idx}", x + 0.22, y + 0.24, 1.72, 0.28, step_title(step, idx), bold=True)
        return shape_id

    if style == "gate":
        for idx, step in enumerate(active_steps, start=1):
            x = 0.98 + (idx - 1) * (11.0 / max(count, 1))
            shapes.append(
                _shape_box(
                    shape_id,
                    f"{marker} {idx}",
                    x,
                    2.26,
                    1.82,
                    3.52,
                    fill=theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Gate Bar {idx}",
                    x,
                    3.04,
                    1.82,
                    0.12,
                    fill=theme.accent,
                    line=None,
                ),
            )
            shape_id += 1
            label(f"Process Gate Label {idx}", x + 0.18, 4.78, 1.46, 0.34, step_title(step, idx), bold=True)
        return shape_id

    if style == "wave":
        for idx, step in enumerate(active_steps, start=1):
            x = 0.92 + (idx - 1) * 2.2
            y = 3.1 + (idx % 2) * 0.72
            shapes.append(
                _shape_box(
                    shape_id,
                    f"{marker} {idx}",
                    x,
                    y,
                    1.74,
                    0.72,
                    fill=theme.accent if idx % 2 else theme.panel,
                    line=theme.rule,
                    geometry="roundRect",
                ),
            )
            shape_id += 1
            label(f"Process Wave Label {idx}", x + 0.18, y + 0.2, 1.38, 0.24, step_title(step, idx), color="FFFFFF" if idx % 2 else theme.ink, bold=True)
        return shape_id

    if style == "ribbon":
        x0 = 0.84
        ribbon_w = 2.24
        for idx, step in enumerate(active_steps, start=1):
            x = x0 + (idx - 1) * 2.18
            shapes.append(
                _shape_box(
                    shape_id,
                    f"{marker} {idx}",
                    x,
                    3.08,
                    ribbon_w,
                    1.02,
                    fill=theme.accent if idx == 1 else theme.panel,
                    line=theme.rule,
                    geometry="chevron",
                ),
            )
            shape_id += 1
            label(f"Process Ribbon Label {idx}", x + 0.28, 3.38, 1.56, 0.28, step_title(step, idx), color="FFFFFF" if idx == 1 else theme.ink, bold=True)
        return shape_id

    if style == "orbit":
        shapes.append(
            _shape_box(
                shape_id,
                marker,
                4.36,
                2.08,
                4.6,
                3.88,
                fill=None,
                line=theme.accent,
                geometry="ellipse",
                line_width_pt=2.0,
            ),
        )
        shape_id += 1
        positions = [(5.72, 1.88), (8.66, 3.12), (7.4, 5.48), (3.64, 4.56), (4.1, 2.72)]
        for idx, step in enumerate(active_steps, start=1):
            x, y = positions[idx - 1]
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Orbit Node {idx}",
                    x,
                    y,
                    1.2,
                    0.68,
                    fill=theme.panel,
                    line=theme.rule,
                    geometry="roundRect",
                ),
            )
            shape_id += 1
            label(f"Process Orbit Label {idx}", x + 0.12, y + 0.18, 0.96, 0.22, step_title(step, idx), size_pt=11, bold=True)
        return shape_id

    if style == "scorecard":
        for idx, step in enumerate(active_steps, start=1):
            y = 2.12 + (idx - 1) * 0.78
            shapes.append(
                _shape_box(
                    shape_id,
                    f"{marker} {idx}",
                    0.9,
                    y,
                    11.46,
                    0.58,
                    fill=theme.panel if idx % 2 else theme.canvas,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            label(f"Process Scorecard Label {idx}", 1.18, y + 0.14, 2.8, 0.26, step_title(step, idx), bold=True)
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Scorecard Bar {idx}",
                    5.08,
                    y + 0.18,
                    5.6 * idx / count,
                    0.18,
                    fill=theme.accent,
                    line=None,
                ),
            )
            shape_id += 1
        return shape_id

    if style == "timeline_cards":
        shapes.append(
            _shape_box(shape_id, "Process Timeline Cards Rail", 0.96, 4.92, 11.34, 0.06, fill=theme.rule, line=None),
        )
        shape_id += 1
        for idx, step in enumerate(active_steps, start=1):
            x = 1.0 + (idx - 1) * (10.72 / max(count, 1))
            y = 2.4 if idx % 2 else 3.34
            shapes.append(
                _shape_box(shape_id, f"{marker} {idx}", x, y, 2.0, 1.1, fill=theme.panel, line=theme.rule),
            )
            shape_id += 1
            label(f"Process Timeline Card Label {idx}", x + 0.2, y + 0.3, 1.54, 0.28, step_title(step, idx), bold=True)
        return shape_id

    if style == "cascade":
        for idx, step in enumerate(active_steps, start=1):
            x = 1.0 + (idx - 1) * 0.78
            y = 2.16 + (idx - 1) * 0.54
            shapes.append(
                _shape_box(
                    shape_id,
                    f"{marker} {idx}",
                    x,
                    y,
                    8.76,
                    1.0,
                    fill=theme.panel if idx < count else theme.accent_soft,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            label(f"Process Cascade Label {idx}", x + 0.3, y + 0.28, 3.2, 0.3, step_title(step, idx), bold=True)
        return shape_id

    if style == "quadrant":
        positions = [(0.92, 2.12), (6.72, 2.12), (0.92, 4.18), (6.72, 4.18)]
        for idx, step in enumerate(active_steps[:4], start=1):
            x, y = positions[idx - 1]
            shapes.append(
                _shape_box(shape_id, f"{marker} {idx}", x, y, 5.18, 1.52, fill=theme.panel if idx % 2 else theme.accent_soft, line=theme.rule),
            )
            shape_id += 1
            label(f"Process Quadrant Label {idx}", x + 0.3, y + 0.36, 4.4, 0.34, step_title(step, idx), bold=True)
        return shape_id

    if style == "bridge":
        shapes.append(
            _shape_box(shape_id, marker, 1.02, 3.18, 11.08, 0.28, fill=theme.accent, line=None),
        )
        shape_id += 1
        for idx, step in enumerate(active_steps, start=1):
            x = 1.18 + (idx - 1) * 2.08
            shapes.append(
                _shape_box(shape_id, f"Process Bridge Pillar {idx}", x, 3.46, 0.46, 2.0, fill=theme.panel, line=theme.rule),
            )
            shape_id += 1
            label(f"Process Bridge Label {idx}", x - 0.34, 5.7, 1.18, 0.28, step_title(step, idx), size_pt=11, bold=True)
        return shape_id

    if style == "conveyor":
        shapes.append(
            _shape_box(shape_id, marker, 0.94, 4.36, 11.34, 0.34, fill=theme.panel_alt, line=theme.rule),
        )
        shape_id += 1
        for idx, step in enumerate(active_steps, start=1):
            x = 1.08 + (idx - 1) * 2.18
            shapes.append(
                _shape_box(shape_id, f"Process Conveyor Roller {idx}", x, 4.16, 0.54, 0.54, fill=theme.canvas, line=theme.accent, geometry="ellipse"),
            )
            shape_id += 1
            shapes.append(
                _shape_box(shape_id, f"Process Conveyor Package {idx}", x - 0.26, 3.0, 1.24, 0.78, fill=theme.panel, line=theme.rule),
            )
            shape_id += 1
            label(f"Process Conveyor Label {idx}", x - 0.24, 3.22, 1.08, 0.24, step_title(step, idx), size_pt=11, bold=True)
        return shape_id

    if style == "decision_tree":
        positions = [(5.74, 2.18), (3.1, 4.18), (8.38, 4.18), (1.0, 5.48), (10.46, 5.48)]
        for idx, step in enumerate(active_steps, start=1):
            x, y = positions[idx - 1]
            shapes.append(
                _shape_box(shape_id, f"{marker} {idx}", x, y, 1.44, 1.0, fill=theme.panel, line=theme.accent, geometry="diamond"),
            )
            shape_id += 1
            label(f"Process Decision Label {idx}", x + 0.28, y + 0.36, 0.86, 0.22, step_title(step, idx), size_pt=10, bold=True)
        return shape_id

    if style == "matrix":
        cell_w = 3.55
        cell_h = 1.18
        for idx, step in enumerate(active_steps[:4], start=1):
            x = 1.0 + ((idx - 1) % 2) * 5.72
            y = 2.24 + ((idx - 1) // 2) * 1.72
            shapes.append(
                _shape_box(shape_id, f"{marker} {idx}", x, y, cell_w, cell_h, fill=theme.panel, line=theme.rule),
            )
            shape_id += 1
            label(f"Process Matrix Label {idx}", x + 0.26, y + 0.36, 2.9, 0.3, step_title(step, idx), bold=True)
        return shape_id

    if style == "layered_timeline":
        shapes.append(
            _shape_box(shape_id, marker, 1.08, 2.28, 10.98, 0.06, fill=theme.accent, line=None),
        )
        shape_id += 1
        for idx, step in enumerate(active_steps, start=1):
            y = 2.74 + (idx - 1) * 0.64
            shapes.append(
                _shape_box(shape_id, f"Process Layered Timeline Layer {idx}", 1.08 + (idx - 1) * 0.36, y, 9.8 - (idx - 1) * 0.72, 0.42, fill=theme.panel, line=theme.rule),
            )
            shape_id += 1
            label(f"Process Layered Timeline Label {idx}", 1.34 + (idx - 1) * 0.36, y + 0.08, 2.2, 0.2, step_title(step, idx), size_pt=10, bold=True)
        return shape_id

    if style == "compass":
        shapes.append(
            _shape_box(shape_id, marker, 5.42, 2.8, 2.0, 2.0, fill=theme.accent, line=None, geometry="ellipse"),
        )
        shape_id += 1
        directions = [(5.72, 1.72), (8.58, 3.36), (5.72, 5.46), (2.6, 3.36), (9.9, 5.24)]
        for idx, step in enumerate(active_steps, start=1):
            x, y = directions[idx - 1]
            shapes.append(
                _shape_box(shape_id, f"Process Compass Point {idx}", x, y, 1.42, 0.72, fill=theme.panel, line=theme.rule, geometry="roundRect"),
            )
            shape_id += 1
            label(f"Process Compass Label {idx}", x + 0.14, y + 0.2, 1.14, 0.22, step_title(step, idx), size_pt=11, bold=True)
        return shape_id

    if style == "map_route":
        shapes.append(
            _shape_box(shape_id, marker, 1.2, 4.12, 10.62, 0.08, fill=theme.rule, line=None),
        )
        shape_id += 1
        for idx, step in enumerate(active_steps, start=1):
            x = 1.18 + (idx - 1) * 2.32
            y = 3.0 + (idx % 2) * 0.72
            shapes.append(
                _shape_box(shape_id, f"Process Map Pin {idx}", x, y, 0.68, 0.68, fill=theme.accent, line=None, geometry="ellipse"),
            )
            shape_id += 1
            label(f"Process Map Label {idx}", x - 0.32, y + 0.9, 1.28, 0.26, step_title(step, idx), size_pt=11, bold=True)
        return shape_id

    if style == "pulse":
        shapes.append(
            _shape_box(shape_id, "Process Pulse Rail", 0.9, 3.84, 11.38, 0.04, fill=theme.rule, line=None),
        )
        shape_id += 1
        for idx, step in enumerate(active_steps, start=1):
            x = 1.08 + (idx - 1) * 2.24
            size = 0.76 + idx * 0.08
            shapes.append(
                _shape_box(shape_id, f"{marker} {idx}", x, 3.42 - idx * 0.04, size, size, fill=theme.accent_soft, line=theme.accent, geometry="ellipse"),
            )
            shape_id += 1
            label(f"Process Pulse Label {idx}", x - 0.2, 4.5, 1.24, 0.28, step_title(step, idx), size_pt=11, bold=True)
        return shape_id

    if style == "cluster":
        positions = [(5.8, 2.58), (4.28, 3.64), (7.32, 3.64), (5.8, 4.88), (9.36, 4.64)]
        for idx, step in enumerate(active_steps, start=1):
            x, y = positions[idx - 1]
            shapes.append(
                _shape_box(shape_id, f"{marker} {idx}", x, y, 1.52, 0.92, fill=theme.panel if idx > 1 else theme.accent, line=theme.rule, geometry="roundRect"),
            )
            shape_id += 1
            label(f"Process Cluster Label {idx}", x + 0.18, y + 0.28, 1.16, 0.24, step_title(step, idx), color="FFFFFF" if idx == 1 else theme.ink, size_pt=11, bold=True)
        return shape_id

    if style == "evidence":
        shapes.append(
            _shape_box(shape_id, marker, 0.96, 2.06, 0.14, 4.32, fill=theme.accent, line=None),
        )
        shape_id += 1
        for idx, step in enumerate(active_steps, start=1):
            y = 2.16 + (idx - 1) * 0.8
            shapes.append(
                _shape_box(shape_id, f"Process Evidence Card {idx}", 1.42, y, 10.62, 0.58, fill=theme.panel, line=theme.rule),
            )
            shape_id += 1
            label(f"Process Evidence Label {idx}", 1.72, y + 0.14, 2.8, 0.26, step_title(step, idx), bold=True)
            label(f"Process Evidence Body {idx}", 5.0, y + 0.14, 5.8, 0.26, step_body(step), color=theme.body)
        return shape_id

    if style == "calendar":
        for idx, step in enumerate(active_steps[:5], start=1):
            x = 1.0 + ((idx - 1) % 5) * 2.18
            shapes.append(
                _shape_box(shape_id, f"{marker} {idx}", x, 2.48, 1.76, 2.44, fill=theme.panel, line=theme.rule),
            )
            shape_id += 1
            label(f"Process Calendar Date {idx}", x + 0.18, 2.76, 0.5, 0.3, f"{idx:02d}", color=theme.accent, bold=True)
            label(f"Process Calendar Label {idx}", x + 0.18, 3.42, 1.3, 0.42, step_title(step, idx), size_pt=12, bold=True)
        return shape_id

    if style == "handoff":
        for idx, step in enumerate(active_steps[:5], start=1):
            y = 2.1 + (idx - 1) * 0.78
            shapes.append(
                _shape_box(shape_id, f"{marker} {idx}", 0.96, y, 4.44, 0.54, fill=theme.panel, line=theme.rule),
            )
            shape_id += 1
            shapes.append(
                _shape_box(shape_id, f"Process Handoff Arrow {idx}", 5.72, y + 0.08, 1.5, 0.38, fill=theme.accent, line=None, geometry="chevron"),
            )
            shape_id += 1
            shapes.append(
                _shape_box(shape_id, f"Process Handoff Receiver {idx}", 7.52, y, 4.18, 0.54, fill=theme.accent_soft, line=theme.rule),
            )
            shape_id += 1
            label(f"Process Handoff Label {idx}", 1.18, y + 0.12, 3.4, 0.24, step_title(step, idx), bold=True)
        return shape_id

    return None


def _layout_process(
    shapes: list[str],
    shape_id: int,
    slide: SlideSpec,
    theme: ThemeSpec,
    *,
    variant: str = "horizontal",
) -> int:
    shape_id = _add_title_block(shapes, shape_id, slide, theme)
    steps = slide.steps or _items_from_bullets(slide.bullets, 5)
    count = min(max(len(steps), 1), 5)
    advanced_shape_id = _layout_advanced_process(
        shapes,
        shape_id,
        slide,
        theme,
        steps,
        count,
        variant,
    )
    if advanced_shape_id is not None:
        return advanced_shape_id
    if variant == "vertical":
        rail_x = 1.08
        y0 = 2.08
        lane_gap = 0.78
        lane_h = min(0.98, (4.7 - lane_gap * (count - 1)) / max(count, 1))
        shapes.append(
            _shape_box(
                shape_id,
                "Process Vertical Rail",
                rail_x + 0.31,
                y0 + 0.1,
                0.04,
                4.55,
                fill=theme.rule,
                line=None,
            ),
        )
        shape_id += 1
        for idx, step in enumerate(steps[:count], start=1):
            y = y0 + (idx - 1) * (lane_h + lane_gap)
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Lane {idx}",
                    1.62,
                    y - 0.08,
                    10.56,
                    lane_h + 0.28,
                    fill=theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Step {idx}",
                    rail_x,
                    y,
                    0.66,
                    0.66,
                    fill=theme.accent,
                    line=None,
                    geometry="ellipse",
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Process Number {idx}",
                    rail_x + 0.14,
                    y + 0.11,
                    0.38,
                    0.32,
                    [
                        _paragraph(
                            str(idx),
                            size_pt=13,
                            color="FFFFFF",
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Process Title {idx}",
                    1.92,
                    y + 0.04,
                    2.55,
                    0.44,
                    [
                        _paragraph(
                            step.get("title", ""),
                            size_pt=17,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            if step.get("body"):
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Process Body {idx}",
                        4.56,
                        y + 0.06,
                        7.32,
                        0.5,
                        [
                            _paragraph(
                                step["body"],
                                size_pt=14,
                                color=theme.body,
                                font_face=theme.font_family,
                            ),
                        ],
                    ),
                )
                shape_id += 1
        return shape_id

    if variant == "stair":
        x0 = 0.92
        y0 = 4.94
        gap = 0.22
        stair_w = (11.48 - gap * (count - 1)) / count
        for idx, step in enumerate(steps[:count], start=1):
            x = x0 + (idx - 1) * (stair_w + gap)
            y = y0 - (idx - 1) * 0.52
            h = 0.86 + (idx - 1) * 0.18
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Stair {idx}",
                    x,
                    y,
                    stair_w,
                    h,
                    fill=theme.accent if idx == count else theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Process Number {idx}",
                    x + 0.16,
                    y + 0.14,
                    0.44,
                    0.34,
                    [
                        _paragraph(
                            str(idx),
                            size_pt=13,
                            color="FFFFFF" if idx == count else theme.accent,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Process Title {idx}",
                    x + 0.18,
                    y + 0.54,
                    stair_w - 0.36,
                    0.48,
                    [
                        _paragraph(
                            step.get("title", ""),
                            size_pt=16,
                            color="FFFFFF" if idx == count else theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            if step.get("body"):
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Process Body {idx}",
                        x + 0.18,
                        y + 1.04,
                        stair_w - 0.36,
                        0.62,
                        [
                            _paragraph(
                                step["body"],
                                size_pt=12,
                                color="FFFFFF" if idx == count else theme.body,
                                font_face=theme.font_family,
                            ),
                        ],
                    ),
                )
                shape_id += 1
        return shape_id

    if variant == "radial":
        hub_x = 5.4
        hub_y = 3.06
        hub_w = 2.45
        hub_h = 1.16
        anchor_points = [
            (1.0, 2.1, 3.76, 0.2),
            (8.58, 2.1, -0.94, 0.2),
            (1.0, 5.12, 3.76, -1.16),
            (8.58, 5.12, -0.94, -1.16),
            (4.18, 5.72, 1.0, -1.54),
        ]
        shapes.append(
            _shape_box(
                shape_id,
                "Process Hub",
                hub_x,
                hub_y,
                hub_w,
                hub_h,
                fill=theme.accent,
                line=None,
                geometry="ellipse",
            ),
        )
        shape_id += 1
        shapes.append(
            _text_box(
                shape_id,
                "Process Hub Label",
                hub_x + 0.34,
                hub_y + 0.34,
                hub_w - 0.68,
                0.38,
                [
                    _paragraph(
                        slide.title or "Process",
                        size_pt=14,
                        color="FFFFFF",
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        for idx, step in enumerate(steps[:count], start=1):
            x, y, spoke_w, spoke_y_offset = anchor_points[idx - 1]
            spoke_x = hub_x + (hub_w / 2)
            spoke_y = hub_y + (hub_h / 2) + spoke_y_offset
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Spoke {idx}",
                    min(spoke_x, spoke_x + spoke_w),
                    spoke_y,
                    abs(spoke_w),
                    0.035,
                    fill=theme.rule,
                    line=None,
                ),
            )
            shape_id += 1
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Node {idx}",
                    x,
                    y,
                    3.08,
                    1.0,
                    fill=theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Process Number {idx}",
                    x + 0.16,
                    y + 0.16,
                    0.42,
                    0.32,
                    [
                        _paragraph(
                            str(idx),
                            size_pt=12,
                            color=theme.accent,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Process Title {idx}",
                    x + 0.66,
                    y + 0.15,
                    2.12,
                    0.36,
                    [
                        _paragraph(
                            step.get("title", ""),
                            size_pt=15,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            if step.get("body"):
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Process Body {idx}",
                        x + 0.66,
                        y + 0.54,
                        2.12,
                        0.34,
                        [
                            _paragraph(
                                step["body"],
                                size_pt=11,
                                color=theme.body,
                                font_face=theme.font_family,
                            ),
                        ],
                    ),
                )
                shape_id += 1
        return shape_id

    if variant == "swimlane":
        y0 = 2.08
        lane_h = 0.86
        lane_gap = 0.22
        for idx, step in enumerate(steps[:count], start=1):
            y = y0 + (idx - 1) * (lane_h + lane_gap)
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Swimlane {idx}",
                    0.84,
                    y,
                    11.56,
                    lane_h,
                    fill=theme.panel if idx % 2 else theme.canvas,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Swimlane Header {idx}",
                    0.84,
                    y,
                    2.06,
                    lane_h,
                    fill=theme.accent,
                    line=None,
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Process Swimlane Title {idx}",
                    1.08,
                    y + 0.22,
                    1.58,
                    0.34,
                    [
                        _paragraph(
                            step.get("title", ""),
                            size_pt=14,
                            color="FFFFFF",
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            body = step.get("body") or f"Phase {idx}"
            shapes.append(
                _text_box(
                    shape_id,
                    f"Process Swimlane Body {idx}",
                    3.22,
                    y + 0.22,
                    8.68,
                    0.34,
                    [
                        _paragraph(
                            body,
                            size_pt=13,
                            color=theme.body,
                            font_face=theme.font_family,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "chevron":
        x0 = 0.82
        y = 2.68
        gap = 0.08
        chevron_w = (11.7 - gap * (count - 1)) / count
        for idx, step in enumerate(steps[:count], start=1):
            x = x0 + (idx - 1) * (chevron_w + gap)
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Chevron {idx}",
                    x,
                    y,
                    chevron_w,
                    1.46,
                    fill=theme.accent if idx == 1 else theme.panel,
                    line=theme.rule,
                    geometry="chevron",
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Process Chevron Label {idx}",
                    x + 0.26,
                    y + 0.4,
                    chevron_w - 0.64,
                    0.4,
                    [
                        _paragraph(
                            step.get("title", ""),
                            size_pt=15,
                            color="FFFFFF" if idx == 1 else theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            if step.get("body"):
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Process Chevron Body {idx}",
                        x + 0.28,
                        y + 1.68,
                        chevron_w - 0.5,
                        0.56,
                        [
                            _paragraph(
                                step["body"],
                                size_pt=11,
                                color=theme.body,
                                font_face=theme.font_family,
                            ),
                        ],
                    ),
                )
                shape_id += 1
        return shape_id

    if variant == "cycle":
        cx = 6.28
        cy = 4.02
        shapes.append(
            _shape_box(
                shape_id,
                "Process Cycle Ring",
                4.2,
                2.24,
                4.16,
                3.56,
                fill=None,
                line=theme.accent,
                geometry="ellipse",
                line_width_pt=2.2,
            ),
        )
        shape_id += 1
        node_positions = [
            (5.6, 1.98),
            (8.3, 3.28),
            (6.98, 5.52),
            (3.76, 4.86),
            (3.82, 2.66),
        ]
        for idx, step in enumerate(steps[:count], start=1):
            x, y = node_positions[idx - 1]
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Cycle Node {idx}",
                    x,
                    y,
                    1.36,
                    0.76,
                    fill=theme.panel,
                    line=theme.rule,
                    geometry="roundRect",
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Process Cycle Label {idx}",
                    x + 0.14,
                    y + 0.2,
                    1.08,
                    0.28,
                    [
                        _paragraph(
                            step.get("title", ""),
                            size_pt=12,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        shapes.append(
            _text_box(
                shape_id,
                "Process Cycle Center",
                cx - 0.8,
                cy - 0.22,
                1.6,
                0.38,
                [
                    _paragraph(
                        "ITERATE",
                        size_pt=13,
                        color=theme.accent,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        return shape_id

    if variant == "stack":
        x = 2.18
        y0 = 5.38
        layer_w = 8.92
        for idx, step in enumerate(steps[:count], start=1):
            y = y0 - (idx - 1) * 0.68
            inset = (idx - 1) * 0.34
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Process Stack Layer {idx}",
                    x + inset,
                    y,
                    layer_w - inset * 2,
                    0.58,
                    fill=theme.accent if idx == count else theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Process Stack Label {idx}",
                    x + inset + 0.28,
                    y + 0.14,
                    layer_w - inset * 2 - 0.56,
                    0.24,
                    [
                        _paragraph(
                            step.get("title", ""),
                            size_pt=13,
                            color="FFFFFF" if idx == count else theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    x0 = 0.82
    gap = 0.34
    box_w = (11.7 - gap * (count - 1)) / count
    y = 2.68
    shapes.append(
        _shape_box(
            shape_id,
            "Process Spine",
            x0,
            y + 0.48,
            11.7,
            0.04,
            fill=theme.rule,
            line=None,
        ),
    )
    shape_id += 1
    for idx, step in enumerate(steps[:count], start=1):
        x = x0 + (idx - 1) * (box_w + gap)
        shapes.append(
            _shape_box(
                shape_id,
                f"Process Step {idx}",
                x,
                y,
                0.96,
                0.96,
                fill=theme.accent,
                line=None,
                geometry="ellipse",
            ),
        )
        shape_id += 1
        shapes.append(
            _text_box(
                shape_id,
                f"Process Number {idx}",
                x + 0.18,
                y + 0.18,
                0.6,
                0.42,
                [
                    _paragraph(
                        str(idx),
                        size_pt=18,
                        color="FFFFFF",
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        shapes.append(
            _text_box(
                shape_id,
                f"Process Title {idx}",
                x,
                y + 1.26,
                box_w,
                0.58,
                [
                    _paragraph(
                        step.get("title", ""),
                        size_pt=18,
                        color=theme.ink,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        if step.get("body"):
            shapes.append(
                _text_box(
                    shape_id,
                    f"Process Body {idx}",
                    x,
                    y + 1.9,
                    box_w,
                    1.2,
                    [
                        _paragraph(
                            step["body"],
                            size_pt=14,
                            color=theme.body,
                            font_face=theme.font_family,
                        ),
                    ],
                ),
            )
            shape_id += 1
    return shape_id


def _layout_metrics(
    shapes: list[str],
    shape_id: int,
    slide: SlideSpec,
    theme: ThemeSpec,
    *,
    variant: str = "cards",
) -> int:
    shape_id = _add_title_block(shapes, shape_id, slide, theme)
    metrics = slide.metrics or [
        {**item, "value": ""}
        for item in _items_from_bullets(slide.bullets, 4)
    ]
    count = min(max(len(metrics), 1), 4)

    def metric_value(metric: dict[str, str]) -> str:
        return metric.get("value") or metric.get("title") or metric.get("label", "")

    def metric_label(metric: dict[str, str]) -> str:
        return metric.get("label") or metric.get("title") or ""

    def metric_caption(metric: dict[str, str]) -> str:
        return metric.get("caption") or metric.get("body") or ""

    if variant == "chart_insight":
        shapes.append(
            _shape_box(
                shape_id,
                "Chart Insight Frame",
                0.82,
                2.04,
                11.68,
                4.34,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Chart Plot Area",
                1.14,
                2.48,
                7.24,
                3.34,
                fill=theme.canvas,
                line=theme.rule,
            ),
        )
        shape_id += 1
        for idx, metric in enumerate(metrics[:count], start=1):
            bar_h = 0.34 + idx * 0.16
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Chart Plot Bar {idx}",
                    1.56 + (idx - 1) * 1.92,
                    5.56 - bar_h,
                    1.12,
                    bar_h,
                    fill=theme.accent,
                    line=None,
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Chart Plot Value {idx}",
                    1.42 + (idx - 1) * 1.92,
                    5.74,
                    1.4,
                    0.28,
                    [
                        _paragraph(
                            metric_value(metric),
                            size_pt=11,
                            color=theme.accent,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Chart Insight Rail",
                8.72,
                2.48,
                3.22,
                3.34,
                fill=theme.accent_soft,
                line=None,
            ),
        )
        shape_id += 1
        for idx, metric in enumerate(metrics[:3], start=1):
            shapes.append(
                _text_box(
                    shape_id,
                    f"Chart Insight Item {idx}",
                    9.02,
                    2.7 + (idx - 1) * 0.88,
                    2.56,
                    0.46,
                    [
                        _paragraph(
                            f"{metric_label(metric)} {metric_value(metric)}",
                            size_pt=13,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=idx == 1,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "chart_split":
        shapes.append(
            _shape_box(
                shape_id,
                "Chart Split Plot",
                0.88,
                2.18,
                7.18,
                4.12,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        for idx, metric in enumerate(metrics[:count], start=1):
            y = 2.78 + (idx - 1) * 0.86
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Chart Split Track {idx}",
                    1.3,
                    y,
                    5.74,
                    0.3,
                    fill=theme.panel_alt,
                    line=None,
                ),
            )
            shape_id += 1
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Chart Split Bar {idx}",
                    1.3,
                    y,
                    5.74 * (count - idx + 1) / count,
                    0.3,
                    fill=theme.accent,
                    line=None,
                ),
            )
            shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Chart Legend Panel",
                8.54,
                2.18,
                3.78,
                4.12,
                fill=theme.canvas,
                line=theme.rule,
            ),
        )
        shape_id += 1
        for idx, metric in enumerate(metrics[:count], start=1):
            shapes.append(
                _text_box(
                    shape_id,
                    f"Chart Legend Item {idx}",
                    8.88,
                    2.58 + (idx - 1) * 0.78,
                    2.88,
                    0.38,
                    [
                        _paragraph(
                            f"{metric_label(metric)}: {metric_value(metric)}",
                            size_pt=13,
                            color=theme.body,
                            font_face=theme.font_family,
                            bold=idx == 1,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "leaderboard":
        y = 2.06
        for idx, metric in enumerate(metrics[:count], start=1):
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Metric Leaderboard Row {idx}",
                    0.82,
                    y,
                    11.68,
                    0.9,
                    fill=theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Metric Rank {idx}",
                    1.08,
                    y + 0.18,
                    0.54,
                    0.54,
                    fill=theme.accent,
                    line=None,
                    geometry="ellipse",
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Metric Rank Text {idx}",
                    1.22,
                    y + 0.28,
                    0.26,
                    0.22,
                    [
                        _paragraph(
                            str(idx),
                            size_pt=11,
                            color="FFFFFF",
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Metric Leaderboard Label {idx}",
                    1.9,
                    y + 0.2,
                    4.8,
                    0.36,
                    [
                        _paragraph(
                            metric_label(metric),
                            size_pt=16,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Metric Leaderboard Value {idx}",
                    8.6,
                    y + 0.12,
                    3.3,
                    0.5,
                    [
                        _paragraph(
                            metric_value(metric),
                            size_pt=23,
                            color=theme.accent,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            caption = metric_caption(metric)
            if caption:
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Metric Leaderboard Caption {idx}",
                        1.9,
                        y + 0.56,
                        5.8,
                        0.22,
                        [
                            _paragraph(
                                caption,
                                size_pt=11,
                                color=theme.body,
                                font_face=theme.font_family,
                            ),
                        ],
                    ),
                )
                shape_id += 1
            y += 1.08
        return shape_id

    if variant == "spotlight":
        primary = metrics[0] if metrics else {"label": "", "value": ""}
        shapes.append(
            _shape_box(
                shape_id,
                "Metric Spotlight",
                4.55,
                2.28,
                4.22,
                2.12,
                fill=theme.accent,
                line=None,
                geometry="ellipse",
            ),
        )
        shape_id += 1
        shapes.append(
            _text_box(
                shape_id,
                "Metric Spotlight Value",
                5.18,
                2.8,
                2.96,
                0.62,
                [
                    _paragraph(
                        metric_value(primary),
                        size_pt=30,
                        color="FFFFFF",
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        shapes.append(
            _text_box(
                shape_id,
                "Metric Spotlight Label",
                5.12,
                3.48,
                3.08,
                0.32,
                [
                    _paragraph(
                        metric_label(primary),
                        size_pt=13,
                        color="FFFFFF",
                        font_face=theme.font_family,
                    ),
                ],
            ),
        )
        shape_id += 1
        satellite_frames = [(0.92, 2.28), (9.28, 2.28), (4.55, 5.02)]
        for idx, metric in enumerate(metrics[1:4], start=1):
            x, y = satellite_frames[idx - 1]
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Metric Satellite {idx}",
                    x,
                    y,
                    3.12,
                    1.2,
                    fill=theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Metric Satellite Value {idx}",
                    x + 0.28,
                    y + 0.24,
                    1.14,
                    0.44,
                    [
                        _paragraph(
                            metric_value(metric),
                            size_pt=20,
                            color=theme.accent,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Metric Satellite Label {idx}",
                    x + 1.48,
                    y + 0.3,
                    1.34,
                    0.36,
                    [
                        _paragraph(
                            metric_label(metric),
                            size_pt=13,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "bars":
        y = 2.18
        for idx, metric in enumerate(metrics[:count], start=1):
            bar_w = 7.92 * (count - idx + 1) / count
            shapes.append(
                _text_box(
                    shape_id,
                    f"Metric Bar Label {idx}",
                    0.92,
                    y + 0.02,
                    2.2,
                    0.32,
                    [
                        _paragraph(
                            metric_label(metric),
                            size_pt=14,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Metric Bar Track {idx}",
                    3.32,
                    y + 0.04,
                    7.92,
                    0.34,
                    fill=theme.panel_alt,
                    line=None,
                ),
            )
            shape_id += 1
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Metric Bar {idx}",
                    3.32,
                    y + 0.04,
                    bar_w,
                    0.34,
                    fill=theme.accent,
                    line=None,
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Metric Bar Value {idx}",
                    11.42,
                    y - 0.04,
                    0.88,
                    0.42,
                    [
                        _paragraph(
                            metric_value(metric),
                            size_pt=15,
                            color=theme.accent,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            y += 0.94
        return shape_id

    if variant == "gauge":
        primary = metrics[0] if metrics else {"label": "", "value": ""}
        shapes.append(
            _shape_box(
                shape_id,
                "Metric Gauge Dial",
                4.56,
                2.08,
                4.18,
                4.18,
                fill=theme.panel,
                line=theme.rule,
                geometry="ellipse",
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Metric Gauge Arc",
                5.08,
                2.6,
                3.14,
                3.14,
                fill=theme.accent_soft,
                line=None,
                geometry="ellipse",
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Metric Gauge Needle",
                6.56,
                3.22,
                0.16,
                1.58,
                fill=theme.accent,
                line=None,
            ),
        )
        shape_id += 1
        shapes.append(
            _text_box(
                shape_id,
                "Metric Gauge Value",
                5.32,
                4.26,
                2.68,
                0.64,
                [
                    _paragraph(
                        metric_value(primary),
                        size_pt=31,
                        color=theme.ink,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        for idx, metric in enumerate(metrics[1:4], start=1):
            shapes.append(
                _text_box(
                    shape_id,
                    f"Metric Gauge Support {idx}",
                    0.96 if idx == 1 else 9.0,
                    2.1 + (idx - 1) * 0.86,
                    3.1,
                    0.46,
                    [
                        _paragraph(
                            f"{metric_label(metric)} {metric_value(metric)}",
                            size_pt=14,
                            color=theme.body,
                            font_face=theme.font_family,
                            bold=idx == 1,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "tile_wall":
        shapes.append(
            _shape_box(
                shape_id,
                "Metric Tile Wall",
                0.82,
                2.02,
                11.68,
                4.28,
                fill=theme.panel_alt,
                line=None,
            ),
        )
        shape_id += 1
        tile_count = min(max(len(metrics), 1), 6)
        tile_w = 3.62
        tile_h = 1.46
        for idx in range(tile_count):
            metric = metrics[idx]
            x = 1.02 + (idx % 3) * 3.86
            y = 2.28 + (idx // 3) * 1.72
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Metric Tile {idx + 1}",
                    x,
                    y,
                    tile_w,
                    tile_h,
                    fill=theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Metric Tile Value {idx + 1}",
                    x + 0.28,
                    y + 0.28,
                    1.52,
                    0.44,
                    [
                        _paragraph(
                            metric_value(metric),
                            size_pt=22,
                            color=theme.accent,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Metric Tile Label {idx + 1}",
                    x + 1.92,
                    y + 0.32,
                    1.34,
                    0.36,
                    [
                        _paragraph(
                            metric_label(metric),
                            size_pt=13,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "waterfall":
        shapes.append(
            _shape_box(
                shape_id,
                "Metric Waterfall Baseline",
                1.02,
                5.76,
                11.08,
                0.04,
                fill=theme.rule,
                line=None,
            ),
        )
        shape_id += 1
        step_w = 2.32
        for idx, metric in enumerate(metrics[:count], start=1):
            height = 0.72 + idx * 0.42
            x = 1.18 + (idx - 1) * 2.72
            y = 5.76 - height
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Metric Waterfall Step {idx}",
                    x,
                    y,
                    step_w,
                    height,
                    fill=theme.accent if idx % 2 else theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Metric Waterfall Value {idx}",
                    x + 0.18,
                    y + 0.18,
                    step_w - 0.36,
                    0.36,
                    [
                        _paragraph(
                            metric_value(metric),
                            size_pt=17,
                            color="FFFFFF" if idx % 2 else theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Metric Waterfall Label {idx}",
                    x + 0.04,
                    5.92,
                    step_w,
                    0.3,
                    [
                        _paragraph(
                            metric_label(metric),
                            size_pt=11,
                            color=theme.body,
                            font_face=theme.font_family,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "compare_ring":
        ring_positions = [(1.08, 2.38), (4.58, 2.08), (8.08, 2.38)]
        for idx, metric in enumerate(metrics[:3], start=1):
            x, y = ring_positions[idx - 1]
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Metric Compare Ring {idx}",
                    x,
                    y,
                    2.72,
                    2.72,
                    fill=theme.panel,
                    line=theme.accent,
                    geometry="ellipse",
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Metric Compare Value {idx}",
                    x + 0.54,
                    y + 0.88,
                    1.64,
                    0.5,
                    [
                        _paragraph(
                            metric_value(metric),
                            size_pt=22,
                            color=theme.accent,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Metric Compare Center",
                4.18,
                4.92,
                4.98,
                0.82,
                fill=theme.accent_soft,
                line=None,
            ),
        )
        shape_id += 1
        return shape_id

    gap = 0.28
    x0 = 0.72
    card_w = (11.88 - gap * (count - 1)) / count
    for idx, metric in enumerate(metrics[:count], start=1):
        x = x0 + (idx - 1) * (card_w + gap)
        shapes.append(
            _shape_box(
                shape_id,
                f"Metric {idx}",
                x,
                2.2,
                card_w,
                3.65,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        value = metric_value(metric)
        label = metric_label(metric)
        caption = metric_caption(metric)
        shapes.append(
            _text_box(
                shape_id,
                f"Metric Value {idx}",
                x + 0.24,
                2.74,
                card_w - 0.48,
                0.95,
                [
                    _paragraph(
                        value,
                        size_pt=34,
                        color=theme.accent,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        if label and label != value:
            shapes.append(
                _text_box(
                    shape_id,
                    f"Metric Label {idx}",
                    x + 0.24,
                    3.78,
                    card_w - 0.48,
                    0.48,
                    [
                        _paragraph(
                            label,
                            size_pt=16,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        if caption:
            shapes.append(
                _text_box(
                    shape_id,
                    f"Metric Caption {idx}",
                    x + 0.24,
                    4.42,
                    card_w - 0.48,
                    0.8,
                    [
                        _paragraph(
                            caption,
                            size_pt=14,
                            color=theme.body,
                            font_face=theme.font_family,
                        ),
                    ],
                ),
            )
            shape_id += 1
    return shape_id


def _layout_table(
    shapes: list[str],
    shape_id: int,
    slide: SlideSpec,
    theme: ThemeSpec,
    *,
    variant: str = "grid",
) -> int:
    shape_id = _add_title_block(shapes, shape_id, slide, theme)
    headers = slide.table.get("headers") or []
    rows = slide.table.get("rows") or []
    if not headers and rows:
        headers = [f"列 {idx}" for idx in range(1, len(rows[0]) + 1)]
    if not headers:
        return _layout_content(shapes, shape_id, slide, theme)
    col_count = max(len(headers), max((len(row) for row in rows), default=0), 1)
    x0, y0, table_w = 0.72, 2.04, 11.88
    row_h = 0.64
    col_w = table_w / col_count

    if variant == "matrix":
        shapes.append(
            _shape_box(
                shape_id,
                "Table Matrix Header Band",
                x0,
                y0,
                table_w,
                0.62,
                fill=theme.accent,
                line=None,
            ),
        )
        shape_id += 1
        for col_idx, header in enumerate(headers[:col_count], start=1):
            x = x0 + (col_idx - 1) * col_w
            shapes.append(
                _text_box(
                    shape_id,
                    f"Table Matrix Header {col_idx}",
                    x + 0.12,
                    y0 + 0.14,
                    col_w - 0.24,
                    0.28,
                    [
                        _paragraph(
                            header,
                            size_pt=13,
                            color="FFFFFF",
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        for row_idx, row in enumerate(rows[:5], start=1):
            y = y0 + 0.78 + (row_idx - 1) * 0.78
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Table Matrix Row {row_idx}",
                    x0,
                    y,
                    table_w,
                    0.64,
                    fill=theme.panel if row_idx % 2 else theme.canvas,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            for col_idx in range(1, col_count + 1):
                text = row[col_idx - 1] if col_idx - 1 < len(row) else ""
                x = x0 + (col_idx - 1) * col_w
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Table Matrix Cell {row_idx}-{col_idx}",
                        x + 0.12,
                        y + 0.14,
                        col_w - 0.24,
                        0.3,
                        [
                            _paragraph(
                                text,
                                size_pt=12,
                                color=theme.body,
                                font_face=theme.font_family,
                            ),
                        ],
                    ),
                )
                shape_id += 1
        return shape_id

    if variant == "records":
        card_gap = 0.28
        card_count = min(max(len(rows), 1), 3)
        card_w = (table_w - card_gap * (card_count - 1)) / card_count
        for row_idx, row in enumerate(rows[:card_count], start=1):
            x = x0 + (row_idx - 1) * (card_w + card_gap)
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Table Record Card {row_idx}",
                    x,
                    y0,
                    card_w,
                    4.28,
                    fill=theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            for col_idx in range(1, col_count + 1):
                header = headers[col_idx - 1] if col_idx - 1 < len(headers) else ""
                text = row[col_idx - 1] if col_idx - 1 < len(row) else ""
                y = y0 + 0.42 + (col_idx - 1) * 1.12
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Table Record Label {row_idx}-{col_idx}",
                        x + 0.28,
                        y,
                        card_w - 0.56,
                        0.28,
                        [
                            _paragraph(
                                header,
                                size_pt=11,
                                color=theme.accent,
                                font_face=theme.font_family,
                                bold=True,
                            ),
                        ],
                    ),
                )
                shape_id += 1
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Table Record Value {row_idx}-{col_idx}",
                        x + 0.28,
                        y + 0.34,
                        card_w - 0.56,
                        0.44,
                        [
                            _paragraph(
                                text,
                                size_pt=15,
                                color=theme.ink,
                                font_face=theme.font_family,
                                bold=col_idx == 1,
                            ),
                        ],
                    ),
                )
                shape_id += 1
        return shape_id

    if variant == "heatmap":
        for col_idx, header in enumerate(headers[:col_count], start=1):
            x = x0 + (col_idx - 1) * col_w
            shapes.append(
                _text_box(
                    shape_id,
                    f"Table Heat Header {col_idx}",
                    x,
                    y0,
                    col_w,
                    row_h,
                    [
                        _paragraph(
                            header,
                            size_pt=13,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                    fill=theme.panel_alt,
                    line=theme.rule,
                ),
            )
            shape_id += 1
        for row_idx, row in enumerate(rows[:5], start=1):
            for col_idx in range(1, col_count + 1):
                text = row[col_idx - 1] if col_idx - 1 < len(row) else ""
                x = x0 + (col_idx - 1) * col_w
                y = y0 + row_idx * row_h
                heat_fill = theme.accent_soft if (row_idx + col_idx) % 2 else theme.panel
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Table Heat Cell {row_idx}-{col_idx}",
                        x,
                        y,
                        col_w,
                        row_h,
                        [
                            _paragraph(
                                text,
                                size_pt=12,
                                color=theme.body,
                                font_face=theme.font_family,
                            ),
                        ],
                        fill=heat_fill,
                        line=theme.rule,
                    ),
                )
                shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Table Heat Legend",
                9.96,
                6.42,
                2.48,
                0.28,
                fill=theme.accent_soft,
                line=theme.rule,
            ),
        )
        shape_id += 1
        return shape_id

    if variant == "timeline":
        rail_x = 1.42
        shapes.append(
            _shape_box(
                shape_id,
                "Table Timeline Rail",
                rail_x,
                y0 + 0.34,
                0.08,
                4.16,
                fill=theme.accent,
                line=None,
            ),
        )
        shape_id += 1
        for row_idx, row in enumerate(rows[:5], start=1):
            y = y0 + 0.18 + (row_idx - 1) * 0.82
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Table Timeline Node {row_idx}",
                    rail_x - 0.16,
                    y + 0.2,
                    0.4,
                    0.4,
                    fill=theme.canvas,
                    line=theme.accent,
                    geometry="ellipse",
                ),
            )
            shape_id += 1
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Table Timeline Row {row_idx}",
                    2.02,
                    y,
                    10.12,
                    0.74,
                    fill=theme.panel if row_idx % 2 else theme.canvas,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            for col_idx in range(1, col_count + 1):
                header = headers[col_idx - 1] if col_idx - 1 < len(headers) else ""
                text = row[col_idx - 1] if col_idx - 1 < len(row) else ""
                x = 2.28 + (col_idx - 1) * (9.38 / col_count)
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Table Timeline Cell {row_idx}-{col_idx}",
                        x,
                        y + 0.16,
                        9.06 / col_count,
                        0.42,
                        [
                            _paragraph(
                                f"{header}: {text}" if col_idx > 1 else text,
                                size_pt=12 if col_idx > 1 else 14,
                                color=theme.body if col_idx > 1 else theme.ink,
                                font_face=theme.font_family,
                                bold=col_idx == 1,
                            ),
                        ],
                    ),
                )
                shape_id += 1
        return shape_id

    for col_idx, header in enumerate(headers[:col_count], start=1):
        x = x0 + (col_idx - 1) * col_w
        shapes.append(
            _text_box(
                shape_id,
                f"Table Header {col_idx}",
                x,
                y0,
                col_w,
                row_h,
                [
                    _paragraph(
                        header,
                        size_pt=15,
                        color=theme.ink,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
                fill=theme.panel_alt,
                line=theme.rule,
            ),
        )
        shape_id += 1
    for row_idx, row in enumerate(rows[:6], start=1):
        for col_idx in range(1, col_count + 1):
            text = row[col_idx - 1] if col_idx - 1 < len(row) else ""
            x = x0 + (col_idx - 1) * col_w
            y = y0 + row_idx * row_h
            shapes.append(
                _text_box(
                    shape_id,
                    f"Table Cell {row_idx}-{col_idx}",
                    x,
                    y,
                    col_w,
                    row_h,
                    [
                        _paragraph(
                            text,
                            size_pt=13,
                            color=theme.body,
                            font_face=theme.font_family,
                        ),
                    ],
                    fill=theme.canvas,
                    line=theme.rule,
                ),
            )
            shape_id += 1
    return shape_id


def _layout_two_column(
    shapes: list[str],
    shape_id: int,
    slide: SlideSpec,
    theme: ThemeSpec,
    *,
    variant: str = "balanced",
) -> int:
    shape_id = _add_title_block(shapes, shape_id, slide, theme)
    columns = slide.columns or slide.items
    if not columns and slide.bullets:
        half = max(1, len(slide.bullets) // 2)
        columns = [
            {"title": "要点", "body": "\n".join(slide.bullets[:half])},
            {"title": "说明", "body": "\n".join(slide.bullets[half:])},
        ]
    entries = [
        columns[idx] if idx < len(columns) else {"title": "", "body": ""}
        for idx in range(2)
    ]

    if variant == "sidebar":
        sidebar, main = entries
        shapes.append(
            _shape_box(
                shape_id,
                "Two Column Sidebar Rail",
                0.72,
                2.04,
                0.12,
                4.36,
                fill=theme.accent,
                line=None,
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Sidebar Column Panel",
                0.9,
                2.04,
                3.25,
                4.36,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        if sidebar.get("title"):
            shapes.append(
                _text_box(
                    shape_id,
                    "Sidebar Column Title",
                    1.18,
                    2.42,
                    2.68,
                    0.52,
                    [
                        _paragraph(
                            sidebar["title"],
                            size_pt=18,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        if sidebar.get("body"):
            shapes.append(
                _text_box(
                    shape_id,
                    "Sidebar Column Body",
                    1.18,
                    3.18,
                    2.68,
                    2.58,
                    [
                        _paragraph(
                            line,
                            size_pt=14,
                            color=theme.body,
                            font_face=theme.font_family,
                        )
                        for line in str(sidebar["body"]).splitlines()
                        if line.strip()
                    ],
                ),
            )
            shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Main Column Panel",
                4.42,
                2.04,
                8.12,
                4.36,
                fill=theme.canvas,
                line=theme.rule,
            ),
        )
        shape_id += 1
        if main.get("title"):
            shapes.append(
                _text_box(
                    shape_id,
                    "Main Column Title",
                    4.82,
                    2.42,
                    7.32,
                    0.58,
                    [
                        _paragraph(
                            main["title"],
                            size_pt=22,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        if main.get("body"):
            shapes.append(
                _text_box(
                    shape_id,
                    "Main Column Body",
                    4.82,
                    3.18,
                    7.32,
                    2.72,
                    [
                        _paragraph(
                            line,
                            size_pt=16,
                            color=theme.body,
                            font_face=theme.font_family,
                        )
                        for line in str(main["body"]).splitlines()
                        if line.strip()
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "compare":
        shapes.append(
            _shape_box(
                shape_id,
                "Two Column Divider",
                6.65,
                2.02,
                0.035,
                4.42,
                fill=theme.rule,
                line=None,
            ),
        )
        shape_id += 1
        for idx, entry in enumerate(entries, start=1):
            x = 0.82 if idx == 1 else 6.96
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Compare Column {idx}",
                    x,
                    2.16,
                    5.36,
                    4.08,
                    fill=theme.panel if idx == 1 else theme.accent_soft,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Compare Column Badge {idx}",
                    x + 0.28,
                    2.48,
                    0.58,
                    0.58,
                    fill=theme.accent,
                    line=None,
                    geometry="ellipse",
                ),
            )
            shape_id += 1
            if entry.get("title"):
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Compare Column Title {idx}",
                        x + 1.02,
                        2.48,
                        3.96,
                        0.5,
                        [
                            _paragraph(
                                entry["title"],
                                size_pt=20,
                                color=theme.ink,
                                font_face=theme.font_family,
                                bold=True,
                            ),
                        ],
                    ),
                )
                shape_id += 1
            if entry.get("body"):
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Compare Column Body {idx}",
                        x + 0.34,
                        3.34,
                        4.68,
                        2.14,
                        [
                            _paragraph(
                                line,
                                size_pt=15,
                                color=theme.body,
                                font_face=theme.font_family,
                            )
                            for line in str(entry["body"]).splitlines()
                            if line.strip()
                        ],
                    ),
                )
                shape_id += 1
        return shape_id

    if variant == "offset":
        for idx, entry in enumerate(entries, start=1):
            x = 0.92 if idx == 1 else 6.5
            y = 2.2 if idx == 1 else 2.84
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Two Column Offset Band {idx}",
                    x + 0.28,
                    y - 0.2,
                    4.78,
                    0.32,
                    fill=theme.accent,
                    line=None,
                ),
            )
            shape_id += 1
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Two Column Offset Card {idx}",
                    x,
                    y,
                    5.26,
                    3.48,
                    fill=theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            if entry.get("title"):
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Two Column Offset Title {idx}",
                        x + 0.34,
                        y + 0.38,
                        4.58,
                        0.58,
                        [
                            _paragraph(
                                entry["title"],
                                size_pt=20,
                                color=theme.ink,
                                font_face=theme.font_family,
                                bold=True,
                            ),
                        ],
                    ),
                )
                shape_id += 1
            if entry.get("body"):
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Two Column Offset Body {idx}",
                        x + 0.34,
                        y + 1.14,
                        4.58,
                        1.88,
                        [
                            _paragraph(
                                line,
                                size_pt=15,
                                color=theme.body,
                                font_face=theme.font_family,
                            )
                            for line in str(entry["body"]).splitlines()
                            if line.strip()
                        ],
                    ),
                )
                shape_id += 1
        return shape_id

    if variant == "callout":
        primary, evidence = entries
        shapes.append(
            _shape_box(
                shape_id,
                "Two Column Callout Panel",
                0.82,
                2.08,
                7.2,
                4.18,
                fill=theme.accent,
                line=None,
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Two Column Evidence Panel",
                8.34,
                2.08,
                3.86,
                4.18,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        if primary.get("title"):
            shapes.append(
                _text_box(
                    shape_id,
                    "Two Column Callout Title",
                    1.18,
                    2.56,
                    6.36,
                    0.62,
                    [
                        _paragraph(
                            primary["title"],
                            size_pt=25,
                            color="FFFFFF",
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        if primary.get("body"):
            shapes.append(
                _text_box(
                    shape_id,
                    "Two Column Callout Body",
                    1.2,
                    3.36,
                    6.14,
                    1.7,
                    [
                        _paragraph(
                            line,
                            size_pt=16,
                            color="FFFFFF",
                            font_face=theme.font_family,
                        )
                        for line in str(primary["body"]).splitlines()
                        if line.strip()
                    ],
                ),
            )
            shape_id += 1
        if evidence.get("title"):
            shapes.append(
                _text_box(
                    shape_id,
                    "Two Column Evidence Title",
                    8.72,
                    2.58,
                    3.08,
                    0.44,
                    [
                        _paragraph(
                            evidence["title"],
                            size_pt=17,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "media":
        text_entry, media_entry = entries
        shapes.append(
            _shape_box(
                shape_id,
                "Two Column Text Rail",
                0.82,
                2.04,
                4.18,
                4.32,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Two Column Media Frame",
                5.36,
                2.04,
                6.98,
                4.32,
                fill=theme.accent_soft,
                line=theme.rule,
            ),
        )
        shape_id += 1
        if text_entry.get("title"):
            shapes.append(
                _text_box(
                    shape_id,
                    "Two Column Text Rail Title",
                    1.16,
                    2.46,
                    3.48,
                    0.5,
                    [
                        _paragraph(
                            text_entry["title"],
                            size_pt=18,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        if media_entry.get("title"):
            shapes.append(
                _text_box(
                    shape_id,
                    "Two Column Media Caption",
                    5.7,
                    5.62,
                    6.2,
                    0.34,
                    [
                        _paragraph(
                            media_entry["title"],
                            size_pt=13,
                            color=theme.body,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "decision":
        shapes.append(
            _shape_box(
                shape_id,
                "Two Column Decision Matrix",
                0.86,
                2.08,
                11.42,
                4.24,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        for idx, entry in enumerate(entries, start=1):
            x = 1.2 if idx == 1 else 6.72
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Two Column Decision Cell {idx}",
                    x,
                    2.54,
                    5.04,
                    3.3,
                    fill=theme.canvas if idx == 1 else theme.accent_soft,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            if entry.get("title"):
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Two Column Decision Title {idx}",
                        x + 0.32,
                        2.92,
                        4.34,
                        0.44,
                        [
                            _paragraph(
                                entry["title"],
                                size_pt=18,
                                color=theme.ink,
                                font_face=theme.font_family,
                                bold=True,
                            ),
                        ],
                    ),
                )
                shape_id += 1
        return shape_id

    if variant == "stacked":
        for idx, entry in enumerate(entries, start=1):
            y = 2.18 + (idx - 1) * 1.92
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Two Column Stack Card {idx}",
                    0.96 + (idx - 1) * 0.6,
                    y,
                    10.8 - (idx - 1) * 1.2,
                    1.48,
                    fill=theme.panel if idx == 1 else theme.accent_soft,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            if entry.get("title"):
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Two Column Stack Title {idx}",
                        1.28 + (idx - 1) * 0.6,
                        y + 0.34,
                        4.4,
                        0.38,
                        [
                            _paragraph(
                                entry["title"],
                                size_pt=18,
                                color=theme.ink,
                                font_face=theme.font_family,
                                bold=True,
                            ),
                        ],
                    ),
                )
                shape_id += 1
        return shape_id

    if variant == "stat_band":
        shapes.append(
            _shape_box(
                shape_id,
                "Two Column Stat Band",
                0.82,
                2.24,
                11.68,
                1.08,
                fill=theme.accent,
                line=None,
            ),
        )
        shape_id += 1
        for idx, entry in enumerate(entries, start=1):
            x = 1.1 + (idx - 1) * 5.78
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Two Column Stat {idx}",
                    x,
                    3.62,
                    5.18,
                    2.16,
                    fill=theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Two Column Stat Title {idx}",
                    x + 0.34,
                    3.94,
                    4.46,
                    0.48,
                    [
                        _paragraph(
                            entry.get("title", ""),
                            size_pt=20,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "quote_pair":
        for idx, entry in enumerate(entries, start=1):
            x = 0.92 if idx == 1 else 6.86
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Two Column Quote Panel {idx}",
                    x,
                    2.08,
                    5.32,
                    4.24,
                    fill=theme.panel if idx == 1 else theme.accent_soft,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Two Column Quote Mark {idx}",
                    x + 0.3,
                    2.44,
                    0.6,
                    0.62,
                    [
                        _paragraph(
                            "“",
                            size_pt=34,
                            color=theme.accent,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Two Column Quote Body {idx}",
                    x + 0.92,
                    2.7,
                    3.94,
                    1.42,
                    [
                        _paragraph(
                            line,
                            size_pt=16,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        )
                        for line in str(entry.get("body", entry.get("title", ""))).splitlines()
                        if line.strip()
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "timeline_pair":
        shapes.append(
            _shape_box(
                shape_id,
                "Two Column Timeline Rail",
                6.64,
                2.12,
                0.06,
                4.16,
                fill=theme.accent,
                line=None,
            ),
        )
        shape_id += 1
        for idx, entry in enumerate(entries, start=1):
            x = 0.9 if idx == 1 else 7.06
            y = 2.34 + (idx - 1) * 1.64
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Two Column Timeline Node {idx}",
                    6.45,
                    y + 0.18,
                    0.44,
                    0.44,
                    fill=theme.canvas,
                    line=theme.accent,
                    geometry="ellipse",
                ),
            )
            shape_id += 1
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Two Column Timeline Card {idx}",
                    x,
                    y,
                    5.08,
                    1.14,
                    fill=theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Two Column Timeline Title {idx}",
                    x + 0.3,
                    y + 0.28,
                    4.42,
                    0.36,
                    [
                        _paragraph(
                            entry.get("title", ""),
                            size_pt=17,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "image_compare":
        for idx, entry in enumerate(entries, start=1):
            x = 0.88 if idx == 1 else 6.84
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Two Column Image Compare Frame {idx}",
                    x,
                    2.08,
                    5.32,
                    3.44,
                    fill=theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Two Column Image Compare Caption {idx}",
                    x + 0.28,
                    5.72,
                    4.7,
                    0.34,
                    [
                        _paragraph(
                            entry.get("title", ""),
                            size_pt=13,
                            color=theme.body,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Two Column Image Divider",
                6.58,
                2.42,
                0.12,
                2.78,
                fill=theme.accent,
                line=None,
            ),
        )
        shape_id += 1
        return shape_id

    if variant == "qa":
        question, answer = entries
        shapes.append(
            _shape_box(
                shape_id,
                "Two Column QA Question",
                0.96,
                2.16,
                5.1,
                3.96,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Two Column QA Answer",
                6.72,
                2.16,
                5.58,
                3.96,
                fill=theme.accent_soft,
                line=theme.rule,
            ),
        )
        shape_id += 1
        shapes.append(
            _text_box(
                shape_id,
                "Two Column QA Question Text",
                1.34,
                2.66,
                4.32,
                0.72,
                [
                    _paragraph(
                        question.get("title", ""),
                        size_pt=22,
                        color=theme.ink,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        shapes.append(
            _text_box(
                shape_id,
                "Two Column QA Answer Text",
                7.1,
                2.66,
                4.78,
                0.72,
                [
                    _paragraph(
                        answer.get("title", ""),
                        size_pt=22,
                        color=theme.ink,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        return shape_id

    if variant == "summary_grid":
        shapes.append(
            _shape_box(
                shape_id,
                "Two Column Summary Grid",
                0.88,
                2.08,
                11.42,
                4.18,
                fill=theme.panel_alt,
                line=None,
            ),
        )
        shape_id += 1
        cells = [
            (0.98, 2.26, entries[0].get("title", "")),
            (6.64, 2.26, entries[1].get("title", "")),
            (0.98, 4.22, entries[0].get("body", "")),
            (6.64, 4.22, entries[1].get("body", "")),
        ]
        for idx, (x, y, text) in enumerate(cells, start=1):
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Two Column Summary Cell {idx}",
                    x,
                    y,
                    5.28,
                    1.52,
                    fill=theme.canvas,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            if text:
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Two Column Summary Text {idx}",
                        x + 0.28,
                        y + 0.32,
                        4.68,
                        0.52,
                        [
                            _paragraph(
                                line,
                                size_pt=15,
                                color=theme.ink if idx <= 2 else theme.body,
                                font_face=theme.font_family,
                                bold=idx <= 2,
                            )
                            for line in str(text).splitlines()
                            if line.strip()
                        ],
                    ),
                )
                shape_id += 1
        return shape_id

    for idx in range(2):
        entry = entries[idx]
        x = 0.72 + idx * 6.05
        shapes.append(
            _shape_box(
                shape_id,
                f"Column Panel {idx + 1}",
                x,
                2.04,
                5.75,
                4.32,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        if entry.get("title"):
            shapes.append(
                _text_box(
                    shape_id,
                    f"Column Title {idx + 1}",
                    x + 0.28,
                    2.36,
                    5.2,
                    0.58,
                    [
                        _paragraph(
                            entry["title"],
                            size_pt=20,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        if entry.get("body"):
            shapes.append(
                _text_box(
                    shape_id,
                    f"Column Body {idx + 1}",
                    x + 0.28,
                    3.12,
                    5.2,
                    2.4,
                    [
                        _paragraph(
                            line,
                            size_pt=15,
                            color=theme.body,
                            font_face=theme.font_family,
                        )
                        for line in entry["body"].splitlines()
                        if line.strip()
                    ],
                ),
            )
            shape_id += 1
    return shape_id


def _layout_agenda(
    shapes: list[str],
    shape_id: int,
    slide: SlideSpec,
    theme: ThemeSpec,
    *,
    variant: str = "list",
) -> int:
    shape_id = _add_title_block(shapes, shape_id, slide, theme)
    items = slide.items or _items_from_bullets(slide.bullets)

    if variant == "timeline":
        count = min(max(len(items), 1), 5)
        x0 = 0.92
        y = 3.5
        gap = 0.28
        item_w = (11.48 - gap * (count - 1)) / count
        shapes.append(
            _shape_box(
                shape_id,
                "Agenda Timeline Rail",
                x0,
                y + 0.34,
                11.48,
                0.05,
                fill=theme.rule,
                line=None,
            ),
        )
        shape_id += 1
        for idx, item in enumerate(items[:count], start=1):
            x = x0 + (idx - 1) * (item_w + gap)
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Agenda Timeline Node {idx}",
                    x,
                    y,
                    0.72,
                    0.72,
                    fill=theme.accent,
                    line=None,
                    geometry="ellipse",
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Agenda Timeline Number {idx}",
                    x + 0.2,
                    y + 0.16,
                    0.32,
                    0.28,
                    [
                        _paragraph(
                            str(idx),
                            size_pt=12,
                            color="FFFFFF",
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Agenda Timeline Item {idx}",
                    x,
                    y + 1.02,
                    item_w,
                    0.54,
                    [
                        _paragraph(
                            item.get("title", ""),
                            size_pt=15,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    if variant == "grid":
        card_w = 5.54
        card_h = 1.38
        positions = [(0.82, 2.04), (6.2, 2.04), (0.82, 3.76), (6.2, 3.76)]
        for idx, item in enumerate(items[:4], start=1):
            x, y = positions[idx - 1]
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Agenda Grid Card {idx}",
                    x,
                    y,
                    card_w,
                    card_h,
                    fill=theme.panel,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Agenda Grid Number {idx}",
                    x + 0.24,
                    y + 0.28,
                    0.58,
                    0.58,
                    fill=theme.accent,
                    line=None,
                    geometry="ellipse",
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Agenda Grid Title {idx}",
                    x + 1.04,
                    y + 0.28,
                    4.1,
                    0.36,
                    [
                        _paragraph(
                            item.get("title", ""),
                            size_pt=16,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            if item.get("body"):
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Agenda Grid Body {idx}",
                        x + 1.04,
                        y + 0.72,
                        4.1,
                        0.3,
                        [
                            _paragraph(
                                item["body"],
                                size_pt=11,
                                color=theme.body,
                                font_face=theme.font_family,
                            ),
                        ],
                    ),
                )
                shape_id += 1
        return shape_id

    if variant == "chapters":
        y = 2.04
        for idx, item in enumerate(items[:4], start=1):
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Agenda Chapter Card {idx}",
                    0.82,
                    y,
                    11.58,
                    0.9,
                    fill=theme.panel if idx % 2 else theme.accent_soft,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Agenda Chapter Index {idx}",
                    1.08,
                    y + 0.2,
                    0.62,
                    0.34,
                    [
                        _paragraph(
                            f"{idx:02d}",
                            size_pt=13,
                            color=theme.accent,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Agenda Chapter Title {idx}",
                    1.9,
                    y + 0.2,
                    4.6,
                    0.36,
                    [
                        _paragraph(
                            item.get("title", ""),
                            size_pt=17,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            if item.get("body"):
                shapes.append(
                    _text_box(
                        shape_id,
                        f"Agenda Chapter Body {idx}",
                        6.72,
                        y + 0.22,
                        5.1,
                        0.32,
                        [
                            _paragraph(
                                item["body"],
                                size_pt=12,
                                color=theme.body,
                                font_face=theme.font_family,
                            ),
                        ],
                    ),
                )
                shape_id += 1
            y += 1.04
        return shape_id

    if variant == "navigator":
        count = min(max(len(items), 1), 5)
        shapes.append(
            _shape_box(
                shape_id,
                "Agenda Navigator Rail",
                0.98,
                5.52,
                11.26,
                0.06,
                fill=theme.rule,
                line=None,
            ),
        )
        shape_id += 1
        card_w = 2.02
        gap = (11.26 - count * card_w) / max(count - 1, 1)
        for idx, item in enumerate(items[:count], start=1):
            x = 0.98 + (idx - 1) * (card_w + gap)
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Agenda Navigator Node {idx}",
                    x + 0.68,
                    5.18,
                    0.58,
                    0.58,
                    fill=theme.accent if idx == 1 else theme.canvas,
                    line=theme.accent,
                    geometry="ellipse",
                ),
            )
            shape_id += 1
            shapes.append(
                _shape_box(
                    shape_id,
                    f"Agenda Navigator Card {idx}",
                    x,
                    2.24,
                    card_w,
                    2.38,
                    fill=theme.panel if idx % 2 else theme.accent_soft,
                    line=theme.rule,
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Agenda Navigator Index {idx}",
                    x + 0.24,
                    2.56,
                    0.54,
                    0.3,
                    [
                        _paragraph(
                            f"{idx:02d}",
                            size_pt=12,
                            color=theme.accent,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
            shapes.append(
                _text_box(
                    shape_id,
                    f"Agenda Navigator Title {idx}",
                    x + 0.24,
                    3.08,
                    card_w - 0.48,
                    0.66,
                    [
                        _paragraph(
                            item.get("title", ""),
                            size_pt=15,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=True,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id

    y = 2.1
    for idx, item in enumerate(items[:6], start=1):
        shapes.append(
            _shape_box(
                shape_id,
                f"Agenda Number {idx}",
                0.82,
                y,
                0.58,
                0.58,
                fill=theme.accent,
                line=None,
                geometry="ellipse",
            ),
        )
        shape_id += 1
        shapes.append(
            _text_box(
                shape_id,
                f"Agenda Number Text {idx}",
                0.98,
                y + 0.13,
                0.28,
                0.22,
                [
                    _paragraph(
                        str(idx),
                        size_pt=12,
                        color="FFFFFF",
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        shapes.append(
            _text_box(
                shape_id,
                f"Agenda Item {idx}",
                1.62,
                y - 0.04,
                9.8,
                0.55,
                [
                    _paragraph(
                        item.get("title", ""),
                        size_pt=22,
                        color=theme.ink,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        if item.get("body"):
            shapes.append(
                _text_box(
                    shape_id,
                    f"Agenda Body {idx}",
                    1.66,
                    y + 0.48,
                    8.8,
                    0.38,
                    [
                        _paragraph(
                            item["body"],
                            size_pt=13,
                            color=theme.body,
                            font_face=theme.font_family,
                        ),
                    ],
                ),
            )
            shape_id += 1
        y += 0.82
    return shape_id


def _layout_comparison(
    shapes: list[str],
    shape_id: int,
    slide: SlideSpec,
    theme: ThemeSpec,
) -> int:
    shape_id = _add_title_block(shapes, shape_id, slide, theme)
    columns = slide.columns or slide.items
    if not columns and slide.bullets:
        half = max(1, len(slide.bullets) // 2)
        columns = [
            {"title": "Before", "body": "\n".join(slide.bullets[:half])},
            {"title": "After", "body": "\n".join(slide.bullets[half:])},
        ]
    while len(columns) < 2:
        columns.append({"title": "", "body": ""})
    for idx, entry in enumerate(columns[:2], start=1):
        x = 0.72 if idx == 1 else 6.78
        fill = theme.panel if idx == 1 else theme.accent_soft
        shapes.append(
            _shape_box(
                shape_id,
                f"Comparison Panel {idx}",
                x,
                2.1,
                5.82,
                4.28,
                fill=fill,
                line=theme.rule,
            ),
        )
        shape_id += 1
        shapes.append(
            _text_box(
                shape_id,
                f"Comparison Title {idx}",
                x + 0.34,
                2.46,
                5.1,
                0.62,
                [
                    _paragraph(
                        entry.get("title", ""),
                        size_pt=22,
                        color=theme.ink,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        body_lines = [
            line.strip()
            for line in entry.get("body", "").splitlines()
            if line.strip()
        ]
        if body_lines:
            shapes.append(
                _text_box(
                    shape_id,
                    f"Comparison Body {idx}",
                    x + 0.34,
                    3.24,
                    5.06,
                    2.1,
                    [
                        _paragraph(
                            f"- {line}",
                            size_pt=15,
                            color=theme.body,
                            font_face=theme.font_family,
                        )
                        for line in body_lines
                    ],
                ),
            )
            shape_id += 1
    return shape_id


def _layout_roadmap(
    shapes: list[str],
    shape_id: int,
    slide: SlideSpec,
    theme: ThemeSpec,
) -> int:
    shape_id = _add_title_block(shapes, shape_id, slide, theme)
    steps = slide.steps or _items_from_bullets(slide.bullets)
    count = min(max(len(steps), 1), 5)
    x0, y0, gap = 0.78, 2.58, 0.2
    step_w = (11.78 - gap * (count - 1)) / count
    shapes.append(
        _shape_box(
            shape_id,
            "Roadmap Rail",
            x0,
            y0 + 1.06,
            11.78,
            0.05,
            fill=theme.rule,
            line=None,
        ),
    )
    shape_id += 1
    for idx, step in enumerate(steps[:count], start=1):
        x = x0 + (idx - 1) * (step_w + gap)
        shapes.append(
            _shape_box(
                shape_id,
                f"Roadmap Step {idx}",
                x,
                y0,
                step_w,
                2.65,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                f"Roadmap Marker {idx}",
                x + 0.22,
                y0 + 0.86,
                0.42,
                0.42,
                fill=theme.accent,
                line=None,
                geometry="ellipse",
            ),
        )
        shape_id += 1
        shapes.append(
            _text_box(
                shape_id,
                f"Roadmap Title {idx}",
                x + 0.22,
                y0 + 0.22,
                step_w - 0.44,
                0.48,
                [
                    _paragraph(
                        step.get("title", ""),
                        size_pt=16,
                        color=theme.ink,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        if step.get("body"):
            shapes.append(
                _text_box(
                    shape_id,
                    f"Roadmap Body {idx}",
                    x + 0.2,
                    y0 + 1.44,
                    step_w - 0.4,
                    0.92,
                    [
                        _paragraph(
                            step["body"],
                            size_pt=12,
                            color=theme.body,
                            font_face=theme.font_family,
                        ),
                    ],
                ),
            )
            shape_id += 1
    return shape_id


def _layout_quote(
    shapes: list[str],
    shape_id: int,
    slide: SlideSpec,
    theme: ThemeSpec,
) -> int:
    shape_id = _add_title_block(shapes, shape_id, slide, theme)
    shapes.append(
        _text_box(
            shape_id,
            "Quote Mark",
            0.78,
            2.08,
            0.9,
            0.8,
            [
                _paragraph(
                    "“",
                    size_pt=54,
                    color=theme.accent,
                    font_face=theme.font_family,
                    bold=True,
                ),
            ],
        ),
    )
    shape_id += 1
    if slide.body:
        shapes.append(
            _text_box(
                shape_id,
                "Quote Body",
                1.72,
                2.24,
                10.4,
                2.2,
                [
                    _paragraph(
                        slide.body,
                        size_pt=28,
                        color=theme.ink,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
    attribution = slide.footer or slide.subtitle
    if attribution:
        shapes.append(
            _text_box(
                shape_id,
                "Quote Attribution",
                1.78,
                4.92,
                6.8,
                0.44,
                [
                    _paragraph(
                        attribution,
                        size_pt=14,
                        color=theme.muted,
                        font_face=theme.font_family,
                    ),
                ],
            ),
        )
        shape_id += 1
    return shape_id


def _layout_architecture(
    shapes: list[str],
    shape_id: int,
    slide: SlideSpec,
    theme: ThemeSpec,
) -> int:
    shape_id = _add_title_block(shapes, shape_id, slide, theme)
    nodes = slide.items or [{"title": bullet, "body": ""} for bullet in slide.bullets]
    nodes = nodes[:6]
    if not nodes and slide.body:
        nodes = [{"title": slide.body, "body": ""}]
    positions = [
        (0.9, 2.28),
        (4.78, 2.28),
        (8.66, 2.28),
        (0.9, 4.52),
        (4.78, 4.52),
        (8.66, 4.52),
    ]
    if len(nodes) >= 3:
        shapes.append(
            _shape_box(
                shape_id,
                "Architecture Connector",
                1.72,
                3.2,
                9.2,
                0.04,
                fill=theme.rule,
                line=None,
            ),
        )
        shape_id += 1
    for idx, node in enumerate(nodes, start=1):
        x, y = positions[idx - 1]
        shapes.append(
            _shape_box(
                shape_id,
                f"Architecture Node {idx}",
                x,
                y,
                3.0,
                1.42,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        shapes.append(
            _text_box(
                shape_id,
                f"Architecture Node Title {idx}",
                x + 0.22,
                y + 0.22,
                2.54,
                0.38,
                [
                    _paragraph(
                        node.get("title", ""),
                        size_pt=16,
                        color=theme.ink,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
        if node.get("body"):
            shapes.append(
                _text_box(
                    shape_id,
                    f"Architecture Node Body {idx}",
                    x + 0.22,
                    y + 0.68,
                    2.54,
                    0.46,
                    [
                        _paragraph(
                            node["body"],
                            size_pt=12,
                            color=theme.body,
                            font_face=theme.font_family,
                        ),
                    ],
                ),
            )
            shape_id += 1
    return shape_id


def _layout_section(
    shapes: list[str],
    shape_id: int,
    slide: SlideSpec,
    theme: ThemeSpec,
) -> int:
    shapes.append(
        _shape_box(
            shape_id,
            "Section Accent",
            0.72,
            1.3,
            1.18,
            0.1,
            fill=theme.accent,
            line=None,
        ),
    )
    shape_id += 1
    shapes.append(
        _shape_box(
            shape_id,
            "Section Panel",
            0.72,
            4.88,
            11.9,
            0.72,
            fill=theme.panel,
            line=None,
        ),
    )
    shape_id += 1
    if slide.kicker:
        shapes.append(
            _text_box(
                shape_id,
                "Section Kicker",
                0.82,
                2.4,
                11.6,
                0.42,
                [
                    _paragraph(
                        slide.kicker.upper(),
                        size_pt=13,
                        color=theme.accent,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
    if slide.title:
        shapes.append(
            _text_box(
                shape_id,
                "Section Title",
                0.82,
                2.9,
                11.6,
                1.1,
                [
                    _paragraph(
                        slide.title,
                        size_pt=48,
                        color=theme.ink,
                        font_face=theme.font_family,
                        bold=True,
                    ),
                ],
            ),
        )
        shape_id += 1
    if slide.subtitle:
        shapes.append(
            _text_box(
                shape_id,
                "Section Subtitle",
                0.86,
                4.05,
                9.2,
                0.56,
                [
                    _paragraph(
                        slide.subtitle,
                        size_pt=20,
                        color=theme.muted,
                        font_face=theme.font_family,
                    ),
                ],
            ),
        )
        shape_id += 1
    return shape_id


def _layout_content(
    shapes: list[str],
    shape_id: int,
    slide: SlideSpec,
    theme: ThemeSpec,
    *,
    variant: str = "plain",
) -> int:
    shape_id = _add_title_block(shapes, shape_id, slide, theme)
    paragraphs = _body_paragraphs(slide, theme)
    if variant == "modular":
        shapes.append(
            _shape_box(
                shape_id,
                "Content Modular Canvas",
                0.72,
                2.0,
                11.88,
                4.52,
                fill=theme.panel,
                line=theme.rule,
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Content Primary Panel",
                1.0,
                2.32,
                7.1,
                3.82,
                fill=theme.canvas,
                line=theme.rule,
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Content Support Rail",
                8.42,
                2.32,
                3.82,
                3.82,
                fill=theme.accent_soft,
                line=None,
            ),
        )
        shape_id += 1
        if slide.body:
            shapes.append(
                _text_box(
                    shape_id,
                    "Content Primary Text",
                    1.34,
                    2.72,
                    6.32,
                    1.4,
                    [
                        _paragraph(
                            slide.body,
                            size_pt=17,
                            color=theme.body,
                            font_face=theme.font_family,
                        ),
                    ],
                ),
            )
            shape_id += 1
        for idx, bullet in enumerate(slide.bullets[:5], start=1):
            shapes.append(
                _text_box(
                    shape_id,
                    f"Content Support Item {idx}",
                    8.74,
                    2.66 + (idx - 1) * 0.56,
                    3.1,
                    0.34,
                    [
                        _paragraph(
                            f"{idx}. {bullet}",
                            size_pt=12,
                            color=theme.ink,
                            font_face=theme.font_family,
                            bold=idx == 1,
                        ),
                    ],
                ),
            )
            shape_id += 1
        return shape_id
    if paragraphs:
        shapes.append(
            _text_box(
                shape_id,
                "Body",
                0.72,
                2.02,
                7.0 if slide.images else 11.3,
                4.6,
                paragraphs,
            ),
        )
        shape_id += 1
    return shape_id


def _append_layout_shapes(
    shapes: list[str],
    shape_id: int,
    slide: SlideSpec,
    slide_no: int,
    theme: ThemeSpec,
) -> tuple[int, str]:
    layout = _infer_layout(slide, slide_no)
    if layout in {"image_hero", "imagehero"}:
        template_slide_number = _resolve_template_slide_number(slide.layout)
        if template_slide_number is not None and 76 <= template_slide_number <= 77:
            cover_variants = ("cover_field", "cover_masthead")
            variant = cover_variants[(template_slide_number - 76) % len(cover_variants)]
        else:
            image_hero_variants = (
                "split",
                "full_bleed",
                "band",
                "mosaic",
                "poster",
                "device",
                "gallery",
            )
            variant = image_hero_variants[
                (template_slide_number - 59) % len(image_hero_variants)
            ] if template_slide_number is not None else "split"
        return _layout_image_hero(
            shapes,
            shape_id,
            slide,
            theme,
            variant=variant,
        ), "image_hero"
    if layout == "cards":
        return _layout_cards(shapes, shape_id, slide, theme), "cards"
    if layout in {"process", "timeline"}:
        template_slide_number = _resolve_template_slide_number(slide.layout)
        process_variants = (
            "horizontal",
            "vertical",
            "stair",
            "radial",
            "swimlane",
            "chevron",
            "cycle",
            "stack",
            "milestone",
            "ladder",
            "kanban",
            "funnel",
            "pyramid",
            "loopback",
            "sprint",
            "dependency",
            "gate",
            "wave",
            "ribbon",
            "orbit",
            "scorecard",
            "timeline_cards",
            "cascade",
            "quadrant",
            "bridge",
            "conveyor",
            "decision_tree",
            "matrix",
            "layered_timeline",
            "compass",
            "map_route",
            "pulse",
            "cluster",
            "evidence",
            "calendar",
            "handoff",
        )
        variant = process_variants[
            (template_slide_number - 1) % len(process_variants)
        ] if template_slide_number is not None else "horizontal"
        return _layout_process(shapes, shape_id, slide, theme, variant=variant), "process"
    if layout in {"metrics", "metric"}:
        template_slide_number = _resolve_template_slide_number(slide.layout)
        if template_slide_number is not None and 78 <= template_slide_number <= 79:
            chart_variants = ("chart_insight", "chart_split")
            variant = chart_variants[(template_slide_number - 78) % len(chart_variants)]
        else:
            metric_variants = (
                "cards",
                "leaderboard",
                "spotlight",
                "bars",
                "gauge",
                "tile_wall",
                "waterfall",
                "compare_ring",
            )
            variant = metric_variants[
                (template_slide_number - 51) % len(metric_variants)
            ] if template_slide_number is not None else "cards"
        return _layout_metrics(
            shapes,
            shape_id,
            slide,
            theme,
            variant=variant,
        ), "metrics"
    if layout == "table":
        template_slide_number = _resolve_template_slide_number(slide.layout)
        table_variants = ("grid", "matrix", "records", "heatmap", "timeline")
        variant = table_variants[
            (template_slide_number - 71) % len(table_variants)
        ] if template_slide_number is not None else "grid"
        return _layout_table(
            shapes,
            shape_id,
            slide,
            theme,
            variant=variant,
        ), "table"
    if layout == "agenda":
        template_slide_number = _resolve_template_slide_number(slide.layout)
        agenda_variants = ("list", "timeline", "grid", "chapters", "navigator")
        variant = agenda_variants[
            (template_slide_number - 66) % len(agenda_variants)
        ] if template_slide_number is not None else "list"
        return _layout_agenda(
            shapes,
            shape_id,
            slide,
            theme,
            variant=variant,
        ), "agenda"
    if layout == "comparison":
        return _layout_comparison(shapes, shape_id, slide, theme), "comparison"
    if layout == "roadmap":
        return _layout_roadmap(shapes, shape_id, slide, theme), "roadmap"
    if layout == "quote":
        return _layout_quote(shapes, shape_id, slide, theme), "quote"
    if layout == "architecture":
        return _layout_architecture(shapes, shape_id, slide, theme), "architecture"
    if layout in {"two_column", "two_columns"}:
        template_slide_number = _resolve_template_slide_number(slide.layout)
        two_column_variants = (
            "balanced",
            "sidebar",
            "compare",
            "offset",
            "callout",
            "media",
            "decision",
            "stacked",
            "stat_band",
            "quote_pair",
            "timeline_pair",
            "image_compare",
            "qa",
            "summary_grid",
        )
        variant = two_column_variants[
            (template_slide_number - 37) % len(two_column_variants)
        ] if template_slide_number is not None else "balanced"
        return _layout_two_column(
            shapes,
            shape_id,
            slide,
            theme,
            variant=variant,
        ), "two_column"
    if layout in {"section", "divider"}:
        return _layout_section(shapes, shape_id, slide, theme), "section"
    template_slide_number = _resolve_template_slide_number(slide.layout)
    if layout == "content" and template_slide_number == 80:
        return _layout_content(
            shapes,
            shape_id,
            slide,
            theme,
            variant="modular",
        ), "content"
    return _layout_content(shapes, shape_id, slide, theme), layout or "content"


def _custom_slide_xml(
    slide: SlideSpec,
    image_refs: list[dict[str, Any]],
    theme: ThemeSpec,
) -> str:
    shape_id = 2
    shapes = [_background_shape(shape_id, theme)]
    shape_id += 1
    image_iter = iter(image_refs)
    for layer in slide.custom_layers:
        layer_type = _clean_text(layer.get("type")).lower()
        if layer_type == "text":
            shapes.append(_compose_text_box(shape_id, layer, theme))
        elif layer_type == "image":
            image_ref = next(image_iter, None)
            if image_ref is None:
                raise ValueError(
                    f"custom image layer {_clean_text(layer.get('name'))!r} has no embedded image relation.",
                )
            shapes.append(
                _picture(
                    shape_id,
                    image_ref["rel_id"],
                    _clean_text(layer.get("name")),
                    _clean_text(layer.get("alt_text")) or image_ref["source_path"],
                    image_ref["box"],
                ),
            )
        else:
            fill_value = layer.get("fill")
            if layer_type == "line":
                fill_value = layer.get("color") or layer.get("line") or fill_value
            shapes.append(
                _shape_box(
                    shape_id,
                    _clean_text(layer.get("name")),
                    float(layer["x"]),
                    float(layer["y"]),
                    float(layer["w"]),
                    float(layer["h"]),
                    fill=_hex_color(fill_value, "") or None,
                    line=_hex_color(layer.get("line"), "") or None,
                    geometry=_clean_text(layer.get("geometry")) or "rect",
                    line_width_pt=_optional_float(layer.get("line_width")) or 1.0,
                ),
            )
        shape_id += 1

    layout_name = f"custom_compose:{slide.archetype or 'freeform'}"
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld name="layout:{_xml_text(layout_name)}">
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm>
      </p:grpSpPr>
      {''.join(shapes)}
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>"""


def _slide_xml(
    slide: SlideSpec,
    slide_no: int,
    image_refs: list[dict[str, Any]],
    theme: ThemeSpec,
) -> str:
    if slide.custom_layers:
        return _custom_slide_xml(slide, image_refs, theme)
    shape_id = 2
    shapes = [_background_shape(shape_id, theme)]
    shape_id += 1
    template_id = _resolve_template_id(slide.layout)
    if template_id:
        shapes.append(
            _shape_box(
                shape_id,
                f"Template Variant {template_id}",
                0,
                0,
                0.01,
                0.01,
                fill=None,
                line=None,
            ),
        )
        shape_id += 1

    background_refs = [
        ref
        for ref in image_refs
        if ref["role"] in {"background", "full_bleed", "full-bleed"}
    ]
    foreground_refs = [ref for ref in image_refs if ref not in background_refs]
    for image_ref in background_refs:
        shapes.append(
            _picture(
                shape_id,
                image_ref["rel_id"],
                f"Background Image {shape_id}",
                image_ref["source_path"],
                image_ref["box"],
            ),
        )
        shape_id += 1
        shapes.append(
            _shape_box(
                shape_id,
                "Background Overlay",
                0,
                0,
                SLIDE_WIDTH_IN,
                SLIDE_HEIGHT_IN,
                fill=theme.canvas,
                line=None,
            ),
        )
        shape_id += 1

    shape_id, layout = _append_layout_shapes(shapes, shape_id, slide, slide_no, theme)

    for image_ref in foreground_refs:
        shapes.append(
            _picture(
                shape_id,
                image_ref["rel_id"],
                f"Image {shape_id}",
                image_ref["source_path"],
                image_ref["box"],
            ),
        )
        shape_id += 1

    if slide.footer:
        shapes.append(
            _text_box(
                shape_id,
                "Footer",
                0.72,
                6.86,
                11.8,
                0.28,
                [
                    _paragraph(
                        slide.footer,
                        size_pt=10,
                        color=theme.muted,
                        font_face=theme.font_family,
                    ),
                ],
            ),
        )

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld name="layout:{_xml_text(layout)}">
    <p:spTree>
      <p:nvGrpSpPr>
        <p:cNvPr id="1" name=""/>
        <p:cNvGrpSpPr/>
        <p:nvPr/>
      </p:nvGrpSpPr>
      <p:grpSpPr>
        <a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm>
      </p:grpSpPr>
      {''.join(shapes)}
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>"""


def _rels_xml(rels: list[tuple[str, str, str]]) -> str:
    body = "".join(
        f'<Relationship Id="{rel_id}" Type="{rel_type}" Target="{target}"/>'
        for rel_id, rel_type, target in rels
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{body}</Relationships>"
    )


def _content_types(slide_count: int) -> str:
    slide_overrides = "".join(
        f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="{SLIDE_CT}"/>'
        for i in range(1, slide_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/ppt/presentation.xml" ContentType="{PML_CT}"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="{SLIDE_MASTER_CT}"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="{SLIDE_LAYOUT_CT}"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="{THEME_CT}"/>
  <Override PartName="/docProps/core.xml" ContentType="{CORE_CT}"/>
  <Override PartName="/docProps/app.xml" ContentType="{APP_CT}"/>
  {slide_overrides}
</Types>"""


def _presentation_xml(slide_count: int) -> str:
    slide_ids = "".join(
        f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>'
        for i in range(1, slide_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
  <p:sldIdLst>{slide_ids}</p:sldIdLst>
  <p:sldSz cx="{SLIDE_WIDTH_EMU}" cy="{SLIDE_HEIGHT_EMU}" type="wide"/>
  <p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>"""


def _master_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
    <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
  </p:spTree></p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
  <p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles>
</p:sldMaster>"""


def _layout_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
             type="blank" preserve="1">
  <p:cSld name="Blank"><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
    <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
  </p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>"""


def _theme_xml(theme: ThemeSpec) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="QwenPaw Presentation Builder">
  <a:themeElements>
    <a:clrScheme name="QwenPaw">
      <a:dk1><a:srgbClr val="{theme.ink}"/></a:dk1>
      <a:lt1><a:srgbClr val="{theme.canvas}"/></a:lt1>
      <a:dk2><a:srgbClr val="{theme.body}"/></a:dk2>
      <a:lt2><a:srgbClr val="{theme.panel}"/></a:lt2>
      <a:accent1><a:srgbClr val="{theme.accent}"/></a:accent1>
      <a:accent2><a:srgbClr val="{theme.muted}"/></a:accent2>
      <a:accent3><a:srgbClr val="{theme.panel_alt}"/></a:accent3>
      <a:accent4><a:srgbClr val="F59E0B"/></a:accent4>
      <a:accent5><a:srgbClr val="A855F7"/></a:accent5>
      <a:accent6><a:srgbClr val="F43F5E"/></a:accent6>
      <a:hlink><a:srgbClr val="{theme.accent}"/></a:hlink>
      <a:folHlink><a:srgbClr val="{theme.muted}"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="QwenPaw Fonts">
      <a:majorFont><a:latin typeface="{_xml_text(theme.font_family)}"/><a:ea typeface="{_xml_text(theme.font_family)}"/><a:cs typeface="{_xml_text(theme.font_family)}"/></a:majorFont>
      <a:minorFont><a:latin typeface="{_xml_text(theme.font_family)}"/><a:ea typeface="{_xml_text(theme.font_family)}"/><a:cs typeface="{_xml_text(theme.font_family)}"/></a:minorFont>
    </a:fontScheme>
    <a:fmtScheme name="QwenPaw Format">
      <a:fillStyleLst><a:solidFill><a:schemeClr val="accent1"/></a:solidFill></a:fillStyleLst>
      <a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="accent1"/></a:solidFill></a:ln></a:lnStyleLst>
      <a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>
      <a:bgFillStyleLst><a:solidFill><a:schemeClr val="lt1"/></a:solidFill></a:bgFillStyleLst>
    </a:fmtScheme>
  </a:themeElements>
</a:theme>"""


def _core_xml(title: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:dcterms="http://purl.org/dc/terms/"
                   xmlns:dcmitype="http://purl.org/dc/dcmitype/"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{_xml_text(title)}</dc:title>
  <dc:creator>QwenPaw presentation_builder</dc:creator>
  <dc:description>generated using qwenpaw presentation_builder with layout, asset, and QA checks</dc:description>
</cp:coreProperties>"""


def _app_xml(slide_count: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
            xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>QwenPaw</Application>
  <PresentationFormat>On-screen Show (16:9)</PresentationFormat>
  <Slides>{slide_count}</Slides>
</Properties>"""


def _build_pptx(
    output_path: Path,
    slides: list[SlideSpec],
    deck_title: str,
    theme: ThemeSpec,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    media_counter = 1

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as deck:
        deck.writestr("[Content_Types].xml", _content_types(len(slides)))
        deck.writestr(
            "_rels/.rels",
            _rels_xml(
                [
                    (
                        "rId1",
                        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
                        "ppt/presentation.xml",
                    ),
                    (
                        "rId2",
                        "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
                        "docProps/core.xml",
                    ),
                    (
                        "rId3",
                        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties",
                        "docProps/app.xml",
                    ),
                ],
            ),
        )
        deck.writestr("docProps/core.xml", _core_xml(deck_title))
        deck.writestr("docProps/app.xml", _app_xml(len(slides)))
        deck.writestr("ppt/presentation.xml", _presentation_xml(len(slides)))

        presentation_rels = [
            (
                "rId1",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster",
                "slideMasters/slideMaster1.xml",
            ),
        ]
        for slide_no in range(1, len(slides) + 1):
            presentation_rels.append(
                (
                    f"rId{slide_no + 1}",
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
                    f"slides/slide{slide_no}.xml",
                ),
            )
        deck.writestr("ppt/_rels/presentation.xml.rels", _rels_xml(presentation_rels))
        deck.writestr("ppt/slideMasters/slideMaster1.xml", _master_xml())
        deck.writestr(
            "ppt/slideMasters/_rels/slideMaster1.xml.rels",
            _rels_xml(
                [
                    (
                        "rId1",
                        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout",
                        "../slideLayouts/slideLayout1.xml",
                    ),
                    (
                        "rId2",
                        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme",
                        "../theme/theme1.xml",
                    ),
                ],
            ),
        )
        deck.writestr("ppt/slideLayouts/slideLayout1.xml", _layout_xml())
        deck.writestr(
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
            _rels_xml(
                [
                    (
                        "rId1",
                        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster",
                        "../slideMasters/slideMaster1.xml",
                    ),
                ],
            ),
        )
        deck.writestr("ppt/theme/theme1.xml", _theme_xml(theme))

        for slide_no, slide in enumerate(slides, start=1):
            slide_rels = [
                (
                    "rId1",
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout",
                    "../slideLayouts/slideLayout1.xml",
                ),
            ]
            image_refs: list[dict[str, Any]] = []
            layout = _infer_layout(slide, slide_no)
            for placement in slide.images:
                image_bytes, image_width, image_height = _ensure_image(placement.path)
                media_name = f"image{media_counter}.png"
                deck.writestr(f"ppt/media/{media_name}", image_bytes)
                rel_id = f"rId{len(slide_rels) + 1}"
                slide_rels.append(
                    (
                        rel_id,
                        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
                        f"../media/{media_name}",
                    ),
                )
                image_refs.append(
                    {
                        "rel_id": rel_id,
                        "source_path": str(placement.path),
                        "role": placement.role,
                        "box": _default_box(
                            placement,
                            (image_width, image_height),
                            layout,
                        ),
                    },
                )
                media_counter += 1

            deck.writestr(
                f"ppt/slides/slide{slide_no}.xml",
                _slide_xml(slide, slide_no, image_refs, theme),
            )
            deck.writestr(
                f"ppt/slides/_rels/slide{slide_no}.xml.rels",
                _rels_xml(slide_rels),
            )


def _sort_slide_preview_paths(paths: list[Path]) -> list[Path]:
    def key(path: Path) -> tuple[int, str]:
        match = re.search(r"(\d+)(?=\.png$)", path.name)
        return (int(match.group(1)) if match else 0, path.name)

    return sorted(paths, key=key)


def _create_contact_sheet(
    slide_images: list[Path],
    output_path: Path,
    *,
    columns: int = 3,
    thumbnail_width: int = 420,
) -> None:
    if not slide_images:
        raise ValueError("render QA did not produce slide images.")
    columns = max(1, min(columns, len(slide_images)))
    gap = 20
    label_height = 28
    margin = 24
    thumbnails: list[Image.Image] = []
    try:
        for image_path in slide_images:
            image = Image.open(image_path).convert("RGB")
            ratio = thumbnail_width / max(1, image.width)
            thumbnail_height = max(1, int(image.height * ratio))
            image = image.resize((thumbnail_width, thumbnail_height))
            thumbnails.append(image)

        cell_width = thumbnail_width
        cell_height = max(image.height for image in thumbnails) + label_height
        rows = (len(thumbnails) + columns - 1) // columns
        sheet_width = margin * 2 + columns * cell_width + (columns - 1) * gap
        sheet_height = margin * 2 + rows * cell_height + (rows - 1) * gap
        sheet = Image.new("RGB", (sheet_width, sheet_height), "white")
        draw = ImageDraw.Draw(sheet)
        for index, thumbnail in enumerate(thumbnails, start=1):
            row = (index - 1) // columns
            col = (index - 1) % columns
            x = margin + col * (cell_width + gap)
            y = margin + row * (cell_height + gap)
            sheet.paste(thumbnail, (x, y))
            draw.text((x, y + thumbnail.height + 6), f"Slide {index}", fill=(55, 65, 81))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(output_path)
    finally:
        for image in thumbnails:
            image.close()


def _renderer_paths() -> tuple[str | None, str | None]:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    pdftoppm = shutil.which("pdftoppm")
    return soffice, pdftoppm


def _run_render_command(command: list[str], timeout: int) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise ValueError(f"render QA command failed: {' '.join(command)} {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"render QA command timed out: {' '.join(command)}") from exc


def _render_pptx_preview(
    pptx_path: str | Path,
    preview_dir: str | Path | None = None,
) -> dict[str, Any]:
    path = _resolve_path(pptx_path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    soffice, pdftoppm = _renderer_paths()
    missing = []
    if not soffice:
        missing.append("soffice/libreoffice")
    if not pdftoppm:
        missing.append("pdftoppm")
    if missing:
        raise ValueError(
            "render QA requires " + " and ".join(missing) + " to be installed.",
        )

    preview_root = (
        _resolve_path(preview_dir)
        if preview_dir
        else path.parent / f"{path.stem}_render_qa"
    )
    preview_root.mkdir(parents=True, exist_ok=True)
    for stale in list(preview_root.glob("slide-*.png")) + [
        preview_root / "contact_sheet.png",
    ]:
        stale.unlink(missing_ok=True)
    work_dir = preview_root / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    for stale in work_dir.glob("*"):
        if stale.is_file():
            stale.unlink(missing_ok=True)

    _run_render_command(
        [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(work_dir),
            str(path),
        ],
        timeout=180,
    )
    pdf_path = work_dir / f"{path.stem}.pdf"
    if not pdf_path.exists():
        pdfs = sorted(work_dir.glob("*.pdf"), key=lambda item: item.stat().st_mtime)
        if not pdfs:
            raise ValueError("render QA failed: LibreOffice did not produce a PDF.")
        pdf_path = pdfs[-1]

    preview_prefix = preview_root / "slide"
    _run_render_command(
        [pdftoppm, "-png", "-r", "144", str(pdf_path), str(preview_prefix)],
        timeout=180,
    )
    slide_images = _sort_slide_preview_paths(list(preview_root.glob("slide-*.png")))
    if not slide_images:
        raise ValueError("render QA failed: pdftoppm did not produce slide PNGs.")
    contact_sheet = preview_root / "contact_sheet.png"
    _create_contact_sheet(slide_images, contact_sheet)
    return {
        "status": "ok",
        "engine": "libreoffice+pdftoppm",
        "preview_dir": str(preview_root),
        "contact_sheet": str(contact_sheet),
        "pdf_path": str(pdf_path),
        "slide_images": [str(path) for path in slide_images],
        "slide_count": len(slide_images),
    }


def _export_delivery_pdf(
    pptx_path: str | Path,
    render_result: dict[str, Any] | None = None,
) -> Path:
    path = _resolve_path(pptx_path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    target = path.with_suffix(".pdf")
    rendered_pdf = _clean_text((render_result or {}).get("pdf_path"))
    if rendered_pdf:
        source = _resolve_path(rendered_pdf)
        if source.exists() and source.is_file():
            if source.resolve() != target.resolve():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            return target

    soffice, _ = _renderer_paths()
    if not soffice:
        raise ValueError("PDF export requires soffice/libreoffice to be installed.")

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{path.stem}_pdf_", dir=target.parent) as tmp:
        work_dir = Path(tmp)
        _run_render_command(
            [
                soffice,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(work_dir),
                str(path),
            ],
            timeout=180,
        )
        pdf_path = work_dir / f"{path.stem}.pdf"
        if not pdf_path.exists():
            pdfs = sorted(work_dir.glob("*.pdf"), key=lambda item: item.stat().st_mtime)
            if not pdfs:
                raise ValueError("PDF export failed: LibreOffice did not produce a PDF.")
            pdf_path = pdfs[-1]
        shutil.copy2(pdf_path, target)
    return target


def _extract_text_values(xml: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", value).strip()
        for value in re.findall(r"<a:t>(.*?)</a:t>", xml, flags=re.S)
        if re.sub(r"\s+", " ", value).strip()
    ]


def _element_blocks(xml: str, tag: str) -> list[str]:
    return re.findall(rf"(<p:{tag}\b.*?</p:{tag}>)", xml, flags=re.S)


def _extract_box(block: str) -> tuple[int, int, int, int] | None:
    off = re.search(r"<a:off[^>]+x=\"(-?\d+)\"[^>]+y=\"(-?\d+)\"", block)
    ext = re.search(r"<a:ext[^>]+cx=\"(\d+)\"[^>]+cy=\"(\d+)\"", block)
    if not off or not ext:
        return None
    return (
        int(off.group(1)),
        int(off.group(2)),
        int(ext.group(1)),
        int(ext.group(2)),
    )


def _extract_name(block: str) -> str:
    match = re.search(r'<p:cNvPr[^>]+name="([^"]*)"', block)
    return match.group(1) if match else ""


def _extract_shape_id(block: str) -> int | None:
    match = re.search(r'<p:cNvPr[^>]+id="(\d+)"', block)
    return int(match.group(1)) if match else None


def _placeholder_type(block: str) -> str:
    match = re.search(r"<p:ph\b[^>]*\btype=\"([^\"]+)\"", block)
    return match.group(1) if match else ""


def _source_slide_paths(names: list[str]) -> dict[int, str]:
    slide_paths: dict[int, str] = {}
    for name in names:
        match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name)
        if match:
            slide_paths[int(match.group(1))] = name
    return slide_paths


def _is_source_slide_part(name: str) -> bool:
    return bool(
        re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        or re.fullmatch(r"ppt/slides/_rels/slide\d+\.xml\.rels", name),
    )


def _should_copy_template_part(name: str) -> bool:
    if name in {
        "[Content_Types].xml",
        "docProps/app.xml",
        "docProps/core.xml",
        "ppt/presentation.xml",
        "ppt/_rels/presentation.xml.rels",
    }:
        return False
    return not _is_source_slide_part(name)


def _rewrite_template_content_types(content_xml: str, slide_count: int) -> str:
    xml = re.sub(
        r'\s*<Override\b(?=[^>]*\bPartName="/ppt/slides/slide\d+\.xml")[^>]*/>',
        "",
        content_xml,
    )
    if 'Extension="png"' not in xml:
        default_png = (
            '<Default Extension="png" ContentType="image/png"/>'
        )
        if "<Override" in xml:
            xml = xml.replace("<Override", f"{default_png}\n  <Override", 1)
        else:
            xml = xml.replace("</Types>", f"  {default_png}\n</Types>")
    slide_overrides = "".join(
        f'\n  <Override PartName="/ppt/slides/slide{i}.xml" ContentType="{SLIDE_CT}"/>'
        for i in range(1, slide_count + 1)
    )
    return xml.replace("</Types>", f"{slide_overrides}\n</Types>")


def _rewrite_template_presentation_xml(presentation_xml: str, slide_count: int) -> str:
    slide_ids = "".join(
        f'<p:sldId id="{255 + i}" r:id="rIdQpSlide{i}"/>'
        for i in range(1, slide_count + 1)
    )
    replacement = f"<p:sldIdLst>{slide_ids}</p:sldIdLst>"
    if re.search(r"<p:sldIdLst\b.*?</p:sldIdLst>", presentation_xml, flags=re.S):
        return re.sub(
            r"<p:sldIdLst\b.*?</p:sldIdLst>",
            replacement,
            presentation_xml,
            count=1,
            flags=re.S,
        )
    return presentation_xml.replace("</p:presentation>", f"{replacement}</p:presentation>")


def _rewrite_template_presentation_rels(rels_xml: str, slide_count: int) -> str:
    xml = re.sub(
        r'\s*<Relationship\b(?=[^>]*\bType="[^"]*/slide")[^>]*/>',
        "",
        rels_xml,
    )
    slide_rels = "".join(
        (
            f'<Relationship Id="rIdQpSlide{i}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
            f'Target="slides/slide{i}.xml"/>'
        )
        for i in range(1, slide_count + 1)
    )
    return xml.replace("</Relationships>", f"{slide_rels}</Relationships>")


def _block_matches_target(block: str, target: dict[str, Any]) -> bool:
    if target.get("shape_name") and _extract_name(block) != target["shape_name"]:
        return False
    if target.get("shape_id") and _extract_shape_id(block) != target["shape_id"]:
        return False
    if target.get("placeholder_type") and _placeholder_type(block) != target["placeholder_type"]:
        return False
    if target.get("match_text"):
        values = _extract_text_values(block)
        if not any(target["match_text"] in value for value in values):
            return False
    return True


def _replace_text_runs(block: str, text: str) -> str:
    if "<a:t>" not in block:
        raise ValueError("matched template text target does not contain editable text.")
    first = True

    def replace(match: re.Match[str]) -> str:
        nonlocal first
        if first:
            first = False
            return f"{match.group(1)}{_xml_text(text)}{match.group(3)}"
        return f"{match.group(1)}{match.group(3)}"

    return re.sub(r"(<a:t>)(.*?)(</a:t>)", replace, block, flags=re.S)


def _apply_template_text_target(slide_xml: str, target: dict[str, Any]) -> str:
    for block in _element_blocks(slide_xml, "sp"):
        if _block_matches_target(block, target):
            return slide_xml.replace(
                block,
                _replace_text_runs(block, target["text"]),
                1,
            )
    raise ValueError(
        "template text edit target did not match an inherited shape: "
        f"{target.get('shape_name') or target.get('match_text') or target.get('shape_id')}",
    )


def _extract_picture_rel_id(block: str) -> str:
    match = re.search(r'\br:embed="([^"]+)"', block)
    return match.group(1) if match else ""


def _replace_relationship_target(rels_xml: str, rel_id: str, target: str) -> str:
    pattern = re.compile(
        r'(<Relationship\b(?=[^>]*\bId="'
        + re.escape(rel_id)
        + r'")[^>]*\bTarget=")([^"]*)(")',
    )
    if not pattern.search(rels_xml):
        raise ValueError(f"template image relationship was not found: {rel_id}")
    return pattern.sub(lambda match: f"{match.group(1)}{target}{match.group(3)}", rels_xml, count=1)


def _apply_template_image_target(
    slide_xml: str,
    rels_xml: str,
    target: dict[str, Any],
    slide_no: int,
    target_no: int,
) -> tuple[str, str, list[tuple[str, bytes]]]:
    for block in _element_blocks(slide_xml, "pic"):
        if not _block_matches_target(block, target):
            continue
        rel_id = _extract_picture_rel_id(block)
        if not rel_id:
            raise ValueError("matched template image target has no relationship id.")
        image_bytes, _, _ = _ensure_image(target["asset_path"])
        media_name = f"qwenpaw_template_image_{slide_no}_{target_no}.png"
        updated_rels = _replace_relationship_target(
            rels_xml,
            rel_id,
            f"../media/{media_name}",
        )
        return slide_xml, updated_rels, [(f"ppt/media/{media_name}", image_bytes)]
    raise ValueError(
        "template image edit target did not match an inherited picture: "
        f"{target.get('shape_name') or target.get('shape_id')}",
    )


def _apply_template_edit_targets(
    slide_xml: str,
    rels_xml: str,
    frame_entry: dict[str, Any],
    slide_no: int,
) -> tuple[str, str, list[tuple[str, bytes]]]:
    media_parts: list[tuple[str, bytes]] = []
    for target_no, target in enumerate(frame_entry["edit_targets"], start=1):
        if target["action"] == "rewrite":
            slide_xml = _apply_template_text_target(slide_xml, target)
            continue
        slide_xml, rels_xml, new_media = _apply_template_image_target(
            slide_xml,
            rels_xml,
            target,
            slide_no,
            target_no,
        )
        media_parts.extend(new_media)
    return slide_xml, rels_xml, media_parts


def _build_template_following_pptx(
    output_path: Path,
    template_path: str,
    frame_map: list[dict[str, Any]],
    deck_title: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    template = _resolve_path(template_path)

    with zipfile.ZipFile(template) as source:
        names = source.namelist()
        source_slides = _source_slide_paths(names)
        if "[Content_Types].xml" not in names:
            raise ValueError("template PPTX is missing [Content_Types].xml.")
        if "ppt/presentation.xml" not in names:
            raise ValueError("template PPTX is missing ppt/presentation.xml.")

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as deck:
            for name in names:
                if _should_copy_template_part(name):
                    deck.writestr(name, source.read(name))

            deck.writestr(
                "[Content_Types].xml",
                _rewrite_template_content_types(
                    source.read("[Content_Types].xml").decode("utf-8", errors="ignore"),
                    len(frame_map),
                ),
            )
            deck.writestr("docProps/core.xml", _core_xml(deck_title))
            deck.writestr("docProps/app.xml", _app_xml(len(frame_map)))
            deck.writestr(
                "ppt/presentation.xml",
                _rewrite_template_presentation_xml(
                    source.read("ppt/presentation.xml").decode("utf-8", errors="ignore"),
                    len(frame_map),
                ),
            )
            rels_xml = (
                source.read("ppt/_rels/presentation.xml.rels").decode(
                    "utf-8",
                    errors="ignore",
                )
                if "ppt/_rels/presentation.xml.rels" in names
                else _rels_xml([])
            )
            deck.writestr(
                "ppt/_rels/presentation.xml.rels",
                _rewrite_template_presentation_rels(rels_xml, len(frame_map)),
            )

            for slide_no, frame_entry in enumerate(frame_map, start=1):
                source_slide_path = source_slides.get(frame_entry["source_slide"])
                if not source_slide_path:
                    raise ValueError(
                        f"template source slide {frame_entry['source_slide']} was not found.",
                    )
                source_rels_path = (
                    "ppt/slides/_rels/"
                    f"slide{frame_entry['source_slide']}.xml.rels"
                )
                slide_xml = source.read(source_slide_path).decode(
                    "utf-8",
                    errors="ignore",
                )
                slide_rels_xml = (
                    source.read(source_rels_path).decode("utf-8", errors="ignore")
                    if source_rels_path in names
                    else _rels_xml([])
                )
                slide_xml, slide_rels_xml, media_parts = _apply_template_edit_targets(
                    slide_xml,
                    slide_rels_xml,
                    frame_entry,
                    slide_no,
                )
                deck.writestr(f"ppt/slides/slide{slide_no}.xml", slide_xml)
                deck.writestr(
                    f"ppt/slides/_rels/slide{slide_no}.xml.rels",
                    slide_rels_xml,
                )
                for media_name, media_bytes in media_parts:
                    deck.writestr(media_name, media_bytes)


def _extract_picture_bounds(xml: str) -> list[dict[str, Any]]:
    bounds: list[dict[str, Any]] = []
    for block in _element_blocks(xml, "pic"):
        box = _extract_box(block)
        if not box:
            continue
        bounds.append({"name": _extract_name(block), "box": box})
    return bounds


def _extract_text_box_bounds(xml: str) -> list[dict[str, Any]]:
    bounds: list[dict[str, Any]] = []
    for block in _element_blocks(xml, "sp"):
        if "<p:txBody>" not in block or not _extract_text_values(block):
            continue
        name = _extract_name(block)
        if name.startswith("Template Variant "):
            continue
        box = _extract_box(block)
        if not box:
            continue
        bounds.append({"name": name, "box": box})
    return bounds


def _overlap_ratio(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return 0.0
    overlap_area = (right - left) * (bottom - top)
    smaller_area = max(1, min(aw * ah, bw * bh))
    return overlap_area / smaller_area


def _picture_overlaps(xml: str) -> list[str]:
    pictures = _extract_picture_bounds(xml)
    overlaps: list[str] = []
    for first_index, first in enumerate(pictures):
        for second in pictures[first_index + 1 :]:
            ratio = _overlap_ratio(first["box"], second["box"])
            if ratio > 0.15:
                overlaps.append(
                    f"{first['name']} overlaps {second['name']} ({ratio:.0%})",
                )
    return overlaps


def _text_box_overlaps(xml: str) -> list[str]:
    text_boxes = _extract_text_box_bounds(xml)
    overlaps: list[str] = []
    for first_index, first in enumerate(text_boxes):
        for second in text_boxes[first_index + 1 :]:
            ratio = _overlap_ratio(first["box"], second["box"])
            if ratio > 0.25:
                overlaps.append(
                    f"{first['name']} overlaps {second['name']} ({ratio:.0%})",
                )
    return overlaps


def _qa_for_slide(xml: str) -> dict[str, Any]:
    text_values = _extract_text_values(xml)
    names = re.findall(r'<p:cNvPr[^>]* name="([^"]*)"', xml)
    layout_match = re.search(r'<p:cSld[^>]* name="layout:([^"]*)"', xml)
    layout = layout_match.group(1) if layout_match else "unknown"
    template_match = next(
        (
            re.match(r"Template Variant (.+)$", name)
            for name in names
            if name.startswith("Template Variant ")
        ),
        None,
    )
    template_id = template_match.group(1) if template_match else ""
    pic_count = xml.count("<p:pic")
    if layout.startswith("custom_compose:"):
        component_count = max(len([name for name in names if name != "Background"]), 0)
    else:
        component_count = sum(
            1
            for name in names
            if name.startswith(
                (
                    "Agenda Item",
                    "Architecture Node",
                    "Card ",
                    "Comparison Panel",
                    "Metric ",
                    "Process Step",
                    "Quote Mark",
                    "Roadmap Step",
                    "Section Accent",
                    "Table Cell",
                ),
            )
        )
    overlaps = _picture_overlaps(xml) + _text_box_overlaps(xml)
    media_frame_names = [
        name
        for name in names
        if (
            "Media Frame" in name
            or "Media Strip" in name
            or "Image Compare Frame" in name
            or "Gallery Frame" in name
            or "Mosaic Frame" in name
            or name in {"Hero Full Bleed Frame", "Hero Poster Frame"}
        )
    ]
    unfilled_media_frames = media_frame_names if pic_count == 0 else []
    weak = not text_values and pic_count == 0
    if len(text_values) <= 1 and pic_count == 0 and component_count == 0:
        weak = True
    return {
        "layout": layout,
        "template": template_id,
        "text_count": len(text_values),
        "pic_count": pic_count,
        "component_count": component_count,
        "overlap_count": len(overlaps),
        "overlaps": overlaps,
        "unfilled_media_frame_count": len(unfilled_media_frames),
        "unfilled_media_frames": unfilled_media_frames,
        "weak": weak,
    }


def inspect_pptx_media_usage(
    pptx_path: str | Path,
    required_image_assets: list[str] | None = None,
) -> dict[str, Any]:
    """Inspect a PPTX package for embedded media, picture nodes, and QA."""
    path = _resolve_path(pptx_path)
    required = required_image_assets or []
    if not path.exists():
        raise FileNotFoundError(str(path))

    with zipfile.ZipFile(path) as deck:
        names = deck.namelist()
        media_files = sorted(
            name for name in names if name.startswith("ppt/media/")
        )
        slide_files = sorted(
            (
                name
                for name in names
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            ),
            key=lambda value: int(re.search(r"slide(\d+)\.xml", value).group(1)),
        )
        pic_count = 0
        per_slide = []
        for slide_file in slide_files:
            xml = deck.read(slide_file).decode("utf-8", errors="ignore")
            pic_count += xml.count("<p:pic")
            per_slide.append(_qa_for_slide(xml))

    weak_count = sum(1 for item in per_slide if item["weak"])
    overlap_count = sum(int(item["overlap_count"]) for item in per_slide)
    layouts = [item["layout"] for item in per_slide]
    templates = [item["template"] for item in per_slide]
    used_templates = [template for template in templates if template]
    warnings: list[str] = []
    if weak_count:
        warnings.append(f"{weak_count} visually weak slide(s)")
    if overlap_count:
        warnings.append(f"{overlap_count} overlap(s) detected")
    if len(set(layouts)) <= 1 and len(layouts) > 2:
        warnings.append("layout variety is too low")
    if required and len(media_files) < len(required):
        warnings.append("not all required image assets were embedded")
    unfilled_media_frame_count = sum(
        int(item.get("unfilled_media_frame_count") or 0) for item in per_slide
    )

    return {
        "media_count": len(media_files),
        "media_files": media_files,
        "pic_count": pic_count,
        "slide_count": len(slide_files),
        "unused_required_assets": [] if not required else [],
        "qa": {
            "weak_slide_count": weak_count,
            "overlap_count": overlap_count,
            "layout_variety": len(set(layouts)),
            "template_variety": len(set(used_templates)),
            "layouts": layouts,
            "templates": templates,
            "warnings": warnings,
            "per_slide": per_slide,
            "unfilled_media_frame_count": unfilled_media_frame_count,
        },
    }


def _validate_custom_package(output: Path, slides: list[SlideSpec]) -> None:
    with zipfile.ZipFile(output) as deck:
        for slide_no, slide in enumerate(slides, start=1):
            xml = deck.read(f"ppt/slides/slide{slide_no}.xml").decode(
                "utf-8",
                errors="ignore",
            )
            expected_layout = f"layout:custom_compose:{slide.archetype or 'freeform'}"
            if expected_layout not in xml:
                raise ValueError(
                    f"custom package QA failed: slide {slide_no} lost its compose archetype.",
                )
            for layer in slide.custom_layers:
                name = _clean_text(layer.get("name"))
                if f'name="{_xml_text(name)}"' not in xml:
                    raise ValueError(
                        f"custom package QA failed: slide {slide_no} lost layer {name!r}.",
                    )
                if _clean_text(layer.get("type")).lower() == "text":
                    for line in _clean_text(layer.get("text")).splitlines():
                        if _xml_text(line) not in xml:
                            raise ValueError(
                                "custom package QA failed: "
                                f"slide {slide_no} lost text {line!r}.",
                            )
            expected_pictures = sum(
                1
                for layer in slide.custom_layers
                if _clean_text(layer.get("type")).lower() == "image"
            )
            if xml.count("<p:pic") != expected_pictures:
                raise ValueError(
                    "custom package QA failed: "
                    f"slide {slide_no} expected {expected_pictures} picture(s), "
                    f"got {xml.count('<p:pic')}.",
                )


def _final_delivery_visual_asset_warnings(
    *,
    usage: dict[str, Any],
    session_imagegen_assets: list[Path],
    referenced_assets: set[Path],
    visual_assets_setting: bool | str,
) -> list[str]:
    if visual_assets_setting is False:
        return []
    if not session_imagegen_assets:
        return []

    slide_count = int(usage.get("slide_count") or 0)
    pic_count = int(usage.get("pic_count") or 0)
    if slide_count < 8:
        return []

    minimum_source_assets = 3
    if len(session_imagegen_assets) < minimum_source_assets:
        asset_word = "asset" if len(session_imagegen_assets) == 1 else "assets"
        return [
            "visual asset suite is too thin: "
            f"{len(session_imagegen_assets)} generated image {asset_word} "
            f"for {slide_count} slides; expected at least "
            f"{minimum_source_assets} project-bound visual assets before "
            "final PPTX production",
        ]

    expected_pictures = min(
        len(session_imagegen_assets),
        max(3, (slide_count + 4) // 5),
    )
    if expected_pictures <= 0 or pic_count >= expected_pictures:
        return []

    return [
        "visual asset coverage is too low: "
        f"{pic_count} picture(s) for {slide_count} slides; "
        f"expected at least {expected_pictures} for a final deck with "
        "generated visual assets",
    ]


def _theme_compose_manifest(theme: ThemeSpec) -> dict[str, str]:
    return {
        "mode": theme.mode,
        "canvas": f"#{theme.canvas}",
        "ink": f"#{theme.ink}",
        "body": f"#{theme.body}",
        "muted": f"#{theme.muted}",
        "panel": f"#{theme.panel}",
        "panelAlt": f"#{theme.panel_alt}",
        "rule": f"#{theme.rule}",
        "accent": f"#{theme.accent}",
        "accentSoft": f"#{theme.accent_soft}",
        "fontFamily": theme.font_family,
    }


def _slide_content_roles(slide: SlideSpec) -> list[str]:
    roles: set[str] = set()
    if slide.title:
        roles.add("title")
    if slide.subtitle:
        roles.add("subtitle")
    if slide.body:
        roles.add("body")
    if slide.kicker:
        roles.add("kicker")
    if slide.bullets:
        roles.add("bullet")
    if slide.images:
        roles.add("image")
    if slide.items:
        roles.add("item")
    if slide.steps:
        roles.add("step")
    if slide.metrics:
        roles.add("metric")
    if slide.table:
        roles.add("table")
    if slide.columns:
        roles.add("column")
    if slide.footer:
        roles.add("footer")
    return sorted(roles)


def _image_asset_refs(slide: SlideSpec) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for index, placement in enumerate(slide.images, start=1):
        ref: dict[str, Any] = {
            "index": index,
            "path": str(placement.path),
            "role": placement.role,
            "label": placement.label,
            "purpose": placement.purpose,
            "usageMode": placement.usage_mode,
        }
        if placement.x is not None:
            ref["x"] = placement.x
        if placement.y is not None:
            ref["y"] = placement.y
        if placement.w is not None:
            ref["w"] = placement.w
        if placement.h is not None:
            ref["h"] = placement.h
        refs.append(ref)
    return refs


def _slide_content_counts(slide: SlideSpec) -> dict[str, int]:
    rows = slide.table.get("rows") if isinstance(slide.table, dict) else None
    return {
        "bullets": len(slide.bullets),
        "images": len(slide.images),
        "items": len(slide.items),
        "steps": len(slide.steps),
        "metrics": len(slide.metrics),
        "tableRows": len(rows) if isinstance(rows, list) else 0,
        "columns": len(slide.columns),
    }


def _slide_compose_manifest(
    slide: SlideSpec,
    slide_no: int,
    usage: dict[str, Any],
    frame_map: list[dict[str, Any]],
) -> dict[str, Any]:
    if slide.custom_layers:
        per_slide = usage["qa"].get("per_slide", [])
        slide_qa = per_slide[slide_no - 1] if slide_no - 1 < len(per_slide) else {}
        return {
            "slideNumber": slide_no,
            "title": slide.title,
            "route": "custom_compose",
            "archetype": slide.archetype or "freeform",
            "layerCount": len(slide.custom_layers),
            "layers": [
                {
                    "name": _clean_text(layer.get("name")),
                    "type": _clean_text(layer.get("type")).lower(),
                    "semanticGroup": _clean_text(layer.get("semantic_group")),
                    "bounds": {
                        key: float(layer[key])
                        for key in ("x", "y", "w", "h")
                    },
                }
                for layer in slide.custom_layers
            ],
            "expectedContent": slide.expected_content,
            "qa": {
                "layout": slide_qa.get("layout", ""),
                "componentCount": slide_qa.get("component_count", 0),
                "picCount": slide_qa.get("pic_count", 0),
                "overlapCount": slide_qa.get("overlap_count", 0),
                "weak": bool(slide_qa.get("weak", False)),
            },
        }
    template_id = _resolve_template_id(slide.layout)
    template = CODEX_GRID_TEMPLATE_BY_ID.get(template_id.lower()) if template_id else None
    canonical_layout = (
        str(template["canonicalLayout"]) if template else _infer_layout(slide, slide_no)
    )
    per_slide = usage["qa"].get("per_slide", [])
    slide_qa = per_slide[slide_no - 1] if slide_no - 1 < len(per_slide) else {}
    entry: dict[str, Any] = {
        "slideNumber": slide_no,
        "title": slide.title,
        "requestedLayout": slide.layout,
        "templateId": template_id,
        "templateSlideNumber": _resolve_template_slide_number(slide.layout),
        "canonicalLayout": canonical_layout,
        "contentRoles": _slide_content_roles(slide),
        "contentCounts": _slide_content_counts(slide),
        "assetRefs": _image_asset_refs(slide),
        "qa": {
            "layout": slide_qa.get("layout", ""),
            "template": slide_qa.get("template", ""),
            "componentCount": slide_qa.get("component_count", 0),
            "picCount": slide_qa.get("pic_count", 0),
            "overlapCount": slide_qa.get("overlap_count", 0),
            "weak": bool(slide_qa.get("weak", False)),
        },
    }
    if template:
        entry["templateUse"] = template["templateUse"]
        entry["layoutFamily"] = template["layoutFamily"]
    if frame_map and slide_no - 1 < len(frame_map):
        frame_entry = frame_map[slide_no - 1]
        entry["templateFrame"] = {
            "sourceSlide": frame_entry["source_slide"],
            "reuseMode": frame_entry["reuse_mode"],
            "narrativeRole": frame_entry["narrative_role"],
            "editTargetCount": len(frame_entry["edit_targets"]),
        }
    return entry


def _build_compose_manifest(
    output: Path,
    manifest_path: Path,
    pdf_path: Path | None,
    slides: list[SlideSpec],
    title: str,
    theme: ThemeSpec,
    usage: dict[str, Any],
    normalized_delivery_mode: str,
    effective_strict_qa: bool,
    effective_render_qa: bool,
    export_pdf_requested: bool,
    visual_assets_display: str,
    template_info: dict[str, Any],
    frame_map: list[dict[str, Any]],
    normalized_route_mode: str,
    compose_data: dict[str, Any],
    font_resolution: dict[str, Any],
    expected_slide_count: int | None,
    visual_direction_records: list[dict[str, str]],
) -> dict[str, Any]:
    output_info = {
        "pptx": str(output),
        "composeManifest": str(manifest_path),
    }
    if pdf_path:
        output_info["pdf"] = str(pdf_path)
    return {
        "schemaVersion": "qwenpaw.presentation.compose.v2",
        "authoringMode": "qwenpaw-pptx-compose",
        "title": title,
        "output": output_info,
        "route": normalized_route_mode,
        "layoutRegistry": {
            "name": "Codex Grid Layout Library compatible registry",
            "templateCount": len(CODEX_GRID_TEMPLATE_REGISTRY),
            "slideSize": {"width": 1280, "height": 720},
            "authoringMode": "qwenpaw-pptx-compose",
        },
        "delivery": {
            "mode": normalized_delivery_mode,
            "strictQa": effective_strict_qa,
            "renderQa": effective_render_qa,
            "exportPdf": export_pdf_requested,
            "requiresVisualAssets": visual_assets_display,
            "expectedSlideCount": expected_slide_count,
        },
        "visualDirection": {
            "directionName": visual_direction_records[0]["direction_name"],
            "productionAssets": visual_direction_records,
        }
        if visual_direction_records
        else None,
        "theme": _theme_compose_manifest(theme),
        "template": {
            "path": template_info.get("path", ""),
            "sourceSlideCount": template_info.get("source_slide_count", 0),
            "mode": "clone_edit" if frame_map else "theme_seed",
            "frameMapCount": len(frame_map),
        }
        if template_info
        else None,
        "customCompose": {
            "schemaVersion": _clean_text(compose_data.get("schema_version")) or "2.0",
            "visualTranslationContract": compose_data.get("visual_translation_contract") or {},
            "nativeTranslationRationale": _clean_text(
                compose_data.get("native_translation_rationale"),
            ),
            "fontResolution": font_resolution,
        }
        if normalized_route_mode == "custom_compose"
        else None,
        "slides": [
            _slide_compose_manifest(slide, index, usage, frame_map)
            for index, slide in enumerate(slides, start=1)
        ],
        "qa": {
            "slideCount": usage["slide_count"],
            "mediaCount": usage["media_count"],
            "picCount": usage["pic_count"],
            "layoutVariety": usage["qa"]["layout_variety"],
            "templateVariety": usage["qa"]["template_variety"],
            "weakSlideCount": usage["qa"]["weak_slide_count"],
            "overlapCount": usage["qa"]["overlap_count"],
            "warnings": usage["qa"]["warnings"],
        },
    }


async def presentation_builder(
    output_path: str,
    slides: list[dict[str, Any]] | str | None = None,
    required_image_assets: list[str] | str | None = None,
    asset_usage_matrix: list[dict[str, Any]] | str | None = None,
    deck_title: str = "",
    theme: dict[str, Any] | str | None = None,
    template_path: str | None = None,
    template_frame_map: list[dict[str, Any]] | dict[str, Any] | str | None = None,
    route_mode: str = "auto",
    compose_spec: dict[str, Any] | str | None = None,
    render_qa: bool = False,
    render_qa_dir: str | None = None,
    strict_qa: bool = False,
    delivery_mode: str = "auto",
    requires_visual_assets: bool | str = "auto",
    include_compose_manifest: bool | str = "auto",
    export_pdf: bool | str = "auto",
    expected_slide_count: int | str | None = None,
) -> ToolResponse:
    """Build an editable PPTX and fail if required images are not embedded.

    Args:
        output_path: Target `.pptx` path. Relative paths resolve from the
            current agent workspace.
        slides: Slide specs. Each slide may contain title, subtitle, body,
            bullets, layout, items, steps, metrics, table, columns, and images.
        required_image_assets: Generated image paths that must appear in the
            PPTX as direct raster images. Do not include component sheets,
            icon sheets, module sheets, connector sheets, moodboards, or
            style-reference boards that should be translated into native PPT
            components instead.
        asset_usage_matrix: Explicit image-to-slide mapping. Entries require
            `asset_path` (or `path`), a 1-based `slide_index`, a direct
            raster role such as `hero`/`background`/`wide`/`thumbnail`, and
            a short `purpose`.
        deck_title: Optional deck title metadata.
        theme: Optional theme object or theme name. Supports light/dark mode,
            accent, canvas, text colors, and font_family.
        template_path: Optional reference/template PPTX. The service inspects
            the template, records a template audit, and inherits its theme when
            no explicit theme is provided.
        template_frame_map: Optional clone/edit map for template-following.
            When provided, every output slide is duplicated from sourceSlide
            and editTargets rewrite inherited text or replace inherited images.
        route_mode: `auto`, `template_following`, `custom_compose`, or
            `codex_grid`. The legacy alias `custom_formatting` resolves to
            `custom_compose`.
        compose_spec: Exact editable layer authoring contract for
            `custom_compose`. Contains `slides`; every slide contains an
            archetype, named `layers`, and optional `expected_content`
            semantic QA assertions. The supported layer types are text,
            shape, line, and image.
        render_qa: When true, render the final PPTX to per-slide PNGs and a
            contact sheet using LibreOffice and pdftoppm. Missing render
            dependencies are treated as a failed QA gate.
        render_qa_dir: Optional directory for render QA PNG/PDF artifacts.
        strict_qa: When true, fail the export if visual QA reports weak slides
            or missing required image media.
        delivery_mode: `auto`, `draft`, or `final`. Final delivery forces
            strict QA and render QA even if the model forgets those flags.
            Auto treats service workspace outputs under WORKING_DIR as final.
            Draft/preview outputs under internal preview directories are not
            returned as user deliverables.
        requires_visual_assets: When true, fail unless generated image assets
            are provided and explicitly mapped into slides/template frames.
        include_compose_manifest: `auto`, true, or false. Auto emits a
            service-native source ledger for final delivery and leaves drafts
            lean unless explicitly set.
        export_pdf: `auto`, true, or false. Auto exports a user-facing PDF for
            final delivery and leaves drafts as PPTX-only unless explicitly set.
        expected_slide_count: Optional hard slide-count contract. Use the
            approved storyboard count for final delivery and the approved
            representative-page count for a prototype. A mismatch fails QA.
    """
    render_result: dict[str, Any] | None = None
    manifest_path: Path | None = None
    pdf_path: Path | None = None
    try:
        output = _resolve_output_path(output_path)
        compose_data = _as_dict(compose_spec, "compose_spec")
        if compose_data:
            if _as_list(slides, "slides"):
                raise ValueError("Pass slides inside compose_spec, not in both inputs.")
            slides_input = compose_data.get("slides")
            if theme is None and compose_data.get("theme") is not None:
                theme = compose_data.get("theme")
            if not deck_title:
                deck_title = _clean_text(
                    compose_data.get("deck_title") or compose_data.get("title"),
                )
            slide_size = _as_dict(compose_data.get("slide_size"), "compose_spec.slide_size")
            if slide_size:
                width = _optional_float(
                    slide_size.get("width")
                    if slide_size.get("width") not in (None, "")
                    else slide_size.get("w"),
                )
                height = _optional_float(
                    slide_size.get("height")
                    if slide_size.get("height") not in (None, "")
                    else slide_size.get("h"),
                )
                if width is None or height is None:
                    raise ValueError(
                        "compose_spec.slide_size requires width/height "
                        "(w/h aliases are also accepted).",
                    )
                if abs(width - SLIDE_WIDTH_IN) > 0.01 or abs(height - SLIDE_HEIGHT_IN) > 0.01:
                    raise ValueError(
                        "custom_compose currently requires a 13.333 x 7.5 inch 16:9 canvas.",
                    )
        else:
            slides_input = slides
        normalized_delivery_mode = _normalize_delivery_mode(delivery_mode, output)
        final_delivery = normalized_delivery_mode == "final"
        prototype_delivery = normalized_delivery_mode == "prototype"
        if final_delivery:
            output = _session_isolated_final_output_path(output)
        compose_manifest_setting = _as_bool_or_auto(include_compose_manifest)
        compose_manifest_requested = (
            bool(compose_manifest_setting)
            if compose_manifest_setting != "auto"
            else (final_delivery or prototype_delivery)
        )
        effective_strict_qa = bool(strict_qa) or final_delivery or prototype_delivery
        effective_render_qa = bool(render_qa) or final_delivery or prototype_delivery
        pdf_setting = _as_bool_or_auto(export_pdf)
        export_pdf_requested = (
            bool(pdf_setting)
            if pdf_setting != "auto"
            else final_delivery
        )
        visual_assets_setting = _as_bool_or_auto(requires_visual_assets)
        visual_assets_required = visual_assets_setting is True
        template_info = _inspect_template_pptx(template_path)
        if template_frame_map and not template_info:
            raise ValueError("template_frame_map requires template_path.")
        frame_map = _normalize_template_frame_map(
            template_frame_map,
            template_info.get("source_slide_count", 0),
        )
        normalized_route_mode = _normalize_route_mode(
            route_mode,
            has_template_frame_map=bool(frame_map),
            has_compose_spec=bool(compose_data),
        )
        asset_usage_entries = _as_list(asset_usage_matrix, "asset_usage_matrix")
        normalized_slides = _normalize_slides(
            slides_input,
            None if normalized_route_mode == "custom_compose" else asset_usage_entries,
        )
        expected_count = _optional_positive_int(
            expected_slide_count
            if expected_slide_count not in (None, "")
            else compose_data.get("expected_slide_count"),
            "expected_slide_count",
        )
        if expected_count is not None and len(normalized_slides) != expected_count:
            raise ValueError(
                "slide-count QA failed: expected_slide_count="
                f"{expected_count}, but received {len(normalized_slides)} slide(s). "
                "Restore the approved storyboard inventory instead of silently "
                "merging or dropping pages.",
            )
        if normalized_route_mode == "custom_compose":
            if asset_usage_entries:
                raise ValueError(
                    "custom_compose image placements belong in compose_spec slide layers; "
                    "do not pass asset_usage_matrix.",
                )
            _validate_custom_layers(normalized_slides)
        else:
            _apply_final_delivery_codex_grid_templates(
                normalized_slides,
                output=output,
                final_delivery=final_delivery,
                frame_map=frame_map,
            )
        required_assets = _normalize_required_assets(required_image_assets)
        referenced_assets = _referenced_assets(normalized_slides) | _referenced_template_assets(frame_map)
        visual_direction_records = _referenced_visual_direction_records(referenced_assets)
        visual_direction_names = sorted(
            {record["direction_name"] for record in visual_direction_records},
        )
        if len(visual_direction_names) > 1:
            raise ValueError(
                "visual direction QA failed: referenced imagegen assets mix "
                f"multiple selected directions: {', '.join(visual_direction_names)}. "
                "Regenerate or remap assets so every production asset uses the "
                "same selected direction_name.",
            )
        if visual_direction_records and normalized_route_mode == "codex_grid":
            raise ValueError(
                "visual route QA failed: referenced imagegen production assets "
                f"declare selected direction '{visual_direction_names[0]}', so "
                "route_mode=codex_grid is forbidden. Use route_mode=custom_compose "
                "with compose_spec and the selected visual-translation contract; "
                "do not downgrade an approved visual direction to theme colors.",
            )
        if (
            visual_direction_records
            and normalized_route_mode == "custom_compose"
            and not _as_dict(
                compose_data.get("visual_translation_contract"),
                "compose_spec.visual_translation_contract",
            )
        ):
            raise ValueError(
                "visual translation QA failed: custom_compose with selected "
                "imagegen production assets requires a non-empty "
                "compose_spec.visual_translation_contract.",
            )
        session_imagegen_assets = _current_session_imagegen_assets(output)
        native_translation_rationale = _clean_text(
            compose_data.get("native_translation_rationale"),
        )
        native_translation_approved = (
            normalized_route_mode == "custom_compose"
            and bool(native_translation_rationale)
        )
        explicit_visual_asset_bypass = (
            visual_assets_setting is False
            and final_delivery
            and bool(session_imagegen_assets)
            and not native_translation_approved
        )
        if explicit_visual_asset_bypass:
            asset_word = "asset" if len(session_imagegen_assets) == 1 else "assets"
            raise ValueError(
                "visual asset QA failed: requires_visual_assets=false is not "
                "allowed for final delivery because the current session has "
                f"{len(session_imagegen_assets)} generated image {asset_word}. "
                "Map the generated assets with required_image_assets and "
                "asset_usage_matrix, or create a true text-only draft under "
                "a draft/preview path instead of a final deck.",
            )
        auto_visual_assets_required = (
            visual_assets_setting == "auto"
            and final_delivery
            and bool(session_imagegen_assets)
            and not referenced_assets
            and not native_translation_approved
        )
        if auto_visual_assets_required:
            asset_word = "asset" if len(session_imagegen_assets) == 1 else "assets"
            raise ValueError(
                "visual asset QA failed: current session has "
                f"{len(session_imagegen_assets)} generated image {asset_word}, "
                "but none were mapped into the final deck. Pass "
                "required_image_assets and asset_usage_matrix, or create a "
                "true text-only draft under a draft/preview path if the user "
                "explicitly asked for one.",
            )
        if visual_assets_required and not required_assets:
            raise ValueError(
                "visual asset QA failed: requires_visual_assets=true but "
                "required_image_assets is empty. Provide generated visual "
                "assets and map them with asset_usage_matrix or "
                "template_frame_map replace-image targets.",
            )
        if visual_assets_required and not referenced_assets:
            raise ValueError(
                "visual asset QA failed: generated image assets were not "
                "mapped into the deck. Provide asset_usage_matrix entries "
                "or template_frame_map replace-image targets.",
            )
        _validate_required_assets(required_assets, referenced_assets)
        for asset in referenced_assets:
            _ensure_image(asset)

        final_visual_assets_active = (
            final_delivery
            and not template_info
            and (
                visual_assets_required
                or bool(required_assets)
                or bool(referenced_assets)
                or bool(session_imagegen_assets)
            )
        )
        if final_visual_assets_active and not _has_explicit_visual_theme(theme):
            raise ValueError(
                "visual design QA failed: final decks with generated visual "
                "assets require an explicit theme object derived from the "
                "selected visual scheme. Pass theme with selected-scheme "
                "canvas/ink/panel/accent/accent_soft/font_family values "
                "instead of relying on the default blue report theme.",
            )
        _validate_final_visual_asset_placements(
            normalized_slides,
            final_visual_assets_active=final_visual_assets_active,
        )

        theme_spec = _normalize_theme(theme) if theme is not None else _theme_from_template(template_info)
        font_resolution: dict[str, Any] = {}
        if normalized_route_mode == "custom_compose":
            font_resolution = _resolve_custom_compose_font(
                compose_data,
                theme_spec,
                normalized_slides,
            )
        title = deck_title or normalized_slides[0].title or output.stem
        if frame_map:
            _build_template_following_pptx(output, str(template_path), frame_map, title)
        else:
            _build_pptx(output, normalized_slides, title, theme_spec)
        if normalized_route_mode == "custom_compose":
            _validate_custom_package(output, normalized_slides)
        usage = inspect_pptx_media_usage(output, [str(path) for path in required_assets])
        if template_info:
            usage["qa"]["template"] = {
                "source_slide_count": template_info["source_slide_count"],
                "media_count": template_info["media_count"],
                "placeholder_count": template_info["placeholder_count"],
                "path": template_info["path"],
                "mode": "clone_edit" if frame_map else "theme_seed",
                "frame_map_count": len(frame_map),
            }
        if effective_render_qa:
            try:
                render_result = _render_pptx_preview(output, render_qa_dir)
            except Exception:
                output.unlink(missing_ok=True)
                raise
            usage["qa"]["render"] = render_result
            if render_result["slide_count"] != usage["slide_count"]:
                output.unlink(missing_ok=True)
                raise ValueError(
                    "render QA failed: rendered slide count does not match "
                    "the PPTX package slide count.",
                )
        if (
            final_delivery
            and not frame_map
            and normalized_route_mode == "codex_grid"
            and usage["qa"]["template_variety"] == 0
        ):
            output.unlink(missing_ok=True)
            raise ValueError(
                "Codex Grid layout QA failed: final workspace deliverables "
                "must use the 80-layout registry or template clone/edit. "
                "Pass layouts such as codex-grid-layout-library#slide-01, "
                "or provide template_path with template_frame_map.",
            )
        expected_images = len(referenced_assets)
        image_qa_failed = expected_images and (
            usage["media_count"] < expected_images
            or usage["pic_count"] < expected_images
        )
        if final_delivery and not frame_map and usage["qa"].get("unfilled_media_frame_count"):
            usage["qa"]["warnings"].append(
                f"{usage['qa']['unfilled_media_frame_count']} "
                "unfilled media frame(s) detected",
            )
        if not native_translation_approved:
            usage["qa"]["warnings"].extend(
                _final_delivery_visual_asset_warnings(
                    usage=usage,
                    session_imagegen_assets=session_imagegen_assets,
                    referenced_assets=referenced_assets,
                    visual_assets_setting=visual_assets_setting,
                ),
            )
        visual_qa_failed = effective_strict_qa and bool(usage["qa"]["warnings"])
        if image_qa_failed or visual_qa_failed:
            output.unlink(missing_ok=True)
            if image_qa_failed:
                raise ValueError(
                    "PPTX image QA failed: generated package does not contain "
                    "the expected embedded media and picture nodes.",
                )
            raise ValueError(
                "visual QA failed: " + "; ".join(usage["qa"]["warnings"]),
            )
        if export_pdf_requested:
            pdf_path = _export_delivery_pdf(output, render_result)
        if compose_manifest_requested:
            visual_assets_display = (
                "auto"
                if visual_assets_setting == "auto"
                else str(bool(visual_assets_setting)).lower()
            )
            manifest_path = output.with_suffix(".presentation.compose.json")
            manifest = _build_compose_manifest(
                output,
                manifest_path,
                pdf_path,
                normalized_slides,
                title,
                theme_spec,
                usage,
                normalized_delivery_mode,
                effective_strict_qa,
                effective_render_qa,
                export_pdf_requested,
                visual_assets_display,
                template_info,
                frame_map,
                normalized_route_mode,
                compose_data,
                font_resolution,
                expected_count,
                visual_direction_records,
            )
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return _text_response(f"Error: presentation_builder failed - {exc}")

    qa_warnings = len(usage["qa"]["warnings"])
    template_line = ""
    if usage["qa"].get("template"):
        template_qa = usage["qa"]["template"]
        template_line = (
            f"\nTemplate: template_source_slide_count={template_qa['source_slide_count']}, "
            f"template_media_count={template_qa['media_count']}, "
            f"template_placeholder_count={template_qa['placeholder_count']}, "
            f"template_mode={template_qa['mode']}, "
            f"template_frame_map={template_qa['frame_map_count']}"
        )
    render_line = ""
    if render_result:
        render_line = (
            f"\nRender QA: render_qa={render_result['status']}, "
            f"rendered_slide_count={render_result['slide_count']}, "
            f"contact_sheet={render_result['contact_sheet']}"
        )
    visual_assets_display = (
        "auto"
        if visual_assets_setting == "auto"
        else str(bool(visual_assets_setting)).lower()
    )
    internal_preview = _is_internal_preview_output(output)
    response_content: list[Any] = [] if internal_preview else [_file_block(output)]
    pdf_line = ""
    if pdf_path:
        if not internal_preview:
            response_content.append(_file_block(pdf_path))
        pdf_line = f"\nPDF: pdf={pdf_path}"
    manifest_line = ""
    if manifest_path:
        if not internal_preview:
            response_content.append(_file_block(manifest_path))
        manifest_line = f"\nCompose: compose_manifest={manifest_path}"
    if prototype_delivery:
        status_line = "Generated rendered prototype checkpoint with presentation_builder.\n"
        completion_line = (
            "Required checkpoint: present the rendered prototype contact sheet "
            "to the user and wait for explicit approval, revision instructions, "
            "or delegated approval. Do not generate the final deck in this turn."
        )
    elif internal_preview:
        status_line = "Generated internal draft preview with presentation_builder.\n"
        completion_line = (
            "Next required action: do not stop here; continue internal iteration "
            "or build a prototype checkpoint before final delivery when the task "
            "is client-ready or visual."
        )
    else:
        status_line = "Built editable PPTX with presentation_builder.\n"
        completion_line = (
            "The deck was exported with service-native editable text/shapes, "
            "the selected authoring route, explicit asset handling, and package-level QA."
        )
    internal_preview_line = (
        "\nDraft: internal_preview=true, not returned as a user deliverable\n"
        if internal_preview
        else ""
    )
    response_content.append(
        TextBlock(
            type="text",
            text=(
                f"{status_line}"
                f"Output: {output}\n"
                f"Slides: {usage['slide_count']}\n"
                f"Expected slides: {expected_count if expected_count is not None else 'not-set'}\n"
                f"Delivery: delivery_mode={normalized_delivery_mode}, "
                f"route_mode={normalized_route_mode}, "
                f"strict_qa={str(effective_strict_qa).lower()}, "
                f"render_qa={str(effective_render_qa).lower()}, "
                f"export_pdf={str(export_pdf_requested).lower()}, "
                f"requires_visual_assets={visual_assets_display}\n"
                f"QA: media_count={usage['media_count']}, "
                f"pic_count={usage['pic_count']}, "
                f"layout_variety={usage['qa']['layout_variety']}, "
                f"weak_slide_count={usage['qa']['weak_slide_count']}, "
                f"overlap_count={usage['qa']['overlap_count']}, "
                f"qa_warnings={qa_warnings}"
                f"{template_line}"
                f"{render_line}\n"
                f"{pdf_line}"
                f"{manifest_line}\n"
                f"{internal_preview_line}"
                f"{completion_line}"
            ),
        ),
    )
    return ToolResponse(
        content=response_content,
    )
