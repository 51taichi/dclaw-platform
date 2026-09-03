# Super Expert AIGC Workflow Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete super-expert AIGC checklist loop so DClaw prebuilds validated single- or multi-node workflows and guides the customer through real node execution, recovery, and final submission.

**Architecture:** Add a server-owned semantic node registry and graph compiler behind two new signed capabilities, persist the compiled workflow and guide definition on the existing material task, and project live guide status from persisted canvas jobs and assets. The console renders that server projection and only highlights real canvas controls; Luyu converts its tolerant model output into a deterministic typed workflow request without changing S0-S15.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, file-backed atomic repositories, pytest, React, TypeScript, Vitest, Testing Library, CSS Modules/Less, sealed-agent release tooling.

**Spec:** `docs/superpowers/specs/2026-09-04-super-expert-aigc-workflow-guide-design.md`

## Global Constraints

- Preserve `aigc.task.create/2`, its static operation contract, old task documents, and `binding.node_id` behavior.
- `aigc.workflow.create/1` accepts semantic fields only; physical IDs and raw `node.data` are server-generated.
- `aigc.workflow.capabilities.list/1` reports every registered canvas node as `AUTO_PROVISIONABLE`, `MANUAL_ONLY`, or `UNAVAILABLE`.
- Model output remains tolerant text/INI; only the deterministic Luyu adapter emits the JSON/HTTP machine request.
- Customer clicks remain the only trigger for billable AIGC jobs.
- Server data, not `localStorage`, is authoritative for guide progress.
- Automatic provisioning is all-or-nothing; manual fallback creates a truly blank canvas.
- S0-S15 stages, one-main-Skill routing, content revisions, S8/S10/S11 review gates, and publish authorization do not change.
- Do not include or overwrite unrelated dirty-worktree changes in either DClaw repository.
- Upgrade the Luyu version exactly once when the final package is ready, rebuild its release manifest, upload it to local DClaw, and verify the activated release identity.

---

### Task 1: Semantic workflow contracts and node registry

**Files:**
- Create: `src/qwenpaw/aigc/workflow_contract.py`
- Test: `tests/unit/aigc/test_workflow_contract.py`
- Modify: `src/qwenpaw/app/super_experts/capabilities.py`
- Test: `tests/unit/app/sealed_agents/test_super_expert_manifest.py`

**Interfaces:**
- Consumes: existing `CanvasNode` type names and AIGC capability names.
- Produces: `WorkflowBlueprint`, `WorkflowNode`, `WorkflowEdge`, `NodeRegistration`, `WorkflowCapabilityCatalog`, `workflow_node_registry()`, and `validate_workflow_blueprint()`.

- [ ] **Step 1: Write failing strict-contract tests**

```python
def test_registry_covers_every_canvas_node_type():
    catalog = workflow_node_registry()
    assert set(catalog) == {
        "prompt", "image_generate", "video_generate", "audio_generate",
        "script_generate", "long_image_export", "reference_note",
        "reference_asset", "output", "video_compose", "director_stage",
    }
    assert catalog["video_generate"].provisioning == "AUTO_PROVISIONABLE"
    assert catalog["director_stage"].provisioning in {"MANUAL_ONLY", "UNAVAILABLE"}

def test_blueprint_rejects_physical_and_unknown_fields():
    with pytest.raises(ValidationError):
        WorkflowBlueprint.model_validate({**valid_blueprint(), "canvas_id": "x"})
    with pytest.raises(ValidationError):
        WorkflowNode.model_validate({**valid_node(), "data": {"raw": True}})
```

- [ ] **Step 2: Run the contract tests and confirm they fail because the module is absent**

Run: `uv run pytest tests/unit/aigc/test_workflow_contract.py -q`

Expected: FAIL during import of `qwenpaw.aigc.workflow_contract`.

- [ ] **Step 3: Implement frozen, extra-forbid Pydantic contracts and the full node registry**

```python
ProvisioningMode = Literal["AUTO_PROVISIONABLE", "MANUAL_ONLY", "UNAVAILABLE"]

class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    node_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    kind: str
    title: str = Field(min_length=1, max_length=120)
    capability: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    customer_action: Literal["CLICK_GENERATE", "INSPECT", "SELECT_ASSET", "NONE"]
    optional: bool = False

class WorkflowEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: str
    target: str
    target_slot: str

class WorkflowBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    title: str = Field(min_length=1, max_length=160)
    execution_preference: Literal["CUSTOMER_TRIGGERED"]
    nodes: tuple[WorkflowNode, ...] = Field(min_length=1, max_length=20)
    edges: tuple[WorkflowEdge, ...] = Field(default=(), max_length=40)
    output_node_id: str
    fallback_policy: Literal["MANUAL_BUILD_IF_UNSUPPORTED", "FAIL_CLOSED"]
```

Define all eleven registrations with input/output media types, allowed target slots, strict parameter schema, completion rule, stable control ID, and provisioning reason. Add `aigc.workflow.capabilities.list/1` and `aigc.workflow.create/1` to `PLATFORM_CAPABILITY_CATALOG_V1`, with creation depending on list capability.

- [ ] **Step 4: Run contract and manifest tests**

