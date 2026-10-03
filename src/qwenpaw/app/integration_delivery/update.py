# -*- coding: utf-8 -*-
"""Validation primitives for integration delivery updates."""

from __future__ import annotations

import io
import hashlib
import json
import re
import shutil
import stat
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ...config.utils import load_config
from ...constant import WORKING_DIR
from ...mindspace import MindspaceScope
from ..open_api.knowledge import publication_knowledge_service
from .archive import (
    ArchiveLimits,
    SnapshotArchiveError,
    _normalize_path,
    collect_directory_files,
    deterministic_digest,
)
from .export import (
    DclawSnapshotExporter,
    _is_agent_runtime_path,
    _sanitize_agent_files,
    _sanitize_config,
)
from .models import DeliveryOperationView, DeliveryValidation
from .service import (
    DclawConfigurationContextService,
    get_dclaw_configuration_context_service,
)


class DeliveryBundleError(ValueError):
    """A delivery bundle is unsafe or does not match its target."""


class DeliverySourceChanged(DeliveryBundleError):
    """The caller's exported baseline no longer matches the current source."""


class DeliveryIdempotencyKeyReused(DeliveryBundleError):
    """An operation identity was reused for a different delivery request."""


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
    agent_digest_before: str
    agent_digest_after: str
    workspace_dir: Path | None = None
    backup_dir: Path | None = None
    previous_release_id: str | None = None
    applied_release_id: str | None = None


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
                # pylint: disable=too-many-boolean-expressions
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
    except (
        OSError,
        RuntimeError,
        SnapshotArchiveError,
        zipfile.BadZipFile,
    ) as exc:
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


def parse_delivery_bundle(
    agent_id: str,
    archive: bytes,
) -> ParsedDeliveryBundle:
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
        path: content
        for path, content in files.items()
        if path.startswith("agent/")
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
        if (
            not isinstance(relative, str)
            or f"knowledge/{relative}" not in knowledge_files
        ):
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
    if knowledge_base_id is not None and not isinstance(
        knowledge_base_id,
        str,
    ):
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
        _sanitize_agent_files(
            collect_directory_files(
                workspace,
                prefix="agent",
                exclude=_is_agent_runtime_path,
            ),
        ),
    )


def _merge_server_owned_json(
    original: Any,
    sanitized: Any,
    submitted: Any,
) -> Any:
    if not all(
        isinstance(value, dict) for value in (original, sanitized, submitted)
    ):
        if submitted == sanitized and original != sanitized:
            return original
        return submitted
    result: dict[str, Any] = {}
    for key, value in submitted.items():
        if key in original and key in sanitized:
            result[key] = _merge_server_owned_json(
                original[key],
                sanitized[key],
                value,
            )
        else:
            result[key] = value
    for key, value in original.items():
        if key not in sanitized:
            result[key] = value
    return result


