from __future__ import annotations

from pathlib import Path

from agentscope.message import Msg

from qwenpaw.app.runner.runner import _sealed_model_execution_messages
from qwenpaw.app.sealed_agents.runtime import (
    PinnedSealedRuntime,
    resolve_adapter_session_root,
)


def _pinned(tmp_path: Path, adapter: str) -> PinnedSealedRuntime:
    release = tmp_path / "release"
    release.mkdir(exist_ok=True)
    return PinnedSealedRuntime(
        agent_id="sealed-agent",
        release_id="release-1",
        version="1.0.0",
        content_digest=f"sha256:{'a' * 64}",
        release_root=release,
        entrypoint="agent/runtime.py",
        adapter_key=(adapter, "1"),
        failure_policy="fail_closed",
    )


def test_non_sealed_and_legacy_paths_do_not_create_entrypoint_session(tmp_path):
    sessions_root = tmp_path / "sessions"

    assert resolve_adapter_session_root(
        None,
        session_id="session-1",
        sessions_root=sessions_root,
    ) is None
    assert resolve_adapter_session_root(
        _pinned(tmp_path, "standard"),
        session_id="session-1",
        sessions_root=sessions_root,
    ) is None
    assert resolve_adapter_session_root(
        _pinned(tmp_path, "sealed_harness"),
        session_id="session-1",
        sessions_root=sessions_root,
    ) is None
    assert not sessions_root.exists()


def test_entrypoint_session_root_is_stable_and_isolated(tmp_path):
    sessions_root = tmp_path / "sessions"
    pinned = _pinned(tmp_path, "sealed_entrypoint")

    first = resolve_adapter_session_root(
        pinned,
        session_id="session-1",
        sessions_root=sessions_root,
    )
    repeated = resolve_adapter_session_root(
        pinned,
        session_id="session-1",
        sessions_root=sessions_root,
    )
    other = resolve_adapter_session_root(
        pinned,
        session_id="session-2",
        sessions_root=sessions_root,
    )

    assert first == repeated
    assert first == sessions_root / "sealed-agent" / "session-1"
    assert other == sessions_root / "sealed-agent" / "session-2"
    assert first.is_dir()
    assert other.is_dir()


def test_entrypoint_promotes_trusted_controller_instruction_to_system_role():
    customer = Msg(name="user", role="user", content="hello")

    messages = _sealed_model_execution_messages(
        (customer,),
        {"model_instruction": "return the controller contract"},
    )

    assert messages[0] is customer
    assert messages[-1].name == "sealed_controller"
    assert messages[-1].role == "system"
    assert messages[-1].get_text_content() == "return the controller contract"
