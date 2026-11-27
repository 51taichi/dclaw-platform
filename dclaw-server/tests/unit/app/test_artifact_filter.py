# -*- coding: utf-8 -*-
"""Tests for user-facing artifact filtering."""

from pathlib import Path

from qwenpaw.app.artifact_filter import (
    extract_user_task_files_from_text,
    filter_user_task_files,
    is_internal_task_file,
    strip_session_data_prefix,
)


def test_tool_results_are_not_user_artifacts() -> None:
    assert is_internal_task_file("tool_results/result.txt")
    assert filter_user_task_files(
        ["儿童节短剧_最好的礼物.md", "tool_results/result.txt"],
    ) == ["儿童节短剧_最好的礼物.md"]


def test_presentation_render_qa_files_are_not_user_artifacts() -> None:
    assert is_internal_task_file("deck_render_qa/contact_sheet.png")
    assert is_internal_task_file("deck_render_qa/slide-01.png")
    assert is_internal_task_file("deck_render_qa/_work/deck.pdf")
    assert filter_user_task_files(
        [
            "deck.pptx",
            "deck_render_qa/contact_sheet.png",
            "deck_render_qa/slide-01.png",
            "deck_render_qa/_work/deck.pdf",
        ],
    ) == ["deck.pptx"]


def test_presentation_draft_directory_is_not_user_artifact() -> None:
    assert is_internal_task_file("draft/深兆左智企业AI落地共建服务手册_草稿.pptx")
    assert filter_user_task_files(
        [
            "draft/深兆左智企业AI落地共建服务手册_草稿.pptx",
            "深兆左智企业AI落地共建服务手册.pdf",
            "深兆左智企业AI落地共建服务手册.pptx",
        ],
    ) == [
        "深兆左智企业AI落地共建服务手册.pdf",
        "深兆左智企业AI落地共建服务手册.pptx",
    ]


def test_presentation_compose_manifest_is_not_user_artifact() -> None:
    assert is_internal_task_file("deck.presentation.compose.json")
    assert filter_user_task_files(
        [
            "deck.pptx",
            "deck.presentation.compose.json",
            "客户可读配置.json",
        ],
    ) == ["deck.pptx", "客户可读配置.json"]


def test_primary_deliverables_hide_intermediate_imagegen_media() -> None:
    assert filter_user_task_files(
        [
            "media/imagegen/imagegen_123.png",
            "深兆左智企业AI落地共建服务手册_数据驱动版.pptx",
            "media/imagegen/imagegen_456.png",
        ],
    ) == ["深兆左智企业AI落地共建服务手册_数据驱动版.pptx"]


def test_imagegen_only_task_keeps_generated_images() -> None:
    assert filter_user_task_files(
        [
            "media/imagegen/imagegen_123.png",
            "media/imagegen/imagegen_456.png",
        ],
    ) == [
        "media/imagegen/imagegen_123.png",
        "media/imagegen/imagegen_456.png",
    ]


def test_aigc_studio_runtime_files_are_never_generic_task_artifacts() -> None:
    assert filter_user_task_files(
        [
            "aigc_studio/canvas-old/jobs/job-old/output.png",
            "aigc_studio/canvas-current/meta.json",
            "sessions_data/current/report.md",
        ],
    ) == ["sessions_data/current/report.md"]


def test_extracts_only_explicit_existing_user_artifacts_from_text(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "儿童节短剧_最好的礼物.md").write_text("# 最好的礼物", encoding="utf-8")
    (workspace / "snake-game.html").write_text("<html></html>", encoding="utf-8")
    (workspace / "BOOTSTRAP.md").write_text("internal", encoding="utf-8")

    text = (
        "Wrote 5696 bytes to "
        f"{workspace}/儿童节短剧_最好的礼物.md.\n"
        "剧本文件已保存为：`儿童节短剧_最好的礼物.md`\n"
        "BOOTSTRAP.md 是系统文件，snake-game.html 没有被本任务提及为产物。"
    )

    assert extract_user_task_files_from_text(text, workspace) == [
        "儿童节短剧_最好的礼物.md",
    ]


def test_bare_skill_md_instruction_is_not_a_task_artifact(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SKILL.md").write_text("---\nname: old-skill\n---\n", encoding="utf-8")

    text = (
        "你可以使用技能系统。说明里会提到 `SKILL.md`，"
        "但这个普通问答任务没有生成任何文件。"
    )

    assert extract_user_task_files_from_text(text, workspace) == []


def test_skill_md_is_artifact_only_when_explicitly_written(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "SKILL.md").write_text("---\nname: new-skill\n---\n", encoding="utf-8")

    text = "Wrote 17291 bytes to SKILL.md"

    assert extract_user_task_files_from_text(text, workspace) == ["SKILL.md"]


def test_extracts_media_deliverables_from_bare_final_filenames(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    media = workspace / "media"
    media.mkdir(parents=True)
    (media / "深兆左智企业AI落地共建服务手册.pptx").write_bytes(b"pptx")
    (media / "深兆左智企业AI落地共建服务手册.pdf").write_bytes(b"pdf")
    (media / "深兆左智企业AI落地共建服务手册.presentation.compose.json").write_text(
        "{}",
        encoding="utf-8",
    )
    render_dir = media / "深兆左智企业AI落地共建服务手册_render_qa"
    render_dir.mkdir()
    (render_dir / "contact_sheet.png").write_bytes(b"png")

    text = (
        "### 生成的文件\n"
        "1. 主文件：`深兆左智企业AI落地共建服务手册.pptx`\n"
        "2. PDF版本：`深兆左智企业AI落地共建服务手册.pdf`\n"
        "3. 来源清单：`深兆左智企业AI落地共建服务手册.presentation.compose.json`\n"
        "4. 渲染预览：`深兆左智企业AI落地共建服务手册_render_qa/contact_sheet.png`\n"
    )

    assert extract_user_task_files_from_text(text, workspace) == [
        "media/深兆左智企业AI落地共建服务手册.pptx",
        "media/深兆左智企业AI落地共建服务手册.pdf",
    ]


def test_strip_session_data_prefix_normalizes_session_artifacts() -> None:
    assert (
        strip_session_data_prefix(
            "sessions_data/1780137002067/穿越大唐短剧_剧本.md",
            "1780137002067",
        )
        == "穿越大唐短剧_剧本.md"
    )
    assert (
        strip_session_data_prefix(
            "sessions_data/other/穿越大唐短剧_剧本.md",
            "1780137002067",
        )
        == "sessions_data/other/穿越大唐短剧_剧本.md"
    )
