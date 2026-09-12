"""Request-local model tools for the existing super-expert AIGC protocol.

No business stages or expert identities belong here. All mutations still pass
through the platform dispatcher and its live grant validation.
"""
# Keep concrete annotations: AgentScope builds tool schemas in its own
# namespace and cannot resolve postponed Literal annotations from this module.

from contextlib import contextmanager
from copy import copy, deepcopy
import hashlib
import json
from typing import Any, Callable, Literal

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from qwenpaw.aigc.workflow_contract import WorkflowBlueprint


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


def _response(value: Any) -> ToolResponse:
    return ToolResponse(content=[TextBlock(
        type="text", text=json.dumps(value, ensure_ascii=False, allow_nan=False),
    )])


def _identity(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


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
        if not isinstance(node, dict) or node.get("provisioning") != "AUTO_PROVISIONABLE":
            continue
        kind = node.get("kind")
        if not isinstance(kind, str) or not kind:
            continue
        capabilities = set(node.get("capabilities") or [])
        preferred = _STANDALONE_EXAMPLE_CAPABILITIES.get(kind, ())
        model = next((
            item
            for capability in preferred
            for item in models
            if (isinstance(item, dict)
                and item.get("capability") == capability
                and capability in capabilities)
        ), None)
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
        workflow_node.update({
            "capability": model["capability"],
            "provider_id": model["provider_id"],
            "model_id": model["model_id"],
        })
        examples.append({
            "schema_version": 1,
            "title": f"{node.get('title') or kind}示例任务",
            "execution_preference": "CUSTOMER_TRIGGERED",
            "nodes": [workflow_node],
            "edges": [],
            "output_node_id": node_id,
            "review_node_ids": [node_id],
            "fallback_policy": "FAIL_CLOSED",
        })
    return examples


def _filter_catalog(catalog: Any, node_kinds: list[str]) -> dict[str, Any] | None:
    if hasattr(catalog, "model_dump"):
        catalog = catalog.model_dump(mode="python")
    if not isinstance(catalog, dict):
        return None
    projected = deepcopy(catalog)
    if not node_kinds:
        return projected
    requested = set(node_kinds)
    nodes = [
        node for node in projected.get("nodes") or []
        if isinstance(node, dict) and node.get("kind") in requested
    ]
    capabilities = {
        capability
        for node in nodes
        for capability in (node.get("capabilities") or [])
    }
    projected["nodes"] = nodes
    projected["available_models"] = [
        model for model in projected.get("available_models") or []
        if isinstance(model, dict) and model.get("capability") in capabilities
    ]
    return projected


def build_aigc_tools(
    *, grants: dict[str, str], installation_id: str, conversation_id: str,
    business_call: Callable | None, read_task: Callable | None,
    review_input: dict | None, media_delivery: dict,
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
        if (binding.get("installation_id") != installation_id
                or binding.get("conversation_id") != conversation_id
                or binding.get("material_task_id") != key):
            return None
        return deepcopy(task)

    async def dispatch(capability, arguments, recovery=None):
        if not authorized(capability):
            return _response({"error": "CAPABILITY_UNAVAILABLE"})
        try:
            return _response(await business_call(capability, arguments))
        except Exception:
            # Do not leak database paths, provider credentials, or raw errors.
            # No implicit retry: uncertain operations must retain their key.
            return _response({
                **(recovery or {}),
                "error": "PLATFORM_OPERATION_UNCONFIRMED",
                "guidance": "Check the same task before retrying; keep its task key and revision. Do not claim success.",
            })

    async def aigc_workflow_catalog(node_kinds: list[str] = []) -> ToolResponse:
        """Read current AIGC models, workflow node parameters and blueprint schema.

        Request only the node kinds needed for the current production plan. The
        response includes compact live models plus executable examples using
        real provider/model/capability tuples. An empty list returns all kinds.
        Model availability is not evidence that generation has completed.

        Args:
            node_kinds: Exact catalog node kinds needed, such as ["image_generate"].
        """
        if (not isinstance(node_kinds, list)
                or any(not isinstance(kind, str) or not kind.strip() for kind in node_kinds)):
            return _response({
                "error": "INVALID_CATALOG_REQUEST",
                "field": "node_kinds",
                "expected": "array of non-empty strings",
                "received": _json_type(node_kinds),
            })
        try:
            catalog = _filter_catalog(await business_call(CATALOG, {}), node_kinds)
            if catalog is None:
                return _response({"error": "CATALOG_UNAVAILABLE"})
            return _response({
                "workflow_examples": _workflow_examples(catalog) if node_kinds else [],
                "catalog": catalog,
                "workflow_schema": WorkflowBlueprint.model_json_schema(),
            })
        except Exception:
            return _response({"error": "CATALOG_UNAVAILABLE"})

    async def aigc_workflow_create(
        task_key: str, content_revision: int, workflow: dict,
    ) -> ToolResponse:
        """Create a real workflow canvas and material task using the live catalog.

        Creation is not media generation. The customer uses the task card to
        start/submit production. Reuse task_key and revision for a retry;
        revise content_revision for an intentionally changed production plan.
        Never generate installation, conversation, canvas or asset identities.

        Args:
            task_key: Stable logical name of this content task, retained across turns.
            content_revision: Positive version of the production plan.
            workflow: Complete blueprint matching aigc_workflow_catalog, with real dependencies and review_node_ids.
        """
        if (not isinstance(task_key, str) or not task_key.strip() or len(task_key) > 160
                or type(content_revision) is not int or content_revision < 1):
            return _response({"error": "INVALID_WORKFLOW_REQUEST"})
        if isinstance(workflow, str):
            try:
                workflow = json.loads(workflow)
            except (TypeError, ValueError):
                pass
        if not isinstance(workflow, dict):
            return _response({
                "error": "INVALID_WORKFLOW_REQUEST",
                "field": "workflow",
                "expected": "object",
                "received": _json_type(workflow),
                "retryable": True,
                "guidance": "Pass workflow as a nested JSON object, not a serialized JSON string.",
            })
        task_id = "content-" + _identity(installation_id, conversation_id, task_key)
        material_id = "material-" + _identity(task_id, content_revision)
        operation = "create-" + _identity(material_id)
        return await dispatch(CREATE, {
            "idempotency_key": operation, "event_id": operation,
            "scope": {"installation_id": installation_id,
                      "conversation_id": conversation_id,
                      "agent_task_id": task_id, "content_revision": content_revision,
                      "material_task_id": material_id},
            "workflow": deepcopy(workflow),
        }, recovery={"material_task_id": material_id})

    async def aigc_task_status(material_task_id: str = "") -> ToolResponse:
        """Read an existing material task in this conversation, including asset/review state.

        Task metadata is not evidence of seeing or hearing its media. A task
        ID from another installation or conversation cannot be accessed.
        Omit the ID to resolve the current host-submitted review task.
        """
        if not material_task_id:
            material_task_id = (review_input or {}).get("binding", {}).get("material_task_id", "")
        task = owned_task(material_task_id)
        if task is None:
            return _response({"error": "TASK_UNAVAILABLE"})
        return _response({"task": task})

    async def aigc_task_resume(material_task_id: str, operation_key: str) -> ToolResponse:
        """Resume a bound task after the customer's request to continue.

        This updates the existing task state; it does not bypass the canvas
        generation controls. Retain operation_key on retries of this action.
        """
        task = owned_task(material_task_id)
        if task is None:
            return _response({"error": "TASK_UNAVAILABLE"})
        if not isinstance(operation_key, str) or not operation_key.strip() or len(operation_key) > 160:
            return _response({"error": "INVALID_OPERATION_KEY"})
        key = "resume-" + _identity(installation_id, conversation_id, material_task_id, operation_key)
        return await dispatch(RESUME, {
            "idempotency_key": key, "event_id": key, "binding": task["binding"],
        })

    async def aigc_task_review(
        material_task_id: str, decision: Literal["ACCEPTED", "REVISION_REQUIRED"],
        assessment: str,
    ) -> ToolResponse:
        """Record review of the current host-submitted asset set after observing it.

        ACCEPTED requires native media delivery for every submitted modality;
        text or URLs claiming media was inspected are insufficient. A single
        material task acceptance is not approval of all business content.
        """
        task = owned_task(material_task_id)
        if task is None:
            return _response({"error": "TASK_UNAVAILABLE"})
        if (decision not in {"ACCEPTED", "REVISION_REQUIRED"}
                or not isinstance(assessment, str) or not assessment.strip()):
            return _response({"error": "INVALID_REVIEW"})
        if (not review_input or review_input.get("binding") != task["binding"]
                or review_input.get("asset_id") != task.get("asset_id")
                or (review_input.get("review_assets") or []) != (task.get("review_assets") or [])
                or not task.get("asset_id")
                or task.get("status") not in {"SUBMITTED", "REVIEWING"}):
            return _response({"error": "REVIEW_INPUT_UNAVAILABLE"})
        if decision == "ACCEPTED":
            blocks = review_input.get("review_blocks") or [{
                "type": review_input.get("media_kind"),
                "digest": review_input.get("block_digest"),
            }]
            delivered = set(media_delivery.get("delivered_modalities", []))
            identities = {item["block_digest"] for item in media_delivery.get("media_inputs", [])}
            if any(block.get("type") != "text" and (
                block.get("type") not in delivered or block.get("digest") not in identities
            ) for block in blocks):
                return _response({"error": "MEDIA_NOT_DELIVERED"})
        key = "review-" + _identity(installation_id, conversation_id, material_task_id,
                                   task.get("asset_id"), task.get("review_assets"), decision)
        return await dispatch(REVIEW, {
            "idempotency_key": key, "event_id": key, "binding": task["binding"],
            "asset_id": task["asset_id"], "decision": decision,
            "payload": {"assessment": assessment, "assessment_bound": True},
        })

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
        if authorized(REVIEW) and authorized("aigc.task.create"):
            tools["aigc_task_review"] = aigc_task_review
    return tools


@contextmanager
def bind_aigc_tools(agent: Any, tools: dict[str, Callable]):
    """Temporarily extend a request-owned Agent; never mutate its base toolkit."""
    if not tools:
        yield
        return
    original = agent.toolkit
    scoped = copy(original)
    scoped.tools = dict(original.tools)
    for tool in tools.values():
        scoped.register_tool_function(tool, namesake_strategy="raise")
    agent.toolkit = scoped
    try:
        yield
    finally:
        agent.toolkit = original


@contextmanager
def track_media_delivery(agent: Any, messages: list, delivery: dict):
    """Observe successful native model transport without another model call."""
    from .media_delivery import (
        media_input_manifest, media_input_identities, build_media_delivery,
    )
    manifest = media_input_manifest(messages)
    if not manifest:
        yield
        return
    identities = media_input_identities(messages)
    original = agent.model

    class TrackedModel:
        def __getattr__(self, key):
            return getattr(original, key)

        async def __call__(self, *args, **kwargs):
            delivery.clear()
            prompt = kwargs.get("messages", args[0] if args else None)
            # Snapshot before the model/provider can mutate its input.
            evidence = build_media_delivery(manifest, prompt, "", input_identities=identities)
            response = await original(*args, **kwargs)
            if hasattr(response, "__aiter__"):
                async def stream():
                    last = None
                    async for chunk in response:
                        last = chunk
                        yield chunk
                    if last is not None:
                        evidence["model_response_id"] = str(getattr(last, "id", ""))[:200]
                        delivery.clear()
                        delivery.update(evidence)
                return stream()
            evidence["model_response_id"] = str(getattr(response, "id", ""))[:200]
            delivery.clear()
            delivery.update(evidence)
            return response

    agent.model = TrackedModel()
    try:
        yield
    finally:
        agent.model = original
