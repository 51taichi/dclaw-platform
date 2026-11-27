#!/usr/bin/env python3
"""Read an authorized task's published DClaw runtime diagnostics."""

import argparse
from datetime import datetime, timedelta
import getpass
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse

from fetch_developer_pack import request_json
from summarize_runtime_diagnostics import (
    render_reference_summary, render_search_summary, render_summary,
    validate_full_schema, validate_reference_response, validate_response,
    validate_search_response,
)


CONTRACT = "developer.runtime.diagnostics.read/1"
RESOURCE = "/api/user/super-expert-platform/runtime-diagnostics/v1/tasks/"
REFERENCE_RESOURCE = "/api/user/super-expert-publishing/runtime-diagnostics/v1/references/"
REFERENCE_RESOURCE_V2 = "/api/user/super-expert-publishing/runtime-diagnostics/v2/references/"
REFERENCE_RESOURCE_V3 = "/api/user/super-expert-publishing/runtime-diagnostics/v3/references/"
REFERENCE_RESOURCE_V4 = "/api/user/super-expert-publishing/runtime-diagnostics/v4/references/"
REFERENCE_RESOURCE_V5 = "/api/user/super-expert-publishing/runtime-diagnostics/v5/references/"
REFERENCE_RESOURCE_V6 = "/api/user/super-expert-publishing/runtime-diagnostics/v6/references/"
SEARCH_RESOURCE = "/api/user/super-expert-publishing/runtime-diagnostics/v1/search"
IDENTIFIER = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
INVOCATION_ID = re.compile(r"(?:[0-9a-f]{32}|preflight-[0-9a-f]{32})\Z")


def check_response(response, schema, by_reference=False):
    if by_reference:
        validate_reference_response(response, schema)
    else:
        validate_response(response, schema)


def check_search_window(start, end):
    try:
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except ValueError as exc:
        raise ValueError("search window must use UTC ISO-8601 timestamps") from exc
    if (first.tzinfo is None or last.tzinfo is None
            or first.utcoffset() != timedelta(0) or last.utcoffset() != timedelta(0)
            or not timedelta(0) < last - first <= timedelta(hours=24)):
        raise ValueError("search window must be UTC, increasing, and at most 24 hours")


