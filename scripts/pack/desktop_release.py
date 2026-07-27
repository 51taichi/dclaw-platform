#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helpers for the domestic DClaw desktop release flow."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX_URL = "https://static.deepmega.cn/metadata/apps/desktop/index.json"
DEFAULT_BUCKET = "oss://deepmega-applet"
DEFAULT_DOWNLOAD_BASE_URL = "https://static.deepmega.cn"
DEFAULT_DESKTOP_API_URL = "https://dclaw.deepmega.cn"
DEFAULT_CONFIG_PATH = REPO_ROOT / "scripts/pack/desktop_release.local.json"


@dataclass(frozen=True)
class OssConfig:
    config_file: Path | None = None
    endpoint: str = ""
    access_key_id: str = ""
    access_key_secret: str = ""


@dataclass(frozen=True)
class ReleaseConfig:
    index_url: str = DEFAULT_INDEX_URL
    bucket: str = DEFAULT_BUCKET
    download_base_url: str = DEFAULT_DOWNLOAD_BASE_URL
    desktop_api_url: str = DEFAULT_DESKTOP_API_URL
    cdn_refresh_command: str = ""
    oss: OssConfig = OssConfig()


def _stable_triplet(version: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version.strip())
    if not match:
        raise ValueError(f"Invalid stable version: {version}")
    return tuple(int(part) for part in match.groups())


def _format_triplet(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def _latest_index_version(index: dict[str, Any]) -> str | None:
    versions: list[tuple[int, int, int]] = []
    files = index.get("files", {})
    if isinstance(files, dict):
        for metadata in files.values():
            if isinstance(metadata, dict) and metadata.get("version"):
                try:
                    versions.append(_stable_triplet(str(metadata["version"])))
                except ValueError:
                    continue
    return _format_triplet(max(versions)) if versions else None


def next_patch_version(index: dict[str, Any], fallback_version: str) -> str:
    base = _latest_index_version(index) or fallback_version
    major, minor, patch = _stable_triplet(base)
    return f"{major}.{minor}.{patch + 1}"


def artifact_name(platform: str, version: str) -> str:
    if platform == "win":
        return f"DClaw-Setup-{version}.exe"
    if platform == "mac":
        return f"DClaw-{version}-macOS.zip"
    raise ValueError(f"Unsupported desktop platform: {platform}")


def _resolve_config_path(path: str, *, base_dir: Path) -> Path:
    config_path = Path(path).expanduser()
    if config_path.is_absolute():
        return config_path
    return base_dir / config_path


def load_release_config(config_path: str | Path | None) -> ReleaseConfig:
    """Load local desktop release config.

    Missing config files are allowed so CI and dry-run commands can continue
    using defaults. Secret-bearing local configs should not be committed.
    """
    if config_path is None:
        path = DEFAULT_CONFIG_PATH
    else:
        path = Path(config_path)
    path = path.expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path

    data: dict[str, Any] = {}
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))

    oss_data = data.get("oss", {})
    if not isinstance(oss_data, dict):
        oss_data = {}
    config_file = oss_data.get("config_file")
    resolved_config_file = (
        _resolve_config_path(str(config_file), base_dir=path.parent)
        if config_file
        else None
    )
    oss_config = OssConfig(
        config_file=resolved_config_file,
        endpoint=str(oss_data.get("endpoint", "")).strip(),
        access_key_id=str(oss_data.get("access_key_id", "")).strip(),
        access_key_secret=str(oss_data.get("access_key_secret", "")).strip(),
    )
    return ReleaseConfig(
        index_url=str(data.get("index_url", DEFAULT_INDEX_URL)).strip()
        or DEFAULT_INDEX_URL,
        bucket=str(data.get("bucket", DEFAULT_BUCKET)).strip()
        or DEFAULT_BUCKET,
        download_base_url=str(
            data.get("download_base_url", DEFAULT_DOWNLOAD_BASE_URL),
        ).strip()
        or DEFAULT_DOWNLOAD_BASE_URL,
        desktop_api_url=str(
            data.get(
                "desktop_api_url",
                os.environ.get("DCLAW_DESKTOP_API_URL", DEFAULT_DESKTOP_API_URL),
            ),
        ).strip()
        or DEFAULT_DESKTOP_API_URL,
        cdn_refresh_command=str(
            data.get(
                "cdn_refresh_command",
                os.environ.get("DCLAW_CDN_REFRESH_COMMAND", ""),
            ),
        ).strip(),
        oss=oss_config,
    )


