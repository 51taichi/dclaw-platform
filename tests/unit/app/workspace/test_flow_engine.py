"""Configured flow behavior; fixtures intentionally use non-Luyu node names."""
from copy import deepcopy

import pytest

from qwenpaw.app.workspace.flow_engine import FlowEngine, FlowError, candidate_digest


def definition():
    return {
        "schema_version": "3.0", "id": "consultation", "version": "3.0.0",
        "entry_node": "intake", "nodes": [
            {"id": "intake", "main_skill": "interview", "goal": "Collect business and goal",
             "collect_fields": ["business", "goal"], "required_methods": [],
             "support_skills": [], "dimensions": [], "next_node": "insight", "return_nodes": [],
             "fact_policies": {"business": {"sources": ["customer"], "allow_unknown": False},
                               "goal": {"sources": ["customer"], "allow_unknown": True}}},
            {"id": "insight", "main_skill": "research", "goal": "Explain a concrete opportunity",
             "collect_fields": [], "required_methods": ["scene_method"], "support_skills": [],
             "dimensions": [{"id": "scene", "criterion": "A concrete trigger", "allow_provisional": True},
                            {"id": "barrier", "criterion": "A specific barrier", "allow_provisional": True}],
             "next_node": "production", "return_nodes": ["intake"]},
            {"id": "production", "main_skill": "produce", "goal": "Produce bound material",
             "collect_fields": [], "required_methods": [], "support_skills": [], "dimensions": [],
             "required_receipts": [{"kind": "asset", "status": "submitted"}],
             "next_node": None, "return_nodes": []},
        ],
    }


def candidate(**changes):
    result = {"reply": "What outcome do you need?", "facts": {}, "outcomes": {},
              "node_completed": False, "interaction": {"kind": "none"},
              "actions": []}
    result.update(changes)
    if result["node_completed"] and "interaction" not in changes:
        result["interaction"] = {"kind": "none"}
    return result


def assessment(value, dimensions=None, *, state=None, **changes):
    result = {"candidate_digest": candidate_digest(value), "acceptable": True,
              "facts_valid": True, "reply_valid": True, "dimensions": dimensions or {},
              "issues": [], "context_revision": state["revision"] if state else 0,
              "context_node": state["current_node"] if state else "intake"}
    result.update(changes)
    return result


def apply(engine, state, value, text="I teach English; I want more students.", **kwargs):
    return engine.apply(state, value, assessment(value, state=state), invocation_id="turn-1", customer_text=text, **kwargs)


def intake_facts():
    return {"business": {"value": "English teaching", "source": "customer", "status": "known", "quote": "teach English"},
            "goal": {"value": "more students", "source": "customer", "status": "known", "quote": "more students"}}


def test_model_cannot_choose_a_nonadjacent_destination():
    engine = FlowEngine(definition())
    state = engine.initial_state()
    value = candidate(facts=intake_facts(), node_completed=True, next_node="production")
    with pytest.raises(FlowError, match="unexpected_candidate_fields"):
        apply(engine, state, value)
    assert state["current_node"] == "intake"


def test_schema_repair_reports_expected_type_without_echoing_customer_value():
    with pytest.raises(FlowError) as error:
        FlowEngine._validate_schema("customer confidential words", {"type": "object"}, "fact_schema:ability")
    assert "expected=object" in str(error.value)
    assert "customer confidential" not in str(error.value)


def test_hold_predicate_persists_customer_refusal_and_blocks_effects_and_completion():
    document = definition()
    node = document["nodes"][0]
    node["collect_fields"] = ["publish_authorization"]
    node["fact_policies"] = {"publish_authorization": {"sources": ["customer"], "allow_unknown": False}}
    node["fact_schemas"] = {"publish_authorization": {"type": "boolean"}}
    node["completion_policy"] = {"hold_when": [{
        "field": "publish_authorization", "operator": "equals", "value": False,
        "reason": "customer_publish_refused",
    }]}
    node["capabilities"] = ["publisher.publish"]
    engine = FlowEngine(document)
    state = engine.initial_state()
    refusal = {"value": False, "source": "customer", "status": "known", "quote": "do not publish"}
    proposed = candidate(facts={"publish_authorization": refusal}, node_completed=True,
                         outcomes={"claim": {"ready": True}},
                         actions=[{"capability": "publisher.publish"}])
    report = assessment(proposed, state=state)

    command, bound = engine.resolve(state, proposed, report, customer_text="do not publish")
    assert command["facts"] == {"publish_authorization": refusal}
    assert command["node_completed"] is False
    assert command["outcomes"] == {}
    assert command["actions"] == []
    assert command["interaction"] == {"kind": "external_action", "reason": "customer_publish_refused"}

    # Direct callers cannot bypass resolve: apply enforces the same hold while
    # retaining the customer's authoritative refusal.
    result = engine.apply(state, proposed, report, invocation_id="refuse", customer_text="do not publish")
    assert result["facts"]["publish_authorization"] == refusal
    assert result["current_node"] == "intake"
    assert result["outcomes"]["intake"]["values"] == {}
    assert result["outcomes"]["intake"]["completed"] is False
    assert result["pending_interaction"] == {"kind": "external_action", "reason": "customer_publish_refused"}


def test_hold_predicate_definition_is_closed_and_references_a_configured_fact():
    document = definition()
    document["nodes"][0]["completion_policy"] = {"hold_when": [{
        "field": "unconfigured", "operator": "contains", "value": False, "reason": "blocked",
    }]}
    with pytest.raises(FlowError, match="invalid_hold_policy"):
        FlowEngine(document)


