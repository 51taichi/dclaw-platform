# 调用方 AI 第一阶段测试联调执行单

测试环境的个人 Codex Token 已创建，并通过安全渠道单独交付。

本次只验证身份认证、能力目录、Bot 列表、配置上下文和可信工作包导出。当前阶段不测试上传、预检、发布、回滚，也不得对线上配置执行任何写入操作。

## 一、环境信息

```text
测试环境 Base URL：https://worktool-test.deepmega.cn
鉴权方式：Authorization: Bearer <个人 Codex Token>
```

请将 Token 保存在本地 Secret 或环境变量中，不要把完整 Token 写入聊天、日志、代码、Git、测试快照或客户工作目录。

推荐使用以下环境变量：

```bash
export CONFIG_PATCH_BASE_URL="https://worktool-test.deepmega.cn"
export CONFIG_PATCH_STAFF_TOKEN="<通过安全渠道取得的个人Token>"
```

执行前关闭 Shell 调试输出：

```bash
set +x
```

## 二、第一步：验证身份

调用：

```http
GET /staff/v1/whoami
```

示例：

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $CONFIG_PATCH_STAFF_TOKEN" \
  "$CONFIG_PATCH_BASE_URL/staff/v1/whoami"
```

验收要求：

- HTTP 状态为 `200`；
- 返回 `tokenId`、`employeeName` 和 `tokenName`；
- 员工身份与本次 Token 的实际领取人一致；
- 输出和日志中没有完整 Token。

请记录 `tokenId`，不要记录完整 Token。

## 三、第二步：获取动态能力目录

调用：

```http
GET /staff/v1/capabilities
```

示例：

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $CONFIG_PATCH_STAFF_TOKEN" \
  "$CONFIG_PATCH_BASE_URL/staff/v1/capabilities" \
  -o capability-catalog.json
```

验收要求：

- HTTP 状态为 `200`；
- `schemaVersion`、`version`、`modules` 和 `profiles` 存在；
- 能识别普通专家和超级专家 Profile；
- 调用方只使用能力清单，不处理超级专家的加密、签名或密钥；
- 后续能力判断以本次接口结果为准，不以旧 Demo 或本地缓存为准。

## 四、第三步：读取全部 Bot

调用：

```http
GET /staff/v1/bots
```

示例：

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $CONFIG_PATCH_STAFF_TOKEN" \
  "$CONFIG_PATCH_BASE_URL/staff/v1/bots" \
  -o bots.json
```

请从结果中整理所有 Bot 的以下字段：

```text
botName
botId
enabled
boundAgentId
agentProfileId
knowledgeBaseId
readiness.status
readiness.ready
readiness.missingItems
readiness.code
currentReleaseId
```

只允许把 `readiness.ready=true` 的 Bot 列为可联调候选。

`readiness.ready=true` 表示平台已检查：

- Bot 已启用；
- Bot 已绑定并启用 Agent；
- DClaw 定位信息有效；
- Agent 已完成管理员首次安装，并存在可读取源码快照；
- OpenAPI 发布关系已建立；
- 积分账户归属已配置；
- 知识库已关联；
- 状态机可读取；
- 标签可读取；
- 工作包所需来源摘要完整。

不要仅根据“这个 Agent 当前正在使用”判断它一定就绪，必须以接口返回的 readiness 为准。

### 本步骤需要回传并等待确认

请把候选列表按以下格式回复给平台负责人：

```text
身份验证：通过／未通过
tokenId：只填写 whoami 返回的 tokenId
能力目录版本：

可联调 Bot 1
- 名称：
- Bot ID：
- 绑定 Agent ID：
- Agent Profile：
- 知识库 ID：
- currentReleaseId：
- readiness：ready

不可联调 Bot（如有）
- 名称：
- Bot ID：
- readiness.status：
- readiness.code：
- missingItems：
```

平台负责人将从 `ready=true` 的候选中明确指定一个测试 Bot。收到 Bot 名称和 Bot ID 的确认前，不要自行猜测目标，也不要继续导出工作包。

## 五、第四步：读取已指定 Bot 的配置上下文

平台负责人明确指定 Bot 后，先对 Bot ID 做 URL 编码：

```bash
BOT_ID="<平台负责人确认的Bot ID>"
BOT_ID_ENCODED="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$BOT_ID")"
```

调用：

```http
GET /staff/v1/bots/{botId}/configuration-context
```

示例：

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $CONFIG_PATCH_STAFF_TOKEN" \
  "$CONFIG_PATCH_BASE_URL/staff/v1/bots/$BOT_ID_ENCODED/configuration-context" \
  -o configuration-context.json
```

