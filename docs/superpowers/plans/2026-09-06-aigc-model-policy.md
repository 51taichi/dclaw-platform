# AIGC Model Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an administrator-managed, ordered allowlist and explicit default for text, image, video, and audio models used by AIGC Studio, while preserving legacy behavior until each category is first configured.

**Architecture:** A new server-side policy repository stores one versioned platform policy per AIGC category and ordered provider/model entries. A shared policy service joins those saved references against live provider, publication, pricing, capability, and adapter state; admin APIs expose the complete annotated inventory, while the existing user capability API and job submission path consume only the effective allowlist. The console adds a stable four-section policy manager and updates existing model selectors to show disabled inventory with explicit reasons.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy Core, Pydantic, pytest; React 18, TypeScript, Ant Design/AgentScope Design, Less modules, Vitest, Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-06-aigc-model-policy-design.md`

## Global Constraints

- Categories are exactly `text`, `image`, `video`, and `audio`.
- Model identity is always the pair `(provider_id, model_id)`.
- Text candidates include every ordinary published/priced LLM; they do not need an explicit `storyboard` capability declaration.
- A configured category must keep at least one currently selectable model and one explicit default model.
- Unpriced, unpublished, provider-unconfigured, provider-disabled, and adapter-unsupported models remain visible in admin inventory but are disabled.
- An unconfigured category preserves legacy behavior and exposes every currently effective model in that category.
- A configured default that becomes invalid is retained; the first valid selected model becomes the effective default, and the configured default resumes automatically when valid again.
- User-selected models that become invalid are rejected at submission rather than silently replaced.
- Existing provider adapters, task payloads, billing calculations, canvases, generated assets, and historical records remain unchanged.
- Use tests before production changes and make a focused commit after every task.

---

### Task 1: Persist versioned AIGC model policies

**Files:**
- Modify: `src/qwenpaw/app/storage/schema.py`
- Create: `src/qwenpaw/app/storage/repos/aigc_model_policy_repo.py`
- Test: `tests/unit/app/storage/repos/test_aigc_model_policy_repo.py`

**Interfaces:**
- Produces: `AigcModelPolicyRepository.get(category: str) -> dict[str, Any] | None`
- Produces: `AigcModelPolicyRepository.replace(category: str, expected_version: int | None, models: list[dict[str, Any]], default_model: dict[str, str], updated_by: int | None) -> dict[str, Any]`
- Raises: `AigcModelPolicyVersionConflict` when `expected_version` does not match the stored version.

- [ ] **Step 1: Write repository tests that define storage behavior**

```python
def test_replace_creates_ordered_policy(engine):
    repo = AigcModelPolicyRepository(engine)
    saved = repo.replace(
        "image",
        expected_version=None,
        models=[
            {"provider_id": "mxapi", "model_id": "gpt-image-2"},
            {"provider_id": "volcengine", "model_id": "seedream-5"},
        ],
        default_model={"provider_id": "mxapi", "model_id": "gpt-image-2"},
        updated_by=7,
    )
    assert saved["version"] == 1
    assert saved["models"][0]["is_default"] is True
    assert repo.get("image")["models"][1]["sort_order"] == 1


def test_replace_rejects_stale_version(engine):
    repo = AigcModelPolicyRepository(engine)
    repo.replace("image", None, [{"provider_id": "p", "model_id": "m"}], {"provider_id": "p", "model_id": "m"}, 1)
    with pytest.raises(AigcModelPolicyVersionConflict):
        repo.replace("image", 0, [{"provider_id": "p", "model_id": "m"}], {"provider_id": "p", "model_id": "m"}, 2)
