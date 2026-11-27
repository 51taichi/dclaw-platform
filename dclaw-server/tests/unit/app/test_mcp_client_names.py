"""MCP display names must remain usable with AgentScope 2."""

import re

import pytest

from qwenpaw.app.mcp.manager import MCPClientManager
from qwenpaw.config.config import MCPClientConfig


@pytest.mark.parametrize(
    ("transport", "connection"),
    [
        ("stdio", {"command": "true"}),
        ("streamable_http", {"url": "http://127.0.0.1:8088/mcp"}),
    ],
)
def test_unicode_display_name_uses_stable_provider_name(transport, connection):
    config = MCPClientConfig(
        name="DClaw 本地能力网关",
        transport=transport,
        **connection,
    )

    client = MCPClientManager._build_client("local_capability_gateway", config)

    assert re.fullmatch(r"[A-Za-z0-9_-]+", client.name)
    assert client.name.startswith("local_capability_gateway_")
    assert client._qwenpaw_rebuild_info["name"] == client.name
    assert config.name == "DClaw 本地能力网关"


def test_provider_name_keeps_existing_ascii_name_and_distinguishes_keys():
    config = MCPClientConfig(name="搜索服务", command="true")
    first = MCPClientManager._build_client("search_a", config)
    second = MCPClientManager._build_client("search_b", config)
    ascii_client = MCPClientManager._build_client(
        "search_c",
        MCPClientConfig(name="search-mcp", command="true"),
    )

    assert first.name != second.name
    assert ascii_client.name == "search-mcp"


def test_local_gateway_url_override_keeps_release_config_unchanged(monkeypatch):
    local_url = "http://127.0.0.1:8088/api/super-agent-support/mcp"
    release_url = "https://production.example/api/super-agent-support/mcp"
    monkeypatch.setenv("DCLAW_LOCAL_CAPABILITY_GATEWAY_URL", local_url)
    config = MCPClientConfig(
        name="local-gateway",
        transport="streamable_http",
        url=release_url,
    )

    gateway = MCPClientManager._build_client("local_capability_gateway", config)
    other = MCPClientManager._build_client("external_gateway", config)

    assert gateway.mcp_config.url == local_url
    assert other.mcp_config.url == release_url
    assert gateway._qwenpaw_rebuild_info["url"] == local_url
    assert other._qwenpaw_rebuild_info["url"] == release_url
    assert config.url == release_url
