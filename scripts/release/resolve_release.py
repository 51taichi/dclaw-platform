#!/usr/bin/env python3
"""Resolve an immutable DClaw server/client release pair."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class ReleasePair:
    """The exact source revisions that make up one combined image."""

    server_sha: str
    client_sha: str

    def __post_init__(self) -> None:
        for value in (self.server_sha, self.client_sha):
            if not SHA_RE.fullmatch(value):
                raise ValueError(
                    "revision must be a 40-character lowercase hexadecimal SHA"
                )

    @property
    def pair_tag(self) -> str:
        return f"server-{self.server_sha[:12]}-client-{self.client_sha[:12]}"


def resolve_pair(
    event_name: str,
    event_payload: Mapping[str, Any],
    inputs: Mapping[str, str],
    server_main_sha: str,
    client_main_sha: str,
) -> ReleasePair:
    """Resolve event-specific revisions without consulting mutable refs."""

    manual_server = inputs.get("server_sha", "").strip()
    manual_client = inputs.get("client_sha", "").strip()
    if bool(manual_server) != bool(manual_client):
        raise ValueError("both server_sha and client_sha must be supplied together")
    if manual_server:
        return ReleasePair(manual_server, manual_client)

    if event_name == "push":
        return ReleasePair(str(event_payload.get("after", "")), client_main_sha)
    if event_name == "repository_dispatch":
        if event_payload.get("action") != "dclaw_client_main":
            raise ValueError("unsupported repository_dispatch action")
        payload = event_payload.get("client_payload")
        if not isinstance(payload, Mapping):
            raise ValueError("repository_dispatch client_payload is required")
        return ReleasePair(server_main_sha, str(payload.get("client_sha", "")))
    if event_name == "workflow_dispatch":
        return ReleasePair(server_main_sha, client_main_sha)
    raise ValueError(f"unsupported event: {event_name}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--event-path", type=Path, required=True)
    parser.add_argument("--server-main-sha", required=True)
    parser.add_argument("--client-main-sha", required=True)
    parser.add_argument("--server-sha", default="")
    parser.add_argument("--client-sha", default="")
    parser.add_argument("--github-output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    event_payload = json.loads(args.event_path.read_text())
    pair = resolve_pair(
        args.event_name,
        event_payload,
        {"server_sha": args.server_sha, "client_sha": args.client_sha},
        args.server_main_sha,
        args.client_main_sha,
    )
    with args.github_output.open("a", encoding="utf-8") as output:
        output.write(f"server_sha={pair.server_sha}\n")
        output.write(f"client_sha={pair.client_sha}\n")
        output.write(f"pair_tag={pair.pair_tag}\n")


if __name__ == "__main__":
    main()
