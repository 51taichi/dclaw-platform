# DClaw Miniapp Create Task Design

## Goal

The mini-program create-task page should help ordinary users delegate real work to DClaw, not feel like a raw prompt-to-text generator. It should preserve the web console task model in a mobile-sized flow: choose the execution context, provide task intent and materials, create a task chat, send the first task request, then continue in task detail.

## Current Product Model

- Web workbench creates a backend task chat before execution, stores task metadata, saves the first task intent, and navigates to `/task/{chatId}`.
- Web task composition supports agent or mode selection, expert-team context, skill selection, attachments, and task prompt formatting.
- Mini-program task detail already supports continuing a task with an agent selector, skill selector, stop action, confirmations, messages, and artifact links.
- Mini-program create-task currently has only a default context card, a textarea, and three scenario chips. It does not expose agent or skill selection and does not fully pass selected skill metadata through the create-and-submit service path.

## First-Release Audience

The first mobile release is for ordinary users. It should make quick delegation, follow-up, confirmation, and result retrieval easy. It should not expose admin or workspace-management controls.

## Recommended Experience

Use a mobile task-delegation form with five sections.

### 1. Execution Context

Replace "当前执行上下文" with an actionable "交给谁处理" section.

The section shows two compact rows:

- `智能体`: default to `DClaw 助手` or the first enabled agent from `/api/user/agents`.
- `技能`: default to `不使用技能`; list enabled workspace skills plus default pool skills for the selected agent.

Tapping either row opens a native action sheet. Changing the agent clears the selected skill and reloads available skills.

### 2. Materials

Show a "补充材料" section before the task goal.

First implementation can support a visible entry and selected-file summary, with actual upload wired only if the endpoint and WeChat file picker path are reliable in the mini-program build. The UI should communicate the product model even if advanced material sources are delivered in a later slice.

Preferred material sources by priority:

- Local file or image attachment through WeChat picker and `/api/user/console/upload`.
- Existing knowledge or workspace file selection in a later slice.
- Text-only task remains valid when no material is attached.

### 3. Task Goal

Keep the large textarea, but change the copy from generic prompt language to task delegation language.

Recommended label:

`描述任务目标`

Recommended placeholder:

`告诉 DClaw 要完成什么、参考什么、希望输出什么结果...`

The submit button should read:

`交给 DClaw 执行`

### 4. Common Task Templates

Keep common tasks, but treat them as task templates. Tapping a template fills the goal and can optionally recommend a skill if a matching skill exists.

Initial templates:

- `整理上周项目进展`
- `生成销售数据分析摘要`
- `把资料整理成汇报提纲`

### 5. Web-Only AIGC Project Entry

The current AIGC Studio/project capability is a PC Web capability. The mini-program should still make this visible so users who want AIGC understand where to go.

Show a compact `AIGC 创意项目` or `AIGC 创意工作室` entry on the create-task page. Tapping it must not create a mini-program task. It opens a modal:

```text
体验请到 Web 版：
https://dclaw.deepmega.cn/
```

The modal can offer copying the URL. This keeps mini-program scope focused on ordinary task delegation while guiding AIGC demand to the web product.

## Data Flow

```text
CreateTask page shown
  -> requireAuth()
  -> listAgentOptions()
  -> select default agent
  -> listSkillOptions(agentId)
  -> user selects optional skill and enters goal
  -> formatTaskPrompt(goal, selectedSkill)
  -> createAndSubmitTask({
       name,
       prompt: formattedPrompt,
       agentId,
       skillName,
       expertTeamId
     })
  -> createTaskShell()
  -> sendTaskPrompt()
  -> redirect to /pages/task-detail/index?chatId=...
```

The create-and-submit service must pass `skillName` into the final send path so the backend receives both the invocation-formatted prompt and `meta.selected_skill`.

## Task Naming

Use a short title derived from the goal, with a fallback:

- If goal text exists: first 18 characters.
- If only material exists: first material name.
- Otherwise: `新任务`.

## Error Handling

- No auth: redirect to login through the existing auth helper.
- No goal and no material: toast `请输入任务目标`.
- Agent list failure: fall back to `DClaw 助手`.
- Skill list failure: show `不使用技能` and allow text-only task creation.
- Create or send failure: toast `任务创建失败，请稍后重试` unless the API provides a more specific localized message.

## Visual Direction

Keep the selected style-4 visual system:

- Warm white and pale orange surfaces.
- Rounded cards consistent with the existing mini-program.
- Image-generated mascot and icon assets where available.
- Avoid flat placeholder icons when an image asset exists.
- Avoid turning the page into a dashboard; this is a focused task handoff form.

## Non-Goals

- Do not add mobile web or PWA behavior.
- Do not add admin features.
- Do not make the user configure providers, expert teams, or workspace settings on mobile.
- Do not build full web parity for drag-and-drop, rich file mention, or connector management in the first slice.
- Do not implement AIGC Studio execution inside the mini-program; guide users to `https://dclaw.deepmega.cn/`.
- Do not label the feature as approval until the exact confirmation object is shown by the backend.

## Testing

Add or update mini-program tests for:

- Create-task page contract includes `交给谁处理`, `智能体`, `技能`, `补充材料`, `描述任务目标`, and `交给 DClaw 执行`.
- Create-task page contract includes an AIGC web-only entry and `https://dclaw.deepmega.cn/`.
- The page no longer presents the core flow as `当前执行上下文` and `你想完成什么？`.
- `createAndSubmitTask` forwards selected `agentId` and `skillName` through `sendTaskPrompt`.
- `formatTaskPrompt` keeps the skill invocation syntax.

Run:

```bash
cd /Users/zu/Documents/workes/qwenpaw/miniapp
npm run test:run
npm run typecheck
npm run build:weapp
```