```

- [ ] **Step 2: Run repository tests and verify the missing repository failure**

Run: `pytest tests/unit/app/storage/repos/test_aigc_model_policy_repo.py -q`

Expected: FAIL because `aigc_model_policy_repo` and its tables do not exist.

- [ ] **Step 3: Add normalized policy tables and repository implementation**

Add `aigc_model_policies` with unique `category`, `configured`, `version`, `updated_at`, and `updated_by`. Add `aigc_model_policy_items` with policy foreign key, provider ID, model ID, sort order, and default flag. Add unique constraints on `(policy_id, provider_id, model_id)` and `(policy_id, sort_order)`. Implement `replace` as one transaction: lock/read current policy, compare version, upsert the policy row, replace item rows, and return a stable ordered dictionary.

- [ ] **Step 4: Run repository tests and storage schema tests**

Run: `pytest tests/unit/app/storage/repos/test_aigc_model_policy_repo.py tests/unit/app/storage/test_schema.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the storage unit**

```bash
git add src/qwenpaw/app/storage/schema.py src/qwenpaw/app/storage/repos/aigc_model_policy_repo.py tests/unit/app/storage/repos/test_aigc_model_policy_repo.py
git commit -m "feat: persist AIGC model policies"
```

### Task 2: Build the authoritative AIGC policy inventory service

**Files:**
- Create: `src/qwenpaw/app/aigc/model_policy.py`
- Create: `src/qwenpaw/app/aigc/__init__.py`
- Test: `tests/unit/app/aigc/test_model_policy.py`
- Modify: `src/qwenpaw/app/routers/aigc_studio.py`

**Interfaces:**
- Produces: `AigcModelCategory = Literal["text", "image", "video", "audio"]`
- Produces: `ModelRef(provider_id: str, model_id: str)`
- Produces: `InventoryItem` with names, category, `selectable`, `reasons`, `selected`, and `is_default`.
- Produces: `AigcModelPolicyService.inventory(manager: Any) -> AigcPolicyInventory`
- Produces: `AigcModelPolicyService.effective(category: AigcModelCategory, manager: Any) -> EffectiveCategoryPolicy`
- Consumes: provider inventory, `ModelPublicationService` publication state, and the effective pricing catalog as three distinct sources; do not infer publication from pricing or pricing from publication.

- [ ] **Step 1: Write classification and status tests**

```python
@pytest.mark.asyncio
async def test_inventory_shows_unpriced_and_unpublished_models_disabled(service, manager):
    inventory = await service.inventory(manager)
    unpriced = inventory.find("image", "mxapi", "gpt-image-2")
    unpublished = inventory.find("text", "dashscope", "qwen-max")
    assert unpriced.selectable is False
    assert unpriced.reasons == ["unpriced"]
    assert unpublished.selectable is False
    assert unpublished.reasons == ["unpublished"]


@pytest.mark.asyncio
async def test_text_inventory_includes_ordinary_llms_without_storyboard_flag(service, manager):
    item = (await service.inventory(manager)).find("text", "volcengine", "deepseek-v4")
    assert item.category == "text"
```

Also cover provider unconfigured, provider disabled, adapter unsupported, multi-capability image/video categorization, and audio categorization.

- [ ] **Step 2: Run service tests and verify they fail for missing service**

Run: `pytest tests/unit/app/aigc/test_model_policy.py -q`

Expected: FAIL with missing module/classes.

- [ ] **Step 3: Implement category mapping and status annotation**

Extract or reuse AIGC capability inference from `aigc_studio.py` without duplicating adapter rules. Build complete candidates from `manager.list_provider_info()`, then annotate each with independent reason codes. Preserve all reasons in deterministic priority order: provider state, publication, pricing, adapter.

- [ ] **Step 4: Run service tests and existing capability tests**

