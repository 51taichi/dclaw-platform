"""Request-local model tools for the existing super-expert AIGC protocol.

No business stages or expert identities belong here. All mutations still pass
through the platform dispatcher and its live grant validation.
"""
# Keep concrete annotations: AgentScope builds tool schemas in its own
# namespace and cannot resolve postponed Literal annotations from this module.

from contextlib import contextmanager
from copy import copy, deepcopy
import hashlib
import inspect
import json
import re
from typing import Any, Callable, Literal

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from qwenpaw.aigc.workflow_contract import (
    WorkflowBlueprint,
    workflow_node_registry,
)
from .service import SuperExpertPlatformError


CATALOG = "aigc.workflow.capabilities.list/1"
CREATE = "aigc.workflow.create/1"
RESUME = "aigc.task.resume"
REVIEW = "aigc.review.complete"

_STANDALONE_EXAMPLE_CAPABILITIES = {
    "prompt": ("storyboard",),
    "script_generate": ("storyboard",),
    "image_generate": ("text_to_image",),
    "video_generate": ("text_to_video",),
}

_PLATFORM_ERROR_GUIDANCE = {
    "AIGC_SERVICE_UNAVAILABLE": (
        "The AIGC service is temporarily unavailable. Retry the same task key "
        "and content revision later."
    ),
    "CAPABILITY_NOT_AUTHORIZED": (
        "Refresh the expert installation grants before retrying this capability."
    ),
    "CAPABILITY_NOT_SUPPORTED": (
        "Use a capability declared by the current platform contract."
    ),
    "ASSET_UNAVAILABLE": (
        "Use an asset ID returned by the current user's asset flow, or add a "
        "catalog-supported upload/select node before retrying."
    ),
    "EDGE_INCOMPATIBLE": (
        "Refresh the catalog and connect nodes only through a listed compatible "
        "input slot."
    ),
    "IDEMPOTENCY_CONFLICT": (
        "Reuse a content revision only for an identical workflow; increment "
        "content_revision when the production plan changes."
    ),
    "MODEL_UNAVAILABLE": (
        "Refresh the catalog and copy provider_id, model_id and capability from "
        "one compatible available model entry."
    ),
    "NODE_KIND_UNAVAILABLE": (
        "Refresh the catalog and use a currently available node kind."
    ),
    "NODE_KIND_UNSUPPORTED": (
        "Use a catalog-supported node kind or follow the returned manual fallback "
        "policy."
    ),
    "OUTPUT_NODE_INVALID": (
        "Choose an output-producing terminal node listed in the workflow."
    ),
    "PARAMETER_INVALID": (
        "Refresh the catalog and correct node parameters to match its current "
        "parameter schema."
    ),
    "PROVISIONING_FAILED": (
        "Retry the same task key and content revision; do not change the workflow "
        "unless the production plan changes."
    ),
    "TASK_STATE_INVALID": (
        "Read the current task status and choose an action allowed from that state."
    ),
    "WORKFLOW_CYCLE": "Remove cyclic dependencies from the workflow edges.",
    "WORKFLOW_SCHEMA_INVALID": (
        "Correct the workflow to match the current workflow schema and retry with "
        "the same task key and content revision."
    ),
}
_PLATFORM_ERROR_ALIASES = {
    "AIGC service is unavailable": "AIGC_SERVICE_UNAVAILABLE",
    "capability is not authorized": "CAPABILITY_NOT_AUTHORIZED",
    "capability is not supported": "CAPABILITY_NOT_SUPPORTED",
    "event id is required": "EVENT_ID_REQUIRED",
    "illegal task transition": "TASK_STATE_INVALID",
    "illegal task transition from terminal state": "TASK_STATE_INVALID",
    "task transition requires an existing task": "TASK_UNAVAILABLE",
}
_STABLE_PLATFORM_ERROR = re.compile(r"^[A-Z][A-Z0-9_]{2,80}$")


def _response(value: Any) -> ToolResponse:
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(value, ensure_ascii=False, allow_nan=False),
            ),
        ],
    )


def _identity(*parts: Any) -> str:
    return hashlib.sha256(
        json.dumps(parts, ensure_ascii=False).encode(),
    ).hexdigest()


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return type(value).__name__


