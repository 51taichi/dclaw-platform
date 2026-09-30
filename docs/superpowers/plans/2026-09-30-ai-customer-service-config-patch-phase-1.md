# AI Customer Service Config Patch Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付第一阶段只读纵向链路：管理员可以管理员工 Codex Token，员工通过独立补丁服务查看全部 Bot、检查初始化状态，并下载由 DClaw Agent/经验库和 AI 客服状态机/标签组成的可信工作包；首次成功下载自动建立只读 `R1`。

**Architecture:** 在 `dclaw-server` 中增加两个彼此隔离的运行单元：DClaw 主应用只增加受服务密钥保护的只读参与者接口；新的 `config_patch_service` 包以独立 FastAPI 进程运行，独立保存员工 Token、审计和基线 Release，并通过 HTTP 聚合 DClaw 与 AI 客服中台。`dclaw-omnichannel-service` 只增加只读内部快照接口，以及现有管理员后台中的 Token 管理代理页；第一阶段不提供候选准备、上传、预检、激活或回退写接口。

**Tech Stack:** Python 3.10+、FastAPI、Pydantic v2、SQLite、httpx、pytest；Node.js 22+、Express、`node:sqlite`、`node:test`；确定性 ZIP 与 SHA-256/HMAC-SHA-256。

**Spec:** `docs/superpowers/specs/2026-09-30-ai-customer-service-config-patch-design.md`

## Global Constraints

- 执行时为 `dclaw-server` 和 `/Users/moxi/Desktop/codex space/agent create/dclaw-omnichannel-service` 分别使用隔离 worktree；保留当前仓库既有未跟踪目录 `outputs/`，不得纳入任何提交。
- 第一阶段所有上游参与者接口必须只读；不得调用现有 Agent 导入、经验库上传、状态机 PUT、标签 PUT、超级专家激活或任何线上配置写入口。
- 补丁服务是独立进程、独立 URL、独立数据库和独立服务凭据；不得复用 DClaw 用户 Session、AI 客服 Bot Session 或管理员 Session 作为员工身份。
- 员工 API 固定使用 `/staff/v1`；有效员工 Token 可查看全部 Bot，不增加 Workspace/Bot 权限表。
- Bot 是员工请求中唯一权威业务目标；DClaw URL、Agent ID、OpenAPI Publication ID、Knowledge Base ID、状态机和标签目标均由服务端解析，不能接受员工提交的目标覆盖值。
- 未初始化、禁用、未绑定、不能正常对话或缺少可编辑源码/Publication/积分归属/经验库的 Bot 必须返回 `ADMIN_BOOTSTRAP_REQUIRED` 及完整 `missingItems`，不得建立 Release。
- 普通专家和超级专家导出相同工作包树；超级专家只从受保护的已签名 Release 源载荷读取可编辑源码，不从 runtime workspace 反向生成，也不改变现有应用角色的不可查看/不可导出策略。
- 完整员工 Token 只在创建或轮换响应中出现一次；持久层只保存带服务端 Pepper 的 HMAC-SHA-256，Authorization、服务密钥、OpenAPI Key、客户渠道密钥和超级专家运行密钥不得写入日志或工作包。
- 所有 ZIP 条目必须采用规范化 POSIX 相对路径、固定时间戳和排序；拒绝符号链接、硬链接、设备文件、路径穿越、重复规范化路径以及超出大小/数量限制的文件。
- 首次成功导出只在补丁服务内建立 `R1`，不修改两个上游系统；并发首次导出只能产生一个 `R1`。
- 发现上游绕过补丁服务发生漂移时，员工旧基线不得继续使用；新的导出请求以稳定双读快照建立下一条 `external_baseline` Release，并返回新工作包。
- 保留所有现有 DClaw、AI 客服 API、管理员页面和运行语义；未配置补丁服务环境变量时，原系统继续正常启动和工作。

## Review Focus

- **同一 Agent 被多个 Bot 绑定：** Bot 列表保留每个 Bot，工作包按所选 Bot 生成，但流转配置/标签仍使用服务端解析出的共享 Agent 目标；Task 3 和 Task 5 添加绑定测试。
- **超级专家只有 runtime workspace、缺少受保护源 Release：** 返回 `ADMIN_BOOTSTRAP_REQUIRED` 的 `agent_source_snapshot` 缺失项，绝不导出 runtime 产物；Task 2 添加回归测试。
- **首次导出并发或任一上游在聚合中途变化：** 前者只产生一个 `R1`，后者返回 `TARGET_BINDING_CHANGED` 或可重试快照冲突且不写 Release；Task 6 添加并发和双读测试。
- **员工 Token 泄漏到日志或数据库：** 数据库和审计只出现 Token ID、前缀和摘要，日志捕获中不得出现明文或 Authorization；Task 4 添加持久层与日志测试。
- **源码目录含秘密文件、软链接或超限文件：** 导出必须拒绝整个 Bot，不可静默漏包后仍标记 ready；Task 2 添加 `.env`、私钥、软链接和限制测试。

