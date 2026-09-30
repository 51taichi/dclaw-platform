# AI 客服配置补丁服务设计

日期：2026-09-30

状态：用户已于 2026-09-30 确认；按分阶段实施计划进入开发。

## 1. 目标

为公司员工使用 Codex 开发、调试 AI 客服提供一套独立配置补丁服务。调用方以 Bot 为唯一入口，下载该 Bot 当前线上可信配置，在本地联合修改 Agent、DClaw 经验库、AI 客服状态机和标签，再通过服务端预检与事务发布整套生效。

该能力是现有平台的加法：不改变原有页面和业务接口的语义，不要求现有 Bot 迁移，不允许员工通过接口完成 Agent 首次安装。未加入补丁发布机制的 Bot 继续完全沿用原路径。

## 2. 已确认原则

1. 接口可从公网访问，但只允许持有有效员工 Codex Token 的调用方使用。
2. 所有有效员工 Token 默认可以查看和操作全部 Bot，不做 Workspace 或 Bot 级权限划分。
3. Bot 是调用方选择的唯一业务目标。服务端根据 Bot 解析 Agent、OpenAPI 发布对象、经验库、状态机和标签目标。
4. Agent 第一次安装必须由 DClaw 平台管理员完成。员工接口只支持已初始化、已绑定且可以正常对话的 Agent 升级。
5. 工作包内 Agent ID 必须与 Bot 当前绑定的 Agent ID 完全一致，不提供强制覆盖选项。
6. 员工第一次修改前必须从平台下载当前可信工作包，不能从零构造一个目录上传。
7. 普通专家和超级专家对调用侧采用同一套源码下载、修改、预检和发布流程。调用侧只感知能力 Profile 差异，不感知构建、加密、签名和运行产物差异。
8. 一次工作包发布是一个联合 Release。Agent、经验库、状态机和标签要么全部生效，要么全部不生效。
9. 预检由 Codex 自动调用，是不改变线上有效版本的模拟发布，不是管理员审批。
10. 发布后下一次请求使用新 Release；不维护会话级版本固定或状态迁移。已开始执行的单次请求可以使用旧版本完成。
11. AI 客服后台只提供员工 Codex Token 的创建、查询和撤销界面，不承载工作包、预检、发布、版本或能力管理。
12. 现有 `ai-customer-service-delivery` 仓库继续负责调用方 Codex 的交付方法、职责判断、业务确认、文件修改、测试和经验演进；本项目只补齐线上执行平面。

## 3. 非目标

- 不替调用方重新编写客户业务配置。
- 不新增 Bot 创建或 Agent 首次安装能力。
- 不为员工建立 Bot 级授权矩阵。
- 不把补丁服务功能搬入 AI 客服后台。
- 不让调用方处理超级专家的密钥、加密、签名或受保护运行目录。
- 不改造现有客户交付方法、业务确认 Gate 或 GitHub 经验同步主链。
- 不承诺在已经开始的一次模型推理中途切换配置。

## 4. 系统边界

### 4.1 调用方 Codex

调用方继续使用现有项目级 Skills 和客户任务目录。新增工具只负责：

- 使用员工 Token 调用补丁服务；
- 列出并选择 Bot；
- 下载可信工作包和动态能力目录；
- 提交结构化变更计划；
- 自动预检、修复阻断问题并发起联合发布；
- 查询发布和验证状态；
- 发现能力不足时提交标准化能力申请。

Skill 负责稳定工作方法，补丁服务负责动态线上事实。Demo 只作示例，不能成为能力真相。

### 4.2 AI 客服后台 Token 管理面

AI 客服后台只增加一个小型管理员页面。管理员可以：

- 创建带员工姓名、设备备注和有效期的 Codex Token；
- 只在创建时查看一次 Token 明文；
- 查看 Token 状态、创建时间和最后使用时间；
- 撤销或重新生成 Token。

Token 数据和验证逻辑归补丁服务。AI 客服后台通过内部管理员接口管理 Token；员工 Codex 不经过 AI 客服后台代理，直接访问补丁服务。

