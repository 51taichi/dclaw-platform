"""Read owner-scoped local task diagnostics without exposing device payloads."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from jsonschema import Draft202012Validator, FormatChecker


SCHEMA = Path(__file__).parent / "schemas/local-task-diagnostics-v1/response.schema.json"


def read(base_url: str, agent_id: str, reference: str, kind: str, token: str) -> dict:
    if not base_url.startswith("https://") or kind not in {"tasks", "invocations"}:
        raise ValueError("HTTPS endpoint and task or invocation kind required")
    path = (f"/api/user/super-expert-publishing/local-task-diagnostics/v1/"
            f"{kind}/{quote(reference, safe='')}?{urlencode({'agent_id': agent_id})}")
    request = Request(base_url.rstrip("/") + path, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json",
    })
    with urlopen(request, timeout=20) as response:
        value = json.load(response)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Read redacted local task diagnostics")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--agent-id", required=True)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--task-id")
    choice.add_argument("--invocation-id")
    args = parser.parse_args()
    token = os.environ.get("DCLAW_ACCESS_TOKEN")
    if not token:
        parser.error("sign in locally and set DCLAW_ACCESS_TOKEN")
    result = read(
        args.base_url, args.agent_id,
        args.task_id or args.invocation_id,
        "tasks" if args.task_id else "invocations", token,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
