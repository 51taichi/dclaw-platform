# DClaw 集成交付写入接口

本文档定义 DClaw 为上层配置补丁服务提供的窄内部适配接口。员工和调用方 AI 不直接调用本接口；`worktool-bot-service` 是唯一员工入口。

该适配器只更新已经安装、启用并完成 OpenAPI、计费账户和专属经验库配置的 Agent。它不提供首次安装，不改变原有 Agent、普通专家、密封 Agent或超级专家的管理机制，也不改变未使用本接口的任何业务流程。

## 1. 地址与认证

完整前缀为：

```text
/api/internal/integrations/v1
```

每次请求都必须携带：

```http
X-DClaw-Integration-Client: <固定客户端 ID>
X-DClaw-Integration-Secret: <固定客户端密钥>
```

客户端配置来自 `DCLAW_INTEGRATION_CLIENT_SECRETS_JSON`。密钥不得放入 URL、日志、工作包或操作收据。

所有 ZIP 请求使用原始 `application/zip` 请求体，不使用 multipart。验证和写入都需要携带调用方最近一次导出时取得的基线摘要：

```http
X-DClaw-Expected-Agent-Digest: sha256:<64 位十六进制>
X-DClaw-Expected-Knowledge-Digest: sha256:<64 位十六进制>
```

写操作还必须携带非空 `Idempotency-Key`。同一客户端、同一键、同一请求返回原操作；键相同但 ZIP 或基线摘要不同则返回 `IDEMPOTENCY_KEY_REUSED`。

## 2. 工作包约束

DClaw 子包必须包含：

```text
agent/**
knowledge/knowledge-manifest.json
knowledge/documents/**
dclaw-component.json
```

路径中的 `agent_id`、`dclaw-component.json.agentId` 和 `agent/agent.json.id` 必须完全一致。服务端拒绝路径穿越、绝对路径、链接、大小写折叠后的重复路径、特殊文件、加密 ZIP、超限文件和异常压缩比。

工作包中的敏感字段是导出时生成的透明占位值。更新标准 Agent 时，DClaw 会保留服务端管理的密钥、运行目录和其他未导出字段；调用方不得尝试设置这些值。会话、日志、缓存、媒体和 `sessions_data` 等运行态路径不会被工作包覆盖。

## 3. 验证

```text
POST /api/internal/integrations/v1/agents/{agent_id}/delivery-bundle/validate
```

请求头包含两个基线摘要，请求体为 ZIP。此接口只读：检查包结构、Agent 身份、内容摘要以及当前 DClaw 基线是否仍一致，不写入 Agent、经验库或操作记录。

成功响应：

```json
{
  "valid": true,
  "agentId": "a_service",
  "agentProfileId": "standard-2026.09",
  "sourceVersion": "workspace",
  "agentDigest": "sha256:...",
  "knowledgeDigest": "sha256:..."
}
```

返回的 `agentDigest` 和 `knowledgeDigest` 是候选包摘要；请求头中的两个摘要是发布前基线摘要，二者含义不同。

## 4. 应用

```text
PUT /api/internal/integrations/v1/agents/{agent_id}/delivery-bundle
```

除认证和两个基线摘要外，必须提供 `Idempotency-Key`。服务端再次比较当前摘要，然后把 Agent 和专属经验库作为一个操作应用。Agent 更新成功但经验库失败时，服务端立即恢复两者的发布前状态。

成功响应：

```json
{
  "operationId": "<64 位十六进制>",
  "agentId": "a_service",
  "status": "applied",
  "previousAgentDigest": "sha256:...",
  "previousKnowledgeDigest": "sha256:...",
  "agentDigest": "sha256:...",
  "knowledgeDigest": "sha256:...",
  "errorCode": null
}
```

操作收据和发布前 DClaw 子包保存在 DClaw 数据卷的 `integration_delivery/operations/` 下，因此进程重启后仍可查询和恢复。收据不保存认证密钥或签名私钥。

## 5. 查询

```text
GET /api/internal/integrations/v1/agents/{agent_id}/delivery-operations/{operation_id}
```

