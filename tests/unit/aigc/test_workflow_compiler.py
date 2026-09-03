from __future__ import annotations

from collections.abc import Callable

import pytest

from qwenpaw.aigc.workflow_compiler import (
    AvailableWorkflowModel,
    WorkflowCompileError,
    compile_workflow,
)
from qwenpaw.aigc.workflow_contract import WorkflowBlueprint


def _node(
    node_id: str,
    kind: str,
    *,
    capability: str | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
    inputs: dict | None = None,
    parameters: dict | None = None,
    customer_action: str = "CLICK_GENERATE",
    optional: bool = False,
) -> dict:
    return {
        "node_id": node_id,
        "kind": kind,
        "title": node_id,
        "capability": capability,
        "provider_id": provider_id,
        "model_id": model_id,
        "inputs": inputs or {},
        "parameters": parameters or {},
        "customer_action": customer_action,
        "optional": optional,
    }


def _three_node_payload() -> dict:
    return {
        "schema_version": 1,
        "title": "招生短视频",
        "execution_preference": "CUSTOMER_TRIGGERED",
        "nodes": [
            _node(
                "copy",
                "prompt",
                inputs={"text": "失业后学抖音，第一步应该做什么？"},
                customer_action="NONE",
            ),
            _node(
                "keyframe",
                "image_generate",
                capability="text_to_image",
                provider_id="provider-1",
                model_id="image-1",
                inputs={"prompt": "焦虑的求职者看着手机"},
                parameters={"aspect_ratio": "9:16", "count": 1},
            ),
            _node(
                "clip",
                "video_generate",
                capability="image_to_video",
                provider_id="provider-1",
                model_id="video-1",
                inputs={"prompt": "镜头缓慢推进"},
                parameters={
                    "aspect_ratio": "9:16",
                    "resolution": "720P",
                    "duration_seconds": 5,
                    "generate_audio": True,
                    "video_mode": "image_to_video",
                },
            ),
        ],
        "edges": [
            {"source": "copy", "target": "keyframe", "target_slot": "prompt"},
            {
                "source": "keyframe",
                "target": "clip",
                "target_slot": "first_frame",
            },
        ],
        "output_node_id": "clip",
        "fallback_policy": "FAIL_CLOSED",
    }


def _models() -> tuple[AvailableWorkflowModel, ...]:
    return (
        AvailableWorkflowModel(
            provider_id="provider-1",
            model_id="text-1",
            capabilities=frozenset({"storyboard"}),
        ),
        AvailableWorkflowModel(
            provider_id="provider-1",
            model_id="image-1",
            capabilities=frozenset({"text_to_image"}),
        ),
        AvailableWorkflowModel(
            provider_id="provider-1",
            model_id="video-1",
            capabilities=frozenset({"image_to_video"}),
        ),
    )


def test_clickable_prompt_is_bound_to_an_executable_text_model():
    payload = _three_node_payload()
    payload["nodes"][0].update({
        "capability": "storyboard",
        "provider_id": "provider-1",
        "model_id": "text-1",
        "customer_action": "CLICK_GENERATE",
    })

    compiled = compile_workflow(
        WorkflowBlueprint.model_validate(payload),
        available_models=_models(),
        id_factory=_id_factory(),
        asset_resolver=lambda _asset_id: None,
    )

    prompt = next(node for node in compiled.nodes if node.kind == "prompt")
    assert prompt.data["modelId"] == "text-1"


def _id_factory() -> Callable[[str], str]:
    counts: dict[str, int] = {}

    def create(prefix: str) -> str:
        counts[prefix] = counts.get(prefix, 0) + 1
        return f"{prefix}-{counts[prefix]}"

    return create


def _compile(payload: dict | None = None):
    return compile_workflow(
        WorkflowBlueprint.model_validate(payload or _three_node_payload()),
        available_models=_models(),
        id_factory=_id_factory(),
        asset_resolver=lambda _asset_id: None,
    )


def test_compiler_builds_prompt_image_video_dag_and_output_binding():
    compiled = _compile()

    assert [node.kind for node in compiled.nodes] == [
        "prompt",
        "image_generate",
        "video_generate",
    ]
    assert compiled.bindings == {
        "copy": "prompt-1",
        "keyframe": "image-1",
        "clip": "video-1",
    }
    assert [(edge.source, edge.target, edge.target_slot) for edge in compiled.edges] == [
        ("prompt-1", "image-1", "prompt"),
        ("image-1", "video-1", "first_frame"),
    ]
    assert compiled.output_node_id == "video-1"
    assert compiled.nodes[0].position == {"x": 120.0, "y": 120.0}
    assert compiled.nodes[1].position == {"x": 640.0, "y": 120.0}
    assert compiled.nodes[2].position == {"x": 1160.0, "y": 120.0}
    assert compiled.nodes[2].data["videoDuration"] == 5
    assert compiled.nodes[2].data["modelId"] == "video-1"
    assert [step.kind for step in compiled.guide_steps] == [
        "INSPECT",
        "GENERATE",
        "GENERATE",
        "SUBMIT",
    ]
    assert compiled.guide_steps[2].control_id == "aigc.video.generate-submit"