def materialize_ossutil_config(oss_config: OssConfig, *, dry_run: bool) -> OssConfig:
    """Write an ossutil config file from local release config when needed."""
    if not (
        oss_config.endpoint
        and oss_config.access_key_id
        and oss_config.access_key_secret
    ):
        return oss_config

    config_file = oss_config.config_file or (
        REPO_ROOT / "scripts/pack/.ossutilconfig"
    )
    content = (
        "[Credentials]\n"
        "language=EN\n"
        f"endpoint={oss_config.endpoint}\n"
        f"accessKeyID={oss_config.access_key_id}\n"
        f"accessKeySecret={oss_config.access_key_secret}\n"
    )
    print(f"Using ossutil config file: {config_file}")
    if not dry_run:
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(content, encoding="utf-8")
        config_file.chmod(0o600)
    return OssConfig(config_file=config_file)


def ossutil_command(oss_config: OssConfig, *args: str) -> list[str]:
    command = ["ossutil"]
    if oss_config.config_file:
        command.extend(["-c", str(oss_config.config_file)])
    command.extend(args)
    return command


def read_current_version(repo_root: Path = REPO_ROOT) -> str:
    version_file = repo_root / "src/qwenpaw/__version__.py"
    match = re.search(
        r'__version__\s*=\s*"([^"]+)"',
        version_file.read_text(encoding="utf-8"),
    )
    if not match:
        raise ValueError(f"Cannot read version from {version_file}")
    return match.group(1)


