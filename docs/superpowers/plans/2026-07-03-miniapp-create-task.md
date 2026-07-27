# Miniapp Create Task Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the DClaw mini-program create-task page into a mobile task-delegation flow aligned with the web workbench task model.

**Architecture:** Keep the page as a focused Taro/React form and reuse existing mini-program service helpers. Add one small attachment upload helper, fix the create-and-submit service to preserve `skillName`, then render execution context, materials, task goal, templates, and a Web-only AIGC project entry from local page state.

**Tech Stack:** Taro 4, React 18, TypeScript, WeChat mini-program APIs, Vitest.

---

## File Structure

- Modify `miniapp/src/services/consoleChat.ts`: pass selected skill metadata through `createAndSubmitTask`.
- Create `miniapp/src/services/consoleChat.test.ts`: assert create-and-submit sends agent and selected skill.
- Modify `miniapp/src/services/api.ts`: export a reusable request URL builder for upload helpers.
- Create `miniapp/src/services/attachments.ts`: upload WeChat-selected files to `/api/user/console/upload` and return markdown-ready file metadata.
- Create `miniapp/src/services/attachments.test.ts`: assert upload URL and auth header behavior.
- Create `miniapp/src/pages/create-task/createTaskContract.test.ts`: lock task-delegation UI copy and service usage.
- Modify `miniapp/src/pages/create-task/index.tsx`: implement agent selection, skill selection, materials, task goal, templates, AIGC Web guidance, and submission.
- Modify `miniapp/src/pages/create-task/index.scss`: style the revised sections using the existing style-4 visual system.

---

### Task 1: Preserve Skill Metadata During Initial Task Submission

**Files:**
- Create: `miniapp/src/services/consoleChat.test.ts`
- Modify: `miniapp/src/services/consoleChat.ts`

- [ ] **Step 1: Write the failing test**

Create `miniapp/src/services/consoleChat.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";

vi.mock("./api", () => ({
  request: vi.fn(),
}));

import { request } from "./api";
import { createAndSubmitTask } from "./consoleChat";

const mockRequest = vi.mocked(request);

describe("createAndSubmitTask", () => {
  it("creates a task chat and sends the initial prompt with agent and skill metadata", async () => {
    mockRequest
      .mockResolvedValueOnce({
        id: "chat-1",
        session_id: "session-1",
        user_id: "user-1",
        channel: "console",
        name: "销售分析",
        meta: {
          agent_id: "data-analysis",
        },
      })
      .mockResolvedValueOnce("ok");

    const chat = await createAndSubmitTask({
      name: "销售分析",
      prompt: "/[xlsx]\n\n生成销售分析",
      agentId: "data-analysis",
      skillName: "xlsx",
    });

    expect(chat.id).toBe("chat-1");
    expect(mockRequest).toHaveBeenNthCalledWith(
      1,
      "/chats",
      expect.objectContaining({
        method: "POST",
        header: { "X-Agent-Id": "data-analysis" },
      }),
    );
    expect(mockRequest).toHaveBeenNthCalledWith(
      2,
      "/console/chat",
      expect.objectContaining({
        method: "POST",
        header: { "X-Agent-Id": "data-analysis" },
        data: expect.objectContaining({
          input: [{ role: "user", content: "/[xlsx]\n\n生成销售分析" }],
          chat_id: "chat-1",
          session_id: "session-1",
          meta: expect.objectContaining({
            selected_skill: "xlsx",
            agent_id: "data-analysis",
          }),
        }),
      }),
    );
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
cd /Users/zu/Documents/workes/qwenpaw/miniapp
npm run test:run -- src/services/consoleChat.test.ts
```

Expected: FAIL because `selected_skill` is currently `undefined` during `createAndSubmitTask`.

- [ ] **Step 3: Write minimal implementation**

Modify `miniapp/src/services/consoleChat.ts`:

```ts
export async function submitTaskPrompt(
  chat: ChatSpec,
  prompt: string,
  skillName?: string,
) {
  return sendTaskPrompt({
    chatId: chat.id,
    sessionId: chat.session_id,
    userId: chat.user_id,
    agentId:
      typeof chat.meta?.agent_id === "string" ? chat.meta.agent_id : undefined,
    prompt,
    skillName,
  });
}

export async function createAndSubmitTask(input: CreateTaskInput) {
  const chat = await createTaskShell(input);
  await submitTaskPrompt(chat, input.prompt, input.skillName);
  return chat;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
npm run test:run -- src/services/consoleChat.test.ts
```

Expected: PASS.

---

### Task 2: Add Mini-Program Attachment Upload Helper

**Files:**
- Modify: `miniapp/src/services/api.ts`
- Create: `miniapp/src/services/attachments.ts`
- Create: `miniapp/src/services/attachments.test.ts`

- [ ] **Step 1: Write the failing test**

Create `miniapp/src/services/attachments.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";

vi.mock("@tarojs/taro", () => ({
  default: {
    uploadFile: vi.fn(),
    getStorageSync: vi.fn(() => "token-1"),
  },
}));

import Taro from "@tarojs/taro";
import { uploadConsoleAttachment } from "./attachments";

describe("uploadConsoleAttachment", () => {
  it("uploads a selected local file to the console upload endpoint", async () => {
    vi.mocked(Taro.uploadFile).mockResolvedValueOnce({
      statusCode: 200,
      data: JSON.stringify({
        url: "/uploads/report.pdf",
        file_name: "report.pdf",
      }),
      errMsg: "uploadFile:ok",
    } as never);

    const result = await uploadConsoleAttachment({
      path: "wxfile://tmp/report.pdf",
      name: "report.pdf",
    });

    expect(result).toEqual({
      name: "report.pdf",
      url: "/uploads/report.pdf",
      markdown: "📎 [report.pdf](/uploads/report.pdf)",
    });
    expect(Taro.uploadFile).toHaveBeenCalledWith(
      expect.objectContaining({
        url: "http://127.0.0.1:18088/api/user/console/upload",
        filePath: "wxfile://tmp/report.pdf",
        name: "file",
        header: { Authorization: "Bearer token-1" },
      }),
    );
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
npm run test:run -- src/services/attachments.test.ts
```

Expected: FAIL because `attachments.ts` does not exist.

- [ ] **Step 3: Export a request URL builder**

Modify `miniapp/src/services/api.ts`:

```ts
export function buildRequestUrl(prefix: string, path: string): string {
  return joinUrl(prefix, path);
}
```

- [ ] **Step 4: Implement attachment upload**

Create `miniapp/src/services/attachments.ts`:

```ts
import Taro from "@tarojs/taro";

import { buildRequestUrl } from "./api";
import { getAuthToken } from "./auth";

export interface LocalAttachmentInput {
  path: string;
  name: string;
}

export interface UploadedAttachment {
  name: string;
  url: string;
  markdown: string;
}

interface UploadResponsePayload {
  url?: string;
  file_name?: string;
}

function parseUploadPayload(data: string): UploadResponsePayload {
  try {
    return JSON.parse(data) as UploadResponsePayload;
  } catch {
    return {};
  }
}

export async function uploadConsoleAttachment(
  input: LocalAttachmentInput,
): Promise<UploadedAttachment> {
  const token = getAuthToken();
  const response = await Taro.uploadFile({
    url: buildRequestUrl("/api/user", "/console/upload"),
    filePath: input.path,
    name: "file",
    header: token ? { Authorization: `Bearer ${token}` } : undefined,
  });

  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw new Error(`附件上传失败：${response.statusCode}`);
  }

  const payload = parseUploadPayload(String(response.data || ""));
  const url = payload.url || "";
  const name = payload.file_name || input.name;
  if (!url) {
    throw new Error("附件上传失败：缺少文件地址");
  }

  return {
    name,
    url,
    markdown: `📎 [${name}](${url})`,
  };
}
```

- [ ] **Step 5: Run the attachment test**

Run:

```bash
npm run test:run -- src/services/attachments.test.ts
```

Expected: PASS.

---

### Task 3: Lock The Create-Task UI Contract

