"""Message adapters for data persisted by the AgentScope 1 runtime."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from agentscope.message import (
    Base64Source,
    DataBlock,
    HintBlock,
    Msg as AgentScopeMsg,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
    ToolResultBlock,
    URLSource,
)
from pydantic import ConfigDict


class LegacyToolCallBlock(ToolCallBlock):
    """Tool call that can carry provider metadata from old sessions."""

    model_config = ConfigDict(extra="allow", use_enum_values=True)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def pop(self, key: str, default: Any = None) -> Any:
        extras = self.__pydantic_extra__ or {}
        return extras.pop(key, default)


def _media_type(kind: str, source: dict[str, Any]) -> str:
    explicit = str(source.get("media_type") or "").strip()
    if explicit:
        return explicit
    candidate = str(source.get("url") or source.get("path") or "")
    guessed, _ = mimetypes.guess_type(candidate)
    return guessed or f"{kind}/unknown"


def _data_block(kind: str, source: dict[str, Any], **kwargs: Any) -> DataBlock:
    source_type = str(source.get("type") or "url")
    media_type = _media_type(kind, source)
    if source_type == "base64":
        normalized = Base64Source(
            data=str(source.get("data") or ""),
            media_type=media_type,
        )
    else:
        raw_url = str(source.get("url") or source.get("path") or "")
        if raw_url and "://" not in raw_url:
            raw_url = Path(raw_url).expanduser().resolve().as_uri()
        normalized = URLSource(url=raw_url, media_type=media_type)
    block_kwargs: dict[str, Any] = {
        "source": normalized,
        "name": kwargs.get("name"),
    }
    if kwargs.get("id"):
        block_kwargs["id"] = kwargs["id"]
    return DataBlock(**block_kwargs)


def ImageBlock(*, source: dict[str, Any], **kwargs: Any) -> DataBlock:
    """Create an AgentScope 2 image data block."""
    kwargs.pop("type", None)
    return _data_block("image", source, **kwargs)


def AudioBlock(*, source: dict[str, Any], **kwargs: Any) -> DataBlock:
    """Create an AgentScope 2 audio data block."""
    kwargs.pop("type", None)
    return _data_block("audio", source, **kwargs)


def VideoBlock(*, source: dict[str, Any], **kwargs: Any) -> DataBlock:
    """Create an AgentScope 2 video data block."""
    kwargs.pop("type", None)
    return _data_block("video", source, **kwargs)


def ToolUseBlock(
    *,
    id: str,
    name: str,
    input: str | dict[str, Any],
    raw_input: str | None = None,
    **_kwargs: Any,
) -> ToolCallBlock:
    """Convert a legacy tool-use block to AgentScope 2's tool-call block."""
    serialized = raw_input
    if serialized is None:
        serialized = input if isinstance(input, str) else json.dumps(input)
    extras = {
        key: value
        for key, value in _kwargs.items()
        if key not in {"type", "state"}
    }
    return LegacyToolCallBlock(
        id=id,
        name=name,
        input=serialized,
        **extras,
    )


def _normalize_content(value: Any) -> list[Any]:
    if isinstance(value, str):
        return [TextBlock(text=value)]
    normalized: list[Any] = []
    for block in value or []:
        if not isinstance(block, dict):
            normalized.append(block)
            continue
        block_type = block.get("type")
        if block_type == "text":
            normalized.append(TextBlock(text=str(block.get("text") or "")))
        elif block_type == "thinking":
            normalized.append(
                ThinkingBlock(thinking=str(block.get("thinking") or "")),
            )
        elif block_type == "hint":
            normalized.append(
                HintBlock(
                    hint=block.get("hint") or "",
                    source=block.get("source"),
                ),
            )
        elif block_type in {"tool_use", "tool_call"}:
            provider_fields = {
                key: block[key]
                for key in ("raw_input", "extra_content")
                if key in block
            }
            normalized.append(
                ToolUseBlock(
                    id=str(block.get("id") or ""),
                    name=str(block.get("name") or ""),
                    input=block.get("input") or {},
                    **provider_fields,
                ),
            )
        elif block_type in {"image", "audio", "video"}:
            factory = {
                "image": ImageBlock,
                "audio": AudioBlock,
                "video": VideoBlock,
            }[block_type]
            normalized.append(factory(source=block.get("source") or {}))
        elif block_type == "file":
            source = block.get("source") or {}
            if isinstance(source, str):
                raw_url = source
                if raw_url and "://" not in raw_url:
                    raw_url = Path(raw_url).expanduser().resolve().as_uri()
                source = {"type": "url", "url": raw_url}
            normalized.append(
                _data_block(
                    "file",
                    source,
                    name=block.get("filename") or block.get("name"),
                ),
            )
        elif block_type == "tool_result":
            output = block.get("output", "")
            if isinstance(output, list):
                output = _normalize_content(output)
            normalized.append(
                ToolResultBlock(
                    id=str(block.get("id") or ""),
                    name=str(block.get("name") or ""),
                    output=output,
                    state=block.get("state", "success"),
                ),
            )
        else:
            normalized.append(block)
    return normalized


