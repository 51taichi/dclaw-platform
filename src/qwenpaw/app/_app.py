# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument
import inspect
import asyncio
import mimetypes
import os

# Ensure localhost requests bypass system proxies to avoid timeout errors
# when connecting to local model providers like LM Studio or Ollama.
if "NO_PROXY" not in os.environ and "no_proxy" not in os.environ:
    os.environ[
        "NO_PROXY"
    ] = "localhost,127.0.0.1,0.0.0.0,::1,192.168.0.0/16,10.0.0.0/8"

import sys
import time
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from agentscope_runtime.engine.app import AgentApp
from agentscope_runtime.engine.schemas.exception import (
    AppBaseException,
)

from ..config import load_config  # pylint: disable=no-name-in-module
from ..config.utils import get_config_path, save_config
from ..constant import (
    CORS_ORIGIN_REGEX,
    DOCS_ENABLED,
    LOG_LEVEL_ENV,
    CORS_ORIGINS,
    WORKING_DIR,
    PROJECT_NAME,
)
from ..__version__ import __version__
from ..backup._utils.safe_swap import cleanup_startup_restore_artifacts
from ..utils.logging import (
    setup_logger,
    add_project_file_handler,
    LOG_FILE_PATH,
)
from ..utils.console_static import (
    CONSOLE_STATIC_ENV,
    resolve_console_static_dir,
)
from ..utils.system_info import summarize_python_environment
from .auth import AuthMiddleware, auto_register_from_env
from .performance import RequestTimingMiddleware
from .routers import router as api_router, create_agent_scoped_router
from .task_limits import create_task_limiter_from_env
from .routers.agent_scoped import AgentContextMiddleware
from .routers.approval import router as approval_router
from .routers.voice import voice_router
from .routers.realtime_stt import realtime_stt_router
from ..envs import load_envs_into_environ
from ..providers.provider_manager import ProviderManager
from ..local_models.manager import LocalModelManager
from .multi_agent_manager import MultiAgentManager
from .migration import (
    migrate_legacy_workspace_to_default_agent,
    migrate_legacy_skills_to_skill_pool,
    ensure_default_agent_exists,
    ensure_product_builtin_assets,
    ensure_qa_agent_exists,
    migrate_all_agents_global_data,
)
from .storage.bootstrap import bootstrap_top_up_products, ensure_durable_schema
from .expert_teams import bootstrap_expert_teams
from .channels.registry import register_custom_channel_routes
from .sealed_agents.registry import get_sealed_agent_registry
from .sealed_agents.workspace_reconciliation import (
    WorkspaceReconciliationResult,
    reconcile_active_sealed_profiles,
)

# Apply log level on load so reload child process gets same level as CLI.
logger = setup_logger(os.environ.get(LOG_LEVEL_ENV, "info"))

# Ensure static assets are served with browser-compatible MIME types across
# platforms (notably Windows may miss .js/.mjs mappings).
mimetypes.init()
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/wasm", ".wasm")

# Load persisted env vars into os.environ at module import time
# so they are available before the lifespan starts.
load_envs_into_environ()


def _reconcile_sealed_agent_profiles(
) -> WorkspaceReconciliationResult | None:
    """Best-effort startup alignment isolated from ordinary Agent startup."""

    try:
        config_path = get_config_path()
        config = load_config(config_path)
        result = reconcile_active_sealed_profiles(
            config,
            get_sealed_agent_registry(),
            Path(WORKING_DIR) / "sealed_agents",
        )
        if result.config_changed:
            save_config(config, config_path)
        if result.unavailable:
            logger.error(
                "Unavailable sealed workspaces: %s",
                result.unavailable,
            )
        return result
    except Exception:
        logger.exception(
            "Sealed workspace reconciliation failed; continuing startup",
        )
        return None


