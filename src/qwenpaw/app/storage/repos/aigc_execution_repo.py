"""Core execution records. Schema creation belongs to application startup."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
from typing import Any, Iterator

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from ...aigc.workflow_execution import WorkflowExecutionBinding
from ..schema import aigc_operation_journal as operations
from ..schema import aigc_workflow_execution_bindings as bindings_table


def command_digest(value: Any) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class AigcExecutionRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.engine.begin() as connection:
            # SQLite has no row-level FOR UPDATE. Acquire its write reservation
            # before reading; PostgreSQL callers lock the operation row instead.
            if self.engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            yield connection

    @staticmethod
    def _operation(connection: Connection, owner: str, operation_id: str):
        return connection.execute(select(operations).where(
            operations.c.owner_user_id == owner,
            operations.c.operation_id == operation_id,
        ).with_for_update()).mappings().one_or_none()

    def get_operation(self, owner: str, operation_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = self._operation(connection, owner, operation_id)
            return dict(row) if row is not None else None

    def prepare_operation(
        self, owner: str, operation_id: str, *, canvas_id: str,
        digest: str, snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        if not owner.strip() or not operation_id.strip():
            raise ValueError("INVALID_OPERATION_ID")
        serialized = json.dumps(snapshot, allow_nan=False)
        with self.transaction() as connection:
            try:
                with connection.begin_nested():
                    connection.execute(insert(operations).values(
                        owner_user_id=owner, operation_id=operation_id,
                        canvas_id=canvas_id, command_digest=digest,
                        resource_snapshot=serialized, phase="PREPARED",
                    ))
            except IntegrityError:
                pass
            saved = self._operation(connection, owner, operation_id)
            if saved is None or saved["command_digest"] != digest:
                raise ValueError("OPERATION_CONFLICT")
            return dict(saved)

    @staticmethod
    def mark_applied(connection: Connection, owner: str, operation_id: str) -> None:
        connection.execute(update(operations).where(
            operations.c.owner_user_id == owner,
            operations.c.operation_id == operation_id,
        ).values(phase="APPLIED"))

    @staticmethod
    def _validate_group(bindings: list[WorkflowExecutionBinding]) -> None:
        if not bindings:
            raise ValueError("EMPTY_EXECUTION_BINDINGS")
        scopes = {(b.owner_user_id, b.canvas_id, b.workflow_id, b.workflow_revision)
                  for b in bindings}
        if len(scopes) != 1:
            raise ValueError("BINDING_SCOPE_MISMATCH")
        if (len({b.node_id for b in bindings}) != len(bindings)
                or len({b.logical_node_id for b in bindings}) != len(bindings)):
            raise ValueError("DUPLICATE_EXECUTION_BINDING")

    @staticmethod
    def _insert_bindings(connection: Connection, bindings: list[WorkflowExecutionBinding],
                         operation_id: str) -> None:
        for binding in bindings:
            values = asdict(binding)
            existing = connection.execute(select(bindings_table).where(
                bindings_table.c.owner_user_id == binding.owner_user_id,
                bindings_table.c.canvas_id == binding.canvas_id,
                bindings_table.c.node_id == binding.node_id,
            )).mappings().one_or_none()
            if existing is not None:
                if any(existing[key] != value for key, value in values.items()):
                    raise ValueError("EXECUTION_BINDING_CONFLICT")
                continue
            connection.execute(insert(bindings_table).values(**values, operation_id=operation_id))

    def register_bindings(self, bindings: list[WorkflowExecutionBinding], operation_id: str) -> None:
        self._validate_group(bindings)
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("INVALID_OPERATION_ID")
        values = [asdict(binding) for binding in sorted(bindings, key=lambda b: b.node_id)]
        digest = command_digest(values)
        owner = bindings[0].owner_user_id
        try:
            with self.transaction() as connection:
                # A savepoint also handles concurrent PostgreSQL registration of
                # the same operation without leaving the transaction aborted.
                try:
                    with connection.begin_nested():
                        connection.execute(insert(operations).values(
                            owner_user_id=owner, operation_id=operation_id,
                            canvas_id=bindings[0].canvas_id, command_digest=digest,
                            resource_snapshot=json.dumps({"bindings": values}), phase="PREPARED",
                        ))
                except IntegrityError:
                    pass
                operation = self._operation(connection, owner, operation_id)
                if operation is None or operation["command_digest"] != digest:
                    raise ValueError("OPERATION_CONFLICT")
                self._insert_bindings(connection, bindings, operation_id)
                connection.execute(update(operations).where(
                    operations.c.owner_user_id == owner,
                    operations.c.operation_id == operation_id,
                ).values(phase="APPLIED"))
        except IntegrityError as exc:
            raise ValueError("EXECUTION_BINDING_CONFLICT") from exc

    def get_binding(self, owner_user_id: str, canvas_id: str,
                    node_id: str) -> WorkflowExecutionBinding | None:
        with self.engine.connect() as connection:
            pending = connection.execute(select(operations.c.operation_id).where(
                operations.c.owner_user_id == owner_user_id,
                operations.c.canvas_id == canvas_id,
                operations.c.phase != "APPLIED",
            )).first()
            if pending is not None:
                raise ValueError("WORKFLOW_OPERATION_INCOMPLETE")
            row = connection.execute(select(bindings_table).where(
                bindings_table.c.owner_user_id == owner_user_id,
                bindings_table.c.canvas_id == canvas_id,
                bindings_table.c.node_id == node_id,
            )).mappings().one_or_none()
            if row is None:
                return None
            operation = connection.execute(select(operations.c.phase).where(
                operations.c.owner_user_id == owner_user_id,
                operations.c.operation_id == row["operation_id"],
            )).scalar_one_or_none()
            if operation != "APPLIED":
                raise ValueError("WORKFLOW_OPERATION_INCOMPLETE")
            return WorkflowExecutionBinding(**{
                key: row[key] for key in WorkflowExecutionBinding.__dataclass_fields__
            })