Run: `uv run pytest tests/unit/aigc/test_workflow_contract.py tests/unit/app/sealed_agents/test_super_expert_manifest.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the protocol unit**

```bash
git add src/qwenpaw/aigc/workflow_contract.py tests/unit/aigc/test_workflow_contract.py src/qwenpaw/app/super_experts/capabilities.py tests/unit/app/sealed_agents/test_super_expert_manifest.py
git commit -m "feat: define super expert AIGC workflow contract"
```

### Task 2: Deterministic graph compiler and physical node factories

**Files:**
- Create: `src/qwenpaw/aigc/workflow_compiler.py`
- Test: `tests/unit/aigc/test_workflow_compiler.py`
- Modify: `src/qwenpaw/app/routers/aigc_studio.py`

**Interfaces:**
- Consumes: `WorkflowBlueprint`, node registry, `CanvasNode`, `CanvasEdge`, and trusted existing assets.
- Produces: `compile_workflow(blueprint, available_models, id_factory, asset_resolver) -> CompiledWorkflow`, `provision_super_expert_aigc_workflow(owner_user_id, material_task_id, compiled) -> Canvas`, and `provision_blank_super_expert_aigc_workspace(owner_user_id, material_task_id, workflow_id) -> Canvas`.

- [ ] **Step 1: Write failing graph and factory tests**

```python
def test_compile_prompt_image_video_graph():
    compiled = compile_workflow(three_node_blueprint(), deterministic_ids, no_assets)
    assert [node.type for node in compiled.nodes] == [
        "prompt", "image_generate", "video_generate"
    ]
    assert [(edge.source, edge.target) for edge in compiled.edges] == [
        (compiled.bindings["copy"], compiled.bindings["keyframe"]),
        (compiled.bindings["keyframe"], compiled.bindings["clip"]),
    ]
    assert compiled.output_node_id == compiled.bindings["clip"]

@pytest.mark.parametrize("mutation", [cycle, duplicate_id, bad_slot, bad_model, two_outputs])
def test_compile_rejects_invalid_graph_before_any_write(mutation):
    with pytest.raises(WorkflowContractError):
        compile_workflow(mutation(three_node_blueprint()), deterministic_ids, no_assets)
```

- [ ] **Step 2: Run compiler tests and confirm missing implementation failure**

Run: `uv run pytest tests/unit/aigc/test_workflow_compiler.py -q`

Expected: FAIL because `compile_workflow` is unavailable.

- [ ] **Step 3: Implement validation, topological ordering, layout, and node factories**

```python
@dataclass(frozen=True)
class CompiledWorkflow:
    workflow_id: str
    nodes: tuple[CanvasNode, ...]
    edges: tuple[CanvasEdge, ...]
    bindings: dict[str, str]
    output_node_id: str
    guide_steps: tuple[WorkflowGuideStepDefinition, ...]

def compile_workflow(
    blueprint: WorkflowBlueprint,
    *,
    available_models: Collection[AvailableModel],
    id_factory: Callable[[str], str],
    asset_resolver: Callable[[str], TrustedAsset | None],
) -> CompiledWorkflow:
    """Validate the complete DAG before creating any physical resource."""
```

Use a stable layered layout: topological depth controls `x` with 520px spacing and order within a depth controls `y` with 360px spacing. Node factories translate only semantic fields into DClaw-owned `node.data`. `reference_asset` accepts a same-owner asset ID only. Experimental nodes never compile as automatic.

- [ ] **Step 4: Replace the one-video provisioner with a generic provisioner while retaining its wrapper**

```python
def provision_super_expert_aigc_workflow(*, owner_user_id, material_task_id, compiled):
    canvas = Canvas(
        id=f"canvas-{uuid.uuid4()}",
        name=compiled.title,
        nodes=list(compiled.nodes),
        edges=list(compiled.edges),
        viewport=compiled.viewport,
        meta={"owner_user_id": owner_user_id, "workflow_id": compiled.workflow_id},
        created_at=_now(),
        updated_at=_now(),
    )
    _write_json(_json_path("canvases", canvas.id), canvas)
    return canvas
```

Keep `provision_super_expert_aigc_workspace()` as a v1-compatible adapter that compiles its existing text-to-video operation into one semantic node.

- [ ] **Step 5: Run compiler and existing AIGC router tests**

Run: `uv run pytest tests/unit/aigc/test_workflow_compiler.py tests/unit/aigc/test_operation_contract.py tests/unit/routers/test_super_expert_platform.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the compiler unit**

```bash
git add src/qwenpaw/aigc/workflow_compiler.py tests/unit/aigc/test_workflow_compiler.py src/qwenpaw/app/routers/aigc_studio.py
git commit -m "feat: compile semantic AIGC workflows"
```

### Task 3: Versioned task binding and durable workflow definition

**Files:**
- Modify: `src/qwenpaw/app/super_experts/models.py`
- Modify: `src/qwenpaw/app/super_experts/aigc_tasks.py`
- Create: `tests/unit/app/super_experts/test_aigc_workflow_tasks.py`
- Modify: `tests/unit/routers/test_super_expert_platform.py`

**Interfaces:**
- Consumes: `CompiledWorkflow` and existing `AigcTaskRepository.apply()`.
- Produces: backward-compatible `AigcTaskBinding`, `AigcWorkflowDefinition`, `AigcGuideStepDefinition`, and workflow data stored atomically in `AigcMaterialTask`.

- [ ] **Step 1: Write migration and idempotency tests**

