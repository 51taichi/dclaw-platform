"""Both API entrances must enforce the same resource ownership rules."""

import importlib
from types import SimpleNamespace

import pytest

from qwenpaw.app.aigc.models import CanvasUpsert
from qwenpaw.app.aigc.resource_store import AigcResourceError, AigcResourceStore


def canvas_service(tmp_path):
    module = importlib.import_module("qwenpaw.app.aigc.canvas_service")
    return module.AigcCanvasService(AigcResourceStore(tmp_path))


def test_canvas_owner_is_not_taken_from_payload(tmp_path):
    service = canvas_service(tmp_path)
    canvas = service.create("user-a", CanvasUpsert(meta={"owner_user_id": "user-b"}))
    assert service.get("user-a", canvas.id).meta["owner_user_id"] == "user-a"


def test_canvas_cross_owner_hidden_and_updates_preserve_owner(tmp_path):
    service = canvas_service(tmp_path)
    canvas = service.create("user-a", CanvasUpsert(name="first"))
    with pytest.raises(AigcResourceError) as caught:
        service.get("user-b", canvas.id)
    assert caught.value.code == "CANVAS_NOT_FOUND"
    updated = service.update("user-a", canvas.id, CanvasUpsert(name="second", meta={"owner_user_id": "user-b"}))
    assert updated.meta["owner_user_id"] == "user-a"
    assert updated.created_at == canvas.created_at
    assert service.get("user-a", canvas.id).name == "second"


def test_legacy_ownerless_access_requires_explicit_context(tmp_path):
    service = canvas_service(tmp_path)
    AigcResourceStore(tmp_path).write("canvases", "legacy", {
        "id": "legacy", "name": "old", "created_at": "old", "updated_at": "old",
    })
    with pytest.raises(AigcResourceError):
        service.get("user-a", "legacy")
    assert service.get("user-a", "legacy", allow_ownerless=True).id == "legacy"


def test_delete_canvas_does_not_delete_other_canvas_jobs(tmp_path):
    service = canvas_service(tmp_path)
    first = service.create("user-a", CanvasUpsert())
    second = service.create("user-b", CanvasUpsert())
    store = AigcResourceStore(tmp_path)
    for ordinal, canvas in enumerate((first, second)):
        store.write("jobs", f"job-{ordinal}", {
            "id": f"job-{ordinal}", "canvas_id": canvas.id, "node_id": "n",
            "capability": "text_to_video", "provider_id": "p", "model_id": "m",
            "status": "queued", "created_at": "now", "updated_at": "now",
        })
    service.delete("user-a", first.id)
    assert service.get("user-b", second.id).id == second.id
    assert store.read("jobs", "job-1")["canvas_id"] == second.id
    with pytest.raises(AigcResourceError):
        store.read("jobs", "job-0")


def test_owned_asset_resolver_does_not_accept_different_owner(tmp_path):
    module = importlib.import_module("qwenpaw.app.aigc.asset_service")
    store = AigcResourceStore(tmp_path)
    store.write("assets", "asset-1", {
        "id": "asset-1", "kind": "image", "path": "/not-read", "name": "image",
        "created_at": "now", "meta": {"owner_user_id": "user-a"},
    })
    service = module.AigcAssetService(store)
    assert service.resolve_owned("user-a", "asset-1").kind == "image"
    with pytest.raises(AigcResourceError) as caught:
        service.resolve_owned("user-b", "asset-1")
    assert caught.value.code == "ASSET_NOT_FOUND"


