"""Official Streamable HTTP MCP endpoint for the eight local tools."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .service import LocalExecutionService


class LocalExecutionMcp:
    def __init__(self, service: LocalExecutionService) -> None:
        self.service = service
        self.server = FastMCP(
            "DClaw Local Execution",
            instructions=(
                "Generic DClaw local execution tools. Business decisions and "
                "third-party API selection remain in the Super Agent."
            ),
            stateless_http=True,
            json_response=True,
            streamable_http_path="/",
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False,
            ),
        )
        self.app = self.server.streamable_http_app()
        self._lifecycle: AbstractAsyncContextManager | None = None
        self._register_tools()

    async def start(self) -> None:
        if self._lifecycle is not None:
            return
        lifecycle = self.server.session_manager.run()
        await lifecycle.__aenter__()
        self._lifecycle = lifecycle

    async def stop(self) -> None:
        lifecycle, self._lifecycle = self._lifecycle, None
        if lifecycle is not None:
            await lifecycle.__aexit__(None, None, None)

    def _register_tools(self) -> None:
        service = self.service

        @self.server.tool(
            description="Check local helper connection and protocol compatibility."
        )
        async def local_environment_status(
            agent_protocol_version: str,
            dclaw_session_token: str,
            bootstrap_session_id: str | None = None,
            wait_seconds: int = 0,
        ) -> dict[str, Any]:
            return await service.call("local_environment_status", locals())

        @self.server.tool(
            description="List generic capabilities reported by the user's local helper."
        )
        async def local_capabilities_list(
            dclaw_session_token: str,
            output_type: str | None = None,
            device_id: str | None = None,
        ) -> dict[str, Any]:
            return await service.call("local_capabilities_list", locals())

        @self.server.tool(
            description="Prepare a signed capability package on the local helper."
        )
        async def local_runtime_prepare(
            capability: str,
            dclaw_session_token: str,
        ) -> dict[str, Any]:
            return await service.call("local_runtime_prepare", locals())

        @self.server.tool(
            description="Start one schema-validated local capability task."
        )
        async def local_task_start(
            capability_id: str,
            input: dict[str, Any],
            idempotency_key: str,
            dclaw_session_token: str,
        ) -> dict[str, Any]:
            return await service.call("local_task_start", locals())

        @self.server.tool(
            description="Continue a waiting local task at its current checkpoint."
        )
        async def local_task_continue(
            task_id: str,
            checkpoint_id: str,
            input: dict[str, Any],
            dclaw_session_token: str,
        ) -> dict[str, Any]:
            return await service.call("local_task_continue", locals())

        @self.server.tool(
            description="Read durable task status without advancing the task."
        )
        async def local_task_status(
            dclaw_session_token: str,
            task_id: str | None = None,
            current_task: bool = False,
            wait_seconds: int = 0,
        ) -> dict[str, Any]:
            return await service.call("local_task_status", locals())

        @self.server.tool(description="Idempotently cancel one local task.")
        async def local_task_cancel(
            task_id: str,
            dclaw_session_token: str,
        ) -> dict[str, Any]:
            return await service.call("local_task_cancel", locals())

        @self.server.tool(
            description="Read terminal result, error, and local artifact metadata."
        )
        async def local_task_result(
            task_id: str,
            dclaw_session_token: str,
        ) -> dict[str, Any]:
            return await service.call("local_task_result", locals())
