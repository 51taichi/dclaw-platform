# -*- coding: utf-8 -*-
"""Token usage manager — durable storage backed orchestrator.
"""

import asyncio
import logging
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, Field

from ..app.storage.repos.token_usage_repo import (
    TokenUsageLogRecord,
    get_token_usage_repository,
)
from .buffer import _UsageEvent

logger = logging.getLogger(__name__)


class TokenUsageStats(BaseModel):
    """Prompt/completion tokens and call count."""

    prompt_tokens: int = Field(0, ge=0)
    completion_tokens: int = Field(0, ge=0)
    call_count: int = Field(0, ge=0)


class TokenUsageRecord(TokenUsageStats):
    """Single row from token usage query (per date + provider + model)."""

    date: str = Field(..., description="Date (YYYY-MM-DD)")
    provider_id: str = Field("", description="Provider ID")
    model: str = Field(..., description="Model name")
    user_id: Optional[str] = Field(None, description="User ID")


class TokenUsageByModel(TokenUsageStats):
    """Per-model aggregate in summary (provider + model + counts)."""

    provider_id: str = Field("", description="Provider ID")
    model: str = Field(..., description="Model name")


class TokenUsageByDateModel(TokenUsageStats):
    """Per-date per-model aggregate in summary."""

    provider_id: str = Field("", description="Provider ID")
    model: str = Field(..., description="Model name")


class TokenUsageSummary(BaseModel):
    """Aggregated token usage summary returned by get_summary()."""

    total_prompt_tokens: int = Field(0, ge=0)
    total_completion_tokens: int = Field(0, ge=0)
    total_calls: int = Field(0, ge=0)
    by_date: dict[str, TokenUsageStats] = Field(
        default_factory=dict,
        description="Per date (YYYY-MM-DD) - all models combined",
    )


class TokenUsageManager:
    """Orchestrator for token usage recording and querying."""

    _instance: "TokenUsageManager | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._flush_interval = 5
        self._queue: asyncio.Queue = asyncio.Queue()
        self._flush_task: Optional[asyncio.Task] = None
        self._stopped = False

    def start(self, flush_interval: int = 5) -> None:
        """Start background flush task."""
        if self._flush_task is not None:
            return
        self._flush_interval = flush_interval
        self._stopped = False
        self._flush_task = asyncio.create_task(
            self._flush_loop(),
            name="token-usage-sqlite-flush",
        )

    async def stop(self) -> None:
        """Stop the flush task and perform a final flush before exit."""
        self._stopped = True
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        await self._flush_once()

    def enqueue(self, event: _UsageEvent) -> None:
        """Synchronous fire-and-forget — enqueue a pre-built usage event."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(
                "token_usage: queue full, dropping event for %s",
                event.model_name,
            )

    async def record(
        self,
        provider_id: str,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        at_date: Optional[date] = None,
    ) -> None:
        from ..app.agent_context import get_current_user_id
        user_id = get_current_user_id()
        if at_date is None:
            at_date = date.today()
        self.enqueue(
            _UsageEvent(
                provider_id=provider_id,
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                date_str=at_date.isoformat(),
                now_iso=datetime.now(tz=timezone.utc).isoformat(
                    timespec="seconds",
                ),
                user_id=user_id,
            ),
        )

    async def _flush_once(self) -> None:
        """Drain the queue and insert batch into SQLite."""
        batch = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break
                
        if not batch:
            return
            
        def _do_insert(events: list[_UsageEvent]):
            get_token_usage_repository().insert_events(
                [
                    TokenUsageLogRecord(
                        id=uuid.uuid4().hex,
                        user_id=ev.user_id,
                        model_name=ev.model_name,
                        prompt_tokens=ev.prompt_tokens,
                        completion_tokens=ev.completion_tokens,
                        created_at=ev.now_iso,
                    )
                    for ev in events
                ]
            )
            
        try:
            await asyncio.to_thread(_do_insert, batch)
        except Exception:
            logger.exception("Failed to flush token usage logs to DB")

    async def _flush_loop(self) -> None:
        """Periodically flush the queue to disk."""
        try:
            while not self._stopped:
                await asyncio.sleep(self._flush_interval)
                await self._flush_once()
        except asyncio.CancelledError:
            pass

    async def get_summary(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        model_name: Optional[str] = None,
        provider_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> TokenUsageSummary:
        """Get aggregated token usage summary from DB."""
        # Ensure pending logs are flushed before query
        await self._flush_once()

        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=30)
            
        def _do_query():
            return get_token_usage_repository().get_summary_rows(
                start_date=start_date,
                end_date=end_date,
                model_name=model_name,
                provider_id=provider_id,
                user_id=user_id,
            )

        rows = await asyncio.to_thread(_do_query)

        summary = TokenUsageSummary()
        
        # Populate current date range buckets with 0 to ensure frontend charts look nice
        current = start_date
        while current <= end_date:
            date_str = current.isoformat()
            summary.by_date[date_str] = TokenUsageStats(
                prompt_tokens=0,
                completion_tokens=0,
                call_count=0
            )
            current += timedelta(days=1)
            
        for row in rows:
            usage_date = row["usage_date"]
            pt = row["prompt_tokens"] or 0
            ct = row["completion_tokens"] or 0
            cnt = row["call_count"] or 0
            
            summary.total_prompt_tokens += pt
            summary.total_completion_tokens += ct
            summary.total_calls += cnt
            
            if usage_date in summary.by_date:
                stat = summary.by_date[usage_date]
                stat.prompt_tokens += pt
                stat.completion_tokens += ct
                stat.call_count += cnt
                
        return summary
        
    async def get_details(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        model_name: Optional[str] = None,
        provider_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> list[TokenUsageRecord]:
        """Get raw token usage records from DB."""
        await self._flush_once()

        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=30)
            
        def _do_query():
            return get_token_usage_repository().get_detail_rows(
                start_date=start_date,
                end_date=end_date,
                model_name=model_name,
                provider_id=provider_id,
                user_id=user_id,
            )

        rows = await asyncio.to_thread(_do_query)
        results = []
        for row in rows:
            results.append(
                TokenUsageRecord(
                    date=row["usage_date"],
                    provider_id="",
                    model=row["model_name"],
                    user_id=row["user_id"],
                    prompt_tokens=row["prompt_tokens"] or 0,
                    completion_tokens=row["completion_tokens"] or 0,
                    call_count=row["call_count"] or 0,
                )
            )
        return results


def get_token_usage_manager() -> TokenUsageManager:
    """Singleton accessor."""
    if TokenUsageManager._instance is None:
        with TokenUsageManager._lock:
            if TokenUsageManager._instance is None:
                TokenUsageManager._instance = TokenUsageManager()
    return TokenUsageManager._instance

__all__ = ["TokenUsageManager", "get_token_usage_manager", "TokenUsageSummary", "TokenUsageStats", "_UsageEvent"]
