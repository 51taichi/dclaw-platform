# -*- coding: utf-8 -*-
"""DClaw constructor adapters for AgentScope 2 MCP clients.

AgentScope 2 owns the stateful lifecycle task, transport recovery and tool
cache. These adapters preserve DClaw's configuration-facing constructors so
the application does not maintain a second MCP runtime.
"""

from __future__ import annotations

from typing import Any, Literal

from agentscope.mcp import HttpMCPConfig, MCPClient, StdioMCPConfig


class StdIOStatefulClient(MCPClient):
    """Stateful stdio MCP client backed by AgentScope 2."""

    def __init__(
        self,
        name: Any,
        command: Any,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        encoding: str = "utf-8",
        encoding_error_handler: Literal[
            "strict",
            "ignore",
            "replace",
        ] = "strict",
        read_timeout_seconds: float = 60 * 5,
    ) -> None:
        if not isinstance(name, str):
            raise TypeError(f"name must be str, got {type(name).__name__}")
        if not isinstance(command, str):
            raise TypeError(
                f"command must be str, got {type(command).__name__}",
            )
        if encoding != "utf-8":
            raise ValueError("AgentScope 2 stdio MCP requires UTF-8")
        super().__init__(
            name=name,
            is_stateful=True,
            mcp_config=StdioMCPConfig(
                command=command,
                args=args,
                env=env,
                cwd=cwd,
                encoding_error_handler=encoding_error_handler,
            ),
            execution_timeout=read_timeout_seconds,
        )

    @property
    def read_timeout_seconds(self) -> float:
        return float(self.execution_timeout or 60 * 5)

    async def reload(self, timeout: float = 30.0) -> None:
        """Reconnect using the official lifecycle implementation."""
        del timeout
        await self.close()
        await self.connect()


class HttpStatefulClient(MCPClient):
    """Stateful HTTP/SSE MCP client backed by AgentScope 2."""

    def __init__(
        self,
        name: Any,
        transport: str,
        url: Any,
        headers: dict[str, str] | None = None,
        timeout: float = 5.0,
        sse_read_timeout: float = 60 * 5,
        read_timeout_seconds: float | None = None,
        client_kwargs: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(name, str):
            raise TypeError(f"name must be str, got {type(name).__name__}")
        if not isinstance(url, str):
            raise TypeError(f"url must be str, got {type(url).__name__}")
        if transport not in {"sse", "streamable_http", "http"}:
            raise ValueError(f"Unsupported MCP transport: {transport}")
        if client_kwargs:
            raise ValueError(
                "AgentScope 2 MCP does not accept arbitrary client_kwargs",
            )
        execution_timeout = read_timeout_seconds or sse_read_timeout
        super().__init__(
            name=name,
            is_stateful=True,
            mcp_config=HttpMCPConfig(
                url=url,
                headers=headers,
                timeout=timeout,
            ),
            execution_timeout=execution_timeout,
        )
    @property
    def read_timeout_seconds(self) -> float:
        return float(self.execution_timeout or 60 * 5)

    async def reload(self, timeout: float = 30.0) -> None:
        """Reconnect using the official lifecycle implementation."""
        del timeout
        await self.close()
        await self.connect()
