# -*- coding: utf-8 -*-
"""Typed records used by the Mindspace knowledge base."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MindspaceScope(str, Enum):
    ENTERPRISE = "enterprise"
    PERSONAL = "personal"
    GLOBAL = "global"
    AGENT = "agent"


DEFAULT_KNOWLEDGE_CATEGORY = "uncategorized"


def normalize_knowledge_category(value: Any) -> str:
    category = str(value or "").strip()
    return category[:64] or DEFAULT_KNOWLEDGE_CATEGORY


def normalize_knowledge_tags(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            values: list[Any] = []
        else:
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError:
                decoded = [item.strip() for item in raw.split(",")]
            values = decoded if isinstance(decoded, list) else [decoded]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = []

    tags: list[str] = []
    seen: set[str] = set()
    for item in values:
        tag = str(item or "").strip()[:32]
        key = tag.casefold()
        if not tag or key in seen:
            continue
        seen.add(key)
        tags.append(tag)
        if len(tags) >= 10:
            break
    return tags


def normalize_mindspace_scope(
    scope: MindspaceScope | str | None,
    default: MindspaceScope | None = None,
) -> MindspaceScope | None:
    if scope is None:
        return default
    value = scope.value if isinstance(scope, MindspaceScope) else str(scope)
    if value == "all":
        return None
    if value == MindspaceScope.GLOBAL.value:
        return MindspaceScope.ENTERPRISE
    if value == MindspaceScope.AGENT.value:
        return MindspaceScope.PERSONAL
    try:
        resolved = MindspaceScope(value)
    except ValueError:
        return default
    if resolved == MindspaceScope.GLOBAL:
        return MindspaceScope.ENTERPRISE
    if resolved == MindspaceScope.AGENT:
        return MindspaceScope.PERSONAL
    return resolved


def legacy_scope_value(scope: MindspaceScope | str | None) -> str | None:
    resolved = normalize_mindspace_scope(scope)
    if resolved == MindspaceScope.ENTERPRISE:
        return MindspaceScope.GLOBAL.value
    if resolved == MindspaceScope.PERSONAL:
        return MindspaceScope.AGENT.value
    return None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MindspaceDoc:
    id: str
    scope: MindspaceScope
    name: str
    source_type: str
    category: str = "uncategorized"
    tags: list[str] = field(default_factory=list)
    size: str = "0 KB"
    chunk_count: int = 0
    status: str = "pending"
    progress: int = 0
    updated_at: str = field(default_factory=utc_now_iso)
    agent_ids: list[str] = field(default_factory=list)
    source_url: str | None = None
    last_error: str | None = None
    failed_stage: str | None = None
    generated_wiki: list[str] = field(default_factory=list)
    cloud_account_id: str | None = None
    owner_user_id: str | None = None
    legacy_agent_id: str | None = None
    byte_size: int = 0

    @classmethod
    def from_dict(
        cls,
        raw: dict[str, Any],
        default_scope: MindspaceScope = MindspaceScope.PERSONAL,
    ) -> "MindspaceDoc":
        scope_value = raw.get("scope") or default_scope.value
        scope = normalize_mindspace_scope(scope_value, default_scope) or default_scope

        source_type = raw.get("source_type") or raw.get("type") or "txt"
        updated_at = raw.get("updated_at") or raw.get("updatedAt") or utc_now_iso()
        chunk_count = raw.get("chunk_count", raw.get("slices", 0)) or 0
        status = raw.get("status") or raw.get("sync_status") or "pending"
        progress = raw.get("progress")
        if progress is None:
            progress = 100 if status == "ready" else 0

        return cls(
            id=str(raw.get("id")),
            scope=scope,
            name=str(raw.get("name") or raw.get("title") or "Untitled"),
            source_type=str(source_type),
            category=normalize_knowledge_category(raw.get("category")),
            tags=normalize_knowledge_tags(raw.get("tags")),
            size=str(raw.get("size") or "0 KB"),
            chunk_count=int(chunk_count),
            status=str(status),
            progress=int(progress),
            updated_at=str(updated_at),
            agent_ids=list(raw.get("agent_ids") or raw.get("agentIds") or []),
            source_url=raw.get("source_url") or raw.get("url"),
            last_error=raw.get("last_error") or raw.get("lastError"),
            failed_stage=raw.get("failed_stage") or raw.get("failedStage"),
            generated_wiki=list(raw.get("generated_wiki") or []),
            cloud_account_id=raw.get("cloud_account_id") or raw.get("cloudAccountId"),
            owner_user_id=(
                str(raw.get("owner_user_id") or raw.get("ownerUserId"))
                if raw.get("owner_user_id") or raw.get("ownerUserId")
                else None
            ),
            legacy_agent_id=raw.get("legacy_agent_id") or raw.get("legacyAgentId"),
            byte_size=int(raw.get("byte_size") or raw.get("byteSize") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scope": self.scope.value,
            "agent_ids": self.agent_ids,
            "name": self.name,
            "source_type": self.source_type,
            "category": self.category,
            "tags": self.tags,
            "source_url": self.source_url,
            "size": self.size,
            "chunk_count": self.chunk_count,
            "status": self.status,
            "progress": self.progress,
            "last_error": self.last_error,
            "failed_stage": self.failed_stage,
            "updated_at": self.updated_at,
            "generated_wiki": self.generated_wiki,
            "cloud_account_id": self.cloud_account_id,
            "owner_user_id": self.owner_user_id,
            "legacy_agent_id": self.legacy_agent_id,
            "byte_size": self.byte_size,
        }

    def to_api_dict(self) -> dict[str, Any]:
        data = self.to_dict()
        legacy_scope = legacy_scope_value(self.scope)
        data.update(
            {
                "type": self.source_type,
                "url": self.source_url,
                "slices": self.chunk_count,
                "updatedAt": self.updated_at,
                "lastError": self.last_error,
                "failedStage": self.failed_stage,
                "cloudAccountId": self.cloud_account_id,
                "ownerUserId": self.owner_user_id,
                "legacyAgentId": self.legacy_agent_id,
                "legacy_scope": legacy_scope,
            }
        )
        return data


@dataclass
class MindspaceChunk:
    id: str
    doc_id: str
    doc_name: str
    scope: MindspaceScope
    text: str
    source_url: str | None = None
    owner_user_id: str | None = None
    chunk_index: int = 0
    locator: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MindspaceChunk":
        scope = normalize_mindspace_scope(raw.get("scope"), MindspaceScope.PERSONAL)
        assert scope is not None
        return cls(
            id=str(raw["id"]),
            doc_id=str(raw["doc_id"]),
            doc_name=str(raw.get("doc_name") or ""),
            scope=scope,
            text=str(raw.get("text") or ""),
            source_url=raw.get("source_url"),
            owner_user_id=(
                str(raw.get("owner_user_id"))
                if raw.get("owner_user_id") is not None
                else None
            ),
            chunk_index=int(raw.get("chunk_index") or 0),
            locator=raw.get("locator"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "doc_id": self.doc_id,
            "doc_name": self.doc_name,
            "scope": self.scope.value,
            "text": self.text,
            "source_url": self.source_url,
            "owner_user_id": self.owner_user_id,
            "chunk_index": self.chunk_index,
            "locator": self.locator,
        }


@dataclass
class MindspaceSearchHit:
    doc_id: str
    doc_name: str
    chunk_id: str
    text: str
    score: float
    scope: MindspaceScope
    source_url: str | None = None
    match_reason: str | None = None
    locator: str | None = None
    context: str | None = None
    context_chunk_ids: list[str] = field(default_factory=list)
    citation: str | None = None
    rank: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "doc_name": self.doc_name,
            "chunk_id": self.chunk_id,
            "text": self.text,
            "score": self.score,
            "source_url": self.source_url,
            "scope": self.scope.value,
            "match_reason": self.match_reason,
            "locator": self.locator,
            "context": self.context,
            "context_chunk_ids": self.context_chunk_ids,
            "citation": self.citation,
            "rank": self.rank,
        }