Run: `pytest tests/unit/app/aigc/test_model_policy.py tests/unit/routers/test_aigc_studio.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the inventory service**

```bash
git add src/qwenpaw/app/aigc src/qwenpaw/app/routers/aigc_studio.py tests/unit/app/aigc/test_model_policy.py
git commit -m "feat: classify AIGC model inventory"
```

### Task 3: Add admin policy APIs and validation

**Files:**
- Create: `src/qwenpaw/app/routers/aigc_model_policy.py`
- Modify: `src/qwenpaw/app/routers/__init__.py`
- Test: `tests/unit/routers/test_aigc_model_policy.py`

**Interfaces:**
- Produces: `GET /api/admin/aigc-model-policy/inventory`
- Produces: `GET /api/admin/aigc-model-policy`
- Produces: `PUT /api/admin/aigc-model-policy/{category}`
- Consumes: `AigcModelPolicyService` and `AigcModelPolicyRepository` from Tasks 1–2.

- [ ] **Step 1: Write router tests for complete inventory and independent category saving**

```python
@pytest.mark.asyncio
async def test_admin_inventory_keeps_unpriced_model_visible_but_disabled(client):
    response = await client.get("/api/admin/aigc-model-policy/inventory")
    item = next(x for x in response.json()["categories"]["image"] if x["model_id"] == "gpt-image-2")
    assert item["selectable"] is False
    assert item["reasons"] == ["unpriced"]


@pytest.mark.asyncio
async def test_save_rejects_default_outside_selected_models(client):
    response = await client.put("/api/admin/aigc-model-policy/image", json={
        "version": None,
        "models": [{"provider_id": "p", "model_id": "a"}],
        "default_model": {"provider_id": "p", "model_id": "b"},
    })
    assert response.status_code == 422
```

Cover invalid category, no effective selected model, adding disabled candidates, retaining an already-selected invalid item, and stale version returning `409`.

- [ ] **Step 2: Run router tests and verify route-not-found failures**

Run: `pytest tests/unit/routers/test_aigc_model_policy.py -q`

Expected: FAIL with 404 or missing router.

- [ ] **Step 3: Implement Pydantic contracts and endpoints**

Use one request model for ordered refs plus explicit default. Resolve the authenticated admin ID for `updated_by`. Recompute inventory inside the save operation immediately before repository replacement. Return structured errors containing category, provider/model pair, and reason codes.

- [ ] **Step 4: Run admin policy tests**

Run: `pytest tests/unit/routers/test_aigc_model_policy.py tests/unit/app/aigc/test_model_policy.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the admin API**

```bash
git add src/qwenpaw/app/routers/aigc_model_policy.py src/qwenpaw/app/routers/__init__.py tests/unit/routers/test_aigc_model_policy.py
git commit -m "feat: manage AIGC model policies"
```

### Task 4: Enforce effective policies in capability discovery and job submission

**Files:**
- Modify: `src/qwenpaw/app/aigc/model_policy.py`
- Modify: `src/qwenpaw/app/routers/aigc_studio.py`
- Modify: `src/qwenpaw/app/runner/runner.py`
- Test: `tests/unit/app/aigc/test_model_policy.py`
- Test: `tests/unit/routers/test_aigc_studio.py`
- Test: `tests/unit/app/runner/test_workspace_orchestration.py`

**Interfaces:**
- Produces: `filter_capabilities(capabilities: CapabilityList, policies: EffectivePolicySet) -> CapabilityList`
- Produces: per-category `configured_default`, `effective_default`, `fallback_active`, and `fallback_reason` in the user capability response.
- Produces: `assert_job_model_allowed(category, provider_id, model_id)` used before billing and provider dispatch.
- Produces: `AIGC_MODEL_POLICY_ENFORCEMENT` environment switch; values `0`, `false`, or `off` bypass policy filtering and restore legacy effective-inventory behavior without deleting saved policies.

- [ ] **Step 1: Write compatibility, fallback, and enforcement tests**

```python
@pytest.mark.asyncio
async def test_unconfigured_category_preserves_all_effective_models(service, manager):
    effective = await service.effective("image", manager)
    assert effective.configured is False
    assert {item.model_id for item in effective.models} == {"gpt-image-2", "seedream-5"}


@pytest.mark.asyncio
async def test_invalid_configured_default_falls_back_without_overwriting_it(service, manager):
    effective = await service.effective("image", manager)
    assert effective.configured_default.model_id == "gpt-image-2"
    assert effective.effective_default.model_id == "seedream-5"
    assert effective.fallback_active is True


@pytest.mark.asyncio
async def test_job_submission_rejects_model_removed_from_allowlist(client):
    response = await client.post("/api/aigc-studio/jobs", json=job_for("image", "p", "removed"))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "aigc_model_not_allowed"
```

