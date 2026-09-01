from __future__ import annotations

import pytest
from agentscope.message import Msg

from qwenpaw.app.sealed_agents.adapters import (
    SealedEntrypointAdapterV1,
    SealedHarnessAdapterV1,
    SealedHarnessExecutionError,
    UnsupportedSealedRuntime,
    get_runtime_adapter,
)
from qwenpaw.app.sealed_agents.entrypoint_protocol import RuntimeFinal
from qwenpaw.app.sealed_agents.harness_protocol import HarnessStageResponse
from qwenpaw.app.sealed_agents.request_context import SealedAdapterRequest
from qwenpaw.app.sealed_agents.runtime import PinnedSealedRuntime


def test_only_allowlisted_runtime_adapters_can_be_resolved():
    standard = get_runtime_adapter("standard", "1")
    harness = get_runtime_adapter("sealed_harness", "1")
    entrypoint = get_runtime_adapter("sealed_entrypoint", "1")

    assert standard.key == ("standard", "1")
    assert harness.key == ("sealed_harness", "1")
    assert entrypoint.key == ("sealed_entrypoint", "1")


def test_unknown_adapter_is_rejected():
    with pytest.raises(UnsupportedSealedRuntime):
        get_runtime_adapter("arbitrary", "1")


def test_unknown_contract_version_is_rejected():
    with pytest.raises(UnsupportedSealedRuntime):
        get_runtime_adapter("sealed_harness", "2")


class _Harness:
    def __init__(self, events, failed_stage=None):
        self.events = events
        self.failed_stage = failed_stage

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def invoke(self, stage, payload):
        self.events.append(stage)
        if stage == self.failed_stage:
            raise RuntimeError("private failure")
        result = dict(payload)
        if stage == "required_skill_dispatch":
            result["capability"] = "model_execution"
        if stage == "render_bound":
            result["messages"] = [
                {"role": "assistant", "content": "rendered"},
            ]
            if hasattr(self, "debug"):
                result["debug"] = self.debug
        return HarnessStageResponse(
            request_id="test",
            ok=True,
            payload=result,
        )


