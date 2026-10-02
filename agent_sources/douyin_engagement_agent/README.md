# Douyin Engagement Agent source

`workspace/` is the deployable ordinary DClaw Agent used by the DClaw Bot comment and private-message workflows. It follows the same workspace model as other business Agents: `agent.json`, prompt files, `skill.json`, and local Skills. It is not a sealed Agent and does not require a signer or a sealed-Agent installation.

The older `agent/` orchestration runtime and `manifest.template.json` remain only as contract-test reference material. They are not the deployment target.

## Local validation

```bash
uv run pytest \
  tests/unit/app/test_douyin_engagement_standard_agent.py \
  tests/unit/app/sealed_agents/test_douyin_engagement_contracts.py \
  tests/unit/app/sealed_agents/test_douyin_engagement_runtime.py \
  tests/contract/test_douyin_engagement_fixtures.py -q
```

The sealed-runtime tests remain in the gate because they exercise the same five wire contracts consumed by Bot Server. Passing them does not make the ordinary workspace a sealed Agent.

## Package

Create a ZIP whose single wrapper directory contains the contents of `workspace/`. DClaw's normal Agent import page accepts that package and discovers `agent.json` plus the local Skill.

```bash
mkdir -p /tmp/douyin-engagement-agent-package/douyin-engagement-agent
cp -R agent_sources/douyin_engagement_agent/workspace/. \
  /tmp/douyin-engagement-agent-package/douyin-engagement-agent/
(cd /tmp/douyin-engagement-agent-package && \
  zip -qr /path/to/douyin-engagement-agent-v1.0.0.zip douyin-engagement-agent)
```

The package contains no model key, OpenAPI key, Bot credential, or customer data.

## Operator handoff

After the local gates pass, the operator performs the live steps with credentials they control:

1. In the server DClaw Agent page, import the ZIP as a normal Agent and select an available model.
2. Test `HEALTH_CHECK` in a fresh conversation and confirm the response is exactly `{"ok":true,"capabilityVersion":"2"}`.
3. In **Open API**, publish the Agent as a target. Enable it, grant `messages:create`, bind a dedicated application/API key, and copy the stable Public ID.
4. Send the DClaw base URL, Public ID, and dedicated API key to the Bot Server operator through a secure channel. Persistent sessions are required for private-message operations; isolated attempts are used for comment-plan operations.
5. In Bot Server, save the Agent configuration and use **测试连接** before enabling any Agent-backed strategy.
6. Start with controlled test accounts. Verify request audit, persistent private conversation continuity, isolated comment planning, error alarms, and quota behavior before production use.

Source validation and fixture tests do not upload, import, publish, or call a live Agent. The first server import and OpenAPI publication remain explicitly user-operated.
