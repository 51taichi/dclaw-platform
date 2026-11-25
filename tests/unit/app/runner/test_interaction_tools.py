from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from qwenpaw.agents.toolkit import DClawToolkit as Toolkit

from qwenpaw.app.super_experts.interaction_cards import InteractionError
from qwenpaw.app.super_experts.interaction_contract import build_interaction_catalog
from qwenpaw.app.workspace.interaction_tools import (
    CATALOG,
    CANCEL,
    CREATE,
    bind_interaction_tools,
    build_interaction_tools,
)


def _result(response):
    return json.loads(response.content[0].text)


def _single_card():
    return {
        "title": "请选择",
        "options": [
            {"id": "a", "text": "甲", "recommended": True},
            {"text": "乙"},
        ],
        "supplement": {"enabled": True, "required": False},
    }


def _harness(grants=None, cards=None, error=None):
    calls = []

    async def business_call(capability, arguments):
        calls.append((capability, arguments))
        if error is not None:
            raise error
        if capability == CATALOG:
            return build_interaction_catalog(arguments.get("component_types", []))
        if capability == CREATE:
            return {
                "interaction": {
                    "interaction_id": "interaction-1",
                    "status": "PENDING",
                    "version": 1,
                    "input_policy": arguments["request"]["input_policy"],
                },
            }
        if capability == CANCEL:
            return {
                "interaction": {
                    "interaction_id": arguments["interaction_id"],
                    "status": "CANCELLED",
                    "version": 2,
                },
            }
        raise AssertionError(capability)

    def read_card(interaction_id):
        if not interaction_id:
            return (cards or {}).get("active")
        return (cards or {}).get(interaction_id)

    tools = build_interaction_tools(
        grants=grants or {},
        installation_id="installation-1",
        conversation_id="conversation-1",
        business_call=business_call,
        read_card=read_card,
    )
    return tools, calls


def test_only_granted_supported_interaction_tools_are_exposed():
    assert _harness()[0] == {}
    assert _harness({CATALOG: "2"})[0] == {}
    assert set(_harness({CATALOG: "1"})[0]) == {
        "interaction_component_catalog",
    }
    assert set(_harness({CATALOG: "1", CREATE: "1"})[0]) == {
        "interaction_component_catalog",
        "interaction_card_create",
        "interaction_card_status",
    }
    assert set(_harness({CATALOG: "1", CREATE: "1", CANCEL: "1"})[0]) == {
        "interaction_component_catalog",
        "interaction_card_create",
        "interaction_card_status",
        "interaction_card_cancel",
    }


@pytest.mark.asyncio
async def test_catalog_returns_only_requested_detailed_component():
    tools, calls = _harness({CATALOG: "1"})

    reply = _result(
        await tools["interaction_component_catalog"](["single_select"]),
    )

    assert calls == [(CATALOG, {"component_types": ["single_select"]})]
    assert [item["component_type"] for item in reply["components"]] == [
        "single_select",
    ]
    assert reply["components"][0]["schema"]["additionalProperties"] is False


@pytest.mark.asyncio
async def test_question_form_catalog_and_create_dispatch_normalized_items():
    tools, calls = _harness({CATALOG: "1", CREATE: "1"})

    catalog = _result(
        await tools["interaction_component_catalog"](["question_form"]),
    )
    created = _result(
        await tools["interaction_card_create"](
            task_key="business-context",
            interaction_revision=1,
            component_type="question_form",
            card={
                "title": "请补充",
                "items": [{"id": "scope", "question": "服务范围？"}],
            },
        ),
    )

    assert catalog["components"][0]["component_type"] == "question_form"
    assert created["interaction"]["status"] == "PENDING"
    request = calls[1][1]["request"]
    assert request["component_type"] == "question_form"
    assert request["card"]["items"] == [
        {
            "id": "scope",
            "question": "服务范围？",
            "description": None,
            "placeholder": "请输入回答",
            "required": True,
            "max_length": 2000,
        },
    ]


@pytest.mark.asyncio
async def test_create_defaults_to_card_only_and_dispatches_normalized_request():
    tools, calls = _harness({CATALOG: "1", CREATE: "1"})

    reply = _result(
        await tools["interaction_card_create"](
            task_key="candidate-calibration",
            interaction_revision=1,
            component_type="single_select",
            card=_single_card(),
        ),
    )

    assert reply["interaction"]["status"] == "PENDING"
    assert calls[0][0] == CREATE
    arguments = calls[0][1]
    assert arguments["idempotency_key"].startswith("interaction-create-")
    assert arguments["request"]["input_policy"] == "card_only"
    assert arguments["request"]["component_type"] == "single_select"
    assert arguments["request"]["card"]["options"][0] == {
        "id": "a",
        "text": "甲",
        "description": None,
        "recommended": True,
        "default_selected": False,
    }


