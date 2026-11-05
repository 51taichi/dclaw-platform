"""Operator-controlled, copy-on-write migration of one empty state field."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from .orchestration import WorkspaceStateTransaction, _scope_key


class StateMigrationError(ValueError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _value_digest(value: Any) -> str:
    return _sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))


def _tokens(pointer: str) -> list[str]:
    if not pointer.startswith("/") or pointer in {"/", "/identity", "/schema_version"}:
        raise StateMigrationError("invalid state pointer")
    tokens = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    if any(not part or part in {"identity", "schema_version"} for part in tokens):
        raise StateMigrationError("protected state field")
    return tokens


def _field(document: dict[str, Any], tokens: list[str]) -> Any:
    current: Any = document
    for token in tokens:
        if not isinstance(current, dict) or token not in current:
            raise StateMigrationError("state pointer not found")
        current = current[token]
    return current


def _state_file(root: Path, installation_id: str, session_id: str) -> Path:
    directory = root / "state" / _scope_key(installation_id) / _scope_key(session_id)
    if not directory.is_dir() or directory.is_symlink():
        raise StateMigrationError("state directory missing or unsafe")
    if any(path.is_symlink() for path in directory.rglob("*")):
        raise StateMigrationError("state directory contains a symlink")
    files = list(directory.iterdir())
    if len(files) != 1 or not files[0].is_file() or files[0].suffix != ".json":
        raise StateMigrationError("expected exactly one state JSON file")
    return files[0]


def _empty_target_state(source: dict[str, Any], installation_id: str) -> dict[str, Any]:
    """Derive an empty schema from a source state without copying business values."""
    def empty(value: Any) -> Any:
        if isinstance(value, list):
            return []
        if isinstance(value, dict):
            if not value:
                return {}
            if all(isinstance(item, (list, dict)) for item in value.values()):
                return {key: empty(item) for key, item in value.items()}
        raise StateMigrationError("source state cannot define an empty target schema")

    if not isinstance(source.get("schema_version"), int):
        raise StateMigrationError("source state schema version missing")
    identity = source["identity"]
    return {
        "schema_version": source["schema_version"],
        "identity": {**identity, "installation_id": installation_id},
        **{key: empty(value) for key, value in source.items()
           if key not in {"schema_version", "identity"}},
    }


def _read_state(path: Path, installation_id: str, session_id: str, user_id: str) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    try:
        document = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StateMigrationError("invalid state JSON") from exc
    if not isinstance(document, dict) or document.get("identity") != {
        "installation_id": installation_id,
        "session_id": session_id,
        "user_id": user_id,
    }:
        raise StateMigrationError("state identity mismatch")
    return document, _sha256(raw)


def migrate_empty_field(
    *,
    storage_root: Path,
    grants: Any,
    source_installation_id: str,
    target_installation_id: str,
    session_id: str,
    user_id: str,
    pointer: str,
    apply: bool = False,
    expected_source_file_sha256: str | None = None,
    expected_target_file_sha256: str | None = None,
    bootstrap_empty_target: bool = False,
) -> dict[str, Any]:
    """Copy a nonempty JSON array into an empty field; preserve all other target state."""
    source_grant = grants.get(source_installation_id)
    target_grant = grants.get(target_installation_id)
    if (
        source_installation_id == target_installation_id
        or source_grant is None or target_grant is None
        or source_grant.agent_id != target_grant.agent_id
        or source_grant.tenant_id != target_grant.tenant_id
        or source_grant.release_id == target_grant.release_id
    ):
        raise StateMigrationError("installations do not belong to one agent and tenant")
    tokens = _tokens(pointer)
    root = Path(storage_root).resolve(strict=True)
    source_file = _state_file(root, source_installation_id, session_id)
    source, source_sha = _read_state(source_file, source_installation_id, session_id, user_id)
    try:
        target_file = _state_file(root, target_installation_id, session_id)
    except StateMigrationError as exc:
        target_dir = root / "state" / _scope_key(target_installation_id) / _scope_key(session_id)
        if (
            not bootstrap_empty_target or target_dir.exists() or target_dir.is_symlink()
            or target_dir.parent.is_symlink()
        ):
            raise exc
        target_file = target_dir / source_file.name
        target = _empty_target_state(source, target_installation_id)
        target_sha = "missing"
    else:
        target, target_sha = _read_state(target_file, target_installation_id, session_id, user_id)
    source_value = _field(source, tokens)
    target_value = _field(target, tokens)
    if not isinstance(source_value, list) or not source_value or target_value != []:
        raise StateMigrationError("source must be nonempty and target must be an empty array")
    if not apply:
        return {
            "contract": "workspace.state.empty-field-migration/1",
            "status": "preview",
            "agent_id": source_grant.agent_id,
            "session_id": session_id,
            "source_installation_id": source_installation_id,
            "source_release_id": source_grant.release_id,
            "target_installation_id": target_installation_id,
            "target_release_id": target_grant.release_id,
            "pointer": pointer,
            "source_file_sha256": source_sha,
            "target_file_sha256": target_sha,
            "target_bootstrap_required": target_sha == "missing",
            "source_value_sha256": _value_digest(source_value),
            "source_versions": [item.get("version") for item in source_value if isinstance(item, dict)],
            "target_count": 0,
        }
    if source_sha != expected_source_file_sha256 or target_sha != expected_target_file_sha256:
        raise StateMigrationError("state changed since preview")

    migration_id = uuid.uuid4().hex
    transaction = WorkspaceStateTransaction.begin(
        root,
        installation_id=target_installation_id,
        session_id=session_id,
        invocation_id=migration_id,
    )
    try:
        staged_file = transaction.transaction_root / target_file.name
        if target_sha == "missing":
            if staged_file.exists() or any(transaction.transaction_root.iterdir()):
                raise StateMigrationError("target changed during migration")
            staged = target
        else:
            staged, staged_sha = _read_state(
                staged_file, target_installation_id, session_id, user_id,
            )
            if staged_sha != target_sha or _field(staged, tokens) != []:
                raise StateMigrationError("target changed during migration")
        current_source, current_source_sha = _read_state(
            source_file, source_installation_id, session_id, user_id,
        )
        if current_source_sha != source_sha or _value_digest(_field(current_source, tokens)) != _value_digest(source_value):
            raise StateMigrationError("source changed during migration")
        parent = staged
        for token in tokens[:-1]:
            parent = parent[token]
        parent[tokens[-1]] = source_value
        staged_file.write_text(json.dumps(staged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _, after_sha = _read_state(
            staged_file, target_installation_id, session_id, user_id,
        )
        receipt = {
            "contract": "workspace.state.empty-field-migration/1",
            "migration_id": migration_id,
            "status": "prepared",
            "agent_id": source_grant.agent_id,
            "session_id": session_id,
            "source_installation_id": source_installation_id,
            "source_release_id": source_grant.release_id,
            "target_installation_id": target_installation_id,
            "target_release_id": target_grant.release_id,
            "pointer": pointer,
            "source_file_sha256": source_sha,
            "target_file_sha256_before": target_sha,
            "target_file_sha256_after": after_sha,
            "value_sha256": _value_digest(source_value),
            "versions": [item.get("version") for item in source_value if isinstance(item, dict)],
        }
        receipts = root / "migrations" / "receipts"
        receipts.mkdir(parents=True, exist_ok=True)
        receipt_path = receipts / f"{migration_id}.json"
        temporary = receipt_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, receipt_path)
        transaction.commit()
    except Exception:
        transaction.discard()
        raise
    receipt["status"] = "committed"
    temporary.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, receipt_path)
    return receipt
