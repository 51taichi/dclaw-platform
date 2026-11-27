"""Expert review resolves actual owned assets without a system-router call."""

from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from qwenpaw.app.aigc.asset_service import AigcAssetService
from qwenpaw.app.aigc.resource_store import AigcResourceStore
from qwenpaw.app.aigc.models import AigcAsset


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", ["user", "other", None])
async def test_expert_review_source_uses_shared_service_and_exact_owner(tmp_path, monkeypatch, owner):
    from qwenpaw.app.routers import super_expert_platform, aigc_studio
    store = AigcResourceStore(tmp_path / "studio")
    media = tmp_path / "fixture.mp4"
    media.write_bytes(b"path-resolution fixture, not generated media")
    asset = AigcAsset(id="asset", kind="video", name=media.name, path=str(media),
                      created_at="2026-09-06", meta={"owner_user_id": owner, "canvas_id": "canvas", "node_id": "node"})
    store.write("assets", asset.id, asset.model_dump())
    service = SimpleNamespace(aigc=SimpleNamespace(assets=AigcAssetService(store)))
    request = SimpleNamespace(state=SimpleNamespace(user_id="user"),
                              app=SimpleNamespace(state=SimpleNamespace(aigc_artifact_root=tmp_path)))

    async def forbidden(*args, **kwargs):
        raise AssertionError("expert review called a system HTTP router")

    monkeypatch.setattr(aigc_studio, "resolve_owned_asset_for_agent_review", forbidden)
    if owner == "user":
        block = await super_expert_platform.resolve_owned_asset_for_agent_review(
            request, "asset", canvas_id="canvas", node_ids={"node"}, service=service,
        )
        assert block == {"type": "video", "source": {"type": "url", "url": media.as_uri()}}
    else:
        with pytest.raises(HTTPException) as error:
            await super_expert_platform.resolve_owned_asset_for_agent_review(
                request, "asset", canvas_id="canvas", node_ids={"node"}, service=service,
            )
        assert error.value.status_code == 404
