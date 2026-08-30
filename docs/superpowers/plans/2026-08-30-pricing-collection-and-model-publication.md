# 官方价格采集与模型发布状态 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自动采集生产环境已启用模型的可审计价格候选，并由管理员逐模型审批发布；正式目录同时成为所有普通客户端模型选择器和服务端调用入口的统一白名单。

**Architecture:** 在现有 `PricingModelInventory`、`PricingSyncService`、草案和价格目录之上增加持久化采集任务、证据分级候选和模型发布决策。采集任务独立于十五分钟保险锁运行，审批与发布继续受锁保护；运行时通过服务端目录资格服务统一过滤和拒绝未发布模型，前端只消费该资格结果。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy、PostgreSQL/SQLite、asyncio/httpx、Pydantic、React 18、TypeScript、Ant Design、Vitest、pytest。

**Spec:** `docs/superpowers/specs/2026-08-30-pricing-collection-and-model-publication-design.md`

## Global Constraints

- 官方已验证、AI 官方证据提取、AI 多来源推断、AI 无证据估算的默认倍率分别为 `1.5`、`1.6`、`1.8`、`2.0`。
- AI、模糊价格和采集失败默认不发布；管理员可明确审批 AI 无证据估算。
- 相同模型的必要计价维度必须整体发布或整体不发布。
- 采集、查看任务和生成候选不依赖十五分钟保险锁；映射、倍率、审批和发布必须持有保险锁。
- 普通客户和 `szzz_admin` 都不能绕过模型发布白名单；`szzz_admin` 只豁免费用。
- 采集失败不得改变正式目录、钱包或客户余额。
- 当前请求锁定旧目录；只对新请求执行最新目录资格判断。
- 外部来源仅允许 HTTPS 和平台官方域名白名单；大模型输出必须通过结构、单位、币种和数值校验。

---

### Task 1: 持久化采集任务、候选证据与模型发布决策

**Files:**
- Modify: `src/qwenpaw/app/storage/schema.py`
- Modify: `src/qwenpaw/app/storage/repos/pricing_admin_repo.py`
- Modify: `tests/unit/app/storage/test_billing_schema.py`
- Modify: `tests/integration/test_billing_schema_postgres.py`
- Modify: `tests/unit/app/storage/repos/test_pricing_admin_repo.py`

**Interfaces:**
- Produces: `PricingAdminRepository.create_collection_job(...) -> dict[str, Any]`
- Produces: `PricingAdminRepository.claim_collection_job(worker_id, now, lease_seconds) -> dict[str, Any] | None`
- Produces: `PricingAdminRepository.update_collection_item(...) -> dict[str, Any]`
- Produces: `PricingAdminRepository.list_collection_jobs(limit=...) -> list[dict[str, Any]]`
- Produces: `PricingAdminRepository.set_model_publication_decisions(draft_key, decisions, actor_id) -> list[dict[str, Any]]`

- [ ] **Step 1: Write failing fresh/upgrade schema tests**

```python
def test_pricing_collection_schema_is_created_and_upgrade_is_idempotent(engine):
    create_all(engine)
    create_all(engine)
    names = set(inspect(engine).get_table_names())
    assert {
        "billing_pricing_collection_jobs",
        "billing_pricing_collection_items",
        "billing_pricing_model_decisions",
    } <= names
    item_columns = {
        row["name"]
        for row in inspect(engine).get_columns("billing_official_price_candidates")
    }
    assert {
        "evidence_level",
        "evidence_excerpt",
        "collector_version",
        "ai_model",
        "prompt_version",
        "confidence_decimal",
        "default_multiplier_decimal",
    } <= item_columns
```

- [ ] **Step 2: Run schema tests and verify RED**

Run: `pytest tests/unit/app/storage/test_billing_schema.py tests/integration/test_billing_schema_postgres.py -q`

Expected: FAIL because the three tables and evidence columns do not exist.

- [ ] **Step 3: Add exact tables, constraints, indexes, and idempotent upgrades**

```python
billing_pricing_collection_jobs = Table(
    "billing_pricing_collection_jobs",
    metadata,
    Column("id", String, primary_key=True),
    Column("inventory_digest", String, nullable=False),
    Column("status", String, nullable=False),
    Column("requested_by", String, nullable=False),
    Column("worker_id", String),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("progress_json", Text, nullable=False, server_default="{}"),
    Column("error_summary", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    CheckConstraint(
        "status IN ('pending','running','succeeded','partially_succeeded','failed')",
        name="ck_billing_pricing_collection_jobs_status",
    ),
)

billing_pricing_model_decisions = Table(
    "billing_pricing_model_decisions",
    metadata,
    Column("id", String, primary_key=True),
    Column("draft_key", String, nullable=False),
    Column("provider_id", String, nullable=False),
    Column("model_key", String, nullable=False),
    Column("include_in_publish", Boolean, nullable=False),
    Column("reason", Text),
    Column("updated_by", String, nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)
```

