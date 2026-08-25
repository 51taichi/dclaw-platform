# Sealed Global Agents Design

## Summary

DClaw will support an optional class of globally callable agents whose implementation assets remain unavailable to every DClaw application-layer role. The first such agent is Lu Yu (`luyu`), delivered as a DClaw-compatible ZIP containing its own skills and operating rules.

Sealed agents are optional platform assets with cardinality `0..N`. DClaw must work normally when none exist, and the failure of one sealed agent must not affect ordinary agents or other sealed agents. A sealed global agent may be called through DClaw conversations and through a published OpenAPI endpoint, but callers receive only public metadata, final business output, and approved generated artifacts. Customers, tenant administrators, and DClaw system administrators cannot inspect, edit, clone, export, or download its implementation.

The threat model covers DClaw users and application-layer administrators. Host root users, cloud account owners, database operators, and infrastructure administrators are trusted and are outside this design's confidentiality boundary.

## Goals

- Support zero, one, or many sealed agents without making them a DClaw startup dependency.
- Make a sealed agent globally discoverable and callable while keeping its ZIP, rules, skills, tools, configuration, workspace, traces, and internal files unavailable through DClaw.
- Enforce confidentiality in the backend even when callers bypass the frontend.
- Permit `invoke_only` OpenAPI publication of a sealed agent.
- Accept only signed, validated packages and preserve a known-good version when a release fails.
- Keep ordinary agent behavior and management flows unchanged.
- Provide a reusable model for future sealed agents rather than hard-coding Lu Yu.

## Non-goals

- Preventing host root or infrastructure operators from reading disk or process memory.
- Making a callable agent reveal nothing about its observable expertise or behavior. Normal answers inevitably reveal capability characteristics.
- Providing online editing of sealed agents.
- Supporting tenant-private sealed agents in the first release.
- Exposing internal tool events, retrieved context, chain of thought, or raw traces to callers.
- Treating model instructions as the security boundary.

## Domain Model

The initial domain model adds two independent attributes to an agent:

```text
agent_type = standard | sealed
scope      = private | tenant | global
```

The first release supports `sealed + global`. The schema leaves room for other combinations, but APIs must reject unsupported combinations rather than silently accepting them.

Lu Yu is represented as:

```text
agent_id   = luyu
agent_type = sealed
scope      = global
```

Sealed status is immutable for an installed agent identity. A standard agent cannot be converted into a sealed agent, or vice versa, through an update endpoint. Migration requires publishing a distinct agent identity so that ordinary workspace files cannot accidentally become sealed or sealed assets accidentally become ordinary.

### Public metadata

Public metadata is safe to return to any caller allowed to discover the agent:

- Stable agent ID
- Display name, icon, and public description
- Public capability tags and usage guidance
- Availability state
- Public release version
- Optional public release notes

### Protected metadata

Operational metadata is visible only on the sealed-agent administration page and must not expose package contents:

- Content digest
- Signer ID
- Release and activation timestamps
- Installation and health state
- Sanitized release failure code
- OpenAPI publication state and aggregate usage

### Sealed assets

The following are never returned through application APIs:

- Original or normalized ZIP package
- Package file list beyond explicitly public assets
- Agent instructions and operating rules
- Skills and skill metadata not declared public
- Tool definitions and private configuration
- Workspace and internal files
- Raw retrieval context, tool inputs, and tool outputs
- Full traces, model context, and unsanitized exceptions

## Authorization Model

Authorization first evaluates asset policy, then the caller's role. A high application role cannot override a sealed denial.

| Capability | Customer | Tenant admin | DClaw system admin | Release service |
| --- | ---: | ---: | ---: | ---: |
| Discover public metadata | Allow | Allow | Allow | Allow |
| Invoke enabled agent | Allow | Allow | Allow | Test only |
| View protected release metadata | Deny | Deny | Allow | Allow |
| Publish signed package | Deny | Deny | Allow | Allow |
| Enable, disable, or roll back | Deny | Deny | Allow | Allow |
| Manage OpenAPI publication | Deny | Subject to existing policy | Allow | Deny |
| Inspect workspace, skills, config, or tools | Deny | Deny | Deny | Deny |
| Edit, clone, export, or download | Deny | Deny | Deny | Deny |
| Read raw traces or internal logs | Deny | Deny | Deny | Deny |

The release service is a narrow backend component, not an interactive user role. It can validate and install a package but has no generic content-reading endpoint.

Backend responses return explicit capabilities so clients render from server decisions:

```json
{
  "agent_id": "luyu",
  "name": "陆羽",
  "agent_type": "sealed",
  "scope": "global",
  "capabilities": {
    "invoke": true,
    "inspect": false,
    "edit": false,
    "clone": false,
    "export": false,
    "download": false
  }
}
```

