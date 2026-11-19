"""Signed model-route checks and bounded, content-free model stage tracing."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Callable


_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")


class ModelRouteError(ValueError):
    def __init__(self, code: str, category: str, provider_id: str = "", model_id: str = ""):
        super().__init__(category)
        self.code = code
        self.category = category
        self.provider_id = provider_id
        self.model_id = model_id


class ModelStageTimeout(asyncio.TimeoutError):
    def __init__(self, stage: str, attempt: int):
        super().__init__(stage)
        self.stage = stage
        self.attempt = attempt


def _slot(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, dict):
        return None
    provider_id, model_id = value.get("provider_id"), value.get("model")
    if not isinstance(provider_id, str) or not isinstance(model_id, str):
        return None
    if not _MODEL_ID.fullmatch(provider_id) or not _MODEL_ID.fullmatch(model_id):
        return None
    return provider_id, model_id


def model_identity(model: Any) -> tuple[str, str]:
    key = getattr(model, "model_key", None)
    if isinstance(key, str) and ":" in key:
        provider_id, model_id = key.split(":", 1)
        if _MODEL_ID.fullmatch(provider_id) and _MODEL_ID.fullmatch(model_id):
            return provider_id, model_id
    return "unknown", "unknown"


def declared_model_route(
    *, signed_root: Path | None, signed_files: frozenset[str],
    selected_model: dict[str, Any] | None, actual_model: Any, manager: Any,
) -> tuple[str, str] | None:
    """Require an explicit chat choice or signed Agent default to exist and match."""
    signed_slot = None
    if signed_root is not None and "agent.json" in signed_files:
        try:
            path = signed_root / "agent.json"
            if path.is_symlink() or path.stat().st_size > 1_000_000:
                raise ValueError("unsafe signed model declaration")
            declaration = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(declaration, dict):
                raise ValueError("invalid signed model declaration")
            if "active_model" in declaration and declaration["active_model"] is not None:
                signed_slot = _slot(declaration["active_model"])
                if signed_slot is None:
                    raise ValueError("invalid signed model declaration")
        except (OSError, ValueError, TypeError) as exc:
            raise ModelRouteError("MODEL_ROUTE_UNAVAILABLE", "model_declaration_invalid") from exc
    selected_slot = _slot(selected_model) if selected_model is not None else None
    if selected_model is not None and selected_slot is None:
        raise ModelRouteError("MODEL_ROUTE_UNAVAILABLE", "selected_model_invalid")
    expected = selected_slot or signed_slot
    if expected is None or expected == ("auto", "routing"):
        return expected
    provider_id, model_id = expected
    provider = manager.get_provider(provider_id) if manager is not None else None
    models = list(getattr(provider, "models", ()) or ()) + list(
        getattr(provider, "extra_models", ()) or ()
    )
    available = any(
        getattr(item, "id", None) == model_id
        and getattr(item, "model_type", "llm") == "llm"
        for item in models
    )
    if not available:
        raise ModelRouteError(
            "MODEL_ROUTE_UNAVAILABLE",
            "selected_model_not_in_catalog" if selected_slot else "signed_model_not_in_catalog",
            provider_id, model_id,
        )
    if model_identity(actual_model) != expected:
        raise ModelRouteError(
            "MODEL_ROUTE_MISMATCH", "effective_model_mismatch", provider_id, model_id,
        )
    return expected


class TimedModel:
    """Trace each Agent model call and stop a stalled request or stream."""

    def __init__(
        self, inner: Any, *, deadline: float, emit: Callable[[str, dict], None],
        provider_id: str, model_id: str,
    ) -> None:
        self._inner = inner
        self._deadline = deadline
        self._emit = emit
        self._provider_id = provider_id
        self._model_id = model_id
        self._attempt = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _stage(self, event: str, stage: str, attempt: int) -> None:
        self._emit(event, {
            "provider_id": self._provider_id,
            "model_id": self._model_id,
            "stage": stage,
            "attempt": attempt,
        })

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self._attempt += 1
        attempt = self._attempt
        self._stage("model.call.started", "request", attempt)
        try:
            response = await asyncio.wait_for(
                self._inner(*args, **kwargs),
                timeout=max(0, self._deadline - asyncio.get_running_loop().time()),
            )
        except asyncio.TimeoutError as exc:
            self._stage("model.call.timed_out", "request", attempt)
            raise ModelStageTimeout("request", attempt) from exc
        except Exception as exc:
            self._emit("model.call.failed", {
                "provider_id": self._provider_id, "model_id": self._model_id,
                "stage": "request", "attempt": attempt,
                "category": type(exc).__name__,
            })
            raise
        if not hasattr(response, "__aiter__"):
            self._stage("model.call.completed", "response", attempt)
            return response

        async def stream():
            first_chunk = True
            try:
                iterator = response.__aiter__()
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            iterator.__anext__(),
                            timeout=max(
                                0, self._deadline - asyncio.get_running_loop().time(),
                            ),
                        )
                    except StopAsyncIteration:
                        break
                    if first_chunk:
                        self._stage("model.stream.first_chunk", "stream", attempt)
                        first_chunk = False
                    yield chunk
            except asyncio.TimeoutError as exc:
                self._stage("model.call.timed_out", "stream", attempt)
                raise ModelStageTimeout("stream", attempt) from exc
            except Exception as exc:
                self._emit("model.call.failed", {
                    "provider_id": self._provider_id, "model_id": self._model_id,
                    "stage": "stream", "attempt": attempt,
                    "category": type(exc).__name__,
                })
                raise
            self._stage("model.call.completed", "stream", attempt)

        return stream()
