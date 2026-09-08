"""The UI bus is a delivery target, not the authority for completed generation."""

import pytest

from tests.unit.app.aigc.test_job_lifecycle import resources, lifecycle


@pytest.mark.asyncio
async def test_runtime_notification_survives_bus_outage_and_consumer_restart(resources):
    from qwenpaw.app.runtime.aigc_events import AigcRuntimeNotifications
    from qwenpaw.app.runtime.event_bus import MemoryRuntimeEventBus

    lifecycle(resources).record_success(resources.job, [resources.asset], owner_user_id="owner")
    class OfflineBus:
        async def publish(self, _event):
            raise OSError("unavailable")

    first = AigcRuntimeNotifications(resources.repository, OfflineBus(), clock=lambda: 0)
    assert await first.deliver_pending() == 1  # asset event does not require a UI broadcast
    assert resources.repository.get_job_result("job") is not None
    bus = MemoryRuntimeEventBus(max_events=100, max_age_seconds=60)
    recovered = AigcRuntimeNotifications(resources.repository, bus, clock=lambda: 6)
    assert await recovered.deliver_pending() == 1
    events = await bus.replay(session_id=None, since_id=None)
    assert len(events) == 1
    assert events[0].type == "aigc.job.updated"
    assert events[0].payload["job_id"] == "job"
    assert events[0].payload["status"] == "succeeded"
    assert events[0].payload["output_count"] == 1
    assert "private/path" not in str(events[0].to_dict())
    assert await recovered.deliver_pending() == 0


@pytest.mark.asyncio
async def test_runtime_delivery_does_not_replay_obsolete_failure(resources):
    from qwenpaw.app.runtime.aigc_events import AigcRuntimeNotifications
    from qwenpaw.app.runtime.event_bus import MemoryRuntimeEventBus

    lifecycle(resources).record_failure(resources.job, "private/raw/error", owner_user_id="owner")
    lifecycle(resources).record_success(resources.job, [resources.asset], owner_user_id="owner")
    bus = MemoryRuntimeEventBus(max_events=100, max_age_seconds=60)
    await AigcRuntimeNotifications(resources.repository, bus).deliver_pending()
    events = await bus.replay(session_id=None, since_id=None)
    assert [event.status for event in events] == ["succeeded"]
    assert "private" not in str([event.to_dict() for event in events])


@pytest.mark.asyncio
async def test_cancel_notification_is_recoverable(resources):
    from qwenpaw.app.runtime.aigc_events import AigcRuntimeNotifications
    from qwenpaw.app.runtime.event_bus import MemoryRuntimeEventBus

    lifecycle(resources).cancel(resources.job, owner_user_id="owner")
    bus = MemoryRuntimeEventBus(max_events=100, max_age_seconds=60)
    await AigcRuntimeNotifications(resources.repository, bus).deliver_pending()
    events = await bus.replay(session_id=None, since_id=None)
    assert [event.status for event in events] == ["cancelled"]
    assert events[0].payload["error"] is None


@pytest.mark.asyncio
async def test_recovery_worker_restores_projection_and_stops_cleanly(resources, monkeypatch):
    import asyncio
    from qwenpaw.app.runtime.aigc_events import AigcRecoveryWorker, AigcRuntimeNotifications
    from qwenpaw.app.runtime.event_bus import MemoryRuntimeEventBus

    service = lifecycle(resources)
    with monkeypatch.context() as patch:
        def unavailable(*_):
            raise OSError("disk unavailable")
        patch.setattr(resources.store, "write", unavailable)
        service.record_success(resources.job, [resources.asset], owner_user_id="owner")
    bus = MemoryRuntimeEventBus(max_events=100, max_age_seconds=60)
    ready = asyncio.Event()
    class Notifications(AigcRuntimeNotifications):
        async def deliver_pending(self, limit=100):
            result = await super().deliver_pending(limit)
            ready.set()
            return result
    worker = AigcRecoveryWorker(service, [Notifications(resources.repository, bus)])
    worker.start()
    try:
        await asyncio.wait_for(ready.wait(), timeout=2)
        assert resources.store.read("jobs", "job")["status"] == "succeeded"
        assert len(await bus.replay(session_id=None, since_id=None)) == 1
    finally:
        await worker.stop()
    assert not worker.running


@pytest.mark.asyncio
async def test_projection_does_not_block_event_loop_and_stop_drains_active_write(resources, monkeypatch):
    import asyncio
    import threading
    from qwenpaw.app.runtime.aigc_events import AigcRecoveryWorker

    service = lifecycle(resources)
    with monkeypatch.context() as patch:
        def unavailable(*_):
            raise OSError("projection unavailable")
        patch.setattr(resources.store, "write", unavailable)
        service.record_success(resources.job, [resources.asset], owner_user_id="owner")
    started = asyncio.Event()
    release = threading.Event()
    finished = threading.Event()
    loop = asyncio.get_running_loop()
    original = service._write_projection
    def delayed(row):
        loop.call_soon_threadsafe(started.set)
        release.wait(timeout=1)
        original(row)
        finished.set()
    monkeypatch.setattr(service, "_write_projection", delayed)
    worker = AigcRecoveryWorker(service, [])
    worker.start()
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        assert not finished.is_set(), "projection blocked the event loop"
        stopping = asyncio.create_task(worker.stop())
        await asyncio.sleep(0)
        assert not stopping.done(), "shutdown must drain the active projection"
        release.set()
        await stopping
        assert finished.is_set()
    finally:
        release.set()
        await worker.stop()
