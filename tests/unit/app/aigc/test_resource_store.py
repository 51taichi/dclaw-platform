"""Shared storage must preserve resources independently of HTTP/experts."""

import importlib
import pytest


def store_module():
    return importlib.import_module("qwenpaw.app.aigc.resource_store")


def test_resource_store_survives_new_instance(tmp_path):
    store = store_module().AigcResourceStore(tmp_path)
    store.write("canvases", "canvas-1", {"id": "canvas-1"})
    assert store_module().AigcResourceStore(tmp_path).read("canvases", "canvas-1") == {
        "id": "canvas-1"
    }


@pytest.mark.parametrize("kind,resource_id", [
    ("../outside", "canvas-1"), ("canvases", "../outside"),
    ("/tmp", "canvas-1"), ("canvases", ""),
])
def test_rejects_resource_path_escape(tmp_path, kind, resource_id):
    module = store_module()
    with pytest.raises(module.AigcResourceError) as caught:
        module.AigcResourceStore(tmp_path).write(kind, resource_id, {})
    assert caught.value.code == "INVALID_RESOURCE_ID"
    assert list(tmp_path.iterdir()) == []


def test_rejects_symlink_outside_store(tmp_path):
    module = store_module()
    root = tmp_path / "studio"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "canvases").symlink_to(outside, target_is_directory=True)
    with pytest.raises(module.AigcResourceError) as caught:
        module.AigcResourceStore(root).write("canvases", "canvas-1", {})
    assert caught.value.code == "INVALID_RESOURCE_PATH"
    assert list(outside.iterdir()) == []


def test_failed_atomic_replace_preserves_previous_document(tmp_path, monkeypatch):
    module = store_module()
    store = module.AigcResourceStore(tmp_path)
    store.write("canvases", "canvas-1", {"revision": 1})

    def fail_replace(source, target):
        raise OSError("simulated storage failure")

    monkeypatch.setattr(module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated storage failure"):
        store.write("canvases", "canvas-1", {"revision": 2})
    assert module.AigcResourceStore(tmp_path).read("canvases", "canvas-1") == {"revision": 1}
    assert [p.name for p in (tmp_path / "canvases").iterdir()] == ["canvas-1.json"]


def test_cached_nested_values_are_not_mutable_authority(tmp_path):
    store = store_module().AigcResourceStore(tmp_path)
    store.write("canvases", "canvas-1", {"meta": {"owner_user_id": "user-a"}})
    returned = store.read("canvases", "canvas-1")
    returned["meta"]["owner_user_id"] = "user-b"
    assert store.read("canvases", "canvas-1") == {"meta": {"owner_user_id": "user-a"}}


def test_roots_do_not_share_cache_and_external_changes_are_visible(tmp_path):
    cls = store_module().AigcResourceStore
    first, second = cls(tmp_path / "a"), cls(tmp_path / "b")
    first.write("canvases", "canvas-1", {"owner": "a"})
    second.write("canvases", "canvas-1", {"owner": "b"})
    assert first.read("canvases", "canvas-1") == {"owner": "a"}
    assert second.read("canvases", "canvas-1") == {"owner": "b"}
    cls(tmp_path / "a").write("canvases", "canvas-1", {"owner": "changed"})
    assert first.read("canvases", "canvas-1") == {"owner": "changed"}


@pytest.mark.parametrize("raw", ["{", "[]", "null", '"string"'])
def test_corrupt_or_non_object_document_is_domain_error(tmp_path, raw):
    module = store_module()
    directory = tmp_path / "canvases"
    directory.mkdir()
    (directory / "canvas-1.json").write_text(raw)
    with pytest.raises(module.AigcResourceError) as caught:
        module.AigcResourceStore(tmp_path).read("canvases", "canvas-1")
    assert caught.value.code == "CORRUPT_RESOURCE"
    assert caught.value.resource_name == "canvas-1.json"


def test_deleted_cached_resource_is_not_returned(tmp_path):
    module = store_module()
    store = module.AigcResourceStore(tmp_path)
    store.write("canvases", "canvas-1", {"id": "canvas-1"})
    store.read("canvases", "canvas-1")
    store.delete("canvases", "canvas-1")
    with pytest.raises(module.AigcResourceError) as caught:
        store.read("canvases", "canvas-1")
    assert caught.value.code == "RESOURCE_NOT_FOUND"


def test_canvas_round_trip_uses_shared_models(tmp_path):
    models = importlib.import_module("qwenpaw.app.aigc.models")
    canvas = models.Canvas(id="c", created_at="start", updated_at="start")
    store = store_module().AigcResourceStore(tmp_path)
    store.write("canvases", "c", canvas.model_dump())
    assert models.Canvas(**store.read("canvases", "c")).model_dump() == {
        "id": "c", "name": "Untitled canvas", "nodes": [], "edges": [],
        "viewport": {"x": 0.0, "y": 0.0, "zoom": 1.0}, "thumbnail": None,
        "meta": {}, "created_at": "start", "updated_at": "start",
    }
def test_stale_projection_write_preserves_new_canvas_edits(tmp_path):
    from qwenpaw.app.aigc.resource_store import AigcResourceStore

    first = AigcResourceStore(tmp_path)
    second = AigcResourceStore(tmp_path)
    first.write("canvases", "c", {"id": "c", "name": "before"})
    observed = first.read("canvases", "c")
    second.write("canvases", "c", {"id": "c", "name": "customer edit"})
    assert not first.compare_and_write("canvases", "c", observed, {"id": "c", "name": "stale"})
    assert second.read("canvases", "c")["name"] == "customer edit"


def _increment_resource(root):
    store = store_module().AigcResourceStore(root)
    for _ in range(20):
        for _retry in range(1000):
            current = store.read("canvases", "counter")
            if store.compare_and_write("canvases", "counter", current, {"value": current["value"] + 1}):
                break
        else:
            raise AssertionError("Concurrent writer made no progress")


def test_compare_and_write_is_atomic_across_processes(tmp_path):
    import multiprocessing

    store = store_module().AigcResourceStore(tmp_path)
    store.write("canvases", "counter", {"value": 0})
    context = multiprocessing.get_context("spawn")
    workers = [context.Process(target=_increment_resource, args=(tmp_path,)) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            assert worker.exitcode == 0
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
    assert store.read("canvases", "counter") == {"value": 40}
