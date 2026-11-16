from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROUTING_PATH = Path(__file__).parents[3] / "plugins/tool/jev-private-routing/routing.py"
spec = importlib.util.spec_from_file_location("jev_private_routing", ROUTING_PATH)
assert spec is not None and spec.loader is not None
routing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routing)


def load_plugin_module():
    plugin_path = ROUTING_PATH.parent / "plugin.py"
    plugin_spec = importlib.util.spec_from_file_location(
        "jev_routing_plugin",
        plugin_path,
        submodule_search_locations=[str(ROUTING_PATH.parent)],
    )
    assert plugin_spec is not None and plugin_spec.loader is not None
    import sys

    plugin_module = importlib.util.module_from_spec(plugin_spec)
    sys.modules["jev_routing_plugin"] = plugin_module
    plugin_spec.loader.exec_module(plugin_module)
    return plugin_module


def test_plugin_registers_the_routing_tool():
    plugin_module = load_plugin_module()

    class Api:
        registered = None
        router = None

        def register_tool(self, **kwargs):
            self.registered = kwargs

        def register_http_router(self, router, **kwargs):
            self.router = (router, kwargs)

    api = Api()
    plugin_module.plugin.register(api)
    assert api.registered["tool_name"] == "route_private_message_jev"
    assert callable(api.registered["tool_func"])
    assert api.router is not None
    assert api.router[1]["prefix"] == "/open/v1/jev-private-routing"


@pytest.mark.asyncio
async def test_http_route_checks_publication_and_calls_jev_directly(monkeypatch):
    plugin_module = load_plugin_module()
    calls = []

    class Repository:
        def get_enabled_publication_by_public_id(self, public_id):
            assert public_id == "douyin-agent"
            return {"id": "publication-1", "target_type": "agent"}

    async def direct_jev(**kwargs):
        calls.append(kwargs)
        return routing._result(
            "MATCHED", task_id="task-1", probability=0.88, confidence=0.9
        )

    monkeypatch.setattr(plugin_module, "get_open_api_repository", Repository)
    monkeypatch.setattr(plugin_module, "route_private_message_jev", direct_jev)
    payload = plugin_module.RouteRequest.model_validate(
        {
            "schemaVersion": 2,
            "message": "我想问旧房翻新",
            "candidateTasks": [
                {
                    "taskId": "task-1",
                    "routingContext": (
                        "归因线索：旧房翻新\n"
                        "目标视频：看看【装修师傅的作品】#旧房翻新 "
                        "https://v.douyin.com/demo/"
                    ),
                }
            ],
        }
    )
    request = SimpleNamespace(
        state=SimpleNamespace(open_publication_id="publication-1")
    )

    result = await plugin_module.route_private_message(
        "douyin-agent", payload, request
    )

    assert result["status"] == "MATCHED"
    assert result["taskId"] == "task-1"
    context = calls[0]["candidate_tasks"][0]["routingContext"]
    assert "归因线索：旧房翻新" in context
    assert "#旧房翻新" in context


def result_body(result):
    return json.loads(result.content[0]["text"])


