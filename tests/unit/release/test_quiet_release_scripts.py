# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = REPO_ROOT / "deploy" / "production"


FAKE_GH = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
state = Path(os.environ["FAKE_GH_STATE"])
payload = (
    json.loads(state.read_text()) if state.exists() else {"started": False}
)
if args[:2] == ["auth", "status"]:
    raise SystemExit(0)
if args[:2] == ["api", "repos/51taichi/dclaw-server/commits/main"]:
    print("a" * 40)
elif args[:2] == ["api", "repos/51taichi/dclaw-client/commits/main"]:
    print("b" * 40)
elif args[:2] == ["run", "list"]:
    print(json.dumps([{"databaseId": 101}]) if payload["started"] else "[]")
elif args[:2] == ["workflow", "run"]:
    payload["started"] = True
    state.write_text(json.dumps(payload))
elif args[:2] == ["run", "watch"]:
    print("verbose build output that must stay in the log")
    if os.environ.get("FAKE_GH_WATCH_FAIL") == "1":
        raise SystemExit(1)
else:
    raise SystemExit(f"unexpected gh call: {args}")
"""


def test_build_release_waits_silently_and_pins_both_main_revisions(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    deploy_root = tmp_path / "deploy"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "DCLAW_DEPLOY_ROOT": str(deploy_root),
        "DCLAW_BUILD_DISCOVERY_INTERVAL": "0",
        "DCLAW_BUILD_DISCOVERY_TIMEOUT": "2",
        "FAKE_GH_STATE": str(tmp_path / "gh-state.json"),
    }

    result = subprocess.run(
        ["bash", str(PRODUCTION / "build-release.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "BUILD_SUCCESS\n"
        "server/main：aaaaaaa\n"
        "client/main：bbbbbbb\n"
        "image：ghcr.io/51taichi/dclaw:server-aaaaaaaaaaaa-"
        "client-bbbbbbbbbbbb\n"
    )
    pending = dict(
        line.split("=", 1)
        for line in (deploy_root / "pending-release.env")
        .read_text()
        .splitlines()
    )
    assert pending["SERVER_SHA"] == "a" * 40
    assert pending["CLIENT_SHA"] == "b" * 40
    detail = Path(pending["BUILD_LOG"])
    assert "verbose build output" in detail.read_text()


def test_build_failure_never_writes_a_deployable_release(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    deploy_root = tmp_path / "deploy"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "DCLAW_DEPLOY_ROOT": str(deploy_root),
        "DCLAW_BUILD_DISCOVERY_INTERVAL": "0",
        "DCLAW_BUILD_DISCOVERY_TIMEOUT": "2",
        "FAKE_GH_STATE": str(tmp_path / "gh-state.json"),
        "FAKE_GH_WATCH_FAIL": "1",
    }

    result = subprocess.run(
        ["bash", str(PRODUCTION / "build-release.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode != 0
    assert result.stdout.startswith("BUILD_FAILED\n")
    assert "BUILD_SUCCESS" not in result.stdout
    assert not (deploy_root / "pending-release.env").exists()


def test_deploy_result_reports_only_the_saved_summary(tmp_path: Path) -> None:
    deploy_root = tmp_path / "deploy"
    deploy_root.mkdir()
    result_file = deploy_root / "latest-deploy-result"
    result_file.write_text(
        "UPDATE_SUCCESS\n"
        "server/main：aaaaaaa\n"
        "client/main：bbbbbbb\n"
        "container：running\n"
        "local_api：200\n"
        "public_api：200\n",
    )
    environment = {
        **os.environ,
        "DCLAW_DEPLOY_ROOT": str(deploy_root),
    }

    result = subprocess.run(
        ["bash", str(PRODUCTION / "deploy-result.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == result_file.read_text()