def test_capability_catalog_is_core_owned_and_route_is_compatibility_alias():
    core = importlib.import_module("qwenpaw.app.aigc.capability_service")
    route = importlib.import_module("qwenpaw.app.routers.aigc_studio")
    from qwenpaw.app.aigc.models import AigcCapabilityInfo, CapabilityList

    assert route.build_capability_list is core.build_capability_list
    assert route.project_workflow_capability_catalog is core.project_workflow_capability_catalog
    inventory = CapabilityList(capabilities=[AigcCapabilityInfo(
        provider_id="published", provider_name="Published", model_id="allowed",
        model_name="Allowed", capability="text_to_video", source="model_registry",
    )])
    catalog = core.project_workflow_capability_catalog(inventory)
    assert [(item.provider_id, item.model_id) for item in catalog.available_models] == [("published", "allowed")]
    video = next(node for node in catalog.nodes if node.kind == "video_generate")
    assert video.parameter_schema["additionalProperties"] is False
    assert video.parameter_schema["properties"]["resolution"]["enum"] == [
        "480P", "720P", "1080P", "1K", "2K", "4K",
    ]
    assert video.parameter_schema["properties"]["duration_seconds"] == {
        "type": "integer", "minimum": 1, "maximum": 60, "default": 5,
    }
    assert video.input_schema["additionalProperties"] is False
    assert video.input_schema["properties"]["first_frame_asset_id"] == {
        "type": "string", "minLength": 1,
    }
    reference = next(node for node in catalog.nodes if node.kind == "reference_asset")
    assert reference.customer_actions == ("SELECT_ASSET", "INSPECT")


def test_independent_audio_and_music_tools_are_not_projected_as_aigc_capabilities():
    core = importlib.import_module("qwenpaw.app.aigc.capability_service")

    assert "text_to_audio" not in core.SUPPORTED_AIGC_CAPABILITIES
    assert core._tool_capabilities("text_to_audio") == []
    assert core._tool_capabilities("generate_audio") == []
    assert core._tool_capabilities("text_to_music") == []
    assert core._tool_capabilities("generate_music") == []


@pytest.mark.asyncio
async def test_both_capability_entrances_call_core_catalog(monkeypatch):
    core = importlib.import_module("qwenpaw.app.aigc.capability_service")
    system = importlib.import_module("qwenpaw.app.routers.aigc_studio")
    platform = importlib.import_module("qwenpaw.app.routers.super_expert_platform")
    from qwenpaw.providers.provider_manager import ProviderManager
    from qwenpaw.app.aigc.models import CapabilityList

    manager = object()
    calls = []

    async def inventory(actual_manager, **kwargs):
        calls.append((actual_manager, kwargs))
        return CapabilityList(capabilities=[])

    monkeypatch.setattr(core, "build_capability_list", inventory)
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(provider_manager=manager)))
    system_catalog = await system.list_workflow_capabilities(request)
    platform_catalog = await platform._load_workflow_capability_catalog()
    assert calls == [
        (manager, {"include_unselected": True}),
        (manager, {"include_unselected": True}),
    ]
    assert system_catalog == platform_catalog


@pytest.mark.parametrize("kind", ["image", "video", "audio"])
def test_review_source_uses_actual_modality_and_bound_file(tmp_path, kind):
    from qwenpaw.app.aigc.asset_service import AigcAssetService
    from qwenpaw.app.aigc.models import AigcAsset

    media = tmp_path / "media"
    media.write_bytes(b"test-only")
    asset = AigcAsset(id="asset", kind=kind, name="test", path=str(media), created_at="now",
                      meta={"canvas_id": "canvas", "node_id": "output"})
    service = AigcAssetService(AigcResourceStore(tmp_path / "studio"))
    block = service.review_source(asset, canvas_id="canvas", node_ids={"output"},
                                  artifact_root=tmp_path, asset_kinds={kind})
    assert block == {"type": kind, "source": {"type": "url", "url": media.as_uri()}}
    with pytest.raises(AigcResourceError, match="ASSET_TYPE_MISMATCH"):
        service.review_source(asset, canvas_id="canvas", node_ids={"output"},
                              artifact_root=tmp_path, asset_kinds={"other"})


