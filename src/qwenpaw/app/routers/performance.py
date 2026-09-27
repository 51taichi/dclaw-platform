# -*- coding: utf-8 -*-
"""Admin-only performance diagnostics."""
from __future__ import annotations

from datetime import datetime, timezone
import os
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
from ..task_limits import get_task_limiter
from ...providers.rate_limiter import get_rate_limiter

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


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.01, float(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


def _masked_api_key_id(api_key_id: str) -> str:
    suffix = api_key_id[-4:] if len(api_key_id) > 4 else api_key_id
    return f"••••{suffix}"


async def _concurrency_status(request: Request) -> dict[str, Any]:
    from .open_api import _get_open_api_wait_queue

    task_snapshot = await get_task_limiter(request.app).snapshot()
    queue_snapshot = await _get_open_api_wait_queue(request.app).snapshot()
    llm_snapshot = (await get_rate_limiter()).stats()

    agent_prefix = "openapi-publication:"
    key_prefix = "openapi-api-key:"
    running_by_agent = {
        key.removeprefix(agent_prefix): int(value)
        for key, value in task_snapshot.get("running_by_agent", {}).items()
        if key.startswith(agent_prefix)
    }
    running_by_key = {
        key.removeprefix(key_prefix): int(value)
        for key, value in task_snapshot.get("running_by_user", {}).items()
        if key.startswith(key_prefix)
    }
    waiting_by_agent = queue_snapshot["waiting_by_publication"]
    waiting_by_key = queue_snapshot["waiting_by_api_key"]
    agent_limit = _env_int(
        "DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_PUBLICATION",
        30,
    )
    api_key_limit = _env_int(
        "DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_API_KEY",
        20,
    )

    by_agent = [
        {
            "agent_id": agent_id,
            "running": running_by_agent.get(agent_id, 0),
            "waiting": waiting_by_agent.get(agent_id, 0),
            "max_running": agent_limit,
        }
        for agent_id in sorted(set(running_by_agent) | set(waiting_by_agent))
    ]
    by_api_key = [
        {
            "api_key": _masked_api_key_id(api_key_id),
            "running": running_by_key.get(api_key_id, 0),
            "waiting": waiting_by_key.get(api_key_id, 0),
            "max_running": api_key_limit,
        }
        for api_key_id in sorted(set(running_by_key) | set(waiting_by_key))
    ]

    return {
        "sampled_at": datetime.now(timezone.utc).isoformat(),
        "open_api": {
            "running": queue_snapshot["running_global"],
            "max_running": _env_int(
                "DCLAW_OPEN_API_MAX_RUNNING_TASKS_GLOBAL",
                8,
            ),
            "waiting": queue_snapshot["waiting_global"],
            "max_waiting_per_agent": _env_int(
                "DCLAW_OPEN_API_MAX_WAITING_PER_PUBLICATION",
                200,
            ),
            "max_waiting_per_api_key": _env_int(
                "DCLAW_OPEN_API_MAX_WAITING_PER_API_KEY",
                100,
            ),
            "wait_timeout_seconds": _env_float(
                "DCLAW_OPEN_API_WAIT_TIMEOUT_SECONDS",
                120.0,
            ),
            "by_agent": by_agent,
            "by_api_key": by_api_key,
        },
        "platform_tasks": {
            "running": int(task_snapshot.get("running_global") or 0),
            "max_running": int(task_snapshot.get("max_global") or 0),
        },
        "model_calls": {
            "running": int(llm_snapshot.get("current_in_flight") or 0),
            "max_running": int(llm_snapshot.get("max_concurrent") or 0),
            "available": int(llm_snapshot.get("current_available") or 0),
        },
    }


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


@router.get("/concurrency")
async def get_concurrency_diagnostics(request: Request) -> dict[str, Any]:
    return await _concurrency_status(request)
