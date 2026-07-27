"""Helpers for separating user-facing task artifacts from agent internals."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable


INTERNAL_TASK_FILE_NAMES = frozenset(
    {
        "agent.json",
        "agent_config.json",
        "memory_file_metadata.json",
        "MEMORY.md",
        "HEARTBEAT.md",
        "BOOTSTRAP.md",
        "SOUL.md",
        "PROFILE.md",
        "AGENTS.md",
        "jobs.json",
        "chats.json",
        "config.json",
        "cloud_docs.json",
        "skills.json",
        "skill.json",
        "token_usage.json",
        "qwenpaw_app.log",
        "qwenpaw_app_new.log",
        "overview.md.lock",
        ".bootstrap_completed",
        ".reme_store_v1",
        ".skill.json.lock",
    },
)

INTERNAL_TASK_DIR_NAMES = frozenset(
    {
        ".git",
        ".github",
        ".gemini",
        "__pycache__",
        ".pytest_cache",
        "browser",
        "cloud_docs",
        "dialog",
        "draft",
        "embedding_cache",
        "file_store",
        "logs",
        "memory",
        "missions",
        "node_modules",
        "sessions",
        "skills",
        "tool_result",
        "tool_results",
        "_work",
        "attachments",
        "input",
        "inputs",
        "source",
        "sources",
        "uploads",
        "上传",
        "附件",
        "输入",
        "原始资料",
        "参考资料",
        "补充资料",
        "资料库",
        "venv",
    },
)

PRIMARY_DELIVERABLE_EXTENSIONS = frozenset(
    {
        ".docx",
        ".html",
        ".htm",
        ".pdf",
        ".pptx",
        ".xlsx",
    },
)

IMAGEGEN_MEDIA_PATTERN = re.compile(
    r"(^|/)media/imagegen/imagegen_[^/]+\.(?:png|jpe?g|webp|gif|bmp|svg)$",
    re.IGNORECASE,
)


def is_internal_task_file(path: str) -> bool:
    """Return true when a path is agent runtime state, not a user deliverable."""
    parts = Path(path).parts
    if not parts:
        return True

    if any(part.startswith(".") for part in parts):
        return True

    if any(part.endswith("_render_qa") or part == "render_qa" for part in parts[:-1]):
        return True

    if any(part in INTERNAL_TASK_DIR_NAMES for part in parts[:-1]):
        return True

    filename = parts[-1]
    if filename in INTERNAL_TASK_FILE_NAMES:
        return True

    if filename.endswith(".presentation.compose.json"):
        return True

    if filename.endswith(".imagegen.json"):
        return True

    if filename.endswith(".lock") or filename.endswith(".log"):
        return True

    return False


def _is_imagegen_media_file(path: str) -> bool:
    return bool(IMAGEGEN_MEDIA_PATTERN.search(path.replace("\\", "/")))


def _has_primary_deliverable(files: Iterable[str]) -> bool:
    return any(
        Path(file).suffix.lower() in PRIMARY_DELIVERABLE_EXTENSIONS
        for file in files
    )


def filter_user_task_files(files: Iterable[str]) -> list[str]:
    """Keep user-facing task files, preserving order and removing duplicates."""
    result: list[str] = []
    seen: set[str] = set()
    for file in files:
        if not file or is_internal_task_file(file) or file in seen:
            continue
        seen.add(file)
        result.append(file)
    if _has_primary_deliverable(result):
        result = [file for file in result if not _is_imagegen_media_file(file)]
    return result


def strip_session_data_prefix(path: str, session_id: str | None = None) -> str:
    """Return the display path for a file inside ``sessions_data/<session>``."""
    parts = Path(path).parts
    if len(parts) < 3 or parts[0] != "sessions_data":
        return path
    if session_id and parts[1] != session_id:
        return path
    return Path(*parts[2:]).as_posix()


USER_ARTIFACT_EXTENSIONS = (
    "md",
    "markdown",
    "html",
    "htm",
    "txt",
    "csv",
    "json",
    "yaml",
    "yml",
    "pdf",
    "docx",
    "pptx",
    "xlsx",
    "py",
    "js",
    "jsx",
    "ts",
    "tsx",
    "css",
)


def _is_supported_artifact_path(path: str) -> bool:
    suffix = Path(path).suffix.lower().lstrip(".")
    return suffix in USER_ARTIFACT_EXTENSIONS


def _strip_path_punctuation(path: str) -> str:
    return path.strip().strip("`'\"，,。；;）)]}、")


def _is_root_skill_manifest(path: str) -> bool:
    return Path(path).parts == ("SKILL.md",)


def _media_fallback_allowed(rel_path: str) -> bool:
    path = Path(rel_path)
    return (
        len(path.parts) == 1
        and path.suffix.lower() in PRIMARY_DELIVERABLE_EXTENSIONS
    )


def _normalise_candidate_path(candidate: str, workspace_dir: Path) -> str | None:
    path = _strip_path_punctuation(candidate)
    if not path or not _is_supported_artifact_path(path):
        return None

    workspace_dir = workspace_dir.resolve()
    if path.startswith("file://"):
        path = path.removeprefix("file://")

    candidate_path = Path(path).expanduser()
    if candidate_path.is_absolute():
        try:
            rel_path = candidate_path.resolve().relative_to(workspace_dir).as_posix()
        except ValueError:
            return None
    else:
        rel_path = path[2:] if path.startswith("./") else path
        candidate_path = workspace_dir / rel_path
        if not candidate_path.exists() and _media_fallback_allowed(rel_path):
            media_path = workspace_dir / "media" / rel_path
            if media_path.exists():
                rel_path = Path("media", rel_path).as_posix()
                candidate_path = media_path

    if is_internal_task_file(rel_path):
        return None
    if not candidate_path.exists() or not candidate_path.is_file():
        return None

    return rel_path


def extract_user_task_files_from_text(text: str, workspace_dir: Path) -> list[str]:
    """Extract explicit user artifact paths mentioned in chat/tool text.

    This intentionally does not infer from every file in the workspace.  A file
    belongs to a chat only when the chat text explicitly names a real,
    user-facing file under the agent workspace.
    """
    if not text:
        return []

    workspace_dir = workspace_dir.resolve()
    ext_pattern = "|".join(re.escape(ext) for ext in USER_ARTIFACT_EXTENSIONS)
    candidates: list[tuple[str, bool]] = []

    # Markdown/code spans are strong evidence of an intended deliverable.
    code_span_pattern = re.compile(
        rf"`([^`\r\n]+?\.(?:{ext_pattern}))`",
        re.IGNORECASE,
    )
    candidates.extend(
        (match.group(1), False) for match in code_span_pattern.finditer(text)
    )

    # Common tool/user-facing phrases without backticks.
    labelled_pattern = re.compile(
        rf"(?:保存为|保存到了|saved as|wrote \d+ bytes to)\s*[:：]?\s*([^\s\r\n]+?\.(?:{ext_pattern}))",
        re.IGNORECASE,
    )
    candidates.extend(
        (match.group(1), True) for match in labelled_pattern.finditer(text)
    )

    result: list[str] = []
    seen: set[str] = set()
    for candidate, has_write_context in candidates:
        rel_path = _normalise_candidate_path(candidate, workspace_dir)
        if rel_path and _is_root_skill_manifest(rel_path) and not has_write_context:
            continue
        if rel_path and rel_path not in seen:
            seen.add(rel_path)
            result.append(rel_path)
    return result


def extract_user_task_files_from_texts(
    texts: Iterable[str],
    workspace_dir: Path,
) -> list[str]:
    """Extract explicit user artifact paths from multiple chat text blocks."""
    result: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for rel_path in extract_user_task_files_from_text(text, workspace_dir):
            if rel_path in seen:
                continue
            seen.add(rel_path)
            result.append(rel_path)
    return result
