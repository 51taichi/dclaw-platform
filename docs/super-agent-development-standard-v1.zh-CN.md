# DClaw 第三方超级 Agent 开发、密封与协作标准 V2

状态：`stable`

标准标识：`dclaw.super-agent-development`

当前版本：`2.0`

发布日期：`2026-10-26`

## 1. 文档目的

本标准规定第三方开发方如何使用 Codex 开发、测试、密封、上传和维护 DClaw 超级 Agent，以及 DClaw 平台方如何提供公共平台能力、本地助手和兼容保障。

本标准只设置两个组织责任方：

1. **开发方**：拥有超级 Agent 的业务实现和发布物。
2. **DClaw 平台方**：拥有 DClaw 公共平台、公共协议和通用本地助手核心。

网关、Runner、能力包、业务 MCP、第三方 API 等是技术组件，不是新增的组织责任方。每个组件都必须归入上述两方之一。

本文面向：

- 从零开发超级 Agent 的团队；
- 从 WorkBuddy、豆包或其他平台迁移 Agent 的团队；
- 负责审核、安装和维护超级 Agent 的 DClaw 管理员；
- 负责扩展 DClaw 公共能力的 DClaw 平台团队。

开发者应把本文作为新 Codex 任务的第一份入口文件。本文包含全部人工开发规则；字段级机器合同、模板和密封工具由目标 DClaw 的官方 Super Agent DevKit 提供。本文与同版本 DevKit Schema 不一致时，以机器 Schema 为准，并向平台方提交文档缺陷。

### 1.1 唯一对外开发标准

本文是 DClaw 超级 Agent 开发方唯一需要接收和阅读的人工标准文档。用户向开发方发送本文文件或可访问链接，文件名固定为：

```text
super-agent-development-standard-v1.zh-CN.md
```

强制维护规则：

1. 开发流程、职责边界、本地执行、迁移、密封、发布和平台协作规则只在本文维护。
2. 后续修订保持同一文件路径，修改文内当前版本和版本记录，不再新建并行的人工标准或独立变更记录。
3. 历史版本通过本文第 34 节和 Git 提交追溯，不为每个 minor 版本复制新文件。
4. JSON Schema、能力目录、最小模板和密封 CLI 统一由本文第 33 节指定的官方 DevKit 提供；它们是机器材料，不是第二份人工标准。
5. 开发方只使用本文、自己的业务材料和从目标 DClaw 下载的 DevKit。任何步骤都不得要求访问、克隆或导入 `dclaw-server`、`qwenpaw` 或平台插件源码。
6. 验收时必须在不含 DClaw 服务端源码的干净目录完成摘要计算、工作区校验、密封构建和独立验签；否则不能宣称标准可独立使用。

迁移开发者应先执行第 27.2 节的“默认优先、最少提问”规则。收到本文和源包即可开始安全盘点与源码迁移；不要求用户先填写项目身份、Git、操作系统、依赖、卡片、签名和验收问卷。

## 2. 规范用语与核心概念

本文中的“必须”“禁止”表示强制要求；“应”表示原则上必须执行，只有记录充分理由后才能例外；“可以”表示可选。

| 名称 | 定义 |
|---|---|
| 超级 Agent | 面向客户交付完整业务结果的产品，由密封超级专家、业务服务和可选本地能力包组成 |
| 超级专家 | DClaw 中 `package_type=super_expert` 的签名密封运行包，负责理解意图、编排业务、调用获授权能力和完成回复 |
| 能力清单 | 密封 manifest 中声明的不可变平台能力集合；安装时由管理员整体授权 |
| 密封 | 对发布内容计算摘要并使用 Ed25519 私钥签名，使平台可以验证来源、完整性和能力声明 |
| 业务服务 | 开发方维护的业务 MCP、HTTP 服务、确定性状态机、连接器和数据存储 |
| 平台能力 | 可供多个无关 Agent 复用、不包含行业规则的通用能力 |
| 本地助手 | DClaw 桌面版配套的 Windows 通用工具箱，技术名称可称 Runner |
| 本地能力网关 | DClaw 提供的通用 MCP 和任务网关，历史代码中可能称 Relay |
| 本地能力包 | 开发方交付、由本地助手按协议安装和执行的 Agent 专属代码 |
| 客户端 | 客户直接使用的 DClaw 桌面版；它是唯一登录和业务交互入口 |
| 安装授权 | 管理员对某个签名发布版的完整能力清单进行一次性整体授权 |
| `trace_id` | 跨平台、超级专家、网关、本地助手、能力包和外部服务关联日志的追踪标识 |

“超级 Agent”是产品概念，“超级专家”是 DClaw 密封包类型。开发一个超级 Agent 时至少交付超级专家包；只有业务确实需要时才增加业务服务和本地能力包。

## 3. 两方协作模型

```mermaid
flowchart LR
    U[客户] --> D[DClaw 客户端与平台]
    D --> E[签名密封超级专家]
    E --> B[开发方业务服务或业务 MCP]
    B --> X[第三方 API]
    E --> G[DClaw 公共本地能力网关]
    G --> R[DClaw 本地助手核心]
    R --> P[开发方本地能力包]
    P --> L[本机文件、网络和桌面软件]

    subgraph PO[DClaw 平台方]
      D
      G
      R
    end

    subgraph DO[开发方]
      E
      B
      P
    end
```

第三方 API 是开发方业务实现的依赖，其选型、凭证、费用、重试和结果解释都归开发方。DClaw 平台不因承载请求而成为第三方业务依赖的所有者。

密封超级专家是业务控制中心，必须承载全部产品业务逻辑：客户意图与状态、业务流程编排、素材来源选择、候选评分与筛选、脚本与编辑决策、返工策略、客户交互、DClaw 卡片调用和最终业务验收。开发方业务服务是超级专家的受控服务端适配层，只负责第三方连接、Secret、严格合同、幂等、费用限制、短时资源授权和结构化结果，不得在超级专家不可见的情况下另行改变业务目标或完成判据。

### 3.1 唯一允许的依赖方向

```text
DClaw 平台 -> 密封超级专家
密封超级专家 -> 开发方业务服务 -> 第三方 API
密封超级专家 -> 公共本地能力网关 -> 本地助手核心 -> 开发方能力包
```

禁止反向依赖：

- DClaw 平台不得导入某个 Agent 的业务代码、提示词或供应商连接器。
- 公共网关和本地助手核心不得识别具体行业流程、Agent 名称或第三方供应商。
- 能力包不得修改平台数据库、授权记录或本地助手核心。
- 业务服务不得要求平台根据业务字段替它做业务判断。
- 业务服务不得绕过超级专家独立选择素材、评分候选、决定时间线、判定成品合格或直接生成客户业务回复。
- 超级专家不得通过提示词、客户输入或运行时参数扩大签名能力清单。

### 3.2 平台插件隔离

超级 Agent 开发、密封 Agent 调用开发方业务 MCP、本地能力包和本地助手所需的新增平台支持，必须统一作为可选的 `dclaw.super-agent-support` 插件包实现，不得把这些能力写入 DClaw 核心业务模块。该插件包包含：

- `local-execution` 模块：对外使用 `dclaw.local-execution` 公共合同，注册八个 `local_*` 工具，实现设备路由、任务、检查点、产物、错误和追踪；
- `credential-broker` 模块：把需要由 DClaw 管理的客户凭证加密保存为不透明引用，按用户、Agent 安装和权限范围隔离，支持撤销，并只在已授权本地能力执行时受控注入；开发方业务服务自身使用的供应商 Token 仍由开发方 Secret 管理系统持有；
- `capability-packages` 模块：实现能力描述符、Schema、签名验证、注册、安装、版本、授权和回滚；
- DClaw 客户端插件适配：在已登录客户端内完成安装、更新、连接和用户交互引导；
- 通用 Windows 本地助手：作为插件套件的配套客户端组件独立发布，执行受信能力包；
- 公共合同和测试套件：提供 Schema、兼容性夹具和边界测试。
- 官方 Super Agent DevKit：提供独立 CLI、版本化 Schema、能力目录和最小模板，并通过插件公开下载；DevKit 不得导入 DClaw 服务端模块。

DClaw 核心只提供与业务无关的插件 SPI，包括插件生命周期、已验证的租户/用户/Agent/发布版/会话主体、能力授权校验、受控消息通道、插件隔离存储和审计追踪。插件只能依赖这些公开 SPI，DClaw 核心不得导入或调用 `dclaw.super-agent-support` 插件的内部模块。

必须同时满足：

1. 未安装、禁用、升级失败或卸载该插件时，普通对话、普通 Agent 运行、交互卡、文件和其他平台能力仍可正常使用；依赖该插件的超级 Agent 必须返回明确的能力不可用错误。
2. 插件的路由、配置、数据表/命名空间、队列、日志和迁移必须可独立安装、升级、回滚和删除。
3. 核心不得硬编码 `local_*`、Runner 版本、能力包类型或任何 Agent 的业务名称；目录和工具由插件安装时注册。
4. 插件即使与 DClaw 核心暂时运行在同一进程，也必须保持独立包、单向依赖和可单独发布；同进程不等于允许写入核心。
5. 超级 Agent 开发方只依赖已发布的 MCP 凭证、`local_*` 和能力包公开合同，不得导入 DClaw 核心或插件内部代码。
6. 服务端镜像必须使用明确的自动加载白名单交付平台插件。源码仓库中的插件目录只是候选目录，禁止把整个目录设为自动加载路径；未获平台方明确启用的插件不得注册 Agent、工具、路由或修改持久工作区。
7. 插件必须提供与当前平台合同匹配的 DevKit 下载入口；DevKit 输出必须通过平台实现的兼容测试，开发方不得被要求取得平台源码。

### 3.3 开发方问题的插件交付范围

开发方在对接中发现的平台通用能力缺口，经平台方确认后纳入 `dclaw.super-agent-support` 插件包。每个接受的缺口必须在同一交付中明确：

- 公开能力或工具名称及语义；
- 请求、响应、事件、错误和能力描述符 Schema；
- 插件目标版本、最低 DClaw 核心 SPI 版本、客户端版本和 Runner 版本；
- 实现代码、数据迁移、合同测试、核心隔离回归和兼容矩阵；
- 开发、签名、安装、测试和生产状态，不得用单一“已完成”代替。

“正式 DClaw 对接仍缺配套协议、Schema 和目标版本”属于本插件包的平台交付问题。插件必须提供协议、Schema、版本和真实接入点后，开发方才能完成正式集成。

“尚未签名、上传或上线”是插件实现后的发布门禁：插件提供能力包签名验证、注册、安装和授权机制；开发方仍要签名并上传自己的超级专家包和能力包，管理员仍要授权、激活和完成真实验收。插件代码完成不会自动使 Agent 上线。

## 4. 责任矩阵

### 4.1 组织责任

| 工作项 | 责任方 | 必须做到 | 禁止事项 | 需要协作时 |
|---|---|---|---|---|
| 业务目标、业务流程、提示词、Skill | 开发方的超级专家 | 明确输入、状态、输出、选择/评分、编辑决策和完成条件 | 把业务规则放进平台、本地助手或不透明业务服务分支 | 平台能力不足时提交能力缺口申请 |
| 业务 MCP/HTTP API | 开发方 | 定义严格合同、鉴权、幂等、费用限制和错误映射，返回结构化事实 | 要求 DClaw 保存开发方长期密钥，或绕过超级专家做最终业务决策 | 只向平台申请通用连接能力 |
| 第三方 API 选型和费用 | 开发方 | 控制调用次数、超时、降级和费用 | 由平台替 Agent 决定供应商 | 报告平台通用网络限制即可 |
| 超级专家源码 | 开发方 | 维护、测试、版本化并密封 | 把私有源码上传为可编辑普通 Agent | 使用平台规定的密封格式 |
| 能力清单 | 开发方声明，平台校验授权 | 最小化声明且满足依赖闭包 | 运行时临时加权或部分授权 | 新公共能力需平台发布版本 |
| 本地能力包 | 开发方 | 签名、Schema、权限、资源限制、回滚 | 修改 Runner 核心或建立第二套登录 | 使用公共本地执行协议 |
| DClaw UI、会话、登录、身份 | 平台方 | 提供统一客户入口和可信上下文 | 加入某个 Agent 的业务阶段 | 开发方用公开能力而非定制页面 |
| 密封验证、安装、授权、激活 | 平台方 | 验签、摘要、能力授权和原子切换 | 接受未信任签名或越权能力 | 开发方完成签名方入驻 |
| 通用交互卡 | 平台方 | 渲染、持久化、提交和可信回传 | 替 Agent 决定提问内容 | 开发方声明并调用交互能力 |
| 本地能力网关 | 平台方 | 在线、任务状态、检查点、追踪和协议兼容 | 选择业务能力或修改业务输入 | 开发方提供能力包合同 |
| 本地助手核心 | 平台方 | 安装、更新、连接、隔离和通用执行 | 内置某个 Agent 的业务流程 | 开发方包按声明被加载 |
| 公共协议与兼容 | 平台方 | 版本化、兼容窗口、迁移说明和测试夹具 | 静默改变字段语义 | 开发方提前验证新版本 |
| 业务验收和客户结果 | 开发方 | 证明真实业务结果达到约定 | 仅凭工具返回“成功”宣称业务成功 | 平台提供 trace 与运行证据 |

### 4.2 技术组件归属

| 技术组件 | 组织所有者 |
|---|---|
| 密封超级专家工作区 | 开发方 |
| Agent 业务 MCP、HTTP 服务和状态存储 | 开发方 |
| 第三方连接器、账号、Cookie、Token 和费用 | 开发方 |
| Agent 本地能力包 | 开发方 |
| DClaw 客户端、会话和身份 | DClaw 平台方 |
| 密封包验签、安装、授权、激活和回滚框架 | DClaw 平台方 |
| 公共交互、文件、AIGC 等平台能力 | DClaw 平台方 |
| 公共本地执行协议与网关 | DClaw 平台方 |
| 通用 Windows 本地助手核心 | DClaw 平台方 |
| 公共 Schema、审计、追踪和兼容框架 | DClaw 平台方 |

## 5. 判断能力应放在哪一侧

### 5.1 属于开发方的能力

满足任一条件即优先归开发方：

- 不能以同一公开合同提供给所有超级 Agent；
- 只对某个 Agent、行业、客户或供应商有完整意义；
- 包含业务阶段、评分、筛选、文案、审核或完成判据；
- 需要选择具体第三方供应商；
- 需要持有第三方长期凭证；
- 输入或输出以业务字段为核心；
- 变化频率由业务策略决定；
- 失败后是否重试取决于业务含义。

示例：选择具体第三方接口、筛选业务素材、判断素材是否合格、生成业务脚本、编排视频剪辑和制定渠道运营策略，均归开发方。

### 5.2 属于平台方的能力

同时满足下列条件才适合进入 DClaw 公共能力：

- 所有超级 Agent 都可以按同一公开合同声明、申请授权并调用；
- 不含行业名、Agent 名、供应商名和业务流程分支；
- 输入输出能够形成稳定、严格、版本化的通用合同；
- 平台能够统一实施身份、权限、隔离、审计和兼容；
- 能力进入平台后不会要求平台承担业务结果判断。

示例：通用选择卡、通用问答表单、会话上下文、通用本地任务生命周期、受控文件交付和统一错误追踪，归平台方。

“提供给所有超级 Agent”表示平台对所有超级 Agent 提供相同的能力声明、授权和调用机制。它不表示所有 Agent 默认获得权限，也不表示所有 Agent 必须使用该能力。租户授权、合同版本、操作系统、设备状态和资源配额仍可形成通用的使用条件，但平台不得按具体 Agent 名称、行业或供应商编写特例。

### 5.3 快速判定问题

提出平台改造前依次回答：

1. 删除 Agent 和供应商名称后，这个能力仍有完整意义吗？
2. 任意超级 Agent 能否在满足相同公开条件后原样使用合同？
3. 平台能否只校验技术正确性，不判断业务正确性？
4. 能否给出稳定 Schema、权限范围、幂等语义和失败语义？
5. 能否在不更新已有 Agent 的情况下兼容发布？

任一答案为“否”，通常应由开发方在超级专家、业务服务或本地能力包中实现，平台方不修改公共能力。

## 6. 标准交付架构

### 6.1 最小形态

业务只需要模型和平台公共能力时：

```text
密封超级专家
└── 调用获授权的 DClaw 公共能力
```

### 6.2 带业务服务

需要第三方 API、持久业务状态或确定性服务端逻辑时：

```text
密封超级专家
└── 开发方业务 MCP/HTTP 服务
    ├── 业务状态机
    ├── 第三方连接器
    ├── Secret 管理
    └── 业务审计
```

### 6.3 带本地执行

需要大文件下载、上传、视频剪辑、桌面软件、浏览器或高 CPU/内存任务时：

```text
密封超级专家
└── local_capability_gateway
    └── DClaw 本地助手核心
        └── Agent 本地能力包
```