Also prove that restoring the configured default makes it effective again, and that policy validation occurs before billing capture/provider calls.

- [ ] **Step 2: Run focused tests and verify legacy code exposes disallowed models**

Run: `pytest tests/unit/app/aigc/test_model_policy.py tests/unit/routers/test_aigc_studio.py tests/unit/app/runner/test_workspace_orchestration.py -q`

Expected: FAIL on allowlist filtering/enforcement assertions.

- [ ] **Step 3: Integrate the shared effective-policy service**

Apply per-category filtering after the existing provider/publication/pricing capability build. Add defaults metadata without changing individual capability item fields. In job validation, map capability to category and reject an invalid explicit selection; never mutate `job.provider_id` or `job.model_id`. Ensure sealed/workspace catalog builders use the same filtered capability list. Read `AIGC_MODEL_POLICY_ENFORCEMENT` through one helper that defaults to enabled and bypasses both discovery filtering and submission enforcement only for explicit false values.

- [ ] **Step 4: Run focused and billing regression tests**

Run: `pytest tests/unit/app/aigc/test_model_policy.py tests/unit/routers/test_aigc_studio.py tests/unit/app/runner/test_workspace_orchestration.py tests/unit/app/billing -q`

Expected: PASS.

- [ ] **Step 5: Commit runtime enforcement**

```bash
git add src/qwenpaw/app/aigc/model_policy.py src/qwenpaw/app/routers/aigc_studio.py src/qwenpaw/app/runner/runner.py tests/unit/app/aigc/test_model_policy.py tests/unit/routers/test_aigc_studio.py tests/unit/app/runner/test_workspace_orchestration.py
git commit -m "feat: enforce AIGC model allowlists"
```

### Task 5: Add console API contracts and policy state hook

**Files (client repository `dclaw-client/console`):**
- Create: `src/api/modules/aigcModelPolicy.ts`
- Create: `src/api/modules/aigcModelPolicy.test.ts`
- Modify: `src/api/index.ts`
- Create: `src/pages/Settings/Models/hooks/useAigcModelPolicy.ts`
- Create: `src/pages/Settings/Models/hooks/useAigcModelPolicy.test.tsx`

**Interfaces:**
- Produces: `AigcModelCategory`, `AigcModelRef`, `AigcInventoryItem`, `AigcCategoryPolicy`, and `AigcPolicyInventory` TypeScript types.
- Produces: `aigcModelPolicyApi.getInventory()`, `getPolicies()`, and `saveCategory(category, request)`.
- Produces: `useAigcModelPolicy()` with inventory, policies, loading/error state, dirty category drafts, reorder/default/remove operations, and `saveCategory`.

- [ ] **Step 1: Write failing API and hook tests**

```ts
it("saves one ordered AIGC model category", async () => {
  await aigcModelPolicyApi.saveCategory("image", {
    version: 3,
    models: [{ provider_id: "mxapi", model_id: "gpt-image-2" }],
    default_model: { provider_id: "mxapi", model_id: "gpt-image-2" },
  });
  expect(request).toHaveBeenCalledWith("/admin/aigc-model-policy/image", expect.objectContaining({ method: "PUT" }));
});
```

Hook tests must prove category edits are independent and a `409` leaves the draft dirty while requesting a refresh.

- [ ] **Step 2: Run tests and verify missing module failures**

Run: `npm test -- --run src/api/modules/aigcModelPolicy.test.ts src/pages/Settings/Models/hooks/useAigcModelPolicy.test.tsx`

Expected: FAIL because API module and hook do not exist.

- [ ] **Step 3: Implement contracts, API methods, and hook**

