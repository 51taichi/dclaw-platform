# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pytest

from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.agents.tools import generate_image_gpt
from qwenpaw.agents.tools import __all__ as exported_tools
from qwenpaw.agents.tools import imagegen as imagegen
from qwenpaw.config.config import ToolsConfig, _default_builtin_tools


class _FakeResponse:
    def __init__(
        self,
        payload: dict[str, object],
        *,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self.content = content
        self.headers = headers or {}
        self.status_code = 200
        self.text = ""

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        return None


@pytest.mark.asyncio
async def test_imagegen_generates_image_with_mxapi(monkeypatch, tmp_path):
    imagegen_module = importlib.import_module("qwenpaw.agents.tools.imagegen")
    context_module = importlib.import_module("qwenpaw.config.context")

    calls: list[tuple[str, str]] = []
    submitted: dict[str, object] = {}
    submitted_headers: dict[str, str] = {}
    query_headers: dict[str, str] = {}
    workspace_dir = tmp_path / "workspace"

    class FakeAsyncClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            calls.append(("post", url))
            submitted.update(kwargs["json"])
            submitted_headers.update(kwargs["headers"])
            assert url == "https://open.mxapi.org/api/v2/gpt-image-2"
            assert kwargs["json"]["aspect_ratio"] == "16:9"
            assert kwargs["json"]["quality"] == "high"
            return _FakeResponse({"code": 200, "data": {"task_id": "task-1"}})

        async def get(self, url, **kwargs):
            calls.append(("get", url))
            if "gpt-image/task" in url:
                query_headers.update(kwargs["headers"])
                return _FakeResponse(
                    {
                        "data": {
                            "status": "completed",
                            "result": {
                                "images": ["https://cdn.example.test/out.png"],
                            },
                        },
                    },
                )
            return _FakeResponse(
                {},
                content=b"fake-png-bytes",
                headers={"content-type": "image/png"},
            )

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(imagegen_module.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(imagegen_module, "_sleep", no_sleep)
    monkeypatch.setattr(
        imagegen_module,
        "_resolve_provider",
        lambda _provider_id=None: SimpleNamespace(
            id="mxapi",
            base_url="https://open.mxapi.org",
            api_key="test-key",
            custom_headers={
                "X-Channel": "official",
                "X-Provider-Trace": "enabled",
                "Authorization": "must-not-override-api-key",
            },
            meta={"channel": "default"},
        ),
    )
    context_module.set_current_workspace_dir(workspace_dir)

    try:
        response = await imagegen_module.imagegen(
            prompt="生成一张 16:9 PPT 视觉方案图",
            aspect_ratio="16:9",
            quality="high",
        )
    finally:
        context_module.set_current_workspace_dir(None)

    saved = list((workspace_dir / "media" / "imagegen").glob("imagegen_*.png"))
    assert len(saved) == 1
    assert submitted_headers == {
        "X-Provider-Trace": "enabled",
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
        "X-Channel": "official",
    }
    assert query_headers == {
        "X-Channel": "official",
        "X-Provider-Trace": "enabled",
        "Authorization": "Bearer test-key",
    }
    assert saved[0].read_bytes() == b"fake-png-bytes"
    image_blocks = [
        block
        for block in response.content
        if block.type == "data"
        and block.source.media_type.startswith("image/")
    ]
    assert len(image_blocks) == 1
    image_url = str(image_blocks[0].source.url)
    assert image_url == f"file://{saved[0]}"
    text = "\n".join(
        block.text
        for block in response.content
        if block.type == "text"
    )
    assert "The generated image is attached as an image block" in text
    assert "workspace artifact" in text
    assert "Display URL:" not in text
    assert "Saved to:" not in text
    assert str(saved[0]) not in text
    assert "media/imagegen/imagegen_" not in text
    assert "task-1" in text
    assert "Prompt profile: visual_scheme" in text
    assert str(submitted["prompt"]).startswith(
        "Use case: productivity-visual\n"
        "Asset type: visual direction contact sheet",
    )
    assert "one scheme only" in str(submitted["prompt"])
    manifest = json.loads(saved[0].with_suffix(".imagegen.json").read_text())
    assert manifest["promptProfile"] == "visual_scheme"
    assert manifest["originalPrompt"] == "生成一张 16:9 PPT 视觉方案图"
    assert manifest["effectivePrompt"] == submitted["prompt"]
    assert manifest["generation"]["aspectRatio"] == "16:9"
    assert calls[0] == ("post", "https://open.mxapi.org/api/v2/gpt-image-2")


def test_presentation_scheme_prompt_uses_structured_codex_like_contract():
    imagegen_module = importlib.import_module("qwenpaw.agents.tools.imagegen")

    stage = imagegen_module._presentation_stage(
        "Generate a PowerPoint visual direction for an AI service deck",
        {
            "stage": "visual_scheme",
            "direction_name": "高级产品叙事",
        },
    )
    compiled = imagegen_module._compile_presentation_prompt(
        "Create five representative pages with cinematic product storytelling.",
        stage,
        {
            "stage": "visual_scheme",
            "deck_topic": "企业 AI 落地共建服务",
            "audience": "企业创始人和高管",
            "direction_name": "高级产品叙事",
            "visual_temperature": "bold",
            "dominant_visual_anchor": "cinematic platform scene",
            "commercial_rationale": "Make the offer memorable without losing credibility.",
            "represented_pages": ["cover", "thesis", "evidence", "platform", "closing"],
            "forbidden_patterns": ["generic SaaS cards", "blue-purple dashboard sameness"],
        },
    )

    assert stage == "visual_scheme"
    assert "Use case: productivity-visual" in compiled
    assert "Style direction: 高级产品叙事" in compiled
    assert "Visual temperature: bold" in compiled
    assert "Dominant visual anchor: cinematic platform scene" in compiled
    assert "Generate one scheme only" in compiled
    assert "generic SaaS cards, blue-purple dashboard sameness" in compiled


def test_presentation_asset_prompt_keeps_selected_dna_and_text_safe_area():
    imagegen_module = importlib.import_module("qwenpaw.agents.tools.imagegen")
    context = {
        "stage": "visual_asset",
        "deck_topic": "企业 AI 落地共建服务",
        "audience": "企业决策者",
        "direction_name": "战略 AI 指挥中心",
        "asset_type": "cover hero background",
        "composition": "command wall on the right, dark negative space on the left",
        "reserved_text_area": "left third",
        "output_role": "background behind editable title text",
        "forbidden_patterns": "fake UI and embedded labels",
    }

    stage = imagegen_module._presentation_stage("Create the selected hero scene", context)
    compiled = imagegen_module._compile_presentation_prompt(
        "Create a restrained executive command room.",
        stage,
        context,
    )

    assert stage == "visual_asset"
    assert "Asset type: cover hero background" in compiled
    assert "Style direction: 战略 AI 指挥中心" in compiled
    assert "Reserved text area: left third" in compiled
    assert "background behind editable title text" in compiled
    assert imagegen_module._is_full_slide_asset(context) is True


@pytest.mark.asyncio
async def test_presentation_visual_scheme_rejects_non_widescreen():
    imagegen_module = importlib.import_module("qwenpaw.agents.tools.imagegen")

    response = await imagegen_module.imagegen(
        prompt="Create a PPT visual scheme",
        aspect_ratio="1:1",
        presentation_context={"stage": "visual_scheme"},
    )

    text = "\n".join(
        block.text for block in response.content if block.type == "text"
    )
    assert "must use aspect_ratio='16:9'" in text


@pytest.mark.asyncio
async def test_generate_image_gpt_is_compatibility_alias(monkeypatch, tmp_path):
    imagegen_module = importlib.import_module("qwenpaw.agents.tools.imagegen")

    seen: dict[str, str] = {}

    async def fake_imagegen(**kwargs):
        seen.update({key: str(value) for key, value in kwargs.items()})
        return "ok"

    monkeypatch.setattr(imagegen_module, "imagegen", fake_imagegen)

    result = await imagegen_module.generate_image_gpt(
        prompt="cover",
        size="1792x1024",
        quality="medium",
    )

    assert result == "ok"
    assert seen["prompt"] == "cover"
    assert seen["aspect_ratio"] == "16:9"
    assert seen["quality"] == "medium"


def test_imagegen_tools_are_default_builtins():
    tools = _default_builtin_tools()

    assert tools["imagegen"].enabled is True
    assert tools["generate_image_gpt"].enabled is True
    assert tools["edit_image_gpt"].enabled is True
    assert "imagegen" in exported_tools
    assert "generate_image_gpt" in exported_tools
    assert callable(imagegen)
    assert callable(generate_image_gpt)


def test_react_agent_registers_imagegen_as_hardcoded_tool(monkeypatch):
    import qwenpaw.agents.react_agent as react_agent

    class FakeToolkit:
        def __init__(self) -> None:
            self.registered: list[str] = []

        def register_tool_function(self, tool_func, **_kwargs) -> None:
            self.registered.append(tool_func.__name__)

    monkeypatch.setattr(react_agent, "Toolkit", FakeToolkit)

    agent = QwenPawAgent.__new__(QwenPawAgent)
    agent._agent_config = SimpleNamespace(tools=ToolsConfig())

    toolkit = agent._create_toolkit()

    assert "imagegen" in toolkit.registered
    assert "generate_image_gpt" in toolkit.registered
    assert "edit_image_gpt" in toolkit.registered
