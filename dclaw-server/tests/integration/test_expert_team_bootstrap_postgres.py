# -*- coding: utf-8 -*-
"""Live PostgreSQL coverage for explicit expert-team bootstrap."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.schema import CreateSchema, DropSchema

from qwenpaw.app import expert_teams
from qwenpaw.app.routers import expert_teams as expert_team_router
from qwenpaw.app.storage.repos.expert_team_repo import (
    SqlAlchemyExpertTeamRepository,
)
from qwenpaw.app.storage.settings import normalize_postgres_url


@pytest.mark.integration
def test_postgres_bootstrap_twice_then_requests_are_read_only(monkeypatch):
    raw_url = os.environ.get("QWENPAW_TEST_POSTGRES_URL", "").strip()
    if not raw_url:
        pytest.skip("QWENPAW_TEST_POSTGRES_URL is not configured")
    database_url = normalize_postgres_url(raw_url)
    schema_name = f"expert_team_{uuid4().hex}"
    admin_engine = create_engine(database_url, future=True, pool_pre_ping=True)
    with admin_engine.begin() as conn:
        conn.execute(CreateSchema(schema_name))
    engine = create_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema_name}"},
    )
    repo = SqlAlchemyExpertTeamRepository(engine)
    monkeypatch.setattr(
        expert_teams,
        "get_expert_team_repository",
        lambda: repo,
    )
    try:
        expert_teams.bootstrap_expert_teams()
        first_ids = {row["id"] for row in repo.list_template_rows()}
        expert_teams.bootstrap_expert_teams()
        assert {row["id"] for row in repo.list_template_rows()} == first_ids

        statements: list[str] = []

        def record(_conn, _cursor, statement, *_args):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        app = FastAPI()
        app.include_router(expert_team_router.user_router)
        client = TestClient(app)

        assert client.get("/expert-teams").status_code == 200
        assert client.get("/expert-teams/software_dev_team").status_code == 200
        assert statements
        assert all(
            statement.lstrip().upper().startswith("SELECT ")
            for statement in statements
        )
    finally:
        engine.dispose()
        with admin_engine.begin() as conn:
            conn.execute(DropSchema(schema_name, cascade=True))
        admin_engine.dispose()
