# -*- coding: utf-8 -*-
"""Unit tests for the token usage core module."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest

from qwenpaw.token_usage.buffer import (
    TokenUsageBuffer,
    _UsageEvent,
    _apply_event,
)
from qwenpaw.token_usage import manager as token_usage_manager_module
from qwenpaw.token_usage.manager import (
    TokenUsageByDateModel,
    TokenUsageByModel,
    TokenUsageManager,
    TokenUsageRecord,
    TokenUsageStats,
    TokenUsageSummary,
)
from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper
from qwenpaw.token_usage.storage import load_data, save_data_sync


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _isolate_token_usage_manager():
    """Isolate token usage manager singleton for each test."""
    # pylint: disable=protected-access
    TokenUsageManager._instance = None
    yield
    TokenUsageManager._instance = None


# =============================================================================
# Test _apply_event
# =============================================================================


class TestApplyEvent:
    """Test the _apply_event function that accumulates usage events."""

    # pylint: disable=protected-access

    def test_apply_event_creates_new_entry(self):
        """Should create new entry for first event."""
        cache = {}
        event = _UsageEvent(
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            date_str="2026-04-24",
            now_iso="2026-04-24T10:00:00+00:00",
        )
        _apply_event(cache, event)

        assert "2026-04-24" in cache
        assert "openai:gpt-4" in cache["2026-04-24"]
        entry = cache["2026-04-24"]["openai:gpt-4"]
        assert entry["prompt_tokens"] == 100
        assert entry["completion_tokens"] == 50
        assert entry["call_count"] == 1

    def test_apply_event_accumulates_same_model(self):
        """Should accumulate tokens for same provider:model on same date."""
        cache = {}
        for _ in range(3):
            _apply_event(
                cache,
                _UsageEvent(
                    provider_id="openai",
                    model_name="gpt-4",
                    prompt_tokens=100,
                    completion_tokens=50,
                    date_str="2026-04-24",
                    now_iso="2026-04-24T10:00:00+00:00",
                ),
            )

        entry = cache["2026-04-24"]["openai:gpt-4"]
        assert entry["prompt_tokens"] == 300
        assert entry["call_count"] == 3


# =============================================================================
# Test Storage
# =============================================================================


class TestStorage:
    """Test storage load/save operations."""

    @pytest.mark.asyncio
    async def test_load_data_nonexistent_file(self, tmp_path):
        """Should return empty dict when file doesn't exist."""
        data = await load_data(tmp_path / "token_usage.json")
        assert data == {}

    @pytest.mark.asyncio
    async def test_load_data_valid_json(self, tmp_path):
        """Should load and return valid JSON data."""
        path = tmp_path / "token_usage.json"
        expected = {
            "2026-04-24": {
                "openai:gpt-4": {
                    "provider_id": "openai",
                    "model_name": "gpt-4",
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "call_count": 2,
                },
            },
        }
        path.write_text(json.dumps(expected))
        data = await load_data(path)
        assert data["2026-04-24"]["openai:gpt-4"]["prompt_tokens"] == 100

    @pytest.mark.asyncio
    async def test_load_data_corrupt_json(self, tmp_path):
        """Should handle corrupt JSON gracefully."""
        path = tmp_path / "token_usage.json"
        path.write_text("{invalid json}")
        data = await load_data(path)
        assert data == {}

    def test_save_data_sync_writes_file(self, tmp_path):
        """Should write data to file atomically."""
        path = tmp_path / "token_usage.json"
        data = {"2026-04-24": {"openai:gpt-4": {"prompt_tokens": 100}}}
        save_data_sync(path, data)
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded == data

    def test_save_data_sync_creates_parent_dirs(self, tmp_path):
        """Should create parent directories if needed."""
        path = tmp_path / "subdir" / "token_usage.json"
        save_data_sync(path, {"test": "data"})
        assert path.exists()


