"""DClaw-owned runner lifecycle and public event projection."""

from __future__ import annotations

import inspect
import logging
import traceback
from copy import deepcopy
from contextlib import AsyncExitStack
from typing import Any, AsyncGenerator
from uuid import uuid4

from qwenpaw.agents.message_compat import Msg

from .contracts import (
    AgentRequest,
    AgentResponse,
    ContentType,
    Error,
    Event,
    ImageContent,
    Message,
    RunStatus,
    SequenceNumberGenerator,
    TextContent,
)
from .exceptions import AppBaseException, UnknownAgentException

logger = logging.getLogger(__name__)


def _stream_metadata(message: Message) -> dict[str, Any]:
    metadata = message.metadata or {}
    nested = metadata.get("metadata")
    return nested if isinstance(nested, dict) else {}


def _merge_stream_terminal(active: Message, terminal: Message) -> None:
    """Apply a terminal snapshot without discarding accumulated tool output."""
    if _stream_metadata(terminal).get("stream_snapshot"):
        active.content = deepcopy(terminal.content)
    elif terminal.content:
        for index, incoming in enumerate(terminal.content):
            if index >= len(active.content or []):
                active.add_content(incoming.model_copy(deep=True))
                continue
            previous = active.content[index]
            if incoming.type == ContentType.DATA and previous.type == ContentType.DATA:
                merged = {**(previous.data or {}), **(incoming.data or {})}
                if not (incoming.data or {}).get("output") and (
                    previous.data or {}
                ).get("output"):
                    merged["output"] = previous.data["output"]
                previous.data = merged
            elif incoming.type == ContentType.TEXT and incoming.text:
                previous.text = incoming.text
            else:
                active.content[index] = incoming.model_copy(deep=True)
    active.metadata = terminal.metadata
    active.usage = terminal.usage


def _add_stream_content(
    active: Message,
    content: Any,
    content_index: int | None,
) -> Event | None:
    """Accumulate a chunk and return the content event sent to the client."""
    if content_index is not None:
        content.index = content_index
        if (
            active.type == "plugin_call_output"
            and content.type == ContentType.DATA
            and active.content
        ):
            previous = active.content[content_index]
            previous_data = previous.data or {}
            incoming_data = content.data or {}
            merged = {**previous_data, **incoming_data}
            if isinstance(previous_data.get("output"), str) and isinstance(
                incoming_data.get("output"),
                str,
            ):
                merged["output"] = (
                    previous_data["output"] + incoming_data["output"]
                )
            content.data = merged
    return active.add_delta_content(content)


def _request_messages_to_agent_msgs(messages: list[Message]) -> list[Msg]:
    """Convert the stable API contract to AgentScope public messages."""
    result: list[Msg] = []
    for message in messages:
        blocks: list[dict[str, Any]] = []
        for content in message.content or []:
            if content.type == ContentType.TEXT:
                blocks.append({"type": "text", "text": content.text or ""})
            elif content.type == ContentType.IMAGE:
                blocks.append(
                    {
                        "type": "image",
                        "source": {"type": "url", "url": content.image_url or ""},
                    },
                )
            elif content.type == ContentType.AUDIO:
                blocks.append(
                    {
                        "type": "audio",
                        "source": {"type": "url", "url": content.data or ""},
                    },
                )
            elif content.type == ContentType.VIDEO:
                blocks.append(
                    {
                        "type": "video",
                        "source": {"type": "url", "url": content.video_url or ""},
                    },
                )
            elif content.type == ContentType.FILE:
                blocks.append(
                    {
                        "type": "file",
                        "filename": content.filename,
                        "source": content.file_url or content.file_data or "",
                    },
                )
            elif content.type == ContentType.DATA:
                blocks.append({"type": "data", "data": content.data or {}})
            elif content.type == ContentType.REFUSAL:
                blocks.append({"type": "text", "text": content.refusal or ""})
        result.append(
            Msg(
                name=(message.metadata or {}).get("original_name", message.role or "user"),
                role=message.role or "user",
                content=blocks,
            ),
        )
    return result