---

### Task 1: DClaw 内部身份与初始化上下文

**Files (in `dclaw-server`):**
- Create: `src/qwenpaw/app/config_patch_participant/__init__.py`
- Create: `src/qwenpaw/app/config_patch_participant/auth.py`
- Create: `src/qwenpaw/app/config_patch_participant/models.py`
- Create: `src/qwenpaw/app/config_patch_participant/service.py`
- Create: `src/qwenpaw/app/config_patch_participant/router.py`
- Modify: `src/qwenpaw/app/auth.py`
- Modify: `src/qwenpaw/app/routers/__init__.py`
- Create: `tests/unit/app/config_patch_participant/test_auth.py`
- Create: `tests/unit/app/config_patch_participant/test_context.py`

**Interfaces:**
- Produces: `require_config_patch_service(request: Request) -> None`，使用 `X-DClaw-Config-Patch-Secret` 与 `DCLAW_CONFIG_PATCH_INTERNAL_SECRET` 做常量时间比较。
- Produces: `DclawConfigurationContextService.describe(agent_id: str) -> DclawConfigurationContext`。
- Produces: `GET /api/internal/config-patch/v1/agents/{agent_id}/context`，返回 Agent 类型/Profile、当前源版本、Publication、Knowledge Base、积分挂靠与结构化 readiness，不返回管理凭据。

- [ ] **Step 1: 编写内部鉴权失败测试**

覆盖未配置服务密钥时路由返回 503、缺失/错误密钥返回 401、正确密钥可访问；同时断言普通 Bearer、管理员 Bearer 和员工 Token 都不能替代内部密钥。检查 401/503 日志不包含请求头原文。

- [ ] **Step 2: 编写上下文解析失败测试**

用 fake repositories 固定覆盖：标准 Agent 完整就绪、超级专家 active Release 完整就绪、Agent 不存在、Agent 禁用、超级专家无 active Release、Publication 缺失/禁用、`target_id` 不匹配、`bound_user_id` 无钱包。断言每个失败都返回确定的 `missingItems`，而不是首个错误即停止。

- [ ] **Step 3: 运行测试确认 RED**

Run: `python -m pytest tests/unit/app/config_patch_participant/test_auth.py tests/unit/app/config_patch_participant/test_context.py -q`

Expected: FAIL，因为参与者包、路由和内部鉴权尚不存在。

- [ ] **Step 4: 实现内部鉴权和只读上下文服务**

仅将 `/api/internal/config-patch/` 加入 DClaw 登录中间件的公共前缀，再由更窄的 `require_config_patch_service` 强制服务密钥；不得把该前缀变成匿名可用。标准 Agent 从 `load_config/load_agent_config` 读取，超级专家从 `SealedAgentRegistry.active_release` 读取；Publication 通过 `OpenApiRepository.list_publications(enabled_only=False)` 按 `target_type=agent,target_id=agent_id` 唯一解析，积分就绪通过 Publication 的 `bound_user_id` 对应钱包判断。

- [ ] **Step 5: 运行测试确认 GREEN**

Run: `python -m pytest tests/unit/app/config_patch_participant/test_auth.py tests/unit/app/config_patch_participant/test_context.py tests/unit/app/test_open_api_admin.py tests/unit/app/test_sealed_agent_admin.py -q`

Expected: PASS；原管理接口的权限和超级专家不可导出断言保持不变。

- [ ] **Step 6: 提交 DClaw 上下文切片**

```bash
git add src/qwenpaw/app/auth.py src/qwenpaw/app/routers/__init__.py \
  src/qwenpaw/app/config_patch_participant tests/unit/app/config_patch_participant
git commit -m "feat: expose config patch readiness context"
```

### Task 2: DClaw 确定性源码与经验库快照

**Files (in `dclaw-server`):**
- Create: `src/qwenpaw/app/config_patch_participant/archive.py`
- Create: `src/qwenpaw/app/config_patch_participant/export.py`
- Modify: `src/qwenpaw/app/config_patch_participant/router.py`
- Create: `tests/unit/app/config_patch_participant/test_archive.py`
- Create: `tests/unit/app/config_patch_participant/test_export.py`

