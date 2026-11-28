from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, validate

from super_agent.capability_stage import CapabilityStageError, CapabilityStageGate, local_guide
from super_agent.interaction_contract import build_interaction_catalog
from super_agent.orchestration import WorkspaceOrchestrationError, WorkspaceRuntimeHost
from qwenpaw.aigc.capability_guide import build_aigc_guide
from devkit.capability_stage_api_demo import CapabilityGuideError, enter_stage


ROOT = Path(__file__).resolve().parents[1]
GRANTS = {
    "capability.stage.enter/1": "1",
    "agent.execute": "2",
    "interaction.capabilities.list/1": "1",
    "interaction.card.create/1": "1",
    "interaction.card.cancel/1": "1",
    "aigc.workflow.capabilities.list/1": "1",
    "aigc.workflow.create/1": "1",
    "local.task.start/1": "1",
}


def _validate(name: str, payload: dict) -> None:
    schema = json.loads((ROOT / "devkit/schemas/capability-stage-v1" / name).read_text())
    validate(payload, schema)


def test_stage_gate_requires_declaration_and_enforces_model_action_mutual_exclusion():
    gate = CapabilityStageGate(GRANTS)
    with pytest.raises(CapabilityStageError, match="stage_required"):
        gate.model_grants()
    with pytest.raises(CapabilityStageError, match="action_outside_stage"):
        gate.check("interaction.card.create/1")
    gate.enter("interaction")
    assert "aigc.workflow.create/1" not in gate.model_grants()
    assert "local.task.start/1" not in gate.model_grants()
    assert "interaction.card.create/1" in gate.model_grants()
    gate.check("interaction.card.create/1")
    with pytest.raises(CapabilityStageError, match="action_outside_stage"):
        gate.check("aigc.workflow.create/1")
    with pytest.raises(CapabilityStageError, match="invalid_stage_transition"):
        gate.enter("aigc")
    gate.record_model_call()
    gate.enter("aigc")
    assert "interaction.card.create/1" not in gate.model_grants()
    assert "local.task.start/1" not in gate.model_grants()
    with pytest.raises(CapabilityStageError, match="action_outside_stage"):
        gate.check("interaction.card.cancel/1")
    gate.check("aigc.workflow.create/1")
    with pytest.raises(CapabilityStageError, match="invalid_stage_transition"):
        gate.enter("local")
    with pytest.raises(CapabilityStageError, match="invalid_stage_transition"):
        gate.enter("interaction")


def test_legacy_release_does_not_enable_stage_gate():
    gate = CapabilityStageGate({"agent.execute": "1", "aigc.workflow.create/1": "1"})
    gate.record_model_call()
    gate.check("aigc.workflow.create/1")
    assert gate.model_grants()["aigc.workflow.create/1"] == "1"


def test_local_stage_does_not_expose_aigc_or_interaction_actions():
    gate = CapabilityStageGate(GRANTS)
    gate.enter("local")
    assert "aigc.workflow.create/1" not in gate.model_grants()
    assert "interaction.card.create/1" not in gate.model_grants()
    assert "local.task.start/1" in gate.model_grants()
    gate.check("local.task.start/1")
    with pytest.raises(CapabilityStageError, match="action_outside_stage"):
        gate.check("interaction.card.create/1")
    with pytest.raises(CapabilityStageError, match="undeclared_stage"):
        CapabilityStageGate({"capability.stage.enter/1": "1"}).enter("local")


@pytest.mark.asyncio
async def test_host_returns_current_interaction_guide_and_rejects_cross_stage_action():
    calls = []

    async def business(capability, arguments):
        calls.append((capability, arguments))
        if capability == "interaction.capabilities.list/1":
            return build_interaction_catalog(arguments.get("component_types", []))
        return {"accepted": True}

    host = WorkspaceRuntimeHost(
        request=SimpleNamespace(granted_capabilities=GRANTS, invocation_id="run-1"),
        execute_agent=lambda args: {"content": "ok"},
        session_context=lambda: {},
        business_call=business,
    )
    with pytest.raises(WorkspaceOrchestrationError, match="orchestration_error"):
        await host.call("agent.execute", {"messages": [{"role": "user", "content": "hi"}]})
    _validate("request.schema.json", {"stage": "interaction"})
    response = await host.call("capability.stage.enter/1", {"stage": "interaction"})
    _validate("response.schema.json", response)
    catalog = response["guide"]["catalog"]
    assert {item["component_type"] for item in catalog["components"]} == {
        "single_select", "multi_select", "question_form", "file_selector",
    }
    assert all(isinstance(item["schema"], dict) for item in catalog["components"])
    assert calls[0] == ("interaction.capabilities.list/1", {})
    with pytest.raises(WorkspaceOrchestrationError) as error:
        await host.call("aigc.workflow.create/1", {})
    assert error.value.diagnostic_ref == "action_outside_stage"


@pytest.mark.asyncio
async def test_devkit_demo_uses_live_guide_and_fails_closed_on_wrong_stage():
    class Host:
        async def call(self, capability, arguments):
            assert capability == "capability.stage.enter/1"
            return {
                "contract": capability, "stage": arguments["stage"],
                "guide": {
                    "stage": "interaction", "instructions": "one question",
                    "catalog": build_interaction_catalog([]),
                    "answer_kind_map": {"one_choice": ["single_select"]},
                },
            }

    assert (await enter_stage(Host(), "interaction"))["answer_kind_map"]
    with pytest.raises(CapabilityGuideError, match="invalid stage guide"):
        await enter_stage(Host(), "aigc")


@pytest.mark.asyncio
async def test_host_stage_entry_failure_keeps_previous_stage():
    async def business(capability, arguments):
        if capability == "interaction.capabilities.list/1":
            return build_interaction_catalog(arguments.get("component_types", []))
        raise RuntimeError("catalog unavailable")

    gate = CapabilityStageGate(GRANTS)
    host = WorkspaceRuntimeHost(
        request=SimpleNamespace(granted_capabilities=GRANTS, invocation_id="run-2"),
        execute_agent=lambda args: {}, session_context=lambda: {},
        business_call=business, stage_gate=gate,
    )
    await host.call("capability.stage.enter/1", {"stage": "interaction"})
    await host.call("agent.execute", {})
    with pytest.raises(RuntimeError, match="catalog unavailable"):
        await host.call("capability.stage.enter/1", {"stage": "aigc"})
    assert gate.stage == "interaction"
    assert gate.transitions == 0
    with pytest.raises(WorkspaceOrchestrationError):
        await host.call("capability.stage.enter/1", {"stage": "unknown"})


def test_local_guide_publishes_real_host_schemas():
    guide = local_guide()
    assert guide["stage"] == "local"
    assert guide["owner"] == "dclaw.super-agent-support"
    assert "start_request" in guide["schemas"]
    for schema in guide["schemas"].values():
        Draft202012Validator.check_schema(schema)


def test_aigc_guide_owns_live_catalog_and_complete_create_schema():
    catalog = {"nodes": [{"kind": "image_generate"}], "available_models": []}
    guide = build_aigc_guide(catalog)
    assert guide["catalog"] is catalog
    assert guide["owner"] == "qwenpaw.aigc"
    Draft202012Validator.check_schema(guide["create_request_schema"])
    _validate("response.schema.json", {
        "contract": "capability.stage.enter/1", "stage": "aigc", "guide": guide,
    })
