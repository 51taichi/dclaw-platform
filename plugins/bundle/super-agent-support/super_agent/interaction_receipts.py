"""Machine-readable receipts for persisted interaction transitions."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .interaction_cards import InteractionCardRecord


def card_receipt(card: InteractionCardRecord, action: str) -> dict[str, Any]:
    if action not in {"created", "submitted"}:
        raise ValueError("unsupported interaction receipt action")
    expected = "create" if action == "created" else "submit"
    matches = [
        (index, item)
        for index, item in enumerate(card.transitions)
        if item.action == expected
    ]
    if len(matches) != 1:
        raise ValueError("interaction transition does not match receipt")
    index, transition = matches[0]
    answer_digest = None
    if action == "submitted":
        if card.answer is None:
            raise ValueError("submitted interaction has no answer")
        encoded = json.dumps(
            card.answer.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        answer_digest = hashlib.sha256(encoded).hexdigest()
    return {
        "contract": "interaction.card.receipt/1",
        "action": action,
        "event_id": transition.event_id,
        "interaction_id": card.interaction_id,
        "installation_id": card.binding.installation_id,
        "conversation_id": card.binding.conversation_id,
        "task_key": card.task_key,
        "interaction_revision": card.interaction_revision,
        "version": index + 1,
        "status": transition.to_status.value,
        "answer_sha256": answer_digest,
        "occurred_at": transition.occurred_at.isoformat(),
    }
