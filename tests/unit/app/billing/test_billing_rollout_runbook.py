# -*- coding: utf-8 -*-
"""Executable safety contracts for the production billing runbook."""
import os
from pathlib import Path
import subprocess
import time

import pytest
from sqlalchemy import create_engine

from qwenpaw.app.storage.schema import billing_usage_items


RUNBOOK = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "operations"
    / "open-api-billing-rollout.md"
)


def _candidate_boot_loops() -> list[str]:
    lines = RUNBOOK.read_text(encoding="utf-8").splitlines()
    loops: list[str] = []
    for start, line in enumerate(lines):
        if line != "for BOOT in 1 2; do":
            continue
        depth = 0
        body: list[str] = []
        for candidate in lines[start:]:
            body.append(candidate)
            stripped = candidate.strip()
            if stripped.startswith("for ") and stripped.endswith("; do"):
                depth += 1
            elif stripped == "done":
                depth -= 1
                if depth == 0:
                    break
        loops.append("\n".join(body))
    return loops


def _write_fake_command(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    path.chmod(0o755)


def _run_boot_loop(tmp_path: Path, loop: str, health: str):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    docker_log = tmp_path / "docker.log"
    _write_fake_command(
        fake_bin / "docker",
        'printf \'%s\\n\' "$*" >> "$DOCKER_LOG"\nexit 0\n',
    )
    _write_fake_command(
        fake_bin / "curl",
        '[ "$FAKE_HEALTH" = healthy ]\n',
    )
    _write_fake_command(fake_bin / "sleep", "exit 0\n")
    script = (
        "CANDIDATE_PROJECT=qwenpaw-billing-candidate\n"
        "CHANGE_DIR=/safe/change\n"
        "CANDIDATE_PORT=28088\n"
        f"{loop}\n"
    )
    started = time.monotonic()
    completed = subprocess.run(
        ["sh", "-eu", "-c", script],
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "DOCKER_LOG": str(docker_log),
            "FAKE_HEALTH": health,
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=3,
    )
    elapsed = time.monotonic() - started
    log = docker_log.read_text(encoding="utf-8") if docker_log.exists() else ""
    return completed, elapsed, log


def test_runbook_uses_real_compose_services_and_isolates_candidate_state():
    text = RUNBOOK.read_text(encoding="utf-8")

    for required in (
        "docker-compose.yml",
        "qwenpaw-saas",
        "postgres:16-alpine",
        "redis:7-alpine",
        "QWENPAW_SAAS_HOST_PORT",
        "CANDIDATE_PROJECT=qwenpaw-billing-candidate",
        "CANDIDATE_PORT=28088",
        "RELEASE_PORT=28089",
        "candidate.compose.yml",
        "qwenpaw-billing-candidate-postgres",
        "qwenpaw-billing-candidate-redis",
        "pg_restore --exit-on-error --clean --if-exists",
        "qwenpaw-release",
        "down --remove-orphans",
    ):
        assert required in text
    assert "<change-dir>" not in text
    assert "rm -rf" not in text
    candidate = text.split('cat > "$CHANGE_DIR/candidate.compose.yml"', 1)[1]
    candidate = candidate.split("YAML", 2)[1]
    assert "18088" not in candidate
    for production_volume in (
        "qwenpaw-data:",
        "qwenpaw-secrets:",
        "qwenpaw-backups:",
        "qwenpaw-postgres:",
        "qwenpaw-redis:",
    ):
        assert production_volume not in candidate
    assert (
        '-f docker-compose.yml \\\n+  -f "$CHANGE_DIR/candidate.compose.yml"'
        not in text
    )


def test_runbook_has_secret_safe_activation_and_atomic_nginx_revert():
    text = RUNBOOK.read_text(encoding="utf-8")

    for required in (
        "ADMIN_TOKEN_FILE=/run/secrets/qwenpaw-admin-token",
        'CURL_CONFIG="$(mktemp',
        'chmod 0600 "$CURL_CONFIG"',
        "trap 'rm -f -- \"$CURL_CONFIG\"' EXIT",
        'curl --config "$CURL_CONFIG"',
        "nginx -t",
        "upstream-active.conf",
        "ln -sfn",
        "mv -Tf",
        "sha256sum",
        "nginx -s reload",
        "upstream-old.conf",
        "upstream-release.conf",
    ):
        assert required in text
    assert "Authorization: Bearer <" not in text
    assert "ADMIN_TOKEN=" not in text
    assert "Authorization: Bearer ${" not in text
    assert "upstream-candidate.conf" not in text


def test_runbook_declares_redis_aof_backup_or_loss_semantics():
    text = RUNBOOK.read_text(encoding="utf-8")

    assert 'command: ["redis-server", "--appendonly", "yes"]' in text
    assert "qwenpaw-redis" in text
    assert "in-flight runtime state" in text
    assert "docker compose --profile saas stop qwenpaw-saas redis" in text
    assert "docker compose --profile saas start redis qwenpaw-saas" in text


def test_fresh_and_restored_boot_checks_complete_two_bounded_rounds(tmp_path):
    loops = _candidate_boot_loops()

    assert len(loops) == 2
    for index, loop in enumerate(loops):
        completed, elapsed, log = _run_boot_loop(
            tmp_path / str(index),
            loop,
            "healthy",
        )

        assert completed.returncode == 0, completed.stderr
        assert elapsed < 3
        commands = log.splitlines()
        starts = [command for command in commands if " run -d " in command]
        stops = [
            command for command in commands if command.startswith("stop ")
        ]
        cleanups = [
            command for command in commands if command.startswith("rm -f ")
        ]
        assert len(starts) == 2
        assert all(
            "--service-ports qwenpaw-saas" in command for command in starts
        )
        assert len(stops) == 2
        assert len(cleanups) == 2


@pytest.mark.parametrize("loop_index", [0, 1])
def test_boot_health_failure_exits_and_cleans_up_without_hanging(
    tmp_path,
    loop_index,
):
    loop = _candidate_boot_loops()[loop_index]

    completed, elapsed, log = _run_boot_loop(tmp_path, loop, "unhealthy")

    assert completed.returncode != 0
    assert elapsed < 3
    commands = log.splitlines()
    assert len([command for command in commands if " run -d " in command]) == 1
    cleanups = [
        command for command in commands if command.startswith("rm -f ")
    ]
    assert len(cleanups) == 1


def test_upgrade_token_snapshots_execute_against_usage_item_schema():
    text = RUNBOOK.read_text(encoding="utf-8")
    snapshots = []
    for name in ("before", "after"):
        snapshot = text.split(f'upgrade-{name}.tsv"', 1)[1].split("SQL", 1)[0]
        lines = snapshot.splitlines()
        start = next(
            index
            for index, line in enumerate(lines)
            if line.startswith("SELECT 'items'")
        )
        statement_lines = []
        for line in lines[start:]:
            statement_lines.append(line.strip())
            if line.endswith(";"):
                break
        snapshots.append(" ".join(statement_lines))

    assert "charged_credits" in billing_usage_items.c
    assert "captured_credits" not in billing_usage_items.c
    engine = create_engine("sqlite://")
    billing_usage_items.metadata.create_all(engine)
    try:
        with engine.connect() as connection:
            for statement in snapshots:
                row = connection.exec_driver_sql(statement).one()
                assert row == ("items", 0, 0, 0, 0)
                assert "sum(input_tokens)" in statement
                assert "sum(output_tokens)" in statement
                assert "sum(charged_credits)" in statement
    finally:
        engine.dispose()


def test_nginx_switch_script_restores_old_symlink_on_each_injected_failure(
    tmp_path,
):
    script = RUNBOOK.parent / "open-api-billing-nginx-switch.sh"
    nginx_dir = tmp_path / "nginx"
    nginx_dir.mkdir()
    old = nginx_dir / "upstream-old.conf"
    release = nginx_dir / "upstream-release.conf"
    old.write_text("old", encoding="utf-8")
    release.write_text("release", encoding="utf-8")
    active = nginx_dir / "upstream-active.conf"
    active.symlink_to(old)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "sudo"
    fake.write_text(
        "#!/bin/sh\n"
        'case "$FAIL_STEP:$*" in\n'
        "  test:*nginx*-t*) exit 11 ;;\n"
        "  reload:*nginx*-s*reload*) exit 12 ;;\n"
        "esac\n"
        'exec "$@"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    curl = fake_bin / "curl"
    curl.write_text(
        '#!/bin/sh\n[ "$FAIL_STEP" != health ]\n',
        encoding="utf-8",
    )
    curl.chmod(0o755)
    nginx = fake_bin / "nginx"
    nginx.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    nginx.chmod(0o755)

    for failure in ("test", "reload", "health"):
        active.unlink()
        active.symlink_to(old)
        completed = subprocess.run(
            [str(script), str(active), str(release), "https://health.invalid"],
            env={
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "FAIL_STEP": failure,
            },
            check=False,
        )
        assert completed.returncode != 0
        assert active.resolve() == old
