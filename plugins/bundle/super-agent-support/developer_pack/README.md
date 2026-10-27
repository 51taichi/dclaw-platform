# DClaw Super Agent Developer Pack

This package is the offline, public development surface for DClaw Super
Agents. It contains the human standard, standalone DevKit, schemas, templates,
SDK helpers, fixtures, and a single cross-platform command line tool. DClaw
server source is not required.

Version 1.5.2 bundles DevKit 1.4.1 and the public contracts for
`business.service.installation-identity/1`. Business service assertions are
issued and injected by the platform; Agent projects only receive and pass the
opaque one-time `binding_ref`. Project upgrades update the pack, standard and
DevKit versions together before validation.

## Supported environments

- CPython 3.10 through 3.13
- Windows x64
- macOS x64 and ARM64
- Linux glibc x64 and ARM64
- PowerShell 5.1+ for `bootstrap.ps1`
- POSIX shell for `bootstrap.sh`
- Node.js is not required

## Start here

Run all commands from the unpacked developer pack root.

Prepare the locked offline environment once:

```text
bootstrap.ps1     # Windows PowerShell
./bootstrap.sh    # macOS / Linux
```

Use `.venv/Scripts/python.exe` on Windows or `.venv/bin/python` on macOS and
Linux for the commands below.

```text
python dclaw_developer.py doctor
python dclaw_developer.py init --target ./my-agent --agent-id my-agent --name "My Agent" --local-helper required
python dclaw_developer.py validate --project ./my-agent
python dclaw_developer.py test --project ./my-agent
python dclaw_developer.py keygen --private-key /secure/dev-private.b64 --public-key /secure/dev-public.b64
python dclaw_developer.py build --project ./my-agent --private-key /secure/dev-private.b64 --public-key /secure/dev-public.b64 --output ./release/my-agent-0.1.0.zip
```

For an Agent whose `local-helper` is `optional` or `required`, add
`--capability-artifact-url https://developer.example/capabilities/package.zip`.
The same `build` command then creates and signs the local capability artifact,
verifies that signature, and builds the sealed Super Expert package. Use the
standalone `capability-build` command when the capability artifact must be
prepared before the Super Expert release.

For a capability with multiple modules, embedded runtimes, FFmpeg, models, or
other locked resources, list files and directories in
`capability-pack/windows-x64/capability-build.json`. Each path is validated,
archived deterministically, and recorded with its size and SHA-256 in the
artifact inventory. To sign an existing ZIP produced by another deterministic
builder, set its build manifest source to `prebuilt`, or pass
`--capability-artifact-file /path/to/artifact.zip`; the CLI validates ZIP paths
and integrity before binding its digest into the signed descriptor.

Every local capability project must also keep
`capability-pack/windows-x64/resources.lock.json` release-ready. The lock fixes
the production HTTPS allowlist and, for every external resource, its size,
SHA-256, SBOM evidence, license evidence, cache key, and rollback version.
`validate`, `test`, `capability-build`, and `build` reject blocked resources,
placeholder hosts such as `.test` or localhost, unapproved domains, temporary
paths, and incomplete evidence before writing an artifact or sealed ZIP.

The project test adapter is declared in `project.json`:

```json
{
  "tests": {
    "adapter": "pytest",
    "paths": ["tests"],
    "arguments": ["-q"]
  }
}
```

Supported adapters are `unittest` and `pytest`. The CLI invokes them without a
shell and writes the normalized command plus the actual executed test count to
release evidence. When project test dependencies live in a project virtual
environment, set `tests.python` to its safe project-relative interpreter path,
which must be exactly `.venv/Scripts/python.exe` or `.venv/bin/python`. The pack verifies the
project virtual environment, CPython version, executable identity and
`sys.prefix`; normal POSIX virtual-environment Python symlinks are supported,
while directory symlink escapes, wrappers and arbitrary interpreters are
rejected. Projects without this field retain unittest discovery with the
interpreter running the developer CLI.

`build` runs the mandatory release gate, project tests, standalone DevKit
validation, sealing, signature verification, and evidence generation. It fails
closed when behavior evidence, approvals, schemas, capability declarations,
dependencies, resource locks, or signing checks are incomplete.

Run the bundled end-to-end exercise without production credentials:

```text
python dclaw_developer.py demo --workspace ./demo-work
```

The exercise copies the example outside the pack, runs its local capability,
generates an ephemeral test signer, builds a sealed Super Expert ZIP, verifies
it, and writes reviewable evidence. It performs no network calls or deployment.

See `standard/super-agent-development-standard-v1.zh-CN.md` for the governing
rules, `COMPATIBILITY.md` for supported versions, and `UPGRADE.md` for upgrades
and rollback.

## Package layout

```text
dclaw-super-agent-developer-pack-<version>/
  dclaw_developer.py
  bootstrap.ps1
  bootstrap.sh
  PACKAGE-MANIFEST.json
  SHA256SUMS
  standard/
  devkit/
    schemas/
    templates/
    wheelhouse/
  schemas/
    developer-pack-v1/
  sdk/python/
  templates/project/
    agent/
    business-service/
    capability-pack/windows-x64/
    docs/
    tests/
  examples/minimal-local/
  SBOM.spdx.json
  THIRD_PARTY_LICENSES.md
  COMPATIBILITY.md
  CHANGELOG.md
  UPGRADE.md
```

## Release workflow

1. Verify the downloaded ZIP against the authenticated metadata SHA-256 and
   verify all entries in `SHA256SUMS`.
2. Bootstrap the offline environment and run `doctor`.
3. Initialize a project. The generated behavior evidence is deliberately a
   draft, so a new project cannot be sealed before real evidence is recorded.
4. Implement the Agent, optional business service, and optional local
   capability. Keep long-lived credentials outside the project and inject them
   into the business service or the approved credential broker.
5. Replace the placeholder signer ID, complete `SOURCE_BEHAVIOR_SPEC.json`, and
   record every approved behavior difference in `PORTING_RECORD.json`.
6. Run `validate` and `test` until both pass.
7. Keep the Ed25519 private key outside the project and run `build`. Archive the
   generated ZIP, checksum, and `release-evidence/<version>.json`.
8. Upload, grant, activate, and run three real customer tasks only after the
   platform owner authorizes those separate production actions.