```python
def test_v1_task_document_loads_without_workflow_fields(tmp_path):
    write_legacy_task_document(tmp_path)
    task = AigcTaskRepository(tmp_path).get("material-1")
    assert task.binding.node_id == "video-1"
    assert task.binding.workflow_id is None
    assert task.workflow is None

def test_workflow_create_replay_returns_same_definition(tmp_path):
    repo = AigcTaskRepository(tmp_path)
    first = repo.apply(workflow_create_command(), "same-key")
    second = repo.apply(workflow_create_command(), "same-key")
    assert second == first
    assert first.binding.node_id == first.binding.output_node_id
```

- [ ] **Step 2: Run the new repository tests and confirm schema failure**

Run: `uv run pytest tests/unit/app/super_experts/test_aigc_workflow_tasks.py -q`

Expected: FAIL because workflow fields do not exist.

- [ ] **Step 3: Extend models without breaking v1 parsing**

```python
class AigcTaskBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    # existing required scope and physical fields remain unchanged
    workflow_id: str | None = None
    execution_mode: Literal["LEGACY", "PREBUILT_WORKFLOW", "MANUAL_BUILD"] = "LEGACY"
    node_bindings: dict[str, str] = Field(default_factory=dict)
    output_node_id: str | None = None
    workflow_revision: int | None = Field(default=None, ge=1)
    guide_revision: int | None = Field(default=None, ge=1)

class AigcMaterialTask(BaseModel):
    # existing fields remain
    workflow: AigcWorkflowDefinition | None = None
    guide_events: tuple[AigcWorkflowGuideEvent, ...] = ()
```

Add `workflow` and optional `guide_event` to `AigcTaskCommand`; on create, require `binding.node_id == binding.output_node_id` for v2 and persist the immutable workflow definition in the same atomic task document. Add a `guide_update` command path that accepts only a binding-exact, revision-exact `SKIP_OPTIONAL` event, appends it to `guide_events`, increments the task version, and does not change the material task status. Keep the legacy guide-update no-op response for tasks without a workflow.

- [ ] **Step 4: Run repository and v1 regression tests**

Run: `uv run pytest tests/unit/app/super_experts/test_aigc_workflow_tasks.py tests/unit/routers/test_super_expert_platform.py -q`

Expected: PASS, including legacy fixture loading.

- [ ] **Step 5: Commit the persistence unit**

```bash
git add src/qwenpaw/app/super_experts/models.py src/qwenpaw/app/super_experts/aigc_tasks.py tests/unit/app/super_experts/test_aigc_workflow_tasks.py tests/unit/routers/test_super_expert_platform.py
git commit -m "feat: persist AIGC workflow task bindings"
```

### Task 4: Signed capability discovery and atomic workflow creation command

**Files:**
- Modify: `src/qwenpaw/app/routers/super_expert_platform.py`
- Modify: `src/qwenpaw/app/routers/aigc_studio.py`
- Modify: `src/qwenpaw/app/runner/runner.py`
- Modify: `tests/unit/routers/test_super_expert_platform.py`
- Modify: `tests/unit/app/runner/test_workspace_orchestration.py`
- Modify: `docs/super-expert-platform-v1.md`

**Interfaces:**
- Consumes: registry, compiler, versioned task model, authorization grant, user/tenant scope.
- Produces: `GET /super-expert-platform/workflow-capabilities`, command `aigc.workflow.capabilities.list/1`, command `aigc.workflow.create/1`, and stable public error codes.

- [ ] **Step 1: Write failing authorization, discovery, creation, rollback, and fallback route tests**

```python
@pytest.mark.asyncio
async def test_authorized_workflow_create_returns_all_bindings(service):
    result = await service.execute(
        tenant_id="tenant-a", user_id="user-a", installation_id=grant.id,
        capability="aigc.workflow.create/1", contract_version="1",
        arguments=workflow_create_arguments(), idempotency_key="workflow-1",
    )
    binding = result["task"]["binding"]
    assert binding["execution_mode"] == "PREBUILT_WORKFLOW"
    assert set(binding["node_bindings"]) == {"copy", "keyframe", "clip"}
    assert binding["node_id"] == binding["output_node_id"]

@pytest.mark.asyncio
async def test_task_write_failure_removes_provisioned_canvas(service, monkeypatch):
    monkeypatch.setattr(service.task_repository, "apply", raise_storage_error)
    with pytest.raises(SuperExpertPlatformError):
        await execute_workflow_create(service)
    assert list(canvas_root.glob("*.json")) == []
```

Also assert cross-tenant, ungranted, unpriced model, bad graph, idempotency conflict, manual-only with `FAIL_CLOSED`, and manual-only with blank-canvas fallback behavior.

- [ ] **Step 2: Run the focused router tests and confirm missing capability failures**

Run: `uv run pytest tests/unit/routers/test_super_expert_platform.py -q`

Expected: FAIL for unsupported workflow capabilities.

- [ ] **Step 3: Implement discovery and create command**

