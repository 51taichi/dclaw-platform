# AIGC Script Real Workflow Design

## Goal

The AIGC Studio script flow should stop relying on simulated `SCRIPT_SHOTS`, timer-based progress, and custom storyboard mock cards for production behavior. The first real slice keeps the script component as the short-drama workflow controller, but routes generation through the existing text, image, and video node execution contracts.

## Current Product Model

- `script_generate` is already registered as the script component for "剧情分镜、角色分镜".
- The current script flow is product-shaped: choose a script entry, generate a shot table, confirm shots, prepare role/scene/prop assets, compose per-shot prompts, create a storyboard image group, then create a storyboard video group.
- The flow currently uses hardcoded `SCRIPT_SHOTS` and `window.setTimeout()` in several steps, so it proves the UX shape but does not prove real generation.
- Text, image, and video nodes already follow a stronger pattern: node-specific components prepare node data, then delegate to `runNode`, which creates an AIGC job, runs it, and merges outputs back onto the node.

## Design Decision

The flow logic is correct. The execution mechanism is the part that must change.

Keep the script component as a workflow container and replace simulated execution with real nodes:

```text
Script node
  -> real storyboard text job
  -> parsed shot data on the script node
  -> real image nodes for asset and storyboard generation
  -> real video nodes for selected storyboard clips
```

The script component owns structure, selection, and orchestration. Text, image, and video components own generation. This preserves the existing AIGC Studio boundary: `index.tsx` remains canvas orchestration, node families keep their own workflow hooks, and cross-node job execution stays behind the existing `runNode` path.

## First Real Slice

Implement the smallest useful real path first:

```text
User enters or selects script source
  -> script node submits a storyboard text job
  -> backend returns structured storyboard JSON as text output
  -> frontend parses and stores scriptShots
  -> user confirms shots
  -> script flow creates real image_generate nodes from shot prompts
  -> image nodes run through the existing AIGC job lifecycle
```

Video batch generation remains in the second slice. The first slice should leave the video UI visible only where it can truthfully create real `video_generate` nodes from completed image outputs.

## Script Text Generation Contract

Use the existing `prompt` node behavior as the reference, but keep the visible component as `script_generate`.

The script node must run a real storyboard-capable text job with:

- `capability`: `storyboard`
- `inputs.prompt`: the user's source script, character brief, or self-written request
- `inputs.node_type`: `script_generate`
- `parameters.textMode`: `storyboard_script`
- `parameters.outputFormat`: `storyboard_shots_json`

The expected model output is JSON text with this shape:

```json
{
  "title": "我在盛唐写天下",
  "shots": [
    {
      "id": "shot-1",
      "no": 1,
      "duration": 4,
      "imageDescription": "深夜办公室里，女主在电脑前加班到崩溃。",
      "character": "沈昭昭现代",
      "characterDescription": "28岁女性，疲惫，白衬衫，头发凌乱。",
      "scene": "现代办公室",
      "shotType": "特写",
      "camera": "缓慢推进",
      "action": "手指停下，头部垂落。",
      "emotion": "极度疲惫",
      "dialogue": "无",
      "soundEffect": "键盘声逐渐停止",
      "prompt": "特写，深夜办公室蓝色屏幕光，疲惫女性加班，电影感低饱和。",
      "videoPrompt": "镜头缓慢向前推进，屏幕蓝光闪烁，女性手指停下，头部沉重垂落。"
    }
  ]
}
```

If the model returns plain text or malformed JSON, the frontend should keep the generated text in the node output and show a clear parse failure state. It should not silently fall back to `SCRIPT_SHOTS`.

## Shot Data Rules

Each parsed shot must be normalized before storing on the script node:

- `id`: keep model id if present; otherwise use `shot-${index + 1}`.
- `no`: numeric order, defaulting to `index + 1`.
- `duration`: positive number, defaulting to `5`.
- Text fields: trim strings; missing optional fields become empty strings.
- `prompt`: required for storyboard image generation. If missing, derive it from `imageDescription`, `scene`, `shotType`, `camera`, and `emotion`.
- `videoPrompt`: required for video generation. If missing, derive it from `prompt` plus `action`.

The script node should store:

- `scriptMode: "script_ready"` after successful parsing.
- `scriptShots`: the normalized shots.
- `selectedShotIds`: all normalized shot ids by default.
- `scriptWorkflowStep: "shots"`.
- `job_id`, `job_status`, `outputs`, and `job_error` from the real text job.

## Asset Preparation

The current "准备资产" step should stay in the workflow because it is product-correct, but it must no longer pretend that assets were generated.

First real behavior:

- Extract role, scene, and prop candidates from `scriptShots`.
- Show each candidate as a pending asset card.
- "一键生成所有资产" creates one real `image_generate` node per asset candidate.
- Each created image node uses the candidate description as prompt text and stores `sourceScriptNodeId`, `scriptAssetId`, and `scriptAssetKind`.
- The asset card is ready only when a linked image node has a successful image output.

The existing `reference_asset` "脚本资产组" can remain as an aggregator only after real image outputs exist. It should reference generated asset URLs, not text-only labels.

## Storyboard Image Generation

The current custom `storyboard_from_script` node should be replaced by real image node execution.

First real behavior:

- "批量生成分镜" creates real `image_generate` nodes from selected shots.
- Each storyboard image node stores:
  - `imageMode: "text_to_image"`
  - `text` and `composerText` from `shot.prompt`
  - `sourceScriptNodeId`
  - `sourceShotId`
  - `storyboardShotNo`
  - `storyboardStyle`
  - `aspectRatio`, `resolution`, and `imageCount`