**Interfaces:**
- Produces: `build_deterministic_archive(files: Mapping[str, bytes], *, limits: ArchiveLimits) -> bytes`。
- Produces: `DclawSnapshotExporter.export(agent_id: str) -> ExportedDclawSnapshot`，其中包含 `archive: bytes`、`agent_id`、`profile_id`、`source_version`、`agent_digest`、`knowledge_digest`。
- Produces: `GET /api/internal/config-patch/v1/agents/{agent_id}/snapshot`，响应 ZIP，并以响应头返回组件摘要；只接受 Task 1 的内部服务身份。

- [ ] **Step 1: 编写归档安全与确定性测试**

断言相同规范化文件集合无论插入顺序如何都产生相同 SHA-256；固定 ZIP 时间戳、权限和 UTF-8 路径。分别测试绝对路径、`..`、反斜杠碰撞、Unicode 规范化碰撞、软/硬链接、设备文件、超过 4,096 文件、单文件 100 MiB 和总展开 400 MiB 被整体拒绝。

- [ ] **Step 2: 编写标准/超级专家导出测试**

标准 Agent 从配置指向的 workspace 读取；超级专家只从 `SealedAgentService.release_root(agent_id, active_release_id)/agent` 读取。两者都生成 `agent/` 和 `knowledge/` 前缀及 `dclaw-component.json`，且相同内容摘要稳定。断言超级专家 runtime workspace 即使存在也不会被读取；缺少源 Release 返回 `agent_source_snapshot` 缺失项。

- [ ] **Step 3: 编写秘密与经验库完整性测试**

在 Agent 源目录放置 `.env`、PEM 私钥、凭据命名文件和软链接，断言导出失败并报告安全缺失项，而不是静默省略；使用 fake `MindspaceService` 断言 Publication 专属经验库的文档原件、类别、标签和清单被导出，索引缓存、临时文件和其他用户经验库不进入 ZIP。

- [ ] **Step 4: 运行测试确认 RED**

Run: `python -m pytest tests/unit/app/config_patch_participant/test_archive.py tests/unit/app/config_patch_participant/test_export.py -q`

Expected: FAIL，因为安全归档器和快照导出器尚不存在。

- [ ] **Step 5: 实现最小只读导出器**

复用 Task 1 的权威 Publication/Knowledge Base 解析结果。普通与超级专家共享同一规范化文件枚举器；显式允许常规文件，拒绝任何链接或特殊文件。`dclaw-component.json` 只写安全元数据和摘要，不写 workspace 绝对路径、owner/bound user、Key 或服务密钥。

- [ ] **Step 6: 运行测试确认 GREEN**

Run: `python -m pytest tests/unit/app/config_patch_participant -q`

Expected: PASS，且现有 `test_router_has_no_package_or_content_download_route` 仍然通过，因为员工快照位于独立内部路由，不新增 sealed admin/user 下载路由。

- [ ] **Step 7: 提交 DClaw 快照切片**

```bash
git add src/qwenpaw/app/config_patch_participant \
  tests/unit/app/config_patch_participant
git commit -m "feat: export trusted dclaw configuration snapshots"
```

### Task 3: AI 客服中台只读 Bot 快照参与者

**Files (in `dclaw-omnichannel-service`):**
- Create: `src/config-patch-participant.js`
- Modify: `src/server.js`
- Create: `tests/config-patch-participant.test.js`
- Create: `tests/server-config-patch-participant-boundary.test.js`

**Interfaces:**
- Produces: `assertConfigPatchService(req) -> true`，验证 `X-Omnichannel-Config-Patch-Secret` 与 `OMNICHANNEL_CONFIG_PATCH_INTERNAL_SECRET`。
- Produces: `listConfigPatchBots() -> Array<ConfigPatchBotSummary>`。
- Produces: `getConfigPatchBotSnapshot(botId: string) -> ConfigPatchBotSnapshot | null`，只返回 Bot/Agent 绑定、启用状态、DClaw 定位元数据、状态机、标签和来源摘要，不返回 Agent API Key、渠道 Token、Webhook Secret 或访问 Key 哈希。
- Produces: `GET /internal/config-patch/v1/bots` 与 `GET /internal/config-patch/v1/bots/:botId/snapshot`。

- [ ] **Step 1: 编写领域快照测试**

使用临时 runtime data dir 建立两个 Bot 绑定，其中两个 Bot 可共享一个 Agent。断言列表保留两个 Bot；单 Bot 快照通过 `getBotBinding` 解析 Agent，通过 `getFlowMachineForBot` 和 `getAgentTagSchema` 读取共享配置，空状态机/标签使用明确的 canonical empty 值而非创建默认配置。

- [ ] **Step 2: 编写内部路由边界测试**

