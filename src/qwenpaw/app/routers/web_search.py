# -*- coding: utf-8 -*-
"""Admin APIs for the shared web-search provider."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..web_search import (
    ALIYUN_IQS_ENDPOINT,
    ALIYUN_IQS_ENGINE,
    MASKED_SECRET,
    WebSearchConfig,
    WebSearchConfigStore,
    WebSearchError,
    get_web_search_service,
)

router = APIRouter(prefix="/web-search", tags=["web-search"])


class WebSearchConfigRequest(BaseModel):
    enabled: bool = False
    api_key: str | None = None
    endpoint: str = ALIYUN_IQS_ENDPOINT
    engine_type: str = ALIYUN_IQS_ENGINE
    default_max_results: int = 5
    timeout_seconds: float = 8.0
    cache_ttl_seconds: int = 300


def _store() -> WebSearchConfigStore:
    return WebSearchConfigStore()


def _config_from_request(payload: WebSearchConfigRequest) -> WebSearchConfig:
    return _store().config_from_payload(payload.model_dump())


@router.get("/config")
async def get_web_search_config() -> dict:
    return {"config": _store().get_config().to_public_dict()}


@router.put("/config")
async def put_web_search_config(payload: WebSearchConfigRequest) -> dict:
    try:
        config = _store().update_config(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await get_web_search_service().clear_cache()
    return {"config": config.to_public_dict()}


@router.post("/test")
async def test_web_search_config(payload: WebSearchConfigRequest) -> dict:
    try:
        config = _config_from_request(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not config.configured:
        raise HTTPException(
            status_code=400,
            detail="Configure an IQS API Key before testing web search.",
        )

    started_at = time.perf_counter()
    try:
        response = await get_web_search_service().search(
            "阿里云",
            max_results=1,
            freshness="no_limit",
            include_content=False,
            config=config,
            require_enabled=False,
            use_cache=False,
        )
    except (WebSearchError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "ok": True,
        "provider": response.provider,
        "engine_type": response.engine_type,
        "result_count": len(response.results),
        "request_id": response.request_id,
        "latency_ms": round((time.perf_counter() - started_at) * 1000),
        "sample_title": response.results[0].title if response.results else "",
        "api_key": MASKED_SECRET,
    }

