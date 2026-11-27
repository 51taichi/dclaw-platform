# -*- coding: utf-8 -*-
"""Recoverable background jobs for knowledge ingestion and synchronization."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from ..app.storage.settings import get_storage_settings
from .cloud_auth import CloudAuthStore
from .connectors import CloudConnectorRegistry
from .models import MindspaceDoc, MindspaceScope
from .service import MindspaceService

logger = logging.getLogger(__name__)

KnowledgeJobOperation = Literal["ingest", "link", "resync"]
_RETRYABLE_FAILED_STAGES = {"fetching", "embedding"}
_JOB_TTL_SECONDS = 7 * 24 * 60 * 60
_ACTIVE_TTL_SECONDS = _JOB_TTL_SECONDS


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(1, value)


def _positive_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(0.1, value)


@dataclass
class KnowledgeJob:
    """Everything needed to reconstruct a Mindspace service after restart."""

    id: str
    operation: KnowledgeJobOperation
    doc_id: str
    scope: str
    user_id: str
    agent_id: str
    global_root: str
    agent_workspace: str
    failed_attempts: int = 0
    last_error: str | None = None
    started_at: float | None = None
    heartbeat_at: float | None = None

    @classmethod
    def from_service(
        cls,
        service: MindspaceService,
        doc: MindspaceDoc,
        *,
        operation: KnowledgeJobOperation,
    ) -> "KnowledgeJob":
        return cls(
            id=f"knowledge-{uuid.uuid4().hex}",
            operation=operation,
            doc_id=doc.id,
            scope=doc.scope.value,
            user_id=service.user_id,
            agent_id=service.agent_id,
            global_root=str(service.global_root.resolve()),
            agent_workspace=str(service.agent_workspace.resolve()),
        )

    @classmethod
    def from_json(cls, raw: str) -> "KnowledgeJob":
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Knowledge job payload must be an object")
        if payload.get("operation") not in {"ingest", "link", "resync"}:
            raise ValueError("Unsupported knowledge job operation")
        return cls(**payload)

    def to_json(self) -> str:
        return json.dumps(
            asdict(self),
            ensure_ascii=False,
            separators=(",", ":"),
        )


class KnowledgeJobManager:
    """Bounded worker queue with Redis durability and job heartbeats."""

    def __init__(
        self,
        redis_client=None,
        *,
        max_attempts: int = 3,
        worker_count: int | None = None,
        heartbeat_interval_seconds: float | None = None,
    ) -> None:
        self.redis = redis_client
        self.max_attempts = max(1, max_attempts)
        self.worker_count = max(
            1,
            worker_count
            if worker_count is not None
            else _positive_int_env("QWENPAW_KNOWLEDGE_WORKERS", 2),
        )
        self.heartbeat_interval_seconds = max(
            0.1,
            heartbeat_interval_seconds
            if heartbeat_interval_seconds is not None
            else _positive_float_env(
                "QWENPAW_KNOWLEDGE_HEARTBEAT_SECONDS",
                5.0,
            ),
        )
        self.backend = "redis" if redis_client is not None else "memory"
        self.namespace = "qwenpaw:knowledge-jobs"
        self._memory_queue: asyncio.Queue[str] = asyncio.Queue()
        self._memory_jobs: dict[str, KnowledgeJob] = {}
        self._memory_active: dict[str, str] = {}
        self._worker_tasks: list[asyncio.Task[None]] = []
        self._start_lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._start_lock:
            if any(not task.done() for task in self._worker_tasks):
                return
            if self.redis is not None:
                await self._recover_interrupted_jobs()
            self._worker_tasks = [
                asyncio.create_task(
                    self._worker_loop(worker_index),
                    name=f"knowledge-ingestion-worker-{worker_index + 1}",
                )
                for worker_index in range(self.worker_count)
            ]
            logger.info(
                "Knowledge job workers started with %s backend count=%s",
                self.backend,
                self.worker_count,
            )

    async def stop(self) -> None:
        tasks = self._worker_tasks
        self._worker_tasks = []
        if not tasks:
            return
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Knowledge job workers stopped")

    async def enqueue(self, job: KnowledgeJob) -> str:
        await self.start()
        if self.redis is not None:
            active_key = self._active_key(job.doc_id)
            created = await self.redis.set(
                active_key,
                job.id,
                ex=_ACTIVE_TTL_SECONDS,
                nx=True,
            )
            if not created:
                active_job_id = await self.redis.get(active_key)
                return str(active_job_id or job.id)
            try:
                pipe = self.redis.pipeline(transaction=True)
                pipe.set(
                    self._job_key(job.id),
                    job.to_json(),
                    ex=_JOB_TTL_SECONDS,
                )
                pipe.lpush(self._pending_key(), job.id)
                await pipe.execute()
            except Exception:
                await self.redis.delete(active_key)
                raise
            return job.id

        active_job_id = self._memory_active.get(job.doc_id)
        if active_job_id:
            return active_job_id
        self._memory_active[job.doc_id] = job.id
        self._memory_jobs[job.id] = job
        await self._memory_queue.put(job.id)
        return job.id

    async def stats(self) -> dict[str, object]:
        if self.redis is not None:
            pending, processing = await asyncio.gather(
                self.redis.llen(self._pending_key()),
                self.redis.llen(self._processing_key()),
            )
            return {
                "backend": self.backend,
                "pending": int(pending or 0),
                "processing": int(processing or 0),
            }
        return {
            "backend": self.backend,
            "pending": self._memory_queue.qsize(),
            "processing": (
                len(self._memory_active) - self._memory_queue.qsize()
            ),
        }

    async def _worker_loop(self, worker_index: int) -> None:
        while True:
            try:
                await self._worker_iteration()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Knowledge job worker %s iteration failed",
                    worker_index + 1,
                )
                await asyncio.sleep(2)
                if self.redis is not None:
                    try:
                        await self._recover_interrupted_jobs()
                    except Exception:
                        logger.warning(
                            "Knowledge queue recovery is still unavailable",
                            exc_info=True,
                        )

    async def _worker_iteration(self) -> None:
        job_id = await self._take_next()
        if not job_id:
            return
        job = await self._load_job(job_id)
        if job is None:
            await self._ack(job_id, doc_id=None)
            return
        now = time.time()
        job.started_at = job.started_at or now
        job.heartbeat_at = now
        await self._save_job(job)
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(job),
            name=f"knowledge-heartbeat-{job.id}",
        )
        try:
            try:
                terminal_status, error = await self._execute_with_retries(job)
            except asyncio.CancelledError:
                # Redis keeps the ID in the processing list. Startup recovery
                # moves it back to pending, so a restart cannot lose the job.
                raise
            except Exception as exc:  # defensive boundary around job execution
                logger.exception("Knowledge job %s crashed", job.id)
                terminal_status, error = "failed", str(exc)
                await self._mark_terminal_exception(job, str(exc))
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        await self._finish(job, terminal_status=terminal_status, error=error)

    async def _heartbeat_loop(self, job: KnowledgeJob) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval_seconds)
            job.heartbeat_at = time.time()
            try:
                await self._save_job(job)
                if self.redis is not None:
                    await self.redis.expire(
                        self._active_key(job.doc_id),
                        _ACTIVE_TTL_SECONDS,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Knowledge job heartbeat failed for %s",
                    job.id,
                    exc_info=True,
                )

    async def _execute_with_retries(
        self,
        job: KnowledgeJob,
    ) -> tuple[str, str | None]:
        while True:
            failed_result = False
            try:
                result = await self._execute_once(job)
                if result is None:
                    return "completed", None
                if result.status != "failed":
                    return "completed", None
                error = result.last_error or "Knowledge processing failed."
                retryable = result.failed_stage in _RETRYABLE_FAILED_STAGES
                failed_result = True
                if not retryable:
                    return "failed", error
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Knowledge job %s attempt failed: %s",
                    job.id,
                    exc,
                    exc_info=True,
                )
                error = str(exc)
                retryable = True

            job.failed_attempts += 1
            job.last_error = error
            await self._save_job(job)
            if not retryable or job.failed_attempts >= self.max_attempts:
                if not failed_result:
                    await self._mark_terminal_exception(job, error)
                return "failed", error

            service = self._build_service(job)
            await asyncio.to_thread(
                service.mark_document_queued,
                job.doc_id,
                scope=job.scope,
                operation=job.operation,
            )
            await asyncio.sleep(min(2 ** job.failed_attempts, 4))

    async def _execute_once(self, job: KnowledgeJob) -> MindspaceDoc | None:
        service = self._build_service(job)
        scope = MindspaceScope(job.scope)
        if job.operation == "ingest":
            return await asyncio.to_thread(
                service.process_staged_document,
                job.doc_id,
                scope,
            )
        if job.operation == "link":
            return await service.process_staged_cloud_document(
                job.doc_id,
                scope=scope,
                user_id=job.user_id,
            )
        return await service.resync_document(
            job.doc_id,
            scope=scope,
            user_id=job.user_id,
        )

    def _build_service(self, job: KnowledgeJob) -> MindspaceService:
        global_root = Path(job.global_root)
        return MindspaceService(
            global_root=global_root,
            agent_workspace=Path(job.agent_workspace),
            agent_id=job.agent_id,
            user_id=job.user_id,
            connectors=CloudConnectorRegistry(
                auth_store=CloudAuthStore(global_root),
            ),
        )

    async def _mark_terminal_exception(
        self,
        job: KnowledgeJob,
        error: str,
    ) -> None:
        try:
            service = self._build_service(job)
            await asyncio.to_thread(
                service.mark_document_failed,
                job.doc_id,
                scope=job.scope,
                failed_stage="background",
                error=error,
            )
        except Exception:
            logger.exception(
                "Failed to persist failure for knowledge job %s",
                job.id,
            )

    async def _take_next(self) -> str | None:
        if self.redis is not None:
            value = await self.redis.brpoplpush(
                self._pending_key(),
                self._processing_key(),
                timeout=1,
            )
            return str(value) if value else None
        try:
            return await asyncio.wait_for(self._memory_queue.get(), timeout=1)
        except asyncio.TimeoutError:
            return None

    async def _load_job(self, job_id: str) -> KnowledgeJob | None:
        if self.redis is not None:
            raw = await self.redis.get(self._job_key(job_id))
            if not raw:
                return None
            try:
                return KnowledgeJob.from_json(str(raw))
            except (TypeError, ValueError, json.JSONDecodeError):
                logger.error("Discarding invalid knowledge job %s", job_id)
                return None
        return self._memory_jobs.get(job_id)

    async def _save_job(self, job: KnowledgeJob) -> None:
        if self.redis is not None:
            await self.redis.set(
                self._job_key(job.id),
                job.to_json(),
                ex=_JOB_TTL_SECONDS,
            )
        else:
            self._memory_jobs[job.id] = job

    async def _finish(
        self,
        job: KnowledgeJob,
        *,
        terminal_status: str,
        error: str | None,
    ) -> None:
        job.last_error = error
        if self.redis is not None:
            payload = json.loads(job.to_json())
            payload["terminal_status"] = terminal_status
            pipe = self.redis.pipeline(transaction=True)
            pipe.set(
                self._job_key(job.id),
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                ex=_JOB_TTL_SECONDS,
            )
            pipe.lrem(self._processing_key(), 1, job.id)
            pipe.delete(self._active_key(job.doc_id))
            await pipe.execute()
        else:
            self._memory_active.pop(job.doc_id, None)
            self._memory_jobs.pop(job.id, None)
        logger.info(
            "Knowledge job %s finished with status=%s operation=%s doc=%s",
            job.id,
            terminal_status,
            job.operation,
            job.doc_id,
        )

    async def _ack(self, job_id: str, doc_id: str | None) -> None:
        if self.redis is not None:
            await self.redis.lrem(self._processing_key(), 1, job_id)
            if doc_id:
                current = await self.redis.get(self._active_key(doc_id))
                if current == job_id:
                    await self.redis.delete(self._active_key(doc_id))
        else:
            if doc_id:
                self._memory_active.pop(doc_id, None)
            self._memory_jobs.pop(job_id, None)

    async def _recover_interrupted_jobs(self) -> None:
        recovered = 0
        while True:
            job_id = await self.redis.rpoplpush(
                self._processing_key(),
                self._pending_key(),
            )
            if not job_id:
                break
            recovered += 1
        if recovered:
            logger.warning(
                "Recovered %s interrupted knowledge job(s)",
                recovered,
            )

    def _pending_key(self) -> str:
        return f"{self.namespace}:pending"

    def _processing_key(self) -> str:
        return f"{self.namespace}:processing"

    def _job_key(self, job_id: str) -> str:
        return f"{self.namespace}:job:{job_id}"

    def _active_key(self, doc_id: str) -> str:
        return f"{self.namespace}:active:{doc_id}"


_job_manager: KnowledgeJobManager | None = None


def _make_redis_client(redis_url: str):
    from redis import asyncio as redis_asyncio

    return redis_asyncio.from_url(redis_url, decode_responses=True)


def get_knowledge_job_manager() -> KnowledgeJobManager:
    """Return the process-wide knowledge job manager."""
    global _job_manager
    if _job_manager is not None:
        return _job_manager
    settings = get_storage_settings()
    redis_client = None
    if settings.runtime_backend == "redis":
        if not settings.redis_url:
            raise RuntimeError(
                "QWENPAW_REDIS_URL is required for knowledge jobs",
            )
        redis_client = _make_redis_client(settings.redis_url)
    _job_manager = KnowledgeJobManager(redis_client=redis_client)
    return _job_manager


async def enqueue_knowledge_job(
    service: MindspaceService,
    doc: MindspaceDoc,
    *,
    operation: KnowledgeJobOperation,
) -> str:
    """Queue a staged document using server-controlled service context."""
    job = KnowledgeJob.from_service(service, doc, operation=operation)
    return await get_knowledge_job_manager().enqueue(job)


def reset_knowledge_job_manager_for_tests() -> None:
    """Forget the singleton after a test has stopped its worker."""
    global _job_manager
    _job_manager = None
