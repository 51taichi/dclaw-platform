# -*- coding: utf-8 -*-
from pathlib import Path

from qwenpaw.utils.console_static import _resolve_console_static_dir_from


def _touch_index(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    index = directory / "index.html"
    index.write_text("<!doctype html>", encoding="utf-8")
    return directory


def test_source_checkout_prefers_fresh_console_dist_over_packaged_console(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "qwenpaw"
    pkg_dir = repo / "src" / "qwenpaw"
    pkg_dir.mkdir(parents=True)
    (repo / "console").mkdir()
    (repo / "console" / "package.json").write_text("{}", encoding="utf-8")

    packaged_console = _touch_index(pkg_dir / "console")
    fresh_dist = _touch_index(repo / "console" / "dist")

    assert (
        _resolve_console_static_dir_from(pkg_dir, tmp_path, "")
        == str(fresh_dist)
    )
    assert fresh_dist != packaged_console


def test_console_static_env_override_still_wins(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "src" / "qwenpaw"
    pkg_dir.mkdir(parents=True)
    override = tmp_path / "custom-static"

    assert (
        _resolve_console_static_dir_from(pkg_dir, tmp_path, str(override))
        == str(override)
    )
