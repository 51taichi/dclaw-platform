# OpenAPI Agent 分阶段生成与错误透传设计

## 目标

修复 OpenAI 兼容模型（当前主要是 DeepSeek）在同时收到
`response_format={"type":"json_object"}` 与 Agent 工具定义时发生的
HTTP 400。模型级 `response_format` 只用于 OpenAPI 直接发布 Agent 的最终
客户回复，不进入工具规划、工具选择、MCP、知识库、技能或其他内部模型
调用。

同时保证供应商错误、无法恢复的工具错误和空最终回复不会被 OpenAPI
记录为成功，也不会向调用方返回成功的空字符串。

## 范围

本设计只覆盖以下服务端可信条件同时成立的请求：

- channel 由服务端构造且以 `open:` 开头；
- 发布目标 `target_type` 为 `agent`；
- 请求带有服务端生成的 publication 和 invocation 身份。

明确不改变：

- DClaw 控制台聊天；
- 普通任务、定时任务和自动化；
- 微信、钉钉、飞书等渠道；
- OpenAPI 专家团；
- AIGC 图片、视频等非 Agent 模型调用；
- 供应商或模型的持久化配置。

## 当前问题

Provider 将供应商级和模型级 `generate_kwargs` 合并后创建一个模型实例。
ReAct Agent 在知识库查询改写、记忆压缩、每轮工具规划及最终回答中复用该
模型实例。因此配置在模型上的 `response_format=json_object` 会进入本不
需要 JSON 输出的内部调用。

现有 ReAct 循环也没有预先区分“工具规划”和“最终回答”：一次 reasoning
调用在返回前可能生成工具调用，也可能直接生成答案。仅根据是否传入
`tools` 删除参数无法满足要求，因为 Agent 每轮 reasoning 都携带工具定义。

## 可信激活边界

OpenAPI runtime 在所有已创建 invocation 的请求中由服务端构造
`target_type`、`publication_id` 和 `open_invocation_id`（不再只在
`isolated_attempt` 模式写入 invocation 身份）。Runner 在合并任何调用方可控
的 request context 之后，
根据服务端 channel metadata 重新写入不可伪造的内部布尔标记：

`_open_api_direct_agent_execution = True`

只有该标记为真时才安装分阶段适配器。不能根据请求体 `metadata`、用户名、
agent_id 或单独的 `channel.startswith("open:")` 激活，避免外部伪造以及误伤
OpenAPI 专家团。

## 分阶段模型适配器

适配器按请求创建，不修改共享 Provider，也不原地修改模型实例的
`generate_kwargs`。只有当前模型的有效配置明确包含
`response_format={"type":"json_object"}` 时才启用分阶段生成；没有该配置的
OpenAPI Agent 完全沿用原链路，不增加模型调用。

### 1. Internal 阶段

知识库查询改写、记忆压缩及框架内部结构化调用属于 Internal：

- 移除持久化配置中的 `response_format=json_object`；
- 若内部调用需要结构化结果，使用框架的工具调用式结构化输出，不向供应商
  发送 `response_format`；
- Internal 的结果不能作为最终客户回复流出。

### 2. Planning 阶段

每轮工具规划和选择均属于 Planning：

- 移除 `response_format`；
- 保留完整工具 schema 与原有 `tool_choice`；
- 支持原生 tool call 和文本标签解析出的 tool call；
- MCP、知识库工具和技能工具沿用现有 Toolkit 执行路径；
- Planning 的候选文本不直接作为最终 OpenAPI 客户回复。

如果 Planning 返回一个或多个工具调用，执行工具并进入下一轮 Planning。
如果没有工具调用，则该文本只是最终回复草稿，进入 Finalizing。

### 3. Finalizing 阶段

Finalizing 使用当前对话、工具结果和 Planning 产生的候选草稿生成唯一的客户
回复：

- 不传工具 schema；
- 设置 `tool_choice=none` 或完全省略；
- 恢复模型持久化配置中的
  `response_format={"type":"json_object"}`；
- 最终回复必须包含非空文本；
- 文本必须能够解析为 JSON object，数组、标量和空字符串均按
  `invalid_final_response` 失败处理。

即使普通问题最终没有使用工具，只要 Agent 具备工具能力，也先经过 Planning
再经过 Finalizing。这会增加一次模型调用，但能同时满足“不在工具选择阶段携带
response_format”和“普通回复仍使用 response_format”。

