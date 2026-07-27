# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_desktop_release():
    module_path = Path(__file__).parents[3] / "scripts" / "pack" / "desktop_release.py"
    spec = importlib.util.spec_from_file_location("desktop_release", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_next_patch_version_uses_latest_stable_index_version():
    desktop_release = _load_desktop_release()
    index = {
        "platforms": {"win": {"latest": "desktop-win-1.1.8"}},
        "files": {"desktop-win-1.1.8": {"version": "1.1.8"}},
    }

    assert desktop_release.next_patch_version(index, fallback_version="1.1.8b1") == "1.1.9"


def test_next_patch_version_falls_back_to_current_version_when_index_is_empty():
    desktop_release = _load_desktop_release()

    assert desktop_release.next_patch_version({}, fallback_version="1.1.8b1") == "1.1.9"


def test_artifact_names_are_dclaw_names():
    desktop_release = _load_desktop_release()

    assert desktop_release.artifact_name("win", "1.1.9") == "DClaw-Setup-1.1.9.exe"
    assert desktop_release.artifact_name("mac", "1.1.9") == "DClaw-1.1.9-macOS.zip"


def test_write_version_files_updates_all_desktop_version_sources(tmp_path):
    desktop_release = _load_desktop_release()
    repo = tmp_path
    (repo / "src/qwenpaw").mkdir(parents=True)
    (repo / "console/src-tauri").mkdir(parents=True)
    (repo / "src/qwenpaw/__version__.py").write_text(
        '# -*- coding: utf-8 -*-\n__version__ = "1.1.8b1"\n',
        encoding="utf-8",
    )
    tauri_conf = {
        "productName": "DClaw",
        "version": "0.1.0",
        "identifier": "com.dclaw.desktop",
    }
    (repo / "console/src-tauri/tauri.conf.json").write_text(
        json.dumps(tauri_conf, indent=2),
        encoding="utf-8",
    )
    (repo / "console/src-tauri/Cargo.toml").write_text(
        '[package]\nname = "dclaw"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )

    desktop_release.write_version_files(repo, "1.1.9")

    assert '__version__ = "1.1.9"' in (
        repo / "src/qwenpaw/__version__.py"
    ).read_text(encoding="utf-8")
    assert json.loads(
        (repo / "console/src-tauri/tauri.conf.json").read_text(encoding="utf-8"),
    )["version"] == "1.1.9"
    assert 'version = "1.1.9"' in (
        repo / "console/src-tauri/Cargo.toml"
    ).read_text(encoding="utf-8")


def test_release_config_file_overrides_default_values(tmp_path):
    desktop_release = _load_desktop_release()
    config_path = tmp_path / "desktop_release.local.json"
    config_path.write_text(
        json.dumps(
            {
                "index_url": "https://download.example.cn/metadata/apps/desktop/index.json",
                "bucket": "oss://dclaw-download",
                "desktop_api_url": "https://api.example.cn",
                "cdn_refresh_command": "aliyun cdn RefreshObjectCaches --ObjectPath https://download.example.cn/files/",
                "oss": {
                    "config_file": str(tmp_path / "ossutilconfig"),
                    "endpoint": "oss-cn-hangzhou.aliyuncs.com",
                    "access_key_id": "test-ak",
                    "access_key_secret": "test-sk",
                },
            },
        ),
        encoding="utf-8",
    )

    config = desktop_release.load_release_config(config_path)

    assert config.index_url == "https://download.example.cn/metadata/apps/desktop/index.json"
    assert config.bucket == "oss://dclaw-download"
    assert config.desktop_api_url == "https://api.example.cn"
    assert config.cdn_refresh_command.startswith("aliyun cdn")
    assert config.oss.config_file == tmp_path / "ossutilconfig"
    assert config.oss.endpoint == "oss-cn-hangzhou.aliyuncs.com"


def test_missing_release_config_uses_deepmega_defaults(tmp_path):
    desktop_release = _load_desktop_release()

    config = desktop_release.load_release_config(tmp_path / "missing.json")

    assert (
        config.index_url
        == "https://static.deepmega.cn/metadata/apps/desktop/index.json"
    )
    assert config.bucket == "oss://deepmega-applet"
    assert config.download_base_url == "https://static.deepmega.cn"
    assert config.desktop_api_url == "https://dclaw.deepmega.cn"


def test_build_platform_passes_configured_desktop_api_url(monkeypatch):
    desktop_release = _load_desktop_release()
    calls = []

    def fake_run(cmd, *, cwd=desktop_release.REPO_ROOT, dry_run=False, env=None):
        calls.append((cmd, cwd, dry_run, env))

    monkeypatch.setattr(desktop_release, "run", fake_run)

    artifact = desktop_release._build_platform(
        "mac",
        "1.2.3",
        True,
        desktop_api_url="https://api.example.cn",
    )

    assert artifact == desktop_release.REPO_ROOT / "dist/DClaw-1.2.3-macOS.zip"
    assert calls[0][3]["DCLAW_DESKTOP_API_URL"] == "https://api.example.cn"


def test_ossutil_command_uses_config_file_when_configured(tmp_path):
    desktop_release = _load_desktop_release()
    oss_config = desktop_release.OssConfig(config_file=tmp_path / "ossutilconfig")

    command = desktop_release.ossutil_command(oss_config, "cp", "a", "b")

    assert command == [
        "ossutil",
        "-c",
        str(tmp_path / "ossutilconfig"),
        "cp",
        "a",
        "b",
    ]
