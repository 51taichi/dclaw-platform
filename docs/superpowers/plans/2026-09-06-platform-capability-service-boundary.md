# Platform Capability Service Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 AIGC 系统入口与超级专家能力入口接到同一套共享 Service，移除核心对开放层的反向依赖，并保留权限、旧工作流执行约束和可靠回传。

**Architecture:** 同进程共享 Service，不新增制作引擎或 HTTP 自调用。AIGC 核心持有资源和执行约束；开放层持有专家授权、会话/卡片绑定及业务回传。核心事件与开放层事件分别建模，以持久化回执和对账实现至少一次投递、幂等消费。

**Tech Stack:** Python >=3.10,<3.14，FastAPI，Pydantic，SQLAlchemy（现有 SQLite/Postgres 存储），pytest/pytest-asyncio，现有 JSON AIGC 资源存储和 RuntimeEventBus。

**Spec:** `docs/superpowers/specs/2026-09-06-platform-capability-service-boundary-design.md`（已确认）。

## Global Constraints

- 两套接口入口、一套核心业务实现、依赖方向单向。
- 两种入口均直接调用共享 Service，不通过 HTTP 回调本机页面接口，不复制业务实现。
- 不实现 MCP、RPA 新开放接口，不新增视频合成执行器，不另建通用工作流引擎，不拆分部署服务，不增加消息中间件。
- 不修改陆羽 S0–S4，不放宽阶段 Gate、真实素材审核、计费或资源隔离规则。
- 保持普通 Agent 路由和现有签名安装授权机制；“按授权开放”不改变既有签名包整包授权规则。
- 不在本轮架构重构中顺带改变单卡绑定为多卡共享画布；逐卡审核和素材版本依赖另行交付。
- 不运行生产数据迁移、不部署、不发布客户内容、不自动开始付费生成。代码与迁移工具验收使用隔离存储。
- 已有脏修改属于用户：禁止整体 checkout、stash、覆盖文件或把其他改动纳入本轮提交。

## 环境与基线

后端目录：`/Users/moxi/Desktop/codex space/dclaw-server`。

陆羽目录：`/Users/moxi/Desktop/codex space/agent create/agents/luyu-traffic-operator-agent`；本轮不编辑该目录生产文件。

已核对后端为普通 checkout，分支 `codex/super-expert-aigc-workflows`，不是 linked worktree。开始实现前按 using-git-worktrees 征询隔离选择；新 worktree 默认不会包含当前未提交代码，不能以旧 HEAD 冒充当前基线。若选择隔离，先明确需要迁入的相关差异并保留源目录；若选择原地，逐块修改和暂存，不整文件夹带他人差异。

2026-09-06 当前本地基线：

```bash
.venv/bin/python -m pytest tests/unit/routers/test_super_expert_platform.py tests/unit/app/test_super_expert_aigc_tasks.py tests/unit/app/super_experts/test_aigc_workflow_tasks.py tests/unit/aigc/test_workflow_compiler.py -q
```

结果：107 passed，9.19 秒；1 条已有 dashscope 弃用警告。这不是全部回归或真实 AIGC 验收。执行前重新记录 git diff 与基线，不沿用过期结果。

## 文件职责

现有 `routers/aigc_studio.py` 保留 HTTP 路由和暂未涉及的供应商执行实现；逐项转调 Service。现有 `routers/super_expert_platform.py` 保留对外路径并移出应用 Service。

新增文件限定为以下职责，禁止把大路由原样复制成第二个大文件：

- `app/aigc/models.py`：从路由移动共享 Canvas、Job、Asset、能力目录 DTO，不改变字段默认值；旧路由可单向 re-export 类型兼容调用方。
- `app/aigc/resource_store.py`：移动 AIGC JSON 路径、读取、原子替换和缓存逻辑；抛领域错误，不依赖 HTTP。
- `app/aigc/canvas_service.py`：画布 CRUD、受控工作流落盘及精确补偿；复用原编译器。
- `app/aigc/asset_service.py`：实际资产所有权、节点绑定及可读取来源解析；不发起专家审核。
- `app/aigc/capability_service.py`：移动已有模型能力目录/工作流目录投影，复用模型政策和已发布目录。
- `app/aigc/workflow_execution.py`：受信工作流执行约束与提交验证。
- `app/aigc/job_lifecycle.py`：生成结果持久化、节点输出投影和通用事件记录，不实现新供应商。
- `app/aigc/events.py`：通用事件 DTO、持久投递与对账。
- `app/storage/repos/aigc_execution_repo.py`：执行约束、操作记录、事件与消费回执；使用现有 SQLAlchemy Engine。
- `app/super_experts/service.py`：移动现有 `SuperExpertPlatformService`，通过显式构造参数接入核心 Service。
- `app/super_experts/aigc_adapter.py`：专家 scope/物理资源映射，保留现有签名/授权/版本规则。
- `app/super_experts/aigc_event_adapter.py`：核心事件映射到原专家/会话；不由核心反向调用。
- `scripts/migrate_aigc_execution_bindings.py`：受信离线迁移入口，默认 dry-run。