```python
_EVENT_TYPES.update({"aigc.workflow.create/1": "aigc.task.created"})

class AigcWorkflowCreateArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scope: AigcTaskScope
    event_id: str = Field(min_length=1)
    workflow: WorkflowBlueprint

async def _create_bound_aigc_workflow(
    self,
    *,
    installation_id: str,
    user_id: str,
    event_id: str,
    arguments: dict[str, Any],
    idempotency_key: str,
) -> tuple[dict[str, Any], AigcTaskBinding]:
    request = AigcWorkflowCreateArguments.model_validate(arguments)
    catalog = await build_workflow_capability_catalog()
    compiled = compile_workflow(
        request.workflow,
        available_models=catalog.available_models,
        id_factory=physical_workflow_id,
        asset_resolver=lambda asset_id: resolve_owned_asset(user_id, asset_id),
    )
    canvas = provision_super_expert_aigc_workflow(
        owner_user_id=user_id,
        material_task_id=request.scope.material_task_id,
        compiled=compiled,
    )
    try:
        task = self.task_repository.apply(
            workflow_create_command(request, compiled, canvas.id),
            idempotency_key,
        )
    except Exception:
        discard_super_expert_aigc_workspace(
            owner_user_id=user_id,
            material_task_id=request.scope.material_task_id,
            canvas_id=canvas.id,
        )
        raise
    return {"task": task, "payload": {"workflow_id": compiled.workflow_id}}, task.binding
```

Capability discovery must use the same publication and price checks as AIGC job submission. The command route uses `scope` for chat authorization exactly as `aigc.task.create/2` does. Public failures return one of the spec's stable codes with HTTP 400/403/409/422/500 according to class.

Add a `business_call` branch in `runner.py` parallel to the existing `aigc.capabilities.list/1` branch. It must first require the signed grant entry, reject non-empty caller arguments, and return the server-built workflow catalog; it must not route the read through the state-changing platform command service.

- [ ] **Step 4: Document request, response, fallback, and compatibility examples**

Add complete one-node and prompt-image-video examples to `docs/super-expert-platform-v1.md`, including the rule that these are machine API payloads assembled by adapters, not raw model output.

- [ ] **Step 5: Run platform, manifest, operation, and AIGC tests**

Run: `uv run pytest tests/unit/routers/test_super_expert_platform.py tests/unit/app/runner/test_workspace_orchestration.py tests/unit/app/sealed_agents/test_super_expert_manifest.py tests/unit/aigc/test_workflow_contract.py tests/unit/aigc/test_workflow_compiler.py tests/unit/aigc/test_operation_contract.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the command unit**

```bash
git add src/qwenpaw/app/routers/super_expert_platform.py src/qwenpaw/app/routers/aigc_studio.py src/qwenpaw/app/runner/runner.py tests/unit/routers/test_super_expert_platform.py tests/unit/app/runner/test_workspace_orchestration.py docs/super-expert-platform-v1.md
git commit -m "feat: expose super expert workflow capabilities"
```

### Task 5: Server-authoritative guide projection and recovery

**Files:**
- Create: `src/qwenpaw/app/super_experts/aigc_guide.py`
- Create: `tests/unit/app/super_experts/test_aigc_guide.py`
- Modify: `src/qwenpaw/app/routers/super_expert_platform.py`
- Modify: `tests/unit/routers/test_super_expert_platform.py`

**Interfaces:**
- Consumes: persisted task/workflow, current canvas, all jobs for bound nodes, output assets.
- Produces: `project_aigc_guide(task, canvas, jobs) -> AigcGuideProjection` and `GET /super-expert-platform/tasks/{material_task_id}/guide`.

- [ ] **Step 1: Write failing step-state projection tests**

```python
def test_downstream_generate_stays_locked_until_upstream_succeeds():
    guide = project_aigc_guide(task=three_node_task(), canvas=canvas(), jobs=[])
    assert status(guide, "copy.generate") == "READY"
    assert status(guide, "keyframe.generate") == "LOCKED"

def test_failed_job_exposes_retry_and_refresh_reconstructs_same_step():
    guide = project_aigc_guide(task=task(), canvas=canvas(), jobs=[failed_job()])
    assert guide.current_step.status == "FAILED"
    assert guide.current_step.recovery.action == "RETRY_NODE"
    assert project_aigc_guide(task=task(), canvas=canvas(), jobs=[failed_job()]) == guide

def test_regenerated_upstream_invalidates_old_downstream_result():
    guide = project_aigc_guide(task=task(), canvas=canvas(), jobs=job_history_with_new_upstream())
    assert status(guide, "clip.verify") != "COMPLETED"
```

- [ ] **Step 2: Run guide tests and confirm missing projector failure**

Run: `uv run pytest tests/unit/app/super_experts/test_aigc_guide.py -q`

Expected: FAIL because the guide projector is unavailable.

- [ ] **Step 3: Implement deterministic projection**

```python
class AigcGuideProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    workflow_id: str
    workflow_revision: int
    guide_revision: int
    execution_mode: Literal["PREBUILT_WORKFLOW", "MANUAL_BUILD"]
    current_step_id: str
    steps: tuple[AigcGuideStepProjection, ...]
    task_summary: AigcTaskSummary

def project_aigc_guide(*, task, canvas, jobs, now=None):
    """Derive statuses only from immutable guide definitions and persisted facts."""
```

For each bound node, compare job `created_at`/`updated_at` and output IDs. A downstream result counts only if it was produced after the latest required upstream success. Frontend input cannot set `COMPLETED`. Manual mode exposes build steps against an empty canvas. Legacy tasks are projected from the old static operation guide.

Required successful nodes auto-complete without an extra confirmation click. For an optional node, validate and persist only `SKIP_OPTIONAL` through the existing `aigc.guide.update` capability. Store an immutable guide event on the task and reject stale `workflow_id`, `guide_revision`, `step_id`, or physical node bindings; the projector is the only component that turns that event into `SKIPPED`.

- [ ] **Step 4: Add authenticated guide endpoint and ownership checks**

The route loads the bound task, calls `ensure_chat_access`, loads only the task's canvas and jobs, and returns the projection. Missing/deleted bound resources return a blocked guide with a stable recovery code rather than selecting another canvas.

- [ ] **Step 5: Run guide and platform suites**

Run: `uv run pytest tests/unit/app/super_experts/test_aigc_guide.py tests/unit/routers/test_super_expert_platform.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the guide service**