- Edges should connect `script_generate -> image_generate`.
- Optional asset references should connect ready role/scene/prop image nodes to the relevant shot image node when the selected shot mentions those assets.
- Each image node then runs through the normal image `runNode` lifecycle.

The UI may still present a grouped storyboard view, but it should be derived from the real image nodes and their job outputs. It should not own an independent simulated completion state.

## Video Generation

Video generation is second-slice behavior after the first real image slice is stable.

Second real behavior:

- "批量生视频" creates real `video_generate` nodes for selected shots that have completed storyboard image outputs.
- Each video node stores:
  - `videoMode: "image_to_video"` when a storyboard image exists.
  - `text` and `composerText` from `shot.videoPrompt`.
  - `sourceScriptNodeId`, `sourceShotId`, and `sourceStoryboardImageNodeId`.
  - `referenceThumb`, `referenceAssetName`, and `referencePreviewUrl` from the generated image output.
  - `aspectRatio`, `videoResolution`, `videoDuration`, `videoAudio`, and `videoCount`.
- Edges should connect `image_generate -> video_generate`.
- Each video node runs through the normal video `runNode` lifecycle.

The custom `storyboard_video_batch` display can survive as a read-only grouped dashboard only if it reflects real child video nodes. It must not invent running, failed, or "算力不足" states.

## Workflow Runner

Do not build a general agentic planner in this slice. Add a narrow script workflow runner with explicit stages:

```text
generate_script
prepare_assets
generate_storyboard_images
generate_videos
```

Each stage should be resumable from canvas state:

- If the script node already has valid `scriptShots`, skip `generate_script`.
- If asset image nodes already exist and succeeded, count them as ready.
- If storyboard image nodes already exist and succeeded, count them as ready.
- If a downstream node failed, pause the stage and surface the failed node.

The runner should call existing node execution helpers instead of duplicating submit-job logic. The first implementation can expose stage-specific actions instead of one "run all" button, as long as each stage uses real jobs.

## Error Handling

- No storyboard-capable model: show the same missing-model pattern as text nodes, scoped to the script node.
- Empty script input: keep the user in the script composer and show an inline validation message.
- Text job failure: mark the script node failed with the backend `job_error`.
- Empty text output: mark the script node failed; do not use demo shots.
- JSON parse failure: keep raw text output, mark `scriptParseStatus: "failed"`, and offer retry or manual paste/edit.
- No selected shots: disable asset, image, and video generation actions.
- Image node failure: keep the failed image node visible and mark the related shot card failed.
- Video node failure: keep the failed video node visible and mark the related shot video card failed.

## Testing

Frontend unit tests should cover:

- Submitting a script node calls the real run path instead of filling `SCRIPT_SHOTS` directly.
- Successful storyboard text output is parsed into normalized `scriptShots`.
- Malformed storyboard text output produces a parse failure state and does not fall back to demo data.
- Asset generation creates real `image_generate` nodes with `sourceScriptNodeId` and `scriptAssetId`.
- Storyboard image generation creates real `image_generate` nodes with per-shot prompts and edges from the script node.
- Storyboard grouped UI reflects real child image nodes and job states.
- Video generation creates real `video_generate` nodes only for shots with completed image outputs.

Backend tests should cover:

- `storyboard` text jobs accept `node_type: "script_generate"` and save text output metadata.
- The storyboard prompt mode requests JSON output without breaking ordinary prompt text jobs.
- Empty or malformed model responses surface as job failures or parse failures rather than demo data.

Verification commands for the implementation plan should include:

```bash
cd /Users/zu/Documents/workes/qwenpaw/console
npm exec -- vitest run src/pages/AigcStudio/components/ScriptNode/ScriptNode.test.tsx src/pages/AigcStudio/components/ScriptNode/useScriptNodeWorkflow.test.tsx src/pages/AigcStudio/components/StoryboardWorkflow/StoryboardImageNode.test.tsx src/pages/AigcStudio/components/VideoNode/useVideoNodeWorkflow.test.tsx src/pages/AigcStudio/canvasJobActions.test.ts
npm exec -- tsc -b --noEmit

cd /Users/zu/Documents/workes/qwenpaw
pytest tests/unit/routers/test_aigc_studio.py -q
git diff --check
```

## Migration

Existing canvases that contain script nodes with `SCRIPT_SHOTS`-shaped data should continue to render. They should be marked as legacy/demo-backed only when the node has no real `job_id` or generated text output.

Recommended migration behavior:

- Keep legacy `scriptShots` renderable.
- Do not auto-delete legacy storyboard image or video batch nodes.
- When the user reruns a legacy script node, replace simulated downstream nodes only for that script flow.
- Preserve user-edited shot text when possible by using it as the next real job input.

## Non-Goals

- Do not remove the script component.
- Do not move script business logic into `AigcStudio/index.tsx`.
- Do not create a separate provider-specific script generator.
- Do not implement a general multi-branch workflow engine in this slice.
- Do not make video batch generation part of the first real slice.
- Do not keep `SCRIPT_SHOTS` as a production fallback after real text generation fails.
- Do not simulate success for assets, storyboard images, or videos once a real node exists for that item.

## Acceptance Criteria

- A new script run no longer completes by copying `SCRIPT_SHOTS`.
- A successful script run stores real text job metadata and parsed shot data.
- A failed or malformed script run shows an honest failure state.
- Storyboard images are represented by real image nodes that can be run individually and inspected like other image nodes.
- The first real slice keeps current canvas interaction patterns and does not expand `index.tsx` with script-specific business logic.
