# 密封 Agent 统一普通运行链路 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让所有密封 Agent 在网页会话和 OpenAPI 中完整复用普通 Agent 的工作区、Runner、模型、工具、Skill、MCP、知识库、会话、计费和输出链路，同时保留签名发布、版本管理、源码隐藏和管理页面。

**Architecture:** 密封模块只负责控制面：签名包、release、active release、enabled 和不可查看/编辑/下载权限。激活与启动 reconciliation 将 active release 的 `agent/` 注册为标准 `AgentProfileRef`，之后网页和 OpenAPI 都只把 Agent ID 交给现有 `MultiAgentManager` 和普通 Runner；在线链路不再解析 Runtime Adapter，也不再构造 Worker、Harness、HostBridge、`sealed_sessions`、密封消息或密封输出过滤器。

**Tech Stack:** Python 3.13、FastAPI、Pydantic v2、AgentScope Runtime、pytest/pytest-asyncio、Ed25519 签名包、Docker/Compose。

**Spec:** `docs/superpowers/specs/2026-09-01-sealed-agent-unified-standard-runtime-design.md`

## Global Constraints

- 本次只修改 `dclaw-server`；不修改陆羽 Agent 业务代码和 `dclaw-client`。
- 所有密封 Agent 全量采用普通运行链路，不增加 Agent ID 白名单、版本开关或 publication 开关。
- 普通 Agent 不读取密封 Registry、不执行 reconciliation、不改变工作区路径、Runner 参数、工具、Skill、MCP、会话、SSE、计费或错误协议。
- 管理页面和管理 API 继续隐藏内部资产，并继续禁止查看、编辑、克隆、导出和下载。
- 历史 `runtime_adapter`、`runtime_contract_version`、`entrypoint` 只保留为发布审计字段，不参与在线执行选择。
- 旧 `sealed_sessions` 不迁移、不读取、不删除。
- 单个密封 Agent 的安装、校验、启动或调用失败不能阻塞 DClaw、普通 Agent或其他密封 Agent。
- 当前陆羽发布身份固定为 `luyu_traffic_operator` 2.1.0；已知 ZIP SHA-256 为 `01d4561a0493566145528580350dc7954538819040f15f97fe28c66670eca7a6`。
- 全部自动化、普通/密封对照和陆羽连续多轮验收通过前不得要求生产部署。
- 实施任务可在隔离分支产生小提交；合入 `main` 前必须压成一个功能提交，生产只部署一次。

---

### Task 1: 用标准工作区校验取代密封 Runtime Adapter 校验

**Files:**
- Create: `src/qwenpaw/app/sealed_agents/standard_workspace.py`
- Modify: `src/qwenpaw/app/sealed_agents/service.py`
- Modify: `tests/unit/app/sealed_agents/test_service.py`
- Create: `tests/unit/app/sealed_agents/test_standard_workspace.py`

**Interfaces:**
- Produces: `StandardWorkspaceError(error_code: str)`。
- Produces: `validate_standard_workspace(agent_id: str, workspace_root: Path) -> AgentProfileConfig`。
- Preserves: `SealedAgentService.validate_release_runtime(agent_id: str, release_id: str) -> RuntimeValidationRecord` as an async API used by the admin router.
- Changes: `SealedAgentService.activate(agent_id: str, release_id: str)` becomes metadata-only; workspace preload/reload remains exclusively in the admin router and `MultiAgentManager`.

- [ ] **Step 1: Write failing standard-workspace tests**

Add exact cases to `tests/unit/app/sealed_agents/test_standard_workspace.py`:

```python
import json
from pathlib import Path

import pytest

from qwenpaw.app.sealed_agents.standard_workspace import (
    StandardWorkspaceError,
    validate_standard_workspace,
)


def _workspace(root: Path, *, agent_id: str = "luyu") -> Path:
    root.mkdir(parents=True)
    (root / "agent.json").write_text(
        json.dumps({"id": agent_id, "name": "陆羽"}),
        encoding="utf-8",
    )
    return root


def test_valid_standard_workspace_returns_agent_profile(tmp_path):
    result = validate_standard_workspace("luyu", _workspace(tmp_path / "agent"))
    assert result.id == "luyu"
    assert result.name == "陆羽"


@pytest.mark.parametrize(
    ("builder", "error_code"),
    [
        (lambda root: root.mkdir(parents=True), "agent_config_missing"),
        (
            lambda root: (
                root.mkdir(parents=True),
                (root / "agent.json").write_text("{", encoding="utf-8"),
            ),
            "agent_config_invalid",
        ),
        (
            lambda root: _workspace(root, agent_id="other"),
            "agent_id_mismatch",
        ),
    ],
)
def test_invalid_standard_workspace_has_stable_error(tmp_path, builder, error_code):
    root = tmp_path / error_code
    builder(root)
    with pytest.raises(StandardWorkspaceError) as exc_info:
        validate_standard_workspace("luyu", root)
    assert exc_info.value.error_code == error_code


def test_agent_config_symlink_is_rejected(tmp_path):
    source = _workspace(tmp_path / "source") / "agent.json"
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "agent.json").symlink_to(source)
    with pytest.raises(StandardWorkspaceError) as exc_info:
        validate_standard_workspace("luyu", candidate)
    assert exc_info.value.error_code == "unsafe_agent_config"
```

Replace Runtime Adapter handshake expectations in `test_service.py` with:

```python
def _service(tmp_path, public):
    return SealedAgentService(
        root=tmp_path,
        registry=SealedAgentRegistry(tmp_path),
        trusted_signers={"publisher": public},
    )


@pytest.mark.asyncio
async def test_historical_adapter_is_validated_as_standard_workspace(tmp_path):
    private = Ed25519PrivateKey.generate()
    service = _service(tmp_path, private.public_key())
    release = service.install(
        _package(
            private,
            schema_version=2,
            runtime={
                "adapter": "sealed_entrypoint",
                "contract_version": "1",
                "failure_policy": "fail_closed",
            },
        ),
    )
    result = await service.validate_release_runtime("luyu", release.release_id)
    assert result.status == "valid"
    assert result.adapter == "standard"
    assert result.contract_version == "1"


@pytest.mark.asyncio
async def test_validation_never_constructs_legacy_runtime(tmp_path, monkeypatch):
    private = Ed25519PrivateKey.generate()
    service = _service(tmp_path, private.public_key())
    release = service.install(
        _package(
            private,
            schema_version=2,
            runtime={
                "adapter": "sealed_harness",
                "contract_version": "1",
                "failure_policy": "fail_closed",
            },
        ),
    )
    import qwenpaw.app.sealed_agents.service as service_module

    def fail_legacy_runtime(*_args, **_kwargs):
        pytest.fail("legacy sealed runtime must not run")

    monkeypatch.setattr(
        service_module,
        "SealedEntrypointProcess",
        fail_legacy_runtime,
        raising=False,
    )
    monkeypatch.setattr(
        service_module,
        "HarnessProcess",
        fail_legacy_runtime,
        raising=False,
    )
    result = await service.validate_release_runtime("luyu", release.release_id)
    assert result.status == "valid"
    assert result.adapter == "standard"
```

- [ ] **Step 2: Run tests and verify the old implementation fails**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/app/sealed_agents/test_standard_workspace.py \
  tests/unit/app/sealed_agents/test_service.py
```

Expected: collection fails because `standard_workspace` does not exist, or historical adapters still enter the old handshake validator.

- [ ] **Step 3: Implement strict standard-workspace validation**

Create `standard_workspace.py` with this public shape:

```python
from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from ...config.config import AgentProfileConfig


class StandardWorkspaceError(ValueError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def validate_standard_workspace(
    agent_id: str,
    workspace_root: Path,
) -> AgentProfileConfig:
    root = Path(workspace_root)
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise StandardWorkspaceError("workspace_missing") from exc
    agent_config_path = root / "agent.json"
    if agent_config_path.is_symlink():
        raise StandardWorkspaceError("unsafe_agent_config")
    try:
        resolved_config = agent_config_path.resolve(strict=True)
    except OSError as exc:
        raise StandardWorkspaceError("agent_config_missing") from exc
    if not resolved_config.is_relative_to(resolved_root) or not resolved_config.is_file():
        raise StandardWorkspaceError("unsafe_agent_config")
    try:
        payload = json.loads(resolved_config.read_text(encoding="utf-8"))
        profile = AgentProfileConfig.model_validate(payload)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValidationError,
        TypeError,
    ) as exc:
        raise StandardWorkspaceError("agent_config_invalid") from exc
    if profile.id != agent_id:
        raise StandardWorkspaceError("agent_id_mismatch")
    return profile
```

In `service.py`:

- remove `get_runtime_adapter`, `SealedEntrypointProcess`, `HarnessProcess`, protocol errors, `PinnedSealedRuntime`, `RuntimeValidator`, `_runtime_validator`, `_validate_pinned_runtime`, and `_reload_agent`;
- keep runtime fields when installing releases for history/audit;
- make `validate_release_runtime` call `validate_standard_workspace(agent_id, release_root / "agent")` only;
- persist `RuntimeValidationRecord(status="valid", adapter="standard", contract_version="1")` on success;
- persist `status="invalid"`, `adapter="standard"`, `contract_version="1"`, and the exact `StandardWorkspaceError.error_code` on failure;
- make `activate` reject non-valid validation, verify `release_root/agent`, update release states and registry, but never start a process or reload a workspace.

- [ ] **Step 4: Run focused tests**

Run the command from Step 2.

Expected: PASS; no test imports a legacy process from `service.py`.

- [ ] **Step 5: Commit the isolated lifecycle change**

```bash
git add \
  src/qwenpaw/app/sealed_agents/standard_workspace.py \
  src/qwenpaw/app/sealed_agents/service.py \
  tests/unit/app/sealed_agents/test_standard_workspace.py \
  tests/unit/app/sealed_agents/test_service.py
git commit -m "refactor: validate sealed releases as standard workspaces"
```

### Task 2: 启动时幂等对齐 active release 与普通工作区配置

**Files:**
- Create: `src/qwenpaw/app/sealed_agents/workspace_reconciliation.py`
- Modify: `src/qwenpaw/app/_app.py`
- Create: `tests/unit/app/sealed_agents/test_workspace_reconciliation.py`

**Interfaces:**
- Consumes: `validate_standard_workspace(agent_id: str, workspace_root: Path) -> AgentProfileConfig` from Task 1.
- Produces: frozen `WorkspaceReconciliationResult(reconciled: tuple[str, ...], unavailable: tuple[str, ...], config_changed: bool)`.
- Produces: `reconcile_active_sealed_profiles(config: Config, registry: SealedAgentRegistry, sealed_root: Path) -> WorkspaceReconciliationResult`.
- Startup ordering: reconciliation runs inside `_background_startup` immediately before `multi_agent_manager.start_all_configured_agents()`.

- [ ] **Step 1: Write failing reconciliation tests**

Create tests for empty, success, idempotency, multi-Agent, and isolated failure. Use these complete helpers at the top of the test module:

```python
import json
from pathlib import Path

from qwenpaw.app.sealed_agents.models import (
    SealedAgentRecord,
    SealedReleaseRecord,
)
from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry
from qwenpaw.app.sealed_agents.workspace_reconciliation import (
    WorkspaceReconciliationResult,
    reconcile_active_sealed_profiles,
)
from qwenpaw.config.config import AgentProfileRef, Config


def _config_with_ordinary(workspace: Path) -> Config:
    config = Config()
    config.agents.profiles["ordinary"] = AgentProfileRef(
        id="ordinary",
        workspace_dir=str(workspace),
        enabled=True,
    )
    return config


def _append_active_release(
    registry: SealedAgentRegistry,
    sealed_root: Path,
    agent_id: str,
    *,
    valid: bool,
) -> Path:
    release = SealedReleaseRecord(
        release_id=f"{agent_id}-release",
        version="1.0.0",
        content_digest="sha256:" + "a" * 64,
        signer_id="publisher",
        state="active",
    )
    record = SealedAgentRecord(
        agent_id=agent_id,
        name=agent_id,
        active_release_id=release.release_id,
        releases=[release],
    )
    registry.upsert_agent(record)
    release_root = sealed_root / "releases" / agent_id / release.release_id
    agent_root = release_root / "agent"
    agent_root.mkdir(parents=True)
    if valid:
        (agent_root / "agent.json").write_text(
            json.dumps({"id": agent_id, "name": agent_id}),
            encoding="utf-8",
        )
    return release_root


