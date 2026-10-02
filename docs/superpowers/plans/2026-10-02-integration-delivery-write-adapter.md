# DClaw Integration Delivery Write Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 AI 客服配置补丁服务增加一个窄范围、可校验、可恢复的 DClaw Agent 与经验库写入适配器，同时保持 DClaw 现有运行和管理机制不变。

**Architecture:** 所有新增能力都留在现有 `qwenpaw.app.integration_delivery` 模块中。适配器接收补丁服务提取出的 DClaw 子包，先验证 Agent 身份和当前摘要，再复用标准 Agent、密封 Agent、超级专家及经验库现有能力完成更新；每次更新保存一个有限期恢复收据。外部员工不直接调用这些接口，AI 客服补丁服务是唯一调用方。

**Tech Stack:** Python 3.10+、FastAPI、Pydantic v2、SQLite/文件存储、pytest、现有 DClaw Agent 与 Mindspace 服务。

**Spec:** `/Users/moxi/Desktop/codex space/agent create/worktool-bot-service/docs/config-patch-write-loop-design.zh-CN.md`

## Global Constraints

- 只在 `src/qwenpaw/app/integration_delivery/` 内增加写入适配逻辑；确需调用现有服务时通过公开 Python 接口复用，不改变原有路由语义。
- 只允许更新已存在、已启用、已经配置 OpenAPI、账户归属和专属经验库的 Agent；禁止首次安装。
- 请求路径 `agent_id`、包内 `agent/agent.json` ID 和当前目标 Agent ID 必须完全一致。
- 普通专家、密封 Agent 和超级专家使用同一集成接口；签名与封装对调用方透明。
- 标准 Agent 更新必须保留会话、日志、缓存、媒体及其他运行期目录。
- 所有写接口要求 `Idempotency-Key`，同键同请求返回原结果，同键不同请求返回冲突。
- 不修改 `dclaw-bot-server`，不增加 DClaw 环境版本固定机制，不改变共享 Agent 的既有语义。

## Review Focus

- 基线摘要或 Agent 绑定已变化：返回 `DCLAW_SOURCE_CHANGED`，不得写入任何文件或知识库。
- ZIP 包含路径穿越、链接、重复规范化路径或超限文件：返回 `DCLAW_DELIVERY_BUNDLE_INVALID`，不得产生恢复收据。
- Agent 已更新但知识库更新失败：必须恢复 Agent 和经验库旧状态，并返回失败而不是部分成功。
- 超级专家服务端签名材料未配置或与可信公钥不匹配：预检失败，现有 Active Release 保持不变。
- 相同幂等键重复提交：返回同一个 `operationId`；载荷摘要不同则返回 `IDEMPOTENCY_KEY_REUSED`。

---

### Task 1: 定义写入契约和只读验证器

**Files:**
- Create: `src/qwenpaw/app/integration_delivery/update.py`
- Modify: `src/qwenpaw/app/integration_delivery/models.py`
- Modify: `src/qwenpaw/app/integration_delivery/resources/dclaw-capability-catalog.v1.json`
- Test: `tests/unit/app/integration_delivery/test_update.py`

**Interfaces:**
- Consumes: 当前 `source-bundle` 中 `agent/`、`knowledge/`、`dclaw-component.json` 的格式。
- Produces: `parse_delivery_bundle(agent_id: str, archive: bytes) -> ParsedDeliveryBundle`、`validate_delivery_bundle(agent_id: str, archive: bytes, expected_agent_digest: str, expected_knowledge_digest: str) -> DeliveryValidation`。

- [ ] **Step 1: 写失败测试**

增加 `test_validate_delivery_bundle_is_read_only_and_returns_four_identifiers`、`test_validate_rejects_agent_id_mismatch`、`test_validate_rejects_unsafe_or_oversized_members`，断言验证不改变 Agent 目录和知识库。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/app/integration_delivery/test_update.py -q`

Expected: FAIL，因为 `update.py` 和新模型尚不存在。

- [ ] **Step 3: 实现最小契约**

在 `models.py` 增加 `DeliveryValidation`、`DeliveryOperationView`；在 `update.py` 实现安全解包、`agent.json` 身份检查、知识清单检查和确定性摘要，复用 `archive.py` 的限制与路径规则。

- [ ] **Step 4: 更新能力目录**

在 `platformCapabilities` 增加 `agent-delivery-validate`、`agent-delivery-update`、`knowledge-delivery-update`、`delivery-restore`，不修改现有 Profile 能力含义。

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/unit/app/integration_delivery/test_update.py tests/unit/app/integration_delivery/test_capabilities.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/qwenpaw/app/integration_delivery tests/unit/app/integration_delivery/test_update.py
git commit -m "feat: validate integration delivery bundles"
```

