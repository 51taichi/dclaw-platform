# -*- coding: utf-8 -*-
"""Immutable, publication-scoped group history storage for the Open API."""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from ... import db
from ..engine import get_app_engine
from ..schema import (
    create_all,
    open_api_group_histories,
    open_api_group_history_messages,
)
from ..settings import get_storage_settings


class OpenApiGroupHistoryRepository(Protocol):
    def ensure_tables(self) -> None:
        ...

    def append_messages(
        self,
        *,
        publication_id: str,
        external_group_id: str,
        messages: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        ...

    def list_messages(
        self,
        *,
        publication_id: str,
        external_group_id: str,
        from_at: datetime | str | None,
        until_at: datetime | str | None,
        after: str | None,
        limit: int,
    ) -> dict[str, Any]:
        ...


class SqlAlchemyOpenApiGroupHistoryRepository:
    """SQLAlchemy implementation for PostgreSQL and SQLAlchemy SQLite tests."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def ensure_tables(self) -> None:
        create_all(self.engine)

    def append_messages(
        self,
        *,
        publication_id: str,
        external_group_id: str,
        messages: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        history_id = _history_id(publication_id, external_group_id)
        normalized = _normalize_messages(messages)
        now = datetime.now(timezone.utc)
        inserted = 0
        with self.engine.begin() as conn:
            conn.execute(
                _insert_ignore(
                    self.engine,
                    open_api_group_histories,
                    {
                        "id": history_id,
                        "publication_id": _required_text(publication_id, "publication_id"),
                        "external_group_id": _required_text(external_group_id, "external_group_id"),
                        "created_at": now,
                        "updated_at": now,
                    },
                    ["publication_id", "external_group_id"],
                ),
            )
            for message in normalized:
                result = conn.execute(
                    _insert_ignore(
                        self.engine,
                        open_api_group_history_messages,
                        {
                            "id": str(uuid.uuid4()),
                            "history_id": history_id,
                            **message,
                            "created_at": now,
                        },
                        ["history_id", "external_message_id"],
                    ),
                )
                inserted += max(0, int(result.rowcount or 0))
        return {
            "history_id": history_id,
            "inserted": inserted,
            "duplicates": len(normalized) - inserted,
        }

    def list_messages(
        self,
        *,
        publication_id: str,
        external_group_id: str,
        from_at: datetime | str | None,
        until_at: datetime | str | None,
        after: str | None,
        limit: int,
    ) -> dict[str, Any]:
        page_limit = _page_limit(limit)
        history_id = _history_id(publication_id, external_group_id)
        cursor = _decode_cursor(after, history_id) if after else None
        stmt = select(open_api_group_history_messages).where(
            open_api_group_history_messages.c.history_id == history_id,
        )
        normalized_from = _optional_datetime(from_at, "from_at")
        normalized_until = _optional_datetime(until_at, "until_at")
        if normalized_from is not None:
            stmt = stmt.where(
                open_api_group_history_messages.c.occurred_at >= normalized_from,
            )
        if normalized_until is not None:
            stmt = stmt.where(
                open_api_group_history_messages.c.occurred_at <= normalized_until,
            )
        if cursor is not None:
            stmt = stmt.where(
                or_(
                    open_api_group_history_messages.c.occurred_at > cursor[0],
                    and_(
                        open_api_group_history_messages.c.occurred_at == cursor[0],
                        open_api_group_history_messages.c.id > cursor[1],
                    ),
                ),
            )
        stmt = stmt.order_by(
            open_api_group_history_messages.c.occurred_at.asc(),
            open_api_group_history_messages.c.id.asc(),
        ).limit(page_limit + 1)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return _page_result(history_id, rows, page_limit)


class SqliteOpenApiGroupHistoryRepository:
    """Compatibility implementation using the application's sqlite3 connection."""

    def ensure_tables(self) -> None:
        db.init_db()

    def append_messages(
        self,
        *,
        publication_id: str,
        external_group_id: str,
        messages: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        history_id = _history_id(publication_id, external_group_id)
        normalized = _normalize_messages(messages)
        connection = db.get_db()
        connection.execute(
            """
            INSERT OR IGNORE INTO open_api_group_histories (
                id, publication_id, external_group_id, updated_at
            ) VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                history_id,
                _required_text(publication_id, "publication_id"),
                _required_text(external_group_id, "external_group_id"),
            ),
        )
        inserted = 0
        for message in normalized:
            result = connection.execute(
                """
                INSERT OR IGNORE INTO open_api_group_history_messages (
                    id, history_id, external_message_id, occurred_at,
                    sender_id, sender_name, participant_role_id, direction,
                    source, message_type, content, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    history_id,
                    message["external_message_id"],
                    _datetime_text(message["occurred_at"]),
                    message["sender_id"],
                    message["sender_name"],
                    message["participant_role_id"],
                    message["direction"],
                    message["source"],
                    message["message_type"],
                    message["content"],
                    message["metadata"],
                ),
            )
            inserted += max(0, int(result.rowcount or 0))
        connection.commit()
        return {
            "history_id": history_id,
            "inserted": inserted,
            "duplicates": len(normalized) - inserted,
        }

    def list_messages(
        self,
        *,
        publication_id: str,
        external_group_id: str,
        from_at: datetime | str | None,
        until_at: datetime | str | None,
        after: str | None,
        limit: int,
    ) -> dict[str, Any]:
        page_limit = _page_limit(limit)
        history_id = _history_id(publication_id, external_group_id)
        cursor = _decode_cursor(after, history_id) if after else None
        clauses = ["history_id = ?"]
        params: list[Any] = [history_id]
        normalized_from = _optional_datetime(from_at, "from_at")
        normalized_until = _optional_datetime(until_at, "until_at")
        if normalized_from is not None:
            clauses.append("occurred_at >= ?")
            params.append(_datetime_text(normalized_from))
        if normalized_until is not None:
            clauses.append("occurred_at <= ?")
            params.append(_datetime_text(normalized_until))
        if cursor is not None:
            clauses.append("(occurred_at > ? OR (occurred_at = ? AND id > ?))")
            cursor_time = _datetime_text(cursor[0])
            params.extend([cursor_time, cursor_time, cursor[1]])
        params.append(page_limit + 1)
        rows = db.get_db().execute(
            f"""
            SELECT * FROM open_api_group_history_messages
            WHERE {' AND '.join(clauses)}
            ORDER BY occurred_at ASC, id ASC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return _page_result(history_id, rows, page_limit)


def get_open_api_group_history_repository() -> OpenApiGroupHistoryRepository:
    settings = get_storage_settings()
    if settings.database_backend == "postgres":
        return SqlAlchemyOpenApiGroupHistoryRepository(get_app_engine())
    return SqliteOpenApiGroupHistoryRepository()


def _insert_ignore(
    engine: Engine,
    table: Any,
    values: dict[str, Any],
    conflict_columns: list[str],
) -> Any:
    insert_factory = (
        postgres_insert
        if engine.dialect.name == "postgresql"
        else sqlite_insert
    )
    return insert_factory(table).values(**values).on_conflict_do_nothing(
        index_elements=[table.c[column] for column in conflict_columns],
    )


def _history_id(publication_id: str, external_group_id: str) -> str:
    publication = _required_text(publication_id, "publication_id")
    group = _required_text(external_group_id, "external_group_id")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"dclaw-group-history:{publication}:{group}"))


def _normalize_messages(messages: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(messages, (str, bytes)) or not isinstance(messages, Sequence):
        raise ValueError("messages must be a sequence")
    if not messages or len(messages) > 200:
        raise ValueError("messages must contain between 1 and 200 items")
    return [_normalize_message(message) for message in messages]


def _normalize_message(message: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(message, dict):
        raise ValueError("message must be an object")
    direction = _required_text(message.get("direction"), "direction")
    if direction not in {"inbound", "outbound"}:
        raise ValueError("direction must be inbound or outbound")
    metadata = message.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    return {
        "external_message_id": _required_text(
            message.get("external_message_id"),
            "external_message_id",
        ),
        "occurred_at": _required_datetime(message.get("occurred_at"), "occurred_at"),
        "sender_id": str(message.get("sender_id") or ""),
        "sender_name": _required_text(message.get("sender_name"), "sender_name"),
        "participant_role_id": str(message.get("participant_role_id") or ""),
        "direction": direction,
        "source": _required_text(message.get("source"), "source"),
        "message_type": _required_text(message.get("message_type"), "message_type"),
        "content": str(message.get("content") or ""),
        "metadata": json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
    }


def _page_result(history_id: str, rows: Sequence[Any], limit: int) -> dict[str, Any]:
    has_more = len(rows) > limit
    selected = list(rows[:limit])
    messages = [_message_row(row) for row in selected]
    next_cursor = None
    if has_more and selected:
        last = dict(selected[-1])
        next_cursor = _encode_cursor(
            history_id,
            _required_datetime(last["occurred_at"], "occurred_at"),
            str(last["id"]),
        )
    return {
        "messages": messages,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def _message_row(row: Any) -> dict[str, Any]:
    value = dict(row)
    return {
        "external_message_id": str(value["external_message_id"]),
        "occurred_at": _required_datetime(value["occurred_at"], "occurred_at"),
        "sender_id": str(value.get("sender_id") or ""),
        "sender_name": str(value["sender_name"]),
        "participant_role_id": str(value.get("participant_role_id") or ""),
        "direction": str(value["direction"]),
        "source": str(value["source"]),
        "message_type": str(value["message_type"]),
        "content": str(value.get("content") or ""),
        "metadata": _metadata_value(value.get("metadata")),
    }


def _encode_cursor(history_id: str, occurred_at: datetime, row_id: str) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "h": history_id,
            "t": _datetime_text(occurred_at),
            "i": row_id,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(value: str, expected_history_id: str) -> tuple[datetime, str]:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii")).decode("utf-8"),
        )
        if (
            payload.get("v") != 1
            or payload.get("h") != expected_history_id
            or not payload.get("i")
        ):
            raise ValueError
        return _required_datetime(payload.get("t"), "cursor timestamp"), str(payload["i"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("invalid group history cursor") from exc


def _page_limit(value: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be between 1 and 500") from exc
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    return limit


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _required_datetime(value: datetime | str | None, field: str) -> datetime:
    parsed = _optional_datetime(value, field)
    if parsed is None:
        raise ValueError(f"{field} is required")
    return parsed


def _optional_datetime(value: datetime | str | None, field: str) -> datetime | None:
    if value is None or value == "":
        return None
    parsed = value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO datetime") from exc
    if not isinstance(parsed, datetime):
        raise ValueError(f"{field} must be a datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _datetime_text(value: datetime) -> str:
    return _required_datetime(value, "datetime").isoformat(timespec="microseconds")


def _metadata_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value in {None, ""}:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise ValueError("stored group history metadata is invalid") from exc
    if not isinstance(parsed, dict):
        raise ValueError("stored group history metadata must be an object")
    return parsed