def _inline_schema_refs(value: Any, definitions: dict[str, Any]) -> Any:
    """Inline local Pydantic references for provider-compatible tool schemas."""
    if isinstance(value, list):
        return [_inline_schema_refs(item, definitions) for item in value]
    if not isinstance(value, dict):
        return value
    reference = value.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/$defs/"):
        name = reference.removeprefix("#/$defs/")
        target = deepcopy(definitions[name])
        target.update(
            {key: item for key, item in value.items() if key != "$ref"},
        )
        return _inline_schema_refs(target, definitions)
    result = {
        key: _inline_schema_refs(item, definitions)
        for key, item in value.items()
        if key not in {"$defs", "const"}
    }
    if "const" in value:
        constant = _inline_schema_refs(value["const"], definitions)
        if isinstance(constant, str):
            result["enum"] = [constant]
        else:
            result["default"] = constant
            requirement = (
                f"Must equal {json.dumps(constant, ensure_ascii=False)}."
            )
            description = str(result.get("description") or "").strip()
            result["description"] = f"{description} {requirement}".strip()
    return result


def _workflow_tool_schema(tool: Callable) -> dict[str, Any]:
    workflow_schema = WorkflowBlueprint.model_json_schema()
    definitions = workflow_schema.get("$defs", {})
    workflow_schema = _inline_schema_refs(workflow_schema, definitions)
    return {
        "type": "function",
        "function": {
            "name": tool.__name__,
            "description": inspect.getdoc(tool) or "",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_key": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 160,
                        "description": "Stable logical task name retained across retries.",
                    },
                    "content_revision": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "Increment only when the production plan changes.",
                    },
                    "workflow": workflow_schema,
                },
                "required": ["task_key", "content_revision", "workflow"],
                "additionalProperties": False,
            },
        },
    }


def _validation_issue(error: dict[str, Any]) -> dict[str, str]:
    field = ".".join(
        ("workflow", *(str(part) for part in error.get("loc", ()))),
    )
    error_type = str(error.get("type") or "")
    if error_type == "missing":
        code = "FIELD_REQUIRED"
    elif error_type == "extra_forbidden":
        code = "FIELD_NOT_ALLOWED"
    else:
        code = "INVALID_VALUE"
    return {"field": field, "code": code}


def _model_binding_issues(workflow: dict[str, Any]) -> list[dict[str, str]]:
    issues = []
    registry = workflow_node_registry()
    nodes = workflow.get("nodes")
    if not isinstance(nodes, (list, tuple)):
        return issues
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        registration = registry.get(node.get("kind"))
        if (
            registration is None
            or not registration.requires_model
            or node.get("customer_action") != "CLICK_GENERATE"
        ):
            continue
        for field in ("capability", "provider_id", "model_id"):
            if not isinstance(node.get(field), str) or not node[field].strip():
                issues.append(
                    {
                        "field": f"workflow.nodes.{index}.{field}",
                        "code": "FIELD_REQUIRED",
                    },
                )
    return issues


def _registered_node_schema_issues(
    workflow: dict[str, Any],
) -> list[dict[str, str]]:
    issues = []
    registry = workflow_node_registry()
    nodes = workflow.get("nodes")
    if not isinstance(nodes, (list, tuple)):
        return issues
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        registration = registry.get(node.get("kind"))
        if registration is None:
            continue
        for field, schema in (
            ("inputs", registration.input_schema),
            ("parameters", registration.parameter_schema),
        ):
            value = node.get(field)
            if not isinstance(value, dict):
                continue
            errors = Draft202012Validator(schema).iter_errors(value)
            for error in errors:
                path = ".".join(str(part) for part in error.absolute_path)
                target = f"workflow.nodes.{index}.{field}"
                if path:
                    target = f"{target}.{path}"
                if error.validator == "required":
                    code = "FIELD_REQUIRED"
                elif error.validator == "additionalProperties":
                    code = "FIELD_NOT_ALLOWED"
                else:
                    code = "INVALID_VALUE"
                issues.append({"field": target, "code": code})
    return sorted(issues, key=lambda issue: (issue["field"], issue["code"]))


