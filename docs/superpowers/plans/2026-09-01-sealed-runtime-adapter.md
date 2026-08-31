# 通用密封 Agent Runtime Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为所有密封 Agent提供由签名 manifest 声明、服务端白名单执行、默认关闭且向后兼容的 Runtime Adapter，使 Controller/Harness 生命周期在每轮请求中被宿主强制执行。

**Architecture:** 扩展密封包 manifest，分离 Agent 业务版本与 Runtime Contract 版本；新增 Adapter Registry、请求级 release 固定对象及受控子进程 JSON 协议。Runner 仅在激活 release 明确声明受支持 Adapter 时切换到 Harness 生命周期，否则保留现有 `agent(msgs)` 路径；密封模型危险工具策略保持不变。

**Tech Stack:** Python 3.10+、FastAPI、Pydantic v2、asyncio subprocess、SQLAlchemy、pytest、现有 QwenPaw Runner/ModelMeter/密封包签名体系。

**Spec:** `docs/superpowers/specs/2026-09-01-sealed-runtime-adapter-design.md`

## Global Constraints

- DClaw 源码不得按任何具体 Agent ID、名称或业务版本选择 Adapter。
- `runtime.adapter` 只能取服务端静态白名单值，不能是模块、类或命令路径。
- manifest 未声明 `runtime` 时必须保持当前标准密封 Agent 行为。
- Harness 声明存在但无效、不可用或执行失败时必须 fail closed，禁止退回 `agent(msgs)`。
- 每次请求开始时固定 active release；同一请求不得因激活切换而更换 release。
- 请求 metadata 属于不可信数据，不能覆盖可信身份、release、Adapter 或安全策略。
- `debug` 只控制经授权测试接口的诊断输出，不控制 Controller/Harness 是否运行。
- 不向密封模型开放 `execute_shell_command`、`read_file`、`python_sandbox` 或任意插件工具。
- Harness entrypoint 不得 import 到 Web 主进程，必须使用固定参数的无 shell 子进程协议。
- 现有计费、OpenAPI 幂等和普通 Agent执行路径必须保持兼容。

---

## File Map

- `src/qwenpaw/app/sealed_agents/package.py`：manifest schema、runtime 声明及包级校验。
- `src/qwenpaw/app/sealed_agents/models.py`：持久化 release runtime 元数据。
- `src/qwenpaw/app/sealed_agents/adapters.py`：Adapter Registry、固定 release 与生命周期接口。
- `src/qwenpaw/app/sealed_agents/harness_protocol.py`：受控子进程 JSON 协议、超时、大小限制和阶段 DTO。
- `src/qwenpaw/app/sealed_agents/harness_worker.py`：子进程入口，只加载已固定 release 的 entrypoint。
- `deploy/Dockerfile`：生产镜像安装 bubblewrap，提供无网络、最小只读挂载的 OS 隔离。
- `src/qwenpaw/app/sealed_agents/service.py`：安装/激活时的 Adapter 兼容与 handshake 验证。
- `src/qwenpaw/app/sealed_agents/runtime.py`：密封目录边界和请求级 runtime resolution。
- `src/qwenpaw/app/runner/runner.py`：完整 metadata 传递和标准/Harness 执行分流。
- `src/qwenpaw/app/routers/sealed_agents.py`：管理 DTO 返回 runtime 与最近验证结果。
- `src/qwenpaw/app/billing/context.py`、`src/qwenpaw/app/billing/coordinator.py`：将固定 release identity 写入计费请求快照，不改变金额计算。
- `tests/unit/app/sealed_agents/`：manifest、registry、协议、激活、工具边界单元测试。
- `tests/unit/app/runner/test_sealed_runtime_adapter.py`：Runner metadata 和生命周期分流测试。
- `tests/integration/test_open_api_sealed_runtime_adapter.py`：OpenAPI、幂等、计费、release 切换端到端测试。

---

### Task 1: Manifest Runtime Contract and Backward-Compatible Persistence

**Files:**
- Modify: `src/qwenpaw/app/sealed_agents/package.py`
- Modify: `src/qwenpaw/app/sealed_agents/models.py`
- Modify: `src/qwenpaw/app/sealed_agents/service.py`
- Test: `tests/unit/app/sealed_agents/test_package.py`
- Test: `tests/unit/app/sealed_agents/test_service.py`