def test_task_scoped_facts_are_bound_by_host_and_not_reused_for_another_content():
    document = definition()
    document["nodes"][2]["collect_fields"] = ["publish_authorization"]
    document["nodes"][2]["fact_policies"] = {"publish_authorization": {
        "sources": ["customer"], "allow_unknown": False,
        "scope_outcome": {"node": "insight", "field": "binding", "keys": ["task_id", "revision"]}}}
    engine = FlowEngine(document)
    state = engine.initial_state(); state["current_node"] = "production"
    state["outcomes"]["insight"] = {"valid": True, "values": {"binding": {"task_id": "task-1", "revision": 1}}}
    fact = {"source": "customer", "status": "known", "value": True, "quote": "publish"}
    result = apply(engine, state, candidate(facts={"publish_authorization": fact}), text="publish")
    assert result["fact_scopes"]["publish_authorization"] == {"task_id": "task-1", "revision": 1}
    result["outcomes"]["insight"]["values"]["binding"]["task_id"] = "task-2"
    assert "publish_authorization" not in engine.prepare(result)["facts"]
    projected = engine.project_scoped_state(result)
    assert projected["fact_history"][-1]["fact"] == fact
    assert result["facts"]["publish_authorization"] == fact  # Never mutate caller.


def test_two_recommendations_keep_the_same_persisted_choice_ids():
    engine=FlowEngine(definition())
    value=candidate(interaction={"kind":"choice","choices":[{"id":"one","text":"One"},{"id":"two","text":"Two"}],"recommended":["one","two"]})
    result=apply(engine,engine.initial_state(),value)
    assert result["pending_interaction"]["recommended"]==["one","two"]
    value["interaction"]["recommended"].append("not-a-choice")
    with pytest.raises(FlowError,match="invalid_choices"):
        apply(engine,engine.initial_state(),value)


def test_choice_text_is_projected_from_business_problem_and_path_not_backend_analysis():
    doc=definition(); node=doc["nodes"][0]
    node["collect_fields"]=[]; node["dimensions"]=[{"id":"candidates","allow_provisional":True}]
    node["completion_policy"]={"requires_prior_interaction":"choice","choice_projection":{
        "outcome":"candidates","collection":"items","id":"id","fields":["problem","path"]}}
    engine=FlowEngine(doc); state=engine.initial_state()
    value=candidate(outcomes={"candidates":{"items":[{"id":"c1","problem":"No trust","path":"Show genuine examples","confidence":0.8}]}},
                    interaction={"kind":"choice","choices":[{"id":"c1","text":"Internal evidence and framework details"}],"recommended":"c1"})
    report=assessment(value,{"candidates":"sufficient"})
    command,bound=engine.resolve(state,value,report,customer_text="")
    assert command["interaction"]["choices"]==[{"id":"c1","label":"A","text":"No trust → Show genuine examples"}]
    assert bound["source_candidate_digest"]==candidate_digest(value)


def test_first_candidate_batch_becomes_host_choice_and_drops_invented_calibration():
    doc = definition(); node = doc["nodes"][0]
    node["collect_fields"] = []
    node["dimensions"] = [
        {"id": "candidates", "allow_provisional": True},
        {"id": "priority", "allow_provisional": True},
        {"id": "calibration", "allow_provisional": False},
    ]
    node["completion_policy"] = {
        "requires_prior_interaction": "choice",
        "choice_binding": {"outcome": "calibration", "selected": "selected_ids",
                           "quote": "quote", "correction": "correction"},
        "choice_projection": {"outcome": "candidates", "collection": "items", "id": "id",
                              "fields": ["problem", "path"], "recommended": "priority.recommended_ids"},
    }
    items = [{"id": f"c{i}", "problem": f"problem {i}", "path": f"path {i}"} for i in range(1, 4)]
    value = candidate(outcomes={
        "candidates": {"items": items},
        "priority": {"recommended_ids": ["c2"], "reasons": ["best fit"]},
    }, interaction={"kind": "choice", "choices": [
        {"id": item["id"], "text": item["id"]} for item in items
    ], "recommended": "c2"})
    engine = FlowEngine(doc); state = engine.initial_state()
    report = assessment(value, {"candidates": "sufficient", "priority": "sufficient",
                                "calibration": "insufficient"})
    command, bound = engine.resolve(state, value, report, customer_text="")
    assert command["node_completed"] is False
    assert command["interaction"] == {"kind": "choice", "choices": [
        {"id": "c1", "label": "A", "text": "problem 1 → path 1"},
        {"id": "c2", "label": "B", "text": "problem 2 → path 2"},
        {"id": "c3", "label": "C", "text": "problem 3 → path 3"}],
        "recommended": "c2"}
    persisted = engine.apply(state, command, bound, invocation_id="first-batch",
                             customer_text="", receipts=[])
    assert persisted["current_node"] == "intake" and persisted["revision"] == 1
    assert persisted["pending_interaction"] == command["interaction"]
    assert "calibration" not in persisted["outcomes"]["intake"]["values"]


def test_bound_choice_projection_requires_valid_recommendation_path():
    doc = definition(); node = doc["nodes"][0]
    node["dimensions"] = [{"id": "candidates"}, {"id": "calibration"}]
    node["completion_policy"] = {"requires_prior_interaction": "choice",
        "choice_binding": {"outcome": "calibration"},
        "choice_projection": {"outcome": "candidates", "collection": "items",
                              "id": "id", "fields": ["problem", "path"]}}
    with pytest.raises(FlowError, match="invalid_choice_projection"):
        FlowEngine(doc)


