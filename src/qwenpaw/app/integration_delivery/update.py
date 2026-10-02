"""Validation primitives for integration delivery updates."""

from __future__ import annotations

import io
import json
import stat
import zipfile
from dataclasses import dataclass
from typing import Any

from .archive import ArchiveLimits, SnapshotArchiveError, _normalize_path, deterministic_digest
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
