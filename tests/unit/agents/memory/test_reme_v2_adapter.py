"""ReMe 0.4 integration and legacy memory compatibility tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from agentscope.credential import OpenAICredential
from agentscope.model import OpenAIChatModel

from qwenpaw.agents.memory.reme_v2_adapter import ReMeV2Adapter


def _model():
    return OpenAIChatModel(
        credential=OpenAICredential(api_key="test-only"),
        model="gpt-4o-mini",
    )


@pytest.mark.asyncio
async def test_real_start_preserves_legacy_memory_search(tmp_path):
    memory_file = tmp_path / "MEMORY.md"
    memory_file.write_text("The project uses AgentScope 2.\n")
    daily = tmp_path / "memory"
    daily.mkdir()
    (daily / "2026-11-25.md").write_text("客户偏好中文回复。\n")
    adapter = ReMeV2Adapter(str(tmp_path), _model, {}, True)

    try:
        await adapter.start()
        result = await adapter.memory_search("AgentScope")
        assert "MEMORY.md:1" in result.content[0].text
        assert "AgentScope 2" in result.content[0].text

        daily_result = await adapter.memory_search("中文")
        assert "memory/2026-11-25.md:1" in daily_result.content[0].text
    finally:
        await adapter.close()

    assert memory_file.read_text() == "The project uses AgentScope 2.\n"


@pytest.mark.asyncio
async def test_failed_search_reports_backend_failure(tmp_path):
    adapter = ReMeV2Adapter(str(tmp_path), _model, {}, False)
    adapter._app = MagicMock(
        run_job=AsyncMock(return_value=MagicMock(success=False)),
    )
    adapter._started = True

    with pytest.raises(RuntimeError, match="memory search failed"):
        await adapter.memory_search("previous decision")


@pytest.mark.asyncio
async def test_failed_model_setup_does_not_mark_store_ready(tmp_path):
    def broken_model():
        raise ValueError("model unavailable")

    adapter = ReMeV2Adapter(str(tmp_path), broken_model, {}, False)
    with pytest.raises(ValueError, match="model unavailable"):
        await adapter.start()
    assert adapter._started is False
