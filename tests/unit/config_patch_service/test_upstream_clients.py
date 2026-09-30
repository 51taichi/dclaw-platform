from __future__ import annotations

import httpx
import pytest

from config_patch_service.upstreams import UpstreamContractError, UpstreamUnavailableError
from config_patch_service.upstreams.dclaw import DclawClient
from config_patch_service.upstreams.omnichannel import OmnichannelClient


def omni_summary(bot_id: str = "bot-a", agent_id: str = "agent-a") -> dict:
    return {
        "botId": bot_id,
        "botName": f"Name {bot_id}",
        "enabled": True,
        "agentId": agent_id,
        "agentName": "Agent A",
        "dclaw": {"baseUrl": "https://dclaw.internal.example", "publicId": "public-a"},
        "readiness": {"ready": True, "checks": {"bot_enabled": True}, "missingItems": []},
        "configurationDigest": "a" * 64,
    }


def omni_snapshot() -> dict:
    return {
        "schemaVersion": "config-patch-bot-snapshot.v1",
        "bot": {"botId": "bot-a", "botName": "Bot A", "enabled": True},
        "agent": {
            "agentId": "agent-a",
            "agentName": "Agent A",
            "enabled": True,
            "dclaw": {"baseUrl": "https://dclaw.internal.example", "publicId": "public-a"},
        },
        "flowMachine": {"enabled": False, "config": None},
        "tags": {"config": None},
        "source": {"service": "dclaw-omnichannel-service"},
        "readiness": {
            "ready": False,
            "checks": {"flow_readable": True},
            "missingItems": ["bot_enabled"],
        },
        "digests": {"flowMachine": "f" * 64, "tags": "t" * 64, "snapshot": "s" * 64},
    }


def dclaw_context() -> dict:
    return {
        "agentId": "agent-a",
        "agentType": "standard",
        "agentProfileId": "standard-2026.09",
        "enabled": True,
        "sourceVersion": "workspace",
        "publicationId": "publication-a",
        "openapiPublicId": "public-a",
        "knowledgeBaseId": "knowledge-a",
        "billingAccountConfigured": True,
        "readiness": {"ready": False, "missingItems": ["billing_account"]},
    }


def test_omnichannel_client_uses_exact_readonly_paths_headers_and_timeouts():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["X-Omnichannel-Config-Patch-Secret"] == "omni-secret"
        assert request.headers["X-Correlation-ID"] == "correlation-a"
        assert request.extensions["timeout"]["connect"] == 2.0
        assert request.extensions["timeout"]["read"] == 10.0
        if request.url.path.endswith("/snapshot"):
            return httpx.Response(200, json={"ok": True, "snapshot": omni_snapshot()})
        return httpx.Response(200, json={"ok": True, "bots": [omni_summary()]})

    client = OmnichannelClient(
        base_url="https://omnichannel.internal.example",
        service_secret="omni-secret",
        transport=httpx.MockTransport(handler),
    )

    assert client.list_bots(correlation_id="correlation-a")[0].bot_id == "bot-a"
    assert client.get_bot_snapshot("bot-a", correlation_id="correlation-a").agent.agent_id == "agent-a"
    assert [request.url.path for request in requests] == [
        "/internal/config-patch/v1/bots",
        "/internal/config-patch/v1/bots/bot-a/snapshot",
    ]
    assert all(request.method == "GET" and not request.content for request in requests)


def test_dclaw_client_uses_only_supplied_authoritative_location_and_download_contract():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["X-DClaw-Config-Patch-Secret"] == "dclaw-secret"
        assert request.headers["X-Correlation-ID"] == "correlation-b"
        if request.url.path.endswith("/snapshot"):
            return httpx.Response(
                200,
                content=b"PK\x03\x04archive",
                headers={
                    "content-type": "application/zip",
                    "X-DClaw-Agent-Id": "agent-a",
                    "X-DClaw-Agent-Profile-Id": "standard-2026.09",
                    "X-DClaw-Source-Version": "workspace",
                    "X-DClaw-Agent-Digest": "a" * 64,
                    "X-DClaw-Knowledge-Digest": "k" * 64,
                },
            )
        return httpx.Response(200, json=dclaw_context())

    client = DclawClient(
        service_secret="dclaw-secret",
        allowed_origins=("https://dclaw.internal.example",),
        transport=httpx.MockTransport(handler),
    )
    context = client.get_context(
        "https://dclaw.internal.example/root/",
        "agent-a",
        correlation_id="correlation-b",
    )
    archive = client.download_snapshot(
        "https://dclaw.internal.example/root/",
        "agent-a",
        correlation_id="correlation-b",
    )

    assert context.agent_profile_id == "standard-2026.09"
    assert archive.archive.startswith(b"PK")
    assert archive.agent_digest == "a" * 64
    assert [str(request.url) for request in requests] == [
        "https://dclaw.internal.example/root/api/internal/config-patch/v1/agents/agent-a/context",
        "https://dclaw.internal.example/root/api/internal/config-patch/v1/agents/agent-a/snapshot",
    ]


@pytest.mark.parametrize("client_kind", ["omnichannel", "dclaw"])
def test_upstream_failures_and_invalid_schemas_never_echo_secrets_or_response_bodies(client_kind: str):
    leaked_body = "upstream-body-secret-must-not-leak"
    service_secret = "service-secret-must-not-leak"

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text=leaked_body)

    if client_kind == "omnichannel":
        client = OmnichannelClient(
            base_url="https://omnichannel.internal.example",
            service_secret=service_secret,
            transport=httpx.MockTransport(failing_handler),
        )
        call = client.list_bots
    else:
        client = DclawClient(
            service_secret=service_secret,
            allowed_origins=("https://dclaw.internal.example",),
            transport=httpx.MockTransport(failing_handler),
        )
        call = lambda: client.get_context("https://dclaw.internal.example", "agent-a")

    with pytest.raises(UpstreamUnavailableError) as caught:
        call()
    rendered = repr(caught.value)
    assert leaked_body not in rendered
    assert service_secret not in rendered

    invalid_transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    if client_kind == "omnichannel":
        invalid_client = OmnichannelClient(
            base_url="https://omnichannel.internal.example",
            service_secret=service_secret,
            transport=invalid_transport,
        )
        invalid_call = invalid_client.list_bots
    else:
        invalid_client = DclawClient(
            service_secret=service_secret,
            allowed_origins=("https://dclaw.internal.example",),
            transport=invalid_transport,
        )
        invalid_call = lambda: invalid_client.get_context("https://dclaw.internal.example", "agent-a")
    with pytest.raises(UpstreamContractError):
        invalid_call()


@pytest.mark.parametrize(
    "untrusted_url",
    [
        "http://127.0.0.1:8080",
        "http://169.254.169.254/latest/meta-data",
        "https://dclaw.internal.example.attacker.invalid",
        "https://attacker.invalid/dclaw",
    ],
)
def test_dclaw_client_rejects_untrusted_origins_before_sending_secret(
    untrusted_url: str,
):
    requests: list[httpx.Request] = []
    client = DclawClient(
        service_secret="must-not-leave-service",
        allowed_origins=("https://dclaw.internal.example",),
        transport=httpx.MockTransport(
            lambda request: requests.append(request)
            or httpx.Response(200, json=dclaw_context()),
        ),
    )

    with pytest.raises(UpstreamContractError, match="DCLAW_LOCATION_NOT_ALLOWED"):
        client.get_context(untrusted_url, "agent-a")

    assert requests == []