def test_review_source_rejects_binding_before_signing(tmp_path):
    from qwenpaw.app.aigc.asset_service import AigcAssetService
    from qwenpaw.app.aigc.models import AigcAsset
    from unittest.mock import Mock

    asset = AigcAsset(id="asset", kind="video", name="test", path="private",
                      created_at="now", meta={"canvas_id": "other", "node_id": "output",
                      "storage": {"provider": "aliyun_oss", "object_key": "key"}})
    client = Mock()
    service = AigcAssetService(AigcResourceStore(tmp_path))
    with pytest.raises(AigcResourceError, match="ASSET_BINDING_MISMATCH"):
        service.review_source(asset, canvas_id="canvas", node_ids={"output"},
                              artifact_root=tmp_path, storage_client=client)
    client.signed_get_url.assert_not_called()


def test_review_source_preserves_cloud_video_kind(tmp_path):
    from qwenpaw.app.aigc.asset_service import AigcAssetService
    from qwenpaw.app.aigc.models import AigcAsset
    from unittest.mock import Mock

    asset = AigcAsset(id="asset", kind="video", name="test", path="unused",
                      created_at="now", meta={"canvas_id": "canvas", "node_id": "output",
                      "storage": {"provider": "aliyun_oss", "object_key": "key"}})
    client = Mock()
    client.signed_get_url.return_value = "https://media.example.test/signed"
    service = AigcAssetService(AigcResourceStore(tmp_path))
    result = service.review_source(asset, canvas_id="canvas", node_ids={"output"},
                                   artifact_root=tmp_path, storage_client=client)
    assert result == {"type": "video", "source": {"type": "url", "url": "https://media.example.test/signed"}}
    client.signed_get_url.assert_called_once_with("key")


def test_asset_local_path_refuses_escape(tmp_path):
    from qwenpaw.app.aigc.asset_service import AigcAssetService
    from qwenpaw.app.aigc.models import AigcAsset

    service = AigcAssetService(AigcResourceStore(tmp_path / "studio"))
    asset = AigcAsset(id="asset", kind="image", name="test", path="../outside",
                      created_at="now")
    with pytest.raises(AigcResourceError, match="ASSET_PATH_OUTSIDE_ROOTS"):
        service.local_path(asset, artifact_root=tmp_path / "workspace")


@pytest.mark.asyncio
async def test_system_and_expert_canvas_creation_share_service(tmp_path, monkeypatch):
    from qwenpaw.app.aigc.canvas_service import AigcCanvasService
    from qwenpaw.app.routers import aigc_studio

    original = AigcCanvasService.create
    calls = []

    def create(service, owner, body, **kwargs):
        calls.append(owner)
        return original(service, owner, body, **kwargs)

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path)
    monkeypatch.setattr(AigcCanvasService, "create", create)
    await aigc_studio.create_canvas(
        SimpleNamespace(state=SimpleNamespace(user_id="u")), CanvasUpsert(name="System"),
    )
    _adapter(aigc_studio.STUDIO_ROOT).provision_workspace(
        owner_user_id="u", material_task_id="m", operation_id="aigc.text_to_video.create",
        arguments={"prompt": "test", "aspect_ratio": "9:16", "duration_seconds": 5,
                   "model_id": "model", "project_name": "test"},
    )
    _adapter(aigc_studio.STUDIO_ROOT).provision_blank_workspace(
        owner_user_id="u", material_task_id="manual", workflow_id="wf", title="Manual",
    )
    assert calls == ["u", "u", "u"]


@pytest.mark.parametrize("used_kind", ["jobs", "assets"])
def test_compensation_never_removes_used_canvas(tmp_path, used_kind):
    service = canvas_service(tmp_path)
    canvas = service.create("u", CanvasUpsert(meta={"origin": "operation"}))
    if used_kind == "jobs":
        resource = {"id": "used", "canvas_id": canvas.id, "node_id": "n",
                    "capability": "text_to_video", "provider_id": "p", "model_id": "m",
                    "status": "queued", "created_at": "now", "updated_at": "now"}
    else:
        resource = {"id": "used", "meta": {"canvas_id": canvas.id}}
    service.store.write(used_kind, "used", resource)
    with pytest.raises(AigcResourceError, match="RESOURCE_ALREADY_USED"):
        service.discard_unstarted("u", canvas.id, expected_meta={"origin": "operation"})
    assert service.get("u", canvas.id).id == canvas.id
    assert service.store.read(used_kind, "used") == resource