@pytest.mark.asyncio
async def test_invalid_create_returns_field_issues_without_dispatching():
    tools, calls = _harness({CATALOG: "1", CREATE: "1"})

    reply = _result(
        await tools["interaction_card_create"](
            task_key="candidate-calibration",
            interaction_revision=1,
            component_type="single_select",
            card={"title": "缺选项", "options": []},
        ),
    )

    assert reply["error"] == "INVALID_INTERACTION_REQUEST"
    assert reply["retryable"] is True
    assert reply["issues"]
    assert calls == []


@pytest.mark.asyncio
async def test_unexpected_create_fields_are_rejected_without_dispatching():
    tools, calls = _harness({CATALOG: "1", CREATE: "1"})

    reply = _result(
        await tools["interaction_card_create"](
            task_key="candidate-calibration",
            interaction_revision=1,
            component_type="single_select",
            card=_single_card(),
            custom_color="#fff",
        ),
    )

    assert reply == {
        "error": "INVALID_INTERACTION_REQUEST",
        "issues": [{"field": "custom_color", "code": "FIELD_NOT_ALLOWED"}],
        "retryable": True,
        "guidance": "Remove fields that are not declared by the selected catalog schema.",
    }
    assert calls == []


@pytest.mark.asyncio
async def test_status_reads_only_host_scoped_projection():
    active = {"interaction_id": "interaction-active", "status": "PENDING"}
    tools, _ = _harness(
        {CATALOG: "1", CREATE: "1"},
        cards={"active": active, "interaction-1": None},
    )

    assert _result(await tools["interaction_card_status"]()) == {
        "interaction": active,
    }
    assert _result(
        await tools["interaction_card_status"]("interaction-1"),
    ) == {"error": "INTERACTION_NOT_FOUND", "retryable": False}


@pytest.mark.asyncio
async def test_cancel_derives_scoped_idempotency_key():
    tools, calls = _harness({CATALOG: "1", CREATE: "1", CANCEL: "1"})

    reply = _result(
        await tools["interaction_card_cancel"](
            interaction_id="interaction-1",
            operation_key="replace-question",
        ),
    )

    assert reply["interaction"]["status"] == "CANCELLED"
    capability, arguments = calls[0]
    assert capability == CANCEL
    assert arguments["interaction_id"] == "interaction-1"
    assert arguments["idempotency_key"].startswith("interaction-cancel-")


@pytest.mark.asyncio
async def test_stable_domain_error_is_preserved_for_agent_correction():
    tools, _ = _harness(
        {CATALOG: "1", CREATE: "1"},
        error=InteractionError(
            "ACTIVE_BLOCKING_INTERACTION_EXISTS",
            guidance="Pass the active interaction ID as replaces_interaction_id.",
        ),
    )

    reply = _result(
        await tools["interaction_card_create"](
            task_key="candidate-calibration",
            interaction_revision=1,
            component_type="single_select",
            card=_single_card(),
        ),
    )

    assert reply == {
        "error": "ACTIVE_BLOCKING_INTERACTION_EXISTS",
        "retryable": True,
        "guidance": "Pass the active interaction ID as replaces_interaction_id.",
    }


@pytest.mark.asyncio
async def test_unknown_platform_failure_never_claims_creation_success():
    tools, _ = _harness(
        {CATALOG: "1", CREATE: "1"},
        error=RuntimeError("secret database path"),
    )

    reply = _result(
        await tools["interaction_card_create"](
            task_key="candidate-calibration",
            interaction_revision=1,
            component_type="single_select",
            card=_single_card(),
        ),
    )

    assert reply["error"] == "PLATFORM_OPERATION_UNCONFIRMED"
    assert "secret" not in json.dumps(reply)


def test_tool_schema_and_docstrings_make_component_choice_unambiguous():
    tools, _ = _harness({CATALOG: "1", CREATE: "1", CANCEL: "1"})
    agent = SimpleNamespace(toolkit=Toolkit())

    with bind_interaction_tools(agent, tools):
        schemas = {
            item["function"]["name"]: item["function"]
            for item in agent.toolkit.get_json_schemas()
        }
        catalog_description = schemas["interaction_component_catalog"]["description"]
        create_description = schemas["interaction_card_create"]["description"]
        assert "先读取" in catalog_description
        assert "single_select" in create_description
        assert "multi_select" in create_description
        assert "question_form" in create_description
        assert "无法预先列全" in create_description
        assert "recommended" in create_description
        assert "default_selected" in create_description
        component_schema = schemas["interaction_card_create"]["parameters"][
            "properties"
        ]["component_type"]
        assert "question_form" in json.dumps(component_schema, ensure_ascii=False)
        assert schemas["interaction_card_create"]["parameters"]["properties"][
            "input_policy"
        ]["default"] == "card_only"
        parameters = schemas["interaction_card_create"]["parameters"]["properties"]
        assert parameters["task_key"]["type"] == "string"
        assert parameters["interaction_revision"]["type"] == "integer"
        assert "object" in json.dumps(parameters["card"])