不得为了满足目录布局拆分无关计费、提示词或其他模块。已有 `app/aigc/__init__.py` 有未提交模型政策修改，保留，不批量重写。

## Task 1：建立行为保护并提取共享资源类型与存储

**Files:** Create `src/qwenpaw/app/aigc/models.py`, `src/qwenpaw/app/aigc/resource_store.py`, `tests/unit/app/aigc/test_resource_store.py`, `tests/unit/app/aigc/test_dependency_boundary.py`; modify `src/qwenpaw/app/routers/aigc_studio.py`。

**Interfaces:** `AigcResourceStore(root: Path)`；`read(kind: str, resource_id: str) -> dict[str, Any]`、`write(kind: str, resource_id: str, value: dict[str, Any]) -> None`、`delete(kind: str, resource_id: str) -> None`。移动原 SAFE_ID_RE 行为，错误类型 `AigcResourceError(code: str)`，字段 `.code`。Canvas/Job/Asset DTO 保持原 schema。

- [x] 保存本轮开始的工作区差异清单；不把既有测试失败记为新改造导致。
- [x] 在新测试文件写入首个 RED：

```python
def test_resource_store_survives_new_instance(tmp_path):
    from qwenpaw.app.aigc.resource_store import AigcResourceStore
    first = AigcResourceStore(tmp_path)
    first.write("canvases", "canvas-1", {"id": "canvas-1"})
    assert AigcResourceStore(tmp_path).read("canvases", "canvas-1") == {"id": "canvas-1"}
```

- [x] 运行 `.venv/bin/python -m pytest tests/unit/app/aigc/test_resource_store.py -q`，确认因模块尚不存在失败，而非环境缺依赖。
- [x] 移动原 DTO 和 `_safe_id/_json_path/_read_json/_write_json/_delete_json` 逻辑；缓存归属移动到 store，路由的 `STUDIO_ROOT` 只在 Service 工厂解析，以保持原测试路径隔离。原模型改为 import，不保留重复定义。
- [x] 增加路径穿越、损坏 JSON、写入中断保留旧文件、不同 root 缓存不串数据测试。依赖测试检查新增核心模块 AST 不导入 `routers`、`super_experts`、`workspace`，同时解析相对 import。现有反向调用先作为明确的现状特征断言，Task 4 才改为禁止，不添加永久 xfail。
- [x] 运行资源测试和 `tests/unit/routers/test_aigc_studio.py`；记录任何兼容性失败，修复类型迁移而非改预期绕过。
- [x] 单独提交本任务新差异；提交信息 `refactor(aigc): extract shared resource models and store`。

## Task 2：两种入口共用画布、资产与目录 Service

**Files:** Create `src/qwenpaw/app/aigc/canvas_service.py`, `asset_service.py`, `capability_service.py`, `tests/unit/app/aigc/test_shared_services.py`; modify both routers and affected import-only callers/tests。

**Interfaces:** `AigcCanvasService(store: AigcResourceStore)`；`create(owner_user_id: str, body: CanvasUpsert) -> Canvas`、`get(owner_user_id: str, canvas_id: str) -> Canvas`。`AigcAssetService(store)` 的 `resolve_owned(owner_user_id: str, asset_id: str) -> AigcAsset`。目录保留 `build_capability_list(manager)` 和 `project_workflow_capability_catalog(capabilities)` 原签名，仅改变所在模块。工作流创建由核心接收原 `CompiledWorkflow`，不接收专家安装对象。

- [x] 写 RED，验证新画布所有者来自服务端参数，调用方不能覆盖：

```python
def test_canvas_owner_is_not_taken_from_payload(tmp_path):
    from qwenpaw.app.aigc.models import CanvasUpsert
    from qwenpaw.app.aigc.resource_store import AigcResourceStore
    from qwenpaw.app.aigc.canvas_service import AigcCanvasService
    service = AigcCanvasService(AigcResourceStore(tmp_path))
    canvas = service.create("user-a", CanvasUpsert(meta={"owner_user_id": "user-b"}))
    assert canvas.meta["owner_user_id"] == "user-a"
```