**Interfaces:**
- Produces: `SealedRuntimeDeclaration(adapter: str, contract_version: str, failure_policy: Literal["fail_closed"])`
- Produces: `SealedReleaseRecord.runtime_adapter`, `runtime_contract_version`, `runtime_failure_policy`, `entrypoint`
- Consumes: existing signed `SealedPackageManifest` and `SealedReleaseRecord`

- [ ] **Step 1: Write failing manifest compatibility tests**

Add tests proving schema v1 remains valid without runtime, schema v2 accepts a white-space-normalized declaration, and arbitrary module paths or fallback policy are rejected:

```python
def test_v1_manifest_without_runtime_keeps_standard_execution():
    manifest = SealedPackageManifest.model_validate(_manifest(schema_version=1))
    assert manifest.runtime is None


def test_v2_manifest_accepts_harness_contract():
    manifest = SealedPackageManifest.model_validate(
        _manifest(
            schema_version=2,
            runtime={
                "adapter": "sealed_harness",
                "contract_version": "1",
                "failure_policy": "fail_closed",
            },
        ),
    )
    assert manifest.runtime.adapter == "sealed_harness"


@pytest.mark.parametrize(
    "runtime",
    [
        {"adapter": "agent.runtime:Adapter", "contract_version": "1", "failure_policy": "fail_closed"},
        {"adapter": "sealed_harness", "contract_version": "1", "failure_policy": "fallback"},
    ],
)
def test_runtime_declaration_rejects_code_paths_and_fallback(runtime):
    with pytest.raises(ValidationError):
        SealedPackageManifest.model_validate(_manifest(schema_version=2, runtime=runtime))
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
uv run pytest tests/unit/app/sealed_agents/test_package.py -q
```

Expected: failures because `runtime` and `SealedRuntimeDeclaration` do not exist.

- [ ] **Step 3: Implement the manifest models and version rules**

Add immutable Pydantic models:

```python
class SealedRuntimeDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    adapter: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    contract_version: str = Field(pattern=r"^[1-9][0-9]{0,7}$")
    failure_policy: Literal["fail_closed"] = "fail_closed"


class SealedPackageManifest(BaseModel):
    # existing fields remain unchanged
    runtime: SealedRuntimeDeclaration | None = None

    def validate_supported_contract(self) -> None:
        if self.schema_version not in {1, 2}:
            raise ValueError("unsupported schema version")
        if self.schema_version == 1 and self.runtime is not None:
            raise ValueError("schema version 1 cannot declare runtime")
```

Persist the signed runtime fields and entrypoint in `SealedReleaseRecord`; use `None` defaults so existing registry JSON remains readable.

- [ ] **Step 4: Add service persistence round-trip tests**

Install a v2 package and assert the release record contains exactly the signed entrypoint and runtime declaration; install a v1 package and assert all runtime fields are `None`.

- [ ] **Step 5: Run package/service tests and verify GREEN**

```bash
uv run pytest tests/unit/app/sealed_agents/test_package.py tests/unit/app/sealed_agents/test_service.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/sealed_agents/package.py src/qwenpaw/app/sealed_agents/models.py src/qwenpaw/app/sealed_agents/service.py tests/unit/app/sealed_agents/test_package.py tests/unit/app/sealed_agents/test_service.py
git commit -m "feat: declare sealed runtime contracts"
```

---

### Task 2: Trusted Adapter Registry and Request-Level Release Pinning

**Files:**
- Create: `src/qwenpaw/app/sealed_agents/adapters.py`
- Modify: `src/qwenpaw/app/sealed_agents/runtime.py`
- Test: `tests/unit/app/sealed_agents/test_adapters.py`
- Test: `tests/unit/app/sealed_agents/test_runtime.py`

**Interfaces:**
- Consumes: runtime fields added to `SealedReleaseRecord` in Task 1
- Produces: `PinnedSealedRuntime`
- Produces: `SealedRuntimeAdapter` protocol
- Produces: `resolve_pinned_runtime(agent_id: str, registry: SealedAgentRegistry) -> PinnedSealedRuntime | None`
- Produces: `get_runtime_adapter(adapter: str, contract_version: str) -> SealedRuntimeAdapter`

