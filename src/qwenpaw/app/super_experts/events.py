"""Bound event envelope and idempotent persistence for platform workflows."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


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
            r"aigc\.review\.completed)$"
        ),
    )
    payload: dict[str, Any] = Field(default_factory=dict)


class _EventDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    events: dict[str, SuperExpertEventEnvelope] = Field(default_factory=dict)


class SuperExpertEventRepository:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "super_expert_events.json"
        self._lock = threading.RLock()

    def append(self, event: SuperExpertEventEnvelope) -> bool:
        with self._lock:
            document = self._read()
            existing = document.events.get(event.event_id)
            if existing is not None:
                if existing != event:
                    raise ValueError("event id is already bound to another envelope")
                return False
            document.events[event.event_id] = event
            self._write(document)
            return True

    def get(self, event_id: str) -> SuperExpertEventEnvelope | None:
        with self._lock:
            return self._read().events.get(event_id)

    def _read(self) -> _EventDocument:
        if not self.path.exists():
            return _EventDocument()
        try:
            return _EventDocument.model_validate_json(
                self.path.read_text(encoding="utf-8"),
            )
        except (OSError, ValidationError, ValueError) as exc:
            raise ValueError("super expert event repository is invalid") from exc

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
