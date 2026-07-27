#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared helpers for QwenPaw performance scripts."""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any


@dataclass
class RequestSample:
    endpoint: str
    method: str
    status_code: int | None
    latency_ms: float
    ok: bool
    error: str = ""


def parse_extra_header(value: str) -> tuple[str, str]:
    if ":" not in value:
        raise ValueError(f"Invalid header {value!r}; expected 'Name: value'")
    name, raw = value.split(":", 1)
    name = name.strip()
    if not name:
        raise ValueError("Header name cannot be empty")
    return name, raw.strip()


def build_headers(
    *,
    token: str = "",
    cookie: str = "",
    agent_id: str = "",
    extra_headers: list[str] | None = None,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if cookie:
        headers["Cookie"] = cookie
    if agent_id:
        headers["X-Agent-Id"] = agent_id
    for item in extra_headers or []:
        name, value = parse_extra_header(item)
        headers[name] = value
    return headers


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, ceil((p / 100) * len(ordered)))
    return ordered[min(rank - 1, len(ordered) - 1)]


def _round(value: float) -> float:
    return round(value, 3)


def summarize_samples(
    samples: list[RequestSample],
    *,
    elapsed_seconds: float,
) -> dict[str, Any]:
    latencies = [sample.latency_ms for sample in samples]
    status_counts: dict[str, int] = {}
    for sample in samples:
        key = str(sample.status_code) if sample.status_code is not None else "error"
        status_counts[key] = status_counts.get(key, 0) + 1

    total = len(samples)
    ok_count = sum(1 for sample in samples if sample.ok)
    error_count = total - ok_count
    elapsed = max(elapsed_seconds, 0.001)
    return {
        "total_requests": total,
        "ok_requests": ok_count,
        "error_requests": error_count,
        "error_rate": error_count / total if total else 0.0,
        "requests_per_second": _round(total / elapsed),
        "latency_ms": {
            "min": _round(min(latencies) if latencies else 0.0),
            "p50": _round(percentile(latencies, 50)),
            "p95": _round(percentile(latencies, 95)),
            "p99": _round(percentile(latencies, 99)),
            "max": _round(max(latencies) if latencies else 0.0),
        },
        "status_counts": status_counts,
    }


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": passed, "detail": detail}


def evaluate_load_summary(
    summary: dict[str, Any],
    *,
    p95_target_ms: float,
    max_error_rate: float,
) -> dict[str, Any]:
    latency = summary.get("latency_ms", {})
    p95 = float(latency.get("p95") or 0)
    error_rate = float(summary.get("error_rate") or 0)
    total_requests = int(summary.get("total_requests") or 0)
    checks = {
        "has_requests": _check(
            "has_requests",
            total_requests > 0,
            f"total_requests={total_requests}",
        ),
        "p95_latency": _check(
            "p95_latency",
            p95 <= p95_target_ms,
            f"p95={p95}ms target<={p95_target_ms}ms",
        ),
        "error_rate": _check(
            "error_rate",
            error_rate <= max_error_rate,
            f"error_rate={error_rate:.3%} target<={max_error_rate:.3%}",
        ),
    }
    return {
        "passed": all(item["passed"] for item in checks.values()),
        "checks": checks,
    }


def evaluate_diagnostics(payload: dict[str, Any]) -> dict[str, Any]:
    storage = payload.get("storage") or {}
    backend = str(storage.get("database_backend") or "sqlite")
    sqlite = payload.get("sqlite") or {}
    postgres = payload.get("postgres") or {}
    task_limits = payload.get("task_limits") or {}
    requests = payload.get("requests") or {}
    running_global = int(task_limits.get("running_global") or 0)
    max_global = int(task_limits.get("max_global") or 0)
    slow_requests = requests.get("slow_requests") or []

    checks = {
        "task_limit_headroom": _check(
            "task_limit_headroom",
            max_global == 0 or running_global < max_global,
            f"running_global={running_global} max_global={max_global}",
        ),
        "no_recent_slow_requests": _check(
            "no_recent_slow_requests",
            len(slow_requests) == 0,
            f"slow_requests={len(slow_requests)}",
        ),
    }

    if backend == "postgres":
        missing_tables = (postgres.get("tables") or {}).get("missing") or []
        checks.update(
            {
                "postgres_connected": _check(
                    "postgres_connected",
                    bool(postgres.get("connected")),
                    f"connected={bool(postgres.get('connected'))}",
                ),
                "postgres_tables": _check(
                    "postgres_tables",
                    len(missing_tables) == 0,
                    f"missing_tables={len(missing_tables)}",
                ),
            },
        )
    else:
        journal_mode = str(sqlite.get("journal_mode") or "").lower()
        busy_timeout = int(sqlite.get("busy_timeout") or 0)
        foreign_keys = int(sqlite.get("foreign_keys") or 0)
        checks.update(
            {
                "sqlite_wal": _check(
                    "sqlite_wal",
                    journal_mode == "wal",
                    f"journal_mode={journal_mode or 'unknown'}",
                ),
                "sqlite_busy_timeout": _check(
                    "sqlite_busy_timeout",
                    busy_timeout >= 5000,
                    f"busy_timeout={busy_timeout}",
                ),
                "sqlite_foreign_keys": _check(
                    "sqlite_foreign_keys",
                    foreign_keys == 1,
                    f"foreign_keys={foreign_keys}",
                ),
            },
        )
    return {
        "passed": all(item["passed"] for item in checks.values()),
        "checks": checks,
    }
