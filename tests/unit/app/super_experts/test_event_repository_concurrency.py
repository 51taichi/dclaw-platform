"""Two consumers must not acknowledge events lost by whole-document overwrite."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
import multiprocessing

import pytest

from qwenpaw.app.super_experts.events import SuperExpertEventEnvelope, SuperExpertEventRepository


def envelope(event_id):
    return SuperExpertEventEnvelope(
        event_id=event_id, installation_id="installation", conversation_id="conversation",
        agent_task_id="task", content_revision=1, material_task_id="material",
        canvas_id="canvas", node_id="node", event_type="aigc.guide.updated",
    )


@pytest.mark.parametrize("second_write", ["event", "receipt"])
def test_concurrent_repository_instances_preserve_both_events(tmp_path, monkeypatch, second_write):
    first, second = SuperExpertEventRepository(tmp_path), SuperExpertEventRepository(tmp_path)
    first_read, second_done = Event(), Event()
    original = first._read
    def delayed_read():
        document = original()
        first_read.set()
        # On the unsafe implementation B finishes while A holds a stale copy.
        # With file locking B waits; the bounded probe then lets A commit first.
        second_done.wait(0.2)
        return document
    monkeypatch.setattr(first, "_read", delayed_read)
    def append_second():
        try:
            if second_write == "receipt":
                return second.save_review_receipt("b", {"reply": "review result"})
            return second.append(envelope("b"))
        finally:
            second_done.set()
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(first.append, envelope("a"))
        assert first_read.wait(1)
        b = pool.submit(append_second)
        assert a.result(timeout=2)
        assert b.result(timeout=2)
    repository = SuperExpertEventRepository(tmp_path)
    assert {event.event_id for event in repository.list_for_session(
        installation_id="installation", conversation_id="conversation",
    )} == ({"a", "b"} if second_write == "event" else {"a"})
    if second_write == "receipt":
        assert repository.get_review_receipt("b") == {"reply": "review result"}


def _append_in_process(root, prefix, ready):
    repository = SuperExpertEventRepository(root)
    assert ready.wait(5)
    for index in range(15):
        repository.append(envelope(f"{prefix}-{index}"))
        repository.save_review_receipt(f"{prefix}-{index}", {"reply": "review result"})


def test_processes_preserve_all_events_and_review_receipts(tmp_path):
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    workers = [context.Process(target=_append_in_process, args=(tmp_path, prefix, ready))
               for prefix in ("a", "b")]
    try:
        for worker in workers:
            worker.start()
        ready.set()
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(2)
    repository = SuperExpertEventRepository(tmp_path)
    events = repository.list_for_session(installation_id="installation", conversation_id="conversation")
    assert {event.event_id for event in events} == {f"{prefix}-{index}" for prefix in ("a", "b") for index in range(15)}
    assert all(repository.get_review_receipt(event.event_id) == {"reply": "review result"} for event in events)