Add a unique index for `(inventory_digest, status)` only for active jobs where supported, a unique collection item key `(job_id, provider_id, model_key, pricing_region)`, and a unique decision key `(draft_key, provider_id, model_key)`.

- [ ] **Step 4: Write repository concurrency and idempotency tests**

```python
def test_collection_job_claim_has_one_winner(repository, utc_now):
    job = repository.create_collection_job("digest-1", "admin-1", utc_now)
    winners = [
        repository.claim_collection_job(f"worker-{index}", utc_now, 60)
        for index in range(2)
    ]
    assert sum(row is not None for row in winners) == 1
    assert repository.get_collection_job(job["id"])["status"] == "running"

def test_model_decision_upsert_is_model_scoped(repository):
    rows = repository.set_model_publication_decisions(
        "draft-1",
        [
            {"provider_id": "dashscope", "model_key": "qwen3-max", "include_in_publish": True, "reason": None},
            {"provider_id": "dashscope", "model_key": "unknown", "include_in_publish": False, "reason": "价格待审核"},
        ],
        "admin-1",
    )
    assert {(row["model_key"], row["include_in_publish"]) for row in rows} == {
        ("qwen3-max", True),
        ("unknown", False),
    }
```

- [ ] **Step 5: Implement repository transactions and rerun tests**

Run: `pytest tests/unit/app/storage/repos/test_pricing_admin_repo.py tests/unit/app/storage/test_billing_schema.py tests/integration/test_billing_schema_postgres.py -q`

Expected: PASS with one atomic claim winner on SQLite and PostgreSQL.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/qwenpaw/app/storage/schema.py src/qwenpaw/app/storage/repos/pricing_admin_repo.py tests/unit/app/storage/test_billing_schema.py tests/integration/test_billing_schema_postgres.py tests/unit/app/storage/repos/test_pricing_admin_repo.py
git commit -m "feat: persist pricing collection workflow"
```

---

### Task 2: 官方采集适配器、证据分级与 AI 兜底

**Files:**
- Create: `src/qwenpaw/app/billing/pricing_collectors.py`
- Create: `src/qwenpaw/app/billing/pricing_evidence.py`
- Modify: `src/qwenpaw/app/billing/pricing_sync.py`
- Modify: `src/qwenpaw/app/billing/official_pricing.py`
- Create: `tests/unit/app/billing/test_pricing_collectors.py`
- Modify: `tests/unit/app/billing/test_pricing_sync.py`

**Interfaces:**
- Consumes: `PriceableModel` from `pricing_inventory.py`
- Produces: `EvidenceLevel = Literal['official_verified','ai_official_extract','ai_multi_source','ai_no_evidence','failed']`
- Produces: `CollectedPriceCandidate`
- Produces: `PricingCollector.collect(model: PriceableModel) -> Sequence[CollectedPriceCandidate]`
- Produces: `PricingCollectionPipeline.collect(model) -> ModelCollectionResult`

- [ ] **Step 1: Write failing evidence-chain tests**

```python
@pytest.mark.parametrize(
    ("successful_stage", "level", "multiplier", "publish"),
    [
        ("official_api", "official_verified", Decimal("1.5"), True),
        ("ai_official", "ai_official_extract", Decimal("1.6"), False),
        ("ai_multi", "ai_multi_source", Decimal("1.8"), False),
        ("ai_estimate", "ai_no_evidence", Decimal("2.0"), False),
        (None, "failed", None, False),
    ],
)
def test_collection_pipeline_uses_ordered_evidence_chain(
    pipeline_factory, successful_stage, level, multiplier, publish
):
    result = pipeline_factory(successful_stage).collect(priceable_model())
    assert result.evidence_level == level
    assert result.default_multiplier == multiplier
    assert result.default_include_in_publish is publish
```

- [ ] **Step 2: Run collector tests and verify RED**

Run: `pytest tests/unit/app/billing/test_pricing_collectors.py tests/unit/app/billing/test_pricing_sync.py -q`

Expected: FAIL because evidence models and ordered fallback do not exist.

- [ ] **Step 3: Implement strict candidate types and validation**

```python
@dataclass(frozen=True)
class CollectedPriceCandidate:
    provider_id: str
    official_model_id: str
    pricing_region: str | None
    capability: str
    unit_key: str
    unit_size: int
    conditions: Mapping[str, Any]
    original_currency: str
    original_price: Decimal
    rmb_cost: Decimal
    source_url: str | None
    evidence_level: EvidenceLevel
    evidence_excerpt: str | None
    collector_version: str
    ai_model: str | None
    prompt_version: str | None
    confidence: Decimal | None

    def validate(self, official_hosts: frozenset[str]) -> None:
        if self.unit_size <= 0 or self.original_price < 0 or self.rmb_cost < 0:
            raise ValueError("invalid price quantity")
        if self.source_url:
            parsed = urlparse(self.source_url)
            if parsed.scheme != "https" or parsed.hostname not in official_hosts:
                raise ValueError("untrusted pricing source")