A centralized sealed-agent policy must guard workspace, file, skill, configuration, tool, backup, restore, export, clone, download, trace, and debug endpoints. Route-specific checks may add restrictions but must not replace the central policy. Direct requests to a prohibited endpoint return a stable `403` without confirming file names, paths, or asset existence.

## Package and Signature Format

A sealed agent is delivered as a signed DClaw-compatible ZIP:

```text
luyu-agent.zip
├── manifest.json
├── public/
│   ├── icon.png
│   └── description.md
├── agent/
│   ├── AGENTS.md
│   ├── skills/
│   ├── config/
│   └── ...
└── signature.json
```

The manifest contains only fields required to validate, run, and publicly describe the release:

```json
{
  "schema_version": 1,
  "agent_id": "luyu",
  "name": "陆羽",
  "version": "1.0.0",
  "agent_type": "sealed",
  "scope": "global",
  "entrypoint": "agent/AGENTS.md",
  "public_metadata": {
    "description": "Public capability description"
  },
  "content_digest": "sha256:...",
  "signer_id": "dclaw-primary"
}
```

The package specification must define a deterministic digest algorithm: normalized relative paths sorted by UTF-8 byte order, explicit file mode handling, exact file bytes, and exclusion of `signature.json` from the signed payload. The signature covers the manifest and every packaged asset through the content digest. Ambiguous or duplicate normalized paths are invalid.

The first release supports one trusted signing public key while storing `signer_id` on every release. Private signing keys remain in the development or release environment and are never uploaded to DClaw. Future key rotation can add trusted public keys and revoke signers. Revoking a signer prevents new installations; disabling already installed releases is a separate explicit operation.

## Publication Workflow

The administration UI provides a one-way **Sealed Agent Release** flow rather than an editor.

1. Codex builds a DClaw-compatible package.
2. A separate release tool computes the deterministic digest and signs it with the release private key.
3. A DClaw system administrator uploads the signed ZIP.
4. The backend streams it into a private staging area with request-size limits.
5. Validation rejects excessive file count, compressed size, expanded size, compression ratio, unsupported file type, absolute path, path traversal, duplicate normalized path, device file, hard link, and symbolic link.
6. The backend validates schema, signature, digest, signer trust, agent identity, and version policy before installing files.
7. The release is unpacked into a non-public staging directory and subjected to DClaw package validation and an isolated startup smoke test.
8. A successful release is stored as immutable versioned content.
9. Activation atomically switches the current version pointer. In-flight calls may finish on the old version; new calls use the new one.
10. A failed validation or startup leaves the current version untouched and returns only a sanitized error code.

Administrators may enable, disable, activate, and roll back to an already validated release. They cannot inspect file lists, view diffs, edit files, or download packages. Rollback selects immutable content by release ID and never rebuilds it.

Suggested release states are:

```text
uploaded -> validating -> staged -> testing -> ready -> active
                     \-> rejected
                                  \-> failed
active -> superseded
active <-> disabled
```

State transitions use compare-and-swap or equivalent transactional protection so concurrent uploads and activation requests cannot select an unintended version.

## Storage and Runtime Isolation

Sealed package content is stored separately from ordinary agent workspaces and outside all application file-serving roots. The database stores registry and release metadata, not package source text. An internal release ID maps to the private content location; public APIs never return that location.

At runtime, the agent receives two distinct areas:

```text
sealed read-only area
├── instructions
├── skills
└── private configuration

per-session working area
├── user uploads
├── generated working files
└── candidate output artifacts
```

Generic model-facing file tools can access only the per-session working area. Sealed content is loaded by trusted runtime components and is not addressable through file tool parameters. Path authorization resolves canonical real paths and rejects links or mount escapes. Copy, archive, backup, restore, and attachment services apply the same boundary.

Shell access is disabled for sealed agents by default. If a future sealed agent requires it, the package must declare the requirement, the signer policy must allow it, and execution must occur in a dedicated sandbox whose filesystem and network policy cannot reach sealed source assets through model-selected commands. This exception is not part of the first Lu Yu release unless demonstrated as necessary.

The runtime exposes only the tools required for the current task. A sealed agent cannot call DClaw APIs that enumerate or export its own definition, skills, configuration, releases, or traces.

## Conversation Output Policy

Only two caller-visible output classes exist:

- `final_output`: normal business response text.
- `artifact`: a file generated in the per-session working area and approved for release.

The platform must not emit system instructions, skill content, internal configuration, sealed paths, internal tool definitions, raw tool arguments or results, retrieval chunks, chain of thought, debug stacks, or files originating from the sealed area.

Defense is layered:

