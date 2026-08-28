# -*- coding: utf-8 -*-
"""Repositories for durable Open API publications, keys, and invocations."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import Interval, func, insert, literal, or_, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError as SqlAlchemyIntegrityError

from ... import db
from ...billing.execution import OpenApiExecutionFence
from ..engine import get_app_engine
from ..schema import (
    billing_usage_items,
    billing_usage_orders,
    create_all,
    open_api_external_apps,
    open_api_invocations,
    open_api_keys,
    open_api_publications,
)
from ..settings import get_storage_settings


class _EmptyFinalizationLost(RuntimeError):
    """Roll back an empty-order transition if its fence stops matching."""


class OpenApiRepository(Protocol):  # pylint: disable=too-many-public-methods
    def ensure_tables(self) -> None:
        ...

    def upsert_publication(self, row: dict[str, Any]) -> dict[str, Any]:
        ...

    def list_publications(
        self, enabled_only: bool = False
    ) -> list[dict[str, Any]]:
        ...

    def get_publication(self, publication_id: str) -> dict[str, Any] | None:
        ...

    def get_publication_by_public_id(
        self, public_id: str
    ) -> dict[str, Any] | None:
        ...

    def get_enabled_publication_by_public_id(
        self, public_id: str
    ) -> dict[str, Any] | None:
        ...

    def create_external_app(self, row: dict[str, Any]) -> dict[str, Any]:
        ...

    def list_external_apps(
        self, owner_user_id: str | None = None
    ) -> list[dict[str, Any]]:
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

    def update_api_key_status(
        self, key_id: str, status: str
    ) -> dict[str, Any] | None:
        ...

    def mark_api_key_used(self, key_id: str, ip: str) -> None:
        ...

    def create_invocation(self, row: dict[str, Any]) -> dict[str, Any]:
        ...

    def get_invocation(self, invocation_id: str) -> dict[str, Any] | None:
        ...

    def claim_invocation_execution(
        self,
        invocation_id: str,
        owner_token: str,
        *,
        lease_seconds: float,
    ) -> OpenApiExecutionFence | None:
        ...

    def renew_invocation_execution(
        self,
        invocation_id: str,
        fence: OpenApiExecutionFence,
        *,
        lease_seconds: float,
    ) -> bool:
        ...

    def takeover_invocation_execution(
        self,
        invocation_id: str,
        owner_token: str,
        *,
        lease_seconds: float,
    ) -> OpenApiExecutionFence | None:
        ...

    def finalize_invocation_execution(
        self,
        invocation_id: str,
        fence: OpenApiExecutionFence,
        *,
        status: str,
        status_code: int,
        error_summary: str,
        terminal_event: dict[str, Any],
        latency_ms: int | None = None,
        billing_status: str | None = None,
        billing_error_code: str | None = None,
        expert_team_run_id: str | None = None,
    ) -> dict[str, Any] | None:
        ...

    def finalize_empty_invocation_execution(
        self,
        invocation_id: str,
        usage_order_id: str,
        fence: OpenApiExecutionFence,
        *,
        status: str,
        status_code: int,
        error_summary: str,
        terminal_event: dict[str, Any],
        latency_ms: int | None = None,
        billing_error_code: str | None = None,
        expert_team_run_id: str | None = None,
    ) -> dict[str, Any] | None:
        ...

    def update_claimed_invocation(
        self,
        invocation_id: str,
        fence: OpenApiExecutionFence,
        **values: Any,
    ) -> dict[str, Any] | None:
        ...

    def repair_invocation_from_terminal(
        self,
        invocation_id: str,
        *,
        terminal_event: dict[str, Any],
        status: str,
        status_code: int,
        error_summary: str,
        billing_error_code: str | None = None,
    ) -> bool:
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
        expert_team_run_id: str | None = None,
        terminal_event: dict[str, Any] | None = None,
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


class SqlAlchemyOpenApiRepository:  # pylint: disable=too-many-public-methods
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
                        open_api_publications.c.public_id
                        == values["public_id"],
                    ),
                ).first()
            if existing:
                if str(existing[1]) != str(values["owner_user_id"]):
                    raise ValueError(
                        "Open API publication owner cannot be changed"
                    )
                if str(existing[0]) == str(values["id"]) and str(
                    existing[2]
                ) != str(values["knowledge_base_id"]):
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
                    conn.execute(
                        insert(open_api_publications).values(**values)
                    )
                except SqlAlchemyIntegrityError as exc:
                    if _is_publication_public_id_conflict(exc):
                        raise ValueError(
                            "Open API publication public_id is already used",
                        ) from exc
                    raise
        row = self.get_publication(publication_id)
        if row is None:
            raise RuntimeError(
                "failed to read open api publication after upsert"
            )
        return row

    def list_publications(
        self, enabled_only: bool = False
    ) -> list[dict[str, Any]]:
        stmt = select(open_api_publications)
        if enabled_only:
            stmt = stmt.where(open_api_publications.c.status == "enabled")
        stmt = stmt.order_by(
            open_api_publications.c.updated_at.desc(),
            open_api_publications.c.id.asc(),
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_publication_row(row) for row in rows]

    def get_publication(self, publication_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(open_api_publications).where(
                        open_api_publications.c.id == publication_id
                    ),
                )
                .mappings()
                .first()
            )
        return _publication_row(row) if row else None

    def get_publication_by_public_id(
        self, public_id: str
    ) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(open_api_publications).where(
                        open_api_publications.c.public_id == public_id
                    ),
                )
                .mappings()
                .first()
            )
        return _publication_row(row) if row else None

    def get_enabled_publication_by_public_id(
        self, public_id: str
    ) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(open_api_publications).where(
                        open_api_publications.c.public_id == public_id,
                        open_api_publications.c.status == "enabled",
                    ),
                )
                .mappings()
                .first()
            )
        return _publication_row(row) if row else None

    def create_external_app(self, row: dict[str, Any]) -> dict[str, Any]:
        values = _external_app_values(row)
        with self.engine.begin() as conn:
            conn.execute(insert(open_api_external_apps).values(**values))
        created = self.get_external_app(values["id"])
        if created is None:
            raise RuntimeError(
                "failed to read open api external app after create"
            )
        return created

    def list_external_apps(
        self, owner_user_id: str | None = None
    ) -> list[dict[str, Any]]:
        stmt = select(open_api_external_apps)
        if owner_user_id is not None:
            stmt = stmt.where(
                open_api_external_apps.c.owner_user_id == owner_user_id
            )
        stmt = stmt.order_by(
            open_api_external_apps.c.created_at.desc(),
            open_api_external_apps.c.id.asc(),
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_external_app_row(row) for row in rows]

    def get_external_app(self, app_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(open_api_external_apps).where(
                        open_api_external_apps.c.id == app_id
                    ),
                )
                .mappings()
                .first()
            )
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
            row = (
                conn.execute(
                    select(open_api_keys).where(
                        open_api_keys.c.key_hash == key_hash
                    ),
                )
                .mappings()
                .first()
            )
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
        stmt = stmt.order_by(
            open_api_keys.c.created_at.desc(), open_api_keys.c.id.asc()
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_api_key_row(row) for row in rows]

    def update_api_key_status(
        self, key_id: str, status: str
    ) -> dict[str, Any] | None:
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
                .values(
                    last_used_at=_now(), last_used_ip=ip, updated_at=_now()
                ),
            )

    def create_invocation(self, row: dict[str, Any]) -> dict[str, Any]:
        values = _invocation_values(row)
        with self.engine.begin() as conn:
            conn.execute(insert(open_api_invocations).values(**values))
        created = self._get_invocation(values["id"])
        if created is None:
            raise RuntimeError(
                "failed to read open api invocation after create"
            )
        return created

    def get_invocation(self, invocation_id: str) -> dict[str, Any] | None:
        return self._get_invocation(invocation_id)

    def claim_invocation_execution(
        self,
        invocation_id: str,
        owner_token: str,
        *,
        lease_seconds: float,
    ) -> OpenApiExecutionFence | None:
        token = _owner_token(owner_token)
        duration = _lease_seconds(lease_seconds)
        current = _database_now(self.engine)
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    update(open_api_invocations)
                    .where(
                        open_api_invocations.c.id == invocation_id,
                        open_api_invocations.c.status == "accepted",
                        open_api_invocations.c.execution_owner_token.is_(None),
                        open_api_invocations.c.terminal_event_json.is_(None),
                    )
                    .values(
                        status="running",
                        status_code=202,
                        execution_owner_token=token,
                        execution_fence_generation=(
                            open_api_invocations.c.execution_fence_generation
                            + 1
                        ),
                        execution_claimed_at=current,
                        execution_lease_expires_at=_database_expiry(
                            self.engine,
                            duration,
                        ),
                    )
                    .returning(
                        open_api_invocations.c.execution_owner_token,
                        open_api_invocations.c.execution_fence_generation,
                    ),
                )
                .mappings()
                .one_or_none()
            )
        return _execution_fence(row)

    def renew_invocation_execution(
        self,
        invocation_id: str,
        fence: OpenApiExecutionFence,
        *,
        lease_seconds: float,
    ) -> bool:
        checked = _checked_fence(fence)
        duration = _lease_seconds(lease_seconds)
        current = _database_now(self.engine)
        with self.engine.begin() as conn:
            result = conn.execute(
                update(open_api_invocations)
                .where(
                    open_api_invocations.c.id == invocation_id,
                    open_api_invocations.c.status == "running",
                    open_api_invocations.c.execution_owner_token
                    == checked.owner_token,
                    open_api_invocations.c.execution_fence_generation
                    == checked.generation,
                    open_api_invocations.c.execution_lease_expires_at
                    > current,
                    open_api_invocations.c.terminal_event_json.is_(None),
                )
                .values(
                    execution_lease_expires_at=_database_expiry(
                        self.engine,
                        duration,
                    ),
                ),
            )
        return result.rowcount == 1

    def takeover_invocation_execution(
        self,
        invocation_id: str,
        owner_token: str,
        *,
        lease_seconds: float,
    ) -> OpenApiExecutionFence | None:
        token = _owner_token(owner_token)
        duration = _lease_seconds(lease_seconds)
        current = _database_now(self.engine)
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    update(open_api_invocations)
                    .where(
                        open_api_invocations.c.id == invocation_id,
                        open_api_invocations.c.status.in_(
                            ("accepted", "running")
                        ),
                        open_api_invocations.c.terminal_event_json.is_(None),
                        or_(
                            open_api_invocations.c.execution_owner_token.is_(
                                None
                            ),
                            open_api_invocations.c.execution_lease_expires_at.is_(
                                None,
                            ),
                            open_api_invocations.c.execution_lease_expires_at
                            <= current,
                        ),
                    )
                    .values(
                        status="running",
                        status_code=202,
                        execution_owner_token=token,
                        execution_fence_generation=(
                            open_api_invocations.c.execution_fence_generation
                            + 1
                        ),
                        execution_claimed_at=current,
                        execution_lease_expires_at=_database_expiry(
                            self.engine,
                            duration,
                        ),
                    )
                    .returning(
                        open_api_invocations.c.execution_owner_token,
                        open_api_invocations.c.execution_fence_generation,
                    ),
                )
                .mappings()
                .one_or_none()
            )
        return _execution_fence(row)

    def finalize_invocation_execution(
        self,
        invocation_id: str,
        fence: OpenApiExecutionFence,
        *,
        status: str,
        status_code: int,
        error_summary: str,
        terminal_event: dict[str, Any],
        latency_ms: int | None = None,
        billing_status: str | None = None,
        billing_error_code: str | None = None,
        expert_team_run_id: str | None = None,
    ) -> dict[str, Any] | None:
        checked = _checked_fence(fence)
        current = _database_now(self.engine)
        values: dict[str, Any] = {
            "status": status,
            "status_code": int(status_code),
            "error_summary": error_summary,
            "terminal_event_json": _json_text(
                "terminal_event",
                terminal_event,
                dict,
            ),
            "execution_owner_token": None,
            "execution_lease_expires_at": None,
        }
        for key, value in (
            ("latency_ms", latency_ms),
            ("billing_status", billing_status),
            ("billing_error_code", billing_error_code),
            ("expert_team_run_id", expert_team_run_id),
        ):
            if value is not None:
                values[key] = value
        with self.engine.begin() as conn:
            result = conn.execute(
                update(open_api_invocations)
                .where(
                    open_api_invocations.c.id == invocation_id,
                    open_api_invocations.c.execution_owner_token
                    == checked.owner_token,
                    open_api_invocations.c.execution_fence_generation
                    == checked.generation,
                    open_api_invocations.c.execution_lease_expires_at
                    > current,
                    open_api_invocations.c.terminal_event_json.is_(None),
                )
                .values(**values),
            )
        if result.rowcount != 1:
            return None
        return self._get_invocation(invocation_id)

    def finalize_empty_invocation_execution(
        self,
        invocation_id: str,
        usage_order_id: str,
        fence: OpenApiExecutionFence,
        *,
        status: str,
        status_code: int,
        error_summary: str,
        terminal_event: dict[str, Any],
        latency_ms: int | None = None,
        billing_error_code: str | None = None,
        expert_team_run_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Atomically settle and seal an item-free claimed invocation."""
        checked = _checked_fence(fence)
        current = _database_now(self.engine)
        final_values: dict[str, Any] = {
            "status": status,
            "status_code": int(status_code),
            "error_summary": error_summary,
            "billing_status": "settled",
            "terminal_event_json": _json_text(
                "terminal_event",
                terminal_event,
                dict,
            ),
            "execution_owner_token": None,
            "execution_lease_expires_at": None,
        }
        for key, value in (
            ("latency_ms", latency_ms),
            ("billing_error_code", billing_error_code),
            ("expert_team_run_id", expert_team_run_id),
        ):
            if value is not None:
                final_values[key] = value
        try:
            with self.engine.begin() as conn:
                guarded = conn.execute(
                    update(open_api_invocations)
                    .where(
                        open_api_invocations.c.id == invocation_id,
                        open_api_invocations.c.billing_usage_order_id
                        == usage_order_id,
                        open_api_invocations.c.status == "running",
                        open_api_invocations.c.execution_owner_token
                        == checked.owner_token,
                        open_api_invocations.c.execution_fence_generation
                        == checked.generation,
                        open_api_invocations.c.execution_lease_expires_at
                        > current,
                        open_api_invocations.c.terminal_event_json.is_(None),
                    )
                    .values(
                        execution_fence_generation=(
                            open_api_invocations.c.execution_fence_generation
                        ),
                    ),
                )
                if guarded.rowcount != 1:
                    return None
                order = (
                    conn.execute(
                        select(billing_usage_orders)
                        .where(
                            billing_usage_orders.c.id == usage_order_id,
                            billing_usage_orders.c.source_type == "open_api",
                            billing_usage_orders.c.source_id == invocation_id,
                        )
                        .with_for_update(),
                    )
                    .mappings()
                    .one_or_none()
                )
                has_items = conn.execute(
                    select(billing_usage_items.c.id)
                    .where(
                        billing_usage_items.c.usage_order_id
                        == usage_order_id,
                    )
                    .limit(1),
                ).first()
                if order is None or has_items is not None:
                    return None
                if str(order["status"]) not in {"quoted", "settled"}:
                    return None
                conn.execute(
                    update(billing_usage_orders)
                    .where(billing_usage_orders.c.id == usage_order_id)
                    .values(
                        status="settled",
                        settled_at=current,
                        updated_at=current,
                    ),
                )
                finalized = conn.execute(
                    update(open_api_invocations)
                    .where(
                        open_api_invocations.c.id == invocation_id,
                        open_api_invocations.c.execution_owner_token
                        == checked.owner_token,
                        open_api_invocations.c.execution_fence_generation
                        == checked.generation,
                        open_api_invocations.c.execution_lease_expires_at
                        > current,
                        open_api_invocations.c.terminal_event_json.is_(None),
                    )
                    .values(**final_values),
                )
                if finalized.rowcount != 1:
                    raise _EmptyFinalizationLost
        except _EmptyFinalizationLost:
            return None
        return self._get_invocation(invocation_id)

    def update_claimed_invocation(
        self,
        invocation_id: str,
        fence: OpenApiExecutionFence,
        **values: Any,
    ) -> dict[str, Any] | None:
        checked = _checked_fence(fence)
        allowed = {
            "chat_id",
            "status",
            "status_code",
            "latency_ms",
            "error_summary",
            "billing_status",
            "billing_error_code",
            "expert_team_run_id",
        }
        if not values or not set(values) <= allowed:
            raise ValueError("unsupported claimed invocation update")
        current = _database_now(self.engine)
        with self.engine.begin() as conn:
            result = conn.execute(
                update(open_api_invocations)
                .where(
                    open_api_invocations.c.id == invocation_id,
                    open_api_invocations.c.execution_owner_token
                    == checked.owner_token,
                    open_api_invocations.c.execution_fence_generation
                    == checked.generation,
                    open_api_invocations.c.execution_lease_expires_at
                    > current,
                    open_api_invocations.c.terminal_event_json.is_(None),
                )
                .values(**values),
            )
        if result.rowcount != 1:
            return None
        return self._get_invocation(invocation_id)

    def repair_invocation_from_terminal(
        self,
        invocation_id: str,
        *,
        terminal_event: dict[str, Any],
        status: str,
        status_code: int,
        error_summary: str,
        billing_error_code: str | None = None,
    ) -> bool:
        terminal_json = _json_text("terminal_event", terminal_event, dict)
        with self.engine.begin() as conn:
            result = conn.execute(
                update(open_api_invocations)
                .where(
                    open_api_invocations.c.id == invocation_id,
                    open_api_invocations.c.status.in_(("accepted", "running")),
                    open_api_invocations.c.terminal_event_json
                    == terminal_json,
                )
                .values(
                    status=status,
                    status_code=int(status_code),
                    error_summary=error_summary,
                    billing_error_code=billing_error_code,
                    execution_owner_token=None,
                    execution_lease_expires_at=None,
                ),
            )
        return result.rowcount == 1

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
        expert_team_run_id: str | None = None,
        terminal_event: dict[str, Any] | None = None,
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
            ("expert_team_run_id", expert_team_run_id),
        ):
            if value is not None:
                values[key] = value
        if terminal_event is not None:
            values["terminal_event_json"] = _json_text(
                "terminal_event",
                terminal_event,
                dict,
            )
        if values:
            with self.engine.begin() as conn:
                statement = update(open_api_invocations).where(
                    open_api_invocations.c.id == invocation_id,
                )
                if terminal_event is not None:
                    statement = statement.where(
                        open_api_invocations.c.terminal_event_json.is_(None),
                    )
                conn.execute(statement.values(**values))
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
            values["token_summary"] = _json_text(
                "token_summary", token_summary, dict
            )
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
            stmt = stmt.where(
                open_api_invocations.c.publication_id == publication_id
            )
        stmt = (
            stmt.order_by(
                open_api_invocations.c.created_at.desc(),
                open_api_invocations.c.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_invocation_row(row) for row in rows]

    def _get_api_key(self, key_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(open_api_keys).where(open_api_keys.c.id == key_id),
                )
                .mappings()
                .first()
            )
        return _api_key_row(row) if row else None

    def _get_invocation(self, invocation_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(open_api_invocations).where(
                        open_api_invocations.c.id == invocation_id
                    ),
                )
                .mappings()
                .first()
            )
        return _invocation_row(row) if row else None


