# Codex-Like Imagegen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make task conversations reach the practical effect of Codex imagegen: natural-language image generation/editing, reference-image workflows, structured advanced parameters, batch variants, saved previewable outputs, and a clean fallback path.

**Architecture:** Add one conversation-facing AIGC image tool that reuses AIGC Studio capabilities and jobs instead of duplicating provider-specific logic in chat plugins. Keep AIGC Studio as the runtime and asset system; keep Chat as the natural-language entry and result surface. Existing `gpt-image2` and `qwen-image` plugins remain compatibility tools, but the new tool becomes the recommended default.

**Tech Stack:** Python FastAPI/router logic, QwenPaw plugin/tool registration, Agentscope `ToolResponse` blocks, AIGC Studio job/asset persistence, React/TypeScript Chat preview components, Vitest, Pytest.

---

## Scope

Build the first production slice:

- Conversation tool: text-to-image, image-to-image/edit, multi-reference images, prompt-only natural language usage.
- Advanced controls: provider/model selection, size or aspect ratio/resolution, quality, count, output format, negative prompt, style prompt hints.
- Runtime: submit to AIGC Studio jobs, wait for terminal result, return image blocks and text summary.
- UX: existing Chat artifact previews should show generated images; add labels only if needed.
- Leave true native transparency, explicit masks, and image upscale as phase 2 unless the implementation discovers they are already one-function additions.

## Target Behavior

Users can say in task conversation:

- "生成一张 16:9 高质量品牌海报，2K，给我 4 个方案"
- "参考这两张图，保持人物一致，换成工厂场景"
- "做一张透明背景商品主图"
- "用 GPT Image 2 / Seedream / Nano2 生成"

The agent should call one recommended tool, not decide between scattered provider-specific tools. Results should show as chat images and be stored as AIGC assets.

## File Structure

### New files

- `src/qwenpaw/agents/tools/aigc_image.py`
  - Agent-callable tool functions.
  - Normalizes user parameters into an AIGC Studio job request.
  - Executes job through a shared service helper.
  - Returns `ToolResponse` with `ImageBlock` plus concise metadata.

- `src/qwenpaw/app/aigc_image_tool.py`
  - Shared service layer that does not depend on the plugin system.
  - Selects model/capability from provider manager.
  - Creates a transient canvas/node/job.
  - Runs or polls the AIGC Studio job.
  - Converts outputs to chat-displayable URLs or paths.

- `tests/unit/app/test_aigc_image_tool.py`
  - Unit tests for model selection, parameter normalization, reference handling, job request creation, and output formatting.

- `tests/unit/agents/tools/test_aigc_image.py`
  - Tool-level tests for successful text-to-image, image-to-image, invalid references, no configured model, and multiple outputs.

### Modified files

- `src/qwenpaw/config/config.py`
  - Register the new built-in tool in default tools, likely `generate_aigc_image`.

- `src/qwenpaw/agents/react_agent.py`
  - Usually no direct change should be needed because built-in tools are loaded from `src/qwenpaw/agents/tools`.
  - Touch only if the default tool discovery does not pick up the new function.

- `src/qwenpaw/app/routers/aigc_studio.py`
  - Prefer extracting reusable helpers rather than importing private router internals directly.
  - Add public-ish helpers only if needed for non-HTTP job execution.

- `console/src/pages/Chat/components/RuntimeProgressCard.tsx`
  - Add or refine display labels for AIGC image tool outputs if the existing imagegen path heuristics miss AIGC asset URLs.

- `console/src/pages/Chat/components/TaskArtifactCard.tsx`
  - Touch only if generated AIGC assets are not previewed correctly.

- `console/src/pages/Chat/utils.ts`
  - Add URL/path normalization for AIGC asset file URLs if needed.

## Task 1: Backend Service Contract

**Files:**
- Create: `src/qwenpaw/app/aigc_image_tool.py`
- Test: `tests/unit/app/test_aigc_image_tool.py`

- [ ] **Step 1: Write failing tests for parameter normalization**

Create tests that prove a chat-style request becomes AIGC parameters:

```python
def test_normalizes_codex_like_image_parameters():
    payload = normalize_image_tool_request(
        prompt="高端品牌海报",
        mode="generate",
        aspect_ratio="16:9",
        resolution="2K",
        quality="high",
        count=4,
        output_format="webp",
        negative_prompt="不要水印",
    )

    assert payload.inputs["prompt"] == "高端品牌海报"
    assert payload.parameters["aspectRatio"] == "16:9"
    assert payload.parameters["resolution"] == "2K"
    assert payload.parameters["quality"] == "high"
    assert payload.parameters["imageQuality"] == "高画质"
    assert payload.parameters["imageCount"] == 4
    assert payload.parameters["output_format"] == "webp"
    assert payload.parameters["negative_prompt"] == "不要水印"
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
pytest tests/unit/app/test_aigc_image_tool.py::test_normalizes_codex_like_image_parameters -q
```

Expected: fails because `normalize_image_tool_request` does not exist.

- [ ] **Step 3: Implement minimal request normalization**

