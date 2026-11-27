# DClaw Super Agent 开发知识库

本文件随 Skill 分发，只保存公开、可迁移的接入知识。它不是 DClaw 服务端源码、密钥库、某个 Agent 的实现或第二份人工开发标准。若与目标实例的正式标准、DevKit Schema 或实时能力目录冲突，以目标实例的正式材料为准；先核冲突来自本 Skill 的附加规则、目标材料之间不一致，还是项目自身约束，再按[卡点回传规则](blocker-feedback.md)记录准确归属，不把 Skill 错误报成平台缺口。

## 开始所需材料

以下材料用于开始具体 Agent 接入；只安装或了解本 Skill 时可以后补，不要求先登录 DClaw。

1. 当前任务的业务目标、源包或已有 Agent 项目，以及可用的源行为和测试证据。
2. 目标 DClaw 的 HTTPS 基础地址和能访问开发工具的已认证应用身份。EC 客户端入口为 `https://dclaw.rouhigh.com`；陆羽 1.1.34 的认证工具链与发布回执须来自 `https://api.rouhigh.com`，因为当前专家构建器会核对该精确来源。开发方指定其他目标时以其指定实例及项目合同为准。通过正式认证下载和版本回执确认目标，不能把本地源码或另一实例的成功记录当作当前部署证据。没有可用目标实例时仍可做需求和源码盘点，不能宣称完成平台集成或正式发布。
3. 目标实例提供的官方 Developer Pack，其中包含唯一人工标准 `super-agent-development-standard-v1.zh-CN.md`、DevKit、Schema、能力目录、模板、离线依赖和校验清单。文件名中的 `v1` 是稳定名称，实际版本读取文内“当前版本”及元数据。

不要求取得、克隆或导入 `dclaw-server`、`qwenpaw`、插件源码，也不要求使用原作者的项目目录、Git 仓库、会话或工具链缓存。团队可以在任意工作区安装本 Skill；所有模式参考文件与知识文件都位于本 Skill 文件夹内。

## 账号登录边界

需要运行本 Skill 的 v3–v6 诊断脚本时，先按[诊断脚本的 Python 环境](python-environment.md)准备项目隔离解释器并自检；它与目标实例的认证、正式 DevKit 合同分别判断。

DClaw 客户端显示已登录，只能证明该客户端的会话状态，不等于 Codex 或官方 CLI 已取得可用 API 令牌。接入流程必须能在没有 DClaw 客户端、浏览器自动化或 `computer-use` 的开发电脑上完成。按目标实例的正式认证合同，在本机交互输入普通账号凭证并验证令牌；不要让开发者在聊天中发送密码，也不要从客户端文件或进程中提取会话凭证。调用官方 CLI 时只在子进程环境中传递令牌，不把它拼入命令行参数、写入项目文件或发布包。目标工具链的认证方式和令牌有效期仍以认证下载后的正式材料核对。

首次认证下载可在开发者自己的交互终端运行本 Skill 的 `scripts/fetch_developer_pack.py --base-url <目标 HTTPS 地址> --output-dir <项目外工具链目录>`。脚本仅在当前进程持有密码和令牌，核对元数据 ZIP 摘要及包内清单，并只读检查首次发布路由的状态码；它不登记 signer、不安装软件、不发布 Agent。完成后按 Pack 的正式引导建立隔离环境。需要调用官方 `publish` 时，可运行本 Skill 的 `scripts/publish_with_login.py`，在本地交互登录后仅向官方 DevKit 子进程传递短时令牌；脚本不保存密码或令牌。具体用法先运行 `--help`，发布动作仍须按 Node 7/8 的证据与授权门禁执行。

普通账号自助发布的本机命令顺序（仅在目标 Pack 的正式标准仍支持时使用；以下 `python` 应为该 Pack 引导生成的隔离环境解释器）：

```text
python <DevKit>/dclaw_agent_devkit.py keygen --private-key <项目外私钥路径> --public-key <项目外公钥路径>
python <Skill>/scripts/publish_with_login.py --base-url <目标HTTPS地址> --devkit <DevKit>/dclaw_agent_devkit.py register-signer --public-key <公钥路径>
# 将登记回执中的 signer_id 写入 manifest，再执行官方 digest、validate、test、build、verify
python <Skill>/scripts/publish_with_login.py --base-url <目标HTTPS地址> --devkit <DevKit>/dclaw_agent_devkit.py --output <项目发布记录>/receipt.json upload --package <已验签ZIP>
python <Skill>/scripts/publish_with_login.py --base-url <目标HTTPS地址> --devkit <DevKit>/dclaw_agent_devkit.py --output <项目发布记录>/readback.json list
```

