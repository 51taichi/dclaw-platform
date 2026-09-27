# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app import performance
from qwenpaw.app.routers import performance as performance_router
from qwenpaw.app.routers import open_api
from qwenpaw.app.routers.performance import router
from qwenpaw.app.task_limits import TaskConcurrencyLimiter
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


def test_request_metrics_records_slow_requests_with_context():
    store = performance.RequestMetrics(max_entries=2, slow_ms=10)

    store.record(
        path="/api/user/chats",
        method="GET",
        status_code=200,
        duration_ms=25,
        agent_id="default",
        user_id="42",
    )

    assert store.snapshot()["slow_requests"] == [
        {
            "path": "/api/user/chats",
            "method": "GET",
            "status_code": 200,
            "duration_ms": 25,
            "agent_id": "default",
            "user_id": "42",
        },
    ]


@pytest.mark.asyncio
async def test_performance_diagnostics_reports_runtime_counts(monkeypatch):
    class FakeTaskTracker:
        async def get_global_status(self):
            return {"running_task_count": 1}

        async def get_buffer_stats(self):
            return {
                "max_buffer_events": 3,
                "max_buffer_bytes": 24,
                "active_runs": {"chat-1": {"buffer_event_count": 1}},
                "recent_runs": {},
            }

    class FakeEventBus:
        async def stats(self):
            return {
                "backend": "memory",
                "active_subscribers": 2,
                "replay_buffer_size": 5,
            }

    app = FastAPI()
    app.state.multi_agent_manager = SimpleNamespace(
        agents={
            "default": SimpleNamespace(task_tracker=FakeTaskTracker()),
        },
    )
    app.include_router(router, prefix="/api/admin")

    monkeypatch.setattr(
        performance,
        "get_request_metrics",
        lambda: performance.RequestMetrics(max_entries=10, slow_ms=1),
    )
    monkeypatch.setattr(
        performance_router,
        "get_runtime_event_bus",
        lambda: FakeEventBus(),
        raising=False,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/admin/performance/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert "requests" in body
    assert "sqlite" in body
    assert "runtime" in body
    assert body["runtime"]["loaded_agents"] == ["default"]
    assert body["runtime"]["running_task_count"] == 1
    assert body["runtime"]["task_stream_buffers"]["default"]["max_buffer_events"] == 3
    assert body["runtime_events"]["backend"] == "memory"
    assert body["runtime_events"]["active_subscribers"] == 2
    assert "aigc_studio" in body
    assert "job_status_counts" in body["aigc_studio"]


@pytest.mark.asyncio
async def test_performance_diagnostics_uses_postgres_status_without_sqlite(
    tmp_path,
    monkeypatch,
):
    engine = create_engine_from_settings(
        get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")}),
    )
    create_all(engine)
    app = FastAPI()
    app.state.multi_agent_manager = SimpleNamespace(agents={})
    app.include_router(router, prefix="/api/admin")

    monkeypatch.setattr(
        performance_router,
        "get_storage_settings",
        lambda: SimpleNamespace(
            database_backend="postgres",
            diagnostics=lambda: {"database_backend": "postgres"},
        ),
    )
    monkeypatch.setattr(performance_router, "get_app_engine", lambda: engine)

    def fail_sqlite_access():
        raise AssertionError("Postgres diagnostics should not touch SQLite")

    monkeypatch.setattr(performance_router.db, "get_db", fail_sqlite_access)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/admin/performance/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert "sqlite" not in body
    assert body["storage"]["database_backend"] == "postgres"
    assert body["postgres"]["connected"] is True
    assert body["postgres"]["tables"]["missing"] == []


@pytest.mark.asyncio
async def test_concurrency_snapshot_reports_open_api_platform_and_model_usage(
    monkeypatch,
):
    monkeypatch.setenv("DCLAW_OPEN_API_MAX_RUNNING_TASKS_GLOBAL", "100")
    monkeypatch.setenv(
        "DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_PUBLICATION",
        "60",
    )
    monkeypatch.setenv("DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_API_KEY", "20")
    monkeypatch.setenv("DCLAW_OPEN_API_MAX_WAITING_PER_PUBLICATION", "200")
    monkeypatch.setenv("DCLAW_OPEN_API_MAX_WAITING_PER_API_KEY", "100")
    monkeypatch.setenv("DCLAW_OPEN_API_WAIT_TIMEOUT_SECONDS", "120")

    limiter = TaskConcurrencyLimiter(
        max_global=150,
        max_per_agent=12,
        max_per_user=6,
    )
    open_api_permit = await limiter.try_acquire(
        agent_id="openapi-publication:publication-1",
        user_id="openapi-api-key:key-super-secret",
        max_per_agent=60,
        max_per_user=20,
    )
    other_permit = await limiter.try_acquire(
        agent_id="console-agent",
        user_id="admin-user",
    )
    assert open_api_permit is not None
    assert other_permit is not None

    queue = open_api._OpenApiWaitQueue()
    assert await queue.try_acquire_execution_slot(100) is True
    ticket = await queue.try_join(
        "publication-1",
        "key-super-secret",
        max_per_publication=200,
        max_per_api_key=100,
    )
    assert ticket is not None

    app = FastAPI()
    app.state.task_limiter = limiter
    app.state.open_api_wait_queue = queue
    app.include_router(router, prefix="/api/admin")
    class FakeLlmLimiter:
        def stats(self):
            return {
                "current_in_flight": 3,
                "max_concurrent": 999,
                "current_available": 996,
            }

    async def fake_get_rate_limiter():
        return FakeLlmLimiter()

    monkeypatch.setattr(
        performance_router,
        "get_rate_limiter",
        fake_get_rate_limiter,
    )

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.get("/api/admin/performance/concurrency")

        assert response.status_code == 200
        body = response.json()
        assert body["open_api"]["running"] == 1
        assert body["open_api"]["max_running"] == 100
        assert body["open_api"]["waiting"] == 1
        assert body["open_api"]["max_waiting_per_agent"] == 200
        assert body["open_api"]["max_waiting_per_api_key"] == 100
        assert body["open_api"]["wait_timeout_seconds"] == 120.0
        assert body["open_api"]["by_agent"] == [
            {
                "agent_id": "publication-1",
                "running": 1,
                "waiting": 1,
                "max_running": 60,
            },
        ]
        assert body["open_api"]["by_api_key"] == [
            {
                "api_key": "••••cret",
                "running": 1,
                "waiting": 1,
                "max_running": 20,
            },
        ]
        assert body["platform_tasks"] == {
            "running": 2,
            "max_running": 150,
        }
        assert body["model_calls"]["running"] == 3
        assert body["model_calls"]["max_running"] == 999
    finally:
        await ticket.release()
        await queue.release_execution_slot()
        await open_api_permit.release()
        await other_permit.release()
