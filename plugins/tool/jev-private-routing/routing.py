"""Bounded TypeSafe Choice for private-message task attribution."""

import json
import os
from math import isfinite

import httpx
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

API_URL = "https://api.typesafe.ai/v1/systemone"
NO_MATCH = "no_match"
MAX_CANDIDATES = 2_000
MAX_HISTORY = 2_000
BATCH_SIZE = 200  # Choice permits 255 options including no_match.
MIN_MARGIN = 0.15


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
    """Choose a task from taskId/name/routingDescription candidates using Jev.

    Args:
        message: The latest inbound private-message text.
        candidate_tasks: Bot Server tasks with routing metadata and routingThreshold.
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

    descriptions = {}
    thresholds = {}
    margins = {}
    for task in candidate_tasks:
        if not isinstance(task, dict):
            return _result("ERROR")
        task_id = task.get("taskId")
        name = task.get("name")
        description = task.get("routingDescription")
        threshold = task.get("routingThreshold", 0.5)
        margin = task.get("routingMinMargin", minimum_margin)
        if (
            not isinstance(task_id, str)
            or not task_id
            or len(task_id) > 128
            or task_id == NO_MATCH
            or task_id in descriptions
            or not isinstance(name, str)
            or not name.strip()
            or len(name) > 128
            or not isinstance(description, str)
            or not description.strip()
            or len(description) > 1000
            or not _valid_probability(threshold)
            or not _valid_probability(margin)
        ):
            return _result("ERROR")
        descriptions[task_id] = {"task": name, "signals": description}
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

    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        return _result("ERROR")
    winners = []
    unresolved_confidence = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for offset in range(0, len(descriptions), BATCH_SIZE):
                batch = dict(list(descriptions.items())[offset : offset + BATCH_SIZE])
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
                                "只依据业务线索和用户明确陈述；不能因 Bot 账号或候选顺序猜测。"
                                "没有足够证据时选择 no_match。"
                            ),
                            "criteria": criteria,
                        }
                    },
                }
                choice, probabilities, confidence = await _choose(client, payload, criteria, api_key)
                if choice == NO_MATCH:
                    unresolved_confidence = confidence
                    continue
                winners.append((choice, probabilities[choice], confidence, probabilities))

            if not winners:
                return _result("UNRESOLVED", confidence=unresolved_confidence)

            if len(descriptions) <= BATCH_SIZE:
                choice, probability, confidence, probabilities = winners[0]
            else:
                finalist_ids = list(dict.fromkeys(item[0] for item in winners))
                final_criteria = {
                    NO_MATCH: "所有批次候选都缺少足够证据时选择这里。",
                    **{task_id: descriptions[task_id] for task_id in finalist_ids},
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
                    client, final_payload, final_criteria, api_key
                )
                if choice == NO_MATCH:
                    return _result("UNRESOLVED", confidence=confidence)
                probability = probabilities[choice]
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        return _result("ERROR")

    runner_up = max(value for key, value in probabilities.items() if key != choice)
    if probability < thresholds[choice] or probability - runner_up < margins[choice]:
        return _result("UNRESOLVED", confidence=confidence)
    return _result(
        "MATCHED", task_id=choice, probability=probability, confidence=confidence
    )


async def _choose(client, payload, criteria, api_key):
    response = await client.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
    )
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
