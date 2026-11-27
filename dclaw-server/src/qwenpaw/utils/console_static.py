# -*- coding: utf-8 -*-
"""Resolve the web console static assets directory (shared by app and CLI)."""
from __future__ import annotations

import os
from pathlib import Path

from ..constant import EnvVarLoader

# Primary env key (``COPAW_CONSOLE_STATIC_DIR`` is accepted as a legacy
# fallback via :class:`~qwenpaw.constant.EnvVarLoader`).
CONSOLE_STATIC_ENV = "QWENPAW_CONSOLE_STATIC_DIR"


def _resolve_console_static_dir_from(
    pkg_dir: Path,
    cwd: Path,
    static_dir: str,
) -> str:
    if static_dir:
        return static_dir

    repo_dir = pkg_dir.parent.parent
    repo_dist = repo_dir / "console" / "dist"
    is_source_checkout = (
        (repo_dir / "console" / "package.json").is_file()
        and (repo_dir / "src" / "qwenpaw").is_dir()
    )
    if (
        is_source_checkout
        and repo_dist.is_dir()
        and (repo_dist / "index.html").is_file()
    ):
        return str(repo_dist)

    candidate = pkg_dir / "console"
    if candidate.is_dir() and (candidate / "index.html").is_file():
        return str(candidate)

    if repo_dist.is_dir() and (repo_dist / "index.html").is_file():
        return str(repo_dist)

    for subdir in ("console/dist", "console_dist"):
        candidate = cwd / subdir
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return str(candidate)

    return str(cwd / "console" / "dist")


def resolve_console_static_dir() -> str:
    """Return the directory expected to contain ``index.html`` for the console.

    Resolution order: env override, repo ``console/dist`` for source checkouts,
    package ``qwenpaw/console``, then cwd fallbacks.
    """
    pkg_dir = Path(__file__).resolve().parent.parent
    cwd = Path(os.getcwd())
    static_dir = EnvVarLoader.get_str("QWENPAW_CONSOLE_STATIC_DIR")
    return _resolve_console_static_dir_from(pkg_dir, cwd, static_dir)


def find_qwenpaw_source_repo_root() -> Path | None:
    """Return the git checkout root if this Python
    is running from DClaw source.

    Looks upward from :mod:`qwenpaw` for ``console/package.json``,
    ``console/package-lock.json``, and ``src/qwenpaw/``
    (bundled static target).
    Returns ``None`` for a normal pip/wheel install.
    """
    try:
        import qwenpaw  # noqa: PLC0415 — avoid import cycle at module load
    except Exception:  # pylint: disable=broad-exception-caught
        return None
    cur = Path(qwenpaw.__file__).resolve().parent
    for _ in range(20):
        con = cur / "console"
        if (
            (con / "package.json").is_file()
            and (con / "package-lock.json").is_file()
            and (cur / "src" / "qwenpaw").is_dir()
        ):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None
