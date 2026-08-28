# -*- coding: utf-8 -*-
"""Executable safety contracts for the production billing runbook."""
import os
from pathlib import Path
import subprocess


RUNBOOK = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "operations"
    / "open-api-billing-rollout.md"
)


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