断言缺少/错误服务密钥返回 401、未配置密钥返回 503、正确密钥返回 200、未知 Bot 返回 404。序列化响应后断言不包含 `agentApiKey`、`accessKeyHash`、渠道凭据字段或其测试值；原 `/api/public/bots`、`/api/bots`、状态机和标签路由源码保持原状。

- [ ] **Step 3: 运行测试确认 RED**

Run from `dclaw-omnichannel-service`: `npm test -- tests/config-patch-participant.test.js tests/server-config-patch-participant-boundary.test.js`

Expected: FAIL，因为参与者模块和内部路由尚不存在。

- [ ] **Step 4: 实现只读参与者模块和路由**

readiness 至少包含 `bot_enabled`、`agent_bound`、`agent_enabled`、`dclaw_location_configured`、`flow_readable`、`tags_readable`；摘要使用字段排序后的 canonical JSON。路由不得调用 `upsertFlowMachine`、`upsertAgentTagSchema` 或 `defaultFlowMachineConfig`，也不得复用管理员/Bot Session。

- [ ] **Step 5: 运行测试确认 GREEN**

Run from `dclaw-omnichannel-service`: `npm test -- tests/config-patch-participant.test.js tests/server-config-patch-participant-boundary.test.js tests/server-workspace-boundary.test.js tests/admin-console-boundary.test.js`

Expected: PASS；原后台和 Bot/Workspace 隔离测试保持不变。

- [ ] **Step 6: 提交 AI 客服快照切片**

```bash
git add src/config-patch-participant.js src/server.js \
  tests/config-patch-participant.test.js \
  tests/server-config-patch-participant-boundary.test.js
git commit -m "feat: expose readonly bot configuration snapshots"
```

### Task 4: 独立补丁服务骨架、员工 Token 与审计

**Files (in `dclaw-server`):**
- Create: `src/config_patch_service/__init__.py`
- Create: `src/config_patch_service/settings.py`
- Create: `src/config_patch_service/db.py`
- Create: `src/config_patch_service/models.py`
- Create: `src/config_patch_service/tokens.py`
- Create: `src/config_patch_service/audit.py`
- Create: `src/config_patch_service/dependencies.py`
- Create: `src/config_patch_service/app.py`
- Create: `src/config_patch_service/routers/__init__.py`
- Create: `src/config_patch_service/routers/admin_tokens.py`
- Modify: `pyproject.toml`
- Create: `tests/unit/config_patch_service/conftest.py`
- Create: `tests/unit/config_patch_service/test_tokens.py`
- Create: `tests/unit/config_patch_service/test_admin_tokens.py`
- Create: `tests/unit/config_patch_service/test_staff_auth.py`

**Interfaces:**
- Produces: `ConfigPatchSettings.from_env() -> ConfigPatchSettings`，要求独立 data dir、Token Pepper、内部管理员密钥和两个上游服务密钥。
- Produces: `StaffTokenService.create(...) -> IssuedStaffToken`、`list() -> list[StaffTokenView]`、`revoke(token_id: str) -> StaffTokenView`、`rotate(token_id: str) -> IssuedStaffToken`、`authenticate(raw_token: str) -> AuthenticatedStaffToken`。
- Produces: 内部管理员接口 `POST/GET /internal/admin/v1/staff-tokens`、`POST /internal/admin/v1/staff-tokens/{tokenId}/revoke`、`POST /internal/admin/v1/staff-tokens/{tokenId}/rotate`。
- Produces: 员工 Bearer 依赖 `require_staff_token` 和 `GET /staff/v1/whoami`；Token 格式固定为 `dclaw_staff_<high-entropy-body>`。
- Produces: `GET /health`，只返回服务状态和版本，不读取或暴露任何 Token、上游地址及密钥。

- [ ] **Step 1: 编写 Token 生命周期与 schema 测试**

断言 schema 重复初始化安全；创建响应只出现一次完整 Token，数据库只保存 Token ID、HMAC、前缀/后四位和元数据；过期、撤销、轮换旧 Token 立即失效；成功鉴权更新 `last_used_at`，但最多按一分钟粒度写一次以避免每请求写放大。

- [ ] **Step 2: 编写管理员与员工鉴权测试**

内部管理员密钥缺失/错误、员工 Bearer 缺失/错误/过期/撤销分别返回稳定 401/503 机器码。断言员工 Token 不能调用内部管理员接口，内部管理员密钥不能调用员工 API。

- [ ] **Step 3: 编写审计与泄密回归测试**

捕获数据库、结构化审计和 Python 日志，覆盖创建、鉴权失败、鉴权成功、撤销和轮换；断言只记录 Token ID/员工/动作/结果，请求中的完整 Token、Authorization、Pepper 和内部管理员密钥在所有输出中均不存在。

- [ ] **Step 4: 运行测试确认 RED**

