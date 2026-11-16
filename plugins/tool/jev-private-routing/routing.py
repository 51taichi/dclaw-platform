"""Bounded TypeSafe Choice for private-message task attribution."""

import json
import logging
import os
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Mapping
from uuid import uuid4

import httpx
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse
from qwenpaw.constant import WORKING_DIR

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://api.aijiau.com/v1/systemone"
PLUGIN_ID = "jev-private-routing"
CHANNEL_CONFIG_PATH = (
    Path(WORKING_DIR) / "plugin-data" / PLUGIN_ID / "channels.json"
)
NO_MATCH = "no_match"
MAX_CANDIDATES = 2_000
MAX_HISTORY = 2_000
BATCH_SIZE = 200  # Choice permits 255 options including no_match.
MIN_MARGIN = 0.15
NON_FAILOVER_HTTP_STATUSES = {400, 404, 405, 413, 422}


@dataclass(frozen=True)
class _JevChannel:
    name: str
    api_url: str
    api_key: str
    relay_token: str


def _result(status, task_id=None, probability=None, confidence=None):
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(
                    {
                        "status": status,
                        "taskId": task_id,
                        "probability": probability,
                        "confidence": confidence,
                    },
                    ensure_ascii=False,
                ),
            )
        ],
    )


def _valid_probability(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
        and 0 <= value <= 1
    )


async def route_private_message_jev(
    message: str,
    candidate_tasks: list[dict],
    recent_history: list[dict] | None = None,
    shared_video: dict | None = None,
    minimum_margin: float = MIN_MARGIN,
) -> ToolResponse:
    """Choose a task from caller-composed routing contexts using Jev.

    Args:
        message: The latest inbound private-message text.
        candidate_tasks: Opaque routingContext values with IDs and confidence controls.
        recent_history: Recent messages in this same Douyin conversation, with direction and text.
        shared_video: Observable metadata from a shared-video card, when available.
    """
    if not isinstance(message, str) or not message.strip() or len(message) > 4000:
        return _result("ERROR")
    if (
        not isinstance(candidate_tasks, list)
        or not 1 <= len(candidate_tasks) <= MAX_CANDIDATES
    ):
        return _result("ERROR")
    if recent_history is None:
        recent_history = []
    if not isinstance(recent_history, list) or len(recent_history) > MAX_HISTORY:
        return _result("ERROR")
    if not _valid_probability(minimum_margin):
        return _result("ERROR")
    if not recent_history and not shared_video and message.strip().rstrip("!！?？。,.， ").lower() in {
        "你好",
        "您好",
        "在吗",
        "哈喽",
        "hi",
        "hello",
    }:
        return _result("UNRESOLVED")

    contexts = {}
    thresholds = {}
    margins = {}
    for task in candidate_tasks:
        if not isinstance(task, dict):
            return _result("ERROR")
        task_id = task.get("taskId")
        routing_context = task.get("routingContext")
        threshold = task.get("routingThreshold", 0.5)
        margin = task.get("routingMinMargin", minimum_margin)
        if (
            not isinstance(task_id, str)
            or not task_id
            or len(task_id) > 128
            or task_id == NO_MATCH
            or task_id in contexts
            or not _valid_probability(threshold)
            or not _valid_probability(margin)
        ):
            return _result("ERROR")
        if routing_context is None:
            routing_context = _legacy_routing_context(task)
        if (
            not isinstance(routing_context, str)
            or not routing_context.strip()
            or len(routing_context) > 6000
        ):
            return _result("ERROR")
        contexts[task_id] = routing_context
        thresholds[task_id] = float(threshold)
        margins[task_id] = float(margin)

    if shared_video is not None:
        if not isinstance(shared_video, dict) or not any(
            isinstance(shared_video.get(key), str) and shared_video[key].strip()
            for key in ("videoId", "shareUrl", "title", "authorId")
        ):
            return _result("ERROR")

    history = []
    for item in recent_history:
        if not isinstance(item, dict) or item.get("direction") not in (
            "INBOUND",
            "OUTBOUND",
        ):
            return _result("ERROR")
        value = item.get("text")
        if not isinstance(value, str) or len(value) > 4000:
            return _result("ERROR")
        normalized = {"direction": item["direction"], "text": value}
        kind = item.get("kind")
        if kind in ("TEXT", "VIDEO_SHARE"):
            normalized["kind"] = kind
        video = item.get("video")
        if isinstance(video, dict):
            normalized["video"] = video
        observed_at = item.get("observedAt")
        if isinstance(observed_at, str) and observed_at:
            normalized["observedAt"] = observed_at
        history.append(normalized)

    try:
        channels = _load_channels()
    except ValueError as exc:
        logger.error("TypeSafe Jev channel configuration is invalid: %s", exc)
        return _result("ERROR")
    if not channels:
        return _result("ERROR")
    winners = []
    unresolved_confidence = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for offset in range(0, len(contexts), BATCH_SIZE):
                batch = dict(list(contexts.items())[offset : offset + BATCH_SIZE])
                criteria = {
                    NO_MATCH: "没有足够证据归属到本组任一任务；泛化问候也选这里。",
                    **batch,
                }
                payload = {
                    "model": "jev-latest",
                    "state": {
                        "message": message,
                        "recentHistory": history,
                        "sharedVideo": shared_video,
                    },
                    "questions": {
                        "task": {
                            "type": "choice",
                            "instructions": (
                                "根据当前私信及同一会话历史，判断用户明确在咨询本组哪个评论任务。"
                                "每个候选值是调用方提供的完整归因上下文，必须结合用户明确陈述判断。"
                                "不能因 Bot 账号、候选 ID 或候选顺序猜测。"
                                "没有足够证据时选择 no_match。"
                            ),
                            "criteria": criteria,
                        }
                    },
                }
                choice, probabilities, confidence = await _choose(
                    client, payload, criteria, channels
                )
                if choice == NO_MATCH:
                    unresolved_confidence = confidence
                    continue
                winners.append((choice, probabilities[choice], confidence, probabilities))

            if not winners:
                return _result("UNRESOLVED", confidence=unresolved_confidence)

            if len(contexts) <= BATCH_SIZE:
                choice, probability, confidence, probabilities = winners[0]
            else:
                finalist_ids = list(dict.fromkeys(item[0] for item in winners))
                final_criteria = {
                    NO_MATCH: "所有批次候选都缺少足够证据时选择这里。",
                    **{task_id: contexts[task_id] for task_id in finalist_ids},
                }
                final_payload = {
                    "model": "jev-latest",
                    "state": {
                        "message": message,
                        "recentHistory": history,
                        "sharedVideo": shared_video,
                    },
                    "questions": {
                        "task": {
                            "type": "choice",
                            "instructions": (
                                "对各批次优胜候选做最终全局比较。只有证据明确时选择任务，"
                                "否则选择 no_match。"
                            ),
                            "criteria": final_criteria,
                        }
                    },
                }
                choice, probabilities, confidence = await _choose(
                    client,
                    final_payload,
                    final_criteria,
                    channels,
                )
                if choice == NO_MATCH:
                    return _result("UNRESOLVED", confidence=confidence)
                probability = probabilities[choice]
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        logger.warning("TypeSafe Jev routing failed: %s", exc)
        return _result("ERROR")

    runner_up = max(value for key, value in probabilities.items() if key != choice)
    if probability < thresholds[choice] or probability - runner_up < margins[choice]:
        return _result("UNRESOLVED", confidence=confidence)
    return _result(
        "MATCHED", task_id=choice, probability=probability, confidence=confidence
    )


