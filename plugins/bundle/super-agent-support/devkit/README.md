# DClaw Super Agent DevKit

Version 1.8.2 publishes public Component direct-upload commands and closed
request/response schemas. It retains stable installation credential slots,
`agent.outbound.stream/1`, and `resource.exchange/1` in addition to the
provider-neutral controlled
HTTPS transport for sealed Super Agents. The Agent owns provider selection,
request parameters, idempotency, polling, retries, fees, and response
interpretation. The transport resolves an installation-scoped
`credential_ref`, enforces its domain, method, and scope policy, and injects
the secret only at the final network boundary. Long-term provider credentials
are never returned to the Agent, model, workspace, logs, or local helper.
Presigned upload targets now have a dedicated closed response schema. HTTPS
streaming requests can optionally extract one JSON Pointer string and strictly
decode its Base64 payload directly into temporary object storage; the encoded
or decoded media never enters the Agent response.

The 1.6.0 public Component export bindings for Runner 1.3.0 remain compatible,
as do the 1.4.1 business service identity contracts. Component registry
commands continue to call `dclaw.super-agent-support` directly and require no
DClaw management page or server source.

Capability descriptors may bind a declared public Component export to a
process environment variable with `component_exports`. Variables must use the
`DCLAW_COMPONENT_*` namespace, the Component must also appear in
`public_components`, and the capability must require Runner 1.3.0 or newer.
Runner resolves the signed relative export inside the installed Component and
fails closed for undeclared Components, missing exports, duplicate variables,
pre-existing variables, or paths outside the Component root. See
`fixtures/public-components/component-export-cases.json`.

`operation-catalog.json` fixes the public client keys, MCP tool names,
Streamable HTTP endpoint and JSON-RPC sequence. Controlled outbound requests
may omit a body or provide exactly one of `json_body` and `text_body`. The
platform injects exactly one `Authorization: Bearer <assertion>` header;
Agent-supplied authorization and case-insensitive duplicate headers are
rejected.

`agent_outbound.request` does not use the business-service issue/audience
flow. Its credential is installed through the authenticated
`/api/super-agent-support/agent-outbound/credentials` endpoint with explicit
scope, Agent, installation, domain, method, and authentication-header policy.
Sync.so-style API keys use authorization type `header` with name `x-api-key`;
Bearer providers use type `bearer`. The sealed Agent retains only the returned
stable `credential_slot` for new releases or the compatible opaque
`credential_ref` for existing signed Agents.

Business services that verify with the public JWK set must use
`business_identity_verifier.py` or an equivalent durable replay cache. Every
accepted `(issuer, jti)` must be stored atomically until `exp + clock_skew`;
signature validity alone never establishes replay safety. The replay contract
fixture is in `fixtures/business-identity/replay-cases.json`. Verification must
also supply and match the expected issuer, audience, Agent, service,
installation, release, and non-empty minimum scope set.

Receivers must pass the raw list of all `Authorization` header field values to
`extract_bearer_assertion` before signature verification. It accepts exactly
one `Bearer <assertion>` value and rejects missing, duplicate, comma-combined,
non-Bearer and empty values. Do not use a framework accessor that silently
combines or discards duplicate headers.

This directory is a standalone developer kit. It does not require DClaw
server source code.

Supported development environments:

- CPython 3.10-3.13
- Windows x64
- macOS x64 and ARM64
- Linux glibc x64 and ARM64

Run `bootstrap.ps1` on Windows or `bootstrap.sh` on macOS/Linux. The scripts
create `.venv`, verify every bundled wheel, and install the pinned encryption
dependencies without using a package index.

After bootstrap:

```text
.venv/Scripts/python.exe dclaw_agent_devkit.py contracts   # Windows
.venv/bin/python dclaw_agent_devkit.py contracts           # macOS/Linux
```

Signing keys are never read, copied, or printed by the bootstrap scripts.
See `THIRD_PARTY_LICENSES.md` for bundled dependency licenses.
