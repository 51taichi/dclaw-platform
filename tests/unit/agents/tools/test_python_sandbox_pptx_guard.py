# -*- coding: utf-8 -*-
from __future__ import annotations

import json

import pytest

from qwenpaw.agents.tools.python_sandbox import python_sandbox


def _response_payload(response) -> dict:
    text = "\n".join(
        block.text
        for block in response.content
        if block.type == "text"
    )
    return json.loads(text)


@pytest.mark.asyncio
async def test_python_sandbox_rejects_pptx_generation_attempts():
    response = await python_sandbox(
        code=(
            "from pptx import Presentation\n"
            "prs = Presentation()\n"
            "prs.save('regenerated.pptx')\n"
        ),
        description="重新生成 PPT 文件",
    )

    payload = _response_payload(response)

    assert payload["ok"] is False
    assert "presentation_builder" in payload["error"]
    assert "PPTX" in payload["error"]


@pytest.mark.asyncio
async def test_python_sandbox_still_allows_non_pptx_code():
    response = await python_sandbox(code="print(1 + 1)")

    payload = _response_payload(response)

    assert payload["ok"] is True
    assert payload["stdout"] == "2"
