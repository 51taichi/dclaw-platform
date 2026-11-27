# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.app.storage.settings import (
    get_storage_settings,
    normalize_postgres_url,
    redact_url,
)


def test_default_settings_use_sqlite_and_memory(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")})

    assert settings.database_backend == "sqlite"
    assert settings.runtime_backend == "memory"
    assert settings.sqlite_path == tmp_path / "qwenpaw.db"
    assert settings.database_url == Path(tmp_path / "qwenpaw.db").as_uri()
    assert settings.redis_url is None


def test_postgres_backend_requires_database_url():
    with pytest.raises(RuntimeError, match="QWENPAW_DATABASE_URL"):
        get_storage_settings({"QWENPAW_DATABASE_BACKEND": "postgres"})


def test_redis_runtime_requires_redis_url():
    with pytest.raises(RuntimeError, match="QWENPAW_REDIS_URL"):
        get_storage_settings({"QWENPAW_RUNTIME_BACKEND": "redis"})


def test_postgres_url_is_normalized():
    assert (
        normalize_postgres_url("postgres://u:p@example.com:5432/qwenpaw")
        == "postgresql+psycopg://u:p@example.com:5432/qwenpaw"
    )
    assert (
        normalize_postgres_url("postgresql://u:p@example.com/qwenpaw")
        == "postgresql+psycopg://u:p@example.com/qwenpaw"
    )


def test_diagnostics_redacts_secrets():
    settings = get_storage_settings(
        {
            "QWENPAW_DATABASE_BACKEND": "postgres",
            "QWENPAW_DATABASE_URL": "postgres://user:secret@example.com/qwenpaw",
            "QWENPAW_RUNTIME_BACKEND": "redis",
            "QWENPAW_REDIS_URL": "redis://:redis-secret@example.com:6379/0",
        },
    )

    diagnostics = settings.diagnostics()

    assert "redis-secret" not in str(diagnostics)
    assert "user:secret" not in str(diagnostics)
    assert diagnostics["database_url"] == "postgresql+psycopg://user:***@example.com/qwenpaw"
    assert diagnostics["redis_url"] == "redis://:***@example.com:6379/0"


def test_redact_url_keeps_urls_without_passwords():
    assert redact_url("redis://example.com:6379/0") == "redis://example.com:6379/0"
