# Super Agent `agent.execute` v2 (local upgrade draft)

This describes the AgentScope 2 lab implementation. It is not a published
Developer Pack contract or evidence that a target instance supports v2. The
lab starts from standard 2.62 / DevKit 1.9.29, while the other source tree
has progressed to standard 2.67 / DevKit 1.9.31. Reconcile those intervening
releases and their server behavior before assigning release version numbers.

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

The lab DevKit contains `schemas/agent-execute-v2/` and templates declaring
v2. These remain source-level development artifacts until the version baseline,
packaged schemas, examples and integration tests are reconciled. Do not build,
upload or deploy them as the currently numbered Pack 1.10.41.
