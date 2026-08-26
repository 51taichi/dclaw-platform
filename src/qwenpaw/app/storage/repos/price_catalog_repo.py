# -*- coding: utf-8 -*-
"""Persistence for versioned DClaw retail price catalogs."""
from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, exists, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from ..schema import billing_price_catalogs, billing_price_rules


class CatalogNotFoundError(LookupError):
    """No catalog exists for an identifier or quote time."""


class CatalogImmutableError(ValueError):
    """A caller attempted to change a published catalog."""


class DuplicateCatalogVersionError(ValueError):
    """A catalog version must identify one immutable catalog."""


class PriceCatalogRepository:
    """Store draft catalogs and expose time-versioned published rules."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_draft(self, catalog: Any) -> str:
        """Persist an explicit catalog draft command and return its ID."""
        catalog_id = str(uuid4())
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    insert(billing_price_catalogs).values(
                        id=catalog_id,
                        version=catalog.version,
                        status="draft",
                        effective_at=catalog.effective_at,
                        created_by=catalog.created_by,
                        metadata_json=_dump_json(catalog.metadata),
                    ),
                )
                self._insert_rules(conn, catalog_id, catalog.rules)
        except IntegrityError as exc:
            raise DuplicateCatalogVersionError(catalog.version) from exc
        return catalog_id

    def publish_catalog(
        self,
        catalog: Any,
        *,
        published_at: datetime,
    ) -> str:
        """Insert a complete published catalog in one transaction."""
        catalog_id = str(uuid4())
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    insert(billing_price_catalogs).values(
                        id=catalog_id,
                        version=catalog.version,
                        status="published",
                        effective_at=catalog.effective_at,
                        published_at=published_at,
                        created_by=catalog.created_by,
                        metadata_json=_dump_json(catalog.metadata),
                        updated_at=published_at,
                    ),
                )
                self._insert_rules(conn, catalog_id, catalog.rules)
        except IntegrityError as exc:
            raise DuplicateCatalogVersionError(catalog.version) from exc
        return catalog_id

    def replace_draft_rules(
        self,
        catalog_id: str,
        rules: Iterable[Any],
    ) -> None:
        """Replace rules only while a catalog is still an unpublished draft."""
        with self.engine.begin() as conn:
            catalog = (
                conn.execute(self._draft_for_update_statement(catalog_id))
                .mappings()
                .first()
            )
            if catalog is None:
                raise CatalogNotFoundError(catalog_id)
            if catalog["status"] != "draft":
                raise CatalogImmutableError(
                    f"published catalog is immutable: {catalog_id}",
                )
            conn.execute(self._guarded_delete_rules_statement(catalog_id))
            self._insert_rules(conn, catalog_id, rules)

    @staticmethod
    def _draft_for_update_statement(catalog_id: str):
        return (
            select(
                billing_price_catalogs.c.id,
                billing_price_catalogs.c.status,
            )
            .where(billing_price_catalogs.c.id == catalog_id)
            .with_for_update()
        )

    @staticmethod
    def _guarded_delete_rules_statement(catalog_id: str):
        draft_exists = exists(
            select(billing_price_catalogs.c.id).where(
                billing_price_catalogs.c.id == catalog_id,
                billing_price_catalogs.c.status == "draft",
            ),
        )
        return delete(billing_price_rules).where(
            billing_price_rules.c.catalog_id == catalog_id,
            draft_exists,
        )

    def publish_draft(
        self,
        catalog_id: str,
        *,
        published_at: datetime,
    ) -> None:
        """Atomically transition one validated draft to published status."""
        with self.engine.begin() as conn:
            result = conn.execute(
                update(billing_price_catalogs)
                .where(
                    billing_price_catalogs.c.id == catalog_id,
                    billing_price_catalogs.c.status == "draft",
                )
                .values(
                    status="published",
                    published_at=published_at,
                    updated_at=published_at,
                ),
            )
            if result.rowcount:
                return
            catalog = conn.execute(
                select(billing_price_catalogs.c.status).where(
                    billing_price_catalogs.c.id == catalog_id,
                ),
            ).first()
            if catalog is None:
                raise CatalogNotFoundError(catalog_id)
            raise CatalogImmutableError(
                f"published catalog is immutable: {catalog_id}",
            )

    def effective_catalog(self, at: datetime) -> dict[str, Any]:
        """Return the latest catalog effective at ``at`` and its rules."""
        with self.engine.connect() as conn:
            catalog = (
                conn.execute(
                    select(billing_price_catalogs)
                    .where(
                        billing_price_catalogs.c.status == "published",
                        billing_price_catalogs.c.effective_at.is_not(None),
                        billing_price_catalogs.c.effective_at <= at,
                        billing_price_catalogs.c.published_at <= at,
                    )
                    .order_by(
                        billing_price_catalogs.c.effective_at.desc(),
                        billing_price_catalogs.c.published_at.desc(),
                        billing_price_catalogs.c.version.desc(),
                    )
                    .limit(1),
                )
                .mappings()
                .first()
            )
            if catalog is None:
                raise CatalogNotFoundError(
                    "no published retail catalog effective at "
                    f"{at.isoformat()}",
                )
            rules = (
                conn.execute(
                    select(billing_price_rules).where(
                        billing_price_rules.c.catalog_id == catalog["id"],
                        billing_price_rules.c.status == "active",
                    ),
                )
                .mappings()
                .all()
            )

        result = dict(catalog)
        result["metadata"] = _load_json(result.pop("metadata_json"))
        result["rules"] = [_decode_rule(dict(rule)) for rule in rules]
        return result

    @staticmethod
    def _insert_rules(
        conn: Connection,
        catalog_id: str,
        rules: Iterable[Any],
    ) -> None:
        values = [
            {
                "id": rule.id,
                "catalog_id": catalog_id,
                "provider_id": rule.provider_id,
                "model_key": rule.model_key,
                "capability": rule.capability,
                "unit_type": rule.unit_type,
                "status": "active",
                "priority": rule.priority,
                "unit_size": rule.unit_size,
                "credits_per_unit": rule.credits_per_unit,
                "input_credits_per_1k": rule.input_credits_per_1k,
                "output_credits_per_1k": rule.output_credits_per_1k,
                "parameter_match_json": _dump_json(rule.parameter_match),
                "metadata_json": _dump_json(rule.metadata),
            }
            for rule in rules
        ]
        if values:
            conn.execute(insert(billing_price_rules), values)


def _decode_rule(rule: dict[str, Any]) -> dict[str, Any]:
    rule["parameter_match"] = _load_json(rule.pop("parameter_match_json"))
    rule["metadata"] = _load_json(rule.pop("metadata_json"))
    return rule


def _dump_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _load_json(value: str) -> dict[str, Any]:
    loaded = json.loads(value or "{}")
    if not isinstance(loaded, dict):
        raise ValueError("catalog JSON fields must contain objects")
    return loaded
