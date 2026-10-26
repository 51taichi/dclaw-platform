# Upgrade And Rollback

## Upgrade

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
