"""Host-level configured execution with deterministic model boundary fixtures."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.app.workspace.flow_runtime import ConfiguredFlowRuntime


def config():
    return {"id": "support", "version": "3.0.0", "entry_node": "collect", "nodes": [
        {"id": "collect", "goal": "Learn business", "main_skill": "interview", "collect_fields": ["business"],
         "fact_policies": {"business": {"sources": ["customer"], "allow_unknown": False}},
         "required_methods": [], "dimensions": [], "support_skills": [], "next_node": "decide", "return_nodes": []},
        {"id": "decide", "goal": "Create useful judgement", "main_skill": "diagnose", "collect_fields": [],
         "required_methods": ["compare"], "dimensions": [{"id": "opportunity", "criterion": "Concrete scene and mechanism", "allow_provisional": True}],
         "support_skills": [], "next_node": "act", "return_nodes": []},
        {"id": "act", "goal": "Wait for real customer action", "main_skill": "produce", "collect_fields": [],
         "required_methods": [], "dimensions": [], "support_skills": [], "next_node": None, "return_nodes": []},
    ]}


def proposal(reply, **changes):
    return {"reply": reply, "facts": {}, "outcomes": {}, "node_completed": False,
            "interaction": {"kind": "question", "fields": ["business"]}, "actions": [], **changes}


class ModelHost:
    """Only model IO is replaced. Flow execution and persistence remain real."""
    def __init__(self, proposals, *, reject_first=False):
        self.proposals = list(proposals)
        self.reject_first = reject_first
        self.trace = []
        self.completion = None
        self.requests = []

    async def call(self, capability, arguments):
        if capability == "runtime.complete":
            self.completion = arguments
            return {"accepted": True}
        if capability == "runtime.trace":
            self.trace.append(arguments)
            return {"accepted": True}
        if capability != "agent.execute":
            raise AssertionError(f"unexpected external write: {capability}")
        prompt = json.loads(arguments["messages"][-1]["content"])
        self.requests.append(prompt)
        if prompt["operation"] == "generate":
            result = {"candidate": self.proposals.pop(0), "methods": {key: {"conclusion": "A concrete comparison", "basis": "reported business", "limitations": "hypothesis"} for key in prompt["node"].get("required_methods", [])}, "support_requests": []}
        elif prompt["operation"] == "assess":
            allowed = not self.reject_first
            self.reject_first = False
            result = {"candidate_digest": prompt["candidate_digest"], "acceptable": allowed,
                      "context_revision": prompt["context"]["revision"], "context_node": prompt["node"]["id"],
                      "facts_valid": allowed, "reply_valid": True,
                      "dimensions": {d["id"]: "provisional" for d in prompt["node"].get("dimensions", [])},
                      "issues": [] if allowed else ["Answer refers to goal, not business"]}
            clarification = prompt["candidate"]["interaction"].get("clarification")
            if clarification:
                result["clarification_fields"] = [clarification["field"]]
        else:
            raise AssertionError(prompt["operation"])
        return {"text": json.dumps(result)}


def request(tmp_path):
    return SimpleNamespace(invocation_id="turn-one", installation_id="install", session_id="session",
                           transaction_root=tmp_path / "transaction", state_root=tmp_path / "committed",
                           normalized_input={"messages": [{"name": "user", "role": "user", "content": "I teach English"}]},
                           history=[], safe_metadata={}, granted_capabilities={"agent.execute": "1"})


def write_skills(tmp_path):
    for name in ["interview", "diagnose", "produce"]:
        path = tmp_path / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\nUse concrete customer information; do not invent observations.\n")


def test_configured_runtime_handshake_uses_generic_workspace_contract(tmp_path):
    runtime = ConfiguredFlowRuntime(tmp_path, config())
    assert runtime.handshake() == {
        "capability": "workspace.turn.orchestrate/1", "contract_version": "1",
    }


def test_misnested_candidate_fields_are_normalized_without_accepting_conflicts(tmp_path):
    from qwenpaw.app.workspace.flow_engine import FlowError
    raw = {"candidate": {"reply": "draft", "facts": {}, "outcomes": {}},
           "node_completed": False, "interaction": {"kind": "none"}, "actions": []}
    normalized = ConfiguredFlowRuntime._normalize_proposal(raw, config()["nodes"][0])
    assert set(normalized) == {"candidate", "methods", "support_requests"}
    assert normalized["candidate"]["interaction"] == {"kind": "none"}
    assert normalized["candidate"]["node_completed"] is False
    assert "interaction" not in raw["candidate"]  # Input is not authority or mutated.
    raw["candidate"]["interaction"] = {"kind": "question", "fields": ["business"]}
    with pytest.raises(FlowError, match="conflicting_candidate_field"):
        ConfiguredFlowRuntime._normalize_proposal(raw, config()["nodes"][0])


@pytest.mark.asyncio
async def test_configured_json_io_requests_host_json_object_format(tmp_path):
    write_skills(tmp_path)
    class JsonFormatHost(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                assert arguments.get("response_format") == "json_object"
            return await super().call(capability, arguments)
    await ConfiguredFlowRuntime(tmp_path, config()).handle(
        request(tmp_path), JsonFormatHost([proposal("What business?")]),
    )


@pytest.mark.asyncio
async def test_read_only_side_intent_does_not_advance_or_write_business(tmp_path):
    async def side_intent(req, host, state, message):
        assert message["text"] == "I teach English"
        state["revision"] = 999  # Untrusted hook copy cannot mutate authority.
        return "Public description"
    host = ModelHost([])
    await ConfiguredFlowRuntime(tmp_path, config(), side_intent_handler=side_intent).handle(request(tmp_path), host)
    state = json.loads((tmp_path / "transaction" / "configured-flow.json").read_text())
    assert state["revision"] == 0 and not state["history"] and not state["facts"]
    assert host.completion["message"]["reply"] == "Public description"


@pytest.mark.asyncio
async def test_output_formatter_projects_delivery_without_mutating_business_state(tmp_path):
    def formatter(req, state, reply):
        state["revision"] = 999
        return json.dumps({"reply": reply, "attachments": [], "sources": []})
    async def side(req, host, state, message):
        return "Public description"
    runtime = ConfiguredFlowRuntime(tmp_path, config(), side_intent_handler=side, output_formatter=formatter)
    host = ModelHost([])
    await runtime.handle(request(tmp_path), host)
    assert json.loads(host.completion["message"]["reply"])["reply"] == "Public description"
    assert json.loads((request(tmp_path).transaction_root / "configured-flow.json").read_text())["revision"] == 0


@pytest.mark.asyncio
async def test_trusted_support_executor_returns_unavailable_without_fake_model_search(tmp_path):
    write_skills(tmp_path)
    definition=config(); definition["nodes"][0]["support_skills"]=[{"skill":"diagnose","when":"needs knowledge"}]
    class Host(ModelHost):
        async def call(self, capability, arguments):
            result=await super().call(capability, arguments)
            if capability=="agent.execute":
                payload=json.loads(arguments["messages"][-1]["content"])
                if payload["operation"]=="generate":
                    value=json.loads(result["text"])
                    if not payload["support_results"]:
                        value["support_requests"]=[{"skill":"diagnose","reason":"needs knowledge"}]
                    else:
                        assert payload["support_results"]["diagnose"]["status"]=="unavailable"
                    return {"text":json.dumps(value)}
            return result
    async def support(req, host, state, node, requested):
        return {"status":"unavailable","records":[],"limitations":["No trusted source"]}
    host=Host([proposal("What business?"),proposal("What business?")])
    await ConfiguredFlowRuntime(tmp_path,definition,support_executor=support).handle(request(tmp_path),host)
    assert not any(item["operation"]=="support" for item in host.requests)


@pytest.mark.asyncio
async def test_agent_lifecycle_can_provide_fixed_greeting_without_business_call(tmp_path):
    def normalize(state, req):
        state["interaction_mode"] = "operator"
        state["greeting_sent"] = True
        return state, {"text": "hello"}, "Fixed welcome"

    host = ModelHost([])
    await ConfiguredFlowRuntime(tmp_path, config(), lifecycle_normalizer=normalize).handle(request(tmp_path), host)
    assert host.completion["message"]["reply"] == "Fixed welcome"
    state = json.loads((tmp_path / "transaction" / "configured-flow.json").read_text())
    assert state["revision"] == 0
    assert state["greeting_sent"] is True
    assert host.requests == []


@pytest.mark.asyncio
async def test_normalized_business_text_and_rules_reach_generation_and_assessment(tmp_path):
    write_skills(tmp_path)

    def normalize(state, req):
        return state, {"text": "Normalized customer answer", "attachments": []}, None

    host = ModelHost([proposal("Which service do you offer?")])
    await ConfiguredFlowRuntime(tmp_path, config(), lifecycle_normalizer=normalize,
                                extra_system_rules="Keep original business policy").handle(request(tmp_path), host)
    assert all(p["customer_text"] == "Normalized customer answer" for p in host.requests)


@pytest.mark.asyncio
async def test_active_conditional_method_requires_actual_result(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][0]["conditional_methods"] = [{"method": "account_health", "when": "account exists"}]

    class ConditionalHost(ModelHost):
        async def call(self, capability, args):
            result = await super().call(capability, args)
            if capability == "agent.execute":
                prompt = json.loads(args["messages"][-1]["content"])
                parsed = json.loads(result["text"])
                if prompt["operation"] == "assess":
                    parsed["conditional_methods"] = {"account_health": True}
                result["text"] = json.dumps(parsed)
            return result

    value = proposal("Ready", facts={"business": {"value": "English", "source": "customer", "quote": "teach English", "status": "known"}}, node_completed=True, interaction={"kind": "none"})
    host = ConditionalHost([value, value, value])
    await ConfiguredFlowRuntime(tmp_path, definition).handle(request(tmp_path), host)
    state = json.loads((tmp_path / "transaction" / "configured-flow.json").read_text())
    assert state["current_node"] == "collect"
    assert state["revision"] == 0
    assert any(trace.get("code") == "conditional_method_missing" for trace in host.trace)


@pytest.mark.asyncio
async def test_platform_effect_runs_only_after_semantic_and_completion_preflight(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][0]["capabilities"] = ["asset.create"]
    definition["nodes"][0]["required_receipts"] = [{"kind": "asset", "status": "ready"}]
    definition["nodes"][1]["collect_fields"] = ["asset_subject"]

    class Platform:
        def __init__(self):
            self.calls = 0

        async def prepare(self, req, host, state, node):
            return {"context": {"available": True}, "receipts": []}

        def preview(self, req, state, node, candidate, assessment, prepared):
            return {"receipts": [{"kind": "asset", "status": "ready", "node_id": node["id"], "revision": state["revision"]}]}

        async def execute(self, req, host, state, node, candidate, plan):
            self.calls += 1
            return {"receipts": plan["receipts"], "state_patch": {"artifacts": {"asset_id": "server-owned"}},
                    "reply_suffix": "Open created asset"}

    platform = Platform()
    invalid = proposal("Ready", node_completed=True, interaction={"kind": "none"}, actions=[{"capability": "asset.create"}])
    valid = proposal("Prepared", facts={"business": {"value": "English", "source": "customer", "quote": "teach English", "status": "known"}}, node_completed=True,
                     interaction={"kind": "none"}, actions=[{"capability": "asset.create"}])
    host = ModelHost([invalid, valid, proposal("What aspect should this asset demonstrate?", interaction={"kind": "question", "fields": ["asset_subject"]})])
    await ConfiguredFlowRuntime(tmp_path, definition, platform_adapter=platform).handle(request(tmp_path), host)
    assert platform.calls == 1
    state = json.loads((tmp_path / "transaction" / "configured-flow.json").read_text())
    assert state["current_node"] == "decide"
    assert state["artifacts"]["asset_id"] == "server-owned"
    assert "Open created asset" in host.completion["message"]["reply"]


@pytest.mark.asyncio
async def test_preview_receipt_never_commits_without_actual_platform_receipt(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][0]["capabilities"] = ["asset.create"]
    definition["nodes"][0]["required_receipts"] = [{"kind": "asset", "status": "ready"}]

    class Platform:
        async def prepare(self, req, host, state, node):
            return {"context": {}, "receipts": []}

        def preview(self, req, state, node, candidate, assessment, prepared):
            return {"receipts": [{"kind": "asset", "status": "ready", "node_id": node["id"], "revision": state["revision"]}]}

        async def execute(self, *args):
            return {"receipts": [], "state_patch": {}}

    value = proposal("Prepared", facts={"business": {"value": "English", "source": "customer", "quote": "teach English", "status": "known"}}, node_completed=True,
                     interaction={"kind": "none"}, actions=[{"capability": "asset.create"}])
    host = ModelHost([value, value, value])
    await ConfiguredFlowRuntime(tmp_path, definition, platform_adapter=Platform()).handle(request(tmp_path), host)
    state = json.loads((tmp_path / "transaction" / "configured-flow.json").read_text())
    assert state["revision"] == 0
    assert state["history"] == []


@pytest.mark.asyncio
async def test_safe_partial_patch_normalization_keeps_answered_facts_without_inventing_unknown(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][0]["collect_fields"].append("goal")
    definition["nodes"][0]["allowed_actions"] = ["understand facts"]

    class PartialHost(ModelHost):
        async def call(self, capability, args):
            result = await super().call(capability, args)
            if capability == "agent.execute":
                payload = json.loads(args["messages"][-1]["content"])
                value = json.loads(result["text"])
                if payload["operation"] == "generate":
                    value.pop("methods")
                    value.pop("support_requests")
                result["text"] = json.dumps(value)
            return result

    value = proposal("What is your goal?", facts={
        "business": {"value": "English", "source": "customer", "status": "known", "quote": "teach English"},
        "goal": {"value": None, "source": "customer", "status": "unknown", "quote": ""}},
        actions=[], interaction={"kind": "question", "fields": ["goal"]})
    host = PartialHost([value])
    await ConfiguredFlowRuntime(tmp_path, definition).handle(request(tmp_path), host)
    state = json.loads((tmp_path / "transaction" / "configured-flow.json").read_text())
    assert state["facts"]["business"]["value"] == "English"
    assert "goal" not in state["facts"]
    assert state["revision"] == 1


@pytest.mark.asyncio
async def test_automatic_nodes_preserve_each_reply_and_execute_each_owner(tmp_path):
    write_skills(tmp_path)
    runtime = ConfiguredFlowRuntime(tmp_path, config())
    host = ModelHost([
        proposal("Business understood.", facts={"business": {"value": "English lessons", "source": "customer", "quote": "teach English", "status": "known"}}, node_completed=True, interaction={"kind": "none"}),
        proposal("The main opportunity is reducing trial anxiety.", outcomes={"opportunity": "New learners hesitate because trial terms are unclear."}, node_completed=True, interaction={"kind": "none"}),
        proposal("Please upload your real course image.", interaction={"kind": "external_action"}),
    ])
    await runtime.handle(request(tmp_path), host)
    reply = host.completion["message"]["reply"]
    assert "Business understood." in reply
    assert "reducing trial anxiety" in reply
    assert "upload your real course image" in reply
    state = json.loads((tmp_path / "transaction" / "configured-flow.json").read_text())
    assert [h["node_id"] for h in state["history"]] == ["collect", "decide", "act"]
    assert state["current_node"] == "act"
    assert [r["node"]["main_skill"] for r in host.requests if r["operation"] == "generate"] == ["interview", "diagnose", "produce"]


@pytest.mark.asyncio
async def test_semantic_repair_does_not_commit_wrong_fact_or_empty_fallback(tmp_path):
    write_skills(tmp_path)
    runtime = ConfiguredFlowRuntime(tmp_path, config())
    host = ModelHost([proposal("Wrong analysis"), proposal("What business do you operate?")], reject_first=True)
    await runtime.handle(request(tmp_path), host)
    assert host.completion["message"]["reply"] == "What business do you operate?"
    state = json.loads((tmp_path / "transaction" / "configured-flow.json").read_text())
    assert len(state["history"]) == 1
    assert state["facts"] == {}
    assert state["revision"] == 1


@pytest.mark.asyncio
async def test_state_is_never_written_to_committed_root(tmp_path):
    write_skills(tmp_path)
    host = ModelHost([proposal("Which service do you provide?")])
    await ConfiguredFlowRuntime(tmp_path, config()).handle(request(tmp_path), host)
    assert not (tmp_path / "committed").exists()
    assert (tmp_path / "transaction" / "configured-flow.json").exists()


@pytest.mark.asyncio
async def test_skill_path_escape_is_rejected_before_model_execution(tmp_path):
    definition = config()
    definition["nodes"][0]["main_skill"] = "../../outside"
    with pytest.raises(ValueError, match="skill"):
        await ConfiguredFlowRuntime(tmp_path, definition).handle(request(tmp_path), ModelHost([]))


@pytest.mark.asyncio
async def test_reopening_session_restores_facts_and_pending_question(tmp_path):
    write_skills(tmp_path)
    runtime = ConfiguredFlowRuntime(tmp_path, config())
    first = ModelHost([proposal("Which service?", interaction={"kind": "question", "fields": ["business"]})])
    req = request(tmp_path)
    await runtime.handle(req, first)
    req.invocation_id = "turn-two"
    second = ModelHost([proposal("Could you name the service?")])
    await runtime.handle(req, second)
    initial = second.requests[0]
    assert initial["context"]["pending_interaction"]["fields"] == ["business"]
    assert initial["context"]["revision"] == 1


@pytest.mark.asyncio
async def test_owner_reexecutes_after_auxiliary_result_before_committing(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][0]["support_skills"] = [{"skill": "diagnose", "when": "business meaning ambiguous"}]

    class SupportHost(ModelHost):
        def __init__(self):
            super().__init__([proposal("Clarify your service?"), proposal("Which part of the service do you deliver?")])
            self.generated = 0

        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "support":
                    return {"text": json.dumps({"result": "Distinguish provider from buyer", "limitations": "needs fact"})}
                if payload["operation"] == "generate":
                    self.generated += 1
                    result = await super().call(capability, arguments)
                    if self.generated == 1:
                        value = json.loads(result["text"])
                        value["support_requests"] = [{"skill": "diagnose", "reason": "business meaning ambiguous"}]
                        return {"text": json.dumps(value)}
                    assert payload["support_results"]["diagnose"]["result"] == "Distinguish provider from buyer"
                    return result
            return await super().call(capability, arguments)

    host = SupportHost()
    await ConfiguredFlowRuntime(tmp_path, definition).handle(request(tmp_path), host)
    assert host.generated == 2
    assert host.completion["message"]["reply"] == "Which part of the service do you deliver?"


@pytest.mark.asyncio
async def test_actual_method_result_is_persisted_not_only_its_name_or_digest(tmp_path):
    write_skills(tmp_path)
    definition=config(); definition["nodes"][0]["required_methods"]=["compare"]
    host=ModelHost([proposal("What business?")])
    await ConfiguredFlowRuntime(tmp_path,definition).handle(request(tmp_path),host)
    state=json.loads((tmp_path/"transaction"/"configured-flow.json").read_text())
    receipt=state["history"][0]["receipts"][0]
    assert receipt["result"]["conclusion"]=="A concrete comparison"
    assert receipt["result"]["limitations"]=="hypothesis"


@pytest.mark.asyncio
async def test_adapter_value_error_is_bounded_repair_not_uncaught_crash(tmp_path):
    write_skills(tmp_path)
    def enrich(*args):
        raise ValueError("model_supplied_host_field")
    host=ModelHost([proposal("What business?") for _ in range(3)])
    await ConfiguredFlowRuntime(tmp_path,config(),outcome_enricher=enrich).handle(request(tmp_path),host)
    state=json.loads((tmp_path/"transaction"/"configured-flow.json").read_text())
    assert state["revision"]==0
    assert state["recovery"] == {
        "node_id": "collect",
        "reason": "node_repair_exhausted",
        "code": "outcome_enrichment",
        "fields": ["model_supplied_host_field"],
    }
    rejected = [item for item in host.trace if item.get("type") == "flow.proposal.rejected"]
    assert rejected[-1]["code"] == "outcome_enrichment"
    assert rejected[-1]["fields"] == ["model_supplied_host_field"]


@pytest.mark.asyncio
async def test_failed_later_node_does_not_erase_already_accepted_stage_result(tmp_path):
    write_skills(tmp_path)

    class FailingLaterHost(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["node"]["id"] == "decide":
                    return {"text": "malformed"}
            return await super().call(capability, arguments)

    host = FailingLaterHost([proposal("Business understood.", facts={"business": {"value": "English lessons", "source": "customer", "quote": "teach English", "status": "known"}}, node_completed=True, interaction={"kind": "none"})])
    await ConfiguredFlowRuntime(tmp_path, config()).handle(request(tmp_path), host)
    state = json.loads((tmp_path / "transaction" / "configured-flow.json").read_text())
    assert state["current_node"] == "decide"
    assert state["facts"]["business"]["value"] == "English lessons"
    assert len(state["history"]) == 1
    assert "Business understood." in host.completion["message"]["reply"]
    assert "本轮处理未能安全完成" not in host.completion["message"]["reply"]


@pytest.mark.asyncio
async def test_omitted_empty_actions_are_not_a_runtime_key_error(tmp_path):
    write_skills(tmp_path)
    value = proposal("Which service do you provide?")
    del value["actions"]
    host = ModelHost([value])
    await ConfiguredFlowRuntime(tmp_path, config()).handle(request(tmp_path), host)
    assert host.completion["message"]["reply"] == value["reply"]


def test_repeated_historical_evidence_is_omitted_not_reapplied_to_current_message():
    previous = {"value": "lessons", "source": "customer", "status": "known", "quote": "I teach"}
    value = {"candidate": proposal("What is your goal?", facts={"business": previous})}
    normalized = ConfiguredFlowRuntime._normalize_proposal(
        value, config()["nodes"][0], facts={"business": previous}, customer_text="more leads")
    assert normalized["candidate"]["facts"] == {}
    changed = {**previous, "value": "a different service", "quote": "more leads"}
    value["candidate"]["facts"]["business"] = changed
    normalized = ConfiguredFlowRuntime._normalize_proposal(
        value, config()["nodes"][0], facts={"business": previous}, customer_text="more leads")
    assert normalized["candidate"]["facts"]["business"] == changed


@pytest.mark.asyncio
async def test_internal_return_executes_target_owner_without_empty_customer_confirmation(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][1]["return_nodes"] = ["collect"]
    definition["nodes"][1]["return_policies"] = [{"target": "collect", "reasons": ["AMBIGUOUS_BUSINESS"]}]
    runtime = ConfiguredFlowRuntime(tmp_path, definition)
    host = ModelHost([
        proposal("The business anchor is available.", facts={"business": {"value": "English lessons", "source": "customer", "quote": "teach English", "status": "known"}}, node_completed=True, interaction={"kind": "none"}),
        proposal("The service recipient remains ambiguous.", outcomes={"opportunity": "Need provider versus buyer distinction"}, interaction={"kind": "none"}, return_request={"target": "collect", "reason": "AMBIGUOUS_BUSINESS"}),
        proposal("Are these lessons for adults or school students?", interaction={"kind": "question", "fields": ["business"],
                 "clarification": {"field": "business", "reason": "Provider and buyer descriptions conflict"}}),
    ])
    await runtime.handle(request(tmp_path), host)
    assert host.completion["message"]["reply"].endswith("Are these lessons for adults or school students?")
    assert [p["node"]["id"] for p in host.requests if p["operation"] == "generate"] == ["collect", "decide", "collect"]


@pytest.mark.asyncio
@pytest.mark.parametrize("synchronous", [False, True])
async def test_host_enrichment_is_before_assessment_and_limited_to_declared_fields(tmp_path, synchronous):
    definition = config()
    definition["nodes"][0]["outcome_schemas"] = {"task": {"type": "object", "host_enrichment": {"properties": {"id": {"type": "string"}}}}}
    async def enrich(req, host, state, node, candidate):
        candidate["outcomes"]["task"]["id"] = "host-task"
        return candidate
    if synchronous:
        def enrich(req, host, state, node, candidate):
            candidate["outcomes"]["task"]["id"] = "host-task"
            return candidate
    runtime = ConfiguredFlowRuntime(tmp_path, definition, outcome_enricher=enrich)
    value = proposal("A concrete topic", outcomes={"task": {"topic": "lessons"}})
    enriched = await runtime._enrich(request(tmp_path), None, runtime.engine.initial_state(), definition["nodes"][0], value)
    assert enriched["outcomes"]["task"]["id"] == "host-task"
    assert "id" not in value["outcomes"]["task"]
    with pytest.raises(ValueError, match="model_supplied_host_field"):
        await runtime._enrich(request(tmp_path), None, runtime.engine.initial_state(), definition["nodes"][0], enriched)
    async def wrong_enrich(req, host, state, node, candidate):
        candidate["reply"] = "Unauthorized replacement"
        return candidate
    runtime.outcome_enricher = wrong_enrich
    with pytest.raises(ValueError, match="enrichment_changed_business"):
        await runtime._enrich(request(tmp_path), None, runtime.engine.initial_state(), definition["nodes"][0], value)


@pytest.mark.asyncio
async def test_contract_runtime_advances_ready_nodes_and_renders_only_real_customer_action(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][-1]["required_receipts"] = [{"kind": "asset", "status": "submitted"}]
    class RenderHost(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "render":
                    assert payload["pending_interaction"]["kind"] == "external_action"
                    assert [item["node_id"] for item in payload["executed"]] == ["collect", "decide", "act"]
                    return {"text": json.dumps({"reply": "Upload your classroom photo using the task card."})}
                if payload["operation"] == "assess_render":
                    return {"text": json.dumps({"valid": True, "issues": []})}
            return await super().call(capability, arguments)
    host = RenderHost([
        proposal("What business do you run?", facts={"business": {"value": "English lessons", "source": "customer", "quote": "teach English", "status": "known"}}, node_completed=True, interaction={"kind": "none"}),
        proposal("Please say okay before I continue.", outcomes={"opportunity": "Parents need evidence of teaching quality"}, node_completed=True, interaction={"kind": "none"}),
        proposal("Use the task card to upload your classroom photo.", interaction={"kind": "external_action"}),
    ])
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(request(tmp_path), host)
    assert host.completion["message"]["reply"] == "Upload your classroom photo using the task card."
    state = json.loads((tmp_path / "transaction" / "configured-flow.json").read_text())
    assert state["current_node"] == "act"
    assert state["outcomes"]["collect"]["completed"]
    assert state["outcomes"]["decide"]["completed"]


@pytest.mark.asyncio
async def test_question_is_rendered_from_config_not_model_optional_questions(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][0]["field_guidance"] = {"business": {"description": "业务", "question": "你具体提供什么服务？"}}
    class EmptyCollector(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute" and json.loads(arguments["messages"][-1]["content"])["operation"] == "collect":
                return {"text": json.dumps({"fields": {"business": {"status": "not_mentioned"}}})}
            return await super().call(capability, arguments)
    host = EmptyCollector([proposal("How many customers, budget and competitors do you have?")])
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(request(tmp_path), host)
    assert host.completion["message"]["reply"] == "你具体提供什么服务？"
    assert not any(p["operation"] == "render" for p in host.requests)


@pytest.mark.asyncio
async def test_completed_stage_results_are_presented_before_next_real_question(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][1].update(collect_fields=["execution"], field_guidance={"execution": {
        "description": "Production ability", "question": "Can you supply classroom pictures?"}})
    class Host(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "render":
                    assert payload["executed"][0] == {"node_id": "collect", "main_skill": "interview", "completed": True}
                    assert payload["required_question"] == "Can you supply classroom pictures?"
                    self.requests.append(payload)
                    return {"text": json.dumps({"reply": "The business goal is now clear; classroom evidence is the proposed next input.\n\nCan you supply classroom pictures?"})}
                if payload["operation"] == "assess_render":
                    return {"text": json.dumps({"valid": True, "issues": []})}
            return await super().call(capability, arguments)
    host = Host([
        proposal("draft", facts={"business": {"value": "English lessons", "source": "customer", "quote": "teach English", "status": "known"}}, node_completed=True, interaction={"kind": "none"}),
        proposal("draft", interaction={"kind": "none"}),
    ])
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(request(tmp_path), host)
    assert any(p["operation"] == "render" for p in host.requests)
    assert "business goal" in host.completion["message"]["reply"]
    assert host.completion["message"]["reply"].endswith("Can you supply classroom pictures?")


@pytest.mark.asyncio
@pytest.mark.parametrize("option", ["A", "E", "z", "2"])
async def test_missing_customer_permission_cannot_be_invented_by_owner_or_blocked_by_premature_enrichment(tmp_path, option):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][0].update(
        collect_fields=["execution"], field_guidance={"execution": {
            "description": "Customer's actual permitted production modes", "question": "Can you appear on camera or only supply pictures?"}})
    class EmptyCollector(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "collect":
                    return {"text": json.dumps({"fields": {"execution": {"status": "not_mentioned"}}})}
            return await super().call(capability, arguments)
    def enrich(req, host, state, node, value):
        assert value["outcomes"] == {} and value["actions"] == []
        return value
    # An unbound option label is not an answer to a new execution choice.
    host = EmptyCollector([proposal("Ready", facts={"execution": {
        "value": "on camera", "source": "customer", "status": "known", "quote": option}},
        outcomes={"premature_task": {"production_mode": "on camera"}}, actions=[{"capability": "asset.create"}],
        interaction={"kind": "none"})])
    req = request(tmp_path)
    req.normalized_input["messages"][0]["content"] = option
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True, outcome_enricher=enrich).handle(req, host)
    state = json.loads((tmp_path / "transaction" / "configured-flow.json").read_text())
    assert not state["facts"] and "recovery" not in state
    assert state["pending_interaction"] == {"kind": "question", "fields": ["execution"]}
    assert host.completion["message"]["reply"] == "Can you appear on camera or only supply pictures?"


@pytest.mark.asyncio
async def test_focused_collector_does_not_drop_volunteered_optional_fact(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][0].update(optional_fact_fields=["published_at"],
        field_guidance={"business": {"description": "Actual business", "question": "What service do you offer?"}})
    class Host(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute" and json.loads(arguments["messages"][-1]["content"])["operation"] == "collect":
                return {"text": json.dumps({"fields": {"business": {"status": "not_mentioned"},
                    "published_at": {"status": "observed", "fact": fact}}})}
            return await super().call(capability, arguments)
    fact = {"value": "yesterday evening", "source": "customer", "status": "known", "quote": "yesterday evening"}
    host = Host([proposal("draft", facts={"published_at": fact})])
    req = request(tmp_path)
    req.normalized_input["messages"][0]["content"] = "Published yesterday evening"
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(req, host)
    state = json.loads((tmp_path / "transaction" / "configured-flow.json").read_text())
    assert state["facts"]["published_at"] == fact
    assert state["pending_interaction"]["fields"] == ["business"]


@pytest.mark.asyncio
async def test_volunteered_later_profile_fact_is_saved_without_asking_later_stage_questions(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["collect_volunteered_global_facts"] = True
    definition["nodes"][0]["field_guidance"] = {"business": {"description": "Actual business", "question": "What business?"}}
    definition["nodes"][1].update(collect_fields=["execution"], field_guidance={"execution": {
        "description": "Whether customer can appear on camera", "question": "Can you appear on camera?"}})
    class Host(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "collect":
                    assert "execution" in payload["fields"]
                    assert payload["unsolicited_fields"] == ["execution"]
                    return {"text": json.dumps({"fields": {"business": {"status": "not_mentioned"},
                        "execution": {"status": "observed", "fact": {
                            "value": "not on camera", "source": "customer", "status": "known", "quote": "not on camera"}}}})}
            return await super().call(capability, arguments)
    host = Host([proposal("draft")])
    req = request(tmp_path)
    req.normalized_input["messages"][0]["content"] = "I am not on camera"
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(req, host)
    state = json.loads((tmp_path / "transaction" / "configured-flow.json").read_text())
    assert state["facts"]["execution"]["value"] == "not on camera"
    assert state["current_node"] == "collect" and state["pending_interaction"]["fields"] == ["business"]


@pytest.mark.asyncio
@pytest.mark.parametrize("inert_status", ["known", "unknown", "ambiguous"])
async def test_nonobserved_fact_is_discarded_without_losing_observed_choice(tmp_path, inert_status):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][0].update(
        collect_fields=["diagnosis_choice"],
        field_guidance={
            "diagnosis_choice": {"description": "Persisted diagnosis choice", "question": "Choose diagnosis"},
            "execution_ability": {"description": "Execution ability", "question": "Choose capability"},
        },
        next_node=None,
    )
    definition["nodes"] = [definition["nodes"][0]]
    class CollectorHost(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "collect":
                    return {"text": json.dumps({"fields": {
                        "diagnosis_choice": {"status": "observed", "fact": {
                            "value": "A", "source": "customer", "status": "known", "quote": "A"}},
                        "execution_ability": {"status": "ambiguous", "fact": {
                            "value": {"calibrated": True, "available_modes": ["VISUAL_TEXT_ONLY"]},
                            "source": "customer", "status": inert_status, "quote": "A"}},
                    }})}
            return await super().call(capability, arguments)
    host = CollectorHost([proposal("choice retained", node_completed=True, interaction={"kind": "none"})])
    req = request(tmp_path)
    req.normalized_input["messages"][0]["content"] = "A"
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(req, host)
    saved = json.loads((req.transaction_root / "configured-flow.json").read_text())
    assert saved["facts"]["diagnosis_choice"]["value"] == "A"
    assert "execution_ability" not in saved["facts"]


@pytest.mark.asyncio
async def test_failed_presentation_continuation_does_not_resume_business(tmp_path):
    write_skills(tmp_path)
    runtime = ConfiguredFlowRuntime(tmp_path, config(), contract_driven=True)
    req = request(tmp_path)
    state = runtime.engine.initial_state()
    state["pending_interaction"] = {"kind": "external_action"}
    state["presentation"] = {"status": "retry_required", "revision": 0,
                             "reason": "turn_budget_exhausted", "invocation_id": "prior"}
    state["recovery"] = {"node_id": state["current_node"], "reason": "turn_budget_exhausted"}
    runtime._checkpoint(req, state)
    req._runtime_continuation = True
    class BrokenPresentation(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                assert payload["operation"] in {"render", "assess_render"}
                self.requests.append(payload)
                return {"text": "invalid"}
            return await super().call(capability, arguments)
    host = BrokenPresentation([])
    await runtime.handle(req, host)
    saved = json.loads((req.transaction_root / "configured-flow.json").read_text())
    assert saved["revision"] == 0 and not saved["history"]
    assert saved["presentation"]["status"] == "retry_required"
    assert (saved.get("recovery") or {}).get("reason") != "turn_budget_exhausted"
    assert "continuation_reason" not in host.completion["diagnostics"]


@pytest.mark.asyncio
async def test_optional_customer_fact_is_owned_by_collector_not_business_generator(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"] = [definition["nodes"][0]]
    definition["nodes"][0].update(collect_fields=[], next_node=None,
                                  optional_fact_fields=["purchase_scenario"])
    class Host(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "collect":
                    assert "purchase_scenario" in payload["unsolicited_fields"]
                    return {"text": json.dumps({"fields": {
                        "purchase_scenario": {"status": "not_mentioned"}}})}
            return await super().call(capability, arguments)
    host = Host([proposal("draft", facts={"purchase_scenario": {
        "value": "invented scenario", "source": "customer", "status": "known", "quote": "old unseen message"}},
        node_completed=True, interaction={"kind": "none"})])
    runtime = ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True)
    await runtime.handle(request(tmp_path), host)
    saved = json.loads((request(tmp_path).transaction_root / "configured-flow.json").read_text())
    assert "purchase_scenario" not in saved["facts"]
    assert saved["status"] == "completed"
    assert not any(t.get("type") == "flow.proposal.rejected" for t in host.trace)


@pytest.mark.asyncio
async def test_owner_can_propose_current_required_fact_missed_by_collector_with_verbatim_quote(tmp_path):
    write_skills(tmp_path)
    definition = config(); node = definition["nodes"][0]
    definition["nodes"] = [node]
    node.update(collect_fields=["traffic_goal"], next_node=None,
                field_guidance={"traffic_goal": {"description": "客户希望达成的流量目标", "question": "流量目标是什么？"}},
                fact_policies={"traffic_goal": {"sources": ["customer"], "allow_unknown": False}})

    class MissedCollector(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "collect":
                    return {"text": json.dumps({"fields": {"traffic_goal": {"status": "not_mentioned"}}})}
            return await super().call(capability, arguments)

    req = request(tmp_path)
    req.normalized_input["messages"][0]["content"] = "目标每月招生50人"
    fact = {"value": "每月招生50人", "source": "customer", "status": "known", "quote": "目标每月招生50人"}
    host = MissedCollector([proposal("goal found", facts={"traffic_goal": fact},
                                     node_completed=True, interaction={"kind": "none"})])
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(req, host)
    saved = json.loads((req.transaction_root / "configured-flow.json").read_text())
    assert saved["facts"]["traffic_goal"] == fact
    assessed = next(item for item in host.requests if item["operation"] == "assess")
    assert assessed["candidate"]["facts"]["traffic_goal"] == fact


@pytest.mark.asyncio
@pytest.mark.parametrize("quote", ["客户从未说过的目标", "目标每月招生50人"])
async def test_owner_missed_fact_is_not_written_without_grounding_and_semantic_acceptance(tmp_path, quote):
    write_skills(tmp_path)
    definition = config(); node = definition["nodes"][0]
    definition["nodes"] = [node]
    node.update(collect_fields=["traffic_goal"], next_node=None,
                field_guidance={"traffic_goal": {"description": "客户希望达成的流量目标", "question": "流量目标是什么？"}},
                fact_policies={"traffic_goal": {"sources": ["customer"], "allow_unknown": False}})

    class RejectingSemantics(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "collect":
                    return {"text": json.dumps({"fields": {"traffic_goal": {"status": "not_mentioned"}}})}
            result = await super().call(capability, arguments)
            if capability == "agent.execute" and payload["operation"] == "assess":
                value = json.loads(result["text"]); value["facts_valid"] = False
                value["acceptable"] = False; value["issues"] = ["quote does not semantically support traffic_goal"]
                return {"text": json.dumps(value)}
            return result

    req = request(tmp_path); req.normalized_input["messages"][0]["content"] = "目标每月招生50人"
    bad = {"value": "已经成交50人", "source": "customer", "status": "known", "quote": quote}
    host = RejectingSemantics([proposal("draft", facts={"traffic_goal": bad})] * 4)
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(req, host)
    saved = json.loads((req.transaction_root / "configured-flow.json").read_text())
    assert "traffic_goal" not in saved["facts"]


@pytest.mark.asyncio
async def test_separate_collector_preserves_multiple_fields_supported_by_same_quote(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][0].update(
        collect_fields=["business", "service", "goal"],
        field_guidance={"business": {"description": "行业或业务", "question": "你做什么业务？"},
                        "service": {"description": "提供的具体服务，同一句可以支持业务和服务", "question": "提供什么服务？"},
                        "goal": {"description": "希望达到的目标", "question": "你希望实现什么目标？"}})
    class CollectorHost(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "collect":
                    self.requests.append(payload)
                    fact = {"value": "English lessons", "source": "customer", "quote": "teach English", "status": "known"}
                    return {"text": json.dumps({"fields": {
                        "business": {"status": "observed", "fact": fact},
                        "service": {"status": "observed", "fact": fact},
                        "goal": {"status": "not_mentioned"}}})}
            return await super().call(capability, arguments)
    # The primary Skill omits both facts; the focused collector's evidence still
    # reaches the independent assessor and the SAME atomic node commit.
    host = CollectorHost([proposal("What service?", facts={})])
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(request(tmp_path), host)
    state = json.loads((tmp_path / "transaction" / "configured-flow.json").read_text())
    assert set(state["facts"]) == {"business", "service"}
    assert host.completion["message"]["reply"] == "你希望实现什么目标？"
    assessed = next(p for p in host.requests if p["operation"] == "assess")
    assert set(assessed["candidate"]["facts"]) == {"business", "service"}


@pytest.mark.asyncio
async def test_assessor_receives_cross_node_fact_contract_and_can_reject_overcalibration(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["collect_volunteered_global_facts"] = True
    definition["nodes"][0]["collect_fields"] = []
    definition["nodes"][1].update(
        optional_fact_fields=["execution_ability"],
        field_guidance={"execution_ability": {
            "description": "分别核对可拍摄、出镜、配音和团队能力；单项能力不能证明整体已校准",
            "question": "请选择实际具备的执行能力。"}},
        fact_schemas={"execution_ability": {"type": "object", "required": ["calibrated", "can_film", "can_voice"],
            "properties": {"calibrated": {"type": "boolean"}, "can_film": {"type": "boolean"},
                           "can_voice": {"type": "boolean"}}, "additionalProperties": False}},
        fact_policies={"execution_ability": {"sources": ["customer"], "allow_unknown": False}},
    )

    class CapabilityHost(ModelHost):
        saw_contract = False
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "collect":
                    return {"text": json.dumps({"fields": {"execution_ability": {"status": "observed", "fact": {
                        "value": {"calibrated": True, "can_film": True, "can_voice": False},
                        "source": "customer", "status": "known", "quote": "我只能手机拍摄，其他不知道"}}}})}
                if payload["operation"] == "assess":
                    assert "单一行为不能自动证明多维calibrated" in arguments["messages"][0]["content"]
                    contract = payload["fact_contracts"]["execution_ability"]
                    assert "单项能力不能证明整体已校准" in contract["guidance"]["description"]
                    assert contract["schema"]["required"] == ["calibrated", "can_film", "can_voice"]
                    assert contract["policy"] == {"sources": ["customer"], "allow_unknown": False}
                    self.saw_contract = True
            result = await super().call(capability, arguments)
            if capability == "agent.execute" and payload["operation"] == "assess":
                report = json.loads(result["text"])
                report.update(acceptable=False, facts_valid=False,
                              issues=["one filming statement does not establish calibrated voice capability"])
                return {"text": json.dumps(report)}
            return result

    req = request(tmp_path); req.normalized_input["messages"][0]["content"] = "我只能手机拍摄，其他不知道"
    host = CapabilityHost([proposal("draft", interaction={"kind": "none"})] * 4)
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(req, host)
    saved = json.loads((req.transaction_root / "configured-flow.json").read_text())
    assert host.saw_contract
    assert "execution_ability" not in saved["facts"] and saved["revision"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["json", "projection"])
async def test_transient_presentation_error_is_repaired_in_same_turn_without_business_replay(tmp_path, failure):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"] = [definition["nodes"][0]]
    definition["nodes"][0]["next_node"] = None
    class RepairHost(ModelHost):
        renders = 0
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "render":
                    self.renders += 1
                    if self.renders == 1:
                        return {"text": "broken" if failure == "json" else json.dumps({"reply": "invalid mode-specific wording"})}
                    assert payload["repair_issues"]
                    return {"text": json.dumps({"reply": "Your business review is complete."})}
                if payload["operation"] == "assess_render":
                    return {"text": json.dumps({"valid": True, "issues": []})}
            return await super().call(capability, arguments)
    host = RepairHost([proposal("unverified draft", facts={"business": {
        "value": "lessons", "source": "customer", "quote": "teach English", "status": "known"}}, node_completed=True, interaction={"kind": "none"})])
    def format_output(req, state, reply):
        if reply == "invalid mode-specific wording":
            raise ValueError("reply outside selected presentation mode")
        return reply
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True,
                                output_formatter=format_output).handle(request(tmp_path), host)
    state = json.loads((request(tmp_path).transaction_root / "configured-flow.json").read_text())
    assert host.renders == 2
    assert len([p for p in host.requests if p["operation"] == "generate"]) == 1
    assert state["revision"] == 1 and state["presentation"]["status"] == "delivered"
    assert host.completion["message"]["reply"] == "Your business review is complete."


@pytest.mark.asyncio
@pytest.mark.parametrize("render_failure", ["invalid_json", "false_claim", "exception"])
async def test_presentation_failure_preserves_business_and_never_delivers_drafts(tmp_path, render_failure):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][1]["required_receipts"] = [{"kind": "approval", "status": "approved"}]
    class BrokenRenderHost(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "render":
                    if render_failure == "exception":
                        raise RuntimeError("model unavailable")
                    return {"text": "broken" if render_failure == "invalid_json" else json.dumps({"reply": "Your video is published. Authorize unlimited spending?"})}
                if payload["operation"] == "assess_render":
                    return {"text": json.dumps({"valid": False, "issues": ["invented publication and authorization"]})}
            return await super().call(capability, arguments)
    host = BrokenRenderHost([
        proposal("DRAFT: your video is published", facts={"business": {"value": "lessons", "source": "customer", "quote": "teach English", "status": "known"}}, node_completed=True, interaction={"kind": "none"}),
        proposal("DRAFT: authorize all spending", outcomes={"opportunity": "Need teaching evidence"}, interaction={"kind": "external_action"})])
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(request(tmp_path), host)
    state = json.loads((tmp_path / "transaction" / "configured-flow.json").read_text())
    assert state["revision"] == 2
    assert state["outcomes"]["collect"]["completed"]
    assert state["presentation"]["status"] == "retry_required"
    assert "DRAFT" not in host.completion["message"]["reply"]
    assert "published" not in host.completion["message"]["reply"]


@pytest.mark.asyncio
async def test_business_recovery_never_exposes_unassessed_earlier_draft(tmp_path):
    write_skills(tmp_path)
    class FailSecondOwner(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "generate" and payload["node"]["id"] == "decide":
                    return {"text": "invalid"}
            return await super().call(capability, arguments)
    host = FailSecondOwner([proposal("DRAFT: published successfully", facts={"business": {"value": "lessons", "source": "customer", "quote": "teach English", "status": "known"}}, node_completed=True, interaction={"kind": "none"})])
    await ConfiguredFlowRuntime(tmp_path, config(), contract_driven=True).handle(request(tmp_path), host)
    assert "DRAFT" not in host.completion["message"]["reply"]
    assert "published" not in host.completion["message"]["reply"]
    assert json.loads((tmp_path / "transaction" / "configured-flow.json").read_text())["revision"] == 1


@pytest.mark.asyncio
async def test_later_dependency_failure_keeps_committed_progress_and_current_answer(tmp_path):
    write_skills(tmp_path)
    class Platform:
        async def prepare(self, req, host, state, node):
            if node["id"] == "decide":
                raise ValueError("catalog_unavailable:private-provider-details")
            return {"context": {}, "receipts": []}
    host = ModelHost([proposal("unassessed draft", facts={"business": {
        "value": "lessons", "source": "customer", "quote": "teach English", "status": "known"}}, node_completed=True, interaction={"kind": "none"})])
    runtime = ConfiguredFlowRuntime(tmp_path, config(), contract_driven=True, platform_adapter=Platform())
    await runtime.handle(request(tmp_path), host)
    saved = json.loads((request(tmp_path).transaction_root / "configured-flow.json").read_text())
    assert saved["revision"] == 1 and saved["current_node"] == "decide"
    assert saved["facts"]["business"]["value"] == "lessons"
    assert saved["recovery"]["reason"] == "dependency_unavailable"
    assert "private-provider" not in host.completion["message"]["reply"]


@pytest.mark.asyncio
async def test_model_timeout_after_completed_owner_keeps_committed_progress(tmp_path):
    write_skills(tmp_path)
    class TimeoutHost(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "generate" and payload["node"]["id"] == "decide":
                    raise TimeoutError("private-provider-endpoint")
            return await super().call(capability, arguments)
    host = TimeoutHost([proposal("draft", facts={"business": {
        "value": "lessons", "source": "customer", "quote": "teach English", "status": "known"}}, node_completed=True, interaction={"kind": "none"})])
    runtime = ConfiguredFlowRuntime(tmp_path, config(), contract_driven=True)
    await runtime.handle(request(tmp_path), host)
    saved = json.loads((request(tmp_path).transaction_root / "configured-flow.json").read_text())
    assert saved["revision"] == 1 and saved["current_node"] == "decide"
    assert saved["facts"]["business"]["value"] == "lessons"
    assert "private-provider" not in host.completion["message"]["reply"]


@pytest.mark.asyncio
async def test_deadline_continuation_restores_unconsumed_text_and_attachment(tmp_path):
    write_skills(tmp_path)
    req = request(tmp_path)
    req.normalized_input["messages"][0]["content"] = [
        {"type": "text", "text": "I teach English"},
        {"type": "image", "source": {"type": "url", "url": "https://example.com/proof.jpg"}},
    ]
    req._runtime_deadline_monotonic = __import__("asyncio").get_running_loop().time() + 0.03
    req._runtime_deadline_reserve_seconds = 0.02

    class SlowHost(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                await __import__("asyncio").sleep(1)
            return await super().call(capability, arguments)

    definition = config()
    definition["nodes"] = [definition["nodes"][0]]
    definition["nodes"][0]["next_node"] = None
    runtime = ConfiguredFlowRuntime(tmp_path, definition)
    await runtime.handle(req, SlowHost([]))
    pending = json.loads((req.transaction_root / "configured-flow.json").read_text())["pending_input"]
    assert pending["text"] == "I teach English"
    assert pending["normalized_input"]["messages"][0]["content"][1]["type"] == "image"

    req.invocation_id = "turn-two"
    req.normalized_input = {"messages": [{"name": "user", "role": "user", "content": ""}]}
    req._runtime_deadline_monotonic = None
    req._runtime_continuation = True
    host = ModelHost([proposal("captured", facts={"business": {
        "value": "English lessons", "source": "customer",
        "quote": "I teach English", "status": "known",
    }}, node_completed=True, interaction={"kind": "none"})])
    await runtime.handle(req, host)
    assert host.requests[0]["customer_text"].strip() == "I teach English"
    assert host.requests[0]["message"]["attachments"][0]["type"] == "image"


@pytest.mark.asyncio
async def test_attachment_only_failed_input_is_recovered_with_original_binding(tmp_path):
    write_skills(tmp_path)
    definition = config(); definition["nodes"] = [definition["nodes"][0]]
    definition["nodes"][0].update(collect_fields=[], next_node=None,
                                 required_receipts=[{"kind": "asset", "status": "submitted"}])
    image = {"type": "image", "source": {"type": "url", "url": "https://example.com/photo.jpg"}}
    req = request(tmp_path); req.normalized_input["messages"][0]["content"] = [image]
    req.safe_metadata = {"media_binding": {"asset_id": "asset-one"}}
    seen = []
    async def context(req, host, state, node, platform):
        seen.append((req.normalized_input, req.safe_metadata))
        return {"context": {}, "state_patch": {}}
    class FailedHost(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                raise TimeoutError("transient")
            return await super().call(capability, arguments)
    runtime = ConfiguredFlowRuntime(tmp_path, definition, context_provider=context)
    await runtime.handle(req, FailedHost([]))
    saved = json.loads((req.transaction_root / "configured-flow.json").read_text())
    assert saved["pending_input"]["normalized_input"]["messages"][-1]["content"] == [image]
    req.invocation_id = "retry-turn"; req.safe_metadata = {}
    req.normalized_input = {"messages": [{"role": "user", "content": "继续"}]}
    host = ModelHost([proposal("请继续完成素材上传。", interaction={"kind": "external_action"})])
    await runtime.handle(req, host)
    assert image in seen[-1][0]["messages"][-1]["content"]
    assert seen[-1][1]["media_binding"]["asset_id"] == "asset-one"
    assert not json.loads((req.transaction_root / "configured-flow.json").read_text()).get("pending_input")


@pytest.mark.asyncio
async def test_failed_answer_is_retained_without_reasking_stored_choice(tmp_path):
    write_skills(tmp_path)
    class BrokenModel(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                return {"text": "invalid"}
            return await super().call(capability, arguments)
    runtime = ConfiguredFlowRuntime(tmp_path, config(), contract_driven=True)
    req = request(tmp_path); req.normalized_input["messages"][0]["content"] = "A"
    state = runtime.engine.initial_state()
    state["pending_interaction"] = {"kind": "choice", "choices": [{"id": "first", "label": "A", "text": "previous choice"}]}
    runtime._checkpoint(req, state)
    host = BrokenModel([])
    await runtime.handle(req, host)
    saved = json.loads((req.transaction_root / "configured-flow.json").read_text())
    assert saved["pending_input"]["text"] == "A"
    assert "请选择" not in host.completion["message"]["reply"]
    assert saved["revision"] == 0


@pytest.mark.asyncio
async def test_completed_flow_recovers_presentation_without_reexecuting_business(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"] = [definition["nodes"][0]]
    definition["nodes"][0]["next_node"] = None
    class PresentationHost(ModelHost):
        fail = True
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "render":
                    return {"text": "broken" if self.fail else json.dumps({"reply": "Your business review is complete."})}
                if payload["operation"] == "assess_render":
                    return {"text": json.dumps({"valid": True, "issues": []})}
            return await super().call(capability, arguments)
    host = PresentationHost([proposal("unverified draft", facts={"business": {"value": "lessons", "source": "customer", "quote": "teach English", "status": "known"}}, node_completed=True, interaction={"kind": "none"})])
    runtime = ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True)
    req = request(tmp_path)
    await runtime.handle(req, host)
    before = json.loads((req.transaction_root / "configured-flow.json").read_text())
    host.fail = False
    req.invocation_id = "retry-presentation"
    req.normalized_input["messages"][0]["content"] = "Please continue"
    await runtime.handle(req, host)
    after = json.loads((req.transaction_root / "configured-flow.json").read_text())
    assert before["revision"] == after["revision"] == 1
    assert after["presentation"]["status"] == "delivered"
    assert "recovery" not in after
    assert len([p for p in host.requests if p["operation"] == "generate"]) == 1
    assert host.completion["message"]["reply"] == "Your business review is complete."


@pytest.mark.asyncio
async def test_platform_submission_context_and_local_receipt_share_same_prepared_state(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"] = [definition["nodes"][0]]
    definition["nodes"][0].update(collect_fields=[], next_node=None,
                                 required_receipts=[{"kind": "review", "status": "PASS"}])
    class Platform:
        async def prepare(self, req, host, state, node):
            return {"context": {"bound": True}, "receipts": [],
                    "state_patch": {"work_items": [{"id": "material", "status": "SUBMITTED"}]}}
    async def context(req, host, state, node, platform):
        assert state["work_items"][0]["status"] == "SUBMITTED"
        return {"context": {"observations": ["host-native-observation"]},
                "state_patch": {"artifacts": {"media_observations": ["host-native-observation"]}}}
    def certify(req, state, node, candidate, assessment, prepared):
        assert prepared["context"]["observations"] == ["host-native-observation"]
        assert prepared["context"]["bound"]
        assert state["artifacts"]["other_asset"] == "preserved"
        return [{"kind": "review", "status": "PASS", "node_id": node["id"], "revision": state["revision"]}]
    runtime = ConfiguredFlowRuntime(tmp_path, definition, platform_adapter=Platform(),
                                    context_provider=context, evidence_hook=certify)
    req = request(tmp_path)
    state = runtime.engine.initial_state()
    state["artifacts"] = {"other_asset": "preserved"}
    runtime._checkpoint(req, state)
    host = ModelHost([proposal("The submitted material meets this review.", node_completed=True, interaction={"kind": "none"})])
    await runtime.handle(req, host)
    saved = json.loads((req.transaction_root / "configured-flow.json").read_text())
    assert saved["artifacts"] == {"other_asset": "preserved", "media_observations": ["host-native-observation"]}
    assert saved["work_items"][0]["status"] == "SUBMITTED"
    assert saved["history"][0]["receipts"][0]["kind"] == "review"


def test_optional_null_means_absent_but_required_null_is_not_fabricated():
    definition = config()["nodes"][0]
    definition["outcome_schemas"] = {"calibration": {"type": "object", "required": ["quote"],
        "properties": {"quote": {"type": "string"}, "correction": {"type": "string"}}}}
    generated = {"candidate": proposal("Draft", outcomes={"calibration": {"quote": None, "correction": None}})}
    normalized = ConfiguredFlowRuntime._normalize_proposal(generated, definition)
    assert normalized["candidate"]["outcomes"]["calibration"] == {"quote": None}
    assert generated["candidate"]["outcomes"]["calibration"]["correction"] is None


def test_absent_return_request_is_not_a_business_return():
    normalized = ConfiguredFlowRuntime._normalize_proposal({"candidate": proposal("draft", return_request=None)}, config()["nodes"][0])
    assert "return_request" not in normalized["candidate"]


@pytest.mark.asyncio
async def test_single_json_fence_with_explanation_is_parsed_without_using_prose_as_result(tmp_path):
    class Host:
        async def call(self, capability, arguments):
            return {"text": '这是本轮结果：\n```json\n{"reply":"actual result"}\n```'}
    result = await ConfiguredFlowRuntime(tmp_path, config())._json(Host(), "rules", {})
    assert result == {"reply": "actual result"}


@pytest.mark.asyncio
async def test_owner_receives_every_required_business_output_not_just_schema_keys(tmp_path):
    write_skills(tmp_path)
    definition = config(); definition["nodes"][0]["dimensions"] = [
        {"id": "extra_business_result", "criterion": "Concrete alternative", "allow_provisional": True},
        {"id": "style", "scope": "presentation", "criterion": "short"}]
    host = ModelHost([proposal("draft")])
    runtime = ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True)
    await runtime.handle(request(tmp_path), host)
    generated = next(p for p in host.requests if p["operation"] == "generate")
    assert generated["required_business_outputs"] == {"extra_business_result": "Concrete alternative"}


@pytest.mark.asyncio
async def test_owner_node_view_separates_business_scope_from_external_capabilities(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][0]["allowed_actions"] = ["执行流量问题定位"]
    host = ModelHost([proposal("What business?")])
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(request(tmp_path), host)
    generated = next(item for item in host.requests if item["operation"] == "generate")
    assert "allowed_actions" not in generated["node"]
    assert generated["node"]["business_scope"] == {
        "allowed_business_actions": ["执行流量问题定位"]}
    assert generated["node"]["capabilities"] == []
    assert generated["action_contract"] == {
        "capabilities": [], "instruction": "actions must be []"}


@pytest.mark.asyncio
async def test_action_repair_names_empty_api_whitelist_instead_of_only_platform_error(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][0]["collect_fields"] = []

    class RejectingPlatform:
        async def prepare(self, req, host, state, node):
            return {"context": {}, "receipts": []}
        def preview(self, req, state, node, candidate, assessment, prepared):
            raise ValueError("invalid_action")

    invalid = proposal("draft", actions=[{"capability": "执行流量问题定位", "arguments": {}}])
    host = ModelHost([invalid] + [proposal("repaired", interaction={"kind": "external_action"})] * 8)
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True,
                                platform_adapter=RejectingPlatform()).handle(request(tmp_path), host)
    generated = [item for item in host.requests if item["operation"] == "generate"]
    assert "allowed_external_capabilities:none;actions_must_be_empty" in generated[1]["repair_issues"]


@pytest.mark.asyncio
async def test_owner_only_receives_missing_outputs_when_current_node_results_are_locked(tmp_path):
    write_skills(tmp_path)
    definition = config()
    node = definition["nodes"][0]
    node["collect_fields"] = []
    node["dimensions"] = [
        {"id": "candidate_batch", "criterion": "Three concrete candidates", "allow_provisional": False},
        {"id": "priority", "criterion": "Recommended candidates", "allow_provisional": False},
        {"id": "calibration", "criterion": "Customer selection", "allow_provisional": False},
    ]
    node["completion_policy"] = {
        "choice_projection": {"outcome": "candidate_batch", "collection": "items", "id": "id",
                              "fields": ["problem", "path"], "recommended": "priority.recommended_ids"},
        "choice_binding": {"outcome": "calibration", "selected": "selected_ids",
                           "quote": "quote", "correction": "correction"},
    }
    runtime = ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True)
    state = runtime.engine.initial_state()
    state["outcomes"]["collect"] = {"valid": True, "completed": False,
        "values": {"candidate_batch": {"items": [{"id": "0", "problem": "p", "path": "x"}]},
                   "priority": {"recommended_ids": ["0"]}}}
    state["pending_interaction"] = {"kind": "choice", "choices": [{"id": "0", "label": "A", "text": "p"}]}
    state["identity"] = {"installation_id": "install", "session_id": "session"}
    target = tmp_path / "transaction"
    target.mkdir()
    (target / "configured-flow.json").write_text(json.dumps(state))

    class CaptureHost:
        def __init__(self): self.payload = None
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                self.payload = json.loads(arguments["messages"][-1]["content"])
                raise RuntimeError("captured")
            if capability in {"runtime.trace", "runtime.complete"}:
                return {"accepted": True}
            raise AssertionError(capability)

    host = CaptureHost()
    await runtime.handle(request(tmp_path), host)
    assert host.payload["required_business_outputs"] == {"calibration": "Customer selection"}
    assert host.payload["locked_business_outputs"] == {
        "candidate_batch": {"items": [{"id": "0", "problem": "p", "path": "x"}]},
        "priority": {"recommended_ids": ["0"]}}


@pytest.mark.asyncio
async def test_persisted_choice_answer_only_adds_calibration_and_advances_on_model_true(tmp_path):
    write_skills(tmp_path)
    definition = config(); node = definition["nodes"][0]
    node["collect_fields"] = []
    node["required_methods"] = []
    node["dimensions"] = [
        {"id": "candidate_batch", "criterion": "Three candidates", "allow_provisional": False},
        {"id": "priority", "criterion": "Recommendation", "allow_provisional": False},
        {"id": "calibration", "criterion": "Customer selection", "allow_provisional": False},
    ]
    node["completion_policy"] = {
        "requires_prior_interaction": "choice",
        "choice_projection": {"outcome": "candidate_batch", "collection": "items", "id": "id",
                              "fields": ["problem", "path"], "recommended": "priority.recommended_ids"},
        "choice_binding": {"outcome": "calibration", "selected": "selected_ids",
                           "quote": "quote", "correction": "correction"},
    }
    node["outcome_schemas"] = {
        "candidate_batch": {"type": "object", "required": ["items"], "properties": {
            "items": {"type": "array", "minItems": 1}}},
        "priority": {"type": "object", "required": ["recommended_ids"], "properties": {
            "recommended_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}}}},
        "calibration": {"type": "object", "additionalProperties": False,
            "required": ["selected_ids", "quote"], "properties": {
                "selected_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                "quote": {"type": "string", "minLength": 1},
                "correction": {"type": ["string", "null"]}}},
    }
    runtime = ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True)
    state = runtime.engine.initial_state()
    state["outcomes"]["collect"] = {"valid": True, "completed": False,
        "values": {"candidate_batch": {"items": [{"id": "0", "problem": "p", "path": "x"}]},
                   "priority": {"recommended_ids": ["0"]}}}
    state["pending_interaction"] = {"kind": "choice", "choices": [
        {"id": "0", "label": "A", "text": "p → x"}], "recommended": "0"}

    class ChoiceHost(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "generate":
                    assert "有效命中" in arguments["messages"][0]["content"]
                if payload["operation"] == "assess":
                    return {"text": json.dumps({"acceptable": True, "facts_valid": True,
                        "dimensions": {item["id"]: "sufficient" for item in payload["node"]["dimensions"]},
                        "conditional_methods": {}, "issues": []})}
            return await super().call(capability, arguments)

    choice = proposal("calibrated", outcomes={"calibration": {
        "selected_ids": ["0"], "quote": "A"}}, node_completed=True, interaction={"kind": "none"})
    host = ChoiceHost([choice])
    proposed, command = await runtime._execute_node(
        request(tmp_path), host, state, "A", [], 0, {"text": "A"})
    generated = next(item for item in host.requests if item["operation"] == "generate")
    assert generated["required_business_outputs"] == {"calibration": "Customer selection"}
    assert set(command["outcomes"]) == {"calibration"}
    assert command["node_completed"] is True
    assert proposed["current_node"] == "decide"


@pytest.mark.asyncio
async def test_model_false_on_ready_node_safely_stays_without_repair_loop(tmp_path):
    write_skills(tmp_path)
    definition = config(); node = definition["nodes"][0]
    node.update(collect_fields=[], required_methods=[], dimensions=[], next_node=None)
    runtime = ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True)
    host = ModelHost([proposal("not ready", interaction={"kind": "none"})])
    proposed, command = await runtime._execute_node(
        request(tmp_path), host, runtime.engine.initial_state(), "", [], 0, {"text": ""})
    assert command["node_completed"] is False
    assert proposed["status"] == "active"
    assert len([item for item in host.requests if item["operation"] == "generate"]) == 1


@pytest.mark.asyncio
async def test_repair_missing_outputs_excludes_locked_current_node_results(tmp_path):
    write_skills(tmp_path)
    definition = config(); node = definition["nodes"][0]
    node["collect_fields"] = []
    node["dimensions"] = [
        {"id": "candidate_batch", "criterion": "Three candidates", "allow_provisional": False},
        {"id": "priority", "criterion": "Recommended candidates", "allow_provisional": False},
        {"id": "calibration", "criterion": "Customer selection", "allow_provisional": False},
    ]
    node["completion_policy"] = {
        "choice_projection": {"outcome": "candidate_batch", "collection": "items", "id": "id",
                              "fields": ["problem", "path"], "recommended": "priority.recommended_ids"},
        "choice_binding": {"outcome": "calibration", "selected": "selected_ids",
                           "quote": "quote", "correction": "correction"},
    }
    runtime = ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True)
    state = runtime.engine.initial_state()
    state["outcomes"]["collect"] = {"valid": True, "completed": False,
        "values": {"candidate_batch": {"items": [{"id": "0", "problem": "p", "path": "x"}]},
                   "priority": {"recommended_ids": ["0"]}}}
    state["pending_interaction"] = {"kind": "choice", "choices": [{"id": "0", "label": "A", "text": "p"}]}
    state["identity"] = {"installation_id": "install", "session_id": "session"}
    target = tmp_path / "transaction"; target.mkdir()
    (target / "configured-flow.json").write_text(json.dumps(state))

    class RepairHost(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "generate" and payload.get("repair_context"):
                    missing = [item for item in payload["repair_issues"]
                               if item.startswith("missing_required_outcomes:")]
                    assert missing == ["missing_required_outcomes:calibration"]
            return await super().call(capability, arguments)

    drafts = [proposal("draft", node_completed=True, interaction={"kind": "none"})] + [
        proposal("wait", interaction={"kind": "external_action"})] * 8
    await runtime.handle(request(tmp_path), RepairHost(drafts, reject_first=True))


@pytest.mark.asyncio
async def test_partial_external_result_is_not_locked_when_new_receipt_can_complete_it(tmp_path):
    write_skills(tmp_path)
    definition = config(); node = definition["nodes"][0]
    node["collect_fields"] = []
    node["dimensions"] = [{"id": "production", "criterion": "Current asset submission", "allow_provisional": False}]
    runtime = ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True)
    state = runtime.engine.initial_state()
    state["outcomes"]["collect"] = {"valid": True, "completed": False,
        "values": {"production": {"asset_bound": False, "status": "WAITING"}}}
    state["identity"] = {"installation_id": "install", "session_id": "session"}
    target = tmp_path / "transaction"; target.mkdir()
    (target / "configured-flow.json").write_text(json.dumps(state))

    class CaptureHost:
        def __init__(self): self.payload = None
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                self.payload = json.loads(arguments["messages"][-1]["content"])
                raise RuntimeError("captured")
            if capability in {"runtime.trace", "runtime.complete"}:
                return {"accepted": True}
            raise AssertionError(capability)

    host = CaptureHost()
    await runtime.handle(request(tmp_path), host)
    assert host.payload["locked_business_outputs"] == {}
    assert host.payload["required_business_outputs"] == {"production": "Current asset submission"}


@pytest.mark.asyncio
async def test_contract_assessment_binding_is_issued_by_host_not_copied_by_model(tmp_path):
    write_skills(tmp_path)
    definition = config()
    definition["nodes"][0]["field_guidance"] = {"business": {"description": "实际业务", "question": "你做什么业务？"}}
    class HostBound(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "collect":
                    return {"text": json.dumps({"fields": {"business": {"status": "not_mentioned"}}})}
                if payload["operation"] == "assess":
                    return {"text": json.dumps({"acceptable": True, "facts_valid": True,
                        "dimensions": {}, "conditional_methods": {}, "issues": []})}
            return await super().call(capability, arguments)
    host = HostBound([proposal("draft")])
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(request(tmp_path), host)
    state = json.loads((request(tmp_path).transaction_root / "configured-flow.json").read_text())
    assert state["revision"] == 1
    assert state["outcomes"]["collect"]["assessment"]["context_revision"] == 0


@pytest.mark.asyncio
async def test_repair_context_keeps_model_work_but_never_host_enrichment(tmp_path):
    write_skills(tmp_path)
    definition = config()
    node = definition["nodes"][1]
    node["next_node"] = None
    node["outcome_schemas"] = {"opportunity": {"type": "object",
        "host_enrichment": {"properties": {"task_id": {"type": "string"}}}}}
    definition["nodes"] = [node]
    definition["entry_node"] = "decide"
    async def enrich(req, host, state, current, candidate):
        candidate["outcomes"]["opportunity"]["task_id"] = "host-secret-id"
        return candidate
    first = proposal("draft", outcomes={"opportunity": {"plan": "keep this plan"}},
                     node_completed=True, interaction={"kind": "none"})
    second = proposal("repaired", outcomes={"opportunity": {
        "plan": "keep this plan", "risk": "added"}},
        node_completed=True, interaction={"kind": "none"})
    req = request(tmp_path)
    class RepairHost(ModelHost):
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "generate" and "repair_context" in payload:
                    prior = payload["repair_context"]
                    assert prior["status"] == "untrusted_noncommitted_same_node_attempt"
                    assert prior["previous_attempt"]["candidate"]["outcomes"]["opportunity"] == {"plan": "keep this plan"}
                    assert "host-secret-id" not in json.dumps(prior)
                    assert prior["assessment"]["acceptable"] is False
                    assert prior["assessment"]["dimensions"] == {"opportunity": "provisional"}
                    assert not (req.transaction_root / "configured-flow.json").exists()
            return await super().call(capability, arguments)
    host = RepairHost([first, second], reject_first=True)
    await ConfiguredFlowRuntime(tmp_path, definition, outcome_enricher=enrich).handle(req, host)
    saved = json.loads((req.transaction_root / "configured-flow.json").read_text())
    assert saved["revision"] == 1
    assert saved["outcomes"]["decide"]["values"]["opportunity"]["task_id"] == "host-secret-id"


@pytest.mark.asyncio
async def test_repair_lists_all_missing_required_outcomes_and_methods_once(tmp_path):
    write_skills(tmp_path)
    definition = config(); node = definition["nodes"][1]
    node["next_node"] = None
    node["dimensions"] = [{"id": key, "criterion": key, "allow_provisional": True}
                          for key in ("plan", "substitution", "sound")]
    node["required_methods"] = ["compare", "verify"]
    definition["nodes"] = [node]; definition["entry_node"] = "decide"
    first = proposal("draft", outcomes={"plan": {"detail": "valid work"}})
    second = proposal("repaired", outcomes={key: {"detail": key}
        for key in ("plan", "substitution", "sound")}, node_completed=True,
        interaction={"kind": "none"})
    class Host(ModelHost):
        first = True
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "generate" and self.first:
                    self.first = False
                    return {"text": json.dumps({"candidate": first, "methods": {}, "support_requests": []})}
                if payload["operation"] == "generate":
                    assert "missing_required_outcomes:substitution,sound" in payload["repair_issues"]
                    assert "missing_required_methods:compare,verify" in payload["repair_issues"]
            return await super().call(capability, arguments)
    host = Host([second])
    await ConfiguredFlowRuntime(tmp_path, definition).handle(request(tmp_path), host)
    assert json.loads((request(tmp_path).transaction_root / "configured-flow.json").read_text())["revision"] == 1


@pytest.mark.asyncio
async def test_illegal_method_key_repair_lists_exact_key_and_allowed_ids_then_succeeds(tmp_path):
    write_skills(tmp_path)
    definition = config(); node = definition["nodes"][1]
    node["next_node"] = None
    definition["nodes"] = [node]; definition["entry_node"] = "decide"

    class MethodRepairHost(ModelHost):
        generate_count = 0
        async def call(self, capability, arguments):
            payload = None
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "generate":
                    self.generate_count += 1
                    if self.generate_count == 2:
                        assert "invalid_method_keys:competing_explanation" in payload["repair_issues"]
                        assert "allowed_method_ids:compare" in payload["repair_issues"]
            result = await super().call(capability, arguments)
            if payload and payload["operation"] == "generate" and self.generate_count == 1:
                envelope = json.loads(result["text"])
                envelope["methods"]["competing_explanation"] = "alternative business interpretation"
                return {"text": json.dumps(envelope)}
            return result

    value = proposal("diagnosis", outcomes={"opportunity": "Concrete acquisition opportunity"},
                     node_completed=True, interaction={"kind": "none"})
    req = request(tmp_path); host = MethodRepairHost([value, value])
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(req, host)
    saved = json.loads((req.transaction_root / "configured-flow.json").read_text())
    assert saved["status"] == "completed" and saved["revision"] == 1


@pytest.mark.asyncio
async def test_repeated_illegal_method_key_never_advances(tmp_path):
    write_skills(tmp_path)
    definition = config(); node = definition["nodes"][1]
    node["next_node"] = None
    definition["nodes"] = [node]; definition["entry_node"] = "decide"

    class AlwaysInvalidMethods(ModelHost):
        async def call(self, capability, arguments):
            payload = None
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
            result = await super().call(capability, arguments)
            if payload and payload["operation"] == "generate":
                envelope = json.loads(result["text"])
                envelope["methods"]["competing_explanation"] = "still misplaced"
                return {"text": json.dumps(envelope)}
            return result

    value = proposal("diagnosis", outcomes={"opportunity": "Concrete acquisition opportunity"},
                     node_completed=True, interaction={"kind": "none"})
    req = request(tmp_path); host = AlwaysInvalidMethods([value] * 4)
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(req, host)
    saved = json.loads((req.transaction_root / "configured-flow.json").read_text())
    assert saved["revision"] == 0 and not saved["history"]


@pytest.mark.asyncio
async def test_valid_collector_result_is_reused_during_non_fact_repair(tmp_path):
    write_skills(tmp_path)
    definition = config(); node = definition["nodes"][0]
    node["next_node"] = None
    node["field_guidance"] = {"business": {"description": "Actual business", "question": "What business?"}}
    collector_calls = 0

    class ReuseHost(ModelHost):
        generate_calls = 0
        async def call(self, capability, arguments):
            nonlocal collector_calls
            payload = None
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "collect":
                    collector_calls += 1
                    return {"text": json.dumps({"fields": {"business": {"status": "observed", "fact": {
                        "value": "English lessons", "source": "customer", "status": "known", "quote": "teach English"}}}})}
                if payload["operation"] == "generate":
                    self.generate_calls += 1
            result = await super().call(capability, arguments)
            if payload and payload["operation"] == "generate" and self.generate_calls == 1:
                envelope = json.loads(result["text"])
                envelope["methods"]["unconfigured_explanation"] = "misplaced"
                return {"text": json.dumps(envelope)}
            return result

    value = proposal("business understood", node_completed=True, interaction={"kind": "none"})
    req = request(tmp_path); host = ReuseHost([value, value])
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(req, host)
    saved = json.loads((req.transaction_root / "configured-flow.json").read_text())
    assert collector_calls == 1
    assert saved["facts"]["business"]["quote"] == "teach English"


@pytest.mark.asyncio
async def test_semantic_fact_rejection_clears_turn_local_collector_cache(tmp_path):
    write_skills(tmp_path)
    definition = config(); definition["nodes"][0]["next_node"] = None
    definition["nodes"][0]["field_guidance"] = {
        "business": {"description": "Actual business", "question": "What business?"}}
    collector_calls = 0

    class RecollectHost(ModelHost):
        async def call(self, capability, arguments):
            nonlocal collector_calls
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "collect":
                    collector_calls += 1
                    return {"text": json.dumps({"fields": {"business": {"status": "observed", "fact": {
                        "value": "English lessons", "source": "customer", "status": "known", "quote": "teach English"}}}})}
            return await super().call(capability, arguments)

    value = proposal("business understood", node_completed=True, interaction={"kind": "none"})
    req = request(tmp_path); host = RecollectHost([value, value], reject_first=True)
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(req, host)
    assert collector_calls == 2


@pytest.mark.asyncio
async def test_invalid_fact_status_repair_names_field_actual_values_and_allowed_enum(tmp_path):
    write_skills(tmp_path)
    definition = config(); node = definition["nodes"][0]
    node.update(collect_fields=[], optional_fact_fields=["business"], next_node=None,
                fact_policies={"business": {"sources": ["inferred"], "allow_unknown": True}})
    bad = {"value": "likely training", "source": "inferred", "status": "provisional", "quote": "reasoned from context"}
    good = {**bad, "status": "known"}

    class StatusRepairHost(ModelHost):
        assessed = 0
        async def call(self, capability, arguments):
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "generate" and payload.get("repair_context"):
                    detail = next(item for item in payload["repair_issues"]
                                  if item.startswith("invalid_fact_status_detail:"))
                    assert "field=business" in detail
                    assert "source=inferred" in detail and "status=provisional" in detail
                    assert "allowed_status=known|unknown" in detail
                if payload["operation"] == "assess":
                    self.assessed += 1
            return await super().call(capability, arguments)

    first = proposal("draft", facts={"business": bad})
    second = proposal("fixed", facts={"business": good}, node_completed=True, interaction={"kind": "none"})
    req = request(tmp_path); req.normalized_input["messages"][0]["content"] = ""
    host = StatusRepairHost([first, second])
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(req, host)
    saved = json.loads((req.transaction_root / "configured-flow.json").read_text())
    assert host.assessed == 1
    assert saved["facts"]["business"]["source"] == "inferred"
    assert saved["facts"]["business"]["status"] == "known"


@pytest.mark.asyncio
async def test_repeated_invalid_fact_status_never_writes_state(tmp_path):
    write_skills(tmp_path)
    definition = config(); node = definition["nodes"][0]
    node.update(collect_fields=[], optional_fact_fields=["business"], next_node=None,
                fact_policies={"business": {"sources": ["inferred"], "allow_unknown": True}})
    bad = {"value": "likely training", "source": "inferred", "status": "provisional", "quote": "reasoned"}
    req = request(tmp_path); req.normalized_input["messages"][0]["content"] = ""
    host = ModelHost([proposal("draft", facts={"business": bad})] * 4)
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(req, host)
    saved = json.loads((req.transaction_root / "configured-flow.json").read_text())
    assert saved["revision"] == 0 and "business" not in saved["facts"]


@pytest.mark.asyncio
async def test_invalid_generation_envelope_repair_lists_allowed_extra_and_missing_keys(tmp_path):
    write_skills(tmp_path)
    definition = config(); definition["nodes"][0].update(collect_fields=[], next_node=None)

    class EnvelopeRepairHost(ModelHost):
        count = 0
        async def call(self, capability, arguments):
            payload = None
            if capability == "agent.execute":
                payload = json.loads(arguments["messages"][-1]["content"])
                if payload["operation"] == "generate":
                    self.count += 1
                    if self.count == 2:
                        detail = next(item for item in payload["repair_issues"]
                                      if item.startswith("generation_envelope_detail:"))
                        assert "allowed=candidate|methods|support_requests" in detail
                        assert "extra=competing_explanation" in detail and "missing=support_requests" in detail
            result = await super().call(capability, arguments)
            if payload and payload["operation"] == "generate" and self.count == 1:
                envelope = json.loads(result["text"])
                envelope.pop("support_requests")
                envelope["competing_explanation"] = "misplaced"
                return {"text": json.dumps(envelope)}
            return result

    value = proposal("fixed", node_completed=True, interaction={"kind": "none"})
    req = request(tmp_path); host = EnvelopeRepairHost([value, value])
    await ConfiguredFlowRuntime(tmp_path, definition, contract_driven=True).handle(req, host)
    assert json.loads((req.transaction_root / "configured-flow.json").read_text())["revision"] == 1