def _active_release(tmp_path: Path, agent_id: str):
    sealed_root = tmp_path / "sealed"
    registry = SealedAgentRegistry(sealed_root)
    config = _config_with_ordinary(tmp_path / "ordinary")
    release_root = _append_active_release(
        registry,
        sealed_root,
        agent_id,
        valid=True,
    )
    return config, registry, sealed_root, release_root


def _append_broken_active_release(registry, sealed_root, agent_id):
    return _append_active_release(
        registry,
        sealed_root,
        agent_id,
        valid=False,
    )
```

Then add:

```python
def test_empty_registry_does_not_touch_ordinary_profiles(tmp_path):
    config = _config_with_ordinary(tmp_path / "ordinary")
    before = config.model_dump(mode="json")
    result = reconcile_active_sealed_profiles(
        config,
        SealedAgentRegistry(tmp_path / "sealed"),
        tmp_path / "sealed",
    )
    assert result == WorkspaceReconciliationResult((), (), False)
    assert config.model_dump(mode="json") == before


def test_active_release_registers_exact_standard_workspace(tmp_path):
    config, registry, sealed_root, release_root = _active_release(tmp_path, "luyu")
    result = reconcile_active_sealed_profiles(config, registry, sealed_root)
    assert result.reconciled == ("luyu",)
    assert result.unavailable == ()
    assert config.agents.profiles["luyu"] == AgentProfileRef(
        id="luyu",
        workspace_dir=str(release_root / "agent"),
        enabled=True,
    )


def test_reconciliation_preserves_runtime_model_override(tmp_path):
    config, registry, sealed_root, release_root = _active_release(tmp_path, "luyu")
    config.agents.profiles["luyu"] = AgentProfileRef(
        id="luyu",
        workspace_dir="/old/workspace",
        enabled=True,
        active_model_override=True,
        active_model={"provider_id": "provider-1", "model": "model-1"},
    )
    reconcile_active_sealed_profiles(config, registry, sealed_root)
    profile = config.agents.profiles["luyu"]
    assert profile.workspace_dir == str(release_root / "agent")
    assert profile.active_model_override is True
    assert profile.active_model.provider_id == "provider-1"
    assert profile.active_model.model == "model-1"


def test_reconciliation_is_idempotent(tmp_path):
    config, registry, sealed_root, _ = _active_release(tmp_path, "luyu")
    first = reconcile_active_sealed_profiles(config, registry, sealed_root)
    second = reconcile_active_sealed_profiles(config, registry, sealed_root)
    assert first.config_changed is True
    assert second.config_changed is False


def test_one_invalid_sealed_agent_does_not_change_ordinary_or_valid_agent(tmp_path):
    config, registry, sealed_root, _ = _active_release(tmp_path, "luyu")
    _append_broken_active_release(registry, sealed_root, "broken")
    ordinary_before = config.agents.profiles["ordinary"].model_copy(deep=True)
    result = reconcile_active_sealed_profiles(config, registry, sealed_root)
    assert result.reconciled == ("luyu",)
    assert result.unavailable == ("broken",)
    assert config.agents.profiles["ordinary"] == ordinary_before
    assert config.agents.profiles["broken"].enabled is False
```

The helpers must construct `SealedReleaseRecord` and `SealedAgentRecord` directly and write a minimal valid `agent/agent.json`; they must not use runtime adapters or subprocesses.

- [ ] **Step 2: Verify the new module is missing**

Run:

```bash
.venv/bin/pytest -q tests/unit/app/sealed_agents/test_workspace_reconciliation.py
```

Expected: FAIL during import.

- [ ] **Step 3: Implement reconciliation without copying workspaces**

Implement this algorithm:

```python
@dataclass(frozen=True)
class WorkspaceReconciliationResult:
    reconciled: tuple[str, ...]
    unavailable: tuple[str, ...]
    config_changed: bool


def reconcile_active_sealed_profiles(config, registry, sealed_root):
    reconciled: list[str] = []
    unavailable: list[str] = []
    changed = False
    for record in sorted(registry.list_agents(), key=lambda item: item.agent_id):
        active = record.active_release
        if not record.enabled or active is None:
            previous = config.agents.profiles.get(record.agent_id)
            if previous is not None and previous.enabled:
                config.agents.profiles[record.agent_id] = previous.model_copy(
                    update={"enabled": False},
                )
                changed = True
            continue
        workspace_root = (
            Path(sealed_root)
            / "releases"
            / record.agent_id
            / active.release_id
            / "agent"
        )
        try:
            validate_standard_workspace(record.agent_id, workspace_root)
        except StandardWorkspaceError as exc:
            unavailable.append(record.agent_id)
            previous = config.agents.profiles.get(record.agent_id)
            disabled = AgentProfileRef(
                id=record.agent_id,
                workspace_dir=str(workspace_root),
                enabled=False,
            )
            if previous != disabled:
                config.agents.profiles[record.agent_id] = disabled
                changed = True
            _persist_standard_validation(registry, record, active, exc.error_code)
            continue
        previous = config.agents.profiles.get(record.agent_id)
        desired = (
            previous.model_copy(update={
                "id": record.agent_id,
                "workspace_dir": str(workspace_root),
                "enabled": True,
            })
            if previous is not None
            else AgentProfileRef(
                id=record.agent_id,
                workspace_dir=str(workspace_root),
                enabled=True,
            )
        )
        if config.agents.profiles.get(record.agent_id) != desired:
            config.agents.profiles[record.agent_id] = desired
            changed = True
        reconciled.append(record.agent_id)
        _persist_standard_validation(registry, record, active, None)
    return WorkspaceReconciliationResult(
        tuple(reconciled), tuple(unavailable), changed
    )