- [ ] **Step 1: Write failing registry and pinning tests**

```python
def test_standard_agent_has_no_pinned_runtime(registry):
    assert resolve_pinned_runtime("ordinary", registry) is None


def test_v1_sealed_agent_pins_standard_runtime(registry_with_v1_agent):
    pinned = resolve_pinned_runtime("sealed-v1", registry_with_v1_agent)
    assert pinned.adapter_key == ("standard", "1")


def test_harness_release_identity_is_copied_not_live(registry_with_harness):
    pinned = resolve_pinned_runtime("sealed", registry_with_harness)
    registry_with_harness.upsert_agent(_record(active_release_id="new-release"))
    assert pinned.release_id == "old-release"
    assert pinned.content_digest == "sha256:" + "a" * 64


def test_unknown_adapter_is_rejected():
    with pytest.raises(UnsupportedSealedRuntime):
        get_runtime_adapter("arbitrary", "1")
```

- [ ] **Step 2: Run tests and verify RED**

```bash
uv run pytest tests/unit/app/sealed_agents/test_adapters.py tests/unit/app/sealed_agents/test_runtime.py -q
```

Expected: import failures for the new interfaces.

- [ ] **Step 3: Implement immutable runtime and Adapter protocol**

```python
@dataclass(frozen=True)
class PinnedSealedRuntime:
    agent_id: str
    release_id: str
    version: str
    content_digest: str
    release_root: Path
    entrypoint: str
    adapter_key: tuple[str, str]
    failure_policy: str


class SealedRuntimeAdapter(Protocol):
    async def run(
        self,
        *,
        pinned: PinnedSealedRuntime,
        request: "SealedAdapterRequest",
        model_executor: "ModelExecutor",
    ) -> AsyncIterator[tuple[Msg, bool]]:
        raise NotImplementedError
```

Register only `("standard", "1")` and `("sealed_harness", "1")`. `resolve_pinned_runtime` must copy all release fields into the frozen object and verify the resolved entrypoint remains under `release_root`.

- [ ] **Step 4: Run tests and verify GREEN**

```bash
uv run pytest tests/unit/app/sealed_agents/test_adapters.py tests/unit/app/sealed_agents/test_runtime.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/app/sealed_agents/adapters.py src/qwenpaw/app/sealed_agents/runtime.py tests/unit/app/sealed_agents/test_adapters.py tests/unit/app/sealed_agents/test_runtime.py
git commit -m "feat: resolve sealed runtime adapters"
```

---

### Task 3: Isolated Harness Subprocess Protocol

**Files:**
- Create: `src/qwenpaw/app/sealed_agents/harness_protocol.py`
- Create: `src/qwenpaw/app/sealed_agents/harness_worker.py`
- Modify: `deploy/Dockerfile`
- Test: `tests/unit/app/sealed_agents/test_harness_protocol.py`
- Test: `tests/fixtures/sealed_harness/agent/runtime.py`

**Interfaces:**
- Consumes: `PinnedSealedRuntime` from Task 2
- Produces: `HarnessProcess.start(pinned)`, `invoke(stage, payload)`, `close()`
- Produces: `HarnessStageRequest(request_id: str, stage: str, payload: dict[str, JSONValue])`
- Produces: `HarnessStageResponse(request_id: str, ok: bool, payload: dict[str, JSONValue], error_code: str | None)`

- [ ] **Step 1: Write failing protocol tests**

Cover handshake, stage ordering, oversized responses, timeout, malformed JSON, environment stripping and release-root validation:

```python
async def test_harness_handshake_reports_contract(pinned_fixture):
    async with HarnessProcess(pinned_fixture) as process:
        response = await process.invoke("handshake", {})
    assert response.payload == {
        "adapter": "sealed_harness",
        "contract_version": "1",
        "stages": [
            "prepare_interaction",
            "controller_gate",
            "required_skill_dispatch",
            "completion_validation",
            "commit",
            "render_bound",
        ],
    }


async def test_harness_timeout_is_fail_closed(pinned_fixture):
    async with HarnessProcess(pinned_fixture, stage_timeout_seconds=0.01) as process:
        with pytest.raises(HarnessTimeout):
            await process.invoke("sleep_forever", {})
```

