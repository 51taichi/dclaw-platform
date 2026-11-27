# 本地能力包与视频制作

仅在当前 Agent 需要客户设备上的媒体处理、文件操作或本地任务能力时读取。以目标实例认证下载的标准、`operation-catalog.json`、`capability-catalog.json`、Component Registry、Helper manifest 和 DevKit Schema 为准；平台交接中的拟发布能力在目标实例正式材料和授权回执出现前不能视为可用。FFmpeg 是成熟的媒体处理依赖，按平台公共 Component 使用，不另造转码引擎。

## 职责层与入口

| 层 | 本轮职责 | 必须核对的边界 |
| --- | --- | --- |
| 密封 Agent | 选择素材、脚本与时间轴，确定技术输入、返工和业务验收 | 不在服务端下载/剪辑大文件，不把开放式客户意图交给 Runner |
| Support Plugin Host | 按签名声明和安装作用域校验、幂等受理、派发、回执及 AIGC 资产预检 | 不替 Agent 制定剪辑方案或执行 FFmpeg |
| Helper/Runner | 在客户设备准备公共 Component、平台公共任务能力或签名私有包，隔离执行、管理文件/检查点/取消/恢复 | 不选择业务素材或判断作品合格 |
| 平台公共任务能力（若正式发布） | 按统一 Schema 将专家给出的结构化技术计划编译为 FFmpeg 参数并执行 | 不从开放式客户话语推断目标、选择素材或改写顺序 |
| Agent 私有能力包（按需） | 按签名输入 Schema 执行公共能力未覆盖的确定性加工，返回结果 Schema | 不复制公共 FFmpeg，也不冒充 Runner 核心 |

密封 Agent 的本地任务直接 Host 入口以 `operation-catalog.json` 为准：标准 2.56 列 `local.task.outputs.bind/1`、`local.task.start/1`、`local.task.read/1`、`local.task.cancel/1`；AIGC 素材另用 `aigc.task.assets.list/1` 和 `aigc.task.assets.localize/1`。旧实例不推定有 `outputs.bind`。Host 从可信上下文注入租户、用户、会话、安装、Release 和 invocation，Agent 不填物理作用域。按 `schemas/local-task-outputs-bind-v1/`、`schemas/local-task-host-v1/` 与 `schemas/aigc-task-assets-v1/` 核对请求、回执和安装授权。声明 `local.execution.session/1` 才有本地会话；核心承诺依赖本地执行时再声明 `local.environment.preflight/1` 并在目标 Windows x64 客户设备验证预检。预检是环境要求，不是制作工具。

`schemas/local-execution-v1/{tool-call,tool-response}.schema.json` 描述另一入口，即本地能力 MCP 网关的 12 个工具：`local_environment_status`、`local_capabilities_list`、`local_runtime_prepare`、`local_task_start`、`local_task_status`、`local_task_continue`、`local_task_cancel`、`local_task_result`、`local_file_select`、`local_file_upload`、`managed_artifacts_list`、`managed_artifact_action`。它们不等于 12 个密封 `host.call` 能力。密封 Agent 不自行拼 MCP JSON-RPC、读取会话 Token 或假定 `local_runtime_prepare`、`local_file_select`、`local_task_continue` 已桥接为 Host；需要这些动作时逐项核对目标安装的正式 Agent 入口、声明、授权和真实回执。缺少入口则记录平台合同缺口，受影响流程保持阻断。

目标实例正式发布标准 2.57 / Support 1.18.45 起，`operation-catalog.json` 另列密封 Host `local.runtime.prepare/1`，依赖 `local.execution.session/1`；它与上段 MCP `local_runtime_prepare` 是不同入口。新签名 Release 须声明并获得该 Host grant，旧已激活 Release 不自动扩权。按 DevKit `schemas/local-runtime-prepare-v1/` 与 `local_runtime_prepare_api_demo.py` 校验：请求只给已注册的 `capability_id`，可选 `device_id` 仅来自当前用户的可信在线设备；不传下载 URL、会话令牌或物理作用域。只有 `ready` 且回执的 `capability_id`、`package_id`、`package_version` 与目标精确一致、设备和 Runner 版本可核时，才可启动本地任务。复用旧任务文件且需要确定来源设备时，可先 bind 取得受信 `device_id`，随后在该设备 prepare；引用在准备期间过期或跨回合时，start 前须再次 bind，保证用于 start 的绑定与启动处于同一 invocation、同一设备。`preparing` 只表示已派发准备，保存来源任务、槽位等稳定输入供后续回合复查，不保存短时文件引用或启动任务；`device_not_ready`、`runner_update_required`、`invalid_request`、`rejected`、`unavailable` 按正式 `user_action`/`error_code` 失败关闭。旧实例没有此 Host 合同时仍按其正式设备准备入口核对，不从 MCP Schema 猜桥接。

