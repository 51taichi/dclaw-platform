# 三类平台能力的真实验证

本页供当前 Agent 的 Node 4/6 和共享 Skill 的跨项目验证使用。先按目标实例认证下载的正式 Developer Pack、DevKit Schema 和实时目录确定实际合同；下面是取证顺序，不规定业务内容或固定工具字段。每个 Agent 只测试本轮实际使用的能力；共享 Skill 维护者分别收集三类能力的代表性端到端证据，不能让一个 Agent 为凑覆盖而增加无关能力。

三类 API 示例按目标实例当次认证下载的操作目录、关闭 Schema 和下文门禁使用 `interaction_card_api_demo.py`、`validate_live_card.py`、`aigc_workflow_api_demo.py`、`local_task_api_demo.py` 作开发参考。标准 2.54 的 AIGC 资产本地化另见[专门指南](aigc-asset-localization.md)。示例中的 Host 或模型工具 callable 是合同测试适配器，不是密封运行时可直接 import 的平台对象，也不新增 Host 能力。新卡的完整组件 Schema 结构校验由 Support Plugin 在建卡入口承担，专家只需携带其业务校验；其他功能若在签名运行时自行使用第三方 Schema 校验器，须随专家包交付所需版本及依赖。

## 共用模型调用与失败终止

先核目标实例实际发布的能力目录、关闭 Schema、安装授权和签名包声明的 `agent.execute` 版本。若目标正式提供 `agent-execute-v2` 且运行插件已加载 v2，新签名包可声明能力 ID `agent.execute`、合同版本 `2`：只传非空 `messages` 默认走同一 AgentScope Agent Loop，也可显式传 `execution_mode="agent_loop"`；需要无工具的业务候选时显式传 `execution_mode="candidate"`，仅此模式可加 `response_format="json_object"`。`instruction`、`require_interaction` 和 `public_stream` 只用于循环；候选结果仍须 Agent 校验。逐项以同次正式 v2 Schema 验证，不从本地实验源码或旧 Pack 推定生产已支持。每个专家的 Skill、记忆、模型配置与授权隔离仍由该专家自身的包和安装决定；默认循环不会自动授予卡片、AIGC 或本地助手能力。

已签名并声明 v1 的包仍按 v1 默认候选语义运行；不能仅因平台升级而把它当作 v2，也不能直接改写签名包。更新同一专家时，先按其项目测试业务流程、卡片回执、AIGC 和本地任务，再签发声明 v2 的新 Release，验证新旧任务状态续接及回切。

目标正式材料提供标准 2.65 的 `agent-execute-v1` 时，先以同次认证 Pack 的 `devkit/schemas/agent-execute-v1/{request,response}.schema.json` 和 `agent_execute_api_demo.py` 校验实际组装的完整请求与响应。合法请求分三种：文本候选传非空 `messages`，可选 `recover_empty_reply`；JSON 候选再加 `response_format="json_object"`，也可选 `recover_empty_reply`；工具循环传 `messages`、`execution_mode="agent_loop"` 和顶层非空 `instruction`，可按合同使用 `require_interaction`、`public_stream`、`recover_empty_reply`。任务说明写在 `messages` 里不能替代顶层 `instruction`。候选模式不得混入 `instruction`、`public_stream` 或 `require_interaction`；工具循环不得混入 `response_format`。这些非法混用由关闭 Schema 拒绝，不能靠删除真实业务能力、猜 Host 容错或重复调用绕过。`public_stream=false` 在候选请求中同样是非法字段；候选回复由 Agent 内部校验后再决定客户可见结果。

Schema 通过只证明请求或响应形状；`agent.execute` 返回的 `text` 可以为空，JSON 模式也不保证符合 Agent 的业务 Schema。Agent 仍须校验候选文本、JSON、业务不变量及工具结果。`recover_empty_reply` 在工具循环中只允许合同规定的一次无工具文本恢复，不能当作已取得结构化 JSON、可信工具回执或业务完成。当前正式合同不接受调用方指定 `max_tokens`、thinking 控制或强制业务 JSON Schema；目标实例更新时以新 Pack 重新核对，不把这些版本细节固定为永久平台能力边界。

标准 2.66 / Support 1.18.56 描述固定模型目录与实际执行路由预检，以及先于整轮截止时间的 `agent_loop` 执行预算、模型请求/流事件和锁等待分类；DevKit 1.9.31 的机器 Schema 未因此改变。先核目标实例实际加载的插件修订与部署回执，不能仅凭认证下载的 Pack 宣称这些行为已在生产生效。已核实生效时，按客户会话显式选模优先于签名专家默认模型的顺序核固定模型目录；`auto/routing` 仍由平台路由。预检失败与 Agent JSON 候选解析分别归因，超时依同一关联 ID 的实际阶段证据区分。未部署或阶段证据未留存时保留未知，不推测模型返回内容；签名默认模型已退役则由该专家开发方更新签名包，再单独验证新 Release 与旧任务续接，不依赖静默回退或反复客户重试。

