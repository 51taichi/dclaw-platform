"""Resolve existing AIGC tasks through committed installation continuity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .state_continuity import (
    StateContinuityError,
    _binding_matches,
    _committed_state_file,
    _receipt_path,
    _state_dir,
)


CONTRACT = "aigc.task.binding.resolve/1"


def compatible_installations(
    *, storage_root: Path, grants: Any, agent_id: str, tenant_id: str,
    installation_id: str, release_id: str, session_id: str, user_id: str,
) -> frozenset[str]:
    """Walk only committed, intact state continuity receipts for this chat."""
    root = Path(storage_root)
    current = installation_id
    expected_release = release_id
    visited: set[str] = set()
    while current not in visited:
        visited.add(current)
        grant = grants.get(current)
        if (
            grant is None or grant.agent_id != agent_id
            or grant.tenant_id != tenant_id
            or grant.release_id != expected_release
        ):
            raise StateContinuityError("aigc_binding_scope_invalid")
        receipt_path = _receipt_path(root, current, session_id)
        if not receipt_path.exists() and not receipt_path.is_symlink():
            break
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise StateContinuityError("aigc_binding_receipt_invalid")
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise StateContinuityError("aigc_binding_receipt_invalid") from exc
        if (
            not isinstance(receipt, dict)
            or receipt.get("contract") != "workspace.state.continuity/1"
            or receipt.get("status") != "committed"
            or receipt.get("agent_id") != agent_id
            or receipt.get("session_id") != session_id
            or receipt.get("target_installation_id") != current
            or receipt.get("target_release_id") != expected_release
        ):
            raise StateContinuityError("aigc_binding_receipt_invalid")
        state_file = _committed_state_file(_state_dir(root, current, session_id))
        if (
            state_file is None
            or state_file.name != receipt.get("target_filename")
            or not _binding_matches(root, current, session_id, state_file.name)
        ):
            raise StateContinuityError("aigc_binding_receipt_invalid")
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise StateContinuityError("aigc_binding_receipt_invalid") from exc
        if not isinstance(state, dict) or state.get("identity") != {
            "installation_id": current,
            "user_id": user_id,
            "session_id": session_id,
        }:
            raise StateContinuityError("aigc_binding_receipt_invalid")
        source = receipt.get("source_installation_id")
        expected_release = receipt.get("source_release_id")
        if (
            not isinstance(source, str) or not source
            or not isinstance(expected_release, str) or not expected_release
            or source in visited
        ):
            raise StateContinuityError("aigc_binding_receipt_invalid")
        current = source
    return frozenset(visited)


def owned_task(
    *, task: Any, adapter: Any, user_id: str, conversation_id: str,
    allowed_installations: frozenset[str],
) -> bool:
    if task is None or adapter is None:
        return False
    binding = task.binding
    if (
        binding.installation_id not in allowed_installations
        or binding.conversation_id != conversation_id
    ):
        return False
    try:
        canvas, _ = adapter.workflow_context(
            canvas_id=binding.canvas_id,
            material_task_id=binding.material_task_id,
        )
    except (OSError, ValueError):
        return False
    return (
        canvas is not None
        and canvas.id == binding.canvas_id
        and canvas.meta.get("owner_user_id") == user_id
        and canvas.meta.get("super_expert_material_task_id")
        == binding.material_task_id
    )


def resolve_existing_binding(
    *, tasks: tuple[Any, ...], adapter: Any, user_id: str,
    conversation_id: str, allowed_installations: frozenset[str],
    task_key: str | None = None, content_revision: int | None = None,
) -> dict[str, Any]:
    """Return one authoritative binding; never infer one from a card title."""
    if (
        task_key is not None
        and (not isinstance(task_key, str) or not task_key.strip()
             or len(task_key) > 160)
    ) or (
        content_revision is not None
        and (type(content_revision) is not int or content_revision < 1)
    ) or (content_revision is not None and task_key is None):
        return {"contract": CONTRACT, "status": "invalid_request"}
    candidates = []
    for task in tasks:
        binding = task.binding
        if task_key is not None:
            from .aigc_tools import _identity

            expected_task_id = "content-" + _identity(
                binding.installation_id, conversation_id, task_key,
            )
            if binding.agent_task_id != expected_task_id:
                continue
        if content_revision is not None and binding.content_revision != content_revision:
            continue
        if owned_task(
            task=task, adapter=adapter, user_id=user_id,
            conversation_id=conversation_id,
            allowed_installations=allowed_installations,
        ):
            candidates.append(task)
    if len(candidates) != 1:
        return {
            "contract": CONTRACT,
            "status": "not_found" if not candidates else "ambiguous",
        }
    binding = candidates[0].binding
    return {
        "contract": CONTRACT,
        "status": "found",
        "material_task_id": binding.material_task_id,
        "source_installation_id": binding.installation_id,
        "content_revision": binding.content_revision,
        "task_status": candidates[0].status.value,
    }


def read_developer_binding(
    *, storage_root: Path, grants: Any, task_repository: Any,
    event_repository: Any, adapter: Any,
    owner_resolver: Any, agent_id: str, tenant_id: str,
    installation_id: str, release_id: str, session_id: str,
    task_key: str | None = None, content_revision: int | None = None,
) -> dict[str, Any]:
    """Owner-authorized, content-free lookup for a developer's customer chat."""
    contract = "developer.aigc.binding.lookup/1"
    owner = owner_resolver(session_id)
    if (
        not isinstance(owner, dict)
        or owner.get("agent_id") != agent_id
        or owner.get("tenant_id") != tenant_id
        or owner.get("session_id") != session_id
        or not isinstance(owner.get("user_id"), str)
    ):
        return {"contract": contract, "status": "not_found"}
    try:
        installations = compatible_installations(
            storage_root=storage_root, grants=grants,
            agent_id=agent_id, tenant_id=tenant_id,
            installation_id=installation_id, release_id=release_id,
            session_id=session_id, user_id=owner["user_id"],
        )
    except StateContinuityError:
        return {"contract": contract, "status": "unavailable"}
    result = resolve_existing_binding(
        tasks=task_repository.list_for_conversations({session_id}),
        adapter=adapter, user_id=owner["user_id"],
        conversation_id=session_id, allowed_installations=installations,
        task_key=task_key, content_revision=content_revision,
    )
    if result["status"] != "found":
        return {**result, "contract": contract}
    try:
        created_event_persisted = any(
            event.event_type == "aigc.task.created"
            and event.material_task_id == result["material_task_id"]
            for event in event_repository.list_for_session(
                installation_id=result["source_installation_id"],
                conversation_id=session_id,
            )
        )
        state_file = _committed_state_file(
            _state_dir(Path(storage_root), installation_id, session_id),
        )
        state = (
            json.loads(state_file.read_text(encoding="utf-8"))
            if state_file is not None else {}
        )
        if not isinstance(state, dict):
            raise ValueError("invalid state")
        stack = [state]
        references_task = False
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
            elif value == result["material_task_id"]:
                references_task = True
                break
    except (StateContinuityError, OSError, UnicodeError, ValueError):
        return {"contract": contract, "status": "unavailable"}
    return {
        **result,
        "contract": contract,
        "created_event_persisted": created_event_persisted,
        "current_workspace_references_task": references_task,
    }
