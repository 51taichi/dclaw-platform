# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = REPO_ROOT / "deploy" / "production"


FAKE_GH = r"""#!/usr/bin/env python3
import io
import os
import sys
import tarfile

args = sys.argv[1:]
log_path = os.environ.get("FAKE_GH_LOG")
if log_path:
    with open(log_path, "a", encoding="utf-8") as stream:
        stream.write(" ".join(args) + "\n")
if args[:2] == ["auth", "status"]:
    raise SystemExit(0)
elif args[:2] == ["auth", "setup-git"]:
    raise SystemExit(0)
elif args[:1] == ["api"] and "/commits/main" in args[1]:
    failures = int(os.environ.get("FAKE_GH_API_FAILURES", "0"))
    counter_path = os.environ.get("FAKE_GH_API_COUNTER")
    if counter_path:
        counter = __import__("pathlib").Path(counter_path)
        attempts = int(counter.read_text() or "0") if counter.exists() else 0
        counter.write_text(str(attempts + 1))
        if attempts < failures:
            raise SystemExit(1)
    print(("c" if "dclaw-server" in args[1] else "d") * 40)
elif args[:1] == ["api"] and "/tarball/" in args[1]:
    server = "dclaw-server" in args[1]
    files = (
        {"deploy/Dockerfile": b"FROM scratch\n"}
        if server
        else {
            "console/package.json": b"{}\n",
            "console/package-lock.json": b"{}\n",
            "website/public/docs/index.md": b"docs\n",
        }
    )
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo("snapshot/" + name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
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
    assert '"repos/$repository/tarball/$revision"' in text
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
    gh_log = tmp_path / "gh.log"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "DCLAW_DEPLOY_ROOT": str(deploy_root),
        "FAKE_GIT_LOG": str(git_log),
        "FAKE_GH_LOG": str(gh_log),
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
    calls = gh_log.read_text()
    assert "api repos/51taichi/dclaw-server/commits/main --jq .sha" in calls
    assert f"api repos/51taichi/dclaw-server/tarball/{'c' * 40}" in calls
    assert not git_log.exists() or "ls-remote" not in git_log.read_text()


def test_build_release_accepts_an_exact_revision_pair(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_commands(fake_bin)
    deploy_root = tmp_path / "deploy"
    gh_log = tmp_path / "gh.log"
    server_sha = "c" * 40
    client_sha = "d" * 40
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "DCLAW_DEPLOY_ROOT": str(deploy_root),
        "FAKE_GH_LOG": str(gh_log),
    }

    result = subprocess.run(
        [
            "bash",
            str(PRODUCTION / "build-release.sh"),
            "--server-sha",
            server_sha,
            "--client-sha",
            client_sha,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    pending = dict(
        line.split("=", 1)
        for line in (deploy_root / "pending-release.env").read_text().splitlines()
    )
    assert pending["SERVER_SHA"] == server_sha
    assert pending["CLIENT_SHA"] == client_sha
    calls = gh_log.read_text()
    assert "/commits/main" not in calls
    assert f"api repos/51taichi/dclaw-server/tarball/{server_sha}" in calls
    assert f"api repos/51taichi/dclaw-client/tarball/{client_sha}" in calls


def test_build_release_rejects_an_incomplete_revision_pair(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "bash",
            str(PRODUCTION / "build-release.sh"),
            "--server-sha",
            "c" * 40,
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "DCLAW_DEPLOY_ROOT": str(tmp_path / "deploy")},
    )

    assert result.returncode != 0
    assert result.stdout == (
        "BUILD_FAILED\n"
        "reason：both --server-sha and --client-sha are required\n"
    )


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


def test_build_release_retries_transient_github_api_failures(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_commands(fake_bin)
    counter = tmp_path / "github-api-attempts"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "DCLAW_DEPLOY_ROOT": str(tmp_path / "deploy"),
        "FAKE_GH_API_FAILURES": "2",
        "FAKE_GH_API_COUNTER": str(counter),
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
