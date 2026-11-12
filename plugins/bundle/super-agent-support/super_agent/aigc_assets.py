"""Task-bound AIGC asset manifests and local delivery preparation."""

from __future__ import annotations

import re
from typing import Any

from qwenpaw.app.aigc.resource_store import AigcResourceError
from qwenpaw.app.object_storage import get_object_storage_client

from .aigc_guide import _latest_jobs


_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_USAGES = {
    "cover", "timeline_clip", "reference_image", "background_audio",
    "voice_audio", "subtitle", "overlay", "final_output",
}
_DESTINATIONS = {"res", "task_root"}


def _bound_context(
    *, task: Any, adapter: Any, user_id: str,
    installation_id: str, conversation_id: str,
) -> tuple[Any, list[dict[str, Any]]] | None:
    binding = getattr(task, "binding", None)
    if (
        binding is None
        or adapter is None
        or not hasattr(adapter, "assets")
        or binding.installation_id != installation_id
        or binding.conversation_id != conversation_id
    ):
        return None
    canvas, jobs = adapter.workflow_context(
        canvas_id=binding.canvas_id,
        material_task_id=binding.material_task_id,
    )
    bound_nodes = set(binding.node_bindings.values()) or {binding.node_id}
    if (
        canvas is None
        or canvas.id != binding.canvas_id
        or canvas.meta.get("workflow_id") != binding.workflow_id
        or not bound_nodes.issubset({node.id for node in canvas.nodes})
    ):
        raise AigcResourceError("ASSET_BINDING_MISMATCH")
    assets: list[dict[str, Any]] = []
    latest = _latest_jobs([
        job for job in jobs
        if getattr(job, "canvas_id", None) == binding.canvas_id
        and getattr(job, "node_id", None) in bound_nodes
    ])
    for node_id, job in sorted(latest.items()):
        if job.status != "succeeded":
            continue
        for output in getattr(job, "outputs", ()) or ():
            asset = adapter.assets.resolve_owned(user_id, output.id)
            adapter.assets.validate_review_binding(
                asset, canvas_id=binding.canvas_id, node_ids={node_id},
            )
            storage = adapter.assets.cloud_storage_meta(asset)
            assets.append({
                "asset_id": asset.id,
                "node_id": node_id,
                "job_id": job.id,
                "kind": asset.kind,
                "name": asset.name,
                "mime_type": asset.mime_type,
                "size_bytes": int(
                    (storage or {}).get("size_bytes")
                    or (storage or {}).get("size")
                    or 0
                ),
                "sha256": str((storage or {}).get("sha256") or ""),
                "_asset": asset,
            })
    return binding, assets


def list_owned_aigc_assets(
    *, task: Any, adapter: Any, user_id: str,
    installation_id: str, conversation_id: str,
) -> dict[str, Any]:
    try:
        context = _bound_context(
            task=task, adapter=adapter, user_id=user_id,
            installation_id=installation_id,
            conversation_id=conversation_id,
        )
    except (AigcResourceError, ValueError, OSError):
        return {"contract": "aigc.task.assets.list/1", "status": "unavailable"}
    if context is None:
        return {"contract": "aigc.task.assets.list/1", "status": "not_found"}
    binding, assets = context
    return {
        "contract": "aigc.task.assets.list/1",
        "status": "found",
        "material_task_id": binding.material_task_id,
        "assets": [
            {key: value for key, value in item.items() if not key.startswith("_")}
            for item in assets
        ],
    }


def prepare_owned_aigc_localization(
    *, task: Any, adapter: Any, user_id: str,
    installation_id: str, conversation_id: str,
    requested_assets: Any,
) -> list[dict[str, Any]]:
    if not isinstance(requested_assets, list) or not 1 <= len(requested_assets) <= 100:
        raise ValueError("invalid asset selection")
    context = _bound_context(
        task=task, adapter=adapter, user_id=user_id,
        installation_id=installation_id,
        conversation_id=conversation_id,
    )
    if context is None:
        raise AigcResourceError("ASSET_NOT_FOUND")
    _, available = context
    by_id = {item["asset_id"]: item for item in available}
    storage_client = get_object_storage_client(require_enabled=True)
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_slots: set[str] = set()
    for selection in requested_assets:
        if not isinstance(selection, dict) or set(selection) != {
            "asset_id", "usage", "slot", "order", "destination",
        }:
            raise ValueError("invalid asset selection")
        asset_id = selection.get("asset_id")
        usage = selection.get("usage")
        slot = selection.get("slot")
        order = selection.get("order")
        destination = selection.get("destination")
        if (
            not isinstance(asset_id, str) or asset_id in seen_ids
            or not isinstance(usage, str) or usage not in _USAGES
            or not isinstance(slot, str) or not _TOKEN.fullmatch(slot)
            or slot in seen_slots
            or not isinstance(order, int) or isinstance(order, bool) or order < 0
            or destination not in _DESTINATIONS
            or (usage == "final_output" and destination != "task_root")
            or (usage != "final_output" and destination != "res")
        ):
            raise ValueError("invalid asset selection")
        source = by_id.get(asset_id)
        if source is None:
            raise AigcResourceError("ASSET_NOT_FOUND")
        download_url = adapter.assets.signed_source(
            source["_asset"], storage_client=storage_client, ttl_seconds=600,
        )
        if not isinstance(download_url, str) or not download_url:
            raise AigcResourceError("ASSET_FILE_NOT_FOUND")
        seen_ids.add(asset_id)
        seen_slots.add(slot)
        normalized.append({
            **{key: value for key, value in source.items() if not key.startswith("_")},
            "usage": usage,
            "slot": slot,
            "order": order,
            "destination": destination,
            "download_url": download_url,
        })
    return normalized
