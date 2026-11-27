# Agent Mindspace

Mindspace is an independent knowledge-base layer for team knowledge and agent-private knowledge. It is separate from the ReMe memory system and exposes searchable knowledge to agents.

## Scopes

| Scope                 | Storage                            | Purpose                                                      |
| --------------------- | ---------------------------------- | ------------------------------------------------------------ |
| Global team library   | `$QWENPAW_WORKING_DIR/mindspace/`  | Knowledge searchable by all agents                           |
| Agent private library | `workspaces/{agent_id}/mindspace/` | Background, specs, and documents scoped to the current agent |

The existing `/workspace/cloud-docs` endpoints remain compatible, but are now backed by the Mindspace service.

## Sources

- Markdown / TXT: read directly, chunked, and indexed.
- PDF / DOCX: indexed only when text can be parsed; otherwise the document is marked failed with diagnostics.
- Feishu / Lark: an administrator configures the Open Platform app in the admin console; each user then authorizes their own Feishu/Lark account. QwenPaw uses the built-in connector by default. Missing app config or user authorization fails closed.
- Tencent Docs: an administrator configures the Tencent Docs open capability in the admin console; each user then authorizes their own Tencent Docs account. QwenPaw uses the built-in connector by default. Missing app config or user authorization fails closed.

## Cloud Document Flow

Cloud document access is split into two layers:

1. An administrator configures the platform app under **Admin / Cloud Docs Apps**: `Client ID`, `Client Secret`, `Redirect URI`, scopes, and token URL.
2. A user authorizes their own Feishu/Lark or Tencent Docs account from the Mindspace page.
3. When linking a cloud document, the user selects one of their authorized accounts.
4. The backend calls QwenPaw's built-in connector with that user's token, then parses, chunks, indexes, and writes generated Wiki entries.

The system does not use an administrator account to fetch user documents and does not scrape shared links. The built-in connector uses the current user's token with official APIs; the external connector URL is only an optional override for enterprise gateways, MCP connectors, or dedicated export services.

## APIs And Tools

- `GET /workspace/mindspace/search?q=&scope=&top_k=`
- `GET /workspace/mindspace/docs/{doc_id}`
- `GET /workspace/mindspace/connectors`
- Agent tools: `search_mindspace(query, scope?, top_k?)`, `read_mindspace_doc(doc_id, scope?)`

Search results include source metadata, document name, snippets, score, and scope so agents can cite the source. Keyword search is available now; semantic hybrid ranking can be enabled when embedding configuration is wired in.

## Connector Contract

Leave the external connector URL empty to use the built-in connector. If an enterprise deployment needs its own gateway, MCP connector, or export service, the optional admin-configured `Connector URL` receives:

```json
{
  "provider": "lark",
  "url": "https://...",
  "title": "Document title",
  "access_token": "current user's authorized token",
  "refresh_token": "current user's refresh token",
  "cloud_account_id": "cloud account id",
  "user_id": "QwenPaw user id"
}
```

It returns `{ "text": "..." }` or `{ "content": "..." }`. If the built-in or external connector is unavailable, the token has no permission, or the document cannot be exported, the document is marked `failed` with `last_error`.

Tencent Docs still supports the legacy `QWENPAW_TENCENT_DOC_FETCH_URL` as an external override fallback, but the product flow is admin-console configuration plus the built-in connector.
