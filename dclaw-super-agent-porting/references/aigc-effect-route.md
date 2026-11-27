# AIGC 创建副作用门禁

仅当当前 Agent 通过 `agent.execute(execution_mode="agent_loop")` 使用动态 `aigc_workflow_create` 创建工作流时应用。没有此能力的 Agent 记“不适用”。本门禁验证 Agent 对工具副作用的处理，不改变平台工具、Host 请求、默认值或已签名 Agent。

## 可信状态

按当前目标实例的认证标准、Pack/DevKit、实时目录和安装授权核对可用合同。`aigc_workflow_catalog` 只证明目录已读；模型最终正文即使像创建回执，也只是一段候选文本。创建调用、持久化事件、任务绑定和同 ID 快照分别留证。Agent 只能在正式可信创建结果及绑定/快照一致后写“已创建”。平台没有记录某一阶段时记“未记录”，不能反推阶段绝未发生。

创建准备、工具已开始但结果未知、已核验创建应分态。创建工具没有开始时不能把“计划创建”写成永久的“可能已创建”；开始后结果未知时保留原任务键、修订和蓝图，不更换键盲目重试。只读绑定 `not_found` 不独立证明重建安全；`ambiguous` 或 `unavailable` 同样停止。若正式合同无法给出安全重试条件，保持明确阻断并交给当前项目处理，不能凭本指南新增 Host 能力。

## Node 2/4 路由清单

当前项目枚举所有实际可能进入创建或恢复的入口，例如可信卡片提交、自由文字、旧状态续接和重复请求。只记录该 Agent 真正存在的入口；相同结构的入口可以合成一类。每类需追踪触发条件、稳定任务键、内容修订、蓝图来源、授权、创建成功证据、未知结果处置和恢复条件。项目在 `docs/AIGC_EFFECT_ROUTES.json` 提交开发期清单：

```json
{
  "schema_version": "aigc-effect-routes/1",
  "runtime_sha256": "当前待发布 runtime 文件的 64 位小写 SHA-256",
  "entries": [{
    "entry_id": "content.confirmed",
    "cases": ["success", "catalog_only", "created_no_text", "unknown_result", "replay"]
  }]
}
```

清单不进入密封 Host 请求。`entry_id` 仅表示通用入口类别，不得含客户内容、真实任务键或业务规则。若同一 Agent 存在多个独立入口，各列一条；漏列入口使 Node 4 阻断。人工对照代码分支确认入口覆盖，机器检查器不能自行发现未声明的代码分支。

## Node 6 真实代码故障注入

当前 Agent 项目编写一个 Python adapter，按 `--runtime FILE --entry ID --case CASE` 接受参数，仅向 stdout 输出一条 JSON。adapter 必须导入并运行 `FILE` 中受测的真实 Agent 函数，使用受控 Host/模型替身注入场景，并从替身记录实际调用与 Agent 结果。不得手填“应当发生”的成功观察；审阅者须检查 adapter 调用的是本版实际代码、入口映射完整且替身没有代替 Agent 决定状态转移。检查器会验证 runtime SHA，并跟踪至少一次来自该文件的函数调用，但这项技术检查不代替 adapter 代码审阅。

观察 JSON 只含以下字段；替身将不同平台版本的真实回执映射为结构状态，不输出请求参数、模型正文、客户素材、URL、Token 或物理 ID：

| 字段 | 类型及含义 |
| --- | --- |
| `runtime_sha256` | 被运行源码的 SHA-256，须与清单相同 |
| `invocations` | 本场景执行的回合数；`replay=2`，其他为 1 |
| `calls` | 有序数组，每项仅 `capability` 和 `outcome`；`capability` 限目录、创建、绑定查询及快照；`outcome=completed/failed/started_unknown` |
| `state` | `created` 布尔、`attempt=none/planned/unknown/verified`，以及 `key_preserved`、`revision_preserved`、`blueprint_preserved` 三个布尔 |
| `evidence` | `create=not_observed/completed/started_unknown`；`binding=not_read/not_found/found/ambiguous/unavailable`；`snapshot=not_read/matched/mismatch` |
| `terminal` | `status=blocked/created/recovered` 与脱敏大写稳定 `code`；adapter 将当前 Agent 的真实终态映射到场景码 |
| `model_text_kind` | `none/plain/receipt_like`；不保存正文 |

固定场景：

| 场景 | 注入和必须结果 |
| --- | --- |
| `success` | 目录、创建、可信绑定和同 ID 快照通过，Agent 才记录已创建 |
| `catalog_only` | 模型给出貌似回执的文本，但只读目录、未调用创建；Agent 不信文本、不写未知创建标记，终态为 `CREATE_NOT_OBSERVED` |
| `created_no_text` | 创建已经持久化，但模型最终正文为空；Agent 仍通过可信绑定及快照确认原任务，不换键重建 |
| `unknown_result` | 创建已开始、终态不明，绑定不可确证；Agent 保留原键/修订/蓝图、记录未知并停止重放 |
| `replay` | 同一请求进入两回合；至多一次实际创建，恢复同一已核验任务 |

执行：

```text
python <Skill>/scripts/check_aigc_effect_routes.py \
  --runtime <Agent项目>/agent/runtime.py \
  --routes <Agent项目>/docs/AIGC_EFFECT_ROUTES.json \
  --adapter <Agent项目>/tests/aigc_effect_adapter.py \
  --output <Agent项目>/evaluation/aigc-effect-check.json
```

检查器返回 `AIGC.OK` 才放行受影响的 Node 6/7。非零退出码及 `AIGC.*` 稳定码指出漏入口、源码摘要变化、目录无创建、企图把预调用标记当未知副作用、文本冒充回执、绑定不可信或未知结果重放。`AIGC.OBSERVATION_UNVERIFIED` 表示 adapter 没有运行当前源码或观察格式不可信，不能当成业务失败。报告只含入口类别、场景、摘要和稳定码。旧已签名 Agent 不会被这个开发期工具自动改动；它们只在各自下一轮优化时应用。

此离线注入是发布前门禁，不证明生产模型一定会选择工具。Node 8 后仍以本次实际 Release 的真实 Host 操作、持久任务和客户端结果核对。生产诊断未记录的内部细节不能由离线测试补造。