没有本地重任务时，禁止创建空能力包或要求客户安装本地助手。

### 6.4 端到端开发阶段与门禁

第三方开发项目必须按以下顺序推进。阶段可以并行准备，但未通过当前门禁不得把状态报告为下一阶段完成。

| 阶段 | 开发方动作 | 平台方动作 | 必须产物 | 通过门禁 |
|---|---|---|---|---|
| 0. 启动 | 用第 27 节模板创建 Codex 任务，读取标准和源材料 | 提供目标平台版本与文档 | 任务范围、材料清单 | 目标和缺失材料可追踪 |
| 1. 行为规格 | 盘点主流程、异常、人工步骤和完成条件 | 回答现有公共能力范围 | `PRODUCT_SPEC.md` | 每条行为可测试 |
| 2. 边界设计 | 将功能分配到超级专家、业务服务或能力包 | 评审公共能力缺口 | `ARCHITECTURE.md`、能力申请 | 不存在业务逻辑下沉平台 |
| 3. 合同设计 | 定义业务 Schema、错误、幂等、状态和 manifest | 确认公共合同版本 | contracts、`ERROR_CATALOG.md`、manifest 模板 | 合同严格且能力闭包完整 |
| 4. 实现 | 实现密封工作区、必要业务服务和能力包 | 仅处理已接受的平台增强 | 源码与单元测试 | 业务主流程在测试环境通过 |
| 5. 集成 | 对接真实平台合同、第三方沙箱和本地助手 | 提供测试环境和 trace | 合同与集成测试证据 | 跨组件状态和错误可定位 |
| 6. 验收 | 从 DClaw 客户端走真实用户链路 | 保障测试平台可用 | 三个真实任务证据 | 连续成功且实际产物合格 |
| 7. 密封 | 计算能力摘要、签名并独立验包 | 确保签名者已入驻 | 签名 ZIP、校验和、发布记录 | 验签、摘要和运行时合同通过 |
| 8. 上传 | 使用管理员账号上传并核对元数据 | 执行平台验签和运行时验证 | release ID | 状态可进入授权阶段 |
| 9. 授权激活 | 核对能力预览、整体授权和激活 | 固化授权并原子切换 | installation ID、激活记录 | 新版为 `active` |
| 10. 发布后验收 | 再次执行冒烟和三个真实任务 | 提供审计和故障定位 | `e2e-verified` 证据 | 可向客户开放 |
| 11. 维护 | 监控业务质量、费用和第三方变化 | 维护公共能力和兼容窗口 | 变更记录、回滚包 | 每次发布重复门禁 |

任何平台增强都必须有独立版本和发布计划。开发方不得把“平台方已接受需求”视为能力已经可用，也不得在目标平台目录尚未发布时写入生产 manifest。

## 7. 成本与数据放置规则

### 7.1 默认放置

| 工作负载 | 默认位置 | 原因 |
|---|---|---|
| 对话、授权、任务控制和小型 JSON | DClaw/超级专家 | 便于统一身份与编排 |
| 第三方 API 决策与短请求 | 开发方业务服务 | 业务所有权和凭证安全 |
| 大文件下载 | 客户本地 | 避免服务器带宽和磁盘中转 |
| 视频剪辑、转码、压缩 | 客户本地 | 避免服务器 CPU、内存和磁盘成本 |
| 浏览器和桌面软件自动化 | 客户本地 | 依赖客户设备与登录状态 |
| 最终产物 | 默认客户本地 | 仅业务确需共享时受控上传 |

### 7.2 强制数据规则

- 服务端只传控制消息、元数据、小型结构化结果和短时授权。
- 第三方服务返回资源 URL 后，本地助手应从受信源站直接下载。
- 长期 API Key、Cookie、刷新令牌不得进入提示词、聊天消息、trace 或本地任务输入。
- 本地直连确需授权时，由业务服务签发最小权限、短时有效、限定资源的 URL 或令牌。
- 最终文件只有在明确业务需要、客户知情且平台能力允许时上传。
- 日志只记录摘要、状态、耗时、大小、错误码和脱敏标识。

## 8. 项目结构与命名

推荐每个超级 Agent 使用独立代码仓库或独立顶层目录：

```text
<agent-root>/
├── agent/
│   ├── agent.json
│   ├── runtime.py
│   ├── VERSION.json
│   ├── SOUL.md
│   └── skills/
├── business-service/             # 可选
├── capabilities/                 # 可选，本地能力包
├── contracts/                    # Agent 自有业务 Schema
├── docs/
│   ├── PRODUCT_SPEC.md
│   ├── ARCHITECTURE.md
│   ├── ERROR_CATALOG.md
│   ├── RELEASE.md
│   └── PORTING_RECORD.md          # 迁移项目需要
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   └── e2e/
├── tools/
├── manifest.template.json
├── CHANGELOG.md
└── README.md
```

### 8.1 命名规则

- `agent_id`：稳定、可读、表达业务语义，匹配 `[A-Za-z0-9_-]{1,128}`；发布后不得随意改变。
- 某个 Agent 的名称、拼音缩写或行业缩写只属于该业务，禁止作为所有超级 Agent 的公共前缀。
- 平台公共本地 MCP 客户端键固定为 `local_capability_gateway`。
- 平台公共工具使用能力目录中的稳定名称；新 Agent 禁止创建带自身业务前缀的公共工具。
- Agent 自有业务工具用业务动作命名，并置于开发方服务命名空间。
- 本地能力 ID 使用 `<业务域>.<对象>.<动作>`，例如 `video.material.compose`。
- 能力包 ID 应全局避免冲突，可用 `<开发组织>.<业务域>.<包名>`。
- 发布版本、能力包版本、业务 API 版本和平台协议版本分别维护，不得共用一个版本号代替全部版本。

### 8.2 工作区与源码追溯

- 独立 Git 仓库是可选项，不是开发前置条件。迁移任务没有明确要求时，只创建独立项目目录，不得为了满足模板自行初始化 Git 或配置远端。
- 使用 Git 时，发布证据记录 commit；不使用 Git 时，项目必须生成 `SOURCE_REVISION.json`，至少记录源包文件名、源包 SHA-256、采用的本标准版本、项目版本、生成时间和构建输入摘要。
- 用户已经提供迁移压缩包并指定私有迁移工作区时，视为已经授权安全解压和盘点，无须再次询问。解压前仍须检查绝对路径、`..` 路径穿越、符号链接逃逸和异常文件大小。
- 迁移暂存目录必须由任务明确提供，或由开发方在项目仓库之外创建私有临时目录。标准不得固定任何开发者姓名、机器目录或某个 Agent 的项目路径。
- 解压出的私有源包、凭证、运行时、模型、缓存和成品不得提交到 DClaw 仓库或 Agent 发布包。开发方应记录盘点结果，并按任务需要保留或安全删除暂存副本。

## 9. 开发前必须形成的四份规格

### 9.1 产品行为规格

`docs/PRODUCT_SPEC.md` 至少包含：

- 目标客户和业务目标；
- 支持与不支持的范围；
- 主流程和分支流程；
- 每一步所需输入、状态变化、输出和完成判据；
- 需要人工介入的时机；
- 至少三个成功案例；
- 已知失败、重试、取消和恢复案例。

迁移项目的产品行为规格必须来自源 Agent 的真实可执行行为，而不是重新设计目标产品。证据优先级固定为：可重复执行的源代码路径、自动测试、实际工具副作用和真实产物，高于说明文档、示例文案和开发者推测。说明文档与实际执行结果冲突时，以可执行证据为准，并把冲突、采用结论和证据位置写入 `SOURCE_BEHAVIOR_SPEC.md`。

### 9.2 架构规格

`docs/ARCHITECTURE.md` 必须列出每个能力放置位置、理由、数据流、凭证位置、成本位置和依赖方向。

### 9.3 错误目录

`docs/ERROR_CATALOG.md` 必须列出稳定错误码、技术失败层、组织责任方、是否可重试、客户提示、管理员动作和对应测试。

### 9.4 发布规格

`docs/RELEASE.md` 必须记录：

- 所有组件版本，以及 Git commit 或 `SOURCE_REVISION.json` 源码修订摘要；
- manifest 能力清单；
- 签名者 ID 和内容摘要；
- 自动测试与真实测试证据；
- 部署前置条件；
- 激活和回滚步骤；
- 已知限制。

从其他平台迁移时还必须按本文第 27.1 节维护 `PORTING_RECORD.md` 和 `SOURCE_BEHAVIOR_SPEC.md` 源行为基线。

## 10. 超级专家运行设计

### 10.1 确定性外壳

超级专家的 `runtime.py:create_runtime` 是业务回合的确定性入口。它必须：

1. 读取平台提供的可信会话上下文。
2. 解析当前业务状态和客户输入。
3. 校验当前动作是否允许。
4. 调用模型、平台能力或开发方业务服务。
5. 校验工具结果和业务完成条件。
6. 只调用一次 `runtime.complete` 或 `runtime.fail`。

模型输出只能作为候选，不得直接成为客户结果。结构化模型输出必须经过 Schema 和业务不变量校验。

### 10.2 Host 基础能力

每个 V1 超级专家必须声明完整的基础闭包：

- `workspace.turn.orchestrate/1`
- `agent.execute`
- `session.context`
- `runtime.trace`
- `runtime.complete`
- `runtime.fail`

`runtime.py:create_runtime` 必须返回具有 `async handle(request, host) -> None` 的对象。`request` 由平台构造，至少提供 `invocation_id`、`agent_id`、`release_id`、`installation_id`、`session_id`、`user_id`、`channel`、`normalized_input`、`history`、`safe_metadata`、`granted_capabilities`、`state_root` 和 `transaction_root`；开发方不得从客户输入伪造这些字段。

Host 调用合同：

| 调用 | 请求要点 | 成功结果 |
|---|---|---|
| `session.context` | `{}` | 当前可信会话上下文 |
| `agent.execute` | 至少传本轮 `messages`；需要完整工具循环时传 `execution_mode="agent_loop"` | 内部模型候选，不自动成为客户回复 |
| `runtime.trace` | 结构化、无 Secret 的诊断对象 | `{"accepted":true}` |
| `runtime.complete` | 当前 `invocation_id`、合法 assistant `message`、可选 `diagnostics` | `{"accepted":true}` 并原子提交 |
| `runtime.fail` | 当前 `invocation_id`、稳定 `error_code`、可选 `diagnostic_ref` | `{"accepted":true}` 并丢弃事务 |

`runtime.complete` 与 `runtime.fail` 每轮只能二选一调用一次。DevKit 的 `templates/minimal/agent/runtime.py` 是不依赖服务器源码的最小可运行示例。

### 10.3 状态设计

- 会话状态必须是可序列化结构，禁止依赖进程内对象作为唯一事实来源。
- 每个业务动作必须有明确前置状态、成功状态和失败状态。
- 重放同一客户事件不得产生重复收费、重复第三方任务或重复文件。
- 状态写入和客户可见完成必须原子化；失败时不得提交半成品状态。
- 新发布版读取旧状态时必须迁移或明确拒绝，禁止静默误读。

推荐状态机：

```mermaid
stateDiagram-v2
    [*] --> collecting
    collecting --> ready: 输入完整
    ready --> running: 幂等启动
    running --> waiting_user: 需要客户或本机操作
    waiting_user --> running: 可信回执继续
    running --> completed: 业务完成条件通过
    running --> failed: 不可恢复错误
    running --> cancelled: 客户取消
    failed --> running: 新的显式重试动作
```

## 11. 平台能力清单

能力清单是发布版权限边界，不是功能介绍。原则如下：

- 只声明代码实际需要的能力。
- 同一发布版的能力集合、版本和摘要不可变。
- 依赖能力必须完整声明。
- 管理员只能整体接受或拒绝签名清单，不得手工删改后授权。
- 新增能力必须发布新的超级专家版本并重新授权。
- 运行时调用未授权能力必须失败关闭。

当前公共能力目录由目标 DClaw 下载的 DevKit 内 `capability-catalog.json` 定义。常用组包括：

| 能力组 | 用途 | 开发入口 |
|---|---|---|
| `runtime` / `runtime_host` | 确定性回合编排 | 本文第 10 节与 DevKit 最小模板 |
| `interaction` | 单选、多选、开放问答卡 | 本文第 13 节与运行时实时组件目录 |
| `aigc` | DClaw 公共 AIGC 工作流 | 运行时 `aigc_workflow_catalog` 返回的实时 Schema |
| `local_execution` | 本地助手会话与任务 | 本文第 3.2 节和第 15-18 节 |

代码不得根据能力名称猜参数；使用前读取对应版本协议或实时目录。

使用公共 AIGC 时，超级专家必须通过 `agent.execute(execution_mode="agent_loop")` 调用按授权动态注册的 `aigc_workflow_catalog`、`aigc_workflow_create`、`aigc_task_status`、`aigc_task_resume` 和 `aigc_task_review`。先读取实时目录及 `WorkflowBlueprint` Schema，再创建或恢复任务；创建任务不等于生成完成，最终仍按真实任务状态和产物验收。未授权的工具不会注册，Agent 不得自行构造内部接口。

能力出现在 manifest 目录、文档或 Schema 中，只证明平台识别该能力声明，不证明对应运行服务已经生产可用。开发方必须同时核对目标环境的能力可用状态、生产入口和最低组件版本；平台未发布这些信息时不得自行猜测地址或把业务参考实现当作公共平台。

截至 2026-10-26，生产 Server 已运行提交 `f88e5554f9c9b281e47bdbc107b2030ec89b761a`，`dclaw.super-agent-support` `1.4.0` 已成功加载，生产镜像包含 Super Agent DevKit `1.2.0`、离线引导脚本和 26 个带哈希锁定的加密依赖 wheel。插件注册 `local.execution.session/1` 与 `local.environment.preflight/1`、可信工作区上下文、八个 `local_*` MCP 工具、设备配对与 WebSocket 调度、持久任务状态、能力包验签注册、凭证引用和通用 Windows 本地助手核心。DevKit 含独立 CLI、版本化 Schema、能力目录和最小模板，不导入或暴露 DClaw 服务端源码。DClaw Windows 客户端源码已加入按专家声明自动预检和顶部手动检测入口。DClaw 核心只保留通用插件 SPI；卸载插件会同时移除路由、能力和上下文处理器。

本标准 `2.0` 的正式开发与发布门禁如下。版本必须作为一个兼容组合核对，不能只满足其中一项：

| 项目 | 本标准要求 | 2026-10-26 正式环境核对 | 结论 |
|---|---|---|---|
| DClaw 核心 | 至少 `1.1.10` | 公网 `/api/version` 返回 `1.1.10`，运行镜像标记 Server 提交 `f88e555` | 满足 |
| 支持插件 | `dclaw.super-agent-support` `1.4.0` | 生产启动日志确认 `1.4.0` 成功加载 | 满足 |
| Super Agent DevKit | `1.2.0`，且由目标实例认证下载 | 生产镜像包含 `1.2.0` 和完整 wheelhouse；匿名访问按设计返回 `401` | 版本满足，开发方下载时仍须认证并核对 SHA-256 |
| Windows 客户端 | 至少 `2.6.12` | `2.6.11` | 不满足，先发布并升级客户端 |
| 通用 Runner | 至少 `1.0.0` | 随兼容客户端核对 | 待客户端升级后核对 |

正式公开入口：

| 功能 | 认证后的目标实例路径 |
|---|---|
| 插件健康与版本 | `GET /api/super-agent-support/health` |
| DevKit 元数据 | `GET /api/super-agent-support/developer-kit`，返回 `version`、`download_path` 和 `sha256` |
| DevKit ZIP | `GET /api/super-agent-support/developer-kit/v1.zip` |
| 本地执行 MCP | `/api/super-agent-support/mcp/`，Streamable HTTP |
| 客户端环境检测 | `GET /api/super-agent-support/environment-status` |
| 客户端配对 | `POST /api/super-agent-support/device-bootstrap` |
| 本地助手通道 | `/api/super-agent-support/devices/connect`，WebSocket 协议 `1` |
| 能力包注册 | `POST /api/super-agent-support/capability-packages/register` |
| 凭证绑定 / 撤销 | `POST /api/super-agent-support/credentials` / `DELETE /api/super-agent-support/credentials/{credential_ref}` |

上述接口属于认证后的目标 DClaw，不是匿名公共下载站。`401` 表示尚未携带有效身份，不能据此断言接口缺失；有效身份下 `404`、插件版本低于要求、返回的 DevKit 版本不匹配或 ZIP SHA-256 与元数据不一致，均表示当前目标环境未达到发布门禁。开发方只能继续源码和离线测试，状态标记为 `platform-tooling-missing`，不得使用平台仓库内源码副本、旧兼容构建器、历史签名包或其他环境下载的 DevKit 替代。