def check_catalog(devkit_root, key, contract, path_template):
    catalog_path = devkit_root / "operation-catalog.json"
    if not catalog_path.is_file():
        raise ValueError("verified official DevKit has no operation catalog")
    operation = json.loads(catalog_path.read_text(encoding="utf-8")).get(key, {})
    if (operation.get("contract") != contract or operation.get("method") != "GET"
            or operation.get("path_template") != path_template):
        raise ValueError("official operation catalog does not match diagnostics route")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Target DClaw HTTPS origin")
    parser.add_argument("--devkit-root", required=True, type=Path, help="Verified official DevKit directory")
    parser.add_argument("--agent-id", required=True)
    identifier = parser.add_mutually_exclusive_group(required=True)
    identifier.add_argument("--task-id")
    identifier.add_argument("--invocation-id", help="Customer-visible failure reference from the same Agent")
    identifier.add_argument("--start", help="UTC search start; requires --end, at most 24 hours")
    parser.add_argument("--end", help="Exclusive UTC search end")
    parser.add_argument("--limit", type=int, default=50, help="Search page size, 1-50")
    parser.add_argument("--cursor", help="Next cursor from the same search window")
    parser.add_argument("--output", required=True, type=Path, help="New receipt path in the current Agent project")
    parser.add_argument("--summary-output", type=Path, help="Optional new redacted Markdown summary path")
    args = parser.parse_args()

    url = urllib.parse.urlsplit(args.base_url)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.path not in ("", "/") or url.query or url.fragment):
        parser.error("--base-url must be an HTTPS origin without credentials")
    if not IDENTIFIER.fullmatch(args.agent_id) or (args.task_id and not IDENTIFIER.fullmatch(args.task_id)):
        parser.error("--agent-id and --task-id must be simple nonempty identifiers")
    if args.invocation_id and not INVOCATION_ID.fullmatch(args.invocation_id):
        parser.error("--invocation-id must match the official reference format")
    if bool(args.start) != bool(args.end):
        parser.error("--start and --end must be supplied together")
    if (args.cursor or args.limit != 50) and not args.start:
        parser.error("--cursor and --limit require a search window")
    if args.start:
        try:
            check_search_window(args.start, args.end)
        except ValueError as exc:
            parser.error(str(exc))
        schema_dir = args.devkit_root / "schemas" / "runtime-diagnostics-search-v1"
        schema_path = schema_dir / "response.schema.json"
        request_path = schema_dir / "request.schema.json"
        check_catalog(args.devkit_root, "developer_diagnostic_search",
                      "developer.runtime.diagnostics.search/1",
                      SEARCH_RESOURCE + "?agent_id={agent_id}&start={start}&end={end}")
        if not request_path.is_file():
            parser.error("verified official DevKit has no diagnostic search request schema")
        search_request = {"agent_id": args.agent_id, "start": args.start,
                          "end": args.end, "limit": args.limit}
        if args.cursor:
            search_request["cursor"] = args.cursor
        validate_full_schema(search_request, json.loads(request_path.read_text(encoding="utf-8")))
    else:
        schema_name = "by-reference-response.schema.json" if args.invocation_id else "response.schema.json"
        schema_dir = args.devkit_root / "schemas" / "runtime-diagnostics-v1"
        if args.invocation_id:
            for version in ("v6", "v5", "v4", "v3", "v2"):
                candidate = args.devkit_root / "schemas" / f"runtime-diagnostics-{version}"
                if (candidate / schema_name).is_file():
                    schema_dir = candidate
                    break
        schema_path = schema_dir / schema_name
    if not schema_path.is_file():
        parser.error("verified official DevKit has no applicable developer diagnostics schema")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if args.invocation_id:
        version = schema_dir.name.removeprefix("runtime-diagnostics-")
        expected = f"developer.runtime.diagnostics.by-reference/{version[-1]}"
        branches = schema.get("oneOf", [])
        if len(branches) != 2 or any(
            branch.get("properties", {}).get("contract", {}).get("const") != expected
            for branch in branches
        ):
            parser.error("official DevKit schema does not match the selected reference route")
        if version in ("v3", "v4", "v5", "v6"):
            resource = {"v6": REFERENCE_RESOURCE_V6, "v5": REFERENCE_RESOURCE_V5,
                        "v4": REFERENCE_RESOURCE_V4,
                        "v3": REFERENCE_RESOURCE_V3}[version]
            check_catalog(args.devkit_root, f"developer_reference_diagnostics_{version}", expected,
                          resource + "{invocation_id}?agent_id={agent_id}")
            request_path = schema_dir / "by-reference-request.schema.json"
            if not request_path.is_file():
                parser.error(f"verified official DevKit has no {version} request schema")
            validate_full_schema({"agent_id": args.agent_id, "invocation_id": args.invocation_id},
                                 json.loads(request_path.read_text(encoding="utf-8")))
            if version == "v6":
                error_path = schema_dir / "error.schema.json"
                if not error_path.is_file():
                    parser.error("verified official DevKit has no v6 error schema")
                error_schema = json.loads(error_path.read_text(encoding="utf-8"))
                for detail in ("diagnostic not found", "diagnostics unavailable"):
                    validate_full_schema({"detail": detail}, error_schema)
    elif not args.start and schema.get("properties", {}).get("contract", {}).get("const") != CONTRACT:
        parser.error("official DevKit schema does not describe developer diagnostics v1")
    if args.output.exists() or args.output.is_symlink():
        parser.error("output already exists; inspect it before retrying")
    if args.summary_output:
        if args.summary_output.resolve() == args.output.resolve():
            parser.error("summary output must differ from the raw receipt")
        if args.summary_output.exists() or args.summary_output.is_symlink():
            parser.error("summary output already exists; inspect it before retrying")
    if not sys.stdin.isatty():
        parser.error("run in an interactive terminal")

    base = args.base_url.rstrip("/")
    username = input("DClaw username: ").strip()
    password = getpass.getpass("DClaw password: ")
    if not username or not password:
        parser.error("username and password are required")
    try:
        login = request_json(base + "/api/auth/login", payload={"username": username, "password": password})
    finally:
        password = None
    token = login.get("token") if isinstance(login, dict) else None
    if not isinstance(token, str) or not token:
        raise ValueError("login returned no access token")
    request_json(base + "/api/auth/verify", token=token)
    if args.start:
        endpoint = base + SEARCH_RESOURCE + "?" + urllib.parse.urlencode(search_request)
    else:
        resource = RESOURCE
        if args.invocation_id:
            resource = {"v6": REFERENCE_RESOURCE_V6, "v5": REFERENCE_RESOURCE_V5,
                        "v4": REFERENCE_RESOURCE_V4,
                        "v3": REFERENCE_RESOURCE_V3,
                        "v2": REFERENCE_RESOURCE_V2}.get(
                version, REFERENCE_RESOURCE)
        endpoint = base + resource + urllib.parse.quote(args.invocation_id or args.task_id, safe="")
        endpoint += "?" + urllib.parse.urlencode({"agent_id": args.agent_id})
    response = request_json(endpoint, token=token)
    token = None
    if args.start:
        validate_search_response(response, schema)
    else:
        check_response(response, schema, by_reference=bool(args.invocation_id))
    summary = None
    if args.summary_output:
        if args.start:
            summary = render_search_summary(response, schema, args.agent_id, args.start, args.end)
        elif args.invocation_id:
            summary = render_reference_summary(response, schema, args.agent_id, args.invocation_id)
        else:
            summary = render_summary(response, schema, args.agent_id, args.task_id)

    raw = (json.dumps(response, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as receipt:
        receipt.write(raw)
    if summary is not None:
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        with args.summary_output.open("x", encoding="utf-8", newline="\n") as report:
            report.write(summary)
    if args.invocation_id and version in ("v4", "v5", "v6"):
        count_label, count = "turns", int(response["status"] == "found")
    else:
        count_label = "failures"
        count = len(response["failures"]) if args.start or args.task_id else int(response["status"] == "found")
    print(f"saved diagnostics: status={response['status']}, "
          f"{count_label}={count}, sha256={hashlib.sha256(raw).hexdigest()}")
    if summary is not None:
        print(f"saved redacted summary: sha256={hashlib.sha256(summary.encode('utf-8')).hexdigest()}")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        detail = {
            404: "reference not found or not authorized; do not fall back to an older contract",
            503: "diagnostic evidence source unavailable; do not treat this as no_record or fall back",
        }.get(exc.code, "check the target contract and access before retrying")
        print(f"Diagnostics read failed: HTTP {exc.code}; {detail}", file=sys.stderr)
        raise SystemExit(1)
    except urllib.error.URLError:
        print("Diagnostics read failed: network request failed", file=sys.stderr)
        raise SystemExit(1)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Diagnostics read failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
