# 调用方 AI 配置补丁服务第一阶段接入与联调手册

本文供 `ai-customer-service-delivery` 的调用方 Codex、交付员工和平台联调人员使用。目标是让调用方从平台取得正确 Bot 的线上可信基线，在本地完成 Agent、DClaw 经验库、AI 客服状态机和标签的联合分析与修改准备。

本文描述的是截至 2026 年 10 月 1 日已经部署并验收的真实接口，不是完整设计稿。当前阶段只支持鉴权、能力查询、Bot 发现、配置上下文读取和可信工作包下载；上传、预检、发布、版本查询、回滚和能力申请接口尚未开放。

## 1. 当前可联调范围

### 1.1 已经开放

调用方可以：

1. 使用员工个人 Codex Token 验证身份。
2. 读取平台当前能力目录和普通专家、超级专家的能力 Profile。
3. 查看全部 Bot 及其绑定 Agent、知识库和初始化就绪状态。
4. 读取指定 Bot 当前的状态机、标签、Agent Profile 和来源版本。
5. 为已经初始化完成的 Bot 下载可信工作包。
6. 以工作包作为本地修改的唯一基线，制定跨模块变更计划。

工作包导出会在独立补丁服务中建立或复用只读基线 Release，但不会改写 DClaw、AI 客服中台、Bot、Agent、知识库、状态机或标签。

### 1.2 尚未开放

以下能力属于后续阶段，调用方现在不得调用、模拟或宣称成功：

- 上传修改后的工作包；
- 服务端预检和差异报告；
- 跨 DClaw 与 AI 客服中台的联合事务发布；
- 发布状态、历史版本和回滚；
- 平台能力申请提交与状态查询；
- 员工通过接口完成 Agent 第一次安装。

当前服务不存在下列员工写接口：

```text
POST /staff/v1/bots/{botId}/releases/precheck
POST /staff/v1/bots/{botId}/releases
GET  /staff/v1/bots/{botId}/releases
GET  /staff/v1/bots/{botId}/releases/{releaseId}
POST /staff/v1/bots/{botId}/releases/{releaseId}/rollback
POST /staff/v1/platform-capability-requests
GET  /staff/v1/platform-capability-requests/{requestId}
```

如果调用方现有文档中列出了这些接口，应标记为“后续设计，当前不可用”，不能据此开发假实现。

## 2. 环境和入口

| 环境 | 员工 API Base URL | Token 管理后台 | 用途 |
| --- | --- | --- | --- |
| 测试 | `https://worktool-test.deepmega.cn` | `https://worktool-test.deepmega.cn/admin/` | 首次开发、自动化测试和真实联调 |
| 正式 | `https://dclaw.deepmega.cn` | `https://worktool.deepmega.cn/admin/` | 测试环境验收后读取正式 Bot 基线 |

调用方程序必须从配置读取 Base URL，禁止将测试或正式域名写死在业务代码中。测试 Token 与正式 Token 完全隔离，不能跨环境使用。

不要用 `/health` 判断补丁服务身份。由于公网反向代理部署方式不同，根路径的 `/health` 可能属于宿主业务。调用方应使用带 Token 的 `GET /staff/v1/whoami` 作为接入自检。

## 3. 系统职责

| 模块 | 权威归属 | 负责内容 | 典型修改场景 |
| --- | --- | --- | --- |
| Agent | DClaw | 对话策略、工具编排、回复规则和跨模块协作决策 | 改变如何理解客户、如何回复、如何调用工具 |
| 经验库 | DClaw 经验库 | 产品、政策、标准话术和有来源的业务事实 | 新增或纠正事实资料，答案随资料变化但不改变流程 |
| 状态机 | AI 客服中台 | 确定性阶段、字段收集、节点推进和节点动作 | 改变固定业务阶段、必填字段、推进条件或动作 |
| 标签 | AI 客服中台 | 客户分类、证据、提醒、接管和跟进触发 | 改变分类口径、标签证据或标签触发动作 |
| Token 管理 | AI 客服后台页面与独立补丁服务 | 创建、查看、轮换和撤销员工 Token | 员工或设备授权变化 |
| 工作包聚合 | 独立补丁服务 | 聚合两侧线上事实、建立基线并生成确定性 ZIP | 调用方开始一次新的配置修改 |

