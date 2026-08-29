# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.release.resolve_release import ReleasePair, resolve_pair


REPO_ROOT = Path(__file__).resolve().parents[3]
RESOLVER = REPO_ROOT / "scripts" / "release" / "resolve_release.py"


def test_server_push_uses_event_sha_and_current_client_main() -> None:
    pair = resolve_pair(
        "push",
        {"after": "a" * 40},
        {},
        server_main_sha="c" * 40,
        client_main_sha="b" * 40,
    )

    assert pair == ReleasePair(server_sha="a" * 40, client_sha="b" * 40)


def test_client_dispatch_uses_payload_sha_and_current_server_main() -> None:
    pair = resolve_pair(
        "repository_dispatch",
        {
            "action": "dclaw_client_main",
            "client_payload": {"client_sha": "b" * 40},
        },
        {},
        server_main_sha="a" * 40,
        client_main_sha="c" * 40,
    )

    assert pair == ReleasePair(server_sha="a" * 40, client_sha="b" * 40)
    assert pair.pair_tag == f"server-{'a' * 12}-client-{'b' * 12}"


def test_manual_inputs_override_branch_tips_as_a_complete_pair() -> None:
    pair = resolve_pair(
        "workflow_dispatch",
        {},
        {"server_sha": "d" * 40, "client_sha": "e" * 40},
        server_main_sha="a" * 40,
        client_main_sha="b" * 40,
    )

    assert pair == ReleasePair(server_sha="d" * 40, client_sha="e" * 40)


def test_manual_inputs_must_be_both_present_or_both_absent() -> None:
    with pytest.raises(ValueError, match="both server_sha and client_sha"):
        resolve_pair(
            "workflow_dispatch",
            {},
            {"server_sha": "a" * 40, "client_sha": ""},
            server_main_sha="c" * 40,
            client_main_sha="d" * 40,
        )


@pytest.mark.parametrize("bad", ["main", "abc", "g" * 40, "a" * 39])
def test_rejects_non_full_git_sha(bad: str) -> None:
    with pytest.raises(
        ValueError,
        match="40-character lowercase hexadecimal SHA",
    ):
        ReleasePair(server_sha=bad, client_sha="b" * 40)


def test_cli_writes_only_release_outputs(tmp_path: Path) -> None:
    event_file = tmp_path / "event.json"
    output_file = tmp_path / "output.txt"
    event_file.write_text(json.dumps({"after": "a" * 40}))

    result = subprocess.run(
        [
            sys.executable,
            str(RESOLVER),
            "--event-name",
            "push",
            "--event-path",
            str(event_file),
            "--server-main-sha",
            "c" * 40,
            "--client-main-sha",
            "b" * 40,
            "--github-output",
            str(output_file),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert output_file.read_text().splitlines() == [
        f"server_sha={'a' * 40}",
        f"client_sha={'b' * 40}",
        f"pair_tag=server-{'a' * 12}-client-{'b' * 12}",
    ]
