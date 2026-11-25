# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import hashlib
import json
import runpy
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.agents.tools import __all__ as exported_tools
from qwenpaw.app.agent_context import set_current_session_id
from qwenpaw.config.config import ToolsConfig, _default_builtin_tools
from qwenpaw.config.context import set_current_workspace_dir


def _text_from_response(response) -> str:
    return "\n".join(
        block.text
        for block in response.content
        if block.type == "text"
    )


def _file_names_from_response(response) -> list[str]:
    return [
        block.name or ""
        for block in response.content
        if block.type == "data"
    ]


def _sample_png(path: Path) -> None:
    image = Image.new("RGB", (1280, 720), (20, 64, 128))
    image.save(path)


def _slide_xml(pptx_path: Path, slide_no: int) -> str:
    with zipfile.ZipFile(pptx_path) as deck:
        return deck.read(f"ppt/slides/slide{slide_no}.xml").decode(
            "utf-8",
            errors="ignore",
        )


def _media_count(pptx_path: Path) -> int:
    with zipfile.ZipFile(pptx_path) as deck:
        return sum(1 for name in deck.namelist() if name.startswith("ppt/media/"))


def _media_hashes(pptx_path: Path) -> set[str]:
    with zipfile.ZipFile(pptx_path) as deck:
        return {
            hashlib.sha256(deck.read(name)).hexdigest()
            for name in deck.namelist()
            if name.startswith("ppt/media/")
        }


def _scheme_b_compose_spec() -> dict:
    fixture_path = Path(__file__).resolve().parents[3] / "fixtures" / "presentation_scheme_b.py"
    return runpy.run_path(str(fixture_path))["build_scheme_b_compose_spec"]()


@pytest.mark.asyncio
async def test_presentation_builder_embeds_required_image_asset(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    asset_path = tmp_path / "scheme.png"
    _sample_png(asset_path)
    workspace_dir = tmp_path / "workspace"
    set_current_workspace_dir(workspace_dir)

    try:
        response = await builder_module.presentation_builder(
            output_path="outputs/client_deck.pptx",
            delivery_mode="draft",
            slides=[
                {
                    "title": "方案一：战略 AI 指挥中心",
                    "body": "用生成视觉作为页面主视觉，并保留标题正文可编辑。",
                    "bullets": ["图片必须嵌入 PPTX", "正文必须保持原生文本"],
                },
            ],
            required_image_assets=[str(asset_path)],
            asset_usage_matrix=[
                {
                    "asset_path": str(asset_path),
                    "slide_index": 1,
                    "role": "hero",
                },
            ],
        )
    finally:
        set_current_workspace_dir(None)

    output_path = workspace_dir / "outputs" / "client_deck.pptx"
    assert output_path.exists()
    usage = builder_module.inspect_pptx_media_usage(output_path)
    assert usage["media_count"] == 1
    assert usage["pic_count"] == 1
    assert usage["unused_required_assets"] == []
    text = _text_from_response(response)
    assert "media_count=1" in text
    assert "pic_count=1" in text


@pytest.mark.asyncio
async def test_presentation_builder_rejects_unmapped_required_assets(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    asset_path = tmp_path / "unused.png"
    _sample_png(asset_path)

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "bad.pptx"),
        slides=[{"title": "纯文字页"}],
        required_image_assets=[str(asset_path)],
        asset_usage_matrix=[],
    )

    assert not (tmp_path / "bad.pptx").exists()
    text = _text_from_response(response)
    assert "Error:" in text
    assert "required image assets were not mapped" in text


@pytest.mark.asyncio
async def test_presentation_builder_can_emit_compose_manifest(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "compose_source.pptx"),
        delivery_mode="draft",
        include_compose_manifest=True,
        slides=[
            {
                "layout": "codex-grid-layout-library#slide-01",
                "title": "实施路径",
                "steps": ["诊断", "共建", "运营"],
            },
            {
                "layout": "codex-grid-layout-library#slide-51",
                "title": "关键指标",
                "metrics": [
                    {"label": "周期", "value": "4周"},
                    {"label": "组件", "value": "20+"},
                ],
            },
        ],
    )

    manifest_path = tmp_path / "compose_source.presentation.compose.json"
    assert manifest_path.exists()
    file_names = _file_names_from_response(response)
    assert "compose_source.pptx" in file_names
    assert "compose_source.presentation.compose.json" in file_names
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["authoringMode"] == "qwenpaw-pptx-compose"
    assert manifest["layoutRegistry"]["templateCount"] == 80
    assert manifest["output"]["pptx"].endswith("compose_source.pptx")
    assert manifest["qa"]["templateVariety"] == 2
    assert manifest["slides"][0]["templateId"] == "codex-grid-layout-library#slide-01"
    assert manifest["slides"][0]["canonicalLayout"] == "process"
    assert manifest["slides"][0]["contentRoles"] == ["step", "title"]
    assert manifest["slides"][1]["templateId"] == "codex-grid-layout-library#slide-51"
    assert manifest["slides"][1]["canonicalLayout"] == "metrics"
    assert "compose_manifest=" in _text_from_response(response)


@pytest.mark.asyncio
async def test_image_hero_variants_keep_subtitle_clear_of_body(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    output_path = tmp_path / "image_hero_spacing.pptx"
    response = await builder_module.presentation_builder(
        output_path=str(output_path),
        delivery_mode="draft",
        slides=[
            {
                "layout": "codex-grid-layout-library#slide-59",
                "title": "59 image-hero",
                "subtitle": "Codex Grid compatible authoring smoke",
                "body": "服务原生可编辑 PPTX 页面，保留文本、形状、组件和 QA 元数据。",
                "bullets": ["结构清晰", "信息可编辑", "可复现布局"],
            },
            {
                "layout": "codex-grid-layout-library#slide-64",
                "title": "64 image-hero",
                "subtitle": "Codex Grid compatible authoring smoke",
                "body": "服务原生可编辑 PPTX 页面，保留文本、形状、组件和 QA 元数据。",
                "bullets": ["结构清晰", "信息可编辑", "可复现布局"],
            },
        ],
    )

    assert "Error:" not in _text_from_response(response)
    usage = builder_module.inspect_pptx_media_usage(output_path)
    assert usage["qa"]["overlap_count"] == 0
    assert usage["qa"]["warnings"] == []


def test_presentation_builder_is_default_builtin_tool():
    tools = _default_builtin_tools()

    assert tools["presentation_builder"].enabled is True
    assert "presentation_builder" in exported_tools


def test_react_agent_registers_presentation_builder_as_hardcoded_tool(monkeypatch):
    import qwenpaw.agents.react_agent as react_agent

    class FakeToolkit:
        def __init__(self) -> None:
            self.registered: list[str] = []

        def register_tool_function(self, tool_func, **_kwargs) -> None:
            self.registered.append(tool_func.__name__)

    monkeypatch.setattr(react_agent, "Toolkit", FakeToolkit)

    agent = QwenPawAgent.__new__(QwenPawAgent)
    agent._agent_config = type(
        "AgentConfig",
        (),
        {"tools": ToolsConfig()},
    )()

    toolkit = agent._create_toolkit()

    assert "presentation_builder" in toolkit.registered


@pytest.mark.asyncio
async def test_presentation_builder_supports_codex_like_layouts_theme_and_qa(
    tmp_path,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    asset_path = tmp_path / "hero.png"
    _sample_png(asset_path)

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "codex_like.pptx"),
        delivery_mode="draft",
        deck_title="企业 AI 落地共建服务",
        theme={
            "mode": "light",
            "accent": "#2563EB",
            "font_family": "Microsoft YaHei",
        },
        slides=[
            {
                "layout": "image_hero",
                "kicker": "商业提案",
                "title": "深兆左智企业 AI 落地共建服务",
                "subtitle": "从场景诊断到 Agent 中台落地",
                "images": [{"asset_path": str(asset_path), "role": "hero"}],
            },
            {
                "layout": "cards",
                "title": "三条落地路径",
                "items": [
                    {"title": "AI 培训", "body": "让团队先形成共识"},
                    {"title": "战略咨询", "body": "把场景拆成可执行路线"},
                    {"title": "Agent 中台", "body": "沉淀可复用能力"},
                ],
            },
            {
                "layout": "process",
                "title": "共建流程",
                "steps": [
                    {"title": "诊断", "body": "识别高价值场景"},
                    {"title": "试点", "body": "小范围验证闭环"},
                    {"title": "推广", "body": "复制到业务团队"},
                ],
            },
            {
                "layout": "metrics",
                "title": "项目收益指标",
                "metrics": [
                    {"label": "部署周期", "value": "4周", "caption": "试点上线"},
                    {"label": "核心场景", "value": "6个", "caption": "首批沉淀"},
                    {"label": "复用组件", "value": "20+", "caption": "资产积累"},
                ],
            },
            {
                "layout": "table",
                "title": "服务矩阵",
                "table": {
                    "headers": ["模块", "交付物", "价值"],
                    "rows": [
                        ["培训", "课程与工作坊", "团队认知统一"],
                        ["咨询", "路线图与优先级", "降低试错成本"],
                        ["中台", "Agent 与组件库", "能力持续复用"],
                    ],
                },
            },
        ],
        required_image_assets=[str(asset_path)],
    )

    output_path = tmp_path / "codex_like.pptx"
    assert output_path.exists()
    usage = builder_module.inspect_pptx_media_usage(output_path)
    assert usage["slide_count"] == 5
    assert usage["media_count"] == 1
    assert usage["pic_count"] == 1
    assert usage["qa"]["weak_slide_count"] == 0
    assert usage["qa"]["layout_variety"] >= 5

    title_xml = _slide_xml(output_path, 1)
    cards_xml = _slide_xml(output_path, 2)
    process_xml = _slide_xml(output_path, 3)
    metrics_xml = _slide_xml(output_path, 4)
    table_xml = _slide_xml(output_path, 5)
    assert 'name="Background"' in title_xml
    assert 'val="FFFFFF"' in title_xml
    assert 'name="Card 1"' in cards_xml
    assert 'name="Card 3"' in cards_xml
    assert 'name="Process Step 1"' in process_xml
    assert 'name="Metric 1"' in metrics_xml
    assert 'name="Table Cell 1-1"' in table_xml
    assert "qa_warnings=0" in _text_from_response(response)


@pytest.mark.asyncio
async def test_presentation_builder_strict_qa_rejects_empty_slides(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "empty.pptx"),
        slides=[{"layout": "section"}],
        strict_qa=True,
    )

    assert not (tmp_path / "empty.pptx").exists()
    text = _text_from_response(response)
    assert "visual QA failed" in text


def test_presentation_builder_exposes_codex_like_layout_catalog():
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    catalog = builder_module.presentation_layout_catalog()

    layout_ids = {entry["layout"] for entry in catalog["layouts"]}
    assert {"image_hero", "cards", "process", "metrics", "table"}.issubset(
        layout_ids,
    )
    assert {"agenda", "comparison", "roadmap", "quote", "architecture"}.issubset(
        layout_ids,
    )
    assert catalog["route_modes"] == [
        "template_following",
        "custom_compose",
        "codex_grid",
    ]
    assert catalog["qa_contract"]["overlap"] == "warn-or-fail"
    assert catalog["qa_contract"]["render_qa"] == "requires-soffice-and-pdftoppm-when-enabled"
    assert (
        catalog["qa_contract"]["delivery_mode"]
        == "auto-defaults-to-final-with-distinct-prototype-checkpoint"
    )
    assert catalog["qa_contract"]["visual_assets"] == "requires-mapped-assets-when-enabled"
    assert (
        catalog["qa_contract"]["visual_route_continuity"]
        == "imagegen-selected-direction-requires-custom-compose"
    )
    assert catalog["qa_contract"]["expected_slide_count"] == "optional-hard-count-contract"
    assert catalog["qa_contract"]["custom_compose"]["mode"] == "exact-layer-authoring"


