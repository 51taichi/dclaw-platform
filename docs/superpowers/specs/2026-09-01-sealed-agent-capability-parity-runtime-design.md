# 密封 Agent 能力等价运行时设计

## 目标

DClaw 为密封 Agent 提供一个通用、稳定、与具体 Agent 业务无关的运行协议。密封只能阻止模型或外部用户读取发布包源码，不能削弱 Agent 自身执行代码、读取规则、调用工具、持久化状态、输出日志或诊断的能力。

最高约束：如果密封运行方式造成任何可确认的既有能力损失、业务行为缺失或运行限制，则该密封版本不得激活，应继续使用非密封运行方式。

## 范围

本次只修改 DClaw 的密封 Agent 基础设施和密封专项测试。

不修改：

- 非密封 Agent 的 Runner 分支、工具列表、提示词加载、会话协议和输出行为；
- 未声明新运行协议的旧密封 Agent；
- 任何具体 Agent 的业务阶段、Skill、状态机或证据规则；
- `luyu-traffic-operator-agent` 以及其他 Agent 工作区。

## 现状问题

当前 `sealed_harness` 由 DClaw 依次调用 `prepare_interaction`、`controller_gate`、`required_skill_dispatch`、`completion_validation`、`commit` 和 `render_bound`，并识别 `luyu_debug`。这使平台运行时理解了具体 Agent 的内部结构。

该设计产生四类问题：

1. Agent 调整内部阶段后可能要求修改 DClaw；
2. 模型工具权限和 Agent 可信代码权限被混为一谈；
3. 当前 Harness 使用临时会话目录，可信代码状态无法按真实会话稳定持久化；
4. 中间模型消息可能被当作多个客户可见回复发布。

## 方案比较

### 方案 A：恢复模型的 Shell 和源码文件工具

优点是实现最少。缺点是模型可能在提示注入下读取并输出发布包源码，违背密封目标。本方案不采用。

### 方案 B：DClaw 继续编排通用生命周期阶段

可以把阶段名称改得更抽象，但平台仍需理解 Agent 内部生命周期，后续协议演进仍会造成耦合。本方案不采用。

### 方案 C：密封包单入口 + Host Capability RPC

DClaw 只调用密封包唯一入口。Agent 在隔离进程内部自行执行 Controller、状态机、Skill 和校验；需要模型或平台能力时，通过通用 RPC 请求宿主执行。DClaw 不理解 Agent 内部业务结构。

本设计采用方案 C。

## 架构边界

### DClaw 负责

- OpenAPI 和控制台鉴权；
- 会话标识和发布版本固定；
- 计费、超时、取消和审计；
- 启动隔离的密封运行进程；
- 提供经过白名单授权的 Host Capability；
- 校验密封运行时的最终响应；
- 只发布一个最终客户可见回复；
- 在获得可信授权时单独返回诊断信息。

### 密封包负责

- Controller、状态机和阶段 Gate；
- Skill 选择与业务规则；
- 证据登记和防自动补全；
- 读取自身规则、配置、Skill 和资源；
- 会话业务状态的读写；
- 模型执行前后的全部业务校验；
- 最终客户回复和 Agent 自定义 diagnostics；
- 业务日志和可审计决策记录。

### 大模型边界

大模型不能获得读取 `/release` 的文件工具，也不能对 `/release` 执行 Shell。该限制只约束模型工具面，不约束密封包可信入口。

## Manifest

新协议由密封包 Manifest 显式声明，不按 `agent_id` 判断：

```json
{
  "schema_version": 2,
  "entrypoint": "agent/runtime.py",
  "runtime": {
    "adapter": "sealed_entrypoint",
    "contract_version": "1",
    "failure_policy": "fail_closed"
  }
}
```

未声明 `sealed_entrypoint` 的发布包保持原运行方式。

## 进程与文件系统隔离

可信入口运行在独立进程中：

