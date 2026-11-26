# 密封 Agent 统一普通运行链路设计

## 决策摘要

DClaw 中所有 Agent，无论是普通 Agent 还是密封 Agent，在激活后的网页会话和 OpenAPI 调用中都必须使用同一套普通 Agent 工作区、Runner、模型、工具、Skill、MCP、知识库、会话、计费和响应机制。

“密封”今后只是一项发布与管理属性：它继续保护签名包、版本、管理页面和源码访问权限，但不再提供独立进程、文件隔离、工具裁剪或特殊模型调用。准确地说，这是“控制面密封、运行面统一”，不是运行时安全沙箱。

该决策适用于现在和未来的全部密封 Agent，不按 Agent ID、发布版本、调用渠道或 OpenAPI publication 单独配置。

## 最高约束

1. 密封不得改变 Agent 的运行能力。
2. 密封 Agent 与普通 Agent 的在线执行链路必须一致。
3. 网页会话和 OpenAPI 必须进入同一执行链路。
4. 管理页面、签名发布、版本记录、源码隐藏和下载限制保持不变。
5. 普通 Agent 的现有行为、数据和管理流程不得因本次改造发生变化。
6. 密封 Agent 安装或运行失败只能影响该密封 Agent。

## 设计取代关系

本设计取代此前关于 Runtime Adapter、密封 Harness 子进程、
`sealed_entrypoint/1`、Worker、HostBridge、`/release` 与 `/session` 隔离的两份
试验性方案。旧方案已从当前文档集删除，需要审计时可从 Git 历史查阅。

本设计同时取代 `2026-08-26-sealed-global-agents-design.md` 中关于运行时文件隔离、
默认禁用 Shell、密封专用输出策略和密封专用 OpenAPI 执行策略的部分。

以下既有设计继续有效：

- 密封 Agent 的签名包、版本、摘要和发布记录；
- 密封 Agent 管理页面及其权限模型；
- 禁止通过 DClaw UI 或管理 API 查看、编辑、克隆、导出或下载内部资产；
- OpenAPI API Key、publication、配额、计费和会话绑定；
- 普通 Agent 的现有工作区与调用流程。

若旧文档与本设计冲突，以本设计为准。

## 目标

- 让所有密封 Agent 获得与普通 Agent 完全相同的文件、脚本、Skill、MCP、知识库和模型能力。
- 删除密封 Agent 在线调用对 `sealed_entrypoint`、Worker、HostBridge 和专用协议的依赖。
- 让密封 Agent 的网页会话和 OpenAPI 复用普通 Agent 的现有实现，而不是维护兼容适配层。
- 已激活的密封 Agent 在 DClaw 升级后自动生成普通工作区，不要求重新上传发布包或再次激活。
- 在切换前通过普通/密封对照测试和真实发布包多轮测试证明能力一致。

## 非目标

- 不保证模型无法读取、概括或输出其运行工作区中的规则和 Skill。
- 不通过运行时沙箱防止提示注入或源码套取。
- 不迁移旧 `sealed_sessions` 中的业务状态或临时文件。
- 不修改具体 Agent 的业务规则、Controller、Harness、状态机或 Skill 内容。
- 不改变普通 Agent 的功能、工具权限或 OpenAPI 协议。
- 不重新设计密封 Agent 管理页面。

## 安全语义变化

改造后的“密封”提供应用层访问控制，不提供运行时隔离：

### 继续保证

- 客户、租户管理员和 DClaw 管理员不能通过产品 UI 或应用 API 查看密封 Agent 工作区、源码、Skill、配置、发布包或文件列表。
- 密封发布包继续要求签名、摘要校验和版本校验。
- 密封 Agent 继续禁止在线编辑、克隆、导出和下载。
- 后端权限判断仍是实际边界，前端隐藏不作为唯一安全措施。

### 不再保证

- 模型运行时与源码之间不存在文件系统隔离。
- 密封 Agent 不具备比普通 Agent 更严格的 Shell、文件、工具或网络限制。
- DClaw 不再通过独立 Worker 阻止模型访问工作区内部文件。
- DClaw 不再承诺通过平台运行时阻止用户在对话中诱导 Agent 复述内部内容。

具体 Agent 仍可在自身规则中拒绝源码索取，但这属于 Agent 行为，不属于强隔离安全边界。

## 推荐架构

