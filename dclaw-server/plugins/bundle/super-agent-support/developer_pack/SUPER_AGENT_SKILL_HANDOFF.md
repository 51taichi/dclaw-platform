# Super Agent Skill 统一交接：模型调用、交互卡与失败终止

适用基线：标准 2.73、Support 1.18.62、Developer Pack 1.10.52、
DevKit 1.9.37。本文适用于所有 Super Agent，不包含任何单一专家业务规则。

## 平台统一保证

- 跨 Release 状态续接不以来源 Release 仍位于五版可回切列表为必要
  条件。来源已退出列表时，Host 仍核对同租户、同 Agent、用户、
  会话、安装身份及目标 Schema 后原子续接；无身份的旧辅助 JSON
  不作为业务状态。既有五版回切上限不变。
- 显式会话选模优先于签名专家默认模型；固定模型必须仍在目标实例聊天
  模型目录中且与实际执行路由一致，`auto/routing` 保持自动路由。退役
  声明会在专家 runtime 前给出脱敏错误，不能依赖静默回退。
- `agent.execute` 只有三种合法模式：普通文本候选、JSON Object 候选、
  `agent_loop` 工具循环。机器合同在
  `devkit/schemas/agent-execute-v1/`，参考实现在
  `devkit/agent_execute_api_demo.py`。
- `runtime.fail` 保留原有小写错误码，同时接受最长 64 字符的安全大写
  点分错误码，例如 `HOST.AGENT_EXECUTE_FAILED`。机器合同在
  `devkit/schemas/runtime-fail-v1/`。
- 本轮真正新建的交互卡若因失败、超时或取消未完成，平台只取消同
  invocation、同 installation/session 且仍为 PENDING 的新卡。已提交卡、
  幂等重放卡和其他 invocation 的卡不受影响；替换失败时恢复旧 PENDING 卡。
- 已激活 Release 的既有合法调用保持兼容。平台不会静默改写专家业务代码。

## Skill 必须生成的调用

普通文本候选只提交 `messages`。需要结构化模型候选时，提交 `messages` 与
`response_format=json_object`。需要模型使用 Host 工具时，提交
`execution_mode=agent_loop`、`messages` 与非空 `instruction`。

禁止以下组合：

- 候选模式携带 `instruction`；
- `agent_loop` 携带 `response_format`；
- 用普通聊天成功代替 Host 工具循环验收；
- 接受 Fake Host 的宽松回执而不按正式 Schema 校验。

## 统一交互卡流程

1. 每轮先调用一次模型，同时取得业务回复、文字回退和卡片建议；确需客户回答一个采集问题时必须建议卡片。
2. 专家先按业务答案类型确定真实组件：单项枚举用 `single_select`，多项枚举用 `multi_select`，开放文字用单问题 `question_form`，真实本地文件用 `file_selector`。内部联合类型不进入 Host 请求；模型建议必须匹配专家批准的类型。
3. 调用 `interaction.capabilities.list/1` 获取建议组件的实时详细目录，并校验专家自己的业务字段和稳定 option ID。
4. 调用 `interaction.card.create/1`，使用稳定幂等键；Support Plugin 按公开的完整组件 Schema 校验卡片。
5. 同时核对持久卡记录与 `interaction.card.receipt/1` created 回执。
6. 成功时通过 `runtime.complete` 提交卡片与回复；建议无效或建卡失败时提交同轮文字回退，不声称卡片存在。其他失败调用一次 `runtime.fail`，不得伪造成功或让回合无终态。

卡片 API 参考：`devkit/interaction_card_api_demo.py` 和 `devkit/examples/interaction-host-v1/card-type-examples.json`；模型与失败 API 参考：
`devkit/agent_execute_api_demo.py`；完整规则见
`devkit/examples/agent-execute-v1/README.md`。

## 现有专家迁移检查

每个专家责任会话在下一次发布时分别检查真实代码，不得批量复制业务实现：

- 默认候选调用是否错误携带 `instruction`；
- 工具循环是否错误叠加 `response_format=json_object`；
- 自定义失败码是否符合安全大写点分语法；
- 是否读取实时卡片详细目录并校验业务规则，而不是使用本地猜测字段；
- 是否严格核对 created receipt、点击续接、幂等重放和 replacement；
- Fake Host 是否复用正式 Schema 和 Demo 的严格 validator；
- 失败路径是否调用一次 `runtime.fail`，成功路径是否调用一次
  `runtime.complete`。

平台补偿不替代专家正确终止回合。存在非法 `agent.execute` 参数的专家必须
发布新 Release；仅更新 Support 插件不能修改其已签名业务代码。未触及上述
非法模式的已激活专家无需为了本次平台更新强制发版。

## 发布门禁

Skill 应把本 DevKit 的正反例纳入 validate/test。至少覆盖三种合法模型调用、
两种非法混用、自定义错误码、实时卡片 Schema、created receipt、幂等重放、
点击续接、失败补偿和并发隔离。真实客户端端到端验收仍按每个专家的实际
流程单独执行。
