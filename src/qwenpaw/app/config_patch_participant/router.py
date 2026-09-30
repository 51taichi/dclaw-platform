"""Internal read-only routes consumed by the config-patch service."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from .auth import require_config_patch_service
from .models import DclawConfigurationContext
from .service import (
    DclawConfigurationContextService,
    get_dclaw_configuration_context_service,
)
from .export import (
    DclawSnapshotExporter,
    SnapshotExportError,
    get_dclaw_snapshot_exporter,
)


router = APIRouter(
    prefix="/internal/config-patch/v1",
    tags=["config-patch-participant"],
    dependencies=[Depends(require_config_patch_service)],
)


@router.get(
    "/agents/{agent_id}/context",
    response_model=DclawConfigurationContext,
)
def get_agent_configuration_context(
    agent_id: str,
    service: DclawConfigurationContextService = Depends(
        get_dclaw_configuration_context_service,
    ),
) -> DclawConfigurationContext:
    return service.describe(agent_id)


@router.get("/agents/{agent_id}/snapshot")
def get_agent_configuration_snapshot(
    agent_id: str,
    exporter: DclawSnapshotExporter = Depends(get_dclaw_snapshot_exporter),
) -> Response:
    try:
        snapshot = exporter.export(agent_id)
    except SnapshotExportError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": exc.code,
                "missingItems": exc.missing_items,
            },
        ) from exc
    return Response(
        content=snapshot.archive,
        media_type="application/zip",
        headers={
            "X-DClaw-Agent-Id": snapshot.agent_id,
            "X-DClaw-Agent-Profile-Id": snapshot.profile_id,
            "X-DClaw-Source-Version": snapshot.source_version,
            "X-DClaw-Agent-Digest": snapshot.agent_digest,
            "X-DClaw-Knowledge-Digest": snapshot.knowledge_digest,
        },
    )