采用“控制面密封、运行面统一”的单执行器架构。

```text
签名发布包
  -> 密封发布校验与版本管理
  -> 使用普通 Agent 安装机制生成标准工作区
  -> 原子绑定当前激活工作区

网页会话 / OpenAPI
  -> 现有目标与权限解析
  -> 得到普通工作区 Agent ID
  -> 现有普通 Agent Runner
  -> 现有模型、工具、Skill、MCP、知识库、会话和计费
  -> 现有响应流
```

目标解析完成后，不再存在密封运行分支。密封属性只在调用前决定“该 Agent 是否可调用”和“哪个已激活版本对应哪个标准工作区”，不改变 Runner 的执行方式。

## 控制面职责

密封 Agent 模块继续负责：

- 上传和保存签名发布包；
- 校验 Manifest、签名、摘要、Agent ID 和版本策略；
- 保存 release、active release、enabled 和运行可用状态；
- 向管理页面提供公开信息、版本和健康状态；
- 拒绝工作区查看、Skill 查看、编辑、克隆、导出和下载接口；
- 在激活前调用普通 Agent 安装器生成候选工作区；
- 只有候选工作区通过普通 Agent 启动校验后才原子切换。

密封 Agent 模块不再负责：

- 在线模型执行；
- Controller 或 Harness 编排；
- Skill 调度；
- Host Capability；
- 密封专用会话目录；
- 密封专用回复过滤；
- 密封专用 Debug 注入；
- 文件、Shell、MCP 或工具裁剪。

## 标准工作区安装

### 工作区格式

密封发布包中的 `agent/` 必须是一个可由现有普通 Agent 加载的标准工作区。未来密封包即使保留 `runtime.adapter`、`runtime.contract_version` 或 `entrypoint` 字段，这些字段也只作为历史发布元数据，不再选择在线执行器。

不满足普通 Agent 工作区要求的密封发布包不能激活。校验错误必须明确归类为标准工作区安装或启动失败，不能回退到 `sealed_entrypoint`。

### 安装与激活

1. 密封发布流程完成签名、摘要和包结构校验。
2. 使用普通 Agent 已有安装机制将 `agent/` 安装到候选标准工作区。
3. 使用普通 Agent 已有配置加载与启动检查验证候选工作区。
4. 验证通过后，原子切换该密封 Agent 的当前运行工作区绑定。
5. 新调用使用新工作区；已经开始的调用继续完成，不在中途切换。
6. 安装或启动失败时保留上一个可运行工作区，并将失败限制在该密封 Agent。

候选目录、切换方式、工作区文件读写和持久化全部复用普通 Agent 机制，不再设计密封专用文件布局。

### 已激活发布迁移

DClaw 首次启动统一运行版本时，对每个 enabled 且存在 active release 的密封 Agent 执行幂等 reconciliation：

- 已存在且摘要匹配的标准工作区直接复用；
- 缺失或摘要不匹配时，从当前 active release 重新安装标准工作区；
- 单个 Agent 安装失败只标记该 Agent 运行不可用，不阻塞 DClaw 启动或普通 Agent；
- reconciliation 不要求管理员重新上传、重新签名或重新点击激活。

## 在线调用链路

### 网页会话

网页端完成现有权限和 Agent 可用性判断后，直接把密封 Agent ID 交给普通 Runner。后续工作区加载、模型选择、工具注册、Skill、MCP、知识库、消息历史、状态保存和输出流全部使用普通 Agent 实现。

### OpenAPI

OpenAPI 继续根据 API Key 和 publication 在服务端固定目标 Agent、所有者、外部用户和外部会话。目标解析完成后，密封 Agent 与普通 Agent 使用相同的 console/Runner 调用路径。

调用方不能通过请求正文、metadata、Header 或 session ID 改变 Agent、工作区、发布版本或密封管理权限。该限制属于现有 OpenAPI 权限模型，与运行时密封无关。

### 禁止的在线分支

任何网页或 OpenAPI 请求都不得：

- 构造 `SealedEntrypointProcess`；
- 启动 `entrypoint_worker.py`；
- 调用 `sealed_entrypoint/1`、`sealed_harness/1` 或 HostBridge；
- 创建新的 `sealed_sessions` 目录；
- 因 Agent 为 sealed 而修改模型消息角色、工具列表、Skill 列表或响应格式；
- 在普通 Runner 失败后回退到密封专用执行器。

