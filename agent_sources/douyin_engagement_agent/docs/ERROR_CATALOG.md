# 错误目录

| 错误/诊断引用 | 最初失败层 | 责任方 | 可重试 | 客户提示 | 管理员动作 | 测试 |
|---|---|---|---:|---|---|---|
| `invalid_operation_message` | `super_agent` | 开发方/调用方输入 | 否 | 请求格式不合法，请修正后重试 | 对照三段协议检查缺段、重复段和操作名 | 协议解析测试 |
| `session_context_unavailable` | `dclaw_platform` | 平台方 | 是 | 会话上下文暂不可用，请稍后重试 | 用 trace 定位 Host 会话调用 | 运行时 Host 失败测试 |
| `model_unavailable` | `dclaw_platform` | 平台方 | 是 | 智能生成服务暂不可用，请稍后重试 | 检查模型路由和配额 | 模型调用失败测试 |
| `invalid_agent_output` | `super_agent` | 开发方 | 是 | 本次结果未通过安全校验，请重试 | 检查两次候选的稳定校验码 | 双次无效候选测试 |
| `runtime_failed` | `super_agent` | 开发方 | 视原因 | 本次处理失败，请凭追踪编号联系管理员 | 从 `runtime.trace` 找最初失败事件 | 终态唯一性测试 |
| `invalid_route_input` | `super_agent` | 开发方/调用方输入 | 否 | 候选任务配置不合法 | 修正候选阈值、ID 或数量 | 路由合同测试 |
| `route_below_threshold` | `super_agent` | 开发方 | 是 | 归因证据不足，需进一步确认 | 应返回 `UNRESOLVED`，检查提示和候选上下文 | 阈值门禁测试 |
| `invalid_lead_evidence` | `super_agent` | 开发方 | 是 | 线索证据未通过校验 | 确认证据逐字来自入站消息 | 证据真实性测试 |

公开响应不包含堆栈、提示词、客户原文、内部 URL、绝对路径或 Secret。各转发层必须
保留平台提供的 `trace_id`；本专家 trace 不自行伪造追踪标识。