- [ ] **Step 2: Run protocol tests and verify RED**

```bash
uv run pytest tests/unit/app/sealed_agents/test_harness_protocol.py -q
```

- [ ] **Step 3: Implement bounded JSON-lines transport**

Use `asyncio.create_subprocess_exec` with no shell:

```python
process = await asyncio.create_subprocess_exec(
    "/usr/bin/bwrap",
    "--die-with-parent",
    "--unshare-all",
    "--unshare-net",
    "--new-session",
    "--ro-bind", "/usr", "/usr",
    "--ro-bind", "/usr/local", "/usr/local",
    "--ro-bind", str(server_package_root), "/runtime/qwenpaw",
    "--ro-bind", str(pinned.release_root), "/release",
    "--bind", str(session_root), "/session",
    "--proc", "/proc",
    "--dev", "/dev",
    "--tmpfs", "/tmp",
    sys.executable,
    "-I",
    "/runtime/qwenpaw/app/sealed_agents/harness_worker.py",
    "--release-root", "/release",
    "--session-root", "/session",
    "--entrypoint", pinned.entrypoint,
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    env=minimal_worker_environment(),
    start_new_session=True,
)
```

Install `bubblewrap` in the production image's existing first `apt-get install` block. `HarnessProcess` must refuse to start if `/usr/bin/bwrap` is absent or the isolation self-test fails; it must never fall back to an unisolated subprocess. Enforce constants in `harness_protocol.py`: request/response maximum 1 MiB, JSON depth 32, stage timeout 30 seconds, total timeout 300 seconds, stderr capture maximum 64 KiB. Apply Linux `resource.setrlimit` in the worker for 512 MiB address space, 60 CPU seconds, 32 open files and zero child processes. On protocol failure terminate the whole process group and raise a typed error.

- [ ] **Step 4: Implement worker loading and stage dispatch**

The worker resolves `entrypoint` under `/release`, rejects symlinks, loads only that file, requires a top-level `create_harness()` factory, and invokes only fixed stage method names. It sets its working directory to `/session`, accepts and emits one JSON object per line, and never imports a module path supplied inside a request. Add a protocol test whose fixture attempts DNS/TCP access and reading `/app/working.secret`; both must fail inside bubblewrap.

- [ ] **Step 5: Run protocol and existing sealed boundary tests**

```bash
uv run pytest tests/unit/app/sealed_agents/test_harness_protocol.py tests/unit/app/sealed_agents/test_runtime.py tests/unit/app/sealed_agents/test_react_agent_boundary.py -q
```

- [ ] **Step 6: Commit**

```bash
git add deploy/Dockerfile src/qwenpaw/app/sealed_agents/harness_protocol.py src/qwenpaw/app/sealed_agents/harness_worker.py tests/unit/app/sealed_agents/test_harness_protocol.py tests/fixtures/sealed_harness/agent/runtime.py
git commit -m "feat: isolate sealed harness execution"
```

---

### Task 4: Activation-Time Handshake and Operational DTO

**Files:**
- Modify: `src/qwenpaw/app/sealed_agents/service.py`
- Modify: `src/qwenpaw/app/sealed_agents/models.py`
- Modify: `src/qwenpaw/app/routers/sealed_agents.py`
- Test: `tests/unit/app/sealed_agents/test_service.py`
- Test: `tests/unit/app/test_sealed_agent_admin.py`

**Interfaces:**
- Consumes: `get_runtime_adapter` and `HarnessProcess` from Tasks 2–3
- Produces: `validate_release_runtime(agent_id: str, release_id: str) -> RuntimeValidationRecord`
- Produces: `RuntimeValidationRecord(status, validated_at, adapter, contract_version, error_code)` persisted on release
- Produces: admin DTO fields `runtime` and `runtime_validation`

- [ ] **Step 1: Write failing activation tests**