def _pinned(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    return PinnedSealedRuntime(
        agent_id="sealed",
        release_id="release-1",
        version="1.0.0",
        content_digest=f"sha256:{'a' * 64}",
        release_root=release,
        entrypoint="agent/runtime.py",
        adapter_key=("sealed_harness", "1"),
        failure_policy="fail_closed",
    )


def _entrypoint_pinned(tmp_path):
    release = tmp_path / "entrypoint-release"
    release.mkdir()
    return PinnedSealedRuntime(
        agent_id="sealed",
        release_id="release-entrypoint",
        version="1.2.0",
        content_digest=f"sha256:{'b' * 64}",
        release_root=release,
        entrypoint="agent/runtime.py",
        adapter_key=("sealed_entrypoint", "1"),
        failure_policy="fail_closed",
    )


class _EntrypointProcess:
    def __init__(self, final, events, pinned, session_root):
        self.final = final
        self.events = events
        self.pinned = pinned
        self.session_root = session_root

    async def __aenter__(self):
        self.events.append(("session_root", self.session_root))
        return self

    async def __aexit__(self, *_exc):
        return None

    async def invoke(self, request, host_handler):
        self.events.append(("invoke", request))
        result = await host_handler(
            "agent.execute",
            {
                "messages": [
                    {"name": "user", "role": "user", "content": "controlled"},
                ],
                "instruction": "controller instruction",
            },
        )
        self.events.append(("host_result", result))
        return self.final


def _final(diagnostics=None):
    return RuntimeFinal(
        type="runtime.final",
        protocol_version="1",
        invocation_id="invocation-1",
        message_id="final-1",
        reply="final reply",
        artifacts=[],
        diagnostics=diagnostics,
    )


def _entrypoint_adapter(final, events):
    return SealedEntrypointAdapterV1(
        process_factory=lambda pinned, session_root: _EntrypointProcess(
            final,
            events,
            pinned,
            session_root,
        ),
    )


def _entrypoint_request(tmp_path, *, diagnostics_authorized=False):
    return SealedAdapterRequest(
        messages=(Msg(name="user", role="user", content="hello"),),
        trusted_context={
            "agent_id": "sealed",
            "release_id": "release-entrypoint",
            "version": "1.2.0",
            "content_digest": f"sha256:{'b' * 64}",
            "session_id": "session-1",
            "user_id": "user-1",
            "channel": "open:app",
            "invocation_id": "invocation-1",
        },
        metadata={"diagnostics_authorized": False, "luyu_debug": True},
        session_root=tmp_path / "sessions" / "session-1",
        diagnostics_authorized=diagnostics_authorized,
    )


@pytest.mark.asyncio
async def test_entrypoint_adapter_runs_host_agent_and_yields_one_final_message(
    tmp_path,
):
    events = []
    adapter = _entrypoint_adapter(_final({"stage": "S1"}), events)

    async def model_executor(messages, context):
        assert messages[0].get_text_content() == "controlled"
        assert context == {"model_instruction": "controller instruction"}
        yield Msg(name="assistant", role="assistant", content="draft one"), False
        yield Msg(name="assistant", role="assistant", content="draft final"), True

    result = [
        item
        async for item in adapter.run(
            pinned=_entrypoint_pinned(tmp_path),
            request=_entrypoint_request(tmp_path),
            model_executor=model_executor,
        )
    ]

    assert len(result) == 1
    assert result[0][0].get_text_content() == "final reply"
    assert result[0][0].metadata in (None, {})
    assert result[0][1] is True
    assert events[-1][1]["messages"][-1]["content"] == "draft final"


@pytest.mark.asyncio
async def test_entrypoint_adapter_exposes_diagnostics_only_with_trusted_authorization(
    tmp_path,
):
    events = []
    adapter = _entrypoint_adapter(_final({"stage": "S1"}), events)

    async def model_executor(_messages, _context):
        yield Msg(name="assistant", role="assistant", content="draft"), True

    result = [
        item
        async for item in adapter.run(
            pinned=_entrypoint_pinned(tmp_path),
            request=_entrypoint_request(tmp_path, diagnostics_authorized=True),
            model_executor=model_executor,
        )
    ]

    diagnostics = result[0][0].metadata["sealed_runtime_diagnostics"]
    assert diagnostics["agent"] == {"stage": "S1"}
    assert diagnostics["runtime"] == {
        "release_id": "release-entrypoint",
        "version": "1.2.0",
        "content_digest": f"sha256:{'b' * 64}",
        "adapter": "sealed_entrypoint",
        "contract_version": "1",
    }


@pytest.mark.asyncio
async def test_legacy_harness_debug_uses_only_trusted_generic_authorization(tmp_path):
    events = []
    harness = _Harness(events)
    harness.debug = {"legacy": True}
    adapter = SealedHarnessAdapterV1(harness_factory=lambda _pinned: harness)

    async def model_executor(_messages, _context):
        yield Msg(name="assistant", role="assistant", content="draft"), True

    request = SealedAdapterRequest(
        messages=(Msg(name="user", role="user", content="hello"),),
        trusted_context={},
        metadata={},
        diagnostics_authorized=True,
    )
    result = [
        item
        async for item in adapter.run(
            pinned=_pinned(tmp_path),
            request=request,
            model_executor=model_executor,
        )
    ]

    assert result[-1][0].metadata["sealed_runtime_diagnostics"] == {
        "legacy": True,
    }


@pytest.mark.asyncio
async def test_harness_runs_every_stage_when_debug_is_false(tmp_path):
    events = []
    harness = _Harness(events)
    adapter = SealedHarnessAdapterV1(harness_factory=lambda _pinned: harness)

    async def model_executor(messages, context):
        events.append("model_execution")
        yield Msg(name="assistant", role="assistant", content="draft"), True

    request = SealedAdapterRequest(
        messages=(Msg(name="user", role="user", content="hello"),),
        trusted_context={"debug_endpoint_authorized": False},
        metadata={"luyu_debug": False},
    )
    result = [
        item
        async for item in adapter.run(
            pinned=_pinned(tmp_path),
            request=request,
            model_executor=model_executor,
        )
    ]

    assert events == [
        "prepare_interaction",
        "controller_gate",
        "required_skill_dispatch",
        "model_execution",
        "completion_validation",
        "commit",
        "render_bound",
    ]
    assert result[-1][0].get_text_content() == "rendered"
    assert result[-1][1] is True


@pytest.mark.asyncio
async def test_harness_stage_failure_never_runs_standard_fallback(tmp_path):
    events = []
    harness = _Harness(events, failed_stage="controller_gate")
    adapter = SealedHarnessAdapterV1(harness_factory=lambda _pinned: harness)
    model_called = False

    async def model_executor(messages, context):
        nonlocal model_called
        model_called = True
        yield Msg(name="assistant", role="assistant", content="draft"), True

    request = SealedAdapterRequest(messages=(), trusted_context={}, metadata={})

    with pytest.raises(SealedHarnessExecutionError):
        _ = [
            item
            async for item in adapter.run(
                pinned=_pinned(tmp_path),
                request=request,
                model_executor=model_executor,
            )
        ]
    assert model_called is False
