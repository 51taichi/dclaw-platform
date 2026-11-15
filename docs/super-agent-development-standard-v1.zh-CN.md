# DClaw 第三方超级 Agent 开发、密封与协作标准 V2

状态：`stable`

标准标识：`dclaw.super-agent-development`

当前版本：`2.56`

发布日期：`2026-11-15`

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

开发者应把本文作为新 Codex 任务的第一份入口文件。本文包含全部人工开发规则；字段级机器合同、模板和密封工具由目标 DClaw 的官方 Super Agent DevKit 提供。平台发布的 DClaw 超级 Agent 开发包把本文、DevKit、公开 SDK、模板、夹具和离线演练组合为一个带独立版本与校验和的交付物。本文与同版本 DevKit Schema 不一致时，以机器 Schema 为准，并向平台方提交文档缺陷。

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
7. 第三方开发者优先取得官方 DClaw 超级 Agent 开发包；开发包必须包含本文的准确版本和官方 DevKit，不得维护第二份人工规则。单独 DevKit 下载入口在兼容期内继续可用。

迁移开发者应先执行第 27.2 节的“默认优先、最少提问”规则。收到本文和源包即可开始安全盘点与源码迁移；不要求用户先填写项目身份、Git、操作系统、依赖、卡片、签名和验收问卷。

## 2. 规范用语与核心概念

本文中的“必须”“禁止”表示强制要求；“应”表示原则上必须执行，只有记录充分理由后才能例外；“可以”表示可选。

| 名称 | 定义 |
|---|---|
| 超级 Agent | 面向客户交付完整业务结果的产品，至少由密封超级专家组成，并可按真实本地重任务增加本地能力包 |
| 超级专家 | DClaw 中 `package_type=super_expert` 的签名密封运行包，负责理解意图、编排业务、调用获授权能力和完成回复 |
| 能力清单 | 密封 manifest 中声明的不可变平台能力集合；安装时由管理员整体授权 |
| 密封 | 对发布内容计算摘要并使用 Ed25519 私钥签名，使平台可以验证来源、完整性和能力声明 |
| 业务服务 | 只在原业务本来就有独立服务端或确有共享持久数据时保留的开发方服务；不得为了调用第三方 API 而默认新增 |
| 平台能力 | 可供多个无关 Agent 复用、不包含行业规则的通用能力 |
| 本地助手 | DClaw 桌面版配套的 Windows 通用工具箱，技术名称可称 Runner |
| 本地能力网关 | DClaw 提供的通用 MCP 和任务网关，历史代码中可能称 Relay |
| 本地能力包 | 开发方交付、由本地助手按协议安装和执行的 Agent 专属代码 |
| 客户端 | 客户直接使用的 DClaw 桌面版；它是唯一登录和业务交互入口 |
| 安装授权 | 对某个签名发布版的完整能力清单进行一次性整体授权；自助发布由开发者本人授权，历史官方包仍由管理员授权 |
| `trace_id` | 跨平台、超级专家、网关、本地助手、能力包和外部服务关联日志的追踪标识 |

“超级 Agent”是产品概念，“超级专家”是 DClaw 密封包类型。开发一个超级 Agent 时至少交付超级专家包；只有业务确实需要时才增加业务服务和本地能力包。

## 3. 两方协作模型

```mermaid
flowchart LR
    U[客户] --> D[DClaw 客户端与平台]
    D --> E[签名密封超级专家]
    E --> X[超级 Agent 侧调用第三方 API]
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
      P
    end
```

第三方 API 是开发方业务实现的依赖，其选型、凭证、费用、重试和结果解释都归开发方。DClaw 平台不因承载请求而成为第三方业务依赖的所有者。

密封超级专家是业务控制中心，必须承载全部产品业务逻辑：客户意图与状态、业务流程编排、第三方 API 选择与调用、安装级业务凭证、素材来源选择、候选评分与筛选、脚本与编辑决策、返工策略、客户交互、DClaw 卡片调用和最终业务验收。第三方长期 Key 属于 Agent 侧，但必须保存在按用户、Agent 安装和 scope 隔离的加密凭证存储中；密封源码、manifest、聊天、日志和本地任务都不得接触明文。原业务确实已有独立业务服务时可保留，但不得因迁移或凭证保存需求新增外部业务服务、域名或 audience 链路。

### 3.1 唯一允许的依赖方向

```text
DClaw 平台 -> 密封超级专家
密封超级专家 -> Agent 侧受控第三方调用 -> 第三方 API
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

所有只服务超级 Agent 的平台能力必须统一由可选的 `dclaw.super-agent-support` 插件包拥有和实现，不得把实现写入 DClaw 核心业务模块。判断标准是能力的实际使用者和产品语义，而不是代码当前位于哪个目录；如果除超级 Agent 外没有其他 DClaw 功能使用该能力，它就属于本插件。该插件包当前及后续可以包含交互组件、MCP、AIGC、运行编排、密封包生命周期、本地执行等多个模块，而不是只有卡片组件。具体包括：

- `local-execution` 模块：对外使用 `dclaw.local-execution` 公共合同，注册十二个通用工具，实现设备路由、任务、检查点、本地文件选择、直传、产物、错误和追踪；
- `credential-broker` 模块：把 Agent 侧使用的客户或开发方第三方凭证加密保存为不透明引用，按用户、Agent 安装、凭证类型和权限范围隔离，支持撤销与轮换，并只在 Agent 已授权的受控第三方请求边界注入；本地助手只能接收公开或短时预签名资源 URL，不得接收第三方长期 Key；
- `agent-outbound` 模块：向密封超级 Agent 提供与供应商无关的受控 HTTP/MCP 出站合同，校验目标域、方法、大小、超时、重定向和授权 scope，并在运输边界通过安装级稳定 `credential_slot` 或兼容的 `credential_ref` 注入凭证；该模块不识别供应商、不决定业务参数、不创建 Agent 不可见的业务状态；
- `agent-outbound-stream` 模块：为有明确大小上限的 HTTPS 二进制响应和 WSS 流提供受控运输，把结果写入临时资源存储并只向 Agent 返回不透明资源引用、摘要和媒体事实；媒体字节会经过该受控插件运输，但不得进入模型上下文或普通 DClaw API 响应；
- `resource-exchange` 模块：提供按租户、用户、会话、Agent、发布版、安装和调用隔离的短时资源上传、读取和撤销合同；大文件通过预签名 HTTPS 在对象存储、第三方服务和本地助手之间传输，DClaw 服务进程不代理字节流；
- `capability-packages` 模块：实现能力描述符、Schema、签名验证、注册、安装、版本、授权和回滚；
- `public-components` 模块：独立拥有只供 Super Agent 本地重任务复用的 Python Runtime、Node.js、FFmpeg、Whisper 等公共 Component，包括公共性评审、分平台制品构建、许可证和 SBOM、签名、HTTPS 制品上传、完整注册表、版本兼容、本地助手按需下载、验签、缓存、原子安装和回滚；管理面只提供版本化无界面 API/CLI，供迁移 Skill 和平台维护自动化调用；
- `interaction-components` 模块：拥有超级 Agent 使用的选择、问答、文件选择等卡片合同、状态机、工具和路由；
- `aigc-adapter` 模块：拥有超级 Agent 对公共 AIGC 工作流的任务绑定、事件投影、客户完成、工具适配和业务侧状态；历史审核状态仅作兼容读取；
- `workspace-runtime` 模块：拥有超级 Agent 的确定性回合编排、流程运行时、公开流式投影和媒体交付适配；
- `sealed-super-agent-lifecycle` 模块：拥有 `super_expert` 包类型的 manifest 校验、签名者用途授权、安装授权、运行特性和信任策略；
- Super Agent 专属 MCP 服务、工具目录和协议适配；新增 MCP 或其他能力时继续按同一归属规则放入插件；
- DClaw 客户端插件适配：在已登录客户端内完成安装、更新、连接和用户交互引导；
- 通用 Windows 本地助手：作为插件套件的配套客户端组件独立发布，执行受信能力包；
- 公共合同和测试套件：提供 Schema、兼容性夹具和边界测试。
- 官方 Super Agent DevKit：提供独立 CLI、版本化 Schema、能力目录和最小模板，并通过插件公开下载；DevKit 不得导入 DClaw 服务端模块。

DClaw 核心只提供与业务无关的插件 SPI 和确实被其他 DClaw 功能共同使用的基础设施，包括插件生命周期、已验证的租户/用户/Agent/发布版/会话主体、能力授权校验、受控消息通道、插件隔离存储、审计追踪、通用 MCP 客户端及公共 AIGC Studio 执行基础设施。超级 Agent 对这些基础设施的适配、策略、工具和状态投影仍归插件。公共 Component 的概念、ID、注册表、版本、制品、签名、下载和本地安装协议均属于插件内部与公开合同，DClaw 核心不得识别或管理这些对象。插件只能依赖公开 SPI，DClaw 核心不得导入或调用 `dclaw.super-agent-support` 插件的内部模块。

必须同时满足：

1. 未安装、禁用、升级失败或卸载该插件时，普通对话、普通 Agent、公共文件能力、公共 AIGC Studio、通用 MCP 基础设施和其他平台能力仍可正常使用；插件提供的超级 Agent 卡片、AIGC 适配、编排、密封扩展和本地执行入口必须同时卸载并失败关闭。
2. 插件的路由、配置、数据表/命名空间、队列、日志和迁移必须可独立安装、升级、回滚和删除。
3. 核心不得硬编码 `local_*`、Runner 版本、能力包类型或任何 Agent 的业务名称；目录和工具由插件安装时注册。
4. 插件即使与 DClaw 核心暂时运行在同一进程，也必须保持独立包、单向依赖和可单独发布；同进程不等于允许写入核心。
5. 超级 Agent 开发方只依赖已发布的 MCP 凭证、`local_*` 和能力包公开合同，不得导入 DClaw 核心或插件内部代码。
6. 服务端镜像必须使用明确的自动加载白名单交付平台插件。源码仓库中的插件目录只是候选目录，禁止把整个目录设为自动加载路径；未获平台方明确启用的插件不得注册 Agent、工具、路由或修改持久工作区。
7. 插件必须提供与当前平台合同匹配的 DevKit 下载入口；DevKit 输出必须通过平台实现的兼容测试，开发方不得被要求取得平台源码。
8. 核心只能按通用 SPI 查询“某包类型支持哪些运行特性”或“某能力由哪个插件处理”，不得用 `super_expert` 名称硬编码工具、MCP、输出额度、Skill 覆盖、AIGC 或卡片分支。
9. 为兼容旧签名 Agent，可以保留旧 Python 导入路径和旧 manifest 默认值的薄转发层；转发层不得承载实现，插件缺失时运行入口必须返回明确不可用状态。
10. 每次迁移或新增插件能力后必须执行核心残留审计，把命中项逐一归类为通用 SPI、共享基础设施、持久数据合同、历史兼容壳或违规专属实现；无法归入前四类的实现必须迁入插件。
11. 历史兼容壳只能加载并转发插件公开对象，不得保留加密、会话签发、状态机、工具、路由、业务规则或专属默认配置。旧名称可以继续解析，但新代码禁止依赖旧名称。
12. 平台必须用自动测试证明插件未加载和卸载后的普通登录、普通对话、普通 Agent、公共文件、公共 AIGC Studio、通用 MCP、计费与备份链路不依赖插件内部模块。
13. 核心配置示例只发布通用配置名；旧 Super Agent 专属环境变量只能由兼容读取逻辑临时接受，不得继续作为新部署模板的推荐配置。
14. 公共 Component 管理禁止新增 DClaw 客户端页面、管理后台页面、菜单、按钮或普通用户入口；迁移 Skill 必须直接调用插件 API/CLI 完成查询和提交，平台维护自动化通过同一合同完成发布和注册。
15. 在核心插件 SPI 版本不变时，插件安装、升级和回滚必须通过事务化热加载完成，不得要求重启 DClaw 主服务。热加载必须保留已生效配置和 signer，失败时恢复旧文件、旧配置和旧运行注册；只有核心 SPI 本身发生不兼容升级时，才允许作为独立的核心升级要求重启，不能把它当作普通插件更新步骤。

### 3.2.1 插件接口稳定性与现役专家适配

`dclaw.super-agent-support` 对专家公开的能力必须以接口为边界：能力 ID 与合同版本、可信身份来源、请求、成功响应、错误、事件、幂等、状态和授权语义由版本化 Schema 及测试固定；插件内部实现可以替换，但不得按具体专家名称分叉公共合同。新增可选能力须显式声明并授权，不得自动改写已签名专家的能力清单。

每次修改插件公共能力时，平台维护方必须在发布前完成以下门禁：

1. 列出实际受影响的能力 ID、合同版本、字段、错误、事件、状态和权限语义；按生产已激活 Release 的 manifest、授权与真实调用路径盘点使用它的专家，不以某一个专家成功代替其他专家验证。
2. 对既有合同保持原请求与响应的兼容行为，并运行旧签名包或等价冻结夹具回归。内部缺陷修复应在原合同内完成；若需改变既有字段含义、必填项、错误类别、状态转换或权限，则发布新的合同版本，与旧版并行运行，在兼容窗口内不得撤销旧版。
3. 若改动会影响任何已上线专家，平台维护方必须同步处理每个受影响专家：取得该专家的业务基线和责任方发布输入，完成适配、原业务路径回归、重新密封验签、授权与版本升级，并核对生产激活回执。不得只发布插件后把专家的修复留给客户测试；也不得直接改写已签名包或在生产状态中手补业务结果。
4. 发布顺序须使旧专家在插件切换前后都可运行：先交付兼容插件，再逐个升级需要适配的专家；不兼容合同必须并行提供旧版。任何一个受影响专家未完成适配与回归时，不得撤掉其仍使用的合同。插件热加载失败或回归失败时按插件回滚点恢复，专家发布失败时保留上一激活版。
5. 发布回执须列出受影响与不受影响的专家、各自实际 Release、覆盖的调用路径、合同测试结果、待升级项和回滚目标。无影响也须给出依据，不能只写“向后兼容”。

### 3.3 开发方问题的插件交付范围

开发方在对接中发现的平台通用能力缺口，经平台方确认后纳入 `dclaw.super-agent-support` 插件包。每个接受的缺口必须在同一交付中明确：

- 公开能力或工具名称及语义；
- 请求、响应、事件、错误和能力描述符 Schema；
- 插件目标版本、最低 DClaw 核心 SPI 版本、客户端版本和 Runner 版本；
- 实现代码、数据迁移、合同测试、核心隔离回归和兼容矩阵；
- 开发、签名、安装、测试和生产状态，不得用单一“已完成”代替。

“正式 DClaw 对接仍缺配套协议、Schema 和目标版本”属于本插件包的平台交付问题。插件必须提供协议、Schema、版本和真实接入点后，开发方才能完成正式集成。

“尚未签名、上传或上线”是插件实现后的发布门禁：插件提供签名验证、注册、安装和授权机制；开发方仍要签名并上传自己的超级专家包。`super_expert_public` 由开发者普通登录身份自助上传、授权并激活，激活后立即公开；历史 `super_expert` 继续走管理员发布链路。公共 Component 和能力包的平台注册仍由插件管理并按各自合同授权。插件代码完成不会自动使 Agent 上线。

### 3.4 所有超级 Agent 的公共业务骨架

所有新建、移植和优化的超级 Agent 都必须使用同一套业务执行骨架。不同 Agent 可以有不同字段、节点、第三方服务、生成方式和完成判据，但不得绕过以下职责和流程：

```mermaid
flowchart TD
    A[按当前节点用 DClaw 卡片采集需求] --> B{当前节点的信息是否足够执行}
    B -->|否| A
    B -->|是| C[密封超级专家执行业务编排]
    C --> D[按需调用大模型或 DClaw 公共 AIGC]
    C --> E[超级 Agent 按需调用第三方 API]
    C --> F[按需调用本地助手执行本地任务]
    D --> G{是否需要继续采集或确认}
    E --> G
    F --> G
    G -->|需要| A
    G -->|不需要| H{是否需要制作最终视频或其他内容产物}
    H -->|不需要| K[超级专家验收并交付业务结果]
    H -->|需要| I[超级专家确定素材、脚本、制作方案和验收标准]
    I --> J{是否包含本地文件或重任务}
    J -->|否| L[使用 DClaw 公共 AIGC 或远程能力制作]
    J -->|是| M[本地助手下载、剪辑、转码、合成并输出]
    L --> N[超级专家检查真实产物]
    M --> N
    N -->|不合格| C
    N -->|合格| K
