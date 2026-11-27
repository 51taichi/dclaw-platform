"""Bound, content-free AIGC asset references for sealed experts."""

from __future__ import annotations

from typing import Any

from qwenpaw.app.aigc.resource_store import AigcResourceError
from .aigc_guide import _latest_jobs


def project_owned_aigc_snapshot(
    *, task: Any, adapter: Any, user_id: str,
    installation_id: str, conversation_id: str,
) -> dict[str, Any]:
    binding = task.binding
    if (
        binding.installation_id != installation_id
        or binding.conversation_id != conversation_id
        or adapter is None
    ):
        return {"contract": "aigc.task.snapshot/1", "status": "not_found"}
    try:
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
            return {"contract": "aigc.task.snapshot/1", "status": "unavailable"}
        assets = []
        latest = _latest_jobs([
            job for job in jobs
            if getattr(job, "canvas_id", None) == binding.canvas_id
            and getattr(job, "node_id", None) in bound_nodes
        ])
        node_jobs = []
        for node_id, job in sorted(latest.items()):
            node_jobs.append({
                "node_id": node_id,
                "job_id": job.id,
                "job_status": job.status,
            })
            if job.status != "succeeded":
                continue
            for output in getattr(job, "outputs", ()) or ():
                asset = adapter.assets.resolve_owned(user_id, output.id)
                adapter.assets.validate_review_binding(
                    asset, canvas_id=binding.canvas_id, node_ids={node_id},
                )
                assets.append({
                    "node_id": node_id,
                    "job_id": job.id,
                    "asset_id": asset.id,
                    "asset_kind": asset.kind,
                })
    except (AigcResourceError, ValueError, OSError):
        return {"contract": "aigc.task.snapshot/1", "status": "unavailable"}
    return {
        "contract": "aigc.task.snapshot/1",
        "status": "found",
        "material_task_id": binding.material_task_id,
        "workflow_id": binding.workflow_id,
        "canvas_id": binding.canvas_id,
        "task_status": task.status.value,
        "task_version": task.version,
        "submitted_asset_id": task.asset_id,
        "node_jobs": node_jobs,
        "generation_assets": assets,
    }