## 公共 FFmpeg 任务计划

2026-11-16 普通开发账号从目标实例认证取得 Developer Pack 1.10.38（标准 2.59 / DevKit 1.9.26）；正式 `operation-catalog.json` 登记公共任务能力 `dclaw.ffmpeg.task.plan` 0.1.0，最低 Support 1.18.48 / Windows Helper 1.4.9。平台回传 Support 1.18.48 已热更新，本侧尚无独立健康回读；Pack 和目录证明公开合同已发布，不证明特定安装的 grant、客户设备 Helper 版本或真实任务成功。其他目标实例也须先核对其认证 Pack、实时目录和授权；缺任一项时只将该能力记为 `unverified` 或准确阻断，不因本页引用的版本直接放行。

此公共能力由 Support/Helper 管理，区别于公共 `ffmpeg` Component 和 Agent 私有能力包。Agent 决定素材、片段顺序、裁剪、输出和业务验收，只提交正式 Schema 允许的结构化技术计划与受信文件绑定；Helper 校验文件、编译 FFmpeg 参数并执行。Agent、通用 Skill 和客户输入都不生成或传递原始 FFmpeg 参数、shell 命令或滤镜表达式。平台已撤销未部署的 `dclaw.ffmpeg.command` 原始参数方案，不能将其作为新专家依赖。没有本地视频需求的专家不声明此可选能力；已有私有能力包按其既有合同继续维护，切换公共能力须作为单独的 `optimization` 版本核对行为等价、授权及回滚。

正式 V1 input 使用 `plan_version="1"`、1–16 个按数组顺序执行的 `clips`，每段给已绑定的 `slot`、毫秒级 `trim_start_ms`/`trim_end_ms`，可选像素 `crop`；`output` 给安全 MP4 文件名、偶数宽高、整数 `fps`（1–60）和 `audio_policy`：`mute` 或要求每段都有音轨的 `preserve`。输入关闭 Schema 拒绝额外字段，结束时间还须大于起始时间。结果 Schema 的单个 `outputs` 条目只含文件名、大小和 SHA-256；真实产物仍按本地任务回执及设备回读核验。V1 不包含转场、字幕、混音、多轨或自动剪辑决策；超出范围时评估其他已授权能力或私有包，不扩写公共 V1 的语义。以目标认证 DevKit 的 `schemas/local-ffmpeg-task-plan-v1/`、`examples/local-ffmpeg-task-plan-v1/` 和 `local_ffmpeg_task_plan_api_demo.py` 为准。

DevKit 的片段数量、顺序、裁剪时间和输出参数只是 API 示例，不是 Agent 的业务默认。Node 0/2/5 应从当前用户要求和可信素材清单确定本次片段及顺序；用户未要求裁剪时，不擅自取示例的前几段或截取固定时长。`trim_end_ms` 须对应用户明确指定的裁剪终点，或在全长制作时来自当前任务可供密封 Agent 使用的受信时长；有实际时长可核时检查裁剪边界，缺少时按正式运行时回执判断，不能把计划提交视为裁剪有效。分镜预期时长、本机开发者测量值、示例常数和 Schema 最大值不能替代当前客户素材的受信时长。标准 2.59 / Pack 1.10.38 的 V1 每段强制 `trim_end_ms`，而 `aigc.task.assets.list/1` 与 `local.task.outputs.bind/1` 的正式回执均不提供媒体时长，操作目录也没有密封 Agent 可调用的受信时长读取入口或整段标志。若业务要求全长使用且目标实例仍无正式整段语义或受信时长合同，受影响计划与启动保持阻断；向平台提出最小公共合同需求，等正式 Schema、示例、版本及兼容规则发布后再接线，不用猜测时长、超大终点或本机私读值绕过。