目标正式材料提供 `runtime-fail-v1` 时，按其关闭请求/响应 Schema 核对本轮 `invocation_id`、稳定 `error_code` 和可选 `diagnostic_ref`。错误码可为正式保留的旧码，或最长 64 字符的安全大写点分码；不要把内部异常正文、客户内容或 Secret 写入码与引用。每轮只在 `runtime.complete` 与 `runtime.fail` 中二选一调用一次；失败路径以 `runtime.fail` 得到 `accepted=true` 结束并丢弃本轮事务，不在失败后继续提交业务状态。失败提示、首错事件、事务终态和客户端结果分别核对，`accepted=true` 本身不证明客户已见提示或某项外部副作用已撤销。

直接 Host 建卡时，专家先读取实时详细组件目录并校验自己的业务不变量；Support Plugin 在创建入口按该组件公开的完整 Schema 校验结构。建卡后核对新卡 `interaction.status=PENDING` 与 `interaction.card.receipt/1` 的 `created` 回执在作用域、ID、任务键、修订、版本和 `event_id` 上一致，随后才 `runtime.complete`。卡片建议不合法或 Host 拒绝创建时，按标准 2.70 使用同轮模型给出的文字问题继续，不伪称卡片存在。若同一 invocation 在完成前发生其他失败、超时或取消，标准 2.65 的平台补偿只取消该 invocation 新建且仍为 `PENDING` 的卡；幂等重放、其他 invocation 创建的卡和已 `SUBMITTED` 的卡不受此补偿影响，替换新卡失败时恢复原 `PENDING` 卡。Agent 不把本地异常捕获或 `runtime.fail` 请求当成取消回执；发生上述情形时按正式卡片状态/回执及客户端结果核实实际补偿，不主动清理无关卡片。旧已激活 Release 保持其原合同与业务实现，新版指南不证明旧包自动修复。

## 共用证据记录

目标实例正式提供 `developer.runtime.diagnostics.by-reference/6` 时，按[故障反馈](runtime-feedback.md)逐条核对 `findings[]` 与 `local_tasks[]` 的终态；Host 首次可见异常、历史未记录细节、诊断证据源 503 和当前无记录分别保留原语义。开发者只读诊断有助于定位，不替代该 Agent 的真实调用、客户端结果或设备产物验收，也不授予密封专家新的运行能力。

目标实例正式提供 `developer.runtime.diagnostics.by-reference/5` 时，按[故障反馈](runtime-feedback.md)核对已记录的安全 `blocker` 与 v4 延续的 Host 操作和独立任务表；历史 `evidence=historical_detail_not_recorded` 只证明该次具体首错未留存，不能当成修复依据。DevKit Schema、普通账号只读查询和客户真实调用分别留证；旧任务的 v5 查询不代替受控复测或设备产物验收。调用 `aigc.task.assets.localize/1` 时，另按[逐节点证据链](aigc-asset-localization.md)分别核对 Agent 请求、生产 Host 受理、本地助手派发与设备下载。

目标实例正式提供 `developer.runtime.diagnostics.by-reference/4` 时，客户关联 ID 可按[故障反馈](runtime-feedback.md)通过普通开发账号只读核对失败事务及 `runtime.complete` 的业务受阻回合。分别记录回合结果、Host 操作事件、任务受理和独立任务表；`not_recorded`、空 Host 事件或客户可见提示都不替代可信任务终态。旧实例继续使用其已核验的诊断合同。

正式 Pack 的包装器与同次认证下载的标准、DevKit 操作目录或关闭 Schema 不一致时，分别保存输入声明、包装器报错和独立 DevKit 结果。真实调用需要的声明不能为通过包装器而删除，官方包也不在项目中打补丁。先核对正式标准是否允许不依赖包装器的独立 DevKit 构建：若允许，按同一冻结输入完成 `digest → validate → build → verify`，再凭正式服务端发布回执和列表回读判断发布状态；包装器失败仍单列待平台澄清，不能写成已通过。独立路径没有正式依据或自身门禁未通过时，受影响制包与发布保持阻断。单独的 `validate=valid` 不证明密封或激活。

在当前 Agent 项目保存一条能力记录：能力、Skill 版本、模式/Node、目标实例与正式 Pack/DevKit 版本、Agent Release/installation、授权、任务或 invocation ID、实际工具回执或可核对 trace、客户端观察、状态或产物回读、失败及恢复结果、证据路径和未解决项。原始客户内容与凭据留在项目的受控位置，不进入共享 Skill 仓库或 Issue。

