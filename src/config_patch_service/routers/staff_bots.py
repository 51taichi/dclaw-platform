"""Employee read-only Bot discovery and configuration context routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from ..context import BotNotFoundError, ConfigurationContextService
from ..dependencies import require_staff_token
from ..models import (
    AuthenticatedStaffToken,
    BotConfigurationContext,
    BotConfigurationTargetList,
)


router = APIRouter(
    prefix="/staff/v1",
    tags=["config-patch-staff"],
)


def _context_service(request: Request) -> ConfigurationContextService:
    return request.app.state.configuration_context_service


@router.get("/bots", response_model=BotConfigurationTargetList)
def list_bots(
    request: Request,
    identity: AuthenticatedStaffToken = Depends(require_staff_token),
    service: ConfigurationContextService = Depends(_context_service),
) -> BotConfigurationTargetList:
    correlation_id = uuid.uuid4().hex
    bots = service.list_bots(correlation_id=correlation_id)
    request.app.state.config_patch_audit.record(
        "staff.bots.list",
        token_id=identity.token_id,
        employee_name=identity.employee_name,
        result="success",
        metadata={"correlationId": correlation_id, "botCount": len(bots)},
    )
    return BotConfigurationTargetList(bots=bots)


@router.get(
    "/bots/{bot_id}/configuration-context",
    response_model=BotConfigurationContext,
)
def get_bot_configuration_context(
    bot_id: str,
    request: Request,
    identity: AuthenticatedStaffToken = Depends(require_staff_token),
    service: ConfigurationContextService = Depends(_context_service),
) -> BotConfigurationContext:
    correlation_id = uuid.uuid4().hex
    try:
        context = service.get(bot_id, correlation_id=correlation_id)
    except BotNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "CONFIG_PATCH_BOT_NOT_FOUND"},
        ) from exc
    request.app.state.config_patch_audit.record(
        "staff.bot.context.read",
        token_id=identity.token_id,
        employee_name=identity.employee_name,
        result="success",
        metadata={"correlationId": correlation_id, "botId": bot_id},
    )
    return context