适用 Node 依次核对：Node 1 将公共任务能力与 `ffmpeg` Component 分别记录版本、状态和授权；Node 3/4 固定 Agent 计划与 Helper 编译的责任边界，并核对新 Release 的 `local.execution.session/1`、`local.runtime.prepare/1`、`local.task.start/1`、`local.task.read/1` 声明与 grant，复用旧任务文件时再加 `local.task.outputs.bind/1`；Node 5 按正式 input Schema 和业务条件校验计划。若复用旧任务文件且要确定来源设备，先在当前 invocation `bind` 取得受信设备 ID，在该设备 `prepare` 精确能力 ID，核对 `ready` 的能力、包版本、设备与 Helper 版本；准备期间引用过期或跨回合时，启动前在本次 invocation 重新 `bind`，再以受信 `local_file_bindings`、稳定幂等键 `start`。不需复用旧任务文件时按正式 demo 从 `prepare` 进入，再取得当前任务授权文件引用。`preparing` 时停止启动并在后续回合复查，bind 与 start 必须在同一 invocation、同一设备。Node 6 覆盖单段/多段顺序、裁剪、两种音频策略、非法时间范围/文件引用/输出名/原始参数字段、离线、准备中、执行失败、中断、重放与取消。只有正式受理、按原 `task_id` 的 `read` 成功终态、结果 Schema 和客户设备受管成品引用均可核对，才证明技术任务完成；业务成片仍由 Agent 与客户验收。未取得 Helper 1.4.9 精确能力 `ready` 与真实成片回执前，E2E=false。

| MCP 工具组 | 用途和关键回执 |
| --- | --- |
| `local_environment_status` / `local_capabilities_list` / `local_runtime_prepare` | 查询设备、实际授权能力并准备签名包与组件；只有目标设备的 `ready` 可进入执行 |
| `local_task_start` / `local_task_status` / `local_task_continue` / `local_task_cancel` / `local_task_result` | 按原任务 ID 管理受理、状态、最新检查点续接、明确取消和终态结果；受理不等于成功 |
| `local_file_select` / `local_file_upload` | 客户选择设备文件取得受限 `local_file_ref`，或按短时 HTTPS 上传授权由设备直传；不在服务端中转字节 |
| `managed_artifacts_list` / `managed_artifact_action` | 只对 Helper 管理的成品列安全元数据和执行受限操作；不接收任意本机路径 |

## 公共 FFmpeg v2 整段合同

标准 2.61 / Pack 1.10.40 / DevKit 1.9.28 为同一公共能力 `dclaw.ffmpeg.task.plan` 0.1.0 增加独立的 `plan_version="2"` 输入合同，最低 Support 1.18.50、目标 Windows Helper 1.4.10。以目标实例认证材料的 `schemas/local-ffmpeg-task-plan-v2/`、`examples/local-ffmpeg-task-plan-v2/`、`operation-catalog.json` 和同一 `local_ffmpeg_task_plan_api_demo.py` 核对；旧 V1 Schema、已签名授权和 Helper 1.4.9 的 V1 能力保持有效，不因 V2 发布自动改义或重签。Agent 按本轮可信素材和用户要求选择计划版本，不能把 DevKit 示例中的片段数、顺序和时长当作业务默认。

V2 的 `clips` 按播放顺序提交已授权 `slot`：省略 `trim_start_ms`、`trim_end_ms` 表示完整文件；仅有起点表示从该点到文件结尾；仅有终点表示从文件开头到该点；两者都有时必须 `start < end`。可选 `crop` 与裁剪边界独立，`output` 仍按正式关闭 Schema 给 MP4 文件名、尺寸、帧率和 `audio_policy`。整段或开放区间无需 Agent 猜媒体时长，Helper 对受信本机文件生成 FFmpeg 处理参数；`preserve` 要求每段有音轨，输出帧率和编码可能造成一帧以内的容器时长差异。若目标实例只支持 V1 且当前素材没有受信时长，全长计划继续按上文 V1 规则阻断；不得用示例值、估计时长或极大终点伪造整段。

V2 使用既有声明、授权和 `bind → prepare → start → read` 链路；`local.runtime.prepare/1` 的 `ready` 仍为能力 `0.1.0`，不能单凭该版本证明目标设备支持 V2。提交前核对当前设备 Helper 至少 1.4.10；旧版或离线设备在受理前返回 `LOCAL_GATEWAY.DEVICE_NOT_READY`，应更新或重连后按原幂等键受控重试。关闭 Schema 或双边界错误返回 `CAPABILITY.INVALID_PAYLOAD`，须修计划；执行阶段 FFmpeg 失败记为任务终态 `CAPABILITY.PROCESS_FAILED`。设备上运行的 Helper 进程版本只证明该进程，不代替目标安装的 `ready`、任务受理、`read` 成功与客户成片。V2 E2E 仍须逐项取得可信绑定（适用时）、精确设备准备、受理、终态、输出摘要和客户设备成品；发布或静态测试均不能代替。

