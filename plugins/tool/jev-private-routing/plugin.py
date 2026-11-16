"""Register deterministic Jev private-message routing."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from qwenpaw.app.guards import require_admin
from qwenpaw.app.storage.repos.open_api_repo import get_open_api_repository

from .routing import (
    channel_config_status,
    route_private_message_jev,
    save_channel_config,
)


class RouteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal[1, 2] = Field(default=2, alias="schemaVersion")
    message: str = Field(min_length=1, max_length=4_000)
    candidate_tasks: list[dict] = Field(alias="candidateTasks", min_length=1, max_length=2_000)
    recent_history: list[dict] = Field(default_factory=list, alias="recentHistory", max_length=2_000)
    shared_video: dict | None = Field(default=None, alias="sharedVideo")
    minimum_margin: float = Field(default=0.15, alias="minimumMargin", ge=0, le=1)


router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_admin)])


class JevChannelSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    api_url: str | None = Field(default=None, alias="apiUrl", max_length=2048)
    api_key: SecretStr = Field(alias="apiKey")
    relay_token: SecretStr | None = Field(default=None, alias="relayToken")

    def document(self) -> dict:
        result = {"apiKey": self.api_key.get_secret_value()}
        if self.api_url is not None:
            result["apiUrl"] = self.api_url
        if self.relay_token is not None:
            result["relayToken"] = self.relay_token.get_secret_value()
        return result


class JevChannelConfigRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    primary: JevChannelSettings
    fallback: JevChannelSettings | None = None


@admin_router.get("/channels")
async def get_channel_config():
    try:
        return channel_config_status()
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="Stored Jev channel configuration is invalid",
        ) from exc


@admin_router.put("/channels")
async def put_channel_config(payload: JevChannelConfigRequest):
    document = {
        "schemaVersion": payload.schema_version,
        "primary": payload.primary.document(),
    }
    if payload.fallback is not None:
        document["fallback"] = payload.fallback.document()
    try:
        return save_channel_config(document)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not persist Jev channel configuration",
        ) from exc


@router.post("/targets/{public_id}")
async def route_private_message(public_id: str, payload: RouteRequest, request: Request):
    publication = get_open_api_repository().get_enabled_publication_by_public_id(public_id)
    if publication is None:
        raise HTTPException(status_code=404, detail="Open API publication not found")
    if str(getattr(request.state, "open_publication_id", "")) != str(publication["id"]):
        raise HTTPException(
            status_code=403,
            detail="Open API key is not allowed for this publication",
        )
    if str(publication.get("target_type")) != "agent":
        raise HTTPException(status_code=400, detail="Jev routing requires an agent target")

    result = await route_private_message_jev(
        message=payload.message,
        candidate_tasks=payload.candidate_tasks,
        recent_history=payload.recent_history,
        shared_video=payload.shared_video,
        minimum_margin=payload.minimum_margin,
    )
    block = result.content[0]
    text = block.get("text") if isinstance(block, dict) else block.text
    body = json.loads(text)
    return {"schemaVersion": 1, **body}


class JevPrivateRoutingPlugin:
    def register(self, api):
        api.register_tool(
            tool_name="route_private_message_jev",
            tool_func=route_private_message_jev,
            description="Attribute a Douyin private message to a candidate comment task with Jev",
        )
        api.register_http_router(
            router,
            prefix="/open/v1/jev-private-routing",
            tags=["open-api-jev-routing"],
        )
        api.register_http_router(
            admin_router,
            prefix="/jev-private-routing",
            tags=["admin-jev-routing"],
        )


plugin = JevPrivateRoutingPlugin()
