# Enabled Model Pricing Draft Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a non-empty, auditable pricing workbook from every currently enabled provider/model, prefill verified official multidimensional costs, apply a default 1.5 retail multiplier, and let an administrator exclude unresolved models before publishing the first immutable catalog.

**Architecture:** Extend the existing pricing administration path instead of creating a second catalog system. A versioned official-cost registry feeds append-only cost snapshots; `PricingDraftBuilder` joins those snapshots to the network-free enabled-model inventory, produces safe draft rows, and supplies both the three-sheet workbook and the existing import/preview/publish flow. Runtime continues to trust only immutable published catalogs and distinguishes “no catalog exists” from “this model was deliberately not priced.”

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy Core, SQLite, PostgreSQL 16, `Decimal`, openpyxl, React/TypeScript, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-enabled-model-pricing-draft-design.md`

## Global Constraints

- Only currently configured and enabled providers/models appear in an exported draft.
- Match known models by exact `(provider_id, official_model_id)`; never fuzzy-match names.
- A workbook row represents one model pricing dimension, not one whole model.
- Default retail multiplier is exactly `1.5`; credits conversion is exactly `100 credits/CNY`.
- Missing/unverified costs remain visible but are not publishable unless explicitly excluded with a reason.
- Refreshing official prices creates candidates only; it never mutates a published catalog.
- Excel import never supplies authoritative derived prices; the server recomputes them with `Decimal`.
- Existing published catalogs remain authoritative and available when refresh/import fails.
- Free identities still require a published quote snapshot; exemption affects debit only.
- All schema changes must support fresh and existing SQLite/PostgreSQL databases idempotently.

---

## File Structure

### Server files

- Create `src/qwenpaw/app/billing/official_pricing.py`: typed official price records, exact model mapping, versioned bundled registry loader, validation.
- Create `src/qwenpaw/app/billing/pricing_draft.py`: enabled-inventory/cost join, multidimensional draft rows, exclusion validation, safe price calculation.
- Create `src/qwenpaw/app/billing/default_prices/dashscope.json`: reviewed 百炼 official price snapshot with evidence metadata.
- Create `src/qwenpaw/app/billing/default_prices/volcengine.json`: reviewed 火山引擎 official price snapshot with evidence metadata.
- Modify `src/qwenpaw/app/billing/pricing_models.py`: richer immutable cost/draft types and `default_multiplier=1.5`.
- Modify `src/qwenpaw/app/billing/pricing_inventory.py`: expose official model identity/capabilities without network access.
- Modify `src/qwenpaw/app/billing/pricing_excel.py`: three-sheet export and strict round-trip import.
- Modify `src/qwenpaw/app/billing/pricing_admin.py`: generate draft, import exclusions, publish a complete eligible subset.
- Modify `src/qwenpaw/app/billing/pricing_sync.py`: candidate-only official snapshot refresh interface.
- Modify `src/qwenpaw/app/billing/pricing.py`: stable model-not-priced error when a catalog exists but has no matching rule.
- Modify `src/qwenpaw/app/routers/billing.py`: draft/export/refresh endpoints and stable HTTP mappings.
- Modify `src/qwenpaw/app/storage/schema.py`: official snapshot/mapping/exclusion evidence columns and indexes plus upgrade path.
- Modify `src/qwenpaw/app/storage/repos/pricing_admin_repo.py`: append/read official candidates, exact mappings, exclusions and draft projections.

### Client files

- Modify `../dclaw-client/console/src/api/types/billing.ts`: draft coverage, source status, risk and exclusion DTOs.
- Modify `../dclaw-client/console/src/api/modules/billing.ts`: generate/export/refresh/exclude APIs.
- Modify `../dclaw-client/console/src/pages/Settings/Billing/PricingTab.tsx`: first-catalog wizard and coverage summary.
- Modify `../dclaw-client/console/src/pages/Settings/Billing/PricingModels.tsx`: dimension/source/status table.
- Modify `../dclaw-client/console/src/pages/Settings/Billing/PricingDrafts.tsx`: workbook flow, exclusion reason and publish preflight.

---

### Task 1: Persist Versioned Official Cost Evidence and Exact Mappings

**Files:**
- Modify: `src/qwenpaw/app/storage/schema.py`
- Modify: `src/qwenpaw/app/storage/repos/pricing_admin_repo.py`
- Test: `tests/unit/app/storage/test_billing_schema.py`
- Test: `tests/unit/app/storage/repos/test_pricing_admin_repo.py`
- Test: `tests/integration/test_billing_schema_postgres.py`

**Interfaces:**
- Produces: `PricingAdminRepository.append_official_candidate(values: Mapping[str, Any]) -> str`
- Produces: `PricingAdminRepository.latest_official_candidates() -> list[dict[str, Any]]`
- Produces: `PricingAdminRepository.replace_model_mapping(provider_id: str, model_key: str, official_model_id: str, actor_id: str, expected_revision: int) -> dict[str, Any]`
- Produces: `PricingAdminRepository.list_model_mappings() -> list[dict[str, Any]]`
- Produces: `PricingAdminRepository.replace_draft_exclusion(draft_key: str, provider_id: str, model_key: str, excluded: bool, reason: str | None, actor_id: str) -> dict[str, Any]`

- [ ] **Step 1: Write fresh/upgrade schema failures**

Add assertions for append-only `billing_official_price_candidates`, unique exact `billing_pricing_model_mappings`, and `billing_pricing_draft_exclusions`. Assert candidate identity includes provider, official model, dimension, conditions digest, source URL, original currency/price, FX evidence, verification state and registry version.

```python
assert {
    "billing_official_price_candidates",
    "billing_pricing_model_mappings",
    "billing_pricing_draft_exclusions",
} <= set(inspect(engine).get_table_names())
```

- [ ] **Step 2: Run schema tests and capture RED**

Run: `.venv/bin/python -m pytest tests/unit/app/storage/test_billing_schema.py tests/integration/test_billing_schema_postgres.py -q`

Expected: FAIL because the three tables and upgrade DDL do not exist.

- [ ] **Step 3: Add repository contract failures**

Test append-only candidate ordering, exact mapping revision conflict, exclusion reason requirement, and idempotent repeated candidate digest.

```python
first = repo.append_official_candidate(candidate)
second = repo.append_official_candidate(candidate)
assert first == second
with pytest.raises(PricingRevisionConflict):
    repo.replace_model_mapping("custom", "alias", "qwen-plus", "1", 0)
