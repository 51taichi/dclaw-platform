"""DClaw session-memory facade backed by public AgentScope messages."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ..message_compat import Msg

if TYPE_CHECKING:
    from agentscope.state import AgentState


class MemoryMark(StrEnum):
    HINT = "hint"
    COMPRESSED = "compressed"


def message_to_dict(message: Msg) -> dict[str, Any]:
    return message.model_dump(mode="json")


def message_from_dict(value: dict[str, Any]) -> Msg:
    data = dict(value)
    if "created_at" not in data and "timestamp" in data:
        data["created_at"] = data.pop("timestamp")
    if isinstance(data.get("content"), str):
        data["content"] = [{"type": "text", "text": data["content"]}]
    return Msg.model_validate(data)


class InMemoryMemory:
    """Preserve DClaw's historical memory/session interface."""

    def __init__(self) -> None:
        self._content: list[tuple[Msg, list[str]]] = []
        self._compressed_summary = ""
        self._agent_state: AgentState | None = None

    @property
    def content(self) -> list[tuple[Msg, list[str]]]:
        """Return legacy entries while incorporating AgentScope state writes."""
        self._sync_from_agent_state()
        return self._content

    @content.setter
    def content(self, value: list[tuple[Msg, list[str]]]) -> None:
        self._content = value
        self._sync_to_agent_state()

    def bind_agent_state(self, state: AgentState) -> None:
        """Bind the legacy facade to AgentScope 2's persisted state."""
        self._agent_state = state
        if self._content:
            self._sync_to_agent_state()
        else:
            self._sync_from_agent_state()
        if self._compressed_summary:
            state.summary = self._compressed_summary
        elif isinstance(state.summary, str):
            self._compressed_summary = state.summary

    def _sync_from_agent_state(self) -> None:
        state = self._agent_state
        if state is None:
            return
        marks_by_id = {message.id: marks for message, marks in self._content}
        self._content = [
            (message, list(marks_by_id.get(message.id, [])))
            for message in state.context
        ]
        if isinstance(state.summary, str):
            self._compressed_summary = state.summary

    def _sync_to_agent_state(self) -> None:
        state = self._agent_state
        if state is None:
            return
        state.context = [message for message, _ in self._content]
        state.summary = self._compressed_summary

    async def add(
        self,
        memories: Msg | list[Msg],
        marks: str | list[str] | None = None,
    ) -> None:
        messages = memories if isinstance(memories, list) else [memories]
        normalized_marks = (
            [str(marks)]
            if isinstance(marks, str)
            else [str(mark) for mark in (marks or [])]
        )
        self._sync_from_agent_state()
        self._content.extend(
            (message, list(normalized_marks)) for message in messages
        )
        self._sync_to_agent_state()

    async def get_memory(self, **_kwargs: Any) -> list[Msg]:
        return [message for message, _ in self.content]

    async def clear(self) -> None:
        self._content.clear()
        self._sync_to_agent_state()

    def state_dict(self) -> dict[str, Any]:
        return {
            "content": [
                [message_to_dict(message), list(marks)]
                for message, marks in self.content
            ],
            "_compressed_summary": self._compressed_summary,
        }

    def load_state_dict(self, state: dict[str, Any], strict: bool = True) -> None:
        if strict and "content" not in state:
            raise KeyError("The state does not contain 'content'")
        self._content = []
        for item in state.get("content", []):
            if isinstance(item, (list, tuple)) and len(item) == 2:
                raw, marks = item
            else:
                raw, marks = item, []
            self._content.append((message_from_dict(raw), list(marks or [])))
        self._compressed_summary = str(state.get("_compressed_summary", ""))
        self._sync_to_agent_state()