```

- [ ] **Step 4: Implement ordered collectors without treating model memory as official**

Implement `OfficialApiCollector`, `OfficialPageCollector`, `OfficialDocumentCollector`, and `AiFallbackCollector`. The AI adapter receives only sanitized evidence blocks and must return this schema:

```python
class AiPriceExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: str
    unit_key: str
    unit_size: PositiveInt
    conditions: dict[str, str | int | Decimal]
    currency: Literal["CNY", "USD"]
    price: Decimal = Field(ge=0)
    source_urls: list[HttpUrl]
    confidence: Decimal = Field(ge=0, le=1)
    evidence_excerpt: str = Field(min_length=1, max_length=1000)
```

If no official evidence is available, the result must be `ai_no_evidence`, have no official verification flag, and default to non-publish.

- [ ] **Step 5: Add provider adapter registry and initial DashScope/Volcengine host policies**

```python
COLLECTOR_POLICIES = {
    "dashscope": CollectorPolicy(
        official_hosts=frozenset({"help.aliyun.com", "dashscope.aliyun.com"}),
        pricing_regions=frozenset({"cn-beijing", "ap-southeast-1", "us-east-1"}),
    ),
    "volcengine": CollectorPolicy(
        official_hosts=frozenset({"www.volcengine.com", "ark.cn-beijing.volces.com"}),
        pricing_regions=frozenset({"cn-beijing"}),
    ),
}
```

Unknown enabled providers still enter the pipeline and end as AI multi-source, AI estimate, or failed; they must not disappear from coverage.

- [ ] **Step 6: Run all pricing collector tests**

Run: `pytest tests/unit/app/billing/test_pricing_collectors.py tests/unit/app/billing/test_pricing_sync.py tests/unit/app/billing/test_official_pricing.py -q`

Expected: PASS for all five evidence paths, URL allowlisting, invalid units, and regional separation.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/qwenpaw/app/billing/pricing_collectors.py src/qwenpaw/app/billing/pricing_evidence.py src/qwenpaw/app/billing/pricing_sync.py src/qwenpaw/app/billing/official_pricing.py tests/unit/app/billing/test_pricing_collectors.py tests/unit/app/billing/test_pricing_sync.py tests/unit/app/billing/test_official_pricing.py
git commit -m "feat: collect tiered pricing evidence"
```

---

### Task 3: 独立于保险锁的后台采集生命周期和管理 API

**Files:**
- Modify: `src/qwenpaw/app/billing/pricing_sync_runtime.py`
- Modify: `src/qwenpaw/app/_app.py`
- Modify: `src/qwenpaw/app/routers/billing.py`
- Modify: `tests/unit/app/billing/test_pricing_sync_runtime.py`
- Modify: `tests/unit/app/routers/test_billing.py`
- Modify: `tests/integration/test_admin_pricing_flow.py`

**Interfaces:**
- Consumes: Task 1 repository APIs and Task 2 `PricingCollectionPipeline`
- Produces: `PricingCollectionRuntime.enqueue(actor_id) -> dict[str, Any]`
- Produces: `PricingCollectionRuntime.run_pending_once(worker_id) -> str | None`
- HTTP: `POST /api/admin/billing/pricing/collection-jobs`
- HTTP: `GET /api/admin/billing/pricing/collection-jobs`
- HTTP: `GET /api/admin/billing/pricing/collection-jobs/{job_id}`

- [ ] **Step 1: Write failing API and restart-resume tests**

```python
def test_collection_job_does_not_require_unlock(admin_client):
    response = admin_client.post("/api/admin/billing/pricing/collection-jobs")
    assert response.status_code == 202
    assert response.json()["status"] == "pending"

@pytest.mark.asyncio
async def test_expired_running_job_is_reclaimed_after_restart(runtime, repo, now):
    job = repo.create_collection_job("digest", "admin", now)
    repo.claim_collection_job("dead-worker", now, 1)
    await runtime.run_pending_once("new-worker", now=now + timedelta(seconds=2))
    assert repo.get_collection_job(job["id"])["status"] in {
        "succeeded", "partially_succeeded"
    }
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/unit/app/billing/test_pricing_sync_runtime.py tests/unit/app/routers/test_billing.py tests/integration/test_admin_pricing_flow.py -q`