def test_host_choice_does_not_bypass_professional_schema_dimensions_or_methods():
    doc = definition(); node = doc["nodes"][0]
    node["collect_fields"] = []
    node["required_methods"] = ["candidate_method"]
    node["dimensions"] = [{"id": key, "allow_provisional": False}
                          for key in ("candidates", "priority", "calibration")]
    node["outcome_schemas"] = {"candidates": {"type": "object", "required": ["items"],
        "properties": {"items": {"type": "array", "minItems": 3}}}}
    node["completion_policy"] = {"requires_prior_interaction": "choice",
        "choice_binding": {"outcome": "calibration", "selected": "selected_ids", "quote": "quote", "correction": "correction"},
        "choice_projection": {"outcome": "candidates", "collection": "items", "id": "id",
                              "fields": ["problem", "path"], "recommended": "priority.recommended_ids"}}
    engine = FlowEngine(doc); value = candidate(outcomes={
        "candidates": {"items": [{"id": "c1", "problem": "p", "path": "x"}]},
        "priority": {"recommended_ids": ["c1"]},
        "calibration": {"selected_ids": ["c1"], "quote": "invented"}})
    report = assessment(value, {key: "insufficient" for key in ("candidates", "priority", "calibration")})
    with pytest.raises(FlowError, match="outcome_schema|dimension_insufficient|method_missing"):
        engine.resolve(engine.initial_state(), value, report, customer_text="", receipts=[])


def test_calibration_cannot_replace_persisted_candidate_batch_under_same_ids():
    doc = definition(); node = doc["nodes"][0]
    node["collect_fields"] = []
    node["dimensions"] = [{"id": key, "allow_provisional": False}
                          for key in ("candidates", "priority", "calibration")]
    node["completion_policy"] = {"requires_prior_interaction": "choice",
        "choice_binding": {"outcome": "calibration", "selected": "selected_ids", "quote": "quote", "correction": "correction"},
        "choice_projection": {"outcome": "candidates", "collection": "items", "id": "id",
                              "fields": ["problem", "path"], "recommended": "priority.recommended_ids"}}
    engine = FlowEngine(doc); state = engine.initial_state()
    original = [{"id": f"c{i}", "problem": f"p{i}", "path": f"x{i}"} for i in range(3)]
    first = candidate(outcomes={"candidates": {"items": original},
        "priority": {"recommended_ids": ["c0"]}}, interaction={"kind": "choice",
        "choices": [{"id": item["id"], "text": item["id"]} for item in original], "recommended": "c0"})
    report = assessment(first, {"candidates": "sufficient", "priority": "sufficient", "calibration": "insufficient"})
    command, bound = engine.resolve(state, first, report, customer_text="")
    state = engine.apply(state, command, bound, invocation_id="batch", customer_text="")
    changed = deepcopy(original); changed[0]["problem"] = "different problem"
    answer = candidate(node_completed=True, outcomes={"candidates": {"items": changed},
        "priority": {"recommended_ids": ["c0"]},
        "calibration": {"selected_ids": ["c0"], "quote": "A"}})
    with pytest.raises(FlowError, match="choice_batch_changed"):
        engine.apply(state, answer, assessment(answer, {key: "sufficient" for key in
            ("candidates", "priority", "calibration")}, state=state),
            invocation_id="answer", customer_text="A")


def test_incomplete_calibration_cannot_silently_replace_persisted_candidate_batch():
    doc = definition(); node = doc["nodes"][0]
    node["collect_fields"] = []
    node["dimensions"] = [{"id": key, "allow_provisional": False}
                          for key in ("candidates", "priority", "calibration")]
    node["completion_policy"] = {"requires_prior_interaction": "choice",
        "choice_binding": {"outcome": "calibration", "selected": "selected_ids", "quote": "quote", "correction": "correction"},
        "choice_projection": {"outcome": "candidates", "collection": "items", "id": "id",
                              "fields": ["problem", "path"], "recommended": "priority.recommended_ids"}}
    engine = FlowEngine(doc); state = engine.initial_state()
    original = [{"id": f"c{i}", "problem": f"p{i}", "path": f"x{i}"} for i in range(3)]
    first = candidate(outcomes={"candidates": {"items": original},
        "priority": {"recommended_ids": ["c0"]}}, interaction={"kind": "choice",
        "choices": [{"id": item["id"], "text": item["id"]} for item in original], "recommended": "c0"})
    report = assessment(first, {"candidates": "sufficient", "priority": "sufficient", "calibration": "insufficient"})
    command, bound = engine.resolve(state, first, report, customer_text="")
    state = engine.apply(state, command, bound, invocation_id="batch", customer_text="")
    changed = deepcopy(original); changed[0]["path"] = "silently replaced"
    retry = candidate(node_completed=False, outcomes={"candidates": {"items": changed}},
                      interaction={"kind": "none"})
    with pytest.raises(FlowError, match="choice_batch_changed"):
        engine.apply(state, retry, assessment(retry, {key: "insufficient" for key in
            ("candidates", "priority", "calibration")}, state=state),
            invocation_id="silent-replacement", customer_text="")


def test_incomplete_calibration_cannot_replace_batch_by_replaying_old_choice():
    doc = definition(); node = doc["nodes"][0]
    node["collect_fields"] = []
    node["dimensions"] = [{"id": key, "allow_provisional": False}
                          for key in ("candidates", "priority", "calibration")]
    node["completion_policy"] = {"requires_prior_interaction": "choice",
        "choice_binding": {"outcome": "calibration", "selected": "selected_ids", "quote": "quote", "correction": "correction"},
        "choice_projection": {"outcome": "candidates", "collection": "items", "id": "id",
                              "fields": ["problem", "path"], "recommended": "priority.recommended_ids"}}
    engine = FlowEngine(doc); state = engine.initial_state()
    original = [{"id": f"c{i}", "problem": f"p{i}", "path": f"x{i}"} for i in range(3)]
    first = candidate(outcomes={"candidates": {"items": original},
        "priority": {"recommended_ids": ["c0"]}}, interaction={"kind": "choice",
        "choices": [{"id": item["id"], "text": item["id"]} for item in original], "recommended": "c0"})
    report = assessment(first, {"candidates": "sufficient", "priority": "sufficient", "calibration": "insufficient"})
    command, bound = engine.resolve(state, first, report, customer_text="")
    state = engine.apply(state, command, bound, invocation_id="batch", customer_text="")
    changed = deepcopy(original); changed[0]["problem"] = "replacement hidden behind old labels"
    retry = candidate(node_completed=False, outcomes={"candidates": {"items": changed}},
                      interaction=deepcopy(state["pending_interaction"]))
    with pytest.raises(FlowError, match="choice_batch_changed"):
        engine.apply(state, retry, assessment(retry, {key: "insufficient" for key in
            ("candidates", "priority", "calibration")}, state=state),
            invocation_id="replayed-choice", customer_text="")