```bash
git add src/qwenpaw/app/super_experts/aigc_guide.py tests/unit/app/super_experts/test_aigc_guide.py src/qwenpaw/app/routers/super_expert_platform.py tests/unit/routers/test_super_expert_platform.py
git commit -m "feat: project authoritative AIGC guide progress"
```

### Task 6: Console API and guide-state hook

**Files:**
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/api/modules/superExpertPlatform.ts`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/components/GuidePanel/useAigcGuideTask.ts`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/components/GuidePanel/useAigcGuideTask.test.tsx`
- Delete after replacement: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/components/GuidePanel/guideStepCompletion.ts`
- Delete after replacement: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/components/GuidePanel/guideStepCompletion.test.ts`

**Interfaces:**
- Consumes: `GET /tasks/{id}`, `GET /tasks/{id}/guide`, existing AIGC job events.
- Produces: strict TypeScript `AigcWorkflowBinding`, `AigcGuideProjection`, and `{task, guide, refresh}` from `useAigcGuideTask()`.

- [ ] **Step 1: Replace hook tests with server-authoritative behavior tests**

```tsx
it("loads the task and its instance guide without requesting a static operation", async () => {
  mockGetTask.mockResolvedValue(workflowTask);
  mockGetGuide.mockResolvedValue(workflowGuide);
  const { result } = renderHook(() => useAigcGuideTask("?task=task-1"));
  await waitFor(() => expect(result.current.guide?.current_step_id).toBe("copy.generate"));
  expect(mockGetOperation).not.toHaveBeenCalled();
});

it("reloads the authoritative step after refresh", async () => {
  mockGetGuide.mockResolvedValueOnce(runningGuide).mockResolvedValueOnce(completedGuide);
  await act(() => result.current.refresh());
  expect(result.current.guide?.current_step_id).toBe("keyframe.generate");
});
```

- [ ] **Step 2: Run hook tests and confirm type/API failures**

Run: `pnpm --dir console test -- --run src/pages/AigcStudio/components/GuidePanel/useAigcGuideTask.test.tsx`

Expected: FAIL because `getGuide` and v2 types are missing.

- [ ] **Step 3: Add strict API types and guide loader**

```typescript
export type GuideStepStatus = "LOCKED" | "READY" | "RUNNING" | "COMPLETED" | "FAILED" | "SKIPPED";
export interface AigcGuideProjection {
  workflow_id: string;
  execution_mode: "PREBUILT_WORKFLOW" | "MANUAL_BUILD" | "LEGACY";
  current_step_id: string;
  steps: AigcGuideStepProjection[];
  task_summary: AigcTaskSummary;
}

getGuide: (materialTaskId: string) =>
  request<AigcGuideProjection>(`/super-expert-platform/tasks/${encodeURIComponent(materialTaskId)}/guide`)
```

The hook loads task and guide concurrently for v2, falls back to `getOperation()` only for `execution_mode === "LEGACY"`, and exposes one `refresh()` that reloads both task and guide. Remove the browser-computed completion module after all imports are gone.

- [ ] **Step 4: Run hook and TypeScript checks**

Run: `pnpm --dir console test -- --run src/pages/AigcStudio/components/GuidePanel/useAigcGuideTask.test.tsx`

Run: `pnpm --dir console exec tsc -b --noEmit`

Expected: PASS.

- [ ] **Step 5: Commit only the guide data-layer files**

```bash
git add console/src/api/modules/superExpertPlatform.ts console/src/pages/AigcStudio/components/GuidePanel/useAigcGuideTask.ts console/src/pages/AigcStudio/components/GuidePanel/useAigcGuideTask.test.tsx console/src/pages/AigcStudio/components/GuidePanel/guideStepCompletion.ts console/src/pages/AigcStudio/components/GuidePanel/guideStepCompletion.test.ts
git commit -m "feat: load authoritative AIGC guide state"
```

### Task 7: Guide-first panel, real-control focus, and centered canvas tools

**Files:**
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/components/GuidePanel/AigcGuidePanel.tsx`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/components/GuidePanel/AigcGuidePanel.module.less`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/components/GuidePanel/AigcGuidePanel.test.tsx`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/components/GuidePanel/controlRegistry.ts`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/components/CanvasMinimap/CanvasMinimap.tsx`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/components/TextNode/TextComposer.tsx`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/components/ImageNode/ImageComposer.tsx`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/components/VideoNode/VideoComposer.tsx`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/components/AudioNode/AudioComposer.tsx`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/components/ScriptNode/ScriptComposer.tsx`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/components/LongImageExportNode/LongImageExportNode.tsx`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/index.tsx`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/index.module.less`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/AigcStudio.test.tsx`

**Interfaces:**
- Consumes: `AigcGuideProjection`, physical `node_id`, stable `control_id`, canvas viewport callbacks.
- Produces: a current-step-first panel, `onFocusStep(nodeId, controlId)`, highlighted real node control, server refresh after jobs, and canvas-relative centered minimap dock.

- [ ] **Step 1: Write failing UI hierarchy and workflow interaction tests**

```tsx
it("renders the current action before collapsed task parameters", () => {
  render(<AigcGuidePanel guide={readyGuide} onFocusStep={onFocusStep} onSkipOptional={onSkipOptional} onSubmit={onSubmit} />);
  const current = screen.getByRole("heading", { name: "生成痛点文案" });
  const parameters = screen.getByRole("button", { name: "查看任务参数" });
  expect(current.compareDocumentPosition(parameters) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.queryByText(fullPrompt)).not.toBeVisible();
});