# Dynamic runner that selects the correct workspace runner based on request
class DynamicMultiAgentRunner:
    """Runner wrapper that dynamically routes to the correct workspace runner.

    This allows AgentApp to work with multiple agents by inspecting
    the X-Agent-Id header on each request.
    """

    def __init__(self):
        self.framework_type = "agentscope"
        self._multi_agent_manager = None

    def set_multi_agent_manager(self, manager):
        """Set the MultiAgentManager instance after initialization."""
        self._multi_agent_manager = manager

    async def _get_workspace(self, request):
        """Get the correct workspace based on request.

        Returns:
            Workspace: The workspace instance for the current agent.
        """
        from .agent_context import get_current_agent_id

        # Get agent_id from context (set by middleware or header)
        agent_id = get_current_agent_id()

        logger.debug(f"_get_workspace: agent_id={agent_id}")

        # Get the correct workspace
        if not self._multi_agent_manager:
            raise RuntimeError("MultiAgentManager not initialized")

        try:
            workspace = await self._multi_agent_manager.get_agent(agent_id)
            logger.debug(
                "Got workspace: %s, runner: %s",
                workspace.agent_id,
                workspace.runner,
            )
            return workspace
        except (ValueError, AppBaseException) as e:
            logger.error(f"Agent not found: {e}")
            raise
        except Exception as e:
            logger.error(
                f"Error getting workspace: {e}",
                exc_info=True,
            )
            raise

    async def _get_workspace_runner(self, request):
        """Get the correct workspace runner based on request."""
        workspace = await self._get_workspace(request)
        return workspace.runner

    async def stream_query(self, request, *args, **kwargs):
        """Dynamically route to the correct workspace runner.

        Registers the task with the workspace's TaskTracker so that
        graceful shutdown during agent reload can detect in-flight
        background tasks (fixes #3275).
        """
        logger.debug("DynamicMultiAgentRunner.stream_query called")
        workspace = None
        run_key = None
        try:
            workspace = await self._get_workspace(request)
            runner = workspace.runner
            logger.debug(f"Got runner: {runner}, type: {type(runner)}")

            # Register this task with the workspace's TaskTracker so
            # _graceful_stop_old_instance() can see it during reload.
            run_key = f"ext-{uuid.uuid4().hex}"
            await workspace.task_tracker.register_external_task(run_key)

            # Delegate to the actual runner's stream_query generator
            count = 0
            async for item in runner.stream_query(request, *args, **kwargs):
                count += 1
                logger.debug(f"Yielding item #{count}: {type(item)}")
                yield item
            logger.debug(f"stream_query completed, yielded {count} items")
        except Exception as e:
            logger.error(
                f"Error in stream_query: {e}",
                exc_info=True,
            )
            # Yield error message to client
            yield {
                "error": str(e),
                "type": "error",
            }
        finally:
            # Always unregister the task when done (success, error,
            # or cancellation).
            if workspace is not None and run_key is not None:
                await workspace.task_tracker.unregister_external_task(run_key)

    async def query_handler(self, request, *args, **kwargs):
        """Dynamically route to the correct workspace runner.

        Registers the task with the workspace's TaskTracker so that
        graceful shutdown during agent reload can detect in-flight
        requests (fixes #3275).
        """
        workspace = None
        run_key = None
        try:
            workspace = await self._get_workspace(request)
            runner = workspace.runner

            run_key = f"ext-{uuid.uuid4().hex}"
            await workspace.task_tracker.register_external_task(run_key)

            async for item in runner.query_handler(request, *args, **kwargs):
                yield item
        finally:
            # Always unregister the task when done (success, error,
            # or cancellation).
            if workspace is not None and run_key is not None:
                await workspace.task_tracker.unregister_external_task(run_key)

    # Async context manager support for AgentApp lifecycle
    async def __aenter__(self):
        """
        No-op context manager entry (workspaces manage their own runners).
        """
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """No-op context manager exit (workspaces manage their own runners)."""
        return None


# Use dynamic runner for AgentApp
runner = DynamicMultiAgentRunner()

agent_app = AgentApp(
    app_name="DClaw",
    app_description="A helpful assistant with background task support",
    runner=runner,
    enable_stream_task=True,
    stream_task_queue="stream_query",
    stream_task_timeout=300,
)


def _recover_open_api_billing_at_startup() -> int:
    """Fail closed only when billing enforcement could debit a wallet."""
    runtime = None
    try:
        from .open_api.runtime import (
            create_open_api_billing_runtime,
            recover_open_api_billing,
        )

        runtime = create_open_api_billing_runtime()
        return recover_open_api_billing(runtime)
    except Exception as exc:
        logger.error("OpenAPI billing recovery failed", exc_info=True)
        configured_mode = (
            os.environ.get(
                "DCLAW_BILLING_MODE",
                "shadow",
            )
            .strip()
            .lower()
        )
        if (runtime is not None and runtime.mode == "enforced") or (
            configured_mode == "enforced"
        ):
            raise RuntimeError("OpenAPI billing recovery failed") from exc
        # Off/shadow/observe do not mutate customer-wallet balances. Keeping
        # startup available is explicit and recovery will retry next startup.
        return 0


