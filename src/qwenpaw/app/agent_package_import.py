# -*- coding: utf-8 -*-
"""Agent package discovery and import helpers."""

from __future__ import annotations

import io
import json
import logging
import re
import shutil
import tempfile
import zipfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..agents.skill_system import get_workspace_skills_dir
from ..agents.skill_system.registry import reconcile_workspace_manifest
from ..agents.skill_system.store import (
    copy_skill_dir,
    normalize_skill_dir_name,
    scan_skill_dir_or_raise,
)
from ..agents.utils import normalize_agent_language
from ..config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    generate_short_agent_id,
    sanitize_agent_id,
    save_agent_config,
    validate_agent_id,
)
from ..config.utils import load_config, save_config
from ..constant import WORKING_DIR

logger = logging.getLogger(__name__)

_MAX_ZIP_BYTES = 200 * 1024 * 1024
_IGNORED_NAMES = {
    "__MACOSX",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    "__pycache__",
    ".git",
    ".svn",
    "node_modules",
    ".venv",
}
_INVALID_ID_CHARS = re.compile(r"[^a-zA-Z0-9_-]+")


class AgentPackageError(ValueError):
    """Raised when an uploaded agent package is invalid."""


class AgentPackageConflict(AgentPackageError):
    """Raised when importing would overwrite an existing agent/workspace."""

    def __init__(self, detail: dict[str, Any]) -> None:
        self.detail = detail
        super().__init__(str(detail))


class AgentPackagePreview(BaseModel):
    """Preflight details for an uploaded agent package."""

    id: str
    name: str
    description: str = ""
    root_path: str
    agent_json_path: str
    skills: list[str] = Field(default_factory=list)
    files_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    has_conflict: bool = False
    suggested_id: str | None = None


class AgentPackageImportResult(BaseModel):
    """Result returned after an agent package has been installed."""

    imported: bool
    agent_id: str
    name: str
    workspace_dir: str
    skills: list[str] = Field(default_factory=list)
    files_count: int = 0
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class _DiscoveredSkill:
    name: str
    source_dir: Path
    relative_path: str


@dataclass(frozen=True)
class _PackageDiscovery:
    root: Path
    agent_json_path: Path
    agent_payload: dict[str, Any]
    skills: list[_DiscoveredSkill]
    files_count: int


def _is_ignored_name(name: str) -> bool:
    return name in _IGNORED_NAMES or name.startswith("._")