Expected: FAIL because collection-job routes and durable worker do not exist.

- [ ] **Step 3: Implement durable worker with lease renewal and per-model progress**

```python
class PricingCollectionRuntime:
    async def run_pending_once(self, worker_id: str, *, now: datetime | None = None) -> str | None:
        job = self.repository.claim_collection_job(worker_id, now or utcnow(), self.lease_seconds)
        if job is None:
            return None
        for model in self.inventory.list_enabled():
            result = await asyncio.to_thread(self.pipeline.collect, model)
            self.repository.record_collection_result(job["id"], model, result)
            self.repository.renew_collection_job(job["id"], worker_id, utcnow(), self.lease_seconds)
        return self.repository.finish_collection_job(job["id"], worker_id)["status"]
```

The worker must isolate model failures, continue other models, and mark the final job `partially_succeeded` when at least one model fails.

- [ ] **Step 4: Wire lifespan startup and scheduled polling**

Start one `pricing_collection_loop(runtime)` in `_app.lifespan`, cancel it on shutdown, and reclaim expired leases on the next boot. Default source intervals remain daily/weekly/monthly and are configurable through environment settings.

- [ ] **Step 5: Expose routes with admin auth but no pricing unlock**

```python
@admin_router.post("/pricing/collection-jobs", status_code=202)
def start_pricing_collection(request: Request) -> dict[str, Any]:
    return get_pricing_collection_runtime().enqueue(_authenticated_owner(request))

@admin_router.get("/pricing/collection-jobs/{job_id}")
def get_pricing_collection_job(job_id: str) -> dict[str, Any]:
    job = get_pricing_collection_runtime().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Pricing collection job not found")
    return job
```

- [ ] **Step 6: Verify unlock expiry and disconnected page do not stop jobs**

Run: `pytest tests/unit/app/billing/test_pricing_sync_runtime.py tests/unit/app/routers/test_billing.py tests/integration/test_admin_pricing_flow.py -q`

Expected: PASS; the job completes after the request ends and after a synthetic unlock expires.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/qwenpaw/app/billing/pricing_sync_runtime.py src/qwenpaw/app/_app.py src/qwenpaw/app/routers/billing.py tests/unit/app/billing/test_pricing_sync_runtime.py tests/unit/app/routers/test_billing.py tests/integration/test_admin_pricing_flow.py
git commit -m "feat: run durable pricing collection jobs"
```

---

### Task 4: 证据倍率、逐模型发布决策和批量审批

**Files:**
- Modify: `src/qwenpaw/app/billing/pricing_draft.py`
- Modify: `src/qwenpaw/app/billing/pricing_admin.py`
- Modify: `src/qwenpaw/app/billing/pricing_excel.py`
- Modify: `src/qwenpaw/app/routers/billing.py`
- Modify: `tests/unit/app/billing/test_pricing_draft.py`
- Modify: `tests/unit/app/billing/test_pricing_admin.py`
- Modify: `tests/unit/app/billing/test_pricing_excel.py`
- Modify: `tests/integration/test_admin_pricing_flow.py`

**Interfaces:**
- Consumes: evidence candidates and model decisions from Tasks 1–3
- Produces: `PricingDraftRow.evidence_level`, `.default_multiplier`, `.include_in_publish`
- HTTP: `PUT /api/admin/billing/pricing/drafts/{draft_key}/model-decisions`
- HTTP: `POST /api/admin/billing/pricing/drafts/{draft_key}/batch-decision`

- [ ] **Step 1: Write failing multiplier/default-state tests**

```python
@pytest.mark.parametrize(
    ("level", "multiplier", "included"),
    [
        ("official_verified", "1.5", True),
        ("ai_official_extract", "1.6", False),
        ("ai_multi_source", "1.8", False),
        ("ai_no_evidence", "2.0", False),
        ("failed", None, False),
    ],
)
def test_draft_defaults_follow_evidence_level(builder, level, multiplier, included):
    row = builder.build([model()], [candidate(level)], [], []).rows[0]
    assert str(row.multiplier) == multiplier if multiplier else row.rmb_cost is None
    assert row.include_in_publish is included
```

- [ ] **Step 2: Write failing whole-model and batch-decision tests**

```python
def test_partial_dimension_publication_is_rejected(service):
    with pytest.raises(ValueError, match="all required dimensions"):
        service.set_model_decisions(
            "draft",
            [{"provider_id": "dashscope", "model_key": "qwen3-max", "included_units": ["input_tokens"]}],
            "admin",
        )

def test_batch_excludes_all_ai_estimates(service):
    result = service.batch_set_model_decision(
        "draft", evidence_levels=["ai_no_evidence"], include=False, reason="等待核价", actor_id="admin"
    )
    assert result["updated_models"] == 3
