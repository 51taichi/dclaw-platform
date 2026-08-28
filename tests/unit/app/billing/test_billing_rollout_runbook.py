# -*- coding: utf-8 -*-
"""Executable safety contracts for the production billing runbook."""
from pathlib import Path


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


def test_runbook_has_secret_safe_activation_and_atomic_nginx_revert():
    text = RUNBOOK.read_text(encoding="utf-8")

    for required in (
        "ADMIN_TOKEN_FILE=/run/secrets/qwenpaw-admin-token",
        'ADMIN_TOKEN="$(<"$ADMIN_TOKEN_FILE")"',
        "unset ADMIN_TOKEN",
        "Authorization: Bearer ${ADMIN_TOKEN}",
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
    assert "upstream-candidate.conf" not in text


def test_runbook_declares_redis_aof_backup_or_loss_semantics():
    text = RUNBOOK.read_text(encoding="utf-8")

    assert 'command: ["redis-server", "--appendonly", "yes"]' in text
    assert "qwenpaw-redis" in text
    assert "in-flight runtime state" in text
    assert "docker compose --profile saas stop qwenpaw-saas redis" in text
    assert "docker compose --profile saas start redis qwenpaw-saas" in text