def test_compiler_rejects_cycle_before_creating_physical_ids():
    payload = _three_node_payload()
    payload["edges"].append(
        {"source": "clip", "target": "copy", "target_slot": "context"}
    )
    generated: list[str] = []

    with pytest.raises(WorkflowCompileError, match="WORKFLOW_CYCLE"):
        compile_workflow(
            WorkflowBlueprint.model_validate(payload),
            available_models=_models(),
            id_factory=lambda prefix: generated.append(prefix) or prefix,
            asset_resolver=lambda _asset_id: None,
        )

    assert generated == []


def test_compiler_rejects_incompatible_edge_slot():
    payload = _three_node_payload()
    payload["edges"][1]["target_slot"] = "audio"

    with pytest.raises(WorkflowCompileError, match="EDGE_INCOMPATIBLE"):
        _compile(payload)


def test_compiler_rejects_model_not_present_in_current_catalog():
    payload = _three_node_payload()
    payload["nodes"][2]["model_id"] = "removed-model"

    with pytest.raises(WorkflowCompileError, match="MODEL_UNAVAILABLE"):
        _compile(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("duration_seconds", 0),
        ("duration_seconds", 61),
        ("aspect_ratio", "banana"),
        ("generate_audio", "yes"),
    ],
)
def test_compiler_rejects_invalid_video_parameter_values(field: str, value: object):
    payload = _three_node_payload()
    payload["nodes"][2]["parameters"][field] = value

    with pytest.raises(WorkflowCompileError, match="PARAMETER_INVALID"):
        _compile(payload)


def test_compiler_reports_manual_only_node_without_partially_compiling():
    payload = _three_node_payload()
    payload["nodes"] = [
        _node(
            "compose",
            "video_compose",
            capability="image_to_video",
        )
    ]
    payload["edges"] = []
    payload["output_node_id"] = "compose"

    with pytest.raises(WorkflowCompileError) as captured:
        _compile(payload)

    assert captured.value.code == "NODE_KIND_UNSUPPORTED"
    assert captured.value.manual_fallback_allowed is True


def test_compiler_rejects_untrusted_reference_asset():
    payload = _three_node_payload()
    payload["nodes"] = [
        _node(
            "reference",
            "reference_asset",
            inputs={"asset_id": "asset-other-user"},
            customer_action="SELECT_ASSET",
        )
    ]
    payload["edges"] = []
    payload["output_node_id"] = "reference"

    with pytest.raises(WorkflowCompileError, match="ASSET_UNAVAILABLE"):
        _compile(payload)


def test_generic_provisioner_persists_the_compiled_graph(tmp_path, monkeypatch):
    from qwenpaw.app.routers import aigc_studio

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path / "studio")
    aigc_studio._JSON_CACHE.clear()
    compiled = _compile()

    canvas = aigc_studio.provision_super_expert_aigc_workflow(
        owner_user_id="user-1",
        material_task_id="material-1",
        compiled=compiled,
    )

    persisted = aigc_studio._load_canvas(canvas.id)
    assert [node.type for node in persisted.nodes] == [
        "prompt",
        "image_generate",
        "video_generate",
    ]
    assert [(edge.source, edge.target) for edge in persisted.edges] == [
        ("prompt-1", "image-1"),
        ("image-1", "video-1"),
    ]
    assert persisted.edges[1].data == {"role": "first_frame"}
    assert persisted.meta["workflow_id"] == compiled.workflow_id
    assert persisted.meta["super_expert_material_task_id"] == "material-1"
    assert persisted.meta["owner_user_id"] == "user-1"


def test_manual_fallback_provisioner_creates_a_truly_blank_canvas(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.routers import aigc_studio

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path / "studio")
    aigc_studio._JSON_CACHE.clear()

    canvas = aigc_studio.provision_blank_super_expert_aigc_workspace(
        owner_user_id="user-1",
        material_task_id="material-1",
        workflow_id="workflow-1",
        title="手动搭建视频合成",
    )

    assert canvas.nodes == []
    assert canvas.edges == []
    assert canvas.meta["workflow_id"] == "workflow-1"
    assert canvas.meta["execution_mode"] == "MANUAL_BUILD"