Bot 是调用方唯一选择入口。Agent ID、经验库 ID、OpenAPI 发布对象、状态机和标签目标均由服务端按 Bot 当前绑定关系解析。调用方不得把自己猜测的 Agent ID 当成权威目标。

## 4. Token 发放和保存

### 4.1 平台管理员操作

管理员进入对应环境的 AI 客服后台，打开“Codex Token”标签，填写：

- 员工姓名：真实使用人；
- Token 名称：建议使用“姓名-设备-Codex-环境”；
- 有效期：联调 Token 建议设置明确有效期。

完整 Token 只在创建或轮换时显示一次。平台只保存 Token 哈希，之后无法找回原明文；丢失时应轮换或重新创建。

每位员工、每台主要开发设备应使用独立 Token。不要多人共用“团队万能 Token”。

### 4.2 调用方本地配置

本文推荐调用方统一使用以下环境变量名：

```bash
export CONFIG_PATCH_BASE_URL="https://worktool-test.deepmega.cn"
export CONFIG_PATCH_STAFF_TOKEN="<管理员单独交付的测试Token>"
```

这是调用方客户端的推荐配置名称；平台协议只要求 Bearer Token，并不依赖变量名。

可以使用仅当前用户可读的本地 `.env`，但必须加入 `.gitignore`：

```dotenv
CONFIG_PATCH_BASE_URL=https://worktool-test.deepmega.cn
CONFIG_PATCH_STAFF_TOKEN=<管理员单独交付的测试Token>
```

Token 禁止出现在：

- Git 提交、Issue、PR、Skill 和启动包；
- 客户任务目录、工作包和版本归档；
- 普通聊天、截图和工单；
- URL 查询参数；
- 日志、异常堆栈和测试快照；
- shell 的调试输出，例如 `set -x`。

调用方不得获得或使用平台内部管理密钥，也不得调用 `/internal/*` 接口。

## 5. 通用协议

### 5.1 请求

- 协议：HTTPS；
- 员工接口前缀：`/staff/v1`；
- 鉴权头：`Authorization: Bearer <员工Token>`；
- JSON 编码：UTF-8；
- `botId` 放入路径前必须执行 URL 编码；
- 工作包导出使用 `POST`，当前不需要请求体。

示例：

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $CONFIG_PATCH_STAFF_TOKEN" \
  "$CONFIG_PATCH_BASE_URL/staff/v1/whoami"
```

### 5.2 错误响应

错误响应通常使用以下结构：

```json
{
  "detail": {
    "code": "MACHINE_READABLE_CODE"
  }
}
```

部分初始化错误还会返回：

```json
{
  "detail": {
    "code": "ADMIN_BOOTSTRAP_REQUIRED",
    "missingItems": [
      "openapi_publication",
      "billing_account",
      "knowledge_base"
    ]
  }
}
```

调用方判断失败原因必须优先读取 `detail.code`，不要依赖自由文本。

### 5.3 超时和重试建议

- 普通 JSON 查询：连接超时 10 秒，总超时 30 秒；
- 工作包导出：连接超时 10 秒，总超时 120 秒；
- `401`、`404`、`409` 不自动重试；
- `502`、`503` 最多退避重试两次，建议间隔 2 秒、5 秒；
- 网络结果不明时，重新读取 Bot 上下文后再重试导出；
- 禁止关闭 TLS 校验或使用 `verify=False`。

在来源没有变化时，重复导出会返回相同 Release 和相同 ZIP 内容。来源在读取过程中变化时，服务会拒绝导出，而不是拼出一份混合版本工作包。

## 6. 接口说明

### 6.1 验证当前 Token

```text
GET /staff/v1/whoami
```

请求：

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $CONFIG_PATCH_STAFF_TOKEN" \
  "$CONFIG_PATCH_BASE_URL/staff/v1/whoami"
```

成功响应：

```json
{
  "tokenId": "tok_xxx",
  "employeeName": "张三",
  "tokenName": "张三-MacBook-Codex-测试"
}
```

响应不会返回完整 Token。调用方可以在本地联调记录中保存 `tokenId`，但不能保存明文 Token。

### 6.2 获取动态能力目录

