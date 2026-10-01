"""Internal read-only routes consumed by the integration client."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

from fastapi import APIRouter, Depends, HTTPException, Response

from .auth import require_integration_client
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
    prefix="/internal/integrations/v1",
    tags=["dclaw-integrations"],
    dependencies=[Depends(require_integration_client)],
)


@lru_cache(maxsize=1)
def _capability_catalog() -> dict[str, object]:
    resource = files("qwenpaw.app.integration_delivery.resources").joinpath(
        "dclaw-capability-catalog.v1.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


@router.get("/capabilities")
def get_integration_capabilities() -> dict[str, object]:
    return _capability_catalog()


@router.get(
    "/agents/{agent_id}/delivery-context",
    response_model=DclawConfigurationContext,
)
def get_agent_configuration_context(
    agent_id: str,
    service: DclawConfigurationContextService = Depends(
        get_dclaw_configuration_context_service,
    ),
) -> DclawConfigurationContext:
    return service.describe(agent_id)


@router.get("/agents/{agent_id}/source-bundle")
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