@pytest.mark.asyncio
async def test_card_request_rejection_emits_only_contract_field_and_constraint():
    events = []

    async def no_business_call(*_args):
        raise AssertionError("invalid card must not reach platform storage")

    tools = build_interaction_tools(
        grants={CATALOG: "1", CREATE: "1"},
        installation_id="installation", conversation_id="task",
        business_call=no_business_call, read_card=None,
        diagnostic_event=lambda event, payload: events.append((event, payload)),
    )
    response = _result(await tools["interaction_card_create"](
        task_key="choice", interaction_revision=0,
        component_type="single_select", card=_single_card(),
    ))
    assert response["error"] == "INVALID_INTERACTION_REQUEST"
    assert events[-1] == ("interaction.tool.rejected", {
        "capability": CREATE, "category": "INVALID_INTERACTION_REQUEST",
        "field_path": "interaction_revision", "constraint": "INVALID_VALUE",
    })


def test_toolkit_is_restored_after_binding_success_and_failure():
    tools, _ = _harness({CATALOG: "1", CREATE: "1"})
    original = Toolkit()
    agent = SimpleNamespace(toolkit=original)

    with bind_interaction_tools(agent, tools):
        assert agent.toolkit is not original
        assert "interaction_card_create" in agent.toolkit.tools
    assert agent.toolkit is original

    with pytest.raises(RuntimeError):
        with bind_interaction_tools(agent, tools):
            raise RuntimeError("boom")
    assert agent.toolkit is original


@pytest.mark.asyncio
async def test_authorized_agent_loop_binds_interaction_and_aigc_tools_together(tmp_path):
    from qwenpaw.agents.message_compat import Msg

    from qwenpaw.app.workspace.aigc_tools import CATALOG as AIGC_CATALOG
    from qwenpaw.app.workspace.orchestration import (
        AuthorizedWorkspaceRelease,
        run_workspace_orchestration_turn,
    )
    from qwenpaw.app.workspace.orchestration_contract import (
        HOST_CAPABILITIES_V1,
        OrchestrationConfig,
    )

    root = tmp_path / "workspace"
    root.mkdir()
    (root / "runtime.py").write_text(
        """
class Runtime:
    async def handle(self, request, host):
        value = await host.call('agent.execute', {
            'messages': request.normalized_input['messages'],
            'execution_mode': 'agent_loop',
        })
        await host.call('runtime.complete', {
            'invocation_id': request.invocation_id,
            'message': value['message'],
        })
def create_runtime(): return Runtime()
""",
        encoding="utf-8",
    )

    class Agent:
        def __init__(self):
            self.toolkit = Toolkit()
            self.model = SimpleNamespace(generate_kwargs={
                "response_format": {"type": "json_object"},
            })
            self.original_model = self.model

        async def __call__(self, _messages):
            assert self.model is not self.original_model
            assert "aigc_workflow_catalog" in self.toolkit.tools
            assert "interaction_component_catalog" in self.toolkit.tools
            assert "interaction_card_create" in self.toolkit.tools
            return Msg("assistant", "ready", "assistant")

    agent = Agent()
    authorization = AuthorizedWorkspaceRelease(
        installation_id="installation-1",
        release_id="release",
        release_digest="sha256:" + "a" * 64,
        granted_capabilities={
            key: "1"
            for key in [
                *HOST_CAPABILITIES_V1,
                AIGC_CATALOG,
                CATALOG,
                CREATE,
            ]
        },
        signed_workspace_files=frozenset({"runtime.py"}),
    )

    async def business_call(_capability, _arguments):
        return {}

    response = await run_workspace_orchestration_turn(
        agent=agent,
        original_messages=[Msg("user", "请选择", "user")],
        request=SimpleNamespace(
            session_id="conversation-1",
            user_id="user",
            channel="console",
            channel_meta={},
        ),
        agent_id="expert",
        workspace_root=root,
        state_storage_root=tmp_path / "states",
        config=OrchestrationConfig(
            enabled=True,
            entrypoint="runtime.py:create_runtime",
            required_host_capabilities=HOST_CAPABILITIES_V1,
        ),
        authorization=authorization,
        business_call=business_call,
    )

    assert response.error_code is None
    assert agent.toolkit.tools == {}
    assert agent.model is agent.original_model
