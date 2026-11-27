"""Asset ownership rules shared by system and capability entrances."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canvas_service import AigcCanvasService
from .models import AigcAsset
from .resource_store import AigcResourceError, AigcResourceStore


class AigcAssetService:
    def __init__(self, store: AigcResourceStore) -> None:
        self.store = store

    def load(self, asset_id: str) -> AigcAsset:
        return AigcAsset(**self.store.read("assets", asset_id))

    @staticmethod
    def explicit_owner(asset: AigcAsset) -> Any:
        return asset.meta.get("owner_user_id") or asset.meta.get("user_id")

    def resolve_owned(self, owner_user_id: str, asset_id: str) -> AigcAsset:
        asset = self.load(asset_id)
        if (
            not owner_user_id.strip()
            or str(self.explicit_owner(asset) or "").strip() != owner_user_id.strip()
        ):
            raise AigcResourceError("ASSET_NOT_FOUND")
        return asset

    def can_access(
        self, owner_user_id: str, asset: AigcAsset, *, allow_ownerless: bool = False,
    ) -> bool:
        owner = self.explicit_owner(asset)
        if owner is not None:
            return str(owner) == owner_user_id
        canvas_id = str(asset.meta.get("canvas_id") or "")
        if canvas_id:
            try:
                AigcCanvasService(self.store).get(
                    owner_user_id, canvas_id, allow_ownerless=allow_ownerless,
                )
            except AigcResourceError:
                return False
            return True
        return allow_ownerless

    def get(
        self, owner_user_id: str, asset_id: str, *, allow_ownerless: bool = False,
    ) -> AigcAsset:
        asset = self.load(asset_id)
        if not self.can_access(owner_user_id, asset, allow_ownerless=allow_ownerless):
            raise AigcResourceError("ASSET_NOT_FOUND")
        return asset

    @staticmethod
    def cloud_storage_meta(asset: AigcAsset) -> dict[str, Any] | None:
        storage = asset.meta.get("storage")
        if not isinstance(storage, dict) or storage.get("provider") != "aliyun_oss":
            return None
        if not str(storage.get("object_key") or "").strip():
            return None
        return storage

    @classmethod
    def signed_source(
        cls, asset: AigcAsset, *, storage_client: Any,
        ttl_seconds: int | None = None,
    ) -> str | None:
        storage = cls.cloud_storage_meta(asset)
        if storage is None:
            return None
        if storage_client is None:
            raise RuntimeError("Aliyun OSS storage is not configured.")
        object_key = str(storage["object_key"])
        if ttl_seconds is None:
            return storage_client.signed_get_url(object_key)
        return storage_client.signed_get_url(object_key, ttl_seconds=ttl_seconds)

    def local_path(self, asset: AigcAsset, *, artifact_root: Path) -> Path:
        raw_path = Path(asset.path)
        target = (
            raw_path.expanduser().resolve() if raw_path.is_absolute()
            else (artifact_root / raw_path).resolve()
        )
        roots = (artifact_root.resolve(), self.store.directory("asset_files"))
        if not any(target.is_relative_to(root) for root in roots):
            raise AigcResourceError("ASSET_PATH_OUTSIDE_ROOTS")
        return target

    @staticmethod
    def validate_review_binding(
        asset: AigcAsset, *, canvas_id: str, node_ids: set[str],
    ) -> None:
        if (
            str(asset.meta.get("canvas_id") or "") != canvas_id
            or str(asset.meta.get("node_id") or "") not in node_ids
        ):
            raise AigcResourceError("ASSET_BINDING_MISMATCH")

    def review_source(
        self, asset: AigcAsset, *, canvas_id: str, node_ids: set[str],
        artifact_root: Path | None = None, asset_kinds: set[str] | None = None,
        storage_client: Any = None,
    ) -> dict[str, Any]:
        """Resolve an already owner-authorized asset; never initiate a review."""
        self.validate_review_binding(asset, canvas_id=canvas_id, node_ids=node_ids)
        source_url = self.signed_source(asset, storage_client=storage_client)
        if source_url is None:
            if artifact_root is None:
                raise AigcResourceError("ASSET_ROOT_REQUIRED")
            target = self.local_path(asset, artifact_root=artifact_root)
            if not target.is_file():
                raise AigcResourceError("ASSET_FILE_NOT_FOUND")
            source_url = target.as_uri()
        if asset.kind not in {"image", "video", "audio"}:
            raise AigcResourceError("ASSET_TYPE_UNREVIEWABLE")
        if asset_kinds is not None and asset.kind not in asset_kinds:
            raise AigcResourceError("ASSET_TYPE_MISMATCH")
        return {"type": asset.kind, "source": {"type": "url", "url": source_url}}
