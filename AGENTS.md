# DClaw Server Repository Rules

## Required Git delivery

- Every completed development task in this repository must end with the verified changes committed and pushed to `origin/main` before the task is reported complete.
- This requirement applies to source code, tests, migrations, operational scripts, maintained documentation, and repository configuration created or changed by the task.
- Do not leave completed work only in the working tree, an untracked file, a temporary clone, a worktree, or an unmerged branch.
- If work was performed on another branch or worktree, integrate it into local `main`, rerun the relevant verification on the integrated result, and push `main`.
- Before committing, separate task changes from unrelated user changes. Never discard, overwrite, or silently include unrelated work.
- Use focused commits with clear messages. Confirm after pushing that local `main` and `origin/main` resolve to the same commit.
- If tests fail, merge conflicts remain, credentials or network access are unavailable, or pushing would include uncertain/unrelated files, do not force the push. Preserve the work and report the exact blocker instead of claiming completion.

## Generated and temporary files

- Do not commit generated output, caches, screenshots, exports, local databases, credentials, or temporary investigation artifacts unless the user explicitly identifies them as repository deliverables.
- Add appropriate ignore rules when a recurring generated path would otherwise leave the repository dirty.

## Images and deployment

- Committing and pushing source changes does not authorize building or updating deployment images, uploading release artifacts, deploying, restarting services, or changing production state.
- Build or update a deployment image, publish it, or deploy it only after the user explicitly approves that specific image update or deployment.
