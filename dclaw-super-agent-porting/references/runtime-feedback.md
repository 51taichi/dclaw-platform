# DClaw 试跑问题处理规则

适用：开发者、项目方或客户反馈超级专家在适配、上传、激活、客户端真实使用或后续更新中出错。先读主 `SKILL.md`；本规则只处理接入与故障归属，不替当前 Agent 定义业务好坏。任何阶段都可使用，不必等 Node 8 完成。

## 1. 收到反馈时先留住事实

Codex 在当前 Agent 项目记录：目标实例、Agent 显示名与 `agent_id`（已知时）、所选专家与模型、任务或会话标识及客户端关联 ID（界面可见时）、发生时间及时区、操作步骤、预期与实际结果、原始错误码或截图、是否涉及付费/重复任务。每次真实试跑报错按[卡点回传与每日补漏](blocker-feedback.md)逐次登记完整关联 ID 与最终状态，同根因归并卡点，不合并掉单次发生的证据。区分用户亲眼看到的现象与开发方推测。截图可含客户内容时只保存在该 Agent 项目，向外反馈前脱敏。缺少标识时先用现有任务、时间和截图定位；只向用户索取确实缺失且会改变排查结论的信息，不要求密码、Token、私钥或完整客户对话。

先标明失败阶段：`本地校验`、`密封验签`、`上传/授权/激活`、`客户端专家回合`、`平台能力调用`、`结果交付`或`未定位`。保留已签名包、回执和现场记录，不为诊断覆盖它们；需要重试前先检查是否可能造成重复上传、收费生成或状态重复提交。