class SqliteOpenApiRepository:  # pylint: disable=too-many-public-methods
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
                raise ValueError(
                    "Open API publication owner cannot be changed"
                )
            if str(existing["id"]) == str(values["id"]) and str(
                existing["knowledge_base_id"]
            ) != str(values["knowledge_base_id"]):
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
            raise RuntimeError(
                "failed to read open api publication after upsert"
            )
        return created

    def list_publications(
        self, enabled_only: bool = False
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM open_api_publications"
        params: tuple[Any, ...] = ()
        if enabled_only:
            sql += " WHERE status = ?"
            params = ("enabled",)
        sql += " ORDER BY updated_at DESC, id ASC"
        rows = db.get_db().execute(sql, params).fetchall()
        return [_publication_row(dict(row)) for row in rows]

    def get_publication(self, publication_id: str) -> dict[str, Any] | None:
        row = (
            db.get_db()
            .execute(
                "SELECT * FROM open_api_publications WHERE id = ?",
                (publication_id,),
            )
            .fetchone()
        )
        return _publication_row(dict(row)) if row else None

    def get_publication_by_public_id(
        self, public_id: str
    ) -> dict[str, Any] | None:
        row = (
            db.get_db()
            .execute(
                "SELECT * FROM open_api_publications WHERE public_id = ?",
                (public_id,),
            )
            .fetchone()
        )
        return _publication_row(dict(row)) if row else None

    def get_enabled_publication_by_public_id(
        self, public_id: str
    ) -> dict[str, Any] | None:
        row = (
            db.get_db()
            .execute(
                "SELECT * FROM open_api_publications WHERE public_id = ? AND status = 'enabled'",
                (public_id,),
            )
            .fetchone()
        )
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
            raise RuntimeError(
                "failed to read open api external app after create"
            )
        return created

    def list_external_apps(
        self, owner_user_id: str | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM open_api_external_apps"
        params: tuple[Any, ...] = ()
        if owner_user_id is not None:
            sql += " WHERE owner_user_id = ?"
            params = (owner_user_id,)
        sql += " ORDER BY created_at DESC, id ASC"
        rows = db.get_db().execute(sql, params).fetchall()
        return [_external_app_row(dict(row)) for row in rows]

    def get_external_app(self, app_id: str) -> dict[str, Any] | None:
        row = (
            db.get_db()
            .execute(
                "SELECT * FROM open_api_external_apps WHERE id = ?",
                (app_id,),
            )
            .fetchone()
        )
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
        row = (
            db.get_db()
            .execute(
                "SELECT * FROM open_api_keys WHERE key_hash = ?",
                (key_hash,),
            )
            .fetchone()
        )
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

    def update_api_key_status(
        self, key_id: str, status: str
    ) -> dict[str, Any] | None:
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
            raise RuntimeError(
                "failed to read open api invocation after create"
            )
        return created

    def get_invocation(self, invocation_id: str) -> dict[str, Any] | None:
        return self._get_invocation(invocation_id)

    def claim_invocation_execution(
        self,
        invocation_id: str,
        owner_token: str,
        *,
        lease_seconds: float,
    ) -> OpenApiExecutionFence | None:
        token = _owner_token(owner_token)
        duration = _lease_seconds(lease_seconds)
        cursor = db.get_db().execute(
            "UPDATE open_api_invocations SET status = 'running', "
            "status_code = 202, execution_owner_token = ?, "
            "execution_fence_generation = "
            "execution_fence_generation + 1, "
            "execution_claimed_at = CURRENT_TIMESTAMP, "
            "execution_lease_expires_at = strftime('%Y-%m-%d %H:%M:%f', "
            "'now', ?) "
            "WHERE id = ? AND status = 'accepted' "
            "AND execution_owner_token IS NULL "
            "AND terminal_event_json IS NULL RETURNING "
            "execution_owner_token, execution_fence_generation",
            (token, _sqlite_lease_modifier(duration), invocation_id),
        )
        row = cursor.fetchone()
        db.get_db().commit()
        return _execution_fence(row)

    def renew_invocation_execution(
        self,
        invocation_id: str,
        fence: OpenApiExecutionFence,
        *,
        lease_seconds: float,
    ) -> bool:
        checked = _checked_fence(fence)
        duration = _lease_seconds(lease_seconds)
        cursor = db.get_db().execute(
            "UPDATE open_api_invocations SET execution_lease_expires_at = "
            "strftime('%Y-%m-%d %H:%M:%f', 'now', ?) "
            "WHERE id = ? AND status = 'running' "
            "AND execution_owner_token = ? "
            "AND execution_fence_generation = ? "
            "AND execution_lease_expires_at > "
            "strftime('%Y-%m-%d %H:%M:%f', 'now') "
            "AND terminal_event_json IS NULL",
            (
                _sqlite_lease_modifier(duration),
                invocation_id,
                checked.owner_token,
                checked.generation,
            ),
        )
        db.get_db().commit()
        return cursor.rowcount == 1

    def takeover_invocation_execution(
        self,
        invocation_id: str,
        owner_token: str,
        *,
        lease_seconds: float,
    ) -> OpenApiExecutionFence | None:
        token = _owner_token(owner_token)
        duration = _lease_seconds(lease_seconds)
        cursor = db.get_db().execute(
            "UPDATE open_api_invocations SET status = 'running', "
            "status_code = 202, execution_owner_token = ?, "
            "execution_fence_generation = "
            "execution_fence_generation + 1, "
            "execution_claimed_at = CURRENT_TIMESTAMP, "
            "execution_lease_expires_at = strftime('%Y-%m-%d %H:%M:%f', "
            "'now', ?) "
            "WHERE id = ? AND status IN ('accepted', 'running') "
            "AND terminal_event_json IS NULL AND ("
            "execution_owner_token IS NULL OR "
            "execution_lease_expires_at IS NULL OR "
            "execution_lease_expires_at <= "
            "strftime('%Y-%m-%d %H:%M:%f', 'now')) RETURNING "
            "execution_owner_token, execution_fence_generation",
            (token, _sqlite_lease_modifier(duration), invocation_id),
        )
        row = cursor.fetchone()
        db.get_db().commit()
        return _execution_fence(row)

    def finalize_invocation_execution(
        self,
        invocation_id: str,
        fence: OpenApiExecutionFence,
        *,
        status: str,
        status_code: int,
        error_summary: str,
        terminal_event: dict[str, Any],
        latency_ms: int | None = None,
        billing_status: str | None = None,
        billing_error_code: str | None = None,
        expert_team_run_id: str | None = None,
    ) -> dict[str, Any] | None:
        checked = _checked_fence(fence)
        values: list[Any] = [
            status,
            int(status_code),
            error_summary,
            _json_text("terminal_event", terminal_event, dict),
        ]
        assignments = [
            "status = ?",
            "status_code = ?",
            "error_summary = ?",
            "terminal_event_json = ?",
            "execution_owner_token = NULL",
            "execution_lease_expires_at = NULL",
        ]
        for key, value in (
            ("latency_ms", latency_ms),
            ("billing_status", billing_status),
            ("billing_error_code", billing_error_code),
            ("expert_team_run_id", expert_team_run_id),
        ):
            if value is not None:
                assignments.append(f"{key} = ?")
                values.append(value)
        values.extend(
            (invocation_id, checked.owner_token, checked.generation),
        )
        cursor = db.get_db().execute(
            "UPDATE open_api_invocations SET "
            + ", ".join(assignments)
            + " WHERE id = ? AND execution_owner_token = ? "
            "AND execution_fence_generation = ? "
            "AND execution_lease_expires_at > "
            "strftime('%Y-%m-%d %H:%M:%f', 'now') "
            "AND terminal_event_json IS NULL",
            tuple(values),
        )
        db.get_db().commit()
        if cursor.rowcount != 1:
            return None
        return self._get_invocation(invocation_id)

    def finalize_empty_invocation_execution(
        self,
        invocation_id: str,
        usage_order_id: str,
        fence: OpenApiExecutionFence,
        *,
        status: str,
        status_code: int,
        error_summary: str,
        terminal_event: dict[str, Any],
        latency_ms: int | None = None,
        billing_error_code: str | None = None,
        expert_team_run_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Atomically settle and seal an item-free claimed invocation."""
        checked = _checked_fence(fence)
        connection = db.get_db()
        try:
            connection.execute("BEGIN IMMEDIATE")
            guarded = connection.execute(
                "UPDATE open_api_invocations SET "
                "execution_fence_generation = execution_fence_generation "
                "WHERE id = ? AND billing_usage_order_id = ? "
                "AND status = 'running' AND execution_owner_token = ? "
                "AND execution_fence_generation = ? "
                "AND execution_lease_expires_at > "
                "strftime('%Y-%m-%d %H:%M:%f', 'now') "
                "AND terminal_event_json IS NULL",
                (
                    invocation_id,
                    usage_order_id,
                    checked.owner_token,
                    checked.generation,
                ),
            )
            if guarded.rowcount != 1:
                connection.rollback()
                return None
            order = connection.execute(
                "SELECT status FROM billing_usage_orders WHERE id = ? "
                "AND source_type = 'open_api' AND source_id = ?",
                (usage_order_id, invocation_id),
            ).fetchone()
            item = connection.execute(
                "SELECT id FROM billing_usage_items WHERE usage_order_id = ? "
                "LIMIT 1",
                (usage_order_id,),
            ).fetchone()
            if order is None or item is not None or str(order[0]) not in {
                "quoted",
                "settled",
            }:
                connection.rollback()
                return None
            connection.execute(
                "UPDATE billing_usage_orders SET status = 'settled', "
                "settled_at = strftime('%Y-%m-%d %H:%M:%f', 'now'), "
                "updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now') "
                "WHERE id = ?",
                (usage_order_id,),
            )
            values: list[Any] = [
                status,
                int(status_code),
                error_summary,
                _json_text("terminal_event", terminal_event, dict),
            ]
            assignments = [
                "status = ?",
                "status_code = ?",
                "error_summary = ?",
                "terminal_event_json = ?",
                "billing_status = 'settled'",
                "execution_owner_token = NULL",
                "execution_lease_expires_at = NULL",
            ]
            for key, value in (
                ("latency_ms", latency_ms),
                ("billing_error_code", billing_error_code),
                ("expert_team_run_id", expert_team_run_id),
            ):
                if value is not None:
                    assignments.append(f"{key} = ?")
                    values.append(value)
            values.extend(
                (invocation_id, checked.owner_token, checked.generation),
            )
            finalized = connection.execute(
                "UPDATE open_api_invocations SET "
                + ", ".join(assignments)
                + " WHERE id = ? AND execution_owner_token = ? "
                "AND execution_fence_generation = ? "
                "AND execution_lease_expires_at > "
                "strftime('%Y-%m-%d %H:%M:%f', 'now') "
                "AND terminal_event_json IS NULL",
                tuple(values),
            )
            if finalized.rowcount != 1:
                connection.rollback()
                return None
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return self._get_invocation(invocation_id)

    def update_claimed_invocation(
        self,
        invocation_id: str,
        fence: OpenApiExecutionFence,
        **values: Any,
    ) -> dict[str, Any] | None:
        checked = _checked_fence(fence)
        allowed = {
            "chat_id",
            "status",
            "status_code",
            "latency_ms",
            "error_summary",
            "billing_status",
            "billing_error_code",
            "expert_team_run_id",
        }
        if not values or not set(values) <= allowed:
            raise ValueError("unsupported claimed invocation update")
        assignments = ", ".join(f"{key} = ?" for key in values)
        parameters = list(values.values())
        parameters.extend(
            (invocation_id, checked.owner_token, checked.generation),
        )
        cursor = db.get_db().execute(
            f"UPDATE open_api_invocations SET {assignments} "
            "WHERE id = ? AND execution_owner_token = ? "
            "AND execution_fence_generation = ? "
            "AND execution_lease_expires_at > "
            "strftime('%Y-%m-%d %H:%M:%f', 'now') "
            "AND terminal_event_json IS NULL",
            tuple(parameters),
        )
        db.get_db().commit()
        if cursor.rowcount != 1:
            return None
        return self._get_invocation(invocation_id)

    def repair_invocation_from_terminal(
        self,
        invocation_id: str,
        *,
        terminal_event: dict[str, Any],
        status: str,
        status_code: int,
        error_summary: str,
        billing_error_code: str | None = None,
    ) -> bool:
        cursor = db.get_db().execute(
            "UPDATE open_api_invocations SET status = ?, status_code = ?, "
            "error_summary = ?, billing_error_code = ?, "
            "execution_owner_token = NULL, "
            "execution_lease_expires_at = NULL "
            "WHERE id = ? AND status IN ('accepted', 'running') "
            "AND terminal_event_json = ?",
            (
                status,
                int(status_code),
                error_summary,
                billing_error_code,
                invocation_id,
                _json_text("terminal_event", terminal_event, dict),
            ),
        )
        db.get_db().commit()
        return cursor.rowcount == 1

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
        expert_team_run_id: str | None = None,
        terminal_event: dict[str, Any] | None = None,
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
            ("expert_team_run_id", expert_team_run_id),
        ):
            if value is not None:
                assignments.append(f"{key} = ?")
                values.append(value)
        if terminal_event is not None:
            assignments.append("terminal_event_json = ?")
            values.append(_json_text("terminal_event", terminal_event, dict))
        if assignments:
            values.append(invocation_id)
            terminal_guard = (
                " AND terminal_event_json IS NULL"
                if terminal_event is not None
                else ""
            )
            db.get_db().execute(
                "UPDATE open_api_invocations SET "
                + ", ".join(assignments)
                + " WHERE id = ?"
                + terminal_guard,
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
        row = (
            db.get_db()
            .execute(
                "SELECT * FROM open_api_keys WHERE id = ?",
                (key_id,),
            )
            .fetchone()
        )
        return _api_key_row(dict(row)) if row else None

    def _get_invocation(self, invocation_id: str) -> dict[str, Any] | None:
        row = (
            db.get_db()
            .execute(
                "SELECT * FROM open_api_invocations WHERE id = ?",
                (invocation_id,),
            )
            .fetchone()
        )
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
    values["ip_allowlist"] = _json_text(
        "ip_allowlist", values.get("ip_allowlist"), list
    )
    values["quota_policy"] = _json_text(
        "quota_policy", values.get("quota_policy"), dict
    )
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
    result["ip_allowlist"] = _json_value(
        "ip_allowlist", result.get("ip_allowlist"), list
    )
    result["quota_policy"] = _json_value(
        "quota_policy", result.get("quota_policy"), dict
    )
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
    terminal = result.get("terminal_event_json")
    result["terminal_event_json"] = (
        _json_value("terminal_event_json", terminal, dict)
        if terminal
        else None
    )
    for field_name in (
        "execution_claimed_at",
        "execution_lease_expires_at",
    ):
        value = result.get(field_name)
        if isinstance(value, datetime):
            result[field_name] = _utc_datetime(value)
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
        raise ValueError(
            f"{field_name} must be a JSON {expected_type.__name__}"
        )
    raise ValueError(f"{field_name} must be a {expected_type.__name__}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _future_lease(
    lease_expires_at: datetime,
    *,
    now: datetime | None = None,
) -> datetime:
    expiry = _utc_datetime(lease_expires_at)
    if expiry <= _utc_datetime(now or _now()):
        raise ValueError("execution lease must expire in the future")
    return expiry


def _owner_token(owner_token: str) -> str:
    token = str(owner_token or "").strip()
    if not token:
        raise ValueError("execution owner token must be non-empty")
    return token


def _checked_fence(fence: OpenApiExecutionFence) -> OpenApiExecutionFence:
    token = _owner_token(fence.owner_token)
    generation = int(fence.generation)
    if generation <= 0:
        raise ValueError("execution fence generation must be positive")
    return OpenApiExecutionFence(token, generation)


def _execution_fence(row: Any) -> OpenApiExecutionFence | None:
    if row is None:
        return None
    try:
        token = row["execution_owner_token"]
        generation = row["execution_fence_generation"]
    except (KeyError, TypeError):
        token, generation = row[0], row[1]
    return OpenApiExecutionFence(str(token), int(generation))


def _lease_seconds(value: float) -> float:
    seconds = float(value)
    if seconds <= 0:
        raise ValueError("execution lease duration must be positive")
    return seconds


def _sqlite_lease_modifier(seconds: float) -> str:
    return f"+{seconds:.6f} seconds"


def _database_now(engine: Engine):
    if engine.dialect.name == "sqlite":
        return func.strftime("%Y-%m-%d %H:%M:%f", "now")
    return func.current_timestamp()


def _database_expiry(engine: Engine, seconds: float):
    if engine.dialect.name == "sqlite":
        return func.strftime(
            "%Y-%m-%d %H:%M:%f",
            "now",
            _sqlite_lease_modifier(seconds),
        )
    return func.current_timestamp() + literal(
        timedelta(seconds=seconds),
        type_=Interval(),
    )


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
