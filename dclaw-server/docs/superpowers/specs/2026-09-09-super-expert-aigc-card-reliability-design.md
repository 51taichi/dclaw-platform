# Super Expert AIGC Card Reliability Design

## Context

Local production-like testing exposed two independent failures in the Luyu S9 AIGC path:

1. A workflow request for an apparel conversation was rejected, yet an AIGC job belonging to an older Tianmen training canvas ran and its output was appended to the apparel conversation as a generic workspace artifact.
2. A text-to-image workflow used `resolution: "1080x1920"`. DClaw accepts resolution quality enums such as `1080P` and rejected the request with `PARAMETER_INVALID`, so no material task or AIGC card was created. The customer-facing reply nevertheless claimed that creation and multiple retries had succeeded, while the audit contained one failed platform call.

The goal is to make valid Super Expert AIGC requests reliably create a correctly bound card, make infrastructure failures explicit and recoverable, and prevent any cross-conversation card or artifact projection. This design does not add a second business judge: the model continues to own content strategy and workflow intent; trusted code only owns transport contracts, platform identities, persistence, and real effect receipts.

## Success Criteria

- A valid S9 workflow creates exactly one material task and one card bound to the current installation, conversation, content task, content revision, and material task.
- Common equivalent transport values are canonicalized before workflow compilation; for example, portrait or landscape `1080x1920`/`1920x1080` resolution aliases become `1080P` while `aspect_ratio` remains the source of orientation.
- Optional technical parameters that are omitted use platform defaults. Unknown values that cannot be safely canonicalized are returned as a precise infrastructure error and are never represented as success.
- Current inbound image attachments are registered as user-owned AIGC assets before the model prepares a reference workflow. The model receives real opaque asset IDs and never needs placeholder IDs.
- A reference workflow can use only assets owned by the current user and exposed for the current conversation turn.
- A card is announced only from a real platform creation receipt. A failed call leaves `AIGC素材任务` absent and the current S9 state intact.
- Generic workspace artifact discovery never projects `aigc_studio/**`. Formal AIGC outputs are projected only through a material-task binding that matches the current conversation.
- Concurrent conversations for the same user and same sealed Agent release cannot see, execute, or receive one another's cards, canvases, jobs, or outputs.
- The local deployed build passes unit, integration, browser/API card-loading, and repeated live creation smoke tests.

## Non-Goals

- No business-field, stage-completion, method-selection, content-quality, or model-reply validator is introduced.
- DClaw does not invent prompts, models, media strategy, or business conclusions.
- The platform does not claim that an external image/video provider will be available 100% of the time. Provider outages remain real failures with durable diagnostics.
- A failed creation does not produce a fake or empty card merely to make the UI appear successful.
- Historical material tasks are not deleted by this change.

## Considered Approaches

### 1. Prompt-only tightening

Teach Luyu the current enums and examples and leave the host unchanged. This is small but cannot guarantee transport correctness, cannot register inbound attachments, and does not solve shared-workspace artifact leakage.

### 2. Contract-driven model request plus trusted infrastructure canonicalization and binding (selected)

DClaw publishes an exact machine-readable workflow catalog, registers inbound attachments as owned AIGC assets, canonicalizes only safe transport aliases, compiles and persists the workflow transactionally, and projects outputs through conversation-bound receipts. Luyu still chooses the workflow from the catalog. This preserves the model-owned business architecture while making the platform boundary reliable.

### 3. Host-built workflows from a high-level content intent

Have Luyu return only a high-level request and let DClaw choose all nodes and models. This would reduce malformed requests but moves content-production decisions from the model into host code and conflicts with the agreed Luyu architecture.

## Architecture

### Contract source of truth

The server workflow registry and compiler remain authoritative. The capability catalog must expose, for every node kind:

- allowed `customer_action` values;
- allowed capabilities;
- allowed input keys and slots;
- allowed parameter keys;
- exact parameter value domains and defaults;
- available provider/model/capability combinations.

The Luyu prompt context consumes this catalog directly. The checked-in Agent reference contract is generated from or tested against the server contract so it cannot silently drift.

### Inbound attachment registration

When DClaw normalizes a customer message, eligible inbound image, video, and audio attachments are registered in the global AIGC asset store under the authenticated user. The sealed Agent receives a safe projection containing only:

- `asset_id`;
- media kind and MIME type;
- display name;
- current conversation association;
- whether the asset is eligible as a workflow reference.

The sealed Agent never receives storage credentials. Files that cannot be registered remain ordinary inbound attachments and are marked unavailable for workflow references. A reference node must use an exposed real `asset_id`; strings such as `INPUT_ASSET_ID_FROM_HOST` and `PLACEHOLDER_ASSET_ID_FROM_HOST` are not accepted or synthesized.

### Transport canonicalization

A dedicated canonicalizer runs at the Super Expert AIGC workflow boundary before semantic compilation. It may perform only deterministic infrastructure conversions that preserve intent:

- trim surrounding whitespace in identifiers and enum strings;
- canonicalize documented resolution aliases, including `1080x1920` and `1920x1080` to `1080P`, and `720x1280` and `1280x720` to `720P`;
- canonicalize case-only differences for documented enums;
- omit an optional parameter only when the registry declares a platform default and the supplied value is an empty transport value.

It must not change prompts, models, capabilities, node topology, review nodes, customer business data, or unsupported non-empty values. Every canonicalization is recorded in a safe audit entry with the field path, original value, and canonical value.

### Creation and receipt semantics

The creation command uses one idempotency key at the command envelope. The workflow payload contains only fields accepted by `AigcWorkflowCreateArguments`. Creation follows this order:

1. validate and canonicalize transport data;
2. resolve every referenced asset against the authenticated owner;
3. compile the workflow;
4. provision the canvas;
5. persist the material task and binding;
6. emit the creation event and return the binding receipt.

Only step 6 permits Luyu to save `AIGC素材任务` or tell the customer a card exists. Replaying the same idempotency key returns the same bound task. A failure before persistence returns a stable error with structured field diagnostics and leaves no partial card.

The model receives the real failure result in its next prompt context. Prompt rules require it to describe the known failure or choose a valid alternative, never claim an unobserved retry or success. The runtime does not rewrite the model's reply after generation.

### Conversation and artifact isolation

Sealed Agent release workspaces may remain shared for immutable code, but mutable task files must be written beneath a conversation-owned directory. The generic console artifact scanner applies these rules:

- include only `sessions_data/<current_session_id>/**` and explicitly registered current-chat artifacts;
- exclude bare `aigc_studio/**` from generic file-change cards;
- never strip a foreign session prefix into an apparently local path;
- never infer AIGC ownership from file modification time.

AIGC cards and outputs use the platform repository rather than file scanning. Before projection or execution, the complete binding must match authenticated user, installation, conversation, material task, canvas, node, content task, and content revision as applicable.

## Error Handling and Diagnostics

- Pydantic/schema failures include safe field paths and error categories in internal logs.
- Compiler failures include the node ID and parameter/input field path when available.
- Provider submission and polling failures retain provider task identifiers and attempt history without exposing credentials.
- Luyu state stores the raw platform result for the attempted operation and does not convert a failed result into a material task.
- Debug output may expose stable error codes and safe field paths, but not prompts from another conversation, credentials, or private model reasoning.
- The customer-visible reply remains the model's original reply. Reliability comes from complete pre-call context and real receipts, not post-reply filtering.

## Testing Strategy

### Agent contract tests

- The workflow prompt contains exact server-supported resolution enums and node actions.
- A text-to-image example uses `1080P` or omits resolution, never pixel dimensions.
- Reference examples use only host-provided real asset IDs.
- A failed creation result remains failed and does not populate `AIGC素材任务`.
- The following valid requests are covered: one text-to-image node, two text-to-image nodes plus output, reference image edit, image-to-video DAG, and mixed text/image review outputs.

### Server unit tests

- Safe resolution aliases canonicalize to platform enums.
- Unsupported non-empty parameter values still fail with a precise field path.
- Attachment registration enforces user and conversation ownership.
- Placeholder reference asset IDs are rejected with a precise error.
- Generic artifact filtering excludes `aigc_studio/**`.
- A foreign `sessions_data` directory is never scanned or projected.

### Integration tests

- Each valid workflow produces a material task, canvas, binding, guide, and loadable card.
- Repeating the command is idempotent and creates no duplicate card.
- Invalid creation produces no task, canvas leak, or success event.
- Two concurrent conversations using the same Agent release remain isolated when both generate assets.
- An output generated for conversation A never appears in conversation B's message artifacts, card list, canvas endpoint, or asset endpoint.

### Local deployment verification

- Build and deploy current `main` DClaw server/client images.
- Build and install a new local-signed Luyu package.
- Create fresh conversations and run repeated card creation for text-to-image, two-image, reference-image, and image-to-video scenarios.
- Verify card appearance without refresh, card loading, task parameter display, job execution, and output projection.
- Re-run an apparel conversation beside a Tianmen test conversation and verify there is no cross-session output.

## Release and Rollback

Server and client changes remain on local `main` and are not pushed until explicitly requested. The Luyu package receives the next patch version and is built with the local signing key for local deployment; the production-signed package is built separately when requested. Rollback consists of restoring the prior local images and prior active Luyu release. Existing historical tasks remain readable.

## Acceptance Boundary

“Reliable creation” means every request that can be represented by the current catalog, has available provider/model capacity, and references accessible owned assets either creates a correctly bound card or returns a precise recoverable infrastructure error. External provider downtime, exhausted account capacity, or genuinely unsupported workflows cannot be converted into success, but they must never produce a false card, false success statement, or cross-conversation artifact.