```

强制规则：

1. **卡片按节点采集。** 不要求在开始时一次收集全部需求；当前节点取得足够事实后即可执行。已经从对话、附件、源包或前一节点取得的值必须复用，不得重复询问。
2. **采集与执行允许交替。** 大模型、第三方 API、本地助手或生成任务产生新的必要问题时，回到对应卡片节点继续采集或确认；不得把自由文本猜测当成客户已提交卡片。
3. **超级专家始终是业务控制中心。** 它负责决定何时调用哪项能力、如何组合结果、是否继续、是否返工以及最终是否合格。业务服务、本地助手和平台能力不得替它改变业务目标或完成判据。
4. **大模型和第三方调用按需出现。** 第三方业务 API 由超级 Agent 侧调用；供应商选择、请求参数、调用顺序、计费、幂等、轮询、重试、降级和结果解释都不得下沉到本地助手。本地助手只对 Agent 已取得的素材、公开或短时预签名 URL 和确定加工参数执行数据面任务。
5. **本地助手不是固定前置。** 只有步骤涉及客户本地文件、浏览器、桌面软件、大文件下载上传、音视频处理或高 CPU、内存、磁盘和网络任务时才调用。本地助手可以出现在中间业务节点，也可以出现在最终制作节点；没有本地任务时保持 `none`。
6. **最终视频或其他内容制作是条件分支。** 需要制作时，超级专家先确定素材、脚本、制作方案和验收标准，再按任务性质选择 DClaw 公共 AIGC、远程能力或本地助手；不需要制作时直接进入业务结果验收。
7. **真实产物验收后才完成。** 工具调用成功、任务创建成功或接口返回 URL 都不等于业务完成。超级专家必须检查实际产物；不合格时回到造成问题的业务节点返工，合格后才交付。
8. **移植不得改变骨架中的业务语义。** 卡片化和职责拆分只改变交互与执行位置，源流程已有的字段、分支、调用条件、返工和完成标准必须保持；从零开发和优化则以已确认的需求或版本基线为准。

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

### 6.2 Agent 侧第三方调用

需要第三方 API 时，由超级 Agent 管理调用合同、业务状态和加密凭证引用；不得为了调用 API 默认新增外部业务服务：

```text
密封超级专家
├── Agent 安装级加密凭证引用
├── 受控第三方 HTTP/MCP 调用
├── 业务状态、幂等、轮询、重试和费用判断
└── 结果 URL、结构化事实或短时资源授权
```

只有原业务本来就依赖独立服务端，或确实存在跨客户共享持久数据时，才能保留业务服务；迁移不得自行新增域名、HTTPS audience 或第二套运行服务。

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
| 6. 测试与业务验收 | 在开发或测试环境验证卡片、状态机、外部合同、失败恢复和真实业务案例 | 保障测试平台可用 | 自动测试与业务验收证据 | 已确认业务范围通过且失败可定位 |
| 7. 密封 | 计算能力摘要、签名并独立验包 | 确保签名者已入驻 | 签名 ZIP、校验和、发布记录 | 验签、摘要和运行时合同通过 |
| 8. 上传 | 使用管理员账号上传并核对元数据 | 执行平台验签和运行时验证 | release ID | 状态可进入授权阶段 |
| 9. 授权激活 | 核对能力预览、整体授权和激活 | 固化授权并原子切换 | installation ID、激活记录 | 新版为 `active` |
| 10. 客户验收 | 项目方从正式 DClaw 客户端自行执行真实用户任务；开发会话不代替操作 | 提供审计和故障定位 | 项目方确认的 `e2e-verified` 证据 | 项目方决定是否向客户开放 |
| 11. 维护 | 监控业务质量、费用和第三方变化 | 维护公共能力和兼容窗口 | 变更记录、回滚包 | 每次发布重复门禁 |

任何平台增强都必须有独立版本和发布计划。开发方不得把“平台方已接受需求”视为能力已经可用，也不得在目标平台目录尚未发布时写入生产 manifest。

## 7. 成本与数据放置规则

### 7.1 默认放置

| 工作负载 | 默认位置 | 原因 |
|---|---|---|
| 对话、授权、任务控制和小型 JSON | DClaw/超级专家 | 便于统一身份与编排 |
| 第三方 API 决策与短请求 | 超级 Agent 侧 | 业务所有权、凭证隔离和调用状态都不下沉本地助手 |
| 大文件下载 | 客户本地 | 避免服务器带宽和磁盘中转 |
| 视频剪辑、转码、压缩 | 客户本地 | 避免服务器 CPU、内存和磁盘成本 |
| 浏览器和桌面软件自动化 | 客户本地 | 依赖客户设备与登录状态 |
| 最终产物 | 默认客户本地 | 仅业务确需共享时受控上传 |

### 7.2 强制数据规则

- 服务端只传控制消息、元数据、小型结构化结果和短时授权。
- 第三方服务返回资源 URL 后，本地助手应从受信源站直接下载。
- 长期 API Key、Cookie、刷新令牌不得进入提示词、聊天消息、trace 或本地任务输入。
- 本地助手只能使用超级 Agent 已取得的公开或短时预签名资源 URL；不得获得第三方长期 Key，不得创建、轮询或解释第三方业务任务。
- 视频、音频和其他大文件最终必须落到客户本地任务或输出目录；DClaw 和超级 Agent 只保留不透明产物引用、摘要和媒体事实。
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
| `agent.execute` | 至少传本轮 `messages`；普通文本和 JSON 候选使用默认无工具模式，其他确需模型工具调用的能力才传 `execution_mode="agent_loop"` | 内部模型候选，不自动成为客户回复 |
| `runtime.trace` | 结构化、无 Secret 的诊断对象 | `{"accepted":true}` |
| `runtime.complete` | 当前 `invocation_id`、合法 assistant `message`、可选 `diagnostics` | `{"accepted":true}` 并原子提交 |
| `runtime.fail` | 当前 `invocation_id`、稳定 `error_code`、可选 `diagnostic_ref` | `{"accepted":true}` 并丢弃事务 |
| `runtime.failure.read/1` | 可选授权能力；请求必须为 `{}` | 同一任务、用户、租户和专家最近一次失败的脱敏诊断，或 `no_record` |

`runtime.complete` 与 `runtime.fail` 每轮只能二选一调用一次。DevKit 的 `templates/minimal/agent/runtime.py` 是不依赖服务器源码的最小可运行示例。

`agent.execute` 的正式控制边界：默认候选模式可选传 `response_format="json_object"`，Host 会以无工具的模型调用请求 JSON object，但模型是否返回可见文本、是否符合业务 Schema 仍必须由 Agent 校验。`response_format` 不得与 `execution_mode="agent_loop"` 同用。当前合同不支持强制业务 JSON Schema、调用方指定 `max_tokens` 或调用方控制 thinking。`agent_loop` 可使用 `instruction`、`require_interaction`、`public_stream` 及 `recover_empty_reply` 的已实现参数；其中空回复恢复只尝试一次无工具的文本生成，不保证结构化 JSON，不得代替 Agent 自己的候选校验。

`runtime.failure.read/1` 是可选能力，不加入既有 V1 基础闭包。新发布包须在 manifest 和授权清单中显式声明后才能调用；旧发布包与旧 grant 保持原状。Host 只接受空对象请求，使用可信会话 ID、用户 ID、agent ID 和安装授权核对任务所有权，并仅在同租户同专家的历史 installation 中查找。返回最近 30 天内最后一次失败的 invocation、实际 release/installation、开始及失败时间、首个脱敏 `phase/category/attempt`、诊断来源、错误码和 `transaction_status=discarded`；无记录返回 `status=no_record`。`first_failure_source=agent_trace` 表示阶段与类别由专家写入的 trace 报告；`host_stage` 表示 Host 记录的候选调用异常；`platform_preflight` 表示插件在专家 runtime 启动前记录的首错，此时 invocation ID 带 `preflight-` 前缀，不代表专家已执行；没有记录时返回 `not_recorded` 和空字段，不得臆造。请求越权或参数不合法失败关闭。该能力在失败事务丢弃后仍可读取，也支持同一专家新安装续接旧安装的失败诊断；不返回模型正文、thinking、对话、客户素材或 Secret。请求与响应 Schema 位于 DevKit `schemas/runtime-failure-v1/`。

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
| `business_identity` | 安装绑定的业务服务短时身份与受控出站调用 | 本文第 25.2.1 节与 DevKit `business-identity-v1` Schema |
| `agent_outbound` | 超级 Agent 自主编排的第三方业务 API 受控出站 | 本文第 25.2.2 节与 DevKit `agent-outbound-v1` Schema |

代码不得根据能力名称猜参数；使用前读取对应版本协议或实时目录。

使用公共 AIGC 时，超级专家通过 `agent.execute(execution_mode="agent_loop")` 调用按授权动态注册的 `aigc_workflow_catalog`、`aigc_workflow_create`、`aigc_task_status` 和按需的 `aigc_task_resume`。先读取实时目录及 `WorkflowBlueprint` Schema，再创建或恢复任务；创建任务不等于生成完成，最终只以平台持久化的 `ACCEPTED` 状态和绑定产物验收。客户点击“完成并返回会话”后由平台直接完成，不调用 Agent/模型审核。新建或更新的专家不得声明或依赖审核写能力，也不得把 `aigc_task_review` 当作验收步骤。`aigc.asset.submit` 与 `aigc.review.complete` 能力 ID 只为已安装旧包和历史记录解析保留；非前端 submit 与所有 review 新写入分别返回 `AIGC_ASSET_SUBMIT_RETIRED`、`AIGC_REVIEW_RETIRED`。对已经签名且仍声明 `aigc.review.complete` 的旧包，运行时可注册同名 `aigc_task_review` 只读兼容工具：它只按当前安装、会话和物料任务读取平台持久化状态，忽略旧 decision/assessment 参数，不观察媒体、不触发模型审核、不写审核结论；任务已由客户完成时返回顶层 `status=ACCEPTED`、`completion_source=customer`、`review_performed=false` 和 `write_applied=false`，允许旧专家继续会话；未完成时返回真实任务状态和 `customer_action_required=true`。历史 `SUBMITTED/REVIEWING` 状态及审核回执只读，并由客户完成按钮迁移为 `ACCEPTED`。未授权的工具不会注册，Agent 不得自行构造内部接口。

DevKit `aigc_workflow_api_demo.py` 与 `examples/aigc-workflow-v1/README.md` 给出目录、建任务、客户操作后快照及资产校验的参考实现。AIGC 任务卡由工作流创建操作投影，不使用问答卡的 `interaction.card.create/1`；模型工具通过 `agent_loop` 动态注册，`aigc.task.snapshot/1` 是独立的只读 Host 调用。`agent_loop` 不得叠加 `response_format="json_object"`。本地助手的 `local_task_api_demo.py` 和 `examples/local-task-host-v1/README.md` 给出启动、按真实任务 ID 回读和终态产物校验的参考实现。两个示例都只说明已发布合同，不授权新能力，也不能替代目标实例实时目录与客户端验收。

能力出现在 manifest 目录、文档或 Schema 中，只证明平台识别该能力声明，不证明对应运行服务已经生产可用。开发方必须同时核对目标环境的能力可用状态、生产入口和最低组件版本；平台未发布这些信息时不得自行猜测地址或把业务参考实现当作公共平台。

截至 2026-10-27 的上一生产基线为 Server `1.1.10`、提交 `db08ac40fb0033d6c944636da58b2ce82686a951`、`dclaw.super-agent-support` `1.9.0`、Developer Pack `1.4.0` 和 DevKit `1.3.0`。该基线已完成认证下载和健康核对，但 Developer Pack `1.4.0` 未读取 `resources.lock.json`，不得再用于生成新的正式本地能力或超级专家发布包。

本标准 `2.19` 的正式组合为 Developer Pack `1.8.0`、支持插件 `1.14.0`、DevKit `1.7.0` 与 Runner `1.3.0`。该组合在既有公共 Component、非入口 export 绑定和业务服务身份合同之外，正式发布 `agent.outbound/1`：第三方业务请求完全由超级 Agent 决定，插件只执行凭证隔离、策略校验和最终网络运输；本地助手不接收第三方长期 Key。旧已签名 Agent 和既有合同继续按原版本运行。

本标准 `2.23` 的正式组合为 Developer Pack `1.9.3`、支持插件 `1.16.0`、DevKit `1.8.3` 与 Runner `1.3.0`。该组合将通用本地助手的二进制发布和版本清单归入支持插件，DClaw 客户端只负责按需下载、摘要校验、原子切换、启动与回退。

本标准 `2.24` 的组合为 Developer Pack `1.10.0`、支持插件 `1.17.0`、DevKit `1.9.0` 与 Runner `1.3.0`。新增普通登录用户自助签名登记、上传和全局发布的 `super_expert_public` 包类型；已有 `super_expert` 包和管理员发布链路保持兼容。新包类型的业务 Python 只在隔离进程执行，Agent 本体仅有密封运行时的受限工具集；所需业务 API、本地助手和 AIGC 仍通过签名能力清单与插件公开合同调用。

本标准 `2.25` 的组合为 Developer Pack `1.10.1`、支持插件 `1.18.6`、DevKit `1.9.0` 与 Runner `1.3.0`。仅增加插件维护侧的跨安装工作状态恢复合同；Agent 包、签名、能力清单、DevKit 运行合同和既有发布链路不变。

本标准 `2.26` 的组合为 Developer Pack `1.10.2`、支持插件 `1.18.7`、DevKit `1.9.0` 与 Runner `1.3.0`。跨安装恢复支持显式初始化尚无状态文件的目标安装；其他合同保持不变。

本标准 `2.27` 的组合为 Developer Pack `1.10.3`、支持插件 `1.18.8`、DevKit `1.9.0` 与 Runner `1.3.0`。修复公开专家隔离容器在插件热更新后失去工作进程文件的部署缺陷；业务与运行合同不变。

### 跨 Release 安装与工作状态恢复

同一个超级专家发布新版时，每个 Release 独立签发 installation ID。旧安装的状态按 installation ID 与 session ID 隔离保存，不会因激活新版而删除。插件 `1.18.15` 起，使用正式合同 `workspace.state.continuity/1` 在新版第一个业务回合进入 Agent runtime 前自动续接同一租户、同一专家、同一任务和用户的完整状态；不再逐字段搬运作品修订。Agent 的 `propose` 等新建修订操作不得冒充历史恢复。

有持久作品状态的新版 Agent 须在签名包内附 `agent/state-contract.json`，按 DevKit `1.9.3` 的 `schemas/workspace-state-continuity-v1/state-contract.schema.json` 声明 `contract`、稳定的 `format_id`、整数 `schema_version` 和含一个 `{identity_sha256_24}` 占位符的 `filename_template`。该占位符按 `installation_id`、`user_id`、`session_id` 依次用 `\x1f` 连接后取 SHA-256 前 24 位。只有来源和目标签名者相同、声明的格式和 Schema 版本相同、状态文件名均符合各自声明、来源签名目录摘要与发布记录一致，插件才将来源整个任务状态复制到新 installation，唯一替换 `identity.installation_id`。状态正文不写入迁移回执；来源文件不变。

目标状态已有内容但没有可信的续接回执、来源或目标声明缺失、Schema/签名/身份/文件名不一致，以及来源修订未完整保留时，插件在 runtime 启动前失败关闭，记录可定位的脱敏 `state_*` 类别；不得创建空作品或覆盖已有修订。复制通过安装和任务锁串行化，先写准备回执，再原子提升目标目录并绑定 Agent 实际读取的状态文件名，最后写提交回执。中断后只允许验证目标摘要并恢复未完成的绑定；重复调用读取相同提交回执，目标已经新增修订时须保持来源修订前缀，不再回写旧状态。连续两次兼容升级按同一合同逐次续接。

已签名的旧 Release 无法补写声明时，插件维护方可使用 `tools/continue_workspace_state.py register-legacy-pair` 对两个发布摘要和完全一致的已签名状态代码做一次兼容登记；必须先只读预检，再以预检摘要提交。此登记不修改签名包，也不推断业务兼容。管理员可用同一工具的 `resume` 子命令先预检再提交指定任务，之后由业务回合自动续接。新版状态结构不兼容时，开发方须先提供显式迁移方案，插件不得假装兼容。以下 `workspace.state.empty-field-migration/1` 是历史逐字段恢复合同，仅用于旧版特殊修复，不是兼容新版的默认升级流程。

插件 `1.18.16` 起，普通开发者 `publish upload` 的安全顺序为：先本地验签和完整包校验，再上传安装为未激活 Release，签发该 Release 的安装授权，随后对同租户同专家已有任务逐一预检来源与目标签名状态合同、目标空置或可信续接回执；全部通过才切换 active Release、保存配置并加载运行时。成功响应中的 `state_continuity={contract,status:ready,checked_tasks}` 是本次激活前预检回执，不表示任务状态已迁入；实际复制仍在该任务下一次业务回合前按原子合同执行。预检发现缺失的旧版登记、格式/Schema/签名/身份冲突时返回脱敏 `state_*` 类别，旧版保持激活；新版保留为已上传、已授权、未激活，可在平台维护方完成有证据的旧版兼容登记后重试激活。配置保存或运行时加载失败则恢复旧 active Release 与配置；不得自行创建空作品。已签名的旧包、现有 DevKit 密封格式与作品状态均不重写。

内部 `agent.execute` 候选和本轮临时系统指令只供业务运行时判定，不属于客户聊天记录。插件 `1.18.16` 起每个业务回合结束后先恢复执行前的 Agent memory，再仅加入客户本轮输入与经 `runtime.complete` 接受的正式回复，或失败提示。历史上已写入的内部消息不会自动删除；平台维护方只能按具体消息 ID、内容 SHA-256 与整份聊天状态 SHA-256 使用插件工具 `tools/repair_internal_chat_history.py` 预检、备份和原子修复，保留客户消息、正式回复和作品状态，不得凭文本模式批量删除。刷新历史接口回读和下一轮加载须复核已清理消息不再出现。

该合同由 `dclaw.super-agent-support/tools/migrate_workspace_state.py` 提供，只有持有生产主机维护权限的插件维护方执行，不开放给 Agent 或普通开发者，也不要求修改 DClaw 核心。预检默认只读；指定来源和目标 installation ID、同一 session ID、状态所属 user ID 及 JSON Pointer。插件核对两项安装授权属于同一租户和 Agent、不同 Release，且两份状态的安装/会话/用户身份正确。合同 v1 仅支持把来源状态 JSON 中一个非空数组填入目标状态中同位置的空数组；目标已有值、身份字段、跨租户/Agent/用户/会话、多个状态文件或符号链接均失败关闭。不解释业务字段或自动改写现有引用。首次初始化目标状态时，还必须由开发方给出新版 Agent 实际读取的目标状态文件名，平台在预检和提交时核对该文件名；不得沿用旧安装的文件名。

如果旧版迁移已把状态写入错误文件名，且新版 Agent 在正确文件名下另建状态，平台维护方使用插件内 `workspace.state.shadowed-migration-reconcile/1` 工具先只读预检两份文件、身份、安装授权、迁移回执和 SHA-256。确认后，工具把新版 Agent 后建状态原样归档，再将已迁入的历史状态原样激活至 Agent 实际读取的文件名，保留原始内容及修复回执。该操作不合并或重写业务修订；归档的候选若需恢复为新版本，须由开发方另行处理。

迁移提交后，插件还会将目标文件名绑定到该 installation/session。此后每次运行时事务提交前，插件检查该作用域内的 JSON 状态文件是否仍只有绑定的文件名；专家若因错误文件名另建状态，事务必须失败关闭，生产旧状态保持不变，并留下脱敏诊断 `state_scope_conflict`。该校验只作用于已迁移并绑定的任务，不改变其他专家的常规状态读写。已按旧合同修复但尚无绑定的任务，由平台维护方凭修复回执和当前状态摘要使用 `bind_reconciled_state.py` 补登记。

预检返回来源及目标状态文件 SHA-256、来源字段 SHA-256 与版本列表。正式提交必须回传两份预检文件摘要；插件再次核对来源与目标，以工作状态的复制写入和比较后提交事务原子替换目标目录，来源保持不变。回执包含迁移 ID、两个 Release/installation ID、session ID、字段路径、迁移版本列表、来源摘要及目标提交前后摘要，不包含业务正文。回执持久化在插件工作状态目录的 `migrations/receipts/`；只有 `status=committed` 且回读目标版本数、内容哈希与既有引用通过业务校验，才可宣称恢复成功。合同 v1 不支持把来源数组与目标已有数组自动合并；此类情况必须先由开发方给出业务迁移方案，再扩展正式合同。

若目标安装尚未在该会话创建状态文件，维护方可显式指定 `--bootstrap-empty-target`。预检将目标摘要标为 `missing`，提交时从来源状态的容器结构派生空状态，仅替换 installation ID，并只填入本次指定的数组字段；不复制其他业务值。来源结构含无法安全清空的标量、目标目录已出现或预检摘要变化时拒绝。后续字段仍须分别预检和原子提交。维护方须先确认两个 Release 的业务状态结构兼容，不得通过此选项绕过业务兼容评估。

本标准 `2.24` 的正式开发与发布门禁如下。版本必须作为一个兼容组合核对，不能只满足其中一项：

| 项目 | 本标准要求 | 2026-10-26 正式环境核对 | 结论 |
|---|---|---|---|
| DClaw 核心 | 至少 `1.1.10` | 公网 `/api/version` 返回 `1.1.10`，运行镜像标记 Server 提交 `db08ac40` | 满足 |
| 支持插件 | 至少 `1.17.0` | 生产仍须读取健康接口核对 | 新增自助发布与隔离执行；旧插件能力继续可用 |
| Super Agent DevKit | `1.9.0`，且由目标实例认证下载 | 生产仍须读取元数据核对 | 同时识别旧包与自助公开包，提供 `publish` CLI 与关闭 Schema |
| Super Agent 开发包 | `1.10.0`，标准 `2.24`、DevKit `1.9.0` | 生产仍须认证下载核对 | 新开发和迁移默认使用自助公开包 |
| Windows 客户端 | 本地助手按需分发至少 `2.6.19` | 生产仍须核对 | 客户端不携带助手二进制，只提供稳定下载、校验、切换和启动器 |
| 通用 Runner | 普通链路至少 `1.0.0`；本地文件链路至少 `1.1.0`；公共 Component 链路至少 `1.2.0`；非入口 export 绑定至少 `1.3.0` | 随兼容客户端核对 | 声明 `component_exports` 的能力包必须使用实际携带 Runner `1.3.0` 的兼容客户端 |

正式公开入口：

| 功能 | 认证后的目标实例路径 |
|---|---|
| 插件健康与版本 | `GET /api/super-agent-support/health` |
| DevKit 元数据 | `GET /api/super-agent-support/developer-kit`，返回 `version`、`download_path` 和 `sha256` |
| DevKit ZIP | `GET /api/super-agent-support/developer-kit/v1.zip` |
| 开发包元数据 | `GET /api/super-agent-support/developer-pack` |
| 开发包稳定下载 | `GET /api/super-agent-support/developer-pack/download` |
| 开发者公钥登记 | `POST /api/user/super-expert-publishing/signers` |
| 开发者上传并公开 | `POST /api/user/super-expert-publishing/releases`，签名 ZIP 使用 multipart 字段 `file` |
| 开发者已发布专家 | `GET /api/user/super-expert-publishing/agents` |
| 本地执行 MCP | `/api/super-agent-support/mcp/`，Streamable HTTP |
| 客户端环境检测 | `GET /api/super-agent-support/environment-status` |
| 客户端配对 | `POST /api/super-agent-support/device-bootstrap` |
| 本地助手版本清单 | `GET /api/super-agent-support/local-helper/manifest?platform=windows-x64` |
| 本地助手下载 | `GET /api/super-agent-support/local-helper/download?platform=windows-x64` |
| 本地助手通道 | `/api/super-agent-support/devices/connect`，WebSocket 协议 `2` |
| 能力包注册 | `POST /api/super-agent-support/capability-packages/register` |
| 公共 Component 完整注册表 | `GET /api/super-agent-support/component-registry` |
| 公共 Component 制品直传 | `POST /api/super-agent-support/admin/component-artifacts/uploads`，然后 `POST /api/super-agent-support/admin/component-artifacts/uploads/{upload_id}/complete` |
| 公共 Component 签名注册 | `PUT /api/super-agent-support/admin/component-registry/{component_id}/variants/{platform}` |
| 凭证绑定 / 撤销 | `POST /api/super-agent-support/credentials` / `DELETE /api/super-agent-support/credentials/{credential_ref}` |
| Agent 出站凭证绑定 | `POST /api/super-agent-support/agent-outbound/credentials` |
| 业务身份公开验签键 | `GET /api/super-agent-support/business-identities/verification-keys` |
| 业务身份在线验证 | `POST /api/super-agent-support/business-identities/assertions/verify` |
| 业务身份管理 | `/api/super-agent-support/admin/business-identities/` 下的服务、授权、轮换、撤销和审计接口 |

上述接口属于认证后的目标 DClaw，不是匿名公共下载站。`401` 表示尚未携带有效身份，不能据此断言接口缺失；有效身份下 `404`、插件版本低于要求、返回的 DevKit 版本不匹配或 ZIP SHA-256 与元数据不一致，均表示当前目标环境未达到发布门禁。开发方只能继续源码和离线测试，状态标记为 `platform-tooling-missing`，不得使用平台仓库内源码副本、旧兼容构建器、历史签名包或其他环境下载的 DevKit 替代。

生产升级必须部署插件 `1.17.0`、Developer Pack `1.10.0`、DevKit `1.9.0` 和具备插件助手下载器的 Windows 客户端 `2.6.19`；使用本地执行的能力包须完成 Runner `1.3.0`、设备协议 `2` 和 `windows-x64` 平台报告的实际连接核对。助手版本更新只发布支持插件，不再要求发布 DClaw 客户端。manifest 中 `platform_contract_versions.local_execution="1"` 是平台合同主版本；本地执行合同修订版 `1.2`、Runner 设备协议 `2` 和公共 Component 描述符 `1` 是不同层级的版本，不得互相替代或写错字段。开发方必须使用自己的应用身份认证会话实际下载 Developer Pack 或 DevKit、核对服务端 SHA-256；自助公开包的公钥由开发者本人登记，私钥始终只保存在开发者设备上。服务器 root SSH 权限和镜像中存在文件都不能替代应用下载身份或发布证据。

生产安装必须把插件 `state_dir` 放在持久卷，并通过平台 Secret 配置稳定的 `master_key_base64`；容器可使用 `DCLAW_SUPER_AGENT_SUPPORT_MASTER_KEY_BASE64`，该值解码后至少 32 字节，不得写入仓库、镜像或 Agent 包。`trusted_package_signers` 是 `signer_id` 到原始 Ed25519 公钥 Base64 的映射；`trusted_component_signers` 是 `signer_id` 到 DER SubjectPublicKeyInfo 编码的 P-256 公钥 Base64 映射。未配置对应受信公钥时，插件仍可启动和提供环境状态，但对应的能力包或公共 Component 注册必须失败关闭。

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

### 13.1 统一建卡顺序

新建或更新的超级专家使用相同的两段式业务回复与建卡流程；业务内容仍由各专家自己的需求和状态机决定，卡片组件、字段与回执统一遵守插件实时合同：

1. 专家运行时用默认无工具模式调用 `agent.execute`，取得内部业务文本候选。此调用不设置 `response_format="json_object"`，不直接流式展示给客户，也不以候选正文证明卡片已创建。
2. 若已确认业务流程或状态机需要客户输入，运行时先调用 Host `interaction.capabilities.list/1` 取得本轮所需组件的实时详细 Schema，再以第一段文本、可信业务状态及该 Schema 为输入，第二次调用无工具的 `agent.execute` 生成卡片草案。第二次调用可以设置 `response_format="json_object"`；模型只建议组件类型和参数，不调用建卡工具，不增加、删除或改写第一段确定的业务问题和选项。无需客户输入的回合不创建卡片。
3. 运行时解析第二段候选，核对业务问题、字段顺序、必填关系、选项、状态、`task_key` 和 `interaction_revision`，并按实时组件 Schema 校验。校验失败时只针对第二段做有界重试；仍不合格则记录脱敏错误并失败关闭。需要卡片的回合禁止降级为仅输出文本问题。
4. 只有校验通过后，运行时才以稳定幂等键调用 Host `interaction.card.create/1`；插件再次执行权威 Schema、授权和作用域校验。运行时核对真实 `interaction_id`、`PENDING` 状态及 `interaction.card.receipt/1` 的 `created` 回执，再调用 `runtime.complete` 原子提交客户回复及卡片。任何内部候选、失败草案和未经确认的建卡结果都不得提前展示为已完成回复。

这两段模型调用分别处理业务回复和卡片表达；修改通用卡片表达规则时，只调整第二段的候选与校验模块，不改变第一段的业务目标、原始需求或既有状态机。`json_object` 只帮助第二段返回可解析对象，不能替代实时组件 Schema、业务不变量或 Host 最终校验。已签名旧专家的固定卡直建和模型工具建卡路径继续受原合同支持；各责任方在更新其发布包时迁入上述统一流程并验证旧任务续接，不由插件静默改写业务实现。

直接 Host 调用的关闭外层请求/响应 Schema 分别位于 DevKit `schemas/interaction-capabilities-list-v1/` 与 `schemas/interaction-card-create-v1/`，成功的 `single_select` 建卡请求、规范化结果和 `created` 回执位于 `examples/interaction-host-v1/single-select-success.json`。调用 `await host.call("interaction.capabilities.list/1", {"component_types": ["single_select"]})` 后，实时组件 Schema 在响应 `components[0].schema`；空数组或省略类型只返回精简索引，没有组件 Schema。开发方须先按详细目录的 Schema 校验 `request.card`，再按业务不变量校验候选。公共 Component Registry 是本地助手依赖目录，不是交互卡目录，不得替代此 Host 调用。

实时组件 Schema 是完整 JSON Schema，可能包含 `$defs`、`$ref`、`anyOf` 等关键词。运行时必须用支持该 Schema 草案的完整校验器验证 `request.card`，不得用手写关键词白名单或简化模拟 Schema 代替；否则即使平台给出的 `create_example` 合法，也可能在 Host 建卡前被专家自身拒绝。DevKit `fixtures/interaction-host-v1/single-select-live-catalog.json` 是当前 `single_select` 的完整脱敏目录快照，`validate_live_card.py` 提供 Draft 2020-12 验证示例。发布前应验证快照中的合法示例和反例，再用目标实例实时目录验证；静态快照不是目标实例的权威 Schema。若专家运行时使用第三方校验库，开发方负责将其适配版本作为专家依赖纳入签名包，不能假定 DevKit 开发环境或当前沙箱的偶然预装会永久存在。业务选项 ID、顺序、状态及可信回执仍须另行校验。此要求仅针对新建或更新专家，不改变已签名旧包和 Host 卡片合同。

所有新建及更新超级专家的交互卡实现必须以 DevKit `interaction_card_api_demo.py` 的同一 Host 边界为基线，适用于 `single_select`、`multi_select`、`question_form` 和 `file_selector`：按确定类型读取实时详细目录，验证平台 `create_example.card` 与本轮草案；由专家校验业务问题、选项或问题 ID 顺序及其他业务不变量；使用稳定 `task_key`、递增修订和幂等键调用 `interaction.card.create/1`；仅在真实 `PENDING` 卡片与 `interaction.card.receipt/1` 的 `created` 回执在 ID、作用域、版本和事件上匹配后，才提交客户回复。`file_selector` 仍须单独声明和授权 `interaction.file.select/1`。业务内容可不同，但不得跳过上述公共调用与失败关闭门禁。Skill 和各专家的发布前测试至少要覆盖合法实时示例、非法字段、业务不变量被改写、错误创建回执及同任务点击续接；模拟 Host 只能辅助测试，不能替代目标实例实时目录校验。现有签名专家不受静默改写，下一次更新时按本节迁入并复测。

直接建卡请求的 `idempotency_key` 与 `request` 同级；`request` 包含稳定 `task_key`、正整数 `interaction_revision`、类型、卡片对象及可选输入策略，默认 `card_only`。`card_only` 的待提交卡阻塞普通文本输入；`card_or_text`、`concurrent` 均保留文本输入，但文本本身不证明卡片已提交。Host 从可信执行上下文注入租户、installation 和任务身份，调用方不得传入这些作用域字段。相同作用域、问题、修订和载荷的重试沿用原幂等键；实质改动须递增修订并换键，已存在阻塞卡须显式提供其 `replaces_interaction_id`。首次成功时核对 `interaction.status=PENDING`、真实 `interaction_id`，以及 `receipt.contract=interaction.card.receipt/1`、`action=created`、`status=PENDING`；回执的交互 ID、可信作用域、`task_key`、修订、版本和 `event_id` 应与创建结果的 `create` 转换一致。后续 `session.context.interaction_receipts` 中的同一 `created` 回执以 `event_id` 和 `interaction_id` 关联。卡片已提交后重放原幂等请求可能返回当前非 `PENDING` 的卡片状态，但原 `created` 回执仍为 `PENDING`；不得把该重放当作新卡展示。

既有专家可能通过 `agent.execute(execution_mode="agent_loop")` 使用平台按授权动态注册的以下模型工具；它们属于兼容路径，不是新建或更新专家的默认建卡入口：

| 工具 | 用途 |
|---|---|
| `interaction_component_catalog(component_types=[])` | 读取实时组件目录；创建前必须按确定的组件类型再次读取详细 Schema |
| `interaction_card_create(...)` | 以稳定 `task_key`、正整数 `interaction_revision`、`component_type`、`card` 和输入策略创建卡片 |
| `interaction_card_status(interaction_id="")` | 查询指定卡片或当前活动阻塞卡 |
| `interaction_card_cancel(interaction_id, operation_key)` | 以稳定操作键取消仍为 `PENDING` 的卡片 |

请求采用实时目录返回的严格 Schema，未知字段必须拒绝。建卡成功须核对真实 `interaction.interaction_id`、`PENDING` 状态及 `interaction.card.receipt/1` 的 `created` 回执；工具参数、组件字段和枚举不得从平台源码或模型记忆中猜测。

插件 `1.18.19` 起，建卡工具和卡片提交接口返回同一关闭 Schema 的 `interaction.card.receipt/1`。回执绑定 `interaction_id`、installation、conversation、`task_key`、修订、版本、状态、转换事件和时间；提交回执另含规范化答案的 SHA-256，不包含答案正文。`session.context.interaction_receipts` 只读返回当前可信 installation 与任务最近更新的最多 20 张待提交或已提交卡片的回执。旧能力路径使用 `interaction_card_status` 读取实际卡片及答案，核对状态与版本后推进业务；客户端转交的 `user_input` 只作可读摘要，不构成点击或提交证明。回执和上下文数组 Schema 在 DevKit `schemas/interaction-card-receipt-v1/`，旧签名包继续按既有合同运行。

插件 `1.18.20` 起新增可选 `interaction.card.read/1` Host 调用。新专家在签名能力清单中显式声明并取得安装授权后，使用 `await host.call("interaction.card.read/1", {"interaction_id": interaction_id})` 读取本安装、本任务持久化卡片；Host 注入可信租户、安装与任务身份，不接受调用方传入这些作用域字段，也不要求 `idempotency_key`。结果为关闭 Schema 的 `found` 或 `not_found`：未找到与跨任务、跨安装均为同一个 `not_found`，不可探测其他专家的卡片。`found` 返回 `task_key`、`interaction_revision`、组件类型、当前状态和版本；仅 `SUBMITTED` 返回规范化答案与 `submission_receipt`，其余状态均返回 `null`。请求与响应 Schema 位于 DevKit `schemas/interaction-card-read-v1/`。旧签名包无需增加能力，原有 `interaction_card_status` 工具保持可用。

收到回执后，专家须以保存的 `interaction_id` 查询，逐项核对 `task_key`、`interaction_revision`、`status=SUBMITTED`、版本及提交回执的 `event_id`，再推进业务。`answer_sha256` 对 `answer` 的 JSON 对象按键排序、保留 Unicode、无多余空格编码为 UTF-8 后计算 SHA-256；与回执不一致时停止处理。已处理的 `event_id` 应持久记录在专家自己的任务状态中；重复读取或重复点击不得重复执行有副作用的业务步骤。未提交、已取消、已替换、已过期和旧的任务修订均不能被当作新答案。卡片答案是否满足业务要求仍由专家判断，平台不替专家解释业务字段。

交互接口按版本化合同演进。已发布的能力 ID、必填字段、含义、授权与隔离语义保持稳定；需要改变这些约束时新增合同版本并并行保留旧合同，不在原 `/1` 上静默改变。插件每次修改须按能力 ID 盘点现役专家的声明和调用路径，覆盖旧版回归；若确实需要专家适配，由各专家责任方在其版本中更新、密封和验证，平台不能仅发布插件后让已上线专家报错。新增可选能力不自动改写既有专家的签名清单或授权。

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

## 14. Agent 侧第三方 API 与凭证

### 14.1 调用合同

超级 Agent 对第三方 API 的每个动作必须定义：

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

- 长期凭证属于 Agent 侧，保存在 `dclaw.super-agent-support` 按用户、Agent 安装、凭证类型和 scope 隔离的加密凭证存储中；超级 Agent 只持有不透明 `credential_ref`。
- 仓库、manifest、密封包、提示词、测试夹具和日志中不得包含真实凭证。
- 客户账号登录状态若必须在本地浏览器中使用，应由本地能力包读取受控会话，不上传 Cookie。
- 客户可修复的凭证错误应显示“凭证无效、余额不足或授权过期”等可行动说明。
- 密钥轮换不得要求重新发布 Agent，除非权限范围发生变化。
- 凭证明文只能在 Agent 已授权的受控出站运输边界短暂存在；模型、Agent 工作区、本地助手、能力包、日志和 trace 都不得读取。

迁移包内已经包含凭证时，以下规则同时适用：

1. 用户把含凭证的源包作为迁移输入交给开发方，表示开发方可以在受控环境读取这些值，用于识别供应商、完成安全迁移和真实调用验证；开发方不得以“发布包不能含密钥”为由忽略或删除这些值。
2. 读取过程不得把值打印到聊天、终端回显、日志、报告或测试快照。盘点记录只写供应商、用途、所有者、权限范围、环境和迁移状态。
3. 开发方拥有并供当前 Agent 客户共用的第三方服务凭证，也必须迁移到该 Agent 的安装级加密凭证命名空间；超级 Agent 以不透明引用发起受控请求，不读取长期值。
4. 每位客户自己的 OAuth、Cookie 或账号凭证，迁移到 DClaw 已发布的客户凭证绑定能力或供应商官方授权流程，并按客户、安装和权限范围隔离。
5. 本地助手不得接收第三方长期凭证；只能使用 Agent 已获取的公开或限定资源、短时有效的预签名 URL 执行数据面上传或下载。
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

只有原业务本来就有独立业务服务时，该服务自身的长期 Token 才保存在它自己的 Secret 管理系统；这是保留源服务的例外，不得作为新 Agent 调用第三方 API 的默认架构。若 Agent 侧受控出站所需的 OAuth 刷新、凭证注入或撤销合同尚未由目标插件正式发布，生产构建必须失败关闭并提交通用能力申请，不能把 Token 写回密封包或传给本地助手。

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

管理员不能只配置一个 Secret 名称就视为该能力可用。生产密封前，目标实例必须已经公开安装级业务服务身份的能力 ID、请求/响应 Schema、绑定对象、scope、Token 注入或交换位置、过期/刷新/撤销语义、稳定错误码和最低插件版本；该能力必须出现在目标实例下载的能力目录中，并能进入 manifest 能力摘要和管理员授权预览。缺少其中任一项时，开发方不得自行命名能力 ID、猜测 Header 或直接注入 Secret。

静态服务 Bearer、客户端密钥或长期 Token 禁止进入 manifest、Agent 配置、提示词、卡片和本地任务输入。标准 `2.8` 已通过插件 `1.10.1` 和 DevKit `1.4.1` 正式发布 `business.service.installation-identity/1` 的完整调用与运输合同；满足第 25.2.1 节登记、授权和版本门禁的 Agent 可以声明并使用该能力。目标环境低于最低版本、缺少精确服务登记或安装/发布版授权时，生产密封与上传仍必须失败关闭；开发方不得以内嵌 Secret 绕过门禁。

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

本节中的“超级专家侧”以密封超级专家为业务决策和第三方调用主体；“本地执行侧”包括 `dclaw.super-agent-support` 公共 Component、插件配套 Runner 和运行在其中的 Agent 私有能力包。公共 Component 与 Runner 属于插件套件，Agent 私有能力包属于开发方，三者不得混为同一份代码。

总原则：超级专家决定做什么、为什么做、使用哪些业务来源、如何选择和评分素材、如何编辑、何时返工以及什么结果才算完成，并由 Agent 侧完成所有第三方业务 API 调用。本地执行侧只在客户电脑上对 Agent 已确定的素材、短时资源 URL 和加工计划完成高带宽、高算力或设备侧技术任务，并返回可验证的技术结果。能力包可以根据硬件选择线程数、编码器、缓存和技术重试参数，但不得选择业务供应商、改变业务目标、创建或轮询第三方业务任务、筛选业务素材或判断内容是否符合客户要求。

能力包可以理解自己签名声明的技术领域，例如媒体文件、时间轴、字幕、语音识别、编码参数和技术质量规则，也可以在该领域内生成确定性的执行子计划。它不得解释客户的开放式自然语言、选择供应商或素材来源、改变内容目标，或代替超级专家做最终业务验收。Runner 核心始终与业务无关，只负责安装、隔离、调度、状态、权限和资源控制。

以 FFmpeg、Whisper、Python Runtime、模型、字体和媒体资源为例，四层边界固定如下：

| 层 | 必须负责 | 不得负责 |
|---|---|---|
| 插件公共 Component | 维护可复用依赖的准确版本、分平台制品、来源、许可证、SBOM、HTTPS URL、大小、SHA-256、签名、二级公共依赖、缓存键与回滚版本 | 包含 Agent 业务规则、选择具体 Agent 的流程、进入 DClaw 核心或替 Agent 判断业务结果 |
| 插件配套 Runner | 统一安装协议、沙箱与进程隔离、受控 HTTPS 下载框架、验签、任务状态、缓存目录、原子切换、回滚和清理调度 | 自行决定公共 Component 版本、维护 Agent 专属下载域和私有资源清单、判断视频业务质量 |
| Agent 私有能力包 | 声明所需公共 Component 及注册版本，仅打包 Agent 专属代码、私有依赖和私有资源，执行已确定的结构化技术任务 | 重复打包公共 Component，理解客户开放式需求、选择业务素材或供应商、改变脚本和时间线、宣称业务完成 |
| 密封超级专家 | 决定是否需要这些技术能力、生成确定任务参数、选择业务来源与素材、制定脚本和编辑方案、根据技术结果判断接受或返工 | 下载或中转大文件、在 DClaw 服务端执行 FFmpeg/Whisper、把业务判断交给 Runner |

公共 Component 的版本、URL、允许域、摘要、签名、缓存键和回滚目标由插件注册表确定；Agent 私有资源由 Agent 能力包的签名材料确定。Runner 只执行对应签名合同，不把任何具体 Component 编译进 Runner 核心。

| 工作内容 | 超级专家侧职责 | 本地执行侧职责 |
|---|---|---|
| 理解客户需求 | 解析意图、维护业务上下文、确定缺失字段 | 不解释自然语言，不补业务字段 |
| 与客户交互 | 决定何时提问、问题内容、选项和后续动作 | 只报告需要人工操作的技术检查点 |
| 业务流程编排 | 决定步骤、顺序、分支、降级、终止和恢复策略 | 按一个已确定的任务合同执行，不自行改变流程 |
| 第三方服务 | 选择供应商和接口，使用 Agent 安装级加密凭证引用，执行请求、幂等、轮询、重试、限流、费用和结果解释 | 不持有长期 Token，不创建或轮询业务任务；只对 Agent 提供的公开或短时预签名 URL 执行大文件数据传输 |
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

### 15.3 十二个公共工具

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

V1 基础任务固定流程：

1. `local_environment_status`
2. `local_capabilities_list`
3. `local_runtime_prepare`
4. `local_task_start`
5. `local_task_status`
6. `local_task_continue`
7. `local_task_cancel`
8. `local_task_result`

前三步完成环境与能力准备；中间步骤管理任务；最后一步只在终态读取结果。精确请求和响应以 DevKit 内 `schemas/local-execution-v1/tool-call.schema.json` 和 `schemas/local-execution-v1/tool-response.schema.json` 为准。

V1.1 另增加四个按需工具：`local_file_select`、`local_file_upload`、`managed_artifacts_list` 和 `managed_artifact_action`。不使用本地文件的旧 Agent 不需要声明或调用这些工具，原八工具链路继续兼容。

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
  "standard": {"id": "dclaw.local-execution", "version": "1.1"},
  "ok": true,
  "trace_id": "trace_01J...",
  "data": {"task_id": "task_01J...", "status": "queued"}
}
```

