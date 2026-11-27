"""Shared AIGC resource and capability contracts, independent of HTTP."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class CanvasNode(BaseModel):
    id: str
    type: str
    position: dict[str, float] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)


class CanvasEdge(BaseModel):
    id: str
    source: str
    target: str
    sourceHandle: str | None = None
    targetHandle: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class CanvasViewport(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = 1


class CanvasUpsert(BaseModel):
    name: str = Field(default="Untitled canvas")
    nodes: list[CanvasNode] = Field(default_factory=list)
    edges: list[CanvasEdge] = Field(default_factory=list)
    viewport: CanvasViewport = Field(default_factory=CanvasViewport)
    thumbnail: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class Canvas(CanvasUpsert):
    id: str
    created_at: str
    updated_at: str


class CanvasList(BaseModel):
    canvases: list[Canvas]


class AigcCapabilityInfo(BaseModel):
    provider_id: str
    provider_name: str
    model_id: str
    model_name: str
    capability: str
    source: Literal["model_registry", "plugin_tool"]
    parameter_schema: dict[str, Any] = Field(default_factory=dict)


class AigcCategoryDefaults(BaseModel):
    configured: bool = False
    configured_default: dict[str, str] | None = None
    effective_default: dict[str, str] | None = None
    fallback_active: bool = False
    fallback_reason: list[str] = Field(default_factory=list)


class CapabilityList(BaseModel):
    capabilities: list[AigcCapabilityInfo]
    defaults: dict[str, AigcCategoryDefaults] = Field(default_factory=dict)


class WorkflowAvailableModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str
    provider_name: str
    model_id: str
    model_name: str
    capability: str
    source: Literal["model_registry", "plugin_tool"]
    parameter_schema: dict[str, Any] = Field(default_factory=dict)


class WorkflowNodeCapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    title: str
    provisioning: Literal["AUTO_PROVISIONABLE", "MANUAL_ONLY", "UNAVAILABLE"]
    provisioning_reason: str | None = None
    capabilities: tuple[str, ...]
    input_keys: tuple[str, ...]
    parameter_keys: tuple[str, ...]
    input_slots: dict[str, tuple[str, ...]]
    output_type: str
    control_id: str | None
    customer_actions: tuple[str, ...]
    input_schema: dict[str, Any]
    parameter_schema: dict[str, Any]


class WorkflowCapabilityCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    nodes: tuple[WorkflowNodeCapability, ...]
    available_models: tuple[WorkflowAvailableModel, ...]


class AigcJobCreate(BaseModel):
    canvas_id: str
    node_id: str
    capability: str
    provider_id: str
    model_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)


class AigcAsset(BaseModel):
    id: str
    kind: Literal["image", "video", "audio", "file"]
    name: str
    path: str
    url: str | None = None
    mime_type: str | None = None
    created_at: str
    meta: dict[str, Any] = Field(default_factory=dict)


class AigcJob(AigcJobCreate):
    id: str
    status: JobStatus
    created_at: str
    updated_at: str
    outputs: list[AigcAsset] = Field(default_factory=list)
    error: str | None = None
    logs: list[str] = Field(default_factory=list)


class JobList(BaseModel):
    jobs: list[AigcJob]


class AssetList(BaseModel):
    assets: list[AigcAsset]
