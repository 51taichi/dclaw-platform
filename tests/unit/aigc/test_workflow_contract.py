from __future__ import annotations

import pytest
from pydantic import ValidationError

from qwenpaw.aigc.workflow_contract import (
    WorkflowBlueprint,
    WorkflowContractError,
    validate_workflow_blueprint,
    workflow_node_registry,
)


def _video_node() -> dict:
    return {
        "node_id": "clip",
        "kind": "video_generate",
        "title": "生成开场视频",
        "capability": "text_to_video",
        "provider_id": "provider-1",
        "model_id": "video-model-1",
        "inputs": {"prompt": "用一句真实痛点作为开场"},
        "parameters": {"aspect_ratio": "9:16", "duration_seconds": 5},
        "customer_action": "CLICK_GENERATE",
        "optional": False,
    }


def _blueprint() -> dict:
    return {
        "schema_version": 1,
        "title": "第一条抖音测试视频",
        "execution_preference": "CUSTOMER_TRIGGERED",
        "nodes": [_video_node()],
        "edges": [],
        "output_node_id": "clip",
        "fallback_policy": "FAIL_CLOSED",
    }


def test_registry_covers_every_current_canvas_node_type_with_honest_status():
    registry = workflow_node_registry()

    assert set(registry) == {
        "prompt",
        "image_generate",
        "video_generate",
        "script_generate",
        "long_image_export",
        "reference_note",
        "reference_asset",
        "output",
        "video_compose",
        "director_stage",
    }
    assert registry["video_generate"].provisioning == "AUTO_PROVISIONABLE"
    assert registry["reference_asset"].provisioning == "AUTO_PROVISIONABLE"
    assert registry["video_compose"].provisioning == "UNAVAILABLE"
    assert registry["director_stage"].provisioning == "UNAVAILABLE"
    assert registry["video_generate"].control_id == "aigc.video.generate-submit"
    assert registry["prompt"].requires_model is True


def test_blueprint_rejects_removed_independent_audio_generation_node():
    invalid = _blueprint()
    invalid["nodes"] = [
        {
            "node_id": "voice",
            "kind": "audio_generate",
            "title": "生成旁白",
            "capability": "text_to_audio",
            "provider_id": "provider-1",
            "model_id": "audio-1",
            "inputs": {"prompt": "生成旁白"},
            "parameters": {},
            "customer_action": "CLICK_GENERATE",
            "optional": False,
        }
    ]
    invalid["output_node_id"] = "voice"

    with pytest.raises(WorkflowContractError, match="node kind"):
        validate_workflow_blueprint(WorkflowBlueprint.model_validate(invalid))


def test_blueprint_accepts_only_semantic_fields_and_forbids_raw_canvas_data():
    blueprint = WorkflowBlueprint.model_validate(_blueprint())

    assert blueprint.output_node_id == "clip"
    assert blueprint.nodes[0].kind == "video_generate"

    with pytest.raises(ValidationError):
        WorkflowBlueprint.model_validate({**_blueprint(), "canvas_id": "canvas-x"})

    invalid_node = {**_video_node(), "data": {"videoState": "generated"}}
    with pytest.raises(ValidationError):
        WorkflowBlueprint.model_validate({**_blueprint(), "nodes": [invalid_node]})


def test_blueprint_rejects_generation_node_without_catalog_identity():
    invalid = _blueprint()
    invalid["nodes"] = [
        {
            **_video_node(),
            "provider_id": None,
            "model_id": None,
        }
    ]

    with pytest.raises(WorkflowContractError, match="model identity"):
        validate_workflow_blueprint(WorkflowBlueprint.model_validate(invalid))


def test_blueprint_rejects_unregistered_node_kind():
    invalid = _blueprint()
    invalid["nodes"] = [{**_video_node(), "kind": "browser_script"}]

    with pytest.raises(WorkflowContractError, match="node kind"):
        validate_workflow_blueprint(WorkflowBlueprint.model_validate(invalid))


def test_blueprint_has_closed_size_and_identifier_limits():
    invalid = _blueprint()
    invalid["nodes"] = [{**_video_node(), "node_id": "9-invalid"}]
    with pytest.raises(ValidationError):
        WorkflowBlueprint.model_validate(invalid)

    too_many = _blueprint()
    too_many["nodes"] = [
        {**_video_node(), "node_id": f"clip-{index}"}
        for index in range(21)
    ]
    with pytest.raises(ValidationError):
        WorkflowBlueprint.model_validate(too_many)