# =============================================================================
# Test TokenUsageBuffer
# =============================================================================


class TestTokenUsageBuffer:
    """Test TokenUsageBuffer core functionality."""

    # pylint: disable=protected-access

    def test_init_defaults(self, tmp_path):
        """Should initialize with correct defaults."""
        buffer = TokenUsageBuffer(tmp_path / "test.json")
        assert buffer._flush_interval == 10

    @pytest.mark.asyncio
    async def test_enqueue_adds_to_queue(self, tmp_path):
        """Should add event to queue."""
        buffer = TokenUsageBuffer(tmp_path / "test.json")
        event = _UsageEvent(
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            date_str="2026-04-24",
            now_iso="2026-04-24T10:00:00+00:00",
        )
        buffer.enqueue(event)
        assert buffer._queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_consumer_processes_events(self, tmp_path):
        """Consumer should process and accumulate events."""
        buffer = TokenUsageBuffer(tmp_path / "test.json")
        buffer.start()

        for _ in range(3):
            buffer.enqueue(
                _UsageEvent(
                    provider_id="openai",
                    model_name="gpt-4",
                    prompt_tokens=100,
                    completion_tokens=50,
                    date_str="2026-04-24",
                    now_iso="2026-04-24T10:00:00+00:00",
                ),
            )

        await asyncio.sleep(0.2)
        await buffer.stop()

        entry = buffer._disk_cache["2026-04-24"]["openai:gpt-4"]
        assert entry["prompt_tokens"] == 300
        assert entry["call_count"] == 3


# =============================================================================
# Test Pydantic Models
# =============================================================================


class TestTokenUsageStats:
    """Test TokenUsageStats model."""

    def test_default_values(self):
        """Should have zero defaults."""
        stats = TokenUsageStats()
        assert stats.prompt_tokens == 0
        assert stats.completion_tokens == 0
        assert stats.call_count == 0

    def test_custom_values(self):
        """Should accept custom values."""
        stats = TokenUsageStats(
            prompt_tokens=100,
            completion_tokens=50,
            call_count=5,
        )
        assert stats.prompt_tokens == 100
        assert stats.completion_tokens == 50
        assert stats.call_count == 5

    def test_validation_rejects_negative(self):
        """Should reject negative values."""
        with pytest.raises(Exception):
            TokenUsageStats(prompt_tokens=-1)


class TestTokenUsageModels:
    """Test TokenUsage models."""

    def test_create_record(self):
        """Should create record with all fields."""
        record = TokenUsageRecord(
            date="2026-04-24",
            provider_id="openai",
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            call_count=3,
        )
        assert record.date == "2026-04-24"
        assert record.provider_id == "openai"
        assert record.model == "gpt-4"

    def test_empty_summary(self):
        """Should create empty summary with defaults."""
        summary = TokenUsageSummary()
        assert summary.total_prompt_tokens == 0
        assert summary.total_completion_tokens == 0
        assert summary.total_calls == 0
        assert summary.by_date == {}

    def test_summary_with_data(self):
        """Should accept populated data."""
        summary = TokenUsageSummary(
            total_prompt_tokens=500,
            total_completion_tokens=250,
            total_calls=10,
            by_date={
                "2026-04-24": TokenUsageStats(
                    prompt_tokens=500,
                    completion_tokens=250,
                    call_count=10,
                ),
            },
        )
        assert summary.total_prompt_tokens == 500
        assert len(summary.by_date) == 1

    def test_token_usage_by_model(self):
        """Should create TokenUsageByModel with provider_id."""
        by_model = TokenUsageByModel(
            provider_id="openai",
            model="gpt-4",
            prompt_tokens=300,
            completion_tokens=150,
            call_count=6,
        )
        assert by_model.provider_id == "openai"
        assert by_model.model == "gpt-4"

    def test_token_usage_by_date_model(self):
        """Should create TokenUsageByDateModel."""
        by_date_model = TokenUsageByDateModel(
            provider_id="dashscope",
            model="qwen3-max",
            prompt_tokens=200,
            completion_tokens=100,
            call_count=4,
        )
        assert by_date_model.provider_id == "dashscope"
        assert by_date_model.model == "qwen3-max"


