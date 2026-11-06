"""Signed, fail-closed workspace state continuity across installations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from qwenpaw.app.sealed_agents.package import inspect_extracted_payload

from .orchestration import _exclusive_state_lock, _scope_key, _state_binding_path
from .state_migration import _bind_state_file


CONTRACT = "workspace.state.continuity/1"
DESCRIPTOR = "agent/state-contract.json"
_REGISTRY = "migrations/continuity/legacy-contracts.json"
_TEMPLATE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._{}-]{0,126}\.json\Z")
_FORMAT = re.compile(r"[a-z][a-z0-9_.-]{0,127}\Z")


class StateContinuityError(ValueError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class StateContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: Literal["workspace.state.continuity/1"]
    format_id: str = Field(min_length=1, max_length=128)
    schema_version: int = Field(ge=1)
    filename_template: str = Field(min_length=6, max_length=132)

    @field_validator("format_id")
    @classmethod
    def valid_format(cls, value: str) -> str:
        if not _FORMAT.fullmatch(value):
            raise ValueError("invalid format id")
        return value

    @field_validator("filename_template")
    @classmethod
    def valid_filename(cls, value: str) -> str:
        placeholder = "{identity_sha256_24}"
        literal = value.replace(placeholder, "x" * 24)
        if (
            value.count(placeholder) != 1
            or not _TEMPLATE.fullmatch(literal)
            or "{" in literal or "}" in literal
        ):
            raise ValueError("invalid state filename template")
        return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _state_dir(root: Path, installation_id: str, session_id: str) -> Path:
    return root / "state" / _scope_key(installation_id) / _scope_key(session_id)


def _receipt_path(root: Path, installation_id: str, session_id: str) -> Path:
    return (
        root / "migrations" / "continuity" / "receipts"
        / _scope_key(installation_id) / f"{_scope_key(session_id)}.json"
    )


def _filename(contract: StateContract, identity: dict[str, str]) -> str:
    scope = "\x1f".join(
        identity[key] for key in ("installation_id", "user_id", "session_id")
    )
    digest = _sha256(scope.encode("utf-8"))[:24]
    name = contract.filename_template.replace("{identity_sha256_24}", digest)
    if not _TEMPLATE.fullmatch(name) or "{" in name or "}" in name:
        raise StateContinuityError("state_filename_invalid")
    return name


def _payload_digest(state: dict[str, Any]) -> str:
    payload = {key: value for key, value in state.items() if key != "identity"}
    return _sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))


def _read_state(
    path: Path, identity: dict[str, str], contract: StateContract | None,
) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file():
        raise StateContinuityError("state_source_unsafe")
    try:
        raw = path.read_bytes()
        state = json.loads(raw)
    except (OSError, UnicodeError, ValueError) as exc:
        raise StateContinuityError("state_source_invalid") from exc
    if not isinstance(state, dict) or state.get("identity") != identity:
        raise StateContinuityError("state_identity_mismatch")
    if contract is not None and state.get("schema_version") != contract.schema_version:
        raise StateContinuityError("state_schema_incompatible")
    return state, _sha256(raw)


def _committed_state_file(directory: Path) -> Path | None:
    if directory.parent.is_symlink():
        raise StateContinuityError("state_scope_conflict")
    if not directory.exists() and not directory.is_symlink():
        return None
    if directory.is_symlink() or not directory.is_dir():
        raise StateContinuityError("state_scope_conflict")
    files = list(directory.iterdir())
    if not files:
        return None
    if (
        len(files) != 1 or files[0].is_symlink() or not files[0].is_file()
        or files[0].suffix != ".json"
    ):
        raise StateContinuityError("state_scope_conflict")
    return files[0]


def _only_state_file(directory: Path) -> Path:
    state_file = _committed_state_file(directory)
    if state_file is None:
        raise StateContinuityError("state_scope_conflict")
    return state_file


def _binding_matches(
    root: Path, installation_id: str, session_id: str, filename: str,
) -> bool:
    path = _state_binding_path(root, installation_id, session_id)
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink() or not path.is_file():
        raise StateContinuityError("state_scope_conflict")
    try:
        binding = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise StateContinuityError("state_scope_conflict") from exc
    if (
        binding.get("contract") != "workspace.state.binding/1"
        or binding.get("installation_id") != installation_id
        or binding.get("session_id") != session_id
        or binding.get("filename") != filename
    ):
        raise StateContinuityError("state_scope_conflict")
    return True


def _verified_release(
    sealed_root: Path, record: Any, grant: Any,
) -> tuple[Any, Path, frozenset[str]]:
    release = next(
        (item for item in record.releases if item.release_id == grant.release_id),
        None,
    )
    if (
        release is None or release.content_digest != grant.package_digest
        or release.version != grant.package_version
        or release.package_type not in {"super_expert", "super_expert_public"}
    ):
        raise StateContinuityError("state_release_identity_mismatch")
    root = sealed_root / "releases" / record.agent_id / release.release_id
    try:
        digest, files = inspect_extracted_payload(root)
    except Exception as exc:
        raise StateContinuityError("state_release_integrity_failed") from exc
    if digest != release.content_digest:
        raise StateContinuityError("state_release_integrity_failed")
    return release, root, frozenset(files)


def _legacy_records(root: Path) -> list[dict[str, Any]]:
    path = root / _REGISTRY
    if not path.exists() and not path.is_symlink():
        return []
    if path.is_symlink() or not path.is_file():
        raise StateContinuityError("state_contract_registry_invalid")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise StateContinuityError("state_contract_registry_invalid") from exc
    if (
        not isinstance(data, dict) or data.get("schema_version") != 1
        or not isinstance(data.get("contracts"), list)
    ):
        raise StateContinuityError("state_contract_registry_invalid")
    return data["contracts"]


def _contract_for_release(
    storage_root: Path, record: Any, release: Any, release_root: Path,
    signed_files: frozenset[str],
) -> StateContract:
    if DESCRIPTOR in signed_files:
        path = release_root / DESCRIPTOR
        if path.is_symlink() or not path.is_file():
            raise StateContinuityError("state_contract_invalid")
        try:
            return StateContract.model_validate_json(path.read_bytes())
        except (OSError, ValidationError) as exc:
            raise StateContinuityError("state_contract_invalid") from exc
    matches = [
        item for item in _legacy_records(storage_root)
        if isinstance(item, dict)
        and item.get("agent_id") == record.agent_id
        and item.get("release_id") == release.release_id
    ]
    if len(matches) != 1:
        raise StateContinuityError("state_contract_missing")
    entry = matches[0]
    if (
        entry.get("content_digest") != release.content_digest
        or entry.get("signer_id") != release.signer_id
    ):
        raise StateContinuityError("state_contract_stale")
    module = entry.get("evidence_module")
    if (
        not isinstance(module, str) or module not in signed_files
        or _sha256((release_root / module).read_bytes())
        != entry.get("evidence_sha256")
    ):
        raise StateContinuityError("state_contract_stale")
    try:
        return StateContract.model_validate(entry["state_contract"])
    except (KeyError, ValidationError) as exc:
        raise StateContinuityError("state_contract_invalid") from exc


def _source_grant(
    root: Path, grants: Any, target: Any, session_id: str,
) -> Any | None:
    candidates = []
    for grant in grants.list_grants():
        if (
            grant.agent_id != target.agent_id
            or grant.tenant_id != target.tenant_id
            or grant.installation_id == target.installation_id
            or grant.granted_at >= target.granted_at
        ):
            continue
        state_file = _committed_state_file(
            _state_dir(root, grant.installation_id, session_id),
        )
        if state_file is not None:
            candidates.append(grant)
        else:
            binding = _state_binding_path(root, grant.installation_id, session_id)
            if binding.exists() or binding.is_symlink():
                raise StateContinuityError("state_scope_conflict")
    return max(candidates, key=lambda item: item.granted_at) if candidates else None


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _has_missing_revisions(source: dict[str, Any], target: dict[str, Any]) -> bool:
    old = source.get("revisions")
    new = target.get("revisions")
    if not isinstance(old, dict) or not isinstance(new, dict):
        return False
    for key, old_versions in old.items():
        new_versions = new.get(key)
        if (
            isinstance(old_versions, list)
            and (not isinstance(new_versions, list)
                 or new_versions[:len(old_versions)] != old_versions)
        ):
            return True
    return False


def ensure_state_continuity(
    *, storage_root: Path, sealed_root: Path, grants: Any, record: Any,
    target_grant: Any, session_id: str, user_id: str, apply: bool = True,
    expected_source_installation_id: str | None = None,
    expected_source_file_sha256: str | None = None,
    expected_target_release_id: str | None = None,
) -> dict[str, Any]:
    """Promote one verified predecessor's entire state before runtime starts."""
    Path(storage_root).mkdir(parents=True, exist_ok=True)
    root = Path(storage_root).resolve(strict=True)
    sealed = Path(sealed_root).resolve(strict=True)
    if (
        record.agent_id != target_grant.agent_id
        or record.active_release_id != target_grant.release_id
        or (expected_target_release_id is not None
            and expected_target_release_id != target_grant.release_id)
    ):
        raise StateContinuityError("state_release_identity_mismatch")
    source_grant = _source_grant(root, grants, target_grant, session_id)
    if (
        expected_source_installation_id is not None
        and (source_grant is None or source_grant.installation_id != expected_source_installation_id)
    ):
        raise StateContinuityError("state_source_changed")
    target_dir = _state_dir(root, target_grant.installation_id, session_id)
    if source_grant is None:
        target_binding = _state_binding_path(
            root, target_grant.installation_id, session_id,
        )
        if (_committed_state_file(target_dir) is None
                and (target_binding.exists() or target_binding.is_symlink())):
            raise StateContinuityError("state_scope_conflict")
        return {"contract": CONTRACT, "status": "new_or_existing"}
    source_dir = _state_dir(root, source_grant.installation_id, session_id)
    locks = sorted({
        str(source_dir.with_suffix(".lock")),
        str(target_dir.with_suffix(".lock")),
    })
    with ExitStack() as stack:
        if apply:
            for lock in locks:
                stack.enter_context(_exclusive_state_lock(Path(lock)))
        # Re-select under the locks; a newer predecessor must never be skipped.
        if _source_grant(root, grants, target_grant, session_id) != source_grant:
            raise StateContinuityError("state_source_changed")
        source_release, source_root, source_files = _verified_release(
            sealed, record, source_grant,
        )
        target_release, target_root, target_files = _verified_release(
            sealed, record, target_grant,
        )
        source_contract = _contract_for_release(
            root, record, source_release, source_root, source_files,
        )
        target_contract = _contract_for_release(
            root, record, target_release, target_root, target_files,
        )
        if source_release.signer_id != target_release.signer_id:
            raise StateContinuityError("state_signer_incompatible")
        if (
            source_contract.format_id != target_contract.format_id
            or source_contract.schema_version != target_contract.schema_version
        ):
            raise StateContinuityError("state_schema_incompatible")
        source_identity = {
            "installation_id": source_grant.installation_id,
            "user_id": user_id, "session_id": session_id,
        }
        target_identity = {
            "installation_id": target_grant.installation_id,
            "user_id": user_id, "session_id": session_id,
        }
        source_file = _only_state_file(source_dir)
        if source_file.name != _filename(source_contract, source_identity):
            raise StateContinuityError("state_filename_incompatible")
        _binding_matches(
            root, source_grant.installation_id, session_id, source_file.name,
        )
        source_state, source_sha = _read_state(
            source_file, source_identity, source_contract,
        )
        if (
            expected_source_file_sha256 is not None
            and source_sha != expected_source_file_sha256
        ):
            raise StateContinuityError("state_source_changed")
        target_filename = _filename(target_contract, target_identity)
        receipt_path = _receipt_path(
            root, target_grant.installation_id, session_id,
        )
        target_file = _committed_state_file(target_dir)
        if target_file is not None:
            if target_file.name != target_filename:
                raise StateContinuityError("state_filename_incompatible")
            target_state, target_sha = _read_state(
                target_file, target_identity, target_contract,
            )
            if _has_missing_revisions(source_state, target_state):
                raise StateContinuityError("state_target_conflict")
            if receipt_path.exists():
                try:
                    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, ValueError) as exc:
                    raise StateContinuityError("state_receipt_invalid") from exc
                if (
                    receipt.get("status") not in {"prepared", "committed"}
                    or receipt.get("source_installation_id") != source_grant.installation_id
                    or receipt.get("target_installation_id") != target_grant.installation_id
                    or receipt.get("source_file_sha256") != source_sha
                    or receipt.get("target_filename") != target_filename
                ):
                    raise StateContinuityError("state_receipt_conflict")
                if receipt["status"] == "prepared":
                    if target_sha != receipt.get("target_file_sha256"):
                        raise StateContinuityError("state_receipt_conflict")
                    if apply:
                        _bind_state_file(
                            root, target_grant.installation_id, session_id,
                            target_filename, receipt["migration_id"],
                        )
                        receipt["status"] = "committed"
                        _write_json(receipt_path, receipt)
                elif not _binding_matches(
                    root, target_grant.installation_id, session_id,
                    target_filename,
                ):
                    raise StateContinuityError("state_scope_conflict")
                return {**receipt, "status": "already_migrated"}
            raise StateContinuityError("state_target_unverified")
        if _state_binding_path(
            root, target_grant.installation_id, session_id,
        ).exists():
            raise StateContinuityError("state_scope_conflict")
        target_state = {
            **source_state, "identity": target_identity,
        }
        content_sha = _payload_digest(source_state)
        if _payload_digest(target_state) != content_sha:
            raise StateContinuityError("state_content_mismatch")
        target_bytes = (
            json.dumps(target_state, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")
        receipt = {
            "contract": CONTRACT, "migration_id": uuid.uuid4().hex,
            "status": "preview" if not apply else "prepared",
            "agent_id": record.agent_id, "session_id": session_id,
            "source_installation_id": source_grant.installation_id,
            "source_release_id": source_release.release_id,
            "target_installation_id": target_grant.installation_id,
            "target_release_id": target_release.release_id,
            "format_id": target_contract.format_id,
            "schema_version": target_contract.schema_version,
            "source_file_sha256": source_sha,
            "target_file_sha256": _sha256(target_bytes),
            "content_sha256": content_sha,
            "target_filename": target_filename,
        }
        if receipt_path.exists() or receipt_path.is_symlink():
            if receipt_path.is_symlink() or not receipt_path.is_file():
                raise StateContinuityError("state_receipt_conflict")
            try:
                previous = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError) as exc:
                raise StateContinuityError("state_receipt_invalid") from exc
            if (
                previous.get("status") != "prepared"
                or any(previous.get(key) != receipt[key] for key in (
                    "contract", "agent_id", "session_id",
                    "source_installation_id", "source_release_id",
                    "target_installation_id", "target_release_id",
                    "source_file_sha256", "target_file_sha256",
                    "content_sha256", "target_filename",
                ))
                or not isinstance(previous.get("migration_id"), str)
                or not re.fullmatch(r"[0-9a-f]{32}", previous["migration_id"])
            ):
                raise StateContinuityError("state_receipt_conflict")
            receipt["migration_id"] = previous["migration_id"]
        if not apply:
            return receipt
        stage = (
            root / "migrations" / "continuity" / "staging"
            / receipt["migration_id"]
        )
        try:
            if stage.is_symlink():
                raise StateContinuityError("state_staging_unsafe")
            if stage.exists():
                shutil.rmtree(stage)
            stage.mkdir(parents=True)
            (stage / target_filename).write_bytes(target_bytes)
            _write_json(receipt_path, receipt)
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage, target_dir)
            _bind_state_file(
                root, target_grant.installation_id, session_id,
                target_filename, receipt["migration_id"],
            )
            receipt["status"] = "committed"
            _write_json(receipt_path, receipt)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return receipt