def _legacy_routing_context(task):
    """Keep schema v1 requests working during rolling upgrades."""
    name = task.get("name")
    description = task.get("routingDescription")
    target_video = task.get("targetVideo")
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 128
        or not isinstance(description, str)
        or not description.strip()
        or len(description) > 1000
        or (
            target_video is not None
            and (not isinstance(target_video, str) or len(target_video) > 4000)
        )
    ):
        return None
    parts = [f"任务名称：{name.strip()}", f"归因线索：{description.strip()}"]
    if isinstance(target_video, str) and target_video.strip():
        parts.append(f"目标视频：{target_video.strip()}")
    return "\n".join(parts)


def _load_channels() -> list[_JevChannel]:
    document = _read_channel_config()
    if document is None:
        return []
    return _parse_channel_config(document)


def save_channel_config(document: Mapping) -> dict:
    """Validate and atomically persist plugin-owned Jev channel settings."""
    channels = _parse_channel_config(document)
    canonical = {
        "schemaVersion": 1,
        "primary": _channel_document(channels[0]),
    }
    if len(channels) > 1:
        canonical["fallback"] = _channel_document(channels[1])

    target = CHANNEL_CONFIG_PATH
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        target.parent.chmod(0o700)
    except OSError:
        pass
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(canonical, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        try:
            target.chmod(0o600)
        except OSError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
    return channel_config_status()


def channel_config_status() -> dict:
    """Return channel metadata without exposing credentials."""
    channels = _load_channels()
    if not channels:
        return {"schemaVersion": 1, "configured": False}
    result = {
        "schemaVersion": 1,
        "configured": True,
        "primary": _channel_status(channels[0]),
        "fallback": None,
    }
    if len(channels) > 1:
        result["fallback"] = _channel_status(channels[1])
    return result


def _read_channel_config() -> dict | None:
    try:
        raw = CHANNEL_CONFIG_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ValueError("cannot read plugin channel configuration") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("plugin channel configuration is not valid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("plugin channel configuration must be an object")
    return document


def _parse_channel_config(document: Mapping) -> list[_JevChannel]:
    if not isinstance(document, Mapping):
        raise ValueError("plugin channel configuration must be an object")
    if document.get("schemaVersion") != 1:
        raise ValueError("unsupported plugin channel configuration schema")
    if set(document) - {"schemaVersion", "primary", "fallback"}:
        raise ValueError("plugin channel configuration contains unknown fields")
    primary = _parse_channel("primary", document.get("primary"), DEFAULT_API_URL)
    channels = [primary]
    fallback = document.get("fallback")
    if fallback is not None:
        channels.append(_parse_channel("fallback", fallback, None))
    return channels


def _parse_channel(name, value, default_url):
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} channel configuration must be an object")
    if set(value) - {"apiUrl", "apiKey", "relayToken"}:
        raise ValueError(f"{name} channel configuration contains unknown fields")
    api_url = value.get("apiUrl", default_url)
    api_key = value.get("apiKey")
    relay_token = value.get("relayToken", "")
    if not isinstance(api_url, str) or not api_url.strip() or len(api_url) > 2048:
        raise ValueError(f"{name} channel API URL is invalid")
    if not isinstance(api_key, str) or not api_key.strip() or len(api_key) > 8192:
        raise ValueError(f"{name} channel API key is invalid")
    if not isinstance(relay_token, str) or len(relay_token) > 8192:
        raise ValueError(f"{name} channel relay token is invalid")
    return _make_channel(name, api_url, api_key, relay_token)


def _channel_document(channel):
    document = {
        "apiUrl": channel.api_url,
        "apiKey": channel.api_key,
    }
    if channel.relay_token:
        document["relayToken"] = channel.relay_token
    return document


def _channel_status(channel):
    return {
        "apiUrl": channel.api_url,
        "apiKeyConfigured": True,
        "relayTokenConfigured": bool(channel.relay_token),
    }


def _make_channel(name, api_url, api_key, relay_token):
    api_url = api_url.strip()
    try:
        parsed_api_url = httpx.URL(api_url)
        if parsed_api_url.scheme not in ("http", "https") or not parsed_api_url.host:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError(f"{name} channel API URL is invalid") from None
    return _JevChannel(
        name=name,
        api_url=api_url,
        api_key=api_key.strip(),
        relay_token=relay_token.strip(),
    )


async def _choose(client, payload, criteria, channels):
    for index, channel in enumerate(channels):
        try:
            result = await _choose_from_channel(
                client, payload, criteria, channel
            )
            if index > 0:
                logger.info("TypeSafe Jev routing used fallback channel")
            return result
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if index == len(channels) - 1 or status in NON_FAILOVER_HTTP_STATUSES:
                raise
            logger.warning(
                "TypeSafe Jev channel failed; trying fallback: channel=%s status=%s",
                channel.name,
                status,
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
            if index == len(channels) - 1:
                raise
            logger.warning(
                "TypeSafe Jev channel failed; trying fallback: channel=%s error=%s",
                channel.name,
                type(exc).__name__,
            )
    raise ValueError("no TypeSafe Jev channel available")


async def _choose_from_channel(client, payload, criteria, channel):
    headers = {"Authorization": f"Bearer {channel.api_key}"}
    if channel.relay_token:
        headers["X-DClaw-Relay-Token"] = channel.relay_token
    response = await client.post(channel.api_url, headers=headers, json=payload)
    response.raise_for_status()
    answer = response.json()["answers"]["task"]
    if not isinstance(answer, dict):
        raise ValueError("invalid Jev answer")
    probabilities = answer.get("probabilities")
    choice = answer.get("choice")
    confidence = answer.get("confidence")
    if (
        answer.get("type") != "choice"
        or choice not in criteria
        or not isinstance(probabilities, dict)
        or set(probabilities) != set(criteria)
        or not all(_valid_probability(value) for value in probabilities.values())
        or not _valid_probability(confidence)
    ):
        raise ValueError("invalid Jev choice")
    return choice, probabilities, confidence
