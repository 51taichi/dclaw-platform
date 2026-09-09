# Production token-unit correction, 2026-09-09

Authorized scope: audit all billing items and price versions for the confirmed million-to-thousand token unit corruption, refund verified overcharges once, retain financial history.

## Evidence and production changes

- Historical catalog admin-20260903190933 has million-token dimensions. The imported admin-20260905051500 changed 41 token dimensions on 21 models to 1000 while preserving price amounts.
- The stored import 3a63c497-171d-4981-8cc0-b002d8b3b128 already contains the incorrect units. Its filename is 流马AI-gpt-5.6-sol-线上兼容可导入.xlsx. Earlier failed imports retained million units. This is evidence of erroneous compatibility data, not proof that the current Excel parser changes units.
- Published repair-deepseek-token-unit-20260909092737 for the first model, then repair-all-token-units-20260909094000 for the remaining 20 models / 39 dimensions. All other price values preserved.
- Scanned 10,079 billing items across models/accounts. Recalculated 9,935 positive-charge items against their stored price rules with no arithmetic discrepancies. Historical per-unit prices, rather than summation, caused the identified overcharges.
- Refunded 234 items / 1,217,355 credits initially; full audit found 2 additional GLM-5.2 items / 21,236 credits. Total 236 items / 1,238,591 credits.
- Compensation uses admin_grant, business_type pricing_correction, zero cash change, original item/order references and stable token-unit-repair-20260909:<item-id> keys. Original charges and quotes retained.
- Server backup/audit files: /app/working/billing-repair-20260909/ (catalog-before.json, full-catalog-before.json, full-unit-changes.json, refund-plan.json, all-audit.json).

## Remaining evidence gaps

Five affected items remain reconciling: four client model calls with financial_write_failure/provider_call_started evidence but no actual token usage; one AIGC item with provider_outcome_unknown. A sixth uncharged affected item was already released. Do not invent usage, mark unknown outcomes as failed, or automatically charge their erroneous quotes. A separate user choice for incident waiver versus supplier reconciliation is pending.

## Validation

35 pricing draft/Excel/admin/integration tests passed locally. Current server source already uses million-token semantics for legacy token costs without an explicit unit. Current trusted cost records contain million-token or absent units, no explicit thousand-token units. Do not reimport the erroneous compatibility workbook.

No deployment of unrelated local model-balance-admission changes occurred during this repair.
