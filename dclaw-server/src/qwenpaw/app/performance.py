# -*- coding: utf-8 -*-
"""Lightweight in-process performance diagnostics."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


@dataclass(slots=True)
class RequestMetric:
    path: str
    method: str
    status_code: int
    duration_ms: int
    agent_id: str
    user_id: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "method": self.method,
            "status_code": self.status_code,
            "duration_ms": self.duration_ms,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
        }


class RequestMetrics:
    """Bounded request metric store focused on slow paths."""

    def __init__(self, *, max_entries: int = 200, slow_ms: int = 750) -> None:
        self._slow_requests: deque[RequestMetric] = deque(maxlen=max_entries)
        self._total_requests = 0
        self._slow_ms = slow_ms
        self._lock = asyncio.Lock()

    def record(
        self,
        *,
        path: str,
        method: str,
        status_code: int,
        duration_ms: int,
        agent_id: str = "",
        user_id: str = "",
    ) -> None:
        """Record one request without blocking the response path."""
        self._total_requests += 1
        if duration_ms < self._slow_ms:
            return
        self._slow_requests.append(
            RequestMetric(
                path=path,
                method=method,
                status_code=status_code,
                duration_ms=duration_ms,
                agent_id=agent_id,
                user_id=user_id,
            ),
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "total_requests": self._total_requests,
            "slow_threshold_ms": self._slow_ms,
            "slow_requests": [item.as_dict() for item in self._slow_requests],
        }


_request_metrics = RequestMetrics()


def get_request_metrics() -> RequestMetrics:
    return _request_metrics


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Record request durations with lightweight user/agent context."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            state = request.state
            get_request_metrics().record(
                path=request.url.path,
                method=request.method,
                status_code=status_code,
                duration_ms=duration_ms,
                agent_id=(
                    getattr(state, "agent_id", "")
                    or request.headers.get("X-Agent-Id", "")
                ),
                user_id=str(getattr(state, "user_id", "") or ""),
            )

