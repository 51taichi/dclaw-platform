"""Compile semantic super-expert workflows into DClaw-owned canvas specs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .workflow_contract import (
    NodeRegistration,
    WorkflowBlueprint,
    WorkflowNode,
    validate_workflow_blueprint,
    workflow_node_registry,
)


class WorkflowCompileError(ValueError):
    """A stable, public-safe workflow compilation failure."""

    def __init__(
        self,
        code: str,
        *,
        manual_fallback_allowed: bool = False,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.manual_fallback_allowed = manual_fallback_allowed


@dataclass(frozen=True)
class AvailableWorkflowModel:
    provider_id: str
    model_id: str
    capabilities: frozenset[str]


class CompiledCanvasNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    logical_node_id: str
    physical_node_id: str
    kind: str
    position: dict[str, float]
    data: dict[str, Any]


class CompiledCanvasEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    edge_id: str
    source: str
    target: str
    target_slot: str


class WorkflowGuideStepDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str
    kind: Literal["INSPECT", "GENERATE", "SUBMIT", "MANUAL_BUILD"]
    title: str
    instruction: str
    logical_node_id: str
    node_id: str
    control_id: str | None
    optional: bool
    completion_rule: Literal[
        "PRESENT",
        "JOB_SUCCEEDED_WITH_OUTPUT",
        "OUTPUT_AVAILABLE",
    ]
    # Optional defaults keep persisted v1 workflow documents readable while
    # new compilations bind guide completion to the exact executable contract.
    expected_output_type: str | None = None
    expected_capability: str | None = None
    expected_provider_id: str | None = None
    expected_model_id: str | None = None
    manual_action: Literal["ADD_NODE", "CONNECT_EDGE"] | None = None
    node_kind: str | None = None
    source_node_id: str | None = None
    target_node_id: str | None = None
    target_slot: str | None = None
    manual_node_data: dict[str, Any] | None = None


class CompiledWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_id: str
    title: str
    nodes: tuple[CompiledCanvasNode, ...]
    edges: tuple[CompiledCanvasEdge, ...]
    bindings: dict[str, str]
    output_node_id: str
    guide_steps: tuple[WorkflowGuideStepDefinition, ...]
    viewport: dict[str, float]


_PHYSICAL_PREFIX = {
    "prompt": "prompt",
    "image_generate": "image",
    "video_generate": "video",
    "audio_generate": "audio",
    "script_generate": "script",
    "long_image_export": "long-image",
    "reference_note": "reference-note",
    "reference_asset": "reference-asset",
    "output": "output",
}


def _raise(code: str, *, manual: bool = False) -> None:
    raise WorkflowCompileError(code, manual_fallback_allowed=manual)


def _validate_scalar_parameters(node: WorkflowNode) -> None:
    parameters = node.parameters
    if "duration_seconds" in parameters:
        value = parameters["duration_seconds"]
        if type(value) is not int or not 1 <= value <= 60:
            _raise("PARAMETER_INVALID")
    if "count" in parameters:
        value = parameters["count"]
        if type(value) is not int or not 1 <= value <= 8:
            _raise("PARAMETER_INVALID")
    if "shot_count" in parameters:
        value = parameters["shot_count"]
        if type(value) is not int or not 1 <= value <= 100:
            _raise("PARAMETER_INVALID")
    if "generate_audio" in parameters and type(parameters["generate_audio"]) is not bool:
        _raise("PARAMETER_INVALID")
    if "aspect_ratio" in parameters and parameters["aspect_ratio"] not in {
        "1:1",
        "16:9",
        "9:16",
        "4:3",
        "3:4",
        "21:9",
    }:
        _raise("PARAMETER_INVALID")
    if "resolution" in parameters and parameters["resolution"] not in {
        "480P",
        "720P",
        "1080P",
        "1K",
        "2K",
        "4K",
    }:
        _raise("PARAMETER_INVALID")
    for key, value in parameters.items():
        if key in {
            "aspect_ratio",
            "resolution",
            "image_mode",
            "video_mode",
            "voice",
            "language",
            "script_mode",
            "system_prompt",
        } and not isinstance(value, str):
            _raise("PARAMETER_INVALID")


def _validate_inputs(node: WorkflowNode) -> None:
    for key, value in node.inputs.items():
        if key == "reference_asset_ids":
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item for item in value
            ):
                _raise("WORKFLOW_SCHEMA_INVALID")
        elif not isinstance(value, str) or not value.strip():
            _raise("WORKFLOW_SCHEMA_INVALID")


def _validate_model(
    node: WorkflowNode,
    registration: NodeRegistration,
    available_models: Collection[AvailableWorkflowModel],
) -> None:
    if not registration.requires_model or node.customer_action != "CLICK_GENERATE":
        return
    if not node.provider_id or not node.model_id or not node.capability:
        _raise("MODEL_UNAVAILABLE")
    if not any(
        model.provider_id == node.provider_id
        and model.model_id == node.model_id
        and node.capability in model.capabilities
        for model in available_models
    ):
        _raise("MODEL_UNAVAILABLE")


def _topological_order(
    blueprint: WorkflowBlueprint,
    registrations: Mapping[str, NodeRegistration],
) -> tuple[list[str], dict[str, int]]:
    by_id = {node.node_id: node for node in blueprint.nodes}
    original_order = {node.node_id: index for index, node in enumerate(blueprint.nodes)}
    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming_count = {node_id: 0 for node_id in by_id}
    seen_edges: set[tuple[str, str, str]] = set()

    for edge in blueprint.edges:
        if edge.source not in by_id or edge.target not in by_id or edge.source == edge.target:
            _raise("EDGE_INCOMPATIBLE")
        identity = (edge.source, edge.target, edge.target_slot)
        if identity in seen_edges:
            _raise("EDGE_INCOMPATIBLE")
        seen_edges.add(identity)
        source_registration = registrations[by_id[edge.source].kind]
        target_registration = registrations[by_id[edge.target].kind]
        accepted_outputs = target_registration.input_slots.get(edge.target_slot)
        if (
            accepted_outputs is None
            or source_registration.output_type not in accepted_outputs
        ):
            _raise("EDGE_INCOMPATIBLE")
        outgoing[edge.source].append(edge.target)
        incoming_count[edge.target] += 1

    ready = sorted(
        (node_id for node_id, count in incoming_count.items() if count == 0),
        key=original_order.__getitem__,
    )
    ordered: list[str] = []
    depth = {node_id: 0 for node_id in ready}
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for target in sorted(outgoing[current], key=original_order.__getitem__):
            depth[target] = max(depth.get(target, 0), depth[current] + 1)
            incoming_count[target] -= 1
            if incoming_count[target] == 0:
                ready.append(target)
                ready.sort(key=original_order.__getitem__)
    if len(ordered) != len(by_id):
        _raise("WORKFLOW_CYCLE")
    if outgoing.get(blueprint.output_node_id):
        _raise("OUTPUT_NODE_INVALID")
    output_registration = registrations[by_id[blueprint.output_node_id].kind]
    if output_registration.output_type == "none":
        _raise("OUTPUT_NODE_INVALID")
    return ordered, depth


def _node_data(
    node: WorkflowNode,
    *,
    asset_resolver: Callable[[str], Mapping[str, Any] | None],
) -> dict[str, Any]:
    inputs = node.inputs
    parameters = node.parameters
    prompt = str(inputs.get("prompt") or inputs.get("text") or "")
    common: dict[str, Any] = {
        "title": node.title,
        "showTryOptions": False,
        "workflowLogicalNodeId": node.node_id,
    }
    if node.provider_id:
        common["providerId"] = node.provider_id
    if node.model_id:
        common["modelId"] = node.model_id
    if node.capability:
        common["modelCapability"] = node.capability
    if node.kind == "prompt":
        return {
            **common,
            "text": prompt,
            "composerText": prompt,
        }
    if node.kind == "image_generate":
        return {
            **common,
            "text": prompt,
            "composerText": prompt,
            "imageMode": parameters.get("image_mode", "blank"),
            "aspectRatio": parameters.get("aspect_ratio", "1:1"),
            "imageResolution": parameters.get("resolution", "1K"),
            "imageCount": parameters.get("count", 1),
        }
    if node.kind in {"video_generate", "video_compose"}:
        return {
            **common,
            "text": prompt,
            "composerText": prompt,
            "videoMode": parameters.get("video_mode", "blank"),
            "activeVideoTab": node.capability or "text_to_video",
            "aspectRatio": parameters.get("aspect_ratio", "16:9"),
            "videoResolution": parameters.get("resolution", "720P"),
            "videoDuration": parameters.get("duration_seconds", 5),
            "videoAudio": parameters.get("generate_audio", False),
            "videoCount": 1,
        }
    if node.kind == "audio_generate":
        return {
            **common,
            "text": prompt,
            "composerText": prompt,
            "audioDuration": parameters.get("duration_seconds"),
            "voice": parameters.get("voice"),
            "language": parameters.get("language"),
        }
    if node.kind == "script_generate":
        return {
            **common,
            "text": prompt,
            "composerText": prompt,
            "scriptMode": parameters.get("script_mode", "draft"),
            "shotCount": parameters.get("shot_count"),
        }
    if node.kind == "long_image_export":
        return {
            **common,
            "text": str(inputs.get("title") or ""),
            "exportWidth": parameters.get("width", 1080),
            "sliceHeight": parameters.get("slice_height", 2400),
        }
    if node.kind == "reference_note":
        return {**common, "text": str(inputs.get("text") or ""), "participatesInGeneration": False}
    if node.kind == "reference_asset":
        asset_id = str(inputs.get("asset_id") or "")
        asset = asset_resolver(asset_id) if asset_id else None
        if asset is None:
            _raise("ASSET_UNAVAILABLE")
        return {
            **common,
            "assetId": asset_id,
            "assetKind": str(asset.get("kind") or "file"),
            "assetName": str(asset.get("name") or node.title),
            "assetPath": str(asset.get("path") or ""),
            "assetMimeType": str(asset.get("mime_type") or ""),
            "assetPreviewUrl": str(asset.get("url") or ""),
            "savedToAssets": True,
        }
    if node.kind == "output":
        return {**common, "text": str(inputs.get("label") or "")}
    _raise("NODE_KIND_UNSUPPORTED")


def plan_manual_workflow(
    blueprint: WorkflowBlueprint,
    *,
    available_models: Collection[AvailableWorkflowModel],
    id_factory: Callable[[str], str],
    asset_resolver: Callable[[str], Mapping[str, Any] | None],
) -> CompiledWorkflow:
    """Build an empty-canvas, user-clicked construction plan with stable IDs."""
    try:
        validate_workflow_blueprint(blueprint)
    except ValueError as exc:
        raise WorkflowCompileError("WORKFLOW_SCHEMA_INVALID") from exc
    registry = workflow_node_registry()
    by_id = {node.node_id: node for node in blueprint.nodes}
    for node in blueprint.nodes:
        registration = registry[node.kind]
        if registration.provisioning == "UNAVAILABLE":
            _raise("NODE_KIND_UNSUPPORTED")
        _validate_inputs(node)
        _validate_scalar_parameters(node)
        _validate_model(node, registration, available_models)
    ordered_ids, _depth = _topological_order(blueprint, registry)
    workflow_id = id_factory("workflow")
    bindings = {
        logical_id: id_factory(
            _PHYSICAL_PREFIX.get(by_id[logical_id].kind, by_id[logical_id].kind)
        )
        for logical_id in ordered_ids
    }
    steps: list[WorkflowGuideStepDefinition] = []
    for logical_id in ordered_ids:
        node = by_id[logical_id]
        steps.append(
            WorkflowGuideStepDefinition(
                step_id=f"{logical_id}.manual-add",
                kind="MANUAL_BUILD",
                title=f"添加{node.title}",
                instruction="点击下方按钮，把这个节点加入空白画布。",
                logical_node_id=logical_id,
                node_id=bindings[logical_id],
                control_id=f"aigc.canvas.add-node.{node.kind}",
                optional=node.optional,
                completion_rule="PRESENT",
                manual_action="ADD_NODE",
                node_kind=node.kind,
                manual_node_data=_node_data(node, asset_resolver=asset_resolver),
            )
        )
    for index, edge in enumerate(blueprint.edges, start=1):
        steps.append(
            WorkflowGuideStepDefinition(
                step_id=f"workflow.manual-edge-{index}",
                kind="MANUAL_BUILD",
                title="连接工作流节点",
                instruction="点击下方按钮，按蓝图连接这两个节点。",
                logical_node_id=edge.target,
                node_id=bindings[edge.target],
                control_id="aigc.canvas.connect",
                optional=False,
                completion_rule="PRESENT",
                manual_action="CONNECT_EDGE",
                source_node_id=bindings[edge.source],
                target_node_id=bindings[edge.target],
                target_slot=edge.target_slot,
            )
        )
    for logical_id in ordered_ids:
        node = by_id[logical_id]
        if node.customer_action == "CLICK_GENERATE":
            steps.append(_guide_step(node, registry[node.kind], bindings[logical_id]))
    output_id = bindings[blueprint.output_node_id]
    steps.append(
        WorkflowGuideStepDefinition(
            step_id="workflow.submit",
            kind="SUBMIT",
            title="提交最终素材",
            instruction="最终节点生成完成后，提交给陆羽审核。",
            logical_node_id=blueprint.output_node_id,
            node_id=output_id,
            control_id="aigc.workflow.submit",
            optional=False,
            completion_rule="OUTPUT_AVAILABLE",
            expected_output_type=(
                registry[by_id[blueprint.output_node_id].kind].output_type
            ),
        )
    )
    return CompiledWorkflow(
        workflow_id=workflow_id,
        title=blueprint.title,
        nodes=(),
        edges=(),
        bindings=bindings,
        output_node_id=output_id,
        guide_steps=tuple(steps),
        viewport={"x": 0.0, "y": 0.0, "zoom": 1.0},
    )


def _guide_step(
    node: WorkflowNode,
    registration: NodeRegistration,
    physical_node_id: str,
) -> WorkflowGuideStepDefinition:
    if node.customer_action == "CLICK_GENERATE":
        return WorkflowGuideStepDefinition(
            step_id=f"{node.node_id}.generate",
            kind="GENERATE",
            title=node.title,
            instruction="检查预填参数后，点击当前节点的生成按钮。",
            logical_node_id=node.node_id,
            node_id=physical_node_id,
            control_id=registration.control_id,
            optional=node.optional,
            completion_rule="JOB_SUCCEEDED_WITH_OUTPUT",
            expected_output_type=registration.output_type,
            expected_capability=node.capability,
            expected_provider_id=node.provider_id,
            expected_model_id=node.model_id,
        )
    return WorkflowGuideStepDefinition(
        step_id=f"{node.node_id}.inspect",
        kind="INSPECT",
        title=node.title,
        instruction="检查当前节点已预填的内容。",
        logical_node_id=node.node_id,
        node_id=physical_node_id,
        control_id=registration.control_id,
        optional=node.optional,
        completion_rule="PRESENT",
        expected_output_type=registration.output_type,
    )


def compile_workflow(
    blueprint: WorkflowBlueprint,
    *,
    available_models: Collection[AvailableWorkflowModel],
    id_factory: Callable[[str], str],
    asset_resolver: Callable[[str], Mapping[str, Any] | None],
) -> CompiledWorkflow:
    """Validate a complete DAG, then assign DClaw-owned physical IDs."""
    try:
        validate_workflow_blueprint(blueprint)
    except ValueError as exc:
        raise WorkflowCompileError("WORKFLOW_SCHEMA_INVALID") from exc
    registry = workflow_node_registry()
    by_id = {node.node_id: node for node in blueprint.nodes}
    for node in blueprint.nodes:
        registration = registry[node.kind]
        if registration.provisioning != "AUTO_PROVISIONABLE":
            _raise(
                "NODE_KIND_UNSUPPORTED",
                manual=registration.provisioning == "MANUAL_ONLY",
            )
        _validate_inputs(node)
        _validate_scalar_parameters(node)
        _validate_model(node, registration, available_models)
        if node.kind == "reference_asset":
            asset_id = str(node.inputs.get("asset_id") or "")
            if not asset_id or asset_resolver(asset_id) is None:
                _raise("ASSET_UNAVAILABLE")

    ordered_ids, depth = _topological_order(blueprint, registry)

    workflow_id = id_factory("workflow")
    bindings: dict[str, str] = {}
    rows_by_depth: dict[int, int] = defaultdict(int)
    compiled_nodes: list[CompiledCanvasNode] = []
    guide_steps: list[WorkflowGuideStepDefinition] = []
    for logical_id in ordered_ids:
        node = by_id[logical_id]
        layer = depth[logical_id]
        row = rows_by_depth[layer]
        rows_by_depth[layer] += 1
        physical_id = id_factory(_PHYSICAL_PREFIX[node.kind])
        if physical_id in bindings.values():
            _raise("PROVISIONING_FAILED")
        bindings[logical_id] = physical_id
        registration = registry[node.kind]
        compiled_nodes.append(
            CompiledCanvasNode(
                logical_node_id=logical_id,
                physical_node_id=physical_id,
                kind=node.kind,
                position={"x": 120.0 + layer * 520.0, "y": 120.0 + row * 360.0},
                data=_node_data(node, asset_resolver=asset_resolver),
            ),
        )
        guide_steps.append(_guide_step(node, registration, physical_id))

    compiled_edges = tuple(
        CompiledCanvasEdge(
            edge_id=id_factory("edge"),
            source=bindings[edge.source],
            target=bindings[edge.target],
            target_slot=edge.target_slot,
        )
        for edge in blueprint.edges
    )
    output_physical_id = bindings[blueprint.output_node_id]
    guide_steps.append(
        WorkflowGuideStepDefinition(
            step_id="workflow.submit",
            kind="SUBMIT",
            title="提交最终素材",
            instruction="最终节点生成完成后，提交给陆羽审核。",
            logical_node_id=blueprint.output_node_id,
            node_id=output_physical_id,
            control_id="aigc.workflow.submit",
            optional=False,
            completion_rule="OUTPUT_AVAILABLE",
            expected_output_type=(
                registry[by_id[blueprint.output_node_id].kind].output_type
            ),
        ),
    )
    return CompiledWorkflow(
        workflow_id=workflow_id,
        title=blueprint.title,
        nodes=tuple(compiled_nodes),
        edges=compiled_edges,
        bindings=bindings,
        output_node_id=output_physical_id,
        guide_steps=tuple(guide_steps),
        viewport={"x": 0.0, "y": 0.0, "zoom": 1.0},
    )