def _recover_general_billing_at_startup() -> int:
    """Recover enforced user entry points before accepting traffic."""
    try:
        from .billing.recovery import recover_general_billing

        return recover_general_billing()
    except Exception as exc:
        logger.error("General billing recovery failed", exc_info=True)
        raise RuntimeError("General billing recovery failed") from exc


@asynccontextmanager
async def lifespan(  # pylint: disable=too-many-statements,too-many-branches
    app: FastAPI,
):
    startup_start_time = time.time()
    add_project_file_handler(LOG_FILE_PATH)

    # ================================================================
    # Phase 1: Fast synchronous setup (target < 100ms)
    # Everything here must be lightweight so the server starts quickly.
    # ================================================================

    try:
        cleanup_startup_restore_artifacts()
    except Exception as exc:
        message = (
            "DClaw startup failed because restore artifact cleanup did not "
            "complete. Another restore or cleanup may still be running, or "
            "a previous restore may need recovery before startup can safely "
            "read restored files."
        )
        logger.error(message, exc_info=True)
        raise RuntimeError(f"{message} Original error: {exc}") from exc

    if ensure_durable_schema():
        logger.info("Durable Postgres schema ensured")
    bootstrap_top_up_products()
    bootstrap_expert_teams()

    # Recover only bridge-created OpenAPI billing orders. Historical token
    # rows remain ``unbilled`` and are deliberately outside this scan.
    recovered_open_api_orders = _recover_open_api_billing_at_startup()
    if recovered_open_api_orders:
        logger.info(
            "Recovered %d incomplete OpenAPI billing transition(s)",
            recovered_open_api_orders,
        )
    recovered_general_executions = _recover_general_billing_at_startup()
    if recovered_general_executions:
        logger.info(
            "Recovered %d incomplete general billing execution(s)",
            recovered_general_executions,
        )

    auto_register_from_env()

    try:
        from ..utils.telemetry import (
            collect_and_upload_telemetry,
            has_telemetry_been_collected,
            is_telemetry_opted_out,
        )

        if not is_telemetry_opted_out(
            WORKING_DIR,
        ) and not has_telemetry_been_collected(WORKING_DIR):
            collect_and_upload_telemetry(WORKING_DIR)
    except Exception:
        logger.debug(
            "Telemetry collection skipped due to error",
            exc_info=True,
        )

    logger.debug("Checking for legacy config migration...")
    migrate_legacy_workspace_to_default_agent()
    ensure_default_agent_exists()
    migrate_all_agents_global_data()
    migrate_legacy_skills_to_skill_pool()
    ensure_product_builtin_assets()
    ensure_qa_agent_exists()

    # Create core managers (instant — no I/O)
    logger.debug("Initializing MultiAgentManager...")
    multi_agent_manager = MultiAgentManager()
    provider_manager = ProviderManager.get_instance()
    local_model_manager = LocalModelManager.get_instance()
    task_limiter = create_task_limiter_from_env()

    # Start token usage manager background tasks
    logger.debug("Starting TokenUsageManager background tasks...")
    from ..token_usage import get_token_usage_manager

    token_usage_manager = get_token_usage_manager()
    token_usage_manager.start(flush_interval=10)

    # Knowledge uploads return as soon as their source file is persisted. The
    # worker owns parsing, chunking and optional Embedding work. With Redis it
    # also recovers any job interrupted by an application restart.
    from ..mindspace.jobs import get_knowledge_job_manager

    knowledge_job_manager = get_knowledge_job_manager()
    try:
        await knowledge_job_manager.start()
    except Exception:
        logger.error(
            "Knowledge job worker could not start; uploads will return 503 "
            "until the queue backend recovers",
            exc_info=True,
        )

    # Expose to endpoints (must be set before first request arrives)
    app.state.multi_agent_manager = multi_agent_manager
    app.state.provider_manager = provider_manager
    app.state.local_model_manager = local_model_manager
    app.state.task_limiter = task_limiter
    app.state.knowledge_job_manager = knowledge_job_manager
    app.state.plugin_loader = None
    app.state.plugin_registry = None

    if isinstance(runner, DynamicMultiAgentRunner):
        runner.set_multi_agent_manager(multi_agent_manager)

    async def _get_agent_by_id(agent_id: str = None):
        """Get agent instance by ID, or active agent if not specified."""
        if agent_id is None:
            config = load_config(get_config_path())
            agent_id = config.agents.active_agent or "default"
        return await multi_agent_manager.get_agent(agent_id)

    app.state.get_agent_by_id = _get_agent_by_id

    fast_elapsed = time.time() - startup_start_time
    logger.info(
        f"Server ready in {fast_elapsed:.3f}s "
        f"(agents loading in background)",
    )

    # ================================================================
    # Phase 2: Background heavy initialization
    # Agents, plugins, and services start in a background task so the
    # server can begin accepting HTTP requests immediately.
    # First API requests that need an agent will await its readiness
    # via MultiAgentManager.get_agent() lazy-loading / event wait.
    # ================================================================

    async def _background_startup():  # pylint: disable=too-many-statements
        try:
            _reconcile_sealed_agent_profiles()

            # Start all configured agents (truly parallel now)
            await multi_agent_manager.start_all_configured_agents()

            provider_manager.start_local_model_resume(local_model_manager)

            # ---- Plugin System ----
            logger.debug("Initializing plugin system...")

            from ..plugins.loader import PluginLoader
            from ..plugins.runtime import RuntimeHelpers
            from ..config.utils import get_plugins_dir

            plugin_dirs = [
                get_plugins_dir(),
            ]

            plugin_loader = PluginLoader(plugin_dirs)

            plugin_loader.registry.set_plugin_http_app(app)

            config = load_config(get_config_path())
            plugin_configs = (
                config.plugins if hasattr(config, "plugins") else {}
            )
            logger.debug(
                f"Loading plugins with {len(plugin_configs)} config(s)",
            )

            loaded_plugins = await plugin_loader.load_all_plugins(
                configs=plugin_configs,
            )
            logger.debug(f"Loaded {len(loaded_plugins)} plugin(s)")

            runtime_helpers = RuntimeHelpers(
                provider_manager=provider_manager,
            )
            plugin_loader.registry.set_runtime_helpers(runtime_helpers)

            for (
                provider_id,
                provider_reg,
            ) in plugin_loader.registry.get_all_providers().items():
                provider_manager.register_plugin_provider(
                    provider_id=provider_id,
                    provider_class=provider_reg.provider_class,
                    label=provider_reg.label,
                    base_url=provider_reg.base_url,
                    metadata=provider_reg.metadata,
                )
                logger.debug(
                    f"Registered plugin provider: {provider_id}",
                )

            app.state.plugin_loader = plugin_loader
            app.state.plugin_registry = plugin_loader.registry

            # ---- Plugin Control Commands ----
            logger.debug("Registering plugin control commands...")
            from ..app.runner.control_commands import register_command
            from ..app.channels.command_registry import CommandRegistry

            command_registry = CommandRegistry()

            control_commands = plugin_loader.registry.get_control_commands()
            for cmd_reg in control_commands:
                try:
                    register_command(cmd_reg.handler)

                    command_registry.register_command(
                        f"/{cmd_reg.handler.command_name}",
                        priority_level=cmd_reg.priority_level,
                    )

                    logger.debug(
                        f"Registered plugin control command: "
                        f"/{cmd_reg.handler.command_name} "
                        f"from plugin '{cmd_reg.plugin_id}' (priority"
                        f"={cmd_reg.priority_level})",
                    )
                except Exception as e:
                    logger.error(
                        f"✗ Failed to register control command "
                        f"'{cmd_reg.handler.command_name}' "
                        f"from plugin '{cmd_reg.plugin_id}': {e}",
                        exc_info=True,
                    )

            # ---- Startup Hooks ----
            logger.debug("Executing plugin startup hooks...")
            startup_hooks = plugin_loader.registry.get_startup_hooks()
            for hook in startup_hooks:
                try:
                    logger.debug(
                        f"Executing startup hook '{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}' "
                        f"(priority={hook.priority})",
                    )

                    result = hook.callback()
                    if inspect.iscoroutine(
                        result,
                    ) or inspect.isawaitable(result):
                        await result

                    logger.debug(
                        f"Completed startup hook '{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}'",
                    )
                except Exception as e:
                    logger.error(
                        f"✗ Failed to execute startup hook "
                        f"'{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}': {e}",
                        exc_info=True,
                    )

            # ---- Approval Service ----
            try:
                default_agent = await multi_agent_manager.get_agent(
                    "default",
                )
                if default_agent.channel_manager:
                    from .approvals import get_approval_service

                    get_approval_service().set_channel_manager(
                        default_agent.channel_manager,
                    )
            except Exception as e:
                logger.warning(f"Approval service setup skipped: {e}")

            startup_elapsed = time.time() - startup_start_time
            logger.info(
                "Background startup completed in "
                f"{startup_elapsed:.3f} seconds",
            )

            # Print server URL again so it's visible after background logs
            from ..config.utils import read_last_api
            from ..utils.startup_display import print_ready_banner

            api_info = read_last_api()
            print_ready_banner(api_info, startup_elapsed)
        except Exception:
            logger.error(
                "Background startup encountered an error",
                exc_info=True,
            )

    # Application composition only: core AIGC recovery has no expert dependency
    # and never invokes a provider or starts paid generation.
    from .aigc.job_lifecycle import AigcJobLifecycle
    from .aigc.resource_store import AigcResourceStore
    from .routers.aigc_studio import STUDIO_ROOT
    from .runtime.aigc_events import AigcRecoveryWorker, AigcRuntimeNotifications
    from .runtime.event_bus import get_runtime_event_bus
    from .storage.engine import get_app_engine
    from .storage.repos.aigc_execution_repo import AigcExecutionRepository

    aigc_repository = AigcExecutionRepository(get_app_engine())
    aigc_recovery = AigcRecoveryWorker(
        AigcJobLifecycle(AigcResourceStore(STUDIO_ROOT), aigc_repository),
        [AigcRuntimeNotifications(aigc_repository, get_runtime_event_bus())],
    )
    app.state.aigc_recovery_worker = aigc_recovery
    aigc_recovery.start()
    _bg_task = asyncio.create_task(_background_startup())

    try:
        yield
    finally:
        await aigc_recovery.stop()
        # Cancel background startup if still in progress
        if not _bg_task.done():
            _bg_task.cancel()
            with suppress(asyncio.CancelledError):
                await _bg_task

        try:
            await knowledge_job_manager.stop()
        except Exception:
            logger.error("Error stopping knowledge job worker", exc_info=True)

        # ==================== Execute Shutdown Hooks ====================
        plugin_registry = getattr(app.state, "plugin_registry", None)
        if plugin_registry is not None:
            logger.info("Executing plugin shutdown hooks...")
            shutdown_hooks = plugin_registry.get_shutdown_hooks()
            for hook in shutdown_hooks:
                try:
                    logger.info(
                        f"Executing shutdown hook '{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}' (priority"
                        f"={hook.priority})",
                    )

                    result = hook.callback()
                    if inspect.iscoroutine(result) or inspect.isawaitable(
                        result,
                    ):
                        await result

                    logger.info(
                        f"✓ Completed shutdown hook '{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}'",
                    )
                except Exception as e:
                    logger.error(
                        f"✗ Failed to execute shutdown hook "
                        f"'{hook.hook_name}' "
                        f"from plugin '{hook.plugin_id}': {e}",
                        exc_info=True,
                    )

        local_model_mgr = getattr(app.state, "local_model_manager", None)
        if local_model_mgr is not None:
            logger.info("Stopping local model server...")
            try:
                await local_model_mgr.shutdown_server()
            except Exception as exc:
                logger.error(
                    "Error shutting down local model server gracefully: %s",
                    exc,
                )
                with suppress(OSError, RuntimeError, ValueError):
                    local_model_mgr.shutdown_server_sync()

        # Stop multi-agent manager (stops all agents and their components)
        multi_agent_mgr = getattr(app.state, "multi_agent_manager", None)
        if multi_agent_mgr is not None:
            logger.info("Stopping MultiAgentManager...")
            try:
                await multi_agent_mgr.stop_all()
            except Exception as e:
                logger.error(f"Error stopping MultiAgentManager: {e}")

        # Stop token usage manager (drain queue and final flush)
        logger.info("Stopping TokenUsageManager...")
        try:
            await token_usage_manager.stop()
        except Exception as e:
            logger.error(f"Error stopping TokenUsageManager: {e}")

        # Stop all browser instances
        from ..agents.tools.browser_control import stop_all_browsers

        try:
            await stop_all_browsers()
        except Exception as e:
            logger.error(f"Error stopping browsers during shutdown: {e}")

        logger.info("Application shutdown complete")


