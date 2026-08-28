# -*- coding: utf-8 -*-
"""Repositories for durable Open API publications, keys, and invocations."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError as SqlAlchemyIntegrityError

from ... import db
from ..engine import get_app_engine
from ..schema import (
    create_all,
    open_api_external_apps,
    open_api_invocations,
    open_api_keys,
    open_api_publications,
)
from ..settings import get_storage_settings


class OpenApiRepository(Protocol):
    def ensure_tables(self) -> None:
        ...

    def upsert_publication(self, row: dict[str, Any]) -> dict[str, Any]:
        ...

    def list_publications(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        ...

    def get_publication(self, publication_id: str) -> dict[str, Any] | None:
        ...

    def get_publication_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        ...

    def get_enabled_publication_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        ...

    def create_external_app(self, row: dict[str, Any]) -> dict[str, Any]:
        ...

    def list_external_apps(self, owner_user_id: str | None = None) -> list[dict[str, Any]]:
        ...

    def get_external_app(self, app_id: str) -> dict[str, Any] | None:
        ...

    def create_api_key(self, row: dict[str, Any]) -> dict[str, Any]:
        ...

    def get_api_key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        ...

    def list_api_keys(
        self,
        app_id: str | None = None,
        publication_id: str | None = None,
    ) -> list[dict[str, Any]]:
        ...

    def update_api_key_status(self, key_id: str, status: str) -> dict[str, Any] | None:
        ...

    def mark_api_key_used(self, key_id: str, ip: str) -> None:
        ...

    def create_invocation(self, row: dict[str, Any]) -> dict[str, Any]:
        ...

    def get_invocation(self, invocation_id: str) -> dict[str, Any] | None:
        ...

    def update_billing_invocation(
        self,
        invocation_id: str,
        *,
        chat_id: str | None = None,
        status: str | None = None,
        status_code: int | None = None,
        latency_ms: int | None = None,
        error_summary: str | None = None,
        billing_status: str | None = None,
        billing_error_code: str | None = None,
    ) -> dict[str, Any] | None:
        ...

    def update_invocation_status(
        self,
        invocation_id: str,
        *,
        status: str,
        status_code: int,
        latency_ms: int,
        error_summary: str = "",
        token_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        ...

    def list_invocations(
        self,
        publication_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        ...


class SqlAlchemyOpenApiRepository:
    """SQLAlchemy implementation for Postgres and SQLAlchemy-backed tests."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def ensure_tables(self) -> None:
        create_all(self.engine)

    def upsert_publication(self, row: dict[str, Any]) -> dict[str, Any]:
        values = _publication_values(row)
        now = _now()
        values["updated_at"] = now
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(
                    open_api_publications.c.id,
                    open_api_publications.c.owner_user_id,
                    open_api_publications.c.knowledge_base_id,
                ).where(
                    open_api_publications.c.id == values["id"],
                ),
            ).first()
            if not existing:
                existing = conn.execute(
                    select(
                        open_api_publications.c.id,
                        open_api_publications.c.owner_user_id,
                        open_api_publications.c.knowledge_base_id,
                    ).where(
                        open_api_publications.c.public_id == values["public_id"],
                    ),
                ).first()
            if existing:
                if str(existing[1]) != str(values["owner_user_id"]):
                    raise ValueError("Open API publication owner cannot be changed")
                if (
                    str(existing[0]) == str(values["id"])
                    and str(existing[2]) != str(values["knowledge_base_id"])
                ):
                    raise ValueError(
                        "Open API publication knowledge base cannot be changed",
                    )
                values["knowledge_base_id"] = str(existing[2])
                publication_id = str(existing[0])
                update_values = dict(values)
                update_values.pop("id", None)
                conn.execute(
                    update(open_api_publications)
                    .where(open_api_publications.c.id == publication_id)
                    .values(**update_values),
                )
            else:
                publication_id = values["id"]
                values.setdefault("created_at", now)
                try:
                    conn.execute(insert(open_api_publications).values(**values))
                except SqlAlchemyIntegrityError as exc:
                    if _is_publication_public_id_conflict(exc):
                        raise ValueError(
                            "Open API publication public_id is already used",
                        ) from exc
                    raise
        row = self.get_publication(publication_id)
        if row is None:
            raise RuntimeError("failed to read open api publication after upsert")
        return row

    def list_publications(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        stmt = select(open_api_publications)
        if enabled_only:
            stmt = stmt.where(open_api_publications.c.status == "enabled")
        stmt = stmt.order_by(open_api_publications.c.updated_at.desc(), open_api_publications.c.id.asc())
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_publication_row(row) for row in rows]

    def get_publication(self, publication_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(open_api_publications).where(open_api_publications.c.id == publication_id),
            ).mappings().first()
        return _publication_row(row) if row else None

    def get_publication_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(open_api_publications).where(open_api_publications.c.public_id == public_id),
            ).mappings().first()
        return _publication_row(row) if row else None

    def get_enabled_publication_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(open_api_publications).where(
                    open_api_publications.c.public_id == public_id,
                    open_api_publications.c.status == "enabled",
                ),
            ).mappings().first()
        return _publication_row(row) if row else None

    def create_external_app(self, row: dict[str, Any]) -> dict[str, Any]:
        values = _external_app_values(row)
        with self.engine.begin() as conn:
            conn.execute(insert(open_api_external_apps).values(**values))
        created = self.get_external_app(values["id"])
        if created is None:
            raise RuntimeError("failed to read open api external app after create")
        return created

    def list_external_apps(self, owner_user_id: str | None = None) -> list[dict[str, Any]]:
        stmt = select(open_api_external_apps)
        if owner_user_id is not None:
            stmt = stmt.where(open_api_external_apps.c.owner_user_id == owner_user_id)
        stmt = stmt.order_by(open_api_external_apps.c.created_at.desc(), open_api_external_apps.c.id.asc())
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_external_app_row(row) for row in rows]

    def get_external_app(self, app_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(open_api_external_apps).where(open_api_external_apps.c.id == app_id),
            ).mappings().first()
        return _external_app_row(row) if row else None

    def create_api_key(self, row: dict[str, Any]) -> dict[str, Any]:
        values = _api_key_values(row)
        with self.engine.begin() as conn:
            conn.execute(insert(open_api_keys).values(**values))
        created = self._get_api_key(values["id"])
        if created is None:
            raise RuntimeError("failed to read open api key after create")
        return created

    def get_api_key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(open_api_keys).where(open_api_keys.c.key_hash == key_hash),
            ).mappings().first()
        return _api_key_row(row) if row else None

    def list_api_keys(
        self,
        app_id: str | None = None,
        publication_id: str | None = None,
    ) -> list[dict[str, Any]]:
        stmt = select(open_api_keys)
        if app_id is not None:
            stmt = stmt.where(open_api_keys.c.app_id == app_id)
        if publication_id is not None:
            stmt = stmt.where(open_api_keys.c.publication_id == publication_id)
        stmt = stmt.order_by(open_api_keys.c.created_at.desc(), open_api_keys.c.id.asc())
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_api_key_row(row) for row in rows]

    def update_api_key_status(self, key_id: str, status: str) -> dict[str, Any] | None:
        _validate_api_key_status(status)
        with self.engine.begin() as conn:
            conn.execute(
                update(open_api_keys)
                .where(open_api_keys.c.id == key_id)
                .values(status=status, updated_at=_now()),
            )
        return self._get_api_key(key_id)

    def mark_api_key_used(self, key_id: str, ip: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(open_api_keys)
                .where(open_api_keys.c.id == key_id)
                .values(last_used_at=_now(), last_used_ip=ip, updated_at=_now()),
            )

    def create_invocation(self, row: dict[str, Any]) -> dict[str, Any]:
        values = _invocation_values(row)
        with self.engine.begin() as conn:
            conn.execute(insert(open_api_invocations).values(**values))
        created = self._get_invocation(values["id"])
        if created is None:
            raise RuntimeError("failed to read open api invocation after create")
        return created

    def get_invocation(self, invocation_id: str) -> dict[str, Any] | None:
        return self._get_invocation(invocation_id)

    def update_billing_invocation(
        self,
        invocation_id: str,
        *,
        chat_id: str | None = None,
        status: str | None = None,
        status_code: int | None = None,
        latency_ms: int | None = None,
        error_summary: str | None = None,
        billing_status: str | None = None,
        billing_error_code: str | None = None,
    ) -> dict[str, Any] | None:
        values: dict[str, Any] = {}
        for key, value in (
            ("chat_id", chat_id),
            ("status", status),
            ("status_code", status_code),
            ("latency_ms", latency_ms),
            ("error_summary", error_summary),
            ("billing_status", billing_status),
            ("billing_error_code", billing_error_code),
        ):
            if value is not None:
                values[key] = value
        if values:
            with self.engine.begin() as conn:
                conn.execute(
                    update(open_api_invocations)
                    .where(open_api_invocations.c.id == invocation_id)
                    .values(**values),
                )
        return self._get_invocation(invocation_id)

    def update_invocation_status(
        self,
        invocation_id: str,
        *,
        status: str,
        status_code: int,
        latency_ms: int,
        error_summary: str = "",
        token_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        values: dict[str, Any] = {
            "status": status,
            "status_code": status_code,
            "latency_ms": int(latency_ms),
            "error_summary": error_summary,
        }
        if token_summary is not None:
            values["token_summary"] = _json_text("token_summary", token_summary, dict)
        with self.engine.begin() as conn:
            conn.execute(
                update(open_api_invocations)
                .where(open_api_invocations.c.id == invocation_id)
                .values(**values),
            )
        return self._get_invocation(invocation_id)

    def list_invocations(
        self,
        publication_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        stmt = select(open_api_invocations)
        if publication_id is not None:
            stmt = stmt.where(open_api_invocations.c.publication_id == publication_id)
        stmt = stmt.order_by(
            open_api_invocations.c.created_at.desc(),
            open_api_invocations.c.id.desc(),
        ).limit(limit).offset(offset)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_invocation_row(row) for row in rows]

    def _get_api_key(self, key_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(open_api_keys).where(open_api_keys.c.id == key_id),
            ).mappings().first()
        return _api_key_row(row) if row else None

    def _get_invocation(self, invocation_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(open_api_invocations).where(open_api_invocations.c.id == invocation_id),
            ).mappings().first()
        return _invocation_row(row) if row else None


class SqliteOpenApiRepository:
    """SQLite compatibility implementation using the existing sqlite3 module."""

    def ensure_tables(self) -> None:
        db.init_db()

    def upsert_publication(self, row: dict[str, Any]) -> dict[str, Any]:
        values = _publication_values(row)
        conn = db.get_db()
        existing = conn.execute(
            """
            SELECT id, owner_user_id, knowledge_base_id FROM open_api_publications
            WHERE id = ? OR public_id = ?
            LIMIT 1
            """,
            (values["id"], values["public_id"]),
        ).fetchone()
        if existing:
            if str(existing["owner_user_id"]) != str(values["owner_user_id"]):
                raise ValueError("Open API publication owner cannot be changed")
            if (
                str(existing["id"]) == str(values["id"])
                and str(existing["knowledge_base_id"])
                != str(values["knowledge_base_id"])
            ):
                raise ValueError(
                    "Open API publication knowledge base cannot be changed",
                )
            values["knowledge_base_id"] = str(existing["knowledge_base_id"])
            publication_id = str(existing["id"])
            conn.execute(
                """
                UPDATE open_api_publications
                SET public_id = ?, target_type = ?, target_id = ?, owner_user_id = ?,
                    bound_user_id = ?, knowledge_base_id = ?, name = ?,
                    description = ?, status = ?, allowed_scopes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    values["public_id"],
                    values["target_type"],
                    values["target_id"],
                    values["owner_user_id"],
                    values["bound_user_id"],
                    values["knowledge_base_id"],
                    values["name"],
                    values.get("description", ""),
                    values.get("status", "enabled"),
                    values.get("allowed_scopes", "[]"),
                    publication_id,
                ),
            )
        else:
            publication_id = values["id"]
            try:
                conn.execute(
                    """
                    INSERT INTO open_api_publications (
                        id, public_id, target_type, target_id, owner_user_id,
                        bound_user_id, knowledge_base_id, name,
                        description, status, allowed_scopes, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        values["id"],
                        values["public_id"],
                        values["target_type"],
                        values["target_id"],
                        values["owner_user_id"],
                        values["bound_user_id"],
                        values["knowledge_base_id"],
                        values["name"],
                        values.get("description", ""),
                        values.get("status", "enabled"),
                        values.get("allowed_scopes", "[]"),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if _is_publication_public_id_conflict(exc):
                    raise ValueError(
                        "Open API publication public_id is already used",
                    ) from exc
                raise
        conn.commit()
        created = self.get_publication(publication_id)
        if created is None:
            raise RuntimeError("failed to read open api publication after upsert")
        return created

    def list_publications(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM open_api_publications"
        params: tuple[Any, ...] = ()
        if enabled_only:
            sql += " WHERE status = ?"
            params = ("enabled",)
        sql += " ORDER BY updated_at DESC, id ASC"
        rows = db.get_db().execute(sql, params).fetchall()
        return [_publication_row(dict(row)) for row in rows]

    def get_publication(self, publication_id: str) -> dict[str, Any] | None:
        row = db.get_db().execute(
            "SELECT * FROM open_api_publications WHERE id = ?",
            (publication_id,),
        ).fetchone()
        return _publication_row(dict(row)) if row else None

    def get_publication_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        row = db.get_db().execute(
            "SELECT * FROM open_api_publications WHERE public_id = ?",
            (public_id,),
        ).fetchone()
        return _publication_row(dict(row)) if row else None

    def get_enabled_publication_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        row = db.get_db().execute(
            "SELECT * FROM open_api_publications WHERE public_id = ? AND status = 'enabled'",
            (public_id,),
        ).fetchone()
        return _publication_row(dict(row)) if row else None

    def create_external_app(self, row: dict[str, Any]) -> dict[str, Any]:
        values = _external_app_values(row)
        db.get_db().execute(
            """
            INSERT INTO open_api_external_apps (
                id, owner_user_id, name, status, ip_allowlist, quota_policy
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                values["id"],
                values["owner_user_id"],
                values["name"],
                values.get("status", "enabled"),
                values.get("ip_allowlist", "[]"),
                values.get("quota_policy", "{}"),
            ),
        )
        db.get_db().commit()
        created = self.get_external_app(values["id"])
        if created is None:
            raise RuntimeError("failed to read open api external app after create")
        return created

    def list_external_apps(self, owner_user_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM open_api_external_apps"
        params: tuple[Any, ...] = ()
        if owner_user_id is not None:
            sql += " WHERE owner_user_id = ?"
            params = (owner_user_id,)
        sql += " ORDER BY created_at DESC, id ASC"
        rows = db.get_db().execute(sql, params).fetchall()
        return [_external_app_row(dict(row)) for row in rows]

    def get_external_app(self, app_id: str) -> dict[str, Any] | None:
        row = db.get_db().execute(
            "SELECT * FROM open_api_external_apps WHERE id = ?",
            (app_id,),
        ).fetchone()
        return _external_app_row(dict(row)) if row else None

    def create_api_key(self, row: dict[str, Any]) -> dict[str, Any]:
        values = _api_key_values(row)
        db.get_db().execute(
            """
            INSERT INTO open_api_keys (
                id, app_id, publication_id, key_hash, key_prefix, key_suffix,
                scopes, status, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values["id"],
                values["app_id"],
                values["publication_id"],
                values["key_hash"],
                values["key_prefix"],
                values["key_suffix"],
                values.get("scopes", "[]"),
                values.get("status", "active"),
                values.get("expires_at"),
            ),
        )
        db.get_db().commit()
        created = self._get_api_key(values["id"])
        if created is None:
            raise RuntimeError("failed to read open api key after create")
        return created

    def get_api_key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        row = db.get_db().execute(
            "SELECT * FROM open_api_keys WHERE key_hash = ?",
            (key_hash,),
        ).fetchone()
        return _api_key_row(dict(row)) if row else None

    def list_api_keys(
        self,
        app_id: str | None = None,
        publication_id: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM open_api_keys"
        clauses: list[str] = []
        params: list[Any] = []
        if app_id is not None:
            clauses.append("app_id = ?")
            params.append(app_id)
        if publication_id is not None:
            clauses.append("publication_id = ?")
            params.append(publication_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, id ASC"
        rows = db.get_db().execute(sql, tuple(params)).fetchall()
        return [_api_key_row(dict(row)) for row in rows]

    def update_api_key_status(self, key_id: str, status: str) -> dict[str, Any] | None:
        _validate_api_key_status(status)
        db.get_db().execute(
            """
            UPDATE open_api_keys
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, key_id),
        )
        db.get_db().commit()
        return self._get_api_key(key_id)

    def mark_api_key_used(self, key_id: str, ip: str) -> None:
        db.get_db().execute(
            """
            UPDATE open_api_keys
            SET last_used_at = CURRENT_TIMESTAMP, last_used_ip = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (ip, key_id),
        )
        db.get_db().commit()

    def create_invocation(self, row: dict[str, Any]) -> dict[str, Any]:
        values = _invocation_values(row)
        db.get_db().execute(
            """
            INSERT INTO open_api_invocations (
                id, app_id, publication_id, api_key_id, target_type, target_id,
                chat_id, external_session_id, external_user_id, status,
                status_code, latency_ms, token_summary, error_summary
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                values["id"],
                values["app_id"],
                values["publication_id"],
                values["api_key_id"],
                values["target_type"],
                values["target_id"],
                values.get("chat_id"),
                values.get("external_session_id"),
                values.get("external_user_id"),
                values["status"],
                values.get("status_code"),
                int(values.get("latency_ms", 0) or 0),
                values.get("token_summary", "{}"),
                values.get("error_summary"),
            ),
        )
        db.get_db().commit()
        created = self._get_invocation(values["id"])
        if created is None:
            raise RuntimeError("failed to read open api invocation after create")
        return created

    def get_invocation(self, invocation_id: str) -> dict[str, Any] | None:
        return self._get_invocation(invocation_id)

    def update_billing_invocation(
        self,
        invocation_id: str,
        *,
        chat_id: str | None = None,
        status: str | None = None,
        status_code: int | None = None,
        latency_ms: int | None = None,
        error_summary: str | None = None,
        billing_status: str | None = None,
        billing_error_code: str | None = None,
    ) -> dict[str, Any] | None:
        values: list[Any] = []
        assignments: list[str] = []
        for key, value in (
            ("chat_id", chat_id),
            ("status", status),
            ("status_code", status_code),
            ("latency_ms", latency_ms),
            ("error_summary", error_summary),
            ("billing_status", billing_status),
            ("billing_error_code", billing_error_code),
        ):
            if value is not None:
                assignments.append(f"{key} = ?")
                values.append(value)
        if assignments:
            values.append(invocation_id)
            db.get_db().execute(
                "UPDATE open_api_invocations SET "
                + ", ".join(assignments)
                + " WHERE id = ?",
                tuple(values),
            )
            db.get_db().commit()
        return self._get_invocation(invocation_id)

    def update_invocation_status(
        self,
        invocation_id: str,
        *,
        status: str,
        status_code: int,
        latency_ms: int,
        error_summary: str = "",
        token_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        values = [
            status,
            int(latency_ms),
            status_code,
            error_summary,
        ]
        sql = """
            UPDATE open_api_invocations
            SET status = ?, latency_ms = ?, status_code = ?, error_summary = ?
        """
        if token_summary is not None:
            sql += ", token_summary = ?"
            values.append(_json_text("token_summary", token_summary, dict))
        sql += " WHERE id = ?"
        values.append(invocation_id)
        db.get_db().execute(sql, tuple(values))
        db.get_db().commit()
        return self._get_invocation(invocation_id)

    def list_invocations(
        self,
        publication_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM open_api_invocations"
        params: list[Any] = []
        if publication_id is not None:
            sql += " WHERE publication_id = ?"
            params.append(publication_id)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = db.get_db().execute(sql, tuple(params)).fetchall()
        return [_invocation_row(dict(row)) for row in rows]

    def _get_api_key(self, key_id: str) -> dict[str, Any] | None:
        row = db.get_db().execute(
            "SELECT * FROM open_api_keys WHERE id = ?",
            (key_id,),
        ).fetchone()
        return _api_key_row(dict(row)) if row else None

    def _get_invocation(self, invocation_id: str) -> dict[str, Any] | None:
        row = db.get_db().execute(
            "SELECT * FROM open_api_invocations WHERE id = ?",
            (invocation_id,),
        ).fetchone()
        return _invocation_row(dict(row)) if row else None


def get_open_api_repository() -> OpenApiRepository:
    settings = get_storage_settings()
    if settings.database_backend == "postgres":
        return SqlAlchemyOpenApiRepository(get_app_engine())
    return SqliteOpenApiRepository()


def _publication_values(row: dict[str, Any]) -> dict[str, Any]:
    values = dict(row)
    values.setdefault("bound_user_id", values.get("owner_user_id"))
    values.setdefault("knowledge_base_id", f"openapi-{values['id']}")
    values.setdefault("description", "")
    values.setdefault("status", "enabled")
    values["allowed_scopes"] = _json_text(
        "allowed_scopes",
        values.get("allowed_scopes"),
        list,
    )
    return values


def _external_app_values(row: dict[str, Any]) -> dict[str, Any]:
    values = dict(row)
    values.setdefault("status", "enabled")
    values["ip_allowlist"] = _json_text("ip_allowlist", values.get("ip_allowlist"), list)
    values["quota_policy"] = _json_text("quota_policy", values.get("quota_policy"), dict)
    return values


def _api_key_values(row: dict[str, Any]) -> dict[str, Any]:
    values = dict(row)
    values.setdefault("status", "active")
    _validate_api_key_status(str(values["status"]))
    values["scopes"] = _json_text("scopes", values.get("scopes"), list)
    return values


def _invocation_values(row: dict[str, Any]) -> dict[str, Any]:
    values = dict(row)
    values.setdefault("latency_ms", 0)
    values["token_summary"] = _json_text(
        "token_summary",
        values.get("token_summary"),
        dict,
    )
    return values


def _publication_row(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["bound_user_id"] = str(
        result.get("bound_user_id") or result.get("owner_user_id") or "",
    )
    result["allowed_scopes"] = _json_value(
        "allowed_scopes",
        result.get("allowed_scopes"),
        list,
    )
    return result


def _external_app_row(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["ip_allowlist"] = _json_value("ip_allowlist", result.get("ip_allowlist"), list)
    result["quota_policy"] = _json_value("quota_policy", result.get("quota_policy"), dict)
    return result


def _api_key_row(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["scopes"] = _json_value("scopes", result.get("scopes"), list)
    return result


def _invocation_row(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["token_summary"] = _json_value(
        "token_summary",
        result.get("token_summary"),
        dict,
    )
    result["latency_ms"] = int(result.get("latency_ms") or 0)
    return result


def _json_text(field_name: str, value: Any, expected_type: type) -> str:
    if value is None:
        value = [] if expected_type is list else {}
    if isinstance(value, str):
        parsed = _json_value(field_name, value, expected_type)
        return json.dumps(parsed, ensure_ascii=False)
    if not isinstance(value, expected_type):
        raise ValueError(f"{field_name} must be a {expected_type.__name__}")
    return json.dumps(value, ensure_ascii=False)


def _json_value(field_name: str, value: Any, expected_type: type) -> Any:
    if value is None or value == "":
        return [] if expected_type is list else {}
    if isinstance(value, (dict, list)):
        if isinstance(value, expected_type):
            return value
        raise ValueError(f"{field_name} must be a {expected_type.__name__}")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} must be valid JSON") from exc
        if isinstance(parsed, expected_type):
            return parsed
        raise ValueError(f"{field_name} must be a JSON {expected_type.__name__}")
    raise ValueError(f"{field_name} must be a {expected_type.__name__}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_publication_public_id_conflict(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "open_api_publications" in text
        and "public_id" in text
        and ("unique" in text or "duplicate" in text)
    )


def _validate_api_key_status(status: str) -> None:
    if status not in {"active", "revoked"}:
        raise ValueError("api key status must be active or revoked")