```

`_persist_standard_validation` must update only the active release’s `runtime_validation`, always record `adapter="standard"`, `contract_version="1"`, and avoid a registry write when the existing record is semantically identical except `validated_at`. Reconciliation must not call `save_config` itself; `_app.py` saves exactly once only when `config_changed` is true.

Wire startup as:

```python
config = load_config(get_config_path())
result = reconcile_active_sealed_profiles(
    config,
    get_sealed_agent_registry(),
    Path(WORKING_DIR) / "sealed_agents",
)
if result.config_changed:
    save_config(config, get_config_path())
if result.unavailable:
    logger.error("Unavailable sealed workspaces: %s", result.unavailable)
await multi_agent_manager.start_all_configured_agents()
```

This block must be wrapped so a registry read/reconciliation exception is logged and ordinary startup continues with the pre-existing config.

- [ ] **Step 4: Run reconciliation and startup-adjacent tests**

```bash
.venv/bin/pytest -q \
  tests/unit/app/sealed_agents/test_workspace_reconciliation.py \
  tests/unit/app/test_sealed_agent_admin.py \
  tests/unit/workspace
```

Expected: PASS; empty Registry leaves ordinary profiles byte-for-byte equivalent in the Pydantic dump.

- [ ] **Step 5: Commit reconciliation**

```bash
git add \
  src/qwenpaw/app/sealed_agents/workspace_reconciliation.py \
  src/qwenpaw/app/_app.py \
  tests/unit/app/sealed_agents/test_workspace_reconciliation.py
git commit -m "feat: reconcile sealed releases into standard workspaces"
```

### Task 3: 删除 Runner 中全部密封在线执行分支

**Files:**
- Modify: `src/qwenpaw/app/runner/runner.py`
- Delete: `tests/unit/app/runner/test_sealed_entrypoint_isolation.py`
- Create: `tests/unit/app/runner/test_unified_agent_runtime.py`
- Create: `tests/integration/test_sealed_standard_runtime_parity.py`

**Interfaces:**
- Consumes: existing `MultiAgentManager` workspace selection; no sealed interface.
- Preserves: `AgentRunner.query_handler(msgs, request, **kwargs)` and its yielded `(Msg, last)` stream.
- Removes: `_sealed_model_execution_messages` and all query-time calls/imports involving Registry, pinned release, Runtime Adapter, `SealedAdapterRequest`, output guard, diagnostics authorization, and `sealed_sessions`.

- [ ] **Step 1: Add source-boundary and command-parity tests**

Create:

```python
import inspect

from qwenpaw.app.runner import runner


def test_query_handler_has_one_execution_path_for_every_agent():
    source = inspect.getsource(runner.AgentRunner.query_handler)
    for forbidden in (
        "get_sealed_agent_registry",
        "resolve_pinned_runtime",
        "resolve_pinned_release",
        "get_runtime_adapter",
        "SealedAdapterRequest",
        "sealed_sessions",
        "sanitize_message",
        "build_release_output_policy",
    ):
        assert forbidden not in source


def test_runner_module_has_no_sealed_message_injection_helper():
    assert not hasattr(runner, "_sealed_model_execution_messages")
```

These source-boundary assertions are deliberate negative tests: if anyone later reintroduces a Registry lookup, sealed command exception, adapter, output guard or session root into `query_handler`, the test fails before a production deployment.

Create a service-graph parity test proving both workspace types instantiate the same ordinary components:

```python
from qwenpaw.app.runner.runner import AgentRunner
from qwenpaw.app.workspace.workspace import Workspace


def test_standard_and_sealed_workspaces_use_identical_service_graph(tmp_path):
    ordinary = Workspace("ordinary", str(tmp_path / "ordinary"))
    sealed = Workspace("sealed", str(tmp_path / "sealed-release" / "agent"))
    assert type(ordinary.runner) is AgentRunner
    assert type(sealed.runner) is AgentRunner
    assert set(ordinary._service_manager.descriptors) == set(
        sealed._service_manager.descriptors
    )
    assert set(ordinary._service_manager.services) == set(
        sealed._service_manager.services
    )
```

If `ServiceManager` exposes descriptors through a differently named read-only mapping, use that existing public/read-only property in both assertions; do not add a密封-specific inspection API.

- [ ] **Step 2: Verify tests fail on current Runner**

```bash
.venv/bin/pytest -q \
  tests/unit/app/runner/test_unified_agent_runtime.py \
  tests/integration/test_sealed_standard_runtime_parity.py
```

Expected: FAIL listing the current sealed imports/branches and helper.

- [ ] **Step 3: Collapse Runner to the existing ordinary path**

Make these exact behavioral edits:

```python
query = _get_last_user_text(msgs)
session_id = getattr(request, "session_id", "") or ""

if query and _is_command(query):
    async for msg, last in run_command_path(request, msgs, self):
        yield msg, last
    return
```

Remove sealed snapshot resolution and trusted sealed diagnostics from request setup. Replace the whole adapter/output-guard block with the ordinary model stream:

```python
async for msg, last in _stream_printing_messages_interruptible(
    agents=[agent],
    coroutine_task=agent(msgs),
):
    yield msg, last
```

Keep mission execution, generic OpenAPI metadata normalization, error handling, billing hooks, context, tools, MCP, knowledge and session code unchanged. Do not add a new `if sealed` elsewhere.

- [ ] **Step 4: Run Runner and console regressions**

```bash
.venv/bin/pytest -q \
  tests/unit/app/runner \
  tests/integration/test_sealed_standard_runtime_parity.py \
  tests/integration/test_console_billing_flow.py
```

Expected: PASS; `rg` below prints no matches:

```bash
rg -n "get_sealed_agent_registry|resolve_pinned|get_runtime_adapter|SealedAdapterRequest|sealed_sessions|sanitize_message" \
  src/qwenpaw/app/runner/runner.py
```

- [ ] **Step 5: Commit Runner unification**

```bash
git add \
  src/qwenpaw/app/runner/runner.py \
  tests/unit/app/runner/test_unified_agent_runtime.py \
  tests/unit/app/runner/test_sealed_entrypoint_isolation.py \
  tests/integration/test_sealed_standard_runtime_parity.py