@pytest.mark.asyncio
async def test_presentation_builder_custom_compose_preserves_exact_layers_and_three_paths(
    tmp_path,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    output_path = tmp_path / "custom_compose.pptx"

    response = await builder_module.presentation_builder(
        output_path=str(output_path),
        delivery_mode="draft",
        route_mode="custom_formatting",
        include_compose_manifest=True,
        compose_spec={
            "schema_version": "2.0",
            "deck_title": "企业 AI 共建服务",
            "slide_size": {"width": 13.333333, "height": 7.5},
            "theme": {
                "canvas": "F4F0E7",
                "ink": "1C2528",
                "accent": "B45B3E",
                "font_family": "Arial",
            },
            "native_translation_rationale": "Selected visual scheme is translated into editable native geometry.",
            "slides": [
                {
                    "title": "封面",
                    "archetype": "editorial_cover",
                    "expected_content": {
                        "required_text": ["企业 AI 共建服务"],
                        "layer_type_counts": {"shape": 1, "text": 2},
                    },
                    "layers": [
                        {
                            "type": "shape",
                            "name": "Cover accent",
                            "x": 0.8,
                            "y": 0.8,
                            "w": 0.16,
                            "h": 5.9,
                            "fill": "B45B3E",
                        },
                        {
                            "type": "text",
                            "name": "Cover title",
                            "x": 1.3,
                            "y": 2.0,
                            "w": 7.8,
                            "h": 1.1,
                            "text": "企业 AI 共建服务",
                            "font_size": 34,
                            "bold": True,
                        },
                        {
                            "type": "text",
                            "name": "Cover subtitle",
                            "x": 1.34,
                            "y": 3.4,
                            "w": 6.8,
                            "h": 0.5,
                            "text": "从场景诊断到持续运营",
                            "font_size": 18,
                            "color": "566166",
                        },
                    ],
                },
                {
                    "title": "方法漏斗",
                    "archetype": "method_funnel",
                    "expected_content": {
                        "required_text": ["诊断", "共建", "运营"],
                        "layer_type_counts": {"shape": 3, "text": 4},
                    },
                    "layers": [
                        {
                            "type": "text",
                            "name": "Funnel title",
                            "x": 0.8,
                            "y": 0.6,
                            "w": 8.0,
                            "h": 0.6,
                            "text": "三步形成可持续落地闭环",
                            "font_size": 28,
                            "bold": True,
                        },
                        *[
                            {
                                "type": "shape",
                                "name": f"Funnel band {index}",
                                "x": 2.0 + index * 0.6,
                                "y": 1.8 + index * 1.4,
                                "w": 8.8 - index * 1.2,
                                "h": 1.0,
                                "fill": color,
                                "geometry": "trapezoid",
                            }
                            for index, color in enumerate(["D9BFA9", "C78363", "8E4937"])
                        ],
                        *[
                            {
                                "type": "text",
                                "name": f"Funnel label {index}",
                                "x": 4.5,
                                "y": 2.08 + index * 1.4,
                                "w": 4.0,
                                "h": 0.4,
                                "text": label,
                                "font_size": 20,
                                "bold": True,
                                "align": "center",
                                "color": "FFFFFF" if index == 2 else "1C2528",
                            }
                            for index, label in enumerate(["诊断", "共建", "运营"])
                        ],
                    ],
                },
                {
                    "title": "合作路径",
                    "archetype": "three_path_comparison",
                    "expected_content": {
                        "required_text": ["培训赋能", "战略咨询", "Agent 中台"],
                        "layer_type_counts": {"shape": 3, "text": 4},
                        "semantic_group_counts": {"cooperation_path": 6},
                    },
                    "layers": [
                        {
                            "type": "text",
                            "name": "Paths title",
                            "x": 0.8,
                            "y": 0.6,
                            "w": 8.0,
                            "h": 0.6,
                            "text": "三条合作路径，对应不同建设深度",
                            "font_size": 28,
                            "bold": True,
                        },
                        *[
                            {
                                "type": "shape",
                                "name": f"Path panel {index}",
                                "x": 0.8 + index * 4.15,
                                "y": 1.7,
                                "w": 3.65,
                                "h": 4.7,
                                "fill": "FDFBF6" if index != 2 else "EAD3C3",
                                "line": "D7C8BA",
                                "semantic_group": "cooperation_path",
                            }
                            for index in range(3)
                        ],
                        *[
                            {
                                "type": "text",
                                "name": f"Path label {index}",
                                "x": 1.15 + index * 4.15,
                                "y": 2.2,
                                "w": 2.95,
                                "h": 0.55,
                                "text": label,
                                "font_size": 21,
                                "bold": True,
                                "align": "center",
                                "semantic_group": "cooperation_path",
                            }
                            for index, label in enumerate(["培训赋能", "战略咨询", "Agent 中台"])
                        ],
                    ],
                },
            ],
        },
    )

    assert output_path.exists(), _text_from_response(response)
    assert "route_mode=custom_compose" in _text_from_response(response)
    usage = builder_module.inspect_pptx_media_usage(output_path)
    assert usage["slide_count"] == 3
    assert usage["qa"]["layout_variety"] == 3
    assert usage["qa"]["weak_slide_count"] == 0
    comparison_xml = _slide_xml(output_path, 3)
    assert 'name="Path panel 2"' in comparison_xml
    assert "Agent 中台" in comparison_xml
    manifest = json.loads(
        output_path.with_suffix(".presentation.compose.json").read_text(encoding="utf-8"),
    )
    assert manifest["schemaVersion"] == "qwenpaw.presentation.compose.v2"
    assert manifest["route"] == "custom_compose"
    assert manifest["slides"][2]["archetype"] == "three_path_comparison"
    assert manifest["slides"][2]["layerCount"] == 7


@pytest.mark.asyncio
async def test_presentation_builder_custom_compose_rejects_semantic_content_loss(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    output_path = tmp_path / "missing_path.pptx"

    response = await builder_module.presentation_builder(
        output_path=str(output_path),
        delivery_mode="draft",
        route_mode="custom_compose",
        compose_spec={
            "slides": [
                {
                    "archetype": "three_path_comparison",
                    "expected_content": {
                        "required_text": ["培训赋能", "战略咨询", "Agent 中台"],
                    },
                    "layers": [
                        {
                            "type": "text",
                            "name": "Only two paths",
                            "x": 1,
                            "y": 1,
                            "w": 8,
                            "h": 1,
                            "text": "培训赋能 / 战略咨询",
                        },
                    ],
                },
            ],
        },
    )

    assert not output_path.exists()
    assert "missing required text 'Agent 中台'" in _text_from_response(response)


@pytest.mark.asyncio
async def test_custom_compose_accepts_common_canvas_and_layer_aliases(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    output_path = tmp_path / "alias_compose.pptx"

    response = await builder_module.presentation_builder(
        output_path=str(output_path),
        delivery_mode="draft",
        route_mode="custom_compose",
        expected_slide_count=1,
        compose_spec={
            "slide_size": {"w": 13.333333, "h": 7.5, "unit": "inches"},
            "slides": [
                {
                    "archetype": "editorial_cover",
                    "layers": [
                        {
                            "type": "shape",
                            "name": "Accent",
                            "x": 0.8,
                            "y": 0.8,
                            "w": 0.18,
                            "h": 5.8,
                            "fill": "B45B3E",
                            "stroke": "7C3524",
                            "stroke_width": 1.5,
                        },
                        {
                            "type": "text",
                            "name": "Title",
                            "x": 1.3,
                            "y": 2.3,
                            "w": 8.5,
                            "h": 1.1,
                            "content": "企业 AI 共建服务",
                            "font": "Arial",
                            "size": 34,
                            "weight": "bold",
                        },
                    ],
                    "expected_content": {
                        "required_text": ["企业 AI 共建服务"],
                    },
                },
            ],
        },
    )

    assert output_path.exists(), _text_from_response(response)
    xml = _slide_xml(output_path, 1)
    assert "企业 AI 共建服务" in xml
    assert 'b="1"' in xml
    assert "Expected slides: 1" in _text_from_response(response)


@pytest.mark.asyncio
async def test_selected_imagegen_direction_blocks_codex_grid_fallback(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    asset_path = tmp_path / "imagegen_selected.png"
    _sample_png(asset_path)
    asset_path.with_suffix(".imagegen.json").write_text(
        json.dumps(
            {
                "schemaVersion": "qwenpaw.imagegen.v1",
                "presentationContext": {
                    "stage": "visual_asset",
                    "direction_name": "稳重咨询提案型",
                    "asset_type": "cover_background",
                    "output_role": "hero_background",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "forbidden_grid.pptx"),
        delivery_mode="draft",
        route_mode="codex_grid",
        slides=[
            {
                "layout": "image_hero",
                "title": "深兆左智",
                "images": [{"path": str(asset_path), "role": "background"}],
            },
        ],
    )

    assert not (tmp_path / "forbidden_grid.pptx").exists()
    text = _text_from_response(response)
    assert "visual route QA failed" in text
    assert "route_mode=codex_grid is forbidden" in text
    assert "稳重咨询提案型" in text

    custom_response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "missing_contract.pptx"),
        delivery_mode="draft",
        route_mode="custom_compose",
        compose_spec={
            "slide_size": {"width": 13.333333, "height": 7.5},
            "slides": [
                {
                    "archetype": "cover",
                    "layers": [
                        {
                            "type": "image",
                            "name": "Selected background",
                            "asset_path": str(asset_path),
                            "x": 0,
                            "y": 0,
                            "w": 13.333333,
                            "h": 7.5,
                        },
                    ],
                },
            ],
        },
    )
    assert not (tmp_path / "missing_contract.pptx").exists()
    assert "visual translation QA failed" in _text_from_response(custom_response)


@pytest.mark.asyncio
async def test_expected_slide_count_rejects_silent_page_loss(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    output_path = tmp_path / "short_deck.pptx"

    response = await builder_module.presentation_builder(
        output_path=str(output_path),
        delivery_mode="draft",
        expected_slide_count=3,
        slides=[
            {"layout": "section", "title": "第一页"},
            {"layout": "section", "title": "第二页"},
        ],
    )

    assert not output_path.exists()
    text = _text_from_response(response)
    assert "slide-count QA failed" in text
    assert "expected_slide_count=3" in text
    assert "received 2 slide(s)" in text


@pytest.mark.asyncio
async def test_scheme_b_five_slide_golden_compose_contract(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    output_path = tmp_path / "scheme_b_golden.pptx"

    response = await builder_module.presentation_builder(
        output_path=str(output_path),
        delivery_mode="draft",
        route_mode="custom_compose",
        compose_spec=_scheme_b_compose_spec(),
        strict_qa=True,
        include_compose_manifest=True,
        requires_visual_assets=False,
    )

    assert output_path.exists(), _text_from_response(response)
    usage = builder_module.inspect_pptx_media_usage(output_path)
    assert usage["slide_count"] == 5
    assert usage["qa"]["layout_variety"] == 5
    assert usage["qa"]["weak_slide_count"] == 0
    assert usage["qa"]["overlap_count"] == 0
    assert usage["qa"]["warnings"] == []
    method_xml = _slide_xml(output_path, 3)
    choice_xml = _slide_xml(output_path, 5)
    assert all(name in method_xml for name in ["Funnel top", "Funnel middle", "Funnel bottom"])
    assert all(text in choice_xml for text in ["认知启动型", "战略重构型", "全程共建型"])
    assert 'name="Choice panel 3"' in choice_xml
    assert "route_mode=custom_compose" in _text_from_response(response)


def test_presentation_builder_exposes_80_codex_grid_templates():
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    catalog = builder_module.presentation_layout_catalog()
    templates = catalog["templates"]

    assert catalog["template_count"] == 80
    assert len(templates) == 80
    assert templates[0]["templateId"] == "codex-grid-layout-library#slide-01"
    assert templates[-1]["templateId"] == "codex-grid-layout-library#slide-80"
    assert len({item["templateId"] for item in templates}) == 80
    assert all(item["canonicalLayout"] for item in templates)
    assert {
        "templateId",
        "templateUse",
        "useWhen",
        "avoidWhen",
        "layoutFamily",
        "slots",
        "densityBudget",
        "typographyBudget",
        "assetSlots",
        "previewPng",
        "component",
        "canonicalLayout",
    }.issubset(templates[0])
    assert sum(1 for item in templates if item["templateUse"] == "process") == 36
    assert sum(1 for item in templates if item["templateUse"] == "two-column") == 14
    assert sum(1 for item in templates if item["assetSlots"]) == 9


@pytest.mark.asyncio
async def test_presentation_builder_accepts_codex_grid_template_layout_id(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "codex_registry_layout.pptx"),
        delivery_mode="draft",
        slides=[
            {
                "layout": "codex-grid-layout-library#slide-01",
                "title": "实施路线",
                "steps": [
                    {"title": "诊断", "body": "识别场景"},
                    {"title": "试点", "body": "验证闭环"},
                    {"title": "推广", "body": "复制能力"},
                ],
            },
        ],
    )

    output_path = tmp_path / "codex_registry_layout.pptx"
    assert output_path.exists(), _text_from_response(response)
    usage = builder_module.inspect_pptx_media_usage(output_path)
    assert usage["qa"]["layouts"] == ["process"]
    assert 'name="Process Step 1"' in _slide_xml(output_path, 1)


@pytest.mark.asyncio
async def test_presentation_builder_preserves_codex_grid_template_variants(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "codex_registry_variants.pptx"),
        delivery_mode="draft",
        slides=[
            {
                "layout": "codex-grid-layout-library#slide-01",
                "title": "实施路线 A",
                "steps": [
                    {"title": "诊断", "body": "识别场景"},
                    {"title": "试点", "body": "验证闭环"},
                    {"title": "推广", "body": "复制能力"},
                ],
            },
            {
                "layout": "codex-grid-layout-library#slide-02",
                "title": "实施路线 B",
                "steps": [
                    {"title": "调研", "body": "访谈业务"},
                    {"title": "建模", "body": "沉淀流程"},
                    {"title": "上线", "body": "交付系统"},
                ],
            },
        ],
    )

    output_path = tmp_path / "codex_registry_variants.pptx"
    assert output_path.exists(), _text_from_response(response)
    usage = builder_module.inspect_pptx_media_usage(output_path)
    assert usage["qa"]["templates"] == [
        "codex-grid-layout-library#slide-01",
        "codex-grid-layout-library#slide-02",
    ]
    assert usage["qa"]["template_variety"] == 2
    assert 'name="Template Variant codex-grid-layout-library#slide-01"' in _slide_xml(
        output_path,
        1,
    )
    assert 'name="Template Variant codex-grid-layout-library#slide-02"' in _slide_xml(
        output_path,
        2,
    )


@pytest.mark.asyncio
async def test_codex_grid_process_variants_render_distinct_structures(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    extra_process_cases = [
        ("09", "里程碑流程", "Process Milestone Track"),
        ("10", "阶梯栏流程", "Process Ladder Rail"),
        ("11", "看板流程", "Process Kanban Column 1"),
        ("12", "漏斗流程", "Process Funnel Stage 1"),
        ("13", "金字塔流程", "Process Pyramid Tier 1"),
        ("14", "回路流程", "Process Loopback Rail"),
        ("15", "冲刺流程", "Process Sprint Lane 1"),
        ("16", "依赖流程", "Process Dependency Node 1"),
        ("17", "关卡流程", "Process Gate Checkpoint 1"),
        ("18", "波形流程", "Process Wave Segment 1"),
        ("19", "丝带流程", "Process Ribbon Segment 1"),
        ("20", "轨道流程", "Process Orbit Ring"),
        ("21", "评分流程", "Process Scorecard Row 1"),
        ("22", "卡片时间线", "Process Timeline Card 1"),
        ("23", "瀑布卡片", "Process Cascade Card 1"),
        ("24", "象限流程", "Process Quadrant Stage 1"),
        ("25", "桥接流程", "Process Bridge Deck"),
        ("26", "传送带流程", "Process Conveyor Track"),
        ("27", "决策流程", "Process Decision Diamond 1"),
        ("28", "矩阵流程", "Process Matrix Cell 1"),
        ("29", "分层时间线", "Process Layered Timeline Rail"),
        ("30", "罗盘流程", "Process Compass Hub"),
        ("31", "路线地图", "Process Map Route"),
        ("32", "脉冲流程", "Process Pulse Node 1"),
        ("33", "集群流程", "Process Cluster Node 1"),
        ("34", "证据流程", "Process Evidence Rail"),
        ("35", "日历流程", "Process Calendar Slot 1"),
        ("36", "交接流程", "Process Handoff Lane 1"),
    ]
    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "process_variant_structures.pptx"),
        delivery_mode="draft",
        slides=[
            {
                "layout": "codex-grid-layout-library#slide-01",
                "title": "横向流程",
                "steps": ["诊断", "试点", "推广"],
            },
            {
                "layout": "codex-grid-layout-library#slide-02",
                "title": "纵向流程",
                "steps": ["调研", "建模", "上线"],
            },
            {
                "layout": "codex-grid-layout-library#slide-03",
                "title": "阶梯流程",
                "steps": ["盘点", "搭建", "运营"],
            },
            {
                "layout": "codex-grid-layout-library#slide-04",
                "title": "辐射流程",
                "steps": ["目标", "路径", "资源"],
            },
            {
                "layout": "codex-grid-layout-library#slide-05",
                "title": "泳道流程",
                "steps": ["客户", "顾问", "平台"],
            },
            {
                "layout": "codex-grid-layout-library#slide-06",
                "title": "箭带流程",
                "steps": ["进入", "处理", "输出"],
            },
            {
                "layout": "codex-grid-layout-library#slide-07",
                "title": "循环流程",
                "steps": ["规划", "执行", "复盘"],
            },
            {
                "layout": "codex-grid-layout-library#slide-08",
                "title": "堆叠流程",
                "steps": ["基础", "能力", "运营"],
            },
            *[
                {
                    "layout": f"codex-grid-layout-library#slide-{slide_number}",
                    "title": title,
                    "steps": ["诊断", "共建", "运营"],
                }
                for slide_number, title, _marker in extra_process_cases
            ],
        ],
    )

    output_path = tmp_path / "process_variant_structures.pptx"
    assert output_path.exists(), _text_from_response(response)
    usage = builder_module.inspect_pptx_media_usage(output_path)
    assert usage["qa"]["template_variety"] == 36
    first_xml = _slide_xml(output_path, 1)
    second_xml = _slide_xml(output_path, 2)
    third_xml = _slide_xml(output_path, 3)
    fourth_xml = _slide_xml(output_path, 4)
    fifth_xml = _slide_xml(output_path, 5)
    sixth_xml = _slide_xml(output_path, 6)
    seventh_xml = _slide_xml(output_path, 7)
    eighth_xml = _slide_xml(output_path, 8)
    assert 'name="Process Spine"' in first_xml
    assert 'name="Process Vertical Rail"' not in first_xml
    assert 'name="Process Vertical Rail"' in second_xml
    assert 'name="Process Lane 1"' in second_xml
    assert 'name="Process Step 1"' in second_xml
    assert 'name="Process Stair 1"' in third_xml
    assert 'name="Process Vertical Rail"' not in third_xml
    assert 'name="Process Hub"' in fourth_xml
    assert 'name="Process Spoke 1"' in fourth_xml
    assert 'name="Process Stair 1"' not in fourth_xml
    assert 'name="Process Swimlane 1"' in fifth_xml
    assert 'name="Process Swimlane Header 1"' in fifth_xml
    assert 'name="Process Chevron 1"' in sixth_xml
    assert 'name="Process Chevron Label 1"' in sixth_xml
    assert 'name="Process Cycle Ring"' in seventh_xml
    assert 'name="Process Cycle Node 1"' in seventh_xml
    assert 'name="Process Stack Layer 1"' in eighth_xml
    assert 'name="Process Stack Label 1"' in eighth_xml
    assert 'name="Process Spine"' not in fifth_xml
    assert 'name="Process Vertical Rail"' not in sixth_xml
    for slide_index, (_slide_number, _title, marker) in enumerate(
        extra_process_cases,
        start=9,
    ):
        slide_xml = _slide_xml(output_path, slide_index)
        assert f'name="{marker}"' in slide_xml


@pytest.mark.asyncio
async def test_codex_grid_two_column_variants_render_distinct_structures(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    columns = [
        {"title": "现状", "body": "流程分散\n资料不统一"},
        {"title": "目标", "body": "统一入口\n沉淀能力"},
    ]
    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "two_column_variant_structures.pptx"),
        delivery_mode="draft",
        slides=[
            {
                "layout": "codex-grid-layout-library#slide-37",
                "title": "均衡双栏",
                "columns": columns,
            },
            {
                "layout": "codex-grid-layout-library#slide-38",
                "title": "侧栏双栏",
                "columns": columns,
            },
            {
                "layout": "codex-grid-layout-library#slide-39",
                "title": "对比分隔",
                "columns": columns,
            },
            {
                "layout": "codex-grid-layout-library#slide-40",
                "title": "错位卡片",
                "columns": columns,
            },
            {
                "layout": "codex-grid-layout-library#slide-41",
                "title": "重点摘录",
                "columns": columns,
            },
            {
                "layout": "codex-grid-layout-library#slide-42",
                "title": "媒体说明",
                "columns": columns,
            },
            {
                "layout": "codex-grid-layout-library#slide-43",
                "title": "决策矩阵",
                "columns": columns,
            },
            {
                "layout": "codex-grid-layout-library#slide-44",
                "title": "堆叠双栏",
                "columns": columns,
            },
            {
                "layout": "codex-grid-layout-library#slide-45",
                "title": "数字双栏",
                "columns": columns,
            },
            {
                "layout": "codex-grid-layout-library#slide-46",
                "title": "引用双栏",
                "columns": columns,
            },
            {
                "layout": "codex-grid-layout-library#slide-47",
                "title": "时间线双栏",
                "columns": columns,
            },
            {
                "layout": "codex-grid-layout-library#slide-48",
                "title": "图像对比双栏",
                "columns": columns,
            },
            {
                "layout": "codex-grid-layout-library#slide-49",
                "title": "问答双栏",
                "columns": columns,
            },
            {
                "layout": "codex-grid-layout-library#slide-50",
                "title": "摘要网格双栏",
                "columns": columns,
            },
        ],
    )

    output_path = tmp_path / "two_column_variant_structures.pptx"
    assert output_path.exists(), _text_from_response(response)
    first_xml = _slide_xml(output_path, 1)
    second_xml = _slide_xml(output_path, 2)
    third_xml = _slide_xml(output_path, 3)
    fourth_xml = _slide_xml(output_path, 4)
    fifth_xml = _slide_xml(output_path, 5)
    sixth_xml = _slide_xml(output_path, 6)
    seventh_xml = _slide_xml(output_path, 7)
    eighth_xml = _slide_xml(output_path, 8)
    ninth_xml = _slide_xml(output_path, 9)
    tenth_xml = _slide_xml(output_path, 10)
    eleventh_xml = _slide_xml(output_path, 11)
    twelfth_xml = _slide_xml(output_path, 12)
    thirteenth_xml = _slide_xml(output_path, 13)
    fourteenth_xml = _slide_xml(output_path, 14)
    assert 'name="Column Panel 1"' in first_xml
    assert 'name="Two Column Sidebar Rail"' not in first_xml
    assert 'name="Two Column Sidebar Rail"' in second_xml
    assert 'name="Sidebar Column Panel"' in second_xml
    assert 'name="Two Column Divider"' in third_xml
    assert 'name="Compare Column 1"' in third_xml
    assert 'name="Two Column Offset Card 1"' in fourth_xml
    assert 'name="Two Column Offset Band 1"' in fourth_xml
    assert 'name="Two Column Divider"' not in fourth_xml
    assert 'name="Two Column Callout Panel"' in fifth_xml
    assert 'name="Two Column Evidence Panel"' in fifth_xml
    assert 'name="Two Column Media Frame"' in sixth_xml
    assert 'name="Two Column Text Rail"' in sixth_xml
    assert 'name="Two Column Decision Matrix"' in seventh_xml
    assert 'name="Two Column Decision Cell 1"' in seventh_xml
    assert 'name="Two Column Stack Card 1"' in eighth_xml
    assert 'name="Two Column Stack Card 2"' in eighth_xml
    assert 'name="Two Column Offset Card 1"' not in eighth_xml
    assert 'name="Two Column Stat Band"' in ninth_xml
    assert 'name="Two Column Stat 1"' in ninth_xml
    assert 'name="Two Column Quote Panel 1"' in tenth_xml
    assert 'name="Two Column Quote Mark 1"' in tenth_xml
    assert 'name="Two Column Timeline Rail"' in eleventh_xml
    assert 'name="Two Column Timeline Node 1"' in eleventh_xml
    assert 'name="Two Column Image Compare Frame 1"' in twelfth_xml
    assert 'name="Two Column Image Divider"' in twelfth_xml
    assert 'name="Two Column QA Question"' in thirteenth_xml
    assert 'name="Two Column QA Answer"' in thirteenth_xml
    assert 'name="Two Column Summary Grid"' in fourteenth_xml
    assert 'name="Two Column Summary Cell 1"' in fourteenth_xml
    assert 'name="Two Column Stat Band"' not in fourteenth_xml


@pytest.mark.asyncio
async def test_codex_grid_metrics_variants_render_distinct_structures(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    metrics = [
        {"label": "周期", "value": "4周", "caption": "试点上线"},
        {"label": "场景", "value": "6个", "caption": "首批沉淀"},
        {"label": "组件", "value": "20+", "caption": "复用资产"},
    ]
    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "metrics_variant_structures.pptx"),
        delivery_mode="draft",
        slides=[
            {
                "layout": "codex-grid-layout-library#slide-51",
                "title": "指标卡",
                "metrics": metrics,
            },
            {
                "layout": "codex-grid-layout-library#slide-52",
                "title": "排行指标",
                "metrics": metrics,
            },
            {
                "layout": "codex-grid-layout-library#slide-53",
                "title": "中心指标",
                "metrics": metrics,
            },
            {
                "layout": "codex-grid-layout-library#slide-54",
                "title": "条形指标",
                "metrics": metrics,
            },
            {
                "layout": "codex-grid-layout-library#slide-55",
                "title": "仪表指标",
                "metrics": metrics,
            },
            {
                "layout": "codex-grid-layout-library#slide-56",
                "title": "指标墙",
                "metrics": metrics,
            },
            {
                "layout": "codex-grid-layout-library#slide-57",
                "title": "瀑布指标",
                "metrics": metrics,
            },
            {
                "layout": "codex-grid-layout-library#slide-58",
                "title": "对比环指标",
                "metrics": metrics,
            },
        ],
    )

    output_path = tmp_path / "metrics_variant_structures.pptx"
    assert output_path.exists(), _text_from_response(response)
    first_xml = _slide_xml(output_path, 1)
    second_xml = _slide_xml(output_path, 2)
    third_xml = _slide_xml(output_path, 3)
    fourth_xml = _slide_xml(output_path, 4)
    fifth_xml = _slide_xml(output_path, 5)
    sixth_xml = _slide_xml(output_path, 6)
    seventh_xml = _slide_xml(output_path, 7)
    eighth_xml = _slide_xml(output_path, 8)
    assert 'name="Metric 1"' in first_xml
    assert 'name="Metric Leaderboard Row 1"' not in first_xml
    assert 'name="Metric Leaderboard Row 1"' in second_xml
    assert 'name="Metric Rank 1"' in second_xml
    assert 'name="Metric Spotlight"' in third_xml
    assert 'name="Metric Satellite 1"' in third_xml
    assert 'name="Metric Bar Track 1"' in fourth_xml
    assert 'name="Metric Bar 1"' in fourth_xml
    assert 'name="Metric Spotlight"' not in fourth_xml
    assert 'name="Metric Gauge Dial"' in fifth_xml
    assert 'name="Metric Gauge Needle"' in fifth_xml
    assert 'name="Metric Tile Wall"' in sixth_xml
    assert 'name="Metric Tile 1"' in sixth_xml
    assert 'name="Metric Waterfall Baseline"' in seventh_xml
    assert 'name="Metric Waterfall Step 1"' in seventh_xml
    assert 'name="Metric Compare Ring 1"' in eighth_xml
    assert 'name="Metric Compare Center"' in eighth_xml
    assert 'name="Metric Gauge Dial"' not in eighth_xml


@pytest.mark.asyncio
async def test_codex_grid_image_hero_variants_render_distinct_structures(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "image_hero_variant_structures.pptx"),
        delivery_mode="draft",
        slides=[
            {
                "layout": "codex-grid-layout-library#slide-59",
                "title": "分栏主视觉",
                "subtitle": "左文右图",
                "body": "保留可编辑标题和正文。",
            },
            {
                "layout": "codex-grid-layout-library#slide-60",
                "title": "满版主视觉",
                "subtitle": "大图承载视觉方向",
                "body": "文字覆盖在图像安全区。",
            },
            {
                "layout": "codex-grid-layout-library#slide-61",
                "title": "横幅主视觉",
                "subtitle": "上下分区",
                "body": "强调提案开场。",
            },
            {
                "layout": "codex-grid-layout-library#slide-62",
                "title": "拼贴主视觉",
                "subtitle": "多图候选方向",
                "body": "用于视觉方案选择。",
            },
            {
                "layout": "codex-grid-layout-library#slide-63",
                "title": "海报主视觉",
                "subtitle": "强标题版式",
                "body": "适合封面级开场。",
            },
            {
                "layout": "codex-grid-layout-library#slide-64",
                "title": "设备主视觉",
                "subtitle": "产品界面演示",
                "body": "用于承载软件界面。",
            },
            {
                "layout": "codex-grid-layout-library#slide-65",
                "title": "图库主视觉",
                "subtitle": "多资产陈列",
                "body": "适合展示视觉资产套件。",
            },
        ],
    )

    output_path = tmp_path / "image_hero_variant_structures.pptx"
    assert output_path.exists(), _text_from_response(response)
    first_xml = _slide_xml(output_path, 1)
    second_xml = _slide_xml(output_path, 2)
    third_xml = _slide_xml(output_path, 3)
    fourth_xml = _slide_xml(output_path, 4)
    fifth_xml = _slide_xml(output_path, 5)
    sixth_xml = _slide_xml(output_path, 6)
    seventh_xml = _slide_xml(output_path, 7)
    assert 'name="Hero Media Frame"' in first_xml
    assert 'name="Hero Full Bleed Frame"' not in first_xml
    assert 'name="Hero Full Bleed Frame"' in second_xml
    assert 'name="Hero Overlay Panel"' in second_xml
    assert 'name="Hero Band Media Frame"' in third_xml
    assert 'name="Hero Caption Band"' in third_xml
    assert 'name="Hero Mosaic Frame 1"' in fourth_xml
    assert 'name="Hero Mosaic Frame 3"' in fourth_xml
    assert 'name="Hero Band Media Frame"' not in fourth_xml
    assert 'name="Hero Poster Frame"' in fifth_xml
    assert 'name="Hero Poster Title Block"' in fifth_xml
    assert 'name="Hero Device Frame"' in sixth_xml
    assert 'name="Hero Device Screen"' in sixth_xml
    assert 'name="Hero Gallery Strip"' in seventh_xml
    assert 'name="Hero Gallery Frame 1"' in seventh_xml
    assert 'name="Hero Poster Frame"' not in seventh_xml