```text
GET /staff/v1/capabilities
```

请求：

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $CONFIG_PATCH_STAFF_TOKEN" \
  "$CONFIG_PATCH_BASE_URL/staff/v1/capabilities" \
  -o capability-catalog.json
```

主要响应结构：

```json
{
  "schemaVersion": "capability-catalog.v1",
  "version": "2026.09.30",
  "modules": [],
  "profiles": {
    "standard-2026.09": {
      "profileId": "standard-2026.09",
      "name": "普通专家",
      "capabilities": []
    },
    "super-expert-2026.09": {
      "profileId": "super-expert-2026.09",
      "name": "超级专家",
      "capabilities": []
    }
  },
  "semantics": {},
  "capabilityRequest": {}
}
```

示例省略了数组内容，调用方必须使用接口返回的完整目录。Demo、旧 Skill 或本地缓存都不能替代动态能力目录。

普通专家和超级专家使用同一组员工 API。调用方只读取 `agentProfileId` 和对应能力清单，不处理超级专家的加密、签名、密钥或运行产物。

### 6.3 列出全部 Bot

```text
GET /staff/v1/bots
```

请求：

```bash
curl --fail-with-body \
  -H "Authorization: Bearer $CONFIG_PATCH_STAFF_TOKEN" \
  "$CONFIG_PATCH_BASE_URL/staff/v1/bots" \
  -o bots.json
```

脱敏示例：

```json
{
  "bots": [
    {
      "botId": "bot_xxx",
      "botName": "测试客服",
      "enabled": true,
      "boundAgentId": "a_service",
      "agentProfileId": "standard-2026.09",
      "openapiPublicationId": "pub_xxx",
      "openapiPublicId": "public_xxx",
      "knowledgeBaseId": "kb_xxx",
      "readiness": {
        "status": "ready",
        "ready": true,
        "missingItems": [],
        "code": null
      },
      "currentReleaseId": "R1"
    }
  ]
}
```

所有有效员工 Token 都能查看全部 Bot，不按员工、Workspace 或 Bot 过滤。

`currentReleaseId` 在尚未建立只读基线时可以是 `null`；调用方必须接受该值为空，不能因此自行伪造 `R1`。

调用方应向员工展示 `botName`、`botId`、`boundAgentId`、Profile 和 readiness，由员工明确选择目标。名称相似、目录名相似或历史任务记录都不能替代选择确认。

`readiness.status` 可能是：

- `ready`：可以尝试下载；
- `not_ready`：存在明确初始化缺项；
- `unavailable`：某个上游暂时不可用或返回不完整。

### 6.4 读取 Bot 配置上下文

```text
GET /staff/v1/bots/{botId}/configuration-context
```

请求：

```bash
BOT_ID="<员工明确选择的Bot ID>"
BOT_ID_ENCODED="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$BOT_ID")"

curl --fail-with-body \
  -H "Authorization: Bearer $CONFIG_PATCH_STAFF_TOKEN" \
  "$CONFIG_PATCH_BASE_URL/staff/v1/bots/$BOT_ID_ENCODED/configuration-context" \
  -o configuration-context.json
```

主要响应结构：

```json
{
  "botId": "bot_xxx",
  "botName": "测试客服",
  "enabled": true,
  "boundAgentId": "a_service",
  "agentProfileId": "standard-2026.09",
  "openapiPublicationId": "pub_xxx",
  "openapiPublicId": "public_xxx",
  "knowledgeBaseId": "kb_xxx",
  "readiness": {
    "status": "ready",
    "ready": true,
    "missingItems": [],
    "code": null
  },
  "currentReleaseId": "R1",
  "agentType": "standard",
  "sourceVersion": "source_xxx",
  "flowMachine": {},
  "tags": {}
}
```

调用方应先核对：

1. 返回的 `botId` 与员工选择一致；
2. `boundAgentId` 与当前客户任务记录一致；
3. `agentProfileId` 在能力目录中存在；
4. `readiness.ready` 为 `true`；
5. 状态机和标签不是调用方本地旧文件，而是当前线上值。

### 6.5 下载可信工作包

```text
POST /staff/v1/bots/{botId}/workspace-bundles/export
```

请求：

```bash
mkdir -p platform-download

