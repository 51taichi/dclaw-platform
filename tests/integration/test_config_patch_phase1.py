from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from config_patch_service.app import create_app
from config_patch_service.models import (
    DclawConfigurationContext,
    DclawSnapshotArchive,
    OmnichannelBotSnapshot,
    OmnichannelBotSummary,
)
from config_patch_service.settings import ConfigPatchSettings

from tests.unit.config_patch_service.test_releases import dclaw_archive
from tests.unit.config_patch_service.test_upstream_clients import (
    dclaw_context,
    omni_snapshot,
    omni_summary,
)


@dataclass
class MutableClock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock(datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc))


@pytest.fixture
def settings(tmp_path) -> ConfigPatchSettings:
    return ConfigPatchSettings(
        data_dir=tmp_path / "config-patch-data",
        token_pepper="integration-token-pepper",
        admin_secret="integration-admin-secret",
        dclaw_service_secret="integration-dclaw-secret",
        omnichannel_service_secret="integration-omnichannel-secret",
        omnichannel_base_url="https://omnichannel.internal.example",
    )


class SequenceOmnichannel:
    def __init__(self, snapshots: list[dict]):
        self.snapshots = [
            OmnichannelBotSnapshot.model_validate(item) for item in snapshots
        ]
        self.read_index = 0
        self.write_calls = 0

    def list_bots(self, *, correlation_id=None):
        value = self.snapshots[min(self.read_index, len(self.snapshots) - 1)]
        return [
            OmnichannelBotSummary.model_validate(
                {
                    **omni_summary(value.bot.bot_id, value.agent.agent_id),
                    "dclaw": value.agent.dclaw.model_dump(by_alias=True),
                    "readiness": value.readiness.model_dump(by_alias=True),
                    "configurationDigest": value.digests["snapshot"],
                }
            )
        ]

    def get_bot_snapshot(self, bot_id: str, *, correlation_id=None):
        value = self.snapshots[min(self.read_index, len(self.snapshots) - 1)]
        self.read_index += 1
        return value


class SequenceDclaw:
    def __init__(self, contexts: list[dict], *, profile="standard-2026.09"):
        self.contexts = [
            DclawConfigurationContext.model_validate(item) for item in contexts
        ]
        self.context_index = 0
        self.profile = profile
        self.write_calls = 0

    def get_context(
        self, base_url: str, agent_id: str, *, correlation_id=None
    ):
        value = self.contexts[min(self.context_index, len(self.contexts) - 1)]
        self.context_index += 1
        return value

    def download_snapshot(
        self, base_url: str, agent_id: str, *, correlation_id=None
    ):
        context = self.contexts[
            max(0, min(self.context_index - 1, len(self.contexts) - 1))
        ]
        return DclawSnapshotArchive(
            archive=dclaw_archive(),
            agent_id=agent_id,
            profile_id=self.profile,
            source_version=context.source_version or "unknown",
            agent_digest="sha256:" + "a" * 64,
            knowledge_digest="sha256:" + "k" * 64,
        )


def ready_sources():
    snapshot = omni_snapshot()
    snapshot["readiness"] = {
        "ready": True,
        "checks": {
            "bot_enabled": True,
            "agent_bound": True,
            "agent_enabled": True,
            "dclaw_location_configured": True,
            "flow_readable": True,
            "tags_readable": True,
        },
        "missingItems": [],
    }
    context = dclaw_context()
    context["readiness"] = {"ready": True, "missingItems": []}
    return snapshot, context


def authenticated_client(settings, clock, omnichannel, dclaw):
    client = TestClient(
        create_app(
            settings=settings,
            clock=clock,
            omnichannel_client=omnichannel,
            dclaw_client=dclaw,
        )
    )
    issued = client.post(
        "/internal/admin/v1/staff-tokens",
        headers={"X-Config-Patch-Admin-Secret": settings.admin_secret},
        json={"employeeName": "联调员工", "tokenName": "Codex"},
    ).json()
    return client, {"Authorization": f"Bearer {issued['token']}"}


def release_count(client: TestClient) -> int:
    with client.app.state.config_patch_database.connect() as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM configuration_releases"
        ).fetchone()[0]


