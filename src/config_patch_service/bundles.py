"""Deterministic, caller-ready customer-service workspace bundles."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import PurePosixPath

from .capabilities import CapabilityCatalog
from .models import OmnichannelBotSnapshot
from .releases import ConfigurationRelease, ContentAddressedObjectStore


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
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("unsafe workspace archive path")
    return path.as_posix()


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


def _extract_dclaw_snapshot(archive_bytes: bytes) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    total = 0
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        if archive.testzip() is not None:
            raise ValueError("DClaw snapshot ZIP is corrupt")
        for entry in archive.infolist():
            path = _safe_path(entry.filename)
            if path == "dclaw-component.json":
                continue
            if not (
                path.startswith("agent/") or path.startswith("knowledge/")
            ):
                raise ValueError("DClaw snapshot contains an unexpected path")
            if path in result:
                raise ValueError("DClaw snapshot contains a duplicate path")
            if entry.file_size > 100 * 1024 * 1024:
                raise ValueError("DClaw snapshot member is too large")
            total += entry.file_size
            if total > 400 * 1024 * 1024:
                raise ValueError("DClaw snapshot is too large")
            result[path] = archive.read(entry)
    if not any(path.startswith("agent/") for path in result):
        raise ValueError("DClaw snapshot has no Agent source")
    if "knowledge/knowledge-manifest.json" not in result:
        raise ValueError("DClaw snapshot has no knowledge manifest")
    return result


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

    def build(self, release: ConfigurationRelease) -> BuiltWorkspaceBundle:
        dclaw_files = _extract_dclaw_snapshot(
            self._object_store.get(release.dclaw_snapshot_object_key),
        )
        omnichannel = OmnichannelBotSnapshot.model_validate_json(
            self._object_store.get(release.omnichannel_snapshot_object_key),
        )
        profile = self._capability_catalog.profiles.get(
            release.agent_profile_id
        )
        if profile is None:
            raise ValueError("release capability profile is unknown")
        manifest: dict[str, object] = {
            "schemaVersion": "customer-service-workspace.v1",
            "botId": release.bot_id,
            "botName": release.bot_name,
            "agentId": release.agent_id,
            "agentProfileId": release.agent_profile_id,
            "activeCapabilities": profile.capabilities,
            "sourceVersion": release.source_version,
            "baseReleaseId": release.release_id,
            "capabilityCatalogVersion": self._capability_catalog.version,
            "fingerprints": release.component_digests,
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
