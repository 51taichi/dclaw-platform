"""Durable event leases recover without triggering any model/provider action."""

from concurrent.futures import ThreadPoolExecutor
import pytest

from tests.unit.app.aigc.test_job_lifecycle import resources, lifecycle


def test_expired_lease_is_reclaimed_and_old_ack_cannot_win(resources):
    lifecycle(resources).record_failure(resources.job, "provider failed", owner_user_id="owner")
    repo = resources.repository
    first = repo.claim_domain_events("ui", now=100, lease_seconds=10)[0]
    assert repo.claim_domain_events("ui", now=105) == []
    again = repo.claim_domain_events("ui", now=111)[0]
    assert again["event"].event_id == first["event"].event_id
    assert again["lease_token"] != first["lease_token"]
    assert not repo.complete_domain_delivery("ui", first["event"].event_id, first["lease_token"], now=112)
    assert repo.complete_domain_delivery("ui", again["event"].event_id, again["lease_token"], now=112)
    assert repo.claim_domain_events("ui", now=999) == []
    assert len(repo.claim_domain_events("other-adapter", now=999)) == 1


def test_failed_delivery_backs_off_but_stays_recoverable(resources):
    lifecycle(resources).record_failure(resources.job, "failure", owner_user_id="owner")
    repo = resources.repository
    now = 100
    for delay in [5, 15, 60, 300, 300]:
        claim = repo.claim_domain_events("adapter", now=now)[0]
        assert repo.complete_domain_delivery("adapter", claim["event"].event_id, claim["lease_token"],
                                             now=now, outcome="retry", error_code="DELIVERY_FAILED")
        assert repo.claim_domain_events("adapter", now=now + delay - 1) == []
        now += delay
    claim = repo.claim_domain_events("adapter", now=now)[0]
    assert repo.complete_domain_delivery("adapter", claim["event"].event_id, claim["lease_token"],
                                         now=now, outcome="blocked", error_code="INSTALLATION_REVOKED")
    assert repo.claim_domain_events("adapter", now=now + 10000) == []
    assert resources.repository.get_job_result("job") is not None


def test_concurrent_consumers_do_not_claim_same_event(resources):
    lifecycle(resources).record_success(resources.job, [resources.asset], owner_user_id="owner")
    with ThreadPoolExecutor(max_workers=2) as workers:
        batches = list(workers.map(lambda _: resources.repository.claim_domain_events("adapter", now=100, limit=1), range(2)))
    assert len(batches[0]) == len(batches[1]) == 1
    assert batches[0][0]["event"].event_id != batches[1][0]["event"].event_id
    assert resources.repository.claim_domain_events("adapter", now=101) == []
@pytest.mark.asyncio
async def test_consumer_bounds_each_batch_and_keeps_consumers_independent(resources):
    from qwenpaw.app.aigc.events import AigcEventConsumer

    lifecycle(resources).record_success(resources.job, [resources.asset], owner_user_id="owner")
    received = []

    async def handle(event):
        received.append(event.event_type)

    consumer = AigcEventConsumer(resources.repository, "ui", handle)
    assert await consumer.deliver_pending(limit=1) == 1
    assert received == ["job.succeeded"]
    assert await consumer.deliver_pending(limit=1000) == 1
    assert received == ["job.succeeded", "asset.ready"]
    assert await consumer.deliver_pending() == 0
    assert await AigcEventConsumer(resources.repository, "expert", handle).deliver_pending() == 2


@pytest.mark.asyncio
async def test_consumer_timeout_retries_without_losing_event(resources):
    import asyncio
    from qwenpaw.app.aigc.events import AigcEventConsumer

    lifecycle(resources).record_success(resources.job, [resources.asset], owner_user_id="owner")

    async def stalled(_event):
        await asyncio.Event().wait()

    clock = [0.0]
    consumer = AigcEventConsumer(resources.repository, "ui", stalled, timeout_seconds=0.01,
                                 clock=lambda: clock[0])
    assert await consumer.deliver_pending(limit=1) == 0
    claims = resources.repository.claim_domain_events("ui", now=4)
    assert [claim["event"].event_type for claim in claims] == ["asset.ready"]
    claims = resources.repository.claim_domain_events("ui", now=5)
    assert [claim["event"].event_type for claim in claims] == ["job.succeeded"]


@pytest.mark.asyncio
async def test_cancelled_consumer_leaves_event_recoverable(resources):
    import asyncio
    from qwenpaw.app.aigc.events import AigcEventConsumer

    lifecycle(resources).record_success(resources.job, [resources.asset], owner_user_id="owner")

    async def cancelled(_event):
        raise asyncio.CancelledError

    consumer = AigcEventConsumer(resources.repository, "ui", cancelled, clock=lambda: 0)
    with pytest.raises(asyncio.CancelledError):
        await consumer.deliver_pending(limit=1)
    later = resources.repository.claim_domain_events("ui", now=31)
    assert {claim["event"].event_type for claim in later} == {"job.succeeded", "asset.ready"}


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_event_claim_rejects_nonfinite_clock_without_reserving_events(resources, invalid):
    lifecycle(resources).record_success(resources.job, [resources.asset], owner_user_id="owner")
    with pytest.raises(ValueError, match="INVALID_EVENT_CONSUMER"):
        resources.repository.claim_domain_events("ui", now=invalid)
    with pytest.raises(ValueError, match="INVALID_EVENT_CONSUMER"):
        resources.repository.claim_domain_events("ui", now=0, lease_seconds=invalid)
    assert len(resources.repository.claim_domain_events("ui", now=0)) == 2
