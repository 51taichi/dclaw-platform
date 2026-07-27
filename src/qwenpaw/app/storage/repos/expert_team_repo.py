# -*- coding: utf-8 -*-
"""Repositories for expert team templates and runs."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine

from ... import db
from ..engine import get_app_engine
from ..schema import (
    create_all,
    expert_team_member_runs,
    expert_team_runs,
    expert_team_templates,
)
from ..settings import get_storage_settings


class ExpertTeamRepository(Protocol):
    def ensure_tables(self) -> None:
        ...

    def seed_builtin_templates(self, rows: list[dict[str, Any]]) -> None:
        ...

    def list_template_rows(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        ...

    def get_template_row(self, team_id: str) -> dict[str, Any] | None:
        ...

    def upsert_template_row(self, row: dict[str, Any]) -> None:
        ...

    def delete_template(self, team_id: str) -> bool:
        ...

    def create_run(
        self,
        *,
        run_row: dict[str, Any],
        member_rows: list[dict[str, Any]],
        team_id: str,
    ) -> None:
        ...

    def get_run_row(self, run_id: str) -> dict[str, Any] | None:
        ...

    def list_member_run_rows(self, run_id: str) -> list[dict[str, Any]]:
        ...

    def get_latest_run_id_by_chat(self, chat_id: str) -> str | None:
        ...

    def update_run_state(
        self,
        run_id: str,
        state: str,
        *,
        final_summary: str | None = None,
        error: str | None = None,
    ) -> None:
        ...

    def update_member_run_state(
        self,
        run_id: str,
        member_key: str,
        state: str,
        *,
        input_text: str | None = None,
        output_text: str | None = None,
        error: str | None = None,
        task_id: str | None = None,
    ) -> None:
        ...

    def cancel_open_member_runs(self, run_id: str) -> None:
        ...

    def fail_open_member_runs(self, run_id: str, error: str) -> None:
        ...


class SqlAlchemyExpertTeamRepository:
    """SQLAlchemy implementation for Postgres and SQLAlchemy-backed tests."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def ensure_tables(self) -> None:
        create_all(self.engine)

    def seed_builtin_templates(self, rows: list[dict[str, Any]]) -> None:
        now = _now()
        with self.engine.begin() as conn:
            for row in rows:
                values = dict(row)
                values.setdefault("usage_count", 0)
                values["updated_at"] = now
                existing = conn.execute(
                    select(expert_team_templates.c.id).where(
                        expert_team_templates.c.id == values["id"],
                    ),
                ).first()
                if existing:
                    conn.execute(
                        update(expert_team_templates)
                        .where(expert_team_templates.c.id == values["id"])
                        .values(
                            name=values["name"],
                            description=values.get("description", ""),
                            category=values.get("category", "all"),
                            tags=values["tags"],
                            icon=values.get("icon", ""),
                            leader_agent_id=values.get("leader_agent_id", "default"),
                            members=values["members"],
                            workflow=values["workflow"],
                            source=values.get("source", "builtin"),
                            sort_order=int(values.get("sort_order", 0)),
                            updated_at=now,
                        ),
                    )
                else:
                    values.setdefault("created_at", now)
                    conn.execute(insert(expert_team_templates).values(**values))

    def list_template_rows(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        stmt = select(expert_team_templates)
        if enabled_only:
            stmt = stmt.where(expert_team_templates.c.enabled.is_(True))
        stmt = stmt.order_by(
            expert_team_templates.c.sort_order.asc(),
            expert_team_templates.c.usage_count.desc(),
            expert_team_templates.c.updated_at.desc(),
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def get_template_row(self, team_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(expert_team_templates).where(expert_team_templates.c.id == team_id),
            ).mappings().first()
        return dict(row) if row else None

    def upsert_template_row(self, row: dict[str, Any]) -> None:
        now = _now()
        values = dict(row)
        values["updated_at"] = now
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(expert_team_templates.c.id).where(
                    expert_team_templates.c.id == values["id"],
                ),
            ).first()
            if existing:
                conn.execute(
                    update(expert_team_templates)
                    .where(expert_team_templates.c.id == values["id"])
                    .values(**values),
                )
            else:
                values.setdefault("created_at", now)
                conn.execute(insert(expert_team_templates).values(**values))

    def delete_template(self, team_id: str) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(
                delete(expert_team_templates).where(expert_team_templates.c.id == team_id),
            )
        return bool(result.rowcount and result.rowcount > 0)

    def create_run(
        self,
        *,
        run_row: dict[str, Any],
        member_rows: list[dict[str, Any]],
        team_id: str,
    ) -> None:
        now = _now()
        with self.engine.begin() as conn:
            conn.execute(insert(expert_team_runs).values(**_with_timestamps(run_row, now)))
            if member_rows:
                conn.execute(
                    insert(expert_team_member_runs),
                    [_with_timestamps(row, now) for row in member_rows],
                )
            conn.execute(
                update(expert_team_templates)
                .where(expert_team_templates.c.id == team_id)
                .values(
                    usage_count=expert_team_templates.c.usage_count + 1,
                    updated_at=now,
                ),
            )

    def get_run_row(self, run_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(expert_team_runs).where(expert_team_runs.c.id == run_id),
            ).mappings().first()
        return dict(row) if row else None

    def list_member_run_rows(self, run_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(expert_team_member_runs)
            .where(expert_team_member_runs.c.run_id == run_id)
            .order_by(
                expert_team_member_runs.c.stage_index.asc(),
                expert_team_member_runs.c.created_at.asc(),
            )
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def get_latest_run_id_by_chat(self, chat_id: str) -> str | None:
        stmt = (
            select(expert_team_runs.c.id)
            .where(expert_team_runs.c.root_chat_id == chat_id)
            .order_by(expert_team_runs.c.created_at.desc())
            .limit(1)
        )
        with self.engine.connect() as conn:
            row = conn.execute(stmt).first()
        return str(row[0]) if row else None

    def update_run_state(
        self,
        run_id: str,
        state: str,
        *,
        final_summary: str | None = None,
        error: str | None = None,
    ) -> None:
        values: dict[str, Any] = {"state": state, "updated_at": _now()}
        if final_summary is not None:
            values["final_summary"] = final_summary
        if error is not None:
            values["error"] = error
        if _terminal(state):
            values["finished_at"] = _now()
        with self.engine.begin() as conn:
            conn.execute(
                update(expert_team_runs)
                .where(expert_team_runs.c.id == run_id)
                .values(**values),
            )

    def update_member_run_state(
        self,
        run_id: str,
        member_key: str,
        state: str,
        *,
        input_text: str | None = None,
        output_text: str | None = None,
        error: str | None = None,
        task_id: str | None = None,
    ) -> None:
        values: dict[str, Any] = {"state": state, "updated_at": _now()}
        if input_text is not None:
            values["input_text"] = input_text
        if output_text is not None:
            values["output_text"] = output_text
        if error is not None:
            values["error"] = error
        if task_id is not None:
            values["task_id"] = task_id
        if state == "running":
            values["started_at"] = _now()
        if _terminal(state):
            values["finished_at"] = _now()
        with self.engine.begin() as conn:
            conn.execute(
                update(expert_team_member_runs)
                .where(
                    expert_team_member_runs.c.run_id == run_id,
                    expert_team_member_runs.c.member_key == member_key,
                )
                .values(**values),
            )

    def cancel_open_member_runs(self, run_id: str) -> None:
        self._update_open_members(run_id, {"state": "cancelled", "finished_at": _now()})

    def fail_open_member_runs(self, run_id: str, error: str) -> None:
        self._update_open_members(
            run_id,
            {"state": "failed", "error": error, "finished_at": _now()},
        )

    def _update_open_members(self, run_id: str, values: dict[str, Any]) -> None:
        values = {**values, "updated_at": _now()}
        with self.engine.begin() as conn:
            conn.execute(
                update(expert_team_member_runs)
                .where(
                    expert_team_member_runs.c.run_id == run_id,
                    expert_team_member_runs.c.state.in_(["pending", "running"]),
                )
                .values(**values),
            )


class SqliteExpertTeamRepository:
    """SQLite compatibility implementation using the existing sqlite3 module."""

    def ensure_tables(self) -> None:
        conn = db.get_db()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expert_team_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                category TEXT DEFAULT 'all',
                tags TEXT NOT NULL DEFAULT '[]',
                icon TEXT DEFAULT '',
                enabled BOOLEAN DEFAULT 1,
                leader_agent_id TEXT NOT NULL DEFAULT 'default',
                members TEXT NOT NULL DEFAULT '[]',
                workflow TEXT NOT NULL DEFAULT '[]',
                usage_count INTEGER DEFAULT 0,
                source TEXT DEFAULT 'custom',
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expert_team_runs (
                id TEXT PRIMARY KEY,
                team_id TEXT NOT NULL,
                root_chat_id TEXT NOT NULL,
                root_session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                state TEXT DEFAULT 'pending',
                input_text TEXT DEFAULT '',
                final_summary TEXT,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP
            )
            """,
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expert_team_member_runs (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                member_key TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                role TEXT DEFAULT '',
                avatar TEXT DEFAULT '',
                state TEXT DEFAULT 'pending',
                stage_index INTEGER DEFAULT 0,
                task_id TEXT,
                child_session_id TEXT,
                input_text TEXT DEFAULT '',
                output_text TEXT,
                error TEXT,
                started_at TIMESTAMP,
                finished_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
        )
        conn.commit()

    def seed_builtin_templates(self, rows: list[dict[str, Any]]) -> None:
        conn = db.get_db()
        for row in rows:
            conn.execute(
                """
                INSERT INTO expert_team_templates (
                    id, name, description, category, tags, icon, enabled,
                    leader_agent_id, members, workflow, usage_count, source,
                    sort_order, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    category=excluded.category,
                    tags=excluded.tags,
                    icon=excluded.icon,
                    leader_agent_id=excluded.leader_agent_id,
                    members=excluded.members,
                    workflow=excluded.workflow,
                    source=excluded.source,
                    sort_order=excluded.sort_order,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    row["id"],
                    row["name"],
                    row.get("description", ""),
                    row.get("category", "all"),
                    row["tags"],
                    row.get("icon", ""),
                    1 if row.get("enabled", True) else 0,
                    row.get("leader_agent_id", "default"),
                    row["members"],
                    row["workflow"],
                    row.get("source", "builtin"),
                    int(row.get("sort_order", 0)),
                ),
            )
        conn.commit()

    def list_template_rows(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM expert_team_templates"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY sort_order ASC, usage_count DESC, updated_at DESC"
        rows = db.get_db().execute(sql).fetchall()
        return [dict(row) for row in rows]

    def get_template_row(self, team_id: str) -> dict[str, Any] | None:
        row = db.get_db().execute(
            "SELECT * FROM expert_team_templates WHERE id = ?",
            (team_id,),
        ).fetchone()
        return dict(row) if row else None

    def upsert_template_row(self, row: dict[str, Any]) -> None:
        db.get_db().execute(
            """
            INSERT INTO expert_team_templates (
                id, name, description, category, tags, icon, enabled,
                leader_agent_id, members, workflow, source, sort_order, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                description=excluded.description,
                category=excluded.category,
                tags=excluded.tags,
                icon=excluded.icon,
                enabled=excluded.enabled,
                leader_agent_id=excluded.leader_agent_id,
                members=excluded.members,
                workflow=excluded.workflow,
                source=excluded.source,
                sort_order=excluded.sort_order,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                row["id"],
                row["name"],
                row.get("description", ""),
                row.get("category", "all"),
                row["tags"],
                row.get("icon", ""),
                1 if row.get("enabled", True) else 0,
                row.get("leader_agent_id", "default"),
                row["members"],
                row["workflow"],
                row.get("source", "custom"),
                int(row.get("sort_order", 0)),
            ),
        )
        db.get_db().commit()

    def delete_template(self, team_id: str) -> bool:
        cur = db.get_db().execute(
            "DELETE FROM expert_team_templates WHERE id = ?",
            (team_id,),
        )
        db.get_db().commit()
        return cur.rowcount > 0

    def create_run(
        self,
        *,
        run_row: dict[str, Any],
        member_rows: list[dict[str, Any]],
        team_id: str,
    ) -> None:
        conn = db.get_db()
        conn.execute(
            """
            INSERT INTO expert_team_runs (
                id, team_id, root_chat_id, root_session_id, user_id, state,
                input_text, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (
                run_row["id"],
                run_row["team_id"],
                run_row["root_chat_id"],
                run_row["root_session_id"],
                run_row["user_id"],
                run_row.get("state", "pending"),
                run_row.get("input_text", ""),
            ),
        )
        for row in member_rows:
            conn.execute(
                """
                INSERT INTO expert_team_member_runs (
                    id, run_id, member_key, agent_id, display_name, role, avatar,
                    state, stage_index, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    row["id"],
                    row["run_id"],
                    row["member_key"],
                    row["agent_id"],
                    row["display_name"],
                    row.get("role", ""),
                    row.get("avatar", ""),
                    row.get("state", "pending"),
                    int(row.get("stage_index", 0)),
                ),
            )
        conn.execute(
            """
            UPDATE expert_team_templates
            SET usage_count = usage_count + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (team_id,),
        )
        conn.commit()

    def get_run_row(self, run_id: str) -> dict[str, Any] | None:
        row = db.get_db().execute(
            "SELECT * FROM expert_team_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_member_run_rows(self, run_id: str) -> list[dict[str, Any]]:
        rows = db.get_db().execute(
            """
            SELECT * FROM expert_team_member_runs
            WHERE run_id = ?
            ORDER BY stage_index ASC, created_at ASC
            """,
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_latest_run_id_by_chat(self, chat_id: str) -> str | None:
        row = db.get_db().execute(
            """
            SELECT id FROM expert_team_runs
            WHERE root_chat_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (chat_id,),
        ).fetchone()
        return str(row["id"]) if row else None

    def update_run_state(
        self,
        run_id: str,
        state: str,
        *,
        final_summary: str | None = None,
        error: str | None = None,
    ) -> None:
        finished_at = "CURRENT_TIMESTAMP" if _terminal(state) else "finished_at"
        db.get_db().execute(
            f"""
            UPDATE expert_team_runs
            SET state = ?, final_summary = COALESCE(?, final_summary),
                error = COALESCE(?, error), updated_at = CURRENT_TIMESTAMP,
                finished_at = {finished_at}
            WHERE id = ?
            """,
            (state, final_summary, error, run_id),
        )
        db.get_db().commit()

    def update_member_run_state(
        self,
        run_id: str,
        member_key: str,
        state: str,
        *,
        input_text: str | None = None,
        output_text: str | None = None,
        error: str | None = None,
        task_id: str | None = None,
    ) -> None:
        started_at = "CURRENT_TIMESTAMP" if state == "running" else "started_at"
        finished_at = "CURRENT_TIMESTAMP" if _terminal(state) else "finished_at"
        db.get_db().execute(
            f"""
            UPDATE expert_team_member_runs
            SET state = ?,
                input_text = COALESCE(?, input_text),
                output_text = COALESCE(?, output_text),
                error = COALESCE(?, error),
                task_id = COALESCE(?, task_id),
                started_at = {started_at},
                finished_at = {finished_at},
                updated_at = CURRENT_TIMESTAMP
            WHERE run_id = ? AND member_key = ?
            """,
            (state, input_text, output_text, error, task_id, run_id, member_key),
        )
        db.get_db().commit()

    def cancel_open_member_runs(self, run_id: str) -> None:
        self._update_open_member_runs(run_id, "cancelled")

    def fail_open_member_runs(self, run_id: str, error: str) -> None:
        self._update_open_member_runs(run_id, "failed", error=error)

    def _update_open_member_runs(self, run_id: str, state: str, error: str | None = None) -> None:
        db.get_db().execute(
            """
            UPDATE expert_team_member_runs
            SET state = ?, error = COALESCE(?, error), updated_at = CURRENT_TIMESTAMP,
                finished_at = CURRENT_TIMESTAMP
            WHERE run_id = ? AND state IN ('pending', 'running')
            """,
            (state, error, run_id),
        )
        db.get_db().commit()


def get_expert_team_repository() -> ExpertTeamRepository:
    settings = get_storage_settings()
    if settings.database_backend == "postgres":
        return SqlAlchemyExpertTeamRepository(get_app_engine())
    return SqliteExpertTeamRepository()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _terminal(state: str) -> bool:
    return state in {"completed", "failed", "cancelled"}


def _with_timestamps(row: dict[str, Any], now: datetime) -> dict[str, Any]:
    values = dict(row)
    values.setdefault("created_at", now)
    values.setdefault("updated_at", now)
    return values