Run: `python -m pytest tests/unit/config_patch_service/test_tokens.py tests/unit/config_patch_service/test_admin_tokens.py tests/unit/config_patch_service/test_staff_auth.py -q`

Expected: FAIL，因为独立服务包和存储尚不存在。

- [ ] **Step 5: 实现独立应用和 Token 存储**

使用独立 SQLite WAL 数据库和显式事务；Token HMAC 使用 `hmac.new(pepper, raw_token, sha256)`，所有比较使用 `hmac.compare_digest`。`app.py` 只创建补丁服务路由，不导入或挂载 DClaw 主应用；在 `pyproject.toml` 增加 `dclaw-config-patch = "config_patch_service.app:main"` 启动入口，并将 coverage source 扩展为 `src/qwenpaw` 与 `src/config_patch_service`。

- [ ] **Step 6: 运行测试确认 GREEN**

Run: `python -m pytest tests/unit/config_patch_service/test_tokens.py tests/unit/config_patch_service/test_admin_tokens.py tests/unit/config_patch_service/test_staff_auth.py -q`

Expected: PASS；明文 Token 只存在于 create/rotate 的单次响应对象。

- [ ] **Step 7: 提交独立服务身份切片**

```bash
git add pyproject.toml src/config_patch_service \
  tests/unit/config_patch_service
git commit -m "feat: add config patch service token plane"
```

### Task 5: 上游客户端、全部 Bot 列表与配置上下文

**Files (in `dclaw-server`):**
- Create: `src/config_patch_service/upstreams/__init__.py`
- Create: `src/config_patch_service/upstreams/dclaw.py`
- Create: `src/config_patch_service/upstreams/omnichannel.py`
- Create: `src/config_patch_service/context.py`
- Create: `src/config_patch_service/capabilities.py`
- Create: `src/config_patch_service/resources/capability-catalog.v1.json`
- Create: `src/config_patch_service/routers/staff_bots.py`
- Modify: `src/config_patch_service/app.py`
- Create: `tests/unit/config_patch_service/test_upstream_clients.py`
- Create: `tests/unit/config_patch_service/test_bot_context.py`
- Create: `tests/unit/config_patch_service/test_capabilities.py`

**Interfaces:**
- Produces: `OmnichannelClient.list_bots() -> list[OmnichannelBotSnapshot]` 与 `get_bot_snapshot(bot_id: str) -> OmnichannelBotSnapshot`。
- Produces: `DclawClient.get_context(base_url: str, agent_id: str) -> DclawConfigurationContext` 与 `download_snapshot(base_url: str, agent_id: str) -> DclawSnapshotArchive`；`base_url` 只能来自 Omnichannel 内部快照。
- Produces: `ConfigurationContextService.list_bots() -> list[BotConfigurationTarget]` 与 `get(bot_id: str) -> BotConfigurationContext`。
- Produces: `GET /staff/v1/bots`、`GET /staff/v1/bots/{botId}/configuration-context` 和 `GET /staff/v1/capabilities`。

- [ ] **Step 1: 编写上游 HTTP 合约测试**

使用 `httpx.MockTransport` 断言准确路径、内部 Header、连接/读取超时、非 2xx 映射和响应 schema；确保响应体或异常中回显的上游秘密被清除。测试 Omnichannel 返回的 DClaw URL 才能进入 DClawClient，员工 query/body 中不存在 URL 参数。

- [ ] **Step 2: 编写全部 Bot 与共享 Agent 测试**

两个 Bot 共享一个 Agent 时列表仍返回两项；所有有效员工 Token 得到同一列表，不按 Workspace 过滤。配置上下文把 Omnichannel 与 DClaw readiness 合并成完整 `missingItems`，并返回普通/超级专家不同 `agentProfileId`、相同公开字段结构。

- [ ] **Step 3: 编写动态能力目录测试**

断言目录响应包含版本、模块职责矩阵、标准/超级专家 Profile、状态机/标签/经验库语义和能力申请契约；未知 Profile 或目录 schema 损坏时服务启动失败，不以 Demo 推断能力。

- [ ] **Step 4: 运行测试确认 RED**

Run: `python -m pytest tests/unit/config_patch_service/test_upstream_clients.py tests/unit/config_patch_service/test_bot_context.py tests/unit/config_patch_service/test_capabilities.py -q`

Expected: FAIL，因为客户端、聚合服务和员工 Bot 路由尚不存在。

- [ ] **Step 5: 实现只读客户端和上下文聚合**

为每个请求生成 correlation ID 并向两个上游传递；列表先取 Omnichannel Bot，再按 `(base_url, agent_id)` 去重并发读取 DClaw context，最终仍按 Bot 展开。上游不可用时对应 Bot 返回 `readiness=unavailable` 和稳定机器码，不让一次坏 Bot 隐藏其他 Bot。

