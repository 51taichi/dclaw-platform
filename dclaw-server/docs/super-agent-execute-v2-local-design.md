# Super Agent `agent.execute` v2 release contract

This document records the implementation notes for standard 2.68, Support
Plugin 1.18.58, Developer Pack 1.10.47, and DevKit 1.9.32. The normative
developer requirements are in `super-agent-development-standard-v1.zh-CN.md`;
the DevKit JSON Schemas are the machine contracts.

## Runtime contract

- A signed release declaring `agent.execute` version `2` enters its existing
  AgentScope Agent Loop when `execution_mode` is omitted. An explicit
  `agent_loop` has the same effect. Tool access remains subject to that
  release's grants and its Agent configuration.
- A v2 caller requests a model-only candidate with
  `execution_mode="candidate"`. Only this mode accepts
  `response_format="json_object"`. The Agent must validate the candidate
  before use; it is not a customer reply or a trusted operation receipt.
- Existing signed v1 releases retain their candidate default. Their explicit
  `agent_loop` still enters the loop; v1 does not accept `candidate`.
- Each expert keeps its own Skills, memory, model configuration and isolation
  scope. Missing expert-specific settings follow ordinary Agent defaults.
- Cards, AIGC and local helper operations remain Super Agent capabilities and
  require existing declarations, grants and trusted Host receipts. A common
  Agent Loop does not grant these capabilities automatically.

DevKit 1.9.32 contains `schemas/agent-execute-v2/`, reference calls, and new
templates declaring v2. Developer Pack 1.10.47 bundles that exact DevKit and
standard 2.68. Support Plugin 1.18.58 enforces the declared version at the Host
boundary; it does not infer v2 from the request or migrate an existing signed
v1 release.
