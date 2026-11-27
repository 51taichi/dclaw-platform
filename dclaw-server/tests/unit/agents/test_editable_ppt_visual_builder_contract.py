from __future__ import annotations

from pathlib import Path


SKILL_DIR = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "qwenpaw"
    / "agents"
    / "skills"
    / "editable-ppt-visual-builder-zh"
)


def _read_skill_file(relative_path: str) -> str:
    return (SKILL_DIR / relative_path).read_text(encoding="utf-8")


def test_editable_ppt_skill_markets_pptx_pdf_delivery() -> None:
    skill_md = _read_skill_file("SKILL.md")

    assert 'builtin_skill_version: "2.1"' in skill_md
    assert "PPTX/PDF" in skill_md
    assert "presentation_builder" in skill_md
    assert "可编辑 PPTX/PDF" in skill_md
    assert "PPTX/PDF 是面向用户的任务主制品" in skill_md


def test_editable_ppt_skill_requires_final_builder_delivery_contract() -> None:
    combined = "\n".join(
        [
            _read_skill_file("SKILL.md"),
            _read_skill_file("references/workflow.md"),
        ],
    )

    required_contract_terms = [
        'delivery_mode="final"',
        "requires_visual_assets=true",
        "export_pdf=true",
        "include_compose_manifest=true",
        "compose_manifest=",
        "*.presentation.compose.json",
        "内部来源账本",
        "PPTX/PDF 是面向用户的任务主制品",
        'route_mode="custom_compose"',
        "compose_spec",
        "visual_translation_contract",
        "expected_slide_count",
        "expected_content",
        "semantic_group_counts",
        'delivery_mode="prototype"',
        "Do not generate the final deck in the same turn",
    ]
    for term in required_contract_terms:
        assert term in combined


def test_editable_ppt_skill_default_prompt_mentions_final_artifacts() -> None:
    openai_agent = _read_skill_file("agents/openai.yaml")

    assert "PPTX/PDF" in openai_agent
    assert "presentation_builder" in openai_agent
    assert "compose" in openai_agent
    assert "custom_compose" in openai_agent
    assert "不得回退到通用固定布局" in openai_agent
    assert "expected_slide_count" in openai_agent
    assert "小样返回后展示渲染图并停止等待用户确认" in openai_agent


def test_editable_ppt_skill_requires_structured_visual_prompt_provenance() -> None:
    combined = "\n".join(
        [
            _read_skill_file("SKILL.md"),
            _read_skill_file("references/workflow.md"),
            _read_skill_file("references/slide-schema.md"),
        ],
    )

    required_contract_terms = [
        "presentation_context",
        'stage=\"visual_scheme\"',
        'stage=\"visual_asset\"',
        "Use case: productivity-visual",
        "*.imagegen.json",
        "direction_name",
        "visual_temperature",
        "dominant_visual_anchor",
        "reserved_text_area",
        "unscored hybrid/fusion",
    ]
    for term in required_contract_terms:
        assert term in combined
