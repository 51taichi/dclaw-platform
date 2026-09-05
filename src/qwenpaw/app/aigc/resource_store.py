"""Shared JSON resource storage; callers translate domain errors to their API."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import tempfile
from threading import RLock
from typing import Any


SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class AigcResourceError(ValueError):
    def __init__(self, code: str, resource_name: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.resource_name = resource_name


class AigcResourceStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self._cache: dict[str, tuple[tuple[int, int, int], dict[str, Any]]] = {}
        self._lock = RLock()

    @staticmethod
    def safe_id(value: str) -> str:
        if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value):
            raise AigcResourceError("INVALID_RESOURCE_ID")
        return value

    def _contained(self, path: Path) -> Path:
        resolved = path.resolve()
        if resolved == self.root or not resolved.is_relative_to(self.root):
            raise AigcResourceError("INVALID_RESOURCE_PATH")
        return resolved

    def directory(self, kind: str) -> Path:
        path = self._contained(self.root / self.safe_id(kind))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path(self, kind: str, resource_id: str) -> Path:
        # Validate both components before creating anything on disk.
        kind, resource_id = self.safe_id(kind), self.safe_id(resource_id)
        return self._contained(self.root / kind / f"{resource_id}.json")

    def read(self, kind: str, resource_id: str) -> dict[str, Any]:
        return self.read_path(self.path(kind, resource_id))

    def read_path(self, path: Path) -> dict[str, Any]:
        path = self._contained(Path(path))
        key = str(path)
        with self._lock:
            try:
                stat = path.stat()
                fingerprint = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
                cached = self._cache.get(key)
                if cached and cached[0] == fingerprint:
                    return deepcopy(cached[1])
                payload = json.loads(path.read_text("utf-8"))
                if not isinstance(payload, dict):
                    raise AigcResourceError("CORRUPT_RESOURCE", path.name)
                self._cache[key] = (fingerprint, payload)
                return deepcopy(payload)
            except FileNotFoundError as exc:
                self._cache.pop(key, None)
                raise AigcResourceError("RESOURCE_NOT_FOUND", path.name) from exc
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise AigcResourceError("CORRUPT_RESOURCE", path.name) from exc

    def write(self, kind: str, resource_id: str, value: dict[str, Any]) -> None:
        self.write_path(self.path(kind, resource_id), value)

    def write_path(self, path: Path, value: dict[str, Any]) -> None:
        path = self._contained(Path(path))
        if not isinstance(value, dict):
            raise AigcResourceError("CORRUPT_RESOURCE", path.name)
        encoded = json.dumps(value, ensure_ascii=False, indent=2)
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=path.parent,
                    prefix=f".{path.name}.", suffix=".tmp", delete=False,
                ) as output:
                    temporary = Path(output.name)
                    output.write(encoded)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, path)
                self._cache.pop(str(path), None)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

    def delete(self, kind: str, resource_id: str) -> None:
        self.delete_path(self.path(kind, resource_id))

    def delete_path(self, path: Path) -> None:
        path = self._contained(Path(path))
        with self._lock:
            try:
                path.unlink()
            except FileNotFoundError as exc:
                raise AigcResourceError("RESOURCE_NOT_FOUND", path.name) from exc
            finally:
                self._cache.pop(str(path), None)