def test_completed_intake_moves_exactly_one_node_and_keeps_message_node():
    engine = FlowEngine(definition())
    state = engine.initial_state()
    value = candidate(facts=intake_facts(), node_completed=True, interaction={"kind": "none"})
    result = apply(engine, state, value)
    assert result["current_node"] == "insight"
    assert result["history"][0]["node_id"] == "intake"
    assert result["revision"] == 1
    assert state["revision"] == 0


def test_correction_revalidates_earliest_affected_owner_without_losing_fact_or_faking_pass():
    doc = definition(); doc["fact_change_policy"] = "revalidate_affected_owners"
    engine = FlowEngine(doc); state = engine.initial_state()
    state["current_node"] = "production"; state["facts"] = intake_facts()
    state["outcomes"] = {key: {"valid": True, "completed": True,
        "values": {}, "input_fields": ["business", "goal"]} for key in ["intake", "insight"]}
    corrected = candidate(facts={"business": {"value": "Math teaching", "source": "customer", "status": "known", "quote": "teach Math"}},
                          outcomes={}, interaction={"kind": "none"})
    command, report = engine.resolve(state, corrected, assessment(corrected, state=state), customer_text="I teach Math")
    result = engine.apply(state, command, report, invocation_id="correction", customer_text="I teach Math")
    assert result["current_node"] == "intake"
    assert result["facts"]["business"]["value"] == "Math teaching"
    assert not result["outcomes"]["insight"]["valid"]
    assert result["history"][-1]["revalidation"] == {"target": "intake", "fields": ["business"]}
    assert not result["history"][-1]["completed"]
    # Re-execution starts at the owner, not at its previously completed successor.
    done = candidate(node_completed=True)
    next_state = engine.apply(result, done, assessment(done, state=result), invocation_id="recheck", customer_text="")
    assert next_state["current_node"] == "insight"
    assert next_state["outcomes"]["intake"]["valid"]
    assert not next_state["outcomes"]["insight"]["valid"]


def test_partial_answers_merge_without_overwriting_unrelated_facts():
    engine = FlowEngine(definition())
    value = candidate(facts={"business": intake_facts()["business"]})
    state = apply(engine, engine.initial_state(), value)
    value = candidate(facts={"goal": intake_facts()["goal"]}, node_completed=True)
    state = engine.apply(state, value, assessment(value, state=state), invocation_id="turn-2", customer_text="more students")
    assert state["facts"]["business"]["value"] == "English teaching"
    assert state["facts"]["goal"]["value"] == "more students"
    assert state["current_node"] == "insight"


def test_missing_fields_cannot_complete_even_when_model_says_yes():
    engine = FlowEngine(definition())
    with pytest.raises(FlowError, match="missing_fact:business"):
        apply(engine, engine.initial_state(), candidate(node_completed=True))


def test_unknown_allowed_for_goal_but_not_business():
    engine = FlowEngine(definition())
    facts = intake_facts()
    facts["goal"] = {"value": None, "source": "customer", "quote": "don't know", "status": "unknown"}
    result = apply(engine, engine.initial_state(), candidate(facts=facts, node_completed=True), text="teach English, don't know")
    assert result["current_node"] == "insight"
    facts["business"] = facts["goal"]
    with pytest.raises(FlowError, match="unknown_fact:business"):
        apply(engine, engine.initial_state(), candidate(facts=facts, node_completed=True), text="don't know")


def test_fabricated_customer_quote_rejected_without_mutation():
    engine = FlowEngine(definition())
    state = engine.initial_state()
    with pytest.raises(FlowError, match="ungrounded_fact"):
        apply(engine, state, candidate(facts=intake_facts()), text="hello")
    assert state["facts"] == {}


def test_customer_facts_cannot_be_overwritten_by_inference():
    engine = FlowEngine(definition())
    state = apply(engine, engine.initial_state(), candidate(facts={"business": intake_facts()["business"]}))
    value = candidate(facts={"business": {"value": "medicine", "source": "inferred", "status": "known", "quote": ""}})
    with pytest.raises(FlowError, match="fact_source_not_allowed"):
        engine.apply(state, value, assessment(value, state=state), invocation_id="turn-2", customer_text="okay")


def test_assessment_is_bound_to_the_exact_candidate():
    engine = FlowEngine(definition())
    value = candidate(facts=intake_facts(), node_completed=True)
    stale = assessment(value)
    value["reply"] = "changed"
    with pytest.raises(FlowError, match="assessment_binding"):
        engine.apply(engine.initial_state(), value, stale, invocation_id="turn", customer_text="teach English; more students")


def test_semantically_wrong_facts_rejected_even_with_real_quote():
    engine = FlowEngine(definition())
    value = candidate(facts={"business": {"value": "more students", "quote": "more students", "source": "customer", "status": "known"}})
    with pytest.raises(FlowError, match="semantic_assessment"):
        engine.apply(engine.initial_state(), value, assessment(value, facts_valid=False), invocation_id="turn", customer_text="more students")


