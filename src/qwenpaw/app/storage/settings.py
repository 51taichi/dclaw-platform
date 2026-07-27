# -*- coding: utf-8 -*-
"""Storage and runtime backend settings for SaaS deployments."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Literal
from urllib.parse import SplitResult, urlsplit, urlunsplit

from .. import db

DatabaseBackend = Literal["sqlite", "postgres"]
RuntimeBackend = Literal["memory", "redis"]


@dataclass(frozen=True)
class StorageSettings:
    """Resolved database and runtime backend settings."""

    database_backend: DatabaseBackend
    database_url: str
    sqlite_path: Path
    runtime_backend: RuntimeBackend
    redis_url: str | None

    def diagnostics(self) -> dict[str, object]:
        """Return a secret-safe representation for admin diagnostics."""
        return {
            "database_backend": self.database_backend,
            "database_url": redact_url(self.database_url),
            "sqlite_path": str(self.sqlite_path),
            "runtime_backend": self.runtime_backend,
            "redis_url": redact_url(self.redis_url) if self.redis_url else None,
            "redis_configured": bool(self.redis_url),
        }


def get_storage_settings(
    environ: Mapping[str, str] | None = None,
) -> StorageSettings:
    """Resolve storage settings from environment variables.

    Defaults are intentionally conservative: SQLite for durable data and
    in-process memory for runtime coordination.
    """
    env = os.environ if environ is None else environ
    sqlite_path = Path(env.get("QWENPAW_SQLITE_PATH") or db.DB_PATH)

    database_backend = _resolve_backend(
        env.get("QWENPAW_DATABASE_BACKEND"),
        allowed=("sqlite", "postgres"),
        default="sqlite",
        env_name="QWENPAW_DATABASE_BACKEND",
    )
    runtime_backend = _resolve_backend(
        env.get("QWENPAW_RUNTIME_BACKEND"),
        allowed=("memory", "redis"),
        default="memory",
        env_name="QWENPAW_RUNTIME_BACKEND",
    )

    if database_backend == "postgres":
        raw_database_url = _non_empty(
            env.get("QWENPAW_DATABASE_URL"),
            "QWENPAW_DATABASE_URL is required when QWENPAW_DATABASE_BACKEND=postgres",
        )
        database_url = normalize_postgres_url(raw_database_url)
    else:
        database_url = sqlite_path.as_uri()

    redis_url = _clean(env.get("QWENPAW_REDIS_URL")) or None
    if runtime_backend == "redis":
        redis_url = _non_empty(
            redis_url,
            "QWENPAW_REDIS_URL is required when QWENPAW_RUNTIME_BACKEND=redis",
        )

    return StorageSettings(
        database_backend=database_backend,  # type: ignore[arg-type]
        database_url=database_url,
        sqlite_path=sqlite_path,
        runtime_backend=runtime_backend,  # type: ignore[arg-type]
        redis_url=redis_url,
    )


def normalize_postgres_url(url: str) -> str:
    """Normalize postgres URLs to SQLAlchemy's psycopg dialect."""
    cleaned = _clean(url)
    if not cleaned:
        return ""
    if cleaned.startswith("postgres://"):
        return "postgresql+psycopg://" + cleaned[len("postgres://") :]
    if cleaned.startswith("postgresql://"):
        return "postgresql+psycopg://" + cleaned[len("postgresql://") :]
    return cleaned


def redact_url(url: str | None) -> str | None:
    """Redact password-bearing URLs for diagnostics and logs."""
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return "***"
    if not parts.netloc:
        return url

    host = parts.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parts.port is not None:
        host = f"{host}:{parts.port}"

    if parts.username is not None:
        userinfo = parts.username
        if parts.password is not None:
            userinfo = f"{userinfo}:***"
        netloc = f"{userinfo}@{host}"
    else:
        netloc = host

    return urlunsplit(
        SplitResult(
            scheme=parts.scheme,
            netloc=netloc,
            path=parts.path,
            query=parts.query,
            fragment=parts.fragment,
        ),
    )


def _resolve_backend(
    raw: str | None,
    *,
    allowed: tuple[str, ...],
    default: str,
    env_name: str,
) -> str:
    value = _clean(raw) or default
    value = value.lower()
    if value not in allowed:
        allowed_text = ", ".join(allowed)
        raise RuntimeError(f"{env_name} must be one of: {allowed_text}")
    return value


def _non_empty(value: str | None, message: str) -> str:
    cleaned = _clean(value)
    if not cleaned:
        raise RuntimeError(message)
    return cleaned


def _clean(value: str | None) -> str:
    return (value or "").strip()