顶层 `ok=true` 只表示工具调用成功。若 `data.status=failed`，本地任务仍然失败，超级专家必须读取 `data.error`，禁止对客户宣称已完成。

### 15.5 V1.1 环境与准备合同

DClaw 客户端负责按需下载、校验、启动、绑定、重连和原子升级通用本地助手；助手二进制及版本清单由 `dclaw.super-agent-support` 插件发布，不随 DClaw 客户端安装包分发。超级专家不得下载安装器、展示绑定码、拼接 Runner 连接地址或建立第二套安装流程。`local_environment_status` 只返回状态和客户下一步动作：

| `state` | `reason` | `user_action` | 含义 |
|---|---|---|---|
| `ready` | `none` | `none` | 至少一个已登录客户的兼容 Runner 在线 |
| `device_not_ready` | `no_paired_device` | `open_dclaw` | 客户端尚未完成自动设备配对 |
| `device_not_ready` | `device_offline` | `open_dclaw` | 已有设备记录但当前没有在线连接 |
| `runner_update_required` | `runner_version_too_old` | `update_local_helper` | 在线 Runner 低于平台最低版本；客户端从当前支持插件重新下载并原子切换助手 |
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
| `runner_update_required` | `update_local_helper` | Runner 低于能力包声明的 `min_runner_version` |

准备响应固定包含 `state`、`capability_id`、`package_id`、`package_version`、`min_runner_version`、`device_id`、`runner_version` 和 `user_action`。平台不使用旧 Relay 的 `runtime_update_required`：能力包准备无需客户另行确认，版本不一致时返回 `preparing` 并由 Runner 自动更新。

### 15.6 V1.1 任务状态

本地任务公开状态只允许：

```text
queued | running | awaiting_input | cancelling | succeeded | failed | cancelled
```

检查点事件必须把任务置为 `awaiting_input`。`local_task_continue` 只接受该状态且 `checkpoint_id` 与最新检查点一致的任务，受理后恢复为 `running`。历史内部值 `waiting_for_input` 在插件状态库初始化时迁移为 `awaiting_input`；标准正文旧称 `waiting_user` 只描述产品状态机，不得作为工具响应值。

### 15.7 V1.1 本地文件与持久产物

需要客户选择本地文件时，超级专家必须同时声明 `interaction.file.select/1`、`interaction.card.create/1` 和 `local.execution.session/1`，创建 `file_selector` 交互卡，并把卡片的类型、数量、单文件大小和总大小限制原样交给 `local_file_select`。取消系统文件对话框只返回 `cancelled`，不得提交或关闭仍为 `PENDING` 的交互卡。

平台、Agent 和能力包只能看到 `local_file_ref`、显示名称、MIME、大小、设备 ID 和修改时间；本机绝对路径只保存在 Runner 的本地引用注册表。引用绑定租户、用户、会话、Agent、安装、发布、调用和设备，默认一小时过期；过期、撤销、跨范围、跨设备、文件缺失或内容变化必须以稳定 `LOCAL_FILE_REF.*` 错误失败关闭。

`local_task_start.local_file_bindings` 与 `local_task_continue.local_file_bindings` 只接受命名绑定和 `access="read"`。前者用于任务启动前已有的本地文件，后者用于任务在 `awaiting_input` 检查点中途补充的本地文件；继续调用必须使用原 `task_id` 和最新 `checkpoint_id`，绑定引用必须属于原任务设备。Runner 在启动或继续能力包前重新校验范围、有效期、大小、修改时间和 SHA-256，把文件复制到任务目录 `res/bindings/<binding>/<display-name>`，设为只读，并只把相对任务根路径分别写入 `input.json` 或 `continuation.json`。服务端消息、任务记录和公开错误不得出现本机绝对路径或文件字节。旧 Agent 不传该可选字段时继续按原合同运行。

需要上传时，超级 Agent 先通过 Agent 侧第三方调用取得短时 HTTPS 预签名 URL、允许域、方法、允许请求头和最大大小；`local_file_upload` 只把该上传指令送到原设备，由 Runner 直接读取文件并上传。DClaw 服务端不得接收、缓存或中转文件字节；Runner 禁止重定向、非 HTTPS、带用户信息 URL、域名越界、未允许请求头和超限文件。

成功任务的客户成品由 Runner 复制到持久托管产物目录。`managed_artifacts_list` 只返回安全元数据；`managed_artifact_action` 只允许预览、在资源管理器中定位、重新选择为新的不透明引用或删除该托管产物。删除必须限制在 Runner 管理根目录，禁止接受任意路径。上述文件能力要求设备协议 `2`、Runner `1.1.0` 和 Windows 客户端 `2.6.13`；协议 `1` / Runner `1.0.0` 继续支持不含文件绑定的历史任务。

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

FFmpeg、FFprobe、Python Runtime、Node.js、Whisper 引擎、模型和其他可被多个 Super Agent 复用的本地重任务依赖，统一作为 `dclaw.super-agent-support` 插件管理的公共 Component。它们不进入超级专家密封包、Agent 私有本地能力包或 DClaw 核心镜像。Agent 开发会话只负责发现依赖、判断公共或私有并提交补充申请；插件负责公共性评审、准确版本、分平台制品、许可证、SBOM、摘要、签名、HTTPS 制品上传、注册表、兼容和回滚。插件配套本地助手负责按需下载、验签、缓存、原子安装和版本切换。

Agent 私有 component 和只服务该 Agent 的依赖仍随 Agent 能力包交付。私有 component 依赖已注册公共 Component 时，私有包只保留自身代码与资源，按注册版本进行适配，不重复打包公共运行环境。

迁移已有 Agent 时，发现旧 Agent 专属运行库不得直接删除。先逐项与完整公共 Component 注册表对照：已有同类公共 Component 时，把旧运行库映射到注册版本并由 Agent 完成版本适配，不重复注册旧版本；缺少的可复用运行库按公共 Component 合同补齐制品、许可证、SBOM、签名、HTTPS 上传和注册。旧运行库制品在公共注册和 Agent 适配完成前保留为迁移输入；是否删除旧副本属于后续独立操作，必须另行确认。Agent 私有能力包继续作为私有交付物，不得因合并公共运行库而误并入公共注册表。

公共 Component 使用 DevKit 的 `schemas/super-agent-support-v1/public-component-descriptor.schema.json`。每个平台变体必须固定 `component_id`、`platform`、准确版本、状态、直接公共依赖、正式 HTTPS artifact、压缩和解压大小、SHA-256、导出程序、PATH/环境路径、SBOM、许可证、缓存键和回滚版本。`available` 变体不得缺少 artifact、SBOM 或许可证；`reserved` 与 `disabled` 变体不得伪造可下载 artifact。

公共 Component 描述符使用 ECDSA P-256 + SHA-256 签名，签名输入为键排序、无额外空白的 UTF-8 规范 JSON。插件使用 `trusted_component_signers` 独立信任库验签；公共 Component signer 不等于超级专家 signer 或 Agent 私有能力包 signer。GET 必须返回完整注册表，PUT 必须验证路径中的 Component/平台与签名描述符一致、递增 `registry_version` 并返回更新后的完整注册表。

Agent 私有能力描述符通过可选 `public_components` 数组声明精确 `component_id + version`，不得使用版本范围或运行时自行选择版本。入口需要公共运行时时，可以用 `entrypoint.component_id + entrypoint.export` 引用已签名 Component 的导出程序，参数中的 `{package_root}` 与 `{task_root}` 分别指向 Agent 私有能力包根目录和当前任务目录。需要取得非入口 Component 的模型、字典或工具目录时，使用 `component_exports` 显式声明 `environment_variable + component_id + export`；环境变量必须位于 `DCLAW_COMPONENT_*` 命名空间，Component 必须同时出现在 `public_components` 中，且能力包必须声明 Runner `1.3.0` 或更高版本。Runner 只把签名 Component 描述符中该 export 的安全相对路径解析为环境变量，缺失、重复、未声明、越界或预先占用时失败关闭。禁止读取 Runner 私有安装目录、猜测绝对路径或使用未公开环境变量。插件在 `local_runtime_prepare` 时按设备平台解析完整依赖闭包，并把每个 Component 的描述符、签名、签名公钥和规范载荷送给 Runner；Runner 必须重新核对描述符与规范载荷、验签、校验 HTTPS/大小/SHA-256、安全解压并原子安装后，才安装和报告 Agent 私有能力包。旧能力描述符不含 `public_components` 或 `component_exports` 时继续按原合同处理，无需重建。

迁移 Skill 和平台维护自动化使用以下无界面命令，不要求进入 DClaw 页面：

```bash
python dclaw_agent_devkit.py component-registry \
  --base-url https://<dclaw-host> \
  --access-token "$DCLAW_ACCESS_TOKEN" get

python dclaw_agent_devkit.py component-registry \
  --base-url https://<dclaw-host> \
  --access-token "$DCLAW_ACCESS_TOKEN" upload \
  --file /secure/component.zip \
  --component-id <component-id> --platform windows-x64 \
  --component-version <registered-version>

python dclaw_agent_devkit.py component-registry \
  --base-url https://<dclaw-host> \
  --access-token "$DCLAW_ACCESS_TOKEN" register \
  --descriptor /secure/component-descriptor.json \
  --signer-id <component-signer-id> \
  --private-key /secure/component-p256-private.pem
```

查询需要已认证 DClaw 身份，注册还需要管理员权限。平台 Component 私钥只保存在平台受控发布环境，不交给 Agent 开发方；Skill 发现缺失公共依赖时提交补充申请并等待平台返回新完整注册表，不得自行签发公共 Component。

公共制品由插件管理员先调用 `POST /api/super-agent-support/admin/component-artifacts/uploads` 创建短期上传会话，按返回的 HTTPS 预签名 URL 直接 PUT 到插件对象存储命名空间，再调用 `POST /api/super-agent-support/admin/component-artifacts/uploads/{upload_id}/complete`。初始化请求提交 Component 身份、平台、版本、大小、本地 SHA-256 和 MD5；PUT 必须携带返回的 `Content-Type`、`Content-MD5` 和文件长度。完成接口分别对存储原址和公开制品 URL 发起单字节 Range GET，核对长度与 ETag/MD5，并确认 Runner 可无认证读取公开 URL；大文件不经过 DClaw Server。私有桶应在插件配置 `public_component_artifact_base_url`（或环境变量 `DCLAW_PUBLIC_COMPONENT_ARTIFACT_BASE_URL`）指定同一对象命名空间的公开 HTTPS CDN 根地址；上传端计算的 SHA-256 写入签名描述符，Runner 安装时独立核对实际文件 SHA-256。注册插件托管 URL 时，描述符的身份、版本、大小和 SHA-256 必须匹配已完成的上传回执。SBOM、许可证证据、平台 P-256 签名和注册表审核仍按本节既有要求执行。现有外部 HTTPS 制品注册合同保持兼容；Agent 私有能力包继续使用开发方 HTTPS 存储和已有注册入口。