必须确认：

- 返回的 `botId` 等于平台负责人指定的 Bot ID；
- `boundAgentId` 等于 Bot 列表中的绑定 Agent；
- `agentProfileId` 存在于动态能力目录；
- `readiness.ready=true`；
- `flowMachine` 和 `tags` 均可读取；
- `sourceVersion` 存在；
- 没有使用本地旧状态机或旧标签替换服务端返回值。

任何一项不一致都应停止，不得通过手工修改响应或替换 Agent ID 绕过。

## 六、第五步：导出可信工作包

调用：

```http
POST /staff/v1/bots/{botId}/workspace-bundles/export
```

示例：

```bash
mkdir -p platform-download

curl --fail-with-body \
  -X POST \
  -H "Authorization: Bearer $CONFIG_PATCH_STAFF_TOKEN" \
  -D platform-download/response-headers.txt \
  "$CONFIG_PATCH_BASE_URL/staff/v1/bots/$BOT_ID_ENCODED/workspace-bundles/export" \
  -o platform-download/workspace.zip
```

成功结果必须包含：

```text
HTTP 200
Content-Type: application/zip
X-DClaw-Release-Id: Rn
X-DClaw-Bundle-Digest: sha256:...
```

## 七、第六步：校验工作包

### 1. 校验 ZIP 摘要

```bash
python3 - <<'PY'
from hashlib import sha256
from pathlib import Path

data = Path("platform-download/workspace.zip").read_bytes()
print("sha256:" + sha256(data).hexdigest())
PY
```

输出必须等于响应头 `X-DClaw-Bundle-Digest`。

### 2. 检查文件列表

```bash
unzip -l platform-download/workspace.zip
```

至少应包含：

```text
dclaw-manifest.json
AGENTS.md
change-plan.yaml
agent/
knowledge/knowledge-manifest.json
customer-service/flow-machine.json
customer-service/tag-schema.json
platform/capability-catalog.json
platform/responsibility-matrix.md
platform/runtime-mechanism.md
platform/coordinated-change-patterns.md
platform/examples/cross-component-change.md
```

### 3. 检查 Manifest

```bash
unzip -p platform-download/workspace.zip dclaw-manifest.json
```

必须确认：

```text
manifest.schemaVersion = customer-service-workspace.v1
manifest.botId = 平台负责人指定的 Bot ID
manifest.agentId = configuration-context.boundAgentId
manifest.agentProfileId = configuration-context.agentProfileId
manifest.baseReleaseId = X-DClaw-Release-Id
manifest.capabilityCatalogVersion = 本次能力目录版本
四个 sourceFingerprints 均存在并以 sha256: 开头
```

工作包应先安全解压到新目录。拒绝绝对路径、`..`、符号链接、硬链接和设备文件，不覆盖已有客户目录。

## 八、完成后回传结果

请按以下格式回传，不要附完整 Token 或 Authorization 请求头：

```text
环境：测试
whoami：通过／未通过
tokenId：
能力目录版本：

测试 Bot 名称：
测试 Bot ID：
绑定 Agent ID：
Agent Profile：
知识库 ID：
readiness：

配置上下文校验：通过／未通过
状态机读取：通过／未通过
标签读取：通过／未通过

Release ID：
Bundle Digest：
本地计算 Digest：
Digest 是否一致：
Manifest 校验：通过／未通过
工作包文件检查：通过／未通过

上传：未测试
线上写入：未发生

失败项及机器码（如有）：
```

## 九、本阶段明确禁止

- 不调用或模拟上传接口；
- 不调用或模拟预检、发布、回滚接口；
- 不修改 Agent、经验库、状态机或标签；
- 不把本地修改描述为已经线上生效；
- 不自行替换 Bot ID、Agent ID 或 Release ID；
- 不把 Token 写入仓库、Skill、启动包、日志或聊天；
- 不调用 `/internal/*` 管理接口；
- 不为绕过 readiness 创建空文件、假 Manifest 或假工作包。

完成上述只读联调并提交结果后，再讨论调用方客户端及 Skill 的正式改造。