app = FastAPI(
    lifespan=lifespan,
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
)

# Add agent context middleware for agent-scoped routes
app.add_middleware(AgentContextMiddleware)

app.add_middleware(AuthMiddleware)

app.add_middleware(RequestTimingMiddleware)

# Apply CORS middleware for configured exact origins and desktop localhost origins.
if CORS_ORIGINS or CORS_ORIGIN_REGEX:
    origins = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=CORS_ORIGIN_REGEX or None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "Content-Disposition",
            "X-QwenPaw-Chat-Id",
            "X-QwenPaw-Session-Id",
            "X-DClaw-Invocation-Id",
            "X-DClaw-Billing-Status",
        ],
    )


_CONSOLE_STATIC_ENV = CONSOLE_STATIC_ENV


def _resolve_console_static_dir() -> str:
    return resolve_console_static_dir()


_CONSOLE_STATIC_DIR = _resolve_console_static_dir()
_CONSOLE_INDEX = (
    Path(_CONSOLE_STATIC_DIR) / "index.html" if _CONSOLE_STATIC_DIR else None
)
_CONSOLE_INDEX_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}
logger.info(f"STATIC_DIR: {_CONSOLE_STATIC_DIR}")


def _console_index_response():
    if _CONSOLE_INDEX and _CONSOLE_INDEX.exists():
        return FileResponse(_CONSOLE_INDEX, headers=_CONSOLE_INDEX_HEADERS)

    raise HTTPException(status_code=404, detail="Not Found")


