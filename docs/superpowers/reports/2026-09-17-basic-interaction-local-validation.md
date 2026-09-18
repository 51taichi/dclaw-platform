# Basic Interaction Capabilities — Local Validation

Date: 2026-09-17
Scope: DClaw Server, DClaw Client, LuYu Agent
Release state: local source and local `dclaw` container only; no commit, push,
image build, or production deployment

## Result

The v1 basic interaction catalog, single-select, multi-select, and question-form
cards, persisted submission, trusted ordinary-message handoff, Client composer
lock, reload recovery, and LuYu question-routing policy are implemented and
covered locally. The interaction submit endpoint does not invoke or wait for a
model.

## Server

Focused contract, repository, tool, route, platform, AIGC regression, and
in-process end-to-end suites:

```text
python -m pytest tests/unit/app/super_experts \
  tests/unit/app/runner/test_interaction_tools.py \
  tests/unit/app/runner/test_aigc_tools.py \
  tests/unit/routers/test_super_expert_interactions.py \
  tests/unit/routers/test_super_expert_platform.py \
  tests/integration/test_super_expert_interactions.py \
  tests/integration/test_super_expert_aigc_workflow.py -q

251 passed, 1 third-party deprecation warning
```

The latest correction suite ran 132 focused tests covering catalog, repository,
tooling, routes, and the in-process integration flow. It also verifies strict
idempotent replay, removal of legacy card-continuation state, and that the
submit route returns without running an Agent. The integration scenario
covers catalog → create → persisted restore → choice or question submission →
server-resolved `user_input` → the Client's existing ordinary chat submitter.
Question coverage includes stable
ID or exact-question references, required and optional answers, maximum lengths,
outer-whitespace trimming with internal newlines preserved, duplicate-reference
rejection, and exact choice-versus-answer branch validation.

The full Server suite excluding two worktree-only artifact prerequisites reached
`4388 passed, 26 skipped, 2 deselected`, with one unrelated one-second
multiprocessing progress test timing out under concurrent Server/Client load.
That exact test passed immediately after the preview and parallel test processes
were stopped (`1 passed`). The two deselected prerequisites were traced to
ignored local artifacts that Git worktrees do not inherit:

- `src/qwenpaw/agents/md_files/zh/AGENTS.md`
- `src/qwenpaw/console/index.html` and its compiled assets

Running those exact two tests in the main Server checkout, where the ignored
artifacts already exist, produced `2 passed`. No product code was changed and no
console package/build was run to manufacture these worktree-only prerequisites.

`git diff --check` passes. Ruff is not installed in the Server virtual
environment; Python behavior and syntax are exercised by the focused and full
pytest runs.

## Client

```text
pnpm exec vitest run <interaction and composer suites>
6 test files passed, 43 tests passed

pnpm exec tsc -b --noEmit
passed

pnpm build
passed; output copied only into the existing local container

pnpm exec prettier --check <all changed source files and package.json>
passed

pnpm exec eslint <new interaction/API/test files>
passed

pnpm exec vitest run <previous full-suite outliers>
2 test files passed, 19 tests passed

git diff --check
passed
```

The full Client suite reached `177 passed, 1 failed` test files and `1078 passed,
1 failed` tests. The remaining failure is the pre-existing Task-page AIGC restore
test when executed after the entire suite; the same Task-page and OpenAPI files
pass in isolation (`19 passed`). JSDOM also prints its known
`getComputedStyle(..., pseudo-element)` diagnostic. The new interaction files
pass targeted ESLint. No Docker image or release package was built.

Client coverage includes single/multi selection, question-form required and
optional items, defaults versus AI recommendations, limits, supplement
validation, long content, layout and state styles, duplicate-submit prevention,
REST/SSE merging, direct handoff to `input.submit({query})`, response-loss
recovery with the same idempotency key, conversation-switch isolation, and full
composer/toolbar locking for `card_only`.

The real component was also loaded from the local Vite source server and rendered
with long Chinese question text at 1440 px and 420 px widths. Both checks had
`body.scrollWidth == body.clientWidth`; each question remained a full-width row,
hover/focus styling was visible, text wrapped without clipping, and the mobile
submit action became full-width. Screenshots are retained in the local preview
directory under `/tmp/dclaw-question-form-preview/`.

## LuYu Agent

```text
python -m pytest tests -q
62 passed

python scripts/validate_workspace.py --workspace . \
  --dclaw-root <local Server feature worktree>
workspace-valid: 8 skills, 16 nodes, 28 methods, skill-reader opt-in
```

All 16 turn packets were regenerated. LuYu now routes reliably enumerable
questions to single/multi-select cards and genuinely open factual questions to
`question_form`; it must not place answer requests in ordinary message text.
Mixed questions are sequenced one blocking `card_only` interaction at a time.

## Workspace and release audit

- Server feature branch: `feature/basic-interactions`, no new commit.
- Client feature branch: `feature/basic-interactions`, no new commit.
- Client main checkout retains only its pre-existing `VERSION` and Tauri changes.
- Server main checkout retains its pre-existing untracked `outputs/` directory.
- The existing local `dclaw` container was updated and restarted; it is healthy
  at `http://127.0.0.1:18088` and serves `assets/index-CJ7QV8Vw.js`.
- No push, release package, Docker image build, or production update was
  performed.

Release remains intentionally stopped. After explicit confirmation, the next
sequence is: create one consolidated commit in each Git repository, push both
feature branches, then package/build images and deploy using the normal release
procedure.
