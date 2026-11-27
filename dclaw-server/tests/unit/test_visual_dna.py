"""Tests for the model-neutral Visual DNA knowledge layer."""

from qwenpaw.aigc.visual_dna import (
    VisualDnaCompileRequest,
    compile_visual_dna,
    list_visual_dna_dimensions,
    list_visual_dna_elements,
)


def test_visual_dna_catalog_exposes_structured_dimensions_and_search():
    dimensions = list_visual_dna_dimensions()
    lighting = next(item for item in dimensions if item.id == "lighting")

    assert lighting.name == "光影"
    assert lighting.scope == "aesthetic_profile"
    assert lighting.element_count >= 3

    camera = next(item for item in dimensions if item.id == "camera")
    assert camera.scope == "shot"
    assert any(item.id == "art_direction" for item in dimensions)

    elements = list_visual_dna_elements(dimension="camera", query="85mm")

    assert [item.id for item in elements] == ["camera.85mm_portrait"]
    assert elements[0].definition
    assert elements[0].visual_effect
    assert elements[0].prompt_text


def test_visual_dna_compiler_groups_intent_and_collects_constraints():
    compiled = compile_visual_dna(
        VisualDnaCompileRequest(
            selections=[
                {"element_id": "lighting.golden_hour_rim", "weight": 0.9},
                {
                    "element_id": "camera.85mm_portrait",
                    "weight": 0.7,
                    "note": "半身人物",
                },
                {"element_id": "constraint.preserve_identity", "weight": 1},
            ],
            provider_id="openai",
            model_id="gpt-image-2",
            constraints=["不要裁切头部。"],
        ),
    )

    assert "【光影】" in compiled.prompt_appendix
    assert "黄金时刻轮廓光（强）" in compiled.prompt_appendix
    assert "【镜头】" in compiled.prompt_appendix
    assert "本次补充：半身人物" in compiled.prompt_appendix
    assert "【必须遵守的视觉约束】" in compiled.prompt_appendix
    assert "不要裁切头部。" in compiled.constraints
    assert any("保持人物面部结构" in item for item in compiled.constraints)
    assert compiled.warnings == []


def test_visual_dna_compiler_reports_unknown_and_conflicting_elements():
    compiled = compile_visual_dna(
        VisualDnaCompileRequest(
            selections=[
                {"element_id": "camera.85mm_portrait", "weight": 1},
                {"element_id": "camera.35mm_environmental", "weight": 1},
                {"element_id": "missing.element", "weight": 1},
            ],
        ),
    )

    assert len(compiled.elements) == 2
    assert any("存在冲突" in warning for warning in compiled.warnings)
    assert any("missing.element" in warning for warning in compiled.warnings)
