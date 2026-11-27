# 交给超级专家开发 Skill：公共 FFmpeg 任务参数编排

状态：源码与测试已准备；开发方必须从目标实例的正式下载包和能力目录核对生产已加载版本后使用。拟发布版本为 Support 1.18.48、Windows Helper 1.4.9、标准 2.59、Developer Pack 1.10.38、DevKit 1.9.26。公共能力 ID 为 `dclaw.ffmpeg.task.plan`，能力版本 `0.1.0`。

## 职责边界

此能力属于 `dclaw.super-agent-support` 插件套件，供所有获授权超级专家使用，不是漫剧或任何单个专家的私有能力包。插件已注册的 `ffmpeg` 公共 Component 提供可执行程序；公共任务能力在本地 Helper 中校验受信文件，把专家确定的结构化技术计划编译为 FFmpeg 参数，调用 Component 并记录任务结果。专家和 Skill 不生成原始 FFmpeg 参数。Helper 不从客户开放式自然语言推断剪辑目标，也不自行选择素材或改写镜头顺序。

未部署的 `dclaw.ffmpeg.command` 原始参数方案已撤销，不得写入新专家 manifest 或调用示例。没有本地视频需求的专家无需声明此可选能力。

## Skill 对每个相关专家执行的节点

1. 重新从目标实例认证下载正式 Developer Pack，读取实时能力目录并核对插件、Helper、公共能力和 `ffmpeg` Component 的准确版本。不能以本地源码版本证明生产可用。
2. 依据该专家自身需求确定素材、镜头顺序、起止裁剪、可选像素裁剪、输出宽高/帧率及音频策略。素材选择和成片业务验收仍由专家负责，不复制其他专家的业务规则。
3. 在新的签名 Release 中声明并取得 `local.execution.session/1`、`local.runtime.prepare/1`、`local.task.start/1`、`local.task.read/1` 的 grant。续用前序成功任务的设备文件时，还需 `local.task.outputs.bind/1`。旧 Release 不会自动扩权。
4. 从已授权文件选择器或 `local.task.outputs.bind/1` 取得逐槽受信 `local_file_ref`。前序产物的 bind 和 start 必须在同一 invocation、同一设备完成。`clips` 数组顺序就是执行顺序；`local_file_bindings` 把每个用到的槽位绑定到文件引用。
5. 调用 `host.call("local.runtime.prepare/1", {"capability_id":"dclaw.ffmpeg.task.plan"})`。只有回执为同一能力 ID、准确 `package_version=0.1.0` 且 `status=ready` 才可启动；`preparing` 不代表受理。
6. 用认证 DevKit 的 `schemas/local-ffmpeg-task-plan-v1/input.schema.json` 校验 input，再调用 `local.task.start/1`，提交公共能力 ID、稳定幂等键、input 和逐槽文件绑定。核对真实受理回执；终态不明时按原键/任务 ID 查询，不换键重复创建。
7. 用 `local.task.read/1` 回读同一任务 ID。只有 `succeeded`、结果通过 Schema 且取得受管产物引用才证明技术任务完成；专家另按自己的业务条件判断是否成片。失败保留任务 ID 和稳定错误码以供恢复。

## V1 结构化输入

`plan_version` 固定为 `"1"`。`clips` 为 1 至 16 个有序条目，每项包含 `slot`、毫秒级 `trim_start_ms`/`trim_end_ms`，可选像素级 `crop={x,y,width,height}`；结束时间必须大于起始时间。同一受信槽位可重复出现，每个提交的绑定都必须被引用。`output` 包含安全的 MP4 文件名、偶数宽高、整数帧率和 `audio_policy`。`mute` 丢弃音频；`preserve` 要求每个输入都有音轨。Helper 按既定顺序裁剪、统一画面尺寸与帧率并拼接，自己决定 FFmpeg flags。V1 不包含转场、字幕、混音、多轨或自动剪辑决策；新增这些语义需发布新合同版本。

完整请求：`devkit/examples/local-ffmpeg-task-plan-v1/start-request.sample.json`。可调用 demo：`devkit/local_ffmpeg_task_plan_api_demo.py`。结果 Schema：`devkit/schemas/local-ffmpeg-task-plan-v1/result.schema.json`。专家输入不得含 `arguments`、shell 命令、滤镜表达式、OSS URL、本机路径或设备令牌。

## Skill 验收用例

- 用一段和两段受信 MP4 验证顺序、时间裁剪、可选画面裁剪；使用带音轨素材分别验证 `mute` 和 `preserve`。
- 拒绝非法时间范围、缺失/变更文件、不匹配或越权文件引用、不安全输出名和原始参数字段。
- 设备未就绪、仍在准备、FFmpeg 执行失败、取消、原键重放和中断后回读，均不得被误报为成片成功。
- 至少用一个与漫剧无关的专家按同一公共 ID/Schema 做合同测试，不把任一专家的业务时间线放进公共能力。

源码测试与目标实例正式可用是两份证据。平台回传已部署版本、grant 和设备 ready 后，开发方才能在新专家 Release 中使用此能力。