curl --fail-with-body \
  -X POST \
  -H "Authorization: Bearer $CONFIG_PATCH_STAFF_TOKEN" \
  -D platform-download/response-headers.txt \
  "$CONFIG_PATCH_BASE_URL/staff/v1/bots/$BOT_ID_ENCODED/workspace-bundles/export" \
  -o platform-download/workspace.zip
```

成功响应：

- HTTP `200`；
- `Content-Type: application/zip`；
- `X-DClaw-Release-Id: Rn`；
- `X-DClaw-Bundle-Digest: sha256:...`；
- 响应体为 ZIP。

第一次成功导出通常建立 `R1`。如果此前已经建立基线，Release 可能不是 `R1`，调用方不得硬编码。

若 Bot 尚未完成管理员初始化，返回 HTTP `409`：

```json
{
  "detail": {
    "code": "ADMIN_BOOTSTRAP_REQUIRED",
    "missingItems": ["agent_source_snapshot"]
  }
}
```

调用方遇到该错误必须停止下载流程，把全部 `missingItems` 原样交给平台管理员；不能创建空 Agent、修改 manifest 或换一个 Agent ID 绕过。

## 7. 工作包契约

### 7.1 目录结构

工作包至少包含：

```text
customer-service-workspace/
├── dclaw-manifest.json
├── AGENTS.md
├── change-plan.yaml
├── agent/
├── knowledge/
│   ├── knowledge-manifest.json
│   └── ...
├── customer-service/
│   ├── flow-machine.json
│   └── tag-schema.json
└── platform/
    ├── capability-catalog.json
    ├── responsibility-matrix.md
    ├── runtime-mechanism.md
    ├── coordinated-change-patterns.md
    └── examples/
        └── cross-component-change.md
```

上面的 `customer-service-workspace/` 表示调用方选定的解压目录；ZIP 内文件直接从 `dclaw-manifest.json`、`AGENTS.md` 等根条目开始，不额外包含一个固定名称的顶级目录。

`agent/` 和 `knowledge/` 中的实际文件由目标 Agent 当前源码快照决定，不应假设固定文件名。

### 7.2 Manifest

示例：

```json
{
  "schemaVersion": "customer-service-workspace.v1",
  "bundleId": "bundle_xxx",
  "botId": "bot_xxx",
  "botName": "测试客服",
  "agentId": "a_service",
  "agentProfileId": "standard-2026.09",
  "activeCapabilities": [],
  "sourceVersion": "source_xxx",
  "baseReleaseId": "R1",
  "capabilityCatalogVersion": "2026.09.30",
  "sourceFingerprints": {
    "agent": "sha256:...",
    "knowledge": "sha256:...",
    "flow": "sha256:...",
    "tags": "sha256:..."
  },
  "exportedAt": "2026-10-01T00:00:00+00:00"
}
```

调用方必须验证：

- `schemaVersion` 等于 `customer-service-workspace.v1`；
- `botId` 等于所选 Bot；
- `agentId` 等于上下文中的 `boundAgentId`；
- `agentProfileId` 存在于能力目录；
- `baseReleaseId` 等于响应头 `X-DClaw-Release-Id`；
- ZIP 的 SHA-256 等于响应头 `X-DClaw-Bundle-Digest`；
- 四个 `sourceFingerprints` 均存在且以 `sha256:` 开头。

校验 ZIP 摘要：

```bash
python3 - <<'PY'
from hashlib import sha256
from pathlib import Path