- [x] 运行 `.venv/bin/python -m pytest tests/unit/app/aigc/test_shared_services.py -q`，确认 RED。
- [x] 移动画布与资产领域逻辑，保留系统入口既有管理员/历史无主资源访问政策，由可信入口提供访问上下文；专家入口禁止借用系统管理员兼容路径。两边不得另写一份 owner 判断。
- [x] 将 `provision_super_expert_*` 的专家 scope 解析留在适配层，实际 CanvasNode/Canvas 创建调用核心。兼容旧 meta 标识只由适配器映射；核心以通用 workflow/origin 关联保存，不解释陆羽状态。
- [x] 从路由移动能力目录构建及其依赖的纯参数辅助函数，不能保留一个核心函数再反向 import 路由。复用 `AigcModelPolicyService` 和现有发布目录筛选，不更改模型可用性政策。
- [x] 增加两入口共用 Service 的 spy 测试，以及跨用户画布/资产拒绝、实际模态来源保持、目录政策一致测试。
- [x] 运行 `.venv/bin/python -m pytest tests/unit/app/aigc/test_shared_services.py tests/unit/routers/test_aigc_studio.py tests/unit/routers/test_aigc_studio_provider_filter.py tests/unit/routers/test_aigc_model_policy.py tests/unit/routers/test_super_expert_platform.py -q`。
- [x] 提交 `refactor(aigc): share canvas asset and capability services`，保留原接口契约。

## Task 3：系统持有工作流约束与可恢复操作记录

**Files:** Create `src/qwenpaw/app/aigc/workflow_execution.py`, `src/qwenpaw/app/storage/repos/aigc_execution_repo.py`, `tests/unit/app/aigc/test_workflow_execution.py`; modify `src/qwenpaw/app/storage/schema.py`, canvas Service and platform adapter。

**Interfaces:** `WorkflowExecutionBinding` 为冻结 DTO，字段 owner_user_id、canvas_id、workflow_id、workflow_revision、node_id、logical_node_id、provider_id、model_id、capability。`AigcExecutionRepository(engine: Engine)` 提供 `register_bindings(bindings: list[WorkflowExecutionBinding], operation_id: str) -> None` 和 `get_binding(owner_user_id: str, canvas_id: str, node_id: str) -> WorkflowExecutionBinding | None`。

新增 schema 表 `aigc_workflow_execution_bindings`（owner/canvas/node 唯一，保存 workflow revision 与 provider/model/capability）、`aigc_operation_journal`（owner/operation_id 唯一，command_digest、resource_snapshot、phase）。沿用启动期 `create_all`；请求路径不执行 DDL。

- [x] 写 RED：先用测试 SQLAlchemy SQLite Engine 和 `schema.create_all(engine)` 创建隔离库，再注册一条绑定，重建 repository 后仍可读取；同操作同参数重放不写第二条，同操作不同参数抛冲突。

```python
def test_binding_requires_exact_model():
    from qwenpaw.app.aigc.workflow_execution import WorkflowExecutionBinding, validate_execution
    binding = WorkflowExecutionBinding(
        owner_user_id="u", canvas_id="c", workflow_id="w", workflow_revision=1,
        node_id="n", logical_node_id="clip", provider_id="p", model_id="m",
        capability="text_to_video",
    )
    import pytest
    with pytest.raises(ValueError, match="EXECUTION_BINDING_MISMATCH"):
        validate_execution(binding, provider_id="p", model_id="other", capability="text_to_video")
```

- [x] 运行 `.venv/bin/python -m pytest tests/unit/app/aigc/test_workflow_execution.py -q`，确认 RED。
- [x] 实现 `validate_execution(binding, *, provider_id: str, model_id: str, capability: str) -> None`。绑定来源仅受信创建/迁移；不接受画布 PUT 提供的“已验证”字段。原子注册一组节点，冲突整组回滚，不能部分通过。
- [x] 核心创建操作先固定资源 ID 与完整快照并记录 PREPARED，再落 JSON 资源及绑定，最后 APPLIED；重试读取同一操作快照。未 APPLIED 的受管节点不可执行。任何补偿只清理本操作新建且没有 Job/Asset 的资源。
- [x] 注入约束登记/JSON 写入/完成标记之间的失败，重试得到同一画布、不丢原资源。SQLite 与已配置的测试 Postgres 分别报告；没有测试 Postgres 时不宣称验证通过。
- [x] 运行本任务测试与既有 workflow compiler、platform router 测试。此时旧查询保持，尚未切换，提交 `feat(aigc): persist authoritative workflow execution bindings`。

