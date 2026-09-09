"""Application media-source composition shared by both HTTP entrances."""

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..aigc.asset_service import AigcAssetService
from ..aigc.resource_store import AigcResourceError, AigcResourceStore


def resource_http_error(error: AigcResourceError) -> HTTPException:
    asset_errors = {
        "ASSET_BINDING_MISMATCH": (403, "Asset binding mismatch."),
        "ASSET_PATH_OUTSIDE_ROOTS": (403, "Asset file is outside allowed roots."),
        "ASSET_FILE_NOT_FOUND": (404, "Asset file not found."),
        "ASSET_TYPE_UNREVIEWABLE": (409, "Asset type cannot be reviewed."),
        "ASSET_TYPE_MISMATCH": (409, "Asset type does not match workflow output."),
    }
    if error.code in asset_errors:
        status, detail = asset_errors[error.code]
        return HTTPException(status_code=status, detail=detail)
    if error.code == "CANVAS_NOT_FOUND":
        return HTTPException(status_code=404, detail="Canvas not found.")
    if error.code == "ASSET_NOT_FOUND":
        return HTTPException(status_code=404, detail="Asset not found.")
    if error.code == "RESOURCE_NOT_FOUND":
        return HTTPException(status_code=404, detail="AIGC Studio resource not found")
    if error.code == "CORRUPT_RESOURCE":
        return HTTPException(status_code=500, detail=f"Corrupt Studio file: {error.resource_name}")
    return HTTPException(status_code=400, detail="Invalid AIGC Studio resource id")


async def artifact_root_for_request(request, store: AigcResourceStore) -> Path:
    override = getattr(request.app.state, "aigc_artifact_root", None)
    if override:
        root = Path(override).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root
    try:
        from ..agent_context import get_agent_for_request
        workspace = await get_agent_for_request(request)
        root = Path(workspace.workspace_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root
    except Exception:
        return store.directory("workspace_artifacts").resolve()


def cloud_storage_client_or_error():
    from ..object_storage import get_object_storage_client
    client = get_object_storage_client(require_enabled=False)
    if client is None:
        raise RuntimeError("Aliyun OSS storage is not configured.")
    return client


async def review_media_source(
    request, service: AigcAssetService, asset, *, canvas_id: str,
    node_ids: set[str], asset_kinds: set[str] | None = None,
    artifact_root_resolver=None, storage_client_factory=None,
) -> dict[str, Any]:
    """Compose source access for an already authorized asset; never review it."""
    try:
        service.validate_review_binding(asset, canvas_id=canvas_id, node_ids=node_ids)
        is_cloud = service.cloud_storage_meta(asset) is not None
        client = (storage_client_factory or cloud_storage_client_or_error)() if is_cloud else None
        root = None
        if not is_cloud:
            root = (await artifact_root_resolver(request) if artifact_root_resolver
                    else await artifact_root_for_request(request, service.store))
        if asset.kind == "file" and (asset.mime_type or "").split(";")[0] in {"text/plain", "text/markdown", "application/json"}:
            if asset_kinds is not None and "text" not in asset_kinds:
                raise AigcResourceError("ASSET_TYPE_MISMATCH")
            if is_cloud:
                raw, _ = await client.download(service.cloud_storage_meta(asset)["object_key"])
            else:
                path = service.local_path(asset, artifact_root=root)
                if not path.is_file():
                    raise AigcResourceError("ASSET_FILE_NOT_FOUND")
                raw = path.read_bytes()
            return {"type": "text", "text": raw.decode("utf-8-sig")}
        return service.review_source(
            asset, canvas_id=canvas_id, node_ids=node_ids, asset_kinds=asset_kinds,
            artifact_root=root, storage_client=client,
        )
    except AigcResourceError as exc:
        raise resource_http_error(exc) from exc