**Files:**
- Create: `miniapp/src/pages/create-task/createTaskContract.test.ts`

- [ ] **Step 1: Write the failing contract test**

Create `miniapp/src/pages/create-task/createTaskContract.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readPageSource(fileName: string) {
  const sourcePath = fileURLToPath(new URL(fileName, import.meta.url));
  return readFileSync(sourcePath, "utf8");
}

describe("create task page contract", () => {
  it("presents mobile task delegation instead of a prompt-only form", () => {
    const source = readPageSource("./index.tsx");

    expect(source).toContain("交给谁处理");
    expect(source).toContain("智能体");
    expect(source).toContain("技能");
    expect(source).toContain("补充材料");
    expect(source).toContain("描述任务目标");
    expect(source).toContain("AIGC 创意项目");
    expect(source).toContain("https://dclaw.deepmega.cn/");
    expect(source).toContain("showModal");
    expect(source).toContain("交给 DClaw 执行");
    expect(source).toContain("listAgentOptions");
    expect(source).toContain("listSkillOptions");
    expect(source).toContain("formatTaskPrompt");
    expect(source).not.toContain("当前执行上下文");
    expect(source).not.toContain("你想完成什么？");
  });

  it("keeps create-task styles organized around context, materials, goal, and templates", () => {
    const styles = readPageSource("./index.scss");

    expect(styles).toContain("context-card");
    expect(styles).toContain("material-card");
    expect(styles).toContain("goal-card");
    expect(styles).toContain("aigc-card");
    expect(styles).toContain("template-list");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
npm run test:run -- src/pages/create-task/createTaskContract.test.ts
```

Expected: FAIL because the current page still uses the old prompt-only wording.

---

### Task 4: Implement The Mobile Task Delegation Page

**Files:**
- Modify: `miniapp/src/pages/create-task/index.tsx`

- [ ] **Step 1: Replace the old page with the new state model**

Modify imports and constants in `miniapp/src/pages/create-task/index.tsx`:

```ts
import { Button, Text, Textarea, View } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import { useState } from "react";

import AppShell from "../../components/AppShell";
import AssetImage from "../../components/AssetImage";
import { requireAuth } from "../../services/auth";
import { uploadConsoleAttachment, type UploadedAttachment } from "../../services/attachments";
import { createAndSubmitTask } from "../../services/consoleChat";
import {
  formatTaskPrompt,
  listAgentOptions,
  listSkillOptions,
  type MobileAgentOption,
  type MobileSkillOption,
} from "../../services/taskContext";
```

Add:

```ts
const FALLBACK_AGENT: MobileAgentOption = {
  id: "default",
  name: "DClaw 助手",
};

const TASK_TEMPLATES = [
  "整理上周项目进展",
  "生成销售数据分析摘要",
  "把资料整理成汇报提纲",
];

const AIGC_WEB_URL = "https://dclaw.deepmega.cn/";
```

- [ ] **Step 2: Add context-loading and selector handlers**

Inside `CreateTaskPage`, add:

```ts
const [prompt, setPrompt] = useState("");
const [submitting, setSubmitting] = useState(false);
const [agentOptions, setAgentOptions] = useState<MobileAgentOption[]>([]);
const [skillOptions, setSkillOptions] = useState<MobileSkillOption[]>([]);
const [selectedAgentId, setSelectedAgentId] = useState(FALLBACK_AGENT.id);
const [selectedSkillId, setSelectedSkillId] = useState("");
const [attachments, setAttachments] = useState<UploadedAttachment[]>([]);
const [uploadingAttachment, setUploadingAttachment] = useState(false);

const selectedAgent =
  agentOptions.find((agent) => agent.id === selectedAgentId) || FALLBACK_AGENT;
const selectedSkill =
  skillOptions.find((skill) => skill.id === selectedSkillId) || null;

const loadContextOptions = async (agentId = selectedAgentId) => {
  try {
    const agents = await listAgentOptions();
    const nextAgentId =
      agents.find((agent) => agent.id === agentId)?.id ||
      agents[0]?.id ||
      FALLBACK_AGENT.id;
    setAgentOptions(agents.length ? agents : [FALLBACK_AGENT]);
    setSelectedAgentId(nextAgentId);
    setSkillOptions(await listSkillOptions(nextAgentId));
  } catch {
    setAgentOptions([FALLBACK_AGENT]);
    setSelectedAgentId(FALLBACK_AGENT.id);
    setSkillOptions([]);
  }
};

useDidShow(() => {
  if (requireAuth()) {
    void loadContextOptions();
  }
});
```