- [ ] **Step 6: 运行测试确认 GREEN**

Run: `python -m pytest tests/unit/config_patch_service/test_upstream_clients.py tests/unit/config_patch_service/test_bot_context.py tests/unit/config_patch_service/test_capabilities.py -q`

Expected: PASS，且任意有效员工 Token 可见全部 Bot。

- [ ] **Step 7: 提交只读发现切片**

```bash
git add src/config_patch_service tests/unit/config_patch_service
git commit -m "feat: add staff bot discovery and capabilities"
```

### Task 6: 首次 R1、漂移基线与完整工作包导出

**Files (in `dclaw-server`):**
- Create: `src/config_patch_service/releases.py`
- Create: `src/config_patch_service/bundles.py`
- Create: `src/config_patch_service/resources/workspace/AGENTS.md`
- Create: `src/config_patch_service/resources/workspace/change-plan.yaml`
- Create: `src/config_patch_service/resources/workspace/platform/responsibility-matrix.md`
- Create: `src/config_patch_service/resources/workspace/platform/runtime-mechanism.md`
- Create: `src/config_patch_service/resources/workspace/platform/coordinated-change-patterns.md`
- Create: `src/config_patch_service/resources/workspace/platform/examples/cross-component-change.md`
- Create: `src/config_patch_service/routers/staff_bundles.py`
- Modify: `src/config_patch_service/db.py`
- Modify: `src/config_patch_service/app.py`
- Modify: `pyproject.toml`
- Create: `tests/unit/config_patch_service/test_releases.py`
- Create: `tests/unit/config_patch_service/test_bundles.py`
- Create: `tests/integration/test_config_patch_phase1.py`

**Interfaces:**
- Produces: `ReleaseRepository.create_or_get_baseline(snapshot: AggregatedSnapshot, *, actor_token_id: str, source: Literal["initial_baseline", "external_baseline"]) -> ConfigurationRelease`。
- Produces: `WorkspaceBundleBuilder.build(release: ConfigurationRelease) -> BuiltWorkspaceBundle`，返回确定性 ZIP、`bundle_digest` 和 manifest。
- Produces: `POST /staff/v1/bots/{botId}/workspace-bundles/export`，Bot 未就绪时返回 409 `ADMIN_BOOTSTRAP_REQUIRED`，成功时返回 ZIP 与 `X-DClaw-Release-Id`/`X-DClaw-Bundle-Digest`。

- [ ] **Step 1: 编写 Release 存储和并发测试**

断言就绪 Bot 第一次创建 `R1` 和四个组件摘要；相同稳定快照重复导出复用同一 Release；两个独立连接并发首次导出只留下一个 `R1`。不同快照建立 `external_baseline` 下一版本，旧 Release 保持不可变并记录漂移审计。

- [ ] **Step 2: 编写稳定双读与换绑测试**

模拟第一次 Omnichannel 读取为 Agent A、DClaw 下载完成后第二次读取变为 Agent B，断言返回 `TARGET_BINDING_CHANGED` 且数据库无 Release。分别模拟 DClaw context/source version 和 Omnichannel flow/tag 摘要在前后双读中变化，断言返回可重试冲突；两个系统的第二次读取都与已下载快照一致才允许提交基线。

- [ ] **Step 3: 编写工作包契约测试**

精确断言 ZIP 包含 `dclaw-manifest.json`、`AGENTS.md`、`change-plan.yaml`、`agent/`、`customer-service/flow-machine.json`、`customer-service/tag-schema.json`、`knowledge/knowledge-manifest.json`、`knowledge/documents/` 和 `platform/` 五类资料。manifest 固定 `schemaVersion=customer-service-workspace.v1`，Bot/Agent/Profile/Base Release/目录版本和四个来源指纹与 Release 一致。

- [ ] **Step 4: 编写普通/超级专家透明性和错误测试**

对内容等价的普通/超级专家快照断言目录树相同、只有 Profile/能力项不同，包内无 signer 私钥、运行密钥和绝对路径。未绑定、禁用、Publication/积分/经验库/源快照任一缺失时返回包含全部缺失项的 `ADMIN_BOOTSTRAP_REQUIRED`，并断言 Release 表为空。

- [ ] **Step 5: 运行测试确认 RED**

Run: `python -m pytest tests/unit/config_patch_service/test_releases.py tests/unit/config_patch_service/test_bundles.py tests/integration/test_config_patch_phase1.py -q`

Expected: FAIL，因为 Release repository、双读聚合和工作包构建器尚不存在。

