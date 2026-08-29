# Open API 使用说明手册

适用对象：需要把 DClaw/QwenPaw 中的专家或专家团接入外部系统的管理员、实施人员和开发者。

典型场景：

- 客服系统调用“客服专家”自动回复用户问题。
- CRM、工单系统把客户问题发送给指定专家处理。
- 企业内部系统调用专家团完成分析、整理、生成方案等任务。
- 小程序、网站、IM 机器人通过后端服务接入 DClaw/QwenPaw 的智能体能力。

## 1. 基本概念

### 专家和专家团

后台里已经创建好的“专家”和“专家团”就是可以被 Open API 调用的 Agent 能力。

- 专家：单个智能体，适合客服、问答、文案、数据分析等单角色任务。
- 专家团：多个专家协作，适合复杂任务、需要多角色分工的流程。

### 发布对象

发布对象是把某个专家或专家团开放给外部系统调用的配置。

发布对象会生成一个稳定的 `Public ID`，外部系统通过它拼接接口地址：

```text
/api/open/v1/targets/{Public ID}/messages
```

示例：

```text
Public ID: support_agent
接口路径: /api/open/v1/targets/support_agent/messages
```

`Public ID` 不是密钥，可以理解为接口地址里的业务名称。建议使用小写英文、数字、下划线或短横线，例如：

```text
support_agent
crm_helper
ticket-agent
```

### 外部应用

外部应用代表调用方系统，例如：

- CRM 系统
- 客服工作台
- 小程序后端
- 企业内部系统
- 第三方集成服务

一个外部应用可以绑定一个或多个 API Key。生产环境建议不同系统使用不同外部应用，便于审计和撤销。

### API Key

API Key 是外部系统调用 Open API 的凭证，格式类似：

```text
qp_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

API Key 只在创建时显示一次。创建后后台只保存哈希和后四位，无法再次查看明文。如果丢失，需要重新创建一个新的 API Key。

### Scope

Scope 表示 API Key 可以调用哪些能力。

当前消息调用接口需要：

```text
messages:create
```

创建发布对象和 API Key 时，请至少选择 `messages:create`。其它 scope 属于预留能力，是否可用以当前产品版本实际开放的接口为准。

## 2. 使用前准备

使用 Open API 前，请确认：

1. 管理员账号可以登录后台。
2. 已经创建好要开放的专家或专家团。
3. 专家或专家团使用的模型已经配置完成，可以在后台正常对话。
4. 外部系统有自己的后端服务，用于保存 API Key 和转发请求。

重要安全要求：

- 不要把 API Key 写进网页前端、小程序端、App 客户端或公开代码仓库。
- API Key 应保存在服务端环境变量、密钥管理系统或后端配置中心。
- 小程序、网站前端、移动 App 应请求自己的业务后端，再由业务后端调用 Open API。

## 3. 管理员配置流程

进入后台：

```text
设置 -> Open API
```

页面上有四个主要配置区：

- 发布专家/专家团
- 创建外部应用
- 创建 API Key
- 维护发布对象的专属知识库

### 第一步：发布专家或专家团

在“发布专家/专家团”区域填写：

| 字段 | 说明 | 示例 |
| --- | --- | --- |
| Public ID | 外部接口路径中的公开 ID，需要唯一 | `support_agent` |
| 目标类型 | 选择“专家”或“专家团” | `专家` |
| 目标 | 选择已经创建好的专家或专家团 | `客服专家` |
| 发布标题 | 给管理员识别用的名称 | `客服专家` |
| 描述 | 给外部应用识别的说明 | `处理售前和售后常见问题` |
| 允许 scopes | 当前请选择 `messages:create` | `messages:create` |
| 初始状态 | `enabled` 表示创建后立即可用 | `enabled` |

填写完成后点击：

```text
创建发布对象
```

创建成功后，下方“发布对象”列表会出现一条记录，并显示该对象的接口路径。

### 第二步：创建外部应用

在“创建外部应用”区域填写：

| 字段 | 说明 | 示例 |
| --- | --- | --- |
| 应用名称 | 调用方系统名称 | `CRM 系统` |
| IP allowlist | 允许调用的 IP 列表。留空表示不限 IP | `203.0.113.10` |

IP allowlist 可以用逗号或换行分隔多个 IP：

```text
203.0.113.10
203.0.113.11
```

生产环境建议填写调用方服务器的出口 IP。测试环境可以先留空，确认调用链路后再收紧。

注意：

- 如果 DClaw/QwenPaw 部署在反向代理后面，IP allowlist 校验的是服务实际看到的客户端 IP。
- 如果调用被误判为不允许的 IP，请检查代理、网关或容器网络配置。

填写完成后点击：

```text
创建外部应用
```

### 第三步：创建 API Key

在“创建 API Key”区域填写：

| 字段 | 说明 |
| --- | --- |
| 发布对象 | 选择第一步创建的发布对象 |
| 外部应用 | 选择第二步创建的外部应用 |
| Key scopes | 选择 `messages:create` |
| 过期时间 | 可选。为空表示不过期 |

点击：

```text
创建 API Key
```

创建成功后，页面会显示“一次性密钥已生成”。请立即复制保存。

示例格式：

```text
qp_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

