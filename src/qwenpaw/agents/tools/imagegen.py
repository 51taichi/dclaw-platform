# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements
"""Unified image generation tool for chat agents.

The public tool name is intentionally provider-neutral (`imagegen`).
GPT Image 2 through MXAPI is the first adapter behind it.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from agentscope.message import ImageBlock, TextBlock
from agentscope.tool import ToolResponse

from ...config.context import get_current_workspace_dir
from ...constant import DEFAULT_MEDIA_DIR
from ...providers.provider_manager import ProviderManager
from .send_file import _path_to_file_url

_DEFAULT_MXAPI_BASE_URL = "https://open.mxapi.org"
_VALID_QUALITIES = {"low", "medium", "high", "auto"}
_PRESENTATION_STAGES = {"visual_scheme", "visual_asset"}
_sleep = asyncio.sleep


def _text_response(text: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _provider_config_value(
    provider: Any,
    key: str,
    env_key: str,
    default: str = "",
) -> str:
    meta = getattr(provider, "meta", {}) or {}
    value = (
        getattr(provider, key, None)
        if key in {"api_key", "base_url"}
        else meta.get(key)
    )
    return _clean_text(value or os.environ.get(env_key) or default)


def _resolve_provider(provider_id: str | None = None) -> Any:
    manager = ProviderManager.get_instance()
    if provider_id:
        return manager.get_provider(provider_id)

    mxapi = manager.get_provider("mxapi")
    if mxapi is not None:
        return mxapi

    for info in manager.builtin_providers.values():
        meta = getattr(info, "meta", {}) or {}
        if meta.get("aigc_adapter") == "mxapi_gpt_image":
            return info
    return None


def _mxapi_base_url(provider: Any) -> str:
    return _provider_config_value(
        provider,
        "base_url",
        "MXAPI_BASE_URL",
        _DEFAULT_MXAPI_BASE_URL,
    ).rstrip("/")


def _mxapi_channel(provider: Any, channel: str | None = None) -> str:
    meta = getattr(provider, "meta", {}) or {}
    return (
        _clean_text(channel)
        or _clean_text(meta.get("channel"))
        or _clean_text(os.environ.get("MXAPI_CHANNEL"))
        or "default"
    )


def _normalize_quality(quality: str) -> str:
    mapped = {
        "低画质": "low",
        "标准画质": "medium",
        "高画质": "high",
    }.get(_clean_text(quality), _clean_text(quality).lower())
    return mapped if mapped in _VALID_QUALITIES else "auto"


def _aspect_ratio_from_size(size: str) -> str:
    match = re.fullmatch(r"\s*(\d+)\s*x\s*(\d+)\s*", size or "")
    if match is None:
        return ""
    width = int(match.group(1))
    height = int(match.group(2))
    if width <= 0 or height <= 0:
        return ""
    if width == height:
        return "1:1"
    if width > height:
        return "16:9"
    return "9:16"


def _normalize_reference_images(reference_images: list[str] | str | None) -> list[str]:
    if reference_images is None:
        return []
    if isinstance(reference_images, str):
        values = [reference_images]
    else:
        values = list(reference_images)
    images: list[str] = []
    for value in values[:16]:
        cleaned = _clean_text(value)
        if not cleaned:
            continue
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(
                "MXAPI GPT Image 2 reference images must be public HTTP(S) URLs.",
            )
        images.append(cleaned)
    return images


def _presentation_stage(
    prompt: str,
    presentation_context: dict[str, Any] | None,
) -> str:
    context = presentation_context or {}
    requested = _clean_text(context.get("stage")).lower().replace("-", "_")
    if requested in _PRESENTATION_STAGES:
        return requested

    lowered = prompt.lower()
    is_presentation = any(
        marker in lowered
        for marker in ("powerpoint", "ppt", "slide deck", "presentation deck")
    )
    if not is_presentation:
        return ""
    if any(
        marker in lowered
        for marker in (
            "visual scheme",
            "visual direction",
            "contact sheet",
            "视觉方案",
            "视觉方向",
        )
    ):
        return "visual_scheme"
    if any(
        marker in lowered
        for marker in (
            "background",
            "hero",
            "texture",
            "asset sheet",
            "pictogram",
            "背景",
            "主视觉",
            "素材",
            "图标",
        )
    ):
        return "visual_asset"
    return ""


def _context_text(context: dict[str, Any], key: str, fallback: str = "") -> str:
    value = context.get(key)
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_clean_text(item) for item in value if _clean_text(item))
    return _clean_text(value) or fallback


def _compile_presentation_prompt(
    prompt: str,
    stage: str,
    presentation_context: dict[str, Any] | None,
) -> str:
    if stage not in _PRESENTATION_STAGES:
        return prompt
    if re.search(r"(?im)^\s*use case:\s*productivity-visual\s*$", prompt):
        return prompt

    context = presentation_context or {}
    deck_topic = _context_text(context, "deck_topic", "the supplied deck topic")
    audience = _context_text(context, "audience", "the intended decision-makers")
    direction_name = _context_text(
        context,
        "direction_name",
        "the selected design DNA",
    )
    commercial_rationale = _context_text(
        context,
        "commercial_rationale",
        "Preserve commercial credibility, visual distinction, and editable-PPT viability.",
    )

    if stage == "visual_scheme":
        represented_pages = _context_text(
            context,
            "represented_pages",
            "cover, thesis, chart/evidence, process/architecture, roadmap/closing",
        )
        visual_temperature = _context_text(
            context,
            "visual_temperature",
            "balanced",
        )
        dominant_anchor = _context_text(
            context,
            "dominant_visual_anchor",
            "a clear visual anchor beyond color, gradients, icons, or ordinary cards",
        )
        forbidden_patterns = _context_text(
            context,
            "forbidden_patterns",
            "generic enterprise dashboards, repeated rounded rectangles, and palette-only differentiation",
        )
        return "\n".join(
            (
                "Use case: productivity-visual",
                "Asset type: visual direction contact sheet for an editable PowerPoint deck",
                f"Primary request: {prompt}",
                f"Deck topic: {deck_topic}",
                f"Audience: {audience}",
                f"Style direction: {direction_name}",
                f"Visual temperature: {visual_temperature}",
                f"Dominant visual anchor: {dominant_anchor}",
                f"Commercial rationale: {commercial_rationale}",
                f"Represented slide archetypes: {represented_pages}",
                "Content constraints: Use only large placeholder headings and simple labels. No small body text, dense tables, precise numbers, or finished text-heavy slide screenshots.",
                "Composition: Show five distinct slide rhythms that can later be rebuilt with editable PowerPoint components. Generate one scheme only; do not combine A/B/C visual directions in this image.",
                "Output role: This image is a visual-direction reference, not a final slide and not a raster source for editable slide text.",
                "Avoid: rasterized small text, fake unreadable charts, decorative clutter, generic SaaS card grids, stock PPT templates, repeated rounded rectangles, tiny UI labels, blue-purple dashboard sameness, watermarks, and unprovided logos.",
                f"Forbidden patterns for this scheme: {forbidden_patterns}",
            )
        )

    asset_type = _context_text(
        context,
        "asset_type",
        "reusable visual asset suite element",
    )
    composition = _context_text(
        context,
        "composition",
        "Compose for the intended slide placement and preserve the requested crop.",
    )
    reserved_text_area = _context_text(
        context,
        "reserved_text_area",
        "Leave the planned editable text area visually calm.",
    )
    output_role = _context_text(
        context,
        "output_role",
        "This will be placed as a separate image layer behind or beside editable PowerPoint text and shapes.",
    )
    forbidden_patterns = _context_text(
        context,
        "forbidden_patterns",
        "complete slide screenshots, fake UI, text baked into the image, and generic stock imagery",
    )
    return "\n".join(
        (
            "Use case: productivity-visual",
            f"Asset type: {asset_type} for an editable PowerPoint deck",
            f"Primary request: {prompt}",
            f"Deck topic: {deck_topic}",
            f"Audience: {audience}",
            f"Style direction: {direction_name}",
            f"Commercial rationale: {commercial_rationale}",
            f"Composition: {composition}",
            f"Reserved text area: {reserved_text_area}",
            "Content constraints: No readable body text, labels, numbers, charts, tables, watermarks, or logos unless a real logo was explicitly provided.",
            f"Output role: {output_role}",
            "Avoid: complete slide layouts, fake UI details, clutter, tiny typography, generic gradients, and stock-photo blandness.",
            f"Forbidden patterns for this asset: {forbidden_patterns}",
        )
    )


def _is_full_slide_asset(context: dict[str, Any] | None) -> bool:
    asset_type = _context_text(context or {}, "asset_type").lower()
    return any(
        marker in asset_type
        for marker in (
            "background",
            "hero",
            "full-bleed",
            "section divider",
            "closing",
            "背景",
            "主视觉",
            "全幅",
        )
    )


def _write_generation_manifest(
    output_path: Path,
    *,
    original_prompt: str,
    effective_prompt: str,
    presentation_stage: str,
    presentation_context: dict[str, Any] | None,
    aspect_ratio: str,
    quality: str,
    resolution: str,
    task_id: str,
) -> None:
    manifest_path = output_path.with_suffix(".imagegen.json")
    manifest_path.write_text(
        json.dumps(
            {
                "schemaVersion": "qwenpaw.imagegen.v1",
                "originalPrompt": original_prompt,
                "effectivePrompt": effective_prompt,
                "promptProfile": presentation_stage or "generic",
                "presentationContext": presentation_context or {},
                "generation": {
                    "aspectRatio": aspect_ratio,
                    "quality": quality,
                    "resolution": resolution,
                    "taskId": task_id,
                },
                "output": {"filename": output_path.name},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _task_id(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    for candidate in (
        data.get("task_id"),
        data.get("id"),
        payload.get("task_id"),
        payload.get("id"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _http_error_message(response: httpx.Response) -> str:
    message = ""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        for candidate in (
            payload.get("message"),
            payload.get("error"),
            payload.get("detail"),
            data.get("message"),
            data.get("error"),
            data.get("error_message"),
            data.get("error_msg"),
        ):
            message = _clean_text(candidate)
            if message:
                break
    if not message:
        message = _clean_text(getattr(response, "text", ""))
    return message or f"HTTP {getattr(response, 'status_code', 'error')}"


async def _submit_task(
    provider: Any,
    *,
    prompt: str,
    aspect_ratio: str,
    quality: str,
    resolution: str,
    reference_images: list[str],
    channel: str | None,
) -> str:
    api_key = _provider_config_value(provider, "api_key", "MXAPI_KEY")
    if not api_key:
        raise RuntimeError("MXAPI_KEY is not configured for imagegen.")

    body: dict[str, Any] = {
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "quality": quality,
        "resolution": resolution,
    }
    if reference_images:
        body["reference_images"] = reference_images

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=15.0),
        trust_env=False,
    ) as client:
        response = await client.post(
            f"{_mxapi_base_url(provider)}/api/v2/gpt-image-2",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-Channel": _mxapi_channel(provider, channel),
            },
            json=body,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(_http_error_message(exc.response)) from exc

    payload = response.json()
    task_id = _task_id(payload)
    if payload.get("code") not in {None, 200} or not task_id:
        raise RuntimeError(
            _clean_text(payload.get("message")) or "MXAPI task submission failed.",
        )
    return task_id


def _completed_image_url(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    images = result.get("images")
    if isinstance(images, list):
        for image in images:
            if isinstance(image, str) and image.strip():
                return image.strip()
    return ""


def _task_error_message(payload: dict[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return (
        _clean_text(data.get("error_message"))
        or _clean_text(data.get("error_msg"))
        or _clean_text(payload.get("message"))
        or "MXAPI image generation failed."
    )


async def _query_task(provider: Any, task_id: str) -> tuple[str, str]:
    api_key = _provider_config_value(provider, "api_key", "MXAPI_KEY")
    if not api_key:
        raise RuntimeError("MXAPI_KEY is not configured for imagegen.")

    base_url = _mxapi_base_url(provider)
    urls = [
        f"{base_url}/api/v2/gpt-image/task?task_id={task_id}",
        f"{base_url}/api/v2/gpt-image/task/{task_id}",
    ]
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        trust_env=False,
    ) as client:
        for url in urls:
            try:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                response.raise_for_status()
            except httpx.TimeoutException:
                return "running", ""
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    continue
                raise RuntimeError(_http_error_message(exc.response)) from exc
            payload = response.json()
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            status = _clean_text(data.get("status"))
            if status == "completed":
                image_url = _completed_image_url(payload)
                if image_url:
                    return "completed", image_url
                raise RuntimeError("MXAPI completed without an image URL.")
            if status == "failed":
                raise RuntimeError(_task_error_message(payload))
            return "running", ""
    return "running", ""


async def _poll_task(provider: Any, task_id: str) -> str:
    timeout_seconds = float(os.environ.get("MXAPI_POLL_TIMEOUT_SECONDS") or 240)
    interval_seconds = float(os.environ.get("MXAPI_POLL_INTERVAL_SECONDS") or 1.5)
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    while loop.time() - started_at < timeout_seconds:
        status, image_url = await _query_task(provider, task_id)
        if status == "completed" and image_url:
            return image_url
        await _sleep(interval_seconds)
    raise RuntimeError("MXAPI image generation timed out.")


async def _download_image(url: str) -> tuple[bytes, str]:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=15.0),
        follow_redirects=True,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
    mime_type = (
        response.headers.get("content-type", "").split(";", 1)[0].strip()
        or "image/png"
    )
    return response.content, mime_type


def _suffix_for_mime_type(mime_type: str) -> str:
    clean_mime = mime_type.split(";", 1)[0].strip().lower()
    if clean_mime == "image/jpeg":
        return "jpg"
    if clean_mime in {"image/png", "image/webp", "image/gif"}:
        guessed = mimetypes.guess_extension(clean_mime)
        return guessed.lstrip(".") if guessed else "png"
    return "png"


def _output_directory(output_dir: str | None) -> Path:
    if output_dir:
        path = Path(output_dir).expanduser()
    else:
        workspace_dir = get_current_workspace_dir()
        path = (
            Path(workspace_dir).expanduser() / "media" / "imagegen"
            if workspace_dir
            else DEFAULT_MEDIA_DIR / "imagegen"
        )
    path.mkdir(parents=True, exist_ok=True)
    return path


def _display_url_for_output(output_path: Path) -> str:
    return _path_to_file_url(str(output_path.resolve()))


def _preview_path_for_output(output_path: Path) -> str:
    workspace_dir = get_current_workspace_dir()
    if workspace_dir:
        try:
            return (
                output_path.resolve()
                .relative_to(Path(workspace_dir).expanduser().resolve())
                .as_posix()
            )
        except ValueError:
            pass
    return _display_url_for_output(output_path)


async def imagegen(
    prompt: str,
    aspect_ratio: str = "1:1",
    quality: str = "auto",
    resolution: str = "1K",
    reference_images: list[str] | str | None = None,
    output_dir: str | None = None,
    provider_id: str | None = "mxapi",
    channel: str | None = None,
    presentation_context: dict[str, Any] | None = None,
) -> ToolResponse:
    """Generate or edit an image through QwenPaw's unified imagegen adapter.

    Args:
        prompt: Image prompt. For PPT visual schemes, request a 16:9
            contact sheet or a single 16:9 representative direction.
        aspect_ratio: Output aspect ratio, such as "16:9", "1:1", or "9:16".
        quality: One of "low", "medium", "high", or "auto".
        resolution: MXAPI resolution tier, such as "1K", "2K", "3K", or "4K".
        reference_images: Optional public HTTP(S) reference image URLs.
        output_dir: Optional local directory to save the generated image.
        provider_id: Provider id. Defaults to the configured MXAPI provider.
        channel: Optional MXAPI channel override.
        presentation_context: Optional structured PPT prompt contract. Set
            ``stage`` to ``visual_scheme`` or ``visual_asset`` and provide
            fields such as ``deck_topic``, ``audience``, ``direction_name``,
            ``visual_temperature``, ``dominant_visual_anchor``,
            ``commercial_rationale``, ``represented_pages``, ``asset_type``,
            ``composition``, ``reserved_text_area``, ``output_role``, and
            ``forbidden_patterns``. PPT-like prompts are auto-detected when
            this context is omitted.
    """
    original_prompt = _clean_text(prompt)
    if not original_prompt:
        return _text_response("Error: prompt is required for imagegen.")

    presentation_stage = _presentation_stage(
        original_prompt,
        presentation_context,
    )
    normalized_aspect_ratio = _clean_text(aspect_ratio) or "1:1"
    if presentation_stage == "visual_scheme" and normalized_aspect_ratio != "16:9":
        return _text_response(
            "Error: PPT visual schemes must use aspect_ratio='16:9'.",
        )
    if (
        presentation_stage == "visual_asset"
        and _is_full_slide_asset(presentation_context)
        and normalized_aspect_ratio != "16:9"
    ):
        return _text_response(
            "Error: Full-slide PPT background/hero assets must use "
            "aspect_ratio='16:9'.",
        )
    effective_prompt = _compile_presentation_prompt(
        original_prompt,
        presentation_stage,
        presentation_context,
    )

    provider = _resolve_provider(provider_id)
    if provider is None:
        return _text_response("Error: No imagegen provider is configured.")

    try:
        refs = _normalize_reference_images(reference_images)
        task_id = await _submit_task(
            provider,
            prompt=effective_prompt,
            aspect_ratio=normalized_aspect_ratio,
            quality=_normalize_quality(quality),
            resolution=_clean_text(resolution).upper() or "1K",
            reference_images=refs,
            channel=channel,
        )
        image_url = await _poll_task(provider, task_id)
        content, mime_type = await _download_image(image_url)
        suffix = _suffix_for_mime_type(mime_type)
        output_path = _output_directory(output_dir) / (
            f"imagegen_{int(time.time() * 1000)}.{suffix}"
        )
        output_path.write_bytes(content)
        _write_generation_manifest(
            output_path,
            original_prompt=original_prompt,
            effective_prompt=effective_prompt,
            presentation_stage=presentation_stage,
            presentation_context=presentation_context,
            aspect_ratio=normalized_aspect_ratio,
            quality=_normalize_quality(quality),
            resolution=_clean_text(resolution).upper() or "1K",
            task_id=task_id,
        )
    except httpx.TimeoutException:
        return _text_response("Error: Image generation timed out.")
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return _text_response(f"Error: Image generation failed - {exc}")

    display_url = _display_url_for_output(output_path)
    return ToolResponse(
        content=[
            ImageBlock(type="image", source={"type": "url", "url": display_url}),
            TextBlock(
                type="text",
                text=(
                    "Generated image with imagegen (GPT Image 2 / MXAPI)\n"
                    f"Prompt: {original_prompt}\n"
                    f"Prompt profile: {presentation_stage or 'generic'}\n"
                    f"Aspect ratio: {aspect_ratio}, Quality: {quality}, "
                    f"Resolution: {resolution}\n"
                    f"MXAPI task: {task_id}\n"
                    "The generated image is attached as an image block and "
                    "saved as a workspace artifact.\n"
                    "Do not show internal URLs or local file paths to the user; "
                    "refer to it as the generated image."
                ),
            ),
        ],
    )


async def generate_image_gpt(
    prompt: str,
    size: str = "1024x1024",
    quality: str = "auto",
    aspect_ratio: str = "",
    resolution: str = "1K",
    output_dir: str | None = None,
) -> ToolResponse:
    """Compatibility alias for older GPT Image 2 tool prompts."""
    return await imagegen(
        prompt=prompt,
        aspect_ratio=aspect_ratio or _aspect_ratio_from_size(size) or "1:1",
        quality=quality,
        resolution=resolution,
        output_dir=output_dir,
    )


async def edit_image_gpt(
    prompt: str,
    reference_images: list[str] | str,
    size: str = "1024x1024",
    quality: str = "auto",
    aspect_ratio: str = "",
    resolution: str = "1K",
    output_dir: str | None = None,
) -> ToolResponse:
    """Compatibility alias for imagegen with public reference image URLs."""
    return await imagegen(
        prompt=prompt,
        aspect_ratio=aspect_ratio or _aspect_ratio_from_size(size) or "1:1",
        quality=quality,
        resolution=resolution,
        reference_images=reference_images,
        output_dir=output_dir,
    )
