# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
"""Console Channel.

A lightweight channel that prints all agent responses to stdout.

Messages are sent to the agent via the standard AgentApp ``/agent/process``
endpoint or via POST /console/chat. This channel handles the **output** side:
whenever a completed message event or a proactive send arrives, it is
pretty-printed to the terminal.
"""

from __future__ import annotations

import copy
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from agentscope_runtime.engine.schemas.agent_schemas import (
    MessageType,
    Message,
    RunStatus,
)

from ....config.config import ConsoleConfig as ConsoleChannelConfig
from ...console_push_store import append as push_store_append
from ....constant import DEFAULT_MEDIA_DIR, WORKING_DIR
from ...artifact_filter import filter_user_task_files
from ..base import (
    BaseChannel,
    AudioContent,
    ContentType,
    FileContent,
    ImageContent,
    OnReplySent,
    OutgoingContentPart,
    ProcessHandler,
    VideoContent,
    TextContent,
)
from ..utils import file_url_to_local_path


logger = logging.getLogger(__name__)

# ANSI colour helpers (degrade gracefully if not a tty)
_USE_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

_GREEN = "\033[32m" if _USE_COLOR else ""
_YELLOW = "\033[33m" if _USE_COLOR else ""
_RED = "\033[31m" if _USE_COLOR else ""
_BOLD = "\033[1m" if _USE_COLOR else ""
_RESET = "\033[0m" if _USE_COLOR else ""

