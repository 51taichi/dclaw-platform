# AIGC 资产本地化

仅在当前 Agent 需要把 DClaw AIGC 资产下载到客户设备时使用。先核对目标实例认证下载的开发标准、能力与操作目录，以及 DevKit `schemas/aigc-task-assets-v1/`、`schemas/aigc-task-snapshot-v1/` 和 `schemas/local-task-host-v1/`。当前公开 OSS 下载策略依据标准 2.55 / Developer Pack 1.10.33 / DevKit 1.9.22、Support Plugin 1.18.43；该版本的 AIGC 本地化要求 Windows Helper 至少 1.4.6。版本与授权以目标实例当次回读为准。

## 同任务调用

1. 从可信 AIGC 创建回执取得 `material_task_id` 和画布绑定。按已声明且获安装授权的 `aigc.task.snapshot/1` 读取同任务快照，核对画布、节点、job 和成功状态；部分节点成功时，不必自行等待整个工作流提交，但只能选已成功且同作用域的资产。
2. 用该 `material_task_id` 调用 `aigc.task.assets.list/1`，只接受 `found` 和同任务返回。将候选资产与快照中的成功 job、节点、类型和资产 ID 对照；节点重生成后重新读取。列表只提供资产事实，不提供下载 URL。
3. Agent 按自己的业务目标选择资产并组成 `aigc.task.assets.localize/1` 计划。每项有唯一 `asset_id`、业务决定的 `usage` 和 `slot`、唯一非负 `order`、`destination`；`final_output` 只用 `task_root`，其他用途只用 `res`。顺序由 `order` 决定，请求数组顺序无语义。用稳定幂等键提交；Agent 不构造、接收或保存下载 URL。Host 在受理前检查所选 OSS 对象的未签名 HTTPS 地址是否公开可读；失败返回 `ASSET_PUBLIC_DOWNLOAD_UNAVAILABLE`，不创建本地下载任务。
4. 按正式 `local.task.receipt/1` 完整 Schema 分支处理本地化回执。`rejected` 是合法拒绝回执，只有状态和错误码、没有 `task_id`；记录错误码并按当次正式诊断核对责任线、恢复动作及独立任务表，不把它记为回执格式错误、素材选择错误或任务已受理。`queued`、`running` 等已受理回执有真实 `task_id`，保存它与原幂等键，再用 `local.task.read/1` 回读同一任务；两者都不是完成。标准 2.55 的成功回执允许 `artifact_ids=[]`、`result_sha256=null`、`idempotency_key=null`；按完整 Schema 接受这些值，非空幂等键须与原请求一致，任务 ID 与能力 ID 仍精确核对。合法空值不证明设备文件存在；只有同任务终态 `succeeded` 且客户设备的 `assets.json`、文件大小和 SHA-256 可核对时，才记本地化设备产物成功。新资产的服务端非零大小及非空 SHA-256 必须与下载结果一致；历史资产缺服务端 SHA-256 时，Helper 摘要只算本次下载证据。

请求或回执不合 Schema、合法 `rejected`、`not_found`、`unavailable`、`ASSET_PUBLIC_DOWNLOAD_UNAVAILABLE`、资产未成功、作用域不符、设备旧版或离线时停止受影响链路；按实际错误码给客户准确的失败说明，不把设备拒绝误报为素材顺序错误。回执丢失时保留原键和任务标识，先走正式只读回读，不换键盲启；同键同计划重放应指向原任务，变更计划才使用新键。`LOCAL_GATEWAY.DEVICE_NOT_READY` 可能在受理前作为合法 `rejected` 返回，也可能是已受理任务的 `failed` 终态：前者先用独立任务表确认未受理，恢复 Helper 连接后同一输入沿用原幂等键做受控续接；后者先核对原任务终态，恢复连接后按正式标准用新键重试。两种情况均须按新 invocation 回读实际 Release、受理状态和 Helper 终态，不能由连接图标或 Host 返回成功推定下载完成。真实反例还须覆盖越权、错误资产、重复 `order`、错误目录、公开地址不可读，以及受理前拒绝与受理后断线，不用离线脚本代替平台验证。