def write_version_files(repo_root: Path, version: str) -> None:
    version_file = repo_root / "src/qwenpaw/__version__.py"
    version_text = version_file.read_text(encoding="utf-8")
    version_file.write_text(
        re.sub(
            r'__version__\s*=\s*"[^"]+"',
            f'__version__ = "{version}"',
            version_text,
            count=1,
        ),
        encoding="utf-8",
    )

    tauri_path = repo_root / "console/src-tauri/tauri.conf.json"
    tauri_conf = json.loads(tauri_path.read_text(encoding="utf-8"))
    tauri_conf["version"] = version
    tauri_path.write_text(
        json.dumps(tauri_conf, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    cargo_path = repo_root / "console/src-tauri/Cargo.toml"
    cargo_text = cargo_path.read_text(encoding="utf-8")
    cargo_path.write_text(
        re.sub(
            r'(?m)^version\s*=\s*"[^"]+"',
            f'version = "{version}"',
            cargo_text,
            count=1,
        ),
        encoding="utf-8",
    )


def load_index(index_url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(index_url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}


def run(
    cmd: list[str],
    *,
    cwd: Path = REPO_ROOT,
    dry_run: bool = False,
    env: dict[str, str] | None = None,
) -> None:
    print("+", " ".join(cmd))
    if not dry_run:
        subprocess.run(cmd, cwd=cwd, check=True, env=env)


def _build_platform(
    platform: str,
    version: str,
    dry_run: bool,
    *,
    desktop_api_url: str,
) -> Path:
    build_env = os.environ.copy()
    build_env["DCLAW_DESKTOP_API_URL"] = desktop_api_url
    if platform == "win":
        run(
            ["pwsh", "-File", "./scripts/pack/build_win.ps1"],
            dry_run=dry_run,
            env=build_env,
        )
        return REPO_ROOT / "dist" / artifact_name("win", version)
    if platform == "mac":
        run(
            ["bash", "-lc", "CREATE_ZIP=1 bash ./scripts/pack/build_macos.sh"],
            dry_run=dry_run,
            env=build_env,
        )
        return REPO_ROOT / "dist" / artifact_name("mac", version)
    raise ValueError(f"Unsupported desktop platform: {platform}")


def _upload_platform(
    platform: str,
    version: str,
    artifact_path: Path,
    bucket: str,
    oss_config: OssConfig,
    dry_run: bool,
) -> dict[str, Any] | None:
    filename = artifact_name(platform, version)
    platform_dir = "win" if platform == "win" else "mac"
    latest_name = (
        "DClaw-Setup-latest.exe"
        if platform == "win"
        else "DClaw-latest-macOS.zip"
    )
    metadata = REPO_ROOT / f"{platform}-metadata.json"
    run(
        [
            sys.executable,
            "scripts/pack/generate_oss_metadata.py",
            "--file",
            str(artifact_path),
            "--product",
            "desktop",
            "--platform",
            platform,
            "--version",
            version,
            "--output",
            str(metadata),
        ],
        dry_run=dry_run,
    )
    metadata_payload = None
    if metadata.exists():
        metadata_payload = json.loads(metadata.read_text(encoding="utf-8"))
    run(
        [
            *ossutil_command(
                oss_config,
                "cp",
                str(artifact_path),
                f"{bucket}/files/apps/desktop/{platform_dir}/{filename}",
                "--acl",
                "public-read",
                "--force",
            ),
        ],
        dry_run=dry_run,
    )
    run(
        [
            *ossutil_command(
                oss_config,
                "cp",
                str(artifact_path),
                f"{bucket}/files/apps/desktop/{platform_dir}/{latest_name}",
                "--acl",
                "public-read",
                "--force",
            ),
        ],
        dry_run=dry_run,
    )
    run(
        [
            *ossutil_command(
                oss_config,
                "cp",
                str(metadata),
                f"{bucket}/metadata/apps/desktop/{platform_dir}/{filename}.json",
                "--acl",
                "public-read",
                "--force",
            ),
        ],
        dry_run=dry_run,
    )
    run(
        [
            *ossutil_command(
                oss_config,
                "cp",
                str(metadata),
                f"{bucket}/metadata/apps/desktop/{platform_dir}/{latest_name}.json",
                "--acl",
                "public-read",
                "--force",
            ),
        ],
        dry_run=dry_run,
    )
    return metadata_payload


def merge_desktop_index(
    index: dict[str, Any],
    metadata: dict[str, Any],
    platform: str,
) -> dict[str, Any]:
    merged = dict(index)
    merged.setdefault("product", "desktop")
    merged.setdefault("platforms", {})
    merged.setdefault("files", {})
    merged["platforms"].setdefault(platform, {"latest": "", "versions": []})

    file_id = metadata["id"]
    platform_entry = merged["platforms"][platform]
    platform_entry["latest"] = file_id
    versions = platform_entry.setdefault("versions", [])
    if file_id not in versions:
        versions.insert(0, file_id)
    merged["files"][file_id] = metadata
    return merged


def write_desktop_index(index: dict[str, Any], output: Path) -> None:
    output.write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def refresh_cdn(command: str, *, dry_run: bool) -> None:
    if not command:
        print(
            "No CDN refresh command configured. Set DCLAW_CDN_REFRESH_COMMAND "
            "or pass --cdn-refresh-command.",
        )
        return
    run(shlex.split(command), dry_run=dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description="Release DClaw desktop to domestic OSS.")
    parser.add_argument("--platform", choices=["win", "mac", "all"], default="all")
    parser.add_argument(
        "--config",
        default=os.environ.get("DCLAW_DESKTOP_RELEASE_CONFIG", str(DEFAULT_CONFIG_PATH)),
        help="Local JSON config for OSS/CDN release settings.",
    )
    parser.add_argument("--index-url")
    parser.add_argument("--bucket")
    parser.add_argument(
        "--desktop-api-url",
        help="Remote API base URL embedded into the desktop launcher.",
    )
    parser.add_argument("--version", help="Override auto-bumped version.")
    parser.add_argument(
        "--cdn-refresh-command",
        default=None,
        help="Optional command used to refresh the domestic CDN after upload.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_release_config(args.config)
    index_url = args.index_url or config.index_url
    bucket = args.bucket or config.bucket
    desktop_api_url = args.desktop_api_url or config.desktop_api_url
    cdn_refresh_command = (
        args.cdn_refresh_command
        if args.cdn_refresh_command is not None
        else config.cdn_refresh_command
    )
    oss_config = materialize_ossutil_config(config.oss, dry_run=args.dry_run)

    index = load_index(index_url)
    version = args.version or next_patch_version(index, read_current_version())
    print(f"Desktop release version: {version}")
    if args.dry_run:
        print("Dry run: version files will not be modified.")
    else:
        write_version_files(REPO_ROOT, version)

    platforms = ["win", "mac"] if args.platform == "all" else [args.platform]
    merged_index = index
    for platform in platforms:
        artifact_path = _build_platform(
            platform,
            version,
            args.dry_run,
            desktop_api_url=desktop_api_url,
        )
        metadata = _upload_platform(
            platform,
            version,
            artifact_path,
            bucket,
            oss_config,
            args.dry_run,
        )
        if metadata:
            merged_index = merge_desktop_index(merged_index, metadata, platform)

    if not args.dry_run:
        index_path = REPO_ROOT / "desktop-index.json"
        write_desktop_index(merged_index, index_path)
        run(
            [
                *ossutil_command(
                    oss_config,
                    "cp",
                    str(index_path),
                    f"{bucket}/metadata/apps/desktop/index.json",
                    "--acl",
                    "public-read",
                    "--force",
                ),
            ],
        )
    refresh_cdn(cdn_refresh_command, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