git commit -m "refactor: run sealed agents through the standard runner"
```

### Task 4: 让密封 OpenAPI 使用普通消息、SSE、错误和会话协议

**Files:**
- Modify: `src/qwenpaw/app/routers/open_api.py`
- Modify: `src/qwenpaw/app/open_api/runtime.py`
- Modify: `tests/unit/app/sealed_agents/test_open_api_sealed.py`
- Modify: `tests/unit/app/test_open_api_router.py`

**Interfaces:**
- Preserves: OpenAPI authentication, publication binding, external user/session mapping, task limiting, idempotency, billing and durable terminal events.
- Preserves: management availability check for a sealed target (`enabled` and active release required).
- Preserves: non-behavioral billing audit with `release_id`, `version`, and `content_digest`.
- Changes: `prepare_open_agent_chat(request, publication, payload) -> PreparedOpenRun` has no sealed runtime, diagnostics, or invocation parameters.
- Changes: `_streaming_response(...)` has no `sealed_target` parameter and yields tracker events unchanged.
- Produces: `_resolve_sealed_publication_release(publication: dict[str, Any]) -> SealedReleaseRecord | None`; it returns immediately for ordinary publications and reads the Registry only for server-authored `response_policy="sealed"` Agent publications.
- Removes: `resolve_pinned_runtime`, `_sanitize_sealed_stream_event`, `_sealed_failure_event`, diagnostics extraction/authorization and `SCOPE_DIAGNOSTICS_READ` from this route.

- [ ] **Step 1: Replace special-output tests with protocol-parity tests**

In `test_open_api_sealed.py`, add `import inspect`, keep the publication-management and unavailable-target tests, delete sanitizer/diagnostics assertions, and add:

```python
def test_open_api_route_has_no_sealed_execution_or_output_filter():
    source = inspect.getsource(open_api)
    for forbidden in (
        "resolve_pinned_runtime",
        "_sanitize_sealed_stream_event",
        "_sealed_failure_event",
        "_sealed_diagnostics_authorized",
        "sealed_agent_failed",
    ):
        assert forbidden not in source


def test_ordinary_publication_never_reads_sealed_registry(monkeypatch):
    monkeypatch.setattr(
        open_api,
        "get_sealed_agent_registry",
        lambda: pytest.fail("ordinary publication must not read sealed registry"),
    )
    publication = {
        "target_type": "agent",
        "target_id": "ordinary",
        "response_policy": "standard",
    }
    assert open_api._resolve_sealed_publication_release(publication) is None


```

In `test_open_api_router.py`, add:

```python
@pytest.mark.asyncio
async def test_standard_and_sealed_publications_prepare_same_native_shape():
    payload = OpenMessageRequest(
        external_user_id="ext-user",
        external_session_id="ext-session",
        message="hello",
        metadata={"topic": "same"},
    )
    standard_publication = _publication()
    standard_publication["response_policy"] = "standard"
    sealed_publication = _publication()
    sealed_publication["response_policy"] = "sealed"
    standard = await prepare_open_agent_chat(
        _request(workspace=_workspace(agent_id="agent-published")),
        standard_publication,
        payload,
    )
    sealed = await prepare_open_agent_chat(
        _request(workspace=_workspace(agent_id="agent-published")),
        sealed_publication,
        payload,
    )
    assert sealed.agent_id == standard.agent_id
    assert sealed.session_id == standard.session_id
    assert sealed.payload == standard.payload
```

In the same router test module, replace `test_prepare_sealed_open_agent_chat_sets_private_diagnostics_context` with:

```python
@pytest.mark.asyncio
async def test_prepare_open_agent_chat_treats_diagnostics_metadata_as_user_metadata():
    prepared = await prepare_open_agent_chat(
        _request(workspace=_workspace(agent_id="agent-published")),
        _publication(),
        OpenMessageRequest(
            external_user_id="ext-user",
            message="hello",
            metadata={"diagnostics_requested": True},
        ),
    )
    assert prepared.payload["meta"]["metadata"] == {
        "diagnostics_requested": True,
    }
    assert "sealed_runtime" not in prepared.payload["meta"]
    assert "_server_debug_endpoint_authorized" not in prepared.payload["meta"]
    assert "open_invocation_id" not in prepared.payload["meta"]
```

Add this complete stream passthrough unit to `test_open_api_sealed.py`:

```python
@pytest.mark.asyncio
async def test_openapi_stream_passes_native_tool_error_and_completion_events():
    events = [
        'data: {"type":"tool.call","name":"read_file"}\n\n',
        'data: {"type":"response.failed","error":"native_error"}\n\n',
        'data: {"type":"response.completed"}\n\n',
    ]

    class Tracker:
        def stream_from_queue(self, _queue, _run_key):
            async def generate():
                for event in events:
                    yield event
            return generate()

    prepared = SimpleNamespace(chat_id="chat-1", session_id="session-1")
    response = open_api._streaming_response(
        Tracker(),
        object(),
        "run-1",
        prepared,
        "invocation-1",
        "",
        {"billing_status": "completed"},
    )
    actual = [item async for item in response.body_iterator]
    assert actual == events
    assert "sealed_target" not in inspect.signature(
        open_api._streaming_response,
    ).parameters
```

This proves a密封 publication receives the same native tool, error and completion event shapes as the ordinary stream helper; no event becomes `sealed_agent_failed` and no tool event is dropped.

- [ ] **Step 2: Verify current special behavior fails parity**

```bash
.venv/bin/pytest -q \
  tests/unit/app/sealed_agents/test_open_api_sealed.py \
  tests/unit/app/test_open_api_router.py \
  tests/integration/test_open_api_billing_flow.py
```

Expected: FAIL because current code injects sealed runtime metadata and filters SSE.

- [ ] **Step 3: Remove OpenAPI runtime branching**

Implement the resolver exactly around the existing management policy:

```python
def _resolve_sealed_publication_release(
    publication: dict[str, Any],
) -> SealedReleaseRecord | None:
    if not (
        str(publication.get("target_type")) == "agent"
        and str(publication.get("response_policy")) == "sealed"
    ):
        return None
    record = get_sealed_agent_registry().get_agent(
        str(publication.get("target_id")),
    )
    if record is None or not record.enabled or record.active_release is None:
        raise HTTPException(
            status_code=503,
            detail="Sealed agent target is unavailable",
        )
    return record.active_release