@pytest.mark.asyncio
async def test_codex_grid_table_variants_render_distinct_structures(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    table = {
        "headers": ["模块", "交付物", "价值"],
        "rows": [
            ["培训", "课程", "统一认知"],
            ["咨询", "路线图", "降低试错"],
            ["中台", "组件库", "持续复用"],
        ],
    }
    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "table_variant_structures.pptx"),
        delivery_mode="draft",
        slides=[
            {
                "layout": "codex-grid-layout-library#slide-71",
                "title": "网格表",
                "table": table,
            },
            {
                "layout": "codex-grid-layout-library#slide-72",
                "title": "矩阵表",
                "table": table,
            },
            {
                "layout": "codex-grid-layout-library#slide-73",
                "title": "记录卡片",
                "table": table,
            },
            {
                "layout": "codex-grid-layout-library#slide-74",
                "title": "热力表",
                "table": table,
            },
            {
                "layout": "codex-grid-layout-library#slide-75",
                "title": "时间轴表",
                "table": table,
            },
        ],
    )

    output_path = tmp_path / "table_variant_structures.pptx"
    assert output_path.exists(), _text_from_response(response)
    first_xml = _slide_xml(output_path, 1)
    second_xml = _slide_xml(output_path, 2)
    third_xml = _slide_xml(output_path, 3)
    fourth_xml = _slide_xml(output_path, 4)
    fifth_xml = _slide_xml(output_path, 5)
    assert 'name="Table Header 1"' in first_xml
    assert 'name="Table Matrix Header Band"' not in first_xml
    assert 'name="Table Matrix Header Band"' in second_xml
    assert 'name="Table Matrix Row 1"' in second_xml
    assert 'name="Table Record Card 1"' in third_xml
    assert 'name="Table Record Label 1-1"' in third_xml
    assert 'name="Table Heat Cell 1-1"' in fourth_xml
    assert 'name="Table Heat Legend"' in fourth_xml
    assert 'name="Table Record Card 1"' not in fourth_xml
    assert 'name="Table Timeline Rail"' in fifth_xml
    assert 'name="Table Timeline Row 1"' in fifth_xml
    assert 'name="Table Heat Cell 1-1"' not in fifth_xml


