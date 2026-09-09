# -*- coding: utf-8 -*-
"""
Console Channel Unit Tests - Simple Channel Template

This serves as the reference implementation for testing simple channels.
For complex channels with external dependencies (HTTP, WebSocket), see
 test_dingtalk.py for advanced patterns.

Key patterns demonstrated:
1. Basic initialization testing
2. Output capture (for console-based channels)
3. Lifecycle testing (start/stop)
4. Simple mocking (no external dependencies)
"""
# pylint: disable=redefined-outer-name,reimported,protected-access
# pylint: disable=unused-argument
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.channels.console.channel import ConsoleChannel


class TestConsoleChannelUnit:
    """
    Unit tests for ConsoleChannel.

    These complement the contract tests by verifying internal behavior,
    such as enabled/disabled state and output formatting.
    """

    @pytest.fixture
    def mock_process(self):
        """Create mock process handler."""

        async def mock_handler(*_args, **_kwargs):
            event = MagicMock()
            event.object = "message"
            event.status = "completed"
            yield event

        return AsyncMock(side_effect=mock_handler)

    @pytest.fixture
    def channel(self, mock_process):
        """Create ConsoleChannel instance."""
        return ConsoleChannel(
            process=mock_process,
            enabled=True,
            bot_prefix="[BOT] ",
            show_tool_details=False,
            filter_tool_messages=False,
            filter_thinking=False,
        )

    def test_init_stores_enabled_flag(self, mock_process):
        """Constructor should store the enabled flag."""
        from qwenpaw.app.channels.console.channel import ConsoleChannel

        ch = ConsoleChannel(
            process=mock_process,
            enabled=False,
            bot_prefix="[TEST] ",
        )

        assert ch.enabled is False
        assert ch.bot_prefix == "[TEST] "

    def test_workspace_scan_excludes_aigc_studio_runtime(self, channel, tmp_path):
        old_output = tmp_path / "aigc_studio" / "canvas-old" / "output.png"
        old_output.parent.mkdir(parents=True)
        old_output.write_bytes(b"old-canvas")
        current = tmp_path / "sessions_data" / "session-current" / "report.md"
        current.parent.mkdir(parents=True)
        current.write_text("current", encoding="utf-8")

        snapshot = channel._scan_workspace_files(tmp_path, "session-current")

        assert "aigc_studio/canvas-old/output.png" not in snapshot
        assert "sessions_data/session-current/report.md" in snapshot

    @pytest.mark.asyncio
    async def test_send_prints_to_stdout(self, channel, capsys):
        """send() should print message to stdout when enabled."""
        await channel.send("user123", "Hello World", meta={})

        captured = capsys.readouterr()
        assert "Hello World" in captured.out
        assert "[BOT]" in captured.out or "user123" in captured.out

    @pytest.mark.asyncio
    async def test_send_disabled_does_nothing(self, mock_process, capsys):
        """send() should do nothing when disabled."""
        from qwenpaw.app.channels.console.channel import ConsoleChannel

        ch = ConsoleChannel(
            process=mock_process,
            enabled=False,
            bot_prefix="[BOT] ",
        )

        await ch.send("user123", "Hello World", meta={})

        captured = capsys.readouterr()
        assert captured.out == ""

    @pytest.mark.asyncio
    async def test_send_includes_prefix(self, mock_process, capsys):
        """send() should include bot_prefix before message."""
        from qwenpaw.app.channels.console.channel import ConsoleChannel

        ch = ConsoleChannel(
            process=mock_process,
            enabled=True,
            bot_prefix=">> ",
        )

        await ch.send("user123", "Test message", meta={})

        captured = capsys.readouterr()
        # Prefix should appear before or with message
        assert ">> " in captured.out
        assert "Test message" in captured.out

    @pytest.mark.asyncio
    async def test_start_when_enabled(self, channel):
        """start() should complete without error when enabled."""
        # Should not raise
        await channel.start()

    @pytest.mark.asyncio
    async def test_start_when_disabled(self, mock_process):
        """start() should handle disabled channel gracefully."""
        from qwenpaw.app.channels.console.channel import ConsoleChannel

        ch = ConsoleChannel(
            process=mock_process,
            enabled=False,
            bot_prefix="",
        )

        # Should not raise
        await ch.start()

    @pytest.mark.asyncio
    async def test_stop_when_enabled(self, channel):
        """stop() should complete without error when enabled."""
        await channel.start()
        await channel.stop()
        # Should not raise

    @pytest.mark.asyncio
    async def test_stop_when_disabled(self, mock_process):
        """stop() should handle disabled channel gracefully."""
        from qwenpaw.app.channels.console.channel import ConsoleChannel

        ch = ConsoleChannel(
            process=mock_process,
            enabled=False,
            bot_prefix="",
        )

        # Should not raise
        await ch.stop()

    @pytest.mark.asyncio
    async def test_send_content_parts_combines_text(
        self,
        mock_process,
        capsys,
    ):
        """send_content_parts() should combine multiple text parts."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        ch = ConsoleChannel(
            process=mock_process,
            enabled=True,
            bot_prefix="",
        )

        parts = [
            TextContent(type=ContentType.TEXT, text="Line 1"),
            TextContent(type=ContentType.TEXT, text="Line 2"),
        ]

        await ch.send_content_parts("user123", parts, meta={})

        captured = capsys.readouterr()
        assert "Line 1" in captured.out
        assert "Line 2" in captured.out


class TestConsoleChannelFromEnv:
    """Tests for from_env factory method."""

    @pytest.fixture
    def mock_process(self):
        return AsyncMock()

    def test_from_env_reads_enabled(self, mock_process, monkeypatch):
        """from_env should read CONSOLE_CHANNEL_ENABLED from environment."""
        from qwenpaw.app.channels.console.channel import ConsoleChannel

        monkeypatch.setenv("CONSOLE_CHANNEL_ENABLED", "0")

        channel = ConsoleChannel.from_env(mock_process)

        assert channel.enabled is False

    def test_from_env_reads_bot_prefix(self, mock_process, monkeypatch):
        """from_env should read CONSOLE_BOT_PREFIX from environment."""
        from qwenpaw.app.channels.console.channel import ConsoleChannel

        monkeypatch.setenv("CONSOLE_BOT_PREFIX", "[TEST] ")

        channel = ConsoleChannel.from_env(mock_process)

        assert channel.bot_prefix == "[TEST] "

    def test_from_env_defaults(self, mock_process, monkeypatch):
        """from_env should use sensible defaults."""
        from qwenpaw.app.channels.console.channel import ConsoleChannel

        # Clear environment
        monkeypatch.delenv("CONSOLE_CHANNEL_ENABLED", raising=False)
        monkeypatch.delenv("CONSOLE_BOT_PREFIX", raising=False)
        monkeypatch.delenv("CONSOLE_MEDIA_DIR", raising=False)

        channel = ConsoleChannel.from_env(mock_process)

        assert channel.enabled is True  # Default enabled
        assert channel.bot_prefix == ""  # Default is empty string


class TestConsoleChannelFromConfig:
    """Tests for from_config factory method."""

    @pytest.fixture
    def mock_process(self):
        return AsyncMock()

    def test_from_config_uses_config_values(self, mock_process):
        """from_config should use values from config object."""
        from qwenpaw.app.channels.console.channel import ConsoleChannel
        from qwenpaw.config.config import ConsoleConfig

        config = ConsoleConfig(
            enabled=False,
            bot_prefix="[CFG] ",
        )

        channel = ConsoleChannel.from_config(
            process=mock_process,
            config=config,
        )

        assert channel.enabled is False
        assert channel.bot_prefix == "[CFG] "


# =============================================================================
# P2: Console Output Formatting (_safe_print, _print_parts, _parts_to_text)
# =============================================================================


class TestConsolePrinting:
    """
    Console output formatting and printing tests.

    Covers _safe_print, _print_parts, _parts_to_text methods.
    """

    @pytest.fixture
    def channel_for_print(self):
        """Create channel for testing print methods."""
        from qwenpaw.app.channels.console.channel import ConsoleChannel

        return ConsoleChannel(
            process=AsyncMock(),
            enabled=True,
            bot_prefix=">> ",
        )

    def test_safe_print_outputs_text(self, channel_for_print, capsys):
        """_safe_print should output text to stdout."""
        channel_for_print._safe_print("Hello World")

        captured = capsys.readouterr()
        assert "Hello World" in captured.out

    def test_print_parts_formats_text_content(
        self,
        channel_for_print,
        capsys,
    ):
        """_print_parts should format and print text content."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        parts = [TextContent(type=ContentType.TEXT, text="Test message")]
        channel_for_print._print_parts(parts, ev_type="message.completed")

        captured = capsys.readouterr()
        assert ">> Test message" in captured.out
        assert "Bot" in captured.out

    def test_print_parts_formats_refusal_content(
        self,
        channel_for_print,
        capsys,
    ):
        """_print_parts should format refusal content."""
        from qwenpaw.app.channels.base import RefusalContent, ContentType

        parts = [
            RefusalContent(
                type=ContentType.REFUSAL,
                refusal="I cannot do that",
            ),
        ]
        channel_for_print._print_parts(parts)

        captured = capsys.readouterr()
        assert "Refusal" in captured.out
        assert "I cannot do that" in captured.out

    def test_print_parts_formats_image_content(
        self,
        channel_for_print,
        capsys,
    ):
        """_print_parts should format image content."""
        from qwenpaw.app.channels.base import ImageContent, ContentType

        parts = [
            ImageContent(
                type=ContentType.IMAGE,
                image_url="http://example.com/image.jpg",
            ),
        ]
        channel_for_print._print_parts(parts)

        captured = capsys.readouterr()
        assert "Image" in captured.out
        assert "http://example.com/image.jpg" in captured.out

    def test_print_parts_formats_video_content(
        self,
        channel_for_print,
        capsys,
    ):
        """_print_parts should format video content."""
        from qwenpaw.app.channels.base import VideoContent, ContentType

        parts = [
            VideoContent(
                type=ContentType.VIDEO,
                video_url="http://example.com/video.mp4",
            ),
        ]
        channel_for_print._print_parts(parts)

        captured = capsys.readouterr()
        assert "Video" in captured.out

    def test_print_error_formats_error(self, channel_for_print, capsys):
        """_print_error should format error message."""
        channel_for_print._print_error("Something went wrong")

        captured = capsys.readouterr()
        assert "Error" in captured.out
        assert "Something went wrong" in captured.out

    def test_parts_to_text_combines_text_parts(self, channel_for_print):
        """_parts_to_text should combine multiple text parts."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        parts = [
            TextContent(type=ContentType.TEXT, text="Line 1"),
            TextContent(type=ContentType.TEXT, text="Line 2"),
        ]

        result = channel_for_print._parts_to_text(parts, meta={})

        assert "Line 1" in result
        assert "Line 2" in result

    def test_parts_to_text_includes_prefix(self, channel_for_print):
        """_parts_to_text should include bot_prefix."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        parts = [TextContent(type=ContentType.TEXT, text="Hello")]

        result = channel_for_print._parts_to_text(parts, meta={})

        assert ">> " in result

    def test_parts_to_text_skips_empty_parts(self, channel_for_print):
        """_parts_to_text should skip empty text parts."""
        from qwenpaw.app.channels.base import TextContent, ContentType

        parts = [
            TextContent(type=ContentType.TEXT, text=""),
            TextContent(type=ContentType.TEXT, text="Valid"),
        ]

        result = channel_for_print._parts_to_text(parts)

        assert "Valid" in result


