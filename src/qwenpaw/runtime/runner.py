"""DClaw-owned runner lifecycle and public event projection."""

from __future__ import annotations

import inspect
import logging
import traceback
from contextlib import AsyncExitStack
from typing import Any, AsyncGenerator
from uuid import uuid4

from agentscope.message import Msg

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
        yield sequence.yield_with_sequence(response)
        yield sequence.yield_with_sequence(response.in_progress())

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
                    if event.status == RunStatus.Completed:
                        response.add_new_message(event)
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

        if response.output:
            response.usage = response.output[-1].usage
        yield sequence.yield_with_sequence(response.completed())