data = Path("platform-download/workspace.zip").read_bytes()
print("sha256:" + sha256(data).hexdigest())
PY
```

### 7.3 解压安全

即使工作包由受信服务生成，调用方工具仍应安全解压：

- 只允许相对路径；
- 拒绝 `..`、绝对路径和反斜杠路径；
- 拒绝符号链接、硬链接和设备文件；
- 不覆盖客户目录中未纳入本次任务的文件；
- 先解压到新的临时目录，完成校验后再建立客户工作目录。

### 7.4 基线保存

原始 ZIP、响应头和解压后的原始基线应保存为只读归档。实际修改应从基线复制出工作副本，不直接编辑原始归档。

推荐本地结构：

```text
客户任务/
├── 平台基线/
│   └── R1/
│       ├── response-headers.txt
│       ├── workspace.zip
│       └── extracted/
├── 当前工作区/
└── 版本归档/
```

`平台基线/`、客户资料和真实配置不得进入通用 Skill 启动包或共享经验仓库。

## 8. 调用方标准流程

### 8.1 开始一次任务

1. 读取 `CONFIG_PATCH_BASE_URL` 和 `CONFIG_PATCH_STAFF_TOKEN`；
2. 调用 `whoami`，向员工显示当前身份和环境；
3. 调用 `capabilities`，记录目录版本；
4. 调用 `bots`，展示完整候选；
5. 由员工明确选择 Bot；
6. 调用 `configuration-context`；
7. readiness 不通过时停止并生成管理员待办；
8. readiness 通过时导出工作包；
9. 校验响应头、ZIP、manifest 和绑定关系；
10. 读取工作包内 `AGENTS.md` 和 `platform/`；
11. 再读取客户资料和调用方交付 Skill；
12. 制定 `change-plan.yaml`，判断涉及哪些模块；
13. 在本地工作副本中修改和测试；
14. 把状态记录为“本地修改完成，待第二阶段上传”，不得记录为线上生效。

### 8.2 需求归属判断

- 改“怎么理解、怎么回复、怎么调用工具”：Agent；
- 改产品、政策、价格依据、标准事实：经验库；
- 改固定阶段、字段收集、节点推进：状态机；
- 改客户分类、提醒、接管和跟进触发：标签；
- 同一需求影响多个结果时，修改多个模块并设计联合验收，不强行归入单一文件。

以工作包中的动态能力目录和运行机制为平台事实。调用方现有 Demo 只提供结构参考，不能证明当前平台支持某项能力。

### 8.3 第一阶段结束状态

调用方完成本地修改后，应明确记录：

```text
平台基线：已下载并校验
本地配置：已修改或待修改
本地静态检查：通过／未通过
平台上传：未开放
线上保存：未发生
线上绑定：未改变
真实会话验证：未执行或保持原版本
```

## 9. 调用方客户端实现建议

建议在调用方项目中建立独立、窄范围的客户端层，例如：

```text
tools/
└── config_patch_client.py
tests/
└── test_config_patch_client.py
```

客户端至少提供：

```text
whoami()
get_capabilities()
list_bots()
get_configuration_context(bot_id)
export_workspace_bundle(bot_id, output_path)
```

实现要求：

- 构造日志前先脱敏 `Authorization` 和 Token；
- 不接受调用参数覆盖服务端返回的 Agent ID；
- JSON 响应验证顶层结构和必要字段；
- 导出时校验 Content-Type、Release 头和 Digest 头；
- 使用临时文件下载，校验后原子改名；
- 异常对象只保存机器码、状态码和安全响应摘要；
- 单元测试使用假服务，不把真实 Token 写进夹具；
- 真实联调测试默认显式启用，不能在普通测试中自动访问正式环境。

### 9.1 Python 标准库参考

下面的代码只演示接口封装边界，不代替调用方项目自己的目录和测试规范：

```python
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class ConfigPatchError(RuntimeError):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code
        super().__init__(f"config patch request failed: {status} {code}")


