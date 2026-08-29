from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = REPO_ROOT / "docs" / "operations" / "dclaw-container-release.md"


def test_runbook_documents_one_command_for_all_change_types() -> None:
    text = RUNBOOK.read_text()

    assert text.count("/opt/dclaw-deploy/update.sh") >= 3
    assert "server-only" in text
    assert "client-only" in text
    assert "server and client" in text


def test_runbook_documents_disconnect_safe_execution_and_420_second_gate() -> None:
    text = RUNBOOK.read_text()

    assert "nohup sudo /opt/dclaw-deploy/update.sh" in text
    assert "420 seconds" in text
    assert "/opt/dclaw-deploy/logs/" in text


def test_runbook_documents_minimal_github_and_ghcr_credentials() -> None:
    text = RUNBOOK.read_text()

    assert "DCLAW_CLIENT_READ_TOKEN" in text
    assert "DCLAW_SERVER_DISPATCH_TOKEN" in text
    assert "read:packages" in text
    assert "docker login ghcr.io --username 51taichi --password-stdin" in text


def test_runbook_never_recommends_destructive_cleanup_or_automatic_db_restore() -> None:
    text = RUNBOOK.read_text()

    assert "docker system prune" not in text
    assert "docker volume rm" not in text
    assert "ordinary rollback never restores PostgreSQL" in text


def test_runbook_preserves_current_production_resource_names() -> None:
    text = RUNBOOK.read_text()

    for value in (
        "dclaw-postgres",
        "dclaw-redis",
        "dclaw-net",
        "dclaw-data",
        "dclaw-secrets",
        "dclaw-backups",
        "127.0.0.1:18088",
        "https://dclaw.deepmega.cn",
    ):
        assert value in text