```python
async def test_activate_harness_release_requires_successful_handshake(client, service):
    release = service.install(_signed_harness_package())
    response = client.post(f"/admin/sealed-agents/sealed-agent/releases/{release.release_id}/activate")
    assert response.status_code == 200
    record = service.get_agent("sealed-agent")
    assert record.active_release_id == release.release_id
    assert record.active_release.runtime_validation.status == "valid"


async def test_failed_handshake_keeps_previous_release_active(client, service):
    previous = _install_and_activate_standard(client, service)
    candidate = service.install(_signed_harness_package(handshake_ok=False))
    response = client.post(f"/admin/sealed-agents/sealed-agent/releases/{candidate.release_id}/activate")
    assert response.status_code == 400
    assert response.json()["detail"] == "sealed agent runtime validation failed"
    assert service.get_agent("sealed-agent").active_release_id == previous.release_id
```

- [ ] **Step 2: Run tests and verify RED**

```bash
uv run pytest tests/unit/app/sealed_agents/test_service.py tests/unit/app/test_sealed_agent_admin.py -q
```

- [ ] **Step 3: Add validation before registry mutation**

Add async `validate_release_runtime` to the service. For standard runtime, create a successful validation record without a subprocess. For Harness, verify Adapter key, entrypoint and handshake response. In the activation router, await validation before changing the agent profile, preloading/reloading the Agent or calling the existing synchronous `service.activate`; persist a sanitized error code on failure while leaving the previous active release and profile untouched.

- [ ] **Step 4: Extend admin DTO assertions**

Assert `GET /admin/sealed-agents` returns:

```json
{
  "active_release_id": "release-2",
  "version": "3.7.1",
  "content_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "runtime": {"adapter": "sealed_harness", "contract_version": "1"},
  "runtime_validation": {"status": "valid", "validated_at": "2026-09-01T00:00:00Z", "error_code": null}
}
```

- [ ] **Step 5: Run tests and verify GREEN**

```bash
uv run pytest tests/unit/app/sealed_agents/test_service.py tests/unit/app/test_sealed_agent_admin.py -q
```

- [ ] **Step 6: Commit**

```bash
git add src/qwenpaw/app/sealed_agents/service.py src/qwenpaw/app/sealed_agents/models.py src/qwenpaw/app/routers/sealed_agents.py tests/unit/app/sealed_agents/test_service.py tests/unit/app/test_sealed_agent_admin.py
git commit -m "feat: validate sealed runtimes on activation"
```

---

### Task 5: Preserve OpenAPI Metadata Without Trust Escalation

**Files:**
- Modify: `src/qwenpaw/app/runner/runner.py`
- Create: `src/qwenpaw/app/sealed_agents/request_context.py`
- Test: `tests/unit/app/runner/test_sealed_runtime_adapter.py`
- Modify: `tests/unit/app/sealed_agents/test_open_api_sealed.py`

**Interfaces:**
- Produces: `normalize_untrusted_metadata(value: object) -> dict[str, JSONValue]`
- Produces: `SealedAdapterRequest.trusted_context` and `.metadata`
- Consumes: existing `request.channel_meta`

- [ ] **Step 1: Write failing metadata propagation tests**

```python
async def test_runner_passes_nested_open_api_metadata_to_request_context(runner):
    captured = {}
    request = _request(
        channel="open:app-1",
        channel_meta={"metadata": {"luyu_debug": True, "case_id": "case-1"}},
    )
    await _run_with_captured_agent_context(runner, request, captured)
    assert captured["metadata"] == {"luyu_debug": True, "case_id": "case-1"}


async def test_metadata_cannot_override_trusted_identity(runner):
    request = _request(
        channel_meta={
            "metadata": {
                "agent_id": "attacker",
                "release_id": "attacker-release",
                "adapter": "arbitrary",
            },
        },
    )
    context = await _capture_context(runner, request)
    assert context["agent_id"] == runner.agent_id
    assert context["metadata"]["agent_id"] == "attacker"
```

Add size/depth rejection tests for payloads over 64 KiB, depth over 16 and non-object metadata.

- [ ] **Step 2: Run tests and verify RED**

```bash
uv run pytest tests/unit/app/runner/test_sealed_runtime_adapter.py tests/unit/app/sealed_agents/test_open_api_sealed.py -q
```

- [ ] **Step 3: Implement normalization and separate trust domains**