def test_shallow_dimensions_and_missing_actual_method_execution_block_completion():
    engine = FlowEngine(definition())
    state = apply(engine, engine.initial_state(), candidate(facts=intake_facts(), node_completed=True))
    value = candidate(outcomes={"scene": "everywhere", "barrier": "trust"}, node_completed=True)
    report = assessment(value, {"scene": "insufficient", "barrier": "sufficient"}, state=state)
    with pytest.raises(FlowError, match="dimension_insufficient:scene"):
        engine.apply(state, value, report, invocation_id="turn-2", customer_text="okay")
    report["dimensions"]["scene"] = "provisional"
    with pytest.raises(FlowError, match="method_missing:scene_method"):
        engine.apply(state, value, report, invocation_id="turn-2", customer_text="okay")


def test_provisional_depth_can_complete_with_current_skill_execution():
    engine = FlowEngine(definition())
    state = apply(engine, engine.initial_state(), candidate(facts=intake_facts(), node_completed=True))
    value = candidate(outcomes={"scene": {"trigger": "job loss", "basis": "hypothesis"}, "barrier": "fear of hidden fees"}, node_completed=True)
    report = assessment(value, {"scene": "provisional", "barrier": "provisional"}, state=state)
    receipts = [{"kind": "method", "method": "scene_method", "skill": "research", "node_id": "insight", "revision": 1}]
    result = engine.apply(state, value, report, invocation_id="turn-2", customer_text="don't know", receipts=receipts)
    assert result["current_node"] == "production"


@pytest.mark.parametrize("wrong", [{"revision": 0}, {"skill": "interview"}, {"node_id": "intake"}])
def test_stale_or_wrong_owner_method_execution_is_not_completion(wrong):
    engine = FlowEngine(definition())
    state = apply(engine, engine.initial_state(), candidate(facts=intake_facts(), node_completed=True))
    value = candidate(outcomes={"scene": "job loss", "barrier": "hidden fees"}, node_completed=True)
    receipt = {"kind": "method", "method": "scene_method", "skill": "research", "node_id": "insight", "revision": 1, **wrong}
    with pytest.raises(FlowError, match="method_missing"):
        engine.apply(state, value, assessment(value, {"scene": "sufficient", "barrier": "sufficient"}, state=state), invocation_id="turn-2", customer_text="okay", receipts=[receipt])


def test_replay_does_not_duplicate_state_and_different_payload_cannot_reuse_id():
    engine = FlowEngine(definition())
    value = candidate(facts={"business": intake_facts()["business"]})
    state = apply(engine, engine.initial_state(), value)
    assert apply(engine, state, value) == state
    with pytest.raises(FlowError, match="invocation_conflict"):
        apply(engine, state, candidate())


def test_definition_rejects_dangling_next_node():
    config = definition()
    config["nodes"][0]["next_node"] = "missing"
    with pytest.raises(FlowError, match="unknown_next_node"):
        FlowEngine(config)


def test_model_cannot_smuggle_receipts_or_authority_into_candidate():
    engine = FlowEngine(definition())
    with pytest.raises(FlowError, match="unexpected_candidate_fields"):
        apply(engine, engine.initial_state(), candidate(receipts=[{"kind": "asset", "status": "submitted"}]))


def test_pending_question_is_persisted_for_short_answer_interpretation():
    engine = FlowEngine(definition())
    result = apply(engine, engine.initial_state(), candidate(interaction={"kind": "question", "fields": ["goal"]}))
    assert result["pending_interaction"] == {"kind": "question", "fields": ["goal"]}


def test_nonfinite_values_never_enter_state():
    engine = FlowEngine(definition())
    with pytest.raises(FlowError, match="invalid_json"):
        apply(engine, engine.initial_state(), candidate(outcomes={"x": float("nan")}))


def test_assessment_against_old_revision_cannot_overwrite_new_fact():
    engine = FlowEngine(definition())
    initial = engine.initial_state()
    value = candidate(facts={"business": intake_facts()["business"]})
    stale = assessment(value, state=initial)
    state = apply(engine, initial, candidate(facts={"business": {"value": "French teaching", "source": "customer", "quote": "teach French", "status": "known"}}), text="teach French")
    with pytest.raises(FlowError, match="stale_assessment"):
        engine.apply(state, value, stale, invocation_id="old-response", customer_text="teach English")
    assert state["facts"]["business"]["value"] == "French teaching"


def test_changing_upstream_fact_requires_owner_revalidation_before_finishing():
    engine = FlowEngine(definition())
    state = apply(engine, engine.initial_state(), candidate(facts=intake_facts(), node_completed=True))
    value = candidate(facts={"business": {"value": "French teaching", "source": "customer", "quote": "teach French", "status": "known"}}, outcomes={"scene": "job loss", "barrier": "fees"}, node_completed=True)
    with pytest.raises(FlowError, match="upstream_result_invalid"):
        engine.apply(state, value, assessment(value, {"scene": "sufficient", "barrier": "sufficient"}, state=state), invocation_id="correction", customer_text="teach French", receipts=[{"kind": "method", "method": "scene_method", "skill": "research", "node_id": "insight", "revision": 1}])