```

- [ ] **Step 3: Run tests and verify RED**

Run: `pytest tests/unit/app/billing/test_pricing_draft.py tests/unit/app/billing/test_pricing_admin.py tests/unit/app/billing/test_pricing_excel.py -q`

Expected: FAIL because evidence-specific defaults and model decisions are absent.

- [ ] **Step 4: Implement evidence policy and merge explicit decisions**

```python
EVIDENCE_DEFAULTS = {
    "official_verified": (Decimal("1.5"), True),
    "ai_official_extract": (Decimal("1.6"), False),
    "ai_multi_source": (Decimal("1.8"), False),
    "ai_no_evidence": (Decimal("2.0"), False),
    "failed": (None, False),
}
```

Explicit model decisions override only `include_in_publish`, not evidence identity. Publishing AI estimates requires a non-empty reason and an audit event containing actor, before/after state, candidate digest, and source URLs.

- [ ] **Step 5: Make Excel round-trip preserve evidence and model status**

Add locked identity columns `evidence_level`, `candidate_digest`, `unit_size`, `capability`, and editable columns `include_in_publish`, `approval_reason`, `multiplier_decimal`. Import must reject identity tampering and mixed inclusion across a model's required dimensions.

- [ ] **Step 6: Add unlock-protected decision routes and publish-time inventory revalidation**

```python
class PricingBatchDecisionBody(BaseModel):
    include_in_publish: bool
    provider_ids: list[str] = []
    evidence_levels: list[str] = []
    model_keys: list[str] = []
    reason: str | None = None
```

Both decision routes use `Depends(require_pricing_unlock)`. `publish_preview()` recomputes the inventory digest and refuses stale drafts before creating the immutable catalog.

- [ ] **Step 7: Run pricing approval suite**

Run: `pytest tests/unit/app/billing/test_pricing_draft.py tests/unit/app/billing/test_pricing_admin.py tests/unit/app/billing/test_pricing_excel.py tests/integration/test_admin_pricing_flow.py -q`

Expected: PASS for exact multipliers, defaults, batch updates, AI approval audit, Excel tamper rejection, and stale inventory rejection.

- [ ] **Step 8: Commit Task 4**

```bash
git add src/qwenpaw/app/billing/pricing_draft.py src/qwenpaw/app/billing/pricing_admin.py src/qwenpaw/app/billing/pricing_excel.py src/qwenpaw/app/routers/billing.py tests/unit/app/billing/test_pricing_draft.py tests/unit/app/billing/test_pricing_admin.py tests/unit/app/billing/test_pricing_excel.py tests/integration/test_admin_pricing_flow.py
git commit -m "feat: approve model publication per catalog"
```

---

### Task 5: 服务端正式目录资格白名单

**Files:**
- Create: `src/qwenpaw/app/billing/model_eligibility.py`
- Modify: `src/qwenpaw/app/routers/providers.py`
- Modify: `src/qwenpaw/app/billing/model_meter.py`
- Modify: `src/qwenpaw/agents/model_factory.py`
- Modify: `src/qwenpaw/app/routers/aigc_studio.py`
- Modify: `src/qwenpaw/app/routers/expert_teams.py`
- Modify: `tests/unit/app/billing/test_model_meter.py`
- Modify: `tests/unit/routers/test_providers.py`
- Modify: `tests/integration/test_general_billing_recovery.py`
- Modify: `tests/integration/test_open_api_billing_flow.py`
- Modify: `tests/integration/test_expert_team_billing_flow.py`

**Interfaces:**
- Produces: `PublishedModelEligibility.snapshot() -> PublishedModelSnapshot`
- Produces: `PublishedModelEligibility.require(provider_id, model_key, capability, catalog_version=None) -> None`
- Produces: `ModelNotPublishedError(code='model_not_priced')`
- HTTP provider DTO adds `billing_eligible: bool` and `billing_catalog_version: str | None` for each model.

- [ ] **Step 1: Write failing eligibility tests**

```python
def test_regular_and_complimentary_users_cannot_start_unpublished_model(eligibility):
    with pytest.raises(ModelNotPublishedError) as regular:
        eligibility.require("dashscope", "missing", "chat")
    with pytest.raises(ModelNotPublishedError) as complimentary:
        eligibility.require("dashscope", "missing", "chat", payer_id="szzz_admin")
    assert regular.value.code == complimentary.value.code == "model_not_priced"