def _invalid_workflow_response(
    *,
    workflow: dict[str, Any],
    validation_error: ValidationError | None = None,
) -> ToolResponse:
    issues = (
        [
            _validation_issue(error)
            for error in validation_error.errors(include_url=False)
        ]
        if validation_error is not None
        else []
    )
    issues.extend(_model_binding_issues(workflow))
    issues.extend(_registered_node_schema_issues(workflow))
    return _response(
        {
            "error": "INVALID_WORKFLOW_REQUEST",
            "retryable": True,
            "issues": issues,
            "guidance": (
                "Correct the listed fields using the latest catalog example, then "
                "retry with the same task key and content revision."
            ),
        },
    )


def _invalid_create_request_response(
    issues: list[dict[str, str]],
) -> ToolResponse:
    return _response(
        {
            "error": "INVALID_WORKFLOW_REQUEST",
            "retryable": True,
            "issues": issues,
            "guidance": (
                "Correct the listed request fields, then retry with the same task "
                "key and content revision."
            ),
        },
    )


def _platform_rejection_response(
    exc: SuperExpertPlatformError,
) -> ToolResponse | None:
    message = str(exc)
    code = _PLATFORM_ERROR_ALIASES.get(message)
    if code is None and _STABLE_PLATFORM_ERROR.fullmatch(message):
        code = message
    if code is None:
        return None
    guidance = _PLATFORM_ERROR_GUIDANCE.get(
        code,
        "Correct the request using the latest capability catalog before retrying.",
    )
    return _response({"error": code, "retryable": True, "guidance": guidance})


def _default_parameters(node: dict[str, Any]) -> dict[str, Any]:
    properties = (node.get("parameter_schema") or {}).get("properties") or {}
    return {
        key: deepcopy(schema["default"])
        for key, schema in properties.items()
        if isinstance(schema, dict) and "default" in schema
    }


def _example_inputs(node: dict[str, Any]) -> dict[str, Any]:
    keys = set(node.get("input_keys") or [])
    if "prompt" in keys:
        return {"prompt": "根据当前任务生成清晰、完整且可审核的内容。"}
    if "text" in keys:
        return {"text": "请将当前业务目标整理为可直接制作的内容。"}
    return {}


