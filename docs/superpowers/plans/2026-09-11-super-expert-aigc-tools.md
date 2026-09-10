# Super Expert AIGC Tools Implementation Plan

**Goal:** Let any authorized super expert use existing AIGC services from its standard Agent loop without expert-specific platform code.

**Architecture:** Register request-local tools only inside an authorized workspace Agent loop. Reuse the current business capability dispatcher. Bind installation and conversation from the host; resolve physical task bindings from the platform repository. Preserve the existing host.call path and all shared AIGC execution behavior.

**Constraints:** Work directly on main. Preserve pre-existing AIGC edits. No RPA/MCP exposure. No paid generation or deployment during implementation. Customer asset submission stays in the existing task UI; it is not synthesized by a model. The task.create capability remains a dependency for resume/review, not a second workflow creation route.

## Tasks

- [x] Add tests for grant-based tool visibility, scoped task access, stable workflow identity, authoritative bindings, task review prerequisites, cleanup and independent sessions.
- [x] Implement `app/workspace/aigc_tools.py`: catalog, workflow create, scoped task status, resume and review tools using the existing dispatcher and repository reads. Model arguments contain logical task key/revision or an existing material task ID, never installation or conversation identities.
- [x] Connect registration to the authorized `agent_loop` branch; add a scoped task reader in the runner. Restore the original toolkit on completion, failure or cancellation. Test the actual workspace entrypoint.
- [x] Add a LuYu AIGC Skill with adapted old prompt instructions, official excerpts/licenses and workflow reference. Wire production/review Skills to it and declare the existing six platform capabilities. Preserve business routing and the transparent runtime.
- [x] Run focused server and package tests, validate capability closure and package files, then broader existing workspace/super-expert/AIGC regression tests. Record exact results and deployment prerequisites.

## Acceptance

Two differently named super experts use the same tool code with their own grants. Missing grants expose no tools. Cross-session task IDs cannot be read or mutated. Repeating workflow creation with the same task key and revision uses the same operation identity; changed content requires a new revision. A created task is not reported as generated media. No customer-authored metadata supplies binding authority.

## Validation results

2026-09-11: 678 server regression tests passed; the final bridge suite has 15 passing tests, including an additional real AgentScope scripted-model loop test. LuYu package: 18 tests passed; standard workspace and Skill validation passed. No paid generation, deployment or activation. Contract documented in docs/super-expert-aigc-agent-tools.md.