### 16.1 大型依赖与按需安装

本节以下规则适用于 Agent 私有能力包和私有大型资源。公共 Component 使用 `dclaw.super-agent-support` 的公共 Component 发布合同、插件管理的 HTTPS 制品命名空间和插件配套本地助手安装协议。

当前 V1 私有能力描述符的单个 `artifact.size_bytes` 上限是 `536870912` 字节。源包超过该上限时，开发方不得原样注册，也不得默认要求 DClaw 核心服务扩大限制或承担大文件托管。按以下顺序处理：

1. 删除重复运行时、开发工具、缓存、测试成品和未使用模型，生成最小可执行能力包。
2. 能独立版本化的功能拆成多个签名能力包，只准备当前任务真正需要的最小集合。
3. 大模型或第三方运行资源从开发方控制的 HTTPS 地址按需下载到客户电脑；下载域名必须同时出现在能力描述符允许域和签名资源清单中。
4. 资源清单固定为 `capability-pack/<platform>/resources.lock.json`，`schema_version=1`、`status=release-ready`、`release_ready=true`，并声明非空 `allowed_domains`。每项必须固定 `resource_id`、版本、正式 HTTPS URL、压缩大小、SHA-256、SBOM URL 与摘要、许可证 SPDX 标识及证据 URL/摘要、缓存键和回滚版本；需要解压时还应固定解压大小与目标相对目录。该状态表示清单内所有正式 URL 和摘要均已冻结，不是 V1 capability descriptor 的新增字段。清单放入能力 artifact，由签名描述符中的 `artifact.sha256` 传递保护，不得宣称资源 ZIP 本身具有独立平台签名。
5. Developer Pack 必须在生成任何 capability artifact 或超级专家 ZIP 前读取并验证该资源清单。`release-blocked`、`release_ready=false`、空 URL、`.test`、localhost、临时路径、未进入允许域的主机、非正数大小、无效 SHA-256、缺失 SBOM、许可证为 pending、缺失缓存键或回滚版本时必须失败关闭；旧已签名包运行不受该构建门禁影响。
6. 下载后先校验大小与 SHA-256，再安全解压到临时目录；许可证或 SBOM 缺失、路径逃逸、摘要不符、磁盘不足时失败关闭。校验通过后原子切换当前版本，旧版本至少保留到新版本完成一次成功任务。
7. 已校验且版本、摘要相同的本地资源允许复用；升级失败自动继续使用上一兼容版本，清理不得影响其他 Agent 或正在执行的任务。
8. 只有上述方式无法满足多个无关 Agent 的共同需求时，才按第 25 节申请平台通用资源合同或调整上限。

`dclaw.super-agent-support` 只保存公共 Component 和私有能力包的描述符、签名、状态与小型元数据。公共 Component 二进制和大型资源由插件管理的 HTTPS 对象存储或 CDN 命名空间提供；Agent 私有能力包和私有资源由开发方 HTTPS 存储提供。插件配套本地助手直接下载，DClaw 核心不上传、转发或缓存这些二进制。任何尚未进入已签名描述符或其 artifact 内签名资源清单的 ZIP 只能称为“未签名资源构建输入”，不得称为正式能力包、资源包或已发布依赖。

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
- 能力包可以在 `res` 下保留原有业务目录含义，例如迁移旧 `制作文件` 目录时使用 `res/制作文件/...`；不得把过程资源继续放在任务根目录。
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

Agent 私有外部按需资源 ZIP 不是平台可注册的独立能力包。它必须由 Agent 私有能力 artifact 内受保护的资源清单绑定，能力包在本地逐项执行 HTTPS、允许域、大小、SHA-256、SBOM 和许可证校验。只有经公共性评审且按上述公共 Component 合同由插件平台方构建、签名和注册的复用依赖，才由插件和 Runner 直接管理；开发方不得把 Agent 私有资源伪装成公共 Component 或自行发明另一种 `resource package` 注册格式。

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

以下前置关系必须全部同时成立，不能用后一步结果替代前一步证据：

1. 所有 artifact 和外部资源已有可从客户网络访问的正式 HTTPS URL，URL 不为空、不使用 `.invalid`、localhost、临时文件地址或开发机路径。
2. 描述符 `permissions.network_domains` 覆盖 artifact 和资源清单中的每个下载主机，资源清单 `release_ready=true`，大小与 SHA-256 来自正式托管对象。
3. 能力描述符使用获 capability-package 信任域授权的 signer 完成签名，目标实例插件已配置对应公钥并通过注册验证。
4. Developer Pack、DevKit、支持插件、客户端和 Runner 版本满足目标实例公布的兼容矩阵；本地源码版本或其他实例版本不能替代目标实例部署版本。
5. 前四项通过后才能注册描述符；注册成功后才能调用 `local_runtime_prepare`；准确版本准备成功后才能把超级专家发布状态推进到真实验收。

任一 URL 为空、允许域不完整、`release_ready` 未通过、摘要仍是占位值、签名缺失、capability 信任域未授权、目标实例工具链版本不匹配或平台尚未部署所需版本时，构建或发布必须失败关闭。此时只能保留未签名资源构建输入，不能把 descriptor、capability package 或 Agent 标记为已发布。

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
  "standard_version": "1.1",
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

服务器 SSH 登录私钥与 DClaw 发布 signer 私钥是两套完全不同的身份。RSA、Ed25519 或其他格式的 SSH key 只证明操作者可以登录服务器，不能用于超级专家 ZIP、capability descriptor 或 capability artifact 签名，也不能证明对应公钥已进入任何 DClaw 信任域。即使 SSH key 恰好也是 Ed25519，其文件格式、用途、登记记录和信任边界仍不满足发布 signer 合同，禁止转换或复用。

同一发布公钥计划跨域复用时，平台也必须分别留下 `super_expert` 与 `capability-package` 两条用途授权及审计证据。历史 Agent 的 signer、公钥登记或已签名 ZIP 只对其真实登记用途和发布证据有效，不能自动给新 Agent、另一个开发方或新的 capability package 继承信任。

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

只有 root SSH 权限、但没有目标 DClaw 的应用身份认证、Developer Pack/DevKit 认证下载权限或受控发布 signer 时，开发方只能交付源码、测试证据和未签名构建输入。此时六态必须记录为 `source-complete=true`（仅在源码与测试确实完成时）、`sealed=false`、`uploaded=false`、`granted=false`、`active=false`、`e2e-verified=false`；不得调用服务器内部构建器、借用历史 signer 或把 SSH 私钥当作发布凭证。

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

### 20.2 项目方真实用户验收

本节在 Node 8 完成后由项目方自行执行，不属于开发、移植与优化 Skill 的节点。项目方验收涉及客户流程时应从 DClaw 客户端测试：

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

迁移项目默认把源包已有自动测试、示例和三个真实案例全部作为开发基线，不再询问是否使用。项目方可以在正式验收时使用三个从 DClaw 客户端开始的代表性用户链路，验证卡片、第三方服务、本地助手、产物和错误定位。开发会话不得代替项目方执行正式验收；只有基线暴露出未覆盖的业务行为时，才集中请求额外案例。

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

### 21.1 获取官方开发包与 DevKit

开发方优先从目标 DClaw 实例取得与平台合同匹配的完整开发包，不得从服务器仓库复制脚本：

```text
GET <DCLAW_BASE_URL>/api/super-agent-support/developer-pack
GET <DCLAW_BASE_URL>/api/super-agent-support/developer-pack/download
```

开发包元数据必须返回准确的开发包版本、标准标识与版本、DevKit 版本、ZIP SHA-256、文件数、支持平台和稳定下载路径。下载后的顶层目录名带开发包版本，包内 `PACKAGE-MANIFEST.json` 和 `SHA256SUMS` 列出公开资产及摘要；开发者根据元数据判断版本，不得根据稳定下载路径、标准文件名或 ZIP 文件名猜测版本。

开发包 `1.8.0` 包含标准 `2.19`、DevKit `1.7.0`、`agent.outbound/1` 机器合同、公共 Component 无界面 CLI、`component_exports` Schema 与夹具、公开 SDK、完整项目模板、业务服务模板、本地能力模板、测试夹具、最小离线示例、SBOM、第三方许可证、兼容矩阵、升级和回滚说明。统一命令如下：

```text
python dclaw_developer.py doctor
python dclaw_developer.py init --target <project> --agent-id <id> --name <name> --local-helper <none|optional|required>
python dclaw_developer.py validate --project <project>
python dclaw_developer.py test --project <project>
python dclaw_developer.py build --project <project> --private-key <private.b64> --public-key <public.b64> --output <release.zip>
```

声明本地助手的 Agent 在 `build` 时还必须传入 `--capability-artifact-url <https-url>`；同一命令确定性生成本地能力 artifact、绑定大小与 SHA-256、签名能力描述符并验签，然后构建超级专家包。需要提前托管 artifact 时可单独运行 `capability-build`。

本地能力 artifact 的构建由 `capability-pack/<platform>/capability-build.json` 声明，当前 `schema_version=1`。`artifact.source=members` 时，`members` 可以列出任意安全相对文件或目录，并可为单文件声明目标路径与预期 SHA-256；构建器必须递归展开目录、拒绝绝对路径、路径穿越、符号链接和大小写冲突，并在 ZIP 内生成每个文件的大小与 SHA-256 清单。Agent 专属代码、私有锁定依赖、私有资源清单和多个业务模块通过该成员清单进入 Agent 自有能力包；Python Runtime、Node.js、FFmpeg/FFprobe、Whisper 等已注册公共 Component 不得重复进入该成员清单。

已有确定性构建器的项目可以把 `artifact.source` 设为 `prebuilt` 并声明项目内 ZIP，或向 `capability-build`/`build` 传入 `--artifact-file`。官方 CLI 必须先校验 ZIP 完整性、相对路径、重复项、加密项和符号链接，再把原始 ZIP 的大小与 SHA-256 写入签名描述符；不得重新解释或遗漏其成员。未声明构建清单的旧项目继续使用 `runner.py` 和三个 Schema 的历史四文件默认值。

自动测试由 `project.json.tests` 声明受控适配器，当前至少支持 `unittest` 与 `pytest`，并允许安全相对测试路径、参数及项目内 Python 虚拟环境解释器。CLI 必须直接调用所选 Python 模块而不经过 shell，通过 unittest 汇总或 pytest JUnit 结果取得真实执行数量，并把适配器、规范化命令、数量和结果写入发布证据；禁止用新增的一项 unittest 代替项目已存在的完整 pytest 套件。未声明 `tests` 的旧项目继续使用 `python -m unittest discover -s tests -v`。

`build` 必须先执行行为基线、差异批准、Schema、能力最小集合、依赖锁、Secret 扫描、完整自动测试和全部签名验证门禁；任一项失败时不得产生可宣称正式的发布包。最小示例使用 `demo` 命令在无平台源码、无网络、无生产凭证的目录运行本地能力、生成测试签名包并独立验签。

为兼容已建立的自动化，独立 DevKit 入口继续保留：

```text
GET <DCLAW_BASE_URL>/api/super-agent-support/developer-kit
GET <DCLAW_BASE_URL>/api/super-agent-support/developer-kit/v1.zip
```

开发包和独立 DevKit 请求都必须携带目标 DClaw 接受的已认证开发者或管理员会话。先读取插件健康和元数据，核对插件、开发包、标准和 DevKit 版本；再使用元数据返回的 `download_path` 下载 ZIP。下载后必须以流式 SHA-256 与元数据中的值逐字比较，匹配后才能解压到 Agent 项目之外的工具目录。不得只根据文件名、HTTP 200 或本地已有 ZIP 推断工具有效。

认证和失败语义：

- `401`：当前请求没有有效身份，先修复认证；不能改用匿名镜像。
- `403`：身份没有开发工具权限，由管理员调整已有权限；不能把平台源码发给开发方。
- `404`：目标环境未安装/启用正确插件或路由尚未部署，记录为平台版本/部署缺口。
- 元数据版本不匹配、ZIP 摘要不匹配或 `contracts` 输出不完整：立即删除本次下载并失败关闭。

#### 21.1.1 平台统一工具链发布闭环

平台每次更新标准、支持插件、Developer Pack 或 DevKit 后，必须由平台统筹会话执行一次统一工具链同步，禁止让每个 Agent 责任会话分别下载、分别猜测版本或复制 `dclaw-server` 源码。官方实现位于 `dclaw.super-agent-support` 插件的 `tools/sync_authenticated_toolchain.py`，只供平台发布运维使用；第三方开发者仍只接收认证后的正式开发包。

同步输入必须显式固定目标 DClaw HTTPS 地址、服务端完整提交、客户端完整提交、镜像 ID，以及预期插件、标准、Developer Pack 和 DevKit 版本。认证 Token 只能从权限受限文件或进程环境读取，不得出现在命令行参数、日志、回执、共享目录或 Agent 项目中。工具必须完成以下门禁后才能原子发布共享目录：

1. 未认证私有健康接口返回 `401`，已认证健康接口返回 `200`；匿名 JWK 返回 `200`、带 ETag 的条件请求返回 `304`。
2. 元数据必须按公开结构读取 `standard.version` 等真实字段，禁止自行发明扁平字段或从文件名推断版本。
3. 插件、标准、Developer Pack、内嵌 DevKit 和独立 DevKit 必须与预期版本组合逐项相等。
4. 下载地址必须保持目标实例同源并位于 `/api/super-agent-support/`；跨域重定向失败关闭。
5. ZIP 的实际 SHA-256 必须等于元数据；开发包内 `PACKAGE-MANIFEST.json`、标准版本、内嵌 DevKit 版本和逐文件摘要必须一致。
6. 两个 ZIP 都必须拒绝绝对路径、路径穿越、大小写重复、符号链接、加密项、`._*`、`.DS_Store`、`__MACOSX`、`__pycache__` 和 `.pyc`。
7. 下载先进入同文件系统临时目录；全部验证成功后一次性重命名为 `standard-<standard>-pack-<pack>-devkit-<devkit>`，失败时删除临时目录，不得留下可被误用的半成品。
8. 最终目录必须位于所有 Agent 项目和 DClaw 服务端源码之外，文件只读、目录不可写；旧版本目录保留且不可原地覆盖。
9. 目录只包含 ZIP、公开元数据、公开 JWK、`SHA256SUMS` 和 `production-receipt.json`。回执必须记录版本组合、服务端/客户端提交、镜像 ID、路由状态、文件摘要、成员数和归档清洁结果，并明确 `contains_credentials=false`。

同一开发机器上的所有 Agent 责任会话只引用这一个只读目录。平台统筹会话维护责任映射；各责任会话在每次新建、继续或恢复工作时自行重新读取唯一标准、核对是否受影响、使用当前目录重跑相应门禁并分别报告六态。标准或工具链更新后，平台统筹会话不逐个动态通知；只有变更会阻断正在进行的发布，或用户明确要求通知时，才主动联系受影响责任会话。部署会话只负责镜像和生产验证，不代替责任会话修改 Agent 业务实现；非开发会话不列入通知对象。

`upgrade --project` 必须原子更新 `project.json` 中的 `developer_pack_version`、`standard.version` 和 `devkit_version`，同时在 `.dclaw/developer-pack.json` 记录旧值、新值和回滚方式。升级命令成功后必须立即使用同一新 Pack 执行 `validate`；回执与项目元数据任一不一致即为 Pack Bug，不得由每个 Agent 长期手工修补。

#### 21.1.2 Super Expert signer 预登记

每个 Agent 的正式 signer 必须在最终构建前由平台统筹会话完成预登记，不能等上传时才发现缺失。平台只接收独立公钥文件、`signer_id` 和开发方另行记录的原始 Ed25519 公钥 SHA-256，不接收私钥。官方平台工具位于插件 `tools/register_super_expert_signer.py`，必须在同一文件锁内完成：

1. Base64 严格解码为恰好 32 字节的 Ed25519 公钥，并与预期 SHA-256 指纹逐字匹配。
2. 检查 `signer_id` 在基础验签信任表和 `super_expert` 官方信任表中不存在异键冲突。
3. 以原子替换分别写入两个信任域；重复执行相同登记返回 `already-registered`，不同公钥复用同一 ID 必须失败关闭。
4. 回执只包含 signer ID、公钥指纹、两个用途状态和变更的信任表，不包含私钥、Token 或其他 signer 的公钥。
5. 登记后必须通过受控插件重载或已批准的服务发布使内存信任状态生效，再用只读状态或真实上传验签确认；只修改磁盘文件不能宣称已生效。

不同 Agent 的 signer、私钥、公钥、指纹、信任状态和发布证据必须独立。历史发布使用的 signer 不撤销、不替换；新 signer 的登记不要求旧 Agent 重新签名。

#### 21.1.3 统一发布执行会话

同一项目可以设置一个统一发布执行会话，集中执行 signer 登记与信任核对、目标实例认证工具链同步、密封构建、独立验签、摘要归档，以及在用户已对该次具体发布明确授权时执行上传、整体授权、激活与回滚。统一发布执行会话属于开发方发布流程中的受控执行角色，不改变本文的两方组织责任模型，也不得成为新的业务实现所有者。

强制交接链路如下：

1. 每个 Agent 的责任会话独立完成并冻结自己的源码、manifest、能力清单、版本、自动测试、发布输入摘要和已知限制。
2. 责任会话把只属于该 Agent 的冻结发布输入和预期 signer 身份移交统一发布执行会话；未冻结或门禁失败的输入不得进入密封。
3. 统一发布执行会话使用目标实例认证工具链完成该 Agent 的密封、独立验签和摘要归档；只有用户已对该次具体发布明确授权时才继续上传、授权和激活。
4. 统一发布执行会话把 release、installation、激活、回滚和摘要回执逐 Agent 返回对应责任会话；责任会话更新自己的六态和发布记录。
5. 项目方自行执行真实客户验收；责任会话和统一发布执行会话都保持 `e2e-verified=false / 待客户验收`，除非项目方提供明确验收确认与证据。

统一发布执行会话禁止修改 Agent 专属业务源码、提示词、字段、状态机、第三方连接器或完成判据；发现发布输入问题时必须退回对应责任会话修复并重新冻结。不同 Agent 的 signer、私钥、公钥、摘要、密封包、release ID、installation ID、授权记录、回滚包和发布证据必须物理或逻辑隔离，禁止跨 Agent 复用、覆盖、推断或合并。共享目标实例、工具链目录或执行会话不构成跨 Agent 复用发布身份和证据的许可。

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

`verify` 必须使用已登记 signer 对应的公钥，在不含 Agent 源目录和 DClaw 服务端源码的干净目录执行。成功证据至少包含 DevKit 版本、ZIP SHA-256、验出的 `agent_id`、版本、实际 `package_type`、`signer_id`、`content_digest`、`capability_digest` 和零错误结果。四步回执必须形成同一条 `digest → validate → build → verify` 证据链；任何一步使用不同 DevKit、不同输入或不同摘要都不能合并为正式证据。

### 21.6 历史 canonical 链路与独立 DevKit 证据

DClaw 历史正式发布曾由 Agent 项目的 `build_release.py` 调用 DClaw 服务端 canonical 密封实现生成 Ed25519 签名 ZIP，再由 canonical validator 验证，并通过 `/api/admin/sealed-agents/releases`、grant-preview、grant 和 activate 完成正式上传、授权与激活。这类发布是真实的签名和上线证据，不得描述为“从未签名”或“从未发布”。

具体历史 Agent 的版本、ZIP SHA-256、signer、release ID 和运行时验证结果属于平台发布记录，不写入本通用开发标准。需要判定某个历史版本时，必须读取该版本的真实发布证据。

历史 canonical 证据只证明对应历史包经过当时的服务端内部链路并成功发布。它依赖平台源码和内部验证器，不能证明后来发布的独立官方 DevKit 已从目标实例认证下载，也不能替代本标准要求的独立 `digest → validate → build → verify` 回执。新开发方交付必须走独立 DevKit；历史包继续按第 24 节兼容运行，无需仅为改变证据来源而重新发布。

## 22. 自助上传、授权与激活

### 22.1 普通开发者自助公开发布

从本标准 `2.24` 起，新开发者默认使用 `package_type=super_expert_public`。开发者只需要普通 DClaw 登录身份和目标实例认证下载的 Developer Pack `1.10.0` / DevKit `1.9.0`，不需要管理员账号、预先人工登记 signer、服务器源码或 SSH。DevKit `keygen` 在开发者设备生成 Ed25519 密钥，私钥不能上传；使用 `publish register-signer` 只提交公钥，插件返回只属于该登录账号的 `signer_id`，然后写入 manifest 并完成 `digest → validate → build → verify`。

```text
python dclaw_agent_devkit.py keygen --private-key <本机私钥路径> --public-key <本机公钥路径>
python dclaw_agent_devkit.py publish --base-url <目标DClaw HTTPS地址> register-signer --public-key <本机公钥路径>
# 将返回的 signer_id 写入 manifest，完成 digest、validate、build、verify
python dclaw_agent_devkit.py publish --base-url <目标DClaw HTTPS地址> upload --package <已验签ZIP路径>
```

上述 `publish` 命令从开发者本机环境变量 `DCLAW_ACCESS_TOKEN` 读取当前登录用户的短时访问令牌；不得把令牌、私钥或 Secret 发到聊天、写入包或提交到仓库。Skill 应通过用户已有的 DClaw 登录会话取得授权；没有有效用户身份时只做离线开发，接口返回 `401` 后提示重新登录，不能要求管理员令牌。插件通过 `POST /api/user/super-expert-publishing/signers` 登记公钥，通过 `POST /api/user/super-expert-publishing/releases` 接收签名 ZIP；这两个接口均仅对已登录用户开放。

上传接口必须验签、校验完整性和能力清单、核对 signer 与 `agent_id` 都归当前账号、校验运行工作区、对准确发布版整体授权并原子激活。成功回执包含 `agent_id`、`release_id`、版本、两个摘要、signer、`state=active` 和 `visibility=public`。激活成功后专家立即向所有客户开放，没有私有测试阶段。开发者可以从正式客户端测试并按新的语义版本继续更新自己名下的专家；不能覆盖其他开发者或管理员发布的同名专家。管理员继续拥有停用和删除不合格专家的权力。

如果 ZIP 已被接受但运行服务暂时无法激活，开发者可通过 `publish retry-activation --agent-id <ID> --release-id <回执ID>` 对同一发布版重试；不允许绕过失败的验签或能力校验。失败时准确报告 `uploaded/granted/active` 的真实状态，不能把已上传称为已上线。

`super_expert_public` 的运行代码必须使用插件隔离进程，并且不获得 `unrestricted_tools` 或任意 MCP 客户端特性；隔离器不可用时上传返回 `503`，运行时失败关闭。第三方 API 通过 Agent 声明并获授权的 `agent.outbound/1` 等插件能力调用，客户本机重任务通过本地助手执行。签名不等于代码安全，管理员事后删除不能替代隔离。旧 `super_expert` 的签名包、权限、运行和管理员更新链路均保持不变。

平台发布 `super_expert_public` 前，必须在实际运行容器内验证 `/usr/bin/bwrap` 存在，且该容器能够成功创建用户、进程和网络命名空间；仅检查二进制文件存在或插件热加载成功不算通过。未通过时，开发方可以继续离线构建和验签，但自助上传不可用，平台维护方负责补齐运行容器的隔离器和容器权限。此项属于运行环境门禁，不能通过把未受信开发者代码改回服务进程内执行来绕过。上传后的激活若失败，错误回执应包含已安装的 `release_id` 及准确的 `uploaded/granted/active` 状态，以便开发者修复环境后重试。

