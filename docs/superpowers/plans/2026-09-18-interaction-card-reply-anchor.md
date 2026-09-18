# Interaction Card Reply Anchor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep every successfully created basic interaction card attached to its creating reply after submission and remove model-generated card-delivery status phrases without changing submission or business flow.

**Architecture:** The server records every distinct `PENDING` interaction ID returned by a successful `interaction.card.create/1` call in a host-owned result field and adds those IDs to the authoritative assistant message metadata for both native messages and reply envelopes. Runtime-supplied diagnostics are never accepted as creation evidence. The server removes complete leading delivery-status sentences only when verified creation evidence exists. The client applies the same narrow sanitizer to the associated reply when replaying older responses with a `PENDING` create-tool result.

**Tech Stack:** Python 3.10+, Pydantic, AgentScope messages, pytest, React 18, TypeScript, Vitest.

**Spec:** User-approved design in the current task: preserve card/reply association, remove “卡片已发送” wording, keep submission and business flow unchanged, test only in local DClaw.

## Global Constraints

- Work only on branch `fix/interaction-card-reply-anchor` in isolated worktrees.
- Do not modify card submission semantics or ordinary user-input continuation.
- Do not push, build production images, or deploy to production.
- Deploy only to the local DClaw environment after tests pass.
- Preserve unrelated changes in the main workspaces.

---

### Task 1: Persist successful interaction creation on the final reply

**Files:**
- Modify: `src/qwenpaw/app/workspace/orchestration.py`
- Test: `tests/unit/app/runner/test_workspace_orchestration.py`

**Interfaces:**
- Consumes: successful `interaction.card.create/1` result containing `interaction.interaction_id`.
- Produces: host-owned `WorkspaceTurnResult.verified_interaction_ids` and assistant metadata `super_expert_interaction_id` / `super_expert_interaction_ids` for native and reply-envelope messages.

- [x] **Step 1: Write the failing orchestration test**

Add a signed test runtime that calls `interaction.card.create/1`, completes with a native assistant message, and assert the returned diagnostics and rendered message metadata contain the created interaction ID.

- [x] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/unit/app/runner/test_workspace_orchestration.py -k "created_interaction" -q`

Expected: FAIL because generic card creation is not propagated into final reply metadata.

- [x] **Step 3: Implement minimal interaction tracking**

Wrap the authorized business-call bridge inside `run_workspace_orchestration_turn`, collect only distinct `PENDING` results, ignore `SUBMITTED` replays, strip runtime-supplied interaction diagnostics, and store verified IDs in the host-owned field before returning.

- [x] **Step 4: Support native assistant message metadata**

Update `workspace_result_to_message` so both accepted message shapes preserve existing metadata and add `super_expert_interaction_id` when diagnostics contain a valid ID.

- [x] **Step 5: Run focused tests**

Run: `python -m pytest tests/unit/app/runner/test_workspace_orchestration.py -k "interaction_completion or created_interaction" -q`

Expected: PASS.

### Task 2: Remove interaction-delivery status clauses deterministically

**Files:**
- Modify: `src/qwenpaw/app/workspace/orchestration.py`
- Test: `tests/unit/app/runner/test_workspace_orchestration.py`

**Interfaces:**
- Consumes: assistant text plus verified interaction ID in diagnostics.
- Produces: the same business text with only leading card-delivery clauses removed.

- [x] **Step 1: Write failing sanitizer tests**

Cover `“好了，卡片已经发给你了。按上面的问题填一下。”` and `“卡片已经发过去了。我从你的业务情况出发……”`, plus a control reply without an interaction ID.

- [x] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/unit/app/runner/test_workspace_orchestration.py -k "delivery_status" -q`

Expected: FAIL because the phrases remain visible.

- [x] **Step 3: Implement the narrow sanitizer**

Add a private helper that removes only leading successful-delivery clauses and invoke it only when the turn has a verified created interaction ID. Preserve all remaining business text and leave failures or ordinary messages unchanged.

- [x] **Step 4: Run focused tests**

Run: `python -m pytest tests/unit/app/runner/test_workspace_orchestration.py -k "delivery_status or interaction_completion or created_interaction" -q`

Expected: PASS.

### Task 3: Clean legacy replay text in the client

**Files:**
- Modify: `console/src/pages/Chat/components/RuntimeProgressCard.tsx`
- Test: `console/src/pages/Chat/components/RuntimeProgressCard.test.tsx`

**Interfaces:**
- Consumes: one runtime response containing a successful `interaction_card_create` output or an anchored assistant message.
- Produces: rendered historical text without the redundant delivery-status clause.

- [x] **Step 1: Write failing replay tests**

Render a historical response with successful create-tool output followed by `“好了，卡片已经发给你了。按上面的问题填一下。”`; assert only the useful suffix is rendered. Add a control response without creation evidence and assert its text is untouched.

- [x] **Step 2: Run tests to verify failure**

Run: `npm run test:run -- console/src/pages/Chat/components/RuntimeProgressCard.test.tsx`

Expected: FAIL because legacy text is rendered verbatim.

- [x] **Step 3: Implement scoped display cleanup**

Detect only `PENDING` interaction creation, associate it with the next visible reply, render every verified anchor on that reply, and sanitize only the first non-empty text/refusal block. Reuse the same sentence-bound phrase forms as the server.

- [x] **Step 4: Run focused client tests**

Run: `npm run test:run -- console/src/pages/Chat/components/RuntimeProgressCard.test.tsx console/src/pages/Chat/components/SuperExpertInteractionCards.test.tsx`

Expected: PASS.

### Task 4: Verify and deploy to local DClaw

**Files:**
- Modify: none unless local compose configuration requires an explicit source path.

**Interfaces:**
- Consumes: tested server and client worktrees.
- Produces: local DClaw at `127.0.0.1:18088` running the branch code for user acceptance testing.

- [x] **Step 1: Run server regression tests**

Run: `python -m pytest tests/unit/app/runner/test_workspace_orchestration.py tests/unit/app/runner/test_interaction_tools.py -q`

Expected: PASS.

- [x] **Step 2: Run client regression tests and typecheck**

Run: `npm run test:run -- console/src/pages/Chat/components/RuntimeProgressCard.test.tsx console/src/pages/Chat/components/SuperExpertInteractionCards.test.tsx && npm run format:check`

Expected: PASS.

- [x] **Step 3: Build and start local services from the isolated worktrees**

Build the client locally and copy the tested server/client artifacts into the existing local-only DClaw container. Do not tag or push production images.

- [ ] **Step 4: Perform local acceptance checks**

Create a new陆羽 conversation, trigger a non-initial selection card, submit it, and verify: the card remains under the creating reply; the reply has no delivery-status phrase; submission continues as ordinary user input exactly once.
