from __future__ import annotations

import pytest

from qwenpaw.app.sealed_agents.adapters import (
    SealedHarnessAdapterV1,
    SealedHarnessExecutionError,
    UnsupportedSealedRuntime,
    get_runtime_adapter,
)
from qwenpaw.app.sealed_agents.harness_protocol import HarnessStageResponse
from qwenpaw.app.sealed_agents.request_context import SealedAdapterRequest
from qwenpaw.app.sealed_agents.runtime import PinnedSealedRuntime
from agentscope.message import Msg


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