Normalize JSON primitives recursively, deep-copy the result, enforce 64 KiB encoded size, depth 16 and 256 total keys. Add only `base_request_context["metadata"]`; do not merge metadata keys into the base context. Construct `SealedAdapterRequest` with distinct dictionaries:

```python
SealedAdapterRequest(
    messages=tuple(msgs),
    trusted_context={
        "agent_id": self.agent_id,
        "session_id": session_id,
        "user_id": user_id,
        "channel": channel,
    },
    metadata=normalize_untrusted_metadata(channel_meta.get("metadata")),
)
```

- [ ] **Step 4: Run tests and verify GREEN**

```bash
uv run pytest tests/unit/app/runner/test_sealed_runtime_adapter.py tests/unit/app/sealed_agents/test_open_api_sealed.py -q
```

- [ ] **Step 5: Commit**

```bash
git add src/qwenpaw/app/runner/runner.py src/qwenpaw/app/sealed_agents/request_context.py tests/unit/app/runner/test_sealed_runtime_adapter.py tests/unit/app/sealed_agents/test_open_api_sealed.py
git commit -m "fix: preserve untrusted OpenAPI metadata"
```

---

### Task 6: Force the Harness Lifecycle in Runner

**Files:**
- Modify: `src/qwenpaw/app/sealed_agents/adapters.py`
- Modify: `src/qwenpaw/app/runner/runner.py`
- Modify: `src/qwenpaw/app/sealed_agents/output_guard.py`
- Test: `tests/unit/app/runner/test_sealed_runtime_adapter.py`
- Test: `tests/unit/app/sealed_agents/test_adapters.py`
- Test: `tests/unit/app/sealed_agents/test_output_guard.py`

**Interfaces:**
- Consumes: `PinnedSealedRuntime`, `HarnessProcess`, `SealedAdapterRequest`
- Produces: `SealedHarnessAdapterV1.run(pinned, request, model_executor) -> AsyncIterator[tuple[Msg, bool]]`
- Produces: `ModelExecutor(messages, controlled_context) -> AsyncIterator[tuple[Msg, bool]]`

- [ ] **Step 1: Write failing lifecycle-order and failure tests**

```python
async def test_harness_runs_every_stage_even_when_debug_is_false(adapter):
    events = []
    result = await _collect(
        adapter.run(
            pinned=_pinned_harness(),
            request=_adapter_request(metadata={"luyu_debug": False}),
            model_executor=_recording_model(events),
            harness=_recording_harness(events),
        ),
    )
    assert events == [
        "prepare_interaction",
        "controller_gate",
        "required_skill_dispatch",
        "model_execution",
        "completion_validation",
        "commit",
        "render_bound",
    ]
    assert result[-1].is_last is True


@pytest.mark.parametrize(
    "failed_stage",
    ["prepare_interaction", "controller_gate", "required_skill_dispatch", "completion_validation", "commit", "render_bound"],
)
async def test_harness_stage_failure_never_falls_back(failed_stage, adapter):
    model = AsyncMock()
    with pytest.raises(SealedHarnessExecutionError):
        await _collect(
            adapter.run(
                pinned=_pinned_harness(),
                request=_adapter_request(metadata={}),
                model_executor=model,
                harness=_failing_harness(failed_stage),
            ),
        )
    if failed_stage in {"prepare_interaction", "controller_gate", "required_skill_dispatch"}:
        model.assert_not_awaited()
```

- [ ] **Step 2: Run tests and verify RED**

```bash
uv run pytest tests/unit/app/sealed_agents/test_adapters.py tests/unit/app/runner/test_sealed_runtime_adapter.py -q
```

- [ ] **Step 3: Implement `SealedHarnessAdapterV1`**

The Adapter must call fixed stage names, validate every response DTO, execute only a fixed semantic capability enum returned by `required_skill_dispatch`, collect model output internally, validate and commit it, then emit only `render_bound` output. It may emit generic progress events before commit but must drop model draft chunks.

Debug exposure rule:

```python
return_debug = (
    request.trusted_context.get("debug_endpoint_authorized") is True
    and request.metadata.get("luyu_debug") is True
)
```