生产 Server、插件和 DevKit 已达到上述源码版本，但 Windows 客户端仍低于 `2.6.12` 门禁，Runner 兼容性仍须随客户端核对。开发方必须使用自己的认证会话实际下载 DevKit、核对服务端 SHA-256，并在上传前核对插件 Secret 与相应信任库配置；平台镜像中存在文件不能替代这些发布证据。任何历史 Agent 专属 Relay、Runner、工具前缀和能力 ID 只作为冻结兼容路径，不得被新发布复制或回退使用。

生产安装必须把插件 `state_dir` 放在持久卷，并通过平台 Secret 配置稳定的 `master_key_base64`；容器可使用 `DCLAW_SUPER_AGENT_SUPPORT_MASTER_KEY_BASE64`，该值解码后至少 32 字节，不得写入仓库、镜像或 Agent 包。`trusted_package_signers` 是 `signer_id` 到原始 Ed25519 公钥 Base64 的映射。未配置受信公钥时，插件仍可启动和提供环境状态，但所有能力包注册必须失败关闭。

## 12. Manifest 标准

超级专家 manifest 必须使用 `schema_version: 3`、`agent_type: sealed`、`scope: global`，且 `package_type` 为 `super_expert`。

最小示例：

```json
{
  "schema_version": 3,
  "agent_id": "example-business-agent",
  "name": "示例业务专家",
  "version": "1.0.0",
  "agent_type": "sealed",
  "scope": "global",
  "entrypoint": "agent/agent.json",
  "package_type": "super_expert",
  "orchestration": {
    "capability_id": "workspace.turn.orchestrate/1",
    "contract_version": "1",
    "entrypoint": "runtime.py:create_runtime",
    "required_host_capabilities": [
      "agent.execute",
      "session.context",
      "runtime.trace",
      "runtime.complete",
      "runtime.fail"
    ]
  },
  "platform_contract_versions": {
    "runtime": "1",
    "runtime_host": "1",
    "interaction": "1",
    "local_execution": "1"
  },
  "capabilities": [
    {"capability_id":"workspace.turn.orchestrate/1","contract_version":"1"},
    {"capability_id":"agent.execute","contract_version":"1"},
    {"capability_id":"session.context","contract_version":"1"},
    {"capability_id":"runtime.trace","contract_version":"1"},
    {"capability_id":"runtime.complete","contract_version":"1"},
    {"capability_id":"runtime.fail","contract_version":"1"},
    {"capability_id":"interaction.capabilities.list/1","contract_version":"1"},
    {"capability_id":"interaction.card.create/1","contract_version":"1"},
    {"capability_id":"interaction.card.cancel/1","contract_version":"1"}
  ],
  "capability_digest": "sha256:<由工具计算的64位十六进制摘要>",
  "signer_id": "approved-developer-signer",
  "public_metadata": {
    "description": "示例业务专家",
    "tags": ["example"]
  }
}
```

说明：

- 不使用交互卡时删除相应组和能力；不使用本地助手是默认行为，不声明任何 `local.*` 能力。
- 可选使用本地助手时声明 `local.execution.session/1`；只有实际调用本地能力前才检查。
- 必须使用本地助手时同时声明 `local.execution.session/1` 与 `local.environment.preflight/1`；后者依赖前者，客户端在进入该专家时统一预检。
- 能力摘要必须通过官方 DevKit 的 `digest --write` 计算，禁止手工拼接或导入平台源码。
- `content_digest` 不写入模板，由密封构建工具根据包内容生成。
- `entrypoint` 必须位于 `agent/` 下。
- `orchestration.entrypoint` 必须与 `agent/agent.json` 中的运行入口一致。
- 能力 ID 和合同版本必须存在于目标 DClaw 版本的公共目录中。

## 13. 基础交互卡设计

DClaw 平台负责卡片持久化、渲染、提交和可信回传；开发方负责业务问题、选项、输入策略和收到答案后的业务动作。

超级专家通过 `agent.execute` 的 `execution_mode="agent_loop"` 使用平台按授权动态注册的四个模型工具：

| 工具 | 用途 |
|---|---|
| `interaction_component_catalog(component_types=[])` | 读取实时组件目录；创建前必须按确定的组件类型再次读取详细 Schema |
| `interaction_card_create(...)` | 以稳定 `task_key`、正整数 `interaction_revision`、`component_type`、`card` 和输入策略创建卡片 |
| `interaction_card_status(interaction_id="")` | 查询指定卡片或当前活动阻塞卡 |
| `interaction_card_cancel(interaction_id, operation_key)` | 以稳定操作键取消仍为 `PENDING` 的卡片 |

请求采用实时目录返回的严格 Schema，未知字段必须拒绝。成功证据只有真实 `interaction.interaction_id` 与 `PENDING` 状态；工具参数、组件字段和枚举不得从平台源码或模型记忆中猜测。

强制规则：

- 可穷举且只能选一项时使用 `single_select`。
- 可穷举且允许多项时使用 `multi_select`。
- 无法可靠穷举时使用 `question_form`。
- 上传素材使用文件或素材能力，禁止用文本问题伪装上传。
- 创建卡片前读取实时组件目录。
- 业务问题和选项写入 `card`，不要在正文重复。
- 只有返回真实 `interaction_id` 和 `PENDING` 才视为创建成功。
- 客户提交必须通过可信卡片事件进入状态机，不能根据自由文本猜客户已点击。
- 同一逻辑问题保持稳定 `task_key`；内容变化时递增 `interaction_revision`。

迁移项目的默认交互规则：

1. DClaw 卡片是唯一面向客户的业务入口。源包的命令行和 JSON 入口只保留为内部适配层或自动测试入口，不继续作为客户操作方式。
2. 开发方先从源包的真实输入合同推导卡片字段、默认值和必填关系，并复用客户已经提供的值；不得把能从源代码、示例或历史输入确定的字段重新问客户。
3. 只有新增选择会改变产品行为、费用、数据去向或不可逆操作时才需要确认卡片方案。纯展示名称、字段顺序和已有默认值由开发方直接完成。
4. 源流程能够自动检索素材时，不得为了套用上传组件而要求客户人工上传素材。只有源行为本来需要客户文件，或自动检索失败后的产品规则明确允许上传，才展示素材上传入口。
5. 客户可见字段使用自然名称和值，不展示 `G1`、`G2` 等内部编号。迁移输入中包含这类编号时，仅把它当作源字段定位信息，最终卡片仍以业务名称呈现。

## 14. 业务服务与第三方 API

### 14.1 服务合同

开发方业务服务的每个动作必须定义：

- 请求和响应 JSON Schema；
- 鉴权主体和权限范围；
- 幂等键；
- 超时、重试、限流和熔断；
- 副作用发生时点；
- 查询和取消方式；
- 稳定错误码及平台错误映射；
- 费用计量与调用次数上限。

### 14.2 第三方调用节省原则

- 能用一次搜索接口返回候选时，禁止逐候选重复搜索。
- 先用元数据筛选，再调用高价解析或生成接口。
- 对无副作用查询使用有时效缓存，缓存键必须包含影响结果的全部条件。
- 重试复用同一幂等键；非幂等接口先查询再决定是否重发。
- 设定每个客户任务的最大调用次数和最大费用。
- 达到预算、余额不足、Token 无效或供应商限流时返回明确错误，不继续盲目调用。
- 供应商原始响应只写入受控诊断日志，不直接显示给客户。

### 14.3 凭证规则

- 长期凭证保存在开发方 Secret 管理系统。
- 仓库、manifest、密封包、提示词、测试夹具和日志中不得包含真实凭证。
- 客户账号登录状态若必须在本地浏览器中使用，应由本地能力包读取受控会话，不上传 Cookie。
- 客户可修复的凭证错误应显示“凭证无效、余额不足或授权过期”等可行动说明。
- 密钥轮换不得要求重新发布 Agent，除非权限范围发生变化。

迁移包内已经包含凭证时，以下规则同时适用：

1. 用户把含凭证的源包作为迁移输入交给开发方，表示开发方可以在受控环境读取这些值，用于识别供应商、完成安全迁移和真实调用验证；开发方不得以“发布包不能含密钥”为由忽略或删除这些值。
2. 读取过程不得把值打印到聊天、终端回显、日志、报告或测试快照。盘点记录只写供应商、用途、所有者、权限范围、环境和迁移状态。
3. 开发方拥有并供所有客户共用的第三方服务凭证，迁移到开发方业务服务的加密 Secret 管理系统；超级专家通过业务服务取得结果或短时资源 URL，不读取长期值。
4. 每位客户自己的 OAuth、Cookie 或账号凭证，迁移到 DClaw 已发布的客户凭证绑定能力或供应商官方授权流程，并按客户、安装和权限范围隔离。
5. 只有本地能力必须直接使用的短时凭证，才通过已授权通道注入本地任务；任务结束后删除。长期明文仍不得写进能力包。
6. 迁移完成后必须用新存储位置完成至少一次真实调用。源包若曾分发给非受控对象、进入日志或无法排除泄露，生产激活前必须轮换凭证；密封包和能力包发布前执行 Secret 扫描。

“可以读取迁移凭证”和“禁止把凭证放进签名发布包”解决的是两个不同阶段的问题，必须同时满足。前者保证迁移后的产品能运行，后者避免同一个长期密钥随 ZIP 分发到每台客户电脑。

### 14.4 业务 MCP 鉴权与当前平台可用性

密封超级专家包只能声明业务 MCP 的公开连接信息和鉴权需求，例如 URL、OAuth `client_id`、`scope` 或待绑定的 Secret 名称。长期访问令牌、刷新令牌、API Key、服务令牌和客户端密钥不得写入 `headers`、`env`、OAuth 配置、提示词或密封包中的任何文件。

平台正式支持的业务 MCP 鉴权必须满足：

- 客户 OAuth 凭证按租户、用户、Agent 安装和 MCP 服务隔离；
- OAuth Token 加密保存并支持刷新、撤销和过期处理；
- 调用时由 DClaw 运输层注入短期访问令牌，模型和 Agent 工作区不可读取；
- 开发方服务身份通过管理员绑定的受控 Secret 或短期凭证交换获得；
- Secret 绑定到具体安装、目标服务和权限范围，不能被其他 Agent 引用；
- 密钥轮换不修改签名包内容；
- 日志、trace、错误和管理 API 只返回脱敏状态。

截至 2026-10-23，DClaw 的通用 MCP 客户端已有 OAuth 2.1 PKCE 授权流程和 Bearer Header 注入，但其现有 Agent 配置存储仍不构成密封全局超级专家的按用户 OAuth 合同。`dclaw.super-agent-support` `1.4.0` 的凭证引用只解决客户凭证向已授权本地能力包注入：密文按用户、安装、Agent 和 scope 绑定，Agent 只传不透明 `credential_ref`，明文只通过已认证设备通道送入本地助手并在子进程结束后删除，管理 API 支持撤销。

开发方业务服务自身调用第三方 API 时，长期 Token 属于开发方业务服务，应保存在开发方 Secret 管理系统；不需要上传 DClaw，也不需要经过 DClaw Credential Broker。若业务 MCP 必须使用每位客户自己的 OAuth 身份，当前插件 `1.4.0` 仍未发布按用户 OAuth 刷新和 MCP 运输层注入，开发方必须保持生产构建失败关闭并提交通用能力申请，不能把 Token 写回密封包。

在所需鉴权方式尚未正式发布前：

1. 需要业务 MCP 鉴权的新超级专家不得进行生产构建和上传。
2. 开发方可以保留不含 Token 的 OAuth `client_id`、`scope` 等声明并完成合同测试。
3. 本地测试凭证必须由测试环境外部注入，并在构建前执行发布包 Secret 扫描。
4. 生产构建缺少安全凭证绑定时必须失败关闭。
5. 禁止为赶进度回退到密封包内嵌长期 Token、API Key 或静态服务 Header。
6. 已发布且包含长期凭证的包必须停止继续分发；完成安全替代后撤销旧发布版并轮换凭证。

### 14.5 安装级业务服务身份

供应商长期 Secret 与“DClaw 安装调用开发方业务服务的身份”是两类凭证：

- 供应商 Secret 只保存在开发方业务服务的 Secret 管理器，由服务端连接器使用；超级专家密封包、本地助手、能力包和客户设备都不得持有。
- 安装级服务身份只用于证明某个已授权的 Agent 安装可以调用指定开发方服务及 scope，不得等同于供应商 Secret，也不得把供应商 Secret 作为 Bearer Header 交给超级专家。

正式安装级身份必须采用以下任一公开合同：

1. 管理员把 Secret 绑定到具体租户、Agent、安装、目标服务和 scope，DClaw 运输层在请求边界注入，模型、超级专家工作区和本地任务不可读取明文；或
2. DClaw 使用平台签名的安装断言向开发方服务交换短时访问令牌，令牌限制目标服务、scope、安装、有效期和重放窗口，并支持轮换、撤销与审计。

静态服务 Bearer、客户端密钥或长期 Token 禁止进入 manifest、Agent 配置、提示词、卡片和本地任务输入。截至插件 `1.4.0` / DevKit `1.2.0` 的已核对材料，尚无可供开发方独立使用的安装级业务服务身份能力 ID 与 Schema。依赖该身份的新 Agent 可以完成源码、业务服务和合同测试，但生产密封与上传必须失败关闭，并按第 25 节提交通用能力申请；开发方不得直接修改平台或以内嵌 Secret 绕过门禁。

## 15. 本地助手协作标准

### 15.1 本地助手的定位

DClaw 桌面版是唯一用户入口，也是唯一登录入口。本地助手是客户端的工具箱：

- 客户不在本地助手中再次登录 DClaw；
- 本地助手不提供第二套登录；本地助手不得再次要求登录；
- 客户不输入第二套绑定码；
- 首次需要时由 DClaw 客户端引导安装并建立设备上下文；
- 本地助手不展示另一套业务流程；
- Runner 核心不理解业务字段，不选择第三方 API，不判断业务结果；能力包只理解其签名合同内的结构化技术字段。

### 15.2 超级专家与本地执行的职责分工

本节中的“超级专家侧”以密封超级专家为业务决策主体，并可以调用开发方自行维护的业务服务；“本地执行侧”包括 DClaw 通用 Runner 核心和运行在其中的 Agent 专属能力包。业务服务与能力包都属于开发方交付组件，但不能因此代替超级专家承担产品决策；Runner 核心属于平台，能力包属于开发方，两者不得混为同一份代码。

总原则：超级专家决定做什么、为什么做、使用哪些业务来源、如何选择和评分素材、如何编辑、何时返工以及什么结果才算完成；业务服务执行已经确定的第三方调用并返回结构化事实；本地执行侧只在客户电脑上完成已经确定的高带宽、高算力或设备侧技术任务，并返回可验证的技术结果。能力包可以根据硬件选择线程数、编码器、缓存和技术重试参数，但不得选择业务供应商、改变业务目标、筛选业务素材或判断内容是否符合客户要求。

能力包可以理解自己签名声明的技术领域，例如媒体文件、时间轴、字幕、语音识别、编码参数和技术质量规则，也可以在该领域内生成确定性的执行子计划。它不得解释客户的开放式自然语言、选择供应商或素材来源、改变内容目标，或代替超级专家做最终业务验收。Runner 核心始终与业务无关，只负责安装、隔离、调度、状态、权限和资源控制。

| 工作内容 | 超级专家侧职责 | 本地执行侧职责 |
|---|---|---|
| 理解客户需求 | 解析意图、维护业务上下文、确定缺失字段 | 不解释自然语言，不补业务字段 |
| 与客户交互 | 决定何时提问、问题内容、选项和后续动作 | 只报告需要人工操作的技术检查点 |
| 业务流程编排 | 决定步骤、顺序、分支、降级、终止和恢复策略 | 按一个已确定的任务合同执行，不自行改变流程 |
| 第三方服务 | 选择供应商和接口，决定业务重试；业务服务保管 Token、执行调用并控制技术限流与费用 | 仅在合同明确要求客户本机会话时访问允许的目标 |
| 素材搜索与筛选 | 决定搜索来源、关键词、优先级和合格标准，筛选候选 URL | 不决定搜索哪个平台，不判断素材是否适合业务 |
| 大文件传输 | 提供受信 URL、校验信息和目标用途，不中转文件内容 | 从源站直接下载、断点续传、校验并管理本地缓存 |
| 浏览器与桌面软件 | 决定何时需要该能力以及操作目标 | 打开和保持本机会话，执行自动化并检测登录、验证码或滑块 |
| 人工验证 | 向客户展示检查点，收到客户操作结果后决定继续或放弃 | 保持或恢复现场，返回 `checkpoint_id`，继续前重新验证真实状态 |
| 剪辑、转码、压缩 | 生成脚本、镜头表、参数和业务验收条件 | 调用本机工具执行计算，管理素材、中间文件和成品 |
| 语音识别与媒体分析 | 决定分析目的、语言策略及如何使用识别结果 | 在本机运行 Whisper、抽帧和媒体探测，返回带时间戳的结构化事实 |
| 技术结果验证 | 根据结构化结果决定下一业务动作 | 验证文件存在、摘要、格式、可解码性、尺寸、时长和进程退出状态 |
| 业务结果验收 | 判断内容、顺序、文案和成品是否满足客户目标 | 不根据业务含义宣称成功，只返回技术事实和错误 |
| 重试与降级 | 决定更换来源、供应商、素材或业务方案 | 只执行合同允许的网络重试、进程重启和幂等恢复 |
| 文件交付 | 决定哪些文件是最终成品以及如何向客户说明 | 把成品放在任务根目录，返回路径、摘要和媒体元数据 |
| 客户回复 | 汇总状态、解释失败、确认业务完成 | 不直接生成业务回复，不展示第二套业务界面 |