Add `AigcImageToolPayload` and `normalize_image_tool_request()` in `src/qwenpaw/app/aigc_image_tool.py`.

Rules:

- `mode="generate"` -> capability preference `text_to_image`.
- `mode="edit"` or reference images present -> capability preference `image_to_image`, fallback `image_edit`.
- `count` maps to `imageCount`, clamped to `1..10` for generic chat tool; provider adapters may clamp further.
- `quality` maps:
  - `low` -> `低画质`
  - `medium` -> `标准画质`
  - `high` -> `高画质`
  - `auto` -> omit `imageQuality` but preserve `quality=auto`.
- `reference_images` maps to both `inputs.reference_images` and `parameters.referenceImages`.

- [ ] **Step 4: Run the unit test**

Run:

```bash
pytest tests/unit/app/test_aigc_image_tool.py -q
```

Expected: all tests in the new file pass.

## Task 2: Model Selection And Job Creation

**Files:**
- Modify: `src/qwenpaw/app/aigc_image_tool.py`
- Test: `tests/unit/app/test_aigc_image_tool.py`

- [ ] **Step 1: Write failing tests for model selection**

Cover:

- Explicit `provider_id` and `model_id` are honored.
- Without explicit model, first configured image model from AIGC capabilities is chosen.
- Editing mode skips text-only image models when an edit-capable model exists.
- Error is clear when no AIGC image model is configured.

- [ ] **Step 2: Implement selection helper**

Add:

```python
async def select_aigc_image_model(
    provider_manager,
    *,
    provider_id: str = "",
    model_id: str = "",
    mode: str = "generate",
):
    ...
```

Use provider/model metadata already consumed by `/api/aigc-studio/capabilities`. Do not hard-code GPT/Qwen/Seedream as the only valid options.

- [ ] **Step 3: Create transient job request**

Add:

```python
async def build_aigc_image_job_create(
    request,
    *,
    prompt: str,
    reference_images: list[str],
    provider_id: str,
    model_id: str,
    parameters: dict,
):
    ...
```

It should create:

- A transient `canvas_id`, for example `chat-imagegen-<session-or-time>`.
- A transient `node_id`, for example `chat-imagegen-node`.
- `inputs.prompt`.
- `inputs.reference_images`.
- `parameters.sourceSurface = "chat"`.
- `parameters.toolName = "generate_aigc_image"`.

- [ ] **Step 4: Run backend tests**

Run:

```bash
pytest tests/unit/app/test_aigc_image_tool.py -q
```

Expected: model selection and job creation tests pass.

## Task 3: Tool Function For Task Conversations

**Files:**
- Create: `src/qwenpaw/agents/tools/aigc_image.py`
- Modify: `src/qwenpaw/config/config.py`
- Test: `tests/unit/agents/tools/test_aigc_image.py`

- [ ] **Step 1: Write failing tool tests**

Test signature-level behavior:

```python
response = await generate_aigc_image(
    prompt="一张产品海报",
    aspect_ratio="16:9",
    resolution="2K",
    count=2,
)
```

Expected response:

- Contains two `ImageBlock`s when the job returns two assets.
- Contains one text summary with model, prompt, count, and saved paths.
- Returns a text error when no model is configured.

- [ ] **Step 2: Implement `generate_aigc_image`**

Signature:

```python
async def generate_aigc_image(
    prompt: str,
    mode: str = "auto",
    reference_images: list[str] | None = None,
    provider_id: str = "",
    model_id: str = "",
    aspect_ratio: str = "",
    resolution: str = "",
    size: str = "",
    quality: str = "auto",
    count: int = 1,
    output_format: str = "png",
    negative_prompt: str = "",
    style: str = "",
) -> ToolResponse:
    ...
```

Behavior:

- `mode=auto` becomes edit when `reference_images` is non-empty; otherwise generate.
- Calls the shared service.
- Returns `ImageBlock(source={"type": "url", "url": asset.url or asset.path})`.
- Returns clear errors as `TextBlock`, not exceptions leaking to chat.

- [ ] **Step 3: Register built-in default tool**

In `src/qwenpaw/config/config.py`, add the tool to `_default_builtin_tools()` with:

- name: `generate_aigc_image`
- enabled by default if project policy allows image generation tools by default
- icon: image/sparkle style if the config supports it
- async execution enabled if supported for long-running tools

- [ ] **Step 4: Run agent tool tests**

Run:

```bash
pytest tests/unit/agents/tools/test_aigc_image.py -q
```

Expected: all new tool tests pass.

## Task 4: Reuse AIGC Job Execution Safely

**Files:**
- Modify: `src/qwenpaw/app/aigc_image_tool.py`
- Modify: `src/qwenpaw/app/routers/aigc_studio.py` only if helper extraction is needed
- Test: `tests/unit/app/test_aigc_image_tool.py`
- Test: `tests/unit/routers/test_aigc_studio.py`

- [ ] **Step 1: Write a failing integration-style unit test**

Test that the tool service submits a job, waits for completion, and returns assets using the same saved asset shape as AIGC Studio.

- [ ] **Step 2: Extract or call shared AIGC execution**

Preferred order:

