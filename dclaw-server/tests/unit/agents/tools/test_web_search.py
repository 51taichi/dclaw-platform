# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from qwenpaw.app.web_search import (
    WebPageResponse,
    WebSearchError,
    WebSearchResponse,
    WebSearchResult,
)
from qwenpaw.config.config import ToolsConfig

web_search_tool = importlib.import_module("qwenpaw.agents.tools.web_search")


def _tool_text(response) -> str:
    return str(response.content[0].text)


def test_web_search_is_a_default_builtin_tool() -> None:
    tool = ToolsConfig().builtin_tools["web_search"]

    assert tool.enabled is True
    assert tool.icon == "🔎"
    read_tool = ToolsConfig().builtin_tools["read_web_page"]
    assert read_tool.enabled is True
    assert read_tool.icon == "📖"


def test_react_agent_registers_web_search_as_hardcoded_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import qwenpaw.agents.react_agent as react_agent

    class FakeToolkit:
        def __init__(self) -> None:
            self.registered: list[str] = []

        def register_tool_function(self, tool_func, **_kwargs) -> None:
            self.registered.append(tool_func.__name__)

    monkeypatch.setattr(react_agent, "Toolkit", FakeToolkit)
    agent = react_agent.QwenPawAgent.__new__(react_agent.QwenPawAgent)
    agent._agent_config = SimpleNamespace(tools=ToolsConfig())

    toolkit = agent._create_toolkit()

    assert "web_search" in toolkit.registered
    assert "read_web_page" in toolkit.registered


@pytest.mark.asyncio
async def test_web_search_formats_real_urls_and_untrusted_content_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeService:
        async def search(self, query: str, **_kwargs):
            return WebSearchResponse(
                query=query,
                request_id="req-1",
                results=(
                    WebSearchResult(
                        title="Current source",
                        url="https://example.com/current",
                        snippet="Current information",
                        published_at="2026-07-10T08:00:00+08:00",
                        source="example.com",
                    ),
                ),
            )

    monkeypatch.setattr(
        web_search_tool,
        "get_web_search_service",
        lambda: FakeService(),
    )

    response = await web_search_tool.web_search("current topic")
    text = _tool_text(response)

    assert "untrusted public webpages" in text
    assert "https://example.com/current" in text
    assert "cite the provided URLs" in text
    assert "IQS request_id: req-1" in text


@pytest.mark.asyncio
async def test_web_search_fails_closed_when_provider_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeService:
        async def search(self, _query: str, **_kwargs):
            raise WebSearchError("administrator disabled it")

    monkeypatch.setattr(
        web_search_tool,
        "get_web_search_service",
        lambda: FakeService(),
    )

    response = await web_search_tool.web_search("topic")

    assert "Web search unavailable" in _tool_text(response)
    assert "administrator disabled it" in _tool_text(response)


@pytest.mark.asyncio
async def test_read_web_page_returns_source_metadata_and_bounded_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeService:
        async def read_page(self, url: str):
            return WebPageResponse(
                url=url,
                final_url="https://example.com/final",
                title="Source article",
                markdown="# Heading\n\n" + ("content " * 1000),
                published_at="2026-07-10T08:00:00+08:00",
                site_name="Example",
                page_type="article",
                request_id="read-1",
            )

    monkeypatch.setattr(
        web_search_tool,
        "get_web_search_service",
        lambda: FakeService(),
    )

    response = await web_search_tool.read_web_page(
        "https://example.com/article",
        max_chars=1200,
    )
    text = _tool_text(response)

    assert "https://example.com/final" in text
    assert "untrusted external data" in text
    assert "published=2026-07-10" in text
    assert "page_type=article" in text
    assert len(text) < 2000
