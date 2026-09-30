"""Deterministic, caller-ready customer-service workspace bundles."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import struct
import unicodedata
import zipfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import PurePosixPath

from .capabilities import CapabilityCatalog
from .models import OmnichannelBotSnapshot
from .releases import (
    AggregatedSnapshot,
    ConfigurationRelease,
    ContentAddressedObjectStore,
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_path(value: str) -> str:
    if not value or "\\" in value or value.startswith("/"):
        raise ValueError("unsafe workspace archive path")
    path = PurePosixPath(unicodedata.normalize("NFC", value))
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("unsafe workspace archive path")
    return path.as_posix()


_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
_MAX_FILES = 4096
_MAX_FILE_BYTES = 100 * 1024 * 1024
_MAX_TOTAL_BYTES = 400 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 100


def _component_digest(source: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path, content in sorted(
        source.items(), key=lambda item: item[0].encode("utf-8")
    ):
        path_bytes = path.encode("utf-8")
        digest.update(struct.pack(">Q", len(path_bytes)))
        digest.update(path_bytes)
        digest.update(struct.pack(">Q", len(content)))
        digest.update(content)
    return "sha256:" + digest.hexdigest()


def _deterministic_zip(source: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for raw_path, content in sorted(
            source.items(), key=lambda item: item[0].encode("utf-8")
        ):
            path = _safe_path(raw_path)
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, bytes(content))
    return output.getvalue()


def _extract_dclaw_snapshot(
    archive_bytes: bytes,
) -> tuple[dict[str, bytes], dict[str, object]]:
    if len(archive_bytes) > _MAX_ARCHIVE_BYTES:
        raise ValueError("DClaw snapshot archive is too large")
    result: dict[str, bytes] = {}
    component_bytes: bytes | None = None
    total = 0
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        entries = archive.infolist()
        if len(entries) > _MAX_FILES:
            raise ValueError("DClaw snapshot has too many files")
        seen: set[str] = set()
        for entry in entries:
            path = _safe_path(entry.filename)
            if path in seen:
                raise ValueError("DClaw snapshot contains a duplicate path")
            seen.add(path)
            mode = entry.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if entry.is_dir() or file_type not in {0, stat.S_IFREG}:
                raise ValueError("DClaw snapshot contains a non-regular file")
            if entry.flag_bits & 0x1:
                raise ValueError("DClaw snapshot contains an encrypted file")
            if path != "dclaw-component.json" and not (
                path.startswith("agent/") or path.startswith("knowledge/")
            ):
                raise ValueError("DClaw snapshot contains an unexpected path")
            if entry.file_size > _MAX_FILE_BYTES:
                raise ValueError("DClaw snapshot member is too large")
            total += entry.file_size
            if total > _MAX_TOTAL_BYTES:
                raise ValueError("DClaw snapshot is too large")
            if (
                entry.file_size > 1024 * 1024
                and entry.file_size
                > max(1, entry.compress_size) * _MAX_COMPRESSION_RATIO
            ):
                raise ValueError("DClaw snapshot compression ratio is unsafe")
            content = bytearray()
            with archive.open(entry) as opened:
                while chunk := opened.read(1024 * 1024):
                    content.extend(chunk)
                    if len(content) > entry.file_size:
                        raise ValueError("DClaw snapshot member size changed")
            if len(content) != entry.file_size:
                raise ValueError("DClaw snapshot member is truncated")
            if path == "dclaw-component.json":
                component_bytes = bytes(content)
            else:
                result[path] = bytes(content)
    if not any(path.startswith("agent/") for path in result):
        raise ValueError("DClaw snapshot has no Agent source")
    if "knowledge/knowledge-manifest.json" not in result:
        raise ValueError("DClaw snapshot has no knowledge manifest")
    if component_bytes is None:
        raise ValueError("DClaw snapshot has no component manifest")
    try:
        component = json.loads(component_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("DClaw component manifest is invalid") from exc
    if not isinstance(component, dict):
        raise ValueError("DClaw component manifest is invalid")
    required = {
        "agentDigest",
        "agentId",
        "agentProfileId",
        "knowledgeDigest",
        "sourceVersion",
    }
    if not required <= component.keys() or any(
        not isinstance(component[key], str) or not component[key]
        for key in required
    ):
        raise ValueError("DClaw component manifest is invalid")
    calculated = {
        "agentDigest": _component_digest(
            {
                path: content
                for path, content in result.items()
                if path.startswith("agent/")
            }
        ),
        "knowledgeDigest": _component_digest(
            {
                path: content
                for path, content in result.items()
                if path.startswith("knowledge/")
            }
        ),
    }
    if any(component[key] != value for key, value in calculated.items()):
        raise ValueError("DClaw component digest mismatch")
    return result, component


@dataclass(frozen=True)
class BuiltWorkspaceBundle:
    archive: bytes
    bundle_digest: str
    object_key: str
    release_id: str
    manifest: dict[str, object]


class WorkspaceBundleBuilder:
    def __init__(
        self,
        *,
        object_store: ContentAddressedObjectStore,
        capability_catalog: CapabilityCatalog,
    ) -> None:
        self._object_store = object_store
        self._capability_catalog = capability_catalog

    @staticmethod
    def _workspace_resource(relative: str) -> bytes:
        return (
            files("config_patch_service.resources")
            .joinpath("workspace", *relative.split("/"))
            .read_bytes()
        )

    def _validated_dclaw_files(
        self,
        archive: bytes,
        *,
        agent_id: str,
        profile_id: str,
        source_version: str,
        agent_digest: str | None,
        knowledge_digest: str | None,
    ) -> dict[str, bytes]:
        try:
            dclaw_files, component = _extract_dclaw_snapshot(archive)
        except (ValueError, zipfile.BadZipFile, RuntimeError) as exc:
            raise ValueError("DClaw snapshot archive is invalid") from exc
        expected_component = {
            "agentDigest": agent_digest,
            "agentId": agent_id,
            "agentProfileId": profile_id,
            "knowledgeDigest": knowledge_digest,
            "sourceVersion": source_version,
        }
        if any(
            component.get(key) != value
            for key, value in expected_component.items()
        ):
            raise ValueError("DClaw snapshot release digest or identity mismatch")
        if profile_id not in self._capability_catalog.profiles:
            raise ValueError("release capability profile is unknown")
        return dclaw_files

    def validate_snapshot(self, snapshot: AggregatedSnapshot) -> None:
        """Validate all source-controlled bundle inputs before persisting Rn."""
        self._validated_dclaw_files(
            snapshot.dclaw.archive,
            agent_id=snapshot.dclaw.agent_id,
            profile_id=snapshot.dclaw.profile_id,
            source_version=snapshot.dclaw.source_version,
            agent_digest=snapshot.component_digests.get("agent"),
            knowledge_digest=snapshot.component_digests.get("knowledge"),
        )

    def build(self, release: ConfigurationRelease) -> BuiltWorkspaceBundle:
        dclaw_files = self._validated_dclaw_files(
            self._object_store.get(release.dclaw_snapshot_object_key),
            agent_id=release.agent_id,
            profile_id=release.agent_profile_id,
            source_version=release.source_version,
            agent_digest=release.component_digests.get("agent"),
            knowledge_digest=release.component_digests.get("knowledge"),
        )
        omnichannel = OmnichannelBotSnapshot.model_validate_json(
            self._object_store.get(release.omnichannel_snapshot_object_key),
        )
        profile = self._capability_catalog.profiles.get(
            release.agent_profile_id
        )
        if profile is None:  # guarded by _validated_dclaw_files
            raise AssertionError("validated capability profile disappeared")
        bundle_id = "bundle_" + hashlib.sha256(
            _canonical_json(
                {
                    "botId": release.bot_id,
                    "releaseId": release.release_id,
                    "snapshotDigest": release.snapshot_digest,
                }
            )
        ).hexdigest()[:24]
        manifest: dict[str, object] = {
            "schemaVersion": "customer-service-workspace.v1",
            "bundleId": bundle_id,
            "botId": release.bot_id,
            "botName": release.bot_name,
            "agentId": release.agent_id,
            "agentProfileId": release.agent_profile_id,
            "activeCapabilities": profile.capabilities,
            "sourceVersion": release.source_version,
            "baseReleaseId": release.release_id,
            "capabilityCatalogVersion": self._capability_catalog.version,
            "sourceFingerprints": {
                "agent": release.component_digests["agent"],
                "knowledge": release.component_digests["knowledge"],
                "flow": release.component_digests["flowMachine"],
                "tags": release.component_digests["tags"],
            },
            "exportedAt": release.created_at.isoformat(),
        }
        workspace_files = {
            **dclaw_files,
            "dclaw-manifest.json": _canonical_json(manifest),
            "customer-service/flow-machine.json": _canonical_json(
                omnichannel.flow_machine,
            ),
            "customer-service/tag-schema.json": _canonical_json(
                omnichannel.tags
            ),
            "AGENTS.md": self._workspace_resource("AGENTS.md"),
            "change-plan.yaml": self._workspace_resource("change-plan.yaml"),
            "platform/capability-catalog.json": _canonical_json(
                self._capability_catalog.model_dump(
                    by_alias=True, mode="json"
                ),
            ),
            "platform/responsibility-matrix.md": self._workspace_resource(
                "platform/responsibility-matrix.md",
            ),
            "platform/runtime-mechanism.md": self._workspace_resource(
                "platform/runtime-mechanism.md",
            ),
            "platform/coordinated-change-patterns.md": (
                self._workspace_resource(
                    "platform/coordinated-change-patterns.md",
                )
            ),
            "platform/examples/cross-component-change.md": (
                self._workspace_resource(
                    "platform/examples/cross-component-change.md",
                )
            ),
        }
        archive = _deterministic_zip(workspace_files)
        bundle_digest = "sha256:" + hashlib.sha256(archive).hexdigest()
        return BuiltWorkspaceBundle(
            archive=archive,
            bundle_digest=bundle_digest,
            object_key=self._object_store.put(archive),
            release_id=release.release_id,
            manifest=manifest,
        )
