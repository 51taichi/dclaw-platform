# -*- coding: utf-8 -*-
# pylint: disable=unused-argument too-many-branches too-many-statements
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncGenerator, Coroutine

import frontmatter as fm
from agentscope.message import Msg, TextBlock
from agentscope_runtime.engine.runner import Runner
from agentscope_runtime.engine.schemas.agent_schemas import AgentRequest
from agentscope_runtime.engine.schemas.exception import (
    AgentException,
    AppBaseException,
)
from dotenv import load_dotenv

from .command_dispatch import (
    _get_last_user_text,
    _is_command,
    run_command_path,
)
from .query_error_dump import write_query_error_dump
from .mission_dispatch import (
    maybe_handle_mission_command,
    detect_active_mission_phase,
)
from .session_sqlite import SqliteSession
from .utils import build_env_context
from ..channels.schema import DEFAULT_CHANNEL
from ..storage.engine import get_app_engine
from ..storage.settings import get_storage_settings
from ..open_api.agent_response_format import (
    install_open_api_agent_response_format,
    is_trusted_direct_agent_open_api,
)
from ...agents.react_agent import QwenPawAgent
from ...exceptions import convert_model_exception
from ...agents.utils.file_handling import (
    read_text_file_with_encoding_fallback,
)
from ...config.config import load_agent_config
from ...constant import WORKING_DIR
from ..workspace.orchestration import (
    WorkspaceOrchestrationError,
    WorkspaceTurnResult,
    is_workspace_business_turn,
    resolve_active_workspace_authorization,
    run_workspace_orchestration_turn,
    workspace_result_to_message,
)

if TYPE_CHECKING:
    from ...agents.memory import BaseMemoryManager
    from ...agents.context import BaseContextManager

logger = logging.getLogger(__name__)


async def _list_aigc_capabilities_for_workspace(request: Any) -> dict[str, Any]:
    """Project the existing user-scoped AIGC inventory into the Host boundary."""
    from ...providers.provider_manager import ProviderManager
    from ..routers.aigc_studio import build_capability_list

    # ``request`` is an AgentScope AgentRequest here, not a Starlette Request.
    # Resolve the application singleton directly so workspace runtimes can use
    # the same catalog builder without depending on ``request.app.state``.
    _ = request
    result = await build_capability_list(ProviderManager.get_instance())
    return result.model_dump(mode="json")


async def _list_aigc_workflow_capabilities_for_workspace(
    request: Any,
) -> dict[str, Any]:
    """Project the closed workflow registry and live priced models to Host."""
    from ...providers.provider_manager import ProviderManager
    from ..routers.aigc_studio import build_workflow_capability_catalog

    _ = request
    result = await build_workflow_capability_catalog(ProviderManager.get_instance())
    return result.model_dump(mode="json")


_PRINT_END_SIGNAL = "[END]"


def _is_isolated_agent_open_api_request(request: Any) -> bool:
    """Accept isolation only from the trusted Agent OpenAPI payload shape."""
    from ..open_api.execution_mode import is_isolated_agent_open_api

    channel = str(getattr(request, "channel", "") or "")
    meta = getattr(request, "channel_meta", None)
    return bool(
        channel.startswith("open:")
        and isinstance(meta, dict)
        and is_isolated_agent_open_api(meta)
        and meta.get("target_type") == "agent"
        and meta.get("execution_mode") == "isolated_attempt"
        and str(meta.get("open_invocation_id") or "").strip()
    )


async def _cancel_streaming_agent_task(task: asyncio.Task) -> None:
    if task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.debug(
            "Streaming agent task finished with error during cancellation",
            exc_info=True,
        )