def mock_api(monkeypatch, choices):
    original_client = httpx.AsyncClient
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        criteria = payload["questions"]["task"]["criteria"]
        choice = choices[len(requests) - 1]
        probabilities = {key: 0.0 for key in criteria}
        probabilities[choice] = 0.93
        probabilities[
            "no_match"
            if choice != "no_match"
            else next(key for key in criteria if key != "no_match")
        ] = 0.07
        return httpx.Response(
            200,
            json={
                "answers": {
                    "task": {
                        "type": "choice",
                        "choice": choice,
                        "probabilities": probabilities,
                        "confidence": 0.9,
                    }
                }
            },
        )

    monkeypatch.setattr(
        routing.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    return requests


@pytest.mark.asyncio
async def test_matches_only_supplied_task_and_keeps_reply_instructions_out_of_jev(
    monkeypatch,
):
    requests = mock_api(monkeypatch, ["task-renovation"])
    result = await routing.route_private_message_jev(
        "我想问装修报价",
        [
            {
                "taskId": "task-renovation",
                "routingContext": (
                    "归因线索：家装报价\n目标视频："
                    "复制打开抖音，看看【装修师傅的作品】# 旧房翻新 "
                    "https://v.douyin.com/demo/"
                ),
                "instructions": "微信 secret",
            }
        ],
    )
    assert result_body(result)["taskId"] == "task-renovation"
    assert result_body(result)["status"] == "MATCHED"
    assert "微信 secret" not in json.dumps(requests, ensure_ascii=False)
    assert requests[0]["questions"]["task"]["criteria"]["task-renovation"] == (
        "归因线索：家装报价\n目标视频：复制打开抖音，看看【装修师傅的作品】"
        "# 旧房翻新 https://v.douyin.com/demo/"
    )
    assert requests[0]["model"] == "jev-latest"


@pytest.mark.asyncio
async def test_generic_greeting_stays_unresolved(monkeypatch):
    requests = mock_api(monkeypatch, ["no_match"])
    result = await routing.route_private_message_jev(
        "你好",
        [{"taskId": "task-a", "name": "装修", "routingDescription": "家装"}],
    )
    assert result_body(result)["status"] == "UNRESOLVED"
    assert result_body(result)["taskId"] is None
    assert requests == []


@pytest.mark.asyncio
async def test_multiple_batches_with_conflicting_matches_stay_unresolved(monkeypatch):
    tasks = [
        {
            "taskId": f"task-{index}",
            "name": f"任务{index}",
            "routingDescription": f"主题{index}",
        }
        for index in range(201)
    ]
    requests = mock_api(monkeypatch, ["task-0", "task-200", "no_match"])
    result = await routing.route_private_message_jev("咨询", tasks)
    assert len(requests) == 3
    assert result_body(result)["status"] == "UNRESOLVED"


@pytest.mark.asyncio
async def test_routes_more_than_500_candidates_with_global_final(monkeypatch):
    tasks = [
        {
            "taskId": f"task-{index}",
            "name": f"任务{index}",
            "routingDescription": f"主题{index}",
            "routingThreshold": 0.5,
        }
        for index in range(501)
    ]
    requests = mock_api(monkeypatch, ["task-0", "task-200", "task-423", "task-423"])
    result = await routing.route_private_message_jev("咨询主题423", tasks)

    assert len(requests) == 4
    assert result_body(result)["status"] == "MATCHED"
    assert result_body(result)["taskId"] == "task-423"


@pytest.mark.asyncio
async def test_task_threshold_is_enforced(monkeypatch):
    mock_api(monkeypatch, ["task-a"])
    result = await routing.route_private_message_jev(
        "装修",
        [
            {
                "taskId": "task-a",
                "name": "装修",
                "routingDescription": "家装",
                "routingThreshold": 0.95,
            }
        ],
    )
    assert result_body(result)["status"] == "UNRESOLVED"


@pytest.mark.asyncio
async def test_task_specific_minimum_margin_is_enforced(monkeypatch):
    original_client = httpx.AsyncClient

    def handler(request):
        criteria = json.loads(request.content)["questions"]["task"]["criteria"]
        probabilities = {key: 0.0 for key in criteria}
        probabilities["task-a"] = 0.60
        probabilities["no_match"] = 0.50
        return httpx.Response(
            200,
            json={
                "answers": {
                    "task": {
                        "type": "choice",
                        "choice": "task-a",
                        "probabilities": probabilities,
                        "confidence": 0.7,
                    }
                }
            },
        )

    monkeypatch.setattr(
        routing.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    result = await routing.route_private_message_jev(
        "装修",
        [
            {
                "taskId": "task-a",
                "name": "装修",
                "routingDescription": "家装",
                "routingThreshold": 0.5,
                "routingMinMargin": 0.15,
            }
        ],
    )
    assert result_body(result)["status"] == "UNRESOLVED"


@pytest.mark.asyncio
async def test_shared_video_prevents_greeting_shortcut(monkeypatch):
    requests = mock_api(monkeypatch, ["task-a"])
    result = await routing.route_private_message_jev(
        "你好",
        [{"taskId": "task-a", "name": "装修", "routingDescription": "家装"}],
        shared_video={"videoId": "123", "title": "装修视频"},
    )
    assert result_body(result)["status"] == "MATCHED"
    assert requests[0]["state"]["sharedVideo"]["videoId"] == "123"


@pytest.mark.asyncio
async def test_missing_key_fails_closed(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = await routing.route_private_message_jev(
        "装修",
        [{"taskId": "task-a", "name": "装修", "routingDescription": "家装"}],
    )
    assert result_body(result)["status"] == "ERROR"


def test_domestic_relay_is_the_plugin_default_channel(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    monkeypatch.delenv("TYPESAFE_API_URL", raising=False)

    channels = routing._load_channels()

    assert len(channels) == 1
    assert channels[0].api_url == "https://api.aijiau.com/v1/systemone"


@pytest.mark.asyncio
async def test_configured_api_url_is_used(monkeypatch):
    original_client = httpx.AsyncClient
    urls = []
    relay_tokens = []

    def handler(request):
        urls.append(str(request.url))
        relay_tokens.append(request.headers.get("X-DClaw-Relay-Token"))
        criteria = json.loads(request.content)["questions"]["task"]["criteria"]
        return httpx.Response(
            200,
            json={
                "answers": {
                    "task": {
                        "type": "choice",
                        "choice": "task-a",
                        "probabilities": {
                            key: 0.93 if key == "task-a" else 0.07
                            for key in criteria
                        },
                        "confidence": 0.9,
                    }
                }
            },
        )

    monkeypatch.setattr(
        routing.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    monkeypatch.setenv(
        "TYPESAFE_API_URL", "https://typesafe-relay.example/v1/systemone"
    )
    monkeypatch.setenv("TYPESAFE_RELAY_TOKEN", "relay-test-token")

    result = await routing.route_private_message_jev(
        "装修",
        [{"taskId": "task-a", "name": "装修", "routingDescription": "家装"}],
    )

    assert result_body(result)["status"] == "MATCHED"
    assert urls == ["https://typesafe-relay.example/v1/systemone"]
    assert relay_tokens == ["relay-test-token"]


@pytest.mark.asyncio
async def test_provider_http_error_is_logged(monkeypatch, caplog):
    original_client = httpx.AsyncClient

    def handler(_request):
        return httpx.Response(
            451,
            json={"title": "Typesafe is not available in your region."},
        )

    monkeypatch.setattr(
        routing.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only")
    caplog.set_level("WARNING")

    result = await routing.route_private_message_jev(
        "装修",
        [{"taskId": "task-a", "name": "装修", "routingDescription": "家装"}],
    )

    assert result_body(result)["status"] == "ERROR"
    assert "451" in caplog.text


@pytest.mark.asyncio
async def test_auth_failure_switches_to_independent_fallback_channel(monkeypatch):
    original_client = httpx.AsyncClient
    requests = []

    def handler(request):
        requests.append(
            (
                request.url.host,
                request.headers.get("Authorization"),
                request.headers.get("X-DClaw-Relay-Token"),
            )
        )
        if request.url.host == "primary.example":
            return httpx.Response(403, json={"detail": "organization deactivated"})
        criteria = json.loads(request.content)["questions"]["task"]["criteria"]
        return httpx.Response(
            200,
            json={
                "answers": {
                    "task": {
                        "type": "choice",
                        "choice": "task-a",
                        "probabilities": {
                            key: 0.93 if key == "task-a" else 0.07
                            for key in criteria
                        },
                        "confidence": 0.9,
                    }
                }
            },
        )

    monkeypatch.setattr(
        routing.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    monkeypatch.setenv("TYPESAFE_API_URL", "https://primary.example/v1/systemone")
    monkeypatch.setenv("TYPESAFE_API_KEY", "primary-key")
    monkeypatch.setenv(
        "TYPESAFE_FALLBACK_API_URL", "https://fallback.example/v1/systemone"
    )
    monkeypatch.setenv("TYPESAFE_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("TYPESAFE_FALLBACK_RELAY_TOKEN", "fallback-token")

    result = await routing.route_private_message_jev(
        "装修",
        [{"taskId": "task-a", "name": "装修", "routingDescription": "家装"}],
    )

    assert result_body(result)["status"] == "MATCHED"
    assert requests == [
        ("primary.example", "Bearer primary-key", None),
        ("fallback.example", "Bearer fallback-key", "fallback-token"),
    ]


@pytest.mark.asyncio
async def test_request_contract_error_does_not_use_fallback(monkeypatch):
    original_client = httpx.AsyncClient
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        return httpx.Response(422, json={"detail": "invalid request"})

    monkeypatch.setattr(
        routing.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    monkeypatch.setenv("TYPESAFE_API_URL", "https://primary.example/v1/systemone")
    monkeypatch.setenv("TYPESAFE_API_KEY", "primary-key")
    monkeypatch.setenv(
        "TYPESAFE_FALLBACK_API_URL", "https://fallback.example/v1/systemone"
    )
    monkeypatch.setenv("TYPESAFE_FALLBACK_API_KEY", "fallback-key")

    result = await routing.route_private_message_jev(
        "装修",
        [{"taskId": "task-a", "name": "装修", "routingDescription": "家装"}],
    )

    assert result_body(result)["status"] == "ERROR"
    assert hosts == ["primary.example"]


@pytest.mark.asyncio
async def test_incomplete_fallback_channel_fails_closed(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "primary-key")
    monkeypatch.setenv(
        "TYPESAFE_FALLBACK_API_URL", "https://fallback.example/v1/systemone"
    )
    monkeypatch.delenv("TYPESAFE_FALLBACK_API_KEY", raising=False)

    result = await routing.route_private_message_jev(
        "装修",
        [{"taskId": "task-a", "name": "装修", "routingDescription": "家装"}],
    )

    assert result_body(result)["status"] == "ERROR"
