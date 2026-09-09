"""Strict semantic contracts for super-expert AIGC workflows.

The models in this module deliberately describe business-level node intent.
They never expose persisted canvas ``node.data`` or physical identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ProvisioningMode = Literal[
    "AUTO_PROVISIONABLE",
    "MANUAL_ONLY",
    "UNAVAILABLE",
]
CustomerAction = Literal[
    "CLICK_GENERATE",
    "INSPECT",
    "SELECT_ASSET",
    "NONE",
]


class WorkflowContractError(ValueError):
    """A public-safe semantic workflow validation failure."""


@dataclass(frozen=True)
class NodeRegistration:
    kind: str
    title: str
    provisioning: ProvisioningMode
    capabilities: tuple[str, ...]
    input_keys: frozenset[str]
    parameter_keys: frozenset[str]
    input_slots: dict[str, tuple[str, ...]]
    output_type: str
    control_id: str | None
    customer_actions: tuple[CustomerAction, ...]
    requires_model: bool = False
    provisioning_reason: str | None = None


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    kind: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    capability: str | None = Field(default=None, min_length=1, max_length=80)
    provider_id: str | None = Field(default=None, min_length=1, max_length=160)
    model_id: str | None = Field(default=None, min_length=1, max_length=160)
    inputs: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    customer_action: CustomerAction
    optional: bool = False


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    target: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    target_slot: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")


class WorkflowBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1]
    title: str = Field(min_length=1, max_length=160)
    execution_preference: Literal["CUSTOMER_TRIGGERED"]
    nodes: tuple[WorkflowNode, ...] = Field(min_length=1, max_length=20)
    edges: tuple[WorkflowEdge, ...] = Field(default=(), max_length=40)
    output_node_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    # Ordered logical producers whose actual outputs form one review submission.
    # Empty preserves the legacy single-output contract.
    review_node_ids: tuple[str, ...] = Field(default=(), max_length=20)
    fallback_policy: Literal[
        "MANUAL_BUILD_IF_UNSUPPORTED",
        "FAIL_CLOSED",
    ]


def _registration(
    kind: str,
    title: str,
    *,
    provisioning: ProvisioningMode = "AUTO_PROVISIONABLE",
    capabilities: tuple[str, ...] = (),
    input_keys: tuple[str, ...] = (),
    parameter_keys: tuple[str, ...] = (),
    input_slots: dict[str, tuple[str, ...]] | None = None,
    output_type: str = "none",
    control_id: str | None = None,
    customer_actions: tuple[CustomerAction, ...] = ("NONE",),
    requires_model: bool = False,
    provisioning_reason: str | None = None,
) -> NodeRegistration:
    return NodeRegistration(
        kind=kind,
        title=title,
        provisioning=provisioning,
        capabilities=capabilities,
        input_keys=frozenset(input_keys),
        parameter_keys=frozenset(parameter_keys),
        input_slots=dict(input_slots or {}),
        output_type=output_type,
        control_id=control_id,
        customer_actions=customer_actions,
        requires_model=requires_model,
        provisioning_reason=provisioning_reason,
    )


_NODE_REGISTRY: dict[str, NodeRegistration] = {
    "prompt": _registration(
        "prompt",
        "文本",
        capabilities=("storyboard",),
        input_keys=("text", "prompt", "reference_asset_ids"),
        parameter_keys=("system_prompt",),
        input_slots={
            "context": ("text", "image", "video"),
        },
        output_type="text",
        control_id="aigc.text.generate-submit",
        customer_actions=("CLICK_GENERATE", "INSPECT", "NONE"),
        requires_model=True,
    ),
    "image_generate": _registration(
        "image_generate",
        "图片生成",
        capabilities=(
            "text_to_image",
            "image_edit",
            "image_to_image",
            "mask_edit",
            "reference_image",
        ),
        input_keys=("prompt", "reference_asset_ids"),
        parameter_keys=("aspect_ratio", "resolution", "count", "image_mode"),
        input_slots={
            "prompt": ("text",),
            "reference_image": ("image",),
        },
        output_type="image",
        control_id="aigc.image.generate-submit",
        customer_actions=("CLICK_GENERATE",),
        requires_model=True,
    ),
    "video_generate": _registration(
        "video_generate",
        "视频生成",
        capabilities=(
            "text_to_video",
            "image_to_video",
            "reference_video",
        ),
        input_keys=(
            "prompt",
            "first_frame_asset_id",
            "last_frame_asset_id",
            "reference_asset_ids",
        ),
        parameter_keys=(
            "aspect_ratio",
            "resolution",
            "duration_seconds",
            "generate_audio",
            "video_mode",
        ),
        input_slots={
            "prompt": ("text",),
            "first_frame": ("image",),
            "last_frame": ("image",),
            "reference_image": ("image",),
            "reference_video": ("video",),
            "audio": ("audio",),
        },
        output_type="video",
        control_id="aigc.video.generate-submit",
        customer_actions=("CLICK_GENERATE",),
        requires_model=True,
    ),
    "audio_generate": _registration(
        "audio_generate",
        "音频生成",
        capabilities=("text_to_audio",),
        input_keys=("prompt",),
        parameter_keys=("duration_seconds", "voice", "language"),
        input_slots={"prompt": ("text",)},
        output_type="audio",
        control_id="aigc.audio.generate-submit",
        customer_actions=("CLICK_GENERATE",),
        requires_model=True,
    ),
    "script_generate": _registration(
        "script_generate",
        "脚本生成",
        capabilities=("storyboard",),
        input_keys=("prompt", "reference_asset_ids"),
        parameter_keys=("script_mode", "shot_count"),
        input_slots={
            "prompt": ("text",),
            "reference_image": ("image",),
            "reference_video": ("video",),
        },
        output_type="text",
        control_id="aigc.script.generate-submit",
        customer_actions=("CLICK_GENERATE",),
        requires_model=True,
    ),
    "long_image_export": _registration(
        "long_image_export",
        "公众号长图",
        capabilities=("long_image_export",),
        input_keys=("title",),
        parameter_keys=("width", "slice_height"),
        input_slots={"text": ("text",), "image": ("image",)},
        output_type="image",
        control_id="aigc.long-image.generate-submit",
        customer_actions=("CLICK_GENERATE",),
    ),
    "reference_note": _registration(
        "reference_note",
        "参考说明",
        input_keys=("text",),
        output_type="none",
        control_id=None,
        customer_actions=("INSPECT", "NONE"),
    ),
    "reference_asset": _registration(
        "reference_asset",
        "参考素材",
        capabilities=("reference_image",),
        input_keys=("asset_id",),
        input_slots={},
        output_type="asset",
        control_id=None,
        customer_actions=("SELECT_ASSET", "INSPECT"),
    ),
    "output": _registration(
        "output",
        "输出",
        input_keys=("label",),
        input_slots={"asset": ("image", "video", "audio", "text", "asset")},
        output_type="asset",
        control_id=None,
        customer_actions=("INSPECT", "NONE"),
    ),
    "video_compose": _registration(
        "video_compose",
        "视频合成",
        provisioning="UNAVAILABLE",
        input_slots={"video": ("video",), "audio": ("audio",)},
        output_type="video",
        control_id=None,
        customer_actions=("NONE",),
        provisioning_reason="stable_server_executor_unavailable",
    ),
    "director_stage": _registration(
        "director_stage",
        "导演台",
        provisioning="UNAVAILABLE",
        capabilities=("storyboard",),
        input_slots={"reference_image": ("image",)},
        output_type="none",
        control_id=None,
        customer_actions=("NONE",),
        provisioning_reason="server_contract_unavailable",
    ),
}


def workflow_node_registry() -> dict[str, NodeRegistration]:
    """Return a caller-safe snapshot of the semantic node registry."""
    return dict(_NODE_REGISTRY)


def validate_workflow_blueprint(
    blueprint: WorkflowBlueprint,
) -> WorkflowBlueprint:
    """Validate node-level rules that depend on the server registry."""
    seen: set[str] = set()
    for node in blueprint.nodes:
        if node.node_id in seen:
            raise WorkflowContractError("duplicate workflow node id")
        seen.add(node.node_id)
        registration = _NODE_REGISTRY.get(node.kind)
        if registration is None:
            raise WorkflowContractError("workflow node kind is unavailable")
        if node.capability is not None and node.capability not in registration.capabilities:
            raise WorkflowContractError("workflow node capability is unavailable")
        if registration.requires_model and node.customer_action == "CLICK_GENERATE" and (
            not node.provider_id or not node.model_id or not node.capability
        ):
            raise WorkflowContractError("workflow node model identity is required")
        if node.customer_action not in registration.customer_actions:
            raise WorkflowContractError("workflow node customer action is unavailable")
        unknown_inputs = set(node.inputs) - registration.input_keys
        if unknown_inputs:
            raise WorkflowContractError("workflow node input is unavailable")
        unknown_parameters = set(node.parameters) - registration.parameter_keys
        if unknown_parameters:
            raise WorkflowContractError("workflow node parameter is unavailable")
    if blueprint.output_node_id not in seen:
        raise WorkflowContractError("workflow output node is unavailable")
    if len(set(blueprint.review_node_ids)) != len(blueprint.review_node_ids):
        raise WorkflowContractError("duplicate workflow review node id")
    if any(node_id not in seen for node_id in blueprint.review_node_ids):
        raise WorkflowContractError("workflow review node is unavailable")
    return blueprint
