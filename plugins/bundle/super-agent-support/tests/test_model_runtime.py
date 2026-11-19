from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from super_agent.model_runtime import (
    ModelRouteError, ModelStageTimeout, TimedModel, declared_model_route,
)


def _manager(*models: str):
    provider = SimpleNamespace(models=[SimpleNamespace(id=item, model_type="llm")
                                       for item in models], extra_models=[])
    return SimpleNamespace(get_provider=lambda value: provider if value == "provider" else None)


def _signed(tmp_path, model="old"):
    (tmp_path / "agent.json").write_text(json.dumps({
        "active_model": {"provider_id": "provider", "model": model},
    }), encoding="utf-8")
    return {"signed_root": tmp_path, "signed_files": frozenset({"agent.json"})}


def test_retired_signed_model_fails_before_fallback(tmp_path):
    with pytest.raises(ModelRouteError) as error:
        declared_model_route(
            **_signed(tmp_path), selected_model=None,
            actual_model=SimpleNamespace(model_key="provider:new"),
            manager=_manager("new"),
        )
    assert (error.value.code, error.value.category) == (
        "MODEL_ROUTE_UNAVAILABLE", "signed_model_not_in_catalog",
    )


def test_valid_route_and_effective_mismatch(tmp_path):
    source = _signed(tmp_path, model="new")
    assert declared_model_route(
        **source, selected_model=None,
        actual_model=SimpleNamespace(model_key="provider:new"),
        manager=_manager("new"),
    ) == ("provider", "new")
    with pytest.raises(ModelRouteError) as error:
        declared_model_route(
            **source, selected_model=None,
            actual_model=SimpleNamespace(model_key="provider:other"),
            manager=_manager("new", "other"),
        )
    assert (error.value.code, error.value.category) == (
        "MODEL_ROUTE_MISMATCH", "effective_model_mismatch",
    )


def test_explicit_supported_choice_overrides_retired_default(tmp_path):
    assert declared_model_route(
        **_signed(tmp_path),
        selected_model={"provider_id": "provider", "model": "new"},
        actual_model=SimpleNamespace(model_key="provider:new"),
        manager=_manager("new"),
    ) == ("provider", "new")


def test_automatic_route_does_not_require_a_fixed_catalog_entry(tmp_path):
    assert declared_model_route(
        **_signed(tmp_path),
        selected_model={"provider_id": "auto", "model": "routing"},
        actual_model=SimpleNamespace(model_key="provider:new"),
        manager=_manager("new"),
    ) == ("auto", "routing")


@pytest.mark.asyncio
async def test_request_timeout_records_safe_model_stage():
    class SlowModel:
        async def __call__(self, *_args, **_kwargs):
            await asyncio.sleep(1)

    events = []
    model = TimedModel(
        SlowModel(), deadline=asyncio.get_running_loop().time() + 0.02,
        emit=lambda event, payload: events.append((event, payload)),
        provider_id="provider", model_id="new",
    )
    with pytest.raises(ModelStageTimeout) as error:
        await model([])
    assert (error.value.stage, error.value.attempt) == ("request", 1)
    assert [event for event, _ in events] == [
        "model.call.started", "model.call.timed_out",
    ]
    assert events[-1][1] == {
        "provider_id": "provider", "model_id": "new", "stage": "request", "attempt": 1,
    }


@pytest.mark.asyncio
async def test_stream_timeout_records_first_chunk_and_stage():
    class SlowStreamModel:
        async def __call__(self, *_args, **_kwargs):
            async def stream():
                yield SimpleNamespace(content="first")
                await asyncio.sleep(1)
            return stream()

    events = []
    model = TimedModel(
        SlowStreamModel(), deadline=asyncio.get_running_loop().time() + 0.02,
        emit=lambda event, payload: events.append((event, payload)),
        provider_id="provider", model_id="new",
    )
    stream = await model([])
    with pytest.raises(ModelStageTimeout) as error:
        async for _ in stream:
            pass
    assert error.value.stage == "stream"
    assert [event for event, _ in events] == [
        "model.call.started", "model.stream.first_chunk", "model.call.timed_out",
    ]


@pytest.mark.asyncio
async def test_fast_model_completes_without_extra_calls():
    class FastModel:
        async def __call__(self, *_args, **_kwargs):
            return "ok"

    events = []
    model = TimedModel(
        FastModel(), deadline=asyncio.get_running_loop().time() + 1,
        emit=lambda event, payload: events.append(event),
        provider_id="provider", model_id="new",
    )
    assert await model([]) == "ok"
    assert events == ["model.call.started", "model.call.completed"]