### 4.3 独立补丁服务

补丁服务单独部署，负责：

- 员工 Token 验证与审计；
- Bot 发现、初始化就绪检查和配置上下文聚合；
- 首次下载自动建立基线；
- 工作包生成、校验和来源指纹；
- 动态能力目录和专家能力 Profile；
- 预检、候选版本、并发冲突检测；
- 跨 DClaw 与 AI 客服中台的发布编排、恢复和回退；
- 发布历史、能力申请和状态查询。

### 4.4 DClaw 内部参与者

DClaw 仍然拥有 Agent、超级专家发布、OpenAPI、积分挂靠和经验库。新增窄内部适配器，提供只读导出、候选准备、激活、回退和状态回读，不对员工直接开放管理凭据。

现有标准 Agent 导入、超级专家发布和经验库接口可以在适配器内复用，但不能把当前“直接覆盖生效”的行为冒充候选准备。标准 Agent 与经验库需要补齐不可变候选版本和恢复能力。

超级专家在 DClaw 原有用户、租户和应用管理员接口中继续保持不可查看、不可导出。员工源码访问属于单独的受信公司开发平面，不扩大 DClaw 应用角色权限。首次管理员发布必须同时形成受保护的可编辑源码快照；运行时加密产物不作为以后导出源码的来源。

### 4.5 AI 客服中台内部参与者

AI 客服中台继续拥有 Bot-Agent 绑定、状态机、标签和运行会话。补丁服务通过窄内部适配器读取绑定和当前配置，准备候选状态机与标签，并执行激活或回退。

AI 客服中台不保存统一 Release，不承担员工工作流，也不增加相关管理页面。旧 API 和未加入补丁机制的 Bot 行为保持不变。

## 5. 核心数据模型

### 5.1 员工 Token

```text
StaffToken
  id
  token_hash
  employee_name
  token_name
  expires_at
  revoked_at
  last_used_at
  created_at
```

Token 使用带产品前缀的高熵随机值，服务端只保存哈希。完整 Token 和 Authorization 头不得写入日志。

### 5.2 Bot 配置目标

```text
BotConfigurationTarget
  bot_id
  bot_name
  enabled
  bound_agent_id
  agent_profile_id
  openapi_publication_id
  knowledge_base_id
  readiness
  current_release_id
```

调用方不能提交权威 Agent ID、知识库 ID 或发布对象 ID。请求中的可选预期值只作为断言，权威绑定始终由服务端解析。

### 5.3 联合 Release

```text
ConfigurationRelease
  id
  bot_id
  base_release_id
  bundle_digest
  capability_catalog_version
  agent_component_version
  knowledge_component_version
  flow_component_version
  tag_component_version
  status
  created_by_token_id
  created_at
  activated_at
```

Release 和组件版本均不可变。回退选择已经验证的旧 Release，不重新构建旧内容。

### 5.4 发布状态

```text
DRAFT
PRECHECKING
PRECHECK_FAILED
PREPARED
COMMITTING
ACTIVE
ABORTING
ABORTED
ROLLING_BACK
ROLLED_BACK
RECOVERY_REQUIRED
```

`RECOVERY_REQUIRED` 表示跨参与者恢复未完成。此时目标 Bot 保持发布屏障，不允许暴露部分新配置，直到自动恢复或管理员处置完成。

## 6. 工作包契约

工作包是员工修改的唯一合法起点：

```text
customer-service-workspace/
├── dclaw-manifest.json
├── AGENTS.md
├── change-plan.yaml
├── agent/
├── customer-service/
│   ├── flow-machine.json
│   └── tag-schema.json
├── knowledge/
│   ├── knowledge-manifest.json
│   └── documents/
└── platform/
    ├── responsibility-matrix.md
    ├── runtime-mechanism.md
    ├── capability-catalog.json
    ├── coordinated-change-patterns.md
    └── examples/
```

`dclaw-manifest.json` 至少包含：

