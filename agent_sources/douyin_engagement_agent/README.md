# Douyin Engagement Agent source

This directory is the source package for the single sealed Agent used by the DClaw Bot comment and private-message workflows.

## Local validation

```bash
uv run python scripts/validate_standard_agent_workspace.py \
  agent_sources/douyin_engagement_agent/agent \
  --agent-id douyin-engagement-agent

uv run pytest \
  tests/unit/app/sealed_agents/test_douyin_engagement_contracts.py \
  tests/unit/app/sealed_agents/test_douyin_engagement_runtime.py \
  tests/contract/test_douyin_engagement_fixtures.py -q
```

## User-operated packaging

Copy `manifest.template.json`, replace the version and approved signer ID, then sign it with a user-controlled Ed25519 private key:

```bash
uv run python scripts/build_sealed_agent.py \
  --source agent_sources/douyin_engagement_agent/agent \
  --manifest /path/to/manifest.json \
  --private-key /path/to/private-key.base64 \
  --output /path/to/douyin-engagement-agent.zip
```

The repository intentionally contains no production key. Uploading, installing, publishing, and binding the resulting package are deployment actions performed by the operator; they are not part of this source implementation.

## Operator handoff

After the local gates pass, the operator performs the live steps with credentials they control:

1. Copy `manifest.template.json`, choose an immutable semantic version, and set an approved signer ID. Do not put the private key or an API key in this repository.
2. Run the packaging command above and retain the ZIP digest and manifest beside the release record.
3. In DClaw, register the signer public key, then open **设置 → 密封 Agent**, upload the ZIP, inspect validation output, install it, and activate that exact version.
4. In **Open API**, publish the activated sealed Agent as an Agent target. Enable it, grant `messages:create`, bind a dedicated application/API key, and copy the generated stable Public ID. Persistent sessions are required for private-message operations; isolated attempts are used by the comment-plan operations requested by Bot Server.
5. In Bot Server, open **系统设置 → DClaw Agent** and enter the DClaw base URL, Public ID, dedicated API key, capability version `2`, and timeout. Save, then use **测试连接** before enabling any Agent-backed strategy.
6. Start with controlled test accounts. Verify request audit, persistent private conversation continuity, isolated comment planning, error alarms, and quota behavior before production use.

Source validation and fixture tests do not upload, install, activate, publish, or call a live Agent. Those state-changing operations remain explicitly user-operated.
