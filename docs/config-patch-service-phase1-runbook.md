# 配置补丁服务阶段一运行手册

阶段一是独立、只读的员工配置获取服务。员工可列出全部 Bot、读取配置上下文并下载可信工作包；服务不会写入 DClaw 或 AI 客服中台，也不提供上传、预检、发布和回退接口。AI 客服后台只负责管理员工 Codex Token。

## 环境变量

补丁服务必须使用与现有业务会话完全不同的凭据。生产值应由密码管理系统或受限环境文件注入，不写进仓库、Compose 或日志。

| 变量 | 用途 |
| --- | --- |
| `CONFIG_PATCH_DATA_DIR` | 独立 SQLite、内容寻址对象和工作包目录 |
| `CONFIG_PATCH_TOKEN_PEPPER` | 员工 Token HMAC Pepper；丢失后现有 Token 全部失效 |
| `CONFIG_PATCH_ADMIN_SECRET` | AI 客服后台服务端调用 Token 管理接口的专用密钥 |
| `DCLAW_CONFIG_PATCH_INTERNAL_SECRET` | 补丁服务只读访问 DClaw 的专用密钥 |
| `DCLAW_CONFIG_PATCH_ALLOWED_ORIGINS` | 可接收上述专用密钥的 DClaw Origin 精确白名单，多个值用逗号分隔 |
| `OMNICHANNEL_CONFIG_PATCH_INTERNAL_SECRET` | 补丁服务只读访问 AI 客服中台的专用密钥 |
| `OMNICHANNEL_CONFIG_PATCH_BASE_URL` | AI 客服中台的服务端地址 |
| `CONFIG_PATCH_HOST` / `CONFIG_PATCH_PORT` | 独立监听地址和端口，默认 `0.0.0.0:8788` |

同时在 DClaw 主进程配置同一个 `DCLAW_CONFIG_PATCH_INTERNAL_SECRET`；在 AI 客服中台配置同一个 `OMNICHANNEL_CONFIG_PATCH_INTERNAL_SECRET`，以及补丁服务的 `CONFIG_PATCH_ADMIN_BASE_URL` 和 `CONFIG_PATCH_ADMIN_SECRET`。员工 Token 不配置到上述两个业务进程。

## 启动与健康检查

先生成五个彼此独立的高熵值，放入仅部署账号可读的环境文件，然后显式启动新增 Compose 文件：

```bash
docker compose --env-file /opt/dclaw-config-patch/config-patch.env \
  -f deploy/config-patch.compose.yaml up -d --build
curl --fail --silent http://127.0.0.1:18788/health
```

健康接口不需要员工 Token，只返回服务名、阶段版本和状态，不返回地址或密钥。公网入口应由现有 HTTPS 反向代理转发到 `127.0.0.1:18788`；只开放 `/staff/v1/*` 给员工。`/internal/admin/v1/*` 只允许 AI 客服后台的服务端访问。

## 本地 Smoke Test

以下占位符必须在当前 shell 中临时替换，不要把真实值写入命令历史或工单：

```bash
curl --fail https://patch.example.com/health

curl --fail -X POST https://patch.example.com/internal/admin/v1/staff-tokens \
  -H 'X-Config-Patch-Admin-Secret: <内部管理员密钥>' \
  -H 'Content-Type: application/json' \
  --data '{"employeeName":"联调员工","tokenName":"Codex 临时设备"}'

curl --fail https://patch.example.com/staff/v1/bots \
  -H 'Authorization: Bearer <员工_TOKEN>'

curl --fail https://patch.example.com/staff/v1/bots/<BOT_ID>/configuration-context \
  -H 'Authorization: Bearer <员工_TOKEN>'

curl --fail -X POST \
  https://patch.example.com/staff/v1/bots/<BOT_ID>/workspace-bundles/export \
  -H 'Authorization: Bearer <员工_TOKEN>' \
  --output /tmp/dclaw-workspace.zip

unzip -l /tmp/dclaw-workspace.zip
unzip -p /tmp/dclaw-workspace.zip dclaw-manifest.json
```

预期 ZIP 至少包含 `dclaw-manifest.json`、`AGENTS.md`、`change-plan.yaml`、`agent/`、`knowledge/`、`customer-service/` 和 `platform/`。第一次成功导出返回 `X-DClaw-Release-Id: R1`；重复下载同一稳定快照的摘要保持一致。

## 密钥轮换

- 员工 Token：管理员在 AI 客服后台的“Codex Token”页点击“轮换”，旧 Token 立即失效，新 Token 只显示一次。
- `CONFIG_PATCH_ADMIN_SECRET`：先同时准备补丁服务和 AI 客服中台的新值，在维护窗口依次重启；不允许双值长期并存。
- 两个上游内部密钥：分别同步修改参与者和补丁服务后重启，并用 health、Bot 列表和一次工作包导出验证。
- `CONFIG_PATCH_TOKEN_PEPPER`：属于全量吊销操作。修改后所有员工 Token 都必须重新创建，并应记录维护原因。

任何密钥轮换都不得打印环境变量、完整 Authorization 或完整 Token。

## 备份与恢复

停止补丁服务或使用 SQLite 在线备份后，完整备份 `CONFIG_PATCH_DATA_DIR`。数据库与 `objects/` 必须作为同一恢复点保存；只恢复数据库或只恢复对象目录都会破坏 Release 可验证性。备份应加密并限制到平台管理员。

恢复时先停止服务，将整个目录恢复到临时路径，校验文件权限和容量，再原子替换目标目录并启动。恢复不需要、也不得覆盖 DClaw 与 AI 客服业务数据库。

## 审计查询

审计表记录动作、员工、Token ID、结果、Bot、Release 和相关摘要，不记录完整 Token。示例只读查询：

```bash
sqlite3 "$CONFIG_PATCH_DATA_DIR/config-patch.sqlite3" \
  'SELECT created_at, action, token_id, employee_name, result, metadata_json FROM audit_events ORDER BY created_at DESC LIMIT 100;'
```

调查下载事件时使用 Token ID、Bot ID、Release ID 和 bundle digest 关联，不要索取员工的完整 Token。

## ADMIN_BOOTSTRAP_REQUIRED 排查

该机器码表示 Bot 尚未具备可正常对话和可编辑的管理员基线。按响应中的全部 `missingItems` 一次性处理：

- `agent_bound` / `agent_enabled` / `bot_enabled`：在 AI 客服后台完成 Bot 与 Agent 绑定并启用。
- `dclaw_location_configured`：补全该 Agent 的 DClaw 服务端定位信息。
- `agent_source_snapshot`：由 DClaw 平台管理员完成第一次 Agent 套包上传；超级专家必须有受保护的已签名源 Release。
- `openapi_publication` / `billing_account` / `knowledge_base`：由 DClaw 平台管理员建立 OpenAPI、积分归属和经验库关系。
- `flow_readable` / `tags_readable`：修复 AI 客服中台对应的只读配置。

不要通过员工接口创建第一个 Agent 包，也不要手工改补丁服务数据库绕过缺失项。

## 停用与回滚

阶段一停用只需停止独立服务并从反向代理移除入口：

```bash
docker compose --env-file /opt/dclaw-config-patch/config-patch.env \
  -f deploy/config-patch.compose.yaml stop
```

随后可移除 AI 客服后台的两个补丁服务环境变量以让 Token 页安全返回 503。DClaw 和 AI 客服的原业务继续运行；无需回滚 DClaw 或 AI 客服业务数据。保留 `config-patch-data` 卷和加密备份以便审计或恢复，不要直接删除。