@pytest.mark.asyncio
async def test_codex_grid_agenda_variants_render_distinct_structures(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    items = [
        {"title": "背景判断", "body": "看清业务问题"},
        {"title": "方案设计", "body": "确定能力边界"},
        {"title": "落地路径", "body": "形成执行计划"},
    ]
    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "agenda_variant_structures.pptx"),
        delivery_mode="draft",
        slides=[
            {
                "layout": "codex-grid-layout-library#slide-66",
                "title": "列表议程",
                "items": items,
            },
            {
                "layout": "codex-grid-layout-library#slide-67",
                "title": "时间轴议程",
                "items": items,
            },
            {
                "layout": "codex-grid-layout-library#slide-68",
                "title": "网格议程",
                "items": items,
            },
            {
                "layout": "codex-grid-layout-library#slide-69",
                "title": "章节议程",
                "items": items,
            },
            {
                "layout": "codex-grid-layout-library#slide-70",
                "title": "导航议程",
                "items": items,
            },
        ],
    )

    output_path = tmp_path / "agenda_variant_structures.pptx"
    assert output_path.exists(), _text_from_response(response)
    first_xml = _slide_xml(output_path, 1)
    second_xml = _slide_xml(output_path, 2)
    third_xml = _slide_xml(output_path, 3)
    fourth_xml = _slide_xml(output_path, 4)
    fifth_xml = _slide_xml(output_path, 5)
    assert 'name="Agenda Number 1"' in first_xml
    assert 'name="Agenda Timeline Rail"' not in first_xml
    assert 'name="Agenda Timeline Rail"' in second_xml
    assert 'name="Agenda Timeline Node 1"' in second_xml
    assert 'name="Agenda Grid Card 1"' in third_xml
    assert 'name="Agenda Grid Number 1"' in third_xml
    assert 'name="Agenda Chapter Card 1"' in fourth_xml
    assert 'name="Agenda Chapter Index 1"' in fourth_xml
    assert 'name="Agenda Grid Card 1"' not in fourth_xml
    assert 'name="Agenda Navigator Rail"' in fifth_xml
    assert 'name="Agenda Navigator Node 1"' in fifth_xml
    assert 'name="Agenda Chapter Card 1"' not in fifth_xml


@pytest.mark.asyncio
async def test_codex_grid_cover_and_chart_variants_render_distinct_structures(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    metrics = [
        {"label": "效率提升", "value": "35%", "caption": "流程自动化"},
        {"label": "成本下降", "value": "18%", "caption": "重复工作减少"},
        {"label": "满意度", "value": "92", "caption": "内部评分"},
    ]
    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "cover_chart_variant_structures.pptx"),
        delivery_mode="draft",
        slides=[
            {
                "layout": "codex-grid-layout-library#slide-76",
                "title": "企业 AI 落地方案",
                "subtitle": "执行版提案",
                "body": "从诊断到共建。",
            },
            {
                "layout": "codex-grid-layout-library#slide-77",
                "title": "企业 AI 落地方案",
                "subtitle": "商务演示版",
                "body": "面向管理层汇报。",
            },
            {
                "layout": "codex-grid-layout-library#slide-78",
                "title": "收益趋势",
                "metrics": metrics,
            },
            {
                "layout": "codex-grid-layout-library#slide-79",
                "title": "指标拆解",
                "metrics": metrics,
            },
        ],
    )

    output_path = tmp_path / "cover_chart_variant_structures.pptx"
    assert output_path.exists(), _text_from_response(response)
    cover_one_xml = _slide_xml(output_path, 1)
    cover_two_xml = _slide_xml(output_path, 2)
    chart_one_xml = _slide_xml(output_path, 3)
    chart_two_xml = _slide_xml(output_path, 4)
    assert 'name="Cover Field Frame"' in cover_one_xml
    assert 'name="Cover Title Lockup"' in cover_one_xml
    assert 'name="Cover Masthead Band"' in cover_two_xml
    assert 'name="Cover Media Strip"' in cover_two_xml
    assert 'name="Cover Field Frame"' not in cover_two_xml
    assert 'name="Chart Insight Frame"' in chart_one_xml
    assert 'name="Chart Plot Area"' in chart_one_xml
    assert 'name="Chart Split Plot"' in chart_two_xml
    assert 'name="Chart Legend Panel"' in chart_two_xml
    assert 'name="Chart Insight Frame"' not in chart_two_xml


@pytest.mark.asyncio
async def test_codex_grid_content_template_renders_modular_structure(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "content_variant_structure.pptx"),
        delivery_mode="draft",
        slides=[
            {
                "layout": "codex-grid-layout-library#slide-80",
                "title": "关键结论",
                "body": "用一页承接无法归类的信息，但仍保持模块化结构。",
                "bullets": ["保留主叙事", "提供支撑要点", "避免退化成纯文本"],
            },
        ],
    )

    output_path = tmp_path / "content_variant_structure.pptx"
    assert output_path.exists(), _text_from_response(response)
    slide_xml = _slide_xml(output_path, 1)
    assert 'name="Content Modular Canvas"' in slide_xml
    assert 'name="Content Primary Panel"' in slide_xml
    assert 'name="Content Support Rail"' in slide_xml
    assert 'name="Body"' not in slide_xml


@pytest.mark.asyncio
async def test_presentation_builder_render_qa_returns_preview_artifacts(
    tmp_path,
    monkeypatch,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    def fake_render_preview(pptx_path, preview_dir=None):
        preview_root = Path(preview_dir or Path(pptx_path).with_suffix("")) / "render_qa"
        preview_root.mkdir(parents=True, exist_ok=True)
        work_dir = preview_root / "_work"
        work_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = work_dir / f"{Path(pptx_path).stem}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n% fake final delivery pdf\n")
        slide_one = preview_root / "slide-1.png"
        slide_two = preview_root / "slide-2.png"
        contact_sheet = preview_root / "contact_sheet.png"
        _sample_png(slide_one)
        _sample_png(slide_two)
        Image.new("RGB", (960, 540), (255, 255, 255)).save(contact_sheet)
        return {
            "status": "ok",
            "engine": "libreoffice+pdftoppm",
            "preview_dir": str(preview_root),
            "contact_sheet": str(contact_sheet),
            "pdf_path": str(pdf_path),
            "slide_images": [str(slide_one), str(slide_two)],
            "slide_count": 2,
        }

    monkeypatch.setattr(
        builder_module,
        "_render_pptx_preview",
        fake_render_preview,
        raising=False,
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "rendered.pptx"),
        delivery_mode="draft",
        render_qa=True,
        slides=[
            {"layout": "section", "title": "第一页"},
            {"layout": "cards", "title": "第二页", "items": ["A", "B"]},
        ],
    )

    file_names = _file_names_from_response(response)
    assert file_names == ["rendered.pptx"]
    text = _text_from_response(response)
    assert "render_qa=ok" in text
    assert "rendered_slide_count=2" in text