def _is_ignored_path(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(_is_ignored_name(part) for part in rel.parts)


def _visible_children(path: Path) -> list[Path]:
    return sorted(
        child
        for child in path.iterdir()
        if not _is_ignored_name(child.name)
    )


def _iter_visible_files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*"):
        if _is_ignored_path(path, root):
            continue
        if path.is_file():
            yield path


def _relative_display(path: Path, root: Path) -> str:
    if path == root:
        return "."
    return path.relative_to(root).as_posix()


def _contains_cjk(value: str) -> bool:
    return any(
        "\u3400" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
        for char in value
    )


def _looks_legacy_mojibake(value: str) -> bool:
    if _contains_cjk(value):
        return False
    return any(
        "\u0370" <= char <= "\u03ff"
        or "\u2500" <= char <= "\u257f"
        for char in value
    )


def _decode_zip_member_name(info: zipfile.ZipInfo) -> str:
    """Return a usable member name for archives missing UTF-8 filename flags.

    Some WeChat/Windows exported zips store UTF-8 or GBK bytes without setting
    the ZIP UTF-8 flag. Python decodes those names as CP437, which produces
    paths like ``τƒÑΦ»åσ║ô`` instead of ``知识库``.
    """
    name = info.filename
    if info.flag_bits & 0x800 and not _looks_legacy_mojibake(name):
        return name

    try:
        raw_name = name.encode("cp437")
    except UnicodeEncodeError:
        return name

    for encoding in ("utf-8", "gb18030", "gbk", "big5"):
        try:
            candidate = raw_name.decode(encoding)
        except UnicodeDecodeError:
            continue
        if candidate == name:
            return name
        if _contains_cjk(candidate) or _looks_legacy_mojibake(name):
            return candidate

    return name


def _extract_zip(data: bytes) -> Iterator[Path]:
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise AgentPackageError("Uploaded file is not a valid zip archive")

    tmp_dir = Path(tempfile.mkdtemp(prefix="qwenpaw_agent_import_"))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            total = sum(info.file_size for info in zf.infolist())
            if total > _MAX_ZIP_BYTES:
                raise AgentPackageError("Uncompressed zip exceeds 200MB limit")

            root_path = tmp_dir.resolve()
            for info in zf.infolist():
                member_name = _decode_zip_member_name(info)
                target = (tmp_dir / member_name).resolve()
                if not target.is_relative_to(root_path):
                    raise AgentPackageError(
                        f"Unsafe path in zip: {member_name}",
                    )
                file_type = info.external_attr >> 16
                if file_type & 0o120000 == 0o120000:
                    raise AgentPackageError(
                        f"Symlink not allowed in zip: {member_name}",
                    )

                if _is_ignored_path(target, root_path):
                    continue
                if info.is_dir() or member_name.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
        yield tmp_dir
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


_extracted_package = contextmanager(_extract_zip)


def _read_agent_payload(agent_json_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(agent_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AgentPackageError(
            f"Invalid agent.json: {exc.msg}",
        ) from exc
    if not isinstance(payload, dict):
        raise AgentPackageError("agent.json must contain a JSON object")
    return payload


def _find_agent_json(scan_root: Path) -> Path:
    candidates = [
        path
        for path in scan_root.rglob("agent.json")
        if path.is_file() and not _is_ignored_path(path, scan_root)
    ]
    if not candidates:
        raise AgentPackageError("No agent.json found in uploaded package")
    if len(candidates) > 1:
        display = ", ".join(
            path.relative_to(scan_root).as_posix()
            for path in candidates
        )
        raise AgentPackageError(
            f"Multiple agent.json files found: {display}",
        )
    return candidates[0]


def _resolve_package_root(tmp_dir: Path, agent_json_path: Path) -> Path:
    children = _visible_children(tmp_dir)
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return tmp_dir


def _parse_skill_frontmatter_name(skill_md_path: Path) -> str:
    try:
        text = skill_md_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = skill_md_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if not stripped.startswith("name:"):
            continue
        value = stripped.split(":", 1)[1].strip().strip("\"'")
        return value
    return ""


def _skill_name_for_dir(skill_dir: Path) -> str:
    raw_name = _parse_skill_frontmatter_name(skill_dir / "SKILL.md")
    for candidate in (raw_name, skill_dir.name):
        if not candidate:
            continue
        try:
            return normalize_skill_dir_name(candidate)
        except Exception:
            continue
    return normalize_skill_dir_name(skill_dir.name)


def _discover_skills(package_root: Path) -> list[_DiscoveredSkill]:
    found: list[_DiscoveredSkill] = []
    seen_names: set[str] = set()
    seen_roots: list[Path] = []

    for skill_md_path in sorted(package_root.rglob("SKILL.md")):
        if _is_ignored_path(skill_md_path, package_root):
            continue
        skill_dir = skill_md_path.parent
        if any(skill_dir.is_relative_to(root) for root in seen_roots):
            continue
        name = _skill_name_for_dir(skill_dir)
        if name in seen_names:
            logger.warning(
                "Skipping duplicate skill '%s' from agent package path %s",
                name,
                skill_dir,
            )
            continue
        found.append(
            _DiscoveredSkill(
                name=name,
                source_dir=skill_dir,
                relative_path=skill_dir.relative_to(package_root).as_posix(),
            ),
        )
        seen_names.add(name)
        seen_roots.append(skill_dir)
    return found


def _discover_package(tmp_dir: Path) -> _PackageDiscovery:
    if not _visible_children(tmp_dir):
        raise AgentPackageError("Uploaded package is empty")

    scan_root = tmp_dir
    children = _visible_children(tmp_dir)
    if len(children) == 1 and children[0].is_dir():
        scan_root = children[0]

    agent_json_path = _find_agent_json(scan_root)
    package_root = _resolve_package_root(tmp_dir, agent_json_path)
    if not agent_json_path.is_relative_to(package_root):
        package_root = agent_json_path.parent

    payload = _read_agent_payload(agent_json_path)
    return _PackageDiscovery(
        root=package_root,
        agent_json_path=agent_json_path,
        agent_payload=payload,
        skills=_discover_skills(package_root),
        files_count=sum(1 for _ in _iter_visible_files(package_root)),
    )


def _coerce_package_agent_id(raw_id: str, fallback_name: str) -> tuple[str, str | None]:
    raw_id = sanitize_agent_id(raw_id)
    if raw_id:
        try:
            validate_agent_id(raw_id, set())
            return raw_id, None
        except ValueError:
            pass

    source = raw_id or fallback_name or "imported_agent"
    candidate = _INVALID_ID_CHARS.sub("_", source).strip("_-")
    if not candidate or not candidate[0].isalnum() or not candidate[-1].isalnum():
        candidate = "imported_agent"
    candidate = candidate[:64].strip("_-") or "imported_agent"
    try:
        validate_agent_id(candidate, set())
        return (
            candidate,
            f"Package agent id '{source}' was normalized to '{candidate}'.",
        )
    except ValueError:
        fallback = generate_short_agent_id()
        return fallback, f"Package agent id '{source}' was replaced with '{fallback}'."


def _resolve_agent_id(
    payload: dict[str, Any],
    requested_id: str | None,
    warnings: list[str],
) -> str:
    if requested_id and requested_id.strip():
        candidate = sanitize_agent_id(requested_id)
        validate_agent_id(candidate, set())
        return candidate

    raw_id = str(payload.get("id") or "").strip()
    name = str(payload.get("name") or "").strip()
    candidate, warning = _coerce_package_agent_id(raw_id, name)
    if warning:
        warnings.append(warning)
    return candidate


def _suggest_agent_id(base: str, existing_ids: Iterable[str]) -> str:
    existing = set(existing_ids)
    stem = base[:60].strip("_-") or "imported_agent"
    for index in range(2, 102):
        suffix = f"_{index}"
        candidate = f"{stem[:64 - len(suffix)]}{suffix}"
        try:
            validate_agent_id(candidate, set())
        except ValueError:
            candidate = f"imported_agent{suffix}"
        if candidate not in existing:
            return candidate
    return generate_short_agent_id()


def _default_workspace_dir(agent_id: str) -> Path:
    return Path(WORKING_DIR) / "workspaces" / agent_id


def _build_preview(
    discovery: _PackageDiscovery,
    *,
    extract_root: Path,
    existing_ids: set[str] | None,
    requested_id: str | None,
) -> AgentPackagePreview:
    warnings: list[str] = []
    agent_id = _resolve_agent_id(
        discovery.agent_payload,
        requested_id,
        warnings,
    )
    existing_ids = existing_ids or set()
    workspace_dir = _default_workspace_dir(agent_id)
    has_agent_conflict = agent_id in existing_ids
    has_workspace_conflict = agent_id not in existing_ids and workspace_dir.exists()
    has_conflict = has_agent_conflict or has_workspace_conflict
    suggested_id = _suggest_agent_id(agent_id, existing_ids) if has_conflict else None
    if has_agent_conflict:
        warnings.append(
            f"Agent id '{agent_id}' already exists; import can update it.",
        )
    elif has_workspace_conflict:
        warnings.append(
            f"Agent workspace '{workspace_dir}' already exists; import can replace and register it.",
        )
    if discovery.agent_json_path.parent != discovery.root:
        warnings.append(
            "agent.json was found below the package root and will be "
            "normalized to the imported workspace root.",
        )
    if not discovery.skills:
        warnings.append("No skills were found in the package.")

    return AgentPackagePreview(
        id=agent_id,
        name=str(discovery.agent_payload.get("name") or agent_id),
        description=str(discovery.agent_payload.get("description") or ""),
        root_path=_relative_display(discovery.root, extract_root),
        agent_json_path=_relative_display(discovery.agent_json_path, extract_root),
        skills=sorted(skill.name for skill in discovery.skills),
        files_count=discovery.files_count,
        warnings=warnings,
        has_conflict=has_conflict,
        suggested_id=suggested_id,
    )


def preview_agent_package(
    data: bytes,
    *,
    existing_ids: set[str] | None = None,
    requested_id: str | None = None,
) -> AgentPackagePreview:
    """Inspect an uploaded agent package without writing anything."""
    with _extracted_package(data) as tmp_dir:
        discovery = _discover_package(tmp_dir)
        return _build_preview(
            discovery,
            extract_root=tmp_dir,
            existing_ids=existing_ids,
            requested_id=requested_id,
        )


def _copy_package_files(source_root: Path, workspace_dir: Path) -> None:
    workspace_dir.mkdir(parents=True, exist_ok=True)

    def _ignore(_dir: str, names: list[str]) -> set[str]:
        return {name for name in names if _is_ignored_name(name)}

    for item in source_root.iterdir():
        if _is_ignored_name(item.name):
            continue
        target = workspace_dir / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target, ignore=_ignore)
        elif item.is_file():
            shutil.copy2(item, target)


def _install_package_workspace(
    discovery: _PackageDiscovery,
    workspace_dir: Path,
) -> None:
    _copy_package_files(discovery.root, workspace_dir)
    _install_discovered_skills(discovery.skills, workspace_dir)
    reconcile_workspace_manifest(workspace_dir)


def _install_discovered_skills(
    skills: list[_DiscoveredSkill],
    workspace_dir: Path,
) -> None:
    skills_dir = get_workspace_skills_dir(workspace_dir)
    skills_dir.mkdir(parents=True, exist_ok=True)
    for skill in skills:
        scan_skill_dir_or_raise(skill.source_dir, skill.name)
        copy_skill_dir(skill.source_dir, skills_dir / skill.name)


def _build_agent_config(
    payload: dict[str, Any],
    *,
    agent_id: str,
    workspace_dir: Path,
) -> AgentProfileConfig:
    normalized = dict(payload)
    normalized["id"] = agent_id
    normalized["name"] = str(normalized.get("name") or agent_id)
    normalized["description"] = str(normalized.get("description") or "")
    normalized["workspace_dir"] = str(workspace_dir)
    if normalized.get("language"):
        normalized["language"] = normalize_agent_language(
            str(normalized.get("language")),
        )
    return AgentProfileConfig(**normalized)


def import_agent_package(
    data: bytes,
    *,
    requested_id: str | None = None,
    enabled: bool = True,
    mode: str = "create",
) -> AgentPackageImportResult:
    """Install an uploaded agent package as a configured local agent."""
    if mode not in {"create", "update"}:
        raise AgentPackageError("Import mode must be 'create' or 'update'")

    config = load_config()
    existing_ids = set(config.agents.profiles.keys())

    with _extracted_package(data) as tmp_dir:
        discovery = _discover_package(tmp_dir)
        preview = _build_preview(
            discovery,
            extract_root=tmp_dir,
            existing_ids=existing_ids,
            requested_id=requested_id,
        )
        agent_id = preview.id

        if preview.has_conflict and mode != "update":
            raise AgentPackageConflict(
                {
                    "reason": "agent_id_conflict",
                    "agent_id": agent_id,
                    "suggested_id": preview.suggested_id,
                },
            )
        try:
            validation_existing_ids = (
                existing_ids - {agent_id}
                if mode == "update"
                else existing_ids
            )
            validate_agent_id(agent_id, validation_existing_ids)
        except ValueError as exc:
            raise AgentPackageError(str(exc)) from exc

        existing_ref = config.agents.profiles.get(agent_id)
        workspace_dir = (
            Path(existing_ref.workspace_dir).expanduser()
            if mode == "update" and existing_ref is not None
            else _default_workspace_dir(agent_id)
        )
        if (
            mode == "update"
            and agent_id not in existing_ids
            and not workspace_dir.exists()
        ):
            raise AgentPackageError(
                f"Agent '{agent_id}' does not exist and cannot be updated.",
            )
        if mode == "create" and workspace_dir.exists():
            raise AgentPackageConflict(
                {
                    "reason": "workspace_exists",
                    "agent_id": agent_id,
                    "workspace_dir": str(workspace_dir),
                    "suggested_id": _suggest_agent_id(agent_id, existing_ids),
                },
            )

        agent_config = _build_agent_config(
            discovery.agent_payload,
            agent_id=agent_id,
            workspace_dir=workspace_dir,
        )

        previous_ref = config.agents.profiles.get(agent_id)
        previous_order = list(config.agents.agent_order)
        config_saved = False
        backup_dir: Path | None = None
        staging_dir: Path | None = None
        swapped_workspace = False
        try:
            if mode == "update":
                workspace_parent = workspace_dir.parent
                workspace_parent.mkdir(parents=True, exist_ok=True)
                staging_dir = Path(
                    tempfile.mkdtemp(
                        prefix=f".{agent_id}_import_",
                        dir=str(workspace_parent),
                    ),
                )
                _install_package_workspace(discovery, staging_dir)

                if workspace_dir.exists():
                    backup_dir = Path(
                        tempfile.mkdtemp(
                            prefix=f".{agent_id}_backup_",
                            dir=str(workspace_parent),
                        ),
                    )
                    shutil.rmtree(backup_dir)
                    workspace_dir.rename(backup_dir)
                staging_dir.rename(workspace_dir)
                staging_dir = None
                swapped_workspace = True
            else:
                _install_package_workspace(discovery, workspace_dir)

            agent_ref = AgentProfileRef(
                id=agent_id,
                workspace_dir=str(workspace_dir),
                enabled=enabled,
            )
            config.agents.profiles[agent_id] = agent_ref
            ordered_ids: list[str] = []
            for existing_id in config.agents.agent_order:
                if (
                    existing_id in config.agents.profiles
                    and existing_id not in ordered_ids
                ):
                    ordered_ids.append(existing_id)
            if agent_id not in ordered_ids:
                ordered_ids.append(agent_id)
            for existing_id in config.agents.profiles:
                if existing_id not in ordered_ids:
                    ordered_ids.append(existing_id)
            config.agents.agent_order = ordered_ids
            save_config(config)
            config_saved = True
            save_agent_config(agent_id, agent_config)
        except Exception:
            if staging_dir is not None:
                shutil.rmtree(staging_dir, ignore_errors=True)
            if swapped_workspace:
                shutil.rmtree(workspace_dir, ignore_errors=True)
                if backup_dir is not None and backup_dir.exists():
                    backup_dir.rename(workspace_dir)
                    backup_dir = None
            elif mode == "create":
                shutil.rmtree(workspace_dir, ignore_errors=True)

            if mode == "update":
                if previous_ref is not None:
                    config.agents.profiles[agent_id] = previous_ref
                else:
                    config.agents.profiles.pop(agent_id, None)
                config.agents.agent_order = previous_order
                if config_saved:
                    save_config(config)
            elif agent_id not in existing_ids:
                config.agents.profiles.pop(agent_id, None)
                config.agents.agent_order = [
                    existing_id
                    for existing_id in config.agents.agent_order
                    if existing_id != agent_id
                ]
                if config_saved:
                    save_config(config)
            raise
        finally:
            if backup_dir is not None:
                shutil.rmtree(backup_dir, ignore_errors=True)

    return AgentPackageImportResult(
        imported=True,
        agent_id=agent_id,
        name=agent_config.name,
        workspace_dir=str(workspace_dir),
        skills=preview.skills,
        files_count=preview.files_count,
        warnings=preview.warnings,
    )