def test_review_can_return_only_to_configured_owner_without_claiming_pass():
    engine = FlowEngine(definition())
    state = apply(engine, engine.initial_state(), candidate(facts=intake_facts(), node_completed=True))
    value = candidate(outcomes={"scene": "Wrong business premise", "barrier": "Different audience"}, return_request={"target": "intake", "reason": "rework"})
    receipts = [{"kind": "method", "method": "scene_method", "skill": "research", "node_id": "insight", "revision": 1}]
    result = engine.apply(state, value, assessment(value, {"scene": "sufficient", "barrier": "sufficient"}, state=state), invocation_id="review", customer_text="wrong business", receipts=receipts)
    assert result["current_node"] == "intake"
    assert result["history"][-1]["completed"] is False
    assert result["history"][-1]["return_request"]["reason"] == "rework"
    value["return_request"]["target"] = "production"
    with pytest.raises(FlowError, match="return_not_allowed"):
        engine.apply(state, value, assessment(value, state=state), invocation_id="review-2", customer_text="wrong business", receipts=receipts)


@pytest.mark.parametrize("poison_receipt", [False, True])
def test_nonfinite_assessment_or_receipt_cannot_poison_persisted_state(poison_receipt):
    engine = FlowEngine(definition())
    value = candidate()
    report = assessment(value)
    receipts = []
    if poison_receipt:
        receipts = [{"kind": "method", "value": float("nan")}]
    else:
        report["issues"] = [float("nan")]
    with pytest.raises(FlowError, match="invalid_json"):
        engine.apply(engine.initial_state(), value, report, invocation_id="turn", customer_text="hello", receipts=receipts)


def test_adding_downstream_fact_does_not_invalidate_upstream_result():
    spec = definition()
    spec["nodes"][1]["collect_fields"] = ["audience"]
    engine = FlowEngine(spec)
    state = apply(engine, engine.initial_state(), candidate(facts=intake_facts(), node_completed=True))
    value = candidate(facts={"audience": {"value": "adults", "source": "customer", "quote": "adults", "status": "known"}})
    result = engine.apply(state, value, assessment(value, state=state), invocation_id="next", customer_text="adults")
    assert result["outcomes"]["intake"]["valid"]


def test_conditional_receipt_rule_requires_declared_output_kind_and_actual_scope():
    spec = definition()
    node = spec["nodes"][0]
    node["completion_policy"] = {"required_outcome_fields": ["production.output_kind"],
                                  "advance_requires": [{"field": "production.asset_bound", "operator": "equals", "value": True}],
                                  "receipt_rules": [{"outcome_field": "production.output_kind", "when_output_kinds": ["image", "video"],
                                                     "requires": [{"kind": "asset", "status": "submitted"}]}]}
    engine = FlowEngine(spec)
    state = engine.initial_state()
    value = candidate(facts=intake_facts(), node_completed=True, outcomes={"production": {"output_kind": "image", "asset_bound": True}})
    with pytest.raises(FlowError, match="external_receipt_missing"):
        apply(engine, state, value)
    value["outcomes"]["production"]["output_kind"] = "text"
    assert apply(engine, state, value)["current_node"] == "insight"
    del value["outcomes"]["production"]["output_kind"]
    with pytest.raises(FlowError, match="required_outcome_missing"):
        apply(engine, state, value)


def test_partial_review_uses_registered_continuation_and_does_not_require_whole_task_pass():
    spec = definition()
    node = spec["nodes"][1]
    node["required_receipts"] = [{"kind": "review", "status": "accepted", "scope": ["asset_card"]},
                                  {"kind": "whole", "status": "ready", "scope": ["whole_task"]}]
    node["completion_policy"] = {"required_outcome_fields": ["production.has_remaining_steps", "production.whole_task_ready"],
                                  "advance_requires": [{"field": "production.whole_task_ready", "operator": "equals", "value": True}],
                                  "routes": [{"when_field": "production.has_remaining_steps", "operator": "equals", "value": True,
                                              "target": "intake", "reason": "production_remaining", "rework": False}]}
    engine = FlowEngine(spec)
    state = apply(engine, engine.initial_state(), candidate(facts=intake_facts(), node_completed=True))
    value = candidate(outcomes={"scene": "valid scene", "barrier": "valid barrier", "production": {"has_remaining_steps": True, "whole_task_ready": False}},
                      node_completed=True, interaction={"kind": "none"})
    methods = [{"kind": "method", "method": "scene_method", "skill": "research", "node_id": "insight", "revision": 1}]
    with pytest.raises(FlowError, match="external_receipt_missing"):
        engine.apply(state, value, assessment(value, {"scene": "sufficient", "barrier": "sufficient"}, state=state), invocation_id="review", customer_text="", receipts=methods)
    result = engine.apply(state, value, assessment(value, {"scene": "sufficient", "barrier": "sufficient"}, state=state), invocation_id="review", customer_text="",
                          receipts=methods + [{"kind": "review", "status": "accepted", "scope": "asset_card", "node_id": "insight", "revision": 1}])
    assert result["current_node"] == "intake"
    assert result["outcomes"]["intake"]["valid"]
    assert result["history"][-1]["route"]["reason"] == "production_remaining"


def test_calibration_requires_persisted_choice_and_a_new_customer_answer():
    spec = definition()
    spec["nodes"][0]["completion_policy"] = {"requires_prior_interaction": "choice"}
    engine = FlowEngine(spec)
    value = candidate(facts=intake_facts(), node_completed=True, interaction={"kind": "none"})
    with pytest.raises(FlowError, match="customer_calibration_required"):
        apply(engine, engine.initial_state(), value)
    first = candidate(facts=intake_facts(), interaction={"kind": "choice", "choices": [{"id": "A", "text": "Clear trial terms"}], "recommended": "A"})
    state = apply(engine, engine.initial_state(), first)
    choice = candidate(node_completed=True, interaction={"kind": "none"})
    with pytest.raises(FlowError, match="customer_calibration_required"):
        engine.apply(state, choice, assessment(choice, state=state), invocation_id="choice", customer_text="")
    updated = engine.apply(state, choice, assessment(choice, state=state), invocation_id="choice", customer_text="A")
    assert updated["current_node"] == "insight"


