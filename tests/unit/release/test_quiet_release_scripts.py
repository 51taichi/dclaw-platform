# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = REPO_ROOT / "deploy" / "production"


FAKE_GH = r"""#!/usr/bin/env python3
import sys

args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    raise SystemExit(0)
elif args[:2] == ["auth", "setup-git"]:
    raise SystemExit(0)
else:
    raise SystemExit(f"unexpected gh call: {args}")
"""


FAKE_GIT = r"""#!/usr/bin/env python3
import os
import sys
from pathlib import Path

args = sys.argv[1:]
log_path = os.environ.get("FAKE_GIT_LOG")
if log_path:
    with open(log_path, "a", encoding="utf-8") as stream:
        stream.write(" ".join(args) + "\n")
if args[:2] == ["clone", "--no-checkout"]:
    repository, directory = args[2:]
    root = Path(directory)
    (root / ".git").mkdir(parents=True)
    if "dclaw-server" in repository:
        script = root / "scripts/release/assemble_context.sh"
        script.parent.mkdir(parents=True)
        script.write_text(
            "#!/bin/sh\nmkdir -p \"$3/deploy\"\n"
            "touch \"$3/deploy/Dockerfile\"\n"
        )
        script.chmod(0o755)
    else:
        (root / "console").mkdir()
elif args[:1] == ["ls-remote"]:
    failures = int(os.environ.get("FAKE_GIT_LS_REMOTE_FAILURES", "0"))
    counter_path = os.environ.get("FAKE_GIT_LS_REMOTE_COUNTER")
    if counter_path:
        counter = Path(counter_path)
        attempts = int(counter.read_text() or "0") if counter.exists() else 0
        counter.write_text(str(attempts + 1))
        if attempts < failures:
            raise SystemExit(1)
    repository = args[1]
    print(("c" if "dclaw-server" in repository else "d") * 40 + "\trefs/heads/main")
elif args[:1] == ["-C"]:
    directory = Path(args[1])
    command = args[2]
    if command == "rev-parse":
        print(("c" if directory.name == "server" else "d") * 40)
else:
    raise SystemExit(f"unexpected git call: {args}")
"""


FAKE_DOCKER = r"""#!/usr/bin/env python3
import os
import sys

args = sys.argv[1:]
if args[:1] == ["build"]:
    print("local docker build output that must stay in the log")
    if os.environ.get("FAKE_DOCKER_BUILD_FAIL") == "1":
        raise SystemExit(1)
elif args[:2] == ["image", "inspect"]:
    format_value = args[args.index("--format") + 1]
    if ".Id" in format_value:
        print("sha256:" + "2" * 64)
    else:
        print(("c" if "server-revision" in format_value else "d") * 40)
else:
    raise SystemExit(f"unexpected docker call: {args}")
"""


FAKE_FLOCK = "#!/bin/sh\nexit 0\n"


def _write_fake_commands(fake_bin: Path) -> None:
    for name, content in {
        "gh": FAKE_GH,
        "git": FAKE_GIT,
        "docker": FAKE_DOCKER,
        "flock": FAKE_FLOCK,
    }.items():
        path = fake_bin / name
        path.write_text(content)
        path.chmod(0o755)


def test_build_release_uses_one_local_build_path_without_actions() -> None:
    text = (PRODUCTION / "build-release.sh").read_text()

    assert "gh workflow run" not in text
    assert "gh run watch" not in text
    assert "scripts/release/assemble_context.sh" in text
    assert "docker build" in text
    assert "DCLAW_LOCAL_IMAGE_REPOSITORY:-dclaw-local" in text
    assert 'IMAGE_TAG="$LOCAL_IMAGE_REPOSITORY:server-' in text


def test_build_release_waits_silently_and_pins_both_main_revisions(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_commands(fake_bin)
    deploy_root = tmp_path / "deploy"
    git_log = tmp_path / "git.log"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "DCLAW_DEPLOY_ROOT": str(deploy_root),
        "FAKE_GIT_LOG": str(git_log),
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
        "server/main：ccccccc\n"
        "client/main：ddddddd\n"
        "image：dclaw-local:server-cccccccccccc-"
        "client-dddddddddddd\n"
    )
    pending = dict(
        line.split("=", 1)
        for line in (deploy_root / "pending-release.env")
        .read_text()
        .splitlines()
    )
    assert pending["SERVER_SHA"] == "c" * 40
    assert pending["CLIENT_SHA"] == "d" * 40
    assert pending["IMAGE_ID"] == "sha256:" + "2" * 64
    detail = Path(pending["BUILD_LOG"])
    assert "local docker build output" in detail.read_text()
    calls = git_log.read_text()
    assert "remote set-url origin https://github.com/51taichi/dclaw-server.git" in calls
    assert "ls-remote https://github.com/51taichi/dclaw-server.git refs/heads/main" in calls
    assert f"fetch --force --prune origin {'c' * 40}" in calls


def test_build_failure_never_writes_a_deployable_release(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_commands(fake_bin)
    deploy_root = tmp_path / "deploy"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "DCLAW_DEPLOY_ROOT": str(deploy_root),
        "FAKE_DOCKER_BUILD_FAIL": "1",
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


def test_build_release_retries_transient_remote_lookup_failures(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_commands(fake_bin)
    counter = tmp_path / "ls-remote-attempts"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "DCLAW_DEPLOY_ROOT": str(tmp_path / "deploy"),
        "FAKE_GIT_LS_REMOTE_FAILURES": "2",
        "FAKE_GIT_LS_REMOTE_COUNTER": str(counter),
        "DCLAW_BUILD_RETRY_DELAY_SECONDS": "0",
    }

    result = subprocess.run(
        ["bash", str(PRODUCTION / "build-release.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("BUILD_SUCCESS\n")
    assert int(counter.read_text()) >= 3


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


def test_deploy_worker_uses_snapshot_without_pending_file_dependency() -> None:
    text = (PRODUCTION / "deploy-release.sh").read_text()
    worker = text.split("run_worker() {", 1)[1].split("\n}\n", 1)[0]

    assert '"$PENDING"' not in worker