def normalize_legacy_blocks(value: Any) -> list[Any]:
    """Normalize persisted/runtime 1.x block dictionaries to 2.0 blocks."""
    return _normalize_content(value)


def _legacy_block(block: Any) -> Any:
    """Project an AgentScope 2 block onto DClaw's stable 1.x wire shape."""
    if not hasattr(block, "model_dump"):
        return block
    block_type = getattr(block, "type", None)
    if block_type == "text":
        return {"type": "text", "text": block.text}
    if block_type == "thinking":
        return {"type": "thinking", "thinking": block.thinking}
    if block_type == "hint":
        value = {"type": "hint", "hint": block.hint}
        if block.source is not None:
            value["source"] = block.source
        return value
    if block_type == "tool_call":
        raw_input = block.input
        try:
            tool_input = json.loads(raw_input)
        except (TypeError, ValueError):
            tool_input = raw_input
        value = {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": tool_input,
        }
        extras = block.__pydantic_extra__ or {}
        for key in ("raw_input", "extra_content"):
            if key in extras:
                value[key] = extras[key]
        return value
    if block_type == "tool_result":
        output = block.output
        if isinstance(output, list):
            output = [_legacy_block(item) for item in output]
        return {
            "type": "tool_result",
            "id": block.id,
            "name": block.name,
            "output": output,
            "state": block.state,
        }
    if block_type == "data":
        source = block.source.model_dump(mode="json")
        media_type = str(source.get("media_type") or "")
        if media_type.startswith("image/"):
            legacy_type = "image"
        elif media_type.startswith("audio/"):
            legacy_type = "audio"
        elif media_type.startswith("video/"):
            legacy_type = "video"
        else:
            legacy_type = "file"
        value = {"type": legacy_type, "source": source}
        if block.name:
            value["filename" if legacy_type == "file" else "name"] = block.name
        return value
    return block.model_dump(mode="json")


def legacy_content(value: list[Any]) -> str | list[Any]:
    """Serialize blocks without leaking AgentScope 2 implementation fields."""
    blocks = [_legacy_block(block) for block in value]
    if len(blocks) == 1 and isinstance(blocks[0], dict):
        if blocks[0].get("type") == "text":
            return str(blocks[0].get("text") or "")
    return blocks


class Msg(AgentScopeMsg):
    """AgentScope 2 message that can read DClaw's 1.x persisted shape."""

    model_config = ConfigDict(extra="allow", use_enum_values=True)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if args:
            if len(args) > 3:
                raise TypeError("Msg accepts at most name, content and role")
            for key, value in zip(("name", "content", "role"), args):
                kwargs.setdefault(key, value)
        kwargs["content"] = _normalize_content(kwargs.get("content", []))
        if kwargs.get("role") != "assistant" and any(
            getattr(block, "type", None) == "tool_result"
            for block in kwargs["content"]
        ):
            kwargs["role"] = "assistant"
        if "created_at" not in kwargs and "timestamp" in kwargs:
            kwargs["created_at"] = kwargs.pop("timestamp")
        if kwargs.get("metadata") is None:
            kwargs["metadata"] = {}
        super().__init__(**kwargs)

    @property
    def timestamp(self) -> str:
        return self.created_at

    def to_dict(self) -> dict[str, Any]:
        value = self.model_dump(mode="json", exclude={"content"})
        value["content"] = legacy_content(self.content)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Msg":
        return cls(**value)