诊断失败回合时，先核对目标实例认证下载的 DevKit 是否提供 `runtime-diagnostics-v2/by-reference-response.schema.json`。有该正式合同且客户可见关联 ID 时，按 `/v2/` 查询同一专家的回执：依 `failure_events` 顺序区分 `recovered` 与 `terminal`，用 `final_blocker` 判断最终阻断；`first_failure` 仅作最早错误线索。`status=no_record`、`final_blocker.status=not_recorded` 与 `unrecorded_fields` 均保持未知，不补造提供方信息。没有 v2 Schema 的旧实例按 `/v1/` 合同处理；一次 `404` 不能作为改查旧接口或越权探测的理由。诊断只为定位，仍须按下文取得真实能力回执和客户端结果。

逐项标为 `不适用`、`合同已核`、`本地测试通过`、`真实运行通过` 或 `阻断`。真实调用、客户端结果和最终状态或产物缺任一关键证据时，不记为 `真实运行通过`。发布激活、静态能力声明、Pack 测试、模拟 Host 和模型自述分别记录，不能替代真实运行证据。

代表性端到端验证从目标用户会提供的正常输入或现有任务的自然续接进入，按当前 Agent 已确认的业务流程让其自行提出必要交互、取得可信结果并推进到交付。人工选择和授权仍按实际业务与平台合同执行。为隔离某个接口而直接指定阶段、固定口令、任务 ID 或工具调用的定向测试可以单列，但不能代替正常使用路径的证据；若该 Agent 本来要求命令式输入，以其业务基线为准，不由本 Skill 改写。

多段任务需要把上一步结果用于下一步时，先从目标实例正式 Pack 的 Host 调用表、能力与操作目录、请求/响应 Schema 和运行时实时工具目录寻找回读路径；再核对签名声明、安装授权、可信身份与任务作用域，以及密封 Agent 实际能取得的是原始结构化结果还是仅有 `agent.execute(agent_loop)` 的模型候选。找到路径后用同一任务的受控调用验证字段和失败结果。若没有公开的确定性回读合同，记录准确缺口并停止受影响的下游状态转换；不根据模型正文、截图或静态 Schema 补造任务和产物标识。

## 问答交互卡

业务先判定答案形状，再选唯一真实 API 类型：一个已知选项用 `one_choice → single_select`，可并存的已知选项用 `many_choices → multi_select`，无法可靠列全的文字答案用 `open_text → question_form`，真实本地文件用 `local_file → file_selector`。`single_select_or_multi_select` 只可作为专家内部说明，不是 API 枚举值。DevKit `interaction_card_api_demo.py` 的 `component_for_answer` 和 `create_question_card` 会在 Host 调用前拒绝模型建议类型与业务决定不一致；`examples/interaction-host-v1/card-type-examples.json` 含四类完整草案。每个示例及当前专家实际卡片都需先通过 `schemas/interaction-card-create-v1/request.schema.json` 和目标实例详细目录的 `components[].schema`，并另查本专家的稳定 ID、选项顺序、选择数量、单问题 item 或文件限制。静态示例不是实时目录，也不能替代可信建卡回执。

新建或更新专家的问答卡按标准 2.70 使用 `card_or_text`，让卡片和普通输入同时可用；旧签名包仍按其原 `input_policy` 运行。`card_only` 的待提交卡会阻塞普通文字，`card_or_text` 与 `concurrent` 的文字不构成可信卡片提交。单选的预设选项与卡内自行输入互斥；多选可并存，卡内自行输入计入最少和最多数量。文字回答完整时按正式取消合同关闭旧卡并继续；只回答部分时关闭旧卡，仅对剩余缺口建议新卡。Node 6 分别验证客户端卡片展示、自由文字续接、可信提交、旧卡关闭、部分回答和迟到提交，不能用本地占位退役冒充平台已取消。

目标实例须提供 `interaction.capabilities.list/1` 与 `interaction.card.create/1` 的公开请求/响应 Schema、操作目录和实时详细组件目录。组件目录不是本地公共 Component Registry；能力 ID、旧模型工具说明及 `interaction.card.receipt/1` 回执也不能代替直接 Host 调用合同。目标实例若另发布错误 Schema，一并核对；仅缺独立错误 Schema 不阻断已公开的请求/响应合同。未公开的错误字段保持未知，调用异常或回执不合格时按实际阶段记录并处理。请求/响应合同或必要的失败语义不足时，受影响的 Node 4 接线、密封及发布保持阻断；旧已签名专家按原合同运行。