class ConfigPatchClient:
    def __init__(self) -> None:
        self.base_url = os.environ["CONFIG_PATCH_BASE_URL"].rstrip("/")
        self.token = os.environ["CONFIG_PATCH_STAFF_TOKEN"]

    def _request(self, method: str, path: str):
        request = urllib.request.Request(
            self.base_url + path,
            method=method,
            headers={"Authorization": f"Bearer {self.token}"},
        )
        try:
            return urllib.request.urlopen(request, timeout=120)
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read())
                code = payload.get("detail", {}).get("code", "HTTP_ERROR")
            except (ValueError, AttributeError):
                code = "HTTP_ERROR"
            raise ConfigPatchError(error.code, code) from None

    def whoami(self) -> dict:
        with self._request("GET", "/staff/v1/whoami") as response:
            return json.load(response)

    def get_capabilities(self) -> dict:
        with self._request("GET", "/staff/v1/capabilities") as response:
            return json.load(response)

    def list_bots(self) -> list[dict]:
        with self._request("GET", "/staff/v1/bots") as response:
            return json.load(response)["bots"]

    def get_configuration_context(self, bot_id: str) -> dict:
        encoded = urllib.parse.quote(bot_id, safe="")
        path = f"/staff/v1/bots/{encoded}/configuration-context"
        with self._request("GET", path) as response:
            return json.load(response)

    def export_workspace_bundle(self, bot_id: str, output: Path) -> dict:
        encoded = urllib.parse.quote(bot_id, safe="")
        path = f"/staff/v1/bots/{encoded}/workspace-bundles/export"
        with self._request("POST", path) as response:
            content = response.read()
            release_id = response.headers["X-DClaw-Release-Id"]
            expected = response.headers["X-DClaw-Bundle-Digest"]
        actual = "sha256:" + hashlib.sha256(content).hexdigest()
        if actual != expected:
            raise RuntimeError("workspace bundle digest mismatch")
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as temp:
            temp.write(content)
            temporary = Path(temp.name)
        temporary.replace(output)
        return {"releaseId": release_id, "bundleDigest": actual}