作品状态跨 Release 续接后若保留旧本地化 `task_id`，先核对新旧 installation。新安装的 `local.task.read/1` 对旧 ID 返回 `not_found` 时，按正式安装隔离处理，不能推定旧下载未受理、已失败或文件已落地；优先用正式 `developer.local-task.diagnostics.read/1` 由专家所有者跨安装只读核对旧任务终态，目标实例未提供时再用原安装可用的正式只读路径或授权设备任务中心，结果未知则停止下载与后期链路。开发者只读回执不赋予新安装的 Agent 回读旧任务的权限。旧任务确认为失败、失败原因已有可执行的恢复办法，且原 AIGC 资产仍经可信快照与清单核对可用时，由 Agent 按业务规则提供客户可选择的重新下载入口；客户确认后以当前安装的新幂等键提交，并重新核对受理、终态和设备文件。下载任务的 Helper 异常单独按设备侧证据定位，不用调整 Agent 请求绕过。

本地化任务只把所选资产下载到**自己的任务目录**。`assets.json`、不透明 `artifact_ids` 或该任务的 `res/` 不自动成为另一个本地任务的 `local_file_bindings`。目标实例若提供标准 2.56 的 `local.task.outputs.bind/1`，按[本地能力包与视频制作](local-video-capability.md)核对原成功任务、兼容安装链、同一在线设备、Helper 1.4.7、声明授权、选定槽位与同一 invocation 的 `bind → start` 回执；旧实例或条件不满足时停止自动跨任务消费。下载成功、绑定成功、下游任务受理和成片分别留证，不猜客户电脑路径，也不把本地化成功写成自动合成通过。

## 逐节点证据与故障归属

任何调用 `aigc.task.assets.localize/1` 的专家都按同一条链路留证；未使用交互卡的专家将卡片节点标为不适用，不为凑证据增加卡片。每条记录关联实际 Agent Release、installation、可取得的同一业务任务或 invocation、能力 ID 与版本、目标实例正式合同版本、发生时间及证据位置；原始客户内容只留在当前项目的受控位置，下载 URL 不由 Agent 或模型记录。

| 节点 | 要核对的真实证据 | 不能据此推定 |
| --- | --- | --- |
| 交互卡（适用时） | 创建/读取回执、可信提交和本次答案与任务的关联 | 客户端显示或模型复述不能代替可信提交，也不证明素材可用 |
| AIGC 任务和资产 | 同任务快照中的成功 job、节点及 `aigc.task.assets.list/1` 的资产 ID、类型与作用域；按正式诊断核对所选 OSS 对象的公开可读性 | 快照成功不代替清单；公开地址可访问不证明本地任务受理 |
| Agent 请求 | 签名能力声明、安装授权、实际提交的脱敏请求结构及同任务资产、用途、顺序、目录和幂等键 | Schema 合格、单元测试或隔离重放返回 `queued` 不证明生产 Host 已受理 |
| 生产 Host | 原 invocation 的 Host 操作结果、可信 `local.task.receipt/1` 或正式诊断中的独立任务受理记录、原键和 `task_id` | Host 操作开始不等于受理；`runtime.complete` 或隔离测试不能代替生产任务记录 |
| 本地助手与设备 | 同一 `task_id` 的派发及 `local.task.read/1` 终态、设备下载结果、`assets.json`、大小与 SHA-256 | `queued`、`running`、Helper 已安装或服务器 URL 检查不证明客户设备已下载 |

失败时从最早有证据的异常节点定位，分别写明已证实、未取得和不适用。按目标实例当次正式诊断合同核对 `host_stage`、`error_code`、`responsibility`、`recovery_action`、`task_acceptance` 与独立任务表；正式合同若提供 `host.operation.started` 的 `implementation_revision` 或 `localize-diagnostics-v2` 标记，也记录其真实值和缺失情况，不把平台回传中的字段当成旧版合同已有字段。`host_exception/error_code=null` 且任务表确认为 `not_accepted/tasks=[]`，只说明该回合未受理本地任务、Helper 未进入；首错未留存时不能据此判定 Agent 请求有误、Host 实现故障或设备离线。保留原幂等键，先只读回查；受控复测须有当前项目授权、已核验的资产和可用交互入口，并限定重试次数。再次出现同类未知首错或缺正式要求的诊断标记时停止重复尝试，交平台核查实际执行版本与代码。