1. 按已签名版本和目标正式标准选建卡入口。旧专家的模型工具路径保留原合同。标准 2.71 的新建或更新专家在每次客户交流先做一次无工具模型调用；同一候选给出非空业务回复、可独立理解的文字问题及零或一张卡片建议，不提前公开候选流。每轮最多采集一个问题；确需采集时必须建议单问题卡，`question_form` 只有一个 `item`。建卡后正文只能陈述背景，不能再问第二个问题。无采集问题时保持纯文本，纯解释或修辞反问不建卡，客户问候不阻止模型建议卡。声明 `agent.execute` v2 时显式用 `execution_mode="candidate"`，需要 JSON Object 可设置 `response_format="json_object"`；工具工作另用 `agent_loop`，不得在未完成卡片决策前重复建卡。模型建议缺失、不合法或 Host 建卡拒绝时记录原因并使用同轮单问题文字，不为修卡再次调用模型。
   专家按阶段、业务字段、稳定 `task_key`、修订、组件类型、选项或问题 ID 顺序校验业务不变量，再读取所选组件实时详细目录。Support Plugin 在 `interaction.card.create/1` 入口用公开的完整 Draft 2020-12 组件 Schema 校验 `request.card`；专家无需为这项结构校验自带 `jsonschema`。DevKit `validate_live_card.py` 与完整目录 fixture 用于开发期正反例回归，静态 fixture 不代替目标实例实时目录。外层 Host 请求仍按正式关闭请求 Schema 核对，非法业务身份或缺失必要能力时不得建卡；创建结果必须以真实 Host 回执确认。模型候选、组件目录和创建阶段的失败分别留脱敏诊断，不把前一阶段错误误写成后一阶段故障。
2. 在获准的测试任务以稳定 `task_key`、修订和幂等键创建卡片，核对真实 `interaction_id`、`PENDING` 状态与 `interaction.card.receipt/1` 的 `created` 回执在可信作用域、ID、修订、版本和事件上匹配，之后才提交客户回复并观察客户端展示；用户实际提交后，保存提交回执和对应 invocation。四类已发布组件均走同一 Host 边界；`file_selector` 另核对 `interaction.file.select/1` 的声明和授权。模型工具兼容路径中的 `interaction.tool.invoked` 证明模型进入插件工具；直接 Host 路径须核对 Host 原始调用与回执，不以模型工具事件代替。`interaction.operation.started/completed/failed` 分别证明平台操作发起、完成或失败；旧回合缺这些事件不能推定操作未执行。
3. 若目标正式材料提供 `interaction.card.read/1` 等可信作用域的 Host 读卡能力，先核对签名声明与安装授权，再按其关闭 Schema 读取原始结果；`not_found`、非 `SUBMITTED` 或答案/提交回执缺失时停止写入。与模型循环中的 `interaction_card_status` 分开留证；旧合同按其实际结果边界核验，模型复述不能充当 Host 原始结果。
4. 对已提交答案核对卡片 ID、任务键、修订、版本与提交 `event_id`，并确认 Host 按正式合同隔离本安装与任务；按目标正式合同的序列化规则重算答案摘要，在任务状态中对事件去重，随后才执行业务状态转换并回读。只有答案哈希、有限历史列表或用户自由文本时保持待核。
5. 检查非法卡字段走同轮文字回退、业务不变量被改写、错误创建回执、旧卡、幂等重放、重复提交、跨主体、读卡失败与模型绕过必要工具的路径，并验证客户点击后同一任务续接。增加同一任务状态重复进入的回归：原键须重放相同的完整建卡载荷；模型重生草案造成实质变化时，须递增修订、换键。已有阻塞的 `PENDING` 卡时，以可信状态核实旧 `interaction_id`，在新建卡 `request.replaces_interaction_id` 中显式引用；旧卡 ID 或状态未核实则失败关闭。覆盖不带替换字段而遭 `INVALID_REQUEST`、带正确字段成功替换、重复请求及旧卡提交失效；`IDEMPOTENCY_CONFLICT` 也记录真实拒绝并失败关闭，不把换键重试当作通过。不得在答案未核验时写入确认状态或答案驱动的产物。客户端展示、可信提交、工具读取和 Agent 状态更新分别留证。

续接旧签名包的 `card_only` 卡时，先核对现有 `PENDING` 卡是否锁住消息输入；输入锁发生在 Agent 收到新消息之前。先按该 Agent 的业务含义判断旧卡是否有可安全提交的选项；若不能安全提交，只使用目标实例正式支持的取消或替换入口，不让客户猜选项或反复发送。新包的 `card_or_text` 要单独验证客户直接输入、旧卡真实取消或替换、部分回答的新卡和迟到提交；旧卡截图或 Agent 的替换分支测试不能代替整条路径。

正式 `session.context.interaction_receipts` 是当前可信安装与任务最近更新的最多 20 张卡的回执集合；文字回合也可能再次带来历史 `SUBMITTED` 回执，数组中的“未处理”不等于本轮客户刚提交。先按当前待处理卡的 `interaction_id`、`task_key`、修订、版本及可信安装/会话作用域关联，再决定是否读卡或处理新文字意图；不能任取一个旧回执抢占当前请求，也不能因某张卡不在有限列表中就推定它不存在。当前卡真实提交仍须用 `interaction.card.read/1` 核对答案和提交回执，再按事件去重写入业务状态。Node 6 同时覆盖“历史提交回执 + 新文字请求”、当前卡提交、回执重复出现及列表截断的分流。

