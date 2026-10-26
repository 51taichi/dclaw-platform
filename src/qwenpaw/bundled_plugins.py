# -*- coding: utf-8 -*-
"""Lazy imports for bundled plugin compatibility modules.

Core code must use plugin SPIs for runtime integration. This loader exists only
to preserve historical Python import paths while implementations migrate into
bundled plugins.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import sys
from pathlib import Path
from types import ModuleType


def _module_name(plugin_id: str) -> str:
    return "plugin_" + re.sub(r"[^A-Za-z0-9_]", "_", plugin_id)


def _candidate_roots(directory_name: str) -> tuple[Path, ...]:
    roots: list[Path] = []
    configured = os.environ.get("QWENPAW_BUNDLED_PLUGINS_DIR", "").strip()
    if configured:
        roots.append(Path(configured).expanduser() / directory_name)
    repository = Path(__file__).resolve().parents[2]
    roots.append(repository / "plugins" / "bundle" / directory_name)
    return tuple(dict.fromkeys(roots))


def load_bundled_plugin_module(
    plugin_id: str,
    directory_name: str,
    submodule: str,
) -> ModuleType:
    """Load a bundled plugin module without registering the plugin."""
    root_name = _module_name(plugin_id)
    existing = sys.modules.get(root_name)
    if existing is None:
        root = next(
            (
                candidate
                for candidate in _candidate_roots(directory_name)
                if (candidate / "plugin.py").is_file()
            ),
            None,
        )
        if root is None:
            raise ImportError(f"bundled plugin is unavailable: {plugin_id}")
        spec = importlib.util.spec_from_file_location(
            root_name,
            root / "plugin.py",
            submodule_search_locations=[str(root)],
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load bundled plugin: {plugin_id}")
        # Create only the package namespace. Compatibility imports must not
        # execute plugin.py or register/load unrelated plugin dependencies.
        existing = importlib.util.module_from_spec(spec)
        existing.__package__ = root_name
        existing.__path__ = [str(root)]
        sys.modules[root_name] = existing
    return importlib.import_module(f"{root_name}.{submodule}")


def reexport_bundled_plugin_module(
    namespace: dict[str, object],
    *,
    plugin_id: str,
    directory_name: str,
    submodule: str,
) -> None:
    """Populate a legacy module namespace from its plugin-owned replacement."""
    target = load_bundled_plugin_module(plugin_id, directory_name, submodule)
    public = getattr(target, "__all__", None)
    if public is None:
        public = tuple(
            name for name in vars(target) if not name.startswith("__")
        )
    namespace.update({name: getattr(target, name) for name in public})
    namespace["__all__"] = list(public)
    namespace["__plugin_implementation__"] = target
    legacy_name = str(namespace.get("__name__", ""))
    if legacy_name:
        sys.modules[legacy_name] = target
