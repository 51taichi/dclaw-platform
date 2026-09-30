"""Read-only export of one Agent and its isolated OpenAPI knowledge source."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...config.utils import load_config
from ...constant import WORKING_DIR
from ...mindspace import MindspaceScope
from ..open_api.knowledge import publication_knowledge_service
from ..sealed_agents.registry import (
    SealedAgentRegistry,
    get_sealed_agent_registry,
)
from .archive import (
    SnapshotArchiveError,
    build_deterministic_archive,
    collect_directory_files,
    deterministic_digest,
)
from .service import (
    DclawConfigurationContextService,
    get_dclaw_configuration_context_service,
)


class SnapshotExportError(RuntimeError):
    def __init__(self, code: str, missing_items: list[str]) -> None:
        self.code = code
        self.missing_items = list(missing_items)
        super().__init__(code)


@dataclass(frozen=True)
class ExportedDclawSnapshot:
    archive: bytes
    agent_id: str
    profile_id: str
    source_version: str
    agent_digest: str
    knowledge_digest: str


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_document_name(value: str) -> str:
    normalized = value.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."}:
        raise SnapshotArchiveError("unsafe knowledge document name")
    return name


class DclawSnapshotExporter:
    def __init__(
        self,
        *,
        context_service: DclawConfigurationContextService | Any | None = None,
        config_loader: Callable[[], Any] = load_config,
        sealed_registry: SealedAgentRegistry | Any | None = None,
        sealed_root: Path | None = None,
        knowledge_service_factory: Callable[[dict[str, Any]], Any] = (
            publication_knowledge_service
        ),
    ) -> None:
        self._context_service = (
            context_service or get_dclaw_configuration_context_service()
        )
        self._config_loader = config_loader
        self._sealed_registry = sealed_registry or get_sealed_agent_registry()
        self._sealed_root = Path(
            sealed_root or Path(WORKING_DIR) / "sealed_agents",
        )
        self._knowledge_service_factory = knowledge_service_factory

    def export(self, agent_id: str) -> ExportedDclawSnapshot:
        context = self._context_service.describe(agent_id)
        if not context.readiness.ready:
            raise SnapshotExportError(
                "ADMIN_BOOTSTRAP_REQUIRED",
                context.readiness.missing_items,
            )
        try:
            agent_files = collect_directory_files(
                self._agent_source_root(agent_id, context.agent_type),
                prefix="agent",
            )
        except SnapshotArchiveError as exc:
            missing = (
                "agent_source_snapshot"
                if "unavailable" in str(exc)
                else "agent_source_security"
            )
            raise SnapshotExportError(
                "ADMIN_BOOTSTRAP_REQUIRED",
                [missing],
            ) from exc

        publication = self._context_service.resolve_publication(agent_id)
        if publication is None:
            raise SnapshotExportError(
                "ADMIN_BOOTSTRAP_REQUIRED",
                ["openapi_publication"],
            )
        try:
            knowledge_files = self._knowledge_files(publication)
        except (OSError, SnapshotArchiveError, ValueError) as exc:
            raise SnapshotExportError(
                "ADMIN_BOOTSTRAP_REQUIRED",
                ["knowledge_source_snapshot"],
            ) from exc

        agent_digest = deterministic_digest(agent_files)
        knowledge_digest = deterministic_digest(knowledge_files)
        profile_id = context.agent_profile_id or "unknown"
        source_version = context.source_version or "unknown"
        component = {
            "agentDigest": agent_digest,
            "agentId": agent_id,
            "agentProfileId": profile_id,
            "knowledgeBaseId": context.knowledge_base_id,
            "knowledgeDigest": knowledge_digest,
            "sourceVersion": source_version,
        }
        archive_files = {
            **agent_files,
            **knowledge_files,
            "dclaw-component.json": _canonical_json(component),
        }
        return ExportedDclawSnapshot(
            archive=build_deterministic_archive(archive_files),
            agent_id=agent_id,
            profile_id=profile_id,
            source_version=source_version,
            agent_digest=agent_digest,
            knowledge_digest=knowledge_digest,
        )

    def _agent_source_root(self, agent_id: str, agent_type: str) -> Path:
        if agent_type == "sealed":
            record = self._sealed_registry.get_agent(agent_id)
            active = record.active_release if record is not None else None
            if active is None:
                return self._sealed_root / "missing-source"
            return (
                self._sealed_root
                / "releases"
                / agent_id
                / active.release_id
                / "agent"
            )
        config = self._config_loader()
        ref = config.agents.profiles.get(agent_id)
        if ref is None:
            return Path(WORKING_DIR) / "missing-source"
        return Path(ref.workspace_dir).expanduser()

    def _knowledge_files(self, publication: dict[str, Any]) -> dict[str, bytes]:
        service = self._knowledge_service_factory(publication)
        documents = service.list_documents(MindspaceScope.PERSONAL)
        result: dict[str, bytes] = {}
        manifest_documents: list[dict[str, Any]] = []
        for document in sorted(documents, key=lambda item: item.id):
            name = _safe_document_name(document.name)
            relative = f"documents/{document.id}/{name}"
            path = f"knowledge/{relative}"
            result[path] = self._read_document_source(service, document.id)
            manifest_documents.append(
                {
                    "category": document.category,
                    "id": document.id,
                    "name": document.name,
                    "path": relative,
                    "sourceType": document.source_type,
                    "tags": list(document.tags),
                },
            )
        result["knowledge/knowledge-manifest.json"] = _canonical_json(
            {"documents": manifest_documents},
        )
        return result

    @staticmethod
    def _read_document_source(service: Any, doc_id: str) -> bytes:
        reader = getattr(service, "read_document_source", None)
        if callable(reader):
            return bytes(reader(doc_id))
        asset = service._first_asset(doc_id, kind="raw")  # noqa: SLF001
        if not asset:
            raise OSError("knowledge source asset is unavailable")
        return Path(str(asset["storage_path"])).read_bytes()


def get_dclaw_snapshot_exporter() -> DclawSnapshotExporter:
    return DclawSnapshotExporter()