跨 Release 保留的卡片占位，在继续原卡或其状态不明时先按当前安装的正式 `interaction.card.read/1` 对原 ID 核验。`not_found` 只说明当前作用域不可读；若客户的新消息已实际到达 Agent，可解除本安装状态中的旧占位，但不得据此记为旧卡已取消、已提交或客户已作选择。若要应用 `SUBMITTED` 的答案，必须核对答案、提交回执和事件，再写入对应业务状态；若新的独立文字请求依当前 Agent 已确认的业务优先级明确取代旧卡，可在核对旧回执的可信作用域、卡 ID、任务键、修订和状态，以及已保存的平台卡片版本后，仅将旧事件记为忽略并解除相应占位，不应用未读答案，也不把这一路径用于当前卡的真实提交。仍为 `PENDING` 的卡不得仅因其不符合本轮目标就静默丢弃，应按客户可操作的安全提交或正式取消/替换合同处理。读卡异常、回执身份冲突或当前卡答案/提交回执不合格时保持失败关闭；旧卡客户端状态与新卡展示另做真实回合验收。

## AIGC

1. 核对本 Agent 声明、安装授权和目标实例的运行时工作流目录、所选 `WorkflowBlueprint` Schema；只读目录成功仅记目录已核。目标合同以 `agent.execute(execution_mode="agent_loop")` 动态提供 `aigc_workflow_catalog` / `aigc_workflow_create` 时，不叠加 `response_format="json_object"`；目录中的实时 `workflow_schema`、可用节点和模型共同约束创建请求。AIGC 工作流任务卡与问答交互卡的建卡合同不同，不能互用回执。
2. 取得本次业务所需的生成授权与费用边界后，按正式合同创建一个有界任务，核对创建事件与任务绑定的 `material_task_id`、画布及修订一致，再保存真实任务 ID、工具回执、状态查询与按当次合同允许的续跑记录。目标实例若支持绑定工作流卡，客户经认证点击卡片续跑可按正式合同继承该任务的工作流创建授权；Agent 自己调用续跑仍须独立声明并获授权。卡片导航或客户点击成功不能证明 Agent 拥有续跑权限。创建结果未确认时，只有正式只读路径能按同一 `task_key`、内容修订和蓝图排除既有任务，且再次创建不会重复计费或生成，才可重试；缺查询合同或结果冲突时保留尝试记录并停止受影响的下游链路。
3. 核对最终产物的引用、可访问性与客户侧结果；保存失败、取消或恢复路径的实际回执。任务已提交、状态完成和客户能取得产物是三个不同结论。

对本轮新增或改动的动态工作流创建入口，先用[创建副作用门禁](aigc-effect-route.md)的当前 Agent 代码注入目录已读但无创建、创建成功但模型正文为空、创建终态未知和重复回合。开发期 `AIGC.OK` 与 adapter 审阅仅证明这些受控分支合格；目标实例真实工具注册、创建持久化和客户可见任务卡仍需各自的生产回执。旧已签名 Agent 在下次优化时按当前版本重新审计，不因 Skill 更新自动通过或改变。

若客户页面已有工作流卡而 Agent 状态缺可信 `material_task_id`，先核对当次实际 Release、已发布创建代码、原始创建事件或可用的绑定回执，以及状态写入是否完整。`agent.execute(agent_loop)` 的最终模型正文、可见卡片和“已完成”文字都不能独立证明真实 ID，也不能用于补写绑定。目标实例若提供开发者只读绑定查询，先按[故障反馈](runtime-feedback.md)在当前 Agent 项目取得受限回执，用于判断既有任务是否存在及工作状态是否精确引用它；开发者 `found` 不会自动修复已签名 Agent。无正式查询或结果不唯一时，历史创建子因和任务 ID 保持未取得；停止快照、本地化和重复创建，按项目转交决定请求平台核查。