```

- [ ] **Step 4: Implement schema and repository primitives**

Use immutable UUID rows for candidates, optimistic `revision` for mappings, and a unique `(draft_key, provider_id, model_key)` exclusion key. Add idempotent `create_all()` upgrades and PostgreSQL/SQLite immutable triggers for official candidates.

- [ ] **Step 5: Run focused SQLite and live PostgreSQL tests**

Run: `.venv/bin/python -m pytest tests/unit/app/storage/test_billing_schema.py tests/unit/app/storage/repos/test_pricing_admin_repo.py -q`

Run: `QWENPAW_TEST_POSTGRES_URL='postgresql+psycopg:///postgres' .venv/bin/python -m pytest tests/integration/test_billing_schema_postgres.py -q`

Expected: PASS with fresh and legacy upgrades both idempotent.

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/storage/schema.py src/qwenpaw/app/storage/repos/pricing_admin_repo.py tests/unit/app/storage tests/integration/test_billing_schema_postgres.py
git commit -m "feat: persist official pricing evidence"
```

### Task 2: Load and Validate the Official Default Price Registry

**Files:**
- Create: `src/qwenpaw/app/billing/official_pricing.py`
- Create: `src/qwenpaw/app/billing/default_prices/dashscope.json`
- Create: `src/qwenpaw/app/billing/default_prices/volcengine.json`
- Modify: `src/qwenpaw/app/billing/pricing_models.py`
- Test: `tests/unit/app/billing/test_official_pricing.py`

**Interfaces:**
- Produces: `OfficialPriceDimension`
- Produces: `OfficialPriceRegistry.load_bundled() -> OfficialPriceRegistry`
- Produces: `OfficialPriceRegistry.dimensions(provider_id: str, official_model_id: str) -> tuple[OfficialPriceDimension, ...]`
- Consumes: Task 1 candidate fields.

- [ ] **Step 1: Record primary-source evidence before entering numeric defaults**

For every bundled 百炼 and 火山 row, verify the current official provider documentation and record `source_url`, `source_published_at` when available, `collected_at`, original currency/unit, tier/spec conditions and a registry version. Do not use blogs, search snippets or model-origin prices for aggregator billing.

