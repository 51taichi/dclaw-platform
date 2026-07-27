# -*- coding: utf-8 -*-
"""Repositories for user connections and installed capabilities."""
from __future__ import annotations

import json
from typing import Any, Protocol

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from ... import db
from ..engine import get_app_engine
from ..schema import capability_registry, user_capabilities, user_connections
from ..settings import get_storage_settings


class CapabilityRepository(Protocol):
    def add_or_update_connection(
        self,
        user_id: int,
        connector_key: str,
        oauth_tokens: dict[str, Any] | None = None,
        custom_envs: dict[str, Any] | None = None,
    ) -> int:
        ...

    def get_user_connections(self, user_id: int) -> list[dict[str, Any]]:
        ...

    def disable_connection(self, user_id: int, connector_key: str) -> None:
        ...

    def list_enabled_user_capabilities(self, user_id: int) -> list[dict[str, Any]]:
        ...


class SqlAlchemyCapabilityRepository:
    """SQLAlchemy implementation for Postgres and SQLAlchemy-backed tests."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def add_or_update_connection(
        self,
        user_id: int,
        connector_key: str,
        oauth_tokens: dict[str, Any] | None = None,
        custom_envs: dict[str, Any] | None = None,
    ) -> int:
        oauth_str = _json_or_none(oauth_tokens)
        envs_str = _json_or_none(custom_envs)
        with self.engine.begin() as conn:
            row = conn.execute(
                select(user_connections.c.id).where(
                    user_connections.c.user_id == user_id,
                    user_connections.c.connector_key == connector_key,
                ),
            ).first()
            if row:
                conn_id = int(row[0])
                conn.execute(
                    update(user_connections)
                    .where(user_connections.c.id == conn_id)
                    .values(
                        oauth_tokens=oauth_str,
                        custom_envs=envs_str,
                        is_active=True,
                    ),
                )
                return conn_id

            result = conn.execute(
                insert(user_connections).values(
                    user_id=user_id,
                    connector_key=connector_key,
                    oauth_tokens=oauth_str,
                    custom_envs=envs_str,
                ),
            )
            return int(result.inserted_primary_key[0])

    def get_user_connections(self, user_id: int) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(
                    user_connections.c.connector_key,
                    user_connections.c.oauth_tokens,
                    user_connections.c.custom_envs,
                ).where(
                    user_connections.c.user_id == user_id,
                    user_connections.c.is_active.is_(True),
                ),
            ).mappings().all()
        return [_connection_row(row) for row in rows]

    def disable_connection(self, user_id: int, connector_key: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(user_connections)
                .where(
                    user_connections.c.user_id == user_id,
                    user_connections.c.connector_key == connector_key,
                )
                .values(is_active=False),
            )

    def list_enabled_user_capabilities(self, user_id: int) -> list[dict[str, Any]]:
        stmt = (
            select(
                capability_registry.c.type,
                capability_registry.c.manifest,
                user_capabilities.c.credentials,
                user_capabilities.c.preferences,
            )
            .select_from(
                user_capabilities.join(
                    capability_registry,
                    user_capabilities.c.capability_id == capability_registry.c.id,
                ),
            )
            .where(
                user_capabilities.c.user_id == user_id,
                user_capabilities.c.enabled.is_(True),
            )
            .order_by(
                user_capabilities.c.subscribed_at.asc(),
                user_capabilities.c.capability_id.asc(),
            )
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_capability_row(row) for row in rows]


class SqliteCapabilityRepository:
    """SQLite compatibility implementation using the existing sqlite3 module."""

    def add_or_update_connection(
        self,
        user_id: int,
        connector_key: str,
        oauth_tokens: dict[str, Any] | None = None,
        custom_envs: dict[str, Any] | None = None,
    ) -> int:
        conn = db.get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM user_connections WHERE user_id = ? AND connector_key = ?",
            (user_id, connector_key),
        )
        row = cursor.fetchone()
        oauth_str = _json_or_none(oauth_tokens)
        envs_str = _json_or_none(custom_envs)
        if row:
            conn_id = int(row["id"])
            cursor.execute(
                """
                UPDATE user_connections
                SET oauth_tokens = ?, custom_envs = ?, is_active = 1
                WHERE id = ?
                """,
                (oauth_str, envs_str, conn_id),
            )
        else:
            cursor.execute(
                """
                INSERT INTO user_connections (
                    user_id, connector_key, oauth_tokens, custom_envs
                )
                VALUES (?, ?, ?, ?)
                """,
                (user_id, connector_key, oauth_str, envs_str),
            )
            conn_id = int(cursor.lastrowid)
        conn.commit()
        return conn_id

    def get_user_connections(self, user_id: int) -> list[dict[str, Any]]:
        rows = db.get_db().execute(
            """
            SELECT connector_key, oauth_tokens, custom_envs
            FROM user_connections
            WHERE user_id = ? AND is_active = 1
            """,
            (user_id,),
        ).fetchall()
        return [_connection_row(dict(row)) for row in rows]

    def disable_connection(self, user_id: int, connector_key: str) -> None:
        conn = db.get_db()
        conn.execute(
            """
            UPDATE user_connections
            SET is_active = 0
            WHERE user_id = ? AND connector_key = ?
            """,
            (user_id, connector_key),
        )
        conn.commit()

    def list_enabled_user_capabilities(self, user_id: int) -> list[dict[str, Any]]:
        rows = db.get_db().execute(
            """
            SELECT cr.type, cr.manifest, uc.credentials, uc.preferences
            FROM user_capabilities uc
            JOIN capability_registry cr ON uc.capability_id = cr.id
            WHERE uc.user_id = ? AND uc.enabled = 1
            ORDER BY uc.subscribed_at ASC, uc.capability_id ASC
            """,
            (user_id,),
        ).fetchall()
        return [_capability_row(dict(row)) for row in rows]


def get_capability_repository() -> CapabilityRepository:
    settings = get_storage_settings()
    if settings.database_backend == "postgres":
        return SqlAlchemyCapabilityRepository(get_app_engine())
    return SqliteCapabilityRepository()


def _json_or_none(value: dict[str, Any] | None) -> str | None:
    return json.dumps(value, ensure_ascii=False) if value else None


def _loads_dict(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _connection_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "connector_key": row["connector_key"],
        "oauth_tokens": _loads_dict(row.get("oauth_tokens")),
        "custom_envs": _loads_dict(row.get("custom_envs")),
    }


def _capability_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": row["type"],
        "manifest": _loads_dict(row.get("manifest")),
        "credentials": _loads_dict(row.get("credentials")),
        "preferences": _loads_dict(row.get("preferences")),
    }
