from __future__ import annotations

import pytest

from qwenpaw.app.super_experts.aigc_tasks import (
    AigcTaskCommand,
    AigcTaskError,
    AigcTaskRepository,
)
from qwenpaw.app.super_experts.models import (
    AigcTaskBinding,
    AigcTaskStatus,
)


def _binding(**overrides):
    values = {
        "installation_id": "installation-1",
        "conversation_id": "conversation-1",
        "agent_task_id": "agent-task-1",
        "content_revision": 3,
        "material_task_id": "material-1",
        "canvas_id": "canvas-1",
        "node_id": "node-1",
    }
    values.update(overrides)
    return AigcTaskBinding(**values)


def _command(action, event_id, **overrides):
    values = {
        "action": action,
        "event_id": event_id,
        "binding": _binding(),
    }
    values.update(overrides)
    return AigcTaskCommand(**values)


@pytest.mark.parametrize(
    ("actions", "expected"),
    [
        (("create",), AigcTaskStatus.WAITING_TO_START),
        (("create", "start"), AigcTaskStatus.IN_PROGRESS),
        (("create", "start", "pause"), AigcTaskStatus.PAUSED),
        (("create", "start", "pause", "resume"), AigcTaskStatus.IN_PROGRESS),
        (("create", "start", "submit"), AigcTaskStatus.SUBMITTED),
        (("create", "start", "submit", "review"), AigcTaskStatus.REVIEWING),
        (
            ("create", "start", "submit", "review", "request_revision"),
            AigcTaskStatus.REVISION_REQUIRED,
        ),
        (
            (
                "create",
                "start",
                "submit",
                "review",
                "request_revision",
                "resume",
            ),
            AigcTaskStatus.IN_PROGRESS,
        ),
        (
            ("create", "start", "submit", "review", "accept"),
            AigcTaskStatus.ACCEPTED,
        ),
    ],
)
def test_every_legal_transition_is_explicit(tmp_path, actions, expected):
    repository = AigcTaskRepository(tmp_path)
    task = None
    for index, action in enumerate(actions):
        extra = {"asset_id": "asset-1"} if action == "submit" else {}
        task = repository.apply(
            _command(action, f"event-{index}", **extra),
            idempotency_key=f"key-{index}",
        )

    assert task.status == expected


@pytest.mark.parametrize(
    ("actions", "illegal"),
    [
        (("create",), "submit"),
        (("create", "start"), "accept"),
        (("create", "start", "submit"), "accept"),
        (("create", "start", "submit", "review", "accept"), "resume"),
        (("create", "cancel"), "start"),
        (("create", "invalidate"), "start"),
    ],
)
def test_illegal_skips_and_terminal_recovery_fail_closed(tmp_path, actions, illegal):
    repository = AigcTaskRepository(tmp_path)
    for index, action in enumerate(actions):
        repository.apply(
            _command(
                action,
                f"event-{index}",
                **({"asset_id": "asset-1"} if action == "submit" else {}),
            ),
            idempotency_key=f"key-{index}",
        )

    with pytest.raises(AigcTaskError, match="transition"):
        repository.apply(
            _command(illegal, "illegal-event"),
            idempotency_key="illegal-key",
        )


@pytest.mark.parametrize(
    "from_actions",
    [
        ("create",),
        ("create", "start"),
        ("create", "start", "pause"),
        ("create", "start", "submit"),
        ("create", "start", "submit", "review"),
        ("create", "start", "submit", "review", "request_revision"),
    ],
)
@pytest.mark.parametrize("terminal", ["cancel", "invalidate"])
def test_any_unfinished_task_can_be_cancelled_or_invalidated(
    tmp_path,
    from_actions,
    terminal,
):
    repository = AigcTaskRepository(tmp_path)
    for index, action in enumerate(from_actions):
        repository.apply(
            _command(
                action,
                f"event-{index}",
                **({"asset_id": "asset-1"} if action == "submit" else {}),
            ),
            idempotency_key=f"key-{index}",
        )
    task = repository.apply(
        _command(terminal, "terminal-event"),
        idempotency_key="terminal-key",
    )

    expected = (
        AigcTaskStatus.CANCELLED
        if terminal == "cancel"
        else AigcTaskStatus.INVALIDATED
    )
    assert task.status == expected


def test_idempotency_replay_returns_same_result_but_key_reuse_fails(tmp_path):
    repository = AigcTaskRepository(tmp_path)
    command = _command("create", "event-1")
    first = repository.apply(command, idempotency_key="same-key")
    replay = repository.apply(command, idempotency_key="same-key")
    assert replay == first

    with pytest.raises(AigcTaskError, match="idempotency"):
        repository.apply(
            _command("start", "event-2"),
            idempotency_key="same-key",
        )


def test_duplicate_event_and_cross_binding_or_stale_revision_are_rejected(tmp_path):
    repository = AigcTaskRepository(tmp_path)
    repository.apply(_command("create", "event-1"), idempotency_key="key-1")

    with pytest.raises(AigcTaskError, match="event"):
        repository.apply(
            _command("start", "event-1"),
            idempotency_key="key-2",
        )
    with pytest.raises(AigcTaskError, match="binding"):
        repository.apply(
            _command("start", "event-2", binding=_binding(canvas_id="other")),
            idempotency_key="key-3",
        )
    with pytest.raises(AigcTaskError, match="binding"):
        repository.apply(
            _command("start", "event-3", binding=_binding(content_revision=4)),
            idempotency_key="key-4",
        )


def test_submitted_asset_is_bound_once_and_cannot_cross_bind(tmp_path):
    repository = AigcTaskRepository(tmp_path)
    repository.apply(_command("create", "event-1"), idempotency_key="key-1")
    repository.apply(_command("start", "event-2"), idempotency_key="key-2")
    submitted = repository.apply(
        _command("submit", "event-3", asset_id="asset-1"),
        idempotency_key="key-3",
    )
    assert submitted.asset_id == "asset-1"

    with pytest.raises(AigcTaskError, match="asset|transition"):
        repository.apply(
            _command("submit", "event-4", asset_id="asset-2"),
            idempotency_key="key-4",
        )
