from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert, select

from qwenpaw.app.storage.schema import chats, session_states


TOOL = Path(__file__).parents[1] / "tools" / "repair_internal_chat_history.py"


def _repair():
    spec = importlib.util.spec_from_file_location("repair_internal_chat_history", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.repair_history


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def test_repair_requires_exact_evidence_and_preserves_customer_history(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    chats.create(engine)
    session_states.create(engine)
    candidate = {"id": "candidate", "role": "assistant", "content": "{\"internal\":true}"}
    customer = {"id": "customer", "role": "user", "content": "request"}
    reply = {"id": "reply", "role": "assistant", "content": "safe reply"}
    state = {"agent": {"memory": {"content": [candidate, customer, reply]}}}
    raw = json.dumps(state, ensure_ascii=False)
    with engine.begin() as connection:
        connection.execute(insert(chats).values(
            id="task", user_id="owner", agent_id="comic",
            session_id="task", status="idle",
        ))
        connection.execute(insert(session_states).values(
            chat_id="task", state_json=raw,
        ))
    arguments = dict(
        engine=engine, chat_id="task", agent_id="comic",
        expected_state_sha256=_digest(raw.encode()),
        remove={"candidate": _digest(json.dumps(
            candidate["content"], sort_keys=True, ensure_ascii=False,
        ).encode())},
        backup_root=tmp_path / "backup",
    )
    repair = _repair()
    assert repair(**arguments, apply=False)["status"] == "preview"
    assert not (tmp_path / "backup").exists()
    with pytest.raises(ValueError, match="cannot remove customer"):
        repair(**{**arguments, "remove": {
            "customer": _digest(json.dumps(customer["content"]).encode()),
        }}, apply=True)
    receipt = repair(**arguments, apply=True)
    assert receipt["status"] == "committed"
    with engine.connect() as connection:
        current = connection.execute(select(session_states.c.state_json)).scalar_one()
    assert [item["id"] for item in json.loads(current)["agent"]["memory"]["content"]] == [
        "customer", "reply",
    ]
    assert next((tmp_path / "backup").iterdir()).read_text() == raw
    with pytest.raises(ValueError, match="chat state changed"):
        repair(**arguments, apply=True)
