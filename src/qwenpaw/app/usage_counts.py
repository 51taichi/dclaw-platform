# -*- coding: utf-8 -*-
"""Usage counts shown in the public expert catalog."""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine

from .storage.engine import get_app_engine
from .storage.schema import billing_usage_orders


def get_settled_agent_usage_counts(
    engine: Engine | None = None,
) -> dict[str, int]:
    """Count successfully settled requests by their selected agent."""
    app_engine = engine or get_app_engine()
    statement = select(
        billing_usage_orders.c.request_snapshot_json,
    ).where(billing_usage_orders.c.status == "settled")
    counts: Counter[str] = Counter()

    with app_engine.connect() as conn:
        snapshots = conn.execute(statement).scalars()
        for raw_snapshot in snapshots:
            try:
                snapshot: Any = json.loads(raw_snapshot or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(snapshot, dict):
                continue
            source = snapshot.get("source")
            if not isinstance(source, dict):
                continue
            agent_id = str(source.get("expert_id") or "").strip()
            if agent_id:
                counts[agent_id] += 1

    return dict(counts)
