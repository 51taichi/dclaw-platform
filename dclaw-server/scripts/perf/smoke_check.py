#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Production smoke check for QwenPaw/DClaw performance readiness."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from perf_lib import (  # noqa: E402
    RequestSample,
    build_headers,
    evaluate_diagnostics,
    summarize_samples,
)


def _base_url(value: str) -> str:
    return value.rstrip("/") + "/"


def _url(base_url: str, path: str) -> str:
    return urljoin(_base_url(base_url), path.lstrip("/"))


async def _get_json(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    path: str,
) -> tuple[RequestSample, Any | None]:
    started = time.perf_counter()
    try:
        response = await client.get(_url(base_url, path))
        latency_ms = (time.perf_counter() - started) * 1000
        sample = RequestSample(
            endpoint=path,
            method="GET",
            status_code=response.status_code,
            latency_ms=latency_ms,
            ok=200 <= response.status_code < 400,
            error="" if response.status_code < 400 else response.text[:200],
        )
        payload = response.json() if sample.ok else None
        return sample, payload
    except Exception as exc:  # pragma: no cover - depends on live network
        latency_ms = (time.perf_counter() - started) * 1000
        return (
            RequestSample(
                endpoint=path,
                method="GET",
                status_code=None,
                latency_ms=latency_ms,
                ok=False,
                error=str(exc),
            ),
            None,
        )


async def run_smoke_check(args: argparse.Namespace) -> dict[str, Any]:
    headers = build_headers(
        token=args.token,
        cookie=args.cookie,
        agent_id=args.agent_id,
        extra_headers=args.header,
    )
    started = datetime.now(timezone.utc)
    samples: list[RequestSample] = []
    diagnostics_payload: dict[str, Any] | None = None

    async with httpx.AsyncClient(
        headers=headers,
        timeout=args.timeout,
        trust_env=False,
    ) as client:
        for path in ("/api/version", "/api/admin/performance/diagnostics"):
            sample, payload = await _get_json(client, base_url=args.base_url, path=path)
            samples.append(sample)
            if path.endswith("/diagnostics") and isinstance(payload, dict):
                diagnostics_payload = payload

    summary = summarize_samples(samples, elapsed_seconds=sum(s.latency_ms for s in samples) / 1000)
    diagnostics_result = (
        evaluate_diagnostics(diagnostics_payload)
        if diagnostics_payload is not None
        else {
            "passed": False,
            "checks": {
                "diagnostics_available": {
                    "name": "diagnostics_available",
                    "passed": False,
                    "detail": "No diagnostics payload returned",
                },
            },
        }
    )
    endpoints_passed = all(sample.ok for sample in samples)
    return {
        "started_at": started.isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "config": {"base_url": args.base_url},
        "summary": summary,
        "endpoint_samples": [sample.__dict__ for sample in samples],
        "diagnostics": diagnostics_payload,
        "diagnostics_evaluation": diagnostics_result,
        "passed": endpoints_passed and diagnostics_result["passed"],
    }


def _print_report(report: dict[str, Any]) -> None:
    print("QwenPaw production smoke check")
    for sample in report["endpoint_samples"]:
        mark = "PASS" if sample["ok"] else "FAIL"
        print(
            f"  [{mark}] {sample['method']} {sample['endpoint']} "
            f"status={sample['status_code']} latency={sample['latency_ms']:.1f}ms",
        )
    print(f"  diagnostics passed: {report['diagnostics_evaluation']['passed']}")
    for check in report["diagnostics_evaluation"]["checks"].values():
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"    [{mark}] {check['name']}: {check['detail']}")
    print(f"  overall passed: {report['passed']}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8088")
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--token", default=os.environ.get("QWENPAW_PERF_TOKEN", ""))
    parser.add_argument("--cookie", default="")
    parser.add_argument("--agent-id", default="")
    parser.add_argument("--header", action="append", default=[])
    parser.add_argument("--json-output", default="")
    parser.add_argument(
        "--no-fail-on-check",
        action="store_true",
        help="Always exit 0 even if checks fail.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = asyncio.run(run_smoke_check(args))
    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    _print_report(report)
    if args.no_fail_on_check:
        return 0
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
