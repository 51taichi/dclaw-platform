"""Core execution records. Schema creation belongs to application startup."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import time
import uuid
from typing import Any, Callable, Iterator

from sqlalchemy import and_, insert, or_, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from ...aigc.workflow_execution import WorkflowExecutionBinding
from ..schema import aigc_operation_journal as operations
from ..schema import aigc_workflow_execution_bindings as bindings_table
from ..schema import aigc_job_results as job_results
from ..schema import aigc_job_attempts as job_attempts
from ..schema import aigc_provider_tasks as provider_tasks
from ..schema import aigc_node_results as node_results
from ..schema import aigc_domain_events as domain_events
from ..schema import aigc_event_deliveries as deliveries
from ...aigc.events import AigcDomainEvent
from ...aigc.provider_errors import ProviderSubmissionRejected


def command_digest(value: Any) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def job_creation_timestamp(snapshot: dict[str, Any]) -> float:
    try:
        created = datetime.fromisoformat(snapshot["created_at"].replace("Z", "+00:00"))
        return (created if created.tzinfo else created.replace(tzinfo=timezone.utc)).timestamp()
    except (ValueError, TypeError):
        return 0  # Undated historical jobs precede all dated jobs.


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
                prior = self._operation(connection, owner, operation_id)
                if prior is not None and prior["command_digest"] != digest:
                    raise ValueError("OPERATION_CONFLICT")
                self._classify_bindings(connection, bindings)
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

    @staticmethod
    def _classify_bindings(connection: Connection, bindings: list[WorkflowExecutionBinding]) -> str:
        """Read-only migration assessment; registration repeats it transactionally."""
        canvas_id = bindings[0].canvas_id
        pending = connection.execute(select(operations.c.operation_id).where(
            operations.c.canvas_id == canvas_id, operations.c.phase != "APPLIED",
        )).first()
        if pending is not None:
            raise ValueError("WORKFLOW_OPERATION_INCOMPLETE")
        expected = {binding.node_id: asdict(binding) for binding in bindings}
        rows = connection.execute(select(bindings_table).where(
            bindings_table.c.canvas_id == canvas_id,
        )).mappings().all()
        for row in rows:
            target = expected.get(row["node_id"])
            if target is None or any(row[key] != value for key, value in target.items()):
                raise ValueError("EXECUTION_BINDING_CONFLICT")
            phase = connection.execute(select(operations.c.phase).where(
                operations.c.owner_user_id == row["owner_user_id"],
                operations.c.operation_id == row["operation_id"],
            )).scalar_one_or_none()
            if phase != "APPLIED":
                raise ValueError("WORKFLOW_OPERATION_INCOMPLETE")
        return "unchanged" if len(rows) == len(bindings) else "eligible"

    def classify_bindings(self, bindings: list[WorkflowExecutionBinding]) -> str:
        self._validate_group(bindings)
        with self.engine.connect() as connection:
            return self._classify_bindings(connection, bindings)

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

    def is_managed_canvas(self, canvas_id: str) -> bool:
        """Trusted caller has already authorized the canvas, independently of meta."""
        with self.engine.connect() as connection:
            operation = connection.execute(select(operations.c.operation_id).where(
                operations.c.canvas_id == canvas_id,
            ).limit(1)).first()
            if operation is not None:
                return True
            return connection.execute(select(bindings_table.c.node_id).where(
                bindings_table.c.canvas_id == canvas_id,
            ).limit(1)).first() is not None

    def get_job_result(self, job_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(job_results).where(job_results.c.job_id == job_id)).mappings().one_or_none()
            return dict(row) if row is not None else None

    def begin_job_attempt(self, job_id: str, owner: str, *, command: dict | None = None,
                          now: float | None = None) -> str:
        """Reserve before provider execution; uncertain attempts never auto-repeat."""
        now = time.time() if now is None else now
        digest = command_digest(command) if command is not None else None
        with self.transaction() as connection:
            try:
                with connection.begin_nested():
                    connection.execute(insert(job_attempts).values(
                        job_id=job_id, owner_user_id=owner, attempt_token="initial", phase="finished",
                    ))
            except IntegrityError:
                pass
            row = connection.execute(select(job_attempts).where(job_attempts.c.job_id == job_id)
                                     .with_for_update()).mappings().one()
            if row["owner_user_id"] != owner:
                raise ValueError("JOB_RESULT_BINDING_MISMATCH")
            if row["command_digest"] is not None and row["command_digest"] != digest:
                raise ValueError("JOB_COMMAND_MISMATCH")
            result = connection.execute(select(job_results.c.snapshot).where(
                job_results.c.job_id == job_id,
            )).scalar_one_or_none()
            if result is not None and json.loads(result).get("status") == "succeeded":
                raise ValueError("JOB_ALREADY_SUCCEEDED")
            if result is not None and json.loads(result).get("status") == "cancelled":
                raise ValueError("JOB_CANCELLED")
            if row["phase"] != "finished":
                raise ValueError("JOB_RECONCILIATION_REQUIRED")
            token = uuid.uuid4().hex
            connection.execute(update(job_attempts).where(job_attempts.c.job_id == job_id)
                               .values(attempt_token=token, phase="running", command_digest=digest, lease_until=now + 120))
            return token

    def resume_job_attempt(self, job_id: str, owner: str, *, command: dict, now: float | None = None) -> str:
        now = time.time() if now is None else now
        with self.transaction() as connection:
            row = connection.execute(select(job_attempts).where(job_attempts.c.job_id == job_id)
                                     .with_for_update()).mappings().one_or_none()
            if row is None or row["owner_user_id"] != owner:
                raise ValueError("JOB_RESULT_BINDING_MISMATCH")
            if row["command_digest"] != command_digest(command):
                raise ValueError("JOB_COMMAND_MISMATCH")
            if row["phase"] in {"finished", "cancelled"} or (row["phase"] == "running" and row["lease_until"] > now):
                raise ValueError("JOB_RECONCILIATION_REQUIRED")
            accepted = connection.execute(select(provider_tasks.c.remote_task_id).where(
                provider_tasks.c.job_id == job_id, provider_tasks.c.remote_task_id.is_not(None),
            ).limit(1)).first()
            if accepted is None:
                raise ValueError("JOB_RECONCILIATION_REQUIRED")
            token = uuid.uuid4().hex
            connection.execute(update(job_attempts).where(job_attempts.c.job_id == job_id).values(
                attempt_token=token, phase="running", lease_until=now + 120,
            ))
            return token

    @staticmethod
    def _live_attempt(connection: Connection, job_id: str, token: str, now: float):
        row = connection.execute(select(job_attempts).where(job_attempts.c.job_id == job_id)
                                 .with_for_update()).mappings().one_or_none()
        if (row is None or row["attempt_token"] != token or row["phase"] != "running"
                or row["lease_until"] <= now):
            raise ValueError("JOB_ATTEMPT_MISMATCH")
        return row

    def renew_job_attempt(self, job_id: str, token: str, *, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self.transaction() as connection:
            self._live_attempt(connection, job_id, token, now)
            connection.execute(update(job_attempts).where(job_attempts.c.job_id == job_id).values(lease_until=now + 120))

    def has_provider_tasks(self, job_id: str) -> bool:
        with self.engine.connect() as connection:
            return connection.execute(select(provider_tasks.c.slot).where(provider_tasks.c.job_id == job_id).limit(1)).first() is not None

    def provider_task_references(self, job_id: str) -> list[str]:
        """Return accepted supplier task ids in stable slot order."""
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(provider_tasks.c.remote_task_id).where(
                    provider_tasks.c.job_id == job_id,
                    provider_tasks.c.remote_task_id.is_not(None),
                ).order_by(provider_tasks.c.slot),
            ).all()
        return [str(row[0]) for row in rows if str(row[0] or "").strip()]

    def can_query_provider_tasks(self, job_id: str, owner: str, command: dict) -> bool:
        """A persisted acceptance permits querying, never a new submission."""
        with self.engine.connect() as connection:
            attempt = connection.execute(select(job_attempts).where(job_attempts.c.job_id == job_id)).mappings().one_or_none()
            if attempt is None:
                return False
            if attempt["owner_user_id"] != owner:
                raise ValueError("JOB_RESULT_BINDING_MISMATCH")
            if attempt["command_digest"] != command_digest(command):
                raise ValueError("JOB_COMMAND_MISMATCH")
            return attempt["phase"] != "cancelled" and connection.execute(select(provider_tasks.c.slot).where(
                provider_tasks.c.job_id == job_id, provider_tasks.c.remote_task_id.is_not(None),
            ).limit(1)).first() is not None

    def prepare_provider_task(self, job_id: str, token: str, slot: str, adapter: str, *,
                              read_only: bool = False, reserve: bool = True,
                              now: float | None = None) -> str | None:
        now = time.time() if now is None else now
        with self.transaction() as connection:
            self._live_attempt(connection, job_id, token, now)
            row = connection.execute(select(provider_tasks).where(
                provider_tasks.c.job_id == job_id, provider_tasks.c.slot == slot,
            )).mappings().one_or_none()
            if row is not None:
                if row["adapter"] != adapter:
                    raise ValueError("PROVIDER_TASK_BINDING_MISMATCH")
                if row["rejection_error"] is not None:
                    raise ProviderSubmissionRejected(row["rejection_error"])
                if not row["remote_task_id"]:
                    raise ValueError("PROVIDER_SUBMISSION_UNRESOLVED")
                return row["remote_task_id"]
            if read_only:
                raise ValueError("PROVIDER_SUBMISSION_UNRESOLVED")
            if reserve:
                connection.execute(insert(provider_tasks).values(job_id=job_id, slot=slot, adapter=adapter))
            return None

    def reject_provider_task(self, job_id: str, token: str, slot: str, message: str) -> None:
        with self.transaction() as connection:
            self._live_attempt(connection, job_id, token, time.time())
            result = connection.execute(update(provider_tasks).where(
                provider_tasks.c.job_id == job_id, provider_tasks.c.slot == slot,
                provider_tasks.c.remote_task_id.is_(None),
            ).values(rejection_error=message or "Provider rejected submission"))
            if result.rowcount != 1:
                raise ValueError("PROVIDER_TASK_BINDING_MISMATCH")

    def accept_provider_task(self, job_id: str, token: str, slot: str, remote_task_id: str, *,
                             now: float | None = None) -> None:
        if not isinstance(remote_task_id, str) or not remote_task_id.strip():
            raise ValueError("INVALID_PROVIDER_TASK_ID")
        now = time.time() if now is None else now
        with self.transaction() as connection:
            self._live_attempt(connection, job_id, token, now)
            row = connection.execute(select(provider_tasks).where(
                provider_tasks.c.job_id == job_id, provider_tasks.c.slot == slot,
            )).mappings().one()
            if row["remote_task_id"] not in {None, remote_task_id}:
                raise ValueError("PROVIDER_TASK_BINDING_MISMATCH")
            connection.execute(update(provider_tasks).where(
                provider_tasks.c.job_id == job_id, provider_tasks.c.slot == slot,
            ).values(remote_task_id=remote_task_id))

    def finish_job_attempt(self, job_id: str, token: str, *, uncertain: bool = False) -> None:
        with self.transaction() as connection:
            connection.execute(update(job_attempts).where(
                job_attempts.c.job_id == job_id, job_attempts.c.attempt_token == token,
                job_attempts.c.phase == "running",
            ).values(phase="reconciliation_required" if uncertain else "finished"))

    def save_job_result(self, owner: str, snapshot: dict[str, Any], *, allow_ownerless: bool = False,
                        attempt_token: str | None = None) -> dict[str, Any]:
        """Commit terminal result and its generic events in one transaction."""
        if not isinstance(owner, str) or not owner.strip() or snapshot["status"] not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("INVALID_JOB_RESULT")
        digest = command_digest(snapshot)
        job_id = snapshot["id"]
        with self.transaction() as connection:
            if snapshot["status"] == "cancelled":
                # Serialize cancellation with generation commits and revocation
                # of the current worker, even when the JSON projection is stale.
                try:
                    with connection.begin_nested():
                        connection.execute(insert(job_attempts).values(
                            job_id=job_id, owner_user_id=owner, attempt_token=uuid.uuid4().hex, phase="finished",
                        ))
                except IntegrityError:
                    pass
                attempt = connection.execute(select(job_attempts).where(job_attempts.c.job_id == job_id)
                                             .with_for_update()).mappings().one()
                if attempt["owner_user_id"] != owner:
                    raise ValueError("JOB_RESULT_BINDING_MISMATCH")
            if attempt_token is not None:
                attempt = self._live_attempt(connection, job_id, attempt_token, time.time())
                if attempt["owner_user_id"] != owner:
                    raise ValueError("JOB_ATTEMPT_MISMATCH")
            try:
                with connection.begin_nested():
                    connection.execute(insert(job_results).values(
                        job_id=job_id, owner_user_id=owner, canvas_id=snapshot["canvas_id"],
                        node_id=snapshot["node_id"], resource_version=0, operation_id="initial",
                        snapshot="{}", command_digest="", projection_status="pending",
                        allow_ownerless=allow_ownerless,
                    ))
            except IntegrityError:
                pass
            row = connection.execute(select(job_results).where(job_results.c.job_id == job_id)
                                     .with_for_update()).mappings().one()
            if (row["owner_user_id"], row["canvas_id"], row["node_id"]) != (owner, snapshot["canvas_id"], snapshot["node_id"]):
                raise ValueError("JOB_RESULT_BINDING_MISMATCH")
            prior = json.loads(row["snapshot"])
            if prior.get("status") == "cancelled" or (
                snapshot["status"] == "cancelled" and (
                    prior.get("status") == "succeeded" or
                    prior.get("status") == "failed" and attempt["phase"] == "finished"
                )
            ):
                return dict(row)
            if row["command_digest"] == digest:
                if attempt_token is not None:
                    connection.execute(update(job_attempts).where(job_attempts.c.job_id == job_id)
                                       .values(phase="finished"))
                return dict(row)
            if prior.get("status") == "succeeded":
                raise ValueError("JOB_RESULT_ALREADY_SUCCEEDED")
            version = row["resource_version"] + 1
            operation_id = f"job-result/{job_id}/{version}"
            values = dict(resource_version=version, operation_id=operation_id,
                          snapshot=json.dumps(snapshot, allow_nan=False), command_digest=digest,
                          projection_status="pending")
            connection.execute(update(job_results).where(job_results.c.job_id == job_id).values(**values))
            if snapshot["status"] == "succeeded":
                self._advance_node_result(connection, snapshot)
            payload = {key: snapshot[key] for key in (
                "canvas_id", "node_id", "provider_id", "model_id", "capability", "status", "updated_at",
            )}
            payload.update(job_id=job_id, asset_ids=[asset["id"] for asset in snapshot["outputs"]],
                           output_count=len(snapshot["outputs"]))
            event_type = "resource.changed" if snapshot["status"] == "cancelled" else f"job.{snapshot['status']}"
            events = [(event_type, job_id, payload)]
            if snapshot["status"] == "succeeded":
                events.extend(("asset.ready", asset["id"], {**payload, "asset_id": asset["id"], "kind": asset["kind"]})
                              for asset in snapshot["outputs"])
            stamp = time.time()
            for index, (event_type, resource_id, event_payload) in enumerate(events):
                event = AigcDomainEvent(event_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{operation_id}/{index}")),
                                        owner_user_id=owner, resource_id=resource_id, resource_version=version,
                                        operation_id=operation_id, event_type=event_type, payload=event_payload)
                connection.execute(insert(domain_events).values(
                    event_id=event.event_id, owner_user_id=owner, resource_id=resource_id,
                    resource_version=version, event_type=event_type,
                    event=event.model_dump_json(), created_at=stamp + index * 0.000001,
                ))
            if attempt_token is not None:
                connection.execute(update(job_attempts).where(job_attempts.c.job_id == job_id)
                                   .values(phase="finished"))
            if snapshot["status"] == "cancelled":
                connection.execute(update(job_attempts).where(job_attempts.c.job_id == job_id)
                                   .values(phase="cancelled", lease_until=0))
            return {**dict(row), **values}

    @staticmethod
    def _advance_node_result(connection: Connection, snapshot: dict[str, Any]) -> None:
        # Physical canvas IDs are global. Legacy ownerless canvases may have
        # multiple authorized administrators, but still only one current output.
        key = dict(canvas_id=snapshot["canvas_id"], node_id=snapshot["node_id"])
        match = and_(*(node_results.c[name] == value for name, value in key.items()))
        stamp = job_creation_timestamp(snapshot)
        try:
            with connection.begin_nested():
                connection.execute(insert(node_results).values(**key, job_id=snapshot["id"], job_created_at=stamp))
        except IntegrityError:
            pass
        current = connection.execute(select(node_results).where(match).with_for_update()).mappings().one()
        if stamp >= current["job_created_at"]:
            connection.execute(update(node_results).where(match).values(job_id=snapshot["id"], job_created_at=stamp))

    def get_node_result(self, canvas_id: str, node_id: str) -> dict[str, Any] | None:
        """Read the canonical successful output head; caller authorizes its scope."""
        with self.engine.connect() as connection:
            row = connection.execute(select(node_results).where(
                node_results.c.canvas_id == canvas_id, node_results.c.node_id == node_id,
            )).mappings().one_or_none()
        return dict(row) if row else None

    def pending_job_results(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(select(job_results).where(
                job_results.c.projection_status == "pending",
            ).order_by(job_results.c.projection_attempted_at, job_results.c.job_id)
                .limit(max(0, min(limit, 100)))).mappings()]

    def project_job_result(self, job_id: str, project: Callable[[dict[str, Any]], None]) -> bool:
        """Serialize projections with result updates; never replay a stale snapshot."""
        with self.transaction() as connection:
            row = connection.execute(select(job_results).where(job_results.c.job_id == job_id)
                                     .with_for_update()).mappings().one()
            if row["projection_status"] == "applied":
                return True
            head = connection.execute(select(node_results.c.job_id).where(
                node_results.c.canvas_id == row["canvas_id"], node_results.c.node_id == row["node_id"],
            ).with_for_update()).scalar_one_or_none()
            try:
                project({**dict(row), "project_node": head == job_id})
            except Exception:
                applied = False
            else:
                applied = True
            connection.execute(update(job_results).where(job_results.c.job_id == job_id).values(
                projection_status="applied" if applied else "pending",
                projection_attempted_at=time.time(),
            ))
            return applied

    def list_domain_events(self, limit: int = 100) -> list[AigcDomainEvent]:
        with self.engine.connect() as connection:
            return [AigcDomainEvent.model_validate_json(value) for value in connection.execute(
                select(domain_events.c.event).order_by(domain_events.c.created_at, domain_events.c.event_id)
                .limit(max(0, min(limit, 100))),
            ).scalars()]

    def claim_domain_events(self, consumer_id: str, *, now: float,
                            limit: int = 100, lease_seconds: float = 30) -> list[dict[str, Any]]:
        if (not consumer_id.strip() or not math.isfinite(now) or not math.isfinite(lease_seconds)
                or not math.isfinite(now + lease_seconds) or lease_seconds <= 0):
            raise ValueError("INVALID_EVENT_CONSUMER")
        ready = or_(
            and_(deliveries.c.status == "pending", deliveries.c.next_attempt <= now),
            and_(deliveries.c.status == "inflight", deliveries.c.lease_until <= now),
        )
        result = []
        with self.transaction() as connection:
            candidates = connection.execute(select(domain_events.c.event_id, domain_events.c.event)
                .select_from(domain_events.outerjoin(deliveries, and_(
                    deliveries.c.event_id == domain_events.c.event_id,
                    deliveries.c.consumer_id == consumer_id,
                ))).where(or_(deliveries.c.event_id.is_(None), ready))
                .order_by(domain_events.c.created_at, domain_events.c.event_id)
                .limit(max(0, min(limit, 100)))
                .with_for_update(of=domain_events, skip_locked=True)).mappings().all()
            for item in candidates:
                try:
                    with connection.begin_nested():
                        connection.execute(insert(deliveries).values(
                            event_id=item["event_id"], consumer_id=consumer_id,
                            status="pending", attempts=0, next_attempt=0, lease_until=0,
                        ))
                except IntegrityError:
                    pass
                token = uuid.uuid4().hex
                changed = connection.execute(update(deliveries).where(
                    deliveries.c.event_id == item["event_id"], deliveries.c.consumer_id == consumer_id, ready,
                ).values(status="inflight", attempts=deliveries.c.attempts + 1,
                         lease_token=token, lease_until=now + lease_seconds))
                if changed.rowcount == 1:
                    result.append({"event": AigcDomainEvent.model_validate_json(item["event"]), "lease_token": token})
        return result

    def complete_domain_delivery(self, consumer_id: str, event_id: str, lease_token: str, *,
                                 now: float, outcome: str = "delivered", error_code: str | None = None) -> bool:
        if outcome not in {"delivered", "blocked", "retry"}:
            raise ValueError("INVALID_DELIVERY_OUTCOME")
        if error_code is not None and not re.fullmatch(r"[A-Z0-9_]{1,80}", error_code):
            raise ValueError("INVALID_DELIVERY_ERROR_CODE")
        with self.transaction() as connection:
            match = and_(deliveries.c.consumer_id == consumer_id, deliveries.c.event_id == event_id,
                         deliveries.c.status == "inflight", deliveries.c.lease_token == lease_token,
                         deliveries.c.lease_until > now)
            row = connection.execute(select(deliveries).where(match).with_for_update()).mappings().one_or_none()
            if row is None:
                return False
            delay = [5, 15, 60, 300][min(row["attempts"] - 1, 3)]
            updated = connection.execute(update(deliveries).where(match).values(
                status="pending" if outcome == "retry" else outcome,
                lease_token=None, lease_until=0, error_code=error_code,
                next_attempt=now + delay if outcome == "retry" else 0,
            ))
            return updated.rowcount == 1