- `/release`：当前固定发布包，只读；
- `/session`：按 `agent_id + session_id` 隔离，可读写并持久化；
- `/tmp`：单次进程临时目录；
- 默认无网络；
- 只能通过标准输入输出使用协议消息，不允许把任意标准错误内容返回客户；
- 继承受限环境变量、文件描述符、CPU、内存和总超时限制。

可信入口可以读取并执行 `/release` 中的代码和资源。大模型没有对应文件句柄或工具。

## 通信协议

通信采用有界 JSON Lines。所有消息包含 `protocol_version`、`invocation_id` 和唯一消息 ID。

### DClaw 发起调用

```json
{
  "type": "runtime.invoke",
  "protocol_version": "1",
  "invocation_id": "inv-123",
  "message_id": "msg-1",
  "release": {
    "release_id": "release-1",
    "version": "1.1.0",
    "content_digest": "sha256:..."
  },
  "session": {
    "conversation_id": "open:app:publication:user:session",
    "user_id": "bound-user",
    "channel": "open:app"
  },
  "input": {
    "role": "user",
    "content": "用户消息",
    "attachments": []
  },
  "metadata": {},
  "history": [],
  "runtime": {
    "diagnostics_authorized": false,
    "capabilities": ["agent.execute"]
  }
}
```

调用者传入的 metadata 必须保持不受信任；发布版本、授权状态、Agent ID 和会话身份必须由服务端可信上下文生成。

### 密封包请求宿主能力

```json
{
  "type": "host.call",
  "protocol_version": "1",
  "invocation_id": "inv-123",
  "call_id": "call-1",
  "capability": "agent.execute",
  "arguments": {
    "messages": [],
    "instruction": "由密封包生成的受控执行指令"
  }
}
```

DClaw 验证 capability 已由服务端白名单和发布包声明共同授权，然后返回：

```json
{
  "type": "host.result",
  "protocol_version": "1",
  "invocation_id": "inv-123",
  "call_id": "call-1",
  "ok": true,
  "result": {}
}
```

合同版本 1 至少支持 `agent.execute`。它调用 DClaw 已有 AgentScope 模型与工具循环，从而保留模型、知识库、Wiki、网页、时间等现有能力。未来新增 capability 必须通过新的平台版本实现，但具体 Agent 的业务迭代不得要求新增平台代码。

### 密封包返回最终结果

```json
{
  "type": "runtime.final",
  "protocol_version": "1",
  "invocation_id": "inv-123",
  "message_id": "msg-final",
  "reply": "唯一客户可见回复",
  "artifacts": [],
  "diagnostics": null
}
```

一次 invocation 只能接受一个 `runtime.final`。模型草稿、工具结果、Controller 中间状态和其他协议消息不得进入客户流。

## Host Capability

合同版本 1 必须提供：

- `agent.execute`：执行现有 DClaw 模型和工具循环，并把结构化消息结果返回密封入口。

该能力必须保持密封 Agent 原本可用的知识库、Wiki、网页、时间和模型工具。发布包源码读取与任意 Shell 不属于 Host Capability；可信入口已经可以直接运行自身发布包代码。

能力注册表必须是通用平台注册表，不能出现陆羽阶段、Skill 或 Debug 字段。

## Diagnostics

平台只认识通用的 `diagnostics_authorized`，不认识 `luyu_debug` 或其他 Agent 专属开关。

- 授权来自服务端 API Key scope 或管理员调试接口；
- 用户正文和不受信任 metadata 不能授予诊断权限；
- 密封包可以使用自己的 metadata 约定决定是否生成 diagnostics，但 DClaw 只有在可信授权为真时才向调用方返回；
- 普通客户流永远只包含 `reply`；
- diagnostics 的内部 Schema 由密封包定义，DClaw 只做大小、JSON 类型和敏感输出边界校验。

## 版本与审计

每次 invocation 固定：

- `release_id`；
- `version`；
- `content_digest`；
- `adapter`；
- `contract_version`。