def test_model_context_contains_business_results_not_internal_assessment_authority():
    engine = FlowEngine(definition())
    state = apply(engine, engine.initial_state(), candidate(facts=intake_facts(), node_completed=True))
    context = engine.prepare(state)
    assert context["outcomes"] == {"intake": {}}
    assert "candidate_digest" not in str(context)
    assert "assessment" not in str(context)
    state["outcomes"]["intake"]["valid"] = False
    assert engine.prepare(state)["outcomes"] == {}


def test_return_reason_must_match_target_policy():
    spec = definition()
    spec["nodes"][1]["return_policies"] = [{"target": "intake", "reasons": ["BUSINESS_CHANGED"]}]
    engine = FlowEngine(spec)
    state = apply(engine, engine.initial_state(), candidate(facts=intake_facts(), node_completed=True))
    value = candidate(outcomes={"scene": "business correction requires re-interview"},
                      return_request={"target": "intake", "reason": "WHATEVER"})
    methods = [{"kind": "method", "method": "scene_method", "skill": "research", "node_id": "insight", "revision": 1}]
    with pytest.raises(FlowError, match="return_reason_not_allowed"):
        engine.apply(state, value, assessment(value, state=state), invocation_id="return", customer_text="", receipts=methods)
    value["return_request"]["reason"] = "BUSINESS_CHANGED"
    assert engine.apply(state, value, assessment(value, state=state), invocation_id="return", customer_text="", receipts=methods)["current_node"] == "intake"


def test_completion_cannot_discard_a_customer_question_or_empty_choice():
    engine = FlowEngine(definition())
    value = candidate(facts=intake_facts(), node_completed=True, interaction={"kind": "question", "fields": ["goal"]})
    with pytest.raises(FlowError, match="completion_has_pending_interaction"):
        apply(engine, engine.initial_state(), value)
    value = candidate(interaction={"kind": "choice"})
    with pytest.raises(FlowError, match="invalid_choices"):
        apply(engine, engine.initial_state(), value)


def test_validation_dimension_does_not_require_a_fabricated_business_result():
    spec = definition()
    spec["nodes"][0]["dimensions"] = [{"id": "semantic", "criterion": "Meaning matches field", "allow_provisional": False, "requires_result": False}]
    engine = FlowEngine(spec)
    state = engine.initial_state()
    value = candidate(facts=intake_facts(), node_completed=True)
    result = engine.apply(state, value, assessment(value, {"semantic": "sufficient"}), invocation_id="entry", customer_text="I teach English and want more students")
    assert result["current_node"] == "insight"
    with pytest.raises(FlowError, match="dimension_insufficient"):
        engine.apply(state, value, assessment(value, {"semantic": "insufficient"}), invocation_id="entry", customer_text="I teach English and want more students")


def test_configured_fact_schema_cannot_be_satisfied_by_a_shallow_label():
    spec = definition()
    spec["nodes"][0]["fact_schemas"] = {"business": {"type": "object", "required": ["service"], "properties": {"service": {"type": "string", "minLength": 1}}}}
    engine = FlowEngine(spec)
    with pytest.raises(FlowError, match="fact_schema"):
        apply(engine, engine.initial_state(), candidate(facts=intake_facts()))
    facts = intake_facts()
    facts["business"]["value"] = {"service": "English lessons"}
    assert apply(engine, engine.initial_state(), candidate(facts=facts))["facts"]["business"]["value"]["service"] == "English lessons"


def test_outcome_schema_and_host_fields_are_required_on_completion():
    spec = definition()
    spec["nodes"][0]["dimensions"] = [{"id": "task", "allow_provisional": False}]
    spec["nodes"][0]["outcome_schemas"] = {"task": {"type": "object", "required": ["topic"], "properties": {"topic": {"type": "string"}},
        "host_enrichment": {"required": ["id"], "properties": {"id": {"type": "string", "minLength": 1}}}}}
    engine = FlowEngine(spec)
    value = candidate(facts=intake_facts(), node_completed=True, outcomes={"task": {"topic": "English lesson"}})
    with pytest.raises(FlowError, match="outcome_schema"):
        engine.apply(engine.initial_state(), value, assessment(value, {"task": "sufficient"}), invocation_id="task", customer_text="teach English more students")


def test_interview_does_not_reask_a_fact_satisfied_by_this_answer():
    engine = FlowEngine(definition())
    value = candidate(facts=intake_facts(), interaction={"kind": "question", "fields": ["goal"]})
    with pytest.raises(FlowError, match="question_already_answered:goal"):
        apply(engine, engine.initial_state(), value)
    # A known-but-conflicting fact can be clarified, with explicit grounds.
    value["interaction"]["clarification"] = {"field": "goal", "reason": "Two conflicting target statements need resolution"}
    assert engine.apply(engine.initial_state(), value, assessment(value, clarification_fields=["goal"]), invocation_id="clarify", customer_text="teach English more students")["revision"] == 1


def test_question_permission_is_current_node_not_global_field_registration():
    spec = definition()
    spec["nodes"][2]["collect_fields"] = ["material"]
    engine = FlowEngine(spec)
    value = candidate(interaction={"kind": "question", "fields": ["material"]})
    with pytest.raises(FlowError, match="question_outside_current_node"):
        apply(engine, engine.initial_state(), value)


@pytest.mark.parametrize("fields", [[], ["business", "business"], ["business", "goal"]])
def test_question_requires_specific_unique_fields_within_node_limit(fields):
    spec = definition()
    spec["nodes"][0]["customer_input_policy"] = {"mode": "required", "max_questions": 1}
    engine = FlowEngine(spec)
    value = candidate(interaction={"kind": "question", "fields": fields})
    with pytest.raises(FlowError, match="invalid_question_fields"):
        apply(engine, engine.initial_state(), value)


