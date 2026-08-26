# 密封全局 Agent

密封 Agent 是可选能力：DClaw 可以配置 0 个、1 个或多个，未配置时不影响任何普通 Agent。它可以供所有客户在会话中调用，也可以发布为 OpenAPI 目标；对外能力固定为 invoke-only。

后台管理员只能看到公开名称、描述、启停状态、版本、签名者和内容摘要，不能查看、编辑、克隆、导出或下载提示词、Skill 与源文件。服务器 root 仍属于信任边界，可读取磁盘内容。

## 签名和上传

私钥只保留在发布环境，DClaw 服务器仅保存受信公钥。`trusted_signers.json` 位于运行目录的 `sealed_agents/` 下，格式为 `{ "signer-id": "<base64 raw Ed25519 public key>" }`。

准备 manifest JSON 后构建发布包：

```bash
uv run python scripts/build_sealed_agent.py \
  --source /path/to/luyu-agent \
  --manifest /path/to/manifest.json \
  --private-key /secure/path/ed25519-private-key.b64 \
  --output /tmp/luyu-1.0.0.zip
```

manifest 必须声明 `schema_version: 1`、`agent_type: "sealed"`、`scope: "global"`、`entrypoint: "agent/agent.json"`、语义版本和 signer ID；内容摘要由构建工具生成。随后在“设置 → 密封 Agent”上传并激活。

密封运行时使用独立会话目录，默认禁用 shell、文件读取、Python、Agent 委派、MCP 和插件工具；响应先在服务端收齐并通过防泄漏检查后才返回。备份不会包含密封 Agent，恢复也不能覆盖它们。