## Task 4：迁移旧约束并消除核心反向调用

**Files:** Create `scripts/migrate_aigc_execution_bindings.py`, `src/qwenpaw/app/super_experts/binding_migration.py`, `tests/unit/app/super_experts/test_binding_migration.py`; modify system router, new workflow Service, Task 1 dependency test。

**Interfaces:** `migrate_bindings(*, legacy_root: Path, studio_root: Path, engine: Engine, apply: bool = False) -> dict[str, Any]` 位于 `binding_migration.py`。返回 scanned、eligible、migrated、unchanged、conflicts 列表/计数；冲突条目仅含资源 ID 和安全原因，无素材正文。CLI 必需 `--legacy-root`、`--studio-root`、`--database-url`，默认只读，显式 `--apply` 才写测试/批准目标。

- [x] 用既有 `tests/fixtures/super_expert/aigc-workflow-v2/three-node.json` 通过旧平台创建夹具，不手工伪造 PASS。写 RED 验证 dry-run 不产生核心绑定，apply 两次第二次 unchanged，画布/任务/资产 ID 不变。
- [x] 运行 `.venv/bin/python -m pytest tests/unit/app/super_experts/test_binding_migration.py -q`，确认 RED。
- [x] 实现迁移：检查旧 task 状态、实际所有者、物理/逻辑节点一一对应和同 revision 蓝图；冲突不得覆盖现有核心记录。迁移只调用 Task 3 受信登记 Service；核心不 import 迁移器。
- [x] `_authoritative_workflow_execution_binding` 改查核心记录。已登记约束即使客户端删掉 workflow 标识仍有效；受管画布缺少记录时拒绝生成并返回可诊断迁移错误，不信任可编辑 data 的模型参数。
- [x] 将依赖测试升级为严格禁止 `aigc_studio` 或核心模块依赖 `super_expert_platform`/专家仓库。新增 subprocess 禁止导入专家模块后调用核心 Service 的测试；应用路由总装不计为核心依赖。

```python
def test_core_source_has_no_platform_service_call():
    from pathlib import Path
    source = Path("src/qwenpaw/app/routers/aigc_studio.py").read_text()
    assert "get_super_expert_platform_service" not in source
```

- [x] 上述文本断言只作具体回归；同时运行 AST 相对 import 检查和动态阻断导入，防止改名绕过。
- [x] 运行 Task 3/4 测试、`tests/unit/routers/test_aigc_studio.py`、`tests/integration/test_super_expert_aigc_workflow.py`；验证模型篡改仍被拒绝。
- [x] 提交 `refactor(aigc): remove reverse dependency on expert platform`。不自动迁移线上，切换部署必须先有独立 dry-run 报告。

## Task 5：持久化核心结果与事件，隔离通知故障

**Files:** Create `src/qwenpaw/app/aigc/events.py`, `src/qwenpaw/app/aigc/job_lifecycle.py`, `tests/unit/app/aigc/test_job_lifecycle.py`; modify execution repository/schema and `_run_job_to_completion/_publish_job_event` wiring。

**Interfaces:** `AigcDomainEvent` 字段 event_id、schema_version=1、owner_user_id、resource_id、resource_version、event_type、operation_id、payload；event_type 闭集 job.succeeded/job.failed/asset.ready/resource.changed，不含专家身份。新增 `aigc_domain_events`、`aigc_event_deliveries`，后者按 event_id/consumer_id 唯一。`AigcJobLifecycle(store, repository)` 提供 `record_success(job: AigcJob, outputs: list[AigcAsset]) -> AigcJob`、`recover_projections() -> int`。

