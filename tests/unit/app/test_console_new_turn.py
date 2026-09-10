import asyncio
import pytest
from qwenpaw.app.runner.task_tracker import TaskTracker


@pytest.mark.asyncio
async def test_new_turn_waits_without_replaying_previous_reply():
    tracker = TaskTracker()
    release = asyncio.Event()
    async def old_stream(payload):
        yield 'old opening'
        await release.wait()
    async def new_stream(payload):
        yield 'new answer'
    old_queue, _ = await tracker.attach_or_start('chat', {}, old_stream)
    assert await old_queue.get() == 'old opening'
    pending = asyncio.create_task(tracker.start_new('chat', {'text': 'okay'}, new_stream))
    try:
        await asyncio.sleep(0)
        assert not pending.done()
        reconnect = await tracker.attach('chat')
        assert await reconnect.get() == 'old opening'
        release.set()
        queue, is_new = await asyncio.wait_for(pending, 2)
        assert is_new
        assert [x async for x in tracker.stream_from_queue(queue, 'chat')] == ['new answer']
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