- System guidance tells the agent not to reveal internal assets, but is not treated as enforcement.
- Tool and filesystem policies make source assets unavailable to model-selected reads or copies.
- A response policy detects high-similarity passages from protected text, package canaries, suspiciously large encoded payloads, and prohibited internal identifiers.
- Session- and principal-level controls aggregate repeated extraction attempts across turns.
- Output and artifact size limits reduce bulk exfiltration.
- High-risk extraction requests can be rejected before execution.
- A policy rejection produces a stable public message and a structured security event, not an explanation containing matched content.

Similarity detection must be tuned with an evaluation corpus to avoid blocking legitimate domain answers. Protected-source matching is a secondary control; isolation remains the primary boundary.

## OpenAPI Publication

A sealed global agent may be selected as an OpenAPI publication target. The existing publication layer resolves an API key to a fixed server-side target. Callers cannot override `agent_id`, `team_id`, DClaw user identity, or output policy through headers, query parameters, or request bodies.

Every sealed-agent publication is forced to:

```json
{
  "target_type": "agent",
  "target_id": "luyu",
  "allowed_capability": "invoke_only",
  "response_policy": "sealed",
  "enabled": true
}
```

The backend rejects attempts to create a more permissive publication for a sealed target. Synchronous, streaming, and continued-session calls are permitted. Streaming exposes only a stable public event vocabulary:

```text
response.started
response.output_text.delta
response.artifact.ready
response.completed
response.failed
```

Internal tool calls, handoffs, retrieval events, trace identifiers, internal paths, and raw exceptions are never serialized. Failure responses use stable error codes such as unavailable, rate limited, invalid request, and policy blocked.

OpenAPI controls retain existing API-key authentication, quotas, rate limits, expiry, and audit behavior. Disabling a publication stops external calls without disabling internal DClaw use. Disabling the agent stops new internal and external calls. An absent or unhealthy target returns `503` without affecting other publications.

## Frontend Design

The separated frontend at `/Users/moxi/Desktop/codex space/dclaw-client` renders backend capabilities and never infers sealed access from a role alone.

### Customer experience

Enabled sealed global agents appear in approved discovery surfaces and agent selectors with public name, icon, description, capabilities, and availability. Customers can start and continue conversations. They do not see workspace, skill, configuration, tool, clone, export, download, version, trace, or debug controls.

The conversation page hides skill selectors, internal execution details, source chunks, file paths, raw errors, and tool-event panels for a sealed agent. It displays final output, approved artifacts, and generic progress or policy messages.

### Administration experience

Ordinary agents retain their existing management pages. Selecting a sealed agent opens a dedicated read-only operational page rather than the existing Workspace, Skills, Config, or Tools routes. It shows public information, availability, current version, digest, signer, activation time, sanitized health, aggregate usage, and OpenAPI publication status.

Allowed administration actions are:

- Upload a signed release
- Test invocation through the public execution contract
- Activate, disable, or roll back a validated version
- Create, rotate, disable, or revoke an `invoke_only` OpenAPI publication
- View aggregate operational and security-event counts

Direct navigation to a prohibited existing route redirects to the sealed detail page or shows an access-denied state. The backend still returns `403` for the underlying request.

### Release page

The release page shows upload progress and sanitized phases:

```text
upload complete
package validation passed
signature verification passed
startup test passed
version activated
```

The browser may preview only explicitly public manifest data and public assets. It must not unpack or display the ZIP. Detailed validation occurs only in the backend.

### OpenAPI page

When the selected target is sealed, the UI locks and explains these immutable properties:

```text
Access: invoke only
Internal information: hidden
Tool events: hidden
Raw logs: hidden
```

Quota, rate limit, expiry, status, and API-key rotation remain configurable according to existing authorization.

## Failure Isolation and Availability

- DClaw starts and operates when the sealed-agent registry is empty or unavailable.
- Registration and preload enumerate sealed agents independently and isolate per-agent errors.
- A rejected or failed release does not alter the active release.
- A runtime failure marks only the affected agent unhealthy.
- Ordinary agents and unrelated OpenAPI publications remain available.
- Disabling an agent rejects new calls while allowing an explicit bounded drain policy for in-flight calls.
- Private storage failure makes affected sealed agents unavailable but does not block login, administration, or ordinary agents.
- All public errors are sanitized and mapped to stable codes.

## Auditing and Data Minimization

Audit records may include:

- Actor or external API-key identifier
- Agent and release IDs
- Signer, digest, release time, and activation operation
- Channel, tenant, session identifier, duration, usage, and outcome
- Authorization denials
- Suspected prompt, skill, file, encoding, or multi-turn extraction attempts
- Enable, disable, rollback, and publication changes

Audit records must not contain package content, protected instructions, skill source, full model context, raw tool inputs or outputs, unsanitized exceptions, or unnecessary copies of sensitive customer input. Security aggregation keys events by principal, tenant, session, IP/risk identifier where lawful, and OpenAPI key.

Operational metrics use low-cardinality identifiers and exclude prompts and responses by default. Any temporary diagnostic mode for sealed agents must be designed separately and cannot make protected content visible in the DClaw UI.