开发方必须在开始编码前把每个步骤归入上表的一侧，并写入项目 `ARCHITECTURE.md`。素材选择/评分、编辑决策、客户交互和 DClaw 卡片调用必须逐项出现在超级专家侧，不能只写成不透明业务服务或能力包动作。以下规则是强制门禁：

1. 传给本地任务的输入必须是已确定的结构化参数；禁止把模糊自然语言需求交给能力包自行理解。
2. 本地任务只返回状态、检查点、错误、产物路径和必要元数据；禁止把大文件内容经 DClaw 服务端回传。
3. 技术成功不等于业务成功。本地任务返回 `succeeded` 后，超级专家仍须核对业务完成条件。
4. 业务失败不应伪装成本地执行失败。例如“没有合格素材”由 Agent 侧报告；下载损坏、编码失败或浏览器会话丢失才属于本地能力错误。
5. 如果某一步既包含业务判断又包含本地重任务，必须拆成“Agent 生成确定任务参数 → 本地执行 → Agent 验收结果”三个阶段。

以需要在线素材和本地剪辑的视频 Agent 为例，标准链路必须是：

1. 超级专家理解主题和客户要求，并由业务服务调用素材检索 API。
2. 超级专家按业务规则选择来源、筛选素材，只把最终候选 URL、脚本、镜头顺序和输出参数交给本地能力包。
3. 本地能力包在客户 Windows 上直接下载候选素材并完成剪辑、转码和文件校验；服务端不下载、不上传、不剪辑视频。
4. 遇到登录、验证码或滑块时，本地能力包返回检查点并保持现场；超级专家负责提示客户，客户完成后再调用继续接口。
5. 本地能力包返回成品路径、SHA-256、大小、时长、分辨率和技术状态；超级专家依据业务要求决定接受、重做或更换素材。
6. 只有超级专家确认业务条件满足后，才向客户报告生成成功。

### 15.3 八个公共工具

每个超级专家通过签名能力清单声明本地助手需求，平台不根据专家名称或业务描述猜测：

| 声明 | 模式 | 客户端行为 |
|---|---|---|
| 不声明 `local.*` | `none`，默认值 | 不检测、不启动本地助手 |
| 只声明 `local.execution.session/1` | `optional` | 实际调用本地能力前检测 |
| 再声明 `local.environment.preflight/1` | `required` | 进入该专家时由客户端统一检测、配对并启动 |

判定标准：

- `optional` 只适用于没有本地助手时仍能完成全部核心承诺的 Agent。本地能力只能改善速度、质量、批量规模，或服务客户明确选择的非必需分支；进入该分支前再检测环境，拒绝或不可用时必须保留可完成的核心流程。
- `required` 适用于任一核心承诺依赖本地下载、上传、FFmpeg、Whisper、模型推理、视频渲染、桌面/浏览器、客户设备文件、高 CPU/内存处理或本地成品。缺少本地助手时主流程不能真实完成，因此进入专家即预检。
- 不得为了减少安装提示把真实必需能力声明成 `optional`，也不得为了统一实现让纯对话或纯服务端 Agent 无条件安装本地助手。

旧版超级专家没有 `local.environment.preflight/1` 时保持兼容：未声明本地会话能力视为 `none`，只声明本地会话能力视为 `optional`。`local.environment.preflight/1` 只表达运行前要求，不增加业务工具，也不替代 `local_environment_status`。客户端顶部必须提供“检测本地助手”手动入口，供客户随时检查安装、启动、连接和 Runner 版本；手动检测不改变任何专家的声明或授权。

旧版中实际无法脱离本地助手运行的专家必须发布新版本，增加 `local.environment.preflight/1`，重新计算能力摘要并由管理员重新授权；平台不得根据旧专家名称或行业自动提升为 `required`。

迁移时由开发方根据源包自动判断本地助手模式，不向用户提出抽象选择题。源包出现大文件直接下载、FFmpeg、Whisper、本地 Python 运行时、视频剪辑、桌面软件、浏览器自动化、高 CPU/内存处理或本地成品时，默认判定为 `required`，同时声明 `local.execution.session/1` 和 `local.environment.preflight/1`。目标操作系统先沿用源包已经支持的平台；Windows x64 源包默认只声明 `windows-x64`，后续真实需要其他系统时再发布兼容版本。

V1 固定流程：

1. `local_environment_status`
2. `local_capabilities_list`
3. `local_runtime_prepare`
4. `local_task_start`
5. `local_task_status`
6. `local_task_continue`
7. `local_task_cancel`
8. `local_task_result`

前三步完成环境与能力准备；中间步骤管理任务；最后一步只在终态读取结果。精确请求和响应以 DevKit 内 `schemas/local-execution-v1/tool-call.schema.json` 和 `schemas/local-execution-v1/tool-response.schema.json` 为准。

### 15.4 标准调用示例

```json
{
  "tool": "local_task_start",
  "arguments": {
    "capability_id": "video.material.compose",
    "idempotency_key": "job-20261020-001-rev1",
    "input": {
      "source_urls": ["https://trusted.example/video/1"],
      "title": "客户确认后的标题",
      "output": {"format": "mp4", "width": 1080, "height": 1920}
    }
  }
}
```

`dclaw_session_token` 由平台注入，开发方不得要求客户填写，也不得从普通消息中读取。

成功响应：

```json
{
  "standard": {"id": "dclaw.local-execution", "version": "1.0"},
  "ok": true,
  "trace_id": "trace_01J...",
  "data": {"task_id": "task_01J...", "status": "queued"}
}
```

顶层 `ok=true` 只表示工具调用成功。若 `data.status=failed`，本地任务仍然失败，超级专家必须读取 `data.error`，禁止对客户宣称已完成。

### 15.5 V1.1 环境与准备合同

DClaw 客户端负责安装、携带、启动、绑定、重连和升级通用本地助手。超级专家不得下载安装器、展示绑定码、拼接 Runner 连接地址或建立第二套安装流程。`local_environment_status` 只返回状态和客户下一步动作：

| `state` | `reason` | `user_action` | 含义 |
|---|---|---|---|
| `ready` | `none` | `none` | 至少一个已登录客户的兼容 Runner 在线 |
| `device_not_ready` | `no_paired_device` | `open_dclaw` | 客户端尚未完成自动设备配对 |
| `device_not_ready` | `device_offline` | `open_dclaw` | 已有设备记录但当前没有在线连接 |
| `runner_update_required` | `runner_version_too_old` | `update_dclaw` | 在线 Runner 低于平台最低版本；通过更新 DClaw 客户端处理 |
| `protocol_incompatible` | `protocol_version_mismatch` | `contact_administrator` | Agent 请求的本地执行协议与平台不兼容 |

环境响应固定包含 `state`、`reason`、`protocol_version`、`compatible`、`minimum_runner_version`、`bootstrap_session_id`、`user_action` 和 `devices`。每个设备摘要固定包含 `device_id`、`display_name`、`runner_version`、`online` 和 `last_seen`。

`wait_seconds` 为 0 到 25 秒的设备连接长轮询；没有在线设备时，插件在期限内等待 DClaw 客户端自动连接。`bootstrap_session_id` 只是由调用方提供并由响应原样回传的兼容关联值，不授予身份、配对或安装权限。`compatible` 只表示请求的协议版本是否与平台协议一致，不表示设备当前在线。V1.1 不返回 `installer`、`connect_url`、绑定码或任何下载地址。

历史 Agent 专属 Relay 的 `runner_required`、`binding_required` 和顶层 `device_offline` 不是平台状态枚举。旧实现中的 `device_offline` 只对应上述 `device_not_ready` + `reason=device_offline`。

`local_capabilities_list` 响应固定包含：

- `catalog_version="1"`；
- `availability="available"|"device_not_ready"`；
- `capabilities`，每项包含 `capability_id`、合同 `version`、`package_id`、`package_version`；
- `device_count`，表示本次查询命中的在线设备数。

`local_runtime_prepare` 状态固定为：

| `state` | `user_action` | 含义 |
|---|---|---|
| `ready` | `none` | 目标签名能力包的准确版本已安装 |
| `preparing` | `wait` | Runner 正在自动下载、验证并原子安装目标版本 |
| `device_not_ready` | `open_dclaw` | 当前没有在线设备 |
| `runner_update_required` | `update_dclaw` | Runner 低于能力包声明的 `min_runner_version` |

准备响应固定包含 `state`、`capability_id`、`package_id`、`package_version`、`min_runner_version`、`device_id`、`runner_version` 和 `user_action`。平台不使用旧 Relay 的 `runtime_update_required`：能力包准备无需客户另行确认，版本不一致时返回 `preparing` 并由 Runner 自动更新。

### 15.6 V1.1 任务状态

本地任务公开状态只允许：

```text
queued | running | awaiting_input | cancelling | succeeded | failed | cancelled
```

检查点事件必须把任务置为 `awaiting_input`。`local_task_continue` 只接受该状态且 `checkpoint_id` 与最新检查点一致的任务，受理后恢复为 `running`。历史内部值 `waiting_for_input` 在插件状态库初始化时迁移为 `awaiting_input`；标准正文旧称 `waiting_user` 只描述产品状态机，不得作为工具响应值。

## 16. 本地能力包标准

每个能力包必须包含：

- 稳定 `package_id`、`capability_id` 和语义版本；
- 输入 Schema、结果 Schema 和检查点 Schema；
- `min_runner_version`、本地执行合同版本和所需特性；
- `artifact.url`、`artifact.sha256`、`artifact.size_bytes` 和可执行入口；
- 输入、结果、检查点 Schema 的相对路径和 SHA-256；
- 操作系统和硬件要求；
- 文件、进程、网络、浏览器、摄像头等权限声明；
- 网络域名或地址允许列表；
- CPU、内存、磁盘、并发和最大执行时间限制；
- 幂等、副作用、取消、恢复和清理语义；
- `outputs` 与 `resources` 的明确区分；
- 稳定公开错误；
- 包签名、校验和及回滚版本。

FFmpeg、FFprobe、Python Runtime、Whisper 引擎、模型和其他只服务本地重任务的依赖属于本地执行侧，不进入超级专家密封包或 DClaw 服务端，也不作为所有 Agent 共用的 Runner 内置内容。开发方声明准确依赖、版本、来源、摘要和许可证；本地助手负责按需下载安装、校验、缓存、升级、原子切换和回滚。V1 中 Runner 统一安装能力 artifact；能力包内部的资源管理器按下述“受签名描述符和 artifact 摘要保护的资源清单”管理大型依赖。

### 16.1 大型依赖与按需安装

当前 V1 能力描述符的单个 `artifact.size_bytes` 上限是 `536870912` 字节。源包超过该上限时，开发方不得原样注册，也不得默认要求 DClaw 服务端扩大限制或承担大文件托管。按以下顺序处理：

1. 删除重复运行时、开发工具、缓存、测试成品和未使用模型，生成最小可执行能力包。
2. 能独立版本化的功能拆成多个签名能力包，只准备当前任务真正需要的最小集合。
3. 大模型或第三方运行资源从开发方控制的 HTTPS 地址按需下载到客户电脑；下载域名必须同时出现在能力描述符允许域和签名资源清单中。
4. 资源清单必须固定 `resource_id`、版本、URL、压缩与解压大小、SHA-256、目标相对目录、SBOM、许可证文件、缓存键、最低能力包版本和回滚版本。清单放入能力 artifact，由签名描述符中的 `artifact.sha256` 传递保护，不得宣称资源 ZIP 本身具有独立平台签名。
5. 下载后先校验大小与 SHA-256，再安全解压到临时目录；许可证或 SBOM 缺失、路径逃逸、摘要不符、磁盘不足时失败关闭。校验通过后原子切换当前版本，旧版本至少保留到新版本完成一次成功任务。
6. 已校验且版本、摘要相同的本地资源允许复用；升级失败自动继续使用上一兼容版本，清理不得影响其他 Agent 或正在执行的任务。
7. 只有上述方式无法满足多个无关 Agent 的共同需求时，才按第 25 节申请平台通用资源合同或调整上限。

DClaw 服务端只保存描述符、签名、状态和小型元数据。能力包二进制和大型依赖默认由开发方 HTTPS 或对象存储提供，本地助手直接下载，避免经过 DClaw 服务端上传、转发或缓存。任何尚未进入已签名描述符或其 artifact 内签名资源清单的 ZIP 只能称为“未签名资源构建输入”，不得称为正式能力包、资源包或已发布依赖。

### 16.2 Windows 目录

```text
%LocalAppData%\DClawLocalTool\
└─ tasks\
   └─ <Agent 显示名称>\
      └─ <任务时间-任务短编号>\
         ├─ <客户可直接使用的成品>
         └─ res\
            └─ <素材、缓存、中间文件、日志和任务元数据>
```

强制规则：

- DClaw 会话上下文提供 `Agent 显示名称`，本地助手不得硬编码或猜测。
- 客户成品直接放在任务目录第一层并列入 `outputs`。
- 素材、缓存、中间文件和诊断等过程资源放在 `res` 并列入 `resources`。
- 失败任务不得把半成品放到任务根目录。
- 能力包不得自行创建 Agent 专属 Runner、常驻登录客户端或平台根目录。
- 任务清理不得删除其他 Agent 或其他任务的文件。

### 16.3 人工操作检查点

浏览器登录、滑块验证、验证码、文件选择等需要客户操作时，能力包必须：

1. 保持任务为 `awaiting_input`，不得报为失败或完成。
2. 返回稳定 `checkpoint_id`、安全说明和允许的继续输入 Schema。
3. 保持或可恢复所需浏览器和任务上下文。
4. 客户完成后由超级专家调用 `local_task_continue`。
5. 继续前重新验证真实状态，不能只相信“已完成”文字。
6. 超时后给出明确恢复或重新开始方式。

### 16.4 产物与清理默认值

- 客户可直接使用的最终成品保存在任务根目录，默认不上传 DClaw；返回结构化路径、SHA-256、大小和媒体元数据，并由客户端提供打开文件或目录的动作。
- 脚本、字幕、封面、工程文件和诊断报告只有在产品规格承诺交付时才进入 `outputs`；其余过程文件放入 `res`。
- 技术成功后，最终成品持续保留到客户主动删除；`res` 默认保留 7 天用于重试和追溯，之后由 Runner 自动清理。
- 失败或取消后保留可复用中间资源和诊断 7 天，不立即销毁；客户可以随时执行安全清理。涉及敏感凭证的临时文件在任务或子进程结束时立即删除，不适用 7 天规则。
- 只有产品明确要求 DClaw 内预览或跨设备下载时才上传临时副本，默认 24 小时过期，并支持立即删除。上传失败不得导致本机已生成成品重新制作。

### 16.5 V1 描述符与签名

正式能力包描述符必须通过 DevKit 内 `schemas/super-agent-support-v1/capability-descriptor.schema.json`。候选状态、缺少下载地址、缺少包 SHA-256、缺少 Schema SHA-256、缺少入口程序或最低 Runner 版本的描述符不能注册。

V1 的签名对象是完整能力描述符，不是单独对 ZIP 字节再附一份签名。签名输入为描述符的 UTF-8 规范 JSON：对象键按字典序排序，分隔符固定为 `,` 和 `:`，不含额外空白。开发方用获“能力包签发”授权的 Ed25519 私钥签名并把签名编码为 Base64；插件只使用 `trusted_package_signers[signer_id]` 信任库验证。

描述符签名覆盖 `artifact.url`、`artifact.sha256`、`artifact.size_bytes`、入口、权限、资源限制和三个 Schema 文档，因此能力 ZIP 由签名描述符中的 SHA-256 绑定。三个 `schemas.*.document` 是签名合同，服务端用它们校验任务输入、检查点和结果；Runner 校验 ZIP 大小和摘要、阻止路径穿越、核对三个 Schema 文件摘要与签名文档，并且只能从已校验 ZIP 的安全相对路径启动 `entrypoint`。

