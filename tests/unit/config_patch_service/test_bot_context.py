from __future__ import annotations

from collections import Counter

import pytest

from fastapi.testclient import TestClient

from config_patch_service.app import create_app
from config_patch_service.context import ConfigurationContextService
from config_patch_service.models import (
    DclawConfigurationContext,
    OmnichannelBotSnapshot,
    OmnichannelBotSummary,
)
from config_patch_service.upstreams import (
    UpstreamContractError,
    UpstreamUnavailableError,
)

from .test_upstream_clients import dclaw_context, omni_snapshot, omni_summary


class FakeOmnichannelClient:
    def __init__(self, summaries: list[dict], snapshots: dict[str, dict]):
        self.summaries = [OmnichannelBotSummary.model_validate(value) for value in summaries]
        self.snapshots = {
            key: OmnichannelBotSnapshot.model_validate(value) for key, value in snapshots.items()
        }
        self.correlation_ids: list[str] = []

    def list_bots(self, *, correlation_id: str | None = None):
        self.correlation_ids.append(correlation_id or "")
        return self.summaries

    def get_bot_snapshot(self, bot_id: str, *, correlation_id: str | None = None):
        self.correlation_ids.append(correlation_id or "")
        return self.snapshots[bot_id]


class FakeDclawClient:
    def __init__(self, contexts: dict[str, dict | Exception]):
        self.contexts = contexts
        self.calls: list[tuple[str, str, str]] = []

    def get_context(self, base_url: str, agent_id: str, *, correlation_id: str | None = None):
        self.calls.append((base_url, agent_id, correlation_id or ""))
        value = self.contexts[agent_id]
        if isinstance(value, Exception):
            raise value
        return DclawConfigurationContext.model_validate(value)


def snapshot_for(bot_id: str, agent_id: str, base_url: str = "https://dclaw.internal.example") -> dict:
    value = omni_snapshot()
    value["bot"] = {"botId": bot_id, "botName": f"Name {bot_id}", "enabled": True}
    value["agent"]["agentId"] = agent_id
    value["agent"]["dclaw"]["baseUrl"] = base_url
    return value


def context_for(agent_id: str, profile_id: str, agent_type: str = "standard") -> dict:
    value = dclaw_context()
    value["agentId"] = agent_id
    value["agentType"] = agent_type
    value["agentProfileId"] = profile_id
    return value


def test_all_bots_remain_distinct_while_shared_agent_context_is_fetched_once():
    summaries = [
        omni_summary("bot-a", "agent-shared"),
        omni_summary("bot-b", "agent-shared"),
        omni_summary("bot-super", "agent-super"),
    ]
    omni = FakeOmnichannelClient(summaries, {})
    dclaw = FakeDclawClient({
        "agent-shared": context_for("agent-shared", "standard-2026.09"),
        "agent-super": context_for("agent-super", "super-expert-2026.09", "sealed"),
    })
    service = ConfigurationContextService(omnichannel=omni, dclaw=dclaw)

    targets = service.list_bots(correlation_id="request-one")

    assert [target.bot_id for target in targets] == ["bot-a", "bot-b", "bot-super"]
    assert Counter(agent_id for _, agent_id, _ in dclaw.calls) == {
        "agent-shared": 1,
        "agent-super": 1,
    }
    assert targets[0].agent_profile_id == "standard-2026.09"
    assert targets[2].agent_profile_id == "super-expert-2026.09"
    assert targets[0].model_dump().keys() == targets[2].model_dump().keys()
    assert all(call[2] == "request-one" for call in dclaw.calls)


def test_context_merges_omnichannel_and_dclaw_readiness_and_uses_authoritative_url():
    snapshot = snapshot_for("bot-a", "agent-a", "https://authoritative.dclaw.example")
    snapshot["readiness"]["missingItems"] = ["bot_enabled"]
    omni = FakeOmnichannelClient([omni_summary()], {"bot-a": snapshot})
    dclaw = FakeDclawClient({"agent-a": dclaw_context()})
    service = ConfigurationContextService(omnichannel=omni, dclaw=dclaw)

    context = service.get("bot-a", correlation_id="request-two")

    assert context.readiness.status == "not_ready"
    assert context.readiness.missing_items == ["bot_enabled", "billing_account"]
    assert context.flow_machine == {"enabled": False, "config": None}
    assert context.tags == {"config": None}
    assert dclaw.calls == [("https://authoritative.dclaw.example", "agent-a", "request-two")]
    assert "base_url" not in context.model_dump()


