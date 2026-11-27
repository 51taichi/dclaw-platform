# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import insert

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.token_usage_repo import (
    SqlAlchemyTokenUsageRepository,
    TokenUsageLogRecord,
)
from qwenpaw.app.storage.schema import create_all, users
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def engine(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")})
    engine = create_engine_from_settings(settings)
    create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            insert(users),
            [
                {
                    "id": 1,
                    "username": "alice",
                    "password_hash": "hash",
                    "password_salt": "salt",
                    "role": "user",
                },
                {
                    "id": 2,
                    "username": "bob",
                    "password_hash": "hash",
                    "password_salt": "salt",
                    "role": "user",
                },
            ],
        )
    return engine


@pytest.fixture
def repo(engine):
    return SqlAlchemyTokenUsageRepository(engine)


def test_sqlalchemy_token_usage_repo_inserts_and_summarizes(repo):
    repo.insert_events(
        [
            TokenUsageLogRecord(
                id="usage-1",
                user_id="1",
                model_name="glm-4.7",
                prompt_tokens=100,
                completion_tokens=50,
                created_at=datetime(2026, 6, 8, 1, 0, tzinfo=timezone.utc),
            ),
            TokenUsageLogRecord(
                id="usage-2",
                user_id="1",
                model_name="glm-4.7",
                prompt_tokens=10,
                completion_tokens=5,
                created_at=datetime(2026, 6, 8, 2, 0, tzinfo=timezone.utc),
            ),
            TokenUsageLogRecord(
                id="usage-3",
                user_id="2",
                model_name="qwen-max",
                prompt_tokens=7,
                completion_tokens=3,
                created_at=datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc),
            ),
        ]
    )

    rows = repo.get_summary_rows(
        start_date=date(2026, 6, 8),
        end_date=date(2026, 6, 9),
    )

    assert [
        (
            row["usage_date"],
            row["model_name"],
            row["prompt_tokens"],
            row["completion_tokens"],
            row["call_count"],
        )
        for row in rows
    ] == [
        ("2026-06-08", "glm-4.7", 110, 55, 2),
        ("2026-06-09", "qwen-max", 7, 3, 1),
    ]


def test_sqlalchemy_token_usage_repo_filters_and_groups_details(repo):
    repo.insert_events(
        [
            TokenUsageLogRecord(
                id="usage-1",
                user_id="1",
                model_name="glm-4.7",
                prompt_tokens=100,
                completion_tokens=50,
                created_at=datetime(2026, 6, 8, 1, 0, tzinfo=timezone.utc),
            ),
            TokenUsageLogRecord(
                id="usage-2",
                user_id="2",
                model_name="glm-4.7",
                prompt_tokens=20,
                completion_tokens=10,
                created_at=datetime(2026, 6, 8, 2, 0, tzinfo=timezone.utc),
            ),
            TokenUsageLogRecord(
                id="usage-3",
                user_id="1",
                model_name="qwen-max",
                prompt_tokens=7,
                completion_tokens=3,
                created_at=datetime(2026, 6, 8, 3, 0, tzinfo=timezone.utc),
            ),
        ]
    )

    rows = repo.get_detail_rows(
        start_date=date(2026, 6, 8),
        end_date=date(2026, 6, 8),
        model_name="glm-4.7",
        user_id="1",
    )

    assert rows == [
        {
            "usage_date": "2026-06-08",
            "user_id": "1",
            "model_name": "glm-4.7",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "call_count": 1,
        }
    ]
