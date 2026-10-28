# Upgrade And Rollback

## Upgrade

Pack 1.5.4 adopts development standard 2.11. Public Component inventory and
registration use only the versioned headless API/CLI owned by
`dclaw.super-agent-support`; existing signed Agent releases remain valid.

1. Download the new versioned ZIP and verify the SHA-256 from authenticated
   metadata or the separately delivered checksum file.
2. Extract it beside the old pack. Never overwrite the old pack in place.
3. Run `python dclaw_developer.py doctor` in the new pack.
4. Copy or back up the Agent project, then run:

   `python dclaw_developer.py upgrade --project /path/to/agent`

5. Review `.dclaw/developer-pack.json`, run `validate` and `test`, then build a
   new Agent patch version. Upgrade never edits business source or an existing
   signed release ZIP.

When upgrading from pack 1.0.x, existing projects may keep the original four
capability artifact members and unittest discovery without editing their
configuration. Add `capability-pack/windows-x64/capability-build.json` only when
the artifact needs more files or a prebuilt ZIP, and add `tests` to
`project.json` only when selecting pytest or custom test paths and arguments.

When upgrading to pack 1.4.1 or later, every project with an optional or
required local helper must add
`capability-pack/windows-x64/resources.lock.json`. Set `release_ready=true` and
`status=release-ready` only after all resource URLs are production HTTPS URLs on
the declared allowlist and every resource has size, SHA-256, SBOM, license,
cache-key, and rollback-version evidence. Earlier signed packages remain valid;
the resource gate applies when producing a new release.

Pack 1.5.0 adds DevKit 1.4.0 and the installation-bound business service
identity contracts. Existing manifests remain valid. A rebuilt Agent may
declare the new capability only after its service registration and exact
installation/release grant exist on the target DClaw instance.

Pack 1.5.1 adds DevKit 1.4.1 transport fixtures and safely accepts the normal
`.venv/bin/python` symlink created on POSIX systems. Existing signed packages
remain valid. Re-run `validate` and `test` before rebuilding; no manifest or
capability contract migration is required.

Pack 1.5.2 fixes project metadata upgrades so `developer_pack_version`,
`standard.version`, and `devkit_version` advance together. Run `validate`
immediately after `upgrade`; a successful upgrade followed by a version
mismatch is a tool defect and must not be worked around in a formal release.
No manifest, signature, local execution, or business identity contract changes.

Pack 1.5.3 assigns reusable local runtimes and tools for Super Agents to
`dclaw.super-agent-support`. Pack 1.5.4 fixes their management surface as a
headless plugin API/CLI. Neither version requires a DClaw client or
administration page, and neither changes existing signed Agent contracts.

## Rollback

Keep the previous developer pack ZIP, checksum, public key, last accepted Agent
ZIP, and release evidence. To roll back the tools, reopen the previous pack and
run its `validate` and `verify` commands against the unchanged project or prior
package. To roll back a deployed Agent, reactivate the prior accepted Agent
release through DClaw administration; the developer pack does not deploy or
activate releases.

Pack 1.x receives security and compatibility fixes for at least 12 months after
the first 2.x release. A deprecated command remains available for at least one
minor release with a replacement message before removal in the next major.