## Node 1 与能力包门禁

沿当前业务的正常、可选、返工和恢复分支分别盘点公共 Component、平台公共任务能力与私有任务能力，逐项标记 `available`、`reserved`、`absent` 或 `unverified`，附目标平台、准确版本、目录与授权证据；公共任务能力另列能力记录，不混入 Node 1 的依赖包确认表。Component Registry 中 FFmpeg `available` 仅证明可复用依赖存在；`provides=media.transcode` 不是可传给 `local.task.start/1` 的任务 `capability_id`。示例 `video.render`、平台交接候选或本地草稿 ID 不能作为生产注册证据。公共组件由插件管理制品、许可证、SBOM、签名与版本，Helper 按需准备；公共与私有任务分别引用精确注册版本。

私有能力包在项目中至少核对稳定 `package_id`、实际 `capability_id`、语义版本、Windows 目标平台、`min_runner_version`、输入/结果/检查点 Schema 及摘要、准确公共组件依赖、入口、文件/进程/网络权限、资源上限、输出、稳定错误、幂等、取消、恢复与清理。公钥和符合正式 Schema 的 signer 登记请求可先准备，但须以平台回执确认信任登记。开发方先把私有制品放到客户网络可达的正式 HTTPS 地址，核对 URL、大小及 SHA-256 后冻结并签名最终描述符；平台按正式合同注册能力并授权安装。目标托管域名缺实际部署入口时记录准确缺口并取得部署方式，不猜服务器路径或借公共 Component 直传接口。只有源码、本地测试、公共 FFmpeg、登记请求或 Agent 上传回执，均不证明该私有能力已可调用。准备阶段用实际 `capability_id` 与目标设备/Runner 核对状态，`ready` 才能启动；标准 2.56 的自动绑定还要求目标设备 Helper 至少 1.4.7，平台发布版本不证明每台设备已升级，macOS 不按 Windows 证据放行。

标准 2.56 第 16.5 节还要求下载主机同时列于资源锁 `allowed_domains` 与最终签名描述符 `permissions.network_domains`。冻结描述符前逐项核对；官方构建、Schema 校验或验签通过不能替代该合同检查。改动签名描述符后重新签名、验签，ZIP 内容未变时仍独立核对其摘要。

## 分阶段执行与验证

标准 2.60 / Pack 1.10.39 / DevKit 1.9.27 对 `local.task.outputs.bind/1` 的设备回包增加关闭 Schema：Support 1.18.49 接收 Helper 的 `aigc.assets.bind.result` 成功与拒绝结果；Host 等待设备回包最多 150 秒，超时为 `rejected / LOCAL_SOURCE.UNAVAILABLE`，不同于人工文件选择器的 180 秒。该修复不要求改 Agent 的 bind 请求或升级既有 Helper 1.4.9。收到 `rejected` 时按正式错误码停止下游、核对当前授权设备和来源任务，不把 `LOCAL_SOURCE.UNAVAILABLE` 解释为源文件必然丢失；只有新的真实 `bound` 回执才证明目标安装下绑定成功。平台报告已部署或旧回合超时形态相似，均不证明每次历史设备回包实际到达，也不能代替客户设备复测。

标准 2.56 的自动绑定只接受同租户、用户、会话、专家及已提交兼容安装链中的原成功 `aigc.task.assets.localize/1` 任务，并要求同一在线设备重新核验来源文件；旧 Helper、失败来源任务、文件缺失或变化、跨设备、越权和不兼容安装均不得放行。

按当前 Agent 的真实工作流列出素材来源、AIGC 创建/绑定、素材本地化、公共或私有媒体任务、人工检查点、成品与返工。每个阶段单列结构化输入、可信引用、幂等键、任务 ID、终态、产物、失败恢复与业务验收；可由已正式发布的公共任务能力或私有能力包执行确定性子计划。Agent 决定镜头、起止点、字幕、音轨、画幅、编码和输出要求，先用该能力已注册的输入 Schema 与业务不变量校验，再启动获授权任务。Runner 可以决定线程、缓存和技术重试，不能改变业务目标。

DClaw AIGC 资产先用可信任务绑定、`aigc.task.snapshot/1` 与 `aigc.task.assets.list/1` 核对，再由 Agent 确定 `usage`、`slot`、唯一 `order` 和 `destination`，用稳定键调用本地化并回读同一任务；设备 `assets.json`、文件大小与 SHA-256 证明下载，不证明成片。`asset_id`、本地化 `artifact_ids`、`assets.json` 中的设备路径均不能自动充当另一任务的 `local_file_ref`。下游仅使用正式合同允许、同作用域授权且可回读的文件/产物引用；无跨任务输入合同就停止下游，不复制大文件字节、Secret、绝对路径或模型正文进消息与状态。