- [ ] **Step 2: Write registry validation failures**

Cover duplicate dimensions, binary floats, unsupported currencies/units, missing evidence, invalid timestamps, negative prices, overlapping conditions and a content digest mismatch.

```python
with pytest.raises(OfficialPriceRegistryError, match="duplicate dimension"):
    OfficialPriceRegistry.from_records([row, row])
```

- [ ] **Step 3: Run the test and capture RED**

Run: `.venv/bin/python -m pytest tests/unit/app/billing/test_official_pricing.py -q`

Expected: FAIL because the registry module does not exist.

- [ ] **Step 4: Implement immutable registry types and bundled loader**

Represent all amounts as decimal strings parsed to `Decimal`. Require exact provider/model IDs and explicit `unit_key`; calculate a canonical JSON SHA-256 digest. Keep original evidence in the registry and expose RMB conversion only when verified FX evidence exists.

- [ ] **Step 5: Add reviewed 百炼 and 火山 snapshots**

Include only models and dimensions supported by verified official sources. Missing models are intentionally absent so Task 3 marks them unresolved rather than guessing.

- [ ] **Step 6: Run focused validation**

Run: `.venv/bin/python -m pytest tests/unit/app/billing/test_official_pricing.py -q`

Expected: PASS and registry files produce stable digests.

- [ ] **Step 7: Commit**

```bash
git add src/qwenpaw/app/billing/official_pricing.py src/qwenpaw/app/billing/default_prices src/qwenpaw/app/billing/pricing_models.py tests/unit/app/billing/test_official_pricing.py
git commit -m "feat: add verified default price registry"
```

### Task 3: Join Enabled Models to Multidimensional Draft Rows

**Files:**
- Create: `src/qwenpaw/app/billing/pricing_draft.py`
- Modify: `src/qwenpaw/app/billing/pricing_inventory.py`
- Modify: `src/qwenpaw/app/billing/pricing_models.py`
- Test: `tests/unit/app/billing/test_pricing_inventory.py`
- Test: `tests/unit/app/billing/test_pricing_draft.py`

**Interfaces:**
- Produces: `PricingDraftRow`
- Produces: `PricingDraftResult(rows: tuple[PricingDraftRow, ...], risks: tuple[PricingDraftRisk, ...], coverage: PricingCoverage)`
- Produces: `PricingDraftBuilder.build(models: Sequence[PriceableModel], costs: Sequence[Mapping[str, Any]], mappings: Sequence[Mapping[str, Any]], exclusions: Sequence[Mapping[str, Any]]) -> PricingDraftResult`
- Consumes: `OfficialPriceRegistry.dimensions(...)` from Task 2.

- [ ] **Step 1: Write inventory identity failures**

Extend `PriceableModel` with `official_model_id: str | None` and `capabilities: tuple[str, ...]`. Test configured builtin, extra, hidden, unconfigured and custom models; inventory must remain network-free.

- [ ] **Step 2: Write draft-builder failures**

Cover exact 百炼/火山 matching, multiple token/cache/image dimensions, custom mapped models, unmapped models, verified repository cost overriding bundled reference, default `1.5`, 100 credits/CNY, and safety-floor override.

```python
draft = builder.build(models, costs=[], mappings=[], exclusions=[])
qwen = [row for row in draft.rows if row.model_key == "qwen-plus"]
assert {row.unit_key for row in qwen} >= {"input_tokens", "output_tokens"}
assert all(row.multiplier == Decimal("1.5") for row in qwen)
```

- [ ] **Step 3: Run tests and capture RED**

Run: `.venv/bin/python -m pytest tests/unit/app/billing/test_pricing_inventory.py tests/unit/app/billing/test_pricing_draft.py -q`

- [ ] **Step 4: Implement the pure builder**

Keep calculation and matching independent from FastAPI and persistence. Prefer latest verified repository costs, then verified bundled references. Emit unresolved rows and risks instead of omitting them. Require a non-empty reason for exclusion; exclusions change `include_in_publish`, not evidence.

- [ ] **Step 5: Run focused tests**