# =============================================================================
# Test TokenUsageManager
# =============================================================================


class FakeTokenUsageRepository:
    def __init__(self):
        self.inserted = []
        self.summary_rows = []
        self.detail_rows = []

    def insert_events(self, records):
        self.inserted.extend(records)
        for record in records:
            self.summary_rows.append(
                {
                    "usage_date": record.created_at[:10],
                    "model_name": record.model_name,
                    "prompt_tokens": record.prompt_tokens,
                    "completion_tokens": record.completion_tokens,
                    "call_count": 1,
                }
            )
            self.detail_rows.append(
                {
                    "usage_date": record.created_at[:10],
                    "user_id": str(record.user_id) if record.user_id else None,
                    "model_name": record.model_name,
                    "prompt_tokens": record.prompt_tokens,
                    "completion_tokens": record.completion_tokens,
                    "call_count": 1,
                }
            )

    def get_summary_rows(self, **_kwargs):
        return list(self.summary_rows)

    def get_detail_rows(self, **_kwargs):
        return list(self.detail_rows)


@pytest.fixture
def fake_token_usage_repo(monkeypatch):
    repo = FakeTokenUsageRepository()
    monkeypatch.setattr(
        token_usage_manager_module,
        "get_token_usage_repository",
        lambda: repo,
    )
    return repo