这些字段写入调用审计。管理员接口和获得诊断权限的接口可以查看，普通客户回复不展示。

正在执行的 invocation 不因后台激活新版本而切换发布包。

## 错误处理

- Manifest 未声明受支持协议：拒绝激活新协议，旧运行路径不受影响；
- 入口不存在、协议消息无效、越权 Host Capability、超时或进程退出：`fail_closed`；
- 运行失败不得回退到普通模型路径，避免绕过 Agent Controller；
- 对外只返回稳定错误码，不返回路径、源码、stderr 或内部堆栈；
- 失败调用保留 release 身份、阶段类型、错误码和 invocation ID 供后台审计。

## 非密封 Agent 隔离

Runner 必须先按现有 `sealed_runtime` 判断。只有当前 invocation 已固定到声明 `sealed_entrypoint/1` 的密封发布包时，才加载新协议实现。

禁止修改非密封 Agent 的：

- `QwenPawAgent` 创建参数；
- 工具注册和工具权限；
- `agent(msgs)` 调用方式；
- SSE 和非流式响应内容；
- 会话状态和计费行为。

专项测试必须通过一个会抛错的假密封 Adapter 证明：非密封 Agent 调用时该 Adapter 从未被解析、构造或执行。

## 兼容和迁移

- 保留 `standard/1` 和现有 `sealed_harness/1` 作为旧发布包兼容路径；
- 新发布包使用 `sealed_entrypoint/1`；
- 只有重新打包并显式声明新协议的 Agent 才迁移；
- 新协议通过验收前不得激活到生产；
- Agent 后续升级只上传并激活新密封包，不修改 DClaw；
- 协议自身确需新增宿主能力时，必须升级合同版本并保持旧版本兼容。

## 验收测试

### DClaw 自动化测试

1. 非密封 Agent 不解析、不构造、不执行密封入口；
2. 非密封 Agent 的模型、工具、会话和输出回归测试保持通过；
3. `standard/1` 和 `sealed_harness/1` 旧发布包保持现状；
4. `sealed_entrypoint/1` 能读取并执行只读发布包代码；
5. `/session` 跨同一会话的多次 invocation 持久化，不同会话相互隔离；
6. 密封入口可以调用授权的 `agent.execute`；
7. 未授权 capability 被拒绝且不执行宿主函数；
8. 模型没有 `/release` 的文件读取和 Shell 能力；
9. 一个 invocation 只能产生一个最终 reply；
10. 中间消息、模型草稿和 diagnostics 不进入普通客户流；
11. 只有可信诊断授权可以返回 diagnostics；
12. 入口失败时不回退普通模型；
13. invocation 固定版本，不受并发激活新版本影响；
14. 版本、摘要、Adapter 和合同版本进入后台审计。

### 能力等价验收

迁移某个 Agent 前，必须在非密封和新密封环境执行同一套确定性契约用例，逐项比较：

- Controller 和状态 Gate；
- Skill 路由；
- 本地规则与资源读取；
- 会话状态持久化；
- 模型和所有授权工具；
- 日志与 diagnostics；
- 最终输出协议；
- 异常和恢复逻辑。

任何一项缺失即阻止激活。由于自然语言模型输出存在随机性，比较对象是功能、状态迁移、工具可达性和结构化约束，不要求逐字一致。

## 完成定义

以下条件全部满足才算完成：

- DClaw 不再需要了解任何具体 Agent 的阶段、Skill 或 Debug 字段；
- 密封包可信代码拥有完成自身业务所需的全部本地执行能力；
- 模型仍不能读取或导出发布包源码；
- 非密封 Agent 和旧密封 Agent 的行为不变；
- 一个调用只返回一个最终客户回复；
- 普通调用不返回 diagnostics，授权调用可以返回；
- Agent 的后续业务版本升级不需要修改 DClaw；
- 全部密封专项测试和普通 Agent 回归测试通过。
