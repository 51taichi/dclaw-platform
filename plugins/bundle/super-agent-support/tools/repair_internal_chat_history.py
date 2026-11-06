"""Remove verified internal candidate messages from one Super Agent chat."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from sqlalchemy import select, update

from qwenpaw.app.storage.engine import get_app_engine
from qwenpaw.app.storage.schema import chats, session_states


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _message(item: object) -> dict:
    value = item[0] if isinstance(item, list) and item else item
    if not isinstance(value, dict):
        raise ValueError("invalid memory message")
    return value


def repair_history(
    *, engine, chat_id: str, agent_id: str, expected_state_sha256: str,
    remove: dict[str, str], backup_root: Path, apply: bool,
) -> dict:
    if not remove or any(
        not re.fullmatch(r"[0-9a-f]{64}", digest)
        for digest in [expected_state_sha256, *remove.values()]
    ):
        raise ValueError("expected SHA-256 and message hashes are required")
    with engine.begin() as connection:
        row = connection.execute(
            select(chats.c.id, chats.c.agent_id, chats.c.status,
                   session_states.c.state_json)
            .join(session_states, chats.c.id == session_states.c.chat_id)
            .where(chats.c.id == chat_id)
            .with_for_update(),
        ).one_or_none()
        if row is None or row.agent_id != agent_id or row.status == "running":
            raise ValueError("chat scope unavailable")
        raw = row.state_json.encode("utf-8")
        if _sha256(raw) != expected_state_sha256:
            raise ValueError("chat state changed")
        state = json.loads(raw)
        content = state.get("agent", {}).get("memory", {}).get("content")
        if not isinstance(content, list):
            raise ValueError("chat memory unavailable")
        kept = []
        removed = []
        for item in content:
            message = _message(item)
            message_id = message.get("id")
            if message_id not in remove:
                kept.append(item)
                continue
            if message.get("role") not in {"assistant", "system"}:
                raise ValueError("cannot remove customer message")
            digest = _sha256(json.dumps(
                message.get("content"), sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8"))
            if digest != remove[message_id] or message_id in removed:
                raise ValueError("message evidence mismatch")
            removed.append(message_id)
        if set(removed) != set(remove):
            raise ValueError("message evidence missing")
        state["agent"]["memory"]["content"] = kept
        repaired = json.dumps(state, ensure_ascii=False).encode("utf-8")
        receipt = {
            "contract": "super-agent.chat-history-repair/1",
            "chat_id": chat_id, "agent_id": agent_id,
            "before_sha256": _sha256(raw),
            "after_sha256": _sha256(repaired),
            "removed_message_ids": removed,
            "remaining_message_count": len(kept),
            "status": "preview",
        }
        if apply:
            backup_root.mkdir(parents=True, exist_ok=True)
            if backup_root.is_symlink():
                raise ValueError("backup root is unsafe")
            repair_id = uuid.uuid4().hex
            backup = backup_root / f"{repair_id}.json"
            descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as backup_file:
                backup_file.write(raw)
                backup_file.flush()
                os.fsync(backup_file.fileno())
            connection.execute(
                update(session_states)
                .where(session_states.c.chat_id == chat_id)
                .values(state_json=repaired.decode("utf-8")),
            )
            receipt.update(status="committed", repair_id=repair_id)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--expected-state-sha256", required=True)
    parser.add_argument("--remove", action="append", required=True,
                        help="message-id:content-sha256")
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    evidence = {}
    for item in args.remove:
        message_id, separator, digest = item.partition(":")
        if not separator or not message_id or message_id in evidence:
            parser.error("duplicate or malformed message evidence")
        evidence[message_id] = digest
    print(json.dumps(repair_history(
        engine=get_app_engine(), chat_id=args.chat_id,
        agent_id=args.agent_id,
        expected_state_sha256=args.expected_state_sha256,
        remove=evidence, backup_root=args.backup_root,
        apply=args.apply,
    ), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
