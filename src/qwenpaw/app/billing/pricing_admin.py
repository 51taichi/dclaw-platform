"""Admin orchestration for cost-derived immutable price catalogs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, replace
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
from .pricing_policy import build_catalog_rules, resolve_multiplier
from .pricing_spec import spec_key
from .pricing_inventory import PriceableModel


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
            self.repository.latest_official_candidates(),
            self.repository.list_model_publication_decisions(draft_key),
        )
        policies = self.repository.list_policies()
        multipliers = tuple(
            PricingPolicy(
                row["scope_type"], row["scope_key"], Decimal(row["multiplier_decimal"])
            )
            for row in policies
        )
        model_settings = {
            row["scope_key"]: json.loads(row.get("settings_json") or "{}")
            for row in policies
            if row["scope_type"] == "model"
        }
        updated_rows = []
        for row in result.rows:
            settings = model_settings.get(f"{row.provider_id}/{row.model_key}", {})
            key = json.dumps(
                spec_key(asdict(row)),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            configured = settings.get("dimension_multipliers", {}).get(key)
            if configured is not None:
                multiplier = Decimal(str(configured))
            else:
                try:
                    multiplier = resolve_multiplier(
                        multipliers,
                        ModelIdentity(row.provider_id, row.model_key, row.category),
                    ).value
                except LookupError:
                    multiplier = row.multiplier
            multiplier = max(multiplier, PricingDefaults().minimum_multiplier)
            sale = row.rmb_cost * multiplier if row.rmb_cost is not None else None
            updated_rows.append(
                replace(
                    row,
                    multiplier=multiplier,
                    rmb_sale_price=sale,
                    credits=int((sale * 100).to_integral_value(rounding=ROUND_CEILING))
                    if sale is not None
                    else None,
                )
            )
        result = replace(result, rows=tuple(updated_rows))
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

    def set_model_decisions(
        self,
        draft_key: str,
        decisions: list[dict[str, Any]],
        actor_id: str,
        ip_address: str | None = None,
    ) -> list[dict[str, Any]]:
        generated = self.generate_draft(actor_id)
        if generated["draft_key"] != draft_key:
            raise ValueError("pricing draft is stale")
        rows_by_model: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in generated["rows"]:
            rows_by_model.setdefault(
                (str(row["provider_id"]), str(row["model_key"])), []
            ).append(row)
        normalized: list[dict[str, Any]] = []
        for decision in decisions:
            key = (
                str(decision["provider_id"]),
                str(decision["model_key"]),
            )
            model_rows = rows_by_model.get(key)
            if not model_rows:
                raise ValueError("pricing draft model was not found")
            reason = str(decision.get("reason") or "").strip() or None
            include = bool(decision["include_in_publish"])
            if include and any(
                row.get("evidence_level") != "official_verified" for row in model_rows
            ):
                if reason is None:
                    raise ValueError(
                        "approval reason is required for non-official price"
                    )
            normalized.append(
                {
                    "provider_id": key[0],
                    "model_key": key[1],
                    "include_in_publish": include,
                    "reason": reason,
                }
            )
        before = self.repository.list_model_publication_decisions(draft_key)
        saved = self.repository.set_model_publication_decisions(
            draft_key, normalized, actor_id
        )
        self.repository.append_audit(
            "draft.model_decisions.updated",
            actor_id,
            {
                "decisions": [
                    {
                        key: row.get(key)
                        for key in (
                            "provider_id",
                            "model_key",
                            "include_in_publish",
                            "reason",
                        )
                    }
                    for row in before
                ]
            },
            {"decisions": normalized},
            {"ip_address": ip_address},
        )
        return saved

    def batch_set_model_decision(
        self,
        draft_key: str,
        *,
        include_in_publish: bool,
        provider_ids: list[str],
        evidence_levels: list[str],
        model_keys: list[str],
        reason: str | None,
        actor_id: str,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        generated = self.generate_draft(actor_id)
        if generated["draft_key"] != draft_key:
            raise ValueError("pricing draft is stale")
        selected: set[tuple[str, str]] = set()
        for row in generated["rows"]:
            if provider_ids and row["provider_id"] not in provider_ids:
                continue
            if model_keys and row["model_key"] not in model_keys:
                continue
            if evidence_levels and row.get("evidence_level") not in evidence_levels:
                continue
            selected.add((row["provider_id"], row["model_key"]))
        if not selected:
            raise ValueError("no pricing draft models matched the batch filter")
        saved = self.set_model_decisions(
            draft_key,
            [
                {
                    "provider_id": provider_id,
                    "model_key": model_key,
                    "include_in_publish": include_in_publish,
                    "reason": reason,
                }
                for provider_id, model_key in sorted(selected)
            ],
            actor_id,
            ip_address,
        )
        return {"updated_models": len(saved), "decisions": saved}

    def save_model_mapping(
        self,
        provider_id: str,
        model_key: str,
        official_provider_id: str,
        official_model_id: str,
        expected_revision: int,
        actor_id: str,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        if not official_provider_id.strip() or not official_model_id.strip():
            raise ValueError("official pricing identity is required")
        if not any(
            (model.provider_id, model.model_key) == (provider_id, model_key)
            for model in self.inventory.list_enabled()
        ):
            raise ValueError("enabled pricing model was not found")
        before = next(
            (
                row
                for row in self.repository.list_model_mappings()
                if (row["provider_id"], row["model_key"]) == (provider_id, model_key)
            ),
            {},
        )
        saved = self.repository.replace_model_mapping(
            provider_id,
            model_key,
            official_provider_id.strip(),
            official_model_id.strip(),
            actor_id,
            expected_revision,
        )
        self.repository.append_audit(
            "model.mapping.updated",
            actor_id,
            before,
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
                "pricing_region": model.pricing_region,
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
                (model.provider_id, model.model_key) in covered for model in models
            ),
            "catalogs": self.pricing.list_catalogs(),
        }

    def preview_initial_catalog(
        self,
        actor_id: str,
        imported_rows: list[dict[str, Any]] | None = None,
        import_id: str | None = None,
        *,
        persist: bool = True,
    ) -> dict[str, Any]:
        models = self.inventory.list_enabled()
        if imported_rows is not None:
            enabled = {(model.provider_id, model.model_key) for model in models}
            imported_rows[:] = [
                row for row in imported_rows
                if (str(row["provider_id"]), str(row["model_key"])) in enabled
            ]
        if imported_rows is not None and (not imported_rows or any(
            "unit_size" in row or "official_model_id" in row for row in imported_rows
        )):
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
                row.get("verification_status")
                in {"verified", "manual_pending", "candidate"}
                and row.get("excluded") is not True
            ):
                amount = Decimal(row["rmb_cost_decimal"])
                if row["unit_key"] in {
                    "input_tokens",
                    "output_tokens",
                } and row.get("unit_size"):
                    amount = amount * Decimal(1000) / Decimal(int(row["unit_size"]))
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
                ModelIdentity(model.provider_id, model.model_key, model.category)
            )
            required = (
                ("input_tokens", "output_tokens") if model.category == "text" else ()
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
                key[:2] == (model.provider_id, model.model_key) for key in costs
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
            "inventory_binding": self._draft_key(tuple(models)),
            "inventory_models": [asdict(model) for model in models],
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
        catalog_id = None
        if persist:
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
            "review": {
                "included_models": len(
                    {
                        (str(row["provider_id"]), str(row["model_key"]))
                        for row in imported_rows or []
                        if row.get("excluded") is not True
                    }
                ),
                "included_dimensions": sum(
                    row.get("excluded") is not True for row in imported_rows or []
                ),
                "excluded_models": len(excluded_models),
                "manual_dimensions": sum(
                    row.get("source_type") == "manual"
                    for row in imported_rows or []
                    if row.get("excluded") is not True
                ),
                "rows": [
                    {
                        key: row.get(key)
                        for key in (
                            "provider_id",
                            "model_key",
                            "capability",
                            "unit_key",
                            "unit_size",
                            "conditions",
                            "rmb_cost_decimal",
                            "multiplier_decimal",
                            "source_type",
                            "verification_status",
                            "excluded",
                            "exclusion_reason",
                        )
                    }
                    for row in imported_rows or []
                ],
            },
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
            self.repository.latest_official_candidates(),
            self.repository.list_model_publication_decisions(
                self._draft_key(tuple(models))
            ),
        )
        allowed = {
            (
                *spec_key(asdict(row)),
                row.official_provider_id or "",
                row.official_model_id or "",
                row.registry_version or "",
            ): {
                "category": row.category,
                "capability": row.capability,
                "unit_size": row.unit_size,
                "source_type": row.source_type,
                "source_url": row.source_url or "",
                "verification_status": row.verification_status,
                "rmb_cost_decimal": (
                    str(row.rmb_cost) if row.rmb_cost is not None else None
                ),
                "evidence_level": row.evidence_level,
                "candidate_digest": row.candidate_digest or "",
                "approval_reason": row.approval_reason or "",
            }
            for row in current.rows
        }
        missing_models = {
            (row.provider_id, row.model_key): row
            for row in current.rows
            if row.source_type == "missing"
        }
        manual_models: set[tuple[str, str]] = set()
        supplied: set[tuple[str, ...]] = set()
        enabled = {(model.provider_id, model.model_key) for model in models}
        for row in imported_rows:
            model_identity = (str(row["provider_id"]), str(row["model_key"]))
            if model_identity not in enabled:
                continue
            identity = (
                *spec_key(row),
                str(row.get("official_provider_id") or ""),
                str(row.get("official_model_id") or ""),
                str(row.get("registry_version") or ""),
            )
            if identity not in allowed:
                if any(
                    identity[:5] == key[:5] and identity[6:] == key[6:]
                    for key in allowed
                ):
                    raise ValueError("pricing draft read-only field changed: unit_size")
                missing = missing_models.get(model_identity)
                if missing and self._is_manual_completion(row, missing):
                    manual_models.add(model_identity)
                    continue
                raise ValueError("pricing draft identity or registry is stale")
            supplied.add(identity)
            canonical = allowed[identity]
            for field in ("category", "capability", "unit_size"):
                imported = row.get(field)
                if field == "unit_size":
                    imported = int(imported or 0)
                else:
                    imported = str(imported or "")
                if imported != canonical[field]:
                    raise ValueError(
                        "pricing draft read-only field changed: "
                        f"{field} ({model_identity[0]}/{model_identity[1]})"
                    )
            imported_cost = row.get("rmb_cost_decimal")
            canonical_cost = canonical["rmb_cost_decimal"]
            if imported_cost is None and canonical_cost is None:
                pass
            elif (
                imported_cost is not None
                and canonical_cost is not None
                and Decimal(str(imported_cost)) == Decimal(str(canonical_cost))
            ):
                for field in (
                    "source_type",
                    "source_url",
                    "verification_status",
                    "evidence_level",
                    "candidate_digest",
                    "approval_reason",
                ):
                    if str(row.get(field) or "") != canonical[field]:
                        raise ValueError(
                            "pricing draft read-only field changed: "
                            f"{field} "
                            f"({model_identity[0]}/{model_identity[1]})"
                        )
            else:
                # Editing cost is an administrative manual override, never new
                # official evidence. Normalize before preview AND confirmation.
                row["source_type"] = "manual"
                row["verification_status"] = "manual_pending"
                row["evidence_level"] = "manual"
                row["candidate_digest"] = ""
                row["approval_reason"] = "管理员通过报价单调整成本，待确认发布"
        expected = {
            identity for identity in allowed if identity[:2] not in manual_models
        }
        if supplied != expected:
            raise ValueError("pricing draft dimensions are incomplete")
        inclusion_by_model: dict[tuple[str, str], set[bool]] = {}
        for row in imported_rows:
            inclusion_by_model.setdefault(
                (str(row["provider_id"]), str(row["model_key"])), set()
            ).add(row.get("excluded") is not True)
        if any(len(states) != 1 for states in inclusion_by_model.values()):
            raise ValueError("all dimensions of a model must be included together")

    @staticmethod
    def _is_manual_completion(row: dict[str, Any], missing: Any) -> bool:
        if (
            str(row.get("category") or "") != missing.category
            or str(row.get("official_provider_id") or "")
            != (missing.official_provider_id or "")
            or str(row.get("official_model_id") or "")
            != (missing.official_model_id or "")
            or str(row.get("source_type") or "") != "manual"
            or str(row.get("verification_status") or "") != "manual_pending"
            or not str(row.get("source_url") or "").startswith("https://")
            or not str(row.get("capability") or "").strip()
            or not str(row.get("unit_key") or "").strip()
            or int(row.get("unit_size") or 0) <= 0
        ):
            return False
        return True

    @staticmethod
    def _build_imported_rules(
        imported_rows: list[dict[str, Any]],
    ) -> tuple[PriceRule, ...]:
        included = [
            row
            for row in imported_rows
            if row.get("excluded") is not True
            and row.get("verification_status")
            in {"verified", "manual_pending", "candidate"}
        ]
        groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
        for row in included:
            conditions = dict(row.get("conditions") or {})
            if "region" in conditions:
                conditions["pricing_region"] = conditions.pop("region")
            group_key = (
                str(row["provider_id"]),
                str(row["model_key"]),
                str(row.get("capability") or row.get("category")),
                json.dumps(conditions, sort_keys=True, separators=(",", ":")),
            )
            groups.setdefault(group_key, []).append(row)

        rules: list[PriceRule] = []
        for (
            provider_id,
            model_key,
            capability,
            conditions_json,
        ), rows in sorted(groups.items()):
            digest = hashlib.sha256(conditions_json.encode()).hexdigest()[:12]
            dimensions = [
                {
                    "unit_key": str(row["unit_key"]),
                    "unit_size": int(
                        row.get("unit_size")
                        or (
                            1000
                            if str(row["unit_key"]) in {"input_tokens", "output_tokens"}
                            else 1
                        )
                    ),
                    "credits_per_unit": PricingAdminService._row_credits(row),
                    "rmb_cost": str(row["rmb_cost_decimal"]),
                    "multiplier": str(row["multiplier_decimal"]),
                }
                for row in sorted(rows, key=lambda item: str(item["unit_key"]))
            ]
            rules.append(
                PriceRule(
                    id=f"imported:{provider_id}:{model_key}:metered:{digest}",
                    provider_id=provider_id,
                    model_key=model_key,
                    capability=capability,
                    unit_type="metered_dimensions",
                    parameter_match=json.loads(conditions_json),
                    metadata={
                        "currency": "CNY",
                        "dimensions": dimensions,
                    },
                )
            )
        if not rules:
            raise ValueError("catalog must contain at least one eligible price")
        return tuple(rules)

    @staticmethod
    def _row_credits(row: dict[str, Any]) -> int:
        cost = Decimal(str(row["rmb_cost_decimal"]))
        multiplier = Decimal(str(row["multiplier_decimal"]))
        if multiplier < PricingDefaults().minimum_multiplier:
            raise ValueError("multiplier is below the 1.3 safety floor")
        return int((cost * multiplier * 100).to_integral_value(rounding=ROUND_CEILING))

    def publish_preview(
        self,
        catalog_id: str,
        actor_id: str,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        catalog = self.catalogs.get_catalog(catalog_id)
        expected_inventory = catalog["metadata"].get("inventory_binding")
        models = tuple(self.inventory.list_enabled())
        enabled = {(model.provider_id, model.model_key) for model in models}
        current_inventory = self._draft_key(models)
        snapshot = catalog["metadata"].get("inventory_models")
        if snapshot is not None:
            expected_inventory = self._draft_key(tuple(
                PriceableModel(**row) for row in snapshot
                if (row["provider_id"], row["model_key"]) in enabled
            ))
        if expected_inventory != current_inventory:
            raise ValueError(
                "enabled model inventory changed; generate and approve again"
            )
        import_id = catalog["metadata"].get("pricing_import_id")
        if import_id is not None and not self.repository.import_allows_publish(
            str(import_id), catalog_id
        ):
            raise ValueError("pricing import is not confirmed")
        if catalog["status"] == "draft":
            retained = [row for row in catalog["rules"]
                        if (row["provider_id"], row["model_key"]) in enabled]
            if len(retained) != len(catalog["rules"]):
                if not retained:
                    raise ValueError("no enabled models remain in pricing draft")
                self.catalogs.replace_draft_rules(catalog_id, tuple(
                    PriceRule(**{key: row[key] for key in PriceRule.__dataclass_fields__})
                    for row in retained
                ))
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