### Task 2: 实现标准 Agent 的原位安全更新和恢复

**Files:**
- Modify: `src/qwenpaw/app/integration_delivery/update.py`
- Test: `tests/unit/app/integration_delivery/test_update.py`

**Interfaces:**
- Consumes: Task 1 的 `ParsedDeliveryBundle`。
- Produces: `apply_standard_agent_source(bundle: ParsedDeliveryBundle, operation_id: str) -> AgentApplyReceipt`、`restore_standard_agent_source(receipt: AgentApplyReceipt) -> None`。

- [ ] **Step 1: 写失败测试**

增加 `test_standard_update_replaces_only_exported_source_files`、`test_standard_update_preserves_runtime_directories`、`test_standard_update_restores_old_source_after_reload_failure`。测试必须包含 `sessions_data`、日志和一个已删除源码文件。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/app/integration_delivery/test_update.py -q -k standard_update`

Expected: FAIL，因为标准 Agent 应用函数尚不存在。

- [ ] **Step 3: 实现安全目录交换**

根据当前导出器的“源码文件集合”构造临时目录：保留运行期路径，替换新源码，删除旧版本中已移除的源码；同文件系统执行目录交换。失败时恢复旧目录，并调用现有 Agent reload/preload 入口，不改 `agent_package_import.py` 的行为。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/app/integration_delivery/test_update.py -q -k standard_update`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/qwenpaw/app/integration_delivery/update.py tests/unit/app/integration_delivery/test_update.py
git commit -m "feat: apply standard agent delivery updates"
```

### Task 3: 联合更新经验库并保存恢复收据

**Files:**
- Modify: `src/qwenpaw/app/integration_delivery/update.py`
- Test: `tests/unit/app/integration_delivery/test_update.py`

**Interfaces:**
- Consumes: `publication_knowledge_service(publication)`、Task 2 的 Agent 应用与恢复函数。
- Produces: `IntegrationDeliveryUpdater.apply(...) -> DeliveryOperationView`、`IntegrationDeliveryUpdater.restore(agent_id: str, operation_id: str) -> DeliveryOperationView`。

- [ ] **Step 1: 写失败测试**

增加 `test_apply_replaces_agent_and_knowledge_as_one_operation`、`test_knowledge_failure_restores_agent_and_documents`、`test_restore_is_idempotent`、`test_operation_receipt_survives_service_restart`。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/app/integration_delivery/test_update.py -q -k 'knowledge or restore or receipt'`

Expected: FAIL，因为联合更新器尚不存在。

- [ ] **Step 3: 实现联合更新器**

在 `WORKING_DIR/integration_delivery/operations/` 保存 JSON 收据和发布前 DClaw 子包。先再次比较当前摘要，再应用 Agent 和经验库；任一步失败立即用发布前子包恢复。收据只保存对象路径和摘要，不保存服务密钥。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/app/integration_delivery/test_update.py -q -k 'knowledge or restore or receipt'`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/qwenpaw/app/integration_delivery/update.py tests/unit/app/integration_delivery/test_update.py
git commit -m "feat: coordinate agent knowledge delivery updates"
```

### Task 4: 复用密封 Agent 与超级专家发布机制

**Files:**
- Create: `src/qwenpaw/app/integration_delivery/sealed_update.py`
- Modify: `src/qwenpaw/app/integration_delivery/update.py`
- Test: `tests/unit/app/integration_delivery/test_sealed_update.py`

**Interfaces:**
- Consumes: 当前 Active Release 的 `manifest.json`、`build_signed_package_bytes(...)`、`SealedAgentService.install/validate_release_runtime/activate`。
- Produces: `apply_sealed_agent_source(bundle: ParsedDeliveryBundle, operation_id: str) -> AgentApplyReceipt`、`restore_sealed_agent_source(receipt: AgentApplyReceipt) -> None`。

- [ ] **Step 1: 写失败测试**

