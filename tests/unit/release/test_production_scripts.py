from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = REPO_ROOT / "deploy" / "production"


FAKE_DOCKER = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
log = Path(os.environ["FAKE_CALL_LOG"])
with log.open("a") as stream:
    stream.write(json.dumps(["docker", *args]) + "\n")

current_id = os.environ.get("FAKE_CURRENT_ID", "sha256:" + "1" * 64)
target_id = os.environ.get("FAKE_TARGET_ID", "sha256:" + "2" * 64)
current_digest = os.environ.get("FAKE_CURRENT_DIGEST", "ghcr.io/51taichi/dclaw@sha256:" + "1" * 64)
target_digest = os.environ.get("FAKE_TARGET_DIGEST", "ghcr.io/51taichi/dclaw@sha256:" + "2" * 64)
target_server = os.environ.get("FAKE_TARGET_SERVER", "a" * 40)
target_client = os.environ.get("FAKE_TARGET_CLIENT", "b" * 40)
current_server = os.environ.get("FAKE_CURRENT_SERVER", "c" * 40)
current_client = os.environ.get("FAKE_CURRENT_CLIENT", "d" * 40)
state_path = Path(os.environ["FAKE_STATE"])
if state_path.exists():
    state = json.loads(state_path.read_text())
else:
    state = {"running_id": current_id, "compose_count": 0}
    state_path.write_text(json.dumps(state))

def value_for_image(image, format_value):
    target = image.endswith(":main") or "server-" in image or image == target_digest or image == target_id
    if ".Id" in format_value:
        return target_id if target else current_id
    if "RepoDigests" in format_value:
        return target_digest if target else current_digest
    if "server-revision" in format_value:
        if target and os.environ.get("FAKE_LABEL_DRIFT") == "1" and state["compose_count"] > 0:
            return "f" * 40
        return target_server if target else current_server
    if "client-revision" in format_value:
        return target_client if target else current_client
    return ""

if args[:1] == ["pull"]:
    print(args[1])
elif args[:2] == ["image", "inspect"]:
    image = args[2]
    format_value = args[args.index("--format") + 1] if "--format" in args else ""
    print(value_for_image(image, format_value))
elif args[:1] == ["inspect"]:
    name = args[1]
    format_value = args[args.index("--format") + 1] if "--format" in args else ""
    if name == "dclaw" and ".Image" in format_value:
        print(state["running_id"])
    elif ".State.Status" in format_value:
        print("running")
    elif ".State.Running" in format_value:
        failed = os.environ.get("FAKE_HEALTH_FAILURE") == "container_exit" and state["running_id"] == target_id
        print("false" if failed else "true")
    elif ".State.OOMKilled" in format_value:
        failed = os.environ.get("FAKE_HEALTH_FAILURE") == "oom" and state["running_id"] == target_id
        print("true" if failed else "false")
    else:
        print("{}")
elif args[:2] == ["volume", "inspect"] or args[:2] == ["network", "inspect"]:
    print("{}")
elif args[:1] == ["exec"]:
    print("FAKE_CUSTOM_DUMP")
elif args[:1] == ["run"]:
    if os.environ.get("FAKE_BACKUP_INVALID") == "1":
        raise SystemExit(17)
    print("TABLE DATA public users")
elif args[:1] == ["compose"]:
    env_path = Path(args[args.index("--env-file") + 1])
    selected = next(
        line.split("=", 1)[1]
        for line in env_path.read_text().splitlines()
        if line.startswith("DCLAW_IMAGE=")
    )
    state["running_id"] = target_id if selected in (target_digest, target_id) else current_id
    state["compose_count"] += 1
    state_path.write_text(json.dumps(state))
elif args[:1] in (["tag"], ["logs"]):
    pass
else:
    print("{}")
'''


FAKE_CURL = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

with Path(os.environ["FAKE_CALL_LOG"]).open("a") as stream:
    stream.write(json.dumps(["curl", *sys.argv[1:]]) + "\n")
if os.environ.get("FAKE_CURL_FAIL") == "1":
    raise SystemExit(22)
state = json.loads(Path(os.environ["FAKE_STATE"]).read_text())
target_id = os.environ.get("FAKE_TARGET_ID", "sha256:" + "2" * 64)
failure = os.environ.get("FAKE_HEALTH_FAILURE", "")
url = sys.argv[-1]
if state["running_id"] == target_id:
    if failure == "local_api" and "127.0.0.1" in url:
        raise SystemExit(22)
    if failure == "public_api" and "dclaw.deepmega.cn" in url:
        raise SystemExit(22)
print('{"version":"1.1.10"}')
'''