@pytest.mark.asyncio
async def test_presentation_builder_final_delivery_auto_runs_render_qa(
    tmp_path,
    monkeypatch,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    def fake_render_preview(pptx_path, preview_dir=None):
        preview_root = Path(preview_dir or Path(pptx_path).with_suffix("")) / "render_qa"
        preview_root.mkdir(parents=True, exist_ok=True)
        work_dir = preview_root / "_work"
        work_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = work_dir / f"{Path(pptx_path).stem}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n% fake final delivery pdf\n")
        slide_one = preview_root / "slide-1.png"
        slide_two = preview_root / "slide-2.png"
        contact_sheet = preview_root / "contact_sheet.png"
        _sample_png(slide_one)
        _sample_png(slide_two)
        Image.new("RGB", (960, 540), (255, 255, 255)).save(contact_sheet)
        return {
            "status": "ok",
            "engine": "libreoffice+pdftoppm",
            "preview_dir": str(preview_root),
            "contact_sheet": str(contact_sheet),
            "pdf_path": str(pdf_path),
            "slide_images": [str(slide_one), str(slide_two)],
            "slide_count": 2,
        }

    monkeypatch.setattr(
        builder_module,
        "_render_pptx_preview",
        fake_render_preview,
        raising=False,
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "final.pptx"),
        delivery_mode="final",
        slides=[
            {"layout": "cards", "title": "服务矩阵", "items": ["A", "B", "C"]},
            {"layout": "process", "title": "落地流程", "steps": ["诊断", "试点", "推广"]},
        ],
    )

    file_names = _file_names_from_response(response)
    assert file_names == [
        "final.pptx",
        "final.pdf",
        "final.presentation.compose.json",
    ]
    assert (tmp_path / "final.pdf").exists()
    manifest = json.loads(
        (tmp_path / "final.presentation.compose.json").read_text(encoding="utf-8"),
    )
    assert manifest["output"]["pdf"].endswith("final.pdf")
    text = _text_from_response(response)
    assert "delivery_mode=final" in text
    assert "export_pdf=true" in text
    assert "render_qa=ok" in text


@pytest.mark.asyncio
async def test_final_delivery_rewrites_workspace_media_output_to_session_artifacts(
    tmp_path,
    monkeypatch,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    session_id = "session-presentations"
    requested_output = workspace_dir / "media" / "client_delivery.pptx"
    expected_output = (
        workspace_dir
        / "sessions_data"
        / session_id
        / "artifacts"
        / "presentation"
        / "client_delivery.pptx"
    )

    def fake_render_preview(pptx_path, preview_dir=None):
        preview_root = Path(preview_dir or Path(pptx_path).with_suffix("")) / "render_qa"
        preview_root.mkdir(parents=True, exist_ok=True)
        work_dir = preview_root / "_work"
        work_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = work_dir / f"{Path(pptx_path).stem}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n% fake isolated delivery pdf\n")
        slide_one = preview_root / "slide-1.png"
        slide_two = preview_root / "slide-2.png"
        contact_sheet = preview_root / "contact_sheet.png"
        _sample_png(slide_one)
        _sample_png(slide_two)
        Image.new("RGB", (960, 540), (255, 255, 255)).save(contact_sheet)
        return {
            "status": "ok",
            "engine": "libreoffice+pdftoppm",
            "preview_dir": str(preview_root),
            "contact_sheet": str(contact_sheet),
            "pdf_path": str(pdf_path),
            "slide_images": [str(slide_one), str(slide_two)],
            "slide_count": 2,
        }

    monkeypatch.setattr(
        builder_module,
        "_render_pptx_preview",
        fake_render_preview,
        raising=False,
    )
    set_current_workspace_dir(workspace_dir)
    set_current_session_id(session_id)

    try:
        response = await builder_module.presentation_builder(
            output_path=str(requested_output),
            delivery_mode="final",
            slides=[
                {"layout": "content", "title": "核心判断", "body": "A"},
                {"layout": "process", "title": "落地流程", "steps": ["诊断", "试点"]},
            ],
        )
    finally:
        set_current_workspace_dir(None)
        set_current_session_id("")

    assert not requested_output.exists()
    assert expected_output.exists()
    assert expected_output.with_suffix(".pdf").exists()
    assert expected_output.with_suffix(".presentation.compose.json").exists()
    assert _file_names_from_response(response) == [
        "client_delivery.pptx",
        "client_delivery.pdf",
        "client_delivery.presentation.compose.json",
    ]
    assert f"Output: {expected_output}" in _text_from_response(response)