- [ ] **Step 6: 实现不可变基线和确定性工作包**

先读 Omnichannel 快照和 DClaw context，下载对应 DClaw 快照，再回读两个系统并比较 Bot/Agent/flow/tag/Agent/knowledge 指纹；使用 `BEGIN IMMEDIATE` 和唯一约束解决首次并发。上游原始快照与生成工作包保存于补丁服务 data dir 的内容寻址对象目录，数据库只保存摘要和相对对象键；对象写入采用临时文件、`fsync`、原子 rename。在 `pyproject.toml` 为 `config_patch_service` 声明 `resources/**` package data，确保 wheel/容器内能力目录、平台资料和 examples 均存在。

- [ ] **Step 7: 运行测试确认 GREEN**

Run: `python -m pytest tests/unit/config_patch_service tests/integration/test_config_patch_phase1.py -q`

Expected: PASS；首次导出只改变补丁服务元数据，不改变任何上游 fake 的写调用计数。

- [ ] **Step 8: 提交可信工作包切片**

```bash
git add pyproject.toml src/config_patch_service \
  tests/unit/config_patch_service tests/integration/test_config_patch_phase1.py
git commit -m "feat: export trusted customer service workspaces"
```

### Task 7: AI 客服管理员 Token 管理代理页

**Files (in `dclaw-omnichannel-service`):**
- Create: `src/config-patch-admin-client.js`
- Modify: `src/server.js`
- Modify: `public/admin/index.html`
- Modify: `public/admin/app.js`
- Modify: `public/admin/styles.css`
- Create: `tests/config-patch-admin-client.test.js`
- Create: `tests/server-staff-token-admin-boundary.test.js`
- Modify: `tests/admin-console-boundary.test.js`

**Interfaces:**
- Produces: `ConfigPatchAdminClient.listTokens/createToken/revokeToken/rotateToken`，仅服务端读取 `CONFIG_PATCH_ADMIN_BASE_URL` 与 `CONFIG_PATCH_ADMIN_SECRET`。
- Produces: 受现有管理员 Session 保护的代理接口 `GET/POST /api/admin/staff-tokens`、`POST /api/admin/staff-tokens/:tokenId/revoke`、`POST /api/admin/staff-tokens/:tokenId/rotate`。
- Produces: 管理后台“Codex Token”页签，只包含创建、一次性复制、查询、撤销和轮换。

- [ ] **Step 1: 编写代理客户端与服务端边界测试**

断言管理员 Session 必须有效；浏览器请求不能提供或覆盖补丁服务地址/内部密钥；服务端转发准确路径和管理员 Header。补丁服务未配置/不可用时仅 Token 页返回结构化 503，原工作区/Bot/Agent/系统设置接口继续工作。

- [ ] **Step 2: 编写管理员页面测试**

断言新增页签只出现姓名、设备备注、有效期、状态、创建/最后使用时间以及创建/撤销/轮换动作；完整 Token 仅在创建/轮换成功后的不可恢复弹窗中渲染，列表和页面状态不持久化明文。断言页面中不存在 Bot 选择、工作包、预检、发布、Release 或能力目录功能。

- [ ] **Step 3: 运行测试确认 RED**

Run from `dclaw-omnichannel-service`: `npm test -- tests/config-patch-admin-client.test.js tests/server-staff-token-admin-boundary.test.js tests/admin-console-boundary.test.js`

Expected: FAIL，因为代理客户端、路由和 Token 页尚不存在。

- [ ] **Step 4: 实现窄代理和 Token 页面**

复用现有 `assertAdminAccess`，但不把管理员 Session 转发给补丁服务；后端换成专用内部管理员密钥。创建/轮换弹窗关闭后销毁 Token 字符串引用并刷新列表，UI 明确提示无法再次查看。

- [ ] **Step 5: 运行测试确认 GREEN**

Run from `dclaw-omnichannel-service`: `npm test -- tests/config-patch-admin-client.test.js tests/server-staff-token-admin-boundary.test.js tests/admin-console-boundary.test.js`

Expected: PASS，且原管理员后台功能测试全部保持通过。

- [ ] **Step 6: 提交管理员 Token 页切片**

```bash
git add src/config-patch-admin-client.js src/server.js public/admin \
  tests/config-patch-admin-client.test.js \
  tests/server-staff-token-admin-boundary.test.js \
  tests/admin-console-boundary.test.js
git commit -m "feat: manage employee codex tokens"
```

### Task 8: 独立部署、端到端验收与阶段一运行手册