标准 2.50 / Pack 1.10.28 / DevKit 1.9.18 在插件 1.18.36 起提供可选 Host `aigc.task.binding.resolve/1`。主动恢复旧会话的 Agent 下一签名版本须声明该能力并获安装授权；以目标实例的 `operation-catalog.json` 和 `schemas/aigc-task-binding-v1/{request,response}.schema.json` 接线。原 `task_key` 有可信记录时可用它过滤，并可附正整数 `content_revision`；修订不能单独传。旧键不可核时不要用当前代码的键值猜历史键，可向 Host 传空对象；它只在当前可信会话内唯一兼容任务时返回 `found`。精确过滤的 `not_found` 仅排除该过滤条件，不能推定会话没有其他旧任务，也不能在未核清时重建画布。Host 按已提交的状态连续性回执核对同租户、用户、专家、会话、兼容安装链及画布所有者；`found` 返回 `material_task_id`、`source_installation_id`、`content_revision` 和 `task_status`。Agent 先从可信创建尝试或已存绑定找到原任务所依据的历史作品修订，不以 `latest` 是否存在作为恢复门槛；核对响应修订与该历史修订一致、原状态没有冲突，再以 `aigc.task.snapshot/1` 回读同 ID 任务与非空画布，全部通过后才保存原绑定。未知旧键保持未知，不写入推测值；后续作品已有新修订时，恢复旧任务不表示其产物可自动用于新版，是否续用或切换由当前 Agent 的业务规则决定。`found` 本身不证明资产可用或客户端续接成功。`not_found`、`ambiguous`、`unavailable`、`invalid_request`、非关闭 Schema 回执或身份/状态冲突均失败关闭，不猜 ID、不改写原作品、不重建画布。旧已签名 Agent 不会自动获得此能力。

目标实例采用标准 2.49 时，客户在 AIGC 页面点击“完成并返回会话”后由平台校验归属并持久化 `ACCEPTED`；Agent 以可信任务绑定回读该状态及产物，不调用模型审核。新建或更新的专家不声明或依赖 `aigc.asset.submit`、`aigc.review.complete` 的旧写入路径，也不把 `aigc_task_review` 当作完成步骤。旧已签名专家的同名 review 工具仅在原声明及授权下只读兼容：已完成任务的 `status=ACCEPTED`、`completion_source=customer`、`review_performed=false`、`write_applied=false` 表明完成来自客户操作，未完成时按真实状态与 `customer_action_required` 处理；不能把兼容回执算作 Agent 审核。客户端显示完成仍需可信快照与客户侧结果核对。

将 AIGC 产物继续用于另一工作流或本地任务前，按正式回读合同核对上游任务 ID、任务和节点状态、资产标识、媒体属性及授权作用域，在作品状态中保存可追溯的引用。目标实例提供可选 Host `aigc.task.snapshot/1` 时，声明并取得安装授权后，以绑定的 `material_task_id` 读取原始快照；只考虑同任务、同画布、同节点、同用户且对应成功 job 的 `generation_assets`。

使用已完成任务的产物时，按当次正式合同核对平台持久化的完成状态与绑定资产；若快照给出 `submitted_asset_id`，所选已提交资产还须与之相符。若要在工作流进行中使用成功节点，先确认目标实例正式允许逐节点可信读取及下游使用，再核对每项的节点 ID、job ID、资产 ID/类型、任务版本和当前授权；节点重生成后重新核对所选资产。Schema 允许 `submitted_asset_id=null`、已提交示例或客户端“已完成”均不能单独证明部分节点可供下游。未成功节点、来源不符或合同不明确时停止受影响的下游任务；不因其余节点未完成就自行要求整条工作流结束。`agent.execute(agent_loop)` 返回的模型正文或客户页面可见媒体，不能单独充当密封 Agent 的可信资产回执。

目标实例提供 `aigc.task.assets.list/1`、`aigc.task.assets.localize/1` 时，按当前标准 2.54 和[资产本地化指南](aigc-asset-localization.md)从可信任务绑定与快照进入，列出同任务成功资产，提交有 `usage`、`slot`、唯一 `order` 和合法 `destination` 的计划；Host 在受理前核验公开 OSS 地址，再以 `local.task.read/1` 核对终态与客户设备落盘。合同已核、离线 Schema 通过、本地化真实完成和另一本地任务成功消费分别留证；没有跨任务输入合同就停止后者。

标准 2.56 / Pack 1.10.34 在受支持实例新增密封 Host `local.task.outputs.bind/1`，为原成功本地化任务的选定槽位颁发同一 invocation 可用于 `local.task.start/1.local_file_bindings` 的短时引用；按[本地能力包与视频制作](local-video-capability.md)逐项核对 `bound`、槽位与顺序、设备文件复核、目标任务受理及终态。旧标准无此操作时沿原阻断判据。`bind` 的存在或离线草稿通过只把跨任务输入记为“合同已核/本地测试通过”，不记为真机执行通过，也不解除私有能力托管、签名、注册和安装授权门禁。

## 本地助手

涉及视频制作、文件选择或其他多阶段本地能力时，先读[本地能力包与视频制作](local-video-capability.md)：公共 FFmpeg Component 只是依赖，实际任务须有目标实例正式发布且已注册授权的公共或私有 `capability_id`；平台交接候选不能代替生产目录和设备回执。密封 Host 与 MCP 网关工具的入口和回执分别核对。