it("focuses the physical node and never renders a duplicate generate button", async () => {
  await user.click(screen.getByRole("button", { name: "定位到生成按钮" }));
  expect(onFocusStep).toHaveBeenCalledWith("video-physical-1", "aigc.video.generate-submit");
  expect(screen.queryByRole("button", { name: "开始生成" })).not.toBeInTheDocument();
});

it("does not render create-node instructions for prebuilt mode", () => {
  render(<AigcGuidePanel guide={prebuiltGuide} onFocusStep={onFocusStep} onSkipOptional={onSkipOptional} onSubmit={onSubmit} />);
  expect(screen.queryByText(/新建项目|添加视频生成节点|粘贴提示词/)).not.toBeInTheDocument();
});
```

Add a studio layout assertion that the minimap dock is inside the canvas surface and uses `left: 50%`/`translateX(-50%)`, not viewport `right` positioning.

- [ ] **Step 2: Run panel and studio tests and confirm old behavior failures**

Run: `pnpm --dir console test -- --run src/pages/AigcStudio/components/GuidePanel/AigcGuidePanel.test.tsx src/pages/AigcStudio/AigcStudio.test.tsx`

Expected: FAIL because the old panel is parameter-first and `localStorage`-driven.

- [ ] **Step 3: Rebuild the panel around current server step**

```tsx
<aside className={styles.panel} aria-label="AIGC 执行向导">
  <GuideHeader current={currentIndex + 1} total={guide.steps.length} title={guide.task_summary.title} />
  <CurrentStepCard step={currentStep} onLocate={() => onFocusStep(currentStep.node_id, currentStep.control_id)} />
  <StepOutcome completion={currentStep.completion_rule} recovery={currentStep.recovery} />
  <details className={styles.parameters}>
    <summary>查看任务参数</summary>
    <TaskParameters summary={guide.task_summary} />
  </details>
  <CompletedSteps steps={completedSteps} />
  <NextStepPreview step={nextStep} />
  <GuideFooter paused={paused} action={currentStep.primary_action} />
</aside>
```

Remove step-index reads/writes from `localStorage`. Keep pause as a local display preference only. `RUNNING` polls/refreshes; job completion refreshes the guide. `FAILED` offers the projector-provided recovery. `SUBMIT` resolves the asset from `binding.output_node_id ?? binding.node_id`.

- [ ] **Step 4: Bind stable control IDs and focus the real node**

Mark node wrappers and generation/retry controls with platform IDs. `onFocusStep` selects the requested physical node, centers it in the effective canvas, then calls `focusPlatformControl(controlId, nodeId)`. Missing controls show a blocked state and never fall through to another node.

Use these registry-owned control IDs consistently in server projections and React elements: `aigc.text.generate-submit`, `aigc.image.generate-submit`, `aigc.video.generate-submit`, `aigc.audio.generate-submit`, `aigc.script.generate-submit`, and `aigc.long-image.generate-submit`. Scope lookup to `[data-aigc-node-id="<physical id>"]` before resolving the control ID so identical node kinds cannot focus the wrong button.

- [ ] **Step 5: Center minimap controls within the canvas surface**

```less
.canvasSurface { position: relative; }
.minimapDock {
  position: absolute;
  left: 50%;
  right: auto;
  bottom: 24px;
  transform: translateX(-50%);
}
.minimapPanel {
  position: absolute;
  left: 50%;
  right: auto;
  bottom: 72px;
  transform: translateX(-50%);
}
```

Ensure the surface width already excludes the global left navigation and fixed guide panel; when guide width overlays the surface, expose a CSS custom property or inner `canvasViewport` wrapper whose width excludes the panel before centering.

- [ ] **Step 6: Run focused UI, type, and build checks**

Run: `pnpm --dir console test -- --run src/pages/AigcStudio/components/GuidePanel/AigcGuidePanel.test.tsx src/pages/AigcStudio/components/GuidePanel/useAigcGuideTask.test.tsx src/pages/AigcStudio/AigcStudio.test.tsx`

Run: `pnpm --dir console exec tsc -b --noEmit`

Run: `pnpm --dir console build`

Expected: PASS.

- [ ] **Step 7: Commit only AIGC console files**

```bash
git add console/src/pages/AigcStudio/components/GuidePanel console/src/pages/AigcStudio/components/CanvasMinimap/CanvasMinimap.tsx console/src/pages/AigcStudio/components/TextNode/TextComposer.tsx console/src/pages/AigcStudio/components/ImageNode/ImageComposer.tsx console/src/pages/AigcStudio/components/VideoNode/VideoComposer.tsx console/src/pages/AigcStudio/components/AudioNode/AudioComposer.tsx console/src/pages/AigcStudio/components/ScriptNode/ScriptComposer.tsx console/src/pages/AigcStudio/components/LongImageExportNode/LongImageExportNode.tsx console/src/pages/AigcStudio/index.tsx console/src/pages/AigcStudio/index.module.less console/src/pages/AigcStudio/AigcStudio.test.tsx console/src/api/modules/superExpertPlatform.ts
git commit -m "feat: guide customers through prebuilt AIGC workflows"
```

### Task 8: Luyu workflow adapter and S9 orchestration

**Files:**
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent/scripts/luyu_super_expert_platform.py`
- Create: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent/scripts/luyu_aigc_workflow.py`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent/scripts/luyu_workspace_runtime.py`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent/config/stage-goals.json`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent/scripts/build_sealed_release.py`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent/agent.json`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent/tests/test_super_expert_platform_contract.py`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent/tests/test_workspace_runtime.py`
- Create: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent/tests/test_luyu_aigc_workflow.py`