公共能力故障按正式能力 ID、版本、目标合同、受影响调用路径和上述节点证据提交平台核查；`aigc.task.assets.localize/1` 的修复应维持对所有专家一致的公开合同。若字段、错误、状态、权限或幂等语义要变，须由平台发布新合同并完成现役专家兼容回归，不能要求单个 Agent 修改请求来绕过公共实现缺陷。具体分流与平台交接见[试跑问题处理规则](runtime-feedback.md)。

## 两种 HTTPS 地址与构建入口

标准 2.54 下，`aigc.task.assets.localize/1` 的 Host 先核验任务、资产归属和每个未签名 HTTPS OSS 地址的公开可读性，再通过认证设备通道把稳定地址交给 Helper。地址不带到期签名参数，对象存在并保持公开可读时可继续访问；不可读时以 `ASSET_PUBLIC_DOWNLOAD_UNAVAILABLE` 在受理前失败，不回退到旧的短时签名方式。Agent 不提供、托管或读取下载 URL。开发方 HTTPS `capability-artifact-url` 只用于本轮另有私有本地能力包时的确定性制品托管、描述符签名及安装授权。仅使用平台通用本地化与 `local.task.read/1`，不产生开发方私有能力 artifact；不得把组合构建器的参数要求当作本地化 Host 合同的前提。

仅使用平台通用 `aigc.task.assets.localize/1` 的 Agent 仍需按实际声明核对本地任务回读。以下构建差异仅是 Pack 1.10.24/1.10.27 的历史证据，不作为当前 Pack 1.10.32 的规则：旧版要求声明 `local.task.read/1` 的项目使用 `local_helper=required`，但其组合 `dclaw_developer.py build` 对所有非 `none` 项目要求 `--capability-artifact-url` 并构建开发方私有能力包；当时的通用资产本地化合同本身没有要求开发方提供私有能力制品。当前构建应以目标实例本次正式 Pack、DevKit 和标准为准，组合入口与独立 `digest → validate → build → verify` 的结果分别记录。

若本轮发布确实不含开发方私有本地能力，且目标正式标准允许独立 DevKit 路径，可用同次认证取得的 DevKit 和冻结输入完成四步证据链，按本次授权调用正式 `publish upload`，再核对服务端验签、Release 状态与 `publish list`。Pack 组合 `build` 失败仍标失败，向平台请求澄清或修正该入口；它不能被独立 DevKit 的结果冒称通过。0.3.36 与 0.3.40 的正式回执已证明此路径可被各自目标实例接受并激活，但不证明其他版本或客户端本地化成功。若独立路径的正式依据、验签或服务端回执缺失，则受影响节点保持未放行。不删 `local.task.read/1`、不把 `local_helper` 改成与能力清单不符的 `none`，也不填占位 URL 或未发布的私有制品。

## 脱敏示例与离线核对

[示例 case](../tests/fixtures/aigc_asset_localization_case.json)使用两个已成功的视频资产、一个仍在运行的音频节点，并把请求数组排成与 `order` 相反的顺序。所有 ID 和摘要都是示意值。case 是 Skill 的测试容器，`bound_material_task_id` 与 `bound_canvas_id` 表示从可信创建回执取得的绑定，不是平台请求字段。目标实例正式请求与响应仍以 DevKit Schema 为准。

下方示例校验器只验证成功下载的完整证据链；合法 `rejected` 不属于成功 case，不能仅因校验器报 `localize not accepted` 就称平台回执不合 Schema。在已安装目标 DevKit 依赖的 Python 环境运行：

```text
python scripts/validate_aigc_asset_localization.py --devkit-root <目标实例认证下载的 DevKit 目录> --case tests/fixtures/aigc_asset_localization_case.json
```

脚本按目标 DevKit 的 `operation-catalog.json` 读取七份正式 Schema，检查示例的字段形状、可信任务和画布绑定、成功 job、素材选择、唯一顺序、目录以及本地任务回执关联。项目真实回执可在受控项目目录组成同形 case 离线核对；脚本不联网、不输出原始内容。它不能证明目标生产 Host 授权、Helper 下载、客户端结果、文件实际摘要或跨任务消费；这些必须留真实调用和设备证据。