def test_running_request_keeps_locked_catalog(eligibility):
    locked = eligibility.snapshot()
    eligibility.publish_new_catalog_without("qwen3-max")
    eligibility.require("dashscope", "qwen3-max", "chat", catalog_version=locked.version)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/unit/app/billing/test_model_meter.py tests/integration/test_open_api_billing_flow.py tests/integration/test_expert_team_billing_flow.py -q`

Expected: FAIL because model eligibility is not centralized.

- [ ] **Step 3: Implement immutable published snapshot lookup**

```python
@dataclass(frozen=True)
class PublishedModelSnapshot:
    catalog_id: str
    version: str
    models: frozenset[tuple[str, str, str, str | None]]

class PublishedModelEligibility:
    def require(self, provider_id: str, model_key: str, capability: str, *, region: str | None = None, catalog_version: str | None = None) -> None:
        snapshot = self.repository.get_published_model_snapshot(catalog_version)
        if (provider_id, model_key, capability, region) not in snapshot.models:
            raise ModelNotPublishedError("model_not_priced")
```

- [ ] **Step 4: Enforce at the common billing/model boundary before supplier contact**

Call `eligibility.require(...)` before reserve and before constructing the provider request. Preserve the already locked catalog version for in-flight retries. `szzz_admin` proceeds without wallet debit only after eligibility succeeds.

- [ ] **Step 5: Filter all ordinary provider/model APIs while preserving admin inventory**

Add `scope=customer|admin` to the internal provider serialization helper. Customer endpoints return only eligible models; settings/admin endpoints return all configured models with status metadata. Apply the same service in Chat, Task, Expert, Expert Team, Automation, channel commands, AIGC Studio, and OpenAPI entry points.

- [ ] **Step 6: Run cross-entrypoint tests**

Run: `pytest tests/unit/routers/test_providers.py tests/unit/app/billing/test_model_meter.py tests/integration/test_general_billing_recovery.py tests/integration/test_open_api_billing_flow.py tests/integration/test_expert_team_billing_flow.py -q`

Expected: PASS; unpublished models are absent/refused everywhere, published models work, and active requests retain their locked catalog.

- [ ] **Step 7: Commit Task 5**

```bash
git add src/qwenpaw/app/billing/model_eligibility.py src/qwenpaw/app/routers/providers.py src/qwenpaw/app/billing/model_meter.py src/qwenpaw/agents/model_factory.py src/qwenpaw/app/routers/aigc_studio.py src/qwenpaw/app/routers/expert_teams.py tests/unit/app/billing/test_model_meter.py tests/unit/routers/test_providers.py tests/integration/test_general_billing_recovery.py tests/integration/test_open_api_billing_flow.py tests/integration/test_expert_team_billing_flow.py
git commit -m "feat: enforce published model eligibility"
```

---

### Task 6: 管理端采集进度、草案自动切换和批量发布界面

**Files:**
- Modify: `../dclaw-client/console/src/api/modules/billing.ts`
- Modify: `../dclaw-client/console/src/api/types/billing.ts`
- Modify: `../dclaw-client/console/src/pages/Settings/Billing/PricingTab.tsx`
- Modify: `../dclaw-client/console/src/pages/Settings/Billing/PricingDrafts.tsx`
- Modify: `../dclaw-client/console/src/pages/Settings/Billing/index.module.less`
- Modify: `../dclaw-client/console/src/pages/Settings/Billing/PricingTab.test.tsx`
- Modify: `../dclaw-client/console/src/pages/Settings/Billing/PricingDrafts.test.tsx`

**Interfaces:**
- Consumes: Tasks 3–4 collection job and decision APIs
- Produces: controlled tab key `overview|models|rules|drafts|history`
- Produces: collection progress panel and batch decision toolbar

- [ ] **Step 1: Write failing UI tests**

```tsx
it("switches to the draft tab after generating a draft", async () => {
  vi.mocked(billingApi.initializePricing).mockResolvedValue(draftFixture);
  render(<PricingTab />);
  await userEvent.click(screen.getByRole("button", { name: "生成价格草案" }));
  expect(await screen.findByRole("tab", { name: /价格草稿（27）/ })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText("价格草案已生成，已自动切换到草稿列表")).toBeVisible();
});

it("shows durable progress separately from unlock time", async () => {
  render(<PricingTab />);
  expect(await screen.findByText("价格采集进度")).toBeVisible();
  expect(screen.getByText("计费设置保险锁")).toBeVisible();
});
```

- [ ] **Step 2: Run UI tests and verify RED**

Run: `cd ../dclaw-client/console && npm test -- PricingTab.test.tsx PricingDrafts.test.tsx --run`

Expected: FAIL because tabs are uncontrolled and collection/batch UI is absent.

- [ ] **Step 3: Add typed API contracts**

```ts
export type PricingEvidenceLevel =
  | "official_verified"
  | "ai_official_extract"
  | "ai_multi_source"
  | "ai_no_evidence"
  | "failed";