Expected: PASS including deterministic row ordering by provider/category/model/dimension.

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/billing/pricing_inventory.py src/qwenpaw/app/billing/pricing_models.py src/qwenpaw/app/billing/pricing_draft.py tests/unit/app/billing/test_pricing_inventory.py tests/unit/app/billing/test_pricing_draft.py
git commit -m "feat: build pricing drafts from enabled models"
```

### Task 4: Produce and Round-Trip the Three-Sheet Workbook

**Files:**
- Modify: `src/qwenpaw/app/billing/pricing_excel.py`
- Test: `tests/unit/app/billing/test_pricing_excel.py`

**Interfaces:**
- Produces: `PricingExcelService.export_draft(result: PricingDraftResult) -> bytes`
- Produces: `PricingExcelService.preview_import(content: bytes, filename: str, actor_id: str) -> dict[str, Any]`
- Consumes: Task 3 draft DTOs.

- [ ] **Step 1: Replace the one-sheet test with exact workbook contracts**

Assert sheet names `价格草案`, `缺失与风险`, `填写说明`; verify enabled models appear with no database costs, multi-dimension rows remain distinct, unresolved rows are visible, and instructions state 1.5/100 rules.

- [ ] **Step 2: Add hostile round-trip tests**

Reject modified provider/model/unit identity, unknown columns, formulas, macros, duplicate dimensions, invalid inclusion values, exclusion without reason, stale registry version and a client-supplied sale price inconsistent with server recomputation.

- [ ] **Step 3: Run and capture RED**

Run: `.venv/bin/python -m pytest tests/unit/app/billing/test_pricing_excel.py -q`

- [ ] **Step 4: Implement export and strict import parsing**

Use fixed localized headers and an internal hidden draft identity/digest column. Parse editable cells only; recompute RMB sale price and credits with `Decimal`. Return `valid_rows`, `exclusions`, and structured risks for the existing import repository.

- [ ] **Step 5: Run tests and inspect a rendered workbook**

Load the produced bytes with openpyxl and assert frozen headers, filters, number formats, source hyperlinks and conditional formatting for blockers. Do not add a new spreadsheet dependency.

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/billing/pricing_excel.py tests/unit/app/billing/test_pricing_excel.py
git commit -m "feat: export enabled model pricing workbook"
```

### Task 5: Publish the Eligible Subset and Return Model-Level Unpriced Errors

**Files:**
- Modify: `src/qwenpaw/app/billing/pricing_admin.py`
- Modify: `src/qwenpaw/app/billing/pricing.py`
- Modify: `src/qwenpaw/app/storage/repos/pricing_admin_repo.py`
- Test: `tests/unit/app/billing/test_pricing_admin.py`
- Test: `tests/unit/app/billing/test_pricing.py`
- Test: `tests/integration/test_admin_pricing_flow.py`

**Interfaces:**
- Produces: `PricingAdminService.generate_draft(actor_id: str) -> dict[str, Any]`
- Produces: `PricingAdminService.set_exclusion(draft_key: str, provider_id: str, model_key: str, excluded: bool, reason: str | None, actor_id: str, ip_address: str | None = None) -> dict[str, Any]`
- Produces: `ModelNotPricedError(provider_id: str, model_key: str)`
- Consumes: Task 3 builder and Task 4 import result.

- [ ] **Step 1: Write partial-publish failures**

Test 95 eligible + 5 unresolved: publishing is blocked until every unresolved model is priced or explicitly excluded; after exclusions, rules contain exactly the eligible dimensions and audit metadata contains exclusion reasons.

- [ ] **Step 2: Write runtime distinction failures**

Assert no published catalog raises the existing catalog-not-ready error, while a published catalog with no matching model raises `ModelNotPricedError` and other priced models continue quoting.

- [ ] **Step 3: Run and capture RED**

Run: `.venv/bin/python -m pytest tests/unit/app/billing/test_pricing_admin.py tests/unit/app/billing/test_pricing.py tests/integration/test_admin_pricing_flow.py -q`

- [ ] **Step 4: Refactor preview generation through `PricingDraftBuilder`**

Replace category-based hard-coded required units with registry dimensions. Persist draft identity and exclusion evidence. Build catalog rules only from included verified rows; refuse an empty publishable subset.

- [ ] **Step 5: Implement stable unpriced-model behavior**

Raise `ModelNotPricedError` only after a valid catalog is selected but no rule matches the requested provider/model. Preserve catalog version locking, existing reconciling behavior and complimentary quote snapshots.

