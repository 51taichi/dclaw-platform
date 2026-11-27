# 超级专家 AIGC Agent 工具协议

适用于已通过安装授权、采用 `agent.execute(execution_mode="agent_loop")` 的标准超级专家。工具按当前安装的能力声明注册，不识别专家名称，不要求平台为新专家添加分支。普通专家和旧 candidate/host.call 路径不新增工具。

| 模型工具 | 所需 v1 能力 | 行为 |
| --- | --- | --- |
| aigc_workflow_catalog | aigc.workflow.capabilities.list/1 | 按 `node_kinds` 返回相关实时目录、蓝图 schema 和使用实时模型标识的最小工作流实例；省略筛选时不附加实例 |
| aigc_workflow_create | aigc.workflow.create/1 + 目录能力 | 创建当前会话的真实工作流与物料任务 |
| aigc_task_status | workflow.create、task.resume、review.complete 任一 | 读取当前安装、当前会话的任务；新流程以 `ACCEPTED` 为完成，历史审核状态保持可读 |
| aigc_task_resume | aigc.task.resume + aigc.task.create | 恢复真实绑定的任务状态 |

`aigc.asset.submit` 与 `aigc.review.complete` 能力 ID 保留用于旧安装包和历史记录解析，但非前端 submit 写入返回 `AIGC_ASSET_SUBMIT_RETIRED`，review 写入返回 `AIGC_REVIEW_RETIRED`。新专家不得依赖 `aigc_task_review`；仅对已签名且仍声明旧 review capability 的专家注册同名只读兼容工具，用于读取严格绑定的客户完成状态，不观察媒体、不触发模型审核且不写审核结论。客户在任务页点击“完成并返回会话”属于平台用户操作，只接受当前租户、当前安装实例及持久化任务的精确 binding，并继续校验画布、节点和素材所有权；它不依赖专家包声明提交或审核能力，也不触发模型审核。创建任务不启动生成；生成、计费、素材归属与事件均复用现有平台服务。RPA、MCP 不在本次工具集合内。Skill reader 和完整 Agent 循环沿用现有配置，不因 AIGC 授权自动打开。

创建参数只含稳定 `task_key`、正整数 `content_revision` 和完整 `WorkflowBlueprint` 对象。工具注册时向模型暴露蓝图的全部嵌套字段、必填项与枚举，并移除 Gemini 不接受的 `$ref`、`$defs`、`const` 关键字；数值常量仍在执行前严格校验。安装与会话仍由宿主绑定。同任务同修订生成相同物料 ID 和幂等键，实质变更蓝图需新修订。

连接层会把可解析为对象的字符串化 workflow 规范化为对象，并在进入平台服务前执行完整蓝图校验以及各节点注册的 `input_schema`、`parameter_schema` 校验。结构错误返回包含字段路径与稳定错误码的 `INVALID_WORKFLOW_REQUEST`，不会创建任务或画布。平台明确拒绝的授权、模型、节点、参数、边、任务状态和幂等错误保留稳定错误码及修正指引；只有无法确定是否已产生副作用的异常才返回 `PLATFORM_OPERATION_UNCONFIRMED` 与可查询的物料 ID。该 ID 不证明创建成功，也不返回原始内部错误。

新流程由平台校验当前租户、安装实例、任务 binding、画布、节点与素材所有权后直接写入 `ACCEPTED`，不把素材传入 Agent/模型审核。历史审核状态与回执仅可读取，不再允许 Agent 写入新的审核结论；任务完成不表示允许账号发布。

工具与媒体跟踪均限当前调用，完成、异常或取消后恢复原 Agent 对象。业务规则和提示词模板放在专家包内，平台连接层只处理通用授权、绑定、幂等与工具传输。

验证：`tests/unit/app/runner/test_aigc_tools.py` 覆盖不同专家身份、授权筛选、跨会话隔离、真实画布创建与重试、旧审核兼容、异常恢复和真实 AgentScope 工具循环；平台路由测试另行证明新客户完成路径不调用审核派发。上线需要服务端包含该连接层，专家包声明实际所需能力并完成标准导入授权；仅替换 ZIP 不会升级正在运行的服务。

## 2026-09-11 工具注册修复

真实会话在模型请求前因 postponed Literal 注解无法在 AgentScope 动态 schema 命名空间解析而失败。移除连接层的延迟注解，保留 decision 的枚举约束。新增全授权五工具注册测试；原测试仅注册目录/创建工具，未覆盖审核工具 schema。修复后 66 项连接层与编排测试通过，部署镜像内五工具注册校验通过。