外部按需资源 ZIP 不是 V1 平台可注册的独立能力包。它必须由能力 artifact 内受保护的资源清单绑定，能力包在本地逐项执行 HTTPS、允许域、大小、SHA-256、SBOM 和许可证校验。若希望平台和 Runner 直接注册、验签和管理独立资源包，需要先按第 25 节新增通用资源描述符与信任合同；在该合同发布前不得自行发明 `resource package` 注册格式。

注册请求只提交描述符、`signer_id` 和签名：

```json
{
  "descriptor": {"descriptor_version":"1", "capability_id":"example.video.compose"},
  "signer_id": "example-developer",
  "signature": "<base64-ed25519-signature>"
}
```

示例只展示外层信封，`descriptor` 必须包含 Schema 要求的全部字段。注册成功不等于客户端已安装；超级专家先调用 `local_runtime_prepare`，Runner 校验下载大小和 SHA-256、阻止 ZIP 路径穿越并原子安装，然后通过 `capabilities.report` 报告可用版本。

正式注册顺序固定为：完成许可证审计与 SBOM → 托管 HTTPS artifact/资源 → 计算最终大小和 SHA-256 → 生成最终描述符及包内资源清单 → 使用能力包 signer 签名描述符 → 管理员注册描述符 → Runner `local_runtime_prepare` 下载验证 → 报告准确版本 → 真实任务验收。更改任一 artifact 或资源内容都必须产生新摘要和版本，并重新签名；只替换同 URL 文件属于发布违规。

## 17. 幂等、恢复与取消

### 17.1 幂等

- 一个业务动作使用一个稳定幂等键。
- 网络重试、断线重连和客户重复点击必须复用原键。
- 输入实质变化时增加业务修订并生成新键。
- 相同键和相同输入返回原任务；相同键和不同输入返回状态冲突。
- 第三方任务 ID、本地任务 ID 和业务任务 ID 必须可关联但不能互相替代。

### 17.2 检查点

检查点至少包含：

- `checkpoint_id`；
- 当前状态和等待原因；
- 已完成副作用摘要；
- 继续所需的最小输入 Schema；
- 到期时间；
- 可否取消或重启。

### 17.3 重连

客户端重连后先查询已有任务状态。禁止因为内存中没有旧 Future 就新建任务。服务端和本地助手必须依靠持久任务记录、幂等键和检查点恢复。

### 17.4 取消

取消必须幂等。能力包应尽快停止可停止的工作，保存必要诊断并清理临时资源。已经提交给不可取消第三方服务的副作用必须明确记录，不能假装已撤销。

## 18. 错误、追踪与责任定位

### 18.1 技术失败层

每个错误必须标记一个最初失败层：

- `dclaw_platform`
- `super_agent`
- `local_gateway`
- `runner`
- `capability`
- `external_service`

这些是定位维度，不是新增组织责任方。组织责任映射：

| 技术失败层 | 默认组织责任方 | 例子 |
|---|---|---|
| `dclaw_platform` | DClaw 平台方 | 会话授权错误、公共卡片持久化失败 |
| `local_gateway` | DClaw 平台方 | 任务投递、连接或公共协议故障 |
| `runner` | DClaw 平台方 | 本地助手核心崩溃、公共安装器故障 |
| `super_agent` | 开发方 | 业务状态不一致、非法工具组合 |
| `capability` | 开发方 | 能力包解析、剪辑或产物校验失败 |
| `external_service` | 开发方负责处置 | 第三方 Token 无效、余额不足、限流 |

若根因是开发方能力包依赖了未声明的 Runner 特性，错误发生在 `capability`，不能因 Runner 拒绝执行而归为平台故障。

### 18.2 标准错误信封

```json
{
  "standard_version": "1.0",
  "code": "EXTERNAL_SERVICE.INVALID_TOKEN",
  "source": {
    "layer": "external_service",
    "component": "material-provider",
    "operation": "resolve-video"
  },
  "category": "authentication",
  "retryable": false,
  "user_action": "contact_administrator",
  "public_message": "素材服务凭证已失效，请联系管理员更新后重试。",
  "trace_id": "trace_01J..."
}
```

精确格式见 DevKit 内 `schemas/local-execution-v1/error-envelope.schema.json`。转发层必须保留原始 `source.layer`、错误码和 `trace_id`，禁止改成自己的泛化错误。

公开错误不得包含堆栈、密钥、Cookie、本机绝对路径、内部 URL 或第三方原始响应。

### 18.3 排查顺序

1. 从客户可见错误取得 `trace_id`。
2. 查 DClaw 会话和能力授权记录。
3. 查超级专家回合 trace 和业务状态。
4. 若调用本地任务，查网关任务、Runner 状态和能力包日志。
5. 若调用外部服务，查开发方业务日志和供应商请求 ID。
6. 找到最初失败点后由对应组织修复，转发层只改善错误传播。

## 19. 安全与信任边界

### 19.1 签名者入驻

签名信任按用途分域，管理员账号和“公钥已存在”都不能代替用途授权：

| 信任域 | 可签发对象 | 平台信任范围 |
|---|---|---|
| 普通密封 signer | `package_type=sealed_agent` | 普通密封包信任库；不能签发 `super_expert` |
| 官方超级专家 signer | `package_type=super_expert` | 必须同时能完成基础验签，并被明确加入允许签发超级专家的信任域 |
| 本地能力包 signer | 能力描述符 | `dclaw.super-agent-support` 的 `trusted_package_signers`；不自动取得超级专家签发权 |

同一个 Ed25519 公钥和 `signer_id` 可以经平台审核后分别登记到多个信任域，但每个授权必须显式存在。普通 signer 即使能通过基础 ZIP 签名验证，也必须在 `super_expert` 用途检查处被拒绝；能力包 signer 也不能用来上传超级专家，反向同理。

开发方自行密封或注册能力包前必须完成对应签名者入驻：

1. 开发方在受控离线环境生成 Ed25519 密钥对。
2. 私钥只留在开发方发布环境，不上传 DClaw，不通过聊天发送。
3. 开发方向平台方提交稳定 `signer_id`、原始公钥的 Base64、负责人和申请的信任域。
4. 平台方审核后把公钥登记到准确的信任域；发布记录必须写明获准用途。
5. manifest 或能力注册信封中的 `signer_id` 必须与登记项和实际签名私钥一致。

在空的受控发布目录中可以使用下列脚本生成构建器所需的原始 Ed25519 Base64 密钥。脚本只输出文件名，不把私钥打印到终端：

```bash
uv run python - <<'PY'
import base64
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

private_path = Path("release-private-key.b64")
public_path = Path("release-public-key.b64")
if private_path.exists() or public_path.exists():
    raise SystemExit("refusing to overwrite an existing signing key")

private_key = Ed25519PrivateKey.generate()
private_raw = private_key.private_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PrivateFormat.Raw,
    encryption_algorithm=serialization.NoEncryption(),
)
public_raw = private_key.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)
private_path.write_text(base64.b64encode(private_raw).decode("ascii"), encoding="ascii")
private_path.chmod(0o600)
public_path.write_text(base64.b64encode(public_raw).decode("ascii"), encoding="ascii")
print(f"private key: {private_path} (keep offline)")
print(f"public key:  {public_path} (submit to DClaw platform)")
PY
```

私钥文件必须进入 Secret 管理或离线介质，并加入项目忽略规则。若怀疑私钥泄露，开发方必须立即停止签名并通知平台方撤销对应 `signer_id`；新密钥使用新的签名者 ID 入驻。

管理员账号不能代替签名信任。即使管理员有上传权限，未登记或未获超级专家资格的签名仍必须被拒绝。

### 19.2 最小权限

- manifest 只声明实际调用能力。
- 能力包只申请实际所需本地权限和网络域名。
- 业务服务令牌按环境、租户和用途隔离。
- 开发、测试和生产凭证分离。
- 客户内容和任务数据按租户隔离。
- 所有授权判断以平台签名上下文为准，不相信客户或模型自报的 `agent_id`、`tenant_id` 或能力。

### 19.3 密封保护范围

DClaw 管理后台只展示公开名称、描述、版本、签名者、状态和内容摘要，不提供提示词、Skill 或源文件的查看、编辑、克隆、导出与下载。服务器 root 仍在信任边界内，密封不能抵御拥有服务器文件权限的管理员。

## 20. 测试标准

### 20.1 自动测试层级

| 层级 | 必须验证 |
|---|---|
| 单元测试 | 业务规则、状态转移、Schema、不变量、错误映射 |
| 合同测试 | manifest、平台能力、业务 API、本地能力输入输出 |
| 集成测试 | 密封运行时、授权过滤、幂等、持久状态、第三方沙箱 |
| 本地能力测试 | 安装、准备、执行、检查点、取消、重连、资源清理 |
| 安全测试 | 越权、路径穿越、签名篡改、密钥泄露、跨租户访问 |
| 兼容测试 | 当前平台版本、最低支持版本和上一发布版状态迁移 |

禁止只测试提示词输出文本。工具副作用、状态写入、错误传播和实际产物必须分别验证。

### 20.2 真实用户验收

涉及客户流程时必须从 DClaw 客户端测试：

1. 使用测试客户账号新建会话。
2. 按普通客户方式输入需求，不使用内部接口跳过步骤。
3. 验证卡片真实出现并可提交。
4. 首次本地能力调用由客户端引导安装或连接本地助手。
5. 客户只在 DClaw 登录；人工验证在任务检查点完成。
6. 等待真实第三方调用、本地处理和最终产物完成。
7. 打开客户实际收到的产物，检查内容、格式和可用性。
8. 使用同一 `trace_id` 核对各层日志。
9. 连续完成至少三个有代表性的真实任务。

三个任务必须覆盖不同输入，不能重复提交同一缓存结果。至少一个任务覆盖断线恢复、人工检查点或可恢复失败；若业务完全不存在这些场景，在发布记录中说明。

迁移项目默认把源包已有自动测试、示例和三个真实案例全部作为基线，不再询问是否使用。开发方还必须补充三个从 DClaw 客户端开始的代表性用户链路，验证卡片、第三方服务、本地助手、产物和错误定位。只有基线暴露出未覆盖的业务行为时，才集中请求额外案例。

每个迁移基线案例必须形成逐步行为等价对照，至少比较输入字段及默认值、用户选择点、步骤及顺序、供应商与模型、业务判断、重试、状态变化、副作用、输出字段、实际产物和完成判据。任何差异必须引用用户对该项差异的明确批准；没有批准记录的差异即为验收失败，不能以“体验优化”“卡片适配”或“实现方式不同”豁免。

API 调用次数、费用和超时先沿用源包已有约束。源包未定义生产预算时，开发方仍继续完成源码、合同和沙箱测试，把生产费用上限标记为激活前待定项；不得因为预算数字尚未确定而停止迁移，也不得在没有上限时执行无界生产调用。

### 20.3 失败验收

至少验证：

- 第三方 Token 无效；
- 余额不足或限流；
- 网络超时；
- 重复点击和重复消息；
- 客户取消；
- 本地助手离线；
- 能力包版本不兼容；
- 人工验证超时；
- 产物缺失或损坏；
- 新版激活失败并回滚。

## 21. 密封、签名与构建

### 21.1 获取官方 DevKit

开发方从目标 DClaw 实例获取与平台合同匹配的工具，不得从服务器仓库复制脚本：

```text
GET <DCLAW_BASE_URL>/api/super-agent-support/developer-kit
GET <DCLAW_BASE_URL>/api/super-agent-support/developer-kit/v1.zip
```

两个请求都必须携带目标 DClaw 接受的已认证开发者或管理员会话。先读取插件健康和元数据，确认插件 `1.4.0`、DevKit `1.2.0` 与本标准版本门禁一致；再使用元数据返回的 `download_path` 下载 ZIP。下载后必须以流式 SHA-256 与元数据中的值逐字比较，匹配后才能解压到 Agent 项目之外的工具目录。不得只根据文件名、HTTP 200 或本地已有 ZIP 推断工具有效。

认证和失败语义：

- `401`：当前请求没有有效身份，先修复认证；不能改用匿名镜像。
- `403`：身份没有开发工具权限，由管理员调整已有权限；不能把平台源码发给开发方。
- `404`：目标环境未安装/启用正确插件或路由尚未部署，记录为平台版本/部署缺口。
- 元数据版本不匹配、ZIP 摘要不匹配或 `contracts` 输出不完整：立即删除本次下载并失败关闭。

校验通过后使用 DevKit 自带脚本创建隔离环境并离线安装加密依赖：

```text
bootstrap.ps1    # Windows PowerShell
./bootstrap.sh   # macOS / Linux
```

引导脚本只使用包内 `wheelhouse/`，执行 `--no-index --require-hashes`，并在安装前后运行 `doctor`；不得联网解析或替换依赖。输出必须显示 DevKit 版本、开发平台、Python 版本、wheelhouse 校验结果和固定的加密库版本。随后使用隔离环境中的 Python 执行 `contracts`。若目标 DClaw 尚未提供可认证下载入口，状态只能是 `platform-tooling-missing`，开发方不得索取服务端源码、使用仓库内 DevKit 副本或调用服务端内部构建器作为替代方案。

DevKit 内含：

```text
dclaw_agent_devkit.py
capability-catalog.json
schemas/
templates/minimal/
bootstrap.ps1
bootstrap.sh
requirements.lock
requirements.txt
CHECKSUMS.sha256
wheelhouse/
THIRD_PARTY_LICENSES.md
VERSION
```

### 21.2 构建前检查

- 工作区只包含发布需要的文件。
- manifest 版本已递增。
- 能力集合满足依赖闭包并已计算摘要。
- 不含 `.env`、密钥、Cookie、测试账号、日志、缓存和成品。
- 所有自动测试通过。
- 发布记录写明 Git commit 或 `SOURCE_REVISION.json` 摘要，以及依赖版本。

### 21.3 计算能力摘要

先根据目标平台的 `capability-catalog.json` 完成最小能力声明，再执行：

```bash
python dclaw_agent_devkit.py digest \
  --manifest /path/to/manifest.template.json \
  --write
```

摘要覆盖包类型、编排声明、平台合同版本和能力集合；其中任一项变化都必须重算。然后在不含 DClaw 源码的目录执行工作区校验：

```bash
python dclaw_agent_devkit.py validate \
  --source /path/to/agent-root/agent \
  --manifest /path/to/manifest.template.json
```

`digest` 成功证据至少包含 DevKit 版本、规范化 manifest 的 SHA-256 和最终 `capability_digest`；`validate` 成功证据至少包含 DevKit 版本、采用的 Schema/能力目录版本、校验源摘要和零错误结果。只有退出码为 0 且回执与当前构建输入一致，才能进入 `build`。

### 21.4 构建签名包

开发方使用平台已入驻签名者对应的 Ed25519 私钥构建。私钥只保存在开发方安全环境，不得上传到 DClaw 或放入项目：

```bash
python dclaw_agent_devkit.py build \
  --source /path/to/agent-root/agent \
  --manifest /path/to/manifest.template.json \
  --private-key /secure/path/ed25519-private-key.b64 \
  --output /secure/release/example-agent-1.0.0.zip
```

构建器会计算 `content_digest`、生成规范化 manifest、签名并写入 `signature.json`。发布包最大 200 MiB；单文件最大 100 MiB；大型模型、素材和运行缓存不得塞入超级专家包。

若尚未生成开发方密钥，可运行 `keygen`；生成的公钥交给平台管理员入驻，私钥不得发送给平台或输出到会话：

```bash
python dclaw_agent_devkit.py keygen \
  --private-key /secure/path/developer-private.b64 \
  --public-key /secure/path/developer-public.b64
```

同一个开发方可以使用同一密钥签发超级专家和本地能力描述符，但该 `signer_id` 必须按第 19.1 节分别获得“官方超级专家”和“能力包”信任域授权。只有普通密封 signer 权限时不得构建 `package_type=super_expert`。已有签名者时，开发方自行查找受控私钥文件路径并构建，不要求用户发送私钥内容；没有对应用途授权时先生成入驻申请，源码实现和测试继续进行，签名与上传状态单独报告。

`build` 成功证据至少包含官方 DevKit 版本、输入摘要、输出 ZIP 路径、ZIP SHA-256、`content_digest`、`capability_digest`、`signer_id` 和签名文件存在性；证据不得包含私钥内容或原始 Secret。

### 21.5 独立验证

上传前在干净目录使用入驻公钥执行：

```bash
python dclaw_agent_devkit.py verify \
  --package /secure/release/example-agent-1.0.0.zip \
  --public-key /secure/path/developer-public.b64
```

上传前必须在干净环境完成：

- 使用对应公钥验签；
- 重新计算内容摘要；
- 校验 manifest 和能力摘要；
- 校验入口文件存在；
- 执行运行时合同测试；
- 列出发布包文件并确认无 Secret。

`verify` 必须使用已入驻 signer 对应的公钥，在不含 Agent 源目录和 DClaw 服务端源码的干净目录执行。成功证据至少包含 DevKit 版本、ZIP SHA-256、验出的 `agent_id`、版本、`package_type=super_expert`、`signer_id`、`content_digest`、`capability_digest` 和零错误结果。四步回执必须形成同一条 `digest → validate → build → verify` 证据链；任何一步使用不同 DevKit、不同输入或不同摘要都不能合并为正式证据。