生产可将隔离器放在插件专用的独立容器，主 Server 只通过插件的 Unix socket 合同转发已授权的业务能力调用，不给主 Server 增加命名空间权限。隔离容器不得连接外网或挂载 Server Secret；根文件系统只读，只挂载插件源码、签名发布物、工作区运行状态与 socket 目录。插件代码必须通过稳定的 `plugins` 父目录只读挂载；不得单独绑定插件子目录，否则热更新原子替换子目录后隔离容器会保留失效的旧挂载。插件内的 `tools/Dockerfile.public-runtime` 和 `tools/configure_public_sandbox.py` 分别提供隔离运行镜像的构建配方与现有 Compose 项目的备份式配置步骤。插件热更新涉及隔离器代码时，必须同步重启该隔离容器并重新执行隔离环境探针；主 Server 不因隔离器代码更新而需要重启。隔离容器不可用时，新的自助上传失败关闭，不影响历史 `super_expert` 包。

### 22.2 历史管理员发布链路

开发方取得 DClaw 后台管理员账号后，可以自行完成发布，但只能在签名者已入驻且目标平台支持所声明能力后进行。服务器 SSH 或 root 权限不构成 DClaw 后台应用身份，也不授予 Developer Pack/DevKit 下载、签名、上传、授权或激活权限。

每个版本必须逐项报告六态，布尔值和证据分开保存：

| 状态 | 达成条件 | 最少证据 |
|---|---|---|
| `source-complete` | 源码、合同、测试和未签名构建输入完成 | 源码修订摘要、测试回执、已知阻塞；不得把资源构建输入称为正式包 |
| `sealed` | 使用当前目标环境认证下载的官方 DevKit 完成四步证据链并独立验签 | DevKit/Schema/目录版本、ZIP SHA-256、signer、content/capability digest、`verify` 回执 |
| `uploaded` | 服务器接受该准确 ZIP 并完成验签/运行时校验 | release ID、服务器识别的摘要、signer、`package_type` 和验证状态 |
| `granted` | 自助包由开发者本人、历史官方包由管理员整体接受准确能力清单 | installation/grant ID、授权来源与操作者、能力摘要和授权时间 |
| `active` | 该 release 原子切换为当前运行版本且运行时验证有效 | active release ID、激活时间、runtime validation 和回滚目标 |
| `e2e-verified` | 项目方从正式 DClaw 客户端完成并确认真实用户任务验收 | 项目方确认的任务记录、必要的 trace ID、真实第三方回执、产物摘要或人工检查结果 |

新 Agent 的 `sealed` 只接受独立官方 DevKit 证据；第 21.6 节历史 canonical 包保留其历史状态与证据类型，不得伪造为 DevKit 回执。某一状态为真不能推导后续状态，后续失败也不得回写伪造前序证据。

标准流程：

1. 使用 DClaw 应用身份登录管理后台，并从该目标实例认证下载版本匹配的 Developer Pack/DevKit。
2. 核对超级专家 signer 和所有 capability-package signer 已分别进入准确的信任域。
3. 若 Agent 依赖业务服务安装级身份，确认目标实例已经公开对应能力 ID、Schema、scope、注入/交换语义和最低版本，并能在能力目录和授权预览中看到；否则停止发布。
4. 核对正式 artifact/资源 URL、允许域、`release_ready`、大小、SHA-256、SBOM、许可证和目标组件部署版本全部通过。
5. 进入“设置 → 密封 Agent”并上传签名 ZIP。
6. 核对返回的 `agent_id`、版本、签名者、`content_digest`、`capability_digest` 和状态。
7. 打开授权预览，逐项核对完整能力清单。
8. 整体接受安装授权；发现多余或未知能力时取消发布并重新构建，禁止勉强授权。
9. 激活新发布版。
10. 确认运行时验证成功并且新版本处于 `active`。
11. 记录 release ID、installation ID、激活时间、操作者和回滚目标；开发、移植与优化 Skill 到此结束。
12. 将当前版本、已知限制、回滚目标和 `e2e-verified=false / 待客户验收` 移交项目方，由项目方自行从正式 DClaw 客户端验收并决定是否开放客户使用。

```mermaid
flowchart LR
    A[签名 ZIP] --> B[上传与验签]
    B --> C[运行时验证]
    C --> D[能力授权预览]
    D --> E[管理员整体授权]
    E --> F[原子激活]
    F --> G[项目方客户验收]
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

标准 `2.8` 已接受并实现安装级业务服务身份；目标环境只有同时达到插件 `1.10.1`、DevKit `1.4.1` 和 Developer Pack `1.5.1`，并完成服务登记与安装/发布版授权，才可以宣称该能力可用。Windows 客户端 `2.6.13` / Runner `1.1.0` 的交付只影响本地文件链路，与服务端业务身份能力分别核对。

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

#### 25.2.1 安装级业务服务身份（accepted / implemented）

平台负责人已接受该通用能力，正式实现由 `dclaw.super-agent-support` `1.10.1` 提供，机器合同由 DevKit `1.4.1` 发布，并随 Developer Pack `1.5.1` 交付。Agent 只有在目标环境完成服务登记、精确发布版/安装授权且 manifest 声明该能力时才能使用；插件或合同版本不足时必须失败关闭。

- 正式能力 ID：`business.service.installation-identity/1`
- 合同版本：`1`
- 归属：`dclaw.super-agent-support`
- 目的：让获授权的超级专家调用开发方业务服务时使用短时、安装绑定身份；Agent 永远拿不到平台签名私钥、长期共享 Secret、刷新 Token 或 bearer 原文。

公开操作 `business_service_identity_issue` 的请求是关闭对象，只允许以下字段：

| 字段 | 约束 |
|---|---|
| `service_id` | 预先注册的稳定服务 ID，最长 128 字符 |
| `audience` | 正式 HTTPS audience，必须与服务登记完全匹配 |
| `scopes` | 非空、去重，只能是安装授权范围的子集 |
| `ttl_seconds` | 可选，`30..300`，默认 `120` |
| `idempotency_key` | `16..128` 字符，在同一安装和服务内幂等 |

响应同样是关闭对象，只返回 `binding_ref`、`service_id`、`audience`、`scopes`、`issued_at`、`expires_at`、`issuer`、`key_id` 和 `audit_id`。`binding_ref` 只能交给平台管理的 HTTP/MCP 出站运输层；平台在发送请求时注入短时签名断言，Token 原文不得返回 Agent、写入卡片、对话、普通日志或本地能力输入。

DevKit `operation-catalog.json` 是准确的调用入口目录。超级专家运行时使用客户端键 `business_identity.issue` 和 `business_identity.outbound`；宿主分别映射为 MCP 工具 `business_service_identity_issue` 和 `business_service_outbound_request`。正式入口是 `/api/super-agent-support/mcp/`，运输协议为无状态 MCP Streamable HTTP 与 JSON-RPC `2.0`。宿主完成 `initialize`、`notifications/initialized`、`tools/list` 后通过 `tools/call` 调用，并从受信运行上下文注入 `dclaw_session_token`；Agent 不得自行构造原始 JSON-RPC、提交或覆盖该参数。每次出站必须先成功调用 `issue` 取得一次性 `binding_ref`，再调用 `outbound`，禁止缓存或跨调用重用。

`business_service_outbound_request` 必填 `binding_ref`、`method` 和 `url`，可选 `headers`、`json_body`、`text_body` 和 `timeout_seconds`；请求体可以省略，存在时只能在 `json_body` 与 `text_body` 中选择一个。Agent Header 仅允许 `Accept`、`Content-Type`、`Idempotency-Key`、`User-Agent` 和 `X-Request-Id`，Header 名按大小写不敏感处理，大小写重复项必须失败关闭。Agent 提供任何 `Authorization` 都必须失败；平台在实际出站请求中只注入一个 `Authorization: Bearer <assertion>` 并原样传递。业务服务收到缺失、重复、合并多值、非 Bearer 或空 Token 时必须失败关闭。断言值禁止进入普通日志、trace、错误响应和 Agent 可见输出。

这里的 MCP/JSON-RPC 只描述 Agent 调用 DClaw 平台 `issue` 和 `outbound` 两个宿主工具的入口，不表示平台会作为客户端连接开发方的 FastMCP 服务。合同 `1` 的 `outbound` 是一次无会话 HTTP 请求；Agent 禁止在 `json_body` 或 `text_body` 中自行构造目标业务 MCP 的 `initialize`、`tools/list`、`tools/call` 或维护 `Mcp-Session-Id`。开发方业务服务必须在已登记 audience 路径下提供固定 Schema 的普通 HTTP JSON 端点；其内部可以复用 FastMCP 实现，但该内部协议不暴露给 Agent。若未来需要由宿主管理开发方 MCP 会话，必须另行评审并发布通用业务 MCP 运输能力、客户端键、Schema、状态、鉴权和兼容版本，不能扩张本合同字段或让 Agent 手写 JSON-RPC。

公开验签键固定从匿名 `GET /api/super-agent-support/business-identities/verification-keys` 获取。该匿名权限只匹配精确的 GET/HEAD 路径，插件卸载后立即撤销；其他插件路由继续执行 DClaw 身份认证。响应提供 `ETag` 和短时公共缓存，业务服务应使用条件请求并在密钥轮换后刷新；平台必须限制请求频率和客户端状态数量，响应只能包含公钥材料。

出站 URL 必须使用正式 HTTPS、公网解析地址、登记域名和 audience 的同一 origin，并限制在 audience 路径本身或其子路径；重定向被拒绝。请求与响应正文上限均为 1 MiB，响应按流式读取在超过上限时立即中止，不能先完整缓冲后判断。

平台从已认证运行上下文派生 `tenant_id`、`user_id`、`agent_id`、`release_id`、`installation_id`、`session_id` 和已授权能力，Agent 输入不得声明或覆盖这些字段。签名断言至少包含 `iss`、`aud`、`sub`、`jti`、`iat`、`nbf`、`exp`、上述安装上下文字段、`service_id` 和 `scopes`；`sub` 是不可变安装身份。该能力不依赖 `local.execution.session/1`，不授予本地执行、能力包安装、客户凭证读取或任意网络访问，这些权限继续使用独立能力和管理员授权。

管理员登记业务服务时必须固定开发方、`service_id`、HTTPS audience、允许域、允许 scope 和公开验签方式；安装授权再把该登记绑定到一个签名 Agent 发布版和 scope 子集。更改 Agent 发布版、audience、域名或 scope 必须形成新的授权记录。

平台签名私钥必须放在平台 Secret 存储，禁止进入 Agent 包、能力包、数据库导出、客户端、Runner 或业务服务配置。轮换使用新 `key_id`，先公开新公钥再切换签发，旧公钥至少保留最大 Token 生命周期与时钟偏差之和；同一 `key_id` 禁止静默替换不同密钥。紧急轮换立即停止旧密钥签发，并允许按 `jti` 拒绝仍未过期的断言。

撤销范围必须覆盖服务登记、Agent 发布版、安装、scope 授权、签名密钥和单次 binding。撤销立即阻止新签发；出站运输在注入前再次检查撤销状态。开发方业务服务至少验证签名、JWK issuer、Header `typ=JWT`、`key_id` 的 `alg/use`、断言 issuer、audience、Agent、service、安装、发布版、有效期和业务操作所需的非空最小 scope 集合，跨安装、跨 Agent、跨服务重放必须失败。调用平台在线验证接口时，上述期望值均为必填，平台原子消费 `jti`，第二次或并发重复验证稳定返回 `BUSINESS_IDENTITY.ASSERTION_REPLAYED`。使用公开 JWK 离线验签时，业务服务必须使用 DevKit `business_identity_verifier.py` 或等价持久化 replay cache，把每个已接受的 `(issuer,jti)` 原子保留到 `exp + clock_skew`；签名有效不能单独视为已防重放。

审计记录签发、注入、拒绝、轮换和撤销，字段至少包含 `audit_id`、`trace_id`、操作者、租户、Agent 发布版、安装、服务、scope、audience、结果、稳定原因码、`key_id` 和时间；禁止记录 bearer 原文或私钥。稳定错误至少包括 `BUSINESS_IDENTITY.NOT_GRANTED`、`SERVICE_UNKNOWN`、`AUDIENCE_NOT_ALLOWED`、`SCOPE_NOT_ALLOWED`、`INSTALLATION_REVOKED`、`RELEASE_MISMATCH`、`SIGNER_UNAVAILABLE` 和 `RATE_LIMITED`，且不得泄露其他租户、用户、Agent 或安装是否存在。

兼容要求：合同 `1` 只能做向后兼容修订；现有未声明该能力的 Agent 继续运行，现有静态业务凭证不得静默迁移。新增或改变请求/响应字段、权限语义或必填 claim 必须发布新合同版本。最低组件版本为支持插件 `1.10.1`、DevKit `1.4.1` 和 Developer Pack `1.5.1`；该能力由服务端签发、验证和注入，不要求客户端或 Runner 升级。

正式发布必须持续通过以下测试：关闭 Schema 正反例；运行上下文防伪造；租户、用户、Agent、发布版、安装、服务、audience 和 scope 隔离；签名、有效期、时钟偏差与重放；轮换重叠和紧急撤销；日志、trace、卡片、Agent 输出、数据库导出、崩溃转储和客户端流量无 Token/私钥；插件禁用与卸载隔离；升级/回滚不恢复已撤销签发权；真实业务服务端到端验签及跨安装重放失败。

#### 25.2.2 Agent 自主第三方出站（accepted / implemented）

平台负责人已接受该通用能力，正式实现由 `dclaw.super-agent-support` `1.15.0` 提供，机器合同由 DevKit `1.8.0` 发布，并随 Developer Pack `1.9.0` 交付。

- 正式能力 ID：`agent.outbound/1`
- 合同版本：`1`
- 归属：`dclaw.super-agent-support`
- 目的：让密封超级专家直接负责第三方业务 API 的选择、参数、幂等、创建、轮询、重试、费用和结果解释，同时使长期 Key 只在受控运输边界出现。

该能力不是本地助手任务，也不是开发方业务服务。超级专家通过 DevKit `operation-catalog.json` 的客户端键 `agent_outbound.request` 调用 MCP 工具 `agent_outbound_request`；宿主从受信运行上下文注入 `dclaw_session_token`。Agent 必须声明 `agent.outbound/1`，但不需要同时声明 `local.execution.session/1`。需要下载或加工第三方结果时，Agent 取得公开或短时预签名 URL 后，再独立调用本地助手；本地助手不得接收 `credential_slot`、`credential_ref`、第三方长期 Key、认证 Header 或供应商控制面任务。

安装时通过认证接口 `POST /api/super-agent-support/agent-outbound/credentials` 绑定凭证。绑定请求必须固定供应商标识、认证类型、非空 scope、可用 Agent、可用安装、允许域名和允许方法。认证类型合同 `1` 只允许：

- `bearer`：平台在最终网络边界注入单个 `Authorization: Bearer <value>`；
- `header`：平台注入一个登记的认证 Header，例如 Sync.so 的 `x-api-key`。

新建或主动重建的 Agent 必须为每项安装凭证声明稳定 `credential_slot`，绑定时同时固定可用发布版；运行时只提交 slot，不保存每次安装产生的随机引用。插件在受信上下文中按租户、用户、Agent、发布版、安装和 scope 解析 slot。接口只返回 slot 和非 Secret 策略摘要，不返回认证值或底层 `credential_ref`。旧已签名 Agent 可以继续使用原有不透明 `credential_ref`，不得被强制重建或静默迁移。

运行请求必须在 `credential_slot` 与兼容的 `credential_ref` 中二选一，并提交 `credential_scope`、`method` 和正式 HTTPS `url`；可选 `headers`、`json_body`、`text_body` 和 `timeout_seconds`。请求体最多选择一种；Agent Header 只允许 `Accept`、`Content-Type`、`Idempotency-Key`、`User-Agent` 和 `X-Request-Id`，禁止提交任何认证 Header。插件必须验证公网 HTTPS、私网/环回/保留地址、域名允许表、方法允许表、scope、1 MiB 请求和响应上限、`1..60` 秒超时，并拒绝全部重定向。响应只返回状态码、Content-Type 和受限 JSON 或文本正文；认证值即使被上游回显也必须脱敏。

该合同只提供运输和凭证隔离，不识别 Sync.so、声音供应商或任何行业，不保存 Agent 不可见的业务任务，不决定供应商、请求路径、参数、轮询频率、重试、费用或完成条件。原业务确实已有开发方业务服务时，可以继续使用第 25.2.1 节；迁移不得仅为调用第三方 API 或保存 Key 新增业务服务、域名、audience 或 `business.service.installation-identity/1` 链路。

兼容要求：旧已签名 Agent、`business.service.installation-identity/1` 和本地执行合同继续有效，不强制迁移。新建或主动重建的 Agent 只要第三方调用本来属于其业务逻辑，就使用 `agent.outbound/1`；本合同字段或权限语义发生不兼容变化时必须发布新合同版本。

#### 25.2.3 Agent 流式出站与临时资源交换（accepted / implemented）

平台负责人已接受这两项供应商无关的通用能力，正式实现由 `dclaw.super-agent-support` `1.15.1` 提供，机器合同由 DevKit `1.8.1` 发布，并随 Developer Pack `1.9.1` 交付。

- 正式能力 ID：`agent.outbound.stream/1` 与 `resource.exchange/1`
- 合同版本：均为 `1`
- 归属：`dclaw.super-agent-support`
- 目的：支持有明确大小上限的第三方 HTTPS 二进制响应、WSS 流和本地助手资源交换，不让模型、普通 DClaw API 响应或本地助手接触长期凭证与媒体正文。

`agent.outbound.stream/1` 使用客户端键 `agent_outbound.stream` 和 MCP 工具 `agent_outbound_stream_request`。请求必须在 `credential_slot` 与兼容的 `credential_ref` 中二选一，固定 `https` 或 `wss`、正式公网 URL、scope、输出 MIME、用途、超时和最大输出大小；WSS 可以声明确定的发送帧、完成文本、二进制帧过滤和协议头剥离规则。HTTPS 可以选择关闭的 `response_transform={type:"json_base64",json_pointer:"/..."}`：插件只接受 JSON Content-Type，按 RFC 6901 精确取得一个字符串字段，执行严格 Base64 解码，并把解码结果直接写入临时对象存储；缺字段、错误 Pointer、非字符串、非 JSON、非法 Base64、额外转换字段或超限全部失败关闭。插件禁止重定向、私网/环回/保留地址和未授权目标，对经过插件运输的输出实施 `32 MiB` 硬上限并写入临时对象存储；响应只返回 `resource_ref`、MIME、大小、SHA-256 和过期时间，不返回原始 JSON、Base64 或媒体字节。更大的素材不得使用本合同，应由第三方返回短时 HTTPS URL 后交给本地助手直连下载。

`resource.exchange/1` 使用 `agent_resource_upload_create`、`agent_resource_upload_complete`、`agent_resource_read` 和 `agent_resource_revoke`。宿主从受信运行上下文绑定租户、用户、会话、Agent、发布版、安装和调用；上传前声明 MIME、大小上限、用途和 TTL，创建响应按专用关闭 Schema 返回 `resource_ref`、`status=pending`、MIME、大小上限、过期时间及只含 HTTPS URL、`PUT`、固定上传 Header、允许域和大小上限的 `upload` 对象，供本地助手直接上传。完成时核对实际大小与 SHA-256，读取只签发短时 HTTPS URL，撤销后立即失败关闭。对象存储不可用时返回稳定 `RESOURCE_EXCHANGE.STORAGE_UNAVAILABLE`，不得回退为 DClaw 服务端代理上传或下载。

需要本地加工时，超级 Agent 把短时 `resource_ref` 或预签名读取 URL 交给本地助手；本地助手下载后校验 SHA-256 并在客户本地执行。最终视频、音频和大文件仍必须落到客户本地目录。`agent.outbound.stream/1` 依赖 `resource.exchange/1`，但二者都不要求把第三方业务判断下沉到本地助手。

兼容要求：旧 `agent.outbound/1`、旧 `credential_ref`、旧签名 Agent、本地执行与业务服务身份合同继续有效；只有声明新能力的新发布版才使用流式和临时资源合同。不兼容字段或权限变化必须发布新的合同主版本。

### 25.3 平台评审结果

`business.service.installation-identity/1` 与 `agent.outbound/1` 的正式评审结论均为 `accepted`，并分别按第 25.2.1、25.2.2 节实现。后续修改其字段、权限、状态、隔离或资源限制仍须按本节重新评审。

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

超级 Agent 侧的第三方调用返回短时素材 URL；超级专家启动本地能力；能力包在客户 Windows 直接下载、剪辑并将 MP4 放在任务根目录。服务器不承载素材中转和剪辑 CPU。

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

完成源码和测试后，生成可复核的 manifest 与发布证据。只有本任务已经明确授权时才使用开发方私钥密封并上传；私钥不得输出到聊天或日志。上传后依次完成能力授权预览、整体授权和激活。开发会话在交付激活回执、已知限制、回滚目标以及 `e2e-verified=false / 待客户验收` 后结束；真实客户验收由项目方自行执行。任一步失败时保留 trace_id 并定位到最初失败层。
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
4. 完成职责映射：业务编排、第三方 API 调用和安装级凭证引用进超级专家侧，本地重任务进 Agent 能力包，公共身份、凭证保管和受控出站运输使用 DClaw 已发布的通用能力。只有源业务本来就有独立服务端时才保留业务服务，不得因迁移新增。
5. 只适配承载和调用边界，不改变已冻结业务行为；遇到无法等价承载的步骤立即记录阻塞或提交通用能力申请。
6. 使用同一组基线输入逐步对比源 Agent 与 DClaw 实现。只允许不改变字段含义、用户选择和状态语义的展示措辞差异；其余差异必须有逐项批准记录。
7. 涉及本地能力时，在开发或测试环境完成安装引导、任务恢复和产物检查；正式环境的真实客户验收由项目方自行执行。
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
| 交付范围 | 完成源码、测试、签名包、校验和、验证证据和管理员操作说明；已有管理员环境及会话授权时继续上传、授权和激活，并以“待客户验收”移交 | 发布会替换正在服务客户的生产版本，且当前会话没有该发布授权 |
| 验收 | 开发会话自动使用源测试和源案例完成 Node 6；项目方在 Node 8 后自行执行 DClaw 正式客户端验收 | 基线暴露未覆盖且会改变完成判据的业务场景 |
| 许可证 | 先盘点随包许可证和第三方清单，再报告具体缺口 | 找不到某个组件、模型、字体、音乐或素材的再分发依据 |
| 文档 | 职责和迁移规则写入本文要求的项目文档；平台标准只维护本文件 | 需要改变 DClaw 公共合同或新增平台能力 |

无法避免的问题必须一次集中提出，说明已经查过什么、缺少什么、不同答案分别会改变什么。不得逐项等待用户确认后再盘点下一项，也不得询问不会改变实现或交付结果的偏好。

“许可证”是第三方作者允许如何使用和分发其软件、模型或素材的规则。例如，把 FFmpeg、Python Runtime、Whisper 模型、字体或音乐安装到客户电脑，可能要求保留版权声明、附带许可证、公开修改源码，或禁止某些商业分发。Agent 开发方先检查源包已有的 `LICENSE`、`NOTICE`、依赖元数据和模型卡，形成组件、版本、来源、许可证、交付方式和未决风险清单。公共 Component 由 `dclaw.super-agent-support` 负责最终许可证审核与交付证据；Agent 私有依赖由开发方负责。只有证据确实缺失时才请权利人或用户补充，不先要求用户笼统回答“是否有许可证”。

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

上传、授权并激活后只能报告“已更新并激活，待客户验收”。只有项目方自行完成正式客户端验收并确认后，才能报告“已通过真实验收”。

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
- 项目方真实验收状态；已验收时归档其确认的脱敏任务记录、产物校验和必要的 `trace_id`，未验收时明确记录 `e2e-verified=false / 待客户验收`；
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

### 30.1 平台更新的完成定义

一次 Super Agent 平台更新只有依次完成以下阶段才可以报告“已完成”，每个阶段必须保留独立状态和证据：

1. **源码完成**：标准正文、版本记录、插件实现、Developer Pack、DevKit（如受影响）、Schema（如受影响）和回归测试在同一提交中一致；全仓测试通过。
2. **发布输入冻结**：服务端和客户端完整提交分别固定；客户端不受影响时必须明确固定当前生产提交，禁止因服务端更新顺带升级客户端。
3. **干净构建**：构建上下文在进入 Docker 前扫描并排除 AppleDouble、Finder、`__MACOSX`、缓存、字节码、凭据和生成物；镜像必须同时带服务端与客户端提交标签。构建必须明确目标主机，禁止把本机临时 Docker 构建误认为生产构建。
4. **镜像预检**：不启动生产流量前，从镜像内读取插件、标准、Pack 和 DevKit 版本并核对完整提交标签；任一不匹配不得部署。
5. **受控切换**：只有用户对该次具体镜像更新或部署已有明确批准才能重启或切换生产。部署器必须有单实例锁、资源前检、数据库备份、足够覆盖正常预热的健康超时、公开/本地 API 验证和自动回滚。预热期间只要容器存活、资源正常且仍在超时窗口内，不得人工重复重启。
6. **生产工具链冻结**：部署成功后立即按第 21.1.1 节用应用身份生成新的共享只读工具链；镜像内存在文件、服务器 SSH 权限或部署脚本成功都不能替代这一阶段。
7. **兼容回归**：至少验证一个不需要本地助手的旧 Agent、一个使用现有本地执行合同的旧 Agent，以及所有声明本次变更能力的 Agent。兼容测试不得修改旧签名包；旧 Agent 只有主动重建时才采用新 Pack 的构建门禁。
8. **责任会话收敛**：各活动开发责任会话在下一次新建、继续或恢复工作时自行记录已读取标准版本、采用工具链摘要、适用性判断和六态；平台统筹不为普通更新逐个动态通知。只有变更会阻断正在进行的发布，或用户明确要求通知时，才主动联系受影响责任会话。责任会话完成密封、上传、授权和激活后报告“已更新并激活，待客户验收”；项目方确认真实验收前，平台统筹和责任会话都不得把 `e2e-verified` 写为 `true`，也不得报告“已通过真实验收”。

发现可重复发生的问题时，必须在同一修复中至少增加一项机器门禁或回归测试，并把通用规则写入本文；只记录事故说明、只手工修一次数据或只口头提醒不算闭环。问题只属于单个 Agent 时由该 Agent 的责任会话修复并记录，不得为此把业务特例加入平台插件。

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
- [ ] Super Expert signer 的公钥指纹已由平台工具核对，并在基础验签与 `super_expert` 两个信任域中同时登记和加载。
- [ ] SSH 登录 key 未被当作发布 signer；同一发布公钥跨域使用时已有分别授权。
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
- [ ] 开发或测试环境中的卡片、状态机、外部合同、失败恢复和实际产物检查通过。
- [ ] Node 8 后已明确移交 `e2e-verified=false / 待客户验收`，没有用开发测试冒充项目方正式验收。
- [ ] 项目方已验收时，验收确认和必要证据已归档；未验收时不得勾选或推断通过。

### 31.5 发布

- [ ] 使用平台统一只读工具链目录；DevKit 从目标实例认证下载，版本与服务端 SHA-256 已核对。
- [ ] `production-receipt.json` 的服务端/客户端提交、镜像 ID、插件/标准/Pack/DevKit 版本、路由状态和 ZIP 摘要完整且无凭据。
- [ ] 工具链目录位于 Agent 项目和 DClaw 源码之外，内容只读，未复用旧版本或半成品目录。
- [ ] 使用的是 DClaw 应用身份；root SSH 权限没有被当作下载、上传或授权身份。
- [ ] `digest → validate → build → verify` 四步证据来自同一 DevKit 和构建输入。
- [ ] 能力 artifact/资源的签名绑定、HTTPS、摘要、SBOM 和许可证门禁通过。
- [ ] 正式 URL、允许域、`release_ready`、capability signer 信任域和目标平台部署版本全部通过。
- [ ] 依赖安装级业务服务身份时，目标实例已公开能力 ID、Schema 和授权入口。
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

它们是只供 Super Agent 本地重任务复用的公共 Component，全部归属 `dclaw.super-agent-support` 插件套件。插件负责构建、分平台制品、版本、许可证、SBOM、签名、SHA-256、HTTPS 上传、注册表、兼容和回滚；插件配套本地助手负责按需下载、验签、缓存、原子安装和版本切换。Agent 只声明并适配注册版本，不重复打包。DClaw 核心不识别这些 Component。

### 32.10 `optional` 和 `required` 如何选择？

没有本地助手仍能完成全部核心承诺，只在可选增强分支使用本地能力时才是 `optional`。任一核心结果依赖下载、上传、FFmpeg、Whisper、模型、渲染、浏览器、设备文件或本地成品时必须是 `required`，进入专家即预检。

### 32.11 历史 canonical 签名包是否有效？

有效。它证明对应历史版本通过当时的服务端 canonical 签名、验证、上传、授权和激活链路。它不能充当后来独立官方 DevKit 的下载、`digest`、`validate`、`build` 或 `verify` 回执；新开发方发布必须使用目标环境认证下载的独立 DevKit。

### 32.12 未签名依赖 ZIP 是否是正式能力包？

不是。只有已签名能力描述符、被描述符 SHA-256 绑定的 capability artifact、完成管理员注册和 Runner 准备后，才能称为正式能力包。外部大资源必须由 capability artifact 内受保护的资源清单固定并完成摘要、SBOM 和许可证校验；普通构建 ZIP 只能称为未签名资源构建输入。

## 33. 唯一外部输入与机器合同

开发方的外部输入固定为三类：

1. 本文文件 `super-agent-development-standard-v1.zh-CN.md`，通常随官方开发包交付；
2. 开发方自己的业务目标、源 Agent 材料和测试凭证；
3. 从目标 DClaw 认证调用元数据接口并按其 `download_path` 下载、核对 SHA-256 的官方开发包；兼容自动化可以继续单独下载同版本官方 DevKit。

当前开发包 `1.10.21` 是推荐的单一离线移交物，必须提供：

- 唯一标准文件与明确的标准版本，不复制第二套人工规则；
- 官方 DevKit `1.9.8` 及其完整离线加密依赖；
- `dclaw_developer.py` 的 `doctor`、`info`、`init`、`validate`、`test`、`keygen`、`capability-build`、`build`、`upgrade` 和 `demo`；
- 超级专家、业务服务和本地能力包模板，以及职责边界示例；
- Agent 自主出站、公共业务服务、本地执行和能力包 Schema/SDK；
- 版本化能力构建清单、任意资源的确定性归档与安全预构建 ZIP 导入；
- 受控 `unittest`/`pytest` 测试适配器以及真实命令和测试数量证据；
- 行为基线、差异批准、能力越权、依赖完整性、`resources.lock.json`、Secret、测试、密封和验签失败关闭门禁；
- 最小无网络演练、测试夹具、兼容矩阵、升级/回滚说明、SBOM、许可证清单、包清单和逐文件 SHA-256；
- 可重复归档构建器；相同源码、版本和固定时间戳必须生成相同 ZIP 字节。

开发包本身不得包含平台管理员凭据、生产地址、签名私钥、供应商 Secret、客户数据或 DClaw 私有实现。包内公开工具不得导入 `qwenpaw` 或要求开发者克隆服务器仓库。

当前 DevKit `1.9.13` 必须提供：

- `dclaw_agent_devkit.py`：`doctor`、`contracts`、`digest`、`validate`、`keygen`、`build`、`verify`；
- `capability-catalog.json`：当前可声明的能力、版本、组和依赖；
- `schemas/super-expert-manifest.schema.json` 与 `schemas/agent-profile.schema.json`；
- `schemas/publishing-v1/`：普通开发者公钥登记、自助发布与公开激活回执的关闭合同；
- `schemas/workspace-state-continuity-v1/`：签名包状态格式声明的关闭合同；
- `schemas/interaction-card-receipt-v1/`：可信建卡、提交回执与运行时回执列表的关闭合同；
- `schemas/local-execution-v1/`：本地请求、响应和错误合同；
- `schemas/super-agent-support-v1/`：能力包、设备命令、设备消息和凭证绑定合同；
- `schemas/business-identity-v1/`：安装级业务服务身份签发、出站、在线验证、管理和稳定错误合同；
- `schemas/agent-outbound-v1/`：Agent 自主第三方请求、响应、安装凭证绑定和稳定错误合同；
- `schemas/agent-outbound-stream-v1/`：HTTPS/WSS 流式出站请求、资源引用响应和稳定错误合同；
- `schemas/resource-exchange-v1/`：短时资源创建、完成、读取、撤销、响应和稳定错误合同；
- `schemas/runtime-failure-v1/`：授权读取本任务上次脱敏失败的请求、响应和错误合同；
- `schemas/interaction-card-read-v1/`：按可信安装与任务读取卡片状态、规范化答案和提交回执的关闭合同；
- `schemas/runtime-diagnostics-v1/by-reference-response.schema.json`：开发者按客户可见关联 ID 读取本专家脱敏失败的关闭合同；
- `schemas/runtime-diagnostics-v2/`：开发者按同一关联 ID 读取有界错误顺序、已恢复错误和最终阻断的关闭请求、响应及错误合同；
- `schemas/runtime-diagnostics-v3/` 与 `schemas/runtime-diagnostics-search-v1/`：开发者查询脱敏 Host 拒绝细节，或在缺少关联 ID 时按专家和有界时间窗发现失败引用；
- `runtime_diagnostics_api_demo.py`：使用本地登录身份和正式 Schema 的只读查询示例；
- `schemas/aigc-task-snapshot-v1/`：密封专家按可信安装与任务读取工作流状态和已验证产物资产 ID 的关闭合同；
- `schemas/local-task-host-v1/`：密封专家确定性启动、读取、取消本地任务及读取受限回执的关闭合同；
- `aigc_workflow_api_demo.py`、`local_task_api_demo.py` 及各自 `examples/`：现有 AIGC 模型工具/快照和本地任务 Host 调用的可运行参考、成功/拒绝门禁；
- `schemas/capability-package-signer-v1/`：管理员登记本地能力包签名公钥的关闭请求与回执合同；
- `operation-catalog.json`：正式 MCP 入口、客户端键、工具名、调用顺序和平台注入参数；
- `business_identity_verifier.py` 与 `fixtures/business-identity/`：公开 JWK 离线验签、持久化 `jti` 防重放、断言 Header 运输和正反夹具；
- `templates/minimal/`：最小 manifest、`agent.json` 和 `runtime.py`。
- `publish register-signer/upload/list/retry-activation`：使用普通用户登录令牌的正式自助发布命令；
- `bootstrap.ps1`、`bootstrap.sh`、`requirements.lock`、`CHECKSUMS.sha256` 和 `wheelhouse/`：在支持平台离线创建隔离环境，逐文件校验并安装固定加密依赖；
- `THIRD_PARTY_LICENSES.md`：列出随 DevKit 分发的依赖、版本和许可证。

平台方必须用兼容测试证明 DevKit 的能力摘要、规范化 manifest、内容摘要、Ed25519 签名和 ZIP 结构与服务器验收实现一致。DevKit 本身不得出现 `qwenpaw` 导入，不得读取平台仓库相对路径，不得要求安装 DClaw 服务端 Python 包。

平台内部实现文件、测试文件和维护文档可以继续存在，但它们只服务平台维护者，不属于开发方输入。开发方缺少字段或行为定义时应报告标准或 DevKit 缺陷；平台不得用“请克隆服务器源码”回答。

### 33.1 普通开发者终止根因诊断

插件 `1.18.22` 起，已登录且拥有该专家的开发者可按客户可见 invocation ID 调用 `GET /api/user/super-expert-publishing/runtime-diagnostics/v2/references/{invocation_id}?agent_id={agent_id}`。该接口按租户、开发者拥有的专家、真实任务和安装授权隔离，查询 30 天内失败记录，每账号每分钟至多 30 次，并记录脱敏审计。`404` 对不存在、跨租户、跨专家及无权查询的引用一视同仁；`429` 表示限流；`503` 表示诊断暂不可读。无需客户密码、管理员身份或密封包新增能力。旧 `/v1/` 接口保持原状。

普通开发账号在本机完成 DClaw 登录后，可使用其短期访问令牌调用；令牌只存在本机受控进程环境，不写入 Skill、日志或交付包：

```bash
curl --fail-with-body -H "Authorization: Bearer ${DCLAW_ACCESS_TOKEN}" \
  "https://dclaw.deepmega.cn/api/user/super-expert-publishing/runtime-diagnostics/v2/references/0123456789abcdef0123456789abcdef?agent_id=your_agent_id"
