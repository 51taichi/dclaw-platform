# AIGC Script Real Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the first script/storyboard simulation path with real execution: script nodes run a storyboard text job, parse the returned shot JSON, then create real `image_generate` nodes for selected shots.

**Architecture:** Keep `AigcStudio/index.tsx` as canvas/job orchestration. Script-specific parsing and workflow decisions stay inside `components/ScriptNode` and `components/StoryboardWorkflow`. Shared job request and job merge behavior stays in `canvasJobActions.ts`.

**Tech Stack:** React, TypeScript, Vitest, existing AIGC Studio canvas/job APIs.

---

### Task 1: Add Storyboard Output Parsing

- [x] Create `console/src/pages/AigcStudio/components/ScriptNode/storyboardParser.ts`.
- [x] Add `console/src/pages/AigcStudio/components/ScriptNode/storyboardParser.test.ts`.
- [x] Parse raw JSON and fenced JSON text.
- [x] Normalize shots into existing `ScriptShot` shape.
- [x] Derive missing `prompt` and `videoPrompt` from shot fields.
- [x] Return an explicit parse failure for empty, malformed, or non-`shots` output.

### Task 2: Route Script Submission Through Real Job Execution

- [x] Extend `useScriptNodeWorkflow` args with `runScriptNode`.
- [x] Change `handleScriptComposerSubmit` and `handleScriptRegenerate` so normal script generation sets a running state and calls `runScriptNode`.
- [x] Remove direct `SCRIPT_SHOTS` writes and timer-based script completion from the real submission path.
- [x] Keep storyboard composer submission delegated to `storyboardWorkflow.handleStoryboardComposerSubmit`.
- [x] Add tests proving script submission calls the run path and does not fill demo shots.

### Task 3: Teach Job Actions About Script Nodes

- [x] Update `buildRunNodeJobRequest` so `script_generate` sends `capability: storyboard` when the selected model exposes it.
- [x] Build script prompts from upstream source text plus the script instruction.
- [x] Add script parameters: `textMode: "storyboard_script"`, `outputFormat: "storyboard_shots_json"`, and `scriptInputKind`.
- [x] Update `applyFinishedJobToCanvas` for successful `script_generate` jobs: store job metadata, raw text output, parsed `scriptShots`, default `selectedShotIds`, `scriptMode: "script_ready"`, and `scriptWorkflowStep: "shots"`.
- [x] Update script failure and parse failure behavior without falling back to `SCRIPT_SHOTS`.
- [x] Add `canvasJobActions.test.ts` coverage for request construction, successful parsing, and parse failure.

### Task 4: Wire Script Nodes Into The Existing Runner

- [x] Pass `runNode` into `useScriptNodeWorkflow` from `AigcStudio/index.tsx`.
- [x] Include `script_generate` in the runner's feedback node behavior so it can show run progress and errors.
- [x] Add running/failure patches for script nodes without moving script business logic into `index.tsx`.
- [x] Verify missing-model behavior uses the same pattern as prompt nodes.

### Task 5: Create Real Storyboard Image Nodes

- [x] Change storyboard image generation so selected shots produce real `image_generate` nodes, one per selected shot.
- [x] Store `imageMode: "text_to_image"`, `text`, `composerText`, `sourceScriptNodeId`, `sourceShotId`, `storyboardShotNo`, `storyboardStyle`, `aspectRatio`, `resolution`, and `imageCount`.
- [x] Connect edges from `script_generate` to each created image node.
- [x] Preserve existing custom grouped storyboard UI only as legacy/read-only display where needed.
- [x] Add tests for created image node data and edges.

### Task 6: Keep Asset Preparation Honest

- [x] Stop marking asset generation as ready via timer for the real path.
- [x] Create real `image_generate` nodes for selected script assets with `sourceScriptNodeId`, `scriptAssetId`, and `scriptAssetKind`.
- [x] Keep legacy asset group rendering compatible with existing canvases.
- [x] Add tests for real asset image node creation.

### Task 7: Verify

- [x] Run targeted frontend tests:

```bash
cd /Users/zu/Documents/workes/qwenpaw/console
npm exec -- vitest run src/pages/AigcStudio/components/ScriptNode/storyboardParser.test.ts src/pages/AigcStudio/components/ScriptNode/useScriptNodeWorkflow.test.tsx src/pages/AigcStudio/canvasJobActions.test.ts src/pages/AigcStudio/components/StoryboardWorkflow/StoryboardImageNode.test.tsx
```

- [x] Run broader AIGC Studio regression tests:

```bash
cd /Users/zu/Documents/workes/qwenpaw/console
npm exec -- vitest run src/pages/AigcStudio/components/ScriptNode/ScriptNode.test.tsx src/pages/AigcStudio/components/ScriptNode/useScriptNodeWorkflow.test.tsx src/pages/AigcStudio/AigcStudio.test.tsx
```

- [x] Run TypeScript:

```bash
cd /Users/zu/Documents/workes/qwenpaw/console
npm exec -- tsc -b --noEmit
```

- [x] Run diff hygiene:

```bash
cd /Users/zu/Documents/workes/qwenpaw
git diff --check
```
