# -*- coding: utf-8 -*-
"""Packaged product agents and custom builtin skills."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from ..config.config import AgentProfileRef
from ..config.utils import load_config, save_config
from ..constant import WORKING_DIR
from .skill_system import SkillPoolService, ensure_skill_pool_initialized

logger = logging.getLogger(__name__)

PRODUCT_BUILTIN_AGENT_ORDER: tuple[str, ...] = (
    "default",
    "QwenPaw_QA_Agent_0.2",
    "qa",
    "fullstack_dev",
    "marketing_agent",
    "content_creation",
    "product_design",
    "data_analysis",
    "finance_research",
    "opc_company",
    "consultant",
    "legal",
)

_PROMPT_FILES = (
    "AGENTS.md",
    "SOUL.md",
    "PROFILE.md",
    "MEMORY.md",
    "HEARTBEAT.md",
)

_STALE_ONBOARDING_FILES = {"BOOTSTRAP.md"}


def get_product_builtin_workspaces_dir() -> Path:
    """Return the packaged product workspace asset directory."""
    return Path(__file__).resolve().parent / "builtin_workspaces"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _rewrite_working_dir_placeholders(value: Any, workspace_dir: Path) -> Any:
    if isinstance(value, dict):
        return {
            key: _rewrite_working_dir_placeholders(item, workspace_dir)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _rewrite_working_dir_placeholders(item, workspace_dir)
            for item in value
        ]
    if isinstance(value, str):
        return value.replace(
            "{WORKING_DIR}/workspaces/",
            f"{Path(WORKING_DIR)}/workspaces/",
        ).replace(
            str(Path(WORKING_DIR) / "workspaces" / workspace_dir.name),
            str(workspace_dir),
        )
    return value


def _write_agent_config_from_asset(
    asset_dir: Path,
    workspace_dir: Path,
    agent_id: str,
) -> None:
    raw_config = _read_json(asset_dir / "agent.json", {})
    if not isinstance(raw_config, dict) or not raw_config:
        logger.warning("Skipping builtin agent %s: missing agent.json", agent_id)
        return

    raw_config = _rewrite_working_dir_placeholders(raw_config, workspace_dir)
    raw_config["id"] = agent_id
    raw_config["workspace_dir"] = str(workspace_dir)
    target = workspace_dir / "agent.json"
    target.write_text(
        json.dumps(raw_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _copy_missing_prompt_files(asset_dir: Path, workspace_dir: Path) -> None:
    for filename in _PROMPT_FILES:
        source = asset_dir / filename
        target = workspace_dir / filename
        if source.exists() and not target.exists():
            shutil.copy2(source, target)


def _remove_stale_onboarding_files(workspace_dir: Path) -> None:
    """Remove old bootstrap prompts from managed product workspaces."""
    for candidate in workspace_dir.rglob("*"):
        if candidate.name not in _STALE_ONBOARDING_FILES:
            continue
        try:
            candidate.unlink()
            logger.info("Removed stale onboarding file: %s", candidate)
        except OSError as exc:
            logger.warning(
                "Could not remove stale onboarding file %s: %s",
                candidate,
                exc,
            )


def _normalize_agent_branding(workspace_dir: Path) -> None:
    """Patch old visible greetings in existing product agent configs."""
    config_path = workspace_dir / "agent.json"
    payload = _read_json(config_path, {})
    if not isinstance(payload, dict) or not payload:
        return

    changed = False
    channels = payload.get("channels")
    if isinstance(channels, dict):
        voice = channels.get("voice")
        if isinstance(voice, dict) and voice.get("welcome_greeting") == (
            "Hi! This is DClaw. How can I help you?"
        ):
            voice["welcome_greeting"] = "Hi! This is DClaw. How can I help you?"
            changed = True
        sip = channels.get("sip")
        if isinstance(sip, dict) and sip.get("welcome_greeting") == (
            "你好，我是DClaw"
        ):
            sip["welcome_greeting"] = "你好，我是DClaw"
            changed = True

    if changed:
        config_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _profile_contains_placeholder(content: str) -> bool:
    return any(
        marker in content
        for marker in (
            "挑个你喜欢的",
            "pick something you like",
            "AI？机器人？",
            "ghost in the machine",
        )
    )


def _product_profile_values(asset_dir: Path, agent_id: str) -> tuple[str, str]:
    agent_config = _read_json(asset_dir / "agent.json", {})
    agent_name = str(agent_config.get("name") or agent_id)
    description = str(agent_config.get("description") or "").strip()
    if agent_id == "default" or agent_name.lower() == "default":
        agent_name = "DClaw"
        description = (
            "面向实际任务交付的通用智能体，负责帮助用户拆解问题、"
            "执行操作、整理产物与持续推进。"
        )
    if not description:
        description = "DClaw 内置智能体，负责在对应领域协助用户完成任务。"
    return agent_name, description


def _write_normalized_profile(
    profile_path: Path,
    agent_name: str,
    description: str,
) -> None:
    profile_path.write_text(
        (
            "---\n"
            "summary: \"Agent 身份与用户资料\"\n"
            "read_when:\n"
            "  - 手动引导工作区\n"
            "---\n"
            "\n"
            "## 身份\n"
            "\n"
            f"- **名字：** {agent_name}\n"
            f"- **定位：** {description}\n"
            "- **风格：** 直接、友好、可靠。先理解上下文，"
            "再尽量自己完成；需要用户判断时才简洁确认。\n"
            "- **其他：** 不进行首次身份问卷，不反复询问"
            "“你是谁/我是谁”。每个会话可以有不同上下文，"
            "但内置身份由 DClaw 预设。\n"
            "\n"
            "\n"
            "## 用户资料\n"
            "\n"
            "*了解你在帮的人。边走边更新。*\n"
            "\n"
            "- **名字：**\n"
            "- **怎么叫他们：**\n"
            "- **代词：** *（可选）*\n"
            "- **笔记：**\n"
            "\n"
            "### 背景\n"
            "\n"
            "*（他们在意什么？在做啥项目？什么让他们烦？"
            "什么逗他们笑？边走边积累。）*\n"
        ),
        encoding="utf-8",
    )


def _iter_runtime_profile_paths(workspace_dir: Path):
    yield workspace_dir / "PROFILE.md"
    users_dir = workspace_dir / "users"
    if users_dir.exists():
        for child in users_dir.iterdir():
            if child.is_dir():
                yield child / "PROFILE.md"
    sessions_dir = workspace_dir / "sessions_data"
    if sessions_dir.exists():
        for child in sessions_dir.iterdir():
            if child.is_dir():
                yield child / "PROFILE.md"


def _normalize_profile_identity(
    asset_dir: Path,
    workspace_dir: Path,
    agent_id: str,
) -> None:
    """Replace placeholder identity prompts with concrete product identity."""
    agent_name, description = _product_profile_values(asset_dir, agent_id)
    for profile_path in _iter_runtime_profile_paths(workspace_dir):
        if not profile_path.exists():
            continue
        try:
            current = profile_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if _profile_contains_placeholder(current):
            _write_normalized_profile(profile_path, agent_name, description)


def _load_initial_skill_names(asset_dir: Path) -> list[str]:
    payload = _read_json(asset_dir / "initial_skills.json", [])
    if not isinstance(payload, list):
        return []
    names: list[str] = []
    for item in payload:
        name = str(item or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _install_initial_skills(
    workspace_dir: Path,
    skill_names: list[str],
) -> None:
    pool_service = SkillPoolService()
    install_names: list[str] = []
    for skill_name in [
        *pool_service.list_default_skill_names(),
        *skill_names,
    ]:
        if skill_name and skill_name not in install_names:
            install_names.append(skill_name)

    if not install_names:
        return
    for skill_name in install_names:
        result = pool_service.download_to_workspace(
            skill_name,
            workspace_dir,
            overwrite=False,
        )
        if result.get("success"):
            continue
        reason = result.get("reason", "unknown")
        if reason in {"same_version", "same_content", "already_exists"}:
            continue
        logger.warning(
            "Failed to seed builtin skill %s into %s: %s",
            skill_name,
            workspace_dir,
            reason,
        )


def _product_first_agent_order(existing_order: list[str], profiles) -> list[str]:
    ordered: list[str] = []
    for agent_id in PRODUCT_BUILTIN_AGENT_ORDER:
        if agent_id in profiles and agent_id not in ordered:
            ordered.append(agent_id)
    for agent_id in existing_order:
        if agent_id in profiles and agent_id not in ordered:
            ordered.append(agent_id)
    for agent_id in profiles:
        if agent_id not in ordered:
            ordered.append(agent_id)
    return ordered


def ensure_product_builtin_assets(
    *,
    distribute_default_skills: bool = True,
) -> None:
    """Seed packaged product agents and custom skills into WORKING_DIR.

    This makes a fresh Docker or local deployment start with the product's
    curated agents and skills instead of an empty shell. Runtime history,
    generated files, and auth data are intentionally not packaged.
    """
    assets_root = get_product_builtin_workspaces_dir()
    if not assets_root.exists():
        return

    ensure_skill_pool_initialized(
        distribute_defaults=distribute_default_skills,
    )
    config = load_config()
    changed_config = False

    for agent_id in PRODUCT_BUILTIN_AGENT_ORDER:
        asset_dir = assets_root / agent_id
        if not asset_dir.is_dir():
            continue

        agent_ref = config.agents.profiles.get(agent_id)
        if agent_ref is None:
            workspace_dir = Path(WORKING_DIR) / "workspaces" / agent_id
            config.agents.profiles[agent_id] = AgentProfileRef(
                id=agent_id,
                workspace_dir=str(workspace_dir),
                enabled=True,
            )
            changed_config = True
        else:
            workspace_dir = Path(agent_ref.workspace_dir).expanduser()

        workspace_dir.mkdir(parents=True, exist_ok=True)
        _remove_stale_onboarding_files(workspace_dir)
        if not (workspace_dir / "agent.json").exists():
            _write_agent_config_from_asset(asset_dir, workspace_dir, agent_id)
        else:
            _normalize_agent_branding(workspace_dir)
        _copy_missing_prompt_files(asset_dir, workspace_dir)
        _normalize_agent_branding(workspace_dir)
        _normalize_profile_identity(asset_dir, workspace_dir, agent_id)
        _install_initial_skills(
            workspace_dir,
            _load_initial_skill_names(asset_dir),
        )

    next_order = _product_first_agent_order(
        list(config.agents.agent_order),
        config.agents.profiles,
    )
    if next_order != list(config.agents.agent_order):
        config.agents.agent_order = next_order
        changed_config = True

    if config.agents.active_agent not in config.agents.profiles:
        config.agents.active_agent = "default"
        changed_config = True

    if changed_config:
        save_config(config)