Keep network state in the hook and pure ordered-list helpers in the same focused hook module or a sibling `aigcModelPolicyState.ts` if the hook exceeds roughly 200 lines. Do not encode availability rules in the client; consume server `selectable` and `reasons`.

- [ ] **Step 4: Run API and hook tests**

Run: `npm test -- --run src/api/modules/aigcModelPolicy.test.ts src/pages/Settings/Models/hooks/useAigcModelPolicy.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit client data access**

```bash
git add src/api/modules/aigcModelPolicy.ts src/api/modules/aigcModelPolicy.test.ts src/api/index.ts src/pages/Settings/Models/hooks
git commit -m "feat: load AIGC model policies"
```

### Task 6: Build the stable four-category policy manager UI

**Files (client repository `dclaw-client/console`):**
- Create: `src/pages/Settings/Models/components/sections/AigcModelsSection.tsx`
- Create: `src/pages/Settings/Models/components/sections/AigcModelCategoryCard.tsx`
- Create: `src/pages/Settings/Models/components/sections/AigcModelManagerDrawer.tsx`
- Create: `src/pages/Settings/Models/components/sections/AigcModelsSection.test.tsx`
- Modify: `src/pages/Settings/Models/index.module.less`
- Modify: `src/locales/zh.json`
- Modify: `src/locales/en.json`

**Interfaces:**
- Consumes: `useAigcModelPolicy()` from Task 5.
- Produces: four fixed-height category summaries with searchable virtualized add selector and fixed-height management drawer.

- [ ] **Step 1: Write failing component tests for scale-safe layout and disabled reasons**

```tsx
it("renders four independent model categories and caps the summary at three rows", () => {
  render(<AigcModelsSection state={policyFixture({ imageCount: 20 })} />);
  expect(screen.getByText("生文模型")).toBeInTheDocument();
  expect(screen.getByText("生图模型")).toBeInTheDocument();
  expect(screen.getByText("生视频模型")).toBeInTheDocument();
  expect(screen.getByText("生音频模型")).toBeInTheDocument();
  expect(screen.getByText("查看全部 20 项")).toBeInTheDocument();
});