def preview_activation_continuity(
    *, storage_root: Path, sealed_root: Path, grants: Any, record: Any,
    target_grant: Any,
) -> dict[str, Any]:
    """Check every existing task before a newly installed release becomes active."""
    root = Path(storage_root).resolve(strict=True)
    target_record = SimpleNamespace(
        agent_id=record.agent_id,
        active_release_id=target_grant.release_id,
        releases=record.releases,
    )
    sessions: dict[str, str] = {}
    for grant in grants.list_grants():
        if (
            grant.agent_id != target_grant.agent_id
            or grant.tenant_id != target_grant.tenant_id
            or grant.installation_id == target_grant.installation_id
            or grant.granted_at >= target_grant.granted_at
        ):
            continue
        installation_dir = root / "state" / _scope_key(grant.installation_id)
        if not installation_dir.exists() and not installation_dir.is_symlink():
            continue
        if installation_dir.is_symlink() or not installation_dir.is_dir():
            raise StateContinuityError("state_scope_conflict")
        for session_dir in installation_dir.iterdir():
            if (
                re.fullmatch(r"[0-9a-f]{64}\.lock", session_dir.name)
                and session_dir.is_file() and not session_dir.is_symlink()
            ):
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", session_dir.name):
                raise StateContinuityError("state_scope_conflict")
            state_file = _committed_state_file(session_dir)
            if state_file is None:
                binding = (
                    root / "migrations" / "bindings"
                    / _scope_key(grant.installation_id)
                    / f"{session_dir.name}.json"
                )
                if binding.exists() or binding.is_symlink():
                    raise StateContinuityError("state_scope_conflict")
                continue
            try:
                identity = json.loads(state_file.read_text(encoding="utf-8"))["identity"]
                session_id = identity["session_id"]
                user_id = identity["user_id"]
            except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
                raise StateContinuityError("state_source_invalid") from exc
            if (
                not isinstance(session_id, str)
                or not isinstance(user_id, str)
                or identity.get("installation_id") != grant.installation_id
                or session_dir.name != _scope_key(session_id)
            ):
                raise StateContinuityError("state_identity_mismatch")
            previous_user = sessions.setdefault(session_id, user_id)
            if previous_user != user_id:
                raise StateContinuityError("state_identity_mismatch")
            _binding_matches(
                root, grant.installation_id, session_id, state_file.name,
            )
    for session_id, user_id in sessions.items():
        ensure_state_continuity(
            storage_root=root, sealed_root=sealed_root, grants=grants,
            record=target_record, target_grant=target_grant,
            session_id=session_id, user_id=user_id, apply=False,
        )
    return {
        "contract": CONTRACT,
        "status": "ready",
        "checked_tasks": len(sessions),
    }


