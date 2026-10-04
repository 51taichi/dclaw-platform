from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

ROUTING_PATH = Path(__file__).parents[3] / "plugins/tool/jev-private-routing/routing.py"
spec = importlib.util.spec_from_file_location("jev_private_routing", ROUTING_PATH)
assert spec is not None and spec.loader is not None
routing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routing)


def test_plugin_registers_the_routing_tool():
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

    class Api:
        registered = None

        def register_tool(self, **kwargs):
            self.registered = kwargs

    api = Api()
    plugin_module.plugin.register(api)
    assert api.registered["tool_name"] == "route_private_message_jev"
    assert callable(api.registered["tool_func"])


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
                "name": "装修",
                "routingDescription": "家装报价",
                "instructions": "微信 secret",
            }
        ],
    )
    assert result_body(result)["taskId"] == "task-renovation"
    assert result_body(result)["status"] == "MATCHED"
    assert "微信 secret" not in json.dumps(requests, ensure_ascii=False)
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