it("shows an unpriced candidate but prevents selecting it", async () => {
  render(<AigcModelsSection state={policyFixture({ reason: "unpriced" })} />);
  await userEvent.click(screen.getByRole("combobox", { name: "添加生图模型" }));
  expect(screen.getByText("未定价")).toBeInTheDocument();
  expect(screen.getByText("MXAPI / GPT Image 2").closest("[aria-disabled='true']")).not.toBeNull();
});
```

Also test default-first display, drawer sorting, set-default, removal, independent save, fallback warning, and narrow layout class behavior.

- [ ] **Step 2: Run component test and verify missing component failure**

Run: `npm test -- --run src/pages/Settings/Models/components/sections/AigcModelsSection.test.tsx`

Expected: FAIL because components do not exist.

- [ ] **Step 3: Implement the components and Less layout**

Use one reusable category card. Main-page summaries render at most three selected rows. Put full selected-list sorting/removal in an Ant Design Drawer with a fixed body height and internal scrolling. Use grouped Select options with virtual scrolling for candidates. Render every server reason as localized status text and disable the option when `selectable` is false.

- [ ] **Step 4: Run UI tests and targeted lint**

Run: `npm test -- --run src/pages/Settings/Models/components/sections/AigcModelsSection.test.tsx && npx eslint src/pages/Settings/Models/components/sections/AigcModel*.tsx`

Expected: PASS.

- [ ] **Step 5: Commit the policy UI**

```bash
git add src/pages/Settings/Models/components/sections/AigcModel*.tsx src/pages/Settings/Models/index.module.less src/locales/zh.json src/locales/en.json
git commit -m "feat: manage AIGC models in settings"
```

### Task 7: Mount the policy UI and unify unavailable model display

**Files (client repository `dclaw-client/console`):**
- Modify: `src/pages/Settings/Models/index.tsx`
- Modify: `src/pages/Settings/Models/components/sections/ModelsSection.tsx`
- Modify: `src/pages/Settings/Models/components/sections/ModelsSection.test.tsx`
- Modify: `src/pages/Settings/Models/components/sections/EmbeddingModelsSection.tsx`
- Modify: `src/pages/Settings/Models/components/sections/EmbeddingModelsSection.test.tsx`
- Modify: `src/api/types/provider.ts`
- Modify (server repository): `src/qwenpaw/app/routers/providers.py`
- Test (server repository): `tests/unit/routers/test_providers.py`

**Interfaces:**
- Consumes: policy components from Task 6.
- Produces: common option state mapper `modelAvailabilityOption(model)` or a focused sibling helper, used by LLM and embedding selectors.

- [ ] **Step 1: Add failing tests for unpriced and unpublished options**

```tsx
it("keeps an unpriced LLM visible and disabled", async () => {
  render(<ModelsSection providers={[providerWith({ billing_eligible: false })]} activeModels={null} onSaved={vi.fn()} />);
  await userEvent.click(screen.getByRole("combobox", { name: "模型" }));
  expect(screen.getByText("未定价")).toBeInTheDocument();
  expect(screen.getByText(/Unpriced Model/).closest("[aria-disabled='true']")).not.toBeNull();
});
```

Add the equivalent unpublished and embedding assertions, plus a page test that AIGC policy appears immediately below the embedding section.

- [ ] **Step 2: Run focused tests and verify unavailable models are currently selectable/unlabeled**

Run: `npm test -- --run src/pages/Settings/Models/components/sections/ModelsSection.test.tsx src/pages/Settings/Models/components/sections/EmbeddingModelsSection.test.tsx`

Expected: FAIL on disabled/status assertions.

- [ ] **Step 3: Extend provider model state and render consistent disabled options**

Expose distinct `billing_eligible` and `published` fields from the server provider inventory. Compute `published` from the model-publication service and `billing_eligible` from the effective price catalog; do not infer one from the other. Keep unavailable options visible. Append localized “未定价” or “未发布” labels and set option `disabled: true`. Mount `AigcModelsSection` after `EmbeddingModelsSection`.

- [ ] **Step 4: Run settings tests and production build**

Run server check: `pytest tests/unit/routers/test_providers.py -q`

Run client check: `npm test -- --run src/pages/Settings/Models && npm run build`

Expected: PASS; only existing chunk-size warnings may remain.

- [ ] **Step 5: Commit settings integration**

Server repository:

```bash
git add src/qwenpaw/app/routers/providers.py tests/unit/routers/test_providers.py
git commit -m "feat: expose model publication status"
```

Client repository:

```bash
git add src/pages/Settings/Models src/api/types/provider.ts
git commit -m "feat: show model availability in settings"
```

### Task 8: Apply policy defaults and invalid-model UX in AIGC Studio

**Files (client repository `dclaw-client/console`):**
- Modify: `src/api/modules/aigcStudio.ts`
- Modify: `src/pages/AigcStudio/useCanvasPersistence.ts`
- Modify: `src/pages/AigcStudio/nodeModelSelection.ts`
- Modify: `src/pages/AigcStudio/nodeModelSelection.test.ts`
- Modify: `src/pages/AigcStudio/index.tsx`
- Modify: `src/pages/AigcStudio/AigcStudio.test.tsx`
- Modify: `src/locales/zh.json`
- Modify: `src/locales/en.json`

**Interfaces:**
- Consumes: capability response defaults metadata from Task 4.
- Produces: `modelForNewNode(category)` using `effective_default`.
- Produces: explicit invalid saved-model state without overwriting persisted node data.

- [ ] **Step 1: Write failing selection and page tests**

```ts
it("uses the server effective default instead of the first capability", () => {
  expect(modelForNewNode(capabilities, defaults.image)).toEqual(seedream5);
});

