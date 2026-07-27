# -*- coding: utf-8 -*-
"""Tests for recoverable background knowledge jobs."""

from __future__ import annotations

import asyncio
import threading

import fakeredis.aioredis
import pytest

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings
from qwenpaw.mindspace.jobs import KnowledgeJob, KnowledgeJobManager
from qwenpaw.mindspace.models import MindspaceScope
from qwenpaw.mindspace.service import MindspaceService


def _service(tmp_path) -> MindspaceService:
    settings = get_storage_settings(
        {"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")},
    )
    engine = create_engine_from_settings(settings)
    create_all(engine)
    return MindspaceService(
        global_root=tmp_path / "global",
        agent_workspace=tmp_path / "agent-a",
        agent_id="agent-a",
        user_id="user-a",
        engine=engine,
    )


@pytest.mark.asyncio
async def test_memory_worker_processes_upload_and_deduplicates_active_doc(
    tmp_path,
):
    service = _service(tmp_path)
    doc = service.stage_local_bytes(
        name="policy.md",
        content=b"# Policy\n\nTravel bookings require approval.",
        scope=MindspaceScope.PERSONAL,
        source_type="md",
    )
    gate = threading.Event()
    original_process = service.process_staged_document

    def blocked_process(doc_id, scope=None):
        gate.wait(timeout=2)
        return original_process(doc_id, scope)

    setattr(service, "process_staged_document", blocked_process)
    manager = KnowledgeJobManager()
    setattr(manager, "_build_service", lambda _job: service)
    first = KnowledgeJob.from_service(service, doc, operation="ingest")
    duplicate = KnowledgeJob.from_service(service, doc, operation="ingest")

    try:
        first_id = await manager.enqueue(first)
        await asyncio.sleep(0.05)
        duplicate_id = await manager.enqueue(duplicate)
        assert duplicate_id == first_id

        gate.set()
        for _ in range(100):
            current = service.get_document(doc.id, MindspaceScope.PERSONAL)
            if current and current.status == "ready":
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("knowledge job did not finish")

        stats = await manager.stats()
        assert stats == {"backend": "memory", "pending": 0, "processing": 0}
    finally:
        gate.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_redis_startup_recovers_and_finishes_interrupted_job(
    tmp_path,
):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    manager = KnowledgeJobManager(redis_client=redis)
    service = _service(tmp_path)
    doc = service.stage_local_bytes(
        name="recovered.md",
        content=b"# Recovered\n\nThis job survives an application restart.",
        scope=MindspaceScope.PERSONAL,
        source_type="md",
    )
    job = KnowledgeJob.from_service(service, doc, operation="ingest")
    setattr(manager, "_build_service", lambda _job: service)
    await redis.set(manager._job_key(job.id), job.to_json())
    await redis.set(manager._active_key(job.doc_id), job.id)
    await redis.lpush(manager._processing_key(), job.id)

    try:
        await manager.start()
        for _ in range(100):
            current = service.get_document(doc.id, MindspaceScope.PERSONAL)
            active = await redis.get(manager._active_key(doc.id))
            if current and current.status == "ready" and active is None:
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("recovered Redis knowledge job did not finish")

        assert await redis.llen(manager._processing_key()) == 0
        assert await redis.llen(manager._pending_key()) == 0
        saved = await redis.get(manager._job_key(job.id))
        assert saved is not None
        assert '"terminal_status":"completed"' in saved
    finally:
        await manager.stop()
        await redis.aclose()


@pytest.mark.asyncio
async def test_multiple_workers_do_not_let_one_job_block_another(tmp_path):
    service = _service(tmp_path)
    first_doc = service.stage_local_bytes(
        name="first.md",
        content=b"first",
        scope=MindspaceScope.PERSONAL,
        source_type="md",
    )
    second_doc = service.stage_local_bytes(
        name="second.md",
        content=b"second",
        scope=MindspaceScope.PERSONAL,
        source_type="md",
    )
    release = threading.Event()
    both_running = threading.Event()
    state_lock = threading.Lock()
    state = {"active": 0, "max_active": 0}

    def blocked_process(doc_id, scope=None):
        with state_lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
            if state["active"] >= 2:
                both_running.set()
        release.wait(timeout=2)
        try:
            return service.get_document(doc_id, scope)
        finally:
            with state_lock:
                state["active"] -= 1

    setattr(service, "process_staged_document", blocked_process)
    manager = KnowledgeJobManager(worker_count=2)
    setattr(manager, "_build_service", lambda _job: service)

    try:
        await manager.enqueue(
            KnowledgeJob.from_service(service, first_doc, operation="ingest")
        )
        await manager.enqueue(
            KnowledgeJob.from_service(service, second_doc, operation="ingest")
        )
        assert await asyncio.to_thread(both_running.wait, 1.0)
        assert state["max_active"] == 2
        release.set()
        for _ in range(100):
            stats = await manager.stats()
            if stats["pending"] == 0 and stats["processing"] == 0:
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("concurrent knowledge jobs did not finish")
    finally:
        release.set()
        await manager.stop()


@pytest.mark.asyncio
async def test_running_job_updates_heartbeat(tmp_path):
    service = _service(tmp_path)
    doc = service.stage_local_bytes(
        name="heartbeat.md",
        content=b"heartbeat",
        scope=MindspaceScope.PERSONAL,
        source_type="md",
    )
    release = threading.Event()

    def blocked_process(doc_id, scope=None):
        release.wait(timeout=2)
        return service.get_document(doc_id, scope)

    setattr(service, "process_staged_document", blocked_process)
    manager = KnowledgeJobManager(
        worker_count=1,
        heartbeat_interval_seconds=0.02,
    )
    setattr(manager, "_build_service", lambda _job: service)
    job = KnowledgeJob.from_service(service, doc, operation="ingest")

    try:
        await manager.enqueue(job)
        for _ in range(100):
            stored = manager._memory_jobs.get(job.id)
            if stored and stored.heartbeat_at and stored.heartbeat_at > (
                stored.started_at or 0
            ):
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("knowledge job heartbeat was not updated")
    finally:
        release.set()
        await manager.stop()