def register_legacy_pair(
    *, storage_root: Path, sealed_root: Path, record: Any,
    source_release_id: str, target_release_id: str, evidence_module: str,
    contract: StateContract, apply: bool = False,
    expected_source_digest: str | None = None,
    expected_target_digest: str | None = None,
    expected_evidence_sha256: str | None = None,
) -> dict[str, Any]:
    """Attest identical signed legacy state code without editing either package."""
    if (
        not evidence_module.startswith("agent/")
        or ".." in Path(evidence_module).parts
        or source_release_id == target_release_id
    ):
        raise StateContinuityError("state_evidence_invalid")
    releases = {item.release_id: item for item in record.releases}
    source = releases.get(source_release_id)
    target = releases.get(target_release_id)
    if source is None or target is None or source.signer_id != target.signer_id:
        raise StateContinuityError("state_signer_incompatible")
    sealed = Path(sealed_root).resolve(strict=True)
    evidence = []
    for release in (source, target):
        release_root = sealed / "releases" / record.agent_id / release.release_id
        try:
            digest, files = inspect_extracted_payload(release_root)
        except Exception as exc:
            raise StateContinuityError("state_release_integrity_failed") from exc
        if (
            digest != release.content_digest
            or evidence_module not in files
            or DESCRIPTOR in files
        ):
            raise StateContinuityError("state_evidence_invalid")
        evidence.append(_sha256((release_root / evidence_module).read_bytes()))
    if evidence[0] != evidence[1]:
        raise StateContinuityError("state_evidence_differs")
    preview = {
        "contract": CONTRACT, "status": "preview",
        "agent_id": record.agent_id,
        "source_release_id": source_release_id,
        "target_release_id": target_release_id,
        "source_content_digest": source.content_digest,
        "target_content_digest": target.content_digest,
        "evidence_module": evidence_module,
        "evidence_sha256": evidence[0],
        "state_contract": contract.model_dump(),
    }
    if not apply:
        return preview
    if (
        expected_source_digest != source.content_digest
        or expected_target_digest != target.content_digest
        or expected_evidence_sha256 != evidence[0]
    ):
        raise StateContinuityError("state_evidence_changed")
    root = Path(storage_root).resolve(strict=True)
    registry = root / _REGISTRY
    with _exclusive_state_lock(registry.with_suffix(".lock")):
        records = _legacy_records(root)
        for release in (source, target):
            item = {
                "agent_id": record.agent_id,
                "release_id": release.release_id,
                "content_digest": release.content_digest,
                "signer_id": release.signer_id,
                "evidence_module": evidence_module,
                "evidence_sha256": evidence[0],
                "state_contract": contract.model_dump(),
            }
            existing = [
                candidate for candidate in records
                if candidate.get("agent_id") == record.agent_id
                and candidate.get("release_id") == release.release_id
            ]
            if existing and existing != [item]:
                raise StateContinuityError("state_contract_registry_conflict")
            if not existing:
                records.append(item)
        _write_json(registry, {"schema_version": 1, "contracts": records})
    return {**preview, "status": "registered"}