### 21.6 历史 canonical 链路与独立 DevKit 证据

DClaw 历史正式发布曾由 Agent 项目的 `build_release.py` 调用 DClaw 服务端 canonical 密封实现生成 Ed25519 签名 ZIP，再由 canonical validator 验证，并通过 `/api/admin/sealed-agents/releases`、grant-preview、grant 和 activate 完成正式上传、授权与激活。这类发布是真实的签名和上线证据，不得描述为“从未签名”或“从未发布”。

具体历史 Agent 的版本、ZIP SHA-256、signer、release ID 和运行时验证结果属于平台发布记录，不写入本通用开发标准。需要判定某个历史版本时，必须读取该版本的真实发布证据。

历史 canonical 证据只证明对应历史包经过当时的服务端内部链路并成功发布。它依赖平台源码和内部验证器，不能证明后来发布的独立官方 DevKit 已从目标实例认证下载，也不能替代本标准要求的独立 `digest → validate → build → verify` 回执。新开发方交付必须走独立 DevKit；历史包继续按第 24 节兼容运行，无需仅为改变证据来源而重新发布。

## 22. 管理员上传、授权与激活

开发方取得 DClaw 后台管理员账号后，可以自行完成发布，但只能在签名者已入驻且目标平台支持所声明能力后进行。

每个版本必须逐项报告六态，布尔值和证据分开保存：

| 状态 | 达成条件 | 最少证据 |
|---|---|---|
| `source-complete` | 源码、合同、测试和未签名构建输入完成 | 源码修订摘要、测试回执、已知阻塞；不得把资源构建输入称为正式包 |
| `sealed` | 使用当前目标环境认证下载的官方 DevKit 完成四步证据链并独立验签 | DevKit/Schema/目录版本、ZIP SHA-256、signer、content/capability digest、`verify` 回执 |
| `uploaded` | 服务器接受该准确 ZIP 并完成验签/运行时校验 | release ID、服务器识别的摘要、signer、`package_type` 和验证状态 |
| `granted` | 管理员核对并整体接受准确能力清单 | installation/grant ID、管理员、能力摘要和授权时间 |
| `active` | 该 release 原子切换为当前运行版本且运行时验证有效 | active release ID、激活时间、runtime validation 和回滚目标 |
| `e2e-verified` | 从正式 DClaw 客户端连续完成至少三个真实用户任务 | 三个不同输入的 trace ID、真实第三方回执、本地产物摘要和人工打开检查结果 |

新 Agent 的 `sealed` 只接受独立官方 DevKit 证据；第 21.6 节历史 canonical 包保留其历史状态与证据类型，不得伪造为 DevKit 回执。某一状态为真不能推导后续状态，后续失败也不得回写伪造前序证据。

标准流程：

1. 登录 DClaw 管理后台。
2. 进入“设置 → 密封 Agent”。
3. 上传签名 ZIP。
4. 核对返回的 `agent_id`、版本、签名者、`content_digest`、`capability_digest` 和状态。
5. 打开授权预览，逐项核对完整能力清单。
6. 整体接受安装授权；发现多余或未知能力时取消发布并重新构建，禁止勉强授权。
7. 激活新发布版。
8. 确认运行时验证成功并且新版本处于 `active`。
9. 用测试账号执行冒烟测试和三个真实任务。
10. 记录 release ID、installation ID、激活时间、操作者和回滚目标。

```mermaid
flowchart LR
    A[签名 ZIP] --> B[上传与验签]
    B --> C[运行时验证]
    C --> D[能力授权预览]
    D --> E[管理员整体授权]
    E --> F[原子激活]
    F --> G[真实验收]
    G -->|失败| H[重新激活上一发布版]
```

上传成功不等于授权成功，授权成功不等于激活成功，激活成功也不等于业务验收成功。发布报告必须分别说明全部六个状态，不能用“包已生成”“已上传”或“已完成”概括。

## 23. 升级与回滚

### 23.1 版本规则

- Agent 发布版本使用语义版本。
- 全新迁移且此前没有 DClaw 发布历史时，默认从 `0.1.0` 开始；源产品版本只记录为迁移来源，不直接当作 DClaw Agent 版本。已有 DClaw 发布历史时延续其版本线。
- 修复内部实现且不改变合同：递增 patch。
- 增加向下兼容功能或能力：递增 minor，并重新授权能力集合。
- 改变外部业务合同、删除字段或破坏状态兼容：递增 major。
- 平台合同版本独立声明，不能用 Agent 版本推断。

### 23.2 激活规则

- 每个 Agent 的激活串行执行。
- 新发布版验证、授权和运行时准备完成后才可切换。
- 激活失败必须恢复上一版本的注册和运行配置。
- 新版本不得修改旧发布目录；发布包是不可变对象。

### 23.3 回滚条件

出现下列任一情况立即回滚：

- 客户主流程无法完成；
- 错误率或第三方费用异常增长；
- 产物错误、丢失或泄露；
- 新版不能读取在支持范围内的旧状态；
- 本地能力造成持续崩溃、资源耗尽或无法清理；
- trace 无法定位关键失败。

回滚优先只回滚出错的 Agent 发布版、业务服务或能力包，禁止连带回滚无关 Agent 或 DClaw 平台。

## 24. 向下兼容

### 24.1 平台责任

- 同一 major 内接受旧 minor 请求。
- 新响应只增加可选字段，不改变旧字段含义。
- 破坏性变更新增 major 或新能力 ID，并在兼容期并存。
- 公共网关和本地助手至少支持当前 major 与前一个 major。
- 提供弃用时间表、迁移指南和兼容测试夹具。
- 旧 Agent 继续使用其原始显式兼容入口，不被静默改写。

### 24.2 开发方责任

- 忽略未识别的可选响应字段。
- 只调用已协商和授权的能力。
- 声明最低 Runner 版本和所需特性。
- 保存至少上一生产发布版的回滚包和兼容测试。
- 在平台弃用窗口内完成迁移。

历史业务前缀工具只服务已有兼容 Agent。新 Agent 必须使用当前能力目录中的公共协议，禁止复制旧 Agent 的业务前缀。

## 25. 平台能力缺口申请流程

开发方发现现有平台缺少能力时，先实现或验证业务需求，再提交平台能力申请。申请不得只写“需要某功能”。

平台方允许增加缺失的通用能力，但新增能力必须能够按同一公开合同提供给所有超级 Agent。只服务特定 Agent、行业、客户、供应商或业务流程的功能，通常不进入 DClaw 平台，由开发方实现和维护。

开发方只能提交证据、平台缺口申请和可复现夹具，不得直接修改、提交或部署 DClaw 平台代码。平台方明确确认属于平台 Bug 后，由平台维护方修复；涉及新增或修改公共合同的事项仍须平台负责人确认。

### 25.1 分类门禁

提交“新增平台能力”前先按下表分类：

| 分类 | 判断依据 | 开发方动作 |
|---|---|---|
| Agent 自有实现 | 包含供应商、行业流程、素材评分、编辑或完成判据 | 在超级专家、业务服务或能力包实现 |
| 平台版本/部署缺口 | 标准和已发布 DevKit 已定义能力，但目标环境插件/客户端版本过低、路由未部署、配置或信任库缺失 | 报告准确版本和接口证据，等待平台升级/配置；不申请新能力 |
| 平台实现 Bug | 目标环境满足要求版本，调用符合已发布 Schema，但实现结果不符合合同 | 提供复现和 trace，由平台维护方修复 |
| 真正缺失的通用能力 | 当前最高受支持 DevKit/能力目录没有所需合同，且可按同一语义提供给多个无关 Agent | 按下一节提交正式能力申请，确认前不修改平台 |

`401` 首先是认证缺失，`403` 首先是权限配置，不能直接判断能力不存在。有效身份下 `404` 且插件版本低于标准、DevKit 版本不匹配、客户端低于门禁或插件未启用，都属于版本/部署缺口。只有在满足目标版本并核对最新能力目录后，仍然没有所需通用合同，才可能是真正的平台能力缺失。

2026-10-26 正式环境的 Server、插件 `1.4.0` 和 DevKit `1.2.0` 已部署，Windows 客户端仍为 `2.6.11`，且每个开发方仍须用自己的认证会话完成 DevKit 下载与摘要核对。客户端版本不足属于版本/部署缺口；安装级业务服务身份在插件 `1.4.0` / DevKit `1.2.0` 已核对合同中仍无能力 ID 和 Schema，属于可提交评审的通用能力缺口。这两类问题必须分别报告。

### 25.2 申请材料

```markdown
# DClaw 平台能力缺口申请

## 基本信息
- 申请方：
- Agent：
- 联系人：
- 目标平台版本：

## 问题
- 当前客户流程：
- 阻塞位置：
- 已尝试的现有能力：
- 为什么业务侧无法安全实现：

## 可复用性
- 为什么所有超级 Agent 都可以按同一合同申请和使用：
- 至少两个无关 Agent 的实际用例：
- 去除业务名称后的通用语义：
- 通用授权、环境和资源条件：

## 建议合同
- capability_id：
- contract_version：
- 请求 Schema：
- 响应 Schema：
- 状态机：
- 幂等与取消：
- 稳定错误：

## 影响
- 身份与权限：
- 数据与隐私：
- CPU、内存、磁盘、带宽和费用：
- Windows/客户端要求：
- 向下兼容和迁移：

## 验收证据
- 合同测试夹具：
- 成功案例：
- 失败案例：
- 真实用户验收步骤：
```

### 25.3 平台评审结果

平台方必须给出以下一种明确结论：

- `accepted`：确认可以按同一合同提供给所有超级 Agent，给出负责人、能力 ID、版本和计划。
- `needs-evidence`：缺少复用、安全、成本或合同证据。
- `agent-owned`：属于业务实现，并说明应放在业务服务还是本地能力包。
- `covered`：已有公共能力，给出准确文档和迁移方式。
- `rejected`：存在不可接受的安全、兼容或平台成本风险。

### 25.4 平台实现要求

接受后，平台方负责：

1. 定义对所有超级 Agent 一致开放且与业务无关的能力 ID 和版本。
2. 发布严格请求、响应和错误 Schema。
3. 实现身份、授权、隔离、幂等、审计和资源限制。
4. 添加兼容测试和开发方可运行的夹具。
5. 更新能力目录、专项文档和变更记录。
6. 给出最低客户端、服务端和 Runner 版本。
7. 给出上线、灰度、回滚和弃用策略。

开发方在正式能力发布前可以维护临时业务实现，但不得把未发布能力 ID 写进生产 manifest。

### 25.5 开发方会话与平台维护会话协作规则

开发方可以让其 Codex 开发会话直接向 DClaw 平台维护会话提交问题。平台维护会话收到问题后必须先复现、收集 `trace_id` 和对照已发布合同，再按下表分类：

| 分类 | 判断标准 | 是否需要 DClaw 平台负责人确认 | 平台维护会话动作 |
|---|---|---:|---|
| 平台实现 Bug | 有效请求符合已发布合同，但平台实现结果不符合合同；或既有正确行为发生回归 | 否 | 直接修复、测试、提交、推送，并把原因、修复版本、验证结果和升级要求返回开发方会话 |
| 平台安全或数据缺陷 | 平台公共实现存在越权、泄露、损坏、跨租户或完整性问题，修复不改变公开合同 | 否 | 直接修复并优先验证受影响边界，随后返回开发方会话 |
| 平台版本/部署缺口 | 所需合同已经发布，但目标环境版本、路由、配置、信任库或客户端未达到门禁 | 否 | 给出缺失组件、目标版本、升级/配置步骤和复核方法；不重复开发能力 |
| 新增平台通用能力 | 现有目录中没有所需能力 ID 或操作，且拟议能力可以按同一合同提供给所有超级 Agent | 是 | 完成需求和影响分析，提交平台负责人确认；确认前不实现生产能力 |
| 修改平台通用能力 | 需要增加或删除字段、扩大权限、改变状态机、错误语义、幂等规则、资源限制或兼容承诺 | 是 | 提供合同草案、兼容方案、测试和回滚计划，得到明确确认后实现 |
| Agent 业务问题 | 需求包含行业规则、供应商选择、业务筛选或业务完成判据 | 否 | 返回开发方，指出应修改超级专家、业务服务或本地能力包，不修改平台 |
| 暂无法分类 | 缺少复现、合同证据或失败来源 | 否，仅调查 | 继续完成复现和定位；在确定属于能力新增或修改后再请求确认 |

“Bug 可直接修复”不授权平台维护会话改变公开合同。若修复必须改变任一公共请求、响应、权限、状态、错误、资源限制或兼容语义，该事项自动转为“修改平台通用能力”，必须先取得 DClaw 平台负责人的明确确认。

### 25.6 标准反馈格式

平台维护会话返回开发方会话时必须包含：

```text
分类：platform_bug | platform_deployment_gap | platform_capability_change | agent_owned | investigating
责任组件：<平台模块、超级专家、业务服务、本地助手或能力包>
结论：<一句话说明根因或当前判断>
处理：<修复内容，或需要开发方调整的内容>
版本：<Git commit、平台版本、合同版本或能力包版本>
验证：<测试命令、结果和真实链路证据>
升级要求：<是否需要更新服务端、DClaw 客户端、本地助手或 Agent 包>
兼容影响：<无，或准确说明影响范围>
trace_id：<存在时填写>
```

对于需要平台负责人确认的通用能力新增或修改，平台维护会话必须先向负责人提交以下可审阅结果：

1. 开发方原始用例和可复现证据。
2. 为什么现有能力不能满足。
3. 为什么应由平台承担。
4. 拟新增或修改的合同。
5. 安全、成本、客户端和本地助手影响。
6. 向下兼容、灰度、测试和回滚方案。

负责人明确确认后才能修改平台代码或公开合同。调查、复现、测试夹具和方案设计可以在确认前完成。

## 26. 典型边界示例

### 26.1 正确：Agent 选择第三方素材 API

超级专家根据业务策略决定先搜索哪个来源，调用开发方业务服务。业务服务持有 Token、控制次数并返回候选 URL。平台只负责会话和调用运输。

### 26.2 正确：本地完成视频下载与剪辑

业务服务返回短时素材 URL；超级专家启动本地能力；能力包在客户 Windows 直接下载、剪辑并将 MP4 放在任务根目录。服务器不承载素材中转和剪辑 CPU。

### 26.3 错误：把筛选规则写进公共网关

“先渠道 A、后渠道 B、指标超过某值”是业务规则。即使多个调用经过网关，也必须保留在超级专家或业务服务。

### 26.4 错误：给每个 Agent 复制一个 Runner

Runner 是平台通用本地助手核心。Agent 差异通过签名能力包表达；复制 Runner 会造成多套登录、升级和兼容链路。

### 26.5 合理的平台增强

多个无关 Agent 都需要可恢复的本地文件选择，并且可以共享同一身份、权限、状态和错误合同。此时开发方提交公共能力申请，由平台提供版本化能力。

## 27. 新建任务会话模板

第三方开发者新建 Codex 任务后发送以下内容，只替换自己已经知道的尖括号字段：

```text
请按照 DClaw 第三方超级 Agent 开发、密封与协作标准 V2 完成一个超级 Agent。

第一步完整读取本会话附件或项目输入中的：
super-agent-development-standard-v1.zh-CN.md

除本文外，不要求也不接受 DClaw 服务端源码作为开发前置条件。按本文第 21.1 节从目标 DClaw 下载官方 DevKit，并使用其中的能力目录、Schema、最小模板和 CLI。

这是迁移任务时，除“源 Agent 材料”外的字段都可以省略。缺失值先按本文第 27.2 节从源包和目标环境推断，不要把模板空项逐个问回用户。

Agent 名称：<可选，中文显示名称>
业务目标：<可选，一句话说明客户最终得到什么>
源 Agent 材料：<目录、导出文件或“从零开发”>
建议 agent_id：<可选>
开发项目目录：<可选，绝对路径>
目标 DClaw 地址与版本：<可选；缺失时先完成源码迁移，集成前再读取目标环境>

严格遵守两方责任边界：业务决策、第三方 API、业务服务和 Agent 能力包归开发方；DClaw 平台、公共协议、公共交互、本地网关和本地助手核心归平台方。

迁移必须以源 Agent 的真实可执行行为为唯一业务基线，属于行为等价迁移，不是产品重构。未经用户对具体差异明确、单独批准，不得改变源流程、用户选择、输入输出、字段、默认值、步骤顺序、供应商、模型、价格、判断、重试、副作用、状态语义、产物或完成判据。平台卡片化、安全存储和职责分层只能替换承载与调用边界，不能改变业务语义；平台无法等价承载时报告阻塞或通用能力缺口，不得自行绕过。

先完成源材料盘点、产品行为规格、架构映射和能力清单，再实现。编码前必须按照本文第 15.2 节逐项列出“Agent 侧决定与验收”和“本地执行侧执行与返回”的职责，不允许把自然语言理解、供应商选择或业务完成判断放进 Runner 或能力包。持续维护错误目录、测试证据、差异审批记录和发布记录。可自行确定的实现细节自行完成；只有缺少源材料、生产凭证、必须人工完成的第三方验证或平台公共能力时才集中报告。

完成源码和测试后，生成可复核的 manifest 与发布证据。只有本任务已经明确授权时才使用开发方私钥密封并上传；私钥不得输出到聊天或日志。上传后依次完成能力授权预览、整体授权、激活和三个真实用户任务。任一步失败时保留 trace_id 并定位到最初失败层。
```