## API Contract Principles

- List and detail endpoints return public DTOs for customers and a separate protected operational DTO for authorized administrators.
- Neither DTO contains sealed content or internal locations.
- Prohibited content endpoints return `403` before resolving or reading the requested file.
- Not-found and forbidden behavior is normalized where asset-existence disclosure matters.
- Capability fields are authoritative and covered by contract tests.
- Release upload endpoints accept bytes but expose no reverse download endpoint.
- OpenAPI publication creation resolves target policy on the server and persists `invoke_only` for sealed targets.
- Streaming serialization is allowlist-based rather than a blacklist of internal event types.

## Testing Strategy

### Backend behavior

- Verify `0`, `1`, and multiple sealed agents.
- Verify no regression in standard agent creation, management, chat, backup, and OpenAPI publication.
- Verify customers, tenant administrators, and DClaw system administrators cannot inspect sealed assets.
- Directly exercise every workspace, file, skill, config, tool, backup, restore, export, clone, download, trace, and debug endpoint against a sealed agent.
- Verify all normal users can invoke an enabled sealed global agent and cannot invoke a disabled one.
- Verify one sealed agent's failure does not affect another agent.

### Package security

- Valid and invalid signatures
- Unknown and revoked signers
- Digest and manifest tampering
- Duplicate versions and disallowed downgrade
- Absolute paths, traversal paths, mixed separators, Unicode normalization collisions, and duplicate normalized paths
- Symlinks, hard links, device files, and unsupported file modes
- Excessive compressed size, expanded size, file count, and compression ratio
- Startup-test failure preserving the old active version
- Concurrent publication and activation races

### Runtime security

- File and shell attempts against sealed paths
- Copy, attachment, backup, archive, and artifact escape attempts
- Direct and indirect prompt injection
- Requests to print, translate, encode, summarize, or reconstruct rules and skills
- Directory, tool, and configuration enumeration
- ZIP, Base64, hexadecimal, and external-upload exfiltration
- Multi-turn and cross-session low-rate extraction
- Canary and protected-text similarity detection
- False-positive corpus containing legitimate Lu Yu domain answers
- Sanitization of logs, traces, stream events, and exceptions

### OpenAPI

- Fixed target resolution from the publication and API key
- Rejection or ignoring of caller-supplied target and identity fields
- Forced `invoke_only` and sealed response policy
- Sync, stream, and continued-session output allowlists
- Quota, rate-limit, expiry, revocation, and unavailable-target behavior
- Absence of internal events and details from every error path

### Frontend

- Discovery and invocation of an enabled sealed global agent
- Capability-driven route, menu, tab, and action visibility
- Dedicated sealed detail and release pages for DClaw administrators
- No Workspace, Skills, Config, Tools, clone, export, or download access
- Safe handling of manually entered prohibited routes
- Locked `invoke_only` OpenAPI controls
- Public-only manifest preview and sanitized release progress
- Conversation rendering without skills, tool events, sources, paths, or debug details
- Unchanged behavior for ordinary agents

## Acceptance Criteria

The feature is accepted when:

1. A clean DClaw installation with no sealed agents passes existing startup and regression tests.
2. One or multiple independently versioned sealed agents can be installed without code changes or hard-coded IDs.
3. An enabled sealed global agent is callable by normal DClaw users and by a bound OpenAPI publication.
4. Customers, tenant administrators, and DClaw system administrators cannot retrieve its ZIP, internal files, skills, instructions, configuration, raw traces, or tool internals through any DClaw UI or API.
5. Direct API calls remain denied when frontend restrictions are bypassed.
6. Only a correctly signed and validated package can become ready or active.
7. A bad release or runtime failure is isolated and preserves ordinary DClaw operation and the prior known-good release.
8. Streaming and non-streaming callers receive only public events, final output, approved artifacts, and sanitized errors.
9. Leakage evals demonstrate that filesystem/tool isolation remains effective even when model behavior is manipulated.
10. Documentation explicitly states that host root and infrastructure operators are outside the confidentiality threat model and that observable agent behavior cannot be made completely non-inferable.

## Implementation Slices

Implementation planning should preserve these independently verifiable slices:

1. Registry, schema, centralized policy, and public capability DTOs.
2. Signed package format, validation, private version storage, and activation state machine.
3. Runtime filesystem/tool isolation and output policy.
4. Internal conversation discovery and invocation.
5. `invoke_only` OpenAPI integration and streaming allowlist.
6. Frontend sealed detail, release, conversation, routing, and OpenAPI states.
7. Cross-cutting security tests, leakage evals, auditing, and operational documentation.

No slice may rely on frontend hiding as an authorization boundary, and no implementation may special-case `luyu` where `agent_type = sealed` is the intended rule.
