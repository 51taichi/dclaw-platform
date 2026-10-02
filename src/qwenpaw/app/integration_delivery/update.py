"""Validation primitives for integration delivery updates."""

from __future__ import annotations

import io
import json
import shutil
import stat
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ...config.utils import load_config
from .archive import (
    ArchiveLimits,
    SnapshotArchiveError,
    _normalize_path,
    collect_directory_files,
    deterministic_digest,
)
from .export import _is_agent_runtime_path
from .models import DeliveryValidation


class DeliveryBundleError(ValueError):
    """A delivery bundle is unsafe or does not match its target."""


@dataclass(frozen=True, slots=True)
class ParsedDeliveryBundle:
    archive: bytes
    agent_id: str
    agent_profile_id: str
    source_version: str
    agent_digest: str
    knowledge_digest: str
    knowledge_base_id: str | None
    agent_files: dict[str, bytes]
    knowledge_files: dict[str, bytes]


@dataclass(frozen=True, slots=True)
class AgentApplyReceipt:
    operation_id: str
    agent_id: str
    workspace_dir: Path
    backup_dir: Path
    agent_digest_before: str
    agent_digest_after: str


def _read_archive(archive_bytes: bytes) -> dict[str, bytes]:
    limits = ArchiveLimits()
    if len(archive_bytes) > 200 * 1024 * 1024:
        raise DeliveryBundleError("delivery bundle is invalid")
    result: dict[str, bytes] = {}
    portable_seen: set[str] = set()
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            entries = archive.infolist()
            if len(entries) > limits.max_files:
                raise DeliveryBundleError("delivery bundle is invalid")
            for entry in entries:
                path = _normalize_path(entry.filename)
                portable_key = path.casefold()
                mode = entry.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                if (
                    path in result
                    or portable_key in portable_seen
                    or entry.is_dir()
                    or file_type not in {0, stat.S_IFREG}
                    or entry.flag_bits & 0x1
                    or (
                        path != "dclaw-component.json"
                        and not path.startswith(("agent/", "knowledge/"))
                    )
                    or entry.file_size > limits.max_file_bytes
                    or (
                        entry.file_size > 1024 * 1024
                        and entry.file_size > max(1, entry.compress_size) * 200
                    )
                ):
                    raise DeliveryBundleError("delivery bundle is invalid")
                total += entry.file_size
                if total > limits.max_total_bytes:
                    raise DeliveryBundleError("delivery bundle is invalid")
                portable_seen.add(portable_key)
                content = archive.read(entry)
                if len(content) != entry.file_size:
                    raise DeliveryBundleError("delivery bundle is invalid")
                result[path] = content
    except (OSError, RuntimeError, SnapshotArchiveError, zipfile.BadZipFile) as exc:
        raise DeliveryBundleError("delivery bundle is invalid") from exc
    return result