FAKE_FLOCK = r'''#!/bin/sh
if [ "${FAKE_LOCKED:-0}" = 1 ]; then
  exit 1
fi
exit 0
'''


@pytest.fixture
def deployment(tmp_path: Path) -> dict[str, object]:
    root = tmp_path / "deploy"
    root.mkdir()
    (root / "compose.production.yml").write_text(
        (PRODUCTION / "compose.production.yml").read_text()
    )
    (root / "production.env").write_text("QWENPAW_AUTH_ENABLED=true\n")
    (root / "release.env").write_text(
        "DCLAW_IMAGE=ghcr.io/51taichi/dclaw@sha256:" + "1" * 64 + "\n"
        "SERVER_SHA=" + "c" * 40 + "\n"
        "CLIENT_SHA=" + "d" * 40 + "\n"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, content in {
        "docker": FAKE_DOCKER,
        "curl": FAKE_CURL,
        "flock": FAKE_FLOCK,
    }.items():
        path = bin_dir / name
        path.write_text(content)
        path.chmod(0o755)
    log = tmp_path / "calls.jsonl"
    state = tmp_path / "state.json"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "DCLAW_DEPLOY_ROOT": str(root),
            "DCLAW_IMAGE_REPOSITORY": "ghcr.io/51taichi/dclaw",
            "FAKE_CALL_LOG": str(log),
            "FAKE_STATE": str(state),
            "DCLAW_TESTING": "1",
            "DCLAW_TEST_HEALTH_TIMEOUT": "1",
            "DCLAW_TEST_HEALTH_INTERVAL": "0.01",
        }
    )
    return {"root": root, "env": env, "log": log, "state": state}


def _run(deployment: dict[str, object], script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(PRODUCTION / script)],
        check=False,
        capture_output=True,
        text=True,
        env=deployment["env"],
    )


def _calls(deployment: dict[str, object]) -> list[list[str]]:
    log = deployment["log"]
    assert isinstance(log, Path)
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def _contains_call(calls: list[list[str]], *parts: str) -> bool:
    return any(all(part in call for part in parts) for call in calls)


def test_update_same_digest_does_not_recreate_or_backup(
    deployment: dict[str, object],
) -> None:
    env = deployment["env"]
    assert isinstance(env, dict)
    env["FAKE_TARGET_ID"] = "sha256:" + "1" * 64
    env["FAKE_TARGET_DIGEST"] = "ghcr.io/51taichi/dclaw@sha256:" + "1" * 64

    result = _run(deployment, "update.sh")
    calls = _calls(deployment)

    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("NO_UPDATE_REQUIRED\n")
    assert not _contains_call(calls, "compose", "up")
    assert not _contains_call(calls, "exec", "pg_dump")


def test_second_update_is_rejected_by_shared_lock(
    deployment: dict[str, object],
) -> None:
    env = deployment["env"]
    assert isinstance(env, dict)
    env["FAKE_LOCKED"] = "1"

    result = _run(deployment, "update.sh")

    assert result.returncode != 0
    assert "deployment already in progress" in result.stderr
    assert _calls(deployment) == []


def test_invalid_backup_never_recreates_production(
    deployment: dict[str, object],
) -> None:
    env = deployment["env"]
    assert isinstance(env, dict)
    env["FAKE_BACKUP_INVALID"] = "1"

    result = _run(deployment, "update.sh")
    calls = _calls(deployment)

    assert result.returncode != 0
    assert "backup verification failed" in result.stderr.lower()
    assert not _contains_call(calls, "compose", "up")
    assert not _contains_call(calls, "stop", "dclaw")


def test_health_window_is_at_least_420_seconds() -> None:
    text = (PRODUCTION / "update.sh").read_text()

    assert "HEALTH_TIMEOUT=420" in text