- [x] 在原 `_run_job_to_completion` 测试夹具中 monkeypatch `_execute_job` 返回已保存的测试素材、`_publish_job_event` 抛异常，断言最终 Job 为 succeeded；先运行看到失败，不能先改异常处理。
- [x] 记录第二个 RED：成功快照持久化后模拟进程退出，重建 Service 调用 recover_projections，不调用供应商，恢复 Job 和画布输出。
- [x] 实现成功结果快照、操作状态和领域事件在同一 SQL 事务记录；既有 Job/Canvas JSON 是可恢复投影。已有未迁入 Job 仍可读；不全量迁移历史 Job，也不新增另一份供模型直接修改的权威状态。
- [x] 缩小供应商执行的异常区间。投影/通知错误记录 delivery/projection_pending，不能把成功改失败。若供应商结果尚未持久化即崩溃，状态标记需对账，不盲目重新调用；复用现有 provider job ID 查询能力，不承诺外部 API 恰好执行一次。
- [x] 核心消费回执使用数据库唯一键和有限租约，进程重启可重领。最大单轮处理 100 条，失败退避 5/15/60 秒后封顶 300 秒，取消信号及时退出；不要用无限同步循环阻塞客户请求。
- [x] 原 RuntimeEventBus 用作 UI 通知通道，不作唯一持久记录。事件 payload 保留原 UI 所需字段，禁止泄露凭据及本地私有文件路径。
- [x] 运行 `.venv/bin/python -m pytest tests/unit/app/aigc/test_job_lifecycle.py tests/unit/routers/test_aigc_studio.py tests/unit/app/test_runtime_events_router.py -q`。
- [x] 提交 `fix(aigc): preserve successful results when event delivery fails`。

## Task 6：提取开放层 Service 与通用事件适配

**Files:** Create `src/qwenpaw/app/super_experts/service.py`, `aigc_adapter.py`, `aigc_event_adapter.py`, `tests/unit/app/super_experts/test_aigc_event_adapter.py`; modify platform router, `app/_app.py`, task/events repositories and import-only runtime callers。

**Interfaces:** 移动 `SuperExpertPlatformService` 保持 `execute`、`get_task`、`list_session_events` 对外签名；构造函数增加显式 AIGC Service 依赖，由应用层组装，不在 Service 内 import 路由。`AigcEventAdapter(platform_service, execution_repository)` 的 `async deliver_pending(limit: int = 100) -> int` 返回已确认消费数量。

- [x] 在既有集成测试中使用两个不同 agent_id/安装、两个原会话，创建各自任务。为其中一个实际 Job 产生核心事件，写 RED 验证仅目标会话收到状态更新。

```python
# 加入现有测试构造的 service/grant/task 夹具中，断言原绑定而非当前页面选中专家。
assert event.installation_id == task.binding.installation_id
assert event.conversation_id == task.binding.conversation_id
assert event.material_task_id == task.binding.material_task_id
```

- [x] 运行 `.venv/bin/python -m pytest tests/unit/app/super_experts/test_aigc_event_adapter.py -q`，确认 RED。
- [x] 将原路由 Service 移动为唯一实现；旧路径只单向 re-export 类型兼容，核心及新适配器不导入旧路由。清单与 scope/grant 不变，不新增可绕过授权的命令。
- [x] 核心事件按 owner/canvas/node/workflow revision 查开放层绑定。生成完成仅更新展示进度，不自动提交审核。客户提交继续沿现有 `aigc.asset.submit` 受信链路；审核完成仍用 `aigc.review.complete`，不制造陆羽 Gate PASS。
- [x] 消费状态区分 pending/delivered/blocked，撤销安装或资源版本失效时 blocked 并保存原因，不回传给其他专家、不通过换 conversation 强行投递。重复事件不重复触发审核，乱序版本不能回退卡片状态。
- [x] 应用启动层组装并启动可取消消费者；关闭专家组件时不启动适配器，但核心结果与查询仍正常。共享核心不能要求安装/会话才能记录事件。
- [x] 补取消、超时、消费者宕机、重复回调、并发跨用户和失效资产测试；同时断言调用失败未额外创建 Job 或收费记录。通知失败及恢复后实际 Job 文件、钱包、账单和执行表快照保持不变。
- [x] 运行 `.venv/bin/python -m pytest tests/unit/app/super_experts tests/unit/routers/test_super_expert_platform.py tests/unit/app/test_super_expert_grants.py tests/integration/test_super_expert_aigc_workflow.py -q`（纳入更广的相关回归）。
- [x] 提交 `refactor(platform): adapt AIGC services and durable events`：`f86b5ce`。既有认证兼容挂载单独提交为前置修复 `ade867e`，不夹带其他脏修改。

## Task 7：兼容验收与可审计交付

**Files:** Extend `tests/integration/test_super_expert_aigc_workflow.py`, `tests/integration/test_luyu_aigc_closed_loop.py`; create `tests/integration/test_aigc_core_without_experts.py`, `docs/superpowers/reports/2026-09-06-platform-capability-service-boundary-validation.md`; update `docs/super-expert-platform-v1.md` only for verified architecture。

