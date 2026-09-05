"""Persist terminal results before best-effort JSON projections and notifications."""

from __future__ import annotations

from datetime import datetime, timezone
import logging

from .canvas_service import AigcCanvasService
from .models import AigcAsset, AigcJob, Canvas
from .resource_store import AigcResourceStore
from ..storage.repos.aigc_execution_repo import AigcExecutionRepository

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge_node_output(canvas: Canvas, job: AigcJob) -> Canvas:
    output_payload = [asset.model_dump() for asset in job.outputs]
    nodes = []
    for node in canvas.nodes:
        if node.id != job.node_id:
            nodes.append(node)
            continue
        data = {
            **node.data,
            "job_id": job.id,
            "job_status": job.status,
            "outputs": output_payload,
        }
        if node.type == "image_generate" and job.status == "succeeded":
            data["imageState"] = "generated"
            data["imageProgress"] = None
            data["generatedAspectRatio"] = job.parameters.get("aspectRatio")
        if node.type == "prompt" and job.status == "succeeded":
            generated_text = next(
                (
                    str(asset.meta.get("text") or "").strip()
                    for asset in job.outputs
                    if str(asset.meta.get("text") or "").strip()
                ),
                "",
            )
            data["textState"] = "generated"
            data["showTryOptions"] = False
            if generated_text:
                data["text"] = generated_text
        if node.type == "video_generate" and job.status == "succeeded":
            data["videoState"] = "generated"
            data["videoProgress"] = None
            data["generatedAspectRatio"] = job.parameters.get(
                "aspectRatio",
                job.parameters.get("aspect_ratio"),
            )
        if node.type == "audio_generate" and job.status == "succeeded":
            data["audioState"] = "generated"
            data["audioProgress"] = None
        nodes.append(node.model_copy(update={"data": data}))
    return canvas.model_copy(update={"nodes": nodes, "updated_at": _now()})


class AigcJobLifecycle:
    def __init__(self, store: AigcResourceStore, repository: AigcExecutionRepository):
        self.store = store
        self.repository = repository

    def _saved(self, job: AigcJob, owner_user_id: str) -> AigcJob | None:
        row = self.repository.get_job_result(job.id)
        if row is None:
            return None
        if (row["owner_user_id"], row["canvas_id"], row["node_id"]) != (
            owner_user_id, job.canvas_id, job.node_id,
        ):
            raise ValueError("JOB_RESULT_BINDING_MISMATCH")
        return AigcJob.model_validate_json(row["snapshot"])

    def record_success(self, job: AigcJob, outputs: list[AigcAsset], *, owner_user_id: str,
                       allow_ownerless: bool = False, attempt_token: str | None = None) -> AigcJob:
        prior = self._saved(job, owner_user_id)
        if prior is not None and prior.status == "cancelled":
            return prior
        if prior is not None and prior.status == "succeeded":
            if prior.outputs != outputs:
                raise ValueError("JOB_RESULT_ALREADY_SUCCEEDED")
            self.project_result(self.repository.get_job_result(job.id))
            return prior
        for asset in outputs:
            if (asset.meta.get("owner_user_id", owner_user_id) != owner_user_id
                    or asset.meta.get("canvas_id", job.canvas_id) != job.canvas_id
                    or asset.meta.get("node_id", job.node_id) != job.node_id):
                raise ValueError("ASSET_RESULT_BINDING_MISMATCH")
        result = job.model_copy(deep=True, update={
            "outputs": outputs, "status": "succeeded", "error": None,
            "updated_at": _now(), "logs": [*job.logs, "Job succeeded."],
        })
        row = self.repository.save_job_result(owner_user_id, result.model_dump(mode="json"),
                                               allow_ownerless=allow_ownerless, attempt_token=attempt_token)
        self.project_result(row)
        return AigcJob.model_validate_json(row["snapshot"])

    def record_failure(self, job: AigcJob, error: str, *, owner_user_id: str,
                       allow_ownerless: bool = False, attempt_token: str | None = None) -> AigcJob:
        prior = self._saved(job, owner_user_id)
        if prior is not None and prior.status in {"succeeded", "cancelled"}:
            return prior
        result = job.model_copy(deep=True, update={
            "status": "failed", "error": error, "updated_at": _now(),
            "logs": [*job.logs, f"Job failed: {error}"],
        })
        row = self.repository.save_job_result(owner_user_id, result.model_dump(mode="json"),
                                               allow_ownerless=allow_ownerless, attempt_token=attempt_token)
        self.project_result(row)
        return AigcJob.model_validate_json(row["snapshot"])

    def cancel(self, job: AigcJob, *, owner_user_id: str, allow_ownerless: bool = False) -> AigcJob:
        cancelled = job.model_copy(deep=True, update={
            "status": "cancelled", "updated_at": _now(), "logs": [*job.logs, "Job cancelled by user."],
        })
        row = self.repository.save_job_result(owner_user_id, cancelled.model_dump(mode="json"),
                                              allow_ownerless=allow_ownerless)
        self.project_result(row)
        return AigcJob.model_validate_json(row["snapshot"])

    def recover_terminal(self, job: AigcJob, *, owner_user_id: str) -> AigcJob | None:
        prior = self._saved(job, owner_user_id)
        if prior is not None and prior.status in {"succeeded", "cancelled"}:
            self.project_result(self.repository.get_job_result(job.id))
            return prior
        return None

    def project_result(self, row: dict) -> bool:
        def project(latest: dict) -> None:
            self._write_projection(latest)

        try:
            applied = self.repository.project_job_result(row["job_id"], project)
        except Exception:
            applied = False
        if not applied:
            logger.warning("AIGC result projection pending for job %s", row["job_id"])
        return applied

    def _write_projection(self, row: dict) -> None:
        job = AigcJob.model_validate_json(row["snapshot"])
        self.store.write("jobs", job.id, job.model_dump(mode="json"))
        if job.status == "succeeded" and row["project_node"]:
            observed = self.store.read("canvases", job.canvas_id)
            canvas = Canvas.model_validate(observed)
            if not AigcCanvasService.can_access(
                row["owner_user_id"], canvas, allow_ownerless=row["allow_ownerless"],
            ):
                raise ValueError("RESULT_CANVAS_OWNER_MISMATCH")
            # Missing/deleted nodes are not recreated by result recovery.
            if not any(node.id == job.node_id for node in canvas.nodes):
                raise ValueError("RESULT_NODE_MISSING")
            projected = _merge_node_output(canvas, job)
            if not self.store.compare_and_write(
                "canvases", canvas.id, observed, projected.model_dump(mode="json"),
            ):
                raise ValueError("RESULT_CANVAS_CHANGED")

    def recover_projections(self, limit: int = 100) -> int:
        return sum(self.project_result(row) for row in self.repository.pending_job_results(limit))