**Interfaces:**
- Consumes: tolerant/INI production intent already parsed into authoritative task production fields; workflow capability catalog.
- Produces: `compile_luyu_workflow_intent(state, catalog) -> WorkflowBlueprintRequest`, `list_workflow_capabilities()`, and `create_aigc_workflow()`.

- [ ] **Step 1: Write failing deterministic adapter tests**

```python
def test_prompt_image_video_plan_compiles_without_model_json():
    request = compile_luyu_workflow_intent(state_with_three_actions(), catalog())
    assert [node["kind"] for node in request["nodes"]] == [
        "prompt", "image_generate", "video_generate"
    ]
    assert request["edges"][-1] == {
        "source": "keyframe", "target": "clip", "target_slot": "first_frame"
    }

def test_ambiguous_or_unavailable_plan_fails_closed():
    with pytest.raises(LuyuAigcWorkflowError, match="capability_unavailable"):
        compile_luyu_workflow_intent(ambiguous_state(), catalog_without_match())
```

Add runtime tests proving only S9 can create the workflow, only one material task is active, event bindings remain exact, and S0-S8/S10-S15 never call either new capability.

- [ ] **Step 2: Run adapter and runtime tests and confirm missing capability failure**

Run: `python3 -m unittest tests.test_luyu_aigc_workflow tests.test_super_expert_platform_contract tests.test_workspace_runtime`

Expected: FAIL because the v2 workflow adapter is absent.

- [ ] **Step 3: Implement strict catalog and create methods**

```python
async def list_workflow_capabilities(self) -> dict[str, Any]:
    return validate_workflow_catalog(
        await self.host.call("aigc.workflow.capabilities.list/1", {})
    )

async def create_aigc_workflow(self, *, scope, event_id, idempotency_key, workflow):
    result = await self.host.call("aigc.workflow.create/1", {
        "scope": scope.as_dict(), "event_id": event_id, "workflow": workflow,
    })
    binding = binding_from_create_result(result, expected_scope=scope)
    validate_workflow_binding(result["task"], binding)
    return result, binding
```

Extend `TrustedBinding` with optional workflow metadata while keeping its existing seven fields and event-shape validation compatible.

- [ ] **Step 4: Implement deterministic intent-to-blueprint compilation**

The compiler reads only current S9 production fields and the returned catalog. It maps explicit ordered actions to closed semantic nodes, selects only available priced models, derives edges from declared material dependencies, and uses the current task/content revision in idempotency. It never parses arbitrary raw chat into a graph and never asks the model for physical IDs or raw canvas JSON.

- [ ] **Step 5: Route S9 to v2 with a v1 compatibility fallback**

If both new capabilities are granted, use workflow v2. If not, retain `aigc.task.create/2` only for the existing single text-to-video operation. A v2 validation/platform error remains a controlled no-progress result and must not silently downgrade to a semantically different one-node task.

Update the S9 `platform_capabilities`, sealed manifest capability declarations, and customer reply to say the workflow is ready and the customer should execute its current node; do not claim “文生视频” for image or multi-node tasks.

- [ ] **Step 6: Run Luyu focused and full contract suites**

Run: `python3 -m unittest tests.test_luyu_aigc_workflow tests.test_super_expert_platform_contract tests.test_workspace_runtime tests.test_luyu_aigc_closed_loop tests.test_goal_driven_dialogue_boundaries`

Expected: PASS.

- [ ] **Step 7: Do not commit in the Luyu directory**

The user explicitly removed the local Git metadata from this directory. Preserve that decision; verify changes through tests and release manifests instead of creating a new repository.

### Task 9: Cross-repository compatibility and end-to-end fixtures

**Files:**
- Create: `tests/fixtures/super_expert/aigc-workflow-v2/manifest.json`
- Create: `tests/fixtures/super_expert/aigc-workflow-v2/one-node.json`
- Create: `tests/fixtures/super_expert/aigc-workflow-v2/three-node.json`
- Create: `tests/integration/test_super_expert_aigc_workflow.py`
- Modify: `/Users/moxi/Desktop/codex space/dclaw-client/console/src/pages/AigcStudio/AigcStudio.test.tsx`
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent/tests/test_luyu_aigc_closed_loop.py`

**Interfaces:**
- Consumes: signed capability manifests, DClaw workflow command/guide endpoint, console task route, Luyu S9 events.
- Produces: one-node, three-node, manual fallback, refresh recovery, submission, and v1 regression evidence.

- [ ] **Step 1: Add failing end-to-end fixture tests**

```python
@pytest.mark.asyncio
async def test_three_node_customer_triggered_closed_loop(app_client, signed_agent):
    created = await create_from_fixture(app_client, signed_agent, "three-node.json")
    assert await guide_status(app_client, created, "copy.generate") == "READY"
    await run_stubbed_node(app_client, created, "copy")
    assert await guide_status(app_client, created, "keyframe.generate") == "READY"
    await run_stubbed_node(app_client, created, "keyframe")
    await run_stubbed_node(app_client, created, "clip")
    submitted = await submit_output(app_client, created)
    assert submitted["task"]["status"] == "SUBMITTED"