def test_one_unavailable_agent_does_not_hide_other_bots():
    summaries = [omni_summary("bot-good", "agent-good"), omni_summary("bot-bad", "agent-bad")]
    omni = FakeOmnichannelClient(summaries, {})
    dclaw = FakeDclawClient({
        "agent-good": context_for("agent-good", "standard-2026.09"),
        "agent-bad": UpstreamUnavailableError("DCLAW_UPSTREAM_UNAVAILABLE"),
    })

    targets = ConfigurationContextService(omnichannel=omni, dclaw=dclaw).list_bots()

    assert len(targets) == 2
    assert targets[0].readiness.status == "not_ready"
    assert targets[1].readiness.status == "unavailable"
    assert targets[1].readiness.code == "DCLAW_UPSTREAM_UNAVAILABLE"


def test_publication_identity_mismatch_is_never_reported_ready():
    summary = omni_summary("bot-a", "agent-a")
    context = dclaw_context()
    context["readiness"] = {"ready": True, "missingItems": []}
    context["openapiPublicId"] = "different-public-id"
    service = ConfigurationContextService(
        omnichannel=FakeOmnichannelClient([summary], {}),
        dclaw=FakeDclawClient({"agent-a": context}),
    )

    target = service.list_bots()[0]

    assert target.readiness.ready is False
    assert target.readiness.missing_items == ["openapi_public_id_mismatch"]


def test_staff_routes_show_the_same_all_bot_list_to_every_valid_employee(
    settings,
    clock,
):
    summaries = [omni_summary("bot-a", "agent-a"), omni_summary("bot-b", "agent-b")]
    omni = FakeOmnichannelClient(summaries, {
        "bot-a": snapshot_for("bot-a", "agent-a"),
        "bot-b": snapshot_for("bot-b", "agent-b"),
    })
    dclaw = FakeDclawClient({
        "agent-a": context_for("agent-a", "standard-2026.09"),
        "agent-b": context_for("agent-b", "super-expert-2026.09", "sealed"),
    })
    client = TestClient(create_app(
        settings=settings,
        clock=clock,
        omnichannel_client=omni,
        dclaw_client=dclaw,
    ))

    tokens = []
    for employee in ("员工甲", "员工乙"):
        response = client.post(
            "/internal/admin/v1/staff-tokens",
            headers={"X-Config-Patch-Admin-Secret": settings.admin_secret},
            json={"employeeName": employee, "tokenName": "Codex"},
        )
        tokens.append(response.json()["token"])

    lists = [
        client.get("/staff/v1/bots", headers={"Authorization": f"Bearer {token}"})
        for token in tokens
    ]
    assert all(response.status_code == 200 for response in lists)
    assert [response.json()["bots"] for response in lists][0] == [
        response.json()["bots"] for response in lists
    ][1]
    assert [bot["botId"] for bot in lists[0].json()["bots"]] == ["bot-a", "bot-b"]

    context_response = client.get(
        "/staff/v1/bots/bot-a/configuration-context?baseUrl=https://caller-controlled.invalid",
        headers={"Authorization": f"Bearer {tokens[0]}"},
    )
    assert context_response.status_code == 200
    assert context_response.json()["boundAgentId"] == "agent-a"
    assert "baseUrl" not in context_response.text
    assert dclaw.calls[-1][0] == "https://dclaw.internal.example"


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (UpstreamUnavailableError("OMNICHANNEL_UPSTREAM_UNAVAILABLE"), 503),
        (UpstreamContractError("OMNICHANNEL_UPSTREAM_CONTRACT_INVALID"), 502),
    ],
)
def test_staff_bot_list_maps_and_audits_upstream_failures(
    settings, clock, error, status
):
    class FailingOmnichannel:
        def list_bots(self, *, correlation_id=None):
            raise error

    client = TestClient(
        create_app(
            settings=settings,
            clock=clock,
            omnichannel_client=FailingOmnichannel(),
            dclaw_client=FakeDclawClient({}),
        )
    )
    token = client.post(
        "/internal/admin/v1/staff-tokens",
        headers={"X-Config-Patch-Admin-Secret": settings.admin_secret},
        json={"employeeName": "员工", "tokenName": "Codex"},
    ).json()

    response = client.get(
        "/staff/v1/bots",
        headers={"Authorization": f"Bearer {token['token']}"},
    )

    assert response.status_code == status
    assert response.json()["detail"]["code"] == error.code
    with client.app.state.config_patch_database.connect() as connection:
        row = connection.execute(
            "SELECT result, metadata_json FROM audit_events "
            "WHERE action = 'staff.bots.list' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["result"] == "failure"
    assert error.code in row["metadata_json"]
