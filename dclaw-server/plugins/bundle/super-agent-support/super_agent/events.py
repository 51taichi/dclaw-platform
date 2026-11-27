"""Bound event envelope and idempotent persistence for platform workflows."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from qwenpaw.app.storage.json_file_lock import JsonFileLock


class SuperExpertEventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    installation_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    agent_task_id: str = Field(min_length=1)
    content_revision: int = Field(ge=0)
    material_task_id: str = Field(min_length=1)
    canvas_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    asset_id: str | None = None
    event_type: str = Field(
        pattern=(
            r"^(card\.created|card\.updated|aigc\.task\.created|"
            r"aigc\.task\.resumed|aigc\.task\.cancelled|"
            r"aigc\.guide\.updated|aigc\.asset\.submitted|"
            r"aigc\.asset\.completed|"
            r"aigc\.review\.completed)$"
        ),
    )
    payload: dict[str, Any] = Field(default_factory=dict)


class _EventDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    events: dict[str, SuperExpertEventEnvelope] = Field(default_factory=dict)
    review_receipts: dict[str, dict[str, Any]] = Field(default_factory=dict)


class SuperExpertEventRepository:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "super_expert_events.json"
        self._lock = threading.RLock()
        self._file_lock = JsonFileLock(self.root)

    def append(self, event: SuperExpertEventEnvelope) -> bool:
        with self._lock, self._file_lock.hold(self.path):
            document = self._read()
            existing = document.events.get(event.event_id)
            if existing is not None:
                if existing != event:
                    raise ValueError(
                        "event id is already bound to another envelope",
                    )
                return False
            document.events[event.event_id] = event
            self._write(document)
            return True

    def get(self, event_id: str) -> SuperExpertEventEnvelope | None:
        with self._lock:
            return self._read().events.get(event_id)

    def list_for_session(
        self,
        *,
        installation_id: str,
        conversation_id: str,
    ) -> tuple[SuperExpertEventEnvelope, ...]:
        """Return the append-ordered event stream for one trusted binding scope."""
        if not installation_id or not conversation_id:
            return ()
        with self._lock:
            return tuple(
                event
                for event in self._read().events.values()
                if event.installation_id == installation_id
                and event.conversation_id == conversation_id
            )

    def get_review_receipt(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            receipt = self._read().review_receipts.get(event_id)
            return dict(receipt) if receipt is not None else None

    def save_review_receipt(
        self,
        event_id: str,
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        if not event_id or not isinstance(receipt.get("reply"), str):
            raise ValueError("agent review receipt is invalid")
        with self._lock, self._file_lock.hold(self.path):
            document = self._read()
            existing = document.review_receipts.get(event_id)
            if existing is not None:
                if existing != receipt:
                    raise ValueError("agent review receipt is immutable")
                return dict(existing)
            document.review_receipts[event_id] = dict(receipt)
            self._write(document)
            return dict(receipt)

    def _read(self) -> _EventDocument:
        if not self.path.exists():
            return _EventDocument()
        try:
            return _EventDocument.model_validate_json(
                self.path.read_text(encoding="utf-8"),
            )
        except (OSError, ValidationError, ValueError) as exc:
            raise ValueError(
                "super expert event repository is invalid",
            ) from exc

    def _write(self, document: _EventDocument) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                document.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
