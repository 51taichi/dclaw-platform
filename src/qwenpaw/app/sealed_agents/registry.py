"""Atomic metadata registry for optional sealed agents."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ...constant import WORKING_DIR
from .models import SealedAgentRecord

logger = logging.getLogger(__name__)


class _RegistryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    agents: list[SealedAgentRecord] = Field(default_factory=list)


class SealedAgentRegistry:
    """Small process-safe registry whose absence never blocks DClaw."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "registry.json"
        self._lock = threading.RLock()

    def list_agents(self) -> list[SealedAgentRecord]:
        with self._lock:
            document = self._read()
        return list(document.agents)

    def get_agent(self, agent_id: str) -> SealedAgentRecord | None:
        return next(
            (
                agent
                for agent in self.list_agents()
                if agent.agent_id == agent_id
            ),
            None,
        )

    def is_sealed(self, agent_id: str) -> bool:
        return self.get_agent(agent_id) is not None

    def upsert_agent(self, record: SealedAgentRecord) -> SealedAgentRecord:
        with self._lock:
            agents = self._read().agents
            replaced = False
            updated: list[SealedAgentRecord] = []
            for current in agents:
                if current.agent_id == record.agent_id:
                    updated.append(record)
                    replaced = True
                else:
                    updated.append(current)
            if not replaced:
                updated.append(record)
            self._write(_RegistryDocument(agents=updated))
        return record

    def _read(self) -> _RegistryDocument:
        if not self.path.exists():
            return _RegistryDocument()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return _RegistryDocument.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            logger.error("Ignoring invalid sealed agent registry: %s", exc)
            return _RegistryDocument()

    def _write(self, document: _RegistryDocument) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / "registry.json.tmp"
        temporary.write_text(
            json.dumps(
                document.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)


_registry: SealedAgentRegistry | None = None
_registry_lock = threading.Lock()


def get_sealed_agent_registry() -> SealedAgentRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = SealedAgentRegistry(Path(WORKING_DIR) / "sealed_agents")
        return _registry