目标实例确有标准 2.56 / Support 1.18.44 / Helper 1.4.7 的 `local.task.outputs.bind/1` 时，自动续用前一成功本地化任务须另声明并获授权 `local.task.outputs.bind/1` 和 `local.task.start/1`。以原 `source_task_id` 和所需唯一 `slots` 请求密封 Host；只接受正式 Schema 的 `bound` 回执，并核对返回槽位与请求完全一致、`order` 唯一、设备一致及引用未过期，再按原 `order` 把 `files[].file.local_file_ref` 映射到下一任务 `local_file_bindings[slot]={"local_file_ref":...,"access":"read"}`。绑定与启动必须在同一 invocation；重试绑定可能颁发新的短时引用，但不重下素材、不启动任务，启动重试仍用原幂等键。`not_found`、`source_not_ready`、`invalid_request`、`rejected`、`unavailable` 或回执不合格时不启动下游；不把跨安装 `not_found` 当作原文件不存在。只保存原任务 ID、业务槽位及下游任务 ID/幂等键，不持久化短时文件引用。`bound` 只证明来源任务和设备文件经 Host/Helper 复核，后续仍须单列目标公共或私有任务能力的注册授权、目标设备 `ready`、`local.task.start/1` 受理、`local.task.read/1` 终态及客户成片。旧实例缺此合同则停止自动续接或按已批准业务方案另用客户手选路径，不从 `assets.json`、`artifact_ids` 或设备路径造引用。

若业务允许客户重新选择设备上已有的文件，密封 Agent 按目标实例的实时卡片目录创建 `file_selector`，核对 `interaction.card.create/1`、`interaction.file.select/1` 和 `local.execution.session/1` 的声明与授权；客户提交后按正式卡片回读及提交回执取得受限 `local_file_ref`。Agent 按业务确认的顺序将每个引用映射到 `local.task.start/1` 的命名 `local_file_bindings`，每项仅给 `local_file_ref` 与 `access="read"`，再核对同设备、作用域、时效、文件限制和任务受理回执。文件卡可用不代表客户能从特定下载任务界面选到其文件，须在目标客户端实测。若要求无需客户重选而直接消费上一任务产物，则另核正式的跨任务资源授权入口和回执；不能将 `assets.json`、`artifact_ids` 或 MCP `managed_artifact_action(select)` 冒充密封 Host 的自动转换合同。两条路径分别留证，不以客户手动重选的成功证明自动续接。

已受理任务沿原 `task_id` 查询 `queued`、`running`、`awaiting_input`、`cancelling` 与终态；丢回执或断线先只读回查，不换键盲启。检查点只在 `awaiting_input` 且最新 `checkpoint_id` 匹配时续接；若密封 Agent 没有正式获授权的继续入口，就保持任务等待并提出合同缺口，不直连 MCP 网关。取消须有明确调用及回执。成功后按签名结果 Schema 核对成品引用、大小、SHA-256、时长、分辨率及技术质检，再由 Agent 核对内容、顺序和客户要求；新修订使用新任务。仅有 `succeeded`、空产物字段或技术测试均不代表客户可打开成片。

Node 6 对实际使用阶段测试：合法与非法 Schema、未授权和跨作用域、设备离线与版本不足、同键重放/冲突、派发中断、检查点续接与取消、文件引用过期/变化、下载损坏、组件安装失败、FFmpeg 失败、部分产物清理和业务不合格。每项按当前能力合同选择有区分力的反例；离线模拟、Runner 单测、正式构建验签、平台受理、设备结果和客户验收分开记录。完整视频 E2E 要在目标客户设备按真实入口观察到触发、素材绑定/下载（适用时）、能力准备、任务受理、设备处理、结果与技术质检、Agent 业务验收及客户打开成品；缺任一关键节点保持 `e2e-verified=false`。

标准 2.55 的 `developer.local-task.diagnostics.read/1` 只覆盖 `aigc.task.assets.localize/1` 本地化任务，不能用它查询任意视频制作能力的内部首错。视频任务先查正式 `local.task.read/1`、设备任务中心及该能力正式提供的诊断合同；若没有足够的开发者自查入口，记录准确缺口并按[故障反馈](runtime-feedback.md)申请受限只读合同，不猜私有日志或平台内部 API。
