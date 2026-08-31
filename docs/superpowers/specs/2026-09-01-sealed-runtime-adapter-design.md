# 通用密封 Agent Runtime Adapter 设计

## 背景

DClaw 当前能够安装、校验和激活密封 Agent release，但实际执行仍统一进入普通 `agent(msgs)` 链路。密封包 manifest 的 `entrypoint` 只校验文件存在，没有运行时协议负责调用包内 Controller、Gate、提交或输出约束逻辑。

OpenAPI 会将调用方提供的 `payload.metadata` 保存为 `channel_meta["metadata"]`，Runner 构造请求上下文时却没有传递完整 metadata。依赖该字段的调试或交互参数因此会丢失。

本设计引入通用 Runtime Adapter。DClaw 不识别任何具体 Agent ID 或业务版本；密封 release 通过已签名 manifest 声明受支持的运行时协议，由服务端白名单 Adapter 执行。

## 目标

- 不硬编码 `luyu_traffic_operator` 或任何密封 Agent ID。
- 不硬编码陆羽 `1.1.0`、`2.0.4` 等业务版本。
- 将完整且经过复制隔离的 `channel_meta.metadata` 传入请求上下文。
- 允许密封 Agent 声明必须执行的 Controller/Harness 生命周期。
- 模型回复后强制执行 commit 和 render-bound。
- 调试标志只控制诊断结果是否返回，不控制 Adapter 或 Controller 是否运行。
- 不向密封 Agent 模型开放 shell、文件读取、Python 沙箱或任意插件工具。
- 未声明 Adapter 的现有密封 Agent和普通 Agent保持原运行链路。
- 每次请求固定使用开始时的 release，避免激活切换导致一次请求混用两个版本。

## 非目标

- 不允许密封包通过 manifest 指定任意 Python 模块、类名、命令或宿主机可执行文件。
- 不把危险工具重新加入密封 Agent 的模型工具箱。
- 不让请求 metadata 选择 Adapter、协议版本、release 或安全策略。
- 不在本阶段改变普通 Agent、专家团、计费或 OpenAPI 鉴权语义。

## Manifest 协议

密封包 manifest 增加可选 `runtime`：

```json
{
  "schema_version": 2,
  "agent_id": "example_sealed_agent",
  "version": "3.7.1",
  "entrypoint": "agent/runtime.py",
  "runtime": {
    "adapter": "sealed_harness",
    "contract_version": "1",
    "failure_policy": "fail_closed"
  }
}
```

字段语义：

- `adapter`：服务端受信 Adapter 类型，不能是模块路径。
- `contract_version`：宿主与密封运行时之间的接口版本，与 Agent 业务版本独立。
- `failure_policy`：Harness 类型只允许 `fail_closed`。
- `entrypoint`：密封包内受 digest 和签名保护的入口文件；其执行方式由对应 Adapter 决定。

兼容策略：

- schema v1 或没有 `runtime`：继续当前标准密封 Agent 链路。
- `adapter=standard`：继续当前标准密封 Agent 链路。
- 声明受支持 Adapter：激活前完成协议验证，运行时执行对应生命周期。
- 声明未知 Adapter、未知 contract 或非法 failure policy：拒绝激活。

## 服务端 Adapter Registry

DClaw 维护静态、经过代码审查的 Adapter Registry：

```python
ADAPTERS = {
    ("standard", "1"): StandardSealedAgentAdapter,
    ("sealed_harness", "1"): SealedHarnessAdapterV1,
}
```

Registry 只接受固定枚举键。密封包不能注册新的宿主实现，也不能覆盖已有实现。未来新增协议必须通过 DClaw 代码发布。

## 请求路由与 release 固定

Runner 在创建 Agent 之后、开始执行之前解析运行时：

1. 根据服务端已选定的可信 `agent_id` 查询密封 Registry。
2. 若不是密封 Agent，返回标准执行器。
3. 读取当前 `active_release_id` 和 release 记录。
4. 校验 enabled、release 状态、manifest、签名状态和 content digest。
5. 将 `release_id`、`version`、`content_digest`、`entrypoint`、Adapter 契约固定到本次请求对象。
6. 请求结束前不重新读取 active release。

激活发生在请求中途时，正在运行的请求继续使用旧 release；后续请求使用新 release。

## 请求上下文

Runner 在 `base_request_context` 中加入深复制后的 metadata：

```python
base_request_context["metadata"] = deepcopy(
    channel_meta.get("metadata") or {}
)
```

约束：

- metadata 必须是 JSON 对象并受尺寸、层级和键数量限制。
- 禁止覆盖 `agent_id`、`user_id`、`session_id`、`release_id`、Adapter 类型等服务端字段。
- Adapter 获取两个逻辑区域：可信宿主上下文与不可信调用 metadata，不能混为同一字典。
- `luyu_debug` 等调试字段属于不可信 metadata，仅影响允许暴露的诊断结果。

## Adapter 生命周期

通用 Harness 生命周期为：

```text
prepare_interaction
  → controller_gate
  → required_skill_dispatch
  → model_execution
  → completion_validation
  → commit
  → render_bound
```

接口以结构化 DTO 交互：

- `prepare_interaction`：规范化输入并产生不可变交互对象。
- `controller_gate`：决定允许继续、拒绝或要求一个明确 Skill 操作。
- `required_skill_dispatch`：由宿主执行 Adapter 协议允许的语义能力，不依赖模型自行选择。
- `model_execution`：使用现有模型、计费和流式基础设施。
- `completion_validation`：检查模型是否出现未经 Controller 允许的自动补全或缺失动作。
- `commit`：提交 Harness 状态；失败不得返回未提交结果。
- `render_bound`：将已提交结果转换为对外响应，并应用输出边界。

