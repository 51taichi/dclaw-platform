#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migrate QwenPaw SQLite app data into a SQLAlchemy target database."""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, DateTime, create_engine, func, inspect, insert, select
from sqlalchemy.engine import Engine

from qwenpaw.app.storage.schema import (
    capability_registry,
    chats,
    create_all,
    expert_team_member_runs,
    expert_team_runs,
    expert_team_templates,
    messages,
    session_states,
    token_usage_logs,
    user_capabilities,
    user_connections,
    users,
)
from qwenpaw.app.storage.settings import normalize_postgres_url, redact_url


class MigrationError(RuntimeError):
    """Raised when a migration safeguard blocks execution."""


TABLES = [
    users,
    capability_registry,
    user_connections,
    user_capabilities,
    chats,
    messages,
    session_states,
    token_usage_logs,
    expert_team_templates,
    expert_team_runs,
    expert_team_member_runs,
]

FK_PARENT_COLUMNS = {
    user_connections.name: [("user_id", users.name, "id")],
    user_capabilities.name: [
        ("user_id", users.name, "id"),
        ("capability_id", capability_registry.name, "id"),
    ],
    messages.name: [("chat_id", chats.name, "id")],
    session_states.name: [("chat_id", chats.name, "id")],
    token_usage_logs.name: [("user_id", users.name, "id")],
    expert_team_runs.name: [("team_id", expert_team_templates.name, "id")],
    expert_team_member_runs.name: [("run_id", expert_team_runs.name, "id")],
}


def migrate_sqlite_to_target(
    *,
    sqlite_path: Path,
    target_url: str,
    dry_run: bool,
    execute: bool,
    allow_non_empty_target: bool = False,
) -> dict[str, Any]:
    """Migrate SQLite rows into the target database.

    ``target_url`` is usually a Postgres SQLAlchemy URL. Tests may pass a
    SQLite URL so the migration rules remain unit-testable without Docker.
    """
    sqlite_path = Path(sqlite_path)
    if not sqlite_path.exists():
        raise MigrationError(f"SQLite source does not exist: {sqlite_path}")
    if dry_run == execute:
        raise MigrationError("Choose exactly one of dry_run=True or execute=True")

    normalized_target_url = normalize_postgres_url(target_url)
    source_conn = _open_source(sqlite_path)
    try:
        source_tables = _source_table_names(source_conn)
        source_counts = _source_counts(source_conn, source_tables)
        result: dict[str, Any] = {
            "mode": "dry-run" if dry_run else "execute",
            "sqlite_path": str(sqlite_path),
            "target_url": redact_url(normalized_target_url),
            "source_counts": source_counts,
        }

        engine = create_engine(normalized_target_url, future=True)
        _check_target_reachable(engine)
        result["target_reachable"] = True

        if dry_run:
            return result

        create_all(engine)
        target_counts = _target_counts(engine)
        result["target_counts_before"] = target_counts
        non_empty = {name: count for name, count in target_counts.items() if count > 0}
        if non_empty and not allow_non_empty_target:
            raise MigrationError(
                "target is not empty; pass --allow-non-empty-target to continue: "
                + json.dumps(non_empty, ensure_ascii=False, sort_keys=True),
            )

        inserted_counts, skipped_counts = _copy_rows(source_conn, source_tables, engine)
        result["inserted_counts"] = inserted_counts
        result["skipped_counts"] = skipped_counts
        result["target_counts_after"] = _target_counts(engine)
        return result
    finally:
        source_conn.close()


def _open_source(sqlite_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn


def _source_table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'",
    ).fetchall()
    return {str(row["name"]) for row in rows}


def _source_counts(conn: sqlite3.Connection, source_tables: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in TABLES:
        if table.name not in source_tables:
            counts[table.name] = 0
            continue
        row = conn.execute(f'SELECT COUNT(*) AS count FROM "{table.name}"').fetchone()
        counts[table.name] = int(row["count"] if row else 0)
    return counts


def _check_target_reachable(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(select(1)).scalar_one()


def _target_counts(engine: Engine) -> dict[str, int]:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for table in TABLES:
            if table.name not in existing_tables:
                counts[table.name] = 0
                continue
            counts[table.name] = int(
                conn.execute(select(func.count()).select_from(table)).scalar_one(),
            )
    return counts


def _copy_rows(
    source_conn: sqlite3.Connection,
    source_tables: set[str],
    engine: Engine,
) -> tuple[dict[str, int], dict[str, int]]:
    inserted: dict[str, int] = {}
    skipped: dict[str, int] = {}
    with engine.begin() as target_conn:
        for table in TABLES:
            if table.name not in source_tables:
                inserted[table.name] = 0
                skipped[table.name] = 0
                continue

            rows = source_conn.execute(f'SELECT * FROM "{table.name}"').fetchall()
            if not rows:
                inserted[table.name] = 0
                skipped[table.name] = 0
                continue

            rows, skipped_count = _filter_rows_with_missing_parents(
                source_conn,
                source_tables,
                table.name,
                rows,
            )
            skipped[table.name] = skipped_count
            if not rows:
                inserted[table.name] = 0
                continue

            source_columns = set(rows[0].keys())
            payload = [
                _row_payload(table, row, source_columns)
                for row in rows
            ]
            target_conn.execute(insert(table), payload)
            inserted[table.name] = len(payload)
    return inserted, skipped


def _filter_rows_with_missing_parents(
    conn: sqlite3.Connection,
    source_tables: set[str],
    table_name: str,
    rows: list[sqlite3.Row],
) -> tuple[list[sqlite3.Row], int]:
    parent_specs = FK_PARENT_COLUMNS.get(table_name)
    if not parent_specs:
        return rows, 0

    parent_values: dict[str, set[Any]] = {}
    for fk_column, parent_table, parent_column in parent_specs:
        if parent_table not in source_tables:
            parent_values[fk_column] = set()
            continue
        parent_rows = conn.execute(
            f'SELECT "{parent_column}" AS value FROM "{parent_table}"',
        ).fetchall()
        parent_values[fk_column] = {row["value"] for row in parent_rows}

    kept: list[sqlite3.Row] = []
    for row in rows:
        keep = True
        for fk_column, _, _ in parent_specs:
            value = row[fk_column]
            if value is None:
                continue
            if value not in parent_values[fk_column]:
                keep = False
                break
        if keep:
            kept.append(row)

    return kept, len(rows) - len(kept)


def _row_payload(table, row: sqlite3.Row, source_columns: set[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for column in table.columns:
        if column.name not in source_columns:
            continue
        value = row[column.name]
        payload[column.name] = _normalize_value(table.name, column, value)
    return payload


def _normalize_value(table_name: str, column, value: Any) -> Any:
    if value is None:
        return None
    if table_name == "chats" and column.name == "user_id":
        return str(value)
    if isinstance(column.type, Boolean):
        return bool(value)
    if isinstance(column.type, DateTime):
        return _parse_datetime(value)
    return value


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return datetime.now(timezone.utc)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        # SQLite CURRENT_TIMESTAMP often returns "YYYY-MM-DD HH:MM:SS".
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite-path", required=True, type=Path)
    parser.add_argument("--postgres-url", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-non-empty-target", action="store_true")
    args = parser.parse_args()

    try:
        result = migrate_sqlite_to_target(
            sqlite_path=args.sqlite_path,
            target_url=args.postgres_url,
            dry_run=args.dry_run,
            execute=args.execute,
            allow_non_empty_target=args.allow_non_empty_target,
        )
    except MigrationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2

    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