1. Extract reusable job execution helpers from `aigc_studio.py` into a service-friendly function.
2. Keep existing router endpoints using that same function.
3. Avoid making an HTTP call from backend to itself.

- [ ] **Step 3: Preserve access boundaries**

The service must use the current workspace/user context when creating jobs and assets. It must not write global shared files unless AIGC Studio already does so for the same user.

- [ ] **Step 4: Run router and service tests**

Run:

```bash
pytest tests/unit/app/test_aigc_image_tool.py tests/unit/routers/test_aigc_studio.py -q
```

Expected: existing AIGC Studio tests remain green.

## Task 5: Chat Preview Compatibility

**Files:**
- Modify: `console/src/pages/Chat/utils.ts`
- Modify: `console/src/pages/Chat/components/RuntimeProgressCard.tsx`
- Modify: `console/src/pages/Chat/components/TaskArtifactCard.tsx` only if needed
- Test: `console/src/pages/Chat/utils.test.ts`
- Test: `console/src/pages/Chat/components/RuntimeProgressCard.test.tsx`
- Test: `console/src/pages/Chat/components/TaskArtifactCard.test.tsx`

- [ ] **Step 1: Write failing frontend tests**

Cases:

- AIGC asset URL displays as an image preview.
- AIGC job output text does not show noisy local filesystem paths.
- Multiple generated images are grouped similarly to existing `media/imagegen` previews.

- [ ] **Step 2: Extend URL normalization only if needed**

If AIGC asset URLs already preview through `/api/aigc-studio/assets/...`, no change is needed. If not, add normalization in `console/src/pages/Chat/utils.ts`.

- [ ] **Step 3: Label generated images**

In `RuntimeProgressCard`, ensure text like `Generated image with AIGC Studio` or tool name display does not duplicate long tool names.

- [ ] **Step 4: Run frontend tests**

Run:

```bash
cd console
npm run test:run -- src/pages/Chat/utils.test.ts src/pages/Chat/components/RuntimeProgressCard.test.tsx src/pages/Chat/components/TaskArtifactCard.test.tsx
```

Expected: all pass.

## Task 6: Tool Guidance And User-Facing Copy

**Files:**
- Modify: `src/qwenpaw/agents/md_files/zh/AGENTS.md` if tool usage guidance lives there
- Modify: `src/qwenpaw/agents/md_files/en/AGENTS.md` if English guidance mirrors Chinese guidance
- Modify: `plugins/tool/gpt-image2/README.md` only to mark it as compatibility/fallback, not to remove it

- [ ] **Step 1: Add tool guidance**

Explain:

- Use `generate_aigc_image` first for task conversation image generation/editing.
- Use provider-specific tools only when the user explicitly asks for GPT Image 2 or Qwen-Image plugin behavior.
- For many distinct assets, call the tool once per asset or use `count` for variants of one prompt.

- [ ] **Step 2: Add tests only if docs are rendered or linted**

If no doc lint exists, skip automated doc tests and rely on `git diff --check`.

## Task 7: Verification And Rollout

**Files:**
- No required file changes.

- [ ] **Step 1: Run backend verification**

Run:

```bash
pytest tests/unit/app/test_aigc_image_tool.py tests/unit/agents/tools/test_aigc_image.py tests/unit/routers/test_aigc_studio.py -q
```

- [ ] **Step 2: Run frontend verification**

Run:

```bash
cd console
npm run test:run -- src/pages/Chat/utils.test.ts src/pages/Chat/components/RuntimeProgressCard.test.tsx src/pages/Chat/components/TaskArtifactCard.test.tsx
npm exec -- tsc -b --noEmit
```

- [ ] **Step 3: Run formatting safety check**

Run:

```bash
git diff --check
```

- [ ] **Step 4: Optional local browser check**

If the local app is running or can be rebuilt:

```bash
bash scripts/docker_build.sh qwenpaw-saas-local:latest
QWENPAW_IMAGE=qwenpaw-saas-local:latest QWENPAW_SAAS_HOST_PORT=18088 docker compose --profile saas up -d qwenpaw-saas
curl -sS -o /tmp/qwenpaw-chat.html -w '%{http_code} %{content_type}\n' http://127.0.0.1:18088/claw
```

Expected: `200 text/html`.

## Phase 2 Backlog

- Native transparent output workflow:
  - Default: chroma-key prompt plus local alpha extraction.
  - Advanced: provider/model-specific transparent output only when supported.
- Explicit mask editing:
  - Add `mask_image` argument and route to adapters that support masks.
- Upscale:
  - Expose AIGC Studio upscale mode once backend runtime is real, not only UI parameters.
- Batch prompt list:
  - Add `generate_aigc_image_batch(prompts=[...])` only after the single-tool path is stable.
- Style template picker:
  - Let chat tool accept `style_template_id` and resolve the same prompt-style metadata as AIGC Studio.

## Completion Criteria

- A task conversation can call one recommended image tool for text-to-image and image-to-image.
- The same generated asset system is used by AIGC Studio and chat.
- Chat previews generated images without leaking confusing local paths.
- Existing provider-specific plugins still work.
- Tests prove parameter normalization, model selection, job execution, and Chat preview behavior.
