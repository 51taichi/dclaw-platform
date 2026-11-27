# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from qwenpaw.app import expert_teams
from qwenpaw.app.billing.context import BillingSource
from qwenpaw.app.billing.entrypoint import (
    prepare_user_billing_execution,
    resume_user_billing_execution,
)
from qwenpaw.app.billing.pricing import (
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
)
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.expert_team_repo import (
    SqlAlchemyExpertTeamRepository,
)
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


def test_expert_team_pause_keeps_progress_and_resumes_original_order(
    tmp_path,
    monkeypatch,
):
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "team-billing.db")},
        ),
    )
    create_all(engine)
    team_repo = SqlAlchemyExpertTeamRepository(engine)
    monkeypatch.setattr(
        expert_teams,
        "get_expert_team_repository",
        lambda: team_repo,
    )
    monkeypatch.setattr(
        "qwenpaw.app.billing.entrypoint.get_app_engine",
        lambda: engine,
    )
    team_repo.seed_builtin_templates(
        [
            {
                "id": "team-1",
                "name": "Team",
                "enabled": True,
                "tags": "[]",
                "members": json.dumps(
                    [
                        {"key": "one", "display_name": "One"},
                        {"key": "two", "display_name": "Two"},
                        {"key": "three", "display_name": "Three"},
                    ],
                ),
                "workflow": "[]",
            },
        ],
    )
    PriceCatalogService(PriceCatalogRepository(engine)).publish(
        PriceCatalogDraft(
            version="team-v1",
            effective_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            rules=(
                PriceRule(
                    id="team-rule",
                    provider_id="provider",
                    model_key="model",
                    capability="text",
                    unit_type="tokens",
                    input_credits_per_1k=1,
                    output_credits_per_1k=1,
                    metadata={"economic_tier": "standard"},
                ),
            ),
        ),
    )
    run = expert_teams.create_expert_team_run(
        team_id="team-1",
        root_chat_id="chat-1",
        root_session_id="session-1",
        user_id="7",
        input_text="do work",
    )
    expert_teams.update_expert_team_run_state(run.id, "running")
    expert_teams.update_member_run_state(run.id, "one", "completed")
    expert_teams.update_member_run_state(run.id, "two", "running")
    prepared = prepare_user_billing_execution(
        "7",
        BillingSource(
            type="expert_team",
            id="chat-1",
            expert_team_run_id=run.id,
        ),
        "team-request-1",
        {"message_sha256": "safe"},
    )

    assert prepared.pause_expert_team_insufficient(
        run_id=run.id,
        payer_user_id="7",
        next_member_key="two",
        required_credits=4,
    )
    paused = expert_teams.get_expert_team_run(run.id)
    assert paused is not None
    assert paused.next_member_key == "two"
    assert paused.required_credits == 4
    assert paused.billing_usage_order_id == prepared.session.usage_order_id
    BillingRepository(engine).grant(
        prepared.session.wallet_id,
        credits=10,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund-team",
    )
    resumed_billing = resume_user_billing_execution(
        prepared.session.usage_order_id,
        "7",
    )
    resumed_run = expert_teams.resume_expert_team_run(run.id, "7")

    assert resumed_billing is not None
    assert resumed_billing.session.usage_order_id == prepared.session.usage_order_id
    assert resumed_run is not None
    assert resumed_run.state == "running"
    states = {member.member_key: member.state for member in resumed_run.members}
    assert states == {"one": "completed", "two": "pending", "three": "pending"}
    engine.dispose()