it("keeps an invalid saved model visible and asks before switching", async () => {
  renderStudioWithSavedModel("mxapi", "removed-model");
  expect(screen.getByText("该模型已不可用")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "生成" }));
  expect(screen.getByText(/切换到当前默认模型/)).toBeInTheDocument();
});
```

Cover all four categories and prove a saved valid selection remains selected.

- [ ] **Step 2: Run focused tests and verify current first-item/default behavior fails**

Run: `npm test -- --run src/pages/AigcStudio/nodeModelSelection.test.ts src/pages/AigcStudio/AigcStudio.test.tsx`

Expected: FAIL on server-default and invalid-model UX assertions.

- [ ] **Step 3: Implement default metadata consumption and explicit switch confirmation**

Store defaults alongside capabilities in `useCanvasPersistence`. For new/unbound nodes, select the server `effective_default`. For saved invalid refs, construct a display-only snapshot and do not mutate canvas data until the user confirms switching. On server `aigc_model_not_allowed`, show the same confirmation and resubmit only after consent.

- [ ] **Step 4: Run AIGC tests and build**

Run: `npm test -- --run src/pages/AigcStudio && npm run build`

Expected: PASS.

- [ ] **Step 5: Commit AIGC client enforcement UX**

```bash
git add src/api/modules/aigcStudio.ts src/pages/AigcStudio src/locales/zh.json src/locales/en.json
git commit -m "feat: honor AIGC model policies in studio"
```

### Task 9: Run cross-repository verification and document operations

**Files:**
- Modify: `docs/operations/aigc-model-policy.md`
- Test: server and client suites listed below.

**Interfaces:**
- Consumes: completed Tasks 1–8.
- Produces: operator instructions for first configuration, status meanings, fallback behavior, and rollback feature flag.

- [ ] **Step 1: Write the operations document with exact rollout behavior**

Document that each category remains in legacy mode until first save; explain all disabled reason labels; explain configured versus effective default; state that restoring a default automatically restores it; state that user-selected invalid models require confirmation; and give the exact feature-flag rollback procedure implemented with Task 4.

- [ ] **Step 2: Run the complete focused server verification**

Run:

```bash
pytest \
  tests/unit/app/storage/repos/test_aigc_model_policy_repo.py \
  tests/unit/app/aigc/test_model_policy.py \
  tests/unit/routers/test_aigc_model_policy.py \
  tests/unit/routers/test_aigc_studio.py \
  tests/unit/app/runner/test_workspace_orchestration.py \
  tests/unit/app/billing -q
```

Expected: PASS with zero failures.

- [ ] **Step 3: Run server formatting and type/static checks used by the repository**

Run the repository-supported commands from `pyproject.toml`, limited to changed server files if the existing full tree is not clean. At minimum run `ruff check` and `ruff format --check` on every changed Python file. Record any unrelated pre-existing failures separately.

- [ ] **Step 4: Run the complete focused client verification**

Run:

```bash
npm test -- --run \
  src/api/modules/aigcModelPolicy.test.ts \
  src/pages/Settings/Models \
  src/pages/AigcStudio
npx eslint \
  src/api/modules/aigcModelPolicy.ts \
  src/pages/Settings/Models \
  src/pages/AigcStudio/nodeModelSelection.ts
npm run build
```

Expected: tests, targeted lint, and build PASS; existing Vite chunk-size warnings are acceptable.

- [ ] **Step 5: Verify requirements manually against the spec**

Check four categories, full disabled inventory, independent save, default-first ordering, fallback/recovery, legacy mode, large-list layout, AIGC node filtering, explicit invalid-selection confirmation, and submission-time enforcement. Confirm no provider adapter or billing formula changed.

- [ ] **Step 6: Commit operations documentation**

```bash
git add docs/operations/aigc-model-policy.md
git commit -m "docs: operate AIGC model policies"
```

- [ ] **Step 7: Push both repositories only after their focused verification passes**

Run `git status -sb` and `git diff --cached --check` in each repository, verify unrelated working-tree changes are not staged, then push the current branches. Report both commit ranges and any pre-existing verification failures.