export interface PricingCollectionJob {
  id: string;
  status: "pending" | "running" | "succeeded" | "partially_succeeded" | "failed";
  progress: { total: number; completed: number; official: number; ai: number; manual: number; failed: number };
}
```

- [ ] **Step 4: Make tabs controlled and auto-select drafts**

Use `const [activeTab, setActiveTab] = useState("overview")`, pass `activeKey` and `onChange`, set `activeTab` to `"drafts"` after initialization, and render the draft count in the tab label.

- [ ] **Step 5: Implement collection and batch approval UI**

The collection button calls `startPricingCollection()` without requiring an unlock. Poll the job while `pending|running`, render platform/model progress and evidence counts, and stop polling on a terminal state. Batch controls require an active unlock and submit explicit filters plus a reason.

- [ ] **Step 6: Replace technical missing labels and expose evidence details**

Map statuses as:

```ts
const evidenceLabels: Record<PricingEvidenceLevel, string> = {
  official_verified: "官方价格已验证",
  ai_official_extract: "AI 已从官方证据提取，等待审核",
  ai_multi_source: "AI 多来源推断，默认不发布",
  ai_no_evidence: "AI 无证据估算，默认不发布",
  failed: "尚未取得价格，默认不发布",
};
```

Show source URL, region, unit/tier, multiplier, sale price, publication switch, and approval reason in each model group.

- [ ] **Step 7: Run UI tests and production build**

Run: `cd ../dclaw-client/console && npm test -- PricingTab.test.tsx PricingDrafts.test.tsx --run && npm run build`

Expected: PASS; build produces the console bundle without duplicate keys or TypeScript errors.

- [ ] **Step 8: Commit Task 6 in the client repository**

```bash
cd ../dclaw-client
git add console/src/api/modules/billing.ts console/src/api/types/billing.ts console/src/pages/Settings/Billing/PricingTab.tsx console/src/pages/Settings/Billing/PricingDrafts.tsx console/src/pages/Settings/Billing/index.module.less console/src/pages/Settings/Billing/PricingTab.test.tsx console/src/pages/Settings/Billing/PricingDrafts.test.tsx
git commit -m "feat: manage pricing collection and publication"
```

---

### Task 7: 客户端所有模型选择器统一消费服务端资格

**Files:**
- Modify: `../dclaw-client/console/src/api/types/provider.ts`
- Modify: `../dclaw-client/console/src/pages/Chat/utils/chatModelEligibility.ts`
- Modify: `../dclaw-client/console/src/pages/Chat/ModelSelector/index.tsx`
- Modify: `../dclaw-client/console/src/pages/Task/index.tsx`
- Modify: `../dclaw-client/console/src/pages/Settings/Agents/components/AgentModal.tsx`
- Modify: `../dclaw-client/console/src/pages/Automations/index.tsx`
- Modify: `../dclaw-client/console/src/pages/AigcStudio/nodeModelSelection.ts`
- Modify: corresponding `*.test.ts` and `*.test.tsx` files beside each component

**Interfaces:**
- Consumes: server fields `billing_eligible` and `billing_catalog_version`
- Produces: `isCustomerSelectableModel(model: ModelInfo) -> boolean`

- [ ] **Step 1: Write failing selector tests**

```ts
it("hides unpublished models from ordinary selection", () => {
  const options = buildChatToolbarModelOptions(providerWith([
    model("published", true),
    model("hidden", false),
  ]));
  expect(options.map((item) => item.value)).toEqual(["published"]);
});
```

Repeat the assertion for Task, Agent, Automation, AIGC Studio, and Expert selectors.

- [ ] **Step 2: Run selector tests and verify RED**

Run: `cd ../dclaw-client/console && npm test -- chatModelEligibility.test.ts chatToolbarModelOptions.test.ts AgentModal Automations nodeModelSelection.test.ts --run`

Expected: FAIL because selectors currently use raw provider model arrays.

- [ ] **Step 3: Implement one shared eligibility predicate**

```ts
export function isCustomerSelectableModel(model: ModelInfo): boolean {
  return model.billing_eligible === true;
}
```

Replace local raw-array filters with this predicate. Admin model settings remain unfiltered and display `已发布/未发布` badges.

- [ ] **Step 4: Handle a stale selected model safely**

If a page loads an old selection that is no longer published, show its ID as unavailable, prevent submission, and require the user to select an eligible model. Do not silently substitute another model.

- [ ] **Step 5: Run all selector tests and client build**

Run: `cd ../dclaw-client/console && npm test -- chatModelEligibility.test.ts ModelSelector.test.tsx chatToolbarModelOptions.test.ts nodeModelSelection.test.ts --run && npm run build`

Expected: PASS with unpublished models absent from every ordinary selector.

- [ ] **Step 6: Commit Task 7 in the client repository**

```bash
cd ../dclaw-client
git add console/src/api/types/provider.ts console/src/pages/Chat console/src/pages/Task/index.tsx console/src/pages/Settings/Agents/components/AgentModal.tsx console/src/pages/Automations/index.tsx console/src/pages/AigcStudio/nodeModelSelection.ts
git commit -m "feat: hide unpublished models from clients"
```

---

### Task 8: 端到端验收、运维说明和发布证据

**Files:**
- Create: `tests/integration/test_pricing_collection_publication_flow.py`
- Modify: `docs/operations/admin-pricing-rollout.md`
- Modify: `docs/superpowers/specs/2026-08-30-pricing-collection-and-model-publication-design.md`

**Interfaces:**
- Consumes: all previous tasks
- Produces: tested admin workflow from collection through client eligibility

- [ ] **Step 1: Write the end-to-end acceptance test**

```python
def test_collect_approve_publish_and_enforce_model_visibility(app, admin_client, user_client):
    job = admin_client.post("/api/admin/billing/pricing/collection-jobs").json()
    run_collection_job_to_completion(app, job["id"])
    draft = unlock_and_generate_draft(admin_client)
    set_model_decision(admin_client, draft, "dashscope", "qwen3-max", True)
    set_model_decision(admin_client, draft, "dashscope", "uncertain", False)
    publish(admin_client, draft)
    models = user_client.get("/api/providers").json()
    assert model_ids(models) == {"qwen3-max"}
    assert call_model(user_client, "uncertain").json()["code"] == "model_not_priced"
