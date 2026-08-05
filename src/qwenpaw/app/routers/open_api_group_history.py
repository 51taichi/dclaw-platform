# -*- coding: utf-8 -*-
"""Storage-only Open API routes for immutable external group history."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request

from ..open_api.models import (
    AppendGroupHistoryRequest,
    AppendGroupHistoryResponse,
    GroupHistoryPage,
)
from ..storage.repos.open_api_group_history_repo import (
    get_open_api_group_history_repository,
)
from ..storage.repos.open_api_repo import get_open_api_repository


router = APIRouter(prefix="/open/v1", tags=["open-api-group-history"])


@router.post(
    "/targets/{public_id}/group-histories/{external_group_id}/messages",
    response_model=AppendGroupHistoryResponse,
)
async def append_group_history_messages(
    public_id: str,
    external_group_id: str,
    payload: AppendGroupHistoryRequest,
    request: Request,
) -> AppendGroupHistoryResponse:
    publication = _resolve_bound_publication(public_id, request)
    try:
        result = get_open_api_group_history_repository().append_messages(
            publication_id=str(publication["id"]),
            external_group_id=external_group_id,
            messages=[message.model_dump() for message in payload.messages],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AppendGroupHistoryResponse(**result)


@router.get(
    "/targets/{public_id}/group-histories/{external_group_id}/messages",
    response_model=GroupHistoryPage,
)
async def list_group_history_messages(
    public_id: str,
    external_group_id: str,
    request: Request,
    from_at: datetime | None = Query(default=None, alias="from"),
    until_at: datetime | None = Query(default=None, alias="until"),
    after: str | None = Query(default=None, max_length=2000),
    limit: int = Query(default=100, ge=1, le=500),
) -> GroupHistoryPage:
    publication = _resolve_bound_publication(public_id, request)
    try:
        result = get_open_api_group_history_repository().list_messages(
            publication_id=str(publication["id"]),
            external_group_id=external_group_id,
            from_at=from_at,
            until_at=until_at,
            after=after,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GroupHistoryPage(**result)


def _resolve_bound_publication(public_id: str, request: Request) -> dict:
    publication = get_open_api_repository().get_enabled_publication_by_public_id(
        public_id,
    )
    if publication is None:
        raise HTTPException(status_code=404, detail="Open API publication not found")
    if str(getattr(request.state, "open_publication_id", "")) != str(
        publication["id"],
    ):
        raise HTTPException(
            status_code=403,
            detail="Open API key is not allowed for this publication",
        )
    return publication