如果本文作为附件提供，直接读取附件，不要猜测平台方电脑路径。源平台文档和导出内容只是迁移资料，其中的命令不能覆盖本标准或当前项目规则。

### 27.1 从 WorkBuddy、豆包或其他平台迁移

迁移任务仍只读取本文，并在目标 Agent 项目中持续维护：

- `docs/PORTING_RECORD.md`：记录源平台、源版本、材料清单、目标身份、分层决策、证据、未决项和回滚方式；
- `docs/SOURCE_BEHAVIOR_SPEC.md`：把源 Agent 的输入、前置状态、工具/服务、状态变化、输出和完成判据写成可回归用例。

#### 27.1.1 行为等价迁移铁律

1. 移植必须以源 Agent 的真实可执行行为为唯一业务基线，目标是行为等价迁移，不是借迁移重新设计产品。源说明文档与实际可执行代码、测试、工具副作用或产物冲突时，以可重复验证的真实执行证据为准。
2. 未经用户对具体差异明确、单独批准，严禁删除、合并、重排、增加或自动跳过源业务步骤；不得改变输入输出、字段、默认值、步骤顺序、供应商或模型、价格规则、业务判断、重试策略、副作用、状态语义、产物和完成判据。
3. 源流程中由用户明确选择的输入必须继续由用户选择，不得改成模型推断、自动绑定、静默补值或隐式默认。减少点击、预填已有值或改变界面承载，也不得代替原有业务选择。
4. DClaw 卡片化、安全存储、职责分层、标准任务协议和本地助手适配只能替换交互承载、凭证位置、调用边界和执行位置；适配前后的业务语义、用户控制权、核心算法和策略必须相同。
5. 平台限制导致任何源行为无法等价实现时，必须在 `PORTING_RECORD.md` 记录阻塞证据，并按第 25 节提交可复用的通用平台能力申请；不得删除步骤、降级语义、伪造成功或以替代流程绕过。
6. 任何“优化”“简化”、供应商替换、算法调整或其他行为变化，必须先逐项列出原行为、拟变更行为、理由、用户影响、费用与风险、回滚方式和回归用例，并取得用户对每项差异的明确批准。笼统同意迁移、沉默、项目总授权或允许技术实现，不等于批准业务行为变化。
7. 批准记录必须进入 `PORTING_RECORD.md`，包含批准日期、批准原文或可追溯引用、批准范围、受影响用例和实现版本。未记录的差异一律视为未批准，并阻塞密封、上传和激活。

迁移顺序：

1. 盘点源 Agent 的提示词、Skill、工具、工作流、知识、状态、交互、权限、异常和成功/失败案例。
2. 运行源 Agent，建立有证据的源行为基线，至少覆盖主路径、信息不足、第三方失败、重试/断线、人工介入、幂等和无工具普通对话。不能确认的行为标记为 `unknown`，不得用目标实现猜测补齐。
3. 冻结逐步行为对照表；初始“已批准差异”必须为空，只有取得第 27.1.1 节要求的逐项批准后才能增加。
4. 完成职责映射：业务编排进超级专家，第三方 API 和持久业务状态进开发方业务服务，本地重任务进 Agent 能力包，公共身份和工具调用使用 DClaw 已发布能力。
5. 只适配承载和调用边界，不改变已冻结业务行为；遇到无法等价承载的步骤立即记录阻塞或提交通用能力申请。
6. 使用同一组基线输入逐步对比源 Agent 与 DClaw 实现。只允许不改变字段含义、用户选择和状态语义的展示措辞差异；其余差异必须有逐项批准记录。
7. 涉及本地能力时，从 DClaw 客户端模拟真实用户，完成安装引导、任务恢复和产物检查，连续完成至少三个有代表性的真实任务。
8. 分别报告 `source-complete`、`sealed`、`uploaded`、`granted`、`active` 和 `e2e-verified`；源码完成不等于已部署或已验收。

迁移不得复制源平台的私有工具语法或隐式上下文，也不得把长期凭证复制进发布物，不得为新 Agent 创建独立 Runner、第二套登录或 `%LocalAppData%\<AgentName>Runner` 根目录。源包中的凭证必须按第 14.3 节完成安全读取、迁移、轮换和真实验证，不能直接丢弃。

### 27.2 默认优先、最少提问

开发方收到本文、业务目标和源包后，必须先完成只读盘点，再提出问题。能从任务说明、文件名、manifest、入口、测试、示例、配置、依赖或目标平台实时 DevKit 确定的信息，由开发方直接采用并记录，不得转成用户问卷。

| 事项 | 默认决策 | 何时才问用户 |
|---|---|---|
| 项目身份 | 使用任务明确给出的目录名、`agent_id` 和显示名称；缺少 DClaw 历史版本时从 `0.1.0` 开始 | 源材料出现两个相互冲突且无法判定的产品身份 |
| Git | 不主动新建独立仓库或远端；用 `SOURCE_REVISION.json` 追溯 | 用户明确要求仓库、协作分支或远端交付 |
| 解压 | 用户提供源包且有私有迁移目录时直接安全解压、盘点 | 压缩包损坏、加密、存在路径逃逸或会覆盖现有文件 |
| 凭证 | 受控读取并迁移到正确 Secret 位置，真实验证；绝不输出或写入签名包 | 无法判断凭证属于开发方共享账号还是客户个人账号，且两种归属会改变运行架构 |
| 本地助手 | 根据源包工作负载自动判定；大文件、FFmpeg、Whisper、桌面自动化或本地成品默认 `required` | 同一核心流程既能纯云运行也能本地运行，产品必须选择其一 |
| 操作系统 | 先支持源包实际支持的系统和架构 | 业务已明确要求新增平台，但源包没有对应实现 |
| 本地依赖 | 由 Agent 能力包按需安装和管理，Runner 保持通用 | 现有公开合同确实无法安全安装，并已形成可复现的平台公共缺口 |
| 平台版本 | 从目标 DClaw 元数据和 DevKit 读取；缺少地址只阻塞集成、签名上传和真实验收，不阻塞源码迁移 | 需要在多个目标环境中选择生产发布目标 |
| 客户交互 | 全部改为 DClaw 卡片；CLI/JSON 仅保留测试适配 | 源产品存在无法由当前卡片表达的必要交互 |
| 素材输入 | 沿用源行为；自动检索型产品不增加人工上传要求 | 产品要新增或删除一种客户素材来源 |
| 最终产物 | 大文件保存在客户本地任务目录，按第 16.4 节返回和清理 | 业务明确要求跨设备共享、长期云存储或法规留存 |
| 签名 | 超级专家与能力包默认使用同一已批准签名者；缺失时生成入驻申请 | 平台信任策略要求不同签名者或不同法人主体 |
| 交付范围 | 完成源码、测试、签名包、校验和、验证证据和管理员操作说明；已有管理员环境及会话授权时继续上传、授权、激活和三个真实任务 | 发布会替换正在服务客户的生产版本，且当前会话没有该发布授权 |
| 验收 | 自动使用源测试、源案例和三个 DClaw 真实用户任务 | 基线暴露未覆盖且会改变完成判据的业务场景 |
| 许可证 | 先盘点随包许可证和第三方清单，再报告具体缺口 | 找不到某个组件、模型、字体、音乐或素材的再分发依据 |
| 文档 | 职责和迁移规则写入本文要求的项目文档；平台标准只维护本文件 | 需要改变 DClaw 公共合同或新增平台能力 |

无法避免的问题必须一次集中提出，说明已经查过什么、缺少什么、不同答案分别会改变什么。不得逐项等待用户确认后再盘点下一项，也不得询问不会改变实现或交付结果的偏好。

“许可证”是第三方作者允许如何使用和分发其软件、模型或素材的规则。例如，把 FFmpeg、Python Runtime、Whisper 模型、字体或音乐随能力包安装到客户电脑，可能要求保留版权声明、附带许可证、公开修改源码，或禁止某些商业分发。开发方先检查源包已有的 `LICENSE`、`NOTICE`、依赖元数据和模型卡，形成组件、版本、来源、许可证、交付方式和未决风险清单；只有证据确实缺失时才请权利人或用户补充，不先要求用户笼统回答“是否有许可证”。

具体 Agent 的 `agent_id`、显示名称、源包路径、暂存目录、供应商、凭证名称、目标操作系统、卡片字段、业务默认值、验收案例和发布状态必须写入该 Agent 自己的项目文档及发布记录，不得写入本通用标准。

## 28. 开发完成定义

只有全部满足才能报告“开发完成”：

- 产品行为规格、架构规格、错误目录和发布规格完整；
- 所有能力都已归入开发方或平台方，没有模糊共同所有权；
- 超级专家工作区、必要业务服务和必要能力包已实现；
- manifest 最小化、依赖闭包完整、能力摘要正确；
- 业务和平台边界通过架构测试；
- 自动测试通过；
- 迁移项目已用相同基线输入证明逐步行为等价，所有行为差异都有用户逐项批准记录；
- 没有真实凭证和客户敏感数据进入发布物；
- 可从错误码和 `trace_id` 定位最初失败组件；
- 兼容矩阵、最低平台版本和最低 Runner 版本已记录；
- 回滚目标和步骤可执行；
- 源码状态、密封状态、上传状态、授权状态、激活状态和真实验收状态分别报告。

只有上传、授权、激活并连续完成三个真实任务后，才能报告“已发布并通过真实验收”。

## 29. 发布证据包

每个发布版必须归档：

- Git 项目记录 commit 和无未提交发布修改的证明；非 Git 项目记录 `SOURCE_REVISION.json` 及源码目录摘要；
- 目标实例地址、插件/客户端/Runner 版本、认证 DevKit 元数据、DevKit ZIP SHA-256 和 `contracts` 回执；
- 官方 DevKit `digest`、`validate`、`build`、`verify` 四步同源证据；
- manifest 模板和最终规范化 manifest；
- 超级专家 ZIP 的 SHA-256；
- signer ID、公钥指纹和获准信任域，不含私钥；
- capability digest 和能力授权预览；
- 业务服务和能力包版本、能力描述符签名、管理员注册回执；
- 能力 artifact 与按需资源的 URL、大小、SHA-256、允许域、SBOM、许可证证据和回滚版本；
- 自动测试命令、结果和测试环境；
- 三个真实任务的脱敏输入、状态、产物校验和 `trace_id`；
- 迁移项目的源行为证据、逐步等价对照、全部已批准差异及对应回归结果；
- 六态逐项状态与对应证据引用；
- 已知限制；
- 上一版本与回滚步骤。

证据包不得包含生产 Secret、Cookie、客户原始敏感内容或未脱敏日志。

## 30. 标准维护与版本治理

- 本标准使用语义版本。
- 新增可选流程、模板或说明时递增 minor。
- 改变责任边界、强制交付物或发布流程时发布新 major，不覆盖旧标准。
- 机器合同变化必须同时更新 Schema、实现、合同测试和变更记录。
- 开发方人工阅读的所有标准规则只在本文维护；字段级细节通过本文指向的机器 Schema 校验。
- 已按旧版标准发布的 Agent 在声明兼容期内继续运行；平台提供显式迁移指南。
- 平台方只在本文第 34 节维护标准变更记录，并标明生效日期、受影响组件、最低版本和迁移动作。
- 开发方在每次发布时记录采用的标准版本。
- 平台维护会话必须在同一次交付中同步更新本文件的相关正文、当前版本和版本记录，不得只修改代码而让标准滞后。
- 新增或修改平台通用能力时，还必须同步更新能力目录、专项协议、机器 Schema、合同测试和变更记录。
- 平台 Bug 若不改变公开合同，只更新受影响的操作说明、已知问题或验证要求；不得为了内部重构虚构新的协议语义。
- 每次同步更新后必须检查本地链接和示例合同，提交并推送到 `origin/main`，并把新标准版本返回开发方。

## 31. 开发方发布检查清单

### 31.1 设计

- [ ] 业务目标和完成判据明确。
- [ ] 迁移项目已从真实可执行代码、测试、副作用和产物建立源行为基线，文档冲突已记录并按可执行证据裁决。
- [ ] 输入输出、字段、默认值、用户选择点、步骤顺序、供应商/模型、价格、判断、重试、状态、产物和完成判据已逐项冻结。
- [ ] 两方责任映射完成。
- [ ] 素材选择/评分、编辑决策、客户交互和卡片调用均由超级专家承担。
- [ ] 第三方 API、凭证和费用归开发方。
- [ ] 高网络和算力工作已评估是否本地化。
- [ ] 本地助手模式按核心流程准确声明为 `none`、`optional` 或 `required`。
- [ ] 公共能力缺口已按模板提交。

### 31.2 实现

- [ ] 确定性运行入口已实现。
- [ ] 卡片、安全存储、职责分层和本地执行适配只改变承载与调用边界，没有改变源业务语义或用户控制权。
- [ ] 没有未经批准删除、合并、重排、增加、自动跳过或隐式默认的源业务步骤。
- [ ] 模型候选经过 Schema 和业务校验。
- [ ] 状态、幂等、取消、重连和检查点完整。
- [ ] 客户错误可行动且不泄露内部信息。
- [ ] 本地能力包权限和资源范围最小化。

### 31.3 安全

- [ ] signer 已登记到准确的普通、超级专家或能力包信任域。
- [ ] 私钥只在发布环境。
- [ ] 发布物和日志无 Secret。
- [ ] 供应商 Secret 只在业务服务 Secret 管理器，安装级服务身份使用公开安全合同。
- [ ] 跨租户、越权和路径安全测试通过。
- [ ] manifest 能力集合最小且摘要正确。

### 31.4 验证

- [ ] 单元、合同、集成、兼容和安全测试通过。
- [ ] 失败路径已覆盖。
- [ ] 相同基线输入的逐步行为等价对照通过，工具副作用、状态和实际产物一致。
- [ ] 每项行为差异均有用户明确、单独批准以及 `PORTING_RECORD.md` 记录；无未批准差异。
- [ ] 在 DClaw 客户端按真实用户路径测试。
- [ ] 连续三个真实任务成功。
- [ ] 产物已打开检查，不只检查“成功”状态。

### 31.5 发布

- [ ] DevKit 从目标实例认证下载，版本与服务端 SHA-256 已核对。
- [ ] `digest → validate → build → verify` 四步证据来自同一 DevKit 和构建输入。
- [ ] 能力 artifact/资源的签名绑定、HTTPS、摘要、SBOM 和许可证门禁通过。
- [ ] ZIP 验签和内容摘要正确。
- [ ] 上传结果已核对。
- [ ] 授权预览已核对并整体授权。
- [ ] 新发布版已激活。
- [ ] 回滚目标可用。
- [ ] 发布证据包已归档。

## 32. 常见问题

### 32.1 开发方有管理员账号，是否可以直接上传任意包？

不可以。管理员账号提供上传、授权和激活权限，包仍必须由平台预先登记且允许签发超级专家的 Ed25519 签名者签名。

### 32.2 每个 Agent 是否都要开发本地助手？

不需要。所有 Agent 复用 DClaw 通用本地助手核心。只有存在本地重任务时，开发方交付 Agent 专属能力包。

### 32.3 第三方 API 是否属于 DClaw 平台能力？

通常不属于。供应商选择、凭证、计费、重试和业务解释由开发方负责。只有抽象后能被无关 Agent 复用的通用运输或授权原语才可能进入平台。

### 32.4 能否把能力包的业务判断交给 Runner？

不能。Runner 只校验技术条件并执行能力包。业务输入校验、流程选择和结果是否合格由超级专家及其业务服务负责。

### 32.5 为什么能力清单需要管理员再次授权？

签名证明发布者和内容完整性；管理员授权决定该签名发布版在当前 DClaw 租户中可以使用哪些平台能力。两者解决不同问题。

### 32.6 更新 Agent 时是否一定更新本地助手？

不一定。只更新超级专家业务逻辑时上传新密封包；只更新业务连接器时部署业务服务；只更新能力实现时发布能力包。只有公共协议或 Runner 核心能力变化且新包声明更高最低版本时才更新本地助手。

### 32.7 如何区分代码完成和上线完成？

