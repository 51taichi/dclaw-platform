"""Admin orchestration for cost-derived immutable price catalogs."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from ..storage.repos.price_catalog_repo import PriceCatalogRepository
from ..storage.repos.pricing_admin_repo import PricingAdminRepository
from .pricing import PriceCatalogDraft, PriceCatalogService, PriceRule
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
    ) -> None:
        self.repository = repository
        self.pricing = pricing
        self.catalogs = catalogs
        self.inventory = inventory
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def save_policy(
        self,
        scope_type: str,
        scope_key: str,
        multiplier_decimal: str,
        settings: dict[str, Any],
        actor_id: str,
        expected_revision: int,
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
        self.repository.append_audit("policy.updated", actor_id, {}, saved)
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

    def preview_initial_catalog(self, actor_id: str) -> dict[str, Any]:
        models = self.inventory.list_enabled()
        costs = {
            (
                row["provider_id"],
                row["model_key"],
                row["unit_key"],
            ): TrustedCost(Decimal(row["rmb_cost_decimal"]), row["unit_key"])
            for row in self.repository.latest_trusted_costs()
        }
        blockers = []
        identities = []
        for model in models:
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
        policies = tuple(
            PricingPolicy(
                row["scope_type"],
                row["scope_key"],
                Decimal(row["multiplier_decimal"]),
            )
            for row in self.repository.list_policies()
        )
        rules = build_catalog_rules(
            tuple(identities), costs, policies, PricingDefaults()
        )
        version = f"admin-{self.clock().strftime('%Y%m%d%H%M%S')}"
        catalog_id = self.pricing.create_draft(
            PriceCatalogDraft(
                version=version,
                effective_at=self.clock(),
                rules=rules,
                created_by=f"admin:{actor_id}",
                metadata={"source": "pricing_admin"},
            )
        )
        return {
            "publishable": True,
            "blockers": [],
            "catalog_id": catalog_id,
            "version": version,
            "rule_count": len(rules),
        }

    def publish_preview(
        self, catalog_id: str, actor_id: str
    ) -> dict[str, Any]:
        published = self.pricing.publish_draft(catalog_id)
        self.repository.append_audit(
            "catalog.published",
            actor_id,
            {},
            {"catalog_id": catalog_id, "version": published["version"]},
        )
        return published

    def rollback(self, catalog_id: str, actor_id: str) -> dict[str, Any]:
        source = self.catalogs.get_catalog(catalog_id)
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
        )
        return published