class Runner:
    """Minimal execution lifecycle required by DClaw.

    Deployment and protocol hosting are intentionally not part of this class;
    DClaw's FastAPI application owns those concerns.
    """

    def __init__(self) -> None:
        self.framework_type: str | None = None
        self.in_type_converters = None
        self.out_type_converters = None
        self._health = False
        self._exit_stack = AsyncExitStack()

    async def query_handler(self, *args, **kwargs):
        raise NotImplementedError("query_handler not implemented")

    async def init_handler(self, *args, **kwargs) -> None:
        return None

    async def shutdown_handler(self, *args, **kwargs) -> None:
        return None

    async def start(self):
        result = self.init_handler()
        if inspect.isawaitable(result):
            await result
        self._health = True
        return self

    async def stop(self) -> None:
        try:
            result = self.shutdown_handler()
            if inspect.isawaitable(result):
                await result
        finally:
            await self._exit_stack.aclose()
            self._health = False

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def stream_query(
        self,
        request: AgentRequest | dict[str, Any],
        **kwargs: Any,
    ) -> AsyncGenerator[Event, None]:
        if not self._health:
            raise RuntimeError(
                "Runner has not been started. Call 'await runner.start()' first.",
            )
        if isinstance(request, dict):
            request = AgentRequest(**request)
        request.session_id = request.session_id or str(uuid4())
        request.user_id = request.user_id or request.session_id

        sequence = SequenceNumberGenerator()
        response = AgentResponse(id=request.id, session_id=request.session_id)
        active_streams: dict[str, Message] = {}
        active_content_indexes: dict[str, dict[str, int]] = {}
        yield sequence.yield_with_sequence(response)
        yield sequence.yield_with_sequence(response.in_progress())

        def finalize_stream(message_id: str) -> list[Event]:
            active = active_streams.pop(message_id)
            active_content_indexes.pop(message_id, None)
            terminal_events: list[Event] = []
            for index in range(len(active.content or [])):
                content_event = active.content_completed(index)
                if content_event is not None:
                    terminal_events.append(content_event)
            active.completed()
            response.add_new_message(active.model_copy(deep=True))
            terminal_events.append(active)
            return terminal_events

        try:
            source = self.query_handler(
                msgs=_request_messages_to_agent_msgs(request.input),
                request=request,
                response=response,
                **kwargs,
            )
            async for item in source:
                value = item[0] if isinstance(item, tuple) else item
                if isinstance(value, Message):
                    projected = [value]
                else:
                    from qwenpaw.app.runner.utils import agentscope_msg_to_message

                    projected = agentscope_msg_to_message(value)
                for event in projected:
                    if event.status == RunStatus.InProgress:
                        active = active_streams.get(event.id)
                        if active is None:
                            active = Message(
                                id=event.id,
                                type=event.type,
                                role=event.role,
                                metadata=event.metadata,
                            ).in_progress()
                            active_streams[event.id] = active
                            active_content_indexes[event.id] = {}
                            yield sequence.yield_with_sequence(
                                active.model_copy(deep=True),
                            )

                        block_ids = (event.metadata or {}).get(
                            "content_block_ids",
                            [],
                        )
                        indexes = active_content_indexes[event.id]
                        for position, content in enumerate(event.content or []):
                            block_id = (
                                block_ids[position]
                                if position < len(block_ids)
                                else None
                            )
                            block_key = str(
                                block_id or f"{content.type}:{position}",
                            )
                            content_event = _add_stream_content(
                                active,
                                content.model_copy(deep=True),
                                indexes.get(block_key),
                            )
                            if content_event is None:
                                continue
                            indexes.setdefault(block_key, content_event.index)
                            yield sequence.yield_with_sequence(content_event)
                        continue

                    if event.id in active_streams:
                        _merge_stream_terminal(active_streams[event.id], event)
                        for terminal_event in finalize_stream(event.id):
                            yield sequence.yield_with_sequence(terminal_event)
                        continue

                    if event.status == RunStatus.Completed:
                        response.add_new_message(event.model_copy(deep=True))
                    yield sequence.yield_with_sequence(event)
        except Exception as exc:  # terminal error is projected into response
            converted = (
                exc
                if isinstance(exc, AppBaseException)
                else UnknownAgentException(original_exception=exc)
            )
            logger.error("Agent run failed: %s\n%s", converted, traceback.format_exc())
            yield sequence.yield_with_sequence(
                response.failed(Error(code=converted.code, message=converted.message)),
            )
            return

        for message_id in list(active_streams):
            for terminal_event in finalize_stream(message_id):
                yield sequence.yield_with_sequence(terminal_event)

        if response.output:
            response.usage = response.output[-1].usage
        yield sequence.yield_with_sequence(response.completed())
