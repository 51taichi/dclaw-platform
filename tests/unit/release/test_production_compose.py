from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE = REPO_ROOT / "deploy" / "production" / "compose.production.yml"
EXAMPLE_ENV = REPO_ROOT / "deploy" / "production" / "production.env.example"


def _compose() -> dict[str, object]:
    return yaml.safe_load(COMPOSE.read_text())


def test_production_compose_owns_only_application_container() -> None:
    rendered = _compose()

    assert set(rendered["services"]) == {"dclaw"}
    app = rendered["services"]["dclaw"]
    assert app["image"] == "${DCLAW_IMAGE:?DCLAW_IMAGE is required}"
    assert app["container_name"] == "dclaw"
    assert app["ports"] == ["127.0.0.1:18088:8088"]
    assert app["restart"] == "unless-stopped"


def test_application_uses_exact_existing_mounts_and_network() -> None:
    rendered = _compose()
    app = rendered["services"]["dclaw"]

    assert app["volumes"] == [
        "dclaw-data:/app/working",
        "dclaw-secrets:/app/working.secret",
        "dclaw-backups:/app/working.backups",
    ]
    assert app["networks"] == ["dclaw-net"]


def test_all_runtime_resources_are_external() -> None:
    rendered = _compose()

    assert rendered["networks"]["dclaw-net"] == {
        "external": True,
        "name": "dclaw-net",
    }
    assert rendered["volumes"] == {
        "dclaw-data": {"external": True, "name": "dclaw-data"},
        "dclaw-secrets": {"external": True, "name": "dclaw-secrets"},
        "dclaw-backups": {"external": True, "name": "dclaw-backups"},
    }


def test_compose_does_not_define_database_or_redis() -> None:
    text = COMPOSE.read_text()

    assert "dclaw-postgres:" not in text
    assert "dclaw-redis:" not in text


def test_example_env_contains_no_credentials() -> None:
    text = EXAMPLE_ENV.read_text()

    assert "postgresql+" not in text
    assert "TOKEN=" not in text
    assert "PASSWORD=" not in text
    assert "QWENPAW_DATABASE_URL=" not in text