增加普通密封 Agent 与超级专家各一组测试，断言新包沿用当前能力声明、自动递增 patch 版本、使用平台签名、激活后可回退到旧 Release；再增加签名材料缺失和公钥不匹配测试。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/app/integration_delivery/test_sealed_update.py -q`

Expected: FAIL，因为密封更新适配器尚不存在。

- [ ] **Step 3: 实现平台侧透明封装**

从 `SECRET_DIR/integration_delivery_signer.json` 加载 `signerId` 和 base64 Ed25519 私钥；读取当前 Active Release manifest，仅替换源码、版本、内容摘要和签名，保留类型、能力与编排声明。通过现有 `SealedAgentService` 安装、验证和激活，不直接修改 registry。

- [ ] **Step 4: 实现回退**

恢复时重新激活收据记录的旧 Release，并通过现有 runtime reload 验证；不得删除历史 Release。

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/unit/app/integration_delivery/test_sealed_update.py tests/unit/app/sealed_agents/test_service.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/qwenpaw/app/integration_delivery/sealed_update.py src/qwenpaw/app/integration_delivery/update.py tests/unit/app/integration_delivery/test_sealed_update.py
git commit -m "feat: update sealed agents through delivery adapter"
```

### Task 5: 暴露窄内部接口和幂等语义

**Files:**
- Modify: `src/qwenpaw/app/integration_delivery/router.py`
- Modify: `src/qwenpaw/app/integration_delivery/models.py`
- Modify: `src/qwenpaw/app/integration_delivery/update.py`
- Test: `tests/unit/app/integration_delivery/test_update_routes.py`
- Test: `tests/unit/release/test_integration_delivery_boundary.py`

**Interfaces:**
- Consumes: Task 1～4 的验证、应用和恢复服务。
- Produces:
  - `POST /api/internal/integrations/v1/agents/{agent_id}/delivery-bundle/validate`
  - `PUT /api/internal/integrations/v1/agents/{agent_id}/delivery-bundle`
  - `GET /api/internal/integrations/v1/agents/{agent_id}/delivery-operations/{operation_id}`
  - `POST /api/internal/integrations/v1/agents/{agent_id}/delivery-operations/{operation_id}/restore`

- [ ] **Step 1: 写失败的路由契约测试**

断言集成认证必需、ZIP 使用原始请求体、更新要求 `Idempotency-Key` 和两个 `X-DClaw-Expected-*-Digest` 头、错误码稳定且日志不包含密钥或 ZIP 内容。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/app/integration_delivery/test_update_routes.py tests/unit/release/test_integration_delivery_boundary.py -q`

Expected: FAIL，因为写路由尚不存在。

- [ ] **Step 3: 实现路由与幂等检查**

验证接口只读；更新接口返回 `DeliveryOperationView`；相同幂等键和相同请求摘要复用原操作，不同摘要返回 HTTP 409 `IDEMPOTENCY_KEY_REUSED`；基线变化返回 HTTP 409 `DCLAW_SOURCE_CHANGED`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/app/integration_delivery tests/unit/release/test_integration_delivery_boundary.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/qwenpaw/app/integration_delivery tests/unit/app/integration_delivery tests/unit/release/test_integration_delivery_boundary.py
git commit -m "feat: expose integration delivery write routes"
```

### Task 6: 完整验证与 DClaw 运维说明

**Files:**
- Create: `docs/integration-delivery-write-api.zh-CN.md`
- Modify: `docs/operations/dclaw-container-release.md`
- Test: `tests/unit/app/integration_delivery/test_update_routes.py`

**Interfaces:**
- Consumes: Task 5 的最终内部接口。
- Produces: 可供 `worktool-bot-service` 对接的固定契约、签名密钥配置说明和回退命令。

- [ ] **Step 1: 写契约文档测试**

在边界测试中断言文档列出四个新接口、请求头、稳定错误码、普通/超级专家透明语义和共享 Agent 影响说明。

- [ ] **Step 2: 运行 DClaw 定向测试**

Run: `uv run pytest tests/unit/app/integration_delivery tests/unit/app/sealed_agents tests/unit/release/test_integration_delivery_boundary.py -q`

Expected: PASS。

- [ ] **Step 3: 运行格式与静态检查**

Run: `uv run pre-commit run --all-files`

Expected: PASS；若仓库当前存在与本任务无关的既有失败，只记录并改用对本任务文件的等价定向命令，不修改无关文件。

- [ ] **Step 4: 完成接口和发布说明**

记录密钥文件权限、DClaw 镜像构建、健康检查、旧镜像摘要和只恢复本次集成操作的方式，明确普通容器回退不自动覆盖业务数据。

- [ ] **Step 5: 提交**

```bash
git add docs/integration-delivery-write-api.zh-CN.md docs/operations/dclaw-container-release.md tests/unit/app/integration_delivery/test_update_routes.py
git commit -m "docs: publish integration delivery write contract"
```
