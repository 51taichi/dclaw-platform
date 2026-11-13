"""Authenticated developer diagnostics using only the published HTTP contract."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from jsonschema import Draft202012Validator, FormatChecker


SCHEMA_ROOT = Path(__file__).parent / "schemas"


def _read(base_url: str, path: str, token: str, schema_path: Path) -> dict:
    if not base_url.startswith("https://"):
        raise ValueError("the DClaw endpoint must use HTTPS")
    request = Request(base_url.rstrip("/") + path, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json",
    })
    with urlopen(request, timeout=20) as response:
        value = json.load(response)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    return value


def lookup(base_url: str, agent_id: str, invocation_id: str, token: str) -> dict:
    path = (
        "/api/user/super-expert-publishing/runtime-diagnostics/v3/references/"
        + quote(invocation_id, safe="") + "?" + urlencode({"agent_id": agent_id})
    )
    return _read(base_url, path, token, SCHEMA_ROOT /
                 "runtime-diagnostics-v3/by-reference-response.schema.json")


def lookup_turn(base_url: str, agent_id: str, invocation_id: str, token: str) -> dict:
    path = (
        "/api/user/super-expert-publishing/runtime-diagnostics/v4/references/"
        + quote(invocation_id, safe="") + "?" + urlencode({"agent_id": agent_id})
    )
    return _read(base_url, path, token, SCHEMA_ROOT /
                 "runtime-diagnostics-v4/by-reference-response.schema.json")


def search(
    base_url: str, agent_id: str, start: str, end: str, token: str,
    cursor: str | None = None,
) -> dict:
    params = {"agent_id": agent_id, "start": start, "end": end}
    if cursor is not None:
        params["cursor"] = cursor
    path = "/api/user/super-expert-publishing/runtime-diagnostics/v1/search?" + urlencode({
        **params,
    })
    return _read(base_url, path, token, SCHEMA_ROOT /
                 "runtime-diagnostics-search-v1/response.schema.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read only redacted Super Agent failures")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--agent-id", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--invocation-id")
    group.add_argument("--start", help="UTC ISO-8601 start; requires --end")
    parser.add_argument("--end", help="exclusive UTC ISO-8601 end, at most 24h later")
    parser.add_argument("--cursor", help="next_cursor returned by the previous search page")
    parser.add_argument("--include-completed", action="store_true",
                        help="read Host operations in completed or failed turns using v4")
    args = parser.parse_args()
    if bool(args.start) != bool(args.end):
        parser.error("--start and --end must be supplied together")
    if args.cursor and not args.start:
        parser.error("--cursor requires --start and --end")
    token = os.environ.get("DCLAW_ACCESS_TOKEN")
    if not token:
        parser.error("sign in locally and set DCLAW_ACCESS_TOKEN")
    result = (
        (lookup_turn if args.include_completed else lookup)(
            args.base_url, args.agent_id, args.invocation_id, token,
        )
        if args.invocation_id else
        search(args.base_url, args.agent_id, args.start, args.end, token, args.cursor)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
