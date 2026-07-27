# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_perf_lib():
    module_path = Path(__file__).parents[3] / "scripts" / "perf" / "perf_lib.py"
    spec = importlib.util.spec_from_file_location("perf_lib", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_headers_combines_token_cookie_agent_and_extra_headers():
    perf_lib = _load_perf_lib()

    headers = perf_lib.build_headers(
        token="abc",
        cookie="session=xyz",
        agent_id="agent-1",
        extra_headers=["X-Test: yes", "X-Trace: 123"],
    )

    assert headers == {
        "Authorization": "Bearer abc",
        "Cookie": "session=xyz",
        "X-Agent-Id": "agent-1",
        "X-Test": "yes",
        "X-Trace": "123",
    }


def test_summarize_samples_reports_percentiles_and_error_rate():
    perf_lib = _load_perf_lib()
    samples = [
        perf_lib.RequestSample(
            endpoint="/api/version",
            method="GET",
            status_code=200,
            latency_ms=10,
            ok=True,
        ),
        perf_lib.RequestSample(
            endpoint="/api/version",
            method="GET",
            status_code=200,
            latency_ms=20,
            ok=True,
        ),
        perf_lib.RequestSample(
            endpoint="/api/version",
            method="GET",
            status_code=500,
            latency_ms=100,
            ok=False,
            error="boom",
        ),
    ]

    summary = perf_lib.summarize_samples(samples, elapsed_seconds=2.0)

    assert summary["total_requests"] == 3
    assert summary["ok_requests"] == 2
    assert summary["error_rate"] == 1 / 3
    assert summary["requests_per_second"] == 1.5
    assert summary["latency_ms"]["p50"] == 20
    assert summary["latency_ms"]["p95"] == 100
    assert summary["status_counts"] == {"200": 2, "500": 1}


def test_evaluate_load_summary_fails_on_high_p95_or_errors():
    perf_lib = _load_perf_lib()

    result = perf_lib.evaluate_load_summary(
        {
            "latency_ms": {"p95": 450},
            "error_rate": 0.02,
            "total_requests": 100,
        },
        p95_target_ms=300,
        max_error_rate=0.01,
    )

    assert result["passed"] is False
    assert result["checks"]["p95_latency"]["passed"] is False
    assert result["checks"]["error_rate"]["passed"] is False


def test_evaluate_diagnostics_requires_wal_and_no_slow_requests():
    perf_lib = _load_perf_lib()

    result = perf_lib.evaluate_diagnostics(
        {
            "sqlite": {
                "journal_mode": "wal",
                "busy_timeout": 5000,
                "foreign_keys": 1,
            },
            "task_limits": {"running_global": 2, "max_global": 20},
            "requests": {"slow_requests": []},
        },
    )

    assert result["passed"] is True
    assert result["checks"]["sqlite_wal"]["passed"] is True
    assert result["checks"]["sqlite_busy_timeout"]["passed"] is True


def test_evaluate_diagnostics_accepts_postgres_storage_status():
    perf_lib = _load_perf_lib()

    result = perf_lib.evaluate_diagnostics(
        {
            "storage": {"database_backend": "postgres"},
            "postgres": {
                "connected": True,
                "tables": {"missing": []},
            },
            "task_limits": {"running_global": 2, "max_global": 20},
            "requests": {"slow_requests": []},
        },
    )

    assert result["passed"] is True
    assert result["checks"]["postgres_connected"]["passed"] is True
    assert result["checks"]["postgres_tables"]["passed"] is True
    assert "sqlite_wal" not in result["checks"]
