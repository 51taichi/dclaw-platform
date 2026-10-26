"""Business-neutral configured flow kernel.

The host owns state, invocation identity and execution receipts. Model output is
a proposal, never an authority-bearing transition or external success event.
Semantic quality is evaluated separately and bound to the exact proposal.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from jsonschema import Draft202012Validator


class FlowError(ValueError):
    """A proposal/configuration cannot be committed; existing state is intact."""


def candidate_digest(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (ValueError, TypeError) as exc:
        raise FlowError("invalid_json") from exc
    return hashlib.sha256(encoded.encode()).hexdigest()


def _nonempty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list)):
        return bool(value) and any(
            _nonempty(v)
            for v in (value.values() if isinstance(value, dict) else value)
        )
    return value is not None


def _at(value, path):
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


class FlowEngine:
    """Validate proposals and return a new state, never mutate the input."""

    def __init__(self, definition: dict[str, Any]):
        candidate_digest(definition)
        self.definition = deepcopy(definition)
        raw_nodes = definition.get("nodes")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise FlowError("missing_nodes")
        self.nodes = {}
        for node in raw_nodes:
            node_id = node.get("id") if isinstance(node, dict) else None
            if (
                not isinstance(node_id, str)
                or not node_id
                or node_id in self.nodes
            ):
                raise FlowError("invalid_node_id")
            if not node.get("main_skill") or not node.get("goal"):
                raise FlowError("invalid_node_owner")
            self.nodes[node_id] = deepcopy(node)
        if definition.get("entry_node") not in self.nodes:
            raise FlowError("unknown_entry_node")
        for node in self.nodes.values():
            if (
                node.get("next_node") is not None
                and node["next_node"] not in self.nodes
            ):
                raise FlowError("unknown_next_node")
            if node.get("next_node") == node["id"]:
                raise FlowError("self_forward_transition")
            if any(
                target not in self.nodes
                for target in node.get("return_nodes", [])
            ):
                raise FlowError("unknown_return_node")
            dimensions = node.get("dimensions", [])
            ids = [dimension["id"] for dimension in dimensions]
            if len(ids) != len(set(ids)):
                raise FlowError("duplicate_dimension")
            completion = node.get("completion_policy", {})
            projection = completion.get("choice_projection")
            if projection is not None:
                legacy_keys = {"outcome", "collection", "id", "fields"}
                configured_keys = legacy_keys | {"recommended"}
                expected = (
                    configured_keys
                    if completion.get("choice_binding")
                    else (
                        configured_keys
                        if "recommended" in projection
                        else legacy_keys
                    )
                )
                if (
                    not isinstance(projection, dict)
                    or set(projection) != expected
                    or any(
                        not isinstance(projection.get(key), str)
                        or not projection[key].strip()
                        for key in expected - {"fields"}
                    )
                    or not isinstance(projection.get("fields"), list)
                    or not projection["fields"]
                    or any(
                        not isinstance(field, str) or not field.strip()
                        for field in projection["fields"]
                    )
                    or projection["outcome"] not in ids
                    or (
                        "recommended" in projection
                        and projection["recommended"].split(".", 1)[0]
                        not in ids
                    )
                ):
                    raise FlowError("invalid_choice_projection")
        self.definition_digest = candidate_digest(definition)
        self.fields = {
            key
            for node in self.nodes.values()
            for key in node.get("collect_fields", [])
            + node.get("optional_fact_fields", [])
        }
        for node in self.nodes.values():
            holds = node.get("completion_policy", {}).get("hold_when", [])
            if not isinstance(holds, list) or any(
                not isinstance(item, dict)
                or set(item) != {"field", "operator", "value", "reason"}
                or item.get("operator") != "equals"
                or item.get("field") not in self.fields
                or not isinstance(item.get("reason"), str)
                or not item["reason"].strip()
                for item in holds
            ):
                raise FlowError("invalid_hold_policy")
        self.policies = {}
        self.fact_schemas = {}
        for node in self.nodes.values():
            for key, schema in node.get("fact_schemas", {}).items():
                if (
                    key in self.fact_schemas
                    and self.fact_schemas[key] != schema
                ):
                    raise FlowError("conflicting_fact_schema")
                Draft202012Validator.check_schema(schema)
                self.fact_schemas[key] = deepcopy(schema)
            for key, policy in node.get("fact_policies", {}).items():
                if key in self.policies and self.policies[key] != policy:
                    raise FlowError("conflicting_fact_policy")
                self.policies[key] = policy

    def initial_state(self) -> dict[str, Any]:
        return {
            "schema_version": 3,
            "definition_digest": self.definition_digest,
            "flow_id": self.definition["id"],
            "current_node": self.definition["entry_node"],
            "revision": 0,
            "facts": {},
            "outcomes": {},
            "history": [],
            "pending_interaction": None,
            "status": "active",
            "invocations": {},
        }

    def prepare(self, state: dict[str, Any]) -> dict[str, Any]:
        self._validate_state(state)
        state = self.project_scoped_state(state)
        return {
            "node": deepcopy(self.nodes[state["current_node"]]),
            "revision": state["revision"],
            "facts": deepcopy(state["facts"]),
            # The model consumes business results, never serialized commit
            # certificates/assessments that it could echo as new authority.
            "outcomes": {
                key: deepcopy(result["values"])
                for key, result in state["outcomes"].items()
                if result.get("valid")
            },
            "pending_interaction": deepcopy(state["pending_interaction"]),
        }

    def _fact_scope(self, state, policy):
        spec = policy.get("scope_outcome")
        if not spec:
            return None
        result = state.get("outcomes", {}).get(spec["node"], {})
        value = (
            _at(result.get("values", {}), spec["field"])
            if result.get("valid")
            else None
        )
        if not isinstance(value, dict) or any(
            value.get(key) is None for key in spec["keys"]
        ):
            return None
        return {key: deepcopy(value[key]) for key in spec["keys"]}

    def project_scoped_state(self, state):
        """Archive stale task facts; never silently authorize their new scope."""
        result = deepcopy(state)
        for key in list(result["facts"]):
            policy = self.policies.get(key, {})
            if not policy.get("scope_outcome"):
                continue
            scope = self._fact_scope(result, policy)
            previous = result.get("fact_scopes", {}).get(key)
            if scope is None or previous != scope:
                result.setdefault("fact_history", []).append(
                    {
                        "field": key,
                        "fact": result["facts"].pop(key),
                        "scope": previous,
                        "archived_at_revision": result["revision"],
                    },
                )
                result.get("fact_scopes", {}).pop(key, None)
        return result

    def _validate_state(self, state):
        candidate_digest(state)
        if (
            state.get("schema_version") != 3
            or state.get("definition_digest") != self.definition_digest
            or state.get("flow_id") != self.definition["id"]
        ):
            raise FlowError("state_definition_mismatch")
        if state.get("current_node") not in self.nodes:
            raise FlowError("state_node_missing")
        if type(state.get("revision")) is not int or state["revision"] < 0:
            raise FlowError("invalid_revision")

    def resolve(
        self,
        state,
        candidate,
        assessment,
        *,
        customer_text,
        receipts=(),
    ):
        """Validate a model flow decision without inventing a second decision.

        This follows the configured-agent gateway contract: the model proposes
        completion, while the host validates schema, evidence and the configured
        adjacent route.  A false proposal always stays.  An invalid true proposal
        is downgraded to a diagnosable safe stay instead of becoming an exception
        or a host-invented transition.
        """
        self._validate_state(state)
        self._validate_assessment(
            state,
            assessment,
            candidate_digest(candidate),
        )
        state = self.project_scoped_state(state)
        command = deepcopy(candidate)
        verdict = deepcopy(assessment)
        verdict["source_candidate_digest"] = candidate_digest(candidate)
        verdict["candidate_digest"] = candidate_digest(command)
        probe = deepcopy(state)
        changed = self._merge_facts(probe, candidate["facts"], customer_text)
        hold = self._matched_hold(probe, self.nodes[state["current_node"]])
        if hold:
            command.update(
                node_completed=False,
                interaction={
                    "kind": "external_action",
                    "reason": hold["reason"],
                },
                outcomes={},
                actions=[],
            )
            command.pop("return_request", None)
            verdict["candidate_digest"] = candidate_digest(command)
            return command, verdict
        if self._revalidation_target(state, changed):
            # Commit only the accepted correction. Work derived from invalidated
            # inputs, and external calls based on it, must be generated afresh.
            command.update(
                node_completed=False,
                interaction={"kind": "none"},
                outcomes={},
                actions=[],
            )
            command.pop("return_request", None)
            verdict["candidate_digest"] = candidate_digest(command)
            return command, verdict
        if not command["node_completed"] and not command.get("return_request"):
            # The model is the configured flow-decision source.  The host may
            # reject an invalid transition, but must never promote a false flag.
            self._project_choice_interaction(state, command)
            verdict["candidate_digest"] = candidate_digest(command)
            self.apply(
                state,
                command,
                verdict,
                invocation_id=f"plan:{state['revision']}:{candidate_digest(command)}",
                customer_text=customer_text,
                receipts=receipts,
            )
            return command, verdict
        try:
            self.apply(
                state,
                command,
                verdict,
                invocation_id=f"plan:{state['revision']}:{candidate_digest(command)}",
                customer_text=customer_text,
                receipts=receipts,
            )
            return command, verdict
        except FlowError as exc:
            readiness_errors = {
                "missing_fact",
                "unknown_fact",
                "minimum_known_group",
                "dimension_insufficient",
                "method_missing",
                "required_outcome_missing",
                "advance_condition_missing",
                "external_receipt_missing",
                "customer_calibration_required",
                "outcome_schema",
                "choice_binding",
                "choice_batch_changed",
                "upstream_result_invalid",
            }
            if str(exc).split(":")[0] not in readiness_errors:
                raise
            readiness_reason = str(exc)
        command["node_completed"] = False
        command["interaction"] = deepcopy(candidate["interaction"])
        node = self.nodes[state["current_node"]]
        verdict["transition_diagnostics"] = self._transition_diagnostics(
            readiness_reason,
        )
        merged = {**state["facts"], **candidate["facts"]}
        missing = [
            field
            for field in node.get("collect_fields", [])
            if field not in merged
            or (
                merged[field]["status"] == "unknown"
                and not self.policies.get(field, {}).get("allow_unknown", True)
            )
        ]
        if not missing:
            missing = self._minimum_basis_questions(node, merged)
        if missing:
            command["interaction"] = {
                "kind": "question",
                "fields": missing[
                    : node.get("customer_input_policy", {}).get(
                        "max_questions",
                        3,
                    )
                ],
            }
        elif (
            readiness_reason.split(":")[0] == "customer_calibration_required"
            and (state.get("pending_interaction") or {}).get("kind")
            != "choice"
            and isinstance(
                node.get("completion_policy", {}).get("choice_binding"),
                dict,
            )
            and isinstance(
                node.get("completion_policy", {})
                .get("choice_projection", {})
                .get("recommended"),
                str,
            )
        ):
            projection = node.get("completion_policy", {}).get(
                "choice_projection",
            )
            binding = node.get("completion_policy", {}).get("choice_binding")
            if not isinstance(projection, dict) or not isinstance(
                binding,
                dict,
            ):
                raise FlowError("choice_projection_invalid")
            # A generator cannot self-attest the customer's selection while it
            # is proposing the first candidate batch.
            command["outcomes"].pop(binding["outcome"], None)
            previous = state.get("outcomes", {}).get(node["id"], {})
            values = {
                **(
                    previous.get("values", {}) if previous.get("valid") else {}
                ),
                **command["outcomes"],
            }
            # The missing customer selection is the only deferred Gate. All
            # professional work must already satisfy its normal schema,
            # semantic dimensions, methods and receipts before it is shown.
            projection_node = deepcopy(node)
            projection_node["dimensions"] = [
                item
                for item in node.get("dimensions", [])
                if item["id"] != binding["outcome"]
            ]
            projection_node["outcome_schemas"] = {
                key: schema
                for key, schema in node.get("outcome_schemas", {}).items()
                if key != binding["outcome"]
            }
            self._check_completion(
                probe,
                projection_node,
                values,
                assessment,
                receipts,
            )
            if any(
                not probe["outcomes"].get(key, {}).get("valid")
                or not probe["outcomes"].get(key, {}).get("completed")
                for key in self._predecessors(node["id"])
            ):
                raise FlowError("upstream_result_invalid")
            items = _at(
                values.get(projection["outcome"], {}),
                projection["collection"],
            )
            recommended = _at(values, projection["recommended"])
            if (
                not isinstance(items, list)
                or not 3 <= len(items) <= 5
                or not isinstance(recommended, list)
                or not 1 <= len(recommended) <= 2
                or any(not isinstance(item, str) for item in recommended)
            ):
                raise FlowError("choice_projection_invalid")
            ids = [
                item.get(projection["id"]) if isinstance(item, dict) else None
                for item in items
            ]
            if (
                any(not isinstance(item, str) or not item for item in ids)
                or len(set(ids)) != len(ids)
                or any(item not in ids for item in recommended)
            ):
                raise FlowError("choice_projection_invalid")
            command["interaction"] = {
                "kind": "choice",
                "choices": [{"id": item, "text": item} for item in ids],
                "recommended": recommended,
            }
        elif readiness_reason.split(":")[0] == "choice_batch_changed":
            projection = node.get("completion_policy", {}).get(
                "choice_projection",
                {},
            )
            protected = {projection.get("outcome")}
            recommended = projection.get("recommended")
            if isinstance(recommended, str):
                protected.add(recommended.split(".", 1)[0])
            command["outcomes"] = {
                key: value
                for key, value in command["outcomes"].items()
                if key not in protected
            }
        elif readiness_reason.split(":")[0] == "choice_binding":
            binding = node.get("completion_policy", {}).get(
                "choice_binding",
                {},
            )
            if isinstance(binding.get("outcome"), str):
                command["outcomes"].pop(binding["outcome"], None)
        verdict["candidate_digest"] = candidate_digest(command)
        self._project_choice_interaction(state, command)
        verdict["candidate_digest"] = candidate_digest(command)
        return command, verdict

    def _project_choice_interaction(self, state, command):
        if command["interaction"]["kind"] != "choice":
            return
        node = self.nodes[state["current_node"]]
        projection = node.get("completion_policy", {}).get("choice_projection")
        if projection:
            previous = state.get("outcomes", {}).get(node["id"], {})
            values = {
                **(
                    previous.get("values", {}) if previous.get("valid") else {}
                ),
                **command["outcomes"],
            }
            items = _at(
                values.get(projection["outcome"], {}),
                projection["collection"],
            )
            choices = command["interaction"].get("choices", [])
            if (
                not isinstance(items, list)
                or not items
                or any(
                    not isinstance(item, dict)
                    or not isinstance(item.get(projection["id"]), str)
                    or any(
                        not isinstance(item.get(field), str)
                        or not item[field].strip()
                        for field in projection["fields"]
                    )
                    for item in items
                )
            ):
                raise FlowError("choice_projection_invalid")
            by_id = {item[projection["id"]]: item for item in items}
            if len(by_id) != len(items) or set(by_id) != {
                item["id"] for item in choices
            }:
                raise FlowError("choice_projection_id_mismatch")
            for item in choices:
                item["text"] = " → ".join(
                    by_id[item["id"]][field].strip()
                    for field in projection["fields"]
                )
        for index, item in enumerate(
            command["interaction"].get("choices", []),
        ):
            item["label"] = chr(65 + index) if index < 26 else str(index + 1)

    @staticmethod
    def _transition_diagnostics(reason):
        parts = str(reason).split(":")
        code = parts[0] if parts else "completion_not_accepted"
        fields = []
        if (
            code
            in {
                "missing_fact",
                "unknown_fact",
                "dimension_insufficient",
                "method_missing",
                "required_outcome_missing",
                "advance_condition_missing",
            }
            and len(parts) > 1
        ):
            fields = [parts[1]]
        elif code == "outcome_schema" and len(parts) > 1:
            path = ".".join(item for item in parts[1:3] if item)
            fields = [path or parts[1]]
        elif code in {"customer_calibration_required", "choice_binding"}:
            fields = ["customer_calibration"]
        elif code == "choice_batch_changed":
            fields = ["persisted_choice_batch"]
        elif code == "external_receipt_missing" and len(parts) > 1:
            fields = [parts[1]]
        elif (
            code
            in {
                "outcome_enrichment",
                "prepare_dependency",
                "context",
                "support",
                "evidence",
                "platform_plan",
                "platform_execute",
                "output",
            }
            and len(parts) > 1
        ):
            # Adapter errors are reduced to a validated, non-sensitive code by
            # ConfiguredFlowRuntime._hook before they reach the flow kernel.
            fields = [parts[1]]
        return {"status": "held", "code": code, "fields": fields}

    def apply(
        self,
        state,
        candidate,
        assessment,
        *,
        invocation_id,
        customer_text,
        receipts=(),
    ):
        self._validate_state(state)
        state = self.project_scoped_state(state)
        digest = candidate_digest(candidate)
        candidate_digest(assessment)
        candidate_digest(receipts)
        if not isinstance(receipts, (list, tuple)) or any(
            not isinstance(item, dict) for item in receipts
        ):
            raise FlowError("invalid_receipts")
        if not isinstance(invocation_id, str) or not invocation_id:
            raise FlowError("missing_invocation")
        prior = state["invocations"].get(invocation_id)
        if prior is not None:
            if prior != digest:
                raise FlowError("invocation_conflict")
            return deepcopy(state)
        self._validate_candidate(candidate)
        self._validate_assessment(state, assessment, digest)
        if state["status"] != "active":
            raise FlowError("flow_finished")
        node = self.nodes[state["current_node"]]
        return_request = candidate.get("return_request")
        if return_request and (
            return_request["target"] not in node.get("return_nodes", [])
            or candidate["node_completed"]
        ):
            raise FlowError("return_not_allowed")
        if (
            return_request
            and "return_policies" in node
            and not any(
                item["target"] == return_request["target"]
                and return_request["reason"] in item["reasons"]
                for item in node["return_policies"]
            )
        ):
            raise FlowError("return_reason_not_allowed")
        new = deepcopy(state)
        changed = self._merge_facts(new, candidate["facts"], customer_text)
        hold = self._matched_hold(new, node)
        if hold:
            candidate = deepcopy(candidate)
            candidate.update(
                node_completed=False,
                interaction={
                    "kind": "external_action",
                    "reason": hold["reason"],
                },
                outcomes={},
                actions=[],
            )
            candidate.pop("return_request", None)
            return_request = None
        revalidate = self._revalidation_target(state, changed)
        if revalidate and (
            candidate["node_completed"]
            or candidate["actions"]
            or candidate["outcomes"]
            or return_request
            or candidate["interaction"]["kind"] != "none"
        ):
            raise FlowError("correction_revalidation_required")
        interaction = candidate["interaction"]
        input_policy = node.get("customer_input_policy", {})
        if input_policy.get("mode") == "none" and interaction["kind"] in {
            "question",
            "choice",
            "authorization",
        }:
            raise FlowError("customer_input_not_allowed")
        if interaction["kind"] == "question":
            fields = interaction.get("fields")
            if (
                not isinstance(fields, list)
                or not fields
                or any(not isinstance(field, str) for field in fields)
                or len(set(fields)) != len(fields)
                or len(fields) > input_policy.get("max_questions", 3)
            ):
                raise FlowError("invalid_question_fields")
            if set(fields) - set(node.get("collect_fields", [])):
                raise FlowError("question_outside_current_node")
            for field in fields:
                fact = new["facts"].get(field)
                if fact and (
                    fact["status"] == "known"
                    or self.policies.get(field, {}).get("allow_unknown", True)
                ):
                    if fact[
                        "status"
                    ] == "unknown" and field in self._minimum_basis_questions(
                        node,
                        new["facts"],
                    ):
                        continue
                    clarification = interaction.get("clarification", {})
                    if (
                        clarification.get("field") != field
                        or not clarification.get("reason")
                        or field
                        not in assessment.get("clarification_fields", [])
                    ):
                        raise FlowError(f"question_already_answered:{field}")
        dimensions = {
            dimension["id"]: dimension
            for dimension in node.get("dimensions", [])
        }
        policy = node.get("completion_policy", {})
        paths = policy.get("required_outcome_fields", []) + [
            item["field"] for item in policy.get("advance_requires", [])
        ]
        paths += [item["when_field"] for item in policy.get("routes", [])]
        paths += [
            item["outcome_field"] for item in policy.get("receipt_rules", [])
        ]
        allowed = set(dimensions) | {path.split(".")[0] for path in paths}
        if set(candidate["outcomes"]) - allowed:
            raise FlowError("unknown_outcome")
        self._validate_present_outcomes(node, candidate["outcomes"])
        # A result becomes stale when its input facts change. Preserve old results
        # for audit, but do not use them as current completion certificates.
        if changed:
            for result in new["outcomes"].values():
                if changed.intersection(
                    result.get("input_fields", state["facts"].keys()),
                ):
                    result["valid"] = False
        old_result = new["outcomes"].get(node["id"], {})
        values = (
            deepcopy(old_result.get("values", {}))
            if old_result.get("valid")
            else {}
        )
        complete = candidate["node_completed"]
        projection = policy.get("choice_projection")
        binding = policy.get("choice_binding")
        if (
            isinstance(projection, dict)
            and isinstance(binding, dict)
            and (state.get("pending_interaction") or {}).get("kind")
            == "choice"
        ):
            protected = {projection["outcome"]}
            if isinstance(projection.get("recommended"), str):
                protected.add(projection["recommended"].split(".", 1)[0])
            batch_changed = any(
                key in candidate["outcomes"]
                and candidate["outcomes"][key] != values.get(key)
                for key in protected
            )
            # A persisted choice batch is immutable while its calibration is
            # pending.  Accepting a replacement here would require a fresh,
            # independently assessed projection and a new interaction binding;
            # replaying the old choice envelope cannot establish either.
            if batch_changed:
                raise FlowError("choice_batch_changed")
        values.update(deepcopy(candidate["outcomes"]))
        route = None
        if complete:
            required_interaction = policy.get("requires_prior_interaction")
            if required_interaction and (
                not customer_text.strip()
                or (state.get("pending_interaction") or {}).get("kind")
                != required_interaction
            ):
                raise FlowError("customer_calibration_required")
            selection = policy.get("choice_binding")
            if selection:
                result = values.get(selection["outcome"], {})
                ids = {
                    item["id"]
                    for item in (state.get("pending_interaction") or {}).get(
                        "choices",
                        [],
                    )
                }
                selected = (
                    result.get(selection["selected"])
                    if isinstance(result, dict)
                    else None
                )
                quote = (
                    result.get(selection["quote"])
                    if isinstance(result, dict)
                    else None
                )
                correction = (
                    result.get(selection["correction"])
                    if isinstance(result, dict)
                    else None
                )
                if (
                    not isinstance(selected, list)
                    or any(
                        not isinstance(item, str) or item not in ids
                        for item in selected
                    )
                    or (
                        not selected
                        and not (
                            isinstance(correction, str) and correction.strip()
                        )
                    )
                    or not isinstance(quote, str)
                    or not quote.strip()
                    or quote not in customer_text
                ):
                    raise FlowError("choice_binding")
            if any(
                not new["outcomes"].get(key, {}).get("valid")
                or not new["outcomes"].get(key, {}).get("completed")
                for key in self._predecessors(node["id"])
            ):
                raise FlowError("upstream_result_invalid")
            route = self._check_completion(
                new,
                node,
                values,
                assessment,
                receipts,
            )
        if return_request:
            self._check_methods(new, node, receipts)
            if not values:
                raise FlowError("return_result_missing")
        for action in candidate["actions"]:
            if not isinstance(action, dict) or action.get(
                "capability",
            ) not in node.get("capabilities", []):
                raise FlowError("action_not_allowed")
        new["outcomes"][node["id"]] = {
            "values": values,
            "valid": True,
            "completed": complete and route is None,
            "assessment": deepcopy(assessment),
            "input_revision": state["revision"],
            "candidate_digest": digest,
            "input_fields": sorted(new["facts"]),
        }
        new["history"].append(
            {
                "node_id": node["id"],
                "main_skill": node["main_skill"],
                "revision": state["revision"] + 1,
                "invocation_id": invocation_id,
                "reply": candidate["reply"],
                "completed": complete,
                "candidate_digest": digest,
                "receipts": deepcopy(list(receipts)),
            },
        )
        new["pending_interaction"] = deepcopy(candidate["interaction"])
        if revalidate:
            new["history"][-1]["revalidation"] = {
                "target": revalidate,
                "fields": sorted(changed),
            }
            new["current_node"] = revalidate
            new["pending_interaction"] = None
            for key in set(self.nodes) - set(self._predecessors(revalidate)):
                if key in new["outcomes"]:
                    new["outcomes"][key]["valid"] = False
        elif route:
            new["history"][-1]["route"] = deepcopy(route)
            new["history"][-1]["completed"] = False
            new["current_node"] = route["target"]
            new["pending_interaction"] = None
            if route.get("rework"):
                for key in set(self.nodes) - set(
                    self._predecessors(route["target"]),
                ):
                    if key in new["outcomes"]:
                        new["outcomes"][key]["valid"] = False
        elif return_request:
            new["history"][-1]["return_request"] = deepcopy(return_request)
            new["current_node"] = return_request["target"]
            new["pending_interaction"] = None
            affected = set(self.nodes) - set(
                self._predecessors(return_request["target"]),
            )
            for key in affected:
                if key in new["outcomes"]:
                    new["outcomes"][key]["valid"] = False
        elif complete:
            if node.get("next_node") is None:
                new["status"] = "completed"
            else:
                new["current_node"] = node["next_node"]
            new["pending_interaction"] = None
        new["revision"] += 1
        new["invocations"][invocation_id] = digest
        return self.project_scoped_state(new)

    def _revalidation_target(self, state, changed):
        if (
            not changed
            or self.definition.get("fact_change_policy")
            != "revalidate_affected_owners"
        ):
            return None
        for key in self._predecessors(state["current_node"]):
            result = state.get("outcomes", {}).get(key, {})
            if result and changed.intersection(
                result.get("input_fields", state["facts"].keys()),
            ):
                return key
        return None

    @staticmethod
    def _matched_hold(state, node):
        for condition in node.get("completion_policy", {}).get(
            "hold_when",
            [],
        ):
            fact = state.get("facts", {}).get(condition.get("field"), {})
            actual = (
                fact.get("value") if fact.get("status") == "known" else None
            )
            expected = condition.get("value")
            if (
                condition.get("operator") == "equals"
                and type(actual) is type(expected)
                and actual == expected
            ):
                return condition
        return None

    def _predecessors(self, target):
        predecessors = []
        current = self.definition["entry_node"]
        while current != target:
            if current is None or current in predecessors:
                raise FlowError("invalid_forward_chain")
            predecessors.append(current)
            current = self.nodes[current].get("next_node")
        return predecessors

    def _validate_candidate(self, value):
        required = {
            "reply",
            "facts",
            "outcomes",
            "node_completed",
            "interaction",
            "actions",
        }
        if (
            not isinstance(value, dict)
            or not required.issubset(value)
            or set(value) - required - {"return_request"}
        ):
            raise FlowError("unexpected_candidate_fields")
        if "return_request" in value:
            request = value["return_request"]
            if (
                not isinstance(request, dict)
                or set(request) != {"target", "reason"}
                or not isinstance(request["target"], str)
                or not isinstance(request["reason"], str)
                or not request["reason"].strip()
            ):
                raise FlowError("invalid_return_request")
        if not isinstance(value["reply"], str) or not value["reply"].strip():
            raise FlowError("empty_reply")
        if type(value["node_completed"]) is not bool:
            raise FlowError("invalid_completion_flag")
        if not isinstance(value["facts"], dict) or not isinstance(
            value["outcomes"],
            dict,
        ):
            raise FlowError("invalid_updates")
        if not isinstance(value["actions"], list):
            raise FlowError("invalid_actions")
        interaction = value["interaction"]
        if not isinstance(interaction, dict) or interaction.get(
            "kind",
        ) not in {
            "none",
            "question",
            "choice",
            "authorization",
            "external_action",
        }:
            raise FlowError("invalid_interaction")
        if value["node_completed"] and interaction["kind"] != "none":
            raise FlowError("completion_has_pending_interaction")
        if interaction["kind"] == "choice":
            choices = interaction.get("choices")
            if (
                not isinstance(choices, list)
                or not choices
                or any(
                    not isinstance(item, dict)
                    or not isinstance(item.get("id"), str)
                    or not item["id"].strip()
                    or not isinstance(item.get("text"), str)
                    or not item["text"].strip()
                    for item in choices
                )
            ):
                raise FlowError("invalid_choices")
            ids = [item["id"] for item in choices]
            preferred = interaction.get("recommended")
            preferred = (
                preferred
                if isinstance(preferred, list)
                else []
                if preferred is None
                else [preferred]
            )
            if (
                len(set(ids)) != len(ids)
                or any(
                    not isinstance(item, str) or item not in ids
                    for item in preferred
                )
                or len(set(preferred)) != len(preferred)
            ):
                raise FlowError("invalid_choices")
        if any(
            field not in self.fields for field in interaction.get("fields", [])
        ):
            raise FlowError("unknown_question_field")

    @staticmethod
    def _validate_assessment(state, assessment, digest):
        if (
            not isinstance(assessment, dict)
            or assessment.get("candidate_digest") != digest
        ):
            raise FlowError("assessment_binding")
        if (
            type(assessment.get("context_revision")) is not int
            or assessment["context_revision"] != state["revision"]
            or assessment.get("context_node") != state["current_node"]
        ):
            raise FlowError("stale_assessment")
        if any(
            assessment.get(key) is not True
            for key in ("acceptable", "facts_valid", "reply_valid")
        ):
            raise FlowError("semantic_assessment")
        if not isinstance(assessment.get("dimensions"), dict):
            raise FlowError("invalid_assessment_dimensions")

    def _merge_facts(self, state, updates, customer_text):
        changed = set()
        for key, fact in updates.items():
            if key not in self.fields:
                raise FlowError(f"unconfigured_fact:{key}")
            if not isinstance(fact, dict) or set(fact) != {
                "value",
                "source",
                "status",
                "quote",
            }:
                raise FlowError("invalid_fact")
            if fact["status"] not in {"known", "unknown"}:
                raise FlowError("invalid_fact_status")
            policy = self.policies.get(key, {})
            if policy.get("scope_outcome"):
                scope = self._fact_scope(state, policy)
                if scope is None:
                    raise FlowError("fact_scope_missing")
                state.setdefault("fact_scopes", {})[key] = scope
            source = fact["source"]
            if source not in policy.get("sources", ["customer", "inferred"]):
                raise FlowError("fact_source_not_allowed")
            if source == "customer":
                quote = fact["quote"]
                if (
                    not isinstance(quote, str)
                    or not quote.strip()
                    or quote not in customer_text
                ):
                    raise FlowError("ungrounded_fact")
            if fact["status"] == "known" and not _nonempty(fact["value"]):
                raise FlowError("empty_known_fact")
            if fact["status"] == "known" and key in self.fact_schemas:
                self._validate_schema(
                    fact["value"],
                    self.fact_schemas[key],
                    f"fact_schema:{key}",
                )
            if fact["status"] == "unknown" and fact["value"] is not None:
                raise FlowError("unknown_fact_has_value")
            previous = state["facts"].get(key)
            if (
                previous
                and previous["source"] == "customer"
                and source != "customer"
            ):
                raise FlowError("confirmed_fact_overwrite")
            if previous != fact:
                if previous is not None and any(
                    previous.get(key) != fact.get(key)
                    for key in ("value", "source", "status")
                ):
                    changed.add(key)
                state["facts"][key] = deepcopy(fact)
        return changed

    @staticmethod
    def _minimum_basis_questions(node, facts):
        # UNKNOWN is usually enough, except where the definition explicitly
        # requires one identifiable factual anchor from a group. Ask only one
        # concrete field per unsatisfied group, not a new professional analysis.
        return list(
            dict.fromkeys(
                group[0]
                for group in node.get("minimum_known_groups", [])
                if group
                and not any(
                    facts.get(field, {}).get("status") == "known"
                    for field in group
                )
            ),
        )

    @staticmethod
    def _validate_schema(value, schema, label):
        error = next(Draft202012Validator(schema).iter_errors(value), None)
        if error is not None:
            # Do not include customer content in diagnostic errors.
            location = ".".join(str(item) for item in error.absolute_path)
            expected = (
                f":expected={error.validator_value}"
                if error.validator == "type"
                else ""
            )
            if error.validator == "required" and isinstance(value, dict):
                expected = ":required=" + ",".join(error.validator_value)
            raise FlowError(f"{label}:{location}:{error.validator}{expected}")

    def _validate_present_outcomes(self, node, outcomes):
        """Reject malformed supplied outcomes even on an incomplete turn.

        Omitted outcomes are legitimate partial progress. Once an outcome is
        supplied, however, its complete configured schema applies before any
        value can be persisted.
        """
        schemas = node.get("outcome_schemas", {})
        for key, value in outcomes.items():
            original = schemas.get(key)
            if original is None:
                continue
            schema = deepcopy(original)
            enrichment = schema.pop("host_enrichment", {})
            schema.setdefault("required", []).extend(
                enrichment.get("required", []),
            )
            schema.setdefault("properties", {}).update(
                enrichment.get("properties", {}),
            )
            self._validate_schema(value, schema, f"outcome_schema:{key}")

    def _check_completion(self, state, node, values, assessment, receipts):
        for key, original in node.get("outcome_schemas", {}).items():
            schema = deepcopy(original)
            enrichment = schema.pop("host_enrichment", {})
            schema.setdefault("required", []).extend(
                enrichment.get("required", []),
            )
            schema.setdefault("properties", {}).update(
                enrichment.get("properties", {}),
            )
            self._validate_schema(
                values.get(key),
                schema,
                f"outcome_schema:{key}",
            )
        policy = node.get("completion_policy", {})
        for path in policy.get("required_outcome_fields", []):
            if _at(values, path) is None:
                raise FlowError(f"required_outcome_missing:{path}")
        routes = [
            route
            for route in policy.get("routes", [])
            if route.get("operator") == "equals"
            and type(_at(values, route["when_field"])) is type(route["value"])
            and _at(values, route["when_field"]) == route["value"]
        ]
        if len(routes) > 1:
            raise FlowError("ambiguous_configured_route")
        route = routes[0] if routes else None
        if route and route["target"] not in node.get("return_nodes", []):
            raise FlowError("return_not_allowed")
        if route is None:
            for condition in policy.get("advance_requires", []):
                actual = _at(values, condition["field"])
                if (
                    condition.get("operator") != "equals"
                    or type(actual) is not type(condition["value"])
                    or actual != condition["value"]
                ):
                    raise FlowError(
                        f"advance_condition_missing:{condition['field']}",
                    )
        for key in node.get("collect_fields", []):
            fact = state["facts"].get(key)
            if not fact:
                raise FlowError(f"missing_fact:{key}")
            if fact["status"] == "unknown" and not self.policies.get(
                key,
                {},
            ).get("allow_unknown", True):
                raise FlowError(f"unknown_fact:{key}")
        for group in node.get("minimum_known_groups", []):
            if not any(
                state["facts"].get(key, {}).get("status") == "known"
                for key in group
            ):
                raise FlowError("minimum_known_group")
        for dimension in node.get("dimensions", []):
            if dimension.get("scope") == "presentation":
                continue
            key = dimension["id"]
            status = assessment["dimensions"].get(key)
            if (
                dimension.get("requires_result", True)
                and not _nonempty(values.get(key))
            ) or status not in (
                {"sufficient", "provisional"}
                if dimension.get("allow_provisional")
                else {"sufficient"}
            ):
                raise FlowError(f"dimension_insufficient:{key}")
        self._check_methods(state, node, receipts)
        bound = self._bound_receipts(state, node, receipts)
        requirements = list(node.get("required_receipts", []))
        for rule in policy.get("receipt_rules", []):
            if _at(values, rule["outcome_field"]) in rule["when_output_kinds"]:
                requirements.extend(rule["requires"])
        for needed in requirements:
            scopes = needed.get("scope", [])
            if (
                scopes
                and set(scopes) <= {"image", "video"}
                and _at(values, "production.output_kind") not in scopes
            ):
                continue
            if route and not route.get("rework") and scopes == ["whole_task"]:
                continue
            if not any(
                all(
                    receipt.get(key) == value
                    for key, value in needed.items()
                    if key != "scope"
                )
                and (not scopes or receipt.get("scope") in scopes)
                for receipt in bound
            ):
                raise FlowError("external_receipt_missing")
        return route

    @staticmethod
    def _bound_receipts(state, node, receipts):
        return [
            receipt
            for receipt in receipts
            if receipt.get("node_id") == node["id"]
            and receipt.get("revision") == state["revision"]
        ]

    def _check_methods(self, state, node, receipts):
        bound = self._bound_receipts(state, node, receipts)
        for method in node.get("required_methods", []):
            if not any(
                receipt.get("kind") == "method"
                and receipt.get("method") == method
                and receipt.get("skill") == node["main_skill"]
                for receipt in bound
            ):
                raise FlowError(f"method_missing:{method}")
