"""Read an existing AIGC task binding as the signed-in expert developer."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from jsonschema import Draft202012Validator


def lookup(
    base_url: str, agent_id: str, session_id: str, token: str,
    *, task_key: str | None = None, content_revision: int | None = None,
) -> dict:
    if not base_url.startswith("https://"):
        raise ValueError("the DClaw endpoint must use HTTPS")
    params = {"agent_id": agent_id}
    if task_key is not None:
        params["task_key"] = task_key
    if content_revision is not None:
        params["content_revision"] = content_revision
    path = (
        "/api/user/super-expert-publishing/aigc-tasks/v1/sessions/"
        + quote(session_id, safe="") + "/binding?" + urlencode(params)
    )
    request = Request(base_url.rstrip("/") + path, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json",
    })
    with urlopen(request, timeout=20) as response:
        value = json.load(response)
    schema = json.loads((
        Path(__file__).parent
        / "schemas/developer-aigc-binding-v1/response.schema.json"
    ).read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Read one owned AIGC task binding")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--task-key")
    parser.add_argument("--content-revision", type=int)
    args = parser.parse_args()
    token = os.environ.get("DCLAW_ACCESS_TOKEN")
    if not token:
        parser.error("sign in locally and set DCLAW_ACCESS_TOKEN")
    result = lookup(
        args.base_url, args.agent_id, args.session_id, token,
        task_key=args.task_key, content_revision=args.content_revision,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
