# -*- coding: utf-8 -*-
"""Narrow, server-trusted complimentary billing policy."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from ..storage.schema import billing_price_catalogs, users

_COMPLIMENTARY_USERNAME = "szzz_admin"
COMPLIMENTARY_UNPRICED_CATALOG_ID = "system-complimentary-unpriced"
COMPLIMENTARY_UNPRICED_CATALOG_VERSION = "complimentary-unpriced-v1"


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


def ensure_complimentary_unpriced_catalog(
    conn: Connection,
) -> dict[str, Any]:
    """Return an internal FK anchor that cannot price normal traffic."""
    now = datetime.now(timezone.utc)
    values = {
        "id": COMPLIMENTARY_UNPRICED_CATALOG_ID,
        "version": COMPLIMENTARY_UNPRICED_CATALOG_VERSION,
        "status": "internal",
        "effective_at": None,
        "published_at": None,
        "created_by": "system",
        "metadata_json": json.dumps(
            {"purpose": "complimentary_unpriced"},
            sort_keys=True,
            separators=(",", ":"),
        ),
        "created_at": now,
        "updated_at": now,
    }
    dialect = conn.dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(billing_price_catalogs).values(**values)
        conn.execute(statement.on_conflict_do_nothing(index_elements=["id"]))
    elif dialect == "sqlite":
        statement = sqlite_insert(billing_price_catalogs).values(**values)
        conn.execute(statement.on_conflict_do_nothing(index_elements=["id"]))
    elif conn.scalar(
        select(billing_price_catalogs.c.id).where(
            billing_price_catalogs.c.id == COMPLIMENTARY_UNPRICED_CATALOG_ID,
        ),
    ) is None:
        conn.execute(insert(billing_price_catalogs).values(**values))
    row = conn.execute(
        select(billing_price_catalogs).where(
            billing_price_catalogs.c.id == COMPLIMENTARY_UNPRICED_CATALOG_ID,
        ),
    ).mappings().one()
    return dict(row)
