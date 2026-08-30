"""Admin orchestration for cost-derived immutable price catalogs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal
from typing import Any

from ..storage.repos.price_catalog_repo import PriceCatalogRepository
from ..storage.repos.pricing_admin_repo import PricingAdminRepository
from .pricing import PriceCatalogDraft, PriceCatalogService, PriceRule
from .official_pricing import OfficialPriceRegistry
from .pricing_draft import PricingDraftBuilder
from .pricing_models import (
    ModelIdentity,
    PricingDefaults,
    PricingPolicy,
    TrustedCost,
)
from .pricing_policy import build_catalog_rules


class PricingAdminService:
    def __init__(
        self,
        repository: PricingAdminRepository,
        pricing: PriceCatalogService,
        catalogs: PriceCatalogRepository,
        inventory: Any,
        *,
        clock: Callable[[], datetime] | None = None,
        draft_builder: PricingDraftBuilder | None = None,
    ) -> None:
        self.repository = repository
        self.pricing = pricing
        self.catalogs = catalogs
        self.inventory = inventory
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.draft_builder = draft_builder or PricingDraftBuilder(
            OfficialPriceRegistry.load_bundled()
        )

    def generate_draft(self, actor_id: str) -> dict[str, Any]:
        del actor_id
        models = tuple(self.inventory.list_enabled())
        draft_key = self._draft_key(models)
        result = self.draft_builder.build(
            models,
            self.repository.latest_trusted_costs(),
            self.repository.list_model_mappings(),
            self.repository.list_draft_exclusions(draft_key),
        )
        return {
            "draft_key": draft_key,
            "coverage": asdict(result.coverage),
            "rows": [asdict(row) for row in result.rows],
            "risks": [asdict(risk) for risk in result.risks],
            "result": result,
        }

    def set_exclusion(
        self,
        draft_key: str,
        provider_id: str,
        model_key: str,
        excluded: bool,
        reason: str | None,
        actor_id: str,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        current_key = self._draft_key(tuple(self.inventory.list_enabled()))
        if draft_key != current_key:
            raise ValueError("pricing draft is stale")
        saved = self.repository.replace_draft_exclusion(
            draft_key,
            provider_id,
            model_key,
            excluded,
            reason,
            actor_id,
        )
        self.repository.append_audit(
            "draft.exclusion.updated",
            actor_id,
            {},
            saved,
            {"ip_address": ip_address},
        )
        return saved

    @staticmethod
    def _draft_key(models: tuple[Any, ...]) -> str:
        identity = [
            {
                "provider_id": model.provider_id,
                "model_key": model.model_key,
                "official_model_id": model.official_model_id,
                "category": model.category,
            }
            for model in models
        ]
        encoded = json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def save_policy(
        self,
        scope_type: str,
        scope_key: str,
        multiplier_decimal: str,
        settings: dict[str, Any],
        actor_id: str,
        expected_revision: int,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        if Decimal(multiplier_decimal) < PricingDefaults().minimum_multiplier:
            raise ValueError("multiplier is below the 1.3 safety floor")
        saved = self.repository.replace_policy(
            scope_type=scope_type,
            scope_key=scope_key,
            multiplier_decimal=multiplier_decimal,
            settings=settings,
            actor_id=actor_id,
            expected_revision=expected_revision,
        )
        self.repository.append_audit(
            "policy.updated",
            actor_id,
            {},
            saved,
            {"ip_address": ip_address},
        )
        return saved

    def overview(self) -> dict[str, Any]:
        models = self.inventory.list_enabled()
        costs = self.repository.latest_trusted_costs()
        covered = {(row["provider_id"], row["model_key"]) for row in costs}
        return {
            "enabled_models": len(models),
            "covered_models": sum(
                (model.provider_id, model.model_key) in covered
                for model in models
            ),
            "catalogs": self.pricing.list_catalogs(),
        }

    def preview_initial_catalog(
        self,
        actor_id: str,
        imported_rows: list[dict[str, Any]] | None = None,
        import_id: str | None = None,
    ) -> dict[str, Any]:
        models = self.inventory.list_enabled()
        if imported_rows and any(
            "official_model_id" in row for row in imported_rows
        ):
            self._validate_imported_draft_rows(models, imported_rows)
        excluded_models = {
            (str(row["provider_id"]), str(row["model_key"]))
            for row in imported_rows or []
            if row.get("excluded") is True
        }
        costs = {
            (
                row["provider_id"],
                row["model_key"],
                row["unit_key"],
            ): TrustedCost(Decimal(row["rmb_cost_decimal"]), row["unit_key"])
            for row in self.repository.latest_trusted_costs()
        }
        for row in imported_rows or []:
            if (
                row.get("verification_status") == "verified"
                and row.get("excluded") is not True
            ):
                amount = Decimal(row["rmb_cost_decimal"])
                if row["unit_key"] in {
                    "input_tokens",
                    "output_tokens",
                } and row.get("unit_size"):
                    amount = (
                        amount * Decimal(1000) / Decimal(int(row["unit_size"]))
                    )
                costs[
                    (
                        row["provider_id"],
                        row["model_key"],
                        row["unit_key"],
                    )
                ] = TrustedCost(
                    amount,
                    row["unit_key"],
                )
        blockers = []
        identities = []
        for model in models:
            if (model.provider_id, model.model_key) in excluded_models:
                continue
            identities.append(
                ModelIdentity(
                    model.provider_id, model.model_key, model.category
                )
            )
            required = (
                ("input_tokens", "output_tokens")
                if model.category == "text"
                else ()
            )
            for unit in required:
                if (model.provider_id, model.model_key, unit) not in costs:
                    blockers.append(
                        {
                            "code": "trusted_cost_missing",
                            "provider_id": model.provider_id,
                            "model_key": model.model_key,
                            "unit_key": unit,
                        }
                    )
            if not required and not any(
                key[:2] == (model.provider_id, model.model_key)
                for key in costs
            ):
                blockers.append(
                    {
                        "code": "trusted_cost_missing",
                        "provider_id": model.provider_id,
                        "model_key": model.model_key,
                        "unit_key": "any",
                    }
                )
        if blockers:
            return {"publishable": False, "blockers": blockers}
        policy_rows = self.repository.list_policies()
        imported_policy_keys = {
            f"{row['provider_id']}/{row['model_key']}"
            for row in imported_rows or []
            if row.get("excluded") is not True
        }
        policy_rows = [
            row
            for row in policy_rows
            if not (
                row["scope_type"] == "model"
                and row["scope_key"] in imported_policy_keys
            )
        ]
        policy_rows.extend(
            {
                "scope_type": "model",
                "scope_key": f"{row['provider_id']}/{row['model_key']}",
                "multiplier_decimal": row["multiplier_decimal"],
            }
            for row in imported_rows or []
            if row.get("excluded") is not True
        )
        if not policy_rows:
            policy_rows.append(
                {
                    "scope_type": "global",
                    "scope_key": "*",
                    "multiplier_decimal": "1.5",
                }
            )
        policies = tuple(
            PricingPolicy(
                row["scope_type"],
                row["scope_key"],
                Decimal(row["multiplier_decimal"]),
            )
            for row in policy_rows
        )
        rules = (
            self._build_imported_rules(imported_rows)
            if imported_rows
            else build_catalog_rules(
                tuple(identities), costs, policies, PricingDefaults()
            )
        )
        version = f"admin-{self.clock().strftime('%Y%m%d%H%M%S')}"
        metadata = {
            "source": "pricing_admin",
            "exclusions": [
                {
                    "provider_id": row["provider_id"],
                    "model_key": row["model_key"],
                    "reason": row.get("exclusion_reason"),
                }
                for row in imported_rows or []
                if row.get("excluded") is True
            ],
        }
        if import_id is not None:
            metadata.update(
                source="pricing_excel",
                pricing_import_id=import_id,
            )
        catalog_id = self.pricing.create_draft(
            PriceCatalogDraft(
                version=version,
                effective_at=self.clock(),
                rules=rules,
                created_by=f"admin:{actor_id}",
                metadata=metadata,
            )
        )
        return {
            "publishable": True,
            "blockers": [],
            "catalog_id": catalog_id,
            "version": version,
            "rule_count": len(rules),
        }

    def _validate_imported_draft_rows(
        self,
        models: Any,
        imported_rows: list[dict[str, Any]],
    ) -> None:
        current = self.draft_builder.build(
            models,
            self.repository.latest_trusted_costs(),
            self.repository.list_model_mappings(),
            (),
        )
        allowed = {
            (
                row.provider_id,
                row.model_key,
                row.official_provider_id or "",
                row.official_model_id or "",
                row.unit_key,
                json.dumps(
                    row.conditions,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                row.registry_version or "",
            )
            for row in current.rows
        }
        for row in imported_rows:
            identity = (
                str(row["provider_id"]),
                str(row["model_key"]),
                str(row.get("official_provider_id") or ""),
                str(row.get("official_model_id") or ""),
                str(row.get("unit_key") or ""),
                json.dumps(
                    row.get("conditions") or {},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                str(row.get("registry_version") or ""),
            )
            if identity not in allowed:
                raise ValueError("pricing draft identity or registry is stale")

    @staticmethod
    def _build_imported_rules(
        imported_rows: list[dict[str, Any]],
    ) -> tuple[PriceRule, ...]:
        included = [
            row
            for row in imported_rows
            if row.get("excluded") is not True
            and row.get("verification_status") == "verified"
        ]
        token_groups: dict[
            tuple[str, str, str], dict[str, dict[str, Any]]
        ] = {}
        other_rows: list[dict[str, Any]] = []
        for row in included:
            if row.get("category") != "text":
                other_rows.append(row)
                continue
            conditions = {
                key: value
                for key, value in dict(row.get("conditions") or {}).items()
                if key in {"input_tokens_min_exclusive", "input_tokens_max"}
            }
            group_key = (
                str(row["provider_id"]),
                str(row["model_key"]),
                json.dumps(conditions, sort_keys=True, separators=(",", ":")),
            )
            token_groups.setdefault(group_key, {})[str(row["unit_key"])] = row

        rules: list[PriceRule] = []
        for (provider_id, model_key, conditions_json), components in sorted(
            token_groups.items()
        ):
            if set(components) != {"input_tokens", "output_tokens"}:
                raise ValueError(
                    f"incomplete token price dimensions: {provider_id}/{model_key}"
                )
            input_row = components["input_tokens"]
            output_row = components["output_tokens"]
            input_unit = int(input_row.get("unit_size") or 1_000)
            output_unit = int(output_row.get("unit_size") or 1_000)
            if input_unit != output_unit:
                raise ValueError("token price dimensions use different units")
            input_credits = PricingAdminService._row_credits(input_row)
            output_credits = PricingAdminService._row_credits(output_row)
            digest = hashlib.sha256(conditions_json.encode()).hexdigest()[:12]
            rules.append(
                PriceRule(
                    id=f"imported:{provider_id}:{model_key}:tokens:{digest}",
                    provider_id=provider_id,
                    model_key=model_key,
                    capability=str(input_row.get("capability") or "chat"),
                    unit_type="tokens",
                    unit_size=input_unit,
                    input_credits_per_1k=input_credits,
                    output_credits_per_1k=output_credits,
                    parameter_match=json.loads(conditions_json),
                    metadata={
                        "currency": "CNY",
                        "token_unit_size": input_unit,
                        "input_rmb_cost": str(input_row["rmb_cost_decimal"]),
                        "output_rmb_cost": str(output_row["rmb_cost_decimal"]),
                        "applied_multiplier": str(
                            input_row["multiplier_decimal"]
                        ),
                    },
                )
            )
        for row in other_rows:
            unit_type = {
                "image": "image_count",
                "video": "video_duration",
            }.get(str(row.get("category")), "fixed_workflow")
            rules.append(
                PriceRule(
                    id=(
                        f"imported:{row['provider_id']}:{row['model_key']}:"
                        f"{row['unit_key']}"
                    ),
                    provider_id=str(row["provider_id"]),
                    model_key=str(row["model_key"]),
                    capability=str(
                        row.get("capability") or row.get("category")
                    ),
                    unit_type=unit_type,
                    unit_size=int(row.get("unit_size") or 1),
                    credits_per_unit=PricingAdminService._row_credits(row),
                    parameter_match=dict(row.get("conditions") or {}),
                    metadata={
                        "currency": "CNY",
                        "rmb_cost": str(row["rmb_cost_decimal"]),
                        "applied_multiplier": str(row["multiplier_decimal"]),
                    },
                )
            )
        if not rules:
            raise ValueError(
                "catalog must contain at least one eligible price"
            )
        return tuple(rules)

    @staticmethod
    def _row_credits(row: dict[str, Any]) -> int:
        cost = Decimal(str(row["rmb_cost_decimal"]))
        multiplier = Decimal(str(row["multiplier_decimal"]))
        if multiplier < PricingDefaults().minimum_multiplier:
            raise ValueError("multiplier is below the 1.3 safety floor")
        return int(
            (cost * multiplier * 100).to_integral_value(rounding=ROUND_CEILING)
        )

    def publish_preview(
        self,
        catalog_id: str,
        actor_id: str,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        catalog = self.catalogs.get_catalog(catalog_id)
        import_id = catalog["metadata"].get("pricing_import_id")
        if (
            import_id is not None
            and not self.repository.import_allows_publish(
                str(import_id), catalog_id
            )
        ):
            raise ValueError("pricing import is not confirmed")
        published = self.pricing.publish_draft(catalog_id)
        self.repository.append_audit(
            "catalog.published",
            actor_id,
            {},
            {"catalog_id": catalog_id, "version": published["version"]},
            {"ip_address": ip_address},
        )
        return published

    def rollback(
        self,
        catalog_id: str,
        actor_id: str,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        source = self.catalogs.get_catalog(catalog_id)
        if source["status"] != "published":
            raise ValueError("rollback source must be a published catalog")
        rules = tuple(
            PriceRule(
                id=f"rollback:{rule['id']}",
                provider_id=rule["provider_id"],
                model_key=rule["model_key"],
                capability=rule["capability"],
                unit_type=rule["unit_type"],
                priority=rule["priority"],
                unit_size=rule["unit_size"],
                credits_per_unit=rule["credits_per_unit"],
                input_credits_per_1k=rule["input_credits_per_1k"],
                output_credits_per_1k=rule["output_credits_per_1k"],
                parameter_match=rule["parameter_match"],
                metadata=rule["metadata"],
            )
            for rule in source["rules"]
        )
        version = f"rollback-{self.clock().strftime('%Y%m%d%H%M%S')}"
        new_id = self.pricing.publish(
            PriceCatalogDraft(
                version=version,
                effective_at=self.clock(),
                rules=rules,
                created_by=f"admin:{actor_id}",
                metadata={"rollback_of": catalog_id},
            )
        )
        published = self.catalogs.get_catalog(new_id)
        self.repository.append_audit(
            "catalog.rolled_back",
            actor_id,
            {"catalog_id": catalog_id},
            {"catalog_id": new_id},
            {"ip_address": ip_address},
        )
        return published