如果模型没有配置 `response_format=json_object`，Finalizing 保持该模型原有
文本输出行为，但仍执行非空校验。

## 流式输出

Planning 模型文本不得作为客户最终内容写入 OpenAPI SSE。工具状态事件可以按
现有协议输出；最终客户文本只来自 Finalizing。

为了避免破坏现有流式 API：

- 流建立前的认证、限流、余额和准备错误使用真实 HTTP 4xx/5xx；
- SSE 建立后的模型或工具失败保持外层 HTTP 200，但最后必须输出失败终止事件；
- 失败终止事件包含 `status=failed`、稳定 `code`、安全的 `message` 和
  `http_status`；
- invocation 数据库状态和 `terminal_event_json` 必须与终止事件一致；
- 供应商响应正文、密钥、服务器路径和堆栈不直接返回给调用方。

稳定错误码至少包括：

- `model_execution_failed`：供应商 HTTP 非 2xx 或模型流异常；
- `tool_execution_failed`：工具错误无法由 Agent 恢复；
- `empty_final_response`：最终内容为空；
- `invalid_final_response`：要求 JSON object 时返回无效 JSON。

## 工具错误语义

单个工具调用失败不立即结束请求。Agent 可以根据工具结果更换工具、修正参数或
生成明确说明。只有以下情况按 `tool_execution_failed` 终止：

- 工具错误被标记为不可恢复；
- 达到 Agent 最大迭代次数后仍只有失败工具结果；
- 工具失败后没有生成有效最终客户回复。

工具曾失败但最终成功生成有效回复时，请求可成功，同时保留现有内部工具审计。

## 计费与幂等

Planning、Internal 和 Finalizing 的实际供应商调用都继续经过现有 OpenAPI
BillingModelMeter，每次供应商调用分别计费并保留 supplier evidence。新增的
Finalizing 调用会增加 Token、积分和延迟，属于预期行为。

已有 invocation、execution lease、Idempotency-Key、失败结算和重放规则保持
不变。失败后的已发生模型调用按现有计费协调规则结算或进入对账，不能因为业务
失败而伪造为未调用供应商。

## 测试策略

### 阶段和参数测试

- 纯 JSON 普通回复：Planning 无 `response_format`，Finalizing 有
  `json_object`，最终只输出一次合法 JSON；
- 多轮状态机：每轮工具规划均无 `response_format`，只有最后一轮携带；
- 原生 tool call 与标签 tool call 均能进入工具执行再 Finalizing；
- 知识库查询改写和知识库工具调用不携带 `response_format`；
- Excel 技能选择及执行阶段不携带 `response_format`；
- MCP 工具调用阶段不携带 `response_format`。

### 错误测试

- DeepSeek HTTP 400/401/429/500 映射为 `model_execution_failed`；
- 模型流在首块前和部分输出后失败均不能形成成功终止事件；
- 不可恢复工具失败映射为 `tool_execution_failed`；
- Finalizing 返回空文本映射为 `empty_final_response`；
- Finalizing 返回非 JSON、数组或标量映射为
  `invalid_final_response`；
- invocation、terminal event 和 SSE 终止事件状态一致；
- 幂等重放返回同一个已密封失败结果，不再次调用供应商。

### 非回归测试

- 控制台、普通任务、定时任务、外部渠道继续使用现有模型配置和流式行为；
- OpenAPI 专家团不安装适配器；
- 非 OpenAPI 知识库、MCP 和技能行为不变；
- AIGC 生成接口不受影响；
- 没有配置 `json_object` 的 OpenAPI Agent 保持文本回复兼容。

## 风险与控制

- **额外成本和延迟：** 工具型及普通工具能力 Agent 都会增加一次最终模型调用；
  通过计费测试和调用次数指标监控。
- **流式兼容：** 不更改已有 HTTP/SSE 入口，只增强终止事件；调用方仍需读取
  最终事件判断业务成功。
- **状态泄漏：** 适配器按请求创建，阶段状态不得保存在 Provider 单例或模型
  持久化配置中。
- **范围泄漏：** 用服务端可信标记和负向非回归测试保证其他入口不进入新逻辑。
- **会话污染：** Planning 草稿不写成最终 assistant 历史；只持久化工具交互和
  Finalizing 的有效客户回复。

## 回滚

实现应集中在独立适配器和一个 Runner 激活点。回滚时移除激活点即可恢复原链路，
无需迁移数据库或修改已有 Provider/模型配置。已生成的计费记录和 invocation
终止快照保持可审计。