Always run the same stages; conditionally attach only sanitized `debug` data after render.

- [ ] **Step 4: Replace only the sealed execution branch in Runner**

Resolve the pinned runtime once before execution. For `standard`, preserve the exact current `_stream_printing_messages_interruptible` branch with `coroutine_task=agent(msgs)` and the current output guard. For Harness, pass a `model_executor` closure that invokes the existing Agent/ModelMeter stack, then stream Adapter output through the existing sealed output sanitizer. Never catch Adapter errors by running `agent(msgs)` again.

- [ ] **Step 5: Assert ordinary and standard sealed agents are unchanged**

Add tests that compare emitted messages and call counts for an ordinary Agent and a schema-v1 sealed Agent against the current standard path. Assert `tool_allowed_for_runtime` still rejects all dangerous and plugin tools.

- [ ] **Step 6: Run Runner, Adapter and security tests**

```bash
uv run pytest tests/unit/app/runner/test_sealed_runtime_adapter.py tests/unit/app/sealed_agents/test_adapters.py tests/unit/app/sealed_agents/test_output_guard.py tests/unit/app/sealed_agents/test_react_agent_boundary.py -q
```

- [ ] **Step 7: Commit**

```bash
git add src/qwenpaw/app/sealed_agents/adapters.py src/qwenpaw/app/runner/runner.py src/qwenpaw/app/sealed_agents/output_guard.py tests/unit/app/runner/test_sealed_runtime_adapter.py tests/unit/app/sealed_agents/test_adapters.py tests/unit/app/sealed_agents/test_output_guard.py
git commit -m "feat: enforce sealed harness lifecycle"
```

---

### Task 7: OpenAPI, Billing, Idempotency, Security and Release-Switch Integration

**Files:**
- Modify: `src/qwenpaw/app/billing/context.py`
- Modify: `src/qwenpaw/app/billing/coordinator.py`
- Create: `tests/integration/test_open_api_sealed_runtime_adapter.py`
- Modify: `tests/integration/test_open_api_billing_flow.py`
- Modify: `tests/unit/app/billing/test_billing_coordinator.py`

**Interfaces:**
- Consumes: pinned runtime identity exposed by Task 6
- Produces: billing request snapshot key `sealed_runtime`
- Verifies: complete OpenAPI → Runner → Harness → ModelMeter → billing → response path

- [ ] **Step 1: Write failing billing snapshot test**

```python
def test_sealed_runtime_identity_is_audited_not_priced(engine):
    prepared = coordinator.prepare(
        _command(
            metadata={
                "sealed_runtime": {
                    "release_id": "release-1",
                    "version": "3.7.1",
                    "content_digest": "sha256:" + "a" * 64,
                    "adapter": "sealed_harness",
                    "contract_version": "1",
                },
            },
        ),
    )
    order = usage_service.get_order(prepared.usage_order_id)
    snapshot = json.loads(order["request_snapshot_json"])
    assert snapshot["metadata"]["sealed_runtime"]["release_id"] == "release-1"
    assert order["quoted_credits"] == prepared.quoted_credits
```

- [ ] **Step 2: Run billing test and verify RED**

```bash
uv run pytest tests/unit/app/billing/test_billing_coordinator.py -q
```

- [ ] **Step 3: Add a server-owned audit snapshot field**

Add `sealed_runtime` to the trusted billing command/context, not untrusted request metadata. Serialize only release ID, version, digest, Adapter and contract into `request_snapshot_json`; do not allow the sealed package to set price, credits, model usage or wallet fields.

- [ ] **Step 4: Write end-to-end integration tests**

The new integration file must use the shared `sealed_open_api` fixture, whose `post(metadata, idempotency_key)` method returns the HTTP response and whose `events`, `model_calls`, `active_release` and `billing_order(response)` helpers expose durable observations. Add these tests:

```python
async def test_open_api_harness_runs_complete_lifecycle(sealed_open_api):
    response = await sealed_open_api.post(
        metadata={"luyu_debug": False},
        idempotency_key="complete-lifecycle",
    )
    assert response.status_code == 200
    assert sealed_open_api.events == [
        "prepare_interaction",
        "controller_gate",
        "required_skill_dispatch",
        "model_execution",
        "completion_validation",
        "commit",
        "render_bound",
    ]
    assert response.json()["message"] == "rendered result"
    assert "debug" not in response.json()


async def test_idempotent_replay_does_not_rerun_harness(sealed_open_api):
    first = await sealed_open_api.post({}, "same-key")
    first_events = list(sealed_open_api.events)
    replay = await sealed_open_api.post({}, "same-key")
    assert replay.json() == first.json()
    assert sealed_open_api.events == first_events
    assert sealed_open_api.model_calls == 1


async def test_release_switch_is_visible_only_to_next_request(sealed_open_api):
    blocked = sealed_open_api.post_blocked_after_pin({}, "old-request")
    await sealed_open_api.wait_until_pinned()
    sealed_open_api.activate_release("release-2")
    first = await blocked
    second = await sealed_open_api.post({}, "new-request")
    assert sealed_open_api.billing_order(first)["sealed_runtime"]["release_id"] == "release-1"
    assert sealed_open_api.billing_order(second)["sealed_runtime"]["release_id"] == "release-2"


@pytest.mark.parametrize(
    "case",
    [
        "unauthorized_debug",
        "harness_failure",
        "ordinary_agent",
        "standard_sealed_agent",
        "dangerous_capability_request",
    ],
)
async def test_runtime_security_and_compatibility_cases(sealed_open_api, case):
    result = await sealed_open_api.run_case(case)
    assert result == sealed_open_api.expected_case_result(case)
```

Use signed fixture releases with different `release_id`, version and digest. Block the first request after pinning, activate the second release, then assert the first audit uses release one and the next request uses release two.

- [ ] **Step 5: Run focused integration tests**

```bash
uv run pytest tests/integration/test_open_api_sealed_runtime_adapter.py tests/integration/test_open_api_billing_flow.py tests/unit/app/billing/test_billing_coordinator.py -q
```

- [ ] **Step 6: Run the complete sealed/OpenAPI regression set**

```bash
uv run pytest tests/unit/app/sealed_agents tests/unit/app/test_sealed_agent_admin.py tests/unit/app/test_open_api_router.py tests/integration/test_open_api_billing_flow.py tests/integration/test_open_api_sealed_runtime_adapter.py -q
```

- [ ] **Step 7: Run static and repository verification**

```bash
uv run ruff check src/qwenpaw/app/sealed_agents src/qwenpaw/app/runner/runner.py src/qwenpaw/app/routers/sealed_agents.py src/qwenpaw/app/billing/context.py src/qwenpaw/app/billing/coordinator.py tests/unit/app/sealed_agents tests/unit/app/runner/test_sealed_runtime_adapter.py tests/integration/test_open_api_sealed_runtime_adapter.py
uv run python -m compileall -q src/qwenpaw/app/sealed_agents src/qwenpaw/app/runner
git diff --check
```

- [ ] **Step 8: Commit**

```bash
git add src/qwenpaw/app/billing/context.py src/qwenpaw/app/billing/coordinator.py tests/unit/app/billing/test_billing_coordinator.py tests/integration/test_open_api_billing_flow.py tests/integration/test_open_api_sealed_runtime_adapter.py
git commit -m "test: verify sealed runtime integration"
```

---

## Final Review Gate

- [ ] Confirm no production source contains a concrete Agent ID or Agent business version routing condition:

```bash
rg -n "luyu_traffic_operator|version\s*==\s*['\"]2\.0\.4" src
```

Expected: no matches.

- [ ] Confirm dangerous tools remain denied for all sealed agents:

```bash
uv run pytest tests/unit/app/sealed_agents/test_react_agent_boundary.py -q
```

- [ ] Confirm manifest v1, standard runtime and ordinary Agent compatibility:

```bash
uv run pytest tests/unit/app/sealed_agents/test_package.py tests/unit/app/sealed_agents/test_adapters.py tests/unit/app/runner/test_sealed_runtime_adapter.py -q
```

- [ ] Confirm fresh complete server test result before integration:

```bash
uv run pytest -q
```

- [ ] Review the final diff specifically for silent fallback, direct entrypoint import, shell invocation, environment leakage, unsanitized debug output and caller-controlled Adapter selection.