def test_compensation_only_removes_matching_unstarted_canvas(tmp_path):
    service = canvas_service(tmp_path)
    canvas = service.create("u", CanvasUpsert(meta={"origin": "operation"}))
    with pytest.raises(AigcResourceError):
        service.discard_unstarted("other", canvas.id, expected_meta={"origin": "operation"})
    with pytest.raises(AigcResourceError, match="RESOURCE_BINDING_MISMATCH"):
        service.discard_unstarted("u", canvas.id, expected_meta={"origin": "other"})
    assert service.get("u", canvas.id).id == canvas.id
    service.discard_unstarted("u", canvas.id, expected_meta={"origin": "operation"})
    service.discard_unstarted("u", canvas.id, expected_meta={"origin": "operation"})
    with pytest.raises(AigcResourceError, match="RESOURCE_NOT_FOUND"):
        service.load(canvas.id)


@pytest.mark.asyncio
async def test_system_asset_and_workflow_reference_share_owner_service(tmp_path, monkeypatch):
    from qwenpaw.app.aigc.asset_service import AigcAssetService
    from qwenpaw.app.routers import aigc_studio

    store = AigcResourceStore(tmp_path)
    store.write("assets", "asset", {"id": "asset", "name": "test", "kind": "video",
                "path": "unused", "created_at": "now", "meta": {"owner_user_id": "u"}})
    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path)
    calls = []
    original = AigcAssetService.load

    def load(service, asset_id):
        calls.append(asset_id)
        return original(service, asset_id)

    monkeypatch.setattr(AigcAssetService, "load", load)
    system = aigc_studio._load_asset_for_request(SimpleNamespace(state=SimpleNamespace(user_id="u")), "asset")
    expert = _adapter(aigc_studio.STUDIO_ROOT).resolve_owned_asset("u", "asset")
    assert calls == ["asset", "asset"]
    assert system.model_dump(mode="json") == expert
    assert _adapter(aigc_studio.STUDIO_ROOT).resolve_owned_asset("other", "asset") is None


@pytest.mark.asyncio
async def test_cloud_review_never_resolves_local_workspace(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock, Mock
    from qwenpaw.app.aigc.models import AigcAsset
    from qwenpaw.app.routers import aigc_studio

    asset = AigcAsset(id="cloud", kind="video", name="test", path="unused",
                      created_at="now", meta={"canvas_id": "c", "node_id": "n",
                      "storage": {"provider": "aliyun_oss", "object_key": "key"}})
    client = Mock()
    client.signed_get_url.return_value = "https://media.example.test/signed"
    root_resolver = AsyncMock(side_effect=AssertionError("Cloud review must not initialize workspace"))
    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path)
    monkeypatch.setattr(aigc_studio, "_load_asset_for_request", lambda *_args: asset)
    monkeypatch.setattr(aigc_studio, "_cloud_storage_client_or_error", lambda: client)
    monkeypatch.setattr(aigc_studio, "_artifact_root_for_request", root_resolver)
    result = await aigc_studio.resolve_owned_asset_for_agent_review(
        SimpleNamespace(), "cloud", canvas_id="c", node_ids={"n"},
    )
    assert result["type"] == "video"
    assert result["source"]["url"] == "https://media.example.test/signed"
    root_resolver.assert_not_awaited()


def _adapter(root):
    from qwenpaw.app.aigc.asset_service import AigcAssetService
    from qwenpaw.app.aigc.canvas_service import AigcCanvasService
    from qwenpaw.app.aigc.resource_store import AigcResourceStore
    from qwenpaw.app.super_experts.aigc_adapter import AigcServiceAdapter
    store = AigcResourceStore(root)
    return AigcServiceAdapter(AigcCanvasService(store), AigcAssetService(store))
