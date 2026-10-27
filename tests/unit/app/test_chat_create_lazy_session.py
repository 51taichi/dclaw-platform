# -*- coding: utf-8 -*-
"""Tests for lazy chat creation semantics."""
from __future__ import annotations

import pytest
from fastapi import HTTPException
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


@pytest.mark.asyncio
async def test_create_chat_rejects_invalid_local_access_mode():
    mgr = _FakeChatManager()
    request = SimpleNamespace(state=SimpleNamespace(user_id="default"))

    with pytest.raises(HTTPException) as exc_info:
        await chat_api.create_chat(
            request,
            ChatSpec(
                name="hello",
                session_id="",
                user_id="default",
                channel="console",
                meta={"local_access_mode": "unrestricted-ish"},
            ),
            mgr=mgr,
        )

    assert getattr(exc_info.value, "status_code", None) == 422
    assert mgr.created is None
