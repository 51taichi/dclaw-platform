"""Static contracts for DClaw's direct AgentScope 2 API usage."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
from pathlib import Path

from agentscope.message import DataBlock
from agentscope.tool import ToolChunk

from qwenpaw.agents.acp.tool_adapter import response_text


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION_ROOTS = (
    REPOSITORY_ROOT / "src",
    REPOSITORY_ROOT / "plugins",
)
REMOVED_AGENT_METHODS = {
    "disable_console_output",
    "set_console_output_enabled",
    "set_msg_queue_enabled",
}


def _production_python_files() -> list[Path]:
    return sorted(
        path
        for root in PRODUCTION_ROOTS
        for path in root.rglob("*.py")
        if "tests" not in path.parts
    )


def _agentscope_import(module: str) -> bool:
    return module == "agentscope" or module.startswith("agentscope.")


def test_direct_agentscope_symbols_and_call_keywords_match_installed_api():
    issues: list[str] = []

    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases: dict[str, tuple[str, object]] = {}

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if not node.module or not _agentscope_import(node.module):
                continue
            try:
                module = importlib.import_module(node.module)
            except Exception as exc:  # pragma: no cover - assertion detail
                issues.append(
                    f"{path}:{node.lineno}: cannot import {node.module}: {exc}",
                )
                continue

            for imported in node.names:
                if imported.name == "*":
                    continue
                qualified = f"{node.module}.{imported.name}"
                if not hasattr(module, imported.name):
                    issues.append(
                        f"{path}:{node.lineno}: missing AgentScope symbol "
                        f"{qualified}",
                    )
                    continue
                aliases[imported.asname or imported.name] = (
                    qualified,
                    getattr(module, imported.name),
                )

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name):
                continue
            imported = aliases.get(node.func.id)
            if imported is None:
                continue
            qualified, target = imported
            try:
                signature = inspect.signature(target)
            except (TypeError, ValueError):
                continue
            parameters = signature.parameters
            if any(
                item.kind is inspect.Parameter.VAR_KEYWORD
                for item in parameters.values()
            ):
                continue
            allowed = {
                name
                for name, item in parameters.items()
                if item.kind
                in {
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                }
            }
            for keyword in node.keywords:
                if keyword.arg is not None and keyword.arg not in allowed:
                    issues.append(
                        f"{path}:{node.lineno}: {qualified}{signature} "
                        f"does not accept {keyword.arg!r}",
                    )

    assert issues == []


def test_removed_agentscope_1_agent_methods_are_not_called():
    issues: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in REMOVED_AGENT_METHODS
            ):
                issues.append(
                    f"{path}:{node.lineno}: removed AgentScope 1 method "
                    f"{node.func.attr}()",
                )

    assert issues == []


def test_acp_stream_adapter_returns_agentscope2_tool_chunks():
    chunk = response_text("progress", is_last=False)

    assert isinstance(chunk, ToolChunk)
    assert chunk.is_last is False
    assert chunk.content[0].text == "progress"


def test_media_tool_plugins_load_with_agentscope2_data_blocks(tmp_path):
    plugin_files = (
        REPOSITORY_ROOT / "plugins/tool/gpt-image2/gpt_image2_tool.py",
        REPOSITORY_ROOT / "plugins/tool/qwen-image/qwen_image_tool.py",
        REPOSITORY_ROOT / "plugins/tool/wan27/wan27_tool.py",
    )

    for index, path in enumerate(plugin_files):
        spec = importlib.util.spec_from_file_location(
            f"_agentscope2_media_plugin_{index}",
            path,
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        factory = getattr(module, "VideoBlock", None) or getattr(
            module,
            "ImageBlock",
        )
        block = factory(
            source={"type": "url", "url": str(tmp_path / "asset.bin")},
        )

        assert isinstance(block, DataBlock)
        assert block.type == "data"
        assert block.source.type == "url"