## Agent 内部业务控制

具体 Agent 的 Controller、Harness、状态机、Gate、防自动补全和 Skill 规则继续保存在它自己的标准工作区中，并按照普通 Agent 的方式运行。

DClaw 不再为这些业务控制提供密封专用可信入口，也不保证模型一定执行某个 Agent 内部脚本。其可靠性与普通 Agent 中相同规则的可靠性一致。若某个 Agent 需要比普通 Agent 更强的确定性控制，应通过适用于普通和密封 Agent 的通用能力另行设计，不能重新引入只服务密封 Agent 的调用链路。

## 会话和状态

- DClaw 聊天记录、消息记录、OpenAPI session mapping 和数据库会话状态继续使用普通 Agent 机制。
- Agent 工作区内的状态、记忆和产物按普通 Agent 规则持久化。
- 旧 `/app/working/sealed_sessions` 不再读取，也不自动迁移。
- 旧密封会话目录暂时保留且不自动删除，供必要时检查或手工恢复。
- 切换后的新业务状态从标准工作区开始建立。
- 不同会话的隔离强度与普通 Agent 完全一致，不额外增加密封专用隔离。

## 兼容策略

- 所有密封 Agent 全量切换，不设置 Agent 白名单或逐 Agent 运行开关。
- schema v1、schema v2、`standard/1`、`sealed_harness/1` 和 `sealed_entrypoint/1` 发布记录都可继续展示和审计。
- Runtime Adapter 字段不再参与运行时分支选择。
- 现有 active release 在服务启动时自动安装成标准工作区。
- 当前陆羽 2.1.0 不需要重新生成、重新签名或重新上传，前提是包内 `agent/` 能通过普通工作区校验。
- 不提供失败后回退密封专用链路的兼容行为。
- 普通 Agent 不执行 release reconciliation，不读取密封发布包，也不依赖密封 Agent 是否存在。

## 普通 Agent 隔离

代码可能在共享目标解析入口增加一个受严格条件保护的密封工作区解析步骤，但普通 Agent 的执行对象和执行方法保持不变。

必须满足：

- 普通 Agent 不读取密封 Registry 或 release 文件；
- 普通 Agent 不创建候选工作区或执行 reconciliation；
- 普通 Agent 继续使用原 Agent ID、工作区、`QwenPawAgent` 参数和 `agent(msgs)` 方式；
- 普通 Agent 的工具、MCP、Skill、会话、流式输出、计费和错误映射不变；
- 一个密封 Agent 的安装、启动或调用失败不能改变普通 Agent 的可用性；
- 普通 Agent 的现有自动化测试必须全部通过。

## 错误处理与回滚

### 发布与激活错误

- 签名、摘要、包结构、版本或标准工作区校验失败时，新 release 不得激活。
- 新工作区准备完成前不得修改当前运行绑定。
- 失败只记录 release ID、Agent ID、阶段和稳定错误码，不向客户返回源码或路径。

### 启动 reconciliation 错误

- 单个密封 Agent reconciliation 失败时将该 Agent 标记为 unavailable。
- DClaw、普通 Agent、其他密封 Agent 和无关 OpenAPI publication 继续运行。
- 不自动改写 active release，不回退到密封专用执行器。

### 在线调用错误

- 密封 Agent 使用普通 Agent 的错误类型、SSE 终态、计费终态和重试语义。
- 不再把普通运行错误统一包装成 `sealed_agent_failed`；只在目标不可安装或不可用时返回密封管理层的稳定可用性错误。
- 运行时错误必须保留现有 invocation ID，便于按普通 Agent 日志定位。

### 回滚

- 激活失败时继续使用上一可运行工作区。
- 已经成功切换后，如需回滚，重新选择一个已验证 release并按相同普通工作区安装流程原子切换。
- DClaw 服务版本仍可通过现有镜像部署机制回滚；运行时不保留隐藏的双执行路径。

## 可观测性

密封 Agent 使用普通 Agent 的日志、调用审计、模型用量、工具记录、SSE 和错误关联方式。管理页面仍只显示经过授权的运行状态与版本信息，不展示内部日志正文。

建议在内部审计中附加 `agent_type=sealed`、`release_id`、`release_version` 和 `content_digest`，用于确认调用使用的发布身份；这些字段不改变执行器，也不进入客户回复。

