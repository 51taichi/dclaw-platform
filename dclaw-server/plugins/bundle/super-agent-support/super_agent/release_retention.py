"""Bound the plugin-owned Super Expert release history."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any


MAX_RELEASES = 5
PACKAGE_TYPES = frozenset({"super_expert", "super_expert_public"})
logger = logging.getLogger(__name__)
_lock = threading.RLock()


def _journal_path(root: Path, agent_id: str) -> Path:
    name = hashlib.sha256(agent_id.encode("utf-8")).hexdigest() + ".json"
    return root / "release_retention" / name


def _read_journal(path: Path, agent_id: str) -> set[str]:
    if not path.exists():
        return set()
    if path.is_symlink() or not path.is_file():
        raise ValueError("release retention journal is invalid")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or data.get("agent_id") != agent_id
        or not isinstance(data.get("release_ids"), list)
        or any(not isinstance(item, str) for item in data["release_ids"])
    ):
        raise ValueError("release retention journal is invalid")
    return set(data["release_ids"])


def _write_journal(path: Path, agent_id: str, release_ids: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps({"agent_id": agent_id, "release_ids": sorted(release_ids)}),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _release_path(service: Any, agent_id: str, release_id: str) -> Path:
    base = (service.root / "releases" / agent_id).resolve()
    path = service.release_root(agent_id, release_id)
    if (
        not release_id
        or Path(release_id).name != release_id
        or release_id in {".", ".."}
        or path.is_symlink()
        or path.resolve() != base / release_id
        or not path.resolve().is_relative_to(base)
    ):
        raise ValueError("release retention path is invalid")
    return path


def _cleanup_pending(service: Any, agent_id: str, path: Path) -> None:
    pending = _read_journal(path, agent_id)
    if not pending:
        path.unlink(missing_ok=True)
        return
    record = service.get_agent(agent_id)
    live = {item.release_id for item in record.releases} if record else set()
    remaining: set[str] = set()
    for release_id in pending:
        if release_id in live:
            continue
        try:
            directory = _release_path(service, agent_id, release_id)
            if directory.exists():
                if not directory.is_dir():
                    raise ValueError("release retention path is invalid")
                shutil.rmtree(directory)
        except (OSError, ValueError):
            remaining.add(release_id)
            logger.exception("Failed to remove retired release %s", release_id)
    if remaining:
        _write_journal(path, agent_id, remaining)
    else:
        path.unlink(missing_ok=True)


def retain_releases(service: Any, agent_id: str, release_id: str) -> None:
    """Retain at most five records, protecting the running release."""
    with _lock:
        record = service.get_agent(agent_id)
        if record is None or release_id not in {
            item.release_id for item in record.releases
        }:
            raise ValueError("release retention target is unavailable")
        journal = _journal_path(service.root, agent_id)
        pending = _read_journal(journal, agent_id)
        if len(record.releases) > MAX_RELEASES:
            if any(item.package_type not in PACKAGE_TYPES for item in record.releases):
                raise ValueError("mixed package release history needs review")
            ordered = sorted(
                record.releases,
                key=lambda item: (item.installed_at, item.release_id),
                reverse=True,
            )
            retained = {item.release_id for item in ordered[:MAX_RELEASES]}
            # A running release occupies one of the five slots, even if older.
            if record.active_release_id and record.active_release_id not in retained:
                retained.remove(ordered[MAX_RELEASES - 1].release_id)
                retained.add(record.active_release_id)
            retired = {
                item.release_id for item in record.releases
                if item.release_id not in retained
            }
            for item in retired:
                _release_path(service, agent_id, item)
            _write_journal(journal, agent_id, pending | retired)
            service.registry.upsert_agent(record.model_copy(update={
                "releases": [
                    item for item in record.releases
                    if item.release_id in retained
                ],
            }))
        try:
            _cleanup_pending(service, agent_id, journal)
        except (OSError, ValueError, json.JSONDecodeError):
            logger.exception("Retired release cleanup remains pending for %s", agent_id)


def reconcile_release_retention(service: Any) -> None:
    """Apply the limit to preexisting histories when the plugin starts."""
    for record in service.list_agents():
        if record.releases and record.releases[-1].package_type in PACKAGE_TYPES:
            try:
                retain_releases(
                    service, record.agent_id, record.releases[-1].release_id,
                )
            except (OSError, ValueError, json.JSONDecodeError):
                logger.exception("Release retention failed for %s", record.agent_id)
