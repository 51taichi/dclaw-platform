from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from qwenpaw.app.routers import plugins as plugin_routes
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.registry import PluginRegistry


def _plugin(path: Path, version: str, *, fails: bool = False) -> Path:
    path.mkdir(parents=True)
    (path / "plugin.json").write_text(
        json.dumps(
            {
                "id": "example.hot-reload",
                "name": "Hot reload fixture",
                "version": version,
                "entry": {"backend": "plugin.py"},
            },
        ),
        encoding="utf-8",
    )
    failure = "raise RuntimeError('new version failed')" if fails else ""
    (path / "plugin.py").write_text(
        f"""
class FixturePlugin:
    def __init__(self):
        self.config = None

    def register(self, api):
        self.config = api.config
        {failure}

plugin = FixturePlugin()
""".strip(),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def isolated_registry():
    previous = PluginRegistry._instance
    PluginRegistry._instance = None
    module_name = "plugin_example_hot_reload"
    for name in list(sys.modules):
        if name == module_name or name.startswith(module_name + "."):
            sys.modules.pop(name, None)
    try:
        yield
    finally:
        for name in list(sys.modules):
            if name == module_name or name.startswith(module_name + "."):
                sys.modules.pop(name, None)
        PluginRegistry._instance = previous


@pytest.mark.asyncio
async def test_hot_reload_preserves_plugin_config(
    tmp_path,
    monkeypatch,
    isolated_registry,
):
    install_dir = tmp_path / "installed"
    loader = PluginLoader([install_dir])
    loader.registry.set_plugin_http_app(FastAPI())
    old_source = _plugin(tmp_path / "old", "1.0.0")
    original_config = {
        "master_key_base64": "secret-key",
        "trusted_package_signers": {"signer-1": "public-key"},
    }
    await loader.load_plugin_from_path(
        old_source,
        config=original_config,
        install_dir=install_dir,
    )
    original_config["trusted_package_signers"]["signer-1"] = "changed"

    monkeypatch.setattr(plugin_routes, "_post_unload_cleanup", lambda *a: None)
    post_load = AsyncMock()
    monkeypatch.setattr(plugin_routes, "_post_load_setup", post_load)
    new_source = _plugin(tmp_path / "new", "2.0.0")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    record = await plugin_routes._load_plugin_transactionally(
        request=request,
        loader=loader,
        source_path=new_source,
        install_dir=install_dir,
        force=True,
    )

    assert record.manifest.version == "2.0.0"
    assert record.config == {
        "master_key_base64": "secret-key",
        "trusted_package_signers": {"signer-1": "public-key"},
    }
    assert record.instance.config == record.config
    post_load.assert_awaited_once_with(request, "example.hot-reload")


@pytest.mark.asyncio
async def test_failed_hot_reload_restores_files_config_and_runtime(
    tmp_path,
    monkeypatch,
    isolated_registry,
):
    install_dir = tmp_path / "installed"
    loader = PluginLoader([install_dir])
    loader.registry.set_plugin_http_app(FastAPI())
    old_source = _plugin(tmp_path / "old", "1.0.0")
    config = {
        "master_key_base64": "secret-key",
        "trusted_package_signers": {"signer-1": "public-key"},
    }
    await loader.load_plugin_from_path(
        old_source,
        config=config,
        install_dir=install_dir,
    )

    monkeypatch.setattr(plugin_routes, "_post_unload_cleanup", lambda *a: None)
    post_load = AsyncMock()
    monkeypatch.setattr(plugin_routes, "_post_load_setup", post_load)
    broken_source = _plugin(tmp_path / "broken", "2.0.0", fails=True)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    with pytest.raises(RuntimeError, match="new version failed"):
        await plugin_routes._load_plugin_transactionally(
            request=request,
            loader=loader,
            source_path=broken_source,
            install_dir=install_dir,
            force=True,
        )

    restored = loader.get_loaded_plugin("example.hot-reload")
    assert restored is not None
    assert restored.manifest.version == "1.0.0"
    assert restored.config == config
    assert restored.instance.config == config
    assert json.loads(
        (install_dir / "example.hot-reload" / "plugin.json").read_text(
            encoding="utf-8",
        ),
    )["version"] == "1.0.0"
    post_load.assert_awaited_once_with(request, "example.hot-reload")


@pytest.mark.asyncio
async def test_failed_post_load_setup_restores_previous_plugin(
    tmp_path,
    monkeypatch,
    isolated_registry,
):
    install_dir = tmp_path / "installed"
    loader = PluginLoader([install_dir])
    loader.registry.set_plugin_http_app(FastAPI())
    old_source = _plugin(tmp_path / "old", "1.0.0")
    config = {"trusted_package_signers": {"signer-1": "public-key"}}
    await loader.load_plugin_from_path(
        old_source,
        config=config,
        install_dir=install_dir,
    )

    cleanup_calls = []
    monkeypatch.setattr(
        plugin_routes,
        "_post_unload_cleanup",
        lambda *args: cleanup_calls.append(args),
    )
    post_load = AsyncMock(
        side_effect=[RuntimeError("host refresh failed"), None],
    )
    monkeypatch.setattr(plugin_routes, "_post_load_setup", post_load)
    new_source = _plugin(tmp_path / "new", "2.0.0")
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    with pytest.raises(RuntimeError, match="host refresh failed"):
        await plugin_routes._load_plugin_transactionally(
            request=request,
            loader=loader,
            source_path=new_source,
            install_dir=install_dir,
            force=True,
        )

    restored = loader.get_loaded_plugin("example.hot-reload")
    assert restored is not None
    assert restored.manifest.version == "1.0.0"
    assert restored.config == config
    assert post_load.await_count == 2
    assert len(cleanup_calls) == 2