@pytest.mark.asyncio
async def test_final_delivery_visual_asset_coverage_warns_on_thin_decks(
    tmp_path,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    session_id = "session-thin-visuals"
    session_media_dir = workspace_dir / "sessions_data" / session_id / "media" / "imagegen"
    session_media_dir.mkdir(parents=True)
    assets = []
    for index in range(4):
        asset_path = session_media_dir / f"imagegen_{index}.png"
        _sample_png(asset_path)
        assets.append(asset_path)

    warnings = builder_module._final_delivery_visual_asset_warnings(
        usage={
            "slide_count": 12,
            "pic_count": 1,
            "media_count": 1,
            "qa": {
                "template_variety": 4,
                "warnings": [],
            },
        },
        session_imagegen_assets=assets,
        referenced_assets={assets[0]},
        visual_assets_setting="auto",
    )

    assert warnings == [
        "visual asset coverage is too low: 1 picture(s) for 12 slides; "
        "expected at least 3 for a final deck with generated visual assets",
    ]


@pytest.mark.asyncio
async def test_final_delivery_rejects_single_asset_suite_for_long_decks(
    tmp_path,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    session_id = "session-single-visual"
    session_media_dir = workspace_dir / "sessions_data" / session_id / "media" / "imagegen"
    session_media_dir.mkdir(parents=True)
    asset_path = session_media_dir / "imagegen_1.png"
    _sample_png(asset_path)

    warnings = builder_module._final_delivery_visual_asset_warnings(
        usage={
            "slide_count": 12,
            "pic_count": 1,
            "media_count": 1,
            "qa": {
                "template_variety": 4,
                "warnings": [],
            },
        },
        session_imagegen_assets=[asset_path],
        referenced_assets={asset_path},
        visual_assets_setting=True,
    )

    assert warnings == [
        "visual asset suite is too thin: 1 generated image asset for 12 "
        "slides; expected at least 3 project-bound visual assets before "
        "final PPTX production",
    ]


@pytest.mark.asyncio
async def test_final_delivery_fails_when_mapped_asset_suite_is_too_thin(
    tmp_path,
    monkeypatch,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    session_id = "session-mapped-single-visual"
    session_media_dir = workspace_dir / "sessions_data" / session_id / "media" / "imagegen"
    session_media_dir.mkdir(parents=True)
    asset_path = session_media_dir / "imagegen_1.png"
    _sample_png(asset_path)
    set_current_workspace_dir(workspace_dir)
    set_current_session_id(session_id)

    def fake_render_preview(pptx_path, preview_dir=None):
        preview_root = Path(preview_dir or Path(pptx_path).with_suffix("")) / "render_qa"
        preview_root.mkdir(parents=True, exist_ok=True)
        slide_images = []
        for index in range(1, 9):
            slide_path = preview_root / f"slide-{index}.png"
            _sample_png(slide_path)
            slide_images.append(str(slide_path))
        contact_sheet = preview_root / "contact_sheet.png"
        Image.new("RGB", (960, 540), (255, 255, 255)).save(contact_sheet)
        return {
            "status": "ok",
            "engine": "libreoffice+pdftoppm",
            "preview_dir": str(preview_root),
            "contact_sheet": str(contact_sheet),
            "slide_images": slide_images,
            "slide_count": 8,
        }

    monkeypatch.setattr(
        builder_module,
        "_render_pptx_preview",
        fake_render_preview,
        raising=False,
    )

    output_path = workspace_dir / "single_asset_final.pptx"
    expected_session_output = (
        workspace_dir
        / "sessions_data"
        / session_id
        / "artifacts"
        / "presentation"
        / output_path.name
    )

    try:
        response = await builder_module.presentation_builder(
            output_path=str(output_path),
            delivery_mode="final",
            requires_visual_assets=True,
            theme={
                "canvas": "#FFFFFF",
                "ink": "#111827",
                "panel": "#FFF7ED",
                "panel_alt": "#EDE9FE",
                "accent": "#F97316",
                "accent_soft": "#FDE68A",
                "font_family": "Microsoft YaHei",
            },
            required_image_assets=[str(asset_path)],
            asset_usage_matrix=[
                {
                    "slide_index": 1,
                    "asset_path": str(asset_path),
                    "role": "hero",
                },
            ],
            slides=[
                {
                    "layout": "cover",
                    "title": "客户交付",
                    "subtitle": "制造业 AI 落地共建服务",
                },
                {
                    "layout": "content",
                    "title": "核心判断",
                    "body": "将场景诊断、试点共建和持续运营连成可交付闭环。",
                    "bullets": ["场景优先", "低风险试点", "运营复盘"],
                },
                {
                    "layout": "process",
                    "title": "落地流程",
                    "steps": ["诊断", "试点", "推广"],
                },
                {
                    "layout": "metrics",
                    "title": "交付指标",
                    "metrics": [
                        {"label": "周期", "value": "4周"},
                        {"label": "场景", "value": "3个"},
                    ],
                },
                {
                    "layout": "two_column",
                    "title": "服务模型",
                    "columns": [
                        {"title": "共建", "items": ["业务访谈", "试点落地"]},
                        {"title": "运营", "items": ["复盘优化", "规模推广"]},
                    ],
                },
                {
                    "layout": "comparison",
                    "title": "前后对比",
                    "columns": [
                        {"title": "传统方式", "items": ["周期长", "复用弱"]},
                        {"title": "AI 共建", "items": ["启动快", "可沉淀"]},
                    ],
                },
                {
                    "layout": "roadmap",
                    "title": "实施路线",
                    "steps": ["准备", "试点", "上线", "运营"],
                },
                {
                    "layout": "table",
                    "title": "交付清单",
                    "table": {
                        "headers": ["阶段", "交付物"],
                        "rows": [["诊断", "机会地图"], ["试点", "流程样板"]],
                    },
                },
            ],
        )
    finally:
        set_current_workspace_dir(None)
        set_current_session_id("")

    assert not output_path.exists()
    assert not expected_session_output.exists()
    text = _text_from_response(response)
    assert "visual QA failed" in text
    assert "visual asset suite is too thin" in text


@pytest.mark.asyncio
async def test_final_delivery_with_visual_assets_requires_explicit_theme(
    tmp_path,
    monkeypatch,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    session_id = "session-visual-theme"
    session_media_dir = workspace_dir / "sessions_data" / session_id / "media" / "imagegen"
    session_media_dir.mkdir(parents=True)
    asset_paths = []
    for index in range(1, 4):
        asset_path = session_media_dir / f"imagegen_{index}.png"
        _sample_png(asset_path)
        asset_paths.append(asset_path)
    set_current_workspace_dir(workspace_dir)
    set_current_session_id(session_id)

    def fake_render_preview(pptx_path, preview_dir=None):
        preview_root = Path(preview_dir or Path(pptx_path).with_suffix("")) / "render_qa"
        preview_root.mkdir(parents=True, exist_ok=True)
        work_dir = preview_root / "_work"
        work_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = work_dir / f"{Path(pptx_path).stem}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n% fake visual theme pdf\n")
        slide_images = []
        for index in range(1, 9):
            slide_path = preview_root / f"slide-{index}.png"
            _sample_png(slide_path)
            slide_images.append(str(slide_path))
        contact_sheet = preview_root / "contact_sheet.png"
        Image.new("RGB", (960, 540), (255, 255, 255)).save(contact_sheet)
        return {
            "status": "ok",
            "engine": "libreoffice+pdftoppm",
            "preview_dir": str(preview_root),
            "contact_sheet": str(contact_sheet),
            "pdf_path": str(pdf_path),
            "slide_images": slide_images,
            "slide_count": 8,
        }

    monkeypatch.setattr(
        builder_module,
        "_render_pptx_preview",
        fake_render_preview,
        raising=False,
    )

    output_path = workspace_dir / "visual_theme_final.pptx"
    expected_session_output = (
        workspace_dir
        / "sessions_data"
        / session_id
        / "artifacts"
        / "presentation"
        / output_path.name
    )

    try:
        response = await builder_module.presentation_builder(
            output_path=str(output_path),
            delivery_mode="final",
            requires_visual_assets=True,
            required_image_assets=[str(path) for path in asset_paths],
            asset_usage_matrix=[
                {
                    "slide_index": index,
                    "asset_path": str(path),
                    "role": "visual-language",
                }
                for index, path in enumerate(asset_paths, start=1)
            ],
            slides=[
                {
                    "layout": f"codex-grid-layout-library#slide-{index:02d}",
                    "title": f"页面 {index}",
                    "body": "保持所选视觉方案的节奏、色彩、组件和页面气质。",
                    "items": ["视觉方案", "设计契约", "可编辑实现"],
                }
                for index in range(1, 9)
            ],
        )
    finally:
        set_current_workspace_dir(None)
        set_current_session_id("")

    assert not output_path.exists()
    assert not expected_session_output.exists()
    text = _text_from_response(response)
    assert "visual design QA failed" in text
    assert "explicit theme object" in text


@pytest.mark.asyncio
async def test_final_delivery_rejects_unmapped_visual_assets_by_default(
    tmp_path,
    monkeypatch,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    def fake_render_preview(pptx_path, preview_dir=None):
        preview_root = Path(preview_dir or Path(pptx_path).with_suffix("")) / "render_qa"
        preview_root.mkdir(parents=True, exist_ok=True)
        slide_images = []
        for index in range(1, 9):
            slide_path = preview_root / f"slide-{index}.png"
            _sample_png(slide_path)
            slide_images.append(str(slide_path))
        contact_sheet = preview_root / "contact_sheet.png"
        Image.new("RGB", (960, 540), (255, 255, 255)).save(contact_sheet)
        return {
            "status": "ok",
            "engine": "fake",
            "preview_dir": str(preview_root),
            "contact_sheet": str(contact_sheet),
            "slide_images": slide_images,
            "slide_count": 8,
        }

    monkeypatch.setattr(
        builder_module,
        "_render_pptx_preview",
        fake_render_preview,
        raising=False,
    )

    output_path = tmp_path / "client_final_without_assets.pptx"

    response = await builder_module.presentation_builder(
        output_path=str(output_path),
        delivery_mode="final",
        slides=[
            {
                "layout": f"codex-grid-layout-library#slide-{58 + index:02d}",
                "title": f"页面 {index}",
                "body": "这是一份面向客户交付的最终 PPT，不应该在没有视觉资产映射时成功。",
                "subtitle": "视觉资产必须进入最终构建合同。",
            }
            for index in range(1, 9)
        ],
    )

    assert not output_path.exists()
    text = _text_from_response(response)
    assert "visual QA failed" in text
    assert "unfilled media frame" in text


@pytest.mark.asyncio
async def test_final_delivery_rejects_unfilled_media_frames(
    tmp_path,
    monkeypatch,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    session_id = "session-unfilled-media-frames"
    session_media_dir = workspace_dir / "sessions_data" / session_id / "media" / "imagegen"
    session_media_dir.mkdir(parents=True)
    asset_paths = []
    for index in range(1, 4):
        asset_path = session_media_dir / f"imagegen_{index}.png"
        _sample_png(asset_path)
        asset_paths.append(asset_path)
    set_current_workspace_dir(workspace_dir)
    set_current_session_id(session_id)

    def fake_render_preview(pptx_path, preview_dir=None):
        preview_root = Path(preview_dir or Path(pptx_path).with_suffix("")) / "render_qa"
        preview_root.mkdir(parents=True, exist_ok=True)
        slide_images = []
        for index in range(1, 9):
            slide_path = preview_root / f"slide-{index}.png"
            _sample_png(slide_path)
            slide_images.append(str(slide_path))
        contact_sheet = preview_root / "contact_sheet.png"
        Image.new("RGB", (960, 540), (255, 255, 255)).save(contact_sheet)
        return {
            "status": "ok",
            "engine": "fake",
            "preview_dir": str(preview_root),
            "contact_sheet": str(contact_sheet),
            "slide_images": slide_images,
            "slide_count": 8,
        }

    monkeypatch.setattr(
        builder_module,
        "_render_pptx_preview",
        fake_render_preview,
        raising=False,
    )

    output_path = workspace_dir / "unfilled_media_frames.pptx"
    try:
        response = await builder_module.presentation_builder(
            output_path=str(output_path),
            delivery_mode="final",
            requires_visual_assets=True,
            theme={
                "canvas": "#FFFFFF",
                "ink": "#111827",
                "body": "#374151",
                "muted": "#6B7280",
                "panel": "#F3F4F6",
                "panel_alt": "#E5E7EB",
                "rule": "#D1D5DB",
                "accent": "#2563EB",
                "accent_soft": "#DBEAFE",
                "font_family": "Microsoft YaHei",
            },
            required_image_assets=[str(path) for path in asset_paths],
            asset_usage_matrix=[
                {
                    "slide_index": slide_index,
                    "asset_path": str(asset_path),
                    "role": "hero",
                    "purpose": "关键页面主视觉。",
                }
                for slide_index, asset_path in zip((1, 3, 4), asset_paths)
            ],
            slides=[
                {
                    "layout": "codex-grid-layout-library#slide-59",
                    "title": f"视觉页面 {index}",
                    "body": "需要主视觉承接所选方案。",
                }
                for index in range(1, 5)
            ]
            + [
                {
                    "layout": f"codex-grid-layout-library#slide-{index + 10:02d}",
                    "title": f"内容页面 {index}",
                    "items": ["一", "二", "三"],
                }
                for index in range(5, 9)
            ],
        )
    finally:
        set_current_workspace_dir(None)
        set_current_session_id("")

    assert not output_path.exists()
    text = _text_from_response(response)
    assert "visual QA failed" in text
    assert "unfilled media frame" in text


@pytest.mark.asyncio
async def test_final_delivery_rejects_component_sheet_as_direct_raster_asset(
    tmp_path,
    monkeypatch,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    session_id = "session-component-sheet-stuffing"
    session_media_dir = workspace_dir / "sessions_data" / session_id / "media" / "imagegen"
    session_media_dir.mkdir(parents=True)
    asset_paths = []
    for index in range(1, 4):
        asset_path = session_media_dir / f"imagegen_{index}.png"
        _sample_png(asset_path)
        asset_paths.append(asset_path)
    set_current_workspace_dir(workspace_dir)
    set_current_session_id(session_id)

    def fake_render_preview(pptx_path, preview_dir=None):
        preview_root = Path(preview_dir or Path(pptx_path).with_suffix("")) / "render_qa"
        preview_root.mkdir(parents=True, exist_ok=True)
        slide_images = []
        for index in range(1, 9):
            slide_path = preview_root / f"slide-{index}.png"
            _sample_png(slide_path)
            slide_images.append(str(slide_path))
        contact_sheet = preview_root / "contact_sheet.png"
        Image.new("RGB", (960, 540), (255, 255, 255)).save(contact_sheet)
        return {
            "status": "ok",
            "engine": "libreoffice+pdftoppm",
            "preview_dir": str(preview_root),
            "contact_sheet": str(contact_sheet),
            "slide_images": slide_images,
            "slide_count": 8,
        }

    monkeypatch.setattr(
        builder_module,
        "_render_pptx_preview",
        fake_render_preview,
        raising=False,
    )

    output_path = workspace_dir / "component_sheet_stuffing.pptx"

    try:
        response = await builder_module.presentation_builder(
            output_path=str(output_path),
            delivery_mode="final",
            requires_visual_assets=True,
            theme={
                "canvas": "#FFFFFF",
                "ink": "#111827",
                "body": "#374151",
                "muted": "#6B7280",
                "panel": "#FFF7ED",
                "panel_alt": "#EDE9FE",
                "rule": "#FDBA74",
                "accent": "#F97316",
                "accent_soft": "#FDE68A",
                "font_family": "Microsoft YaHei",
            },
            required_image_assets=[str(path) for path in asset_paths],
            asset_usage_matrix=[
                {
                    "slide_index": index,
                    "asset_path": str(path),
                    "role": "component-sheet",
                    "purpose": "仅作为组件参考，不应作为整张栅格图塞入页面。",
                }
                for index, path in enumerate(asset_paths, start=1)
            ],
            slides=[
                {
                    "layout": f"codex-grid-layout-library#slide-{index:02d}",
                    "title": f"页面 {index}",
                    "body": "用原生 PPT 组件承接视觉语言，而不是粘贴组件图。",
                    "items": ["原生组件", "视觉一致", "信息清晰"],
                }
                for index in range(1, 9)
            ],
        )
    finally:
        set_current_workspace_dir(None)
        set_current_session_id("")

    assert not output_path.exists()
    text = _text_from_response(response)
    assert "visual asset QA failed" in text
    assert "component-sheet" in text
    assert "native PPT components" in text


@pytest.mark.asyncio
async def test_final_delivery_rejects_multiple_stuffed_images_on_one_slide(
    tmp_path,
    monkeypatch,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    session_id = "session-too-many-direct-images"
    session_media_dir = workspace_dir / "sessions_data" / session_id / "media" / "imagegen"
    session_media_dir.mkdir(parents=True)
    asset_paths = []
    for index in range(1, 4):
        asset_path = session_media_dir / f"imagegen_{index}.png"
        _sample_png(asset_path)
        asset_paths.append(asset_path)
    set_current_workspace_dir(workspace_dir)
    set_current_session_id(session_id)

    def fake_render_preview(pptx_path, preview_dir=None):
        preview_root = Path(preview_dir or Path(pptx_path).with_suffix("")) / "render_qa"
        preview_root.mkdir(parents=True, exist_ok=True)
        slide_images = []
        for index in range(1, 9):
            slide_path = preview_root / f"slide-{index}.png"
            _sample_png(slide_path)
            slide_images.append(str(slide_path))
        contact_sheet = preview_root / "contact_sheet.png"
        Image.new("RGB", (960, 540), (255, 255, 255)).save(contact_sheet)
        return {
            "status": "ok",
            "engine": "libreoffice+pdftoppm",
            "preview_dir": str(preview_root),
            "contact_sheet": str(contact_sheet),
            "slide_images": slide_images,
            "slide_count": 8,
        }

    monkeypatch.setattr(
        builder_module,
        "_render_pptx_preview",
        fake_render_preview,
        raising=False,
    )

    output_path = workspace_dir / "stuffed_images.pptx"

    try:
        response = await builder_module.presentation_builder(
            output_path=str(output_path),
            delivery_mode="final",
            requires_visual_assets=True,
            theme={
                "canvas": "#FFFFFF",
                "ink": "#111827",
                "body": "#374151",
                "muted": "#6B7280",
                "panel": "#FFF7ED",
                "panel_alt": "#EDE9FE",
                "rule": "#FDBA74",
                "accent": "#F97316",
                "accent_soft": "#FDE68A",
                "font_family": "Microsoft YaHei",
            },
            required_image_assets=[str(path) for path in asset_paths],
            asset_usage_matrix=[
                {
                    "slide_index": 1,
                    "asset_path": str(path),
                    "role": role,
                    "purpose": "作为该页唯一主视觉或明确辅助视觉，不能堆叠装饰。",
                }
                for path, role in zip(asset_paths, ["hero", "wide", "thumbnail"])
            ],
            slides=[
                {
                    "layout": f"codex-grid-layout-library#slide-{index:02d}",
                    "title": f"页面 {index}",
                    "body": "每页只放必要的直接栅格资产。",
                    "items": ["克制使用", "原生重绘", "信息清晰"],
                }
                for index in range(1, 9)
            ],
        )
    finally:
        set_current_workspace_dir(None)
        set_current_session_id("")

    assert not output_path.exists()
    text = _text_from_response(response)
    assert "visual asset QA failed" in text
    assert "too many direct raster images on slide 1" in text


@pytest.mark.asyncio
async def test_presentation_builder_final_delivery_rejects_qa_warnings(
    tmp_path,
    monkeypatch,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    def fake_render_preview(pptx_path, preview_dir=None):
        preview_root = Path(preview_dir or Path(pptx_path).with_suffix("")) / "render_qa"
        preview_root.mkdir(parents=True, exist_ok=True)
        slide_one = preview_root / "slide-1.png"
        contact_sheet = preview_root / "contact_sheet.png"
        _sample_png(slide_one)
        Image.new("RGB", (960, 540), (255, 255, 255)).save(contact_sheet)
        return {
            "status": "ok",
            "engine": "libreoffice+pdftoppm",
            "preview_dir": str(preview_root),
            "contact_sheet": str(contact_sheet),
            "slide_images": [str(slide_one)],
            "slide_count": 1,
        }

    monkeypatch.setattr(
        builder_module,
        "_render_pptx_preview",
        fake_render_preview,
        raising=False,
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "weak_final.pptx"),
        delivery_mode="final",
        slides=[{"layout": "section"}],
    )

    assert not (tmp_path / "weak_final.pptx").exists()
    assert _file_names_from_response(response) == []
    text = _text_from_response(response)
    assert "visual QA failed" in text
    assert "visually weak slide" in text


@pytest.mark.asyncio
async def test_presentation_builder_visual_delivery_requires_mapped_assets(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "visual_without_assets.pptx"),
        delivery_mode="draft",
        requires_visual_assets=True,
        slides=[
            {"layout": "cards", "title": "视觉方案", "items": ["A", "B", "C"]},
        ],
    )

    assert not (tmp_path / "visual_without_assets.pptx").exists()
    text = _text_from_response(response)
    assert "visual asset QA failed" in text


@pytest.mark.asyncio
async def test_final_delivery_auto_rejects_unmapped_session_imagegen_assets(
    tmp_path,
    monkeypatch,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    session_id = "session-visual"
    session_media_dir = workspace_dir / "sessions_data" / session_id / "media" / "imagegen"
    session_media_dir.mkdir(parents=True)
    _sample_png(session_media_dir / "imagegen_1.png")
    set_current_workspace_dir(workspace_dir)
    set_current_session_id(session_id)

    def fake_render_preview(pptx_path, preview_dir=None):
        preview_root = Path(preview_dir or Path(pptx_path).with_suffix("")) / "render_qa"
        preview_root.mkdir(parents=True, exist_ok=True)
        slide_one = preview_root / "slide-1.png"
        contact_sheet = preview_root / "contact_sheet.png"
        _sample_png(slide_one)
        Image.new("RGB", (960, 540), (255, 255, 255)).save(contact_sheet)
        return {
            "status": "ok",
            "engine": "libreoffice+pdftoppm",
            "preview_dir": str(preview_root),
            "contact_sheet": str(contact_sheet),
            "slide_images": [str(slide_one)],
            "slide_count": 1,
        }

    monkeypatch.setattr(
        builder_module,
        "_render_pptx_preview",
        fake_render_preview,
        raising=False,
    )

    try:
        response = await builder_module.presentation_builder(
            output_path=str(workspace_dir / "unmapped_visual_final.pptx"),
            delivery_mode="final",
            slides=[
                {"layout": "cards", "title": "视觉增强版", "items": ["A", "B", "C"]},
            ],
        )
    finally:
        set_current_workspace_dir(None)
        set_current_session_id("")

    assert not (workspace_dir / "unmapped_visual_final.pptx").exists()
    assert _file_names_from_response(response) == []
    text = _text_from_response(response)
    assert "visual asset QA failed" in text
    assert "current session has 1 generated image asset" in text


@pytest.mark.asyncio
async def test_final_delivery_rejects_explicit_visual_asset_bypass(
    tmp_path,
    monkeypatch,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    session_id = "session-visual-bypass"
    session_media_dir = workspace_dir / "sessions_data" / session_id / "media" / "imagegen"
    session_media_dir.mkdir(parents=True)
    _sample_png(session_media_dir / "imagegen_1.png")
    set_current_workspace_dir(workspace_dir)
    set_current_session_id(session_id)

    def fake_render_preview(pptx_path, preview_dir=None):
        preview_root = Path(preview_dir or Path(pptx_path).with_suffix("")) / "render_qa"
        preview_root.mkdir(parents=True, exist_ok=True)
        slide_one = preview_root / "slide-1.png"
        contact_sheet = preview_root / "contact_sheet.png"
        _sample_png(slide_one)
        Image.new("RGB", (960, 540), (255, 255, 255)).save(contact_sheet)
        return {
            "status": "ok",
            "engine": "libreoffice+pdftoppm",
            "preview_dir": str(preview_root),
            "contact_sheet": str(contact_sheet),
            "slide_images": [str(slide_one)],
            "slide_count": 1,
        }

    monkeypatch.setattr(
        builder_module,
        "_render_pptx_preview",
        fake_render_preview,
        raising=False,
    )

    output_path = workspace_dir / "visual_bypass_final.pptx"
    expected_session_output = (
        workspace_dir
        / "sessions_data"
        / session_id
        / "artifacts"
        / "presentation"
        / output_path.name
    )

    try:
        response = await builder_module.presentation_builder(
            output_path=str(output_path),
            delivery_mode="final",
            requires_visual_assets=False,
            slides=[
                {
                    "layout": "codex-grid-layout-library#slide-01",
                    "title": "视觉增强版",
                    "items": ["A", "B", "C"],
                },
            ],
        )
    finally:
        set_current_workspace_dir(None)
        set_current_session_id("")

    assert not output_path.exists()
    assert not expected_session_output.exists()
    text = _text_from_response(response)
    assert "visual asset QA failed" in text
    assert "requires_visual_assets=false" in text


@pytest.mark.asyncio
async def test_auto_delivery_rejects_unmapped_session_imagegen_assets_outside_workspace(
    tmp_path,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    session_id = "session-download-output"
    session_media_dir = workspace_dir / "sessions_data" / session_id / "media" / "imagegen"
    session_media_dir.mkdir(parents=True)
    _sample_png(session_media_dir / "imagegen_1.png")
    set_current_workspace_dir(workspace_dir)
    set_current_session_id(session_id)

    try:
        response = await builder_module.presentation_builder(
            output_path=str(tmp_path / "Downloads" / "client_deck.pptx"),
            delivery_mode="auto",
            slides=[
                {"layout": "cards", "title": "视觉增强版", "items": ["A", "B", "C"]},
            ],
        )
    finally:
        set_current_workspace_dir(None)
        set_current_session_id("")

    assert not (tmp_path / "Downloads" / "client_deck.pptx").exists()
    text = _text_from_response(response)
    assert "visual asset QA failed" in text
    assert "current session has 1 generated image asset" in text


@pytest.mark.asyncio
async def test_workspace_root_delivery_rejects_draft_bypass(
    tmp_path,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    set_current_workspace_dir(workspace_dir)

    try:
        response = await builder_module.presentation_builder(
            output_path=str(workspace_dir / "client_delivery.pptx"),
            delivery_mode="draft",
            slides=[
                {"layout": "content", "title": "客户交付"},
            ],
        )
    finally:
        set_current_workspace_dir(None)

    assert not (workspace_dir / "client_delivery.pptx").exists()
    text = _text_from_response(response)
    assert "delivery_mode=draft is blocked" in text
    assert "workspace-root deliverable" in text


@pytest.mark.asyncio
async def test_session_root_delivery_rejects_draft_bypass(
    tmp_path,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    session_id = "session-deliverable"
    session_dir = workspace_dir / "sessions_data" / session_id
    session_dir.mkdir(parents=True)
    set_current_workspace_dir(workspace_dir)
    set_current_session_id(session_id)

    try:
        response = await builder_module.presentation_builder(
            output_path=str(session_dir / "client_delivery.pptx"),
            delivery_mode="draft",
            slides=[
                {"layout": "content", "title": "客户交付"},
            ],
        )
    finally:
        set_current_workspace_dir(None)
        set_current_session_id("")

    assert not (session_dir / "client_delivery.pptx").exists()
    text = _text_from_response(response)
    assert "delivery_mode=draft is blocked" in text
    assert "session deliverable" in text


@pytest.mark.asyncio
async def test_draft_subdirectory_output_is_internal_preview_only(
    tmp_path,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    set_current_workspace_dir(workspace_dir)

    try:
        response = await builder_module.presentation_builder(
            output_path=str(workspace_dir / "draft" / "client_delivery_draft.pptx"),
            delivery_mode="draft",
            slides=[
                {
                    "layout": "cards",
                    "title": "客户交付草稿",
                    "items": ["诊断", "试点", "运营"],
                },
            ],
        )
    finally:
        set_current_workspace_dir(None)

    assert (workspace_dir / "draft" / "client_delivery_draft.pptx").exists()
    assert _file_names_from_response(response) == []
    text = _text_from_response(response)
    assert "Generated internal draft preview" in text
    assert "internal_preview=true" in text
    assert "not returned as a user deliverable" in text
    assert "Next required action: do not stop here" in text
    assert "Built editable PPTX" not in text


@pytest.mark.asyncio
async def test_prototype_delivery_is_a_real_pause_checkpoint(tmp_path, monkeypatch):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    set_current_workspace_dir(workspace_dir)

    def fake_render_preview(pptx_path, preview_dir=None):
        preview_root = Path(preview_dir or Path(pptx_path).with_suffix("")) / "render_qa"
        preview_root.mkdir(parents=True, exist_ok=True)
        slide_image = preview_root / "slide-1.png"
        _sample_png(slide_image)
        contact_sheet = preview_root / "contact_sheet.png"
        _sample_png(contact_sheet)
        return {
            "status": "ok",
            "engine": "libreoffice+pdftoppm",
            "preview_dir": str(preview_root),
            "contact_sheet": str(contact_sheet),
            "pdf_path": "",
            "slide_images": [str(slide_image)],
            "slide_count": 1,
        }

    monkeypatch.setattr(
        builder_module,
        "_render_pptx_preview",
        fake_render_preview,
        raising=False,
    )

    try:
        response = await builder_module.presentation_builder(
            output_path=str(workspace_dir / "prototypes" / "visual-checkpoint.pptx"),
            delivery_mode="prototype",
            expected_slide_count=1,
            slides=[
                {
                    "layout": "section",
                    "title": "视觉小样",
                    "subtitle": "等待用户确认",
                },
            ],
        )
    finally:
        set_current_workspace_dir(None)

    output_path = workspace_dir / "prototypes" / "visual-checkpoint.pptx"
    assert output_path.exists(), _text_from_response(response)
    assert output_path.with_suffix(".presentation.compose.json").exists()
    assert _file_names_from_response(response) == []
    text = _text_from_response(response)
    assert "Generated rendered prototype checkpoint" in text
    assert "delivery_mode=prototype" in text
    assert "wait for explicit approval" in text
    assert "Do not generate the final deck in this turn" in text
    assert "do not stop here" not in text


@pytest.mark.asyncio
async def test_workspace_root_final_auto_assigns_codex_grid_templates(
    tmp_path,
    monkeypatch,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    set_current_workspace_dir(workspace_dir)

    def fake_render_preview(pptx_path, preview_dir=None):
        preview_root = Path(preview_dir or Path(pptx_path).with_suffix("")) / "render_qa"
        preview_root.mkdir(parents=True, exist_ok=True)
        work_dir = preview_root / "_work"
        work_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = work_dir / f"{Path(pptx_path).stem}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n% fake final delivery pdf\n")
        slide_images = []
        for index in range(1, 5):
            slide_image = preview_root / f"slide-{index}.png"
            _sample_png(slide_image)
            slide_images.append(str(slide_image))
        contact_sheet = preview_root / "contact_sheet.png"
        Image.new("RGB", (960, 540), (255, 255, 255)).save(contact_sheet)
        return {
            "status": "ok",
            "engine": "libreoffice+pdftoppm",
            "preview_dir": str(preview_root),
            "contact_sheet": str(contact_sheet),
            "pdf_path": str(pdf_path),
            "slide_images": slide_images,
            "slide_count": 4,
        }

    monkeypatch.setattr(
        builder_module,
        "_render_pptx_preview",
        fake_render_preview,
        raising=False,
    )

    try:
        response = await builder_module.presentation_builder(
            output_path=str(workspace_dir / "client_delivery.pptx"),
            delivery_mode="final",
            slides=[
                {
                    "layout": "cover",
                    "title": "客户交付",
                    "subtitle": "制造业 AI 落地共建服务",
                },
                {
                    "layout": "content",
                    "title": "核心判断",
                    "body": "将场景诊断、试点共建和持续运营连成可交付闭环。",
                    "bullets": ["场景优先", "低风险试点", "运营复盘"],
                },
                {
                    "layout": "process",
                    "title": "落地流程",
                    "steps": ["诊断", "试点", "推广"],
                },
                {
                    "layout": "metrics",
                    "title": "交付指标",
                    "metrics": [
                        {"label": "周期", "value": "4周"},
                        {"label": "场景", "value": "3个"},
                    ],
                },
            ],
        )
    finally:
        set_current_workspace_dir(None)

    output_path = workspace_dir / "client_delivery.pptx"
    assert output_path.exists(), _text_from_response(response)
    usage = builder_module.inspect_pptx_media_usage(output_path)
    assert usage["qa"]["template_variety"] >= 4
    assert usage["qa"]["templates"][0] == "codex-grid-layout-library#slide-76"
    assert "codex-grid-layout-library#slide-80" in usage["qa"]["templates"]
    assert "codex-grid-layout-library#slide-01" in usage["qa"]["templates"]
    assert "codex-grid-layout-library#slide-51" in usage["qa"]["templates"]


@pytest.mark.asyncio
async def test_workspace_root_final_rejects_zero_codex_grid_templates(
    tmp_path,
    monkeypatch,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    set_current_workspace_dir(workspace_dir)

    def fake_render_preview(pptx_path, preview_dir=None):
        preview_root = Path(preview_dir or Path(pptx_path).with_suffix("")) / "render_qa"
        preview_root.mkdir(parents=True, exist_ok=True)
        slide_one = preview_root / "slide-1.png"
        slide_two = preview_root / "slide-2.png"
        contact_sheet = preview_root / "contact_sheet.png"
        _sample_png(slide_one)
        _sample_png(slide_two)
        Image.new("RGB", (960, 540), (255, 255, 255)).save(contact_sheet)
        return {
            "status": "ok",
            "engine": "libreoffice+pdftoppm",
            "preview_dir": str(preview_root),
            "contact_sheet": str(contact_sheet),
            "slide_images": [str(slide_one), str(slide_two)],
            "slide_count": 2,
        }

    monkeypatch.setattr(
        builder_module,
        "_render_pptx_preview",
        fake_render_preview,
        raising=False,
    )

    try:
        response = await builder_module.presentation_builder(
            output_path=str(workspace_dir / "freeform_delivery.pptx"),
            delivery_mode="final",
            slides=[
                {"layout": "freeform", "title": "服务矩阵", "items": ["A", "B", "C"]},
                {"layout": "freeform", "title": "资源配置", "items": ["顾问", "平台", "运营"]},
            ],
        )
    finally:
        set_current_workspace_dir(None)

    assert not (workspace_dir / "freeform_delivery.pptx").exists()
    text = _text_from_response(response)
    assert "Codex Grid layout QA failed" in text
    assert "80-layout registry" in text


@pytest.mark.asyncio
async def test_presentation_builder_auto_routes_roadmap_bullets_to_visual_layouts(
    tmp_path,
    monkeypatch,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    def fake_render_preview(pptx_path, preview_dir=None):
        preview_root = Path(preview_dir or Path(pptx_path).with_suffix("")) / "render_qa"
        preview_root.mkdir(parents=True, exist_ok=True)
        slide_one = preview_root / "slide-1.png"
        slide_two = preview_root / "slide-2.png"
        slide_three = preview_root / "slide-3.png"
        contact_sheet = preview_root / "contact_sheet.png"
        _sample_png(slide_one)
        _sample_png(slide_two)
        _sample_png(slide_three)
        Image.new("RGB", (960, 540), (255, 255, 255)).save(contact_sheet)
        return {
            "status": "ok",
            "engine": "libreoffice+pdftoppm",
            "preview_dir": str(preview_root),
            "contact_sheet": str(contact_sheet),
            "slide_images": [str(slide_one), str(slide_two), str(slide_three)],
            "slide_count": 3,
        }

    monkeypatch.setattr(
        builder_module,
        "_render_pptx_preview",
        fake_render_preview,
        raising=False,
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "roadmap_auto.pptx"),
        delivery_mode="auto",
        slides=[
            {
                "title": "AI转型实施路线总览",
                "bullets": [
                    "Phase 1：认知对齐阶段（第1-2周）",
                    "Phase 2：战略诊断阶段（第3-4周）",
                    "Phase 3：平台部署阶段（第5-6周）",
                    "Phase 4：业务落地阶段（第7-12周）",
                    "Phase 5：优化迭代阶段（第13-24周）",
                ],
            },
            {"title": "关键里程碑与验收标准"},
            {
                "title": "资源投入与团队配置",
                "bullets": [
                    "深兆左智团队：FDE驻场专家 + 战略咨询顾问 + 技术支持工程师",
                    "企业方团队：项目发起人 + 业务负责人 + IT支持人员 + 业务骨干",
                    "时间投入：核心团队成员每周投入8-16小时",
                    "预算规划：根据企业规模和AI化复杂度定制方案",
                ],
            },
        ],
    )

    output_path = tmp_path / "roadmap_auto.pptx"
    assert output_path.exists(), _text_from_response(response)
    usage = builder_module.inspect_pptx_media_usage(output_path)
    assert usage["qa"]["warnings"] == []
    assert usage["qa"]["weak_slide_count"] == 0
    assert usage["qa"]["layouts"] == ["process", "section", "cards"]
    assert usage["qa"]["templates"][0].startswith("codex-grid-layout-library#slide-")
    assert usage["qa"]["templates"][1] == ""
    assert usage["qa"]["templates"][2] == ""
    roadmap_xml = _slide_xml(output_path, 1)
    resource_xml = _slide_xml(output_path, 3)
    assert ">Phase 1<" in roadmap_xml
    assert ">认知对齐阶段（第1-2周）<" in roadmap_xml
    assert ">Phase 1：认知对齐阶段（第1-2周）<" not in roadmap_xml
    assert ">深兆左智团队<" in resource_xml
    assert ">FDE驻场专家 + 战略咨询顾问 + 技术支持工程师<" in resource_xml
    assert ">深兆左智团队：FDE驻场专家 + 战略咨询顾问 + 技术支持工程师<" not in resource_xml
    assert "render_qa=ok" in _text_from_response(response)


@pytest.mark.asyncio
async def test_presentation_builder_turns_list_body_into_bullets(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "list_body.pptx"),
        delivery_mode="draft",
        slides=[
            {
                "layout": "content",
                "title": "AI转型的商业现实",
                "body": [
                    "95%的企业AI转型停留在工具采购层面",
                    "核心问题：缺乏数据驱动的AI落地方法论",
                ],
            },
        ],
    )

    output_path = tmp_path / "list_body.pptx"
    assert output_path.exists()
    slide_xml = _slide_xml(output_path, 1)
    assert "95%的企业AI转型停留在工具采购层面" in slide_xml
    assert "核心问题：缺乏数据驱动的AI落地方法论" in slide_xml
    assert "['95%" not in slide_xml
    assert "qa_warnings=0" in _text_from_response(response)


def test_render_pptx_preview_requires_real_renderer(tmp_path, monkeypatch):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    pptx_path = tmp_path / "deck.pptx"
    pptx_path.write_bytes(b"not a real pptx")

    monkeypatch.setattr(builder_module.shutil, "which", lambda _name: None)

    with pytest.raises(ValueError, match="soffice|libreoffice|pdftoppm"):
        builder_module._render_pptx_preview(pptx_path)


@pytest.mark.asyncio
async def test_presentation_builder_supports_extended_layout_families(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "extended_layouts.pptx"),
        delivery_mode="draft",
        strict_qa=True,
        slides=[
            {
                "layout": "agenda",
                "title": "目录",
                "items": ["业务挑战", "共建路径", "交付计划"],
            },
            {
                "layout": "comparison",
                "title": "方案对比",
                "columns": [
                    {"title": "传统外包", "body": "一次性交付\n知识难沉淀"},
                    {"title": "共建服务", "body": "边做边沉淀\n组件可复用"},
                ],
            },
            {
                "layout": "roadmap",
                "title": "落地路线",
                "steps": [
                    {"title": "第 1 周", "body": "场景诊断"},
                    {"title": "第 2 周", "body": "试点搭建"},
                    {"title": "第 4 周", "body": "上线复盘"},
                ],
            },
            {
                "layout": "quote",
                "title": "核心判断",
                "body": "企业 AI 落地不是买工具，而是把组织流程重构成可持续迭代的能力。",
                "footer": "深兆左智",
            },
            {
                "layout": "architecture",
                "title": "Agent 中台架构",
                "items": [
                    {"title": "入口", "body": "任务/知识/审批"},
                    {"title": "编排", "body": "Agent 工作流"},
                    {"title": "资产", "body": "组件与数据"},
                    {"title": "治理", "body": "权限与审计"},
                ],
            },
        ],
    )

    output_path = tmp_path / "extended_layouts.pptx"
    assert output_path.exists()
    usage = builder_module.inspect_pptx_media_usage(output_path)
    assert usage["qa"]["layout_variety"] == 5
    assert usage["qa"]["weak_slide_count"] == 0
    assert usage["qa"]["warnings"] == []
    assert 'name="Agenda Item 1"' in _slide_xml(output_path, 1)
    assert 'name="Comparison Panel 2"' in _slide_xml(output_path, 2)
    assert 'name="Roadmap Step 3"' in _slide_xml(output_path, 3)
    assert 'name="Quote Mark"' in _slide_xml(output_path, 4)
    assert 'name="Architecture Node 4"' in _slide_xml(output_path, 5)
    assert "layout_variety=5" in _text_from_response(response)


@pytest.mark.asyncio
async def test_presentation_builder_uses_template_audit_and_theme_seed(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    template_path = tmp_path / "template_seed.pptx"
    await builder_module.presentation_builder(
        output_path=str(template_path),
        delivery_mode="draft",
        theme={"mode": "dark", "accent": "#F59E0B"},
        slides=[
            {
                "layout": "section",
                "title": "模板页",
                "subtitle": "用于继承主题",
            },
        ],
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "from_template.pptx"),
        delivery_mode="draft",
        template_path=str(template_path),
        slides=[
            {
                "layout": "cards",
                "title": "复用模板主题",
                "items": [{"title": "保留风格", "body": "继承模板颜色"}],
            },
        ],
    )

    output_path = tmp_path / "from_template.pptx"
    assert output_path.exists()
    assert 'val="0F172A"' in _slide_xml(output_path, 1)
    text = _text_from_response(response)
    assert "template_source_slide_count=1" in text
    assert "template_media_count=0" in text


@pytest.mark.asyncio
async def test_presentation_builder_clones_template_frame_map_order(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    first_asset = tmp_path / "first.png"
    second_asset = tmp_path / "second.png"
    _sample_png(first_asset)
    _sample_png(second_asset)
    template_path = tmp_path / "source_template.pptx"

    await builder_module.presentation_builder(
        output_path=str(template_path),
        delivery_mode="draft",
        slides=[
            {
                "layout": "content",
                "title": "源页一",
                "body": "第一个模板页面",
                "images": [{"asset_path": str(first_asset)}],
            },
            {
                "layout": "content",
                "title": "源页二",
                "body": "第二个模板页面",
                "images": [{"asset_path": str(second_asset)}],
            },
        ],
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "starter.pptx"),
        delivery_mode="draft",
        template_path=str(template_path),
        template_frame_map=[
            {"outputSlide": 1, "sourceSlide": 2, "narrativeRole": "opening"},
            {"outputSlide": 2, "sourceSlide": 1, "narrativeRole": "support"},
        ],
        slides=[{}, {}],
        strict_qa=True,
    )

    output_path = tmp_path / "starter.pptx"
    assert output_path.exists()
    usage = builder_module.inspect_pptx_media_usage(output_path)
    assert usage["slide_count"] == 2
    assert usage["media_count"] == 2
    assert "源页二" in _slide_xml(output_path, 1)
    assert "源页一" in _slide_xml(output_path, 2)
    text = _text_from_response(response)
    assert "template_mode=clone_edit" in text
    assert "template_frame_map=2" in text


@pytest.mark.asyncio
async def test_presentation_builder_template_clone_rewrites_text_and_replaces_image(
    tmp_path,
):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    original_asset = tmp_path / "original.png"
    replacement_asset = tmp_path / "replacement.png"
    _sample_png(original_asset)
    Image.new("RGB", (1280, 720), (204, 60, 50)).save(replacement_asset)
    replacement_hash = hashlib.sha256(replacement_asset.read_bytes()).hexdigest()
    template_path = tmp_path / "editable_template.pptx"

    await builder_module.presentation_builder(
        output_path=str(template_path),
        delivery_mode="draft",
        slides=[
            {
                "layout": "content",
                "title": "旧标题",
                "body": "旧正文",
                "images": [{"asset_path": str(original_asset)}],
            },
        ],
    )

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "edited_template.pptx"),
        delivery_mode="draft",
        template_path=str(template_path),
        template_frame_map=[
            {
                "outputSlide": 1,
                "sourceSlide": 1,
                "editTargets": [
                    {
                        "action": "rewrite",
                        "matchText": "旧标题",
                        "text": "新标题",
                    },
                    {
                        "action": "rewrite",
                        "matchText": "旧正文",
                        "text": "新正文",
                    },
                    {
                        "action": "replace-image",
                        "shapeName": "Image 6",
                        "asset_path": str(replacement_asset),
                    },
                ],
            },
        ],
        required_image_assets=[str(replacement_asset)],
        strict_qa=True,
    )

    output_path = tmp_path / "edited_template.pptx"
    assert output_path.exists()
    slide_xml = _slide_xml(output_path, 1)
    assert "新标题" in slide_xml
    assert "新正文" in slide_xml
    assert "旧标题" not in slide_xml
    assert "旧正文" not in slide_xml
    assert replacement_hash in _media_hashes(output_path)
    text = _text_from_response(response)
    assert "template_mode=clone_edit" in text


@pytest.mark.asyncio
async def test_presentation_builder_strict_qa_rejects_overlapping_images(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _sample_png(first)
    _sample_png(second)

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "overlap.pptx"),
        delivery_mode="draft",
        slides=[
            {
                "layout": "content",
                "title": "重叠图片",
                "images": [
                    {"asset_path": str(first), "x": 1, "y": 2, "w": 4, "h": 3},
                    {"asset_path": str(second), "x": 1.5, "y": 2.2, "w": 4, "h": 3},
                ],
            },
        ],
        strict_qa=True,
    )

    assert not (tmp_path / "overlap.pptx").exists()
    assert "overlap" in _text_from_response(response)


@pytest.mark.asyncio
async def test_presentation_builder_keeps_non_strict_overlap_as_warning(tmp_path):
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _sample_png(first)
    _sample_png(second)

    response = await builder_module.presentation_builder(
        output_path=str(tmp_path / "overlap_warning.pptx"),
        delivery_mode="draft",
        slides=[
            {
                "layout": "content",
                "title": "重叠图片",
                "images": [
                    {"asset_path": str(first), "x": 1, "y": 2, "w": 4, "h": 3},
                    {"asset_path": str(second), "x": 1.5, "y": 2.2, "w": 4, "h": 3},
                ],
            },
        ],
    )

    output_path = tmp_path / "overlap_warning.pptx"
    assert output_path.exists()
    assert _media_count(output_path) == 2
    usage = builder_module.inspect_pptx_media_usage(output_path)
    assert usage["qa"]["overlap_count"] == 1
    assert "qa_warnings=1" in _text_from_response(response)


def test_presentation_builder_qa_detects_overlapping_text_boxes():
    builder_module = importlib.import_module(
        "qwenpaw.agents.tools.presentation_builder",
    )

    slide_xml = """
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld name="layout:content">
    <p:spTree>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="1" name="First Text"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="914400" y="914400"/><a:ext cx="2743200" cy="914400"/></a:xfrm>
        </p:spPr>
        <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>First</a:t></a:r></a:p></p:txBody>
      </p:sp>
      <p:sp>
        <p:nvSpPr><p:cNvPr id="2" name="Second Text"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
        <p:spPr>
          <a:xfrm><a:off x="1097280" y="1005840"/><a:ext cx="2743200" cy="914400"/></a:xfrm>
        </p:spPr>
        <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Second</a:t></a:r></a:p></p:txBody>
      </p:sp>
    </p:spTree>
  </p:cSld>
</p:sld>
"""

    qa = builder_module._qa_for_slide(slide_xml)
    assert qa["overlap_count"] == 1
    assert "First Text overlaps Second Text" in qa["overlaps"][0]