- [ ] **Step 6: Run focused and integration tests**

Expected: first catalog can publish a complete subset, priced OpenAPI quote succeeds, excluded model fails before supplier contact, and free `szzz_admin` usage has quote evidence with zero wallet/ledger mutation.

- [ ] **Step 7: Commit**

```bash
git add src/qwenpaw/app/billing/pricing_admin.py src/qwenpaw/app/billing/pricing.py src/qwenpaw/app/storage/repos/pricing_admin_repo.py tests/unit/app/billing tests/integration/test_admin_pricing_flow.py
git commit -m "feat: publish complete pricing subsets"
```

### Task 6: Expose Draft, Export, Refresh and Exclusion APIs

**Files:**
- Modify: `src/qwenpaw/app/routers/billing.py`
- Modify: `src/qwenpaw/app/billing/pricing_sync.py`
- Test: `tests/unit/app/routers/test_billing.py`
- Test: `tests/unit/app/billing/test_pricing_sync.py`
- Test: `tests/integration/test_admin_pricing_flow.py`

**Interfaces:**
- Produces: `POST /api/admin/billing/pricing/drafts`
- Produces: `GET /api/admin/billing/pricing/drafts/{draft_key}/export`
- Produces: `PUT /api/admin/billing/pricing/drafts/{draft_key}/exclusions/{provider_id}/{model_key}`
- Produces: `POST /api/admin/billing/pricing/official-candidates/refresh`
- Produces: stable `409 model_not_priced` mapping at billing entrypoints.

- [ ] **Step 1: Write route authorization and response failures**

Read-only overview/export requires administrator authentication; generate, refresh, exclusion, import confirmation and publish require pricing unlock. Assert actor identity comes from authentication, never request payload.

- [ ] **Step 2: Write candidate-only refresh failures**

Use a fake adapter and assert refresh appends candidates but neither trusted costs nor published catalogs change. Repeating a content digest is idempotent.

- [ ] **Step 3: Run and capture RED**

Run: `.venv/bin/python -m pytest tests/unit/app/routers/test_billing.py tests/unit/app/billing/test_pricing_sync.py -q`

- [ ] **Step 4: Implement endpoints and stable errors**

Return coverage counts, registry version, timestamps, risks and publishability. Stream XLSX with safe filename. Map missing draft to 404, stale/conflicting draft to 409, invalid exclusion to 422, and never expose internal source credentials.

- [ ] **Step 5: Run FastAPI and PostgreSQL flow tests**

Run: `.venv/bin/python -m pytest tests/unit/app/routers/test_billing.py tests/integration/test_admin_pricing_flow.py -q`

