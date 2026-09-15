"""Application media-source composition shared by both HTTP entrances."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import HTTPException
from PIL import Image, ImageOps

from ..aigc.asset_service import AigcAssetService
from ..aigc.resource_store import AigcResourceError, AigcResourceStore


_REVIEW_IMAGE_MAX_SIZE = (1080, 1920)


def build_review_image_proxy(content: bytes) -> tuple[bytes, dict[str, Any]]:
    """Create a compact, readable review copy without modifying the original."""
    with Image.open(BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source)
        if image.mode in {"RGBA", "LA"} or (
            image.mode == "P" and "transparency" in image.info
        ):
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        else:
            image = image.convert("RGB")
        image.thumbnail(_REVIEW_IMAGE_MAX_SIZE, Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="JPEG", quality=82, optimize=True)
        data = output.getvalue()
        return data, {
            "mime_type": "image/jpeg",
            "size": len(data),
            "width": image.width,
            "height": image.height,
            "source_sha256": "sha256:" + sha256(content).hexdigest(),
        }


def _cached_review_image_proxy(
    service: AigcAssetService,
    asset: Any,
    content: bytes,
) -> dict[str, Any]:
    proxy, metadata = build_review_image_proxy(content)
    digest = str(metadata["source_sha256"]).removeprefix("sha256:")
    safe_asset_id = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in str(asset.id)
    )
    target = service.store.directory("review_proxies") / (
        f"{safe_asset_id}-{digest[:24]}.jpg"
    )
    if not target.is_file():
        temporary: Path | None = None
        with NamedTemporaryFile(
            dir=target.parent,
            prefix=target.stem + "-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(proxy)
            temporary = Path(handle.name)
        try:
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return {"type": "image", "source": {"type": "url", "url": target.as_uri()}}


def _stored_review_image_proxy(
    asset: Any,
    *,
    artifact_root: Path | None,
    storage_client: Any,
) -> dict[str, Any] | None:
    proxy = asset.meta.get("review_proxy")
    if not isinstance(proxy, dict):
        return None
    storage = proxy.get("storage")
    if isinstance(storage, dict) and storage.get("provider") == "aliyun_oss":
        object_key = str(storage.get("object_key") or "").strip()
        if object_key and storage_client is not None:
            return {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": storage_client.signed_get_url(object_key),
                },
            }
        return None
    path = str(proxy.get("path") or "").strip()
    if not path or artifact_root is None:
        return None
    target = (artifact_root / path).resolve()
    if not target.is_relative_to(artifact_root.resolve()) or not target.is_file():
        return None
    return {"type": "image", "source": {"type": "url", "url": target.as_uri()}}


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
        if asset.kind == "image":
            if asset_kinds is not None and "image" not in asset_kinds:
                raise AigcResourceError("ASSET_TYPE_MISMATCH")
            stored_proxy = _stored_review_image_proxy(
                asset,
                artifact_root=root,
                storage_client=client,
            )
            if stored_proxy is not None:
                return stored_proxy
            if is_cloud:
                raw, _ = await client.download(
                    service.cloud_storage_meta(asset)["object_key"],
                )
            else:
                path = service.local_path(asset, artifact_root=root)
                if not path.is_file():
                    raise AigcResourceError("ASSET_FILE_NOT_FOUND")
                raw = path.read_bytes()
            try:
                return _cached_review_image_proxy(service, asset, raw)
            except (OSError, ValueError):
                # Unsupported images remain reviewable through their original.
                pass
        return service.review_source(
            asset, canvas_id=canvas_id, node_ids=node_ids, asset_kinds=asset_kinds,
            artifact_root=root, storage_client=client,
        )
    except AigcResourceError as exc:
        raise resource_http_error(exc) from exc
