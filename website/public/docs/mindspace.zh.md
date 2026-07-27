# 智能体协同心智空间

心智空间是独立于 ReMe 记忆系统的知识库能力，用来管理团队资料和智能体私有资料，并把这些资料暴露给智能体检索引用。

## 知识范围

心智空间有两层知识库：

| 范围         | 存储位置                           | 用途                                       |
| ------------ | ---------------------------------- | ------------------------------------------ |
| 团队全局库   | `$QWENPAW_WORKING_DIR/mindspace/`  | 所有智能体都可以检索的团队知识             |
| 智能体私有库 | `workspaces/{agent_id}/mindspace/` | 只服务当前智能体的资料、项目背景和私有规范 |

控制台入口仍兼容旧的 `/workspace/cloud-docs` API，但后端实际由 Mindspace 服务处理。

## 支持的数据源

- Markdown / TXT：直接读取、切片并写入检索索引。
- PDF / DOCX：当前只在可解析为文本时入库；无法解析时会返回失败原因。
- 飞书 / Lark：管理员先在后台配置开放平台应用；用户再授权自己的飞书账号。默认使用 QwenPaw 内置 Connector 拉取正文，未配置或未授权时文档会标记为 `failed`，不会写入模拟正文。
- 腾讯文档：管理员先在后台配置腾讯文档开放能力；用户再授权自己的腾讯文档账号。默认使用 QwenPaw 内置 Connector 拉取正文，未配置或未授权时同样失败闭环，不索引假内容。

## 云文档进入系统的流程

云文档权限分两层：

1. 管理员在 **后台管理 / 云文档应用** 配置平台应用：`Client ID`、`Client Secret`、`Redirect URI`、授权 scopes 和 token URL。
2. 普通用户在心智空间页面点击授权，绑定自己的飞书或腾讯文档账号。
3. 用户关联云文档链接时，必须选择自己的授权账号。
4. 后端用该用户账号的 token 调用 QwenPaw 内置 Connector 拉取原文，随后解析、切片、索引并沉淀 Wiki。

系统不会使用管理员账号代拉用户文档，也不会网页抓取共享链接正文。内置 Connector 会使用当前用户 token 调官方 API；后台的外部 Connector URL 只是企业自有网关/MCP/专用导出服务的可选覆盖项。

## 同步阶段

文档记录会展示真实状态：

- `pending`：等待处理
- `fetching`：拉取云端正文
- `parsing`：解析文本
- `embedding`：语义向量化
- `indexing`：写入检索索引
- `ready`：可检索
- `failed`：失败，并带 `last_error`

删除文档时，系统会同时清理文档元数据、切片、索引记录和由该文档生成的 Wiki 词条。

## 检索与智能体工具

后端提供独立检索接口：

- `GET /workspace/mindspace/search?q=&scope=&top_k=`
- `GET /workspace/mindspace/docs/{doc_id}`
- `GET /workspace/mindspace/connectors`

智能体内置工具：

- `search_mindspace(query, scope?, top_k?)`
- `read_mindspace_doc(doc_id, scope?)`

工具返回来源、文档名、片段、分数和 scope，方便智能体在回答中引用资料。当前实现支持关键词检索；当 embedding 配置可用时可以扩展为语义 + 关键词混合检索。

## 连接器配置

默认留空外部 Connector URL，系统使用内置 Connector。若企业需要接自有网关/MCP/专用导出服务，可以在后台填写可选的外部 `Connector URL`，该地址需要接收：

```json
{
  "provider": "lark",
  "url": "https://...",
  "title": "文档标题",
  "access_token": "当前用户授权 token",
  "refresh_token": "当前用户 refresh token",
  "cloud_account_id": "用户授权账号 ID",
  "user_id": "QwenPaw 用户 ID"
}
```

外部连接器返回 `{ "text": "..." }` 或 `{ "content": "..." }`。如果内置/外部 connector 不可用、token 无权限、文档无法导出，系统会把文档标记为 `failed` 并记录 `last_error`。

腾讯文档仍兼容旧的 `QWENPAW_TENCENT_DOC_FETCH_URL` 作为外部覆盖兜底，但产品入口以后台管理页面配置和内置 Connector 为准。