Expected: PASS and public OpenAPI supplier fake is not contacted for an excluded model.

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/routers/billing.py src/qwenpaw/app/billing/pricing_sync.py tests/unit/app/routers/test_billing.py tests/unit/app/billing/test_pricing_sync.py tests/integration/test_admin_pricing_flow.py
git commit -m "feat: expose pricing draft administration"
```

### Task 7: Add the First-Catalog Wizard to the Split Client

**Files:**
- Modify: `../dclaw-client/console/src/api/types/billing.ts`
- Modify: `../dclaw-client/console/src/api/modules/billing.ts`
- Modify: `../dclaw-client/console/src/pages/Settings/Billing/PricingTab.tsx`
- Modify: `../dclaw-client/console/src/pages/Settings/Billing/PricingModels.tsx`
- Modify: `../dclaw-client/console/src/pages/Settings/Billing/PricingDrafts.tsx`
- Test: `../dclaw-client/console/src/api/modules/billing.test.ts`
- Test: `../dclaw-client/console/src/pages/Settings/Billing/PricingTab.test.tsx`

**Interfaces:**
- Consumes: Task 6 HTTP contracts.
- Produces: administrator workflow for generate, export, import preview, exclusion reason, unlock, confirm and publish.

- [ ] **Step 1: Write API contract failures**

Assert exact routes, unlock header only on mutations, binary workbook response, and typed coverage/risk DTOs.

- [ ] **Step 2: Write wizard behavior failures**

Test empty-catalog callout, enabled/matched/missing/excluded counts, default 1.5 and 100 credits/CNY copy, blocked publish, exclusion reason validation, download action and post-publish success state.

- [ ] **Step 3: Run and capture RED**

Run from `../dclaw-client/console`: `npm test -- --run src/api/modules/billing.test.ts src/pages/Settings/Billing/PricingTab.test.tsx`

- [ ] **Step 4: Implement typed API and wizard**

Reuse `PricingUnlockModal`; do not store the unlock token beyond existing scoped state. Display source URL/status to administrators, never source credentials. Keep unresolved models visible and require explicit reason before exclusion.

- [ ] **Step 5: Run focused client tests and production build**

Run: `npm test -- --run src/api/modules/billing.test.ts src/pages/Settings/Billing/PricingTab.test.tsx`

Run: `npm run build`

Expected: PASS; build emits the pricing wizard in the compiled console.

- [ ] **Step 6: Commit in the client repository**

```bash
git -C ../dclaw-client add console/src/api console/src/pages/Settings/Billing
git -C ../dclaw-client commit -m "feat: guide initial pricing publication"
```

### Task 8: Verify End-to-End Publication and Continuous Operation

**Files:**
- Modify: `tests/integration/test_admin_pricing_flow.py`
- Modify: `tests/integration/test_open_api_billing_flow.py`
- Modify: `tests/integration/test_open_api_billing_postgres.py`
- Modify: `docs/open-api-user-manual.zh.md`
- Modify: `docs/superpowers/specs/2026-08-30-enabled-model-pricing-draft-design.md`

**Interfaces:**
- Consumes: all earlier tasks.
- Produces: complete acceptance evidence and operator instructions.

- [ ] **Step 1: Add a production-shaped enabled-provider fixture**

Configure 百炼, 火山, an extra model and an unmapped custom model. Start with no trusted costs/catalog, export the workbook, import it, explicitly exclude the custom model, publish, and quote a priced model.

- [ ] **Step 2: Add OpenAPI acceptance assertions**

Before publication assert `503 catalog_not_ready` and zero supplier calls. After publication assert the priced model reaches the supplier and settles; excluded model returns stable model-not-priced without supplier contact; complimentary admin records quote/usage without debit.

- [ ] **Step 3: Add continuity assertions**

After a catalog is published, inject official refresh, FX and import failures. Assert the last published catalog remains quotable and historical request snapshots remain unchanged.

- [ ] **Step 4: Run the complete server pricing/billing suite with live PostgreSQL**

Run:

```bash
QWENPAW_TEST_POSTGRES_URL='postgresql+psycopg:///postgres' \
.venv/bin/python -m pytest \
  tests/unit/app/billing \
  tests/unit/app/routers/test_billing.py \
  tests/unit/app/storage/repos/test_pricing_admin_repo.py \
  tests/integration/test_admin_pricing_flow.py \
  tests/integration/test_open_api_billing_flow.py \
  tests/integration/test_open_api_billing_postgres.py \
  tests/integration/test_billing_schema_postgres.py -q
```

Expected: all selected tests pass with no PostgreSQL skips.

- [ ] **Step 5: Run static and artifact verification**

Run:

```bash
.venv/bin/python -m compileall -q src tests
git diff --check
.venv/bin/python -m black --check src/qwenpaw/app/billing src/qwenpaw/app/routers/billing.py tests/unit/app/billing
.venv/bin/python -m flake8 src/qwenpaw/app/billing tests/unit/app/billing
.venv/bin/python -m mypy src/qwenpaw/app/billing
```

Run the client focused tests and `npm run build` again from `../dclaw-client/console`.

- [ ] **Step 6: Update operator documentation and spec status**

Document the exact first-catalog UI flow, explain model-level unpriced errors, and state that no real supplier call is used for publication validation. Change the design status to implemented only after all acceptance commands pass.

- [ ] **Step 7: Commit final server acceptance changes**

```bash
git add tests/integration docs/open-api-user-manual.zh.md docs/superpowers/specs/2026-08-30-enabled-model-pricing-draft-design.md
git commit -m "test: verify enabled model pricing rollout"
```

- [ ] **Step 8: Request final code review before merging or pushing**

Review both repository commit ranges against the approved spec. Resolve every Critical/Important finding, rerun the affected focused tests, then rerun the final server/client acceptance commands before pushing either `main` branch or triggering the combined image workflow.