标准 2.57 起，目标实例正式提供 `local.runtime.prepare/1` 时，先核对新签名 Release 的声明与安装授权、正式请求/响应 Schema、目标设备 `ready` 和准确能力包版本，再调用本地任务；`preparing`、设备未就绪和拒绝都不能记为已安装或已启动。准备、文件绑定、任务受理、终态及客户本地产物分别留证。官方 Pack 的包装器若漏认正式目录中的新能力，按本页上方的同版合同冲突规则记录阻断，不删除真实声明或补写未获授权的能力。

本轮使用开发方私有本地能力（如 FFmpeg 合成包）时，其 artifact 的正式 HTTPS 托管由开发方提供并保证客户网络可访问；平台的公共 Component 对象存储不等于开发方私有托管入口。先冻结正式 URL、大小和 SHA-256，再生成签名描述符；signer 信任、注册与安装授权由平台按正式合同完成。没有正式 URL 时，仅将该私有能力链路记为制品准备阻断，不用占位地址运行其发布门禁。标准 2.54 的平台通用 AIGC 素材本地化使用 Host 校验过的稳定公开 OSS 地址，不使用这类开发方 artifact URL。

上游若是 DClaw AIGC 画布资产，先区分资产身份与设备可读输入。正式快照中的 `asset_id`、`asset_kind` 不能直接填进仅接受 `local_file_ref` 的本地文件绑定，也不是下载 URL；`file_selector` 取得的引用只覆盖客户设备已有文件。按当前标准 2.55 的[资产本地化指南](aigc-asset-localization.md)验证同任务资产下载；旧实例仍以其当次正式合同为准。需要再交给另一剪辑任务时，单独核对跨任务输入与授权 Schema，不能从本地化任务的 `res/`、`assets.json` 或 `artifact_ids` 猜可复用路径。合同缺失时停止该下游任务，不把“请客户先下载再选择文件”的替代路径记作原需求通过。

1. 仅选实际需要客户设备执行的代表性任务。核对目标平台变体、完整 Component 注册表、签名描述符、授权和本地助手/Runner 的正式合同。能力包属于独立签名与登记链路：按目标正式标准确认其 signer、公钥信任、管理员登记和安装授权；普通账号能发布超级专家，不自动取得能力包登记权限。接线前将上游已取得的可信文件或资产引用与拟调用能力的正式 `capability_id`、输入 Schema 和命名绑定逐项对照，核实媒体类型、数量、顺序与必填加工参数；缺少专用能力描述符或输入不匹配时先处理当前 Agent 的采集与映射，不能借 Host 启动合同存在就提交占位 ID 或错误类型的素材。
2. 在获准的客户或测试设备上核对所需组件的下载、SHA-256 验签、安装或命中已验缓存，再执行确定参数的本地任务；保存 Component 版本、安装与执行回执。
3. 回读客户本地实际文件或等效可核对结果，检查任务失败、重试及恢复。仅有依赖声明、注册表 `available` 或 Agent 返回文件路径，不算本地执行通过；不需要本地助手的 Agent 记为 `不适用`。

当可信卡片答案、本地文件引用或已核验的上游产物驱动 `local_task_start` 等有副作用的操作时，另核对密封 Agent 可用的可信结果路径：同一任务及授权作用域、实际 `capability_id`、请求幂等键、`task_id`、受理状态、后续状态和错误。目标实例提供可选 Host `local.task.start/1`、`local.task.read/1` 时，先核对签名声明、安装授权和 `local-task-host-v1` Schema；从原始 `local.task.receipt/1` 核对受理状态、任务 ID、能力 ID、原幂等键，后续按同一任务读回状态、错误、结果摘要与不透明产物 ID。按正式 Schema 分支校验成功回执；`artifact_ids=[]`、`result_sha256=null`、`idempotency_key=null` 在标准 2.55 合法，非空键须匹配原请求，不能额外要求这些字段非空或把空值当作设备产物证据。实际本地执行成功还需同任务设备结果与业务所需产物回读；业务完成由 Agent 检查。取消使用独立 `local.task.cancel/1` 合同，不把停止读取当成已取消。`not_found`、`unavailable` 和 `rejected` 分别留证，不把它们当作未启动的证明。旧实例按其正式合同查等价受限回读；工具响应 Schema 仅定义平台工具的返回形状，不证明 `agent.execute(agent_loop)` 把原始结果交给 Agent。模型候选即使非空，也不能证明工具被调用、任务受理或状态为 `queued`。目标 Pack 若仍未公开 Agent 可独立核验的结果路径，才记录公共能力需求，不自行命名或调用内部接口。

