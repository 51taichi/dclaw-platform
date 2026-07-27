#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lightweight SaaS load test for QwenPaw/DClaw.

Default scenario simulates idle browser tabs: each virtual client polls one
lightweight endpoint every 15 seconds. With 300 clients this is about 20 req/s.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from perf_lib import (  # noqa: E402
    RequestSample,
    build_headers,
    evaluate_load_summary,
    summarize_samples,
)


@dataclass(frozen=True)
class Target:
    path: str
    weight: int = 1
    method: str = "GET"


def _base_url(value: str) -> str:
    return value.rstrip("/") + "/"


def _url(base_url: str, path: str) -> str:
    return urljoin(_base_url(base_url), path.lstrip("/"))


def build_targets(args: argparse.Namespace) -> list[Target]:
    if args.scenario == "idle":
        return [
            Target("/api/version", weight=1),
            Target("/api/user/console/push-messages", weight=3),
        ]
    if args.scenario == "chat-status":
        if not args.chat_id:
            raise SystemExit("--scenario chat-status requires --chat-id")
        return [
            Target(f"/api/user/chats/{quote(chat_id, safe='')}/status", weight=1)
            for chat_id in args.chat_id
        ]
    raise SystemExit(f"Unsupported scenario: {args.scenario}")


async def _request_once(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    target: Target,
) -> RequestSample:
    started = time.perf_counter()
    try:
        response = await client.request(target.method, _url(base_url, target.path))
        latency_ms = (time.perf_counter() - started) * 1000
        return RequestSample(
            endpoint=target.path,
            method=target.method,
            status_code=response.status_code,
            latency_ms=latency_ms,
            ok=200 <= response.status_code < 400,
            error="" if response.status_code < 400 else response.text[:200],
        )
    except Exception as exc:  # pragma: no cover - depends on live network
        latency_ms = (time.perf_counter() - started) * 1000
        return RequestSample(
            endpoint=target.path,
            method=target.method,
            status_code=None,
            latency_ms=latency_ms,
            ok=False,
            error=str(exc),
        )


async def _virtual_client(
    client_id: int,
    client: httpx.AsyncClient,
    *,
    args: argparse.Namespace,
    targets: list[Target],
    samples: list[RequestSample],
) -> None:
    rng = random.Random(args.seed + client_id)
    end_at = time.perf_counter() + args.duration
    # Gentle ramp avoids a thundering herd at t=0.
    if args.ramp_seconds > 0:
        await asyncio.sleep(rng.uniform(0, args.ramp_seconds))
    while time.perf_counter() < end_at:
        target = rng.choices(
            targets,
            weights=[target.weight for target in targets],
            k=1,
        )[0]
        samples.append(
            await _request_once(client, base_url=args.base_url, target=target),
        )
        jitter = rng.uniform(0, args.poll_interval * 0.15)
        await asyncio.sleep(args.poll_interval + jitter)


async def run_load_test(args: argparse.Namespace) -> dict[str, Any]:
    targets = build_targets(args)
    headers = build_headers(
        token=args.token,
        cookie=args.cookie,
        agent_id=args.agent_id,
        extra_headers=args.header,
    )
    samples: list[RequestSample] = []
    started = datetime.now(timezone.utc)
    started_perf = time.perf_counter()
    limits = httpx.Limits(
        max_connections=max(args.users + 10, 20),
        max_keepalive_connections=max(min(args.users, 100), 20),
    )
    async with httpx.AsyncClient(
        headers=headers,
        timeout=args.timeout,
        limits=limits,
        trust_env=False,
    ) as client:
        await asyncio.gather(
            *[
                _virtual_client(
                    client_id,
                    client,
                    args=args,
                    targets=targets,
                    samples=samples,
                )
                for client_id in range(args.users)
            ],
        )

    elapsed = time.perf_counter() - started_perf
    summary = summarize_samples(samples, elapsed_seconds=elapsed)
    evaluation = evaluate_load_summary(
        summary,
        p95_target_ms=args.p95_target_ms,
        max_error_rate=args.max_error_rate,
    )
    return {
        "started_at": started.isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "config": {
            "base_url": args.base_url,
            "scenario": args.scenario,
            "users": args.users,
            "duration": args.duration,
            "poll_interval": args.poll_interval,
            "p95_target_ms": args.p95_target_ms,
            "max_error_rate": args.max_error_rate,
            "targets": [target.__dict__ for target in targets],
        },
        "summary": summary,
        "evaluation": evaluation,
    }


def _print_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    latency = summary["latency_ms"]
    print("QwenPaw load test")
    print(f"  scenario: {report['config']['scenario']}")
    print(f"  users: {report['config']['users']}")
    print(f"  requests: {summary['total_requests']}")
    print(f"  rps: {summary['requests_per_second']}")
    print(
        "  latency(ms): "
        f"p50={latency['p50']} p95={latency['p95']} "
        f"p99={latency['p99']} max={latency['max']}",
    )
    print(f"  error_rate: {summary['error_rate']:.3%}")
    print(f"  passed: {report['evaluation']['passed']}")
    for check in report["evaluation"]["checks"].values():
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"    [{mark}] {check['name']}: {check['detail']}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8088")
    parser.add_argument("--scenario", choices=["idle", "chat-status"], default="idle")
    parser.add_argument("--users", type=int, default=300)
    parser.add_argument("--duration", type=float, default=60)
    parser.add_argument("--poll-interval", type=float, default=15)
    parser.add_argument("--ramp-seconds", type=float, default=10)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--token", default=os.environ.get("QWENPAW_PERF_TOKEN", ""))
    parser.add_argument("--cookie", default="")
    parser.add_argument("--agent-id", default="")
    parser.add_argument("--header", action="append", default=[])
    parser.add_argument("--chat-id", action="append", default=[])
    parser.add_argument("--seed", type=int, default=20260606)
    parser.add_argument("--p95-target-ms", type=float, default=300)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--json-output", default="")
    parser.add_argument(
        "--no-fail-on-threshold",
        action="store_true",
        help="Always exit 0 even if thresholds fail.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = asyncio.run(run_load_test(args))
    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    _print_report(report)
    if args.no_fail_on_threshold:
        return 0
    return 0 if report["evaluation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
