"""User-owned canvas operations shared by HTTP and capability adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from ...aigc.workflow_compiler import CompiledWorkflow
from .models import (
    AigcJob,
    Canvas,
    CanvasEdge,
    CanvasNode,
    CanvasUpsert,
    CanvasViewport,
)
from .resource_store import AigcResourceError, AigcResourceStore


class AigcCanvasService:
    def __init__(self, store: AigcResourceStore) -> None:
        self.store = store

    @staticmethod
    def owner(canvas: Canvas) -> str | None:
        value = canvas.meta.get("owner_user_id")
        if value is None:
            value = canvas.meta.get("user_id")
        if value is None:
            return None
        return str(value).strip() or None

    @classmethod
    def can_access(
        cls, owner_user_id: str, canvas: Canvas, *, allow_ownerless: bool = False,
    ) -> bool:
        owner = cls.owner(canvas)
        return allow_ownerless if owner is None else owner == owner_user_id

    def load(self, canvas_id: str) -> Canvas:
        return Canvas(**self.store.read("canvases", canvas_id))

    def get(
        self, owner_user_id: str, canvas_id: str, *, allow_ownerless: bool = False,
    ) -> Canvas:
        canvas = self.load(canvas_id)
        if not self.can_access(owner_user_id, canvas, allow_ownerless=allow_ownerless):
            raise AigcResourceError("CANVAS_NOT_FOUND")
        return canvas

    def create(
        self, owner_user_id: str, body: CanvasUpsert, *, id_prefix: str = "",
    ) -> Canvas:
        if not owner_user_id or not owner_user_id.strip():
            raise AigcResourceError("INVALID_OWNER")
        now = datetime.now(timezone.utc).isoformat()
        data = body.model_dump()
        data["meta"]["owner_user_id"] = owner_user_id
        canvas = Canvas(
            id=id_prefix + str(uuid.uuid4()), created_at=now, updated_at=now, **data,
        )
        self.store.write("canvases", canvas.id, canvas.model_dump())
        return canvas

    def create_compiled(
        self, owner_user_id: str, compiled: CompiledWorkflow,
        *, meta: dict[str, Any] | None = None,
    ) -> Canvas:
        body = CanvasUpsert(
            name=compiled.title,
            nodes=[
                CanvasNode(
                    id=node.physical_node_id, type=node.kind,
                    position=node.position, data=node.data,
                )
                for node in compiled.nodes
            ],
            edges=[
                CanvasEdge(
                    id=edge.edge_id, source=edge.source, target=edge.target,
                    data={"role": edge.target_slot},
                )
                for edge in compiled.edges
            ],
            viewport=CanvasViewport(**compiled.viewport),
            meta={
                **(meta or {}), "version": 2, "workflow_id": compiled.workflow_id,
                "execution_mode": "PREBUILT_WORKFLOW",
            },
        )
        return self.create(owner_user_id, body, id_prefix="canvas-")

    def update(
        self, owner_user_id: str, canvas_id: str, body: CanvasUpsert,
        *, allow_ownerless: bool = False,
    ) -> Canvas:
        existing = self.get(owner_user_id, canvas_id, allow_ownerless=allow_ownerless)
        data = body.model_dump()
        data["meta"]["owner_user_id"] = self.owner(existing) or owner_user_id
        canvas = Canvas(
            id=canvas_id, created_at=existing.created_at,
            updated_at=datetime.now(timezone.utc).isoformat(), **data,
        )
        self.store.write("canvases", canvas_id, canvas.model_dump())
        return canvas

    def jobs(self, canvas_id: str) -> list[AigcJob]:
        jobs = [
            AigcJob(**self.store.read_path(path))
            for path in sorted(self.store.directory("jobs").glob("*.json"))
        ]
        return [job for job in jobs if job.canvas_id == canvas_id]

    def delete(
        self, owner_user_id: str, canvas_id: str, *, allow_ownerless: bool = False,
    ) -> None:
        self.get(owner_user_id, canvas_id, allow_ownerless=allow_ownerless)
        self.store.delete("canvases", canvas_id)
        for job in self.jobs(canvas_id):
            self.store.delete("jobs", job.id)

    def discard_unstarted(
        self, owner_user_id: str, canvas_id: str, *, expected_meta: dict[str, Any],
    ) -> None:
        try:
            canvas = self.get(owner_user_id, canvas_id)
        except AigcResourceError as exc:
            if exc.code == "RESOURCE_NOT_FOUND":
                return
            raise
        if any(canvas.meta.get(key) != value for key, value in expected_meta.items()):
            raise AigcResourceError("RESOURCE_BINDING_MISMATCH")
        if self.jobs(canvas_id):
            raise AigcResourceError("RESOURCE_ALREADY_USED")
        for path in self.store.directory("assets").glob("*.json"):
            if self.store.read_path(path).get("meta", {}).get("canvas_id") == canvas_id:
                raise AigcResourceError("RESOURCE_ALREADY_USED")
        self.store.delete("canvases", canvas_id)
