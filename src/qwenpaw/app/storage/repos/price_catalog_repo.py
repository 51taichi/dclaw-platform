# -*- coding: utf-8 -*-
"""Persistence for versioned DClaw retail price catalogs."""
from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
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
        self.publish_draft_validated(
            catalog_id,
            published_at=published_at,
            validate=lambda _catalog: None,
        )

    def publish_draft_validated(
        self,
        catalog_id: str,
        *,
        published_at: datetime,
        validate: Callable[[dict[str, Any]], None],
    ) -> None:
        """Lock, validate, and publish the same stored draft snapshot."""
        with self.engine.begin() as conn:
            catalog = (
                conn.execute(
                    select(billing_price_catalogs)
                    .where(billing_price_catalogs.c.id == catalog_id)
                    .with_for_update(),
                )
                .mappings()
                .first()
            )
            if catalog is None:
                raise CatalogNotFoundError(catalog_id)
            if catalog["status"] != "draft":
                raise CatalogImmutableError(
                    f"published catalog is immutable: {catalog_id}",
                )

            rules = (
                conn.execute(
                    select(billing_price_rules)
                    .where(billing_price_rules.c.catalog_id == catalog_id)
                    .order_by(billing_price_rules.c.id),
                )
                .mappings()
                .all()
            )
            validate(_decode_catalog(catalog, rules))

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
            raise CatalogImmutableError(
                f"published catalog is immutable: {catalog_id}",
            )

    def get_catalog(self, catalog_id: str) -> dict[str, Any]:
        """Return one catalog with decoded rules for admin validation."""
        with self.engine.connect() as conn:
            catalog = (
                conn.execute(
                    select(billing_price_catalogs).where(
                        billing_price_catalogs.c.id == catalog_id,
                    ),
                )
                .mappings()
                .first()
            )
            if catalog is None:
                raise CatalogNotFoundError(catalog_id)
            rules = (
                conn.execute(
                    select(billing_price_rules)
                    .where(billing_price_rules.c.catalog_id == catalog_id)
                    .order_by(billing_price_rules.c.id),
                )
                .mappings()
                .all()
            )
        return _decode_catalog(catalog, rules)

    def list_catalogs(self) -> list[dict[str, Any]]:
        """List catalogs and their rules for the trusted admin API."""
        with self.engine.connect() as conn:
            catalogs = (
                conn.execute(
                    select(billing_price_catalogs).order_by(
                        billing_price_catalogs.c.created_at.desc(),
                        billing_price_catalogs.c.version.desc(),
                    ),
                )
                .mappings()
                .all()
            )
            rules = conn.execute(
                select(billing_price_rules).order_by(
                    billing_price_rules.c.catalog_id,
                    billing_price_rules.c.id,
                ),
            ).mappings()
            rules_by_catalog: dict[str, list[Mapping[str, Any]]] = {}
            for rule in rules:
                rules_by_catalog.setdefault(
                    str(rule["catalog_id"]),
                    [],
                ).append(
                    rule,
                )
        return [
            _decode_catalog(
                catalog,
                rules_by_catalog.get(str(catalog["id"]), []),
            )
            for catalog in catalogs
        ]

    def effective_catalog(self, at: datetime) -> dict[str, Any]:
        """Return the latest catalog effective at ``at`` and its rules."""
        with self.engine.connect() as conn:
            return self._effective_catalog_in_connection(conn, at)

    def lock_effective_catalog(
        self,
        conn: Connection,
        at: datetime,
    ) -> dict[str, Any]:
        """Lock and return the catalog selected by the pricing authority."""
        return self._effective_catalog_in_connection(
            conn,
            at,
            for_update=True,
        )

    @staticmethod
    def _effective_catalog_in_connection(
        conn: Connection,
        at: datetime,
        *,
        for_update: bool = False,
    ) -> dict[str, Any]:
        statement = (
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
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update()
        catalog = conn.execute(statement).mappings().first()
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
        rule_list = list(rules)
        business_ids = [rule.id for rule in rule_list]
        existing_ids = set(conn.execute(
            select(billing_price_rules.c.id).where(
                billing_price_rules.c.id.in_(business_ids),
            )
        ).scalars()) if business_ids else set()
        values = [
            {
                # ``id`` is a physical row key and must be unique across
                # immutable catalog versions.  The stable business rule key
                # is preserved in metadata and restored when decoding.
                # Preserve legacy first-version IDs because usage rows have a
                # foreign key to this column.  Only later catalog versions
                # with the same stable business key need a catalog prefix.
                "id": (f"{catalog_id}:{rule.id}"
                       if rule.id in existing_ids else rule.id),
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
                "metadata_json": _dump_json({
                    **dict(rule.metadata), "_business_rule_id": rule.id,
                }),
            }
            for rule in rule_list
        ]
        if values:
            conn.execute(insert(billing_price_rules), values)


def _decode_rule(rule: dict[str, Any]) -> dict[str, Any]:
    storage_id = rule["id"]
    rule["parameter_match"] = _load_json(rule.pop("parameter_match_json"))
    rule["metadata"] = _load_json(rule.pop("metadata_json"))
    rule["id"] = rule["metadata"].pop("_business_rule_id", rule["id"])
    rule["storage_id"] = storage_id
    return rule


def _decode_catalog(
    catalog: Mapping[str, Any],
    rules: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    result = dict(catalog)
    result["metadata"] = _load_json(result.pop("metadata_json"))
    result["rules"] = [_decode_rule(dict(rule)) for rule in rules]
    return result


def _dump_json(value: Any) -> str:
    return json.dumps(
        _to_jsonable(value),
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


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [_to_jsonable(item) for item in value]
    return value