def test_successful_update_writes_manifest_and_keeps_external_resources(
    deployment: dict[str, object],
) -> None:
    result = _run(deployment, "update.sh")
    calls = _calls(deployment)
    root = deployment["root"]
    assert isinstance(root, Path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("UPDATE_SUCCESS\n")
    assert _contains_call(calls, "exec", "pg_dump")
    assert _contains_call(calls, "run", "pg_restore", "--list")
    assert _contains_call(calls, "compose", "up")
    assert not _contains_call(calls, "volume", "rm")
    assert not _contains_call(calls, "network", "rm")
    latest = Path((root / "LATEST_SUCCESS").read_text().strip())
    manifest = json.loads((latest / "manifest.json").read_text())
    assert manifest["result"] == "UPDATE_SUCCESS"
    assert manifest["server_sha"] == "a" * 40
    assert manifest["client_sha"] == "b" * 40
    assert (latest / "manifest.json").stat().st_mode & 0o777 == 0o600
    assert (latest / "pre-update.dump").stat().st_mode & 0o777 == 0o600
    assert (root / "release.env").stat().st_mode & 0o777 == 0o600


def test_exact_pair_uses_immutable_tag_and_validates_both_labels(
    deployment: dict[str, object],
) -> None:
    server_sha = "a" * 40
    client_sha = "b" * 40
    result = subprocess.run(
        [
            "bash",
            str(PRODUCTION / "update.sh"),
            "--server-sha",
            server_sha,
            "--client-sha",
            client_sha,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=deployment["env"],
    )

    assert result.returncode == 0, result.stderr
    assert _contains_call(
        _calls(deployment),
        f"ghcr.io/51taichi/dclaw:server-{server_sha[:12]}-client-{client_sha[:12]}",
    )


@pytest.mark.parametrize(
    "failure",
    ["container_exit", "oom", "local_api", "public_api"],
)
def test_update_failure_restores_previous_image_without_database_restore(
    deployment: dict[str, object],
    failure: str,
) -> None:
    env = deployment["env"]
    assert isinstance(env, dict)
    env["FAKE_HEALTH_FAILURE"] = failure

    result = _run(deployment, "update.sh")
    calls = _calls(deployment)
    state_path = deployment["state"]
    assert isinstance(state_path, Path)
    state = json.loads(state_path.read_text())

    assert result.returncode == 1, result.stderr
    assert "UPDATE_FAILED_ROLLBACK_READY" in result.stdout
    assert state["running_id"] == "sha256:" + "1" * 64
    assert state["compose_count"] == 2
    assert not _contains_call(calls, "pg_restore", "--clean")
    assert not _contains_call(calls, "volume", "rm")


def test_status_is_read_only_and_redacts_secrets(
    deployment: dict[str, object],
) -> None:
    root = deployment["root"]
    assert isinstance(root, Path)
    (root / "production.env").write_text(
        "QWENPAW_DATABASE_URL=postgresql://user:secret-value@db/app\n"
        "GHCR_TOKEN=secret-token\n"
    )

    result = _run(deployment, "status.sh")
    calls = _calls(deployment)

    assert result.returncode == 0, result.stderr
    assert "secret-value" not in result.stdout
    assert "secret-token" not in result.stdout
    assert "postgresql://" not in result.stdout
    assert not _contains_call(calls, "compose", "up")
    assert not _contains_call(calls, "exec", "pg_dump")
    assert not _contains_call(calls, "pull")


def test_rollback_only_switches_application_image(
    deployment: dict[str, object],
) -> None:
    root = deployment["root"]
    assert isinstance(root, Path)
    release = root / "releases" / "successful"
    release.mkdir(parents=True)
    (release / "manifest.json").write_text(
        json.dumps(
            {
                "result": "UPDATE_SUCCESS",
                "previous_image": "sha256:" + "1" * 64,
                "target_image": "ghcr.io/51taichi/dclaw@sha256:" + "2" * 64,
                "server_sha": "a" * 40,
                "client_sha": "b" * 40,
            }
        )
    )
    (root / "LATEST_SUCCESS").write_text(str(release) + "\n")
    env = deployment["env"]
    assert isinstance(env, dict)
    env["FAKE_CURRENT_ID"] = "sha256:" + "2" * 64
    env["FAKE_CURRENT_DIGEST"] = "ghcr.io/51taichi/dclaw@sha256:" + "2" * 64
    env["FAKE_TARGET_ID"] = "sha256:" + "1" * 64
    env["FAKE_TARGET_DIGEST"] = "ghcr.io/51taichi/dclaw@sha256:" + "1" * 64

    result = _run(deployment, "rollback.sh")
    calls = _calls(deployment)

    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("ROLLBACK_SUCCESS\n")
    assert _contains_call(calls, "compose", "up")
    assert not _contains_call(calls, "exec", "pg_dump")
    assert not _contains_call(calls, "volume", "rm")
    assert not _contains_call(calls, "network", "rm")
