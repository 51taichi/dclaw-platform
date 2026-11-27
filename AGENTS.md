# DClaw Platform Repository Rules

## One shared codebase

- All development must happen directly in the single shared `main` checkout of this repository, including work performed by multiple Codex sessions.
- Do not create or switch to development branches, Git worktrees, temporary clones, or separate source copies for implementation work.
- Before editing, inspect the current working tree and re-read every target file. Treat unfamiliar changes as active work from another session.
- Never reset, checkout, revert, overwrite, stash, or otherwise remove another session's changes. Coordinate overlapping edits and preserve all unrelated staged and unstaged work.
- Commit completed changes directly to `main`. Stage only the files or hunks owned by the current task unless the user explicitly requests an integrated snapshot commit.
- Do not force-push or rewrite shared history. Pull or integrate remote changes only after confirming they will not overwrite local work.

## Shared Git coordination

- File edits may happen in parallel because every session shares this working tree. A local edit is immediately visible to every other session, even before it is committed.
- GitHub contains only committed and successfully pushed work. Never describe the remote as current while another session has staged, unstaged, or untracked source changes.
- Git-mutating operations must be serialized. Only one session at a time may run `git add`, `git commit`, `git fetch`, `git pull`, `git merge`, `git rebase`, or `git push`.
- Before entering the commit/push phase, inspect `git status --short --branch` and re-read the files being committed. If another session is performing a Git operation or has overlapping unfinished edits, wait rather than competing with it.
- Never delete `.git/index.lock` to bypass another Git process. Wait for the owning operation to finish and verify the repository state before continuing.
- Stage only the current task's files or hunks. Do not amend, reorder, squash, rebase, reset, or silently absorb another session's commits.
- The session that creates a commit should normally push it before handing off. If local `main` already contains intentional commits from another session, preserve them unchanged and push them only after verifying the worktree is clean and the commits are complete.
- Before pushing, fetch `origin/main` while holding the serialized Git phase. If the remote moved unexpectedly, stop and reconcile without force-pushing or rewriting shared history.
- Remote synchronization is complete only when the worktree is clean, `main` is neither ahead nor behind `origin/main`, and `git rev-parse HEAD` equals `git rev-parse origin/main` after the final fetch or push.

## Build and deployment

- A source-code change or commit does not authorize building deployment images, publishing artifacts, restarting services, or deploying to any environment.
- Build or deploy only after the user explicitly approves that specific operation.