## 测试策略

### 普通 Agent 零影响回归

- 全部现有普通 Agent 单元、集成和 OpenAPI 测试通过。
- 使用会抛错的密封 Registry 假实现证明普通 Agent 调用不会访问密封 Registry。
- 对比改造前后普通 Agent 的工作区路径、Runner 创建参数、工具列表、Skill、MCP、会话键、SSE 和计费终态。
- 普通 Agent 不创建 `sealed_sessions` 或密封 release 工作区。

### 普通/密封能力对照

将同一测试工作区分别作为普通 Agent 和签名密封 Agent 安装，运行相同确定性用例，验证两者均能：

- 读取和修改工作区文件；
- 执行本地脚本；
- 加载并调用 Skill；
- 使用 MCP、企业知识库和其他已配置工具；
- 保存并恢复会话状态；
- 从网页会话和 OpenAPI 调用；
- 返回相同的响应事件类型、错误协议和计费终态。

自然语言结果不要求逐字一致；比较对象是 Runner 路径、工作区、配置、能力、状态副作用和协议。

### 密封管理回归

- 有效和无效签名、摘要、版本与包结构校验保持有效。
- 管理页面继续显示密封 Agent、版本、状态和激活动作。
- UI 和 API 继续拒绝查看、编辑、克隆、导出和下载密封内部资产。
- 已激活 release 可在服务启动时幂等生成标准工作区。
- 候选工作区失败时不覆盖上一可运行工作区。
- 一个密封 Agent 失败不影响普通 Agent 或其他密封 Agent。

### 在线路径否定测试

- 网页调用密封 Agent 时，密封 Worker、HostBridge 和 Adapter 构造器均不被调用。
- OpenAPI 调用密封 Agent 时，密封 Worker、HostBridge 和 Adapter 构造器均不被调用。
- `runtime.adapter` 的不同历史值不改变 Runner 路径。
- 运行失败不回退到任何密封专用执行器。

### 陆羽 2.1.0 真实发布包验收

使用当前签名发布包，而不是测试替身，完成至少以下连续用例：

1. 新 OpenAPI 会话发送“陆羽你好”，得到正常自然语言开场和成功计费终态。
2. 连续提供业务、目标和现状，验证状态能够跨轮恢复。
3. 验证 Agent 能读取规则、执行脚本、调用主 Skill 和支撑 Skill。
4. 验证 Harness 与 Gate 按陆羽普通 Agent 规则运行，并记录阶段、revision、Skill 和恢复动作。
5. 验证前向阶段不会跨级，失败时不会伪造 PASS 或写入错误状态。
6. 使用第二个全新外部会话验证状态隔离。
7. 验证普通客户回复不显示 JSON 外壳、内部日志或调试字段。

如果陆羽 2.1.0 的 `agent/` 不能作为普通工作区运行，必须在部署 DClaw 前报告兼容缺口；不能在生产部署后逐层试错。

## 部署门槛

以下全部完成前不得要求生产部署：

1. 服务端普通 Agent 全量回归通过；
2. 密封管理、签名和权限回归通过；
3. 普通/密封能力对照测试通过；
4. 网页与 OpenAPI 在线路径否定测试通过；
5. 当前陆羽 2.1.0 真实发布包本地连续多轮验收通过；
6. 工作区 reconciliation 在空 Registry、单 Agent、多 Agent、单 Agent 失败时均通过；
7. 变更文件经过范围审查，普通 Agent 不存在行为差异；
8. 只生成一个合并提交和一次明确的部署说明。

## 完成定义

- 所有普通与密封 Agent 的网页会话和 OpenAPI 调用都使用同一个普通 Runner。
- 密封 Agent 具备普通 Agent 的全部运行能力和相同工作区管理方式。
- 在线调用不再使用 `sealed_entrypoint`、Worker、HostBridge、密封专用消息或工具裁剪。
- 密封管理页面、签名发布、版本记录、源码隐藏和下载限制保持有效。
- 普通 Agent 的功能、数据、调用协议和性能路径不变。
- 旧密封会话目录不迁移、不删除、不再参与运行。
- 一个密封 Agent 的失败不会影响 DClaw、普通 Agent 或其他密封 Agent。
- 全部自动化、能力对照和陆羽真实发布包验收通过后才允许部署。