async def _stream_printing_messages_interruptible(
    *,
    agents: list[Any],
    coroutine_task: Coroutine[Any, Any, Msg],
) -> AsyncGenerator[tuple[Msg, bool], None]:
    """Like agentscope.stream_printing_messages, but cancel the agent task
    promptly when the outer stream is stopped or closed.
    """

    queue: asyncio.Queue = asyncio.Queue()
    for agent in agents:
        agent.set_msg_queue_enabled(True, queue)

    task = asyncio.create_task(coroutine_task)
    if task.done():
        await queue.put(_PRINT_END_SIGNAL)
    else:
        task.add_done_callback(lambda _: queue.put_nowait(_PRINT_END_SIGNAL))

    try:
        while True:
            printing_msg = await queue.get()
            if (
                isinstance(printing_msg, str)
                and printing_msg == _PRINT_END_SIGNAL
            ):
                break
            msg, last, _ = printing_msg
            yield msg, last

        exception = task.exception()
        if exception is not None:
            raise exception from None
    except asyncio.CancelledError:
        await _cancel_streaming_agent_task(task)
        raise
    finally:
        await _cancel_streaming_agent_task(task)


async def _run_standard_or_orchestrated_turn(
    *,
    agent: Any,
    messages: list[Any],
    request: Any,
    query: str | None,
    mission_info: dict[str, Any] | None,
    agent_id: str,
    agent_name: str,
    workspace_root: Path,
    orchestration: Any,
) -> AsyncGenerator[tuple[Msg, bool, bool], None]:
    """Yield messages plus whether session state may be persisted."""
    if not orchestration.enabled or not is_workspace_business_turn(
        query,
        mission_info=mission_info,
    ):
        async for msg, last in _stream_printing_messages_interruptible(
            agents=[agent],
            coroutine_task=agent(messages),
        ):
            yield msg, last, True
        return
    try:
        authorization = resolve_active_workspace_authorization(
            agent_id=agent_id,
            workspace_root=workspace_root,
            tenant_id=str(getattr(request, "tenant_id", "local") or "local"),
            config=orchestration,
        )
        tenant_id = str(getattr(request, "tenant_id", "local") or "local")
        from ..super_experts.composition import (
            get_super_expert_platform_service,
        )
        platform_service = get_super_expert_platform_service()
        platform_events = platform_service.list_session_events(
            installation_id=authorization.installation_id,
            conversation_id=str(request.session_id),
        )
        conversation_history: list[Any] = []
        memory = getattr(agent, "memory", None)
        get_memory = getattr(memory, "get_memory", None)
        if callable(get_memory):
            conversation_history = list(
                await get_memory(prepend_summary=True),
            )

        async def business_call(
            capability: str,
            arguments: dict[str, Any],
        ) -> dict[str, Any]:
            payload = dict(arguments)
            contract_version = authorization.granted_capabilities.get(capability)
            if contract_version is None:
                raise WorkspaceOrchestrationError("unauthorized_capability")
            if capability == "aigc.capabilities.list/1":
                if payload:
                    raise WorkspaceOrchestrationError("orchestration_error")
                return await _list_aigc_capabilities_for_workspace(request)
            if capability == "aigc.workflow.capabilities.list/1":
                if payload:
                    raise WorkspaceOrchestrationError("orchestration_error")
                return await _list_aigc_workflow_capabilities_for_workspace(request)
            idempotency_key = str(payload.pop("idempotency_key", ""))
            if not idempotency_key:
                raise WorkspaceOrchestrationError("orchestration_error")
            return await platform_service.execute(
                tenant_id=tenant_id,
                user_id=str(getattr(request, "user_id", "") or ""),
                installation_id=authorization.installation_id,
                capability=capability,
                contract_version=contract_version,
                arguments=payload,
                idempotency_key=idempotency_key,
            )

        from ..workspace.media_review_context import current_review_input
        review_input = current_review_input(
            user_id=str(request.user_id), installation_id=authorization.installation_id,
            conversation_id=str(request.session_id),
        )
        result = await run_workspace_orchestration_turn(
            agent=agent,
            original_messages=messages,
            conversation_history=conversation_history,
            request=request,
            agent_id=agent_id,
            workspace_root=workspace_root,
            state_storage_root=Path(WORKING_DIR) / "workspace_runtime_state",
            config=orchestration,
            authorization=authorization,
            business_call=business_call,
            safe_metadata={
                "platformEvents": [
                    event.model_dump(mode="json") for event in platform_events
                ],
                **({"aigcReviewInput": review_input} if review_input is not None else {}),
            },
        )
    except WorkspaceOrchestrationError:
        logger.exception(
            "Workspace orchestration failed closed for agent %s",
            agent_id,
        )
        result = WorkspaceTurnResult(error_code="orchestration_error")
    response_message = workspace_result_to_message(result, agent_name=agent_name)
    if result.error_code is None:
        memory = getattr(agent, "memory", None)
        add_to_memory = getattr(memory, "add", None)
        if callable(add_to_memory):
            for message in messages:
                await add_to_memory(message)
            await add_to_memory(response_message)
    yield (
        response_message,
        True,
        result.error_code is None,
    )