def _workflow_examples(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    models = catalog.get("available_models") or []
    examples = []
    for node in catalog.get("nodes") or []:
        if (
            not isinstance(node, dict)
            or node.get("provisioning") != "AUTO_PROVISIONABLE"
        ):
            continue
        kind = node.get("kind")
        if not isinstance(kind, str) or not kind:
            continue
        capabilities = set(node.get("capabilities") or [])
        preferred = _STANDALONE_EXAMPLE_CAPABILITIES.get(kind, ())
        model = next(
            (
                item
                for capability in preferred
                for item in models
                if (
                    isinstance(item, dict)
                    and item.get("capability") == capability
                    and capability in capabilities
                )
            ),
            None,
        )
        if model is None:
            continue
        node_id = f"{kind}_1"
        workflow_node = {
            "node_id": node_id,
            "kind": kind,
            "title": node.get("title") or kind,
            "inputs": _example_inputs(node),
            "parameters": _default_parameters(node),
            "customer_action": (node.get("customer_actions") or ["NONE"])[0],
            "optional": False,
        }
        workflow_node.update(
            {
                "capability": model["capability"],
                "provider_id": model["provider_id"],
                "model_id": model["model_id"],
            },
        )
        examples.append(
            {
                "schema_version": 1,
                "title": f"{node.get('title') or kind}示例任务",
                "execution_preference": "CUSTOMER_TRIGGERED",
                "nodes": [workflow_node],
                "edges": [],
                "output_node_id": node_id,
                "review_node_ids": [node_id],
                "fallback_policy": "FAIL_CLOSED",
            },
        )
    return examples


def _filter_catalog(
    catalog: Any,
    node_kinds: list[str],
) -> dict[str, Any] | None:
    if hasattr(catalog, "model_dump"):
        catalog = catalog.model_dump(mode="python")
    if not isinstance(catalog, dict):
        return None
    projected = deepcopy(catalog)
    if not node_kinds:
        return projected
    requested = set(node_kinds)
    nodes = [
        node
        for node in projected.get("nodes") or []
        if isinstance(node, dict) and node.get("kind") in requested
    ]
    capabilities = {
        capability
        for node in nodes
        for capability in (node.get("capabilities") or [])
    }
    projected["nodes"] = nodes
    projected["available_models"] = [
        model
        for model in projected.get("available_models") or []
        if isinstance(model, dict) and model.get("capability") in capabilities
    ]
    return projected


def build_aigc_tools(
    *,
    grants: dict[str, str],
    installation_id: str,
    conversation_id: str,
    business_call: Callable | None,
    read_task: Callable | None,
    review_input: dict | None,
    media_delivery: dict,
) -> dict[str, Callable]:
    """Called only after workspace release authorization, never from user JSON."""
    if business_call is None:
        return {}
    grants = dict(grants)
    review_input = deepcopy(review_input)

    def authorized(capability):
        return grants.get(capability) == "1"

    def owned_task(key):
        task = read_task(key) if read_task else None
        binding = task.get("binding", {}) if isinstance(task, dict) else {}
        trusted_review_binding = (
            review_input.get("binding")
            if isinstance(review_input, dict)
            else None
        )
        installation_matches = (
            binding.get("installation_id") == installation_id
            or binding == trusted_review_binding
        )
        if (
            not installation_matches
            or binding.get("conversation_id") != conversation_id
            or binding.get("material_task_id") != key
        ):
            return None
        return deepcopy(task)

    async def dispatch(capability, arguments, recovery=None):
        if not authorized(capability):
            return _response({"error": "CAPABILITY_UNAVAILABLE"})
        try:
            return _response(await business_call(capability, arguments))
        except SuperExpertPlatformError as exc:
            rejection = _platform_rejection_response(exc)
            if rejection is not None:
                return rejection
        except Exception:
            pass
        # Do not leak database paths, provider credentials, or raw errors.
        # No implicit retry: uncertain operations must retain their key.
        return _response(
            {
                **(recovery or {}),
                "error": "PLATFORM_OPERATION_UNCONFIRMED",
                "guidance": "Check the same task before retrying; keep its task key and revision. Do not claim success.",
            },
        )

    async def aigc_workflow_catalog(
        node_kinds: list[str] = [],
    ) -> ToolResponse:
        """Read current AIGC models, workflow node parameters and blueprint schema.

        Request only the node kinds needed for the current production plan. The
        response includes compact live models plus executable examples using
        real provider/model/capability tuples. An empty list returns all kinds.
        Model availability is not evidence that generation has completed.

        Args:
            node_kinds: Exact catalog node kinds needed, such as ["image_generate"].
        """
        if not isinstance(node_kinds, list) or any(
            not isinstance(kind, str) or not kind.strip()
            for kind in node_kinds
        ):
            return _response(
                {
                    "error": "INVALID_CATALOG_REQUEST",
                    "field": "node_kinds",
                    "expected": "array of non-empty strings",
                    "received": _json_type(node_kinds),
                },
            )
        try:
            catalog = _filter_catalog(
                await business_call(CATALOG, {}),
                node_kinds,
            )
            if catalog is None:
                return _response({"error": "CATALOG_UNAVAILABLE"})
            return _response(
                {
                    "workflow_examples": _workflow_examples(catalog)
                    if node_kinds
                    else [],
                    "catalog": catalog,
                    "workflow_schema": WorkflowBlueprint.model_json_schema(),
                },
            )
        except SuperExpertPlatformError as exc:
            rejection = _platform_rejection_response(exc)
            if rejection is not None:
                return rejection
            return _response({"error": "CATALOG_UNAVAILABLE"})
        except Exception:
            return _response({"error": "CATALOG_UNAVAILABLE"})

    async def aigc_workflow_create(
        task_key: Any = None,
        content_revision: Any = None,
        workflow: Any = None,
        **unexpected: Any,
    ) -> ToolResponse:
        """Create a real workflow canvas and material task using the live catalog.

        Creation is not media generation. The customer uses the task card to
        start/submit production. Reuse task_key and revision for a retry;
        revise content_revision for an intentionally changed production plan.
        Never generate installation, conversation, canvas or asset identities.

        Args:
            task_key: Stable logical name of this content task, retained across turns.
            content_revision: Positive version of the production plan.
            workflow: Complete blueprint matching aigc_workflow_catalog, with real dependencies. The legacy review_node_ids field only identifies output ownership and does not request Agent review.
        """
        request_issues = []
        if task_key is None:
            request_issues.append(
                {"field": "task_key", "code": "FIELD_REQUIRED"},
            )
        elif (
            not isinstance(task_key, str)
            or not task_key.strip()
            or len(task_key) > 160
        ):
            request_issues.append(
                {"field": "task_key", "code": "INVALID_VALUE"},
            )
        if content_revision is None:
            request_issues.append(
                {
                    "field": "content_revision",
                    "code": "FIELD_REQUIRED",
                },
            )
        elif type(content_revision) is not int or content_revision < 1:
            request_issues.append(
                {
                    "field": "content_revision",
                    "code": "INVALID_VALUE",
                },
            )
        if workflow is None:
            request_issues.append(
                {"field": "workflow", "code": "FIELD_REQUIRED"},
            )
        request_issues.extend(
            {"field": field, "code": "FIELD_NOT_ALLOWED"}
            for field in sorted(unexpected)
        )
        if request_issues:
            return _invalid_create_request_response(request_issues)
        if isinstance(workflow, str):
            try:
                workflow = json.loads(workflow)
            except (TypeError, ValueError):
                pass
        if not isinstance(workflow, dict):
            return _response(
                {
                    "error": "INVALID_WORKFLOW_REQUEST",
                    "field": "workflow",
                    "expected": "object",
                    "received": _json_type(workflow),
                    "retryable": True,
                    "guidance": "Pass workflow as a nested JSON object, not a serialized JSON string.",
                },
            )
        raw_workflow = workflow
        try:
            workflow = WorkflowBlueprint.model_validate(
                raw_workflow,
            ).model_dump(mode="json")
        except ValidationError as exc:
            return _invalid_workflow_response(
                workflow=raw_workflow,
                validation_error=exc,
            )
        if _model_binding_issues(workflow) or _registered_node_schema_issues(
            workflow,
        ):
            return _invalid_workflow_response(workflow=workflow)
        task_id = "content-" + _identity(
            installation_id,
            conversation_id,
            task_key,
        )
        material_id = "material-" + _identity(task_id, content_revision)
        operation = "create-" + _identity(material_id)
        return await dispatch(
            CREATE,
            {
                "idempotency_key": operation,
                "event_id": operation,
                "scope": {
                    "installation_id": installation_id,
                    "conversation_id": conversation_id,
                    "agent_task_id": task_id,
                    "content_revision": content_revision,
                    "material_task_id": material_id,
                },
                "workflow": deepcopy(workflow),
            },
            recovery={"material_task_id": material_id},
        )

    async def aigc_task_status(material_task_id: str = "") -> ToolResponse:
        """Read an existing material task in this conversation, including asset/review state.

        Task metadata is not evidence of seeing or hearing its media. A task
        ID from another installation or conversation cannot be accessed.
        Omit the ID to resolve the current host-submitted review task.
        """
        if not material_task_id:
            material_task_id = (
                (review_input or {})
                .get("binding", {})
                .get("material_task_id", "")
            )
        task = owned_task(material_task_id)
        if task is None:
            return _response({"error": "TASK_UNAVAILABLE"})
        return _response({"task": task})

    async def aigc_task_resume(
        material_task_id: str,
        operation_key: str,
    ) -> ToolResponse:
        """Resume a bound task after the customer's request to continue.

        This updates the existing task state; it does not bypass the canvas
        generation controls. Retain operation_key on retries of this action.
        """
        task = owned_task(material_task_id)
        if task is None:
            return _response({"error": "TASK_UNAVAILABLE"})
        if (
            not isinstance(operation_key, str)
            or not operation_key.strip()
            or len(operation_key) > 160
        ):
            return _response({"error": "INVALID_OPERATION_KEY"})
        key = "resume-" + _identity(
            installation_id,
            conversation_id,
            material_task_id,
            operation_key,
        )
        return await dispatch(
            RESUME,
            {
                "idempotency_key": key,
                "event_id": key,
                "binding": task["binding"],
            },
        )

    async def aigc_task_review(
        material_task_id: str,
        decision: Literal["ACCEPTED", "REVISION_REQUIRED"],
        assessment: str,
    ) -> ToolResponse:
        """Read customer completion state for a legacy signed Agent.

        This compatibility tool never reviews media and never writes a task
        decision. The decision and assessment arguments are accepted only so
        previously signed Agent instructions remain executable.
        """
        _ = decision, assessment
        task = owned_task(material_task_id)
        if task is None:
            return _response({"error": "TASK_UNAVAILABLE"})
        binding = task.get("binding")
        if (
            not isinstance(binding, dict)
            or binding.get("installation_id") != installation_id
            or binding.get("conversation_id") != conversation_id
            or binding.get("material_task_id") != material_task_id
        ):
            return _response({"error": "TASK_UNAVAILABLE"})
        accepted = task.get("status") == "ACCEPTED"
        return _response(
            {
                "status": "retired",
                "write_applied": False,
                "customer_action_required": not accepted,
                "task": task,
                "guidance": (
                    "Customer completion is already persisted; continue the conversation."
                    if accepted
                    else "Ask the customer to complete the material task in the task page."
                ),
            },
        )

    tools = {}
    if authorized(CATALOG):
        tools["aigc_workflow_catalog"] = aigc_workflow_catalog
    if authorized(CREATE) and authorized(CATALOG):
        tools["aigc_workflow_create"] = aigc_workflow_create
    if read_task is not None:
        if authorized(CREATE) or authorized(RESUME) or authorized(REVIEW):
            tools["aigc_task_status"] = aigc_task_status
        if authorized(RESUME) and authorized("aigc.task.create"):
            tools["aigc_task_resume"] = aigc_task_resume
        if authorized(REVIEW):
            tools["aigc_task_review"] = aigc_task_review
    return tools


@contextmanager
def bind_aigc_tools(
    agent: Any,
    tools: dict[str, Callable],
    *,
    base_tool_names: set[str] | None = None,
    added_tool_names: set[str] | None = None,
):
    """Temporarily extend a request-owned Agent; never mutate its base toolkit."""
    if not tools and base_tool_names is None:
        yield
        return
    original = agent.toolkit
    scoped = copy(original)
    scoped.tools = {
        name: tool
        for name, tool in original.tools.items()
        if base_tool_names is None or name in base_tool_names
    }
    selected_tools = (
        tools.values()
        if added_tool_names is None
        else (tool for name, tool in tools.items() if name in added_tool_names)
    )
    for tool in selected_tools:
        schema = (
            _workflow_tool_schema(tool)
            if tool.__name__ == "aigc_workflow_create"
            else None
        )
        scoped.register_tool_function(
            tool,
            json_schema=schema,
            namesake_strategy="raise",
        )
    agent.toolkit = scoped
    try:
        yield
    finally:
        agent.toolkit = original


@contextmanager
def track_media_delivery(agent: Any, messages: list, delivery: dict):
    """Observe successful native model transport without another model call."""
    from .media_delivery import (
        media_input_manifest,
        media_input_identities,
        build_media_delivery,
    )

    manifest = media_input_manifest(messages)
    if not manifest:
        yield
        return
    identities = media_input_identities(messages)
    original = agent.model
    delivery.clear()

    def record(evidence: dict[str, Any]) -> None:
        """Keep proof from any successful model call in this review turn."""
        if not delivery:
            delivery.update(evidence)
            return
        delivered = set(delivery.get("delivered_modalities", []))
        delivered.update(evidence.get("delivered_modalities", []))
        delivery.update(evidence)
        delivery["delivered_modalities"] = sorted(delivered)
        kinds = {item["kind"] for item in manifest}
        delivery["unavailable_modalities"] = sorted(kinds - delivered)

    class TrackedModel:
        def __getattr__(self, key):
            return getattr(original, key)

        async def __call__(self, *args, **kwargs):
            prompt = kwargs.get("messages", args[0] if args else None)
            # Snapshot before the model/provider can mutate its input.
            evidence = build_media_delivery(
                manifest,
                prompt,
                "",
                input_identities=identities,
            )
            response = await original(*args, **kwargs)
            if hasattr(response, "__aiter__"):

                async def stream():
                    last = None
                    async for chunk in response:
                        last = chunk
                        yield chunk
                    if last is not None:
                        evidence["model_response_id"] = str(
                            getattr(last, "id", ""),
                        )[:200]
                        record(evidence)

                return stream()
            evidence["model_response_id"] = str(getattr(response, "id", ""))[
                :200
            ]
            record(evidence)
            return response

    agent.model = TrackedModel()
    try:
        yield
    finally:
        agent.model = original
