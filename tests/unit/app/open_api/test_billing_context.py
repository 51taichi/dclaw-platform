# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio

from qwenpaw.app.agent_context import get_current_billing_context
from qwenpaw.app.billing.open_api import OpenApiBillingSession
from qwenpaw.app.billing.execution import OpenApiExecutionFence
from qwenpaw.app.billing.context import get_current_billing_meter
from qwenpaw.app.open_api.runtime import open_api_billing_context


def _session(invocation_id: str) -> OpenApiBillingSession:
    return OpenApiBillingSession(
        invocation_id=invocation_id,
        usage_order_id=f"order-{invocation_id}",
        wallet_id=f"wallet-{invocation_id}",
        bound_user_id=f"user-{invocation_id}",
        app_id="app",
        api_key_id="key",
        publication_id="publication",
        catalog_version="catalog-v1",
        mode="shadow",
    )


def test_context_is_installed_for_committed_session_and_reset_after_scope():
    session = _session("one")
    fence = OpenApiExecutionFence("owner-one", 1)
    meter = object()

    assert get_current_billing_context() is None
    with open_api_billing_context(session, fence, meter) as context:
        assert get_current_billing_context() == context
        assert get_current_billing_meter() is meter
    assert get_current_billing_context() is None
    assert get_current_billing_meter() is None


def test_concurrent_async_billing_contexts_are_isolated_and_do_not_leak():
    async def worker(invocation_id: str):
        session = _session(invocation_id)
        fence = OpenApiExecutionFence(f"owner-{invocation_id}", 1)
        with open_api_billing_context(session, fence) as context:
            await asyncio.sleep(0)
            assert get_current_billing_context() == context
        return get_current_billing_context()

    async def run_workers():
        return await asyncio.gather(worker("left"), worker("right"))

    left, right = asyncio.run(run_workers())

    assert left is None
    assert right is None
    assert get_current_billing_context() is None
