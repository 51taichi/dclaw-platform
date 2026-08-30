# -*- coding: utf-8 -*-
"""Narrow, server-trusted complimentary billing policy."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Connection

from ..storage.schema import users


_COMPLIMENTARY_USERNAME = "szzz_admin"


def is_complimentary_user(conn: Connection, user_id: str) -> bool:
    """Return whether the trusted payer is the temporary free admin."""
    normalized = str(user_id).strip()
    if not normalized.isdigit():
        return False
    row = (
        conn.execute(
            select(users.c.username, users.c.role).where(
                users.c.id == int(normalized),
            ),
        )
        .mappings()
        .one_or_none()
    )
    return bool(
        row is not None
        and str(row["username"]) == _COMPLIMENTARY_USERNAME
        and str(row["role"]) == "admin"
    )
