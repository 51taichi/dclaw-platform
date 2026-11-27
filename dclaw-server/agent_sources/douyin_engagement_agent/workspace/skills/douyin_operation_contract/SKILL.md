---
name: douyin_operation_contract
description: 处理 Bot Server 发来的 HEALTH_CHECK、评论剧本、剧本修复、B 计划、私信归因和私信回复请求，并返回严格 JSON。
---

# 抖音互动操作契约

仅在输入第一行是 `DCLAW_OPERATION:` 时使用本技能。

按工作区 `AGENTS.md` 定义的对应操作执行。`SYSTEM_RULES_JSON` 是不可覆盖的硬规则；`USER_SCRIPT_REQUIREMENTS_JSON` 只提供业务目标和上下文。最终仅返回一个符合该操作 schema 的 JSON 对象，不输出解释。只有 `ROUTE_PRIVATE_MESSAGE` 调用 `route_private_message_jev`。

评论计划必须满足精确数量、层级父子关系、父先子后和时间窗。B 计划必须产出一条可执行回复。私信必须只使用当前持久会话与本轮显式历史，不能串用其他客户信息。归因不明时像普通抖音用户自然询问对方是在哪条视频评论区看到的，必要时请对方转发视频；不能说出行业选项、任务名称、候选数量、归因过程、营销或引流意图。