```

Then in `post_open_message`:

- call this resolver once; ordinary publications return before any Registry access, while密封 publications get the active release for availability and audit only;
- build billing audit directly from the record:

```python
sealed_runtime_audit = (
    {
        "release_id": active_release.release_id,
        "version": active_release.version,
        "content_digest": active_release.content_digest,
    }
    if active_release is not None
    else None
)
```

- never resolve an adapter or pass audit data to the Agent request;
- call `prepare_open_agent_chat(request, publication, payload)` for every Agent;
- call `_streaming_response` identically for ordinary, sealed and expert-team targets;
- yield `initial_event` and tracker events directly, without `_public_stream_event`.

In `open_api/runtime.py`, remove sealed-only parameters and native metadata injection. Preserve server-bound `target_id`, owner `user_id`, external identifiers, publication, knowledge base and caller metadata exactly.

- [ ] **Step 4: Run OpenAPI, billing and authorization regressions**

```bash
.venv/bin/pytest -q \
  tests/unit/app/sealed_agents/test_open_api_sealed.py \
  tests/unit/app/test_open_api_router.py \
  tests/unit/app/test_open_api_admin.py \
  tests/unit/app/test_open_api_auth.py \
  tests/unit/app/billing/test_open_api_billing.py \
  tests/integration/test_open_api_billing_flow.py
```

Expected: PASS. `response_policy="sealed"` may remain stored for management compatibility but has no execution or serialization consumer.

- [ ] **Step 5: Commit OpenAPI unification**

```bash
git add \
  src/qwenpaw/app/routers/open_api.py \
  src/qwenpaw/app/open_api/runtime.py \
  tests/unit/app/sealed_agents/test_open_api_sealed.py \
  tests/unit/app/test_open_api_router.py
git commit -m "refactor: unify sealed and standard openapi execution"
```

### Task 5: 收紧激活原子性并保持密封管理边界

**Files:**
- Modify: `src/qwenpaw/app/routers/sealed_agents.py`
- Modify: `tests/unit/app/test_sealed_agent_admin.py`
- Modify: `tests/unit/app/sealed_agents/test_route_guards.py`

**Interfaces:**
- Consumes: Task 1 standard validation and Task 2 profile layout.
- Preserves: activate/enable/disable endpoints and `_operational_dto` public schema.
- Guarantees: config profile is switched before candidate preload/reload; any preload/reload/registry activation failure restores the prior profile and prior loaded workspace where available.
- Availability: a release is `available` only when enabled, active, and its latest `runtime_validation` is valid with `adapter="standard"`.

- [ ] **Step 1: Add rollback and management-boundary tests**

Add exact admin cases (imports use the existing `router_module`, `SimpleNamespace`, `Config`, `AgentProfileRef`, `RuntimeValidationRecord`, `SealedAgentRecord`, and `SealedReleaseRecord` fixtures in this module):

```python
def _valid_standard_validation():
    return RuntimeValidationRecord(
        status="valid",
        adapter="standard",
        contract_version="1",
    )


def _record():
    release = SealedReleaseRecord(
        release_id="rel-1",
        version="1.0.0",
        content_digest="sha256:" + "a" * 64,
        signer_id="publisher",
        runtime_validation=_valid_standard_validation(),
        state="active",
    )
    return SealedAgentRecord(
        agent_id="luyu",
        name="陆羽",
        description="茶文化专家",
        active_release_id="rel-1",
        releases=[release],
    )