@app.get("/")
def read_root():
    if _CONSOLE_INDEX and _CONSOLE_INDEX.exists():
        return _console_index_response()
    return {
        "message": (
            f"{PROJECT_NAME} web console is not available. "
            "If you installed the project from source code, please run "
            "`npm ci && npm run build` in the `console/` "
            f"directory, and restart {PROJECT_NAME} to enable the "
            "web console."
        ),
    }


@app.get("/api/version")
def get_version():
    """Return the current application version (public-safe payload)."""
    return {
        "version": __version__,
    }


@app.get("/api/doctor/runtime")
def get_doctor_runtime():
    """Return server runtime diagnostics for authenticated troubleshooting."""
    return {
        "python_executable": sys.executable,
        "python_environment": summarize_python_environment(),
    }


app.include_router(api_router, prefix="/api")

# Approval router: /api/approval/approve, /api/approval/deny, etc.
app.include_router(approval_router, prefix="/api")

# Agent-scoped router: /api/agents/{agentId}/chats, etc.
agent_scoped_router = create_agent_scoped_router()
app.include_router(agent_scoped_router, prefix="/api")

app.include_router(
    agent_app.router,
    prefix="/api/agent",
    tags=["agent"],
)

# Voice channel: Twilio-facing endpoints at root level (not under /api/).
# POST /voice/incoming, WS /voice/ws, POST /voice/status-callback
app.include_router(voice_router, tags=["voice"])

