# 迁移记录

## 身份与材料

- 源：DClaw 普通 Agent `douyin_engagement_agent`。
- 目标：密封超级专家 `douyin-engagement-agent` 1.0.0。
- 标准：`dclaw.super-agent-development` 1.12。
- 材料：`workspace/` 中提示词、Profile、Skill 清单、三项 Skill 文档及普通 Agent 配置；
  `agent/` 中已有六项密封参考实现。

## 分层决策

- 评论、私信、归因、阈值和证据判断全部放入超级专家。
- 移除普通 Agent 的 `read_agent_skill` 和 `route_private_message_jev` 工具依赖。
- 不创建业务服务，不持有 TypeSafe Token。
- 不创建本地能力包，不声明本地助手。
- Bot Server 继续拥有执行、配额、调度、幂等、审计和告警；这是源材料明确的外部边界。

## 行为变化

- `HEALTH_CHECK` 改为确定性返回，不再调用模型。
- 密封实现补齐 `ROUTE_PRIVATE_MESSAGE`，七项操作统一进入同一严格合同。
- 归因由超级专家模型产生候选，确定性外壳验证候选 ID、概率阈值和最小置信差。
- 线索证据增加真实入站消息逐字校验；评论依赖增加父节点严格早于子节点校验。

## 证据与未决项

- 源码提交：`039e075556e6717959c364e3e31d178f9b4dfa12`。
- 自动测试记录写入 `docs/RELEASE.md`。
- 目标 DClaw `http://192.168.0.5:4312` 在 2026-10-23 对
  `/api/super-agent-support/developer-kit` 返回 404，当前状态为 `platform-tooling-missing`。
- 未取得官方 DevKit 前，不计算或声称最终能力摘要，不构建签名 ZIP。
- 未提供已入驻 `signer_id` 与对应私钥；签名前必须由开发方受控环境提供。
- 未执行管理员上传、授权、激活或三个真实任务。

## 回滚

激活目标超级专家失败时重新激活上一密封发布版；若尚无上一密封版，则停用新发布并
继续使用现有普通 Agent。回滚不修改 DClaw 平台、不删除源 `workspace/`，也不改变
Bot Server 配置，直至管理员明确切换。