```

路径中的示例 ID 仅展示格式。正式请求/响应/错误以 DevKit `schemas/runtime-diagnostics-v2/` 为准；`found` 返回实际 Release、installation、阶段与失败顺序，`no_record` 是正常结果。

插件 `1.18.28` 起，普通开发者可用相同的专家归属身份读取 `GET /api/user/super-expert-publishing/runtime-diagnostics/v3/references/{invocation_id}?agent_id={agent_id}`。`/v3/` 只增加独立的 Host 终止拒绝详情：稳定 `error_code`、安全 `field_path`、`constraint`、`contract` 和 `recovery_action`，不返回异常消息、请求体、模型输出或客户内容。未知内部异常统一给 `HOST_INTERNAL_ERROR` 与关联 ID；历史 trace 缺字段时返回 `not_recorded`，不能推断具体拒绝码。`/v1/`、`/v2/` 原响应保持不变。Agent 运行时的 `runtime.failure.read/1` 也保持不变。

插件 `1.18.37` 起，普通开发者可在同一身份边界查询 `GET /api/user/super-expert-publishing/runtime-diagnostics/v4/references/{invocation_id}?agent_id={agent_id}`。`/v4/` 同时覆盖失败事务和 `runtime.complete` 后已提交、但业务受阻的回合。Host 对公开业务能力记录脱敏开始、完成和异常事件；仅返回能力 ID、安全状态/错误码、任务是否有受理回执及耗时，不记录请求参数、客户素材、模型正文或异常消息。响应区分 `runtime_outcome`、`transaction_status` 和 `task_acceptance`；历史版本未留存 Host 事件时为 `not_recorded`，不得据此断言任务未创建。插件另按可信租户、客户用户、任务、专家、installation 和 invocation 精确过滤其本地任务表，只返回任务 ID 的 SHA-256、当前状态、错误码和结果 SHA-256；`task_evidence=available` 表示该只读表可查，空 `tasks` 表示在该作用域没有受理记录。无法读取时为 `not_recorded`，不能凭历史 trace 推断终态。正式关闭 Schema、认证示例在 DevKit `1.9.19`。旧 `/v1/` 至 `/v3/` 及 Agent 的 `runtime.failure.read/1` 不变。

插件 `1.18.38` 起，普通开发者可用同一授权身份查询 `/runtime-diagnostics/v5/references/{invocation_id}`，取得 `blocker` 的安全阶段、稳定错误码、字段约束、责任线、恢复动作和证据状态。`aigc.task.assets.localize/1` 在请求校验、资产预检和本地任务派发阶段分别分类；未预期的 Host 异常只标为平台内部错误，不把异常文本或输入回传。历史记录缺少具体错误码时，`evidence=historical_detail_not_recorded`、`responsibility=undetermined`，不得据泛化的 `host_exception` 推断开发方、设备或平台的具体首错。`task_acceptance` 与 `tasks` 仍由精确作用域的任务表独立核对。`/v4/` 的关闭响应不新增字段，旧调用方继续使用；正式 v5 Schema 和认证示例位于 DevKit `1.9.20`。开发方应先核验任务是否受理；同一输入重试沿用幂等键，修改输入须使用新幂等键。设备类错误先恢复本地助手连接；平台类错误将关联 ID 交平台方处理，不盲目重发业务回合。

故障验收按职能节点分别给出 `passed`、`failed` 或 `unverified`，每项附关联 ID 和可复核证据。交互卡节点核对可信提交与读取回执；AIGC 节点核对任务快照、素材清单、每个所选素材的公开 OSS 地址可读性及允许目标来源的 CORS 响应；Agent 节点核对实际发给 Host 的请求、Schema 和能力授权；Host 节点核对本地化预检、幂等、设备选择、任务入表与派发回执；本地助手节点核对实时连接、任务接收、下载校验和原子落盘回执。前一节点通过只证明该节点职责完成，不能推断后一节点通过。设备持久表的 `online` 也不能代替实时连接或任务接收证据。Host 任务表无受理记录时，不把下载失败归因于本地助手。没有留存首错的历史回合保持 `unverified`，先修诊断再以受控故障验证，不能凭泛化 `host_exception` 要求客户重试。

若客户端没有给 invocation ID，开发者可查 `GET /api/user/super-expert-publishing/runtime-diagnostics/v1/search?agent_id={agent_id}&start={UTC}&end={UTC}&limit=50`。时间窗至多 24 小时、只查最近 30 天、每页最多返回 50 条失败的任务 ID、invocation ID、Release ID 和时间；没有正文。`has_more=true` 时以 `next_cursor` 原样传入同一时间窗的下一次查询。按同租户及专家绑定的真实任务过滤，不能据此查询其他专家或租户。两种新查询共享每账号每分钟 30 次限流和脱敏审计，`404` 隐藏不存在与越权差别，`429` 限流，`503` 表示诊断不可读。正式 Schema、路径和可运行示例在 DevKit `1.9.13`。

开发者先查看 `failure_events` 的时间顺序及 `outcome`，再以 `final_blocker` 判断本轮最终阻断。`first_failure` 仅为兼容字段，可能是已恢复的早期错误，不能单独当作整轮原因。`status=not_recorded`、`unrecorded_fields` 或 `provider_code/param=null` 表示当时没有留存，不得用模型解释补造。新回合的卡片参数校验失败返回 `field_path`、稳定 `constraint` 及 `contract`；提供方拒绝只记录 HTTP 状态、稳定 code 与 param，不记录错误正文、模型原文、提示词或客户数据。`stages` 中 `interaction.tool.invoked` 才证明模型进入了插件工具；`interaction.operation.started/completed/failed` 分别证明已发起、已完成或已失败的平台卡片操作。没有这些记录的旧回合不能据此推断工具未执行。

`agent.execute(execution_mode="agent_loop")` 会使用普通文本/工具调用模式，不继承模型配置里的 JSON-only 默认值。旧专家继续通过实时 `interaction_component_catalog` 的详细 Schema 使用建卡模型工具；新建或更新专家按第 13.1 节使用 Host 目录、两段无工具候选及直接 Host 建卡。两条路径都要求 `task_key` 为字符串、`interaction_revision` 为正整数、`card` 为对象，并取得真实 `PENDING` 回执。`response_format="json_object"` 只适用于候选模式，不与 `agent_loop` 组合。历史已签名专家无需变更请求；新增合同是可选的开发者读接口。

### 33.2 六部分公共能力验收

| 部分 | 正式接入和失败关闭证据 |
|---|---|
| 开发输入与盘点 | 使用目标实例的 Pack、DevKit、实时目录和当前 Agent 的真实需求；来源、版本和能力授权不明时停止相关节点。 |
| 业务编排与状态 | 专家负责流程、第三方 API 和版本状态；Host 回执、事务结果和同任务续接分别验证，不以模型正文代替。 |
| 交互卡 | 先读实时目录和详细 Schema，再建卡并核对 `PENDING`；客户提交后用 `interaction.card.read/1` 按真实 `interaction_id` 读取 `SUBMITTED`、规范化答案和提交回执，对 `event_id` 去重。`not_found`、未提交和回执缺失不推进业务状态。重复点击、刷新、旧卡和失败事务分别留证。 |
| AIGC | 先读实时工作流目录；`aigc.workflow.create/1` 返回任务并不代表生成完成。仅用 `aigc.task.snapshot/1` 的绑定 `material_task_id` 核对终态和同画布、同节点、同用户的资产 ID；若旧回合已创建画布却未保存 ID，使用可选 `aigc.task.binding.resolve/1` 从可信会话及兼容安装链找回唯一旧任务，不能从模型正文或卡片标题猜 ID。向后续图生视频工作流传资产前还须满足该工作流实时输入 Schema 和访问权限。 |
| 本地助手 | 只在真实需要时声明能力。能力包由独立 signer 签名，公钥由平台管理员通过插件登记，注册表及安装授权先核对；用 `local.task.start/1` 的同一幂等键取得受理回执，按 `task_id` 用 `local.task.read/1` 回读终态和不透明产物 ID。设备离线、回执丢失或状态不明时原键查询并停止下游，不换键重复启动。 |
| 密封、发布与诊断 | 用正式 Pack 验证、测试、密封和独立验签；普通账号自助发布后核对实际 Release/installation。失败时凭关联 ID 查询 `/v2/` 的最终阻断，旧 `/v1/`、已签包与现役专家合同并行；没有真实客户端及产物回执不得称端到端验收通过。 |

### 33.3 三种公共交互的可执行示例门禁

| 路径 | 开发方实际入口 | 成功判据 | 失败时动作 | DevKit 参考 |
|---|---|---|---|---|
| 问答/文件交互卡 | `interaction.capabilities.list/1` → `interaction.card.create/1` → 客户提交后 `interaction.card.read/1` | 实时完整 Schema 验证通过；建卡的 `PENDING`、`created` 回执与作用域、ID、修订、事件匹配；提交后再验 `SUBMITTED` 和答案摘要 | 不显示虚假卡片；同一问题按原幂等键回读，业务变更才递增修订 | `interaction_card_api_demo.py` 与 `examples/interaction-host-v1/` |
| AIGC 任务卡与生成 | `agent.execute(agent_loop)` 中获授权的 `aigc_workflow_catalog` → `aigc_workflow_create`；后续 `aigc.task.snapshot/1` | 蓝图通过实时 `workflow_schema`，节点和模型来自实时目录；创建事件与任务绑定一致；客户生成/提交后同任务、画布、节点和成功 job 的资产 ID 匹配 | 创建未确认按同一 `task_key`、`content_revision` 和蓝图查询/重试；未提交、失败 job 或资产不匹配不得进入下游 | `aigc_workflow_api_demo.py` 与 `examples/aigc-workflow-v1/` |
| 本地助手任务 | `local.task.start/1` → `local.task.read/1`，需要时显式 `local.task.cancel/1` | 同一能力、任务 ID 和幂等键；`succeeded` 且有符合 Schema 的不透明产物 ID 与结果摘要；Agent 再检查业务完成条件 | 离线、拒绝、丢回执或非终态保持原键与原任务 ID，不换键盲启 | `local_task_api_demo.py` 与 `examples/local-task-host-v1/` |

AIGC 任务卡与问答交互卡是不同合同，不能用一者的创建回执代替另一者。AIGC 的目录/创建由授权后动态注册的模型工具暴露，DevKit 示例中传入的工具 callable 仅用于合同测试；密封运行时通过 `agent.execute(execution_mode="agent_loop")` 触发同一工具，不直接获得平台内部 Python 对象。`aigc.task.snapshot/1` 和本地任务接口由 Host 从可信上下文注入租户、用户、安装、任务与调用身份；Agent 不得自行传这些物理作用域。AIGC 静态示例中的模型 ID、本地示例中的能力 ID 均为演示值，发布前须换成目标实例实时目录/注册表中实际存在且获授权的值。没有本地任务的 Agent 不调用本地助手。

### 33.4 AIGC 资产交接与本地化

超级专家负责从业务目标决定素材用途、槽位、顺序和最终产物；AIGC 模块负责生成资产及其任务绑定，并将生成素材写入公开可读的 OSS 存储范围；DClaw Host 负责所有权和作用域校验、公开地址可读性预检与任务回执；通用本地助手只负责把已授权素材安全下载到客户电脑，不承担业务筛选、剪辑决策或内容判断。Agent 和模型不接收、持久化或转述下载 URL。

标准流程固定为：

1. 以 AIGC 创建回执中的真实 `material_task_id` 调用 `aigc.task.assets.list/1`，只读取当前用户、会话、安装、工作流、画布、节点和成功 job 绑定的资产事实。
2. 从返回资产中选择实际需要的项，为每项填写唯一 `asset_id`、`usage`、`slot`、唯一非负 `order` 与 `destination`；请求数组顺序没有语义。`final_output` 只能写入任务根目录，其余素材只能写入 `res/`。
3. 以稳定幂等键调用 `aigc.task.assets.localize/1`。Host 验证完整计划和每个未签名 HTTPS OSS 地址的公开可读性后，才通过认证设备通道发送稳定地址给本地助手；地址不带到期签名，只要 OSS 对象存在且保持公开可读即可访问。Helper 1.4.5 或更高版本下载、校验、原子落盘并生成 `assets.json`；Agent 通过既有本地任务回执读取终态。地址不可公开读取时，Host 在受理前返回 `ASSET_PUBLIC_DOWNLOAD_UNAVAILABLE`，不得派发不可用地址或静默退回短时签名模式。

所有超级专家共用上述 Host 本地化合同，不按专家名称分叉。AIGC 生成素材上传须继承 OSS 的公开读取策略；平台维护方在改变 Bucket 或上传策略时须验证未来新对象的未签名 URL，而不能只核对已有对象。公开读取不改变 Agent 对资产清单的所有权与任务绑定校验。

最低版本为 Support Plugin `1.18.32`、DClaw Windows Local Helper `1.4.5`、DevKit `1.9.15` 和 Developer Pack `1.10.25`。设备过旧、离线或派发断线必须失败关闭，不得留下长期 `queued`；断线终态为 `LOCAL_GATEWAY.DEVICE_NOT_READY`，连接恢复后使用新的幂等键重试。

自插件 `1.18.43` 起，AIGC 素材本地化要求 Helper `1.4.6` 或更高版本。Helper 在独立异步任务开始前复制消息数据，使接收循环释放 JSON 文档后下载任务仍可读取；旧 Helper 不再接收此能力的新派发。Helper 的失败事件只上报固定阶段、稳定错误码、异常类别和版本，不传下载地址、素材名、本机路径或栈。插件在持久化前再次按白名单过滤。

插件 `1.18.44`、Helper `1.4.7` 起，专家可选择声明 `local.task.outputs.bind/1` 与既有 `local.task.start/1`，自动续用已成功本地化的设备文件。入参只有 `source_task_id` 和要用的唯一 `slots`；Host 仅接受同租户、用户、会话、专家以及已提交兼容安装链中的原成功任务，核对来源 Release、槽位与任务结果，再要求同一在线设备按原 `assets.json`、大小和 SHA-256 重新核验文件。成功回执按原 `order` 返回 `files[].slot/order/file.local_file_ref` 与过期时间；Agent 在**同一 invocation** 将引用放入下一 `local.task.start/1.local_file_bindings[slot]={"local_file_ref":...,"access":"read"}`。旧 Helper、失败任务、文件缺失或变化、跨设备、越权与不兼容安装均不可绑定。绑定重放可能颁发新的短时引用，但不会重新下载或启动任务；下游启动仍使用原幂等键。客户用 `file_selector` 手选设备文件属于另一条路径。正式关闭 Schema 位于 DevKit `schemas/local-task-outputs-bind-v1/`，调用示例位于 `local_task_outputs_bind_api_demo.py` 与 `examples/local-task-outputs-bind-v1/`。本操作不注册私有 FFmpeg 能力，也不代表下游视频任务完成。

普通开发账号可查询本专家的本地化任务：`GET /api/user/super-expert-publishing/local-task-diagnostics/v1/tasks/{task_id}?agent_id={agent_id}`，也可将路径中的 `tasks/{task_id}` 换为 `invocations/{invocation_id}`。正式合同为 `developer.local-task.diagnostics.read/1`，DevKit `1.9.22` 提供关闭的请求/响应 Schema 与 `local_task_diagnostics_api_demo.py`。接口按登录开发者的专家归属、原客户会话的租户/用户/专家身份、来源安装的 Release 授权逐项验证；同专家旧安装可只读定位，越权、无记录和超出 30 天留存统一返回 `no_record`，每账号每分钟限 30 次并记脱敏审计。返回 Host 受理/派发、Helper 接收、执行时留存的 Helper 版本、当前设备在线状态、任务终态和首错的安全分类。当前在线状态不代表执行时在线。历史未上报的首错细节明确为 `historical_detail_not_recorded`，不得从通用失败码推测具体异常；该接口供通用 Skill 的开发侧使用，不交给运行中的专家包。

新资产的非零大小和非空 SHA-256 必须与 Helper 下载结果一致。历史资产若没有服务端 SHA-256，Helper 仍必须计算并回报下载后摘要，但该值只是本次下载证据，不能声称已与服务端权威摘要比对；若历史资产已有非零大小，大小仍须一致。

正式机器合同位于 DevKit `schemas/aigc-task-assets-v1/`：`list-request.schema.json`、`list-response.schema.json` 和 `localize-request.schema.json`；本地化响应复用 `schemas/local-task-host-v1/receipt.schema.json`。完整调用示例位于 `examples/aigc-workflow-v1/README.md`，能力与操作入口分别以 `capability-catalog.json` 和 `operation-catalog.json` 为准。开发方不得从本文复制字段替代目标实例 DevKit Schema。

插件 `1.18.36` 起，更新后的专家可选择声明 `aigc.task.binding.resolve/1`。请求只含原 `task_key` 和可选 `content_revision`，也可传空对象，但空对象只在当前可信会话内唯一任务时返回 `found`。Host 沿已提交的 `workspace.state.continuity/1` 回执验证同租户、同用户、同专家、同会话和兼容安装链，再核对画布所有者；结果只返回原任务 ID、来源安装、修订与状态。`not_found`、`ambiguous`、`unavailable` 和 `invalid_request` 均不得触发新建画布。旧任务通过同样的可信校验后可用于现有快照、资产清单和本地化；原任务与作品状态保持不变。完整关闭 Schema 和示例在 DevKit `1.9.18`，随 Developer Pack `1.10.28` 分发。旧签名专家没有声明该可选能力时仍按原合同运行。

专家所有者也可用普通开发账号调用 `GET /api/user/super-expert-publishing/aigc-tasks/v1/sessions/{session_id}/binding?agent_id={agent_id}`，可选传原 `task_key` 和 `content_revision`。该只读接口复用每账号每分钟 30 次限流，记录脱敏审计；按实际客户会话核对专家、租户、用户、兼容安装及画布所有者，不接受客户端指定物理安装或用户。`found` 的 `created_event_persisted` 表示 Host 是否留有同任务的持久创建事件；`current_workspace_references_task=false` 只表示当前工作状态中没有精确的原任务 ID 引用，可帮助定位“创建已成功但绑定未保存”。两项均不推断专家代码为何未写入。`not_found`、`ambiguous`、`unavailable` 不返回其他用户任务。请求/响应 Schema 和 `aigc_binding_api_demo.py` 随 DevKit 发布；开发者在本机登录并把短期访问令牌保存在受控环境变量中，不通过聊天传递凭证。

Skill 和专家发布前须对每条实际使用的路径同时验证：正确目录与 Schema、真实授权、可确认的回执、错误/超时/重放/跨作用域反例，以及一次客户端“触发 → 展示 → 客户操作 → 同任务续接”。参考脚本通过单元测试只证明入参、回执和失败关闭规则，不能证明生产模型、客户端 AIGC 控件或客户设备已经可用。使用 `jsonschema` 等第三方校验器的签名运行时须自带适配版本及依赖，不能从开发包安装状态推断生产沙箱可用。

以上是通用 Skill 的平台合同输入。Skill 维护方应在其 `references/capability-verification.md` 补 `/v2/` 的首错和终止根因区分，在 `scripts/runtime_diagnostics_with_login.py` 增加按官方 DevKit v2 Schema 查询和摘要，在相关脚本测试加入已恢复错误、最终阻断、`no_record`、越权及旧版回退案例。平台不直接覆盖 Skill 发布仓库，也不把单个专家的业务字段写成公共规则。

## 34. 版本记录

### 2.56 - 2026-11-15

- Support Plugin `1.18.44`、Helper `1.4.7`、DevKit `1.9.23` 和 Developer Pack `1.10.34` 增加通用 `local.task.outputs.bind/1`：在原成功本地化任务和设备文件摘要复核后，为同一 invocation 的下一本地任务提供受信文件引用；原 `local.task.start/1` 合同不变。

### 2.55 - 2026-11-15

- Support Plugin `1.18.43` 与 Windows Helper `1.4.6` 修复 AIGC 本地化异步读取已释放 JSON 文档的问题，并仅对本地化能力提高最低 Helper 版本。
- DevKit `1.9.22`、Developer Pack `1.10.33` 增加普通开发者按本地任务 ID 或 invocation ID 查询脱敏本地任务首错的版本化合同；历史未记录细节不追补，既有专家请求与本地任务回执不变。

### 2.54 - 2026-11-14

- AIGC 生成素材统一使用公开可读的 OSS 存储范围；Support Plugin `1.18.40` 在 `aigc.task.assets.localize/1` 所有权校验后向本地助手发送无到期参数的稳定 HTTPS 地址，并在受理前验证公开可读性。Agent 仍只接收资产事实和任务回执，不接收下载 URL。
- Developer Pack `1.10.32` 与 DevKit `1.9.21` 同步此通用合同；既有请求和响应 Schema、Agent 签名包及 Helper 下载协议不变。

### 2.53 - 2026-11-14

- 按交互卡、AIGC、Agent、Host 和本地助手的职能边界逐节点回传证据与状态；素材可下载不代表本地任务已派发。
- 插件 `1.18.39` 为未分类本地化 Host 异常记录脱敏平台阻断和运行实现标记；DevKit `1.9.20` 的 v5 机器合同保持不变，Developer Pack `1.10.31` 同步本标准。

### 2.52 - 2026-11-14

- 插件 `1.18.38` 对 AIGC 资产本地化的请求校验、资产预检和任务派发记录稳定、脱敏的阻断证据；预期设备及幂等拒绝继续使用现有任务回执，未知内部异常由平台负责定位。
- DevKit `1.9.20` 与 Developer Pack `1.10.30` 提供普通开发账号按本人专家关联 ID 查询的 `/v5/` 关闭 Schema、操作目录和 API 示例；旧 `/v4/` 保持不变。历史未留存的首错只返回未知，不伪造根因。

### 2.51 - 2026-11-13

- 增加已提交但业务受阻回合的开发者只读诊断合同，定义脱敏 Host 调用、受理状态、事务终态及历史未留存语义。
- 保持原失败诊断接口和 Agent 运行时诊断合同兼容。

### 2.50 - 2026-11-13

- 插件 `1.18.36` 新增可选 `aigc.task.binding.resolve/1`，按可信身份和已提交的兼容安装链只读找回同会话已创建的唯一任务；快照、资产清单和本地化可使用核验后的旧任务 ID。零匹配、多匹配、越权和损坏回执均失败关闭，不重建画布或改写作品状态。
- 普通开发账号获得同一专家下的客户会话绑定只读查询及当前工作状态是否精确引用该任务的脱敏标志；查询复用限流和审计，不返回作品内容、素材 URL 或模型正文。
- DevKit `1.9.18` 和 Developer Pack `1.10.28` 增加关闭 Schema、操作目录和恢复示例。既有已签名专家不变；要主动调用新能力的专家需在下一版声明并获授权。

### 2.49 - 2026-11-12

- 旧签名专家的只读 `aigc_task_review` 在客户已完成任务时返回顶层 `status=ACCEPTED`，并以 `completion_source=customer`、`review_performed=false`、`write_applied=false` 明确完成来源，避免旧提示把兼容回执误解为 Agent 审核。
- 未完成任务返回真实持久化状态和 `customer_action_required=true`；严格绑定当前安装、会话和物料任务，跨安装、跨会话或跨任务均不可读。
- 正式组合更新为 Developer Pack `1.10.27`、Support Plugin `1.18.35` 和 DevKit `1.9.17`；旧专家包无需修改、重签或重新发布。

### 2.48 - 2026-11-12

- 新建或更新的超级专家继续禁止依赖 Agent 审核写能力；客户完成 AIGC 任务仍由平台在所有权校验后直接持久化为 `ACCEPTED`，不触发 Agent/模型审核。
- 对已经签名且声明 `aigc.review.complete` 的旧专家，Support Plugin `1.18.34` 提供同名只读兼容工具，只读取严格绑定的任务状态，不写入审核结论；已完成任务可继续会话，未完成任务明确要求客户进入任务页操作。
- 正式组合更新为 Developer Pack `1.10.26`、Support Plugin `1.18.34` 和 DevKit `1.9.16`；旧专家包无需修改、重签或重新发布。

### 2.47 - 2026-11-12

- 客户在 AIGC 任务页点击“完成并返回会话”后，平台在精确校验租户、安装实例、任务 binding、画布、节点和素材归属后直接将任务置为 `ACCEPTED`，不再调用 Agent/模型审核。
- 客户完成动作不依赖专家包声明 `aigc.asset.submit`；该能力与 `SUBMITTED → REVIEWING` 状态链继续保留给旧专家和历史任务兼容，不删除既有能力。
- 最低版本提升为 Support Plugin `1.18.32`、DevKit `1.9.15` 和 Developer Pack `1.10.25`；正式桌面客户端须使用包含 `ACCEPTED` 回执门禁的新版本，禁止把 `SUBMITTED` 或 `REVISION_REQUIRED` 误报为完成。

### 2.46 - 2026-11-12

- 新增 `aigc.task.assets.list/1` 与 `aigc.task.assets.localize/1` 的平台通用交接规范，明确超级专家、AIGC、Host 和本地助手的职责边界，以及“列举 → 选择 → 本地化 → 回读终态”的固定流程。
- 最低版本为 Support Plugin `1.18.31`、Windows Local Helper `1.4.5`、DevKit `1.9.14` 和 Developer Pack `1.10.24`；旧 Helper 不接收新任务，派发断线必须进入明确失败终态。
- 明确素材顺序、目录、摘要和大小校验规则；历史资产缺少服务端摘要时只把 Helper 计算值作为下载后证据。正式 Schema 和 Demo 路径收敛到第 33.4 节，既有 Agent 不声明新能力时无需迁移。

### 2.45 - 2026-11-11

- 插件 `1.18.28` 对新发生的交互卡 Host 失败只记录白名单化稳定错误码、安全字段、约束、合同与恢复动作；未知异常不泄露原文。旧 `/v1/`、`/v2/` 与已签名专家合同不变，历史未留存细节仍标为 `not_recorded`。
- DevKit `1.9.13`、Developer Pack `1.10.21` 提供普通开发者按关联 ID 查询 Host 终止拒绝的 `/v3/` 关闭合同，以及按本人专家和 24 小时时间窗寻找失败引用的只读合同、Schema 与 API 示例。查询按租户、专家和真实任务隔离、限流并审计。

### 2.44 - 2026-11-10

- DevKit `1.9.12` 与 Developer Pack `1.10.20` 补齐 AIGC 工作流任务卡及本地助手的 API 示例、调用顺序、实时目录、绑定回执、幂等与失败关闭门禁；插件 `1.18.27` 只发布参考材料和标准，不改变既有 Host 能力或已签名专家。
- 三种公共路径分别用真实合同验收，AIGC 任务卡不冒充问答交互卡；模型工具与直接 Host 调用的边界明确列出。

### 2.43 - 2026-11-10

- DevKit `1.9.11` 增加可运行的 `interaction_card_api_demo.py`，用统一 Host API 演示四种卡片读取实时目录、完整 Schema 与业务不变量校验、幂等建卡和 `created` 回执核对；Developer Pack `1.10.19` 同步收录。插件 `1.18.26` 不改变既有 Host 合同与已签名专家的行为。
- 新建及更新超级专家以该示例的公共边界和正反例测试为发布前门禁；Skill 维护方负责把同一门禁接入通用开发流程，专家责任方仍负责各自业务逻辑及签名包。

### 2.42 - 2026-11-10

- DevKit `1.9.10` 增加当前 Host `single_select` 完整实时目录快照、Draft 2020-12 校验示例和正反例回归，禁止手写关键词白名单或简化 Schema 冒充发布前验证；Developer Pack `1.10.18` 同步收录，插件 `1.18.25` 的 Host 接口和现有签名包行为不变。
- 漫剧专家 `0.3.21` 的本地校验器因遗漏顶层 `$defs`，在调用 Host 建卡前拒绝了平台合法 Schema；仅补 `$defs` 仍无法完整处理嵌套 `$ref`。专家责任方需修包重签，平台不代改其已签名业务包。

### 2.41 - 2026-11-09

- DevKit `1.9.9` 增加直接 Host 交互卡目录与建卡的关闭外层请求/响应 Schema、`single_select` 成功示例，明确实时 Schema、输入策略、幂等键及 `created` 回执关联；Developer Pack `1.10.17` 同步收录。插件 `1.18.24` 仅补公开开发材料，既有 Host 能力语义不变。

### 2.40 - 2026-11-09

- 统一新建及更新超级专家的交互卡流程：普通无工具调用生成内部业务文本，第二次无工具模型调用根据实时组件 Schema 生成卡片草案，专家运行时校验后通过 `interaction.card.create/1` 建卡并核对可信回执。首段文本在卡片提交前不对客户展示，第二段校验失败不降级为文本提问。
- 既有模型工具建卡路径保持兼容，已签名专家由各责任方更新发布包并验证状态续接。Developer Pack `1.10.16` 同步本标准，DevKit `1.9.8` 的现有 Host 与候选调用合同不变。

### 2.39 - 2026-11-09

- 插件 `1.18.22` 修复普通 `agent_loop` 继承 DeepSeek JSON-only 默认响应模式导致卡片工具调用被提供方拒绝的问题，并为建卡工具的关键参数生成有类型的工具 Schema；新增无正文的工具进入和平台操作 trace。候选模式、公开流式模式、旧卡片合同和已签名专家请求保持兼容。
- DevKit `1.9.8` 增加 `developer.runtime.diagnostics.by-reference/2` 的关闭请求、响应和错误 Schema，按有界顺序区分已恢复的早期错误与最终阻断；旧 `/1` 不变。历史未留存的提供方细节如实返回未知。
- Developer Pack `1.10.15` 同步唯一标准与 DevKit；补齐交互卡、AIGC、本地助手及通用 Skill 六部分接入与验收规则。

### 2.38 - 2026-11-08

- `developer.runtime.diagnostics.by-reference/1`：已登录开发者只能按自己拥有的 `agent_id` 和客户可见 invocation 关联 ID，查询最近 30 天内该专家的脱敏失败。路径为 `/api/user/super-expert-publishing/runtime-diagnostics/v1/references/{invocation_id}?agent_id=...`；不存在、越权与跨专家不得泄露其他客户内容。原按任务 ID 接口仍可用。
- 客户点击 `aigc.workflow.create/1` 生成的绑定工作流卡时，前端受认证的 `aigc.task.resume` 操作可继承该任务的工作流创建授权；Agent 自身调用 `aigc.task.resume` 仍须独立声明和授权。`aigc.task.snapshot/1` 是新的可选 Host 只读调用，请求仅含 `material_task_id`；结果只包含绑定身份、任务状态、版本以及同画布同节点、同用户验证过的资产 ID 与类型。历史 `SUBMITTED/REVIEWING` 只作兼容读取，非绑定画布输出不进入回执。
- `local.task.start/1`、`local.task.read/1`、`local.task.cancel/1` 为新的可选 Host 调用。Host 使用可信租户、用户、任务、专家及安装作用域，给幂等键加作用域，回执固定为 `local.task.receipt/1`，只返回任务 ID、能力 ID、原幂等键、状态、稳定错误、结果 SHA-256 和格式合格的不透明本地产物 ID；不返回本机路径或文件字节。跨作用域读取统一 `not_found`。原 `local_*` MCP 合同不变。
- 能力包是独立信任域。开发者生成并保管 Ed25519 私钥，只向平台管理员交付公钥和 `signer_id`；管理员经插件 `POST /api/super-agent-support/capability-packages/signers` 登记不可覆盖的公钥信任，再由管理员用插件原有 `/capability-packages/register` 接收签名描述符。未经信任、摘要或签名不符均失败关闭。当前不开放普通开发者自行登记能力包 signer；这不影响超级专家密封包的普通账号自助发布。
- 插件 `1.18.21`、Developer Pack `1.10.14`、DevKit `1.9.7` 发布上述新增接口；既有签名包、旧接口和旧安装授权无需改变。

### 2.37 - 2026-11-07

- 将插件公共接口稳定性和现役专家适配纳入发布门禁：逐能力盘点生产调用，旧合同保持并行兼容；有影响时同步更新、重签并验证每个受影响专家，未完成前不得撤销旧合同。
- Developer Pack `1.10.13` 同步本标准；插件 `1.18.20` 和 DevKit `1.9.6` 的机器合同不变。

### 2.36 - 2026-11-07

- 插件 `1.18.20` 增加可选 `interaction.card.read/1`，密封运行时可按可信作用域直接读取已提交的规范化卡片答案；未找到与越域读取统一返回不可枚举结果，旧卡片能力和旧签名包保持不变。
- 明确回执答案摘要算法、修订与事件去重、接口版本演进及现役专家影响检查。Developer Pack `1.10.12` 与 DevKit `1.9.6` 发布关闭 Schema。

### 2.35 - 2026-11-07

- 插件 `1.18.19` 为卡片建卡与提交提供版本化机器回执；`session.context` 只返回同安装、同任务最近的持久化回执，普通输入文本不能证明卡片已提交。
- 新失败回合记录不含模型正文的运行时调用、`session.context`、`agent.execute` 与事务阶段、耗时和候选形状；开发者只读诊断在已有 30 天权限与审计边界内返回这些阶段。每条阶段标明 `source=host|agent`，Agent 自写 trace 不构成 Host 提交证据；运行时调用耗时包含沙箱启动与执行，排队时间尚未单独留存。Host 调用首错标记 `first_failure_source=host_stage`，历史未留存字段保持未知。失败提示显示安全类别、下一步动作和 invocation 关联 ID；作品状态事务仍在失败时丢弃。
- Developer Pack `1.10.11` 与 DevKit `1.9.5` 增加关闭 Schema，既有签名包、核心 SPI 和卡片字段保持兼容。

### 2.34 - 2026-11-06

- 插件 `1.18.16` 使业务回合正式输出与内部候选、临时系统指令在 Agent memory 中隔离，并提供带消息及状态摘要核对的历史修复工具；作品状态不受影响。
- 自助上传激活前检查所有已有任务的状态兼容性，冲突时旧 Release 保持激活，新 Release 可依据脱敏类别补齐登记后重试；成功回执报告预检任务数，实际任务状态仍按原合同在下一次业务回合前迁入。
- Developer Pack `1.10.10` 携带本标准和 DevKit `1.9.4`；DevKit 增加发布回执的关闭 Schema 字段。旧签名包与密封格式兼容。

### 2.33 - 2026-11-06

- 插件 `1.18.15` 增加签名声明驱动的 `workspace.state.continuity/1`：同一专家兼容 Release 的完整任务状态在首次业务回合前原子续接，不兼容或目标冲突时失败关闭；旧签名包可由插件维护方依据相同签名状态代码和发布摘要登记一次兼容关系。
- Developer Pack `1.10.9` 携带本标准和 DevKit `1.9.3`；DevKit 校验可选 `agent/state-contract.json` 并提供关闭 Schema。既有已签包保持原样，历史逐字段迁移工具保留作特殊恢复用途。

### 2.32 - 2026-11-06

- 插件 `1.18.14` 修复失败回合保存聊天历史时可能覆盖既有 Agent memory 的问题：在运行时执行前保存内存快照，失败后恢复原历史，再加入本轮请求和失败提示；异常中断也恢复快照。无法安全恢复时不提交失败回合的内存状态。既有作品状态事务和 `agent.execute` 请求合同不变。
- Developer Pack `1.10.8` 同步本标准；DevKit 仍为 `1.9.2`。历史上已被覆盖的内存不会由此自动恢复，须依据可验证的独立来源单独处理。

### 2.31 - 2026-11-06

- 插件 `1.18.13` 将发布目录摘要不符等启动前失败记录为脱敏 `platform_preflight`，可由原有 `runtime.failure.read/1` 跨同一专家安装版本读取；失败回合的聊天消息仍保存，作品状态事务保持丢弃。
- 普通开发者可用已登录身份读取自己的任务诊断：`GET /api/user/super-expert-platform/runtime-diagnostics/v1/tasks/{task_id}?agent_id=...`。返回最近 30 天同一专家跨安装的失败记录、失败回复的 `persisted/missing/unknown` 回读状态，以及当前消息表与 Agent memory 的只读数量；越权返回 404，读取写审计日志，不返回正文。历史上未记录的失败及逐轮持久化状态不能据此补造。
- DevKit `1.9.2` 构建密封包时排除 `.pyc`、`__pycache__` 等生成缓存，避免可变缓存成为签名发布内容；旧已签包继续按原摘要校验。Developer Pack `1.10.7` 提供新版 Schema。签名发布目录不得直接导入执行验证，须使用隔离副本。

### 2.30 - 2026-11-05

- 插件 `1.18.12` 新增可选 `runtime.failure.read/1`，按可信任务和授权主体读取同一专家跨安装、30 天内的最近一次脱敏失败；旧专家基础能力闭包不变。
- 明确 `agent.execute` 候选模式的 `json_object` 请求边界与不支持的强制 Schema、可配置输出上限和 thinking 控制。
- Developer Pack `1.10.6` 与 DevKit `1.9.1` 提供正式调用说明和闭合 Schema。

### 2.29 - 2026-11-05

- 插件 `1.18.10` 将迁移目标状态文件名绑定到 installation/session，并在每次运行时提交前拒绝状态文件分叉，脱敏诊断为 `state_scope_conflict`。
- 增加凭既有修复回执和当前状态 SHA-256 补登记绑定的维护工具；未迁移任务的运行合同不变。
- Developer Pack `1.10.5` 随标准 `2.29` 发布；DevKit `1.9.0` 保持兼容。

### 2.28 - 2026-11-05

- 插件 `1.18.9` 修复跨安装状态迁移首次初始化时沿用旧文件名的问题；目标文件名由新版 Agent 明确提供并在预检时核对。
- 增加受迁移回执和文件摘要约束的只读预检及状态分叉修复工具，保留被遮蔽的候选原文件，不改写业务 JSON。
- Developer Pack `1.10.4` 随标准 `2.28` 发布；DevKit `1.9.0` 和 Agent 运行合同不变。

### 2.27 - 2026-11-05

- 插件 `1.18.8` 将公开专家隔离容器的只读插件挂载改为稳定父目录，避免插件热更新后工作进程文件不可见。
- Developer Pack `1.10.3` 随标准 `2.27` 发布；DevKit `1.9.0` 与既有 Agent 包保持兼容。

### 2.26 - 2026-11-05

- 插件 `1.18.7` 为 `workspace.state.empty-field-migration/1` 增加显式空目标初始化分支，保留逐字段原子提交、预检摘要与旧安装不变的约束。
- Developer Pack `1.10.2` 随标准 `2.26` 发布；DevKit `1.9.0` 和 Agent 运行合同不变。

### 2.25 - 2026-11-04

- 支持插件 `1.18.6` 提供维护侧 `workspace.state.empty-field-migration/1` 预检、原子迁入和脱敏回执；每个 Release 的 installation ID 仍独立，旧状态不会自动迁移。
- Developer Pack `1.10.1` 随标准 `2.25` 发布；DevKit `1.9.0`、Agent 密封格式和既有运行合同保持不变。

### 2.24 - 2026-11-03

- 插件 `1.17.0` 新增 `super_expert_public` 受限包类型、开发者公钥与专家归属登记、普通用户自助上传、整体授权和公开激活；管理员保留停用与删除。
- 新包类型的业务代码使用插件管理的隔离进程，平台 Agent 不授予无限制工具或任意 MCP；隔离器不可用时失败关闭。既有 `super_expert` 包及管理员发布路径保持兼容，DClaw 核心没有修改。
- DevKit `1.9.0` 与 Developer Pack `1.10.0` 默认生成自助公开包，提供 `publish` CLI、Schema 和目标实例认证下载材料。

### 2.23 - 2026-11-02

- 支持插件 `1.16.0` 在热安装包内发布 Windows 本地助手及不可变版本清单，并提供登录用户可访问的版本检测和下载接口。
- Windows 客户端 `2.6.19` 删除内置助手，首次使用时按需下载，校验大小与 SHA-256 后原子切换；新版本启动失败时保留上一版回退。
- Runner 过旧动作由 `update_dclaw` 改为 `update_local_helper`；DevKit `1.8.3` 与 Developer Pack `1.9.3` 同步发布关闭合同。

### 2.22 - 2026-11-02

- 支持插件 `1.15.2` 新增管理员公共 Component 制品直传初始化、完成校验和插件托管 URL 注册门禁；大文件不经过 DClaw Server。
- DevKit `1.8.2` 新增 `component-registry upload` 及关闭上传 Schema，Developer Pack `1.9.2` 随附标准 `2.22`。
- 既有外部 HTTPS Component、Agent 私有能力包、密封包格式和已签名 Agent 继续兼容；本版不要求客户端或 Runner 升级。

### 2.21 - 2026-10-31

- 支持插件升级为 `1.15.1`，补齐预签名上传创建响应的专用关闭 Schema，公开合同与既有运行时返回保持一致。
- `agent.outbound.stream/1` 增加可选的供应商无关 HTTPS JSON Pointer 加严格 Base64 媒体提取，原始 JSON、Base64 和媒体字节均不进入 Agent 响应。
- DevKit 升级为 `1.8.1`，Developer Pack 升级为 `1.9.1`；合同主版本仍为 `1`，旧 Agent、旧包和不使用新可选字段的调用保持兼容。
- 两项补丁全部属于 `dclaw.super-agent-support` 插件，不修改 DClaw 核心，也不要求客户端或 Runner 强制升级。

### 2.20 - 2026-10-31

- 支持插件升级为 `1.15.0`，新增安装级稳定 `credential_slot`，同时保留旧 `credential_ref` 和旧签名 Agent 的兼容路径。
- 正式发布 `agent.outbound.stream/1` 与 `resource.exchange/1`：受控 HTTPS/WSS 输出限制为 `32 MiB` 并写入临时对象存储；本地助手资源使用预签名 HTTPS 直传，不经 DClaw 服务端代理。
- DevKit 升级为 `1.8.0`，发布流式出站、临时资源和稳定凭证槽 Schema 与操作目录；Developer Pack 升级为 `1.9.0` 并内嵌标准 `2.20`。
- 修复通用插件事务化热加载：同一核心 SPI 下安装、升级和回滚无需重启 DClaw 主服务；失败恢复旧文件、旧配置和旧运行注册，配置与 signer 不丢失。
- 旧 `agent.outbound/1`、业务服务身份、本地执行、公共 Component、密封格式和已签名 Agent 继续有效；本次不要求客户端或 Runner 因机器合同升级而强制更新。

### 2.19 - 2026-10-30

- 支持插件升级为 `1.14.0`，正式发布 `agent.outbound/1`；第三方业务请求由密封超级 Agent 决定，插件只负责加密凭证解析、策略校验和受控 HTTPS 运输。
- DevKit 升级为 `1.7.0`，发布 `agent-outbound-v1` 请求、响应、凭证绑定和错误 Schema，以及准确的 `agent_outbound.request` 操作目录。
- Developer Pack 升级为 `1.8.0`，内嵌标准 `2.19` 与 DevKit `1.7.0`；旧签名 Agent、业务服务身份、本地执行和公共 Component 合同继续兼容。
- 固定第三方长期 Key 不得进入模型、工作区、日志或本地助手；第三方返回的短期资源 URL 可以交给本地助手下载、加工，并把最终视频写入客户本地目录。

### 2.18 - 2026-10-30

- 固定第三方业务 API 全部由超级 Agent 侧负责，包括供应商选择、安装级凭证引用、请求参数、幂等、轮询、重试、费用和结果解释。
- 本地助手不得持有第三方长期 Key，不得创建或轮询第三方业务任务；只处理 Agent 已确定的素材、公开或短时预签名 URL、本地文件与高带宽/高算力技术任务。
- 视频、音频和其他大文件最终必须落到客户本地目录；DClaw 与 Agent 只保留产物引用、摘要和媒体事实。
- 迁移不得为了第三方 API 或凭证保存需求新增外部业务服务、域名或 HTTPS audience；只有原业务本来就有独立服务端时才能保留。
- 本次规则对旧已签名 Agent 保持向后兼容；旧 Agent 只在主动重建或发布新版本时采用新边界。

### 2.17 - 2026-10-30

- 标准和工具链更新后不再由平台统筹逐个动态通知责任会话；各责任会话在每次新建、继续或恢复工作时按项目规则自行检查唯一标准和远程版本。
- 只有更新会阻断正在进行的发布，或用户明确要求通知时，平台统筹才主动联系受影响责任会话。
- 本次只调整会话协作规则，不修改插件、DevKit、Runner、机器合同、密封格式或既有签名 Agent 的兼容性。

### 2.16 - 2026-10-30

- 开发、移植与优化 Skill 的责任范围在上传、整体授权和激活完成后结束，不再由开发会话代替项目方操作正式客户端执行真实客户验收。
- 保留六态中的 `e2e-verified`，但其默认交付状态为 `false / 待客户验收`；只有项目方自行完成并确认真实验收后才能更新为 `true`。
- 允许设置统一发布执行会话集中处理 signer、认证工具链、密封、独立验签和获授权后的上传/授权/激活；各 Agent 责任会话仍独立冻结业务源码和发布输入，并严格隔离所有发布身份、摘要、回执和回滚证据。
- 本次只调整人工开发流程与责任边界，不修改插件、DevKit、Runner、机器合同、密封格式或既有签名 Agent 的兼容性。

### 2.15 - 2026-10-29

- 新增所有超级 Agent 的公共业务骨架：按节点使用卡片采集需求，信息足够后由密封超级专家统一编排大模型、第三方 API、DClaw 公共能力和本地助手。
- 明确需求采集与执行可以交替，本地助手可以出现在中间业务节点或最终制作节点，但没有本地任务时必须保持 `none`。
- 将最终视频或其他内容制作定义为条件分支；超级专家必须基于真实产物验收，不合格时回到对应业务节点返工。
- 本次只更新人工开发规则，不修改插件、DevKit、Runner、机器合同、密封格式或既有签名 Agent 的兼容性。

### 2.14 - 2026-10-28

- 支持插件升级为 `1.13.0`，发布能力描述符 `component_exports` 显式绑定合同；非入口 Component 的模型、字典和工具路径不再依赖未公开环境变量或 Runner 私有目录。
- Runner `1.3.0` 安全解析签名 Component export 并注入 `DCLAW_COMPONENT_*` 环境变量；未声明、缺失、重复、越界和预先占用均失败关闭。
- Developer Pack 升级为 `1.7.0`、DevKit 升级为 `1.6.0`；旧能力包未声明 `component_exports` 时继续兼容。
- 新增 `audio-source-separation@1.0.0` Windows 公共 Component 的构建合同，固定 Demucs `4.0.1`、htdemucs 模型、输入锁、SBOM、许可证证据和可复现制品；只有完成 Windows 真机验证、HTTPS 上传、P-256 签名和完整 Registry 回执后才能标记为 `available`。

### 2.13 - 2026-10-28

- 增加旧 Agent 专属运行库迁移规则：先映射已有公共 Component，缺失项再补齐并注册；禁止在公共注册和 Agent 适配完成前直接删除旧运行库。
- 明确同类公共 Component 已存在时由 Agent 适配注册版本，不重复登记旧版本；Agent 私有能力包不因公共运行库合并而进入公共注册表。
- 本次规则为向后兼容的迁移门禁，公共 Component 描述符、插件、DevKit 和 Runner 合同版本保持不变。

### 2.12 - 2026-10-28

- 发布公共 Component 描述符 `1`：精确依赖闭包、正式 HTTPS artifact、大小、SHA-256、导出程序、环境路径、SBOM、许可证、缓存键与回滚版本均进入签名合同。
- 支持插件 `1.12.0` 独立提供签名注册、完整注册表、设备平台解析和 `runtime.prepare` 下发；公共 Component 管理仍只有认证 API/CLI，没有任何 DClaw 页面或核心实现。
- Runner `1.2.0` 支持 P-256 验签、安全下载、原子安装、组件导出入口及 PATH/Python 环境注入；旧能力包没有 `public_components` 声明时继续兼容。
- Developer Pack 升级为 `1.6.0`、DevKit 升级为 `1.5.0`，新增公共 Component Schema 与 `component-registry get/register` 无界面命令。

### 2.11 - 2026-10-28

- 公共 Component 管理固定为 `dclaw.super-agent-support` 插件内的版本化无界面 API/CLI，由迁移 Skill 和平台维护自动化调用。
- 禁止为公共 Component 新增 DClaw 客户端页面、管理后台页面、菜单、按钮或普通用户入口；DClaw 核心继续保持无感。
- Developer Pack 升级为 `1.5.4`、支持插件升级为 `1.11.3`，DevKit 保持 `1.4.1`；公开机器合同和旧已签名 Agent 继续有效。

### 2.10 - 2026-10-28

- 明确只供 Super Agent 使用的公共 Component 全部归属 `dclaw.super-agent-support` 插件套件，DClaw 核心不识别 Component ID、注册表、版本、制品、签名、下载或安装协议。
- 公共 Component 的公共性评审、分平台构建、许可证、SBOM、签名、HTTPS 制品上传、注册表、版本、兼容和回滚由插件负责；插件配套本地助手负责下载、验签、缓存和原子安装。
- 更正 FFmpeg、Whisper、Python Runtime 归单个 Agent 能力包管理的旧规则；Agent 只保留私有 component 并适配公共注册版本。
- Developer Pack 升级为 `1.5.3`、支持插件升级为 `1.11.2`，DevKit 保持 `1.4.1`；旧已签名 Agent 和旧公开机器合同继续有效。

### 2.9 - 2026-10-27

- Developer Pack 升级为 `1.5.2`、支持插件升级为 `1.10.2`，DevKit 保持 `1.4.1`；manifest、签名包、本地执行和业务身份公开合同不变，旧已签名 Agent 无需重建。
- 修复 `upgrade --project` 只更新 Pack/标准、遗漏 `project.json.devkit_version` 的问题；升级回执现在同时记录旧 DevKit，新项目元数据必须在升级后立即通过同一 Pack 的 `validate`。
- 新增平台统一工具链发布闭环：一次认证下载、显式版本组合、同源限制、ZIP/摘要/成员校验、临时目录原子发布、版本化只读共享目录和无凭据生产回执。
- 固化服务端/客户端双提交、目标构建主机、镜像内版本预检、正常预热窗口、自动回滚、旧 Agent 兼容回归和责任会话逐一通知门禁。
- 要求每个可重复问题同时落入机器门禁或回归测试以及唯一标准，禁止以手工修数据或口头提醒代替闭环。

### 2.8 - 2026-10-27

- 支持插件升级为 `1.10.1`、DevKit 升级为 `1.4.1`、Developer Pack 升级为 `1.5.1`，保持 manifest、签名包、本地执行和业务身份能力合同版本不变。
- 发布准确的业务身份 MCP 操作目录，固定客户端键、MCP 工具名、Streamable HTTP/JSON-RPC 调用顺序和受信运行上下文参数注入。
- 固定受控出站请求体为可省略且最多一种，拒绝 Agent `Authorization` 与大小写重复 Header，平台只发送一个 Bearer 断言，并发布接收方失败关闭夹具。
- 通过通用插件公开路由 SPI 匿名提供精确 JWK 路径，增加 ETag、缓存、限流、轮换和插件卸载隔离；核心不硬编码 Super Agent 业务路由。
- 修复 Developer Pack 对正常 POSIX `.venv/bin/python` 符号链接的误拒绝，同时验证项目虚拟环境、真实 CPython、`sys.prefix` 和目录逃逸。
- Developer Pack 与 DevKit 下载过滤 AppleDouble、Finder、字节码及 macOS 归档元数据，并以固定 ZIP 元数据保证跨构建环境可复现。
- 明确 manifest `platform_contract_versions.local_execution="1"`、本地执行合同修订 `1.1` 与 Runner 设备协议 `2` 属于不同层级。

### 2.7 - 2026-10-27

- 平台负责人正式接受并实现 `business.service.installation-identity/1`，由 `dclaw.super-agent-support` 独立拥有服务登记、安装/发布版授权、短时 Ed25519 断言、一次性 `binding_ref`、受控出站注入、在线验证、轮换、撤销、重放保护和脱敏审计。
- 支持插件最低版本升级为 `1.10.0`，DevKit 升级为 `1.4.0`，Developer Pack 升级为 `1.5.0`；公开机器合同只进入插件和 DevKit，人工规则继续只维护本文。
- 业务身份能力只检查自身 capability grant，并复用平台可信运行上下文签名；它不依赖本地执行授权，也不要求客户端或 Runner 升级。
- 保留标准 `2.6` 的 `resources.lock.json` 失败关闭和 Secret 扫描修复。

### 2.6 - 2026-10-27

- 修复 Developer Pack 在 `resources.lock.json` 仍为阻断状态、资源 URL 为空或使用 `.test`、许可证待定时仍会写出 capability artifact 和超级专家 ZIP 的失败关闭缺口。
- 规定 Developer Pack 必须在写出任何发布 artifact 前验证资源状态、正式 HTTPS 允许域、大小、SHA-256、SBOM、许可证、缓存键和回滚版本；直接 `capability-build` 与完整 `build` 使用同一门禁。
- Developer Pack 升级为 `1.4.1`，支持插件升级为 `1.9.1`；DevKit descriptor、manifest、签名与能力目录合同未变化，保持 `1.3.0`。
- 新门禁只约束新构建，不改写 descriptor/manifest 公开合同，也不影响旧已签名包运行。

### 2.5 - 2026-10-26

- 增加平台核心残留审计门禁：每项 Super Agent 相关命中必须归类为通用 SPI、共享基础设施、持久数据合同、历史兼容壳或违规专属实现，违规实现必须迁入插件。
- 将旧 `app.local_execution.session` 的会话签发与验签实现迁入 `dclaw.super-agent-support`，核心只保留旧 Python 路径转发；旧调用和旧 Token 格式继续兼容。
- 核心部署模板改用通用 `DCLAW_EXTENSION_DEFAULT_OUTPUT_TOKENS`，停止推荐已失效的核心本地会话 Secret；旧输出额度变量仍由运行时代码兼容读取。
- 增加插件缺失、插件卸载、普通 DClaw 功能独立运行和核心禁止依赖插件内部实现的自动回归要求。
- 支持插件源码升级为 `1.9.0`，Super Agent Developer Pack 源码升级为 `1.4.0`，DevKit 和现有签名包合同保持 `1.3.0` 向下兼容。
- 本次只更新源码、测试和唯一标准文档；在该版本提交时正式 ZIP 尚未生成，也未构建镜像、部署或重启服务。

### 2.4 - 2026-10-26

- 将所有只服务超级 Agent 的卡片组件、AIGC 适配、MCP/本地执行、工作区编排和 `super_expert` 包生命周期实现统一归入 `dclaw.super-agent-support` `1.8.0`；核心只保留通用插件 SPI、通用 MCP 客户端和共享 AIGC Studio 基础设施。
- 保留旧 Python 导入路径和旧 manifest 默认值作为薄兼容层；插件缺失或卸载时，专属路由、钩子、包类型和编排处理器同时移除并失败关闭，历史签名 Agent 继续按原合同运行。
- 明确 SSH 登录私钥不等于发布 signer，跨 `super_expert` 与 capability-package 信任域必须分别授权，历史 Agent signer 不自动授权新 Agent。
- 明确无应用身份下载权限或无受控 signer 时只能交付未签名构建输入，后五个发布状态必须保持 `false`。
- 补齐 Runner 核心、Agent 本地能力包和超级专家对 FFmpeg、Whisper、Python Runtime、模型、字体和媒体资源的可执行职责边界。
- 增加正式 URL、允许域、资源清单 `release_ready`、descriptor 签名、capability 信任域、工具链版本和平台部署版本的严格发布前置关系，并增加安装级业务服务身份能力 ID/Schema 门禁。
- Super Agent Developer Pack 源码升级为 `1.3.0`，继续内嵌 DevKit `1.3.0`；本次不生成正式 ZIP、不构建镜像、不部署生产环境。

### 2.3 - 2026-10-26

- Super Agent 开发包升级为 `1.2.0`，支持插件源码升级为 `1.7.0`，DevKit 升级为 `1.3.0`。
- 新增本地文件选择、不透明引用、只读任务绑定、设备直传和持久产物公开合同，密封格式不变。
- `local_task_continue` 新增可选只读 `local_file_bindings`，支持在原任务检查点安全补选本地文件；旧调用不传该字段时行为不变。
- 本地执行合同升级为向后兼容的 `1.1`，文件能力使用设备协议 `2` 和 Runner `1.1.0`；协议 `1` / Runner `1.0.0` 的无文件任务继续有效。
- 本次只完成源码、公开 Schema 和测试，不构建或部署生产镜像，不重启服务。

### 2.2 - 2026-10-26

- Super Agent 开发包升级为 `1.1.0`，支持 `capability-build.json` `schema_version=1` 声明任意安全相对文件、目录、嵌入式运行时和锁定依赖，并生成逐文件摘要清单。
- 支持导入外部确定性能力 ZIP；CLI 校验 ZIP 安全与完整性后绑定原始摘要并签名能力描述符，不要求开发方放弃已有候选构建器。
- `project.json.tests` 新增受控 `unittest`/`pytest` 适配器；发布证据记录规范化命令和真实执行数量，完整 pytest 套件不会被一项兼容 unittest 替代。
- 支持插件源码升级为 `1.6.0`；DevKit 和密封格式保持 `1.2.0`，旧开发包、旧构建默认值和已签名 Agent 继续按原合同有效。
- 本次只完成源码、公开 Schema、测试和开发包产物，不构建或部署生产镜像，不重启服务。

### 2.1 - 2026-10-26

- 新增 DClaw 超级 Agent 开发包 `1.0.0`，把唯一标准、DevKit `1.2.0`、公开 SDK/Schema、模板、夹具、SBOM、许可证和离线演练组合为一个版本化交付物。
- 新增 `doctor`、`init`、`validate`、`test`、`build`、`upgrade` 和 `demo` 统一命令；`build` 强制执行行为基线、差异批准、Schema、能力、依赖、Secret、测试、密封和验签门禁。
- 新增开发包认证元数据和稳定下载接口；独立 DevKit 接口继续保留，旧 Agent 和 DevKit `1.2.x` 签名格式不变。
- 明确开发包、标准和 DevKit 各自独立版本，版本只能来自元数据与包清单，不得根据稳定路径或保留文件名猜测。
- 支持插件源码递增为 `1.5.0`；当前仅完成本地源码和测试，未构建或部署生产镜像，生产仍为插件 `1.4.0`。
- 本次只增加向后兼容的交付与校验工具，不改变职责边界、现有机器合同或旧签名包含义，按第 30 节递增 minor。

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