Controller 与 commit 在非调试请求中同样必须执行。调试只决定是否将经过脱敏的阶段结果附加到测试接口响应。

## 执行隔离

Harness entrypoint 不直接 import 到 Web 主进程。`sealed_harness` Adapter 在受控子进程中执行，至少满足：

- release 目录只读；会话目录独立可写。
- 使用固定解释器和固定启动参数，不经过 shell。
- 清理继承环境变量，不传数据库、Redis、供应商密钥或主服务令牌。
- 默认无网络；协议需要的外部能力通过宿主窄接口请求。
- 请求/响应使用有大小限制的 JSON 消息协议。
- 设置启动、阶段和总执行超时；限制内存、CPU、进程数和输出大小。
- 子进程不能向宿主请求任意工具名，只能请求 Adapter contract 明确定义的能力枚举。

密封 Agent 的模型工具策略保持不变：继续禁止 `execute_shell_command`、`read_file`、`python_sandbox` 和所有未允许插件工具。

## 输出、流式与失败语义

Harness 未完成 commit 和 render-bound 前，不向最终用户发送不可撤回的内容。可发送通用进度事件，但不能泄漏模型草稿或 Controller 内部状态。

失败处理：

- prepare、Controller、Skill、校验、commit 或 render 任一阶段失败：明确返回结构化运行时错误。
- 已声明 Harness 的 Agent 禁止回退到普通 `agent(msgs)`。
- 子进程超时、崩溃、协议违规或 digest 不一致：封闭失败并记录安全审计。
- 调试结果必须脱敏，且只在受信测试接口和 `metadata.debug=true` 同时满足时返回。
- 普通生产 OpenAPI 不因调用方传入 debug 字段而泄漏内部结果。

## 激活验证

上传阶段继续完成包路径、签名和 digest 校验。激活阶段新增：

- Adapter 和 contract 受支持。
- entrypoint 满足 Adapter 对文件类型和位置的限制。
- 在隔离环境执行 handshake，返回正确 contract 与必要阶段能力。
- manifest 声明阶段与 handshake 一致。
- 验证失败时保留旧 active release，不产生部分激活状态。

管理接口继续返回：

- `active_release_id`
- `version`
- `content_digest`
- `runtime.adapter`
- `runtime.contract_version`
- 最近一次运行时验证结果与时间

## 计费与幂等

- Adapter 复用现有请求级计费订单和模型调用计量器。
- Controller/Harness 本身不直接修改钱包。
- 每次模型调用仍由宿主 ModelMeter 记录，不能由密封包自行上报积分。
- release identity 写入请求和计费审计快照，便于定位不同 release 的消费与行为。
- OpenAPI 幂等重放返回原终态，不重新运行 Harness。

## 可观测性与审计

每次 Adapter 请求记录：

- agent ID、release ID、业务版本、content digest。
- Adapter 类型、contract 版本。
- 各阶段开始、完成、耗时与失败代码。
- 是否请求调试结果、是否允许返回调试结果。
- 子进程退出状态和资源限制事件。

日志不得记录完整提示词、密封源码、密钥、原始敏感 metadata 或 Controller 私有状态。

## 测试策略

### 单元测试

- metadata 完整传递且不能覆盖可信字段。
- v1/无 runtime manifest 继续标准链路。
- Adapter Registry 拒绝未知类型和 contract。
- debug 开关不影响 Controller、commit、render 调用次数。
- 每个生命周期阶段失败均封闭失败且不降级。
- 请求执行期间切换 release 不影响已固定请求。
- 密封模型危险工具仍不可用。

### 集成测试

- 使用测试密封包执行完整 Harness 生命周期并验证严格顺序。
- 强制 Skill 不依赖模型主动 tool call。
- commit 前没有最终输出，render-bound 后只有受约束输出。
- OpenAPI 幂等重放不重复执行 Harness。
- 激活不兼容 release 失败且旧 release 保持 active。
- 普通 Agent、标准密封 Agent、专家团和其他 OpenAPI 请求走原链路。
- 计费模型调用条目包含固定 release identity。

### 安全测试

- entrypoint 路径穿越、符号链接、digest 变化被拒绝。
- 子进程不能读取 release 外文件、宿主环境变量或发起网络连接。
- 伪造 metadata 不能选择 Adapter、release 或开启内部调试响应。
- 超时、超大消息、递归消息和进程派生受到限制。

## 发布策略

1. 先发布 manifest schema 与 Adapter Registry，功能默认关闭。
2. 上线标准链路回归测试和运行时指标，不激活 Harness。
3. 安装声明 `sealed_harness.v1` 的候选 release，在非生产请求执行 handshake 和契约测试。
4. 激活候选 release，小流量验证阶段审计、输出和计费。
5. 逐步扩大流量；出现异常时激活上一 release，新请求立即回退，正在执行的请求保持原 release 或按超时结束。

## 验收标准

- DClaw 源码不存在任何陆羽 Agent ID 或业务版本判断。
- 声明 Harness 的任意密封 Agent 每轮都按固定生命周期运行。
- debug 为假时 Controller/Harness 仍运行；仅诊断信息不返回。
- 普通 Agent和未声明 Adapter 的密封 Agent行为保持不变。
- 密封模型没有新增危险工具权限。
- 管理接口和审计能准确显示本次请求使用的 release、版本、digest 和 contract。
- 所有兼容、失败、幂等、计费及安全测试通过。