```

- [ ] **Step 2: Run the acceptance test and fix only integration defects**

Run: `pytest tests/integration/test_pricing_collection_publication_flow.py -q`

Expected: PASS with no supplier call for the unpublished model.

- [ ] **Step 3: Document the operator workflow**

Document this exact sequence: start collection without unlock; wait/view durable result; unlock pricing settings only for edits; review evidence and batch decisions; generate/download/import if needed; approve; publish; verify model selector and `model_not_priced`; generate a new draft for later changes. State that collection never auto-publishes.

- [ ] **Step 4: Run server focused and PostgreSQL suites**

Run:

```bash
pytest tests/unit/app/billing tests/unit/app/routers/test_billing.py tests/unit/routers/test_providers.py tests/integration/test_admin_pricing_flow.py tests/integration/test_pricing_collection_publication_flow.py tests/integration/test_open_api_billing_flow.py tests/integration/test_expert_team_billing_flow.py -q
QWENPAW_TEST_POSTGRES_URL=postgresql+psycopg:///postgres pytest tests/integration/test_billing_schema_postgres.py tests/integration/test_billing_repo_postgres.py -q
python -m compileall -q src/qwenpaw
git diff --check
```

Expected: all focused and PostgreSQL tests PASS; compile and diff checks are clean.

- [ ] **Step 5: Run complete client verification**

Run:

```bash
cd ../dclaw-client/console
npm test -- --run
npm run build
cd ../..
git diff --check
```

Expected: all client tests PASS and production assets build successfully.

- [ ] **Step 6: Run full server regression and classify only reproducible unrelated baseline failures**

Run: `pytest -q`

Expected: no failure in pricing, billing, provider serialization, model selection, OpenAPI, Expert, Task, Automation, or AIGC paths.

- [ ] **Step 7: Request code review and resolve every Critical/Important finding**

Review specifically for source-domain validation, AI evidence promotion, regional price binding, whole-model completeness, publication TOCTOU, customer selector bypasses, and durable job recovery.

- [ ] **Step 8: Commit documentation and acceptance coverage**

```bash
git add tests/integration/test_pricing_collection_publication_flow.py docs/operations/admin-pricing-rollout.md docs/superpowers/specs/2026-08-30-pricing-collection-and-model-publication-design.md docs/superpowers/plans/2026-08-30-pricing-collection-and-model-publication.md
git commit -m "test: verify pricing collection publication flow"
```

## Self-Review

- Spec coverage: Tasks 1–3 cover persistent collection and evidence; Task 4 covers multipliers and per-model/batch approval; Task 5 covers authoritative server enforcement; Tasks 6–7 cover all requested UI behavior and client visibility; Task 8 covers operations and cross-entrypoint acceptance.
- Placeholder scan: the plan contains no deferred implementation markers; each production step defines concrete types, endpoints, rules, and verification commands.
- Type consistency: `evidence_level`, `include_in_publish`, `draft_key`, `provider_id`, `model_key`, and `billing_eligible` retain the same names across persistence, service, HTTP, and client tasks.