@pytest.mark.parametrize("interaction", [
    {"kind": "question", "fields": ["goal"]}, {"kind": "authorization"},
    {"kind": "choice", "choices": [{"id": "a", "text": "Do the analysis"}]},
])
def test_direct_apply_cannot_ask_for_customer_work_in_no_input_node(interaction):
    spec = definition()
    spec["nodes"][0]["customer_input_policy"] = {"mode": "none"}
    engine = FlowEngine(spec)
    with pytest.raises(FlowError, match="customer_input_not_allowed"):
        apply(engine, engine.initial_state(), candidate(interaction=interaction))


def test_model_false_completion_safely_stays_even_when_schema_is_ready():
    engine = FlowEngine(definition())
    state = engine.initial_state()
    value = candidate(facts=intake_facts(), interaction={"kind": "none"})
    command, verdict = engine.resolve(state, value, assessment(value), customer_text="teach English more students")
    assert command["node_completed"] is False
    assert command["interaction"] == {"kind": "none"}
    result = engine.apply(state, command, verdict, invocation_id="resolve", customer_text="teach English more students")
    assert result["current_node"] == "intake"
    assert result["outcomes"]["intake"]["completed"] is False
    assert verdict["source_candidate_digest"] == candidate_digest(value)


def test_contract_never_completes_missing_facts_despite_model_claim():
    engine = FlowEngine(definition())
    state = engine.initial_state()
    value = candidate(facts={"business": intake_facts()["business"]}, node_completed=True)
    command, verdict = engine.resolve(state, value, assessment(value), customer_text="teach English")
    assert command["node_completed"] is False
    assert command["interaction"] == {"kind": "question", "fields": ["goal"]}


def test_incomplete_candidate_still_must_match_declared_outcome_schema():
    spec = definition()
    spec["nodes"][0]["dimensions"] = [{"id": "diagnosis", "allow_provisional": True}]
    spec["nodes"][0]["outcome_schemas"] = {
        "diagnosis": {
            "type": "object",
            "additionalProperties": False,
            "required": ["problem"],
            "properties": {"problem": {"type": "string", "minLength": 1}},
        }
    }
    engine = FlowEngine(spec)
    value = candidate(outcomes={"diagnosis": {"problem": 7}}, node_completed=False)
    with pytest.raises(FlowError, match=r"outcome_schema:diagnosis:problem:type:expected=string"):
        apply(engine, engine.initial_state(), value)


def test_all_unknown_minimum_basis_requests_one_concrete_field_not_model_repair_loop():
    spec = definition()
    spec["nodes"][0]["minimum_known_groups"] = [["business", "goal"]]
    spec["nodes"][0]["fact_policies"]["business"]["allow_unknown"] = True
    engine = FlowEngine(spec)
    value = candidate(facts={key: {"value": None, "source": "customer", "status": "unknown", "quote": "I do not know"}
                             for key in ("business", "goal")},
                      interaction={"kind": "question", "fields": ["business"]})
    command, report = engine.resolve(engine.initial_state(), value, assessment(value), customer_text="I do not know")
    assert command["interaction"] == {"kind": "question", "fields": ["business"]}
    state = engine.apply(engine.initial_state(), command, report, invocation_id="unknown-basis", customer_text="I do not know")
    assert state["current_node"] == "intake" and state["facts"]["goal"]["status"] == "unknown"


def test_incorrect_completion_claim_safely_stays_with_specific_diagnostics():
    engine = FlowEngine(definition())
    state = apply(engine, engine.initial_state(), candidate(facts=intake_facts(), node_completed=True))
    value = candidate(node_completed=True, interaction={"kind": "none"})
    command, verdict = engine.resolve(
        state, value, assessment(value, {"scene": "insufficient", "barrier": "provisional"}, state=state),
        customer_text="",
    )
    assert command["node_completed"] is False
    assert command["interaction"] == {"kind": "none"}
    assert verdict["transition_diagnostics"] == {
        "status": "held",
        "code": "dimension_insufficient",
        "fields": ["scene"],
    }
    result = engine.apply(state, command, verdict, invocation_id="held", customer_text="")
    assert result["current_node"] == "insight"


def test_calibrated_selection_is_bound_to_persisted_choices_and_verbatim_reply():
    spec = definition()
    spec["nodes"][0]["dimensions"] = [{"id": "calibration", "allow_provisional": False}]
    spec["nodes"][0]["completion_policy"] = {"requires_prior_interaction": "choice",
        "choice_binding": {"outcome": "calibration", "selected": "selected_ids", "quote": "quote", "correction": "correction"}}
    engine = FlowEngine(spec)
    state = apply(engine, engine.initial_state(), candidate(facts=intake_facts(), interaction={"kind": "choice", "choices": [{"id": "one", "text": "First explanation"}], "recommended": "one"}))
    value = candidate(node_completed=True, outcomes={"calibration": {"selected_ids": ["invented"], "quote": "first"}})
    with pytest.raises(FlowError, match="choice_binding"):
        engine.apply(state, value, assessment(value, {"calibration": "sufficient"}, state=state), invocation_id="answer", customer_text="first")
    value["outcomes"]["calibration"]["selected_ids"] = ["one"]
    assert engine.apply(state, value, assessment(value, {"calibration": "sufficient"}, state=state), invocation_id="answer", customer_text="first")["current_node"] == "insight"
    with pytest.raises(FlowError, match="choice_binding"):
        engine.apply(state, value, assessment(value, {"calibration": "sufficient"}, state=state), invocation_id="answer", customer_text="not my answer")