按六个状态分别报告：`source-complete`、`sealed`、`uploaded`、`granted`、`active`、`e2e-verified`。不得用一个“已完成”覆盖全部状态。

### 32.8 为什么能读取源包密钥，却不能把密钥放进签名包？

迁移时读取是为了识别供应商、迁移到受控 Secret 存储并验证真实调用；签名包会被上传或安装到客户设备，内嵌长期密钥会把同一凭证分发给所有安装者。正确结果是产品继续能运行，但运行时只通过业务服务、客户授权绑定或短时本地注入取得所需权限。

### 32.9 FFmpeg、Whisper 和 Python Runtime 属于谁？

它们属于使用它们的 Agent 本地能力包及其依赖，不属于通用 Runner 核心。开发方负责版本、签名、SHA-256、许可证、按需安装、缓存和技术测试；Runner 负责统一安装、隔离、权限、任务状态和清理。

### 32.10 `optional` 和 `required` 如何选择？

没有本地助手仍能完成全部核心承诺，只在可选增强分支使用本地能力时才是 `optional`。任一核心结果依赖下载、上传、FFmpeg、Whisper、模型、渲染、浏览器、设备文件或本地成品时必须是 `required`，进入专家即预检。

### 32.11 历史 canonical 签名包是否有效？

有效。它证明对应历史版本通过当时的服务端 canonical 签名、验证、上传、授权和激活链路。它不能充当后来独立官方 DevKit 的下载、`digest`、`validate`、`build` 或 `verify` 回执；新开发方发布必须使用目标环境认证下载的独立 DevKit。

### 32.12 未签名依赖 ZIP 是否是正式能力包？

不是。只有已签名能力描述符、被描述符 SHA-256 绑定的 capability artifact、完成管理员注册和 Runner 准备后，才能称为正式能力包。外部大资源必须由 capability artifact 内受保护的资源清单固定并完成摘要、SBOM 和许可证校验；普通构建 ZIP 只能称为未签名资源构建输入。

## 33. 唯一外部输入与机器合同

开发方的外部输入固定为三类：

1. 本文文件 `super-agent-development-standard-v1.zh-CN.md`；
2. 开发方自己的业务目标、源 Agent 材料和测试凭证；
3. 从目标 DClaw 认证调用元数据接口并按其 `download_path` 下载、核对 SHA-256 的官方 DevKit。

DevKit `1.2.0` 必须提供：

- `dclaw_agent_devkit.py`：`doctor`、`contracts`、`digest`、`validate`、`keygen`、`build`、`verify`；
- `capability-catalog.json`：当前可声明的能力、版本、组和依赖；
- `schemas/super-expert-manifest.schema.json` 与 `schemas/agent-profile.schema.json`；
- `schemas/local-execution-v1/`：本地请求、响应和错误合同；
- `schemas/super-agent-support-v1/`：能力包、设备消息和凭证绑定合同；
- `templates/minimal/`：最小 manifest、`agent.json` 和 `runtime.py`。
- `bootstrap.ps1`、`bootstrap.sh`、`requirements.lock`、`CHECKSUMS.sha256` 和 `wheelhouse/`：在支持平台离线创建隔离环境，逐文件校验并安装固定加密依赖；
- `THIRD_PARTY_LICENSES.md`：列出随 DevKit 分发的依赖、版本和许可证。

平台方必须用兼容测试证明 DevKit 的能力摘要、规范化 manifest、内容摘要、Ed25519 签名和 ZIP 结构与服务器验收实现一致。DevKit 本身不得出现 `qwenpaw` 导入，不得读取平台仓库相对路径，不得要求安装 DClaw 服务端 Python 包。

平台内部实现文件、测试文件和维护文档可以继续存在，但它们只服务平台维护者，不属于开发方输入。开发方缺少字段或行为定义时应报告标准或 DevKit 缺陷；平台不得用“请克隆服务器源码”回答。

## 34. 版本记录

### 2.0 - 2026-10-26

- 新增“行为等价迁移铁律”，规定源 Agent 的真实可执行代码、测试、副作用和产物是唯一业务基线，文档冲突以可执行证据为准。
- 禁止未经逐项批准改变源流程、用户选择、输入输出、字段、默认值、步骤顺序、供应商/模型、价格、判断、重试、状态语义、产物和完成判据。
- 明确卡片化、安全存储、职责分层和标准任务协议只能替换承载与调用边界；无法等价实现时必须记录阻塞或提交通用平台能力申请。
- 将行为等价对照和差异批准记录加入产品规格、任务模板、迁移步骤、真实验收、完成定义、发布证据包和发布检查清单。
- 更新 2026-10-26 生产核对状态：Server `f88e555`、支持插件 `1.4.0` 和 DevKit `1.2.0` 已部署，Windows 客户端仍须升级并核对 Runner。
- 本次新增强制交付证据和密封、上传、激活门禁，按第 30 节升级主版本；不改变机器合同、插件或 DevKit 版本，按 1.x 标准发布的 Agent 在原兼容范围内继续运行。

### 1.17 - 2026-10-23

- `dclaw.super-agent-support` 更新为 `1.4.0`，Super Agent DevKit 更新为 `1.2.0`。
- DevKit 增加 Windows、macOS 和 Linux 的离线加密依赖 wheelhouse、固定版本锁文件、逐文件 SHA-256 清单和第三方许可证记录。
- 增加 `bootstrap.ps1`、`bootstrap.sh` 与 `doctor`，在隔离环境中使用 `--no-index --require-hashes` 安装并验证依赖，不读取或复制签名私钥。
- DevKit 元数据增加依赖模式、离线引导、支持平台、Python 版本以及锁文件和 wheelhouse 清单摘要。

### 1.16 - 2026-10-23

- 恢复本文的纯通用开发手册边界，删除具体 Agent 的 `agent_id`、显示名称、源包、机器路径、供应商、迁移参数和发布证据。
- 规定具体项目参数只进入该 Agent 自己的 `PRODUCT_SPEC.md`、`ARCHITECTURE.md`、`PORTING_RECORD.md`、`SOURCE_REVISION.json` 和发布记录。
- 将业务示例、历史兼容说明和凭证示例改为中性表达，避免开发方把某个已有 Agent 的实现误认为平台固定规则。

### 1.15 - 2026-10-23

- 明确超级专家承担全部业务逻辑、素材选择/评分、编辑决策、客户交互和卡片调用；业务服务只做受控第三方适配，本地执行侧只做高带宽、高算力和设备侧技术执行。
- 固化 `optional` 与 `required` 的判定门槛，并规定 FFmpeg、Whisper、模型和运行时通过本地助手按受签名 artifact 保护的资源清单按需安装、校验、缓存、升级和回滚。
- 区分供应商 Secret 与安装级业务服务身份，记录当前缺少正式安装级身份合同，生产密封必须失败关闭。
- 增加正式目标 DClaw 认证下载 DevKit、版本组合、服务端 SHA-256、接口错误语义和 `digest → validate → build → verify` 同源证据门禁。
- 区分普通 signer、官方超级专家 signer 和能力包 signer 的信任域；明确私钥不上传且相同公钥跨域仍需分别授权。
- 定义能力描述符签名、artifact 摘要绑定、外部资源清单、HTTPS、允许域、SBOM、许可证和管理员注册顺序；未签名资源 ZIP 只能称为构建输入。
- 增加六态逐项条件与证据，并区分平台版本/部署缺口、平台 Bug、Agent 自有实现和真正缺失的通用能力。
- 记录历史 canonical 服务端链路的正式发布证据仍然有效，但不能替代后来独立官方 DevKit 的发布证据。

### 1.14 - 2026-10-23

- 增加默认优先、最少提问的迁移协议，要求先审包并从源代码、测试、配置和 DevKit 推断答案，只集中询问真正改变实现的未决项。
- 明确迁移项目默认不创建 Git 仓库，使用 `SOURCE_REVISION.json` 追溯；增加私有暂存目录和安全解压规则。1.16 起具体迁移基线只保存在 Agent 项目中。
- 区分迁移阶段可受控读取凭证与发布物禁止内嵌长期凭证，规定开发方共享凭证迁入业务服务 Secret 管理并完成真实验证。
- 明确 FFmpeg、Python Runtime、Whisper 和模型由 Agent 能力包管理，并增加 512 MiB 单包限制下的瘦身、拆分、开发方 HTTPS 按需下载和哈希校验规则。
- 增加卡片迁移、产物保留、失败清理、签名者、版本、源案例、费用和许可证审计默认值。

### 1.13 - 2026-10-23

- 增加超级专家、开发方业务服务、通用 Runner 核心和 Agent 本地能力包的逐项职责分工表。
- 明确 Agent 侧负责业务理解、供应商选择、任务编排和业务验收，本地执行侧只负责客户电脑上的确定性重任务及技术结果验证。
- 增加视频生产完整分工示例，并要求新建开发任务在编码前提交 Agent 侧与本地执行侧的职责映射。

### 1.12 - 2026-10-22

- 将本地助手需求定义为签名能力声明：默认 `none`，`local.execution.session/1` 表示 `optional`，增加依赖该能力的 `local.environment.preflight/1` 表示 `required`。
- `dclaw.super-agent-support` 更新为 `1.3.0`，Super Agent DevKit 更新为 `1.1.0`，能力目录和依赖校验同步发布。
- 专家列表公开返回当前发布版的通用能力声明，Windows 客户端据此只对 `required` 专家自动预检；旧专家无需迁移即可继续运行。
- 插件增加登录用户环境检测接口；DClaw 客户端顶部增加本地助手手动检测入口，统一反馈未安装、插件不可用、启动中、未连接、版本和已连接状态。

### 1.11 - 2026-10-21

- 消除开发标准对 DClaw 服务端源码、`qwenpaw` Python 包、仓库脚本和平台方电脑绝对路径的依赖。
- `dclaw.super-agent-support` 更新为 `1.2.0`，提供独立 Super Agent DevKit `1.0.0` 元数据和 ZIP 下载入口。
- DevKit 提供能力目录、版本化 Schema、最小模板，以及摘要、校验、密封、签名和独立验签 CLI；开发方不需要服务器源码。
- 增加 DevKit 与服务器实现的摘要、签名、密封包兼容测试，并要求在无服务器源码的干净目录完成发布验收。
- 将新任务模板改成读取本文附件并从目标 DClaw 下载 DevKit，删除平台方 Mac 绝对路径和“同一仓库”要求。

### 1.10 - 2026-10-21

- 将服务端镜像的插件交付改为明确自动加载目录，只复制并加载 `dclaw.super-agent-support`，禁止扫描整个源码候选插件目录。
- 修复 `CloudPaw` 因共享 `plugins/bundle` 自动加载而未经授权创建三个普通 Agent 的问题；CloudPaw 继续作为可选源码存在，只有管理员明确安装或启用时才可运行。
- 要求受影响环境在部署修复镜像前先卸载当前 CloudPaw 插件，以调用其插件自有清理流程删除 `cloud-orchestrator`、`cloud-executor`、`cloud-verifier` 及相应工作区；新镜像不得再次创建它们。
- 本版本不改变 1.9 已冻结的 `local_*` 请求、响应、错误或任务状态合同，开发方无需修改已完成的 1.9 对接代码。

### 1.9 - 2026-10-20

- 将 `dclaw.super-agent-support` 更新到 `1.1.0`，冻结环境、能力目录、运行时准备和任务状态的准确响应字段与枚举。
- 确认 DClaw 客户端独立负责 Runner 安装、启动、绑定和升级；Agent 不接收安装器、绑定码或连接 URL。
- 实现 `local_environment_status.wait_seconds` 设备连接长轮询，并将 `bootstrap_session_id` 定义为无授权语义的兼容关联值。
- 增加 `catalog_version`、`availability`、Runner 最低版本判断、能力包准确版本判断和可执行 `user_action`。
- 将检查点任务状态统一为 `awaiting_input`，并自动迁移未部署源码期间产生的 `waiting_for_input` 记录。
- 明确旧 Agent 专属 Relay 的状态字段、安装器和连接地址不进入通用平台合同。

### 1.8 - 2026-10-20

- DClaw Windows 客户端 `2.5.3` 加入已登录用户自动配对、助手后台启动、单实例心跳、进程恢复和退出登录停止。
- Windows 安装包构建改为从 `dclaw.super-agent-support` 固定源码版本编译自包含 Runner，并把生成物作为客户端资源打包；生成的二进制不进入 Git。
- 服务端镜像源码加入通用内置插件目录，使插件可以随镜像交付且仍通过公开插件 SPI 加载；插件状态固定到持久卷。
- 设备引导接口支持复用当前用户已有设备，避免每次客户端启动产生新的配对记录，并阻止跨用户复用。
- 明确当前仍是 `source-complete`：服务端镜像和 Windows 安装包均未构建、发布或部署。

### 1.7 - 2026-10-20

- 实现 `dclaw.super-agent-support` `1.0.0` 源码、三个通用核心 SPI 和卸载隔离。
- 发布八个 `local_*` 的正式 Streamable HTTP MCP 入口、设备配对与 WebSocket 协议、持久任务和标准错误链路。
- 发布能力包描述符、设备消息和凭证绑定 Schema，以及验签注册、加密凭证引用和通用 Windows 本地助手核心。
- 给出 DClaw、插件、Runner、入口和发布状态矩阵；明确源码完成后仍需镜像、客户端集成、插件安装、签名注册和三个真实任务验收。
- 明确开发方服务自己的第三方 Token 由开发方 Secret 管理系统持有，不经过 DClaw；客户自有 OAuth 的 MCP 注入仍是后续通用能力。

### 1.6 - 2026-10-20

- 将超级 Agent 对接所需的新增平台支持统一定义为 `dclaw.super-agent-support` 插件包。
- 明确插件包包含 `local-execution`、`credential-broker`、`capability-packages`、客户端适配和 Windows 本地助手。
- 规定每个已接受的平台缺口必须交付公开协议、Schema、目标版本、实现、测试和状态证据。
- 区分插件机制实现与开发方签名、上传、管理员授权、激活和真实验收等发布门禁。

### 1.5 - 2026-10-20

- 确立本文为开发方唯一需要接收和阅读的人工标准文档。
- 将本地执行和跨平台迁移的规则、流程和变更记录统一收入本文。
- 退役重复的本地执行标准、迁移手册和独立变更记录。
- 规定后续版本保持同一文件路径，通过文内版本号、版本记录和 Git 历史追溯。

### 1.4 - 2026-10-20

- 规定超级 Agent 与本地助手的所有平台支持必须以 `dclaw.local-execution` 插件套件交付。
- 限定 DClaw 核心只提供稳定插件 SPI，禁止核心反向依赖本地执行插件。
- 规定插件未安装、禁用、失败或卸载不得影响 DClaw 核心能力。
- 记录现有核心中的本地会话声明和令牌代码为待迁移的过渡实现，不是开发方接口。

### 1.3 - 2026-10-20

- 明确密封超级专家业务 MCP 只能声明公开鉴权需求，禁止包含任何长期凭证。
- 记录当前通用 MCP OAuth 将 Token 保存到 Agent 配置且不自动刷新的实现限制，不将其定义为密封全局超级专家的按用户 OAuth 合同。
- 记录平台尚无正式的安装级 Secret 注入或开发方服务短期凭证交换能力。
- 规定正式安全鉴权能力发布前，依赖业务 MCP 鉴权的新超级专家生产构建必须失败关闭，不得回退内嵌长期 Token。

### 1.2 - 2026-10-20

- 将“能否按同一公开合同提供给所有超级 Agent”设为平台通用能力的强制门槛。
- 明确授权、版本、环境和配额可以限制实际使用，但平台不得按 Agent、行业或供应商编写特例。
- 明确只服务特定 Agent、行业、客户、供应商或业务流程的功能通常归开发方实现。
- 更新平台能力缺口申请、评审结论和协作分类标准。
- 修正本地执行可用性说明：当前只有平台授权令牌和 Schema，公共网关与通用 Windows 本地助手仍待平台正式建设。

### 1.1 - 2026-10-20

- 增加开发方会话与 DClaw 平台维护会话的直接协作流程。
- 规定平台通用能力新增或修改必须先由 DClaw 平台负责人确认。
- 规定符合已发布合同的 DClaw 平台 Bug 可以直接修复并向开发方返回结果。
- 明确会改变公开合同的缺陷修复仍按平台通用能力修改审批。
- 要求能力、代码和开发标准在同一次交付中同步更新版本与记录。

### 1.0 - 2026-10-20

- 确立开发方与 DClaw 平台方两个组织责任层。
- 规定能力清单、密封、签名者入驻、管理员上传、整体授权和原子激活流程。
- 统一超级专家、业务服务、第三方 API、本地能力网关、本地助手核心和能力包的边界。
- 增加本地成本放置、错误定位、真实验收、发布证据和平台能力缺口申请标准。
- 提供第三方开发者可直接使用的新 Codex 任务模板。
