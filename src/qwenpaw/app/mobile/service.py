# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from .models import (
    MobileArtifactSummary,
    MobileDisplayStatus,
    MobilePendingConfirmation,
)


_IMAGE_EXTENSIONS = {
    ".apng",
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".webp",
}
_DOCUMENT_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".pdf",
    ".ppt",
    ".pptx",
    ".txt",
    ".xls",
    ".xlsx",
}
_ARCHIVE_EXTENSIONS = {".7z", ".gz", ".rar", ".tar", ".zip"}
_CODE_EXTENSIONS = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".ts",
    ".tsx",
}


def derive_mobile_display_status(
    *,
    runtime_status: str | None,
    task_status: str | None,
    pending_confirmation_count: int,
    artifact_count: int,
    has_assistant_response: bool = False,
) -> MobileDisplayStatus:
    if runtime_status == "running":
        return "running"
    if pending_confirmation_count > 0:
        return "pending_confirmation"
    if task_status == "failed":
        return "failed"
    if task_status == "completed" or artifact_count > 0 or has_assistant_response:
        return "completed"
    return "idle"


def _extract_tool_params(approval: Any) -> dict[str, Any]:
    extra = getattr(approval, "extra", None)
    if not isinstance(extra, dict):
        return {}

    tool_call = extra.get("tool_call")
    if isinstance(tool_call, dict) and isinstance(tool_call.get("input"), dict):
        return tool_call["input"]

    return {}


def serialize_pending_confirmation(approval: Any) -> MobilePendingConfirmation:
    return MobilePendingConfirmation(
        request_id=str(getattr(approval, "request_id", "")),
        session_id=str(getattr(approval, "session_id", "")),
        root_session_id=str(getattr(approval, "root_session_id", "")),
        owner_agent_id=getattr(approval, "owner_agent_id", None),
        agent_id=str(getattr(approval, "agent_id", "")),
        tool_name=str(getattr(approval, "tool_name", "")),
        severity=str(getattr(approval, "severity", "")),
        findings_count=int(getattr(approval, "findings_count", 0) or 0),
        findings_summary=str(
            getattr(approval, "findings_summary", None)
            or getattr(approval, "result_summary", "")
            or ""
        ),
        tool_params=_extract_tool_params(approval),
        created_at=float(getattr(approval, "created_at", 0) or 0),
        timeout_seconds=int(getattr(approval, "timeout_seconds", 0) or 0),
    )


def serialize_artifact_summary(file_info: Any) -> MobileArtifactSummary:
    name = str(
        getattr(file_info, "name", "")
        or getattr(file_info, "filename", "")
    )
    path = str(getattr(file_info, "path", "") or name)
    return MobileArtifactSummary(
        name=name,
        path=path,
        size=getattr(file_info, "size", None),
        modified_time=getattr(file_info, "modified_time", None),
        kind=_artifact_kind(path or name),
    )


def _artifact_kind(path: str) -> str:
    suffix = ""
    if "." in path:
        suffix = f".{path.rsplit('.', 1)[-1].lower()}"
    if suffix in _IMAGE_EXTENSIONS:
        return "image"
    if suffix in _DOCUMENT_EXTENSIONS:
        return "document"
    if suffix in _ARCHIVE_EXTENSIONS:
        return "archive"
    if suffix in _CODE_EXTENSIONS:
        return "code"
    return "file"
