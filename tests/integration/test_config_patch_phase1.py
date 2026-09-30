from __future__ import annotations

import copy
import io
import json
import zipfile
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


class MultiBotOmnichannel:
    def __init__(self, snapshots: list[dict]):
        self.snapshots = {
            item.bot.bot_id: item
            for item in map(OmnichannelBotSnapshot.model_validate, snapshots)
        }
        self.write_calls = 0

    def list_bots(self, *, correlation_id=None):
        return [
            OmnichannelBotSummary(
                bot_id=item.bot.bot_id,
                bot_name=item.bot.bot_name,
                enabled=item.bot.enabled,
                agent_id=item.agent.agent_id,
                agent_name=item.agent.agent_name,
                dclaw=item.agent.dclaw,
                readiness=item.readiness,
                configuration_digest=item.digests["snapshot"],
            )
            for item in self.snapshots.values()
        ]

    def get_bot_snapshot(self, bot_id: str, *, correlation_id=None):
        return self.snapshots[bot_id]


class MultiAgentDclaw:
    def __init__(self, contexts: dict[str, dict]):
        self.contexts = {
            agent_id: DclawConfigurationContext.model_validate(value)
            for agent_id, value in contexts.items()
        }
        self.write_calls = 0

    def get_context(
        self, base_url: str, agent_id: str, *, correlation_id=None
    ):
        return self.contexts[agent_id]

    def download_snapshot(
        self, base_url: str, agent_id: str, *, correlation_id=None
    ):
        context = self.contexts[agent_id]
        return DclawSnapshotArchive(
            archive=dclaw_archive(),
            agent_id=agent_id,
            profile_id=context.agent_profile_id or "unknown",
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


def test_employee_journey_covers_profiles_bootstrap_and_audit(settings, clock):
    standard_snapshot, standard_context = ready_sources()
    standard_snapshot["bot"] = {
        "botId": "bot-standard",
        "botName": "标准客服",
        "enabled": True,
    }
    standard_snapshot["agent"]["agentId"] = "agent-standard"
    standard_snapshot["agent"]["agentName"] = "标准专家"
    standard_snapshot["digests"]["snapshot"] = "standard-snapshot"
    standard_context.update(
        {
            "agentId": "agent-standard",
            "agentType": "standard",
            "agentProfileId": "standard-2026.09",
        }
    )

    sealed_snapshot = copy.deepcopy(standard_snapshot)
    sealed_snapshot["bot"] = {
        "botId": "bot-sealed",
        "botName": "超级客服",
        "enabled": True,
    }
    sealed_snapshot["agent"]["agentId"] = "agent-sealed"
    sealed_snapshot["agent"]["agentName"] = "超级专家"
    sealed_snapshot["digests"]["snapshot"] = "sealed-snapshot"
    sealed_context = copy.deepcopy(standard_context)
    sealed_context.update(
        {
            "agentId": "agent-sealed",
            "agentType": "sealed",
            "agentProfileId": "super-expert-2026.09",
            "sourceVersion": "sealed-release-7",
        }
    )

    pending_snapshot = copy.deepcopy(standard_snapshot)
    pending_snapshot["bot"] = {
        "botId": "bot-pending",
        "botName": "待管理员初始化",
        "enabled": True,
    }
    pending_snapshot["agent"]["agentId"] = "agent-pending"
    pending_snapshot["agent"]["agentName"] = "待初始化专家"
    pending_snapshot["readiness"] = {
        "ready": False,
        "checks": {
            "bot_enabled": True,
            "agent_bound": True,
            "agent_enabled": True,
            "dclaw_location_configured": True,
            "flow_readable": False,
            "tags_readable": True,
        },
        "missingItems": ["flow_readable"],
    }
    pending_snapshot["digests"]["snapshot"] = "pending-snapshot"
    pending_context = copy.deepcopy(standard_context)
    pending_context.update(
        {
            "agentId": "agent-pending",
            "publicationId": None,
            "knowledgeBaseId": None,
            "billingAccountConfigured": False,
            "readiness": {
                "ready": False,
                "missingItems": [
                    "openapi_publication",
                    "billing_account",
                    "knowledge_base",
                ],
            },
        }
    )

    omnichannel = MultiBotOmnichannel(
        [standard_snapshot, sealed_snapshot, pending_snapshot]
    )
    dclaw = MultiAgentDclaw(
        {
            "agent-standard": standard_context,
            "agent-sealed": sealed_context,
            "agent-pending": pending_context,
        }
    )
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
        json={"employeeName": "联调员工", "tokenName": "Home Codex"},
    ).json()
    headers = {"Authorization": f"Bearer {issued['token']}"}

    listed = client.get("/staff/v1/bots", headers=headers)
    pending = client.get(
        "/staff/v1/bots/bot-pending/configuration-context",
        headers=headers,
    )
    pending_export = client.post(
        "/staff/v1/bots/bot-pending/workspace-bundles/export",
        headers=headers,
    )
    standard = client.post(
        "/staff/v1/bots/bot-standard/workspace-bundles/export",
        headers=headers,
    )
    repeated = client.post(
        "/staff/v1/bots/bot-standard/workspace-bundles/export",
        headers=headers,
    )
    sealed = client.post(
        "/staff/v1/bots/bot-sealed/workspace-bundles/export",
        headers=headers,
    )

    assert listed.status_code == 200
    assert {item["botId"] for item in listed.json()["bots"]} == {
        "bot-standard",
        "bot-sealed",
        "bot-pending",
    }
    assert pending.json()["readiness"]["missingItems"] == [
        "flow_readable",
        "openapi_publication",
        "billing_account",
        "knowledge_base",
    ]
    assert pending_export.status_code == 409
    assert pending_export.json()["detail"] == {
        "code": "ADMIN_BOOTSTRAP_REQUIRED",
        "missingItems": [
            "flow_readable",
            "openapi_publication",
            "billing_account",
            "knowledge_base",
        ],
    }
    assert standard.status_code == sealed.status_code == 200
    assert standard.headers["x-dclaw-release-id"] == "R1"
    assert sealed.headers["x-dclaw-release-id"] == "R1"
    assert repeated.content == standard.content

    def bundle_contract(response):
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("dclaw-manifest.json"))
        return names, manifest

    standard_names, standard_manifest = bundle_contract(standard)
    sealed_names, sealed_manifest = bundle_contract(sealed)
    assert standard_names == sealed_names
    assert standard_manifest["agentProfileId"] == "standard-2026.09"
    assert sealed_manifest["agentProfileId"] == "super-expert-2026.09"

    with client.app.state.config_patch_database.connect() as connection:
        audit_rows = connection.execute(
            "SELECT action, token_id FROM audit_events WHERE token_id = ?",
            (issued["tokenId"],),
        ).fetchall()
        pending_releases = connection.execute(
            "SELECT COUNT(*) FROM configuration_releases WHERE bot_id = ?",
            ("bot-pending",),
        ).fetchone()[0]
    assert {row["action"] for row in audit_rows} >= {
        "staff.bots.list",
        "staff.bot.context.read",
        "staff.workspace_bundle.export",
    }
    assert pending_releases == 0
    assert omnichannel.write_calls == dclaw.write_calls == 0