@pytest.mark.asyncio
async def test_activation_failure_restores_previous_profile_and_runtime(monkeypatch, tmp_path):
    previous = AgentProfileRef(
        id="luyu",
        workspace_dir=str(tmp_path / "previous"),
        enabled=True,
    )
    config = Config()
    config.agents.profiles["luyu"] = previous
    candidate_root = tmp_path / "releases" / "luyu" / "rel-2"
    (candidate_root / "agent").mkdir(parents=True)
    (candidate_root / "agent" / "agent.json").write_text(
        '{"id":"luyu","name":"陆羽"}',
        encoding="utf-8",
    )

    class Service:
        async def validate_release_runtime(self, agent_id, release_id):
            return RuntimeValidationRecord(
                status="valid",
                adapter="standard",
                contract_version="1",
            )

        def release_root(self, agent_id, release_id):
            return candidate_root

        def activate(self, agent_id, release_id):
            pytest.fail("registry must not switch after reload failure")

    class Manager:
        def __init__(self):
            self.reload_calls = []

        def is_agent_loaded(self, agent_id):
            return True

        async def reload_agent(self, agent_id):
            self.reload_calls.append(agent_id)
            if len(self.reload_calls) == 1:
                raise RuntimeError("candidate start failed")
            return True

    manager = Manager()
    monkeypatch.setattr(
        router_module,
        "get_sealed_agent_service",
        lambda: Service(),
    )
    monkeypatch.setattr(router_module, "load_config", lambda: config)
    monkeypatch.setattr(router_module, "save_config", lambda _value: None)
    request = SimpleNamespace(
        state=SimpleNamespace(role="admin", user_id="1"),
        app=SimpleNamespace(
            state=SimpleNamespace(multi_agent_manager=manager),
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        await router_module.activate_sealed_agent_release(
            "luyu",
            "rel-2",
            request,
        )
    assert exc_info.value.status_code == 400
    assert config.agents.profiles["luyu"] == previous
    assert manager.reload_calls == ["luyu", "luyu"]


def test_invalid_standard_workspace_is_reported_unavailable_without_paths():
    validation = RuntimeValidationRecord(
        status="invalid",
        adapter="standard",
        contract_version="1",
        error_code="agent_config_invalid",
    )
    release = SealedReleaseRecord(
        release_id="rel-1",
        version="1.0.0",
        content_digest="sha256:" + "a" * 64,
        signer_id="publisher",
        runtime_validation=validation,
        state="active",
    )
    record = SealedAgentRecord(
        agent_id="luyu",
        name="陆羽",
        active_release_id=release.release_id,
        releases=[release],
    )
    dto = router_module._operational_dto(record)
    assert dto["availability"] == "unavailable"
    assert "/" not in str(dto["runtime_validation"]["error_code"])
```

Keep and rerun assertions that no GET download/content/files/package route exists and no workspace/source path appears in DTOs.

- [ ] **Step 2: Verify rollback test fails before implementation**

```bash
.venv/bin/pytest -q \
  tests/unit/app/test_sealed_agent_admin.py \
  tests/unit/app/sealed_agents/test_route_guards.py
```

Expected: the new availability or rollback assertion fails.

- [ ] **Step 3: Implement one atomic activation owner**

Keep `MultiAgentManager` as the only runtime owner. The router sequence must be:

1. validate candidate as standard workspace;
2. snapshot previous `AgentProfileRef`;
3. save candidate `AgentProfileRef` pointing to `release_root/agent`;
4. `reload_agent` if already loaded, otherwise `preload_agent`;
5. only after load success call `service.activate` to switch Registry state;
6. on any exception restore config; reload previous workspace if it existed; stop the candidate if there was no previous profile;
7. return only stable public errors, never a filesystem path.

Update `_operational_dto` availability to check standard runtime validation, while continuing to display historical adapter fields under `releases[].runtime` for audit only.

- [ ] **Step 4: Run all sealed management and package tests**

```bash
.venv/bin/pytest -q \
  tests/unit/app/sealed_agents \
  tests/unit/app/test_sealed_agent_admin.py \
  tests/unit/app/test_private_skill_access.py \
  tests/unit/app/test_backup_endpoint_policy.py
```

Expected: PASS; signature, digest, version downgrade, route guards and management DTO tests remain intact.

- [ ] **Step 5: Commit activation hardening**

```bash
git add \
  src/qwenpaw/app/routers/sealed_agents.py \
  tests/unit/app/test_sealed_agent_admin.py \
  tests/unit/app/sealed_agents/test_route_guards.py
git commit -m "fix: keep sealed activation atomic on standard workspaces"
```

### Task 6: 删除生产镜像的废弃密封执行依赖并做陆羽部署前验收

**Files:**
- Modify: `deploy/Dockerfile`
- Modify: `deploy/production/compose.production.yml`
- Modify: `tests/unit/release/test_dockerfile_dependencies.py`
- Modify: `tests/unit/release/test_production_compose.py`
- Create: `scripts/validate_standard_agent_workspace.py`
- Create: `tests/unit/scripts/test_validate_standard_agent_workspace.py`

**Interfaces:**
- Consumes: `validate_standard_workspace` from Task 1.
- Produces CLI: `python scripts/validate_standard_agent_workspace.py <workspace-path> --agent-id <agent-id>`; exit 0 prints one JSON object with `status`, `agent_id`, and `workspace`, exit 1 prints one JSON object with `status="invalid"` and stable `error_code`.
- Removes production use of `QWENPAW_SEALED_ENTRYPOINT_EXECUTION_MODE` and `bubblewrap`; legacy protocol modules may remain in source for historical tests but are unreachable online.

- [ ] **Step 1: Write failing deployment and CLI tests**

Change release tests to assert:

```python
def test_runtime_image_has_no_sealed_entrypoint_mode_or_bubblewrap():
    dockerfile = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    assert "QWENPAW_SEALED_ENTRYPOINT_EXECUTION_MODE" not in dockerfile
    assert "bubblewrap" not in dockerfile


def test_production_compose_has_no_sealed_runtime_override():
    app = _compose()["services"]["dclaw"]
    assert "environment" not in app or (
        "QWENPAW_SEALED_ENTRYPOINT_EXECUTION_MODE"
        not in app["environment"]
    )
```

CLI test:

```python
def test_cli_validates_realistic_standard_workspace(tmp_path):
    workspace = tmp_path / "agent"
    workspace.mkdir()
    (workspace / "agent.json").write_text(
        '{"id":"luyu_traffic_operator","name":"陆羽"}',
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate_standard_agent_workspace.py",
            str(workspace),
            "--agent-id",
            "luyu_traffic_operator",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "valid"
```

- [ ] **Step 2: Confirm tests fail on current production configuration**

```bash
.venv/bin/pytest -q \
  tests/unit/release/test_dockerfile_dependencies.py \
  tests/unit/release/test_production_compose.py \
  tests/unit/scripts/test_validate_standard_agent_workspace.py
```

Expected: current trusted-direct env and bubblewrap assertions fail, and the CLI is missing.

- [ ] **Step 3: Implement the validator CLI and remove dead runtime dependencies**

Create the CLI with this implementation shape; it calls the Task 1 validator, resolves the supplied path, emits JSON only, and never modifies the workspace:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from qwenpaw.app.sealed_agents.standard_workspace import (
    StandardWorkspaceError,
    validate_standard_workspace,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--agent-id", required=True)
    args = parser.parse_args()
    workspace = args.workspace.expanduser().resolve()
    try:
        validate_standard_workspace(args.agent_id, workspace)
    except StandardWorkspaceError as exc:
        print(json.dumps({
            "status": "invalid",
            "agent_id": args.agent_id,
            "error_code": exc.error_code,
        }, ensure_ascii=False, separators=(",", ":")))
        return 1
    print(json.dumps({
        "status": "valid",
        "agent_id": args.agent_id,
        "workspace": str(workspace),
    }, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Remove only the sealed-entrypoint environment line and `bubblewrap` package; preserve Chromium, LibreOffice and all ordinary Agent dependencies.

- [ ] **Step 4: Validate the actual local陆羽 2.1.0 workspace**

Run:

```bash
.venv/bin/python scripts/validate_standard_agent_workspace.py \
  '/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent' \
  --agent-id luyu_traffic_operator
```

Expected JSON:

```json
{"status":"valid","agent_id":"luyu_traffic_operator","workspace":"/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent"}
```

Then verify the recorded release digest file exactly:

```bash
grep -Fx \
  '01d4561a0493566145528580350dc7954538819040f15f97fe28c66670eca7a6  luyu-traffic-operator-agent-2.1.0-sealed.zip' \
  '/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent/outputs/releases/luyu-traffic-operator-agent-2.1.0-sealed.zip.sha256'
```

If the actual ZIP is restored locally, additionally run `shasum -a 256 -c` from its release directory. Absence of the ZIP is recorded as an artifact-availability gap; it does not permit production deployment until either the exact ZIP or the active production release directory is checked with the same validator.

- [ ] **Step 5: Run focused tests and commit**

```bash
.venv/bin/pytest -q \
  tests/unit/release/test_dockerfile_dependencies.py \
  tests/unit/release/test_production_compose.py \
  tests/unit/scripts/test_validate_standard_agent_workspace.py
git add \
  deploy/Dockerfile \
  deploy/production/compose.production.yml \
  tests/unit/release/test_dockerfile_dependencies.py \
  tests/unit/release/test_production_compose.py \
  scripts/validate_standard_agent_workspace.py \
  tests/unit/scripts/test_validate_standard_agent_workspace.py
git commit -m "chore: remove obsolete sealed runtime dependencies"
```

### Task 7: 全量验证、范围审查、单提交合入和一次部署说明

**Files:**
- Modify only if verification finds an in-scope defect: files already listed in Tasks 1–6.
- Do not stage pre-existing changes in `src/qwenpaw/app/routers/agents.py`, `src/qwenpaw/app/routers/providers.py`, `src/qwenpaw/config/config.py`, `tests/unit/routers/test_providers.py`, `tests/unit/workspace/test_agent_model.py`, `outputs/`, billing backfill files, or any unrelated untracked file.

**Interfaces:**
- Produces one reviewed feature commit on `main` containing only this implementation and its docs.
- Produces one deployment instruction after all local gates pass.

- [ ] **Step 1: Prove online code cannot reach a密封 executor**

```bash
rg -n \
  "SealedEntrypointProcess|HarnessProcess|get_runtime_adapter|resolve_pinned_runtime|resolve_pinned_release|sealed_sessions|sealed_agent_failed|_sanitize_sealed_stream_event|_sealed_model_execution_messages" \
  src/qwenpaw/app/runner/runner.py \
  src/qwenpaw/app/routers/open_api.py \
  src/qwenpaw/app/open_api/runtime.py \
  src/qwenpaw/app/routers/sealed_agents.py \
  src/qwenpaw/app/sealed_agents/service.py
```

Expected: no matches. Historical protocol modules outside this online set may still contain their own symbols.

- [ ] **Step 2: Run the complete targeted suite**

```bash
.venv/bin/pytest -q \
  tests/unit/app/sealed_agents \
  tests/unit/app/runner \
  tests/unit/app/test_sealed_agent_admin.py \
  tests/unit/app/test_open_api_router.py \
  tests/unit/app/test_open_api_admin.py \
  tests/unit/app/test_open_api_auth.py \
  tests/unit/app/billing/test_open_api_billing.py \
  tests/unit/release/test_dockerfile_dependencies.py \
  tests/unit/release/test_production_compose.py \
  tests/unit/scripts/test_validate_standard_agent_workspace.py \
  tests/integration/test_console_billing_flow.py \
  tests/integration/test_open_api_billing_flow.py
```

Expected: all PASS, no skipped new parity or denial test.

- [ ] **Step 3: Run ordinary-Agent regression independently**

```bash
.venv/bin/pytest -q \
  tests/unit/workspace \
  tests/unit/routers \
  tests/unit/agents \
  tests/unit/app/test_agents_ordering.py \
  tests/unit/app/test_agent_package_import.py
```

Expected: all PASS. A failure in a pre-existing dirty file must be separated from this feature using `git diff -- <path>` and must not be silently included.

- [ ] **Step 4: Review exact scope and squash to one feature commit**

```bash
git status --short
git diff --stat ac76c1e...
git diff --name-only ac76c1e...
git log --oneline ac76c1e..HEAD
```

Confirm every changed file is listed in Tasks 1–6. In the isolated execution branch, squash Task commits into exactly one implementation commit on top of `ac76c1e`:

```bash
git reset --soft ac76c1e
git commit -m "refactor: unify sealed agents on standard runtime"
```

Do not run the reset in a dirty shared checkout; execution must use the worktree created for this plan. Merge or fast-forward the resulting single commit to `main` only after reviewing `git show --stat --oneline HEAD`.

- [ ] **Step 5: Run post-squash verification and inspect diff**

Repeat Steps 1–3, then run:

```bash
git diff ac76c1e..HEAD --check
git show --stat --oneline HEAD
```

Expected: no whitespace errors, exactly one implementation commit after the design commit, no unrelated files.

- [ ] **Step 6: Perform the one production deployment only after all gates pass**

Before build, validate the active production release workspace without changing it:

```bash
docker exec dclaw python -c '
import json
from pathlib import Path
from qwenpaw.config.config import AgentProfileConfig
p = Path("/app/working/sealed_agents/releases/luyu_traffic_operator/a17d9b47f099427e8364bd6ffbd33cc9/agent")
profile = AgentProfileConfig.model_validate_json((p / "agent.json").read_text(encoding="utf-8"))
assert profile.id == "luyu_traffic_operator"
print(json.dumps({"status": "valid", "agent_id": profile.id, "workspace": str(p)}))
'
```

Expected: `status=valid`. Then perform the existing single build/deploy cycle. After deployment, create two new OpenAPI sessions and verify:

1. session A: “陆羽你好” → 业务/目标/现状 → 简化当天可发方案；
2. session B: fresh external session, confirms no state leakage;
3. both receive normal native SSE and successful billing terminal, never `sealed_agent_failed`;
4. logs show the ordinary Runner and active release identity, with no Worker/Harness/HostBridge startup;
5. one ordinary Agent OpenAPI smoke test returns the same protocol as before.

If any item fails, roll back the DClaw image through the existing image deployment mechanism; do not re-enable the deleted密封 runtime branch.
