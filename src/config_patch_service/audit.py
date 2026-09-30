"""Credential-safe structured audit recording."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from .db import ConfigPatchDatabase


logger = logging.getLogger("config_patch_service.audit")

_SENSITIVE_KEYS = {
    "authorization",
    "password",
    "pepper",
    "raw_token",
    "secret",
    "token",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        normalized = str(key).strip().lower()
        if normalized in _SENSITIVE_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[str(key)] = value
    return safe


class AuditService:
    def __init__(
        self,
        database: ConfigPatchDatabase,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._database = database
        self._clock = clock

    def record(
        self,
        action: str,
        *,
        token_id: str | None = None,
        employee_name: str | None = None,
        result: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        safe_metadata = _safe_metadata(metadata)
        event = {
            "action": action,
            "tokenId": token_id,
            "employeeName": employee_name,
            "result": result,
            "metadata": safe_metadata,
            "createdAt": self._clock().astimezone(timezone.utc).isoformat(),
        }
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (
                    action, token_id, employee_name, result, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    action,
                    token_id,
                    employee_name,
                    result,
                    json.dumps(safe_metadata, ensure_ascii=False, sort_keys=True),
                    event["createdAt"],
                ),
            )
        logger.info("config_patch.audit %s", json.dumps(event, ensure_ascii=False, sort_keys=True))