```

- [ ] **Step 2: Run the integration test and confirm fixture/behavior failures**

Run: `uv run pytest tests/integration/test_super_expert_aigc_workflow.py -q`

Expected: FAIL until all cross-layer contracts agree.

- [ ] **Step 3: Resolve contract mismatches without weakening validation**

Use the fixture as the single example payload across server, console mocks, and Luyu host mocks. Fix field names, statuses, control IDs, and event binding mismatches at their owning layer. Do not add permissive `Record<string, unknown>` fallbacks around v2 fields.

- [ ] **Step 4: Run full relevant server and console suites**

Run: `uv run pytest tests/unit/aigc tests/unit/app/super_experts tests/unit/app/sealed_agents/test_super_expert_manifest.py tests/unit/routers/test_super_expert_platform.py tests/integration/test_super_expert_aigc_workflow.py -q`

Run: `pnpm --dir '/Users/moxi/Desktop/codex space/dclaw-client/console' test:run -- src/pages/AigcStudio`

Run: `pnpm --dir '/Users/moxi/Desktop/codex space/dclaw-client/console' exec tsc -b --noEmit`

Expected: PASS.

- [ ] **Step 5: Commit DClaw fixture and compatibility tests**

```bash
git add tests/fixtures/super_expert/aigc-workflow-v2 tests/integration/test_super_expert_aigc_workflow.py
git commit -m "test: cover super expert AIGC workflow loop"
```

### Task 10: Release identity, local deployment, and completion audit

**Files:**
- Modify: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent/VERSION.json`
- Regenerate: `/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent/deployment/luyu-v2-release-manifest.json`
- Update only if generated by existing release tooling: Luyu sealed release artifacts.
- Modify only through existing build tooling: DClaw local image and console bundle.

**Interfaces:**
- Consumes: all passing source and test changes.
- Produces: one new immutable Luyu version, one DClaw image containing the new console/server, activated local installation, and runtime smoke evidence.

- [ ] **Step 1: Run pre-release static and focused test gates**

Run in `dclaw-server`: `git diff --check`

Run in `dclaw-client`: `git diff --check`

Run in Luyu: `python3 -m unittest tests.test_luyu_aigc_workflow tests.test_super_expert_platform_contract tests.test_workspace_runtime tests.test_luyu_aigc_closed_loop`

Expected: all commands exit 0.

- [ ] **Step 2: Upgrade Luyu minor version once and rebuild the manifest**

Use the existing versioning policy: this is a new platform capability, so increment the minor version from the currently deployed `VERSION.json`, generate a new `build_id` and build time, then run:

```bash
python3 scripts/build_release_manifest.py --workspace .
python3 scripts/validate_harness_deployment.py --workspace .
```

Expected: release version, build ID, and manifest digest agree.

- [ ] **Step 3: Build the sealed Luyu package and upload through the existing local DClaw path**

Use the repository's current `scripts/build_sealed_release.py` arguments and local official signing key. Verify the upload returns a new release ID and install/activate it without overwriting the prior release.

- [ ] **Step 4: Build and deploy DClaw server plus the current console bundle**

Use the existing local deployment script so the image includes both `/Users/moxi/Desktop/codex space/dclaw-server` and `/Users/moxi/Desktop/codex space/dclaw-client/console`. Do not manually copy build outputs into tracked source directories.

- [ ] **Step 5: Verify runtime health and signed capabilities**

Check the running container health, confirm the active Luyu installation declares both new capabilities, and call the authenticated workflow capability endpoint. The response must include all eleven node registrations and no unavailable/unpriced model in an executable entry.

- [ ] **Step 6: Run local one-node, three-node, refresh, failure, and submission smoke tests**

Use stub generation for the complete multi-node flow. Verify:

```text
task card -> correct canvas -> first READY node -> job RUNNING -> job COMPLETED
-> downstream READY -> final output -> submit -> Luyu review -> original S10 path
```

Refresh between two nodes and confirm the same server-projected current step returns. Verify a manual-only blueprint creates an empty canvas only when fallback is allowed. Perform at most one explicitly authorized real-provider node generation.

- [ ] **Step 7: Audit every design requirement against evidence**

Record the exact test command and result for each of: capability discovery, graph validation, atomic rollback, idempotency, multi-node binding, guide recovery, UI hierarchy, control focus, centered toolbar, Luyu S9-only routing, S0-S15 regression, v1 compatibility, installed release identity, and local container health. Any missing evidence keeps the release incomplete.

- [ ] **Step 8: Commit DClaw source changes without unrelated files**

Review `git status --short` in both DClaw repositories, stage only files named in Tasks 1-10, and commit with repository-appropriate release messages. Do not stage the pre-existing billing/Tauri changes in `dclaw-client` or unrelated server output files.
