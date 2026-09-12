# 超级专家 AIGC Agent 工具协议

适用于已通过安装授权、采用 `agent.execute(execution_mode="agent_loop")` 的标准超级专家。工具按当前安装的能力声明注册，不识别专家名称，不要求平台为新专家添加分支。普通专家和旧 candidate/host.call 路径不新增工具。

| 模型工具 | 所需 v1 能力 | 行为 |
| --- | --- | --- |
| aigc_workflow_catalog | aigc.workflow.capabilities.list/1 | 按 `node_kinds` 返回相关实时目录、蓝图 schema 和使用实时模型标识的最小工作流实例；省略筛选时不附加实例 |
| aigc_workflow_create | aigc.workflow.create/1 + 目录能力 | 创建当前会话的真实工作流与物料任务 |
| aigc_task_status | workflow.create、task.resume、review.complete 任一 | 读取当前安装、当前会话的任务；省略 ID 时只解析宿主当前审核任务 |
| aigc_task_resume | aigc.task.resume + aigc.task.create | 恢复真实绑定的任务状态 |
| aigc_task_review | aigc.review.complete + aigc.task.create | 回写当前宿主提交素材的审核结论 |

`aigc.asset.submit` 仍由现有任务卡提交入口使用，不提供模型代提交工具。创建任务不启动生成；生成、计费、素材归属与事件均复用现有平台服务。RPA、MCP 不在本次工具集合内。Skill reader 和完整 Agent 循环沿用现有配置，不因 AIGC 授权自动打开。

创建参数只含稳定 `task_key`、正整数 `content_revision` 和对象类型的 `workflow`。安装与会话由宿主绑定；同任务同修订生成相同物料 ID 和幂等键。实质变更蓝图需新修订。连接层会把可解析为对象的字符串化 workflow 规范化为对象；其他错误类型返回包含 field、expected、received 与 guidance 的 `INVALID_WORKFLOW_REQUEST`，且不会进入创建服务。平台执行异常返回 `PLATFORM_OPERATION_UNCONFIRMED` 与可查询的物料 ID；该 ID 不证明创建成功，也不返回原始内部错误。

审核只接受宿主解析过的当前素材身份和集合；`ACCEPTED` 还要求每个非文本模态的真实格式化输入传入模型。此证据证明传输，不保证模型的专业判断正确。任务通过也不表示全部业务内容通过或允许账号发布。

工具与媒体跟踪均限当前调用，完成、异常或取消后恢复原 Agent 对象。业务规则和提示词模板放在专家包内，平台连接层只处理通用授权、绑定、幂等与工具传输。

验证：`tests/unit/app/runner/test_aigc_tools.py` 覆盖不同专家身份、授权筛选、跨会话隔离、真实画布创建与重试、审核证据、异常恢复和真实 AgentScope 工具循环。上线需要服务端包含该连接层，专家包声明能力并完成标准导入授权；仅替换 ZIP 不会升级正在运行的服务。

## 2026-09-11 工具注册修复

真实会话在模型请求前因 postponed Literal 注解无法在 AgentScope 动态 schema 命名空间解析而失败。移除连接层的延迟注解，保留 decision 的枚举约束。新增全授权五工具注册测试；原测试仅注册目录/创建工具，未覆盖审核工具 schema。修复后 66 项连接层与编排测试通过，部署镜像内五工具注册校验通过。
