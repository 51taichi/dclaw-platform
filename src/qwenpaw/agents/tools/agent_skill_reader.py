# -*- coding: utf-8 -*-
"""Read-only access to files inside the current Agent's registered Skills."""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse


MAX_AGENT_SKILL_FILE_BYTES = 256 * 1024
ALLOWED_AGENT_SKILL_SUFFIXES = frozenset(
    {".md", ".txt", ".json", ".yaml", ".yml"}
)


def _response(text: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _safe_relative_path(value: str) -> PurePosixPath | None:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        return None
    normalized = unicodedata.normalize("NFC", value)
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.suffix.lower() not in ALLOWED_AGENT_SKILL_SUFFIXES
    ):
        return None
    return path


def build_read_agent_skill_tool(
    registered_skills: Mapping[str, Mapping[str, Any]],
):
    """Build a reader scoped to the Skills already registered for one request."""

    allowed = {
        str(name): Path(str(metadata.get("dir", "")))
        for name, metadata in registered_skills.items()
        if isinstance(metadata, Mapping) and metadata.get("dir")
    }

    async def read_agent_skill(
        skill_name: str,
        relative_path: str = "SKILL.md",
    ) -> ToolResponse:
        """Read instructions from a Skill registered for the current Agent.

        Read `SKILL.md` before using a Skill. If those instructions refer to a
        supporting text file inside the same Skill, call this tool again with
        its relative path. This tool cannot access ordinary workspace files.

        Args:
            skill_name (`str`): Exact registered Skill name.
            relative_path (`str`): Text path inside that Skill. Defaults to
                `SKILL.md`.
        """
        root_path = allowed.get(skill_name)
        if root_path is None:
            return _response("Error: skill is not registered for this request.")

        relative = _safe_relative_path(relative_path)
        if relative is None:
            return _response("Error: unsafe or unsupported skill file path.")

        try:
            if root_path.is_symlink():
                return _response("Error: unsafe skill file path.")
            root = root_path.resolve(strict=True)
            if not root.is_dir():
                return _response("Error: skill file is unavailable.")

            candidate = root_path
            for part in relative.parts:
                candidate = candidate / part
                if candidate.is_symlink():
                    return _response("Error: unsafe skill file path.")

            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(root) or not resolved.is_file():
                return _response("Error: skill file is unavailable.")

            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(resolved, flags)
            try:
                size = os.fstat(descriptor).st_size
                if size > MAX_AGENT_SKILL_FILE_BYTES:
                    return _response("Error: skill file exceeds the read limit.")
                with os.fdopen(descriptor, "rb", closefd=False) as handle:
                    data = handle.read(MAX_AGENT_SKILL_FILE_BYTES + 1)
            finally:
                os.close(descriptor)
            if len(data) > MAX_AGENT_SKILL_FILE_BYTES:
                return _response("Error: skill file exceeds the read limit.")
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                return _response("Error: skill file is not valid UTF-8 text.")
            return _response(text)
        except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
            return _response("Error: skill file is unavailable.")

    return read_agent_skill


__all__ = [
    "ALLOWED_AGENT_SKILL_SUFFIXES",
    "MAX_AGENT_SKILL_FILE_BYTES",
    "build_read_agent_skill_tool",
]