# =============================================================================
# P2: Console Streaming (stream_one)
# =============================================================================


@pytest.mark.asyncio
class TestConsoleStreaming:
    """
    stream_one streaming process tests.

    Core streaming logic for queue/terminal consumption.
    """

    @pytest.fixture
    def stream_channel(self):
        """Create channel for stream testing."""
        from qwenpaw.app.channels.console.channel import ConsoleChannel

        return ConsoleChannel(
            process=AsyncMock(),
            enabled=True,
            bot_prefix=">> ",
        )

    async def test_stream_one_yields_events(self, stream_channel):
        """stream_one should yield SSE-formatted events."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            RunStatus,
            Event,
            Message,
            MessageType,
            Role,
            TextContent,
            ContentType,
        )

        mock_event = Event(
            object="message",
            status=RunStatus.Completed,
            type="message.completed",
            id="ev-1",
            created_at=1234567890,
            message=Message(
                type=MessageType.MESSAGE,
                role=Role.ASSISTANT,
                content=[
                    TextContent(type=ContentType.TEXT, text="Hello"),
                ],
            ),
        )

        async def mock_process(request):
            yield mock_event

        stream_channel._process = mock_process

        payload = {
            "sender_id": "user123",
            "content_parts": [
                TextContent(
                    type=ContentType.TEXT,
                    text="Hello",
                ),
            ],
            "meta": {},
        }

        events = []
        async for event in stream_channel.stream_one(payload):
            events.append(event)
            break

        assert len(events) == 1
        assert "data:" in events[0]

    async def test_stream_one_handles_dict_payload(self, stream_channel):
        """stream_one should handle dict payload with debounce."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            RunStatus,
            Event,
            Message,
            MessageType,
            Role,
            TextContent,
            ContentType,
        )
        from unittest.mock import patch

        mock_event = Event(
            object="message",
            status=RunStatus.Completed,
            type="message.completed",
            id="ev-1",
            created_at=1234567890,
            message=Message(
                type=MessageType.MESSAGE,
                role=Role.ASSISTANT,
                content=[TextContent(type=ContentType.TEXT, text="Done")],
            ),
        )

        async def mock_process(request):
            yield mock_event

        stream_channel._process = mock_process

        # Payload with content_parts dict-style
        with patch.object(
            stream_channel,
            "_apply_no_text_debounce",
            return_value=(True, []),
        ):
            payload = {
                "sender_id": "user123",
                "content_parts": [],
                "meta": {},
            }

            events = []
            async for event in stream_channel.stream_one(payload):
                events.append(event)
                break

            assert len(events) == 1

    async def test_stream_one_suppresses_standalone_reasoning_events(
        self,
        stream_channel,
    ):
        """Raw reasoning events should not render as empty assistant shells."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            RunStatus,
            Message,
            MessageType,
            Role,
            TextContent,
            ContentType,
        )

        reasoning_event = Message(
            status=RunStatus.Completed,
            type=MessageType.REASONING,
            role=Role.ASSISTANT,
            content=[
                TextContent(type=ContentType.TEXT, text="private thinking"),
            ],
        )
        answer_event = Message(
            status=RunStatus.Completed,
            type=MessageType.MESSAGE,
            role=Role.ASSISTANT,
            content=[
                TextContent(type=ContentType.TEXT, text="visible answer"),
            ],
        )

        async def mock_process(request):
            yield reasoning_event
            yield answer_event

        stream_channel._process = mock_process
        stream_channel._scan_workspace_files = lambda *args: {}

        payload = {
            "sender_id": "user123",
            "content_parts": [
                TextContent(
                    type=ContentType.TEXT,
                    text="Hello",
                ),
            ],
            "meta": {},
        }

        events = []
        async for event in stream_channel.stream_one(payload):
            events.append(event)

        assert len(events) == 1
        assert "visible answer" in events[0]
        assert "private thinking" not in events[0]

    async def test_stream_one_suppresses_reasoning_content_deltas(
        self,
        stream_channel,
    ):
        """Reasoning deltas should not be streamed without their message."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            RunStatus,
            Message,
            MessageType,
            Role,
            TextContent,
            ContentType,
        )

        reasoning_id = "msg_reasoning"
        reasoning_start = Message(
            id=reasoning_id,
            status=RunStatus.InProgress,
            type=MessageType.REASONING,
            role=Role.ASSISTANT,
            content=[],
        )
        reasoning_delta = TextContent(
            type=ContentType.TEXT,
            status=RunStatus.InProgress,
            delta=True,
            msg_id=reasoning_id,
            text="private thinking",
        )
        answer_event = Message(
            status=RunStatus.Completed,
            type=MessageType.MESSAGE,
            role=Role.ASSISTANT,
            content=[
                TextContent(type=ContentType.TEXT, text="visible answer"),
            ],
        )

        async def mock_process(request):
            yield reasoning_start
            yield reasoning_delta
            yield answer_event

        stream_channel._process = mock_process
        stream_channel._scan_workspace_files = lambda *args: {}

        payload = {
            "sender_id": "user123",
            "content_parts": [
                TextContent(
                    type=ContentType.TEXT,
                    text="Hello",
                ),
            ],
            "meta": {},
        }

        events = []
        async for event in stream_channel.stream_one(payload):
            events.append(event)

        assert len(events) == 1
        assert "visible answer" in events[0]
        assert "private thinking" not in events[0]

    async def test_stream_one_does_not_append_card_for_internal_files_only(
        self,
        stream_channel,
    ):
        """Internal agent state changes should not appear as task artifacts."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            RunStatus,
            Message,
            MessageType,
            Role,
            TextContent,
            ContentType,
        )

        answer_event = Message(
            status=RunStatus.Completed,
            type=MessageType.MESSAGE,
            role=Role.ASSISTANT,
            content=[
                TextContent(type=ContentType.TEXT, text="文章已经写好了"),
            ],
        )

        async def mock_process(request):
            yield answer_event

        snapshots = iter(
            [
                {},
                {
                    "agent.json": 2.0,
                    "memory_file_metadata.json": 2.0,
                    "HEARTBEAT.md": 2.0,
                    "MEMORY.md": 2.0,
                    "BOOTSTRAP.md": 2.0,
                    "SOUL.md": 2.0,
                    "AGENTS.md": 2.0,
                    "PROFILE.md": 2.0,
                },
            ],
        )

        stream_channel._process = mock_process
        stream_channel._scan_workspace_files = lambda *args: next(snapshots)

        payload = {
            "sender_id": "user123",
            "content_parts": [
                TextContent(
                    type=ContentType.TEXT,
                    text="写一篇文章",
                ),
            ],
            "meta": {"session_id": "chat-id"},
        }

        events = []
        async for event in stream_channel.stream_one(payload):
            events.append(event)

        combined = "\n".join(events)
        assert "文章已经写好了" in combined
        assert "qwenpaw-artifact-card-trigger" not in combined
        assert "agent.json" not in combined

    async def test_stream_one_falls_back_on_surrogate_json_error(
        self,
        stream_channel,
    ):
        """stream_one should fallback instead of crashing on bad surrogate."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            RunStatus,
            TextContent,
            ContentType,
        )

        class BrokenJsonEvent:
            object = "response"
            status = RunStatus.Completed
            type = "response.completed"
            output = []

            def model_dump_json(self):
                raise UnicodeEncodeError(
                    "utf-8",
                    "\ud83d",
                    0,
                    1,
                    "surrogates not allowed",
                )

            def model_dump(self, mode="python"):
                del mode
                return {
                    "object": "response",
                    "status": "completed",
                    "text": "\ud83d broken",
                }

        async def mock_process(_request):
            yield BrokenJsonEvent()

        stream_channel._process = mock_process

        payload = {
            "sender_id": "user123",
            "content_parts": [
                TextContent(
                    type=ContentType.TEXT,
                    text="Hello",
                ),
            ],
            "meta": {},
        }

        events = []
        async for event in stream_channel.stream_one(payload):
            events.append(event)
            break

        assert len(events) == 1
        assert events[0].startswith("data: ")
        assert "\\ud83d" not in events[0]
        assert "? broken" in events[0]

    async def test_stream_one_raises_when_process_fails(self, stream_channel):
        """stream_one should propagate runtime failures to callers."""
        from agentscope_runtime.engine.schemas.agent_schemas import (
            ContentType,
            TextContent,
        )

        async def mock_process(_request):
            raise RuntimeError("agent runtime failed")
            yield

        stream_channel._process = mock_process

        payload = {
            "sender_id": "user123",
            "content_parts": [
                TextContent(
                    type=ContentType.TEXT,
                    text="Hello",
                ),
            ],
            "meta": {},
        }

        with pytest.raises(RuntimeError, match="agent runtime failed"):
            async for _event in stream_channel.stream_one(payload):
                pass

    async def test_stream_one_raises_when_response_has_error(
        self,
        stream_channel,
    ):
        """stream_one should not hide failed response events."""
        from types import SimpleNamespace
        from agentscope_runtime.engine.schemas.agent_schemas import (
            ContentType,
            RunStatus,
            TextContent,
        )

        class FailedResponseEvent:
            object = "response"
            status = RunStatus.Completed
            type = "response.completed"
            output = []
            error = SimpleNamespace(message="model failed")

            def model_dump_json(self):
                return '{"object": "response", "status": "completed"}'

        async def mock_process(_request):
            yield FailedResponseEvent()

        stream_channel._process = mock_process

        payload = {
            "sender_id": "user123",
            "content_parts": [
                TextContent(
                    type=ContentType.TEXT,
                    text="Hello",
                ),
            ],
            "meta": {},
        }

        events = []
        with pytest.raises(RuntimeError, match="model failed"):
            async for event in stream_channel.stream_one(payload):
                events.append(event)

        assert any("model failed" in event for event in events)

    async def test_consume_one_drain_stream(self, stream_channel):
        """consume_one should drain stream_one."""
        from unittest.mock import patch, AsyncMock

        mock_stream = AsyncMock()
        mock_stream.__aiter__.return_value = ["event1", "event2"]

        with patch.object(
            stream_channel,
            "stream_one",
            return_value=mock_stream,
        ):
            await stream_channel.consume_one({"test": "payload"})


# =============================================================================
# P2: Console Media Handling
# =============================================================================


class TestConsoleMediaHandling:
    """
    Console media directory and handling tests.
    """

    @pytest.fixture
    def media_channel(self):
        """Create channel for media testing."""
        from qwenpaw.app.channels.console.channel import ConsoleChannel

        return ConsoleChannel(
            process=AsyncMock(),
            enabled=True,
            bot_prefix=">> ",
        )

    def test_media_dir_returns_path(self, media_channel):
        """media_dir should return a valid Path."""
        from pathlib import Path

        result = media_channel.media_dir

        assert isinstance(result, Path)
