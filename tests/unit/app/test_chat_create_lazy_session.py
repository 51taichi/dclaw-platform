# -*- coding: utf-8 -*-
"""Tests for lazy chat creation semantics."""
from __future__ import annotations

import pytest
from types import SimpleNamespace

from qwenpaw.app.runner import api as chat_api
from qwenpaw.app.runner.models import ChatSpec


class _FakeChatManager:
    def __init__(self):
        self.created: ChatSpec | None = None

    async def create_chat(self, spec: ChatSpec) -> ChatSpec:
        self.created = spec
        return spec


@pytest.mark.asyncio
async def test_create_chat_uses_generated_chat_id_as_missing_session_id():
    mgr = _FakeChatManager()
    request = SimpleNamespace(state=SimpleNamespace(user_id="default"))

    created = await chat_api.create_chat(
        request,
        ChatSpec(
            name="hello",
            session_id="",
            user_id="default",
            channel="console",
        ),
        mgr=mgr,
    )

    assert created.session_id == created.id
    assert mgr.created is created