目标实例已发布标准 2.65 的 `agent-execute-v1` / `runtime-fail-v1` 时，`agent.execute` 请求被拒先对照失败时实际 Release 拼装的完整请求和关闭 Schema：候选误带 `public_stream` 或 `instruction`、工具循环误带 `response_format` 或缺顶层非空 `instruction` 均属可在 Agent 侧修正的格式问题。先分清请求拒绝、模型候选内容不合格与 Host 建卡回执不合格；只有同一调用的正式诊断显示平台违反其合同，才归为平台问题。卡片已创建而回合失败时，再按[共用模型调用与失败终止](capability-verification.md#共用模型调用与失败终止)核实平台补偿范围与实际卡片状态；不以失败提示推定卡已取消，也不因补偿未取证就重复建卡。

标准 2.66 / Support 1.18.56 描述固定模型路由预检及 `agent_loop` 分段预算和诊断；先核生产插件修订与平台部署回执，不能仅凭标准或 Pack 推定新机制已生效。若已部署且同次诊断证明模型路由预检失败，核失败时 Release 的签名默认模型、客户会话显式选模、实时目录与实际路由，避免把预检归为 Agent 候选解析。若尚未部署，已知签名默认模型退役仍由该专家开发方更正，平台静默回退另作待修项；约整轮截止时间的超时在缺分阶段证据时仍是未归因，不能推断模型请求、响应流、锁等待或专家执行内部的具体阶段，更不能归因于模型返回内容。部署并取得关联 ID 脱敏回执后，才按实际记录区分 Host 预算、模型请求/流、锁等待与整轮截止；旧回合未采集的字段不补造，不为补证反复发起客户任务。若记录仅有 `model_validation/json_parse` 而无模型原文或失败批次，只能确认候选校验观察点，核对应版请求和解析分支并做有限的项目侧回归；不推断围栏、截断、模型路由或平台违约。修复 Agent 的解析与恢复路径后仍需真实客户端复测，发布回执不替代原故障结案。

工作流“建卡失败”时按同一 invocation 分开查询目录、模型调用、`aigc_workflow_create` Host 操作、创建事件、绑定、快照和最终事务。`completed/committed` 只表示专家回合事务完成，不证明 AIGC 业务创建；目录读取成功、模型正文非空及本地任务表为空也都不能证明或否定工作流创建。若新回合的 Host 操作记录只有目录而没有创建，结论限于“该回合未记录到创建调用”，再用实际 Release 代码核对是否过早写入创建尝试标记、是否从模型最终正文解析权威回执；模型为何未选创建工具仍须独立证据。修复进入[创建副作用门禁](aigc-effect-route.md)的受控测试；不以客户重复点击补证。历史没有保留工具操作时标“未记录”，不能反推未执行。

## 2. Codex 自查顺序

1. **确认实际版本。** 从当前 Agent 项目读取签名包摘要、manifest、上传回执和列表回读；有正式账号与安全认证条件时，用目标实例当次官方 DevKit 的只读 `publish list` 核对 `active_release_id`。无法实时回读就写“未知”，不能把本地工作树或历史回执当成当前线上版本。
2. **区分首错与最终阻断。** 比较实际请求、工具回执、错误码、项目日志和已保存的 `trace_id` / `invocation_id`，按同一回合的调用顺序核对重试、后续工具和事务关闭。用对应已发布版本的代码和能力清单检查失败分支；本地草稿只能作为修复候选。通用失败提示、单张截图或已恢复的首错不足以断定最终原因及 Agent、模型或平台责任。
   同时把客户端提示与已证实的最终阻断对照。提示若把已恢复的早期错误或后续工具失败错报为另一类问题，检查已发布 Agent 的异常捕获和错误映射，以及平台实际负责的展示层；正式 Schema 允许的 `rejected` 不应仅因没有 `task_id` 就记为格式错误，更不能把设备拒绝改写成素材错误。按证据由责任方修正提示并回归。终止类别仍未取得时使用准确的未知提示，不编造具体原因。提示纠正和底层失败修复分别记录、分别复测，不能以其中一项代替另一项。
3. **做最小验证。** 对能在本地复现的 Agent 问题运行有针对性的项目测试和官方 Pack 校验；对平台能力核对目标实例正式 Schema、授权及真实回执。必要的客户端对照测试须使用获准的测试数据，并在一次有区分力的对照后停止盲目重试。付费 AIGC、发布、重签、回滚和其他会改变线上状态的操作仍须按原节点授权与门禁执行。没有客户端自动化工具时，由项目方提供界面结果即可，不要求安装 `computer-use`。
4. **列出已知与未知。** 每条结论写明证据路径和能证明的范围。Pack `validate/test`、能力 ID、上传成功、客户端可见和真实业务完成分别记录；任何一种都不能替代下一种。缺服务端 trace 或正式合同且本地无法定位时，保持“未归因”，转入下方管理员核查请求。

### 开发者侧只读诊断边界

目标实例正式提供标准 `2.64` / Support `1.18.54` / Pack `1.10.43` / DevKit `1.9.30` 的 `developer.runtime.diagnostics.by-reference/6` 时，已知关联 ID 优先使用本 Skill 的 `scripts/runtime_diagnostics_with_login.py --invocation-id <ID> --devkit-root <已核验 Pack 的 devkit 目录>` 在线读取；无须另加版本开关，脚本按当次正式操作目录及 `schemas/runtime-diagnostics-v6/` 的请求、关闭响应和错误 Schema 选择 `/v6/`。官方 `runtime_diagnostics_api_demo.py --root-cause` 是同一只读合同的示例。保存原回执后，可用 `scripts/summarize_runtime_diagnostics.py --receipt <原回执> --devkit-root <同一 devkit 目录> --agent-id <专家 ID> --invocation-id <ID> --output <新摘要路径>` 离线复核；两个脚本均只在开发方项目使用，不加入运行中的专家包。v6 缺正式材料时才按已核验的 v5 或更早合同选择路由，HTTP `404` 不降级；HTTP `503` 是诊断证据源不可读，不能当作 `no_record` 或成功，保留原关联 ID 待平台恢复后只读复查。

v6 `found` 先分别读 `runtime_evidence`、`local_task_evidence`、回合/事务状态与 `task_acceptance`，再逐条核对 `findings[]` 的 `layer`、`phase`、`category`、`error_code`、`responsibility`、`recovery_action`、`evidence` 和对应任务；数组第一项不保证是唯一根因。`local_tasks[]` 逐项核对 Host 派发、Helper 接收、执行时版本、首错证据与 `task_status` 的终态；专家回合 `completed` 后本地任务仍可能失败。`HOST_INTERNAL_ERROR` 且 `first_observed_only` 仅说明首次可观察的 Host 异常阶段，不能猜内部异常；`historical_detail_not_recorded` 表示历史具体细节未留存，两者都不授权重复客户回合。`no_failure_recorded` 只表示当前留存证据无失败，`no_record` 只表示本次查询无记录，不证明客户业务或设备产物成功。按回执的安全责任线和正式合同分流，必要时由平台凭同一关联 ID 查其权限内证据；普通账号 v6 查询、官方 Schema 和真实客户端 E2E 分别留证，不为获取失败样本另起业务回合。

在线命令完整形式：`<隔离 Python> <Skill>/scripts/runtime_diagnostics_with_login.py --base-url <目标 HTTPS 源> --devkit-root <当次认证 Pack 的 devkit 目录> --agent-id <本人专家 ID> --invocation-id <原关联 ID> --output <当前项目中的新 JSON 路径> --summary-output <当前项目中的新 Markdown 路径>`；本机交互登录，原始回执只留项目内。以下旧版段落提到的“优先”只在目标正式材料未提供更高版本时适用，不因旧版仍存在就绕过 v6。

标准 2.55 的 `developer.local-task.diagnostics.read/1` 只覆盖 `aigc.task.assets.localize/1` 本地化任务，不是所有私有视频能力任务的通用首错诊断；视频制作任务按其实际公开合同和回执另行核对。

目标实例提供标准 `2.55` / Pack `1.10.33` / DevKit `1.9.22` 的 `developer.local-task.diagnostics.read/1` 时，开发者可按本地 `task_id` 或原 `invocation_id` 查询 AIGC 素材本地化任务。先核对当次认证下载的 `operation-catalog.json`、`schemas/local-task-diagnostics-v1/{request,response,error}.schema.json` 和官方 `local_task_diagnostics_api_demo.py`；仅用专家所有者的普通账号及本机短时 `DCLAW_ACCESS_TOKEN` 调用，按完整 Draft 2020-12 Schema 校验回执。官方示例会将完整回执打印到终端；仅在当前 Agent 项目受控保存原件，向聊天、通用仓库或 Issue 只传脱敏摘要，令牌不进命令参数、文件或回传内容。此接口供开发侧诊断，不放入运行中的 Agent 包。

`found` 可分层核对 `host_accepted`、`host_dispatched`、`helper_received`、`task_status`、首错安全分类、`responsibility` 与 `recovery_action`；它只覆盖正式合同所列的本地化任务，不替代客户设备的文件、大小、摘要或 FFmpeg 产物回读。旧安装可在同专家、原客户会话和安装授权核验后只读定位；`no_record` 同时可能是无记录、越权或超过 30 天留存，不证明任务不存在，也不允许重派。每账号每分钟最多 30 次。`device_online_now` 仅为查询时状态；`helper_version_evidence=historical_detail_not_recorded` 时旧执行版本未知，`failure_evidence=historical_detail_not_recorded` 时旧内部首错未知，均不能由通用错误码反推。已知任务终态为 `failed` 时，再依据正式恢复规则、当前 Agent 状态及客户授权决定是否新建本地任务；只读诊断本身不恢复任务，也不改变旧签名 Agent 的安装作用域。

客户关联 ID 若以 `preflight-` 开头，先按目标实例正式合同将其作为专家 runtime 启动前的 `platform_preflight` 单独记录，并用已公开的开发者只读诊断按同一 ID 查询。它不证明 Agent 代码、本轮交互卡或 `aigc.task.assets.localize/1` 已执行；不得与此前普通 invocation 的 Host 故障合并。按回执核对首错来源、稳定错误码、责任线、恢复动作及本地助手/客户端版本，未取得回执时保持未归因。当前 Agent 的业务确需本地助手且声明 `local_helper=required` 时，不为绕过预检改成 `optional`；按正式恢复动作处理环境条件或将已核实的平台预检实现问题交平台，再从受影响节点继续。不要用重复客户回合代替只读诊断。

正式诊断若把运行前首错归为 `release_digest_mismatch`，开发侧先核对同一 Release 的现存签名 ZIP、manifest、目标 DevKit 重新计算的 `content_digest` / `capability_digest`、独立验签、上传回执、签名者登记和正式列表回读，并写明每项摘要来源及是否一致。只有这些开发侧证据互相一致，不能证明平台保存的授权摘要或预检实际读取值也一致；诊断未给出平台比较的两端值时责任仍未定。凭关联 ID 请平台核对实际 Release/installation、签名 manifest、授权记录和预检读取值，指出首个不一致项及生成时机，再按归属修复并做现役兼容回归。不要靠重新密封、重传同版或放宽必需能力声明来绕过未知差异；恢复预检后再单独验收被阻断的业务调用。

目标实例正式提供标准 `2.52` / Pack `1.10.30` / DevKit `1.9.20`、Support `1.18.38` 的 `developer.runtime.diagnostics.by-reference/5` 时，已知关联 ID 优先用本 Skill 的 `scripts/runtime_diagnostics_with_login.py --invocation-id` 查询 `/v5/`；官方 `runtime_diagnostics_api_demo.py --include-blocker` 是同一正式只读合同示例。先核对操作目录、请求及关闭响应 Schema；新材料缺失才按已核验的旧合同查询，`404` 不降级。v5 在 v4 的回合、Host 操作和独立任务表之外返回安全 `blocker`：阶段、稳定错误码、字段/约束、责任线、恢复动作和 `evidence`。先看回合结果、首错和 Host 事件：`completed/committed` 且没有记录运行失败时，`evidence=historical_detail_not_recorded` 只是诊断占位，不能据此请平台处理故障；若业务结果未满足，先核专家验收条件和正式 Host 结果。`task_acceptance=not_accepted`、`tasks=[]` 只说明本次关联回合没有新任务受理，不否定先前已受理任务。确有旧失败且 `evidence=historical_detail_not_recorded` 时，具体失败字段未留存；即使 `host_exception` 已知，也不能据 `responsibility=undetermined`、空错误码或 `not_recorded` 字段修改 Agent、推断设备状态或认定平台实现故障。按原项目授权凭关联 ID 请求平台核查，不靠盲目重复客户操作补历史证据。新回合若为 `evidence=recorded`，按安全错误码、约束和正式合同核对责任线：开发者请求、环境条件或平台实现分别由对应方处理；`task_acceptance` 与 `tasks` 仍独立判断是否受理，已受理任务须先只读回查。同一输入重试沿用原幂等键，修改输入须用新键。获得项目方授权且已核实旧回合无受理任务时，可在原会话沿用已核验的存量资产做一次受控复测；不要求另建任务或重复付费生成。普通账号 v5 查询通过不等于客户本地助手当前连接或完整 E2E 通过。

运行本 Skill 的诊断脚本前，按[本地 Python 环境](python-environment.md)准备并自检项目隔离解释器，后续查询、离线摘要和测试均显式使用同一解释器。`jsonschema` 缺失、版本或日期校验失败先归为开发环境问题；官方 DevKit bootstrap 的环境未包含此依赖不构成平台合同缺口。

当前目标实例若提供标准 `2.51` / Pack `1.10.29` / DevKit `1.9.19`、Support `1.18.37` 的 `developer.runtime.diagnostics.by-reference/4`，有客户关联 ID 时优先用本 Skill 的 `scripts/runtime_diagnostics_with_login.py --invocation-id` 读取；官方示例以 `runtime_diagnostics_api_demo.py --include-completed` 指向同一 owner-scoped GET。脚本先核对正式操作目录和请求 Schema，再按完整 Draft 2020-12 Schema 校验响应；v4 缺失才选旧版，HTTP `404` 不降级。v4 同时覆盖失败事务与 `runtime.complete` 后业务受阻回合，分别读取 `runtime_outcome`、`transaction_status`、`task_acceptance`、脱敏 `host_operations` 与独立的本地任务表 `task_evidence/tasks`。`task_evidence=available` 且 `tasks=[]` 只证明该可信作用域的任务表没有受理记录；历史 Host 事件或任务表为 `not_recorded` 时不能断言任务没创建。Host 事件、任务表和 Agent 首错各有范围，空事件不能定位具体 Host 调用；`runtime.complete` 也不证明业务成功。旧搜索接口只列失败引用，已知完成回合的关联 ID 直接查 v4；只读诊断不恢复任务，受理或终态未核实时保留幂等键并停止重复派发。

核查历史 AIGC 绑定时，若旧 `task_key` 没有可信记录，先在原会话不加 `task_key` / `content_revision` 过滤查询；正式合同只在当前可信会话内唯一兼容任务时返回 `found`。不要把当前 Agent 代码中的键当作旧任务键。带已知键过滤返回 `not_found` 只说明该条件无匹配，不能推翻同会话无过滤查询的唯一 `found`，也不能推断真实旧键或创建失败原因。若无过滤查询为 `ambiguous`、`not_found` 或不可用，保持失败关闭；开发者只读结果仍不能直接写入 Agent 状态。

目标实例按标准 2.50 / Pack 1.10.28 / DevKit 1.9.18 提供 `developer.aigc.binding.lookup/1` 时，已登录的专家所有者可用普通开发账号只读查询原客户会话的 AIGC 绑定：`GET /api/user/super-expert-publishing/aigc-tasks/v1/sessions/{session_id}/binding?agent_id={agent_id}`，可选原 `task_key` 及其 `content_revision`。先核对当次正式 `operation-catalog.json`、`schemas/developer-aigc-binding-v1/{request,response}.schema.json` 和 `devkit/aigc_binding_api_demo.py`；本机以 DClaw 短时访问令牌运行官方 demo，使用受控环境变量，不把令牌或原始回执写入聊天、命令参数、通用 Skill 仓库或 Issue。回执仅保存在当前 Agent 项目并按关闭 Schema 核验；同一账号每分钟最多 30 次。此查询按专家所有者、真实客户会话、租户/用户、兼容安装链和画布所有者限制，不接受客户端指定物理安装或用户。

`found` 可核对原 `material_task_id`、来源安装、内容修订与任务状态；`created_event_persisted` 仅表示同任务创建事件是否持久化，`current_workspace_references_task=false` 仅表示当前工作状态未精确引用原任务 ID，两者不证明 Agent 未写入的具体原因。`not_found`、`ambiguous`、`unavailable`、`invalid_request` 或越权/异常回执均不能作为重建画布的许可。开发者 GET 是诊断回执，不能代替已签名 Agent 的 `aigc.task.binding.resolve/1` Host 声明、授权、真实调用和后续快照；恢复步骤及 E2E 判据见[能力验证](capability-verification.md)。

客户端画布、卡片或其他平台界面动作报错时，先核对该动作是否属于专家 invocation 及当前诊断合同的记录范围。`developer.runtime.diagnostics.search/1` 的 `no_record` 只表示该窗口没有匹配的专家失败引用，不能排除界面请求的授权拒绝或执行失败；业务受阻但以 `runtime.complete` 正常关闭的回合也可能没有失败引用，`no_record` 不能证明此前有副作用的创建未发生。查询时的 `active_release_id` 也不能证明既有画布当次绑定的 Release。若正式目录未提供适用的开发者只读查询，把当次实际 Release/installation、被拒绝的 `capability_id`、请求关联 ID 分别记为“未取得”，保留时间与可见错误；不要按提示文字猜具体能力或修改 Agent。需要平台内部定位时，先取得当前项目的转交决定，再一次性请求脱敏标识及授权判定；取得实际拒绝能力后，才对照该 Release 的签名声明与安装授权。不要为补诊断而重复可能有副作用的界面动作。

先核对目标实例认证下载的 Developer Pack/DevKit 版本、摘要、官方 CLI `--help`、`publish --help`、`operation-catalog.json` 及公开 Schema。当前 Agent 项目的签名包、发布回执和正式 `publish list` 只读回读可由 Codex 检查；本 Skill 的 `scripts/publish_with_login.py --base-url <目标实例 HTTPS 源> --devkit <官方 DevKit 脚本> --output <当前 Agent 项目中的新回执路径> list` 使用普通账号交互登录并保存列表回执。列表只证明**查询时**的激活版，不能证明某次历史 invocation 实际执行的 Release、首错、事务或消息状态。`runtime.failure.read/1` 是已授权专家在自己的运行回合内调用的 Host 能力，不是普通开发者 CLI；也不能用一次新的客户回合冒充开发侧只读查询。

目标实例若公开 `developer.runtime.diagnostics.read/1`，先从该实例认证下载并核对正式 Pack、DevKit 及 `devkit/schemas/runtime-diagnostics-v1/response.schema.json`。标准 `2.32` / Pack `1.10.8` 公开的入口为 `GET /api/user/super-expert-platform/runtime-diagnostics/v1/tasks/{task_id}?agent_id=...`，目前没有对应 DevKit CLI。本 Skill 的 `scripts/runtime_diagnostics_with_login.py --base-url <目标实例 HTTPS 源> --devkit-root <已核验 Pack 的 devkit 目录> --agent-id <当前专家 ID> --task-id <当前任务 ID> --output <当前 Agent 项目中的新回执路径>` 用普通账号在本机交互登录，按正式 Schema 核对回执并保存完整诊断 JSON；可选 `--summary-output <当前 Agent 项目中的新 Markdown 路径>` 同时生成脱敏摘要与首错分类下一步。已有 JSON 回执可用 `scripts/summarize_runtime_diagnostics.py --receipt <原回执> --devkit-root <已核验 Pack 的 devkit 目录> --agent-id <当前专家 ID> --task-id <当前任务 ID> --output <新 Markdown 路径>` 离线生成摘要，不再登录或查询平台。两个脚本都不覆盖已有文件，也不在终端打印令牌或完整诊断。运行前核对当前目标实例仍提供同一合同，原始回执与摘要仅留在当前 Agent 项目，不提交到通用 Skill 仓库或 Issue。

该接口按专家归属与任务授权限制查询，越权返回 `404`；正式合同目前返回近 30 天、最多 50 条失败记录和当前消息表/Agent memory 的只读数量，不返回正文。`found` 只证明返回范围内有记录；`no_record` 不能证明历史从未失败。逐条核对 `release_id`、首次失败来源及阶段、事务状态和 `message_status`；`persisted` 及当前消息数量都不能单独证明刷新后曾消失的消息已恢复，历史未记录的失败与逐轮持久化状态也不能补造。诊断回执与当前 `publish list` 回读各有时间点，不能互相替代。缺少所需历史字段或结果不一致时，标“未取得/未归因”，再用下方模板请平台人工核查。

诊断摘要只依据公开字段提供检查线索，不提供完整 trace、可信卡片提交事件或逐条消息状态；生成摘要不等于问答交互卡、AIGC 或本地助手的真实运行验收。v2 摘要会合并相邻同类失败，但保留顺序、次数和时间；`field_path`、`constraint`、`contract` 只按回执展示，泛化的 `request/INVALID_VALUE` 不能推断具体参数。`stages` 或 `failure_events` 达到正式 Schema 数组上限时，回执可能截断，不能把数组长度当作实际总次数。

客户端若只显示关联 ID，先核对目标实例是否正式提供 `developer.runtime.diagnostics.by-reference/1`。标准 `2.38` / Pack `1.10.14` 的普通开发者只读接口按自己拥有的 `agent_id` 和客户可见 invocation 关联 ID 查询近 30 天脱敏首错，Schema 为 `devkit/schemas/runtime-diagnostics-v1/by-reference-response.schema.json`；不要求先猜任务 ID。可用上文同一脚本将 `--task-id` 换为 `--invocation-id <关联 ID>`，也可对保存的回执用离线摘要脚本同样传 `--invocation-id`；先核对目标实例版本、正式 Schema、专家归属和查询权限。`found` 的 `task_id` 可用于后续按任务查询，但两份回执的范围不同；`no_record`、越权或保留期外不能推定从未失败。若目标实例尚无此接口，再查项目已保存的可信任务 ID 与正式授权入口，不能把关联 ID 当作任务 ID；仍无法查询时把诊断记为“未取得”，由平台凭关联 ID 在其权限内核查。此情况本身不证明故障属于平台。

`first_failure` 只表示最早记录的错误；若后续重试成功或又有工具失败，按 `stages` 核对调用顺序与 `transaction_status`，把最终阻断阶段、类别分别记录为“已证实”或“未取得”。阶段事件如 `agent.execute.safe_failed` 只证明调用失败，不能据此推定拒绝类别。标准 2.38 的 by-reference Schema 不单列终止失败类别；确需平台 trace 才能定位时，按下方规则一次性请求脱敏核查，并核对正式合同是否已有等价字段。

标准 `2.39` / Pack `1.10.15` / DevKit `1.9.8` 新增 `developer.runtime.diagnostics.by-reference/2`，正式 Schema 位于 `devkit/schemas/runtime-diagnostics-v2/by-reference-response.schema.json`。普通开发者可按同一 `--invocation-id` 使用上述在线和离线脚本；在线脚本仅在已核验 DevKit 含 v2 Schema 时选 `/v2/`，旧版仍用 `/v1/`，收到 `404` 不自动回退。v2 的 `failure_events` 按时间顺序列出已恢复、终止或未记录的错误，`final_blocker` 单列本轮最终阻断的阶段、类别及责任线索；先区分 `recovered` 与 `terminal`，再核对最终阻断，不能把 `first_failure` 直接当作事务终止原因。`no_record`、`not_recorded` 以及 `unrecorded_fields` 表示证据未取得，提供方 code/param 为 `null` 时不补造。`stages` 中 `interaction.tool.invoked` 和 `interaction.operation.started/completed/failed` 是新回合的工具与平台操作线索；旧回合没有这些事件不能推定工具未执行。新版平台声称已修复 `agent_loop` 继承 JSON-only 默认模式，仍需本专家实际调用和客户端回执验证。

标准 `2.45` / Pack `1.10.21` / DevKit `1.9.13` 新增普通开发者 `developer.runtime.diagnostics.by-reference/3` 和 `developer.runtime.diagnostics.search/1`。先在已核验 Pack 的隔离 Python 环境安装 `jsonschema[format]>=4.20,<5`，使完整 Draft 2020-12 校验及日期格式断言都可用；新合同缺依赖时脚本失败关闭；旧 `/v1/`、`/v2/` 查询维持原有校验方式。DevKit 含正式 `/v3/` Schema 和操作目录时，上述在线脚本的 `--invocation-id` 优先选 `/v3/`；缺新版材料才选已发布的 `/v2/` 或 `/v1/`，收到 `404` 不自动降级。`/v3/` 只给 Host 终止拒绝的稳定 `error_code`、安全字段/约束、合同和恢复动作；需与 `/v2/` 的 `failure_events`、已恢复首错和 `final_blocker` 合看，不把 Host 错误码直接当作平台实现责任。`host_failure_detail.status=not_recorded` 表示该历史字段未留存，`no_record` 表示当前授权查询没有匹配失败，均不能补造根因；专家回合内的 `runtime.failure.read/1` 不变。

没有任务 ID 或关联 ID 时，在目标实例正式提供搜索合同的条件下，使用 `scripts/runtime_diagnostics_with_login.py --base-url <目标实例 HTTPS 源> --devkit-root <已核验 Pack 的 devkit 目录> --agent-id <当前专家 ID> --start <UTC 起点> --end <UTC 终点> --output <当前项目中的新回执路径> --summary-output <新摘要路径>`。窗口递增且不超过 24 小时，结果仅覆盖最近 30 天、单页最多 50 条失败引用；`has_more=true` 时在相同窗口显式传 `--cursor <next_cursor>` 查询下一页，不自动连续请求。找到 invocation 后再按目标 DevKit 已发布的最高正式关联 ID 合同查询，不把搜索列表当作根因；搜索无记录不能排除已完成但业务受阻的回合。脚本按正式目录与请求/响应 Schema 校验、在当前 Agent 项目保存新回执，不覆盖已有文件，也不打印令牌或完整诊断；离线摘要脚本按回执合同选择相应 Schema。查询仅限本人拥有的专家及获授权任务；`404` 不区分不存在与越权，`429` 表示限流，`503` 表示诊断不可读，均不改用管理员身份或客户新回合试探。

`final_blocker.responsibility=model_provider`、`reason=provider_rejected_request` 仅证明提供方拒绝了该次请求，不证明请求错误由提供方造成。先核对失败时 Release 的实际请求构造、`execution_mode`、`response_format`、工具 Schema 与目标实例的正式兼容合同；若 `provider_code` 或 `provider_param` 未留存，保持具体拒绝原因未知，并请平台在其权限内按 invocation 核查可取得的脱敏证据。旧版阶段事件只有 `safe_failed` 时，不把它解释成 v2 的终止类别。

若当前正式材料尚未公开适用的诊断接口及 Schema，开发侧只能整理已有项目证据和界面观察，把历史 invocation、消息写入/回读等字段标为“未取得”，按下方模板向平台申请合同并请求本次人工核查。不得猜测未公开接口、借管理员身份或平台私有源码补取数据；普通开发者不必安装客户端自动化工具。

“未归因”不能只作为状态结论。Codex 还须在当前 Agent 项目给出下一步可执行的排查路径，每一步写明执行者、所需回执或字段、不同结果如何分流；平台核查请求引用同一条路径。对客户端专家回合、平台能力调用或结果交付故障，先定位失败任务及**失败时**实际激活版本和安装授权；再沿同一 `trace_id` / `invocation_id`，按该 Agent 已发布入口的真实调用顺序核对 Host、模型或工具、Agent 校验与状态处理、最终提交回执，区分已恢复的首错和导致失败关闭的后续阻断；依据可证实的终止失败点及正式合同决定由谁处理，缺少类别时保持未归因。

若目标是修复并续接原任务，先保留该任务标识、已有业务状态和各失败回合的事务证据；核对失败是否提交、状态是否完整，再按归属修复并依据正式恢复合同在**原任务**复测。trace 暂缺时，只有项目方明确同意、对照确有区分力且不会造成未经授权费用或重复副作用，才可另建一次对照任务；对照结果不能代替原任务续接验收。不适合对照时明确等待平台 trace。其他失败阶段按其本地或发布门禁列出同样具体的下一步，不套用客户端运行路径。不得把某个 Agent 的调用顺序、错误码或对照提示词写成所有 Agent 的固定路径。

若用户报告消息刷新后消失或历史记录与即时界面不一致，分别核对用户输入和专家输出/失败提示的服务端写入、历史接口回读与客户端渲染；把专家事务的提交或丢弃与消息是否持久化分开判断。事务失败本身不能证明用户消息应被删除。缺少服务端证据时保持未归因，暂停会改变最近失败记录或造成副作用的试探回合，并把消息链路与专家首错放在同一份平台核查请求中。

| 现象 | 先检查 | 何时找平台方 |
| --- | --- | --- |
| 上传或激活失败 | 目标 Pack/DevKit 版本、包类型、签名、账号归属、原始回执与 `publish list` | 正式包缺命令、路由或回执异常；已上传但激活状态不明时先查状态，不盲目重传 |
| 专家对话失败 | 实际激活版、该版入口与错误分支、任务时间和模型；必要时一次普通对话对照 | 无法从本地证据定位首次失败，需平台按任务和时间查 trace |
| 卡片、AIGC、客户状态、文件或本地助手失败 | 该 Agent 是否实际声明并获授权；正式 Schema、真实工具回执、任务状态和产物 | 公开合同缺失、能力未按合同提供，或已授权调用在平台侧失败 |

### 工具安全审批与业务卡片

客户端对模型工具显示的安全审批、权限模式和调用参数，是平台工具执行门禁；客户在问答卡中选择、补充或确认，是 Agent 的业务交互。两者可同时出现在一个画面，但不能把审批弹窗当作客户提交回执，也不能用“业务卡无需开发方逐卡审批”推断工具在当前权限模式下不需审批。先以任务、invocation 和卡片 ID 关联实际工具请求、审批结果、建卡回执及客户提交；截图缺少这些标识时，不据此断言重复建卡、平台故障或某一方选择了权限模式。不要让客户为排错授予更大权限；按目标实例正式权限合同和当前任务授权核查工具门禁。

### 平台公共合同变更审查

公共能力故障提交平台时，标明正式能力 ID、版本、目标实例合同版本、最早失败节点和现役专家调用路径。同一能力的隔离重放、生产 Host 受理及客户设备结果分别列证，不用前一节点成功覆盖后一节点失败。`aigc.task.assets.localize/1` 的节点证据按[资产本地化指南](aigc-asset-localization.md)记录。

新增公共能力或修改合同时，先说明现有正式能力在功能、安全、可靠性或可验证性上的具体不足，并排除当前 Agent 的业务规则、状态路由、声明遗漏和客户端展示问题。一个 Agent 的真实案例也可能揭示公共合同缺陷；须证明缺陷位于共享接口或机制，并给出其他专家也可能遇到的场景或通用语义依据，而非仅提交该 Agent 的业务字段。提案写清通用操作、可信身份与作用域、输入输出、错误、事件、幂等、状态和授权边界；公共接口不按专家名称分叉，内部实现可在保持合同语义时替换。证据不足时保持待验证，不把猜测写成已定平台标准。

对已有公共合同，先列出可能受影响的能力 ID、版本、字段和现役专家调用路径。内部实现修复须保持已发布合同的行为；需要改变字段含义、必填项、错误、状态或权限语义时，提议新合同版本并与旧版并行，显式声明和授权新增可选能力。请平台维护方按正式标准核对旧签名专家、不同专家的代表路径、隔离与权限、升级及回滚回归，并给出部署版本、影响清单和回执。若平台改动影响已上线专家，平台维护方须与各专家责任方取得业务基线及发布输入，逐个完成适配、业务路径回归和新版本发布核对；专家责任方确认自己的业务行为与发布范围。Skill 维护者只记录可复用的接入与验证方法，平台维护方负责正式标准与插件实现。当前平台合同是否满足这些门槛仍以目标实例正式材料和实际回执为准。

## 3. 一份事实记录，按归属分别反馈

- **Agent 项目负责的业务或实现问题**：把影响范围、复现输入、预期/实际和本地测试交给该 Agent 的开发者或项目总控；修复走本 Skill 的 `optimization`，保留旧包及回滚证据。业务结果是否合格由项目方判断。
- **DClaw 平台合同、公共能力或实现问题**：给技术老师或平台管理员一份脱敏、可执行的完整任务。开发者不需要管理员账号；平台方在其权限内自行核查 trace 与合同，确认属于平台职责后继续修复、部署、回归和适用的生产只读验收，再一次回传最终结果。归属未明时不猜模块；平台核查若证明是 Agent 问题，回传脱敏依据供开发侧处理。
- **通用 Skill 的流程、说明或脚本问题**：同时向 Skill 维护者提交脱敏反馈。实际卡住的 Agent 或平台问题也按[卡点回传与每日补漏](blocker-feedback.md)进入私有仓库 Issue 供审核，但不自动视为 Skill Bug；若当前环境不能提交，就把脱敏草稿保存在当前 Agent 项目，等待可用渠道，不阻断不受影响的工作。只有经审核可复用的规则或工具问题才改共享 Skill；平台 Bug 和单个 Agent 的业务规则不写进通用 Skill。
- **归属不明或跨多层**：当前 Agent 项目保留“未归因”和最小复现，明确缺失的 trace/合同及 Skill 维护者是否需要关注。按主 Skill 已确定的沟通分工，Codex 在需要平台核查的同一回复中主动给转交人一段填好事实和具体问题的可转发请求，并说明回传位置；不得先让其“去问技术老师要结果”或自行决定技术问题怎么问。已有授权的直接沟通渠道才由 Codex 直接发送。待回执写入当前项目进度或交接记录；平台回复回来后由 Codex 逐项核对，分别推进项目、平台或 Skill 的后续工作，不让用户在多个对话里反复转述。平台明确无法提供历史字段时记录该边界，不重复索要。

## 给平台管理员的可转发核查请求

根据当前 Agent 项目已有证据把下方模板填成可直接转发的一份任务，在第一次需要平台处理时交给既定转交人；无值写“未取得”，不要编造 ID、错误码或版本。平台先在其权限内自行归因；若确认属于平台职责，同一任务继续修复或补合同、部署和验证，再给最终回执。转交人只负责传递，不负责查询日志、解释技术字段或追问中间结论。只有平台确实缺少开发侧独占的包、权限或业务决定时，才由 Codex 整理一次准确的阻断和所需输入。

> 请处理目标 DClaw 实例中超级专家 `[显示名 / agent_id]` 的问题。发生时间 `[时间和时区]`，任务/会话 `[可见标识或未取得]`，客户端关联 ID `[已知准确值或未取得]`，当时所选模型 `[名称或未取得]`。操作：`[最小步骤]`；预期：`[结果]`；实际：`[原文错误、状态或脱敏截图]`。开发方保存的签名包版本/摘要、上传回执和列表回读为 `[摘要或证据说明]`；当次实时 `active_release_id` 为 `[值或未取得]`。开发侧已核查并处理 `[检查项和结论]`，尚不能确定 `[具体未知点]`。请在平台侧自行核对实际激活版本，按任务与时间查 `trace_id` / `invocation_id` 或等价记录，找出首次失败环节、脱敏错误码及与正式合同的差异。若属平台职责，请在同一任务内修复或补正式合同、部署、回归，完成适用的生产只读验收并核对回滚条件；若证据指向 Agent，请给出脱敏依据和开发侧准确待办。最终一次回传归因、修复范围、部署版本、测试与生产核验回执、未解决项；平台能自行取得的中间日志和诊断无需交由转交人往返传递。确需开发侧独占的包、权限或业务决定时，请一次说明准确阻断和所需输入。无需返回密码、Token、私钥或完整客户内容。

涉及刷新后消息消失时，在同一请求中补充受影响消息的服务端写入状态、历史接口是否返回、客户端刷新后是否渲染及对应正式合同；只索取脱敏状态和定位标识，不索取消息正文。

若需要面向普通开发者新增只读诊断合同，另请平台说明查询权限如何同时限定专家归属与任务授权、有限时间窗口和跨页游标、查询时间与各字段证据来源、同一 invocation 与消息的不透明关联 ID、`no_record`/`not_recorded`/权限拒绝的区别、保留期和限流审计，并给出跨租户/跨用户拒绝、旧 Release 查询、失败事务与刷新后消息差异的验收回执。批准和部署前只作为能力申请，不把拟议字段当作现有 DevKit 输出。

管理员只回复“已修复”时，Codex 仍要核对目标实例的版本或正式合同、同一问题的复测结果和受影响 Agent 的实际行为；修复声明本身不等于业务验收。平台回复指向 Agent 问题时，保存其脱敏证据，再回到当前 Agent 的对应节点处理。

## 给 Skill 维护者的脱敏 Issue

实际卡点的 Issue 标题与必填字段按[卡点回传与每日补漏](blocker-feedback.md)执行；归属未明时写待归因，已解决时写解决依据。Issue 作者可能统一显示维护者账号；调用方标识仅用于分拣，不能充当身份认证。不得提交 Agent 源码、业务资料、完整截图/对话、密钥、签名包、原始发布回执或生产地址。维护者当次给出“通用规则需改 / 平台问题 / 当前项目问题 / 证据不足”的判断和依据；需要改 Skill 时验证受影响模式、记录版本并通知原项目复测。

## 结案条件

问题记录须写明责任归属或仍未归因、采取的动作、修复版本或平台部署回执、复测证据、未解决影响。更新 Agent 时分别核对新版本签名、上传、激活和客户端真实调用；只修 Skill 时不得声称已有 Agent 自动更新。未取得真实结果时，`e2e-verified` 保持 `false`。

同类故障反复出现时，不能以查到本次首错、修一个回合和让客户再试一次作为系统性结案。先按证据区分 Agent、平台公共合同/实现与消息客户端责任；归属未明时继续诊断，不预先指定修复方。责任方按已确认的故障类别核对共同机制、受影响版本/任务范围和历史同类事件，说明修复或防护如何覆盖该机制，并提供适用的故障注入与旧版/新版回归、可查询的脱敏诊断、上线监测和回滚条件；不可执行的验证项写明原因及替代证据。平台只处理其正式合同、公共能力和内部实现，Agent 开发侧负责业务路由、候选校验及业务状态。能续接原任务时，还须核对原任务真实复测和对应诊断证据；否则记录可获准的生产复测及其限制。单次成功不等于所有同类风险消失，也不承诺未来故障绝不发生。已转交的平台请求待回执时先保留待办，不连续追加零散请求；回执若只覆盖单次现象，再按缺项形成一份具体补齐清单。