```

正式实现还需要补充安全解压、manifest Schema 校验、日志脱敏、超时分级和测试。

## 10. 错误码与处理

| HTTP | 机器码 | 含义 | 调用方处理 |
| --- | --- | --- | --- |
| 401 | `STAFF_TOKEN_REQUIRED` | 未提供 Bearer Token | 检查本机 Secret 配置，不要把 Token 发到聊天中 |
| 401 | `INVALID_STAFF_TOKEN` | Token 格式或值无效 | 由管理员核对环境或重新创建 |
| 401 | `STAFF_TOKEN_EXPIRED` | Token 已过期 | 管理员创建或轮换 Token |
| 401 | `STAFF_TOKEN_REVOKED` | Token 已撤销 | 停止使用旧 Token，由管理员重新授权 |
| 404 | `CONFIG_PATCH_BOT_NOT_FOUND` | Bot 不存在或已经删除 | 重新获取 Bot 列表并由员工选择 |
| 409 | `ADMIN_BOOTSTRAP_REQUIRED` | Bot 尚未具备可编辑基线 | 停止；把全部 `missingItems` 交给平台管理员 |
| 409 | `TARGET_BINDING_CHANGED` | 读取过程中 Bot-Agent 绑定变化 | 重新获取列表和上下文，重新确认目标 |
| 409 | `OMNICHANNEL_CONFIGURATION_CHANGED` | 状态机或标签在导出期间变化 | 等待变更完成后重新读取和导出 |
| 409 | `DCLAW_SOURCE_CHANGED` | Agent 或经验库在导出期间变化 | 重新读取上下文并重新导出 |
| 409 | `BASELINE_CHANGED_RETRY` | 另一请求先建立了新基线 | 重新获取上下文并导出，不覆盖旧文件 |
| 502 | `OMNICHANNEL_UPSTREAM_CONTRACT_INVALID` | AI 客服上游响应不符合契约 | 记录安全诊断信息并联系平台技术人员 |
| 502 | `DCLAW_UPSTREAM_CONTRACT_INVALID` | DClaw 上游 JSON 不符合契约 | 联系平台技术人员 |
| 502 | `DCLAW_SNAPSHOT_CONTRACT_INVALID` | DClaw 源码快照或摘要不符合契约 | 停止使用下载结果，联系平台技术人员 |
| 502 | `DCLAW_LOCATION_INVALID` | Bot 记录中的 DClaw 地址格式无效 | 停止并联系平台技术人员修复绑定配置 |
| 502 | `DCLAW_LOCATION_NOT_ALLOWED` | Bot 指向未获准的 DClaw 来源 | 停止并联系平台技术人员核对环境配置 |
| 503 | `OMNICHANNEL_UPSTREAM_UNAVAILABLE` | AI 客服上游暂时不可用 | 退避重试；持续失败时上报 |
| 503 | `DCLAW_UPSTREAM_UNAVAILABLE` | DClaw 上游暂时不可用 | 退避重试；持续失败时上报 |

Bot 列表或上下文也可能以 `readiness.status=unavailable`、`readiness.code=DCLAW_AGENT_NOT_FOUND` 告知绑定的 DClaw Agent 不可读取。此时不要换 Agent ID 重试，应由平台管理员核对该 Bot 的现有绑定和首次安装状态。

`missingItems` 常见值：

| 缺项 | 谁处理 |
| --- | --- |
| `bot_enabled` | AI 客服管理员启用 Bot |
| `agent_bound` | AI 客服管理员完成 Bot-Agent 绑定 |
| `agent_enabled` | AI 客服管理员启用 Agent |
| `dclaw_location_configured` | AI 客服管理员补全 DClaw 定位信息 |
| `agent_source_snapshot` | DClaw 管理员完成第一次 Agent 上传或源码快照 |
| `openapi_publication` | DClaw 管理员建立 OpenAPI 发布对象 |
| `billing_account` | DClaw 管理员配置积分账户归属 |
| `knowledge_base` | DClaw 管理员关联经验库 |
| `flow_readable` | AI 客服技术人员修复状态机配置 |
| `tags_readable` | AI 客服技术人员修复标签配置 |
| `source_fingerprints` | 平台技术人员修复来源摘要 |

调用方不得直接修改服务数据库来消除缺项。

## 11. 调用方仓库改造要求

当前 `ai-customer-service-delivery` 的 `latest.json` 指向版本 `b3af9f8649b0a254`。该版本的主 Skill 仍将自动上传标为“待接入”。调用方应在自己的源码工作区完成以下修改：

1. 增加独立配置补丁 API 客户端；
2. 增加本手册或等价的接口 reference；
3. 把主 Skill 的自动上传章节改成准确的分阶段状态；
4. 在项目开始时支持列 Bot、选 Bot、读上下文和下载基线；
5. 把下载工作包内的 `AGENTS.md` 和 `platform/` 作为当前任务动态说明；
6. 保留原有业务确认、资料核对、状态机审计和真实会话测试关口；
7. 不实现不存在的上传、预检或发布接口；
8. 增加 Token 脱敏、URL 编码、错误码和 ZIP 安全测试；
9. 使用测试环境完成一次真实联调；
10. 验收后重新构建启动包并更新 `latest.json`。

发布新的调用方启动包时，不得包含：

- 测试或正式 Token；
- 真实客户资料；
- 真实 Bot 工作包；
- 下载产生的 Release、配置或日志；
- 任何平台内部密钥。

## 12. 双方联调步骤

### 12.1 平台方准备

1. 在测试后台为实际联调员工创建测试 Token；
2. 指定一个允许联调的测试 Bot；
3. 确认 Bot 已启用并绑定正确 Agent；
4. 确认 Agent 已由管理员首次上传；
5. 确认 OpenAPI、积分账户和经验库关系；
6. 确认状态机和标签可读取；
7. 把本手册交给调用方 AI；
8. 通过与手册不同的安全渠道把 Token 交给实际员工。

### 12.2 调用方实施

1. 先实现客户端和单元测试；
2. 使用测试 Token 调用 `whoami`；
3. 保存一份能力目录样例；
4. 列出 Bot 并由员工确认目标；
5. 读取上下文并核对绑定；
6. 下载并验证工作包；
7. 将工作包映射到调用方现有项目结构；
8. 选择一个不改变业务含义的小需求完成本地修改；
9. 记录当前只能本地完成，不能上传；
10. 提交调用方客户端、测试和 Skill 修改供复核。

### 12.3 共同验收

双方逐项确认：

- 身份显示正确；
- 测试与正式环境没有混用；
- Bot 由员工明确选择；
- Bot-Agent 绑定一致；
- 普通或超级专家 Profile 正确；
- 状态机、标签、Agent 和经验库来自同一次稳定快照；
- ZIP 摘要、Release 和 manifest 一致；
- 工作包中的职责资料能指导调用方判断修改范围；
- Token 未出现在日志、Git 或启动包；
- 调用方没有声称本地修改已在线上生效。

## 13. 平台方配合职责

### 13.1 Token 管理

- 按员工和设备发 Token；
- 设置合理有效期；
- 员工离职、设备丢失或疑似泄露时立即撤销；
- 轮换后确认旧 Token 已失效；
- 不替员工保存完整 Token 明文。

### 13.2 Bot 初始化

第一次 Agent 安装必须由 DClaw 管理员完成。平台方根据 `missingItems` 一次补齐相关项，不要求调用方逐个猜测和重试。

### 13.3 业务确认

平台接口提供的是当前线上技术事实，不负责确认客户业务规则。价格、承诺、流程、发卡、接管、标签动作和跟进节奏仍由业务负责人确认。

### 13.4 技术排障

调用方上报时应提供：

```text
环境：测试／正式
发生时间：带时区，精确到分钟
员工 Token ID：来自 whoami，不是完整 Token
接口：方法和路径
Bot ID：如适用
HTTP 状态：
机器码：detail.code
missingItems：如适用
是否重试及结果：
```

当前员工 API 不返回 correlationId。平台技术人员使用时间、Token ID、Bot ID 和动作在服务端审计中定位请求。不要要求调用方提供完整 Token 或 Authorization 头。

## 14. 测试环境验收标准

以下全部满足，才算第一阶段调用方接入完成：

- [ ] `whoami` 返回正确员工和 Token ID；
- [ ] 能读取并保存动态能力目录版本；
- [ ] 能列出全部 Bot；
- [ ] 员工能够明确选择 Bot；
- [ ] 能读取配置上下文；
- [ ] readiness 缺项能生成正确的平台待办；
- [ ] ready Bot 能下载 ZIP；
- [ ] Release、ZIP 摘要和 manifest 校验通过；
- [ ] 工作包目录安全检查通过；
- [ ] 普通专家和超级专家均不要求调用方处理加密；
- [ ] 日志和异常不包含 Token；
- [ ] 调用方 Skill 正确描述第一阶段边界；
- [ ] 调用方自动化测试通过；
- [ ] 测试环境真实联调通过；
- [ ] 新启动包不包含凭据、客户资料或真实工作包。

## 15. 切换正式环境

测试环境验收后，正式接入只允许改变配置，不复制测试 Token：

1. 在正式后台为同一员工创建独立正式 Token；
2. 设置 `CONFIG_PATCH_BASE_URL=https://dclaw.deepmega.cn`；
3. 设置新的正式 `CONFIG_PATCH_STAFF_TOKEN`；
4. 重新调用 `whoami`，明确显示当前是正式环境；
5. 重新获取能力目录和 Bot 列表；
6. 由员工重新选择正式 Bot；
7. 只读下载正式基线并校验；
8. 不把测试工作包、Bot ID、Release ID 或摘要复用到正式环境。