`publish_with_login.py` 每次调用重新交互登录，不提供令牌参数，也不覆盖已有回执。上传前检查 ZIP 的身份、版本、包类型、摘要和独立验签结果；发布后比对回执与列表。若官方标准更新命令或字段，以当次正式材料为准。

上传时可同时传 `--readback-output <新列表文件>`；脚本使用同一次短时登录先执行官方 `publish upload`，再执行官方 `publish list`，分别保存上传回执和列表回读。若上传后列表失败，上传回执仍保留，需先核对平台状态再重试，不能盲目重复上传。

官方 DevKit 非零退出时，发布脚本优先从其 JSON 错误输出提取 HTTP 状态和严格匹配的 `state_*` 类别；旧版仅写 stderr 时只保留 HTTP 状态；不打印错误正文、令牌或密钥，也不会把失败当作未上传。目标标准 `2.34` 允许兼容预检失败后保留已上传、已授权但未激活的 Release；旧版仍 active 的 `publish list` 结果不能证明新 Release 不存在。先用正式只读入口或平台维护回执核对准确 Release 状态和 ID；有已授权未激活 Release 时，按当次正式合同处理原因，再决定是否使用官方 `retry-activation`，不得盲目重传。

在 Windows 默认编码不是 UTF-8 的环境中，本 Skill 的发布脚本会为官方 DevKit 子进程固定 UTF-8 输出，并严格解析 UTF-8 JSON。直接运行官方构建包装器时，用隔离环境的 `python -X utf8`，并为该进程及其子进程设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`。若构建或上传命令在产物生成后报解码错误，先检查产物、验签结果和平台回读；不能把异常退出当作未构建或未上传而盲目重做。

## 从目标实例发现正式合同

先用真实应用身份读取以下相对于 `<DCLAW_BASE_URL>` 的入口；以元数据返回的 `download_path` 下载，不从固定文件名猜版本：

| 用途 | 入口 |
|---|---|
| 插件健康、版本 | `GET /api/super-agent-support/health` |
| Developer Pack 元数据 | `GET /api/super-agent-support/developer-pack` |
| DevKit 元数据 | `GET /api/super-agent-support/developer-kit` |
| 公共 Component 完整注册表 | `GET /api/super-agent-support/component-registry` |
| 客户端环境状态 | `GET /api/super-agent-support/environment-status` |

下载 ZIP 后核对元数据的 SHA-256、包内 `PACKAGE-MANIFEST.json`、`SHA256SUMS`、标准版本和 DevKit 版本，再在 Agent 项目之外建立只读工具目录。`401` 先检查应用认证，`403` 核对当前账号的开发工具权限并交平台方处理；已认证的 `404`、版本或摘要不一致属于目标环境门禁，不得改用平台源码副本或另一实例的旧包。公开的 DClaw 基础地址可用于定位目标；不要在命令行、日志、回执或 Skill 包内保存访问令牌、私钥、供应商 Secret 或客户数据。

正式标准和 Pack 描述新增行为，只证明文档合同；生产是否加载对应插件修订，还须核目标实例的已认证健康/版本回执、平台部署回执及适用的只读或受控运行证据。文档与平台当前部署回执冲突时，把该能力标为“合同已写、生产未确认或未部署”，只暂停依赖它的动作，继续其他独立工作；不得把预计修复当作已生效，也不得为取证反复发起客户任务。平台上线后核版本和关联 ID 脱敏诊断，再在原项目授权范围内做一次有区分力的受控验证。普通账号读取健康接口收到 `401` 只说明该次没有完成认证，不能据此判定插件版本。

首次发布前还须核对目标正式实例的实际发布合同：认证下载的 Pack/DevKit 是否包含所需 `publish` 子命令，目标自助发布路由是否由同一正式实例提供。测试机或内部容器的较新版本不能证明公网已部署；正式包缺命令或正式路由返回 `404` 时，只继续离线开发和可验证的本地测试，记录平台部署缺口，等待平台方升级并重新认证下载。不得用旧包、平台源码或管理员入口代替自助发布验证。

标准 `2.24` 对应支持插件 `1.17.0`、Developer Pack `1.10.0`、DevKit `1.9.0`，新增普通账号的 `super_expert_public` 自助公开发布。此组合只是定位信息，不能代替目标实例的已部署版本；每次开发均以目标实例实时元数据和标准为准。是否需要客户端、Runner、设备协议和平台变体，由本 Agent 实际使用的本地能力及当次标准决定，不能套用其他 Agent 的结论。

## 开发边界与节点证据

- Agent 开发方拥有业务流程、卡片、第三方 API 决策与调用、私有依赖和独立发布物。Agent 决定使用哪个安装级凭证槽，平台凭证能力按正式合同隔离保存长期 Secret；本地助手不得接收该 Secret。
- `dclaw.super-agent-support` 插件套件拥有所有 Super Agent 可共同使用的平台合同、公共 Component 注册表、本地助手通道和 DevKit。DClaw 核心不承载单个 Agent 的业务功能。
- 本地助手只执行 Agent 已确定的本地文件、下载上传、浏览器、视频音频和高资源处理；它按正式合同接收确定参数及 Agent 或 Host 授权交付的公开/短时 URL，不接收第三方长期 Key 或供应商控制面任务。DClaw AIGC 素材本地化的稳定公开 OSS 地址由 Host 预检后直接交付助手，Agent 不取得该 URL。
- 公共依赖以目标实例完整注册表的 ID、版本、平台变体和状态为准。缺少公共组件或公开调用合同，Node 1 保持阻断并向平台维护方提交申请；开发方不自行改平台插件。私有依赖进入与运行位置相符的 Agent 自有发布物。
- 各节点的事实、差异、测试和摘要记录在当前 Agent 项目内；发布者可另设，但必须接收冻结输入。每个 Agent 独立维护 `agent_id`、版本、signer、能力包、凭证槽、发布回执和回滚证据。`super_expert_public` 的上传成功回执按正式合同同时证明公开激活，整体授权为合同推定；列表回读、客户端可见及真实调用分别记录。其他包类型按其合同核对各环节。

## 已发布专家的头像维护

已核实的 DClaw 实例提供独立的管理员头像接口 `POST /api/admin/sealed-agents/{agent_id}/avatar`，以及 `GET /api/admin/sealed-agents` 列表回读。只有用户要求维护头像、该目标实例仍提供此合同、当前 DClaw 账号有相应管理权限时才使用。普通发布者的 DevKit `publish` 不包含头像命令；Git 仓库凭据也不是 DClaw 管理凭据。

可在开发者自己的交互终端运行本 Skill 的 `scripts/upload_avatar_with_login.py --base-url <目标HTTPS地址> --agent-id <准确ID> --file <图片路径> --output <当前Agent项目中的回执路径>`。脚本在本地提示输入 DClaw 管理账号与密码，当前实现接受 PNG/JPEG/WebP、最大 2 MiB，并在上传后比对管理员列表中的头像引用和 `active_release_id`。不得把密码或令牌放进聊天、命令参数、Skill 仓库或回执。目标实例的图片限制若与脚本不同，应先按该实例实际合同调整并验证，不让脚本猜测平台规则。

头像回读一致只证明管理端元数据已更新；客户端专家卡片视觉显示需另行核对，真实专家对话仍是独立验收。管理员头像维护无需重签已有 Agent ZIP；不把头像操作记作一次 `super_expert_public` 版本发布，也不改变其签名包证据。

## 共享 Skill 的改进方式

任何开发者都可以在自己的 Skill 副本上提出改进。对每个改动记录：触发的真实案例或正式合同、受影响节点、旧行为与新行为、是否需要产品/平台负责人确认、对已签名 Agent 和旧 Skill 的兼容结论。确定是平台 Bug 时向平台维护方提交最小复现，不把单个 Agent 的绕过写成公共规则；确定是业务差异时只改该 Agent。

发布共享 Skill 版本前，校验相对引用和 Skill 结构，在不含原作者项目和 DClaw 服务端源码的干净目录演练至少一条适用模式，并保留旧版本供已有项目继续使用。Skill 的知识文件不得包含密钥、生产认证状态、个人目录、固定会话 ID 或某个 Agent 的业务字段。
