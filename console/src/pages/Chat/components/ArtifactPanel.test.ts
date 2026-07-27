import { describe, expect, it } from "vitest";
import {
  buildArtifactDerivedTasks,
  buildExpertTeamRunTasks,
  buildTextOutputDerivedTasks,
  isDownloadOnlyPreviewFile,
  isTextPreviewFile,
} from "./ArtifactPanel";

describe("ArtifactPanel task board", () => {
  it("treats office files as download-only instead of text preview", () => {
    expect(isTextPreviewFile("方案汇报.pptx")).toBe(false);
    expect(isDownloadOnlyPreviewFile("方案汇报.pptx")).toBe(true);
    expect(isTextPreviewFile("notes.md")).toBe(true);
    expect(isDownloadOnlyPreviewFile("cover.png")).toBe(false);
  });

  it("derives completed task items from visible artifacts when task.md is absent", () => {
    const tasks = buildArtifactDerivedTasks([
      {
        filename: "任务列表",
        path: "task.md",
        size: 0,
        created_time: "",
        modified_time: "",
        isVirtual: true,
      },
      {
        filename: "snake_game.html",
        path: "snake_game.html",
        size: 18_000,
        created_time: "",
        modified_time: "",
      },
    ]);

    expect(tasks.map((task) => task.text)).toEqual([
      "整理本次任务产物（1 个文件）",
      "生成 snake_game.html",
      "网页产物已接入右侧内置浏览器预览",
    ]);
    expect(tasks.every((task) => task.status === "completed")).toBe(true);
  });

  it("derives a completed item for text-only assistant output", () => {
    const tasks = buildTextOutputDerivedTasks({
      status: "idle",
      messages: [
        { role: "user", content: "写一个玄幻故事 1000字" },
        {
          role: "assistant",
          content: [{ type: "text", text: "《剑破苍穹》..." }],
        },
      ],
    });

    expect(tasks).toEqual([
      {
        text: "完成文字结果输出",
        status: "completed",
        level: 0,
      },
    ]);
  });

  it("shows an in-progress item while text output is still running", () => {
    const tasks = buildTextOutputDerivedTasks({
      status: "running",
      messages: [{ role: "user", content: "写一个故事" }],
    });

    expect(tasks).toEqual([
      {
        text: "正在生成文字结果",
        status: "in_progress",
        level: 0,
      },
    ]);
  });

  it("derives task progress from an expert team run", () => {
    const tasks = buildExpertTeamRunTasks({
      id: "run-1",
      team_id: "ai_video_team",
      root_chat_id: "chat-1",
      root_session_id: "session-1",
      user_id: "1",
      state: "running",
      members: [
        {
          id: "m1",
          run_id: "run-1",
          member_key: "researcher",
          agent_id: "default",
          display_name: "信息采集员",
          role: "调研",
          state: "completed",
          stage_index: 0,
        },
        {
          id: "m2",
          run_id: "run-1",
          member_key: "planner",
          agent_id: "default",
          display_name: "内容策划师",
          role: "策划",
          state: "running",
          stage_index: 1,
        },
      ],
    });

    expect(tasks).toEqual([
      {
        text: "信息采集员：调研",
        status: "completed",
        level: 0,
      },
      {
        text: "内容策划师：策划",
        status: "in_progress",
        level: 1,
      },
    ]);
  });
});
