"""Application composition for the optional super-expert capability service."""

from pathlib import Path
from qwenpaw.constant import WORKING_DIR
from qwenpaw.app.aigc.resource_store import AigcResourceStore
from qwenpaw.app.aigc.canvas_service import AigcCanvasService
from qwenpaw.app.aigc.asset_service import AigcAssetService
from qwenpaw.app.aigc.workflow_execution import AigcWorkflowExecutionService
from qwenpaw.app.runtime.event_bus import get_runtime_event_bus
from .aigc_adapter import AigcServiceAdapter
from .aigc_tasks import AigcTaskRepository
from .events import SuperExpertEventRepository
from .grants import SuperExpertGrantRepository
from .interaction_cards import InteractionCardRepository, InteractionService
from .service import SuperExpertPlatformService

_service: SuperExpertPlatformService | None = None


def resolve_event_scope(conversation_id: str) -> dict | None:
    """Resolve an original public chat or internal session, rejecting ambiguity."""
    from sqlalchemy import or_, select
    from qwenpaw.app.storage.engine import get_app_engine
    from qwenpaw.app.storage.schema import chats

    with get_app_engine().connect() as connection:
        rows = (
            connection.execute(
                select(
                    chats.c.agent_id,
                    chats.c.session_id,
                    chats.c.user_id,
                )
                .where(
                    or_(
                        chats.c.id == conversation_id,
                        chats.c.session_id == conversation_id,
                    ),
                )
                .limit(2),
            )
            .mappings()
            .all()
        )
    if len(rows) != 1:
        return None
    return {
        **dict(rows[0]),
        "user_id": str(rows[0]["user_id"]),
        "tenant_id": "local",
    }


def installation_is_active(grant, *, registry=None) -> bool:
    from qwenpaw.app.sealed_agents.registry import get_sealed_agent_registry

    record = (registry or get_sealed_agent_registry()).get_agent(
        grant.agent_id,
    )
    if record is None or not record.enabled:
        return False
    release = record.active_release
    return bool(
        release
        and release.package_type in {"super_expert", "super_expert_public"}
        and release.release_id == grant.release_id
        and release.content_digest == grant.package_digest
        and release.capability_digest == grant.capability_digest,
    )


def _resolve_runtime_session_id(conversation_id: str) -> str:
    # Console routes accept public chat UUIDs, while SSE subscribes to the
    # stored session ID. Resolve delivery only; never rewrite task bindings.
    from qwenpaw.app.storage.repos.audit_repo import get_audit_repository

    row = get_audit_repository().get_chat_identity(conversation_id)
    return (
        str(row.get("session_id") or conversation_id)
        if row
        else conversation_id
    )


def get_super_expert_platform_service() -> SuperExpertPlatformService:
    global _service
    if _service is None:
        root = Path(WORKING_DIR) / "sealed_agents"
        from qwenpaw.app.storage.engine import get_app_engine
        from qwenpaw.app.storage.repos.aigc_execution_repo import (
            AigcExecutionRepository,
        )

        _service = SuperExpertPlatformService(
            grant_repository=SuperExpertGrantRepository(root),
            task_repository=AigcTaskRepository(root / "platform"),
            event_repository=SuperExpertEventRepository(root / "platform"),
            event_bus=get_runtime_event_bus(),
            event_session_resolver=_resolve_runtime_session_id,
            interaction_service=InteractionService(
                InteractionCardRepository(root / "platform"),
            ),
            aigc_adapter=AigcServiceAdapter(
                AigcCanvasService(
                    AigcResourceStore(Path(WORKING_DIR) / "aigc_studio"),
                ),
                AigcAssetService(
                    AigcResourceStore(Path(WORKING_DIR) / "aigc_studio"),
                ),
            ),
            workflow_execution_service=AigcWorkflowExecutionService(
                AigcResourceStore(Path(WORKING_DIR) / "aigc_studio"),
                AigcExecutionRepository(get_app_engine()),
            ),
        )
    return _service


def create_aigc_event_consumer(repository, bus):
    """Build the Super Agent projection for the shared AIGC event stream."""
    from .aigc_event_adapter import AigcEventAdapter

    return AigcEventAdapter(
        get_super_expert_platform_service(),
        repository,
        scope_resolver=resolve_event_scope,
        installation_is_active=installation_is_active,
    )


def accepted_workflow_allows_unbound_node(canvas) -> bool:
    """Allow ordinary canvas work after a plugin-owned task is accepted."""
    from .models import AigcTaskStatus

    material_task_id = str(
        getattr(canvas, "meta", {}).get("super_expert_material_task_id") or "",
    ).strip()
    if not material_task_id:
        return False
    task = get_super_expert_platform_service().get_task(material_task_id)
    return bool(
        task is not None
        and task.binding.canvas_id == canvas.id
        and task.status == AigcTaskStatus.ACCEPTED,
    )