def _json_object(content: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeliveryBundleError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise DeliveryBundleError(f"{label} is invalid")
    return value


def parse_delivery_bundle(agent_id: str, archive: bytes) -> ParsedDeliveryBundle:
    files = _read_archive(bytes(archive))
    try:
        component_bytes = files.pop("dclaw-component.json")
        agent_manifest_bytes = files["agent/agent.json"]
        knowledge_manifest_bytes = files["knowledge/knowledge-manifest.json"]
    except KeyError as exc:
        raise DeliveryBundleError("delivery bundle is invalid") from exc

    component = _json_object(component_bytes, label="component manifest")
    agent_manifest = _json_object(agent_manifest_bytes, label="Agent manifest")
    knowledge_manifest = _json_object(
        knowledge_manifest_bytes,
        label="knowledge manifest",
    )
    component_agent_id = str(component.get("agentId") or "")
    manifest_agent_id = str(agent_manifest.get("id") or "")
    if agent_id != component_agent_id or agent_id != manifest_agent_id:
        raise DeliveryBundleError("agent identity mismatch")

    agent_files = {
        path: content for path, content in files.items() if path.startswith("agent/")
    }
    knowledge_files = {
        path: content
        for path, content in files.items()
        if path.startswith("knowledge/")
    }
    if not agent_files or not knowledge_files:
        raise DeliveryBundleError("delivery bundle is invalid")

    documents = knowledge_manifest.get("documents")
    if not isinstance(documents, list):
        raise DeliveryBundleError("knowledge manifest is invalid")
    for document in documents:
        if not isinstance(document, dict):
            raise DeliveryBundleError("knowledge manifest is invalid")
        relative = document.get("path")
        if not isinstance(relative, str) or f"knowledge/{relative}" not in knowledge_files:
            raise DeliveryBundleError("knowledge manifest is invalid")

    agent_digest = deterministic_digest(agent_files)
    knowledge_digest = deterministic_digest(knowledge_files)
    if (
        component.get("agentDigest") != agent_digest
        or component.get("knowledgeDigest") != knowledge_digest
    ):
        raise DeliveryBundleError("component digest mismatch")
    profile_id = component.get("agentProfileId")
    source_version = component.get("sourceVersion")
    if not isinstance(profile_id, str) or not profile_id:
        raise DeliveryBundleError("component manifest is invalid")
    if not isinstance(source_version, str) or not source_version:
        raise DeliveryBundleError("component manifest is invalid")
    knowledge_base_id = component.get("knowledgeBaseId")
    if knowledge_base_id is not None and not isinstance(knowledge_base_id, str):
        raise DeliveryBundleError("component manifest is invalid")
    return ParsedDeliveryBundle(
        archive=bytes(archive),
        agent_id=agent_id,
        agent_profile_id=profile_id,
        source_version=source_version,
        agent_digest=agent_digest,
        knowledge_digest=knowledge_digest,
        knowledge_base_id=knowledge_base_id,
        agent_files=agent_files,
        knowledge_files=knowledge_files,
    )


def validate_delivery_bundle(
    agent_id: str,
    archive: bytes,
    expected_agent_digest: str,
    expected_knowledge_digest: str,
) -> DeliveryValidation:
    parsed = parse_delivery_bundle(agent_id, archive)
    if (
        parsed.agent_digest != expected_agent_digest
        or parsed.knowledge_digest != expected_knowledge_digest
    ):
        raise DeliveryBundleError("component digest mismatch")
    return DeliveryValidation(
        agent_id=parsed.agent_id,
        agent_profile_id=parsed.agent_profile_id,
        source_version=parsed.source_version,
        agent_digest=parsed.agent_digest,
        knowledge_digest=parsed.knowledge_digest,
    )


def _standard_workspace(agent_id: str) -> Path:
    config = load_config()
    profiles = config.agents.profiles if config.agents else {}
    profile = profiles.get(agent_id)
    if profile is None or not getattr(profile, "enabled", True):
        raise DeliveryBundleError("standard Agent is unavailable")
    workspace = Path(profile.workspace_dir).expanduser()
    if not workspace.is_dir():
        raise DeliveryBundleError("standard Agent is unavailable")
    return workspace


def _source_digest(workspace: Path) -> str:
    return deterministic_digest(
        collect_directory_files(
            workspace,
            prefix="agent",
            exclude=_is_agent_runtime_path,
        )
    )


def _remove_source_files(workspace: Path) -> None:
    for candidate in sorted(
        workspace.rglob("*"),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        relative = PurePosixPath(*candidate.relative_to(workspace).parts)
        if _is_agent_runtime_path(relative):
            continue
        if candidate.is_symlink() or candidate.is_file():
            candidate.unlink()
        elif candidate.is_dir():
            try:
                candidate.rmdir()
            except OSError:
                pass


def _temporary_sibling(workspace: Path, label: str) -> Path:
    workspace.parent.mkdir(parents=True, exist_ok=True)
    return Path(
        tempfile.mkdtemp(
            prefix=f".{workspace.name}.{label}-",
            dir=workspace.parent,
        )
    )


def apply_standard_agent_source(
    bundle: ParsedDeliveryBundle,
    operation_id: str,
    *,
    workspace_dir: Path | None = None,
    reload_agent: Callable[[str], None] | None = None,
) -> AgentApplyReceipt:
    """Replace exported Agent source while retaining runtime-only state."""

    workspace = (
        Path(workspace_dir) if workspace_dir is not None else _standard_workspace(bundle.agent_id)
    )
    if not workspace.is_dir():
        raise DeliveryBundleError("standard Agent is unavailable")
    before_digest = _source_digest(workspace)
    staging = _temporary_sibling(workspace, "staging")
    backup = _temporary_sibling(workspace, "backup")
    shutil.rmtree(staging)
    shutil.rmtree(backup)
    installed = False
    try:
        shutil.copytree(workspace, staging, symlinks=True)
        _remove_source_files(staging)
        for archive_path, content in bundle.agent_files.items():
            relative = PurePosixPath(archive_path).relative_to("agent")
            target = staging.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        staged_digest = _source_digest(staging)
        if staged_digest != bundle.agent_digest:
            raise DeliveryBundleError("staged Agent digest mismatch")

        workspace.rename(backup)
        staging.rename(workspace)
        installed = True
        if reload_agent is not None:
            try:
                reload_agent(bundle.agent_id)
            except Exception:
                failed = _temporary_sibling(workspace, "failed")
                shutil.rmtree(failed)
                workspace.rename(failed)
                backup.rename(workspace)
                try:
                    reload_agent(bundle.agent_id)
                except Exception:
                    pass
                shutil.rmtree(failed, ignore_errors=True)
                installed = False
                raise
        return AgentApplyReceipt(
            operation_id=operation_id,
            agent_id=bundle.agent_id,
            workspace_dir=workspace,
            backup_dir=backup,
            agent_digest_before=before_digest,
            agent_digest_after=staged_digest,
        )
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if not installed and backup.exists():
            shutil.rmtree(backup, ignore_errors=True)


def restore_standard_agent_source(
    receipt: AgentApplyReceipt,
    *,
    reload_agent: Callable[[str], None] | None = None,
) -> None:
    """Restore the exact workspace captured before a standard Agent update."""

    workspace = receipt.workspace_dir
    backup = receipt.backup_dir
    if not backup.is_dir() or not workspace.is_dir():
        raise DeliveryBundleError("Agent backup is unavailable")
    replaced = _temporary_sibling(workspace, "replaced")
    shutil.rmtree(replaced)
    workspace.rename(replaced)
    try:
        backup.rename(workspace)
        if reload_agent is not None:
            reload_agent(receipt.agent_id)
    except Exception:
        if workspace.exists():
            workspace.rename(backup)
        replaced.rename(workspace)
        raise
    else:
        shutil.rmtree(replaced, ignore_errors=True)