```json
{
  "schemaVersion": "customer-service-workspace.v1",
  "bundleId": "bundle_xxx",
  "botId": "bot_xxx",
  "agentId": "agent_xxx",
  "agentProfileId": "standard-2026.09",
  "baseReleaseId": "R18",
  "capabilityCatalogVersion": "2026.09.1",
  "sourceFingerprints": {
    "agent": "sha256:...",
    "knowledge": "sha256:...",
    "flow": "sha256:...",
    "tags": "sha256:..."
  },
  "exportedAt": "2026-09-30T10:00:00+08:00"
}
```

工作包必须限制总大小、文件数、单文件大小和解压比例；拒绝绝对路径、路径穿越、重复规范化路径、符号链接、硬链接和设备文件。服务端对规范化文件集合计算确定性摘要。

`change-plan.yaml` 由 Codex 修改前生成，声明各板块是否变更、原因、所需能力、发布顺序含义和联合验收场景。预检核对计划与实际差异，但调用方声明不替代服务端校验。

## 7. 首次下载和基线建立

员工调用导出接口时，补丁服务先检查：

- Bot 存在、启用且已绑定 Agent；
- Agent 源码可导出，包内 ID 与绑定 ID 一致；
- OpenAPI 发布对象已配置并可用；
- 积分账户已经挂靠；
- 专属经验库已经关联；
- 状态机和标签可以读取；
- Bot 已具备正常对话条件。

条件不满足时返回 `ADMIN_BOOTSTRAP_REQUIRED` 和明确缺失项，不创建基线。条件满足且补丁服务尚无 Release 时，只读聚合两个系统的当前有效配置并自动建立 `R1`，不修改线上对象，也不要求管理员在补丁服务重复登记。

后续导出以当前有效 Release 为基线。若发现有人绕过补丁服务直接修改来源系统，服务端记录外部漂移并要求调用方重新下载，不允许旧工作包覆盖新状态。

## 8. 动态能力与职责资料

现有 Codex Skill 保存稳定的交付方法。补丁服务提供版本化动态能力目录，包括：

- Agent Profile 及其真实可用能力；
- 普通专家和超级专家差异；
- Agent 输出协议；
- 状态机、标签、卡片和经验库的字段、限制及运行语义；
- 能力引入版本、废弃状态、Schema 和示例。

普通专家与超级专家使用同一 API。调用方只依据 Profile 和能力项设计配置，不根据专家类型处理加密或签名。

预检始终按服务端最新能力目录执行。旧工作包的能力版本过期时，返回可刷新错误或警告；不能因为本地 Demo 存在某字段就认定平台支持。

能力不足时 Codex 提交标准化申请，至少包含业务需求、当前阻塞、受影响模块、建议契约、兼容要求、临时方案和验收案例。管理员完成平台能力后更新能力目录；调用方刷新后继续原任务。

## 9. 员工 API

首版接口使用 `/staff/v1`：

```text
GET  /staff/v1/bots
GET  /staff/v1/bots/{botId}/configuration-context
POST /staff/v1/bots/{botId}/workspace-bundles/export
GET  /staff/v1/capabilities
POST /staff/v1/bots/{botId}/releases/precheck
POST /staff/v1/bots/{botId}/releases
GET  /staff/v1/bots/{botId}/releases/{releaseId}
GET  /staff/v1/bots/{botId}/releases
POST /staff/v1/bots/{botId}/releases/{releaseId}/rollback
POST /staff/v1/platform-capability-requests
GET  /staff/v1/platform-capability-requests/{requestId}
```

所有写操作要求幂等键。错误使用稳定机器码和可供 Codex 修复的结构化细节，不能只返回自由文本。

关键错误码包括：

```text
ADMIN_BOOTSTRAP_REQUIRED
PACKAGE_AGENT_ID_MISMATCH
TARGET_BINDING_CHANGED
BASE_RELEASE_CHANGED
CAPABILITY_NOT_SUPPORTED
BUNDLE_SCHEMA_INVALID
CROSS_COMPONENT_REFERENCE_BROKEN
PRECHECK_EXPIRED
RELEASE_IN_PROGRESS
PARTICIPANT_PREPARE_FAILED
RECOVERY_REQUIRED
```