返回与应用接口相同的操作结构。`status` 只使用 `applied`、`restored` 或 `failed`。

## 6. 恢复

```text
POST /api/internal/integrations/v1/agents/{agent_id}/delivery-operations/{operation_id}/restore
```

必须携带 `Idempotency-Key`，无请求体。重复恢复同一个已恢复操作返回同一 `restored` 结果。标准 Agent 从发布前包重建源码并保留服务端字段；密封 Agent 和超级专家重新激活原 Active Release，不删除历史 Release。

## 7. 稳定错误码

| HTTP | `detail.code` | 含义 |
|---:|---|---|
| 400 | `DCLAW_REQUEST_INVALID` | 缺少幂等键或基线摘要 |
| 400 | `DCLAW_DELIVERY_BUNDLE_INVALID` | ZIP、清单、Agent ID 或摘要不合法 |
| 401 | `INVALID_INTEGRATION_CREDENTIAL` | 客户端认证失败 |
| 404 | `DCLAW_OPERATION_NOT_FOUND` | 操作不存在或不可读取 |
| 409 | `DCLAW_SOURCE_CHANGED` | Agent 或经验库已经偏离调用方基线 |
| 409 | `IDEMPOTENCY_KEY_REUSED` | 同一幂等键被用于不同请求 |
| 409 | `ADMIN_BOOTSTRAP_REQUIRED` | Agent 尚未完成管理员初始化 |
| 500 | `DCLAW_DELIVERY_APPLY_FAILED` | 应用、回读或运行态加载失败 |
| 503 | `INTEGRATION_API_NOT_CONFIGURED` | 服务端未配置集成客户端 |

错误响应不回显 ZIP 内容、认证密钥、签名材料或内部异常正文。

## 8. 普通专家、密封 Agent 与超级专家

上层调用方始终使用相同的四个接口，不处理加密、签名或 Release 激活细节。

- 普通专家：替换可导出的源码集合，保留运行态目录和服务端字段。
- 密封 Agent：读取当前 Active Release 声明，平台重新签名一个 patch 版本，经现有安装、运行时验证和激活流程生效。
- 超级专家：除源码外保留当前能力、编排和平台契约声明；签名者还必须属于官方超级专家信任集合。

平台签名文件位于 `${QWENPAW_SECRET_DIR}/integration_delivery_signer.json`：

```json
{
  "signerId": "integration-delivery",
  "privateKey": "<base64 编码的 32 字节 Ed25519 私钥>"
}
```

文件应由运行用户持有并设置为 `0600`。对应公钥必须预先加入 `sealed_agents/trusted_signers.json`；若用于超级专家，还必须加入 `sealed_agents/official_super_expert_signers.json`。缺失、无效或公私钥不匹配时验证/发布失败，当前 Active Release 不变。

生产环境使用内置的幂等命令初始化并检查该身份，命令只输出状态，不输出私钥：

```bash
python -m qwenpaw.app.integration_delivery.signer_provisioning --provision
python -m qwenpaw.app.integration_delivery.signer_provisioning --check
```

`--provision` 只在文件不存在时生成私钥；重复执行沿用原密钥并补齐两个公钥信任库。同名 signer 已存在但公钥不一致时失败关闭，不覆盖任何密钥。首次配置或调整信任库后必须重启 DClaw，使密封 Agent 服务重新加载信任集合。

## 9. 共享 Agent 语义

本接口不增加环境锁或 Bot 级 Agent 副本。如果多个系统主动绑定同一个共享 Agent，更新仍按 DClaw 既有语义影响该 Agent 的所有使用方。测试与正式 AI 客服应由业务侧使用不同 Bot 和不同 Agent 隔离。

## 10. 调用顺序

上层补丁服务应固定执行：导出当前包 → 本地生成候选包 → 调用验证 → 获取业务侧写屏障 → 调用应用 → 更新业务侧状态机和标签 → 两侧回读。后续步骤失败时，使用本次 `operationId` 调用恢复，再释放业务侧写屏障。
