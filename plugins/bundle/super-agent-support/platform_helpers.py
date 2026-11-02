"""Immutable platform-helper artifacts shipped by this plugin release."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any


PLATFORM = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_HELPER_BYTES = 268_435_456


class PlatformHelperError(ValueError):
    pass


class PlatformHelperUnavailable(PlatformHelperError):
    pass


class PlatformHelperRegistry:
    def __init__(self, plugin_root: Path) -> None:
        self._plugin_root = plugin_root.resolve()
        self._root = self._plugin_root / "platform_helpers"
        self._cache: dict[str, tuple[dict[str, Any], Path]] = {}

    def _load_manifest(self, platform: str, root: Path) -> dict[str, Any]:
        manifest_path = root / "manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PlatformHelperError("invalid local-helper manifest") from exc
            if not isinstance(manifest, dict):
                raise PlatformHelperError("invalid local-helper manifest")
            return manifest
        if platform != "windows-x64":
            raise PlatformHelperUnavailable(
                f"local helper is not published for {platform}",
            )
        metadata_path = self._plugin_root / "windows-helper" / "helper.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PlatformHelperError("invalid local-helper metadata") from exc
        if not isinstance(metadata, dict):
            raise PlatformHelperError("invalid local-helper metadata")
        artifact = root / str(metadata.get("executable"))
        if not artifact.is_file():
            raise PlatformHelperUnavailable(
                f"local helper is not published for {platform}",
            )
        payload = artifact.read_bytes()
        return {
            **metadata,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def resolve(self, platform: str) -> tuple[dict[str, Any], Path]:
        if not PLATFORM.fullmatch(platform):
            raise PlatformHelperError("invalid helper platform")
        cached = self._cache.get(platform)
        if cached is not None:
            return cached
        root = (self._root / platform).resolve()
        if not root.is_relative_to(self._root):
            raise PlatformHelperError("invalid helper platform")
        manifest = self._load_manifest(platform, root)
        executable = manifest.get("executable")
        artifact = (root / str(executable)).resolve()
        if (
            manifest.get("platform") != platform
            or not isinstance(manifest.get("version"), str)
            or not VERSION.fullmatch(manifest["version"])
            or not isinstance(manifest.get("protocol_version"), str)
            or not manifest["protocol_version"]
            or executable != "DClaw.LocalHelper.exe"
            or not artifact.is_relative_to(root)
            or not artifact.is_file()
            or type(manifest.get("size_bytes")) is not int
            or not 1 <= manifest["size_bytes"] <= MAX_HELPER_BYTES
            or artifact.stat().st_size != manifest["size_bytes"]
            or not isinstance(manifest.get("sha256"), str)
            or not SHA256.fullmatch(manifest["sha256"])
        ):
            raise PlatformHelperError("invalid local-helper manifest")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if digest != manifest["sha256"]:
            raise PlatformHelperError("local-helper artifact checksum mismatch")
        public = {
            **manifest,
            "download_path": (
                "/api/super-agent-support/local-helper/download"
                f"?platform={platform}"
            ),
        }
        self._cache[platform] = (public, artifact)
        return public, artifact
