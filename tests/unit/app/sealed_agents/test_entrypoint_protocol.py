from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from qwenpaw.app.sealed_agents.entrypoint_protocol import (
    HostCall,
    RuntimeFinal,
    RuntimeInvoke,
    SealedEntrypointProcess,
    validate_protocol_message,
)
from qwenpaw.app.sealed_agents.runtime import PinnedSealedRuntime


def _invoke_payload() -> dict:
    return {
        "type": "runtime.invoke",
        "protocol_version": "1",
        "invocation_id": "inv-1",
        "message_id": "msg-1",
        "release": {
            "release_id": "release-1",
            "version": "1.1.0",
            "content_digest": f"sha256:{'a' * 64}",
        },
        "session": {
            "conversation_id": "open:app:pub:user:session",
            "user_id": "user-1",
            "channel": "open:app",
        },
        "input": {
            "role": "user",
            "content": "hello",
            "attachments": [],
        },
        "metadata": {"case": {"id": "case-1"}},
        "history": [],
        "runtime": {
            "diagnostics_authorized": False,
            "capabilities": ["agent.execute"],
        },
    }


def test_runtime_invoke_accepts_complete_literal_contract():
    request = RuntimeInvoke.model_validate(_invoke_payload())

    assert request.session.conversation_id == "open:app:pub:user:session"
    assert request.runtime.capabilities == ["agent.execute"]
    assert request.metadata == {"case": {"id": "case-1"}}


def test_runtime_invoke_rejects_unknown_fields_and_versions():
    unknown = _invoke_payload()
    unknown["agent_specific_stage"] = "S1"
    with pytest.raises(ValidationError):
        RuntimeInvoke.model_validate(unknown)

    wrong_version = _invoke_payload()
    wrong_version["protocol_version"] = "2"
    with pytest.raises(ValidationError):
        RuntimeInvoke.model_validate(wrong_version)


def test_host_call_rejects_unsupported_capability():
    with pytest.raises(ValidationError):
        HostCall(
            type="host.call",
            protocol_version="1",
            invocation_id="inv-1",
            call_id="call-1",
            capability="read.release.source",
            arguments={},
        )


def test_runtime_final_requires_one_non_empty_reply():
    with pytest.raises(ValidationError):
        RuntimeFinal(
            type="runtime.final",
            protocol_version="1",
            invocation_id="inv-1",
            message_id="final-1",
            reply="",
            artifacts=[],
            diagnostics=None,
        )


def test_protocol_message_rejects_oversized_payload():
    payload = _invoke_payload()
    payload["metadata"] = {"bulk": "x" * (1024 * 1024)}

    with pytest.raises(ValueError, match="too large"):
        validate_protocol_message(json.dumps(payload).encode())


def _pinned(tmp_path: Path) -> PinnedSealedRuntime:
    release = tmp_path / "release"
    fixture = (
        Path(__file__).parents[3]
        / "fixtures"
        / "sealed_entrypoint"
        / "agent"
    )
    (release / "agent").mkdir(parents=True, exist_ok=True)
    (release / "agent/runtime.py").write_bytes(
        (fixture / "runtime.py").read_bytes(),
    )
    (release / "agent/resource.txt").write_bytes(
        (fixture / "resource.txt").read_bytes(),
    )
    return PinnedSealedRuntime(
        agent_id="sealed",
        release_id="release-1",
        version="1.0.0",
        content_digest=f"sha256:{'a' * 64}",
        release_root=release,
        entrypoint="agent/runtime.py",
        adapter_key=("sealed_entrypoint", "1"),
        failure_policy="fail_closed",
    )


def _direct_worker_command(
    pinned: PinnedSealedRuntime,
    session_root: Path,
) -> list[str]:
    worker = (
        Path(__file__).parents[4]
        / "src/qwenpaw/app/sealed_agents/entrypoint_worker.py"
    )
    return [
        sys.executable,
        "-I",
        str(worker),
        "--release-root",
        str(pinned.release_root),
        "--session-root",
        str(session_root),
        "--entrypoint",
        pinned.entrypoint,
    ]


async def _invoke_fixture(tmp_path: Path, session_name: str) -> RuntimeFinal:
    pinned = _pinned(tmp_path)
    session_root = tmp_path / "sessions" / session_name
    request = RuntimeInvoke.model_validate(_invoke_payload())

    async def host_handler(capability, arguments):
        assert capability == "agent.execute"
        assert arguments["instruction"] == "resource=sealed resource available"
        return {"reply": "host reply"}

    process = SealedEntrypointProcess(
        pinned,
        session_root=session_root,
        command_builder=_direct_worker_command,
    )
    async with process:
        return await process.invoke(request, host_handler)


@pytest.mark.asyncio
async def test_entrypoint_persists_same_session_and_calls_host(tmp_path):
    first = await _invoke_fixture(tmp_path, "session-a")
    second = await _invoke_fixture(tmp_path, "session-a")
    isolated = await _invoke_fixture(tmp_path, "session-b")

    assert first.reply == "host reply / turn 1"
    assert second.reply == "host reply / turn 2"
    assert isolated.reply == "host reply / turn 1"
    assert second.diagnostics == {
        "release_resource": "sealed resource available",
        "turn": 2,
    }


@pytest.mark.asyncio
async def test_entrypoint_handshake_reports_generic_contract(tmp_path):
    pinned = _pinned(tmp_path)
    process = SealedEntrypointProcess(
        pinned,
        session_root=tmp_path / "sessions" / "handshake",
        command_builder=_direct_worker_command,
    )

    async with process:
        ready = await process.handshake()

    assert ready.adapter == "sealed_entrypoint"
    assert ready.contract_version == "1"


@pytest.mark.asyncio
async def test_entrypoint_refuses_more_than_one_invoke_per_process(tmp_path):
    pinned = _pinned(tmp_path)
    process = SealedEntrypointProcess(
        pinned,
        session_root=tmp_path / "sessions" / "single",
        command_builder=_direct_worker_command,
    )
    request = RuntimeInvoke.model_validate(_invoke_payload())

    async def host_handler(_capability, _arguments):
        return {"reply": "host reply"}

    async with process:
        await process.invoke(request, host_handler)
        with pytest.raises(RuntimeError, match="already completed"):
            await process.invoke(request, host_handler)


@pytest.mark.asyncio
async def test_entrypoint_host_handler_failure_is_fail_closed(tmp_path):
    pinned = _pinned(tmp_path)
    process = SealedEntrypointProcess(
        pinned,
        session_root=tmp_path / "sessions" / "failure",
        command_builder=_direct_worker_command,
    )
    request = RuntimeInvoke.model_validate(_invoke_payload())

    async def host_handler(_capability, _arguments):
        raise RuntimeError("private host failure")

    async with process:
        with pytest.raises(RuntimeError, match="entrypoint"):
            await asyncio.wait_for(
                process.invoke(request, host_handler),
                timeout=5,
            )
