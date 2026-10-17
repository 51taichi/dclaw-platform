from __future__ import annotations

import pytest

from qwenpaw.app.local_execution.session import (
    LOCAL_EXECUTION_SESSION_CAPABILITY,
    LocalExecutionSessionError,
    inject_local_execution_session,
    issue_local_execution_session,
    verify_local_execution_session,
)

SECRET = "local-execution-session-secret-32-bytes"


def test_ordinary_agent_context_is_unchanged_without_signer(monkeypatch):
    monkeypatch.delenv("DCLAW_LOCAL_EXECUTION_SESSION_SECRET", raising=False)
    context = {"user_id": "u1", "session_id": "s1", "agent_id": "ordinary"}

    assert inject_local_execution_session(
        context,
        granted_capabilities={},
        invocation_id="invocation-1",
    ) == context


def test_authorized_agent_receives_relay_compatible_session():
    context = {"user_id": "u1", "session_id": "s1", "agent_id": "super_agent"}
    enriched = inject_local_execution_session(
        context,
        granted_capabilities={LOCAL_EXECUTION_SESSION_CAPABILITY: "1"},
        invocation_id="invocation-1",
        secret=SECRET,
        now=1_000,
    )

    assert context == {"user_id": "u1", "session_id": "s1", "agent_id": "super_agent"}
    assert verify_local_execution_session(
        enriched["local_execution_session_token"], secret=SECRET, now=1_001
    ) == {
        "v": 1,
        "u": "u1",
        "s": "s1",
        "a": "super_agent",
        "i": "invocation-1",
        "iat": 1_000,
        "exp": 1_600,
    }


def test_tampered_and_expired_sessions_are_rejected():
    token = issue_local_execution_session(
        user_id="u1",
        session_id="s1",
        agent_id="super_agent",
        invocation_id="invocation-1",
        secret=SECRET,
        now=1_000,
    )

    with pytest.raises(LocalExecutionSessionError):
        verify_local_execution_session(token + "x", secret=SECRET, now=1_001)
    with pytest.raises(LocalExecutionSessionError):
        verify_local_execution_session(token, secret=SECRET, now=1_600)


def test_authorized_agent_fails_closed_without_signer(monkeypatch):
    monkeypatch.delenv("DCLAW_LOCAL_EXECUTION_SESSION_SECRET", raising=False)

    with pytest.raises(LocalExecutionSessionError):
        inject_local_execution_session(
            {"user_id": "u1", "session_id": "s1", "agent_id": "super_agent"},
            granted_capabilities={LOCAL_EXECUTION_SESSION_CAPABILITY: "1"},
            invocation_id="invocation-1",
        )
