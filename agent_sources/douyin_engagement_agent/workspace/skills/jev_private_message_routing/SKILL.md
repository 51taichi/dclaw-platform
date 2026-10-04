---
name: jev_private_message_routing
description: 抖音私信任务归因。仅在 ROUTE_PRIVATE_MESSAGE 操作中调用 Jev 工具。
---

# 私信任务归因

收到 `ROUTE_PRIVATE_MESSAGE` 时，调用一次 `route_private_message_jev`。传入 `inboundMessage.text`、`inboundMessage.video`（存在时）、当前会话的 `recentHistory` 和 Bot Server 提供的 `candidateTasks`。候选任务只包含 `taskId`、`name`、`routingDescription`、`routingThreshold`，不得加入回复话术、微信号或其他客户的私密配置。

工具把候选任务与 `no_match` 放入 Jev Choice。超过 200 个任务时先分批选出候选，再用一次 Jev Choice 做全局比较，最多支持 2000 个任务。最终概率必须达到所选任务的 `routingThreshold`，并领先第二候选至少 0.15。泛化问候、缺少线索、多个候选接近、API 错误均不得强行归因。

最终 JSON 只转述工具结论。`MATCHED` 时 `taskId` 必须是候选中的 ID；`UNRESOLVED` 和 `ERROR` 时 `taskId`、`probability` 必须为 null。绝不能在这个操作生成私信内容。
