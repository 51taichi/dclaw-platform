# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app import performance
from qwenpaw.app.routers import performance as performance_router
from qwenpaw.app.routers.performance import router
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
