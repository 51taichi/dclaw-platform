# -*- coding: utf-8 -*-
"""Durable ownership for non-OpenAPI billed executions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from ..schema import billing_executions


class ExecutionReplayConflictError(RuntimeError):
    """The persisted execution identity belongs to another request."""


@dataclass(frozen=True)
class BillingExecutionFence:
    """A monotonic owner identity for one general billing execution."""

    owner_token: str
    generation: int


@dataclass(frozen=True)
class BillingExecutionCommand:
    """Immutable fields used to create or replay one execution."""

    execution_id: str
    usage_order_id: str | None
    payer_user_id: str | None
    source_type: str
    source_id: str
    request_sha256: str
    exemption_actor: str | None = None
    exemption_reason: str | None = None


@dataclass(frozen=True)
class BillingExecutionRecord:
    """Public repository representation of a durable execution row."""

    id: str
    usage_order_id: str | None
    payer_user_id: str | None
    source_type: str
    source_id: str
    request_sha256: str
    state: str
    owner_token: str | None
    fence_generation: int
    lease_expires_at: datetime | None
    resume_state_json: str
    exemption_actor: str | None
    exemption_reason: str | None
    error_code: str | None


class BillingExecutionRepository:
    """Create, claim, renew, and finalize general billing executions."""

    _terminal_states = frozenset(
        {"succeeded", "failed", "cancelled", "reconciling"},
    )

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_or_replay(
        self,
        command: BillingExecutionCommand,
    ) -> BillingExecutionRecord:
        values = _command_values(command)
        try:
            with self.engine.begin() as conn:
                row = (
                    conn.execute(
                        insert(billing_executions)
                        .values(**values)
                        .returning(billing_executions),
                    )
                    .mappings()
                    .one()
                )
                return _record(row)
        except IntegrityError:
            existing = self._find_replay(command)
            if existing is None or not _matches(existing, command):
                raise ExecutionReplayConflictError(command.execution_id)
            return existing

    def get(self, execution_id: str) -> BillingExecutionRecord | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(billing_executions).where(
                        billing_executions.c.id == execution_id,
                    ),
                )
                .mappings()
                .one_or_none()
            )
        return _record(row) if row is not None else None

    def get_by_usage_order(
        self,
        usage_order_id: str,
    ) -> BillingExecutionRecord | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(billing_executions).where(
                        billing_executions.c.usage_order_id == usage_order_id,
                    ),
                )
                .mappings()
                .one_or_none()
            )
        return _record(row) if row is not None else None

    def list_recoverable(self) -> list[BillingExecutionRecord]:
        """Return nonterminal executions without treating pauses as stale."""
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    select(billing_executions)
                    .where(
                        billing_executions.c.usage_order_id.is_not(None),
                        billing_executions.c.state.in_(
                            ("accepted", "running")
                        ),
                    )
                    .order_by(
                        billing_executions.c.created_at,
                        billing_executions.c.id,
                    ),
                )
                .mappings()
                .all()
            )
        return [_record(row) for row in rows]

    def claim(
        self,
        execution_id: str,
        owner_token: str,
        *,
        lease_seconds: float,
    ) -> BillingExecutionFence | None:
        normalized_owner = _required(owner_token, "owner_token")
        deadline = _lease_deadline(self.engine, lease_seconds)
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    update(billing_executions)
                    .where(
                        billing_executions.c.id == execution_id,
                        billing_executions.c.state == "accepted",
                        billing_executions.c.owner_token.is_(None),
                    )
                    .values(
                        state="running",
                        owner_token=normalized_owner,
                        fence_generation=(
                            billing_executions.c.fence_generation + 1
                        ),
                        lease_expires_at=deadline,
                        updated_at=_db_now(self.engine),
                    )
                    .returning(
                        billing_executions.c.owner_token,
                        billing_executions.c.fence_generation,
                    ),
                )
                .mappings()
                .one_or_none()
            )
        return _fence(row)

    def renew(
        self,
        execution_id: str,
        fence: BillingExecutionFence,
        *,
        lease_seconds: float,
    ) -> bool:
        now = _db_now(self.engine)
        with self.engine.begin() as conn:
            result = conn.execute(
                update(billing_executions)
                .where(
                    billing_executions.c.id == execution_id,
                    billing_executions.c.state == "running",
                    billing_executions.c.owner_token == fence.owner_token,
                    billing_executions.c.fence_generation == fence.generation,
                    billing_executions.c.lease_expires_at > now,
                )
                .values(
                    lease_expires_at=_lease_deadline(
                        self.engine,
                        lease_seconds,
                    ),
                    updated_at=now,
                ),
            )
        return bool(result.rowcount)

    def takeover(
        self,
        execution_id: str,
        owner_token: str,
        *,
        lease_seconds: float,
    ) -> BillingExecutionFence | None:
        normalized_owner = _required(owner_token, "owner_token")
        now = _db_now(self.engine)
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    update(billing_executions)
                    .where(
                        billing_executions.c.id == execution_id,
                        billing_executions.c.state == "running",
                        billing_executions.c.lease_expires_at <= now,
                    )
                    .values(
                        owner_token=normalized_owner,
                        fence_generation=(
                            billing_executions.c.fence_generation + 1
                        ),
                        lease_expires_at=_lease_deadline(
                            self.engine,
                            lease_seconds,
                        ),
                        updated_at=now,
                    )
                    .returning(
                        billing_executions.c.owner_token,
                        billing_executions.c.fence_generation,
                    ),
                )
                .mappings()
                .one_or_none()
            )
        return _fence(row)

    def pause_for_insufficient_balance(
        self,
        execution_id: str,
        fence: BillingExecutionFence,
        *,
        resume_state_json: str,
    ) -> bool:
        """Release ownership while preserving a resumable execution."""
        now = _db_now(self.engine)
        with self.engine.begin() as conn:
            result = conn.execute(
                update(billing_executions)
                .where(
                    billing_executions.c.id == execution_id,
                    billing_executions.c.state == "running",
                    billing_executions.c.owner_token == fence.owner_token,
                    billing_executions.c.fence_generation == fence.generation,
                    billing_executions.c.lease_expires_at > now,
                )
                .values(
                    state="paused_insufficient_balance",
                    owner_token=None,
                    lease_expires_at=None,
                    resume_state_json=resume_state_json,
                    error_code="INSUFFICIENT_CREDITS",
                    updated_at=now,
                ),
            )
        return bool(result.rowcount)

    def claim_paused(
        self,
        execution_id: str,
        owner_token: str,
        *,
        lease_seconds: float,
    ) -> BillingExecutionFence | None:
        """Acquire one paused execution for a single continuation worker."""
        normalized_owner = _required(owner_token, "owner_token")
        now = _db_now(self.engine)
        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    update(billing_executions)
                    .where(
                        billing_executions.c.id == execution_id,
                        billing_executions.c.state
                        == "paused_insufficient_balance",
                        billing_executions.c.owner_token.is_(None),
                    )
                    .values(
                        state="running",
                        owner_token=normalized_owner,
                        fence_generation=(
                            billing_executions.c.fence_generation + 1
                        ),
                        lease_expires_at=_lease_deadline(
                            self.engine,
                            lease_seconds,
                        ),
                        error_code=None,
                        updated_at=now,
                    )
                    .returning(
                        billing_executions.c.owner_token,
                        billing_executions.c.fence_generation,
                    ),
                )
                .mappings()
                .one_or_none()
            )
        return _fence(row)

    def finalize(
        self,
        execution_id: str,
        fence: BillingExecutionFence,
        *,
        state: str,
        error_code: str | None,
    ) -> bool:
        if state not in self._terminal_states:
            raise ValueError("execution final state is invalid")
        now = _db_now(self.engine)
        with self.engine.begin() as conn:
            result = conn.execute(
                update(billing_executions)
                .where(
                    billing_executions.c.id == execution_id,
                    billing_executions.c.state == "running",
                    billing_executions.c.owner_token == fence.owner_token,
                    billing_executions.c.fence_generation == fence.generation,
                    billing_executions.c.lease_expires_at > now,
                )
                .values(
                    state=state,
                    error_code=error_code,
                    owner_token=None,
                    lease_expires_at=None,
                    updated_at=now,
                ),
            )
        return bool(result.rowcount)

    def _find_replay(
        self,
        command: BillingExecutionCommand,
    ) -> BillingExecutionRecord | None:
        conditions = [billing_executions.c.id == command.execution_id]
        if command.usage_order_id:
            conditions.append(
                billing_executions.c.usage_order_id == command.usage_order_id,
            )
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(billing_executions).where(or_(*conditions)),
                )
                .mappings()
                .first()
            )
        return _record(row) if row is not None else None


def _command_values(command: BillingExecutionCommand) -> dict[str, object]:
    source_type = _required(command.source_type, "source_type")
    source_id = _required(command.source_id, "source_id")
    request_hash = _required(command.request_sha256, "request_sha256")
    if len(request_hash) != 64:
        raise ValueError("request_sha256 must contain 64 characters")
    return {
        "id": _required(command.execution_id, "execution_id"),
        "usage_order_id": command.usage_order_id,
        "payer_user_id": command.payer_user_id,
        "source_type": source_type,
        "source_id": source_id,
        "request_sha256": request_hash,
        "exemption_actor": command.exemption_actor,
        "exemption_reason": command.exemption_reason,
    }


def _matches(
    record: BillingExecutionRecord,
    command: BillingExecutionCommand,
) -> bool:
    return (
        record.id == command.execution_id
        and record.usage_order_id == command.usage_order_id
        and record.payer_user_id == command.payer_user_id
        and record.source_type == command.source_type
        and record.source_id == command.source_id
        and record.request_sha256 == command.request_sha256
        and record.exemption_actor == command.exemption_actor
        and record.exemption_reason == command.exemption_reason
    )


def _record(row) -> BillingExecutionRecord:
    return BillingExecutionRecord(
        id=str(row["id"]),
        usage_order_id=(
            str(row["usage_order_id"]) if row["usage_order_id"] else None
        ),
        payer_user_id=(
            str(row["payer_user_id"]) if row["payer_user_id"] else None
        ),
        source_type=str(row["source_type"]),
        source_id=str(row["source_id"]),
        request_sha256=str(row["request_sha256"]),
        state=str(row["state"]),
        owner_token=(str(row["owner_token"]) if row["owner_token"] else None),
        fence_generation=int(row["fence_generation"]),
        lease_expires_at=row["lease_expires_at"],
        resume_state_json=str(row["resume_state_json"] or "{}"),
        exemption_actor=(
            str(row["exemption_actor"]) if row["exemption_actor"] else None
        ),
        exemption_reason=(
            str(row["exemption_reason"]) if row["exemption_reason"] else None
        ),
        error_code=(str(row["error_code"]) if row["error_code"] else None),
    )


def _fence(row) -> BillingExecutionFence | None:
    if row is None:
        return None
    return BillingExecutionFence(
        owner_token=str(row["owner_token"]),
        generation=int(row["fence_generation"]),
    )


def _required(value: str, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} must be non-empty")
    return normalized


def _db_now(engine: Engine):
    if engine.dialect.name == "postgresql":
        return func.clock_timestamp()
    return func.datetime("now")


def _lease_deadline(engine: Engine, lease_seconds: float):
    seconds = float(lease_seconds)
    if seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    if engine.dialect.name == "postgresql":
        return func.clock_timestamp() + func.make_interval(
            0,
            0,
            0,
            0,
            0,
            0,
            seconds,
        )
    return func.datetime("now", f"+{seconds} seconds")


__all__ = [
    "BillingExecutionCommand",
    "BillingExecutionFence",
    "BillingExecutionRecord",
    "BillingExecutionRepository",
    "ExecutionReplayConflictError",
]