# Authenticated browser speech input gateway. Kept outside the HTTP-only auth
# middleware/dependency stack because WebSocket authentication is explicit.
app.include_router(realtime_stt_router, prefix="/api", tags=["realtime-stt"])

# Custom channel routes (before SPA catch-all to ensure route priority)
register_custom_channel_routes(app)

# Console static files and SPA fallback
# Register these AFTER API routes to ensure proper routing priority
if os.path.isdir(_CONSOLE_STATIC_DIR):
    _console_path = Path(_CONSOLE_STATIC_DIR)

    def _serve_console_index():
        return _console_index_response()

    _assets_dir = _console_path / "assets"
    if _assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(_assets_dir)),
            name="assets",
        )

    @app.get("/console")
    @app.get("/console/")
    @app.get("/console/{full_path:path}")
    def _console_spa_alias(full_path: str = ""):
        _ = full_path
        return _serve_console_index()

    # SPA fallback: catch-all route for frontend routing
    # Must be registered AFTER all API routes to avoid conflicts
    @app.get(
        "/{full_path:path}",
        name="qwenpaw_console_spa_catchall",
    )
    def _console_spa(full_path: str):
        # Prevent catching common system/special paths
        if full_path in ("docs", "redoc", "openapi.json"):
            raise HTTPException(status_code=404, detail="Not Found")
        # Skip API routes (should already be matched due to registration order)
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404, detail="Not Found")

        # Serve static files from the console build directory (e.g. logo SVGs,
        # favicons, images placed in public/).  Only serve regular files whose
        # path does not escape the console directory.
        if full_path and ".." not in full_path:
            # Security: Reject absolute paths to prevent path traversal bypass
            if not Path(full_path).is_absolute():
                static_file = _console_path / full_path
                if static_file.is_file():
                    return FileResponse(static_file)

        return _serve_console_index()
