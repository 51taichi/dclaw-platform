# -*- coding: utf-8 -*-
"""Token usage repositories for durable usage accounting."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Engine

from ... import db
from ..engine import get_app_engine
from ..schema import token_usage_logs
from ..settings import get_storage_settings


@dataclass(frozen=True)
class TokenUsageLogRecord:
    """One token usage event ready for durable insertion."""

    id: str
    user_id: str | int | None
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    created_at: datetime | str


class TokenUsageRepository(Protocol):
    def insert_events(self, records: list[TokenUsageLogRecord]) -> None:
        ...

    def get_summary_rows(
        self,
        *,
        start_date: date,
        end_date: date,
        model_name: str | None = None,
        provider_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        ...

    def get_detail_rows(
        self,
        *,
        start_date: date,
        end_date: date,
        model_name: str | None = None,
        provider_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        ...


class SqlAlchemyTokenUsageRepository:
    """SQLAlchemy implementation for Postgres and SQLAlchemy-backed tests."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def insert_events(self, records: list[TokenUsageLogRecord]) -> None:
        if not records:
            return
        payload = [_record_to_payload(record) for record in records]
        with self.engine.begin() as conn:
            conn.execute(insert(token_usage_logs), payload)

    def get_summary_rows(
        self,
        *,
        start_date: date,
        end_date: date,
        model_name: str | None = None,
        provider_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        del provider_id
        stored_user_id = _storage_user_id(user_id)
        if user_id and stored_user_id is None:
            return []

        usage_date = func.date(token_usage_logs.c.created_at).label("usage_date")
        stmt = (
            select(
                usage_date,
                token_usage_logs.c.model_name,
                func.sum(token_usage_logs.c.prompt_tokens).label("prompt_tokens"),
                func.sum(token_usage_logs.c.completion_tokens).label(
                    "completion_tokens",
                ),
                func.count(token_usage_logs.c.id).label("call_count"),
            )
            .where(*_created_at_range(start_date, end_date))
            .group_by(usage_date, token_usage_logs.c.model_name)
            .order_by(usage_date, token_usage_logs.c.model_name)
        )
        if model_name:
            stmt = stmt.where(token_usage_logs.c.model_name == model_name)
        if stored_user_id is not None:
            stmt = stmt.where(token_usage_logs.c.user_id == stored_user_id)

        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
            return [_normalize_aggregate_row(row) for row in rows]

    def get_detail_rows(
        self,
        *,
        start_date: date,
        end_date: date,
        model_name: str | None = None,
        provider_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        del provider_id
        stored_user_id = _storage_user_id(user_id)
        if user_id and stored_user_id is None:
            return []

        usage_date = func.date(token_usage_logs.c.created_at).label("usage_date")
        stmt = (
            select(
                usage_date,
                token_usage_logs.c.user_id,
                token_usage_logs.c.model_name,
                func.sum(token_usage_logs.c.prompt_tokens).label("prompt_tokens"),
                func.sum(token_usage_logs.c.completion_tokens).label(
                    "completion_tokens",
                ),
                func.count(token_usage_logs.c.id).label("call_count"),
            )
            .where(*_created_at_range(start_date, end_date))
            .group_by(
                usage_date,
                token_usage_logs.c.user_id,
                token_usage_logs.c.model_name,
            )
            .order_by(usage_date, token_usage_logs.c.user_id, token_usage_logs.c.model_name)
        )
        if model_name:
            stmt = stmt.where(token_usage_logs.c.model_name == model_name)
        if stored_user_id is not None:
            stmt = stmt.where(token_usage_logs.c.user_id == stored_user_id)

        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
            return [_normalize_aggregate_row(row, include_user=True) for row in rows]


class SqliteTokenUsageRepository:
    """SQLite compatibility implementation using the existing sqlite3 module."""

    def insert_events(self, records: list[TokenUsageLogRecord]) -> None:
        if not records:
            return
        conn = db.get_db()
        conn.executemany(
            """
            INSERT INTO token_usage_logs (
                id, user_id, model_name, prompt_tokens, completion_tokens, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    record.id,
                    _storage_user_id(record.user_id),
                    record.model_name,
                    int(record.prompt_tokens),
                    int(record.completion_tokens),
                    _parse_datetime(record.created_at).isoformat(),
                )
                for record in records
            ],
        )
        conn.commit()

    def get_summary_rows(
        self,
        *,
        start_date: date,
        end_date: date,
        model_name: str | None = None,
        provider_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        del provider_id
        stored_user_id = _storage_user_id(user_id)
        if user_id and stored_user_id is None:
            return []

        query = """
            SELECT
                date(created_at) AS usage_date,
                model_name,
                SUM(prompt_tokens) AS prompt_tokens,
                SUM(completion_tokens) AS completion_tokens,
                COUNT(id) AS call_count
            FROM token_usage_logs
            WHERE date(created_at) >= ? AND date(created_at) <= ?
        """
        params: list[Any] = [start_date.isoformat(), end_date.isoformat()]
        if model_name:
            query += " AND model_name = ?"
            params.append(model_name)
        if stored_user_id is not None:
            query += " AND user_id = ?"
            params.append(stored_user_id)
        query += " GROUP BY usage_date, model_name ORDER BY usage_date, model_name"

        rows = db.get_db().execute(query, params).fetchall()
        return [_normalize_aggregate_row(dict(row)) for row in rows]

    def get_detail_rows(
        self,
        *,
        start_date: date,
        end_date: date,
        model_name: str | None = None,
        provider_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        del provider_id
        stored_user_id = _storage_user_id(user_id)
        if user_id and stored_user_id is None:
            return []

        query = """
            SELECT
                date(created_at) AS usage_date,
                user_id,
                model_name,
                SUM(prompt_tokens) AS prompt_tokens,
                SUM(completion_tokens) AS completion_tokens,
                COUNT(id) AS call_count
            FROM token_usage_logs
            WHERE date(created_at) >= ? AND date(created_at) <= ?
        """
        params: list[Any] = [start_date.isoformat(), end_date.isoformat()]
        if model_name:
            query += " AND model_name = ?"
            params.append(model_name)
        if stored_user_id is not None:
            query += " AND user_id = ?"
            params.append(stored_user_id)
        query += """
            GROUP BY usage_date, user_id, model_name
            ORDER BY usage_date, user_id, model_name
        """

        rows = db.get_db().execute(query, params).fetchall()
        return [_normalize_aggregate_row(dict(row), include_user=True) for row in rows]


def get_token_usage_repository() -> TokenUsageRepository:
    settings = get_storage_settings()
    if settings.database_backend == "postgres":
        return SqlAlchemyTokenUsageRepository(get_app_engine())
    return SqliteTokenUsageRepository()


def _record_to_payload(record: TokenUsageLogRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "user_id": _storage_user_id(record.user_id),
        "model_name": record.model_name,
        "prompt_tokens": int(record.prompt_tokens),
        "completion_tokens": int(record.completion_tokens),
        "created_at": _parse_datetime(record.created_at),
    }


def _created_at_range(start_date: date, end_date: date):
    start_at = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return (
        token_usage_logs.c.created_at >= start_at,
        token_usage_logs.c.created_at < end_at,
    )


def _parse_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _storage_user_id(value: str | int | None) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text) if text.isdigit() else None


def _normalize_aggregate_row(
    row: dict[str, Any],
    *,
    include_user: bool = False,
) -> dict[str, Any]:
    result = {
        "usage_date": _date_text(row["usage_date"]),
        "model_name": row["model_name"],
        "prompt_tokens": int(row["prompt_tokens"] or 0),
        "completion_tokens": int(row["completion_tokens"] or 0),
        "call_count": int(row["call_count"] or 0),
    }
    if include_user:
        user_id = row.get("user_id")
        result["user_id"] = str(user_id) if user_id is not None else None
    return result


def _date_text(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)