- [x] 新增独立核心集成测试：阻断专家模块导入，调用系统 Service 创建普通画布，并验证已有受管工作流仍按核心记录拒绝错误模型。测试隔离存储，无外部生成；现有实现已满足，为增补验收而非 RED。
- [x] 运行 `.venv/bin/python -m pytest tests/integration/test_aigc_core_without_experts.py -q`；两个独立进程分别创建与重启读取，测试通过，未虚称 RED。
- [x] 原接口契约快照核对：现有卡片 URL、conversation route、guide、submit receipt 格式保持；重启后原画布可恢复。源码签名、既有路由和隔离状态测试验证；真实视频读取、真实业务审核及浏览器闭环仍未验收。
- [x] 完整相关回归命令：

最新现有目录回归 405 passed / 19.61 秒；排除其他脏修复的独立提交候选 373 passed / 20.08 秒，候选应用启动 2 passed / 42.92 秒。两种目录的测试数量不同来自原有未提交测试，不代表漏跑同一测试集。交付前如再修改生产代码仍需重跑。

```bash
.venv/bin/python -m pytest tests/unit/aigc tests/unit/app/aigc tests/unit/app/super_experts tests/unit/app/test_super_expert_aigc_tasks.py tests/unit/app/test_super_expert_grants.py tests/unit/routers/test_aigc_studio.py tests/unit/routers/test_aigc_studio_provider_filter.py tests/unit/routers/test_aigc_model_policy.py tests/unit/routers/test_super_expert_platform.py tests/integration/test_super_expert_aigc_workflow.py tests/integration/test_luyu_aigc_closed_loop.py tests/integration/test_aigc_core_without_experts.py -q
git diff --check
```

- [x] 记录测试环境、数量、失败/跳过原因；隔离真实模型审核与模拟生成结果分别列出。不运行真实付费生成或线上迁移来消除未完成标记。最初独立导出全仓 3824 passed / 25 skipped / 6 failed，六项均在改造前 `3225c52` 同环境复现；后续还原已有测试环境并仅纠正两处历史/配置夹具，现有目录最终全仓 **3888 passed / 25 skipped / 0 failed / 307.15 秒**。没有修改生产计费或授权。完整诊断及跳过原因见报告；不自动合并或部署。
- [x] 核对最终 diff：核心无专家反向调用、无复制 Service、无 S0–S4 编辑、无模型政策/计费业务变更。requesting-code-review 已对实际候选独立审查，重点复跑 58 passed，无新的 Critical/Important；S0–S4 未编辑不等于重新完成其运行时回归。
- [x] 交付当前结果、迁移 dry-run 命令和原会话验收入口；明确尚未部署。由后续发布步骤审核打包差异、备份/迁移报告和回滚兼容，不自动切换生产。详见验证报告顶部的本地结论及尚未验收边界。
- [x] 仅提交本轮测试与报告，`test(aigc): verify shared service boundaries and recovery`。不含原有未提交的业务修复；当前分支保留，不合并或推送。

## 检查点与执行方式

检查点 A：Task 1–2，共享实现与两入口行为保护。

检查点 B：Task 3–4，核心执行约束、旧数据迁移和反向依赖清除。

检查点 C：Task 5–7，可靠结果回传、独立运行与原链路兼容。

每个检查点报告真实测试结果和剩余项，不反复询问已确认的产品原则。遇到脏修改冲突、需改变授权/计费语义或生产迁移时才请求用户决策。

## 计划自检

- Spec 1/4/5 → Task 1、2、6；Spec 6 → Task 3、4；Spec 7 → Task 5、6；Spec 8/9 → Task 7。
- 核心资源、专家任务、Agent 状态的唯一写入者保持分开；不把普通 Job 成功编译为审核通过。
- plan 未要求所有未来模块使用画布、卡片或审核，也没有提前构建 MCP/RPA 接口。
- 计划中的新增类型和方法定义在对应任务 Interfaces；旧接口仅移动和重导出，必须保留现有字段及版本。
- 已按实际测试与提交更新 Task 1–7 的本地实现/验收。现有目录最终全仓 3888 passed、25 skipped、0 failed；原有业务修改保留且未夹带提交。真实生成、真实专家审核和线上闭环未验收，不以本地回归替代。保持当前分支和目录，不合并、推送、迁移或部署。