跨 Release 续接作品状态时，单独核对其中保存的本地 `task_id` 能否在新 installation 的授权作用域读取。标准 2.54 的 `local.task.read/1` 对跨安装等跨作用域读取返回 `not_found`；状态文件带来了旧 ID，不表示旧任务随状态迁移或取得新安装的读取权限。记录新旧 installation、原受理回执与新回读结果；若目标实例提供标准 2.55 的 `developer.local-task.diagnostics.read/1`，开发者先按[故障反馈指南](runtime-feedback.md)跨安装只读核对旧任务终态；否则使用原安装仍可用的正式只读路径或授权设备任务中心。开发者诊断回执不扩大运行中 Agent 的读取授权，也不能直接当作客户会话的可信输入。旧终态未知时保持阻断，不自动重发，也不把 `not_found` 告诉客户为“任务不存在”。确认旧任务失败且失败原因已有可执行的恢复办法后，当前 Agent 才按其业务规则提供恢复选择；客户确认重试且原输入仍有效时，按当前安装作用域使用新幂等键创建新任务。旧 Helper 的执行错误与 Agent 的提示或恢复路径分别归因，设备已连接不等于旧任务成功。

失败关闭：可信回执缺失、与本次幂等键或任务作用域不符、状态不明、重复提交或回执丢失时，保留未消费的选择和原幂等键，标记任务受理状态未知；先按正式只读路径查询，不能确认时停止受影响链路并请求平台核查。不得把“未取得回执”断言为“没有启动”，不得换键重试造成重复任务，也不得对客户宣称已启动或已生成。只有可信受理与 `task_id` 可核对时才更新为已提交；`succeeded` 与客户本地成品仍须另行回读。

若真实工具或结果的公开合同不足，先按[试跑问题处理规则](runtime-feedback.md)检查现有工具、授权和实际回执。只有具体不足得到核验且开发侧无法解决时，才记录平台能力缺口；待平台提供正式合同后从受影响节点继续。共享 Skill 的三类代表性链路均有真实运行证据，才可报告主体能力覆盖里程碑；这不是每个 Agent 的统一发布门槛，也不是 DClaw 官方验收比例。

跨安装成功来源任务的下游步骤，应把“旧任务在新安装可读”和“旧产物可按兼容安装链绑定”分别判断。新安装的 `local.task.read/1` 返回 `not_found` 不能证明来源任务失败，也不应单独阻断无副作用的下一步需求确认或建卡；开发者跨安装诊断只用于项目核查，不能写成运行中 Agent 的可信结果。若当前作品状态保存了可信来源 `task_id` 与槽位，且目标正式合同提供并授权 `local.task.outputs.bind/1`，在真正消费文件时以该 Host 的来源任务、兼容安装链和设备文件复核为准；只有 `bound` 且引用、设备和槽位核对通过，才在同一 invocation 启动下游。绑定失败时按准确状态停止下游，不重下素材、不伪造成功，也不把跨安装读取 `not_found` 当作文件不存在。未提供正式绑定或手选合同的目标实例继续保持受影响执行链路阻断。

## 实际使用路径的最小检查表

| 路径 | 接线与定向反例 | 客户端结果 |
| --- | --- | --- |
| 问答/文件交互卡 | 实时详细目录、平台完整 Schema 校验、专家业务不变量；非法字段文字回退、错误 `created` 回执、幂等重放和跨作用域拒绝 | 真实 `PENDING` 展示、文字输入、旧卡关闭、客户提交、可信读卡与同任务续接；文件选择另验授权 |
| AIGC 工作流 | 实时蓝图、节点和模型、创建事件/任务绑定；错误绑定、未提交、失败 job、资产不匹配及重放 | 客户操作后以 Host 快照核对同任务成功 job 的提交资产及可访问性 |
| AIGC 资产本地化 | 正式 `list/localize/read` Schema、同任务成功资产、唯一顺序与目录；旧 Helper、断线、丢回执、错误资产和越权拒绝 | 客户设备真实下载并核对终态、`assets.json`、文件大小与摘要；另一任务消费另验合同 |
| 本地助手 | 注册与授权、同键 `start/read`、失败/离线/丢回执/非终态和跨作用域拒绝 | 客户设备真实执行后核对 `succeeded`、正式 Schema 规定的结果字段及业务完成条件；可空字段另核设备产物 |

绑定恢复单列证据：开发者 `developer.aigc.binding.lookup/1` 的正式 `found` 只证明只读查询可用及该会话存在受限任务绑定；Host 路径还需核对新签名版的能力声明、安装授权、原会话实际调用 Release、`aigc.task.binding.resolve/1` 原始回执、同任务快照和业务状态续接。没有新的客户业务回合时，Host 真实调用及完整 AIGC E2E 保持未验证，不能用开发者 GET、Schema 校验或历史截图替代。

仅测试本轮使用的路径。正式 Pack 示例、离线 fixture 和模拟 Host 可完成合同及失败分支检查；它们不能替代目标实例实时目录、真实授权和客户端结果。首次发布前无法观察的客户端环节按项目发布状态单列，激活后补测，不能因此把 Skill 方法包或具体 Agent 的离线测试写成三类能力真实通过。
