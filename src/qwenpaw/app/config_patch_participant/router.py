"""Internal read-only routes consumed by the config-patch service."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .auth import require_config_patch_service
from .models import DclawConfigurationContext
from .service import (
    DclawConfigurationContextService,
    get_dclaw_configuration_context_service,
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