## 10. 预检

预检是只读模拟和候选准备，不改变线上有效 Release。它检查：

- Token、Bot、初始化状态和基线；
- Agent ID、绑定关系和来源指纹；
- 工作包 Schema、路径安全和摘要；
- 能力 Profile 与字段合法性；
- Agent 输出、状态机和标签之间的引用；
- 经验库文档解析和候选索引；
- 变更计划与实际差异；
- 外部漂移和并发发布；
- 各参与者是否能够准备候选版本。

结果包含 `canPublish`、阻断项、警告、各板块差异、候选 Release、预检有效期和工作包摘要。Codex 可自动修复阻断项并重试。

正式发布接口必须重新执行不可绕过的安全检查，并确认预检 ID、工作包摘要、基线和绑定关系没有变化。员工没有先调用独立预检接口时，发布接口内部仍执行同一套检查。

## 11. 联合事务发布

### 11.1 准备阶段

补丁服务取得 Bot 发布锁并要求两个参与者分别准备不可变候选：

- DClaw：Agent 源码/运行产物和经验库新索引；
- AI 客服中台：状态机和标签候选版本。

普通专家候选按标准 Agent 方式构建；超级专家候选由平台内部完成构建、加密、签名和启动校验。任何准备失败都中止候选，线上继续使用旧 Release。

### 11.2 可观察原子性

跨两个独立系统无法依赖单一数据库事务。为保证客户看不到半套配置，AI 客服中台为目标 Bot 提供窄发布屏障：

1. 已经开始的单次请求允许用旧配置完成；
2. 新进入的请求在很短的提交窗口内排队；
3. 补丁服务激活两个参与者的候选版本并回读确认；
4. 全部成功后记录新 Release 为 `ACTIVE` 并解除屏障；
5. 任一激活失败时，在屏障内将已经激活的参与者恢复为旧版本；
6. 恢复成功后解除屏障并继续使用旧 Release；恢复失败则保持屏障并进入 `RECOVERY_REQUIRED`。

这样员工可观察到的结果只有整套旧版本或整套新版本。发布不是让调用方逐模块上传；调用方提交一次工作包，服务端内部报告各参与者阶段状态。

### 11.3 并发与回退

激活使用 `baseReleaseId` 比较并交换。基线已变化时返回 `BASE_RELEASE_CHANGED`，要求重新下载和合并。重复请求使用幂等键返回同一操作结果，不重复构建、索引或激活。

回退对一个已经验证的历史 Release 执行同样的准备确认和发布屏障，不重新解释或重建历史文件。

## 12. 审计与安全

至少记录：

- Token 创建、撤销和鉴权失败；
- Bot 列表、上下文和源码工作包下载；
- 预检、发布、回退和恢复；
- 基线、目标 Release、组件版本和结果；
- 调用员工、Token ID、请求关联 ID、时间和安全可用的来源信息；
- 能力申请及状态变化。

日志不得包含完整 Token、密钥、Authorization 头、超级专家运行密钥或客户原始敏感资料。源码工作包下载属于高价值审计事件。

补丁服务使用独立服务凭据调用两个内部参与者。员工 Token 不下发为 DClaw 管理员凭据或 AI 客服管理凭据。

## 13. 兼容策略

- 保留全部原有 DClaw 和 AI 客服业务路由与语义。
- 新增内部参与者接口，不把员工身份塞入现有管理员或 Bot Session。
- 没有补丁 Release 的 Bot 继续读取原配置。
- 首次自动基线只是快照，不改变现有有效配置。
- AI 客服后台仅增加 Token 管理入口；调用工作包和发布不经过该后台。
- 现有 Codex 仓库在自动上传占位处接入新工具，不重写其总控、客户任务和经验同步体系。

## 14. 实施分解

### 阶段一：独立服务基础与只读基线

- 服务骨架、存储、Token 和审计；
- AI 客服后台最小 Token 管理页；
- Bot 列表和配置上下文；
- DClaw 与 AI 客服只读适配器；
- 初始化就绪检查；
- 首次导出自动建立 `R1`；
- 脱敏工作包和能力目录样例。