正式环境第一轮仍然只读。调用方写入能力必须等第二阶段接口发布并完成新的联调验收。

## 16. 快速联调命令

```bash
set +x

: "${CONFIG_PATCH_BASE_URL:?missing CONFIG_PATCH_BASE_URL}"
: "${CONFIG_PATCH_STAFF_TOKEN:?missing CONFIG_PATCH_STAFF_TOKEN}"

auth_header="Authorization: Bearer $CONFIG_PATCH_STAFF_TOKEN"

curl --fail-with-body -H "$auth_header" \
  "$CONFIG_PATCH_BASE_URL/staff/v1/whoami"

curl --fail-with-body -H "$auth_header" \
  "$CONFIG_PATCH_BASE_URL/staff/v1/capabilities" \
  -o capability-catalog.json

curl --fail-with-body -H "$auth_header" \
  "$CONFIG_PATCH_BASE_URL/staff/v1/bots" \
  -o bots.json

# 员工查看 bots.json 后明确填写，不能自动猜测。
BOT_ID="<confirmed-bot-id>"
BOT_ID_ENCODED="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$BOT_ID")"

curl --fail-with-body -H "$auth_header" \
  "$CONFIG_PATCH_BASE_URL/staff/v1/bots/$BOT_ID_ENCODED/configuration-context" \
  -o configuration-context.json

curl --fail-with-body -X POST -H "$auth_header" \
  -D response-headers.txt \
  "$CONFIG_PATCH_BASE_URL/staff/v1/bots/$BOT_ID_ENCODED/workspace-bundles/export" \
  -o workspace.zip

unzip -l workspace.zip
unzip -p workspace.zip dclaw-manifest.json
```

不要在共享终端录像、日志或工单中执行会显示环境变量值的命令。
