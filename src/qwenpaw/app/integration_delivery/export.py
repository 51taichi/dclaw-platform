"""Read-only export of one Agent and its isolated OpenAPI knowledge source."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ...config.utils import load_config
from ...constant import WORKING_DIR
from ...mindspace import MindspaceScope
from ..open_api.knowledge import publication_knowledge_service
from ..sealed_agents.registry import (
    SealedAgentRegistry,
    get_sealed_agent_registry,
)
from .archive import (
    ArchiveLimits,
    SnapshotArchiveError,
    build_deterministic_archive,
    collect_directory_files,
    deterministic_digest,
    read_bounded_regular_file,
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


_SENSITIVE_KEY_SUFFIXES = (
    "authorization",
    "credential",
    "credentials",
    "password",
    "privatekey",
    "signingkey",
    "sessionkey",
    "accesskey",
    "secret",
    "token",
    "apikey",
    "cookie",
    "auth",
    "bearer",
)
_OMITTED_RUNTIME_KEYS = {
    "channels",
    "cwd",
    "lastdispatch",
    "workspacedir",
}
_EMBEDDED_SECRET = re.compile(
    rb"(?im)(?:"
    rb"-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    rb"\bauthorization\s*:\s*(?:bearer|basic)\s+[A-Za-z0-9+/_.=-]{8,}|"
    rb"\b(?:[A-Z][A-Z0-9_]*_)?(?:TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY|ACCESS_KEY)"
    rb"\s*[:=]\s*['\"]?"
    rb"(?!(?:os\.|getenv|process\.|env\.|config\.|settings\.|"
    rb"\$\{|<|your[_-]|replace[_-]|example|x{8}))"
    rb"[A-Za-z0-9+/_.=-]{8,}|"
    rb"https?://[^\s]+[?&](?:api_?key|token|secret|password)=[^&\s]+"
    rb")"
)

_AGENT_RUNTIME_ROOT_DIRS = frozenset(
    {
        ".cache",
        ".git",
        ".pytest_cache",
        ".thumbnails",
        "__pycache__",
        "backup",
        "browser",
        "cloud_docs",
        "dialog",
        "embedding_cache",
        "file_store",
        "logs",
        "media",
        "memory",
        "missions",
        "renders",
        "sessions",
        "sessions_data",
        "tool_result",
        "tool_results",
    }
)
_AGENT_RUNTIME_ROOT_FILES = frozenset(
    {
        ".DS_Store",
        ".bootstrap_completed",
        ".skill.json.lock",
        "chats.json",
        "cloud_docs.json",
        "jobs.json",
        "memory_file_metadata.json",
        "overview.md.lock",
        "qwenpaw_app.log",
        "qwenpaw_app_new.log",
        "token_usage.json",
    }
)


def _is_agent_runtime_path(path: PurePosixPath) -> bool:
    if not path.parts:
        return True
    if path.parts[0] in _AGENT_RUNTIME_ROOT_DIRS:
        return True
    if any(part in {"__pycache__", ".pytest_cache"} for part in path.parts):
        return True
    if len(path.parts) == 1:
        name = path.name
        return (
            name in _AGENT_RUNTIME_ROOT_FILES
            or name.startswith(".reme_store_")
        )
    return False


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _is_sensitive_key(value: str) -> bool:
    return any(value.endswith(suffix) for suffix in _SENSITIVE_KEY_SUFFIXES)


def _is_absolute_runtime_path(key: str, value: Any) -> bool:
    if not isinstance(value, str):
        return False
    path_key = key.endswith(
        ("path", "dir", "directory", "executable", "command")
    )
    return path_key and bool(
        value.startswith(("/", "\\\\"))
        or re.match(r"^[A-Za-z]:[\\/]", value)
    )


def _redacted_shape(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redacted_shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return ["" for _ in value]
    return ""


def _sanitize_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return value
    hostname = parsed.hostname or ""
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    try:
        port = parsed.port
    except ValueError:
        return ""
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _sanitize_args(value: Any) -> Any:
    if not isinstance(value, list):
        return _redacted_shape(value)
    # Arbitrary command-line syntax can encode credentials without a reliable
    # schema (-u, headers, cookies, DSNs, positional values). Runtime args are
    # therefore never part of an employee-downloadable source snapshot.
    return []


def _sanitize_config(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = _normalized_key(key)
            if normalized in _OMITTED_RUNTIME_KEYS:
                continue
            if _is_absolute_runtime_path(normalized, item):
                sanitized[key] = ""
            elif parent_key in {"headers", "env"}:
                sanitized[key] = _redacted_shape(item)
            elif _is_sensitive_key(normalized):
                sanitized[key] = _redacted_shape(item)
            elif normalized == "args":
                sanitized[key] = _sanitize_args(item)
            elif normalized.endswith(("url", "endpoint")) and isinstance(item, str):
                sanitized[key] = _sanitize_url(item)
            else:
                sanitized[key] = _sanitize_config(item, parent_key=normalized)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_config(item, parent_key=parent_key) for item in value]
    return value


def _sanitize_agent_files(files: dict[str, bytes]) -> dict[str, bytes]:
    result = dict(files)
    for path, content in files.items():
        if not path.startswith("agent/") or not path.endswith(".json"):
            continue
        try:
            parsed = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if path == "agent/agent.json":
                raise SnapshotArchiveError("Agent manifest is invalid") from exc
            continue
        result[path] = _canonical_json(_sanitize_config(parsed))
    for path, content in result.items():
        if _EMBEDDED_SECRET.search(content):
            raise SnapshotArchiveError(
                f"Agent source contains an embedded credential: {path}"
            )
    return result


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
        archive_limits: ArchiveLimits = ArchiveLimits(),
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
        self._archive_limits = archive_limits

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
                limits=self._archive_limits,
                exclude=_is_agent_runtime_path,
            )
            agent_files = _sanitize_agent_files(agent_files)
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
            agent_bytes = sum(len(content) for content in agent_files.values())
            knowledge_files = self._knowledge_files(
                publication,
                agent_file_count=len(agent_files),
                remaining_total_bytes=(
                    self._archive_limits.max_total_bytes - agent_bytes
                ),
            )
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

    def _knowledge_files(
        self,
        publication: dict[str, Any],
        *,
        agent_file_count: int,
        remaining_total_bytes: int,
    ) -> dict[str, bytes]:
        service = self._knowledge_service_factory(publication)
        documents = service.list_documents(MindspaceScope.PERSONAL)
        if len(documents) + agent_file_count + 2 > self._archive_limits.max_files:
            raise SnapshotArchiveError("archive has too many files")
        result: dict[str, bytes] = {}
        manifest_documents: list[dict[str, Any]] = []
        for document in sorted(documents, key=lambda item: item.id):
            name = _safe_document_name(document.name)
            relative = f"documents/{document.id}/{name}"
            path = f"knowledge/{relative}"
            max_bytes = min(
                self._archive_limits.max_file_bytes,
                remaining_total_bytes,
            )
            declared_size = int(getattr(document, "byte_size", 0) or 0)
            if declared_size > max_bytes:
                raise SnapshotArchiveError("single file exceeds archive limit")
            content = self._read_document_source(
                service,
                document.id,
                max_bytes=max_bytes,
            )
            remaining_total_bytes -= len(content)
            result[path] = content
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
        manifest = _canonical_json(
            {"documents": manifest_documents},
        )
        if len(manifest) > self._archive_limits.max_file_bytes:
            raise SnapshotArchiveError("single file exceeds archive limit")
        if len(manifest) > remaining_total_bytes:
            raise SnapshotArchiveError("archive total size exceeds limit")
        result["knowledge/knowledge-manifest.json"] = manifest
        return result

    @staticmethod
    def _read_document_source(
        service: Any,
        doc_id: str,
        *,
        max_bytes: int,
    ) -> bytes:
        if max_bytes < 0:
            raise SnapshotArchiveError("archive total size exceeds limit")
        reader = getattr(service, "read_document_source", None)
        if callable(reader):
            content = bytes(reader(doc_id))
            if len(content) > max_bytes:
                raise SnapshotArchiveError("single file exceeds archive limit")
            return content
        asset = service._first_asset(doc_id, kind="raw")  # noqa: SLF001
        if not asset:
            raise OSError("knowledge source asset is unavailable")
        return read_bounded_regular_file(
            Path(str(asset["storage_path"])),
            max_bytes=max_bytes,
        )


def get_dclaw_snapshot_exporter() -> DclawSnapshotExporter:
    return DclawSnapshotExporter()