### 阶段二：预检与候选版本

- 工作包和变更计划校验；
- 动态能力目录；
- 标准/超级专家候选准备；
- 经验库候选索引；
- 状态机和标签候选版本；
- 差异、引用、漂移和并发检查。

### 阶段三：事务发布与恢复

- Bot 发布锁和运行屏障；
- 两参与者激活、回读和补偿恢复；
- 幂等、CAS、历史 Release 和回退；
- 故障注入和重启恢复。

### 阶段四：调用方接入和真实联调

- 在现有 Codex Skills 中接入 Bot 选择、下载、预检、发布和能力申请；
- 使用一个管理员已初始化的测试 Bot 完成基线导出；
- 修改至少一个板块并完成联合发布；
- 回读实际版本并执行同一会话联合验证；
- 记录接口契约、测试结果和未覆盖能力。

## 15. 测试要求

### 15.1 安全和身份

- Token 只显示一次、只存哈希、过期和撤销立即生效；
- 无 Token、错误 Token 和被撤销 Token 无法访问员工 API；
- 员工 Token 不能调用原管理接口；
- 所有有效员工 Token 可以查看全部 Bot；
- 源码下载和发布能审计到具体 Token。

### 15.2 工作包和绑定

- 未初始化 Bot 返回完整缺失项；
- 首次导出只读建立基线；
- Agent ID 不一致、Bot 重新绑定和外部漂移均阻断发布；
- 路径穿越、重复路径、压缩炸弹和非法文件被拒绝；
- 普通专家和超级专家导出的调用侧结构一致、能力 Profile 不同。

### 15.3 预检和事务

- 任一组件准备失败时线上四块全部保持旧版本；
- 每个激活步骤前后注入失败，客户请求只能观察到完整旧版本或完整新版本；
- 补偿失败保持发布屏障并进入可恢复状态；
- 重启后恢复未完成事务，不重复构建或激活；
- 相同幂等键返回同一结果，不同内容复用同一键被拒绝；
- 并发发布只有一个基线比较成功。

### 15.4 业务联调

- 同一测试会话验证 Agent 回复、经验库检索、状态机推进和标签动作；
- 分别记录文件生成、服务端接收、候选准备、统一激活、目标绑定和运行验证；
- 能力不足时不接受伪字段，能够提交能力申请并在目录升级后继续。

## 16. 验收标准

- 员工可以使用个人 Codex Token 查看全部 Bot，但无法为未初始化 Bot 执行首次安装。
- 对可用 Bot 的第一次下载自动生成可信 `R1`，工作包内 Bot、Agent 和来源版本可追溯。
- Codex 能依据当前 Bot 的动态能力 Profile 和职责资料生成跨板块变更计划。
- 预检能在不改变线上有效版本的情况下发现绑定、能力、引用、漂移和并发问题。
- 一次工作包提交只产生整套成功或整套失败；调用方不需要处理部分生效。
- 普通专家和超级专家采用相同调用契约，超级专家加密和签名对调用侧透明。
- 发布和回退均可查询、可审计、可在进程重启后恢复。
- 未加入该机制的原有 Bot 和原有业务接口行为不变。
- 现有调用方 Codex 仓库完成真实测试 Bot 的端到端联调，并保留本地方法演进能力。

## 17. 设计自检结论

本文把 AI 客服后台限制在 Token 管理面，把配置功能集中在独立补丁服务；DClaw 和 AI 客服中台只增加各自领域所需的窄内部参与者接口。首次管理员初始化、首次员工基线、普通/超级专家差异、预检、并发、发布失败和能力不足均有明确处理路径。

“联合事务”没有假设跨系统数据库天然原子，而是通过不可变候选、Bot 发布屏障、回读确认和屏障内恢复提供调用方可观察的全有或全无。现有直接覆盖接口不能直接满足该承诺，必须在阶段二和阶段三补齐候选版本与恢复契约后才能开放正式发布。
