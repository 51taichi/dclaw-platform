# -*- coding: utf-8 -*-
"""Runtime preparation helpers for external Open API message calls."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from agentscope_runtime.engine.schemas.agent_schemas import ContentType, TextContent
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, field_validator


_SAFE_ID_PATTERN = re.compile(r"[^A-Za-z0-9_.:-]+")
_MAX_EXTERNAL_ID_LENGTH = 128
_MAX_MESSAGE_LENGTH = 20_000


class OpenMessageRequest(BaseModel):
    external_user_id: str
    external_session_id: str | None = None
    message: str
    stream: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("external_user_id")
    @classmethod
    def validate_external_user_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("external_user_id is required")
        if len(value) > _MAX_EXTERNAL_ID_LENGTH:
            raise ValueError("external_user_id is too long")
        return value

    @field_validator("external_session_id")
    @classmethod
    def validate_external_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) > _MAX_EXTERNAL_ID_LENGTH:
            raise ValueError("external_session_id is too long")
        return value

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message is required")
        if len(value) > _MAX_MESSAGE_LENGTH:
            raise ValueError("message is too long")
        return value


@dataclass
class PreparedOpenRun:
    chat_id: str
    session_id: str
    channel: str
    agent_id: str
    payload: dict[str, Any]
    workspace: Any
    console_channel: Any


def build_open_session_id(
    app_id: str,
    public_id: str,
    external_user_id: str,
    external_session_id: str | None,
) -> str:
    external_user = _safe_external_id(external_user_id, fallback="anonymous")
    external_session = _safe_external_id(external_session_id or "", fallback="default")
    return f"open:{app_id}:{public_id}:{external_user}:{external_session}"


async def get_open_workspace(request: Request, agent_id: str) -> Any:
    app = getattr(request, "app", None)
    state = getattr(app, "state", None)
    manager = getattr(state, "multi_agent_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=500,
            detail="Open API workspace manager is not configured",
        )
    return await manager.get_agent(
        agent_id,
        user_id=str(request.state.user_id),
    )


async def prepare_open_agent_chat(
    request: Request,
    publication: dict[str, Any],
    payload: OpenMessageRequest,
) -> PreparedOpenRun:
    return await _prepare_open_chat(
        request,
        publication,
        payload,
        agent_id=str(publication["target_id"]),
        expert_team_id=None,
    )


async def prepare_open_expert_team_chat(
    request: Request,
    publication: dict[str, Any],
    payload: OpenMessageRequest,
    *,
    leader_agent_id: str,
) -> PreparedOpenRun:
    return await _prepare_open_chat(
        request,
        publication,
        payload,
        agent_id=leader_agent_id,
        expert_team_id=str(publication["target_id"]),
    )


async def _prepare_open_chat(
    request: Request,
    publication: dict[str, Any],
    payload: OpenMessageRequest,
    *,
    agent_id: str,
    expert_team_id: str | None,
) -> PreparedOpenRun:
    user_id = str(request.state.user_id)
    app_id = str(request.state.open_app_id)
    public_id = str(publication["public_id"])
    session_id = build_open_session_id(
        app_id,
        public_id,
        payload.external_user_id,
        payload.external_session_id,
    )
    channel = f"open:{app_id}"
    workspace = await get_open_workspace(request, agent_id)
    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )

    chat = await workspace.chat_manager.get_or_create_chat(
        session_id,
        user_id,
        channel,
        name=payload.message[:10] or "Open API",
    )
    native_payload = {
        "channel_id": channel,
        "sender_id": user_id,
        "content_parts": [
            TextContent(type=ContentType.TEXT, text=payload.message),
        ],
        "meta": {
            "session_id": session_id,
            "user_id": user_id,
            "external_user_id": payload.external_user_id,
            "external_session_id": payload.external_session_id or "default",
            "publication_id": str(publication["id"]),
            "public_id": public_id,
            "target_type": str(publication["target_type"]),
            "target_id": str(publication["target_id"]),
            "knowledge_base_id": str(
                publication.get("knowledge_base_id")
                or f"openapi-{publication['id']}",
            ),
            "metadata": dict(payload.metadata or {}),
        },
    }
    if expert_team_id:
        native_payload["meta"]["expert_team_id"] = expert_team_id

    return PreparedOpenRun(
        chat_id=str(chat.id),
        session_id=session_id,
        channel=channel,
        agent_id=agent_id,
        payload=native_payload,
        workspace=workspace,
        console_channel=console_channel,
    )


def _safe_external_id(value: str, *, fallback: str) -> str:
    normalized = _SAFE_ID_PATTERN.sub("_", value.strip())[:_MAX_EXTERNAL_ID_LENGTH]
    normalized = normalized.strip("._:-")
    return normalized or fallback
