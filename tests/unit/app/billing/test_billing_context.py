# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio

from qwenpaw.app.agent_context import get_current_billing_context
from qwenpaw.app.billing.context import (
    BillingExecutionContext,
    BillingSession,
    BillingSource,
    billing_context,
    get_current_billing_meter,
)
from qwenpaw.app.storage.repos.billing_execution_repo import (
    BillingExecutionFence,
)


def _session(source_id: str) -> BillingSession:
    return BillingSession(
        execution_id=f"execution-{source_id}",
        usage_order_id=f"order-{source_id}",
        wallet_id=f"wallet-{source_id}",
        payer_user_id=f"user-{source_id}",
        catalog_version="v1",
        source=BillingSource(type="client", id=source_id),
        mode="enforced",
    )


def test_billing_context_installs_meter_and_restores_prior_values():
    session = _session("one")
    fence = BillingExecutionFence("worker-one", 1)
    meter = object()

    with billing_context(session, fence, meter):
        current = get_current_billing_context()
        assert current == BillingExecutionContext(session, fence)
        assert get_current_billing_meter() is meter

    assert get_current_billing_context() is None
    assert get_current_billing_meter() is None


def test_billing_context_isolated_between_async_siblings():
    async def run():
        ready = asyncio.Event()
        release = asyncio.Event()

        async def scoped():
            session = _session("scoped")
            fence = BillingExecutionFence("worker-scoped", 1)
            with billing_context(session, fence, "meter-scoped"):
                ready.set()
                await release.wait()
                return get_current_billing_context(), get_current_billing_meter()

        async def unscoped():
            await ready.wait()
            values = get_current_billing_context(), get_current_billing_meter()
            release.set()
            return values

        return await asyncio.gather(scoped(), unscoped())

    scoped_values, unscoped_values = asyncio.run(run())
    assert isinstance(scoped_values[0], BillingExecutionContext)
    assert scoped_values[1] == "meter-scoped"
    assert unscoped_values == (None, None)
