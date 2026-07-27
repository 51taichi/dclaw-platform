# -*- coding: utf-8 -*-
"""Admin-only performance diagnostics."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import inspect as sa_inspect, text

from .. import db
from ..console_push_store import stats as push_store_stats
from ..performance import get_request_metrics
from ..runtime.event_bus import get_runtime_event_bus
from ..storage.engine import get_app_engine
from ..storage.schema import table_names
from ..storage.settings import get_storage_settings

router = APIRouter(prefix="/performance", tags=["performance"])


def _sqlite_status() -> dict[str, Any]:
    conn = db.get_db()
    return {
        "path": str(db.DB_PATH),
        "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
        "busy_timeout": conn.execute("PRAGMA busy_timeout").fetchone()[0],
        "foreign_keys": conn.execute("PRAGMA foreign_keys").fetchone()[0],
    }


def _postgres_status() -> dict[str, Any]:
    engine = get_app_engine()
    expected_tables = table_names()
    status: dict[str, Any] = {
        "dialect": engine.dialect.name,
        "pool": _pool_status(engine),
    }
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            inspector = sa_inspect(conn)
            present_tables = set(inspector.get_table_names())
            known_present = expected_tables & present_tables
            indexes = {
                table: sorted(
                    str(item["name"])
                    for item in inspector.get_indexes(table)
                    if item.get("name")
                )
                for table in sorted(known_present)
            }
        status.update(
            {
                "connected": True,
                "tables": {
                    "expected_count": len(expected_tables),
                    "present_count": len(known_present),
                    "missing": sorted(expected_tables - present_tables),
                },
                "indexes": indexes,
            },
        )
    except Exception as exc:  # pragma: no cover - defensive diagnostics path
        status.update(
            {
                "connected": False,
                "error": str(exc),
                "tables": {
                    "expected_count": len(expected_tables),
                    "present_count": 0,
                    "missing": sorted(expected_tables),
                },
            },
        )
    return status


def _pool_status(engine: Any) -> str:
    pool = getattr(engine, "pool", None)
    status = getattr(pool, "status", None)
    if not callable(status):
        return ""
    try:
        return str(status())
    except Exception:  # pragma: no cover - best-effort diagnostics
        return ""


async def _runtime_status(request: Request) -> dict[str, Any]:
    manager = getattr(request.app.state, "multi_agent_manager", None)
    if manager is None:
        return {"loaded_agents": [], "running_task_count": 0}

    if hasattr(manager, "list_loaded_agents"):
        loaded_agents = manager.list_loaded_agents()
    else:
        loaded_agents = list(getattr(manager, "agents", {}).keys())
    running_task_count = 0
    task_stream_buffers: dict[str, Any] = {}
    for agent_id, workspace in getattr(manager, "agents", {}).items():
        tracker = getattr(workspace, "task_tracker", None)
        if tracker is None:
            continue
        status = await tracker.get_global_status()
        running_task_count += int(status.get("running_task_count") or 0)
        if hasattr(tracker, "get_buffer_stats"):
            try:
                task_stream_buffers[str(agent_id)] = await tracker.get_buffer_stats()
            except Exception as exc:  # pragma: no cover - diagnostics only
                task_stream_buffers[str(agent_id)] = {"error": str(exc)}

    return {
        "loaded_agents": loaded_agents,
        "running_task_count": running_task_count,
        "task_stream_buffers": task_stream_buffers,
    }


async def _task_limit_status(request: Request) -> dict[str, Any]:
    limiter = getattr(request.app.state, "task_limiter", None)
    if limiter is None:
        return {}
    return await limiter.snapshot()


async def _approval_status() -> dict[str, Any]:
    from ..approvals import get_approval_service

    approval_svc = get_approval_service()
    return await approval_svc.metadata_stats()


def _storage_status() -> dict[str, Any]:
    try:
        return get_storage_settings().diagnostics()
    except RuntimeError as exc:
        return {"error": str(exc)}


def _aigc_studio_status() -> dict[str, Any]:
    try:
        from .aigc_studio import get_aigc_studio_diagnostics

        return get_aigc_studio_diagnostics()
    except Exception as exc:  # pragma: no cover - diagnostics only
        return {"error": str(exc)}


async def _runtime_event_status() -> dict[str, Any]:
    try:
        return await get_runtime_event_bus().stats()
    except Exception as exc:  # pragma: no cover - diagnostics only
        return {"error": str(exc)}


@router.get("/diagnostics")
async def get_performance_diagnostics(request: Request) -> dict[str, Any]:
    storage = _storage_status()
    database_status: dict[str, Any]
    if storage.get("database_backend") == "postgres":
        database_status = {"postgres": _postgres_status()}
    else:
        database_status = {"sqlite": _sqlite_status()}

    return {
        "requests": get_request_metrics().snapshot(),
        "storage": storage,
        **database_status,
        "runtime": await _runtime_status(request),
        "runtime_events": await _runtime_event_status(),
        "task_limits": await _task_limit_status(request),
        "push_messages": await push_store_stats(),
        "approvals": await _approval_status(),
        "aigc_studio": _aigc_studio_status(),
    }