class TestTokenUsageManagerCore:
    """Test TokenUsageManager singleton, lifecycle, and operations."""

    @pytest.mark.asyncio
    async def test_manager_uses_token_usage_repository(self, monkeypatch):
        """Should flush and query through the configured repository."""
        class FakeTokenUsageRepository:
            def __init__(self):
                self.inserted = []

            def insert_events(self, records):
                self.inserted.extend(records)

            def get_summary_rows(self, **kwargs):
                assert kwargs["model_name"] == "glm-4.7"
                return [
                    {
                        "usage_date": "2026-06-08",
                        "model_name": "glm-4.7",
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                        "call_count": 1,
                    }
                ]

            def get_detail_rows(self, **kwargs):
                assert kwargs["user_id"] == "1"
                return [
                    {
                        "usage_date": "2026-06-08",
                        "user_id": "1",
                        "model_name": "glm-4.7",
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                        "call_count": 1,
                    }
                ]

        repo = FakeTokenUsageRepository()
        monkeypatch.setattr(
            token_usage_manager_module,
            "get_token_usage_repository",
            lambda: repo,
        )

        manager = TokenUsageManager()
        manager.enqueue(
            _UsageEvent(
                provider_id="zhipu",
                model_name="glm-4.7",
                prompt_tokens=100,
                completion_tokens=50,
                date_str="2026-06-08",
                now_iso="2026-06-08T12:00:00+00:00",
                user_id="1",
            )
        )

        summary = await manager.get_summary(
            model_name="glm-4.7",
            start_date=token_usage_manager_module.date(2026, 6, 8),
            end_date=token_usage_manager_module.date(2026, 6, 8),
        )
        details = await manager.get_details(
            user_id="1",
            start_date=token_usage_manager_module.date(2026, 6, 8),
            end_date=token_usage_manager_module.date(2026, 6, 8),
        )

        assert [record.model_name for record in repo.inserted] == ["glm-4.7"]
        assert summary.total_prompt_tokens == 100
        assert summary.total_completion_tokens == 50
        assert summary.total_calls == 1
        assert details[0].model == "glm-4.7"

    def test_get_instance_returns_singleton(self):
        """Should return same instance on multiple calls."""
        manager1 = token_usage_manager_module.get_token_usage_manager()
        manager2 = token_usage_manager_module.get_token_usage_manager()
        assert manager1 is manager2

    @pytest.mark.asyncio
    async def test_start_and_stop(self, fake_token_usage_repo):
        """Should start and stop cleanly."""
        manager = TokenUsageManager()
        manager.start(flush_interval=10)
        await manager.stop()
        assert fake_token_usage_repo.inserted == []

    @pytest.mark.asyncio
    async def test_record_usage(self, fake_token_usage_repo):
        """Should record token usage."""
        manager = TokenUsageManager()
        manager.start(flush_interval=10)

        await manager.record(
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
        )

        await asyncio.sleep(0.2)
        await manager.stop()
        assert [record.model_name for record in fake_token_usage_repo.inserted] == ["gpt-4"]

    @pytest.mark.asyncio
    async def test_get_summary_empty(self, fake_token_usage_repo):
        """Should return empty summary when no data."""
        manager = TokenUsageManager()
        manager.start(flush_interval=10)

        summary = await manager.get_summary(
            start_date=token_usage_manager_module.date(2026, 6, 8),
            end_date=token_usage_manager_module.date(2026, 6, 8),
        )

        assert summary.total_prompt_tokens == 0
        assert summary.total_completion_tokens == 0
        assert summary.total_calls == 0
        assert summary.by_date["2026-06-08"].call_count == 0
        assert fake_token_usage_repo.inserted == []

        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_details_empty(self, fake_token_usage_repo):
        """Should return empty list when no data."""
        manager = TokenUsageManager()
        manager.start(flush_interval=10)

        details = await manager.get_details()

        assert details == []

        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_details_with_data(self, fake_token_usage_repo):
        """Should return raw records for frontend aggregation."""
        manager = TokenUsageManager()
        manager.start(flush_interval=10)

        # Record some usage
        await manager.record(
            provider_id="openai",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
        )
        await manager.record(
            provider_id="dashscope",
            model_name="qwen3-max",
            prompt_tokens=200,
            completion_tokens=100,
        )

        await asyncio.sleep(0.2)

        details = await manager.get_details()

        # Should have 2 records
        assert len(details) == 2

        # Verify structure
        models = {r.model for r in details}
        assert "gpt-4" in models
        assert "qwen3-max" in models
        assert len(fake_token_usage_repo.inserted) == 2

        await manager.stop()


# =============================================================================
# Test TokenRecordingModelWrapper
# =============================================================================


class TestTokenRecordingModelWrapper:
    """Test TokenRecordingModelWrapper."""

    # pylint: disable=protected-access

    def test_init_wraps_model(self):
        """Should wrap a ChatModelBase instance."""
        mock_model = MagicMock()
        mock_model.model_name = "gpt-4"

        wrapper = TokenRecordingModelWrapper(
            provider_id="openai",
            model=mock_model,
        )

        assert wrapper._provider_id == "openai"
        assert wrapper._model is mock_model
        assert wrapper.model_name == "gpt-4"

    def test_record_usage_with_valid_usage(self):
        """Should record valid usage."""
        mock_model = MagicMock()
        mock_model.model_name = "gpt-4"

        wrapper = TokenRecordingModelWrapper(
            provider_id="openai",
            model=mock_model,
        )

        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50

        wrapper._record_usage(mock_usage)

    def test_pop_usage_for_session(self):
        """Should pop usage for session."""
        # Clear any existing usage
        TokenRecordingModelWrapper._usage_by_session.clear()

        # Add test usage
        TokenRecordingModelWrapper._usage_by_session["test-session"] = {
            "prompt_tokens": 100,
        }

        usage = TokenRecordingModelWrapper.pop_usage_for_session(
            "test-session",
        )
        assert usage is not None
        assert usage["prompt_tokens"] == 100

        # Verify it was removed
        assert (
            TokenRecordingModelWrapper.pop_usage_for_session("test-session")
            is None
        )