**Files (in `dclaw-server`):**
- Create: `deploy/config-patch.Dockerfile`
- Create: `deploy/config-patch-entrypoint.sh`
- Create: `deploy/config-patch.compose.yaml`
- Create: `docs/config-patch-service-phase1-runbook.md`
- Create: `tests/unit/release/test_config_patch_deployment.py`
- Modify: `tests/integration/test_config_patch_phase1.py`

**Files (in `dclaw-omnichannel-service`):**
- Modify: `README.md`
- Create: `tests/config-patch-phase1-contract.test.js`

**Interfaces:**
- Produces: 单独启动的 `dclaw-config-patch` 容器/进程，不加入或替换现有 DClaw 主进程入口。
- Produces: 阶段一环境变量、密钥轮换、备份、审计查询、`ADMIN_BOOTSTRAP_REQUIRED` 排查和停用回滚手册。

- [ ] **Step 1: 编写部署静态检查**

断言 Dockerfile 使用独立入口和非 root 用户；compose 仅新增显式启动文件，不修改现有默认 compose；数据卷只挂载补丁服务 data dir；健康检查不需要员工 Token且不泄漏配置。断言所有服务密钥均来自环境/secret mount，无默认生产值。

- [ ] **Step 2: 扩展端到端测试**

使用真实补丁服务 TestClient 和两个受控 fake upstream：管理员创建 Token、员工列出全部 Bot、未就绪 Bot 获得完整缺失项、就绪标准 Agent 首次导出 `R1`、同一 Token 再次下载相同摘要、超级专家获得相同目录结构不同 Profile、审计能定位 Token ID。断言 fake upstream 的所有写方法调用数为零。

- [ ] **Step 3: 运行阶段一完整验证**

Run in `dclaw-server`: `python -m pytest tests/unit/app/config_patch_participant tests/unit/config_patch_service tests/integration/test_config_patch_phase1.py tests/unit/release/test_config_patch_deployment.py -q`

Run in `dclaw-omnichannel-service`: `npm test -- tests/config-patch-participant.test.js tests/server-config-patch-participant-boundary.test.js tests/config-patch-admin-client.test.js tests/server-staff-token-admin-boundary.test.js tests/config-patch-phase1-contract.test.js tests/admin-console-boundary.test.js tests/server-workspace-boundary.test.js`

Expected: 两组均 PASS，且没有上游写操作。

- [ ] **Step 4: 运行仓库级回归**

Run in `dclaw-server`: `python -m pytest tests/unit/app/test_agent_package_import.py tests/unit/app/test_sealed_agent_admin.py tests/unit/app/test_open_api_admin.py tests/unit/app/test_open_api_knowledge.py -q`

Run in `dclaw-omnichannel-service`: `npm test`

Expected: PASS；现有 Agent 导入、sealed 权限、OpenAPI 经验库、Bot/Workspace/状态机/标签行为不变。

- [ ] **Step 5: 编写运行手册并执行本地 smoke test**

按手册使用临时 data dir 和测试密钥启动三个进程，执行 health → 创建 Token → 列 Bot → 查 context → 导出工作包 → 解压检查 manifest 的完整链路；记录命令、预期机器码和停止方式，不记录真实 Token 或服务密钥。

- [ ] **Step 6: 提交部署与验收切片**

In `dclaw-server`:

```bash
git add deploy/config-patch.Dockerfile deploy/config-patch-entrypoint.sh \
  deploy/config-patch.compose.yaml docs/config-patch-service-phase1-runbook.md \
  tests/unit/release/test_config_patch_deployment.py \
  tests/integration/test_config_patch_phase1.py
git commit -m "docs: add config patch phase one deployment"
```

In `dclaw-omnichannel-service`:

```bash
git add README.md tests/config-patch-phase1-contract.test.js
git commit -m "test: cover config patch phase one contract"
```

## Phase 1 Exit Gate

- 员工可使用个人 Token 从公网补丁服务查看全部 Bot，但任何员工接口都不能创建 Agent、修改经验库、状态机或标签。
- 管理员只在 AI 客服后台管理 Token；页面没有工作包和发布功能。
- 就绪 Bot 的首次导出只读建立唯一 `R1`，普通/超级专家得到相同目录契约。
- 未就绪 Bot 不产生 Release，并返回管理员可执行的完整缺失清单。
- 工作包来源、组件摘要、Token ID 和下载事件均可审计，所有秘密都不进入日志、数据库明文字段或 ZIP。
- 两个原系统未配置补丁功能时维持原行为；阶段一关闭只需停止独立服务并隐藏 Token 页，不需要回滚业务数据。

后续阶段分别编写新计划：阶段二实现上传解析、动态预检与不可变候选；阶段三实现发布屏障、联合激活、补偿恢复与回退；阶段四接入 `ai-customer-service-delivery` 的 Codex 工具并用真实测试 Bot 联调。
