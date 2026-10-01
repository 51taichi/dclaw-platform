# Douyin Engagement Agent source

This directory is the source package for the single sealed Agent used by the DClaw Bot comment and private-message workflows.

## Local validation

```bash
uv run python scripts/validate_standard_agent_workspace.py \
  agent_sources/douyin_engagement_agent/agent \
  --agent-id douyin-engagement-agent

uv run pytest \
  tests/unit/app/sealed_agents/test_douyin_engagement_contracts.py \
  tests/unit/app/sealed_agents/test_douyin_engagement_runtime.py -q
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
