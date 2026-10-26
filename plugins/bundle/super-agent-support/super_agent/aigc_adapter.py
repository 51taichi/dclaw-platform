"""Map expert material tasks to shared AIGC services, never HTTP routes."""

from __future__ import annotations
from typing import Any, Awaitable, Callable
import uuid
from qwenpaw.aigc.workflow_compiler import CompiledWorkflow
from qwenpaw.app.aigc.models import (
    AigcJob,
    Canvas,
    CanvasNode,
    CanvasUpsert,
    CanvasViewport,
)
from qwenpaw.app.aigc.canvas_service import AigcCanvasService
from qwenpaw.app.aigc.asset_service import AigcAssetService
from qwenpaw.app.aigc.resource_store import AigcResourceError


async def load_workflow_capability_catalog():
    from qwenpaw.providers.provider_manager import ProviderManager
    from qwenpaw.app.aigc.capability_service import (
        build_workflow_capability_catalog,
    )

    return await build_workflow_capability_catalog(
        ProviderManager.get_instance(),
    )


class AigcServiceAdapter:
    def __init__(
        self,
        canvases: AigcCanvasService,
        assets: AigcAssetService,
        *,
        catalog_loader: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self.canvases = canvases
        self.assets = assets
        self._catalog_loader = (
            catalog_loader or load_workflow_capability_catalog
        )

    async def capability_catalog(self):
        return await self._catalog_loader()

    def provision_workspace(
        self,
        *,
        owner_user_id: str,
        material_task_id: str,
        operation_id: str,
        arguments: dict[str, Any],
    ) -> dict[str, str]:
        """Create the real user-owned canvas and node for one guided task."""
        if not str(owner_user_id).strip() or not str(material_task_id).strip():
            raise ValueError("AIGC workspace ownership is incomplete")
        if operation_id != "aigc.text_to_video.create":
            raise ValueError("AIGC operation cannot be provisioned")
        # Prefix physical identifiers so every generated value remains valid for
        # the shared super-expert domain-id contract even when a UUID starts with
        # a digit.
        node_id = f"video-{uuid.uuid4()}"
        node = CanvasNode(
            id=node_id,
            type="video_generate",
            position={"x": 120.0, "y": 120.0},
            data={
                "title": "视频节点",
                "text": str(arguments["prompt"]),
                "videoMode": "blank",
                "showTryOptions": False,
                "aspectRatio": str(arguments["aspect_ratio"]),
                "videoResolution": "720P",
                "videoDuration": int(arguments["duration_seconds"]),
                "videoAudio": True,
                "videoCount": 1,
                "activeVideoTab": "text_to_video",
                "modelId": str(arguments["model_id"]),
            },
        )
        body = CanvasUpsert(
            name=str(arguments["project_name"]),
            nodes=[node],
            edges=[],
            viewport=CanvasViewport(),
            thumbnail=None,
            meta={
                "version": 1,
                "owner_user_id": str(owner_user_id),
                "super_expert_material_task_id": str(material_task_id),
                "super_expert_operation_id": operation_id,
            },
        )
        canvas = self.canvases.create(
            str(owner_user_id),
            body,
            id_prefix="canvas-",
        )
        return {"canvas_id": canvas.id, "node_id": node_id}

    def provision_workflow(
        self,
        *,
        owner_user_id: str,
        material_task_id: str,
        compiled: CompiledWorkflow,
    ) -> Canvas:
        """Adapt a bound card to the shared canvas creation service."""
        if not str(owner_user_id).strip() or not str(material_task_id).strip():
            raise ValueError("AIGC workspace ownership is incomplete")
        return self.canvases.create_compiled(
            owner_user_id,
            compiled,
            meta={"super_expert_material_task_id": str(material_task_id)},
        )

    def provision_blank_workspace(
        self,
        *,
        owner_user_id: str,
        material_task_id: str,
        workflow_id: str,
        title: str,
    ) -> Canvas:
        """Create the only valid starting point for an explicit manual fallback."""
        if not all(
            str(value).strip()
            for value in (owner_user_id, material_task_id, workflow_id, title)
        ):
            raise ValueError("AIGC manual workspace binding is incomplete")
        body = CanvasUpsert(
            name=str(title),
            nodes=[],
            edges=[],
            viewport=CanvasViewport(),
            thumbnail=None,
            meta={
                "version": 2,
                "owner_user_id": str(owner_user_id),
                "super_expert_material_task_id": str(material_task_id),
                "workflow_id": str(workflow_id),
                "execution_mode": "MANUAL_BUILD",
            },
        )
        return self.canvases.create(
            str(owner_user_id),
            body,
            id_prefix="canvas-",
        )

    def discard_workspace(
        self,
        *,
        owner_user_id: str,
        material_task_id: str,
        canvas_id: str,
    ) -> None:
        """Remove only a just-provisioned, still-unpublished task canvas."""
        self.canvases.discard_unstarted(
            str(owner_user_id),
            canvas_id,
            expected_meta={"super_expert_material_task_id": material_task_id},
        )

    def resolve_owned_asset(
        self,
        owner_user_id: str,
        asset_id: str,
    ) -> dict[str, Any] | None:
        """Resolve only an existing asset explicitly owned by the target user."""
        if not str(owner_user_id).strip() or not str(asset_id).strip():
            return None
        try:
            asset = self.assets.resolve_owned(owner_user_id, asset_id)
        except AigcResourceError:
            return None
        return asset.model_dump(mode="json")

    def workflow_context(
        self,
        *,
        canvas_id: str,
        material_task_id: str,
    ) -> tuple[Canvas | None, list[AigcJob]]:
        """Load only the canvas and jobs bound to one authoritative material task."""
        try:
            canvas = self.canvases.load(canvas_id)
        except AigcResourceError as exc:
            if exc.code == "RESOURCE_NOT_FOUND":
                return None, []
            raise
        if str(canvas.meta.get("super_expert_material_task_id") or "") != str(
            material_task_id,
        ):
            return None, []
        return canvas, self.canvases.jobs(canvas_id)
