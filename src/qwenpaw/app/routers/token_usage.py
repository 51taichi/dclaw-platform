# -*- coding: utf-8 -*-
"""Token usage API for console and skill tool."""

from datetime import date, timedelta

from fastapi import APIRouter, Query, Request

from ...token_usage import (
    get_token_usage_manager,
    TokenUsageSummary,
    TokenUsageRecord,
)

router = APIRouter(prefix="/token-usage", tags=["token-usage"])


def _parse_date(s: str | None) -> date | None:
    """Parse YYYY-MM-DD string to date."""
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


@router.get(
    "",
    summary="Get token usage summary",
    description="Return aggregated token usage by date, model, and provider",
)
async def get_token_usage(
    request: Request,
    start_date: str
    | None = Query(
        None,
        description="Start date YYYY-MM-DD (inclusive). Default: 30 days ago",
    ),
    end_date: str
    | None = Query(
        None,
        description="End date YYYY-MM-DD (inclusive). Default: today",
    ),
    model: str
    | None = Query(
        None,
        description="Filter by model name",
    ),
    provider: str
    | None = Query(
        None,
        description="Filter by provider ID",
    ),
    user_id: str
    | None = Query(
        None,
        description="Filter by user ID (admin only)",
    ),
) -> TokenUsageSummary:
    """Return aggregated token usage summary for the given date range."""
    end_d = _parse_date(end_date) or date.today()
    start_d = _parse_date(start_date) or (end_d - timedelta(days=30))
    if start_d > end_d:
        start_d, end_d = end_d, start_d

    # Only admins can query other users' usage. Regular users can only see their own.
    role = getattr(request.state, "role", "user")
    current_user_id = getattr(request.state, "user_id", None)
    
    query_user_id = user_id
    if role != "admin" and current_user_id is not None:
        query_user_id = current_user_id

    return await get_token_usage_manager().get_summary(
        start_date=start_d,
        end_date=end_d,
        model_name=model,
        provider_id=provider,
        user_id=query_user_id,
    )


@router.get(
    "/details",
    summary="Get token usage details",
    description="Return raw token usage records for frontend aggregation",
)
async def get_token_usage_details(
    request: Request,
    start_date: str
    | None = Query(
        None,
        description="Start date YYYY-MM-DD (inclusive). Default: 30 days ago",
    ),
    end_date: str
    | None = Query(
        None,
        description="End date YYYY-MM-DD (inclusive). Default: today",
    ),
    model: str
    | None = Query(
        None,
        description="Filter by model name",
    ),
    provider: str
    | None = Query(
        None,
        description="Filter by provider ID",
    ),
    user_id: str
    | None = Query(
        None,
        description="Filter by user ID (admin only)",
    ),
) -> list[TokenUsageRecord]:
    """Return raw token usage records for the given date range."""
    end_d = _parse_date(end_date) or date.today()
    start_d = _parse_date(start_date) or (end_d - timedelta(days=30))
    if start_d > end_d:
        start_d, end_d = end_d, start_d

    role = getattr(request.state, "role", "user")
    current_user_id = getattr(request.state, "user_id", None)
    
    query_user_id = user_id
    if role != "admin" and current_user_id is not None:
        query_user_id = current_user_id

    return await get_token_usage_manager().get_details(
        start_date=start_d,
        end_date=end_d,
        model_name=model,
        provider_id=provider,
        user_id=query_user_id,
    )