Add action-sheet handlers:

```ts
const chooseAgent = async () => {
  const options = agentOptions.length ? agentOptions : [FALLBACK_AGENT];
  try {
    const { tapIndex } = await Taro.showActionSheet({
      itemList: options.map((agent) => agent.name),
    });
    const nextAgent = options[tapIndex];
    if (!nextAgent) return;
    setSelectedAgentId(nextAgent.id);
    setSelectedSkillId("");
    setSkillOptions(await listSkillOptions(nextAgent.id));
  } catch {
    // User cancelled.
  }
};

const chooseSkill = async () => {
  const itemList = ["不使用技能", ...skillOptions.map((skill) => skill.name)];
  try {
    const { tapIndex } = await Taro.showActionSheet({ itemList });
    if (tapIndex === 0) {
      setSelectedSkillId("");
      return;
    }
    const nextSkill = skillOptions[tapIndex - 1];
    if (nextSkill) {
      setSelectedSkillId(nextSkill.id);
    }
  } catch {
    // User cancelled.
  }
};
```

- [ ] **Step 3: Add real material selection**

Add:

```ts
const uploadSelectedFiles = async (
  files: Array<{ path?: string; name?: string; tempFilePath?: string }>,
) => {
  if (!files.length) return;
  setUploadingAttachment(true);
  try {
    const uploaded: UploadedAttachment[] = [];
    for (const file of files) {
      const path = file.path || file.tempFilePath || "";
      const name = file.name || path.split("/").pop() || "附件";
      if (!path) continue;
      uploaded.push(await uploadConsoleAttachment({ path, name }));
    }
    setAttachments((prev) => [...prev, ...uploaded]);
  } catch (error) {
    Taro.showToast({
      title: error instanceof Error ? error.message : "附件上传失败",
      icon: "none",
    });
  } finally {
    setUploadingAttachment(false);
  }
};

const chooseMaterial = async () => {
  try {
    const { tapIndex } = await Taro.showActionSheet({
      itemList: ["选择文件", "选择图片"],
    });
    if (tapIndex === 0) {
      const result = await Taro.chooseMessageFile({
        count: 3,
        type: "file",
      });
      await uploadSelectedFiles(result.tempFiles || []);
      return;
    }
    const result = await Taro.chooseMedia({
      count: 3,
      mediaType: ["image"],
    });
    await uploadSelectedFiles(result.tempFiles || []);
  } catch {
    // User cancelled.
  }
};

const openAigcWebGuide = () => {
  Taro.showModal({
    title: "请到 Web 版体验",
    content: `AIGC 创意项目当前仅支持 PC Web 端。\n体验请到 Web 版：${AIGC_WEB_URL}`,
    confirmText: "复制链接",
    cancelText: "我知道了",
    success: (result) => {
      if (result.confirm) {
        Taro.setClipboardData({ data: AIGC_WEB_URL });
      }
    },
  });
};
```

- [ ] **Step 4: Submit task with context, skill, and materials**

Replace the existing `submit` implementation:

```ts
const taskNameFrom = (goal: string) => {
  if (goal.trim()) {
    return goal.trim().slice(0, 18);
  }
  return attachments[0]?.name || "新任务";
};

const submit = async () => {
  if (!requireAuth()) return;

  const normalizedPrompt = prompt.trim();
  if (!normalizedPrompt && attachments.length === 0) {
    Taro.showToast({ title: "请输入任务目标", icon: "none" });
    return;
  }
  if (uploadingAttachment) {
    Taro.showToast({ title: "附件还在上传中，请稍候", icon: "none" });
    return;
  }

  const attachmentText = attachments.map((item) => item.markdown).join("\n");
  const taskPrompt = [normalizedPrompt, attachmentText].filter(Boolean).join("\n\n");
  const formattedPrompt = formatTaskPrompt(taskPrompt, selectedSkill);

  setSubmitting(true);
  try {
    const chat = await createAndSubmitTask({
      name: taskNameFrom(normalizedPrompt),
      prompt: formattedPrompt,
      agentId: selectedAgent.id,
      skillName: selectedSkill?.id,
    });
    Taro.redirectTo({ url: `/pages/task-detail/index?chatId=${chat.id}` });
  } catch (error) {
    Taro.showToast({
      title: error instanceof Error ? error.message : "任务创建失败，请稍后重试",
      icon: "none",
    });
  } finally {
    setSubmitting(false);
  }
};
```

- [ ] **Step 5: Render the new UI structure**

Replace the JSX body after the hero with:

```tsx
<View className="card context-card">
  <Text className="card-title">交给谁处理</Text>
  <View className="option-row" onClick={chooseAgent}>
    <View className="option-row__body">
      <Text className="option-row__label">智能体</Text>
      <Text className="option-row__value">{selectedAgent.name}</Text>
    </View>
    <Text className="option-row__action">选择</Text>
  </View>
  <View className="option-row" onClick={chooseSkill}>
    <View className="option-row__body">
      <Text className="option-row__label">技能</Text>
      <Text className="option-row__value">
        {selectedSkill?.name || "不使用技能"}
      </Text>
    </View>
    <Text className="option-row__action">选择</Text>
  </View>
</View>

<View className="card material-card">
  <View className="section-heading">
    <Text className="card-title">补充材料</Text>
    <Text className="section-action" onClick={chooseMaterial}>
      {uploadingAttachment ? "上传中" : "添加"}
    </Text>
  </View>
  {attachments.length ? (
    <View className="attachment-list">
      {attachments.map((item) => (
        <View key={`${item.name}-${item.url}`} className="attachment-item">
          <Text className="attachment-name">{item.name}</Text>
        </View>
      ))}
    </View>
  ) : (
    <Text className="muted-text">可添加文件或图片，让 DClaw 带着材料执行</Text>
  )}
</View>

<View className="card aigc-card" onClick={openAigcWebGuide}>
  <View className="section-heading">
    <View className="aigc-card__copy">
      <Text className="card-title">AIGC 创意项目</Text>
      <Text className="muted-text">图片、视频、创意画布请到 PC Web 版体验</Text>
    </View>
    <Text className="section-action">Web 版</Text>
  </View>
</View>

<View className="card goal-card">
  <Text className="card-title">描述任务目标</Text>
  <Textarea
    className="prompt-input"
    value={prompt}
    placeholder="告诉 DClaw 要完成什么、参考什么、希望输出什么结果..."
    maxlength={2000}
    onInput={(event) => setPrompt(String(event.detail.value || ""))}
  />
</View>

<View className="template-list">
  <Text className="template-title">常用任务</Text>
  {TASK_TEMPLATES.map((template) => (
    <View
      key={template}
      className="template-chip"
      onClick={() => setPrompt(template)}
    >
      <Text>{template}</Text>
    </View>
  ))}
</View>
```

Keep the submit button, but change its label:

```tsx
<Button className="submit-button" loading={submitting} onClick={submit}>
  交给 DClaw 执行
</Button>
```

---

### Task 5: Restyle Create Task For The Style-4 System

**Files:**
- Modify: `miniapp/src/pages/create-task/index.scss`

- [ ] **Step 1: Replace old context/prompt/template classes**

Update the style file so it contains these sections:

```scss
.create-task-page {
  display: flex;
  flex-direction: column;
  gap: 14px;

  .create-hero {
    display: flex;
    align-items: center;
    min-height: 124px;
    box-sizing: border-box;
    padding: 16px;
    border: 1px solid #ffe1cd;
    border-radius: 18px;
    background: #fff0df;
    box-shadow: 0 12px 36px rgba(32, 28, 24, 0.1);
  }

  .create-hero__copy {
    display: flex;
    min-width: 0;
    flex: 1;
    flex-direction: column;
    gap: 8px;
  }

  .create-hero__title {
    color: #19191b;
    font-size: 20px;
    font-weight: 800;
  }

  .create-hero__desc {
    color: #777d89;
    font-size: 13px;
    line-height: 1.5;
  }

  .create-hero__mascot {
    width: 88px;
    height: 88px;
    flex: 0 0 88px;
    border-radius: 24px;
  }

  .context-card,
  .material-card,
  .aigc-card,
  .goal-card {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .card-title {
    color: #19191b;
    font-size: 16px;
    font-weight: 800;
  }

  .option-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px;
    border: 1px solid #eceef2;
    border-radius: 14px;
    background: #fffaf3;
  }

  .option-row__body {
    display: flex;
    min-width: 0;
    flex: 1;
    flex-direction: column;
    gap: 4px;
  }

  .option-row__label {
    color: #777d89;
    font-size: 12px;
  }

  .option-row__value {
    color: #19191b;
    font-size: 14px;
    font-weight: 700;
  }

  .option-row__action,
  .section-action {
    color: #ff5a1f;
    font-size: 13px;
    font-weight: 800;
  }

  .section-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .muted-text {
    color: #777d89;
    font-size: 13px;
    line-height: 1.5;
  }

  .attachment-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .attachment-item {
    padding: 10px 12px;
    border-radius: 12px;
    background: #fffaf3;
  }

  .attachment-name {
    color: #19191b;
    font-size: 13px;
    font-weight: 700;
  }

  .aigc-card {
    background: #ffffff;
  }

  .aigc-card__copy {
    display: flex;
    min-width: 0;
    flex: 1;
    flex-direction: column;
    gap: 6px;
  }

  .prompt-input {
    width: 100%;
    min-height: 150px;
    box-sizing: border-box;
    padding: 12px;
    border-radius: 14px;
    background: #fffaf3;
    color: #19191b;
    font-size: 15px;
    line-height: 1.5;
  }

  .template-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .template-title {
    color: #19191b;
    font-size: 15px;
    font-weight: 800;
  }

  .template-chip {
    padding: 13px 14px;
    border: 1px solid #eceef2;
    border-radius: 14px;
    background: #ffffff;
    color: #19191b;
    font-size: 14px;
  }

  .submit-button {
    height: 48px;
    margin-top: 6px;
    border-radius: 14px;
    color: #ffffff;
    background: #ff5a1f;
    font-size: 16px;
    font-weight: 800;
    line-height: 48px;
  }
}
```

- [ ] **Step 2: Run the contract test**

Run:

```bash
npm run test:run -- src/pages/create-task/createTaskContract.test.ts
```

Expected: PASS.

---

### Task 6: Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run targeted tests**

Run:

```bash
cd /Users/zu/Documents/workes/qwenpaw/miniapp
npm run test:run -- src/services/consoleChat.test.ts src/services/attachments.test.ts src/pages/create-task/createTaskContract.test.ts src/services/taskContext.test.ts
```

Expected: all targeted tests pass.

- [ ] **Step 2: Run all mini-program tests**

Run:

```bash
npm run test:run
```

Expected: all tests pass.

- [ ] **Step 3: Run typecheck**

Run:

```bash
npm run typecheck
```

Expected: no TypeScript errors.

- [ ] **Step 4: Build WeChat output**

Run:

```bash
npm run build:weapp
```

Expected: build succeeds and `scripts/fix-wxml-imports.mjs` normalizes page WXML imports.

- [ ] **Step 5: Manual mini-program smoke test**

Open `/Users/zu/Documents/workes/qwenpaw/miniapp` in WeChat DevTools and verify:

- Create task page shows `交给谁处理`, `补充材料`, `描述任务目标`, and `交给 DClaw 执行`.
- Agent action sheet opens.
- Skill action sheet opens.
- A text-only task can be created.
- The app redirects to task detail with a real `chatId`.
- If a skill is selected, the created task receives the skill invocation in the first message and the backend metadata includes `selected_skill`.