class AgentRunner(Runner):
    def __init__(
        self,
        agent_id: str = "default",
        workspace_dir: Path | None = None,
        task_tracker: Any | None = None,
    ) -> None:
        super().__init__()
        self.framework_type = "agentscope"
        self.agent_id = agent_id  # Store agent_id for config loading
        self.workspace_dir = (
            workspace_dir  # Store workspace_dir for prompt building
        )
        self._chat_manager = None  # Store chat_manager reference
        self._mcp_manager = None  # MCP client manager for hot-reload
        self._workspace: Any = None  # Workspace instance for control commands
        self.memory_manager: BaseMemoryManager | None = None
        self.context_manager: BaseContextManager | None = None
        self._task_tracker = task_tracker  # Task tracker for background tasks
        self._agent_name: str | None = None

    @property
    def agent_name(self) -> str:
        """Agent display name from config, cached after first access."""
        if self._agent_name is None:
            try:
                cfg = load_agent_config(self.agent_id)
                self._agent_name = cfg.name if cfg and cfg.name else "DClaw"
            except Exception:
                self._agent_name = "DClaw"
        return self._agent_name

    def invalidate_agent_name_cache(self) -> None:
        """Clear cached agent_name so next access re-reads config."""
        self._agent_name = None

    def set_chat_manager(self, chat_manager):
        """Set chat manager for auto-registration.

        Args:
            chat_manager: ChatManager instance
        """
        self._chat_manager = chat_manager

    def set_mcp_manager(self, mcp_manager):
        """Set MCP client manager for hot-reload support.

        Args:
            mcp_manager: MCPClientManager instance
        """
        self._mcp_manager = mcp_manager

    def set_workspace(self, workspace):
        """Set workspace for control command handlers.

        Args:
            workspace: Workspace instance
        """
        self._workspace = workspace

    @staticmethod
    def _parse_skill_query(
        query: str,
    ) -> tuple[str, str] | None:
        """Parse ``/name [input]`` or ``/[name with spaces] [input]``.

        Bracket form ``/[...]`` handles spaces in skill names and
        bypasses built-in command priority.

        Returns ``(skill_name, user_input)`` or ``None``.
        """
        stripped = query.strip()
        if not stripped.startswith("/"):
            return None

        rest = stripped[1:]  # drop leading /

        # /[skill name] input — bracket form
        if rest.startswith("["):
            close = rest.find("]")
            if close < 0:
                return None
            name = rest[1:close].strip().lower()
            user_input = rest[close + 1 :].strip()
            return (name, user_input) if name else None

        # /name input — plain form
        parts = rest.split(None, 1)
        if not parts:
            return None
        name = parts[0].lower()
        user_input = parts[1] if len(parts) > 1 else ""
        return (name, user_input) if name else None

    def _maybe_inject_skill(
        self,
        query: str | None,
        msgs: list,
        skills: dict,
    ) -> Msg | None:
        """Handle ``/<skill_name> [input]`` or ``/[skill name] [input]``.

        *skills* is ``agent.toolkit.skills`` — already resolved for
        the current channel during agent init.  Hot-reload safe because
        the agent is recreated on every query.

        Returns a ``Msg`` to short-circuit (skill info), or ``None``
        to continue to the LLM with rewritten ``msgs``.
        """
        if not query or not query.startswith("/") or not msgs:
            return None

        parsed = AgentRunner._parse_skill_query(query)
        if not parsed:
            return None
        name, user_input = parsed

        # Lookup by folder name
        skill = next(
            (
                s
                for s in skills.values()
                if Path(s["dir"]).name.lower() == name
            ),
            None,
        )
        if not skill:
            return None

        skill_dir = Path(skill["dir"])
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            return None

        raw = read_text_file_with_encoding_fallback(skill_md)
        post = fm.loads(raw)
        display_name = post.get("name") or name

        # /<name> without input → return skill info.
        if not user_input:
            desc = post.get("description") or "No description."
            logger.info("Skill info: %s", name)
            return Msg(
                name=self.agent_name,
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"**{name}**\n\n"
                            f"- **command**: `/{name} <input>` to invoke\n"
                            f"- **name**: {display_name}\n"
                            f"- **description**: {desc}\n"
                            f"- **path**: `{skill_dir}`"
                        ),
                    ),
                ],
            )

        # /<name> <input> → rewrite user message with skill body.
        merged = (
            f"Use the [{display_name}] skill in "
            f"`{skill_dir}` to fulfill "
            f"user's task: {user_input}\n\n"
            f"{post.content}"
        )
        AgentRunner._rewrite_last_message_text(msgs, merged)
        logger.info("Skill invocation: %s", name)
        return None

    @staticmethod
    def _rewrite_last_message_text(
        msgs: list,
        new_text: str,
    ) -> None:
        """Rewrite the text content of the last message in-place."""
        if not msgs:
            return
        last = msgs[-1]
        content = getattr(last, "content", None)
        if isinstance(content, list):
            for i, block in enumerate(content):
                if isinstance(block, dict) and block.get("type") == "text":
                    content[i] = TextBlock(
                        type="text",
                        text=new_text,
                    )
                    return
            content.insert(
                0,
                TextBlock(type="text", text=new_text),
            )
        elif isinstance(content, str):
            last.content = new_text

    async def query_handler(
        self,
        msgs,
        request: AgentRequest = None,
        **kwargs,
    ):
        """
        Handle agent query.
        """
        logger.debug(
            f"AgentRunner.query_handler called: agent_id={self.agent_id}, "
            f"msgs={msgs}, request={request}",
        )
        query = _get_last_user_text(msgs)
        session_id = getattr(request, "session_id", "") or ""
        isolated_agent_open_api = _is_isolated_agent_open_api_request(request)

        # Check if query is a command (including /approval)
        logger.debug(f"Query: {query!r}, is_command: {_is_command(query)}")
        if query and _is_command(query) and not isolated_agent_open_api:
            logger.info("Command path: %s", query.strip()[:50])
            async for msg, last in run_command_path(request, msgs, self):
                yield msg, last
            return

        logger.debug(
            f"AgentRunner.stream_query: request={request}, "
            f"agent_id={self.agent_id}",
        )

        # Set agent context for model creation
        from ..agent_context import (
            set_current_agent_id,
            set_current_knowledge_base_id,
            set_current_session_id,
            set_current_root_session_id,
            set_current_user_id,
        )

        set_current_agent_id(self.agent_id)

        # Set session_id and user_id in context for token usage tracking
        set_current_session_id(session_id)
        user_id = getattr(request, "user_id", "default")
        set_current_user_id(user_id)
        set_current_knowledge_base_id(None)

        agent = None
        chat = None
        session_state_loaded = False
        try:
            session_id = request.session_id
            user_id = request.user_id
            channel = getattr(request, "channel", DEFAULT_CHANNEL)

            logger.info(
                "Handle agent query:\n%s",
                json.dumps(
                    {
                        "session_id": session_id,
                        "user_id": user_id,
                        "channel": channel,
                        "msgs_len": len(msgs) if msgs else 0,
                        "msgs_str": str(msgs)[:300] + "...",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )

            # Optional sender display name from channel_meta.user_name.
            channel_meta = getattr(request, "channel_meta", None)
            if not isinstance(channel_meta, dict):
                channel_meta = {}
            user_name = channel_meta.get("user_name")

            # Load agent-specific configuration
            agent_config = load_agent_config(self.agent_id)

            _configured_shell = (
                agent_config.running.shell_command_executable or None
            )
            _default_shell = (
                _configured_shell
                or os.environ.get("SHELL")
                or ("cmd.exe" if sys.platform == "win32" else "/bin/sh")
            )
            env_context = build_env_context(
                session_id=session_id,
                user_id=user_id,
                user_name=user_name,
                channel=channel,
                working_dir=(
                    str(self.workspace_dir)
                    if self.workspace_dir
                    else str(WORKING_DIR)
                ),
                default_shell=_default_shell,
            )

            # Get MCP clients from manager (hot-reloadable)
            mcp_clients = []
            if self._mcp_manager is not None:
                mcp_clients = await self._mcp_manager.get_clients()

            logger.debug(f"Enabled MCP: {mcp_clients}")

            # Build base request context
            base_request_context = {
                "session_id": session_id,
                "user_id": user_id,
                "channel": channel,
                "agent_id": self.agent_id,
                "root_agent_id": self.agent_id,
                "metadata": {},
            }
            if str(channel).startswith("open:"):
                from ..sealed_agents.request_context import (
                    normalize_untrusted_metadata,
                )

                base_request_context["metadata"] = normalize_untrusted_metadata(
                    channel_meta.get("metadata"),
                )
                knowledge_base_id = str(
                    channel_meta.get("knowledge_base_id") or "",
                ).strip()
                if knowledge_base_id:
                    base_request_context["knowledge_base_id"] = knowledge_base_id
                    set_current_knowledge_base_id(knowledge_base_id)
            payload_context = getattr(request, "request_context", None)
            if isinstance(payload_context, dict):
                base_request_context.update(payload_context)
            # Caller-controlled context may add namespaced values but cannot
            # replace the server-resolved execution and billing identity.
            base_request_context.update(
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "channel": channel,
                    "agent_id": self.agent_id,
                    "root_agent_id": self.agent_id,
                    "_persist_context_dialog": not isolated_agent_open_api,
                    "_open_api_direct_agent_execution": (
                        is_trusted_direct_agent_open_api(
                            channel,
                            channel_meta,
                        )
                    ),
                },
            )

            # Extract root_session_id from request payload (agent chat)
            payload_root_session = getattr(request, "root_session_id", "")
            if payload_root_session and isinstance(payload_root_session, str):
                base_request_context["root_session_id"] = payload_root_session
                set_current_root_session_id(payload_root_session)
                root_preview = (
                    payload_root_session[:12]
                    if len(payload_root_session) >= 12
                    else payload_root_session
                )
                logger.debug(
                    "Runner: using root_session_id from payload: %s",
                    root_preview,
                )
            else:
                # Current session is the root
                base_request_context["root_session_id"] = session_id
                set_current_root_session_id(session_id)
                session_preview = (
                    session_id[:12] if len(session_id) >= 12 else session_id
                )
                logger.debug(
                    "Runner: current session is root: %s",
                    session_preview,
                )

            # Mission Mode: /mission
            _ws = self.workspace_dir or WORKING_DIR
            mission_info: dict | None = None

            mission_result = None
            if not isolated_agent_open_api:
                mission_result = await maybe_handle_mission_command(
                    query=query,
                    msgs=msgs,
                    workspace_dir=_ws,
                    agent_id=self.agent_id,
                    rewrite_fn=self._rewrite_last_message_text,
                    session_id=session_id,
                    agent_name=self.agent_name,
                )
            if isinstance(mission_result, Msg):
                yield mission_result, True
                return
            if isinstance(mission_result, dict):
                mission_info = mission_result

            # Active mission: auto-detect follow-up messages
            # (e.g., user confirms PRD without typing /mission again)
            if mission_info is None and not isolated_agent_open_api:
                mission_info = detect_active_mission_phase(
                    _ws,
                    session_id=session_id,
                )

            # Mission Mode: inject context reminder for active mission
            if mission_info is not None:
                # Inject context reminder for active mission
                loop_dir = mission_info.get("loop_dir", "")
                phase = mission_info.get("mission_phase", 1)
                if phase == 1:
                    refresher = (
                        f"[Mission active — dir: `{loop_dir}`]\n"
                        f"You are in Mission Phase 1 (PRD review). "
                        f"The user's message follows.\n"
                        f"If the user is confirming the PRD, update "
                        f"`{loop_dir}/loop_config.json` setting "
                        f"`current_phase` to `execution_confirmed`.\n"
                        f"If the user requests changes, modify "
                        f"prd.json.\n---\n"
                    )
                elif phase == 2:
                    refresher = (
                        f"[Mission active — dir: `{loop_dir}`]\n"
                        f"You are in Mission Phase 2 (execution). "
                        f"The user's follow-up message follows.\n"
                        f"Continue the worker → verifier pipeline. "
                        f"Check prd.json progress and dispatch workers "
                        f"for remaining stories.\n---\n"
                    )
                else:
                    refresher = f"[Mission active — dir: `{loop_dir}`]\n---\n"
                original = query or ""
                self._rewrite_last_message_text(
                    msgs,
                    refresher + original,
                )

            # --- Plan Mode ------------------------------------------
            plan_notebook = None
            plan_enabled = getattr(
                getattr(agent_config, "plan", None),
                "enabled",
                False,
            )
            if plan_enabled:
                try:
                    from agentscope.plan import (
                        PlanNotebook,
                        InMemoryPlanStorage,
                    )
                    from ...plan.hints import SimplePlanToHint, set_plan_gate

                    hint_gen = SimplePlanToHint()
                    plan_notebook = PlanNotebook(
                        plan_to_hint=hint_gen,
                        storage=InMemoryPlanStorage(),
                    )
                    hint_gen.bind_notebook(plan_notebook)

                    # Detect /plan <description> and set gate
                    if query and query.strip().lower().startswith("/plan "):
                        plan_desc = query.strip()[6:].strip()
                        if plan_desc:
                            set_plan_gate(plan_notebook, enabled=True)
                            self._rewrite_last_message_text(
                                msgs,
                                plan_desc,
                            )
                            logger.info(
                                "Plan mode: /plan gate set, desc=%s",
                                plan_desc[:60],
                            )

                    # Register SSE broadcast hook + state tracking
                    from ...plan.broadcast import broadcast_plan_update
                    from ...plan.schemas import plan_to_response

                    def _on_plan_change(  # pylint: disable=protected-access
                        nb,
                        plan,
                    ):
                        if getattr(nb, "_loading_from_state", False):
                            nb._qp_had_plan = plan is not None
                            nb._qp_prev_plan_id = (
                                plan.id if plan is not None else None
                            )
                            return

                        had_plan = getattr(nb, "_qp_had_plan", False)
                        prev_id = getattr(nb, "_qp_prev_plan_id", None)

                        if plan is not None:
                            cur_id = plan.id
                            if not had_plan or cur_id != prev_id:
                                nb._plan_just_mutated = True
                            nb._qp_prev_plan_id = cur_id
                        else:
                            if had_plan:
                                nb._plan_recently_finished = True
                                nb._plan_awaiting_user_confirm = False
                            nb._qp_prev_plan_id = None
                        nb._qp_had_plan = plan is not None

                        payload = {
                            "type": "plan_update",
                            "plan": (
                                plan_to_response(plan).model_dump()
                                if plan is not None
                                else None
                            ),
                        }
                        broadcast_plan_update(
                            self.agent_id,
                            payload,
                            session_id=session_id,
                        )

                    plan_notebook.register_plan_change_hook(
                        "broadcast",
                        _on_plan_change,
                    )
                except Exception:
                    logger.warning(
                        "Failed to create PlanNotebook",
                        exc_info=True,
                    )
                    plan_notebook = None

            agent = QwenPawAgent(
                agent_config=agent_config,
                env_context=env_context,
                mcp_clients=mcp_clients,
                memory_manager=(
                    None
                    if isolated_agent_open_api
                    else self.memory_manager
                ),
                context_manager=self.context_manager,
                request_context=base_request_context,
                workspace_dir=self.workspace_dir,
                task_tracker=self._task_tracker,
                plan_notebook=plan_notebook,
            )
            if base_request_context["_open_api_direct_agent_execution"]:
                install_open_api_agent_response_format(agent)
            await agent.register_mcp_clients()
            agent.set_console_output_enabled(enabled=False)

            logger.debug(
                f"Agent Query msgs {msgs}",
            )

            name = "New Chat"
            if len(msgs) > 0:
                content = msgs[0].get_text_content()
                if content:
                    name = msgs[0].get_text_content()[:10]
                else:
                    name = "Media Message"

            logger.debug(
                f"DEBUG chat_manager status: "
                f"_chat_manager={self._chat_manager}, "
                f"is_none={self._chat_manager is None}, "
                f"agent_id={self.agent_id}",
            )

            if self._chat_manager is not None and not isolated_agent_open_api:
                logger.debug(
                    f"Runner: Calling get_or_create_chat for "
                    f"session_id={session_id}, user_id={user_id}, "
                    f"channel={channel}, name={name}",
                )
                chat = await self._chat_manager.get_or_create_chat(
                    session_id,
                    user_id,
                    channel,
                    name=name,
                )
                logger.debug(f"Runner: Got chat: {chat.id}")
            elif self._chat_manager is None:
                logger.warning(
                    f"ChatManager is None! Cannot auto-register chat for "
                    f"session_id={session_id}",
                )

            # Skill info (/<name> without input) is display-only
            if mission_info is None:
                skill_response = self._maybe_inject_skill(
                    query,
                    msgs,
                    agent.toolkit.skills,
                )
                if skill_response is not None:
                    yield skill_response, True
                    return

            # Ensure session file has a valid plan_notebook dict
            # to prevent TypeError/KeyError during load_state_dict
            if plan_notebook is not None and not isolated_agent_open_api:
                try:
                    _states = await self.session.get_session_state_dict(
                        session_id=session_id,
                        user_id=user_id,
                        channel=channel,
                        allow_not_exist=True,
                    )
                    _agent_st = _states.get("agent", {})
                    _nb_val = _agent_st.get("plan_notebook")
                    if _agent_st and (
                        "plan_notebook" not in _agent_st
                        or not isinstance(_nb_val, dict)
                    ):
                        await self.session.update_session_state(
                            session_id=session_id,
                            key="agent.plan_notebook",
                            value=plan_notebook.state_dict(),
                            user_id=user_id,
                            channel=channel,
                            create_if_not_exist=False,
                        )
                except Exception:
                    logger.debug(
                        "Pre-populate plan_notebook skipped",
                        exc_info=True,
                    )

            if plan_notebook is not None and not isolated_agent_open_api:
                setattr(
                    plan_notebook,
                    "_loading_from_state",
                    True,  # pylint: disable=protected-access
                )
            if not isolated_agent_open_api:
                try:
                    await self.session.load_session_state(
                        session_id=session_id,
                        user_id=user_id,
                        channel=channel,
                        agent=agent,
                    )
                except KeyError as e:
                    logger.warning(
                        "load_session_state skipped (state schema mismatch): %s; "
                        "will save fresh state on completion to recover file",
                        e,
                    )
                finally:
                    if plan_notebook is not None:
                        setattr(
                            plan_notebook,
                            "_loading_from_state",
                            False,  # pylint: disable=protected-access
                        )
                session_state_loaded = True

            if plan_notebook is not None:
                from ...plan.hints import clear_plan_awaiting_user_confirm

                clear_plan_awaiting_user_confirm(plan_notebook)

            # Rebuild system prompt so it always reflects the latest
            # AGENTS.md / SOUL.md / PROFILE.md, not the stale one saved
            # in the session state.
            agent.rebuild_sys_prompt()

            # --- Execution: Mission Mode (phased) or standard -----
            if mission_info is not None:
                from ...agents.mission.mission_runner import (
                    run_mission_phase1,
                    run_mission_phase2,
                )

                phase = mission_info["mission_phase"]
                loop_dir = Path(mission_info["loop_dir"])
                max_iters = mission_info.get(
                    "max_iterations",
                    20,
                )

                if phase == 1:
                    async for msg, last in run_mission_phase1(
                        agent=agent,
                        msgs=msgs,
                        loop_dir=loop_dir,
                        max_iterations=max_iters,
                        agent_id=self.agent_id,
                    ):
                        yield msg, last
                else:
                    async for msg, last in run_mission_phase2(
                        agent=agent,
                        msgs=msgs,
                        loop_dir=loop_dir,
                        max_iterations=max_iters,
                        agent_id=self.agent_id,
                    ):
                        yield msg, last
            else:
                workspace_root = Path(
                    self.workspace_dir or WORKING_DIR,
                ).resolve(strict=True)
                async for msg, last, should_save_session in (
                    _run_standard_or_orchestrated_turn(
                        agent=agent,
                        messages=msgs,
                        request=request,
                        query=query,
                        mission_info=mission_info,
                        agent_id=self.agent_id,
                        agent_name=self.agent_name,
                        workspace_root=workspace_root,
                        orchestration=agent_config.orchestration,
                    )
                ):
                    if not should_save_session:
                        session_state_loaded = False
                    yield msg, last

        except asyncio.CancelledError as exc:
            logger.info(f"query_handler: {session_id} cancelled!")

            # Cancel all pending approvals for this root session
            root_session_id = base_request_context.get(
                "root_session_id",
                session_id,
            )
            from ..approvals.service import get_approval_service

            approval_svc = get_approval_service()
            cancelled_count = (
                await approval_svc.cancel_all_pending_by_root_session(
                    root_session_id,
                )
            )
            if cancelled_count > 0:
                logger.info(
                    "Auto-denied %d pending approval(s) for root session %s",
                    cancelled_count,
                    root_session_id[:8]
                    if len(root_session_id) >= 8
                    else root_session_id,
                )

            if agent is not None:
                await agent.interrupt()
            raise AgentException("任务已手动终止") from exc
        except AppBaseException:
            raise
        except Exception as e:
            model_name = getattr(e, "model_name", None)
            if agent and hasattr(agent, "model"):
                model_name = model_name or getattr(
                    agent.model,
                    "model_name",
                    None,
                )

            converted = convert_model_exception(e, model_name)

            # Preserve all original error dump logic
            debug_dump_path = write_query_error_dump(
                request=request,
                exc=converted,
                locals_=locals(),
            )
            path_hint = (
                f"\n(Details:  {debug_dump_path})" if debug_dump_path else ""
            )
            logger.exception(f"Error in query handler: {converted}{path_hint}")
            if debug_dump_path:
                setattr(converted, "debug_dump_path", debug_dump_path)
                if hasattr(converted, "add_note"):
                    converted.add_note(
                        f"(Details:  {debug_dump_path})",
                    )
                suffix = f"\n(Details:  {debug_dump_path})"
                if hasattr(converted, "message") and isinstance(
                    converted.message,
                    str,
                ):
                    converted.message += suffix
                elif converted.args:
                    converted.args = (
                        f"{converted.args[0]}{suffix}",
                    ) + converted.args[1:]
            raise converted from e
        finally:
            if agent is not None and session_state_loaded:
                await self.session.save_session_state(
                    session_id=session_id,
                    user_id=user_id,
                    channel=channel,
                    agent=agent,
                )

            if (
                self._chat_manager is not None
                and chat is not None
                and not isolated_agent_open_api
            ):
                await self._chat_manager.touch_chat(chat.id)

    async def init_handler(self, *args, **kwargs):
        """
        Init handler.
        """
        # Load environment variables from .env file
        # env_path = Path(__file__).resolve().parents[4] / ".env"
        env_path = Path("./") / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            logger.debug(f"Loaded environment variables from {env_path}")
        else:
            logger.debug(
                f".env file not found at {env_path}, "
                "using existing environment variables",
            )

        settings = get_storage_settings()
        if settings.database_backend == "postgres":
            from .session_sqlalchemy import SqlAlchemySession

            self.session = SqlAlchemySession(
                agent_id=self.agent_id,
                engine=get_app_engine(),
            )
        else:
            self.session = SqliteSession(agent_id=self.agent_id)

    async def shutdown_handler(self, *args, **kwargs):
        """
        Shutdown handler.
        """