如果没有保存或已经关闭提示框，无法再次查看明文，只能重新创建新的 API Key。

### 第四步：维护 Agent 经验库

Open API 页面中的“专属知识库”与用户工作台中的“我的Agent经验库”使用同一套数据和操作接口。管理员可以维护后台中自己有权管理的发布对象；普通用户只能维护 `bound_user_id` 绑定到自己的发布对象。

维护时应先按名称选择 Agent，再用 `Public ID` 辅助核对。支持：

- 上传经验文档。
- 查看文档、切片数量和索引状态。
- 重建知识索引。
- 删除文档及其切片和索引。

发布对象被禁用后，外部调用会停止，但经验库仍可继续维护，便于重新启用前完成资料整理。经验库只服务对应的 Open API 发布对象，不会与个人知识库或企业知识库混用。

普通用户入口：

```text
知识库 -> 我的Agent经验库
```

如果用户看不到可维护对象，请检查：

1. 管理员是否已经创建 Open API 发布对象。
2. 发布对象的运行用户是否绑定到当前登录账号。
3. 该发布对象是否仍然存在；接口启用或禁用不影响维护权限。

## 4. 外部系统调用方式

### 接口地址

```http
POST {Base URL}/api/open/v1/targets/{Public ID}/messages
```

示例：

```http
POST https://your-domain.example.com/api/open/v1/targets/support_agent/messages
```

本地测试示例：

```http
POST http://127.0.0.1:18088/api/open/v1/targets/support_agent/messages
```

### 请求头