def test_first_export_creates_r1_and_repeated_export_is_byte_stable(
    settings, clock
):
    snapshot, context = ready_sources()
    omni = SequenceOmnichannel([snapshot, snapshot, snapshot, snapshot])
    dclaw = SequenceDclaw([context, context, context, context])
    client, headers = authenticated_client(settings, clock, omni, dclaw)

    first = client.post(
        "/staff/v1/bots/bot-a/workspace-bundles/export", headers=headers
    )
    second = client.post(
        "/staff/v1/bots/bot-a/workspace-bundles/export", headers=headers
    )

    assert first.status_code == 200
    assert first.headers["x-dclaw-release-id"] == "R1"
    assert (
        first.headers["x-dclaw-bundle-digest"]
        == second.headers["x-dclaw-bundle-digest"]
    )
    assert first.content == second.content
    assert release_count(client) == 1
    assert omni.write_calls == dclaw.write_calls == 0


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("binding", "TARGET_BINDING_CHANGED"),
        ("bot_state", "OMNICHANNEL_CONFIGURATION_CHANGED"),
        ("omnichannel", "OMNICHANNEL_CONFIGURATION_CHANGED"),
        ("dclaw", "DCLAW_SOURCE_CHANGED"),
    ],
)
def test_double_read_rejects_binding_and_source_drift_without_release(
    settings,
    clock,
    mutation,
    code,
):
    first_snapshot, first_context = ready_sources()
    second_snapshot = copy.deepcopy(first_snapshot)
    second_context = copy.deepcopy(first_context)
    if mutation == "binding":
        second_snapshot["agent"]["agentId"] = "agent-b"
    elif mutation == "bot_state":
        second_snapshot["bot"]["enabled"] = False
    elif mutation == "omnichannel":
        second_snapshot["digests"]["flowMachine"] = "changed-flow"
    else:
        second_context["sourceVersion"] = "workspace-v2"

    client, headers = authenticated_client(
        settings,
        clock,
        SequenceOmnichannel([first_snapshot, second_snapshot]),
        SequenceDclaw([first_context, second_context]),
    )
    response = client.post(
        "/staff/v1/bots/bot-a/workspace-bundles/export",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == code
    assert release_count(client) == 0


def test_unready_bot_returns_all_admin_bootstrap_items_without_release(
    settings, clock
):
    snapshot, context = ready_sources()
    snapshot["readiness"]["ready"] = False
    snapshot["readiness"]["missingItems"] = ["bot_enabled", "flow_readable"]
    context["readiness"] = {
        "ready": False,
        "missingItems": [
            "openapi_publication",
            "billing_account",
            "knowledge_base",
        ],
    }
    client, headers = authenticated_client(
        settings,
        clock,
        SequenceOmnichannel([snapshot]),
        SequenceDclaw([context]),
    )

    response = client.post(
        "/staff/v1/bots/bot-a/workspace-bundles/export",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "ADMIN_BOOTSTRAP_REQUIRED",
        "missingItems": [
            "bot_enabled",
            "flow_readable",
            "openapi_publication",
            "billing_account",
            "knowledge_base",
        ],
    }
    assert release_count(client) == 0


def test_unbound_bot_returns_bootstrap_items_without_calling_dclaw(
    settings, clock
):
    snapshot, context = ready_sources()
    snapshot["agent"]["agentId"] = ""
    snapshot["agent"]["enabled"] = False
    snapshot["agent"]["dclaw"] = {"baseUrl": "", "publicId": ""}
    snapshot["readiness"] = {
        "ready": False,
        "checks": {
            "bot_enabled": True,
            "agent_bound": False,
            "agent_enabled": False,
            "dclaw_location_configured": False,
            "flow_readable": True,
            "tags_readable": True,
        },
        "missingItems": [
            "agent_bound",
            "agent_enabled",
            "dclaw_location_configured",
        ],
    }
    dclaw = SequenceDclaw([context])
    client, headers = authenticated_client(
        settings,
        clock,
        SequenceOmnichannel([snapshot]),
        dclaw,
    )

    response = client.post(
        "/staff/v1/bots/bot-a/workspace-bundles/export",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "ADMIN_BOOTSTRAP_REQUIRED",
        "missingItems": [
            "agent_bound",
            "agent_enabled",
            "dclaw_location_configured",
        ],
    }
    assert dclaw.context_index == 0
    assert release_count(client) == 0