def _agent_source_content(
    workspace: Path,
    relative: PurePosixPath,
    submitted: bytes,
) -> bytes:
    if relative.suffix.casefold() != ".json":
        return submitted
    existing = workspace.joinpath(*relative.parts)
    if not existing.is_file() or existing.is_symlink():
        return submitted
    try:
        original = json.loads(existing.read_text(encoding="utf-8"))
        incoming = json.loads(submitted.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return submitted
    sanitized = _sanitize_config(original)
    if relative == PurePosixPath("skill.json") and isinstance(sanitized, dict):
        sanitized = dict(sanitized)
        sanitized.pop("version", None)
    merged = _merge_server_owned_json(
        original,
        sanitized,
        incoming,
    )
    return json.dumps(
        merged,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


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
        ),
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
        Path(workspace_dir)
        if workspace_dir is not None
        else _standard_workspace(bundle.agent_id)
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
        source_contents = {
            archive_path: _agent_source_content(
                workspace,
                PurePosixPath(archive_path).relative_to("agent"),
                content,
            )
            for archive_path, content in bundle.agent_files.items()
        }
        _remove_source_files(staging)
        for archive_path, content in source_contents.items():
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
    if (
        workspace is None
        or backup is None
        or not backup.is_dir()
        or not workspace.is_dir()
    ):
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
    shutil.rmtree(replaced, ignore_errors=True)


_OPERATION_PART = re.compile(r"^[A-Za-z0-9._-]{1,160}$")


def _delivery_documents(
    bundle: ParsedDeliveryBundle,
) -> list[dict[str, object]]:
    manifest = _json_object(
        bundle.knowledge_files["knowledge/knowledge-manifest.json"],
        label="knowledge manifest",
    )
    result: list[dict[str, object]] = []
    for item in manifest["documents"]:
        relative = str(item["path"])
        result.append(
            {
                "id": str(item["id"]),
                "name": str(item["name"]),
                "sourceType": str(item.get("sourceType") or "txt"),
                "category": str(item.get("category") or "uncategorized"),
                "tags": list(item.get("tags") or []),
                "content": bundle.knowledge_files[f"knowledge/{relative}"],
            },
        )
    return result


def _replace_knowledge_documents(
    service: Any,
    bundle: ParsedDeliveryBundle,
) -> None:  # pylint: disable=protected-access
    # pylint: disable=protected-access
    documents = _delivery_documents(bundle)
    replace = getattr(service, "replace_delivery_documents", None)
    if callable(replace):
        replace(documents)
        return

    current = list(service.list_documents(MindspaceScope.PERSONAL))
    for document in current:
        service.delete_document(document.id, MindspaceScope.PERSONAL)
    for item in documents:
        # Mindspace has no public bulk replace method. This adapter uses its
        # existing staging primitives and retains deterministic document IDs.
        content = item["content"]
        if not isinstance(content, bytes):
            raise DeliveryBundleError("knowledge document content is invalid")
        document = service._new_doc(  # noqa: SLF001
            name=item["name"],
            source_type=item["sourceType"],
            scope=MindspaceScope.PERSONAL,
            byte_size=len(content),
            status="pending",
            progress=5,
            category=item["category"],
            tags=item["tags"],
        )
        document.id = item["id"]
        service._upsert_doc(document)  # noqa: SLF001
        service._store_asset(
            document,
            content,
            mime_type=None,
        )  # noqa: SLF001
        indexed = service.process_staged_document(
            document.id,
            scope=MindspaceScope.PERSONAL,
        )
        if indexed is None or indexed.status != "ready":
            raise DeliveryBundleError("knowledge document indexing failed")


class IntegrationDeliveryUpdater:
    """Coordinate Agent source and isolated knowledge as one operation."""

    def __init__(
        self,
        *,
        operations_root: Path | None = None,
        snapshot_exporter: DclawSnapshotExporter | Any | None = None,
        context_service: DclawConfigurationContextService | Any | None = None,
        knowledge_service_factory: Callable[[dict[str, Any]], Any] = (
            publication_knowledge_service
        ),
        apply_agent: Callable[[ParsedDeliveryBundle, str], AgentApplyReceipt]
        | None = None,
        restore_agent: Callable[[AgentApplyReceipt], None] | None = None,
    ) -> None:
        self._root = Path(
            operations_root
            or Path(WORKING_DIR) / "integration_delivery" / "operations",
        )
        self._root.mkdir(parents=True, exist_ok=True)
        self._context = (
            context_service or get_dclaw_configuration_context_service()
        )
        self._exporter = snapshot_exporter or DclawSnapshotExporter(
            context_service=self._context,
        )
        self._knowledge_factory = knowledge_service_factory
        self._apply_agent_override = apply_agent
        self._restore_agent_override = restore_agent

    def _operation_dir(self, agent_id: str, operation_id: str) -> Path:
        if not _OPERATION_PART.fullmatch(
            agent_id,
        ) or not _OPERATION_PART.fullmatch(
            operation_id,
        ):
            raise DeliveryBundleError("operation identity is invalid")
        return self._root / agent_id / operation_id

    @staticmethod
    def _view(data: dict[str, Any]) -> DeliveryOperationView:
        return DeliveryOperationView.model_validate(data)

    def _write_receipt(
        self,
        directory: Path,
        view: DeliveryOperationView,
    ) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        receipt = directory / "receipt.json"
        temporary = directory / ".receipt.json.tmp"
        temporary.write_text(
            json.dumps(
                view.model_dump(by_alias=True),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        temporary.replace(receipt)

    def get_operation(
        self,
        agent_id: str,
        operation_id: str,
    ) -> DeliveryOperationView:
        receipt = self._operation_dir(agent_id, operation_id) / "receipt.json"
        try:
            data = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DeliveryBundleError(
                "delivery operation is unavailable",
            ) from exc
        return self._view(data)

    def _knowledge_service(self, agent_id: str) -> Any:
        publication = self._context.resolve_publication(agent_id)
        if publication is None:
            raise DeliveryBundleError("OpenAPI publication is unavailable")
        return self._knowledge_factory(publication)

    @staticmethod
    def _request_fingerprint(
        archive: bytes,
        expected_agent_digest: str,
        expected_knowledge_digest: str,
    ) -> str:
        digest = hashlib.sha256()
        for value in (
            expected_agent_digest.encode("ascii"),
            expected_knowledge_digest.encode("ascii"),
            bytes(archive),
        ):
            digest.update(len(value).to_bytes(8, "big"))
            digest.update(value)
        return "sha256:" + digest.hexdigest()

    def validate(
        self,
        agent_id: str,
        archive: bytes,
        *,
        expected_agent_digest: str,
        expected_knowledge_digest: str,
    ) -> DeliveryValidation:
        bundle = parse_delivery_bundle(agent_id, archive)
        current = self._exporter.export(agent_id)
        if (
            current.agent_digest != expected_agent_digest
            or current.knowledge_digest != expected_knowledge_digest
        ):
            raise DeliverySourceChanged("DClaw source changed")
        if self._context.describe(agent_id).agent_type == "sealed":
            from .sealed_update import validate_sealed_agent_source

            validate_sealed_agent_source(bundle)
        return DeliveryValidation(
            agent_id=bundle.agent_id,
            agent_profile_id=bundle.agent_profile_id,
            source_version=bundle.source_version,
            agent_digest=bundle.agent_digest,
            knowledge_digest=bundle.knowledge_digest,
        )

    def _apply_agent_bundle(
        self,
        bundle: ParsedDeliveryBundle,
        operation_id: str,
    ) -> AgentApplyReceipt:
        if self._apply_agent_override is not None:
            return self._apply_agent_override(bundle, operation_id)
        if self._context.describe(bundle.agent_id).agent_type == "sealed":
            from .sealed_update import apply_sealed_agent_source

            return apply_sealed_agent_source(bundle, operation_id)
        return apply_standard_agent_source(bundle, operation_id)

    def _restore_agent_receipt(self, receipt: AgentApplyReceipt) -> None:
        if self._restore_agent_override is not None:
            self._restore_agent_override(receipt)
            return
        if receipt.previous_release_id is not None:
            from .sealed_update import restore_sealed_agent_source

            restore_sealed_agent_source(receipt)
            return
        restore_standard_agent_source(receipt)

    @staticmethod
    def _receipt_payload(receipt: AgentApplyReceipt) -> dict[str, Any]:
        return {
            "operationId": receipt.operation_id,
            "agentId": receipt.agent_id,
            "agentDigestBefore": receipt.agent_digest_before,
            "agentDigestAfter": receipt.agent_digest_after,
            "workspaceDir": (
                str(receipt.workspace_dir)
                if receipt.workspace_dir is not None
                else None
            ),
            "backupDir": (
                str(receipt.backup_dir)
                if receipt.backup_dir is not None
                else None
            ),
            "previousReleaseId": receipt.previous_release_id,
            "appliedReleaseId": receipt.applied_release_id,
        }

    @staticmethod
    def _receipt_from_payload(payload: dict[str, Any]) -> AgentApplyReceipt:
        workspace = payload.get("workspaceDir")
        backup = payload.get("backupDir")
        return AgentApplyReceipt(
            operation_id=str(payload["operationId"]),
            agent_id=str(payload["agentId"]),
            agent_digest_before=str(payload["agentDigestBefore"]),
            agent_digest_after=str(payload["agentDigestAfter"]),
            workspace_dir=Path(str(workspace)) if workspace else None,
            backup_dir=Path(str(backup)) if backup else None,
            previous_release_id=(
                str(payload["previousReleaseId"])
                if payload.get("previousReleaseId")
                else None
            ),
            applied_release_id=(
                str(payload["appliedReleaseId"])
                if payload.get("appliedReleaseId")
                else None
            ),
        )

    def apply(
        self,
        agent_id: str,
        archive: bytes,
        operation_id: str,
        *,
        expected_agent_digest: str,
        expected_knowledge_digest: str,
    ) -> DeliveryOperationView:
        bundle = parse_delivery_bundle(agent_id, archive)
        directory = self._operation_dir(agent_id, operation_id)
        fingerprint = self._request_fingerprint(
            archive,
            expected_agent_digest,
            expected_knowledge_digest,
        )
        request_path = directory / "request.json"
        if directory.exists():
            try:
                previous_request = json.loads(
                    request_path.read_text(encoding="utf-8"),
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise DeliveryIdempotencyKeyReused(
                    "operation identity is already in use",
                ) from exc
            if previous_request.get("fingerprint") != fingerprint:
                raise DeliveryIdempotencyKeyReused(
                    "operation identity is already in use",
                ) from None
            return self.get_operation(agent_id, operation_id)

        current = self._exporter.export(agent_id)
        if (
            current.agent_digest != expected_agent_digest
            or current.knowledge_digest != expected_knowledge_digest
        ):
            raise DeliverySourceChanged("DClaw source changed")

        try:
            directory.mkdir(parents=True)
        except FileExistsError:
            try:
                previous_request = json.loads(
                    request_path.read_text(encoding="utf-8"),
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise DeliveryIdempotencyKeyReused(
                    "operation identity is already in use",
                ) from exc
            if previous_request.get("fingerprint") != fingerprint:
                raise DeliveryIdempotencyKeyReused(
                    "operation identity is already in use",
                ) from None
            return self.get_operation(agent_id, operation_id)
        request_path.write_text(
            json.dumps({"fingerprint": fingerprint}, separators=(",", ":")),
            encoding="utf-8",
        )
        (directory / "before.zip").write_bytes(current.archive)
        (directory / "submitted.zip").write_bytes(bytes(archive))
        previous = parse_delivery_bundle(agent_id, current.archive)
        knowledge = self._knowledge_service(agent_id)
        agent_changed = current.agent_digest != bundle.agent_digest
        knowledge_changed = current.knowledge_digest != bundle.knowledge_digest
        agent_receipt: AgentApplyReceipt | None = None
        try:
            if agent_changed:
                agent_receipt = self._apply_agent_bundle(bundle, operation_id)
            if knowledge_changed:
                _replace_knowledge_documents(knowledge, bundle)
        except Exception:
            if agent_receipt is not None:
                self._restore_agent_receipt(agent_receipt)
            if knowledge_changed:
                try:
                    _replace_knowledge_documents(knowledge, previous)
                except Exception:
                    pass
            failed = DeliveryOperationView(
                operation_id=operation_id,
                agent_id=agent_id,
                status="failed",
                previous_agent_digest=current.agent_digest,
                previous_knowledge_digest=current.knowledge_digest,
                agent_digest=current.agent_digest,
                knowledge_digest=current.knowledge_digest,
                error_code="DCLAW_DELIVERY_APPLY_FAILED",
            )
            self._write_receipt(directory, failed)
            raise

        if agent_receipt is not None:
            (directory / "agent-receipt.json").write_text(
                json.dumps(
                    self._receipt_payload(agent_receipt),
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

        applied = DeliveryOperationView(
            operation_id=operation_id,
            agent_id=agent_id,
            status="applied",
            previous_agent_digest=current.agent_digest,
            previous_knowledge_digest=current.knowledge_digest,
            agent_digest=bundle.agent_digest,
            knowledge_digest=bundle.knowledge_digest,
        )
        self._write_receipt(directory, applied)
        return applied

    def restore(
        self,
        agent_id: str,
        operation_id: str,
    ) -> DeliveryOperationView:
        directory = self._operation_dir(agent_id, operation_id)
        current = self.get_operation(agent_id, operation_id)
        if current.status == "restored":
            return current
        if current.status != "applied":
            raise DeliveryBundleError("delivery operation cannot be restored")

        previous = parse_delivery_bundle(
            agent_id,
            (directory / "before.zip").read_bytes(),
        )
        submitted = parse_delivery_bundle(
            agent_id,
            (directory / "submitted.zip").read_bytes(),
        )
        knowledge = self._knowledge_service(agent_id)
        agent_changed = previous.agent_digest != submitted.agent_digest
        knowledge_changed = previous.knowledge_digest != submitted.knowledge_digest
        receipt: AgentApplyReceipt | None = None
        if agent_changed:
            stored_receipt = self._receipt_from_payload(
                json.loads(
                    (directory / "agent-receipt.json").read_text(
                        encoding="utf-8",
                    ),
                ),
            )
            if stored_receipt.previous_release_id is not None:
                self._restore_agent_receipt(stored_receipt)
                receipt = AgentApplyReceipt(
                    operation_id=f"{operation_id}.restore",
                    agent_id=agent_id,
                    agent_digest_before=previous.agent_digest,
                    agent_digest_after=submitted.agent_digest,
                    previous_release_id=stored_receipt.applied_release_id,
                    applied_release_id=stored_receipt.previous_release_id,
                )
            else:
                receipt = self._apply_agent_bundle(
                    previous,
                    f"{operation_id}.restore",
                )
        try:
            if knowledge_changed:
                _replace_knowledge_documents(knowledge, previous)
        except Exception:
            if receipt is not None:
                self._restore_agent_receipt(receipt)
            if knowledge_changed:
                try:
                    _replace_knowledge_documents(knowledge, submitted)
                except Exception:
                    pass
            raise

        restored = current.model_copy(
            update={
                "status": "restored",
                "agent_digest": previous.agent_digest,
                "knowledge_digest": previous.knowledge_digest,
                "error_code": None,
            },
        )
        self._write_receipt(directory, restored)
        return restored
