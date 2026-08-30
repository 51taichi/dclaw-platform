"""Persistence for trusted pricing costs, policies, imports, and unlocks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from ..schema import (
    billing_cost_snapshots,
    billing_official_price_candidates,
    billing_pricing_audits,
    billing_pricing_draft_exclusions,
    billing_pricing_imports,
    billing_pricing_model_mappings,
    billing_pricing_policies,
    billing_pricing_sync_state,
    billing_pricing_unlock_attempts,
    billing_pricing_unlocks,
)


class PricingRevisionConflict(RuntimeError):
    """A pricing policy was changed after the caller loaded it."""


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


class PricingAdminRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def append_cost_snapshot(self, values: Mapping[str, Any]) -> str:
        row = dict(values)
        row["id"] = str(uuid4())
        row["conditions_json"] = _json(row.pop("conditions", {}))
        with self.engine.begin() as conn:
            conn.execute(insert(billing_cost_snapshots).values(**row))
        return str(row["id"])

    def list_cost_snapshots(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    select(billing_cost_snapshots).order_by(
                        billing_cost_snapshots.c.verified_at.desc(),
                        billing_cost_snapshots.c.created_at.desc(),
                    ),
                ).mappings()
            ]

    def latest_trusted_costs(self) -> list[dict[str, Any]]:
        latest: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for row in self.list_cost_snapshots():
            if row["verification_status"] != "verified":
                continue
            key = tuple(
                str(row[name])
                for name in (
                    "provider_id",
                    "model_key",
                    "capability",
                    "unit_key",
                )
            )
            latest.setdefault(key, row)
        return list(latest.values())

    def append_official_candidate(self, values: Mapping[str, Any]) -> str:
        row = dict(values)
        row["id"] = str(uuid4())
        row["conditions_json"] = _json(row.pop("conditions", {}))
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    insert(billing_official_price_candidates).values(**row)
                )
        except IntegrityError:
            pass
        with self.engine.connect() as conn:
            return str(
                conn.execute(
                    select(billing_official_price_candidates.c.id).where(
                        billing_official_price_candidates.c.content_sha256
                        == values["content_sha256"]
                    )
                ).scalar_one()
            )

    def latest_official_candidates(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    select(billing_official_price_candidates).order_by(
                        billing_official_price_candidates.c.created_at.desc()
                    )
                ).mappings()
            ]

    def replace_model_mapping(
        self,
        provider_id: str,
        model_key: str,
        official_model_id: str,
        actor_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        with self.engine.begin() as conn:
            current = (
                conn.execute(
                    select(billing_pricing_model_mappings).where(
                        billing_pricing_model_mappings.c.provider_id
                        == provider_id,
                        billing_pricing_model_mappings.c.model_key
                        == model_key,
                    )
                )
                .mappings()
                .first()
            )
            if current is None:
                if expected_revision != 0:
                    raise PricingRevisionConflict(model_key)
                row = {
                    "id": str(uuid4()),
                    "provider_id": provider_id,
                    "model_key": model_key,
                    "official_model_id": official_model_id,
                    "revision": 1,
                    "updated_by": actor_id,
                }
                conn.execute(
                    insert(billing_pricing_model_mappings).values(**row)
                )
            else:
                if int(current["revision"]) != expected_revision:
                    raise PricingRevisionConflict(model_key)
                row = dict(current)
                row.update(
                    official_model_id=official_model_id,
                    revision=expected_revision + 1,
                    updated_by=actor_id,
                )
                result = conn.execute(
                    update(billing_pricing_model_mappings)
                    .where(
                        billing_pricing_model_mappings.c.id == current["id"],
                        billing_pricing_model_mappings.c.revision
                        == expected_revision,
                    )
                    .values(
                        official_model_id=official_model_id,
                        revision=expected_revision + 1,
                        updated_by=actor_id,
                    )
                )
                if result.rowcount != 1:
                    raise PricingRevisionConflict(model_key)
            return {
                "id": str(row["id"]),
                "provider_id": provider_id,
                "model_key": model_key,
                "official_model_id": official_model_id,
                "revision": int(row["revision"]),
            }

    def list_model_mappings(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    select(billing_pricing_model_mappings).order_by(
                        billing_pricing_model_mappings.c.provider_id,
                        billing_pricing_model_mappings.c.model_key,
                    )
                ).mappings()
            ]

    def replace_draft_exclusion(
        self,
        draft_key: str,
        provider_id: str,
        model_key: str,
        excluded: bool,
        reason: str | None,
        actor_id: str,
    ) -> dict[str, Any]:
        normalized_reason = (reason or "").strip() or None
        if excluded and normalized_reason is None:
            raise ValueError("exclusion reason is required")
        with self.engine.begin() as conn:
            current = (
                conn.execute(
                    select(billing_pricing_draft_exclusions).where(
                        billing_pricing_draft_exclusions.c.draft_key
                        == draft_key,
                        billing_pricing_draft_exclusions.c.provider_id
                        == provider_id,
                        billing_pricing_draft_exclusions.c.model_key
                        == model_key,
                    )
                )
                .mappings()
                .first()
            )
            values = {
                "excluded": excluded,
                "reason": normalized_reason,
                "updated_by": actor_id,
            }
            if current is None:
                row_id = str(uuid4())
                conn.execute(
                    insert(billing_pricing_draft_exclusions).values(
                        id=row_id,
                        draft_key=draft_key,
                        provider_id=provider_id,
                        model_key=model_key,
                        **values,
                    )
                )
            else:
                row_id = str(current["id"])
                conn.execute(
                    update(billing_pricing_draft_exclusions)
                    .where(billing_pricing_draft_exclusions.c.id == row_id)
                    .values(**values)
                )
        return {
            "id": row_id,
            "draft_key": draft_key,
            "provider_id": provider_id,
            "model_key": model_key,
            **values,
        }

    def replace_policy(
        self,
        *,
        scope_type: str,
        scope_key: str,
        multiplier_decimal: str,
        settings: Mapping[str, Any],
        actor_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        with self.engine.begin() as conn:
            current = (
                conn.execute(
                    select(billing_pricing_policies).where(
                        billing_pricing_policies.c.scope_type == scope_type,
                        billing_pricing_policies.c.scope_key == scope_key,
                    )
                )
                .mappings()
                .first()
            )
            if current is None:
                if expected_revision != 0:
                    raise PricingRevisionConflict(scope_key)
                policy_id, revision = str(uuid4()), 1
                conn.execute(
                    insert(billing_pricing_policies).values(
                        id=policy_id,
                        scope_type=scope_type,
                        scope_key=scope_key,
                        multiplier_decimal=multiplier_decimal,
                        settings_json=_json(settings),
                        revision=revision,
                        updated_by=actor_id,
                    )
                )
            else:
                if int(current["revision"]) != expected_revision:
                    raise PricingRevisionConflict(scope_key)
                policy_id, revision = str(current["id"]), expected_revision + 1
                result = conn.execute(
                    update(billing_pricing_policies)
                    .where(
                        billing_pricing_policies.c.id == policy_id,
                        billing_pricing_policies.c.revision
                        == expected_revision,
                    )
                    .values(
                        multiplier_decimal=multiplier_decimal,
                        settings_json=_json(settings),
                        revision=revision,
                        updated_by=actor_id,
                    )
                )
                if result.rowcount != 1:
                    raise PricingRevisionConflict(scope_key)
            return {
                "id": policy_id,
                "scope_type": scope_type,
                "scope_key": scope_key,
                "revision": revision,
                "multiplier_decimal": multiplier_decimal,
            }

    def list_policies(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    select(billing_pricing_policies).order_by(
                        billing_pricing_policies.c.scope_type,
                        billing_pricing_policies.c.scope_key,
                    ),
                ).mappings()
            ]

    def record_import(
        self,
        digest: str,
        filename: str,
        actor_id: str,
        preview: Mapping[str, Any],
    ) -> dict[str, Any]:
        row = {
            "id": str(uuid4()),
            "content_sha256": digest,
            "filename": filename,
            "status": "previewed",
            "preview_json": _json(preview),
            "created_by": actor_id,
        }
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(billing_pricing_imports).values(**row))
        except IntegrityError:
            pass
        with self.engine.connect() as conn:
            return dict(
                conn.execute(
                    select(billing_pricing_imports).where(
                        billing_pricing_imports.c.content_sha256 == digest,
                    )
                )
                .mappings()
                .one()
            )

    def get_import(self, import_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(billing_pricing_imports).where(
                        billing_pricing_imports.c.id == import_id,
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            result = dict(row)
            result["preview"] = json.loads(result["preview_json"])
            return result

    def import_allows_publish(self, import_id: str, catalog_id: str) -> bool:
        imported = self.get_import(import_id)
        if imported is None or imported["status"] != "confirmed":
            return False
        pricing_preview = imported["preview"].get("pricing_preview", {})
        return pricing_preview.get("catalog_id") == catalog_id

    def confirm_import(self, import_id: str) -> None:
        with self.engine.begin() as conn:
            result = conn.execute(
                update(billing_pricing_imports)
                .where(
                    billing_pricing_imports.c.id == import_id,
                    billing_pricing_imports.c.status == "previewed",
                )
                .values(status="confirmed")
            )
            if result.rowcount != 1:
                raise ValueError("import already confirmed or missing")

    def apply_import_rows(
        self,
        import_id: str,
        rows: list[Mapping[str, Any]],
        filename: str,
        actor_id: str,
        pricing_preview: Mapping[str, Any] | None,
        ip_address: str | None = None,
    ) -> None:
        """Apply every imported cost/policy and claim the import atomically."""
        with self.engine.begin() as conn:
            imported = (
                conn.execute(
                    select(billing_pricing_imports).where(
                        billing_pricing_imports.c.id == import_id,
                    )
                )
                .mappings()
                .one()
            )
            if imported["status"] != "previewed":
                raise ValueError("import already confirmed or missing")
            policy_revisions: dict[str, int] = {}
            for source in rows:
                row = {
                    "id": str(uuid4()),
                    "provider_id": source["provider_id"],
                    "model_key": source["model_key"],
                    "capability": source["category"],
                    "unit_key": source["unit_key"],
                    "source_type": "excel",
                    "source_reference": filename,
                    "original_currency": "CNY",
                    "original_price_decimal": source["rmb_cost_decimal"],
                    "fx_rate_decimal": "1",
                    "rmb_cost_decimal": source["rmb_cost_decimal"],
                    "conditions_json": "{}",
                    "verification_status": source["verification_status"],
                    "verified_at": datetime.fromisoformat(
                        str(source["verified_at"]).replace("Z", "+00:00")
                    ),
                }
                conn.execute(insert(billing_cost_snapshots).values(**row))
                scope_key = f"{source['provider_id']}/{source['model_key']}"
                current = (
                    conn.execute(
                        select(billing_pricing_policies).where(
                            billing_pricing_policies.c.scope_type == "model",
                            billing_pricing_policies.c.scope_key == scope_key,
                        )
                    )
                    .mappings()
                    .first()
                )
                expected = policy_revisions.get(
                    scope_key,
                    int(current["revision"]) if current else 0,
                )
                revision = expected + 1
                if current is None:
                    conn.execute(
                        insert(billing_pricing_policies).values(
                            id=str(uuid4()),
                            scope_type="model",
                            scope_key=scope_key,
                            multiplier_decimal=source["multiplier_decimal"],
                            settings_json="{}",
                            revision=revision,
                            updated_by=actor_id,
                        )
                    )
                else:
                    result = conn.execute(
                        update(billing_pricing_policies)
                        .where(
                            billing_pricing_policies.c.id == current["id"],
                            billing_pricing_policies.c.revision == expected,
                        )
                        .values(
                            multiplier_decimal=source["multiplier_decimal"],
                            settings_json="{}",
                            revision=revision,
                            updated_by=actor_id,
                        )
                    )
                    if result.rowcount != 1:
                        raise PricingRevisionConflict(scope_key)
                policy_revisions[scope_key] = revision
            preview = json.loads(imported["preview_json"])
            preview["pricing_preview"] = dict(pricing_preview or {})
            conn.execute(
                update(billing_pricing_imports)
                .where(
                    billing_pricing_imports.c.id == import_id,
                    billing_pricing_imports.c.status == "previewed",
                )
                .values(status="confirmed", preview_json=_json(preview))
            )
            conn.execute(
                insert(billing_pricing_audits).values(
                    id=str(uuid4()),
                    action="excel.confirmed",
                    actor_id=actor_id,
                    before_json="{}",
                    after_json=_json(
                        {
                            "import_id": import_id,
                            "catalog_id": (pricing_preview or {}).get(
                                "catalog_id"
                            ),
                        }
                    ),
                    metadata_json=_json({"ip_address": ip_address}),
                )
            )

    def create_unlock(
        self,
        actor_id: str,
        token_hash: str,
        credential_fingerprint: str,
        expires_at: datetime,
        ip_address: str | None,
    ) -> str:
        unlock_id = str(uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                insert(billing_pricing_unlocks).values(
                    id=unlock_id,
                    actor_id=actor_id,
                    token_hash=token_hash,
                    credential_fingerprint=credential_fingerprint,
                    expires_at=expires_at,
                    ip_address=ip_address,
                )
            )
        return unlock_id

    def record_unlock_attempt(
        self,
        actor_id: str,
        ip_address: str | None,
        succeeded: bool,
        occurred_at: datetime,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                insert(billing_pricing_unlock_attempts).values(
                    id=str(uuid4()),
                    actor_id=actor_id,
                    ip_address=ip_address,
                    succeeded=succeeded,
                    created_at=occurred_at,
                )
            )

    def recent_unlock_failures(
        self,
        actor_id: str,
        ip_address: str | None,
        since: datetime,
    ) -> int:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(
                    billing_pricing_unlock_attempts.c.succeeded,
                )
                .where(
                    billing_pricing_unlock_attempts.c.actor_id == actor_id,
                    billing_pricing_unlock_attempts.c.ip_address == ip_address,
                    billing_pricing_unlock_attempts.c.created_at > since,
                )
                .order_by(
                    billing_pricing_unlock_attempts.c.created_at.desc(),
                )
            ).all()
        failures = 0
        for row in rows:
            if row[0]:
                break
            failures += 1
        return failures

    def append_audit(
        self,
        action: str,
        actor_id: str,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        audit_id = str(uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                insert(billing_pricing_audits).values(
                    id=audit_id,
                    action=action,
                    actor_id=actor_id,
                    before_json=_json(before),
                    after_json=_json(after),
                    metadata_json=_json(metadata or {}),
                )
            )
        return audit_id

    def list_audits(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    select(billing_pricing_audits).order_by(
                        billing_pricing_audits.c.created_at.desc()
                    ),
                ).mappings()
            ]

    def get_pricing_sync_time(self, state_key: str) -> datetime | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(
                    billing_pricing_sync_state.c.occurred_at,
                ).where(
                    billing_pricing_sync_state.c.state_key == state_key,
                )
            ).first()
            return row[0] if row else None

    def set_pricing_sync_time(
        self, state_key: str, occurred_at: datetime
    ) -> None:
        with self.engine.begin() as conn:
            result = conn.execute(
                update(billing_pricing_sync_state)
                .where(
                    billing_pricing_sync_state.c.state_key == state_key,
                )
                .values(
                    occurred_at=occurred_at,
                    updated_at=datetime.now(occurred_at.tzinfo),
                )
            )
            if result.rowcount == 0:
                conn.execute(
                    insert(billing_pricing_sync_state).values(
                        state_key=state_key, occurred_at=occurred_at
                    )
                )

    def validate_unlock(
        self,
        token_hash: str,
        actor_id: str,
        credential_fingerprint: str,
        now: datetime,
    ) -> bool:
        with self.engine.connect() as conn:
            return (
                conn.execute(
                    select(billing_pricing_unlocks.c.id).where(
                        billing_pricing_unlocks.c.token_hash == token_hash,
                        billing_pricing_unlocks.c.actor_id == actor_id,
                        billing_pricing_unlocks.c.credential_fingerprint
                        == credential_fingerprint,
                        billing_pricing_unlocks.c.revoked_at.is_(None),
                        billing_pricing_unlocks.c.expires_at > now,
                    )
                ).first()
                is not None
            )
