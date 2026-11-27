# DClaw Platform Repository Rules

## One shared codebase

- All development must happen directly in the single shared `main` checkout of this repository, including work performed by multiple Codex sessions.
- Do not create or switch to development branches, Git worktrees, temporary clones, or separate source copies for implementation work.
- Before editing, inspect the current working tree and re-read every target file. Treat unfamiliar changes as active work from another session.
- Never reset, checkout, revert, overwrite, stash, or otherwise remove another session's changes. Coordinate overlapping edits and preserve all unrelated staged and unstaged work.
- Commit completed changes directly to `main`. Stage only the files or hunks owned by the current task unless the user explicitly requests an integrated snapshot commit.
- Do not force-push or rewrite shared history. Pull or integrate remote changes only after confirming they will not overwrite local work.

## Build and deployment

- A source-code change or commit does not authorize building deployment images, publishing artifacts, restarting services, or deploying to any environment.
- Build or deploy only after the user explicitly approves that specific operation.
