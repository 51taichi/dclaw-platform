import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
import pytest
from qwenpaw.app.routers import console
from qwenpaw.app.billing.context import BillingSource

@pytest.mark.asyncio
async def test_title_is_background_deduplicated_and_has_own_billing(monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def generate(**kwargs):
        started.set()
        await release.wait()
    prepared = SimpleNamespace(activate=nullcontext,
        finalize_completed=lambda: calls.append('completed'),
        finalize=lambda *args, **kwargs: calls.append('failed'))
    monkeypatch.setattr(console, 'generate_and_update_title', generate)
    monkeypatch.setattr(console, 'prepare_user_billing_execution', lambda *args: (calls.append(args[2]) or prepared))
    args = dict(workspace=SimpleNamespace(agent_id='agent'), chat_id='chat',
        user_message='hello', placeholder_name='hello', payer_user_id='1',
        source=BillingSource(type='client',id='chat',expert_id='agent'), request_key='turn-1')
    task = console._schedule_chat_title(**args)
    await started.wait()
    assert not task.done()
    assert console._schedule_chat_title(**args) is task
    assert calls == ['turn-1:title']
    release.set()
    await task
    assert calls == ['turn-1:title', 'completed']