_CONSOLE_ATTACHMENT_LINE = re.compile(
    r"^📎 \[(?P<name>[^\]\r\n]+)\]\((?P<ref>[^)\r\n]+)\)$",
)
_IMAGE_ATTACHMENT_SUFFIXES = frozenset(
    {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"},
)


class _ConsoleStreamError(RuntimeError):
    """Raised after an error has already been printed for this stream."""


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _convert_console_attachment_links(
    text: str,
    media_dir: Path,
) -> list[OutgoingContentPart] | None:
    """Promote trusted console-upload Markdown links to typed content."""
    kept_lines: list[str] = []
    attachments: list[OutgoingContentPart] = []
    attachment_names: list[str] = []
    media_root = media_dir.resolve()
    for line in text.splitlines():
        match = _CONSOLE_ATTACHMENT_LINE.fullmatch(line.strip())
        local_ref = (
            file_url_to_local_path(match.group("ref")) if match else None
        )
        if local_ref:
            candidate = Path(local_ref).expanduser().resolve()
            if candidate.is_relative_to(media_root) and candidate.is_file():
                name = match.group("name")
                attachment_names.append(name)
                if candidate.suffix.lower() in _IMAGE_ATTACHMENT_SUFFIXES:
                    attachments.append(
                        ImageContent(
                            type=ContentType.IMAGE,
                            image_url=str(candidate),
                        ),
                    )
                else:
                    attachments.append(
                        FileContent(
                            type=ContentType.FILE,
                            filename=name,
                            file_url=str(candidate),
                        ),
                    )
                continue
        kept_lines.append(line)
    if not attachments:
        return None
    remaining_text = "\n".join(kept_lines).strip()
    label = "已上传附件：" + "、".join(attachment_names)
    return [
        TextContent(
            type=ContentType.TEXT,
            text=(
                f"{remaining_text}\n\n{label}"
                if remaining_text
                else label
            ),
        ),
        *attachments,
    ]


class ConsoleChannel(BaseChannel):
    """Console Channel: prints agent responses to stdout.

    Input is handled by AgentApp's ``/agent/process`` endpoint; this
    channel only takes care of output (printing to the terminal).

    Supports filtering options via config:
        - show_tool_details: Display tool execution details
        - filter_tool_messages: Hide intermediate tool messages
        - filter_thinking: Hide agent thinking/reasoning blocks
    """

    channel = "console"

    def __init__(
        self,
        process: ProcessHandler,
        enabled: bool,
        bot_prefix: str,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        workspace_dir: Optional[Union[str, Path]] = None,
        media_dir: Optional[str] = None,
    ):
        """Initialize ConsoleChannel.

        Args:
            process: Handler for agent requests.
            enabled: Whether this channel is active.
            bot_prefix: Prefix string for bot messages.
            on_reply_sent: Callback when reply is sent.
            show_tool_details: Whether to show tool execution details.
            filter_tool_messages: Whether to filter out tool messages.
            filter_thinking: Whether to filter thinking/reasoning blocks.
            workspace_dir: Agent workspace directory; used to resolve uploaded
                file names (media_dir = workspace_dir / "media").
            media_dir: Agent workspace directory for resolving uploads.
        """
        super().__init__(
            process,
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
        )
        self.enabled = enabled
        self.bot_prefix = bot_prefix
        self._workspace_dir = (
            Path(workspace_dir).expanduser() if workspace_dir else None
        )

        # Use workspace-specific media dir if workspace_dir is provided
        if not media_dir and self._workspace_dir:
            self._media_dir = self._workspace_dir / "media"
        elif media_dir:
            self._media_dir = Path(media_dir).expanduser()
        else:
            self._media_dir = DEFAULT_MEDIA_DIR
        self._media_dir.mkdir(parents=True, exist_ok=True)

        # Windows stdout encoding fix
        if sys.platform == "win32":
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.debug(
                    "Failed to reconfigure stdout encoding on Windows: %s",
                    e,
                )

    @property
    def media_dir(self) -> Path:
        """Media directory"""
        return self._media_dir

    @staticmethod
    def _is_standalone_reasoning_event(event: Any) -> bool:
        """Return True for raw reasoning message events in the stream.

        The final response event already carries reasoning together with the
        assistant message. Streaming the raw reasoning message as its own SSE
        makes the web UI render an empty assistant shell.
        """
        if getattr(event, "object", None) != "message":
            return False

        message = getattr(event, "message", None)
        msg_type = (
            getattr(message, "type", None)
            if message is not None
            else getattr(event, "type", None)
        )
        msg_type_value = getattr(msg_type, "value", msg_type)
        return msg_type_value == MessageType.REASONING

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_reply_sent: OnReplySent = None,
    ) -> "ConsoleChannel":
        return cls(
            process=process,
            enabled=os.getenv("CONSOLE_CHANNEL_ENABLED", "1") == "1",
            bot_prefix=os.getenv("CONSOLE_BOT_PREFIX", ""),
            on_reply_sent=on_reply_sent,
            media_dir=os.getenv("CONSOLE_MEDIA_DIR", ""),
        )

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: ConsoleChannelConfig,
        on_reply_sent: OnReplySent = None,
        show_tool_details: bool = True,
        filter_tool_messages: bool = False,
        filter_thinking: bool = False,
        workspace_dir: Optional[Union[str, Path]] = None,
    ) -> "ConsoleChannel":
        """Create ConsoleChannel from config.

        Args:
            process: Handler for agent requests.
            config: Console channel configuration.
            on_reply_sent: Callback when reply is sent.
            show_tool_details: Whether to show tool execution details.
            filter_tool_messages: Whether to filter out tool messages.
            filter_thinking: Whether to filter thinking/reasoning blocks.
            workspace_dir: Agent workspace directory for resolving uploads.

        Returns:
            Configured ConsoleChannel instance.
        """
        return cls(
            process=process,
            enabled=config.enabled,
            bot_prefix=config.bot_prefix or "",
            on_reply_sent=on_reply_sent,
            show_tool_details=show_tool_details,
            filter_tool_messages=filter_tool_messages,
            filter_thinking=filter_thinking,
            workspace_dir=workspace_dir,
            media_dir=config.media_dir or "",
        )

    def resolve_session_id(
        self,
        sender_id: str,
        channel_meta: Optional[dict] = None,
    ) -> str:
        """Resolve session_id: use explicit meta['session_id'] when provided
        (e.g. from the HTTP /console/chat API), otherwise fall back to
        'console:<sender_id>'.
        """
        if channel_meta and channel_meta.get("session_id"):
            return channel_meta["session_id"]
        return f"{self.channel}:{sender_id}"

    def _scan_workspace_files(
        self,
        workspace_dir: Path,
        current_session_id: Optional[str] = None,
    ) -> dict[str, float]:
        """Scan workspace to record files and their last modification timestamps."""
        files = {}
        if not workspace_dir or not workspace_dir.exists():
            return files

        try:
            # Traverse all files under workspace_dir recursively
            for p in workspace_dir.rglob("*"):
                if p.is_dir():
                    continue
                try:
                    parts = p.relative_to(workspace_dir).parts
                except ValueError:
                    continue

                # Exclude internal VCS or cache files
                if ".git" in parts or ".pytest_cache" in parts:
                    continue

                # AIGC studio canvases are shared runtime internals. Their user-facing
                # cards are projected from fully bound material-task receipts instead
                # of generic workspace modification detection.
                if "aigc_studio" in parts:
                    continue

                # Exclude sessions_data only if it belongs to other sessions
                if "sessions_data" in parts:
                    try:
                        idx = parts.index("sessions_data")
                        if idx + 1 < len(parts):
                            session_folder = parts[idx + 1]
                            # Robust session matching:
                            # 1. Allow if it matches current_session_id
                            # 2. Allow if current_session_id is "claw-global-session" (aggregate main session)
                            # 3. Allow if current_session_id is None/empty (fallback scan)
                            if (
                                not current_session_id
                                or str(current_session_id) == "claw-global-session"
                                or str(session_folder) == str(current_session_id)
                            ):
                                pass
                            else:
                                continue
                        else:
                            continue
                    except ValueError:
                        continue

                try:
                    files[str(p.relative_to(workspace_dir))] = p.stat().st_mtime
                except OSError:
                    continue
        except Exception as e:
            logger.warning("Error scanning workspace files in ConsoleChannel: %s", e)
        return files

    def _assistant_message_text(self, message: Any) -> str:
        """Extract only assistant-facing text, excluding tool outputs."""
        msg_type = getattr(message, "type", None)
        role = str(getattr(message, "role", "") or "").lower()
        if msg_type != MessageType.MESSAGE and role != "assistant":
            return ""

        try:
            parts = self._message_to_content_parts(message)
        except Exception:
            return ""

        texts: list[str] = []
        for part in parts:
            if (
                getattr(part, "type", None) == ContentType.TEXT
                and getattr(part, "text", None)
            ):
                texts.append(part.text)
        return "\n".join(texts).strip()

    @staticmethod
    def _extract_inline_skill_artifact(text: str) -> str | None:
        """Recover a complete SKILL.md accidentally emitted inline."""
        if not text or "name:" not in text or "description:" not in text:
            return None

        fenced = re.finditer(
            r"```(?:markdown|md)?\s*\n(---\s*\n[\s\S]+?)\n```",
            text,
            re.IGNORECASE,
        )
        candidates = [match.group(1).strip() for match in fenced]

        direct = re.search(
            r"(?ms)^---\s*\n(?=[\s\S]*?^name\s*:)(?=[\s\S]*?^description\s*:)",
            text,
        )
        if direct:
            candidate = text[direct.start() :].strip()
            for marker in (
                "\n\n*🔮",
                "\n\n🔮",
                "\n\n技能已",
                "\n\n请在右侧产物面板",
            ):
                marker_idx = candidate.find(marker)
                if marker_idx > 0:
                    candidate = candidate[:marker_idx].strip()
                    break
            candidates.append(candidate)

        for candidate in candidates:
            header = re.match(r"(?ms)^---\s*\n(.*?)\n---\s*\n", candidate)
            if not header:
                continue
            frontmatter = header.group(1)
            if re.search(r"(?m)^name\s*:", frontmatter) and re.search(
                r"(?m)^description\s*:",
                frontmatter,
            ):
                return candidate
        return None

    def _materialize_inline_skill_artifact(
        self,
        workspace_dir: Path,
        current_session_id: Optional[str],
        assistant_texts: list[str],
    ) -> str | None:
        """Write inline skill output to SKILL.md as a last-resort UX guard."""
        deduped_texts: list[str] = []
        seen_texts: set[str] = set()
        for text in assistant_texts:
            if not text or text in seen_texts:
                continue
            seen_texts.add(text)
            deduped_texts.append(text)

        content = self._extract_inline_skill_artifact("\n\n".join(deduped_texts))
        if not content:
            return None

        target_dir = workspace_dir
        if "sessions_data" not in workspace_dir.parts and current_session_id:
            target_dir = workspace_dir / "sessions_data" / str(current_session_id)

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / "SKILL.md"
            if target.exists():
                return None
            target.write_text(content, encoding="utf-8")
            logger.info("Recovered inline skill artifact to %s", target)
            return target.as_posix()
        except Exception as exc:
            logger.warning("Failed to recover inline skill artifact: %s", exc)
            return None

    def _resolve_console_upload_refs(
        self,
        content_parts: List[Any],
    ) -> List[Any]:
        """Resolve Image/File/Audio/VideoContent."""
        if not self._media_dir:
            return content_parts

        def resolve_one(
            part: Any,
        ) -> Optional[OutgoingContentPart | list[OutgoingContentPart]]:
            content_type = getattr(part, "type", None)
            if content_type == ContentType.IMAGE:
                url = getattr(part, "image_url", None)
                if url:
                    return ImageContent(
                        type=ContentType.IMAGE,
                        image_url=url,
                    )
            elif content_type == ContentType.VIDEO:
                url = getattr(part, "video_url", None)
                if url:
                    return VideoContent(
                        type=ContentType.VIDEO,
                        video_url=url,
                    )
            elif content_type == ContentType.AUDIO:
                url = getattr(part, "data", None)
                if url:
                    return AudioContent(
                        type=ContentType.AUDIO,
                        data=url,
                    )
            elif content_type == ContentType.FILE:
                url = getattr(part, "file_url", None)
                if url:
                    return FileContent(
                        type=ContentType.FILE,
                        filename=getattr(part, "filename", None) or url,
                        file_url=url,
                    )
            elif content_type == ContentType.TEXT:
                attachments = _convert_console_attachment_links(
                    part.text,
                    self._media_dir,
                )
                return attachments or TextContent(
                    type=ContentType.TEXT,
                    text=part.text,
                )
            return part

        input_content_parts = []
        for content in content_parts:
            part = resolve_one(content)
            if isinstance(part, list):
                input_content_parts.extend(part)
            elif part is not None:
                input_content_parts.append(part)
        return input_content_parts

    def build_agent_request_from_native(self, native_payload: Any) -> Any:
        """
        Build AgentRequest from console native payload (dict with
        channel_id, sender_id, content_parts, meta). content_parts are
        runtime Content types.
        """
        payload = native_payload if isinstance(native_payload, dict) else {}
        channel_id = payload.get("channel_id") or self.channel
        sender_id = payload.get("sender_id") or ""
        content_parts = payload.get("content_parts") or []
        content_parts = self._resolve_console_upload_refs(content_parts)
        meta = payload.get("meta") or {}
        session_id = self.resolve_session_id(sender_id, meta)
        request = self.build_agent_request_from_user_content(
            channel_id=channel_id,
            sender_id=sender_id,
            session_id=session_id,
            content_parts=content_parts,
            channel_meta=meta,
        )
        request.channel_meta = meta
        return request

    async def _extract_media_message(self, message: Message) -> Message | None:
        """Extract media message from message."""
        parts = self._message_to_content_parts(message)
        media_message = None
        if message.type in (
            MessageType.FUNCTION_CALL_OUTPUT,
            MessageType.PLUGIN_CALL_OUTPUT,
            MessageType.MCP_TOOL_CALL_OUTPUT,
        ):
            new_parts = []
            for part in parts:
                if part.type == ContentType.IMAGE:
                    new_part = copy.deepcopy(part)
                    new_part.image_url = file_url_to_local_path(
                        new_part.image_url,
                    )
                    new_parts.append(new_part)
                elif part.type == ContentType.VIDEO:
                    new_part = copy.deepcopy(part)
                    new_part.video_url = file_url_to_local_path(
                        new_part.video_url,
                    )
                    new_parts.append(new_part)
                elif part.type == ContentType.AUDIO:
                    new_part = copy.deepcopy(part)
                    new_part.data = file_url_to_local_path(new_part.data)
                    new_parts.append(new_part)
                elif part.type == ContentType.FILE:
                    new_part = copy.deepcopy(part)
                    new_part.file_url = file_url_to_local_path(
                        new_part.file_url,
                    )
                    new_parts.append(new_part)
            if new_parts:
                media_message = Message(
                    type=MessageType.MESSAGE,
                    role="assistant",
                    content=new_parts,
                )
        return media_message

    def _extract_token_usage(
        self,
        session_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        from ....token_usage import TokenRecordingModelWrapper

        if not session_id:
            return None

        usage = TokenRecordingModelWrapper.pop_usage_for_session(session_id)
        logger.info("Usage for session %s (cleaned up): %s", session_id, usage)
        return usage

    async def stream_one(self, payload: Any) -> AsyncGenerator[str, None]:
        """Process one payload and yield SSE-formatted events"""
        if isinstance(payload, dict) and "content_parts" in payload:
            session_id = self.resolve_session_id(
                payload.get("sender_id") or "",
                payload.get("meta"),
            )
            content_parts = payload.get("content_parts") or []
            should_process, merged = self._apply_no_text_debounce(
                session_id,
                content_parts,
            )
            if not should_process:
                return
            payload = {**payload, "content_parts": merged}
            request = self.build_agent_request_from_native(payload)
        else:
            request = payload
            session_id = getattr(request, "session_id", "") or ""
            if getattr(request, "input", None):
                contents = list(
                    getattr(request.input[0], "content", None) or [],
                )
                should_process, merged = self._apply_no_text_debounce(
                    session_id,
                    contents,
                )
                if not should_process:
                    return
                if merged and hasattr(request.input[0], "content"):
                    request.input[0].content = merged

        # Scan files before executing reply
        workspace_dir = Path(self._workspace_dir or WORKING_DIR)
        
        send_meta = getattr(request, "channel_meta", None) or {}
        real_session_id = send_meta.get("session_id") or send_meta.get("root_session_id")
        if real_session_id:
            session_id = real_session_id
            
        old_files = self._scan_workspace_files(workspace_dir, session_id)

        try:
            send_meta.setdefault("bot_prefix", self.bot_prefix)
            last_response = None
            event_count = 0
            has_card_trigger = False
            assistant_texts: list[str] = []
            suppressed_reasoning_msg_ids: set[str] = set()

            async for event in self._process(request):
                event_count += 1
                obj = getattr(event, "object", None)
                status = getattr(event, "status", None)
                ev_type = getattr(event, "type", None)

                logger.debug(
                    "console event #%s: object=%s status=%s type=%s",
                    event_count,
                    obj,
                    status,
                    ev_type,
                )

                if self._is_standalone_reasoning_event(event):
                    msg_id = getattr(event, "id", None)
                    if msg_id:
                        suppressed_reasoning_msg_ids.add(str(msg_id))
                    logger.debug(
                        "console event #%s suppressed standalone reasoning",
                        event_count,
                    )
                    continue

                if (
                    obj == "content"
                    and str(getattr(event, "msg_id", "") or "")
                    in suppressed_reasoning_msg_ids
                ):
                    logger.debug(
                        "console event #%s suppressed reasoning content",
                        event_count,
                    )
                    continue

                # Check if event content contains artifact card trigger
                if hasattr(event, "content") and event.content:
                    if isinstance(event.content, str) and "qwenpaw-artifact-card-trigger" in event.content:
                        has_card_trigger = True
                    elif isinstance(event.content, list):
                        for part in event.content:
                            if isinstance(part, dict) and part.get("type") == "text" and "qwenpaw-artifact-card-trigger" in part.get("text", ""):
                                has_card_trigger = True
                            elif hasattr(part, "text") and part.text and "qwenpaw-artifact-card-trigger" in part.text:
                                has_card_trigger = True

                if (
                    event.object == "response"
                    and event.status == RunStatus.Completed
                ):
                    event_output = event.output
                    event.output = []
                    if event_output is not None:
                        for message in event_output:
                            event.output.append(message)
                            assistant_text = self._assistant_message_text(message)
                            if assistant_text:
                                assistant_texts.append(assistant_text)
                            
                            # Check nested output messages for artifact card trigger
                            if hasattr(message, "content") and message.content:
                                if isinstance(message.content, str) and "qwenpaw-artifact-card-trigger" in message.content:
                                    has_card_trigger = True
                                elif isinstance(message.content, list):
                                    for part in message.content:
                                        if isinstance(part, dict) and part.get("type") == "text" and "qwenpaw-artifact-card-trigger" in part.get("text", ""):
                                            has_card_trigger = True
                                        elif hasattr(part, "text") and part.text and "qwenpaw-artifact-card-trigger" in part.text:
                                            has_card_trigger = True

                            media_message = await self._extract_media_message(
                                message,
                            )
                            if media_message:
                                event.output.append(media_message)

                if obj == "response":
                    usage_data = self._extract_token_usage(session_id)
                    if usage_data and hasattr(event, "usage"):
                        setattr(event, "usage", usage_data)

                    response_error = self._get_response_error_message(event)
                    if response_error:
                        error_message = Message(
                            id=(
                                f"error_{session_id}_"
                                f"{int(datetime.now().timestamp() * 1000)}"
                            ),
                            type=MessageType.MESSAGE,
                            role="assistant",
                            content=[
                                TextContent(
                                    type=ContentType.TEXT,
                                    text=f"请求处理失败：{response_error}",
                                ),
                            ],
                            name="DClaw",
                            status=RunStatus.Completed,
                        )
                        error_json = self._serialize_event_for_sse(
                            error_message,
                        )
                        yield f"data: {error_json}\n\n"

                data = self._serialize_event_for_sse(event)
                yield f"data: {data}\n\n"

                if obj == "message" and status == RunStatus.Completed:
                    assistant_text = self._assistant_message_text(event)
                    if assistant_text:
                        assistant_texts.append(assistant_text)

                    media_message = await self._extract_media_message(event)
                    if media_message:
                        media_json = self._serialize_event_for_sse(
                            media_message,
                        )
                        yield f"data: {media_json}\n\n"

                    parts = self._message_to_content_parts(event)
                    self._print_parts(parts, ev_type)

                elif obj == "response":
                    last_response = event

            logger.info(
                "console stream done: event_count=%s has_response=%s",
                event_count,
                last_response is not None,
            )

            # Auto-append delivery card trigger html if there are workspace file modifications and no trigger has been sent yet
            if not has_card_trigger:
                self._materialize_inline_skill_artifact(
                    workspace_dir,
                    session_id,
                    assistant_texts,
                )
                new_files = self._scan_workspace_files(workspace_dir, session_id)
                modified_files = []
                for rel_path, mtime in new_files.items():
                    if rel_path not in old_files or mtime > old_files[rel_path]:
                        modified_files.append(rel_path)

                cleaned_modified_files = []
                for f in modified_files:
                    parts = Path(f).parts
                    if "sessions_data" in parts:
                        try:
                            idx = parts.index("sessions_data")
                            if idx + 1 < len(parts):
                                cleaned_rel = Path(*parts[idx + 2 :])
                                cleaned_modified_files.append(str(cleaned_rel))
                            else:
                                cleaned_modified_files.append(f)
                        except ValueError:
                            cleaned_modified_files.append(f)
                    else:
                        cleaned_modified_files.append(f)

                cleaned_modified_files = filter_user_task_files(
                    cleaned_modified_files,
                )

                if cleaned_modified_files:
                    import json
                    import base64
                    files_json = json.dumps(cleaned_modified_files)
                    encoded_files = base64.b64encode(files_json.encode('utf-8')).decode('utf-8')
                    trigger_html = f'🎯 **本次任务产生的制品和文件变更如下**：\n\n[qwenpaw-artifact-card-trigger](http://qwenpaw.local/?data={encoded_files})\n'
                    
                    artifact_msg = Message(
                        id=f"artifact_{session_id}_{int(datetime.now().timestamp())}",
                        type=MessageType.MESSAGE,
                        role="assistant",
                        content=[TextContent(type=ContentType.TEXT, text=trigger_html)],
                        name="DClaw",
                        status=RunStatus.Completed,
                    )
                    artifact_json = self._serialize_event_for_sse(artifact_msg)
                    yield f"data: {artifact_json}\n\n"
                    logger.info("Auto-appended delivery card trigger HTML for modified files: %s", cleaned_modified_files)

            err_msg = self._get_response_error_message(last_response)
            if err_msg:
                self._print_error(err_msg)
                raise _ConsoleStreamError(err_msg)

            to_handle = request.user_id or ""
            if self._on_reply_sent:
                self._on_reply_sent(
                    self.channel,
                    to_handle,
                    request.session_id or f"{self.channel}:{to_handle}",
                )

        except _ConsoleStreamError:
            raise
        except Exception as e:
            logger.exception("console process/reply failed")
            err_msg = str(e).strip() or "An error occurred while processing."
            self._print_error(err_msg)
            raise RuntimeError(err_msg) from e

    async def consume_one(self, payload: Any) -> None:
        """Process one payload; drain stream_one (queue/terminal)."""
        async for _ in self.stream_one(payload):
            pass

    # ── pretty-print helpers ────────────────────────────────────────

    def _safe_print(self, text: str) -> None:
        """Safely print text, handling Windows encoding and pipe issues.

        On Windows, print() can raise OSError [Errno 22] when output is
        piped or contains unsupported characters. This wrapper handles
        such cases gracefully.
        """
        try:
            print(text)
        except OSError as e:
            if e.errno == 22:
                logger.warning(
                    "Print failed with OSError [Errno 22], attempting "
                    "fallback encoding",
                )
                try:
                    sys.stdout.buffer.write(
                        text.encode("utf-8", errors="replace"),
                    )
                    sys.stdout.buffer.write(b"\n")
                    sys.stdout.buffer.flush()
                except Exception as fallback_err:
                    logger.error(
                        "Failed to print even with fallback: %s",
                        fallback_err,
                    )
            else:
                logger.error("Print failed with OSError: %s", e)

    def _print_parts(
        self,
        parts: List[OutgoingContentPart],
        ev_type: Optional[str] = None,
    ) -> None:
        """Print outgoing content parts to stdout."""
        ts = _ts()
        label = f" ({ev_type})" if ev_type else ""
        self._safe_print(
            f"\n{_GREEN}{_BOLD}🤖 [{ts}] Bot{label}{_RESET}",
        )
        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT and getattr(p, "text", None):
                self._safe_print(f"{self.bot_prefix}{p.text}")
            elif t == ContentType.REFUSAL and getattr(p, "refusal", None):
                self._safe_print(f"{_RED}⚠ Refusal: {p.refusal}{_RESET}")
            elif t == ContentType.IMAGE and getattr(p, "image_url", None):
                self._safe_print(f"{_YELLOW}🖼  [Image: {p.image_url}]{_RESET}")
            elif t == ContentType.VIDEO and getattr(p, "video_url", None):
                self._safe_print(f"{_YELLOW}🎬 [Video: {p.video_url}]{_RESET}")
            elif t == ContentType.AUDIO and getattr(p, "data", None):
                self._safe_print(f"{_YELLOW}🔊 [Audio]{_RESET}")
            elif t == ContentType.FILE:
                url = (
                    getattr(p, "file_url", None)
                    or getattr(p, "file_id", None)
                    or ""
                )
                self._safe_print(f"{_YELLOW}📎 [File: {url}]{_RESET}")
        self._safe_print("")

    def _print_error(self, err: str) -> None:
        ts = _ts()
        self._safe_print(
            f"\n{_RED}{_BOLD}❌ [{ts}] Error{_RESET}\n{_RED}{err}{_RESET}\n",
        )

    def _parts_to_text(
        self,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Merge parts to one body string (same logic as base send_content_parts).
        """
        text_parts: List[str] = []
        for p in parts:
            t = getattr(p, "type", None)
            if t == ContentType.TEXT and getattr(p, "text", None):
                text_parts.append(p.text or "")
            elif t == ContentType.REFUSAL and getattr(p, "refusal", None):
                text_parts.append(p.refusal or "")
        body = "\n".join(text_parts) if text_parts else ""
        prefix = (meta or {}).get("bot_prefix", self.bot_prefix) or ""
        if prefix and body:
            body = prefix + "  " + body
        return body

    # ── send (for proactive sends / cron) ───────────────────────────

    async def send(
        self,
        to_handle: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a text message — prints to stdout and pushes to frontend."""
        if not self.enabled:
            return
        ts = _ts()
        prefix = (meta or {}).get("bot_prefix", self.bot_prefix) or ""
        self._safe_print(
            f"\n{_GREEN}{_BOLD}🤖 [{ts}] Bot → {to_handle}{_RESET}\n"
            f"{prefix}{text}\n",
        )
        sid = (meta or {}).get("session_id")
        if sid and text.strip():
            await push_store_append(sid, text.strip())

    async def send_content_parts(
        self,
        to_handle: str,
        parts: List[OutgoingContentPart],
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Send content parts — prints to stdout and pushes to frontend store.
        """
        self._print_parts(parts)
        sid = (meta or {}).get("session_id")
        if sid:
            body = self._parts_to_text(parts, meta)
            if body.strip():
                await push_store_append(sid, body.strip())

    # ── lifecycle ───────────────────────────────────────────────────

    async def health_check(self) -> Dict[str, Any]:
        """Console channel is always healthy when enabled."""
        if not self.enabled:
            return {
                "channel": self.channel,
                "status": "disabled",
                "detail": "Console channel is disabled.",
            }
        return {
            "channel": self.channel,
            "status": "healthy",
            "detail": "Console channel is running.",
        }

    async def start(self) -> None:
        if not self.enabled:
            logger.debug("console channel disabled")
            return
        logger.info("Console channel started")

    async def stop(self) -> None:
        if not self.enabled:
            return
        logger.info("console channel stopped")