```http
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

示例：

```http
Authorization: Bearer qp_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Content-Type: application/json
```

### 请求体

```json
{
  "external_user_id": "customer-001",
  "external_session_id": "ticket-10001",
  "message": "你好，我想查询订单状态",
  "stream": true,
  "metadata": {
    "source": "crm",
    "ticket_id": "ticket-10001"
  }
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `external_user_id` | 是 | 外部系统里的用户 ID、客户 ID 或访客 ID |
| `external_session_id` | 否 | 外部系统里的会话 ID、工单 ID 或咨询 ID |
| `message` | 是 | 要发送给专家或专家团的用户消息 |
| `stream` | 否 | 当前消息接口要求流式返回。建议传 `true`，不传时默认也是 `true` |
| `metadata` | 否 | 业务自定义信息，例如来源、订单号、工单号 |

会话规则：

- 同一个外部应用、同一个发布对象、同一个 `external_user_id`、同一个 `external_session_id` 会进入同一条会话上下文。
- 如果想开启新会话，请更换 `external_session_id`。
- 如果没有传 `external_session_id`，系统会使用默认会话标识。

安全规则：

- 外部请求不能通过 body 或 query 参数切换目标专家。
- 实际调用哪个专家或专家团，只由后台“发布对象”决定。
- `metadata` 只用于业务辅助信息，不会改变授权范围。

## 5. curl 调用示例

```bash
curl -N \
  -H "Authorization: Bearer <API_KEY>" \
  -H "Content-Type: application/json" \
  -X POST "https://your-domain.example.com/api/open/v1/targets/support_agent/messages" \
  -d '{
    "external_user_id": "customer-001",
    "external_session_id": "ticket-10001",
    "message": "你是客服助手，请回复一句欢迎语",
    "stream": true,
    "metadata": {
      "source": "crm"
    }
  }'
```

本地测试：

```bash
curl -N \
  -H "Authorization: Bearer <API_KEY>" \
  -H "Content-Type: application/json" \
  -X POST "http://127.0.0.1:18088/api/open/v1/targets/support_agent/messages" \
  -d '{
    "external_user_id": "customer-001",
    "external_session_id": "ticket-10001",
    "message": "请只回复：open api ok",
    "stream": true
  }'
```

## 6. 返回格式

接口返回的是 SSE 流：

```http
Content-Type: text/event-stream
```

响应会分多段返回，每段以 `data:` 开头。

示例：

```text
data: {"object":"response","status":"created","session_id":"open:..."}

data: {"object":"response","status":"in_progress","session_id":"open:..."}

data: {"object":"content","type":"text","delta":true,"text":"你好"}

data: {"object":"content","type":"text","delta":true,"text":"，请问有什么可以帮您？"}

data: {"object":"message","status":"completed","role":"assistant","content":[...]}

data: {"object":"response","status":"completed","usage":{"provider_id":"...","model_name":"..."}}
```

开发者可以重点处理：

| 事件 | 说明 |
| --- | --- |
| `object=response, status=created` | 任务已创建 |
| `object=response, status=in_progress` | 正在生成 |
| `object=content, type=text, delta=true` | 文本增量内容 |
| `object=message, status=completed` | 一条助手消息完成 |
| `object=response, status=completed` | 本次响应完成 |

如果只需要最终文本，可以把所有 `object=content` 且 `type=text` 的 `text` 字段按顺序拼接。

## 7. JavaScript 调用示例

适用于 Node.js 后端或支持 `fetch` 的服务端运行环境。

```js
async function callOpenApi({ apiKey, baseUrl, publicId, userId, sessionId, message }) {
  const response = await fetch(`${baseUrl}/api/open/v1/targets/${publicId}/messages`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      external_user_id: userId,
      external_session_id: sessionId,
      message,
      stream: true,
      metadata: {
        source: "crm",
      },
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Open API request failed: ${response.status} ${errorText}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalText = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";

    for (const chunk of chunks) {
      const line = chunk
        .split("\n")
        .find((item) => item.startsWith("data:"));
      if (!line) continue;

      const data = JSON.parse(line.slice(5).trim());
      if (data.object === "content" && data.type === "text" && data.text) {
        finalText += data.text;
      }
      if (data.error) {
        throw new Error(typeof data.error === "string" ? data.error : JSON.stringify(data.error));
      }
    }
  }

  return finalText;
}
```

调用：

```js
const answer = await callOpenApi({
  apiKey: process.env.DCLAW_OPEN_API_KEY,
  baseUrl: "https://your-domain.example.com",
  publicId: "support_agent",
  userId: "customer-001",
  sessionId: "ticket-10001",
  message: "你好，我想了解售后政策",
});

console.log(answer);
```

## 8. Python 调用示例

```python
import json
import requests


def call_open_api(api_key: str, base_url: str, public_id: str, message: str) -> str:
    url = f"{base_url}/api/open/v1/targets/{public_id}/messages"
    payload = {
        "external_user_id": "customer-001",
        "external_session_id": "ticket-10001",
        "message": message,
        "stream": True,
        "metadata": {"source": "crm"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    final_text = []
    with requests.post(url, headers=headers, json=payload, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line or not raw_line.startswith("data:"):
                continue
            data = json.loads(raw_line[5:].strip())
            if data.get("object") == "content" and data.get("type") == "text":
                final_text.append(data.get("text") or "")
            if data.get("error"):
                raise RuntimeError(data["error"])

    return "".join(final_text)
```

## 9. 常见错误和处理

| HTTP 状态 | 返回信息 | 常见原因 | 处理方式 |
| --- | --- | --- | --- |
| 400 | `Open API messages currently require stream=true` | 请求传了 `stream:false` | 改为 `stream:true` 或不传 |
| 401 | `Open API key required` | 没有传 `Authorization: Bearer ...` | 检查请求头 |
| 401 | `Invalid or expired Open API key` | Key 错误、已过期或不存在 | 重新创建或更换 Key |
| 401 | `Open API app is disabled` | 外部应用被禁用 | 联系管理员检查外部应用状态 |
| 401 | `Open API publication is disabled` | 发布对象被禁用 | 在 Open API 页面启用发布对象 |
| 403 | `Client IP is not allowed` | 调用方 IP 不在 allowlist | 添加调用方出口 IP，或检查代理 IP |
| 403 | `Open API scope is not allowed` | 发布对象或 Key 没有 `messages:create` | 给发布对象和 Key 都配置 `messages:create` |
| 403 | `Open API key is not allowed for this publication` | Key 不属于这个发布对象 | 使用该发布对象对应的 Key |
| 404 | `Open API publication not found` | Public ID 不存在或发布对象未启用 | 检查 URL 里的 Public ID |
| 429 | `Too many running tasks...` | 当前运行任务过多 | 稍后重试，或调整并发策略 |
| 500 | `data: {"error":"..."}` 或服务端错误 | 模型、工具、运行时异常 | 查看调用记录和服务日志 |

## 10. 调用记录和审计

后台 Open API 页面会记录外部调用信息，包括：

- 调用 ID
- 发布对象
- 外部应用
- 外部用户
- 外部会话
- 状态
- HTTP 状态码
- 耗时
- 错误摘要
- 调用时间

管理员可以用这些记录排查：

- 哪个外部应用在调用。
- 哪个用户或会话触发了问题。
- 请求是否成功。
- 是否因为鉴权、IP、scope 或运行时错误失败。

## 11. Key 管理建议

生产环境建议：

1. 一个外部系统创建一个独立外部应用。
2. 一个发布对象按调用方分别创建 API Key。
3. 给 API Key 设置过期时间，并定期轮换。
4. 发现泄露或异常调用时，立即在 API Keys 列表中点击“撤销”。
5. 不要把多个业务系统共用同一个 Key。
6. 不要把 Key 发给浏览器、小程序、App 或第三方页面。
7. 如果启用 IP allowlist，请只填写调用方后端服务器的出口 IP。

## 12. 推荐接入架构

推荐链路：

```text
用户浏览器/小程序/App
  -> 业务系统后端
  -> DClaw/QwenPaw Open API
  -> 专家或专家团
```

不推荐链路：

```text
用户浏览器/小程序/App
  -> 直接调用 DClaw/QwenPaw Open API
```

原因：

- API Key 会暴露给终端用户。
- 无法控制调用频率和业务权限。
- 难以做业务审计、风控和数据脱敏。

## 13. 上线检查清单

管理员检查：

- 已创建并测试目标专家或专家团。
- 发布对象状态是 `enabled`。
- 发布对象 scopes 包含 `messages:create`。
- 外部应用已创建。
- API Key 状态是 `active`。
- API Key 未过期。
- IP allowlist 配置正确。

开发者检查：

- URL 中的 `Public ID` 正确。
- 请求头包含 `Authorization: Bearer <API_KEY>`。
- 请求头包含 `Content-Type: application/json`。
- 请求体包含 `external_user_id` 和 `message`。
- `stream` 为 `true` 或不传。
- 客户端按 SSE 流读取响应，不要用普通 JSON 响应解析。
- 业务后端妥善保存 API Key。

运维检查：

- DClaw/QwenPaw 服务外网或内网地址可被业务后端访问。
- HTTPS、反向代理、网关超时时间适合长连接流式返回。
- 如果使用 IP allowlist，网关转发后的客户端 IP 符合预期。
- 模型供应商 API Key 或本地模型可正常工作。

## 14. 最小可用示例

假设：

```text
Base URL: https://dclaw.example.com
Public ID: support_agent
API Key: qp_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

调用：

```bash
curl -N \
  -H "Authorization: Bearer qp_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx" \
  -H "Content-Type: application/json" \
  -X POST "https://dclaw.example.com/api/open/v1/targets/support_agent/messages" \
  -d '{
    "external_user_id": "customer-001",
    "external_session_id": "ticket-10001",
    "message": "请回复一句欢迎语",
    "stream": true
  }'
```

如果配置正常，会看到多段 `data:` 开头的 SSE 返回，其中包含专家生成的文本内容。
