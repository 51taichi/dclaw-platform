from types import SimpleNamespace
import json
from pathlib import Path

import pytest
from jsonschema import validate

from super_agent.aigc_assets import (
    list_owned_aigc_assets,
    prepare_owned_aigc_localization,
)


ROOT = Path(__file__).parents[1]


class _Assets:
    def __init__(self, asset):
        self.asset = asset

    def resolve_owned(self, user_id, asset_id):
        assert user_id == "user-1"
        assert asset_id == self.asset.id
        return self.asset

    @staticmethod
    def validate_review_binding(asset, *, canvas_id, node_ids):
        assert asset.meta["canvas_id"] == canvas_id
        assert asset.meta["node_id"] in node_ids

    @staticmethod
    def cloud_storage_meta(asset):
        return asset.meta["storage"]

    @staticmethod
    def signed_source(asset, *, storage_client, ttl_seconds):
        assert storage_client == "storage"
        assert ttl_seconds == 600
        return f"https://oss.example/{asset.id}?signed=1"


def _fixture():
    asset = SimpleNamespace(
        id="asset-1",
        kind="video",
        name="shot-01.mp4",
        mime_type="video/mp4",
        meta={
            "canvas_id": "canvas-1",
            "node_id": "video-1",
            "storage": {
                "provider": "aliyun_oss",
                "object_key": "aigc/shot-01.mp4",
                "size_bytes": 42,
                "sha256": "a" * 64,
            },
        },
    )
    job = SimpleNamespace(
        id="job-1",
        canvas_id="canvas-1",
        node_id="video-1",
        status="succeeded",
        outputs=[asset],
        updated_at="2026-11-12T00:00:00Z",
    )
    canvas = SimpleNamespace(
        id="canvas-1",
        meta={"workflow_id": "workflow-1"},
        nodes=[SimpleNamespace(id="video-1")],
    )
    adapter = SimpleNamespace(
        assets=_Assets(asset),
        workflow_context=lambda **_: (canvas, [job]),
    )
    binding = SimpleNamespace(
        installation_id="installation-1",
        conversation_id="conversation-1",
        canvas_id="canvas-1",
        material_task_id="material-1",
        workflow_id="workflow-1",
        node_bindings={"clip": "video-1"},
        node_id="video-1",
    )
    return SimpleNamespace(binding=binding), adapter


def test_lists_only_bound_successful_assets():
    task, adapter = _fixture()

    result = list_owned_aigc_assets(
        task=task,
        adapter=adapter,
        user_id="user-1",
        installation_id="installation-1",
        conversation_id="conversation-1",
    )

    assert result == {
        "contract": "aigc.task.assets.list/1",
        "status": "found",
        "material_task_id": "material-1",
        "assets": [{
            "asset_id": "asset-1",
            "node_id": "video-1",
            "job_id": "job-1",
            "kind": "video",
            "name": "shot-01.mp4",
            "mime_type": "video/mp4",
            "size_bytes": 42,
            "sha256": "a" * 64,
        }],
    }
    assert "download_url" not in json.dumps(result)
    validate(
        result,
        json.loads((
            ROOT / "devkit/schemas/aigc-task-assets-v1/list-response.schema.json"
        ).read_text()),
    )


def test_list_is_isolated_by_installation_and_conversation():
    task, adapter = _fixture()

    for installation_id, conversation_id in (
        ("another-installation", "conversation-1"),
        ("installation-1", "another-conversation"),
    ):
        assert list_owned_aigc_assets(
            task=task,
            adapter=adapter,
            user_id="user-1",
            installation_id=installation_id,
            conversation_id=conversation_id,
        ) == {
            "contract": "aigc.task.assets.list/1",
            "status": "not_found",
        }


def test_prepares_signed_localization_without_exposing_it_in_list(monkeypatch):
    task, adapter = _fixture()
    monkeypatch.setattr(
        "super_agent.aigc_assets.get_object_storage_client",
        lambda **_: "storage",
    )

    result = prepare_owned_aigc_localization(
        task=task,
        adapter=adapter,
        user_id="user-1",
        installation_id="installation-1",
        conversation_id="conversation-1",
        requested_assets=[{
            "asset_id": "asset-1",
            "usage": "timeline_clip",
            "slot": "clip_01",
            "order": 1,
            "destination": "res",
        }],
    )

    assert result[0]["download_url"].startswith("https://oss.example/")
    assert result[0]["slot"] == "clip_01"


def test_rejects_final_output_outside_task_root(monkeypatch):
    task, adapter = _fixture()
    monkeypatch.setattr(
        "super_agent.aigc_assets.get_object_storage_client",
        lambda **_: "storage",
    )

    with pytest.raises(ValueError, match="invalid asset selection"):
        prepare_owned_aigc_localization(
            task=task,
            adapter=adapter,
            user_id="user-1",
            installation_id="installation-1",
            conversation_id="conversation-1",
            requested_assets=[{
                "asset_id": "asset-1",
                "usage": "final_output",
                "slot": "final_video",
                "order": 0,
                "destination": "res",
            }],
        )


def test_localize_request_schema_rejects_unstructured_usage_plan():
    schema = json.loads((
        ROOT / "devkit/schemas/aigc-task-assets-v1/localize-request.schema.json"
    ).read_text())
    validate({
        "material_task_id": "material-1",
        "idempotency_key": "download-1",
        "assets": [{
            "asset_id": "asset-1",
            "usage": "timeline_clip",
            "slot": "clip_01",
            "order": 1,
            "destination": "res",
        }],
    }, schema)
