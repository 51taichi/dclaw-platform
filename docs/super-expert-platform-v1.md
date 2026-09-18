# Super Expert Platform v1

This API is the generic platform capability layer used by officially signed super experts. It exposes platform primitives; it does not contain an Agent's business stages, Controller, Harness, Skills, scoring, or content methods.

## Shared implementation and dependency boundary

System APIs and super-expert APIs remain separate interfaces. Both use the same
AIGC core Services; neither makes an HTTP request to the other entrance.

- `app/aigc/` owns resource models/storage, canvases, asset access, model capability
  projection, workflow execution constraints, terminal results and generic events.
- `app/super_experts/service.py` owns installation/capability authorization and
  material-task commands. `aigc_adapter.py` converts accepted expert scope into
  explicit core Service calls; the HTTP router is not its implementation.
- `app/super_experts/aigc_event_adapter.py` maps durable core progress to the
  original authorized expert, conversation and material task. It checks the
  active installation, ownership, resource bindings and workflow revision before
  notification. Core services do not import this adapter or expert repositories.
- `app/runtime/aigc_media.py` composes authorized media-source access for both
  HTTP entrances using the shared Asset Service. The system entrance retains its
  existing legacy access policy; the expert entrance requires explicit ownership.

Generation success is not customer submission or expert approval. Core results
and generic events are persisted together; projection or notification failures
remain recoverable without changing a successful generation into failure.
Expert progress notifications are at-least-once and carry stable event IDs.
Consumers must deduplicate them. Same-node expert delivery is serialized through
fresh validation, persistence and publication so a late old result cannot be
published after a newer successful result. Failed notification retries do not
start generation, create a second billing order or mark material as accepted.

The application composes the optional expert consumer. Setting
`QWENPAW_SUPER_EXPERT_AIGC_EVENTS_ENABLED=false` disables that consumer only;
generic core recovery still operates. This is not a switch that disables the
entire expert API or changes installed grants. The default conversation scope
resolver uses the existing local tenant and rejects ambiguous chat/session IDs;
a deployment with a different tenant model needs a trusted matching resolver.

Existing managed workflows require migration of their trusted execution bindings
before rollout; editable canvas metadata is not authorization. The migration
tool defaults to dry-run, requires an existing initialized database and reports
conflicts rather than guessing missing blueprints or node mappings. Do not run
it against a live writer. See the [validation and rollout record](superpowers/reports/2026-09-06-platform-capability-service-boundary-validation.md)
for tested scope, backup/maintenance prerequisites and the dry-run command.

This refactor does not add MCP/RPA capabilities, a compositor, cross-card asset
versioning, or automatic business review. Local metadata/transport tests are not
evidence of live video generation or real expert approval.

## Capability groups

- Card: `card.create`, `card.update`.
- Human-guided AIGC: `aigc.task.create`, `aigc.task.resume`, `aigc.task.cancel`, `aigc.guide.update`, `aigc.asset.submit`, `aigc.review.complete`.
- Workflow AIGC: `aigc.workflow.capabilities.list/1`, `aigc.workflow.create/1`.
- Basic interaction: `interaction.capabilities.list/1`, `interaction.card.create/1`, `interaction.card.cancel/1`, with additive `single_select`, `multi_select`, and `question_form` components. The detailed immutable Agent contract is [DClaw Basic Interaction Capabilities v1](super-expert-interaction-agent-tools.md).
- Runtime orchestration and host capabilities are documented in [Workspace Turn Orchestration v1](workspace-turn-orchestration-v1.md).

Every command uses contract version `1`, an installation-bound grant, an idempotency key, a unique event ID, and the exact binding:

`installation_id + conversation_id + agent_task_id + content_revision + material_task_id + canvas_id + node_id`.

Assets are additionally bound by `asset_id`. A tenant, conversation, task, revision, canvas, node, material, or asset mismatch is rejected.

## Task lifecycle

`WAITING_TO_START → IN_PROGRESS → SUBMITTED → REVIEWING → ACCEPTED`

Review can instead produce `REVISION_REQUIRED`, followed by `IN_PROGRESS → SUBMITTED → REVIEWING`. Resuming a revision opens a new asset slot while immutable events retain the previously reviewed asset. `CANCELLED` and `INVALIDATED` are terminal. Refreshing or navigating away does not cancel the durable task; the guide resumes from the stored task, operation, canvas, node, and local step state.

Commands emit one idempotent standard event: `card.created`, `card.updated`, `aigc.task.created`, `aigc.task.resumed`, `aigc.task.cancelled`, `aigc.guide.updated`, `aigc.asset.submitted`, or `aigc.review.completed`. Duplicate identical commands replay their original result without duplicate runtime events. Reusing an event ID or idempotency key for different content fails.

## Card and guide behavior

Chat renders platform runtime events as task cards. Repeated clicks are idempotent. The deep link carries only trusted task identity; the AIGC page reloads the authoritative task and operation contract from DClaw.

The right-side guide uses stable control IDs from `src/qwenpaw/aigc/contracts/aigc-operation-contract-v1.json`. Each step declares its instruction, success signal, and recovery action. A missing control or incompatible contract blocks progress; neither the UI nor a model guesses a replacement. The generated novice manual is [AIGC Operation Manual v1](generated/aigc-operation-manual-v1.md).

## Workflow capability discovery

`aigc.workflow.capabilities.list/1` takes an empty arguments object. The Host first verifies that the signed installation grant contains this exact capability and version. Its response contains the closed DClaw node registry plus only models that are configured, published and priced in the current server:

```json
{
  "schema_version": 1,
  "nodes": [
    {
      "kind": "video_generate",
      "title": "视频生成",
      "provisioning": "AUTO_PROVISIONABLE",
      "capabilities": ["text_to_video", "image_to_video", "reference_video"],
      "input_keys": ["first_frame_asset_id", "last_frame_asset_id", "prompt", "reference_asset_ids"],
      "parameter_keys": ["aspect_ratio", "duration_seconds", "generate_audio", "resolution", "video_mode"],
      "input_slots": {"prompt": ["text"], "first_frame": ["image"]},
      "output_type": "video",
      "control_id": "aigc.video.generate-submit",
      "customer_actions": ["CLICK_GENERATE"]
    }
  ],
  "available_models": [
    {
      "provider_id": "provider-1",
      "provider_name": "Provider",
      "model_id": "video-1",
      "model_name": "Video One",
      "capability": "text_to_video",
      "source": "model_registry",
      "parameter_schema": {"type": "object"}
    }
  ]
}
```

All 11 current canvas node kinds are disclosed. `AUTO_PROVISIONABLE` nodes can be compiled into a real canvas, `MANUAL_ONLY` nodes can only enter the explicit blank-canvas fallback, and `UNAVAILABLE` nodes fail closed.

## Atomic workflow creation

The following objects are machine API payloads assembled by a deterministic Agent adapter. They are not raw model output. The model may return tolerant text or INI to its own adapter; DClaw receives and validates this strict typed object.

A one-node request:

```json
{
  "scope": {
    "installation_id": "installation-1",
    "conversation_id": "conversation-1",
    "agent_task_id": "content-1",
    "content_revision": 3,
    "material_task_id": "material-1"
  },
  "event_id": "workflow-create-1",
  "workflow": {
    "schema_version": 1,
    "title": "招生开场视频",
    "execution_preference": "CUSTOMER_TRIGGERED",
    "nodes": [{
      "node_id": "clip",
      "kind": "video_generate",
      "title": "生成开场视频",
      "capability": "text_to_video",
      "provider_id": "provider-1",
      "model_id": "video-1",
      "inputs": {"prompt": "真实课堂，竖屏纪实"},
      "parameters": {"aspect_ratio": "9:16", "duration_seconds": 5},
      "customer_action": "CLICK_GENERATE",
      "optional": false
    }],
    "edges": [],
    "output_node_id": "clip",
    "fallback_policy": "FAIL_CLOSED"
  }
}
```

A prompt → image → video workflow uses three semantic nodes and two typed edges:

```json
{
  "schema_version": 1,
  "title": "痛点开场三节点工作流",
  "execution_preference": "CUSTOMER_TRIGGERED",
  "nodes": [
    {"node_id":"copy","kind":"prompt","title":"提炼开场文案","capability":"storyboard","inputs":{"text":"失业后学抖音，从哪里开始？"},"parameters":{},"customer_action":"CLICK_GENERATE","optional":false},
    {"node_id":"keyframe","kind":"image_generate","title":"生成关键帧","capability":"text_to_image","provider_id":"provider-1","model_id":"image-1","inputs":{"prompt":"真实课堂，纪实摄影"},"parameters":{"aspect_ratio":"9:16"},"customer_action":"CLICK_GENERATE","optional":false},
    {"node_id":"clip","kind":"video_generate","title":"生成开场视频","capability":"image_to_video","provider_id":"provider-1","model_id":"video-1","inputs":{"prompt":"轻微推镜"},"parameters":{"aspect_ratio":"9:16","duration_seconds":5},"customer_action":"CLICK_GENERATE","optional":false}
  ],
  "edges": [
    {"source":"copy","target":"keyframe","target_slot":"prompt"},
    {"source":"keyframe","target":"clip","target_slot":"first_frame"}
  ],
  "output_node_id": "clip",
  "fallback_policy": "FAIL_CLOSED"
}
```

DClaw validates the graph, node/slot compatibility, model publication and pricing,
parameter bounds and owned assets before assigning physical IDs. Core creation
records a stable operation and resource snapshot, then persists the canvas and
trusted execution bindings. If the outer material-task write fails after the
core operation is APPLIED, that core canvas is retained; retry restores the same
task binding without creating another canvas. Legacy compensation may remove only
this operation's newly created, unused resources. Replays return the same
workflow; changed content under the same idempotency identity is rejected.

`MANUAL_BUILD_IF_UNSUPPORTED` applies only when the compiler identifies a registered `MANUAL_ONLY` node. It creates a genuinely empty canvas and records the unsupported reason. Invalid schemas, unavailable models, invalid prices/parameters, inaccessible assets, incompatible edges and `UNAVAILABLE` nodes never fall back.

## Security and failure rules

Only the exact capabilities declared by the current signed package and granted as a whole may be called. Ordinary Agents cannot self-upgrade by prompt or manifest text. Platform errors, timeouts, stale revisions, deleted bindings, missing controls, wrong assets, or unauthorized calls make no Agent business progress.

An accepted material is only a usable material. It cannot itself mark a complete content item as reviewed, publishable, or published. The Agent's own Controller and review Gate remain authoritative.

## v2 extension point

Version 1 is `HUMAN_GUIDED`: the customer performs stable operations with step-by-step assistance. Operation objects already use executor-independent `operation_id`, arguments, preconditions, expected result, idempotency, and version fields. A future v2 may add `AI_EXECUTED` or `HYBRID` executors without changing the Agent's business task semantics. v1 does not expose automatic publishing or arbitrary browser control.
