import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";

import { TaskArtifactCard } from "./TaskArtifactCard";

describe("TaskArtifactCard", () => {
  it("shows a friendly empty state instead of internal agent files", () => {
    renderWithProviders(
      <TaskArtifactCard
        chatId="chat-id"
        files={[
          "agent.json",
          "memory_file_metadata.json",
          "HEARTBEAT.md",
          "MEMORY.md",
          "BOOTSTRAP.md",
          "SOUL.md",
          "AGENTS.md",
          "PROFILE.md",
        ]}
      />,
    );

    expect(
      screen.getByText("本次任务没有生成独立文件，结果已在对话中展示。"),
    ).toBeInTheDocument();
    expect(screen.queryByText("agent.json")).not.toBeInTheDocument();
    expect(
      screen.queryByText("文件变更", { exact: false }),
    ).not.toBeInTheDocument();
  });

  it("keeps user deliverables and hides internal files in mixed results", () => {
    renderWithProviders(
      <TaskArtifactCard
        chatId="chat-id"
        files={[
          "agent.json",
          "article.md",
          "memory_file_metadata.json",
          "src/App.tsx",
        ]}
      />,
    );

    expect(screen.getAllByText("article.md").length).toBeGreaterThan(0);
    expect(screen.getAllByText("src/App.tsx").length).toBeGreaterThan(0);
    expect(screen.queryByText("agent.json")).not.toBeInTheDocument();
    expect(
      screen.queryByText("memory_file_metadata.json"),
    ).not.toBeInTheDocument();
  });

  it("hides tool result caches and emits the active chat id when opening a product", () => {
    const listener = vi.fn();
    window.addEventListener("preview-artifact", listener);

    renderWithProviders(
      <TaskArtifactCard
        chatId="active-chat-id"
        files={[
          "儿童节短剧_最好的礼物.md",
          "tool_results/result.txt",
        ]}
      />,
    );

    expect(screen.getByText("儿童节短剧_最好的礼物.md")).toBeInTheDocument();
    expect(screen.queryByText("tool_results/result.txt")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("儿童节短剧_最好的礼物.md"));

    expect(listener).toHaveBeenCalledTimes(1);
    expect((listener.mock.calls[0][0] as CustomEvent).detail).toMatchObject({
      path: "儿童节短剧_最好的礼物.md",
      activeTab: "artifacts",
      chatId: "active-chat-id",
    });

    window.removeEventListener("preview-artifact", listener);
  });

  it("renders image artifacts as inline thumbnails", () => {
    const listener = vi.fn();
    window.addEventListener("preview-artifact", listener);

    renderWithProviders(
      <TaskArtifactCard
        chatId="active-chat-id"
        files={["media/imagegen/imagegen_123.png"]}
      />,
    );

    const preview = screen.getByAltText("media/imagegen/imagegen_123.png");
    expect(preview).toBeInTheDocument();
    expect(preview).toHaveAttribute(
      "src",
      "/api/user/workspace/preview/__qwenpaw_preview__/default/active-chat-id/media/imagegen/imagegen_123.png",
    );

    fireEvent.click(preview);

    expect(listener).toHaveBeenCalledTimes(1);
    expect((listener.mock.calls[0][0] as CustomEvent).detail).toMatchObject({
      path: "media/imagegen/imagegen_123.png",
      activeTab: "artifacts",
      chatId: "active-chat-id",
    });

    window.removeEventListener("preview-artifact", listener);
  });

  it("renders generated image artifacts as conversation previews with a detail dialog", () => {
    renderWithProviders(
      <TaskArtifactCard
        chatId="active-chat-id"
        files={[
          "media/imagegen/imagegen_123.png",
          "media/imagegen/imagegen_456.png",
        ]}
      />,
    );

    const conversationPreview = screen.getByAltText("对话图片 1");
    expect(conversationPreview).toBeInTheDocument();
    expect(conversationPreview).toHaveAttribute(
      "src",
      "/api/user/workspace/preview/__qwenpaw_preview__/default/active-chat-id/media/imagegen/imagegen_123.png",
    );

    fireEvent.click(conversationPreview);

    expect(
      screen.getByRole("dialog", { name: "图片预览" }),
    ).toBeInTheDocument();
    expect(screen.getByAltText("图片预览")).toHaveAttribute(
      "src",
      "/api/user/workspace/preview/__qwenpaw_preview__/default/active-chat-id/media/imagegen/imagegen_123.png",
    );
    expect(screen.getByText("任务产生制品（2个）：")).toBeInTheDocument();
  });

  it("prefers final PPT deliverables over intermediate imagegen files", () => {
    renderWithProviders(
      <TaskArtifactCard
        chatId="active-chat-id"
        files={[
          "media/imagegen/imagegen_123.png",
          "深兆左智企业AI落地共建服务手册_数据驱动版.pptx",
          "media/imagegen/imagegen_456.png",
        ]}
      />,
    );

    expect(
      screen.getByText("深兆左智企业AI落地共建服务手册_数据驱动版.pptx"),
    ).toBeInTheDocument();
    expect(screen.queryByAltText("media/imagegen/imagegen_123.png")).not.toBeInTheDocument();
    expect(screen.getByText("任务产生制品（1个）：")).toBeInTheDocument();
  });

  it("hides presentation render QA previews from deliverables", () => {
    renderWithProviders(
      <TaskArtifactCard
        chatId="active-chat-id"
        files={[
          "deck.pptx",
          "deck_render_qa/contact_sheet.png",
          "deck_render_qa/slide-01.png",
          "deck_render_qa/_work/deck.pdf",
        ]}
      />,
    );

    expect(screen.getByText("deck.pptx")).toBeInTheDocument();
    expect(screen.queryByAltText("deck_render_qa/contact_sheet.png")).not.toBeInTheDocument();
    expect(screen.queryByText("deck.pdf")).not.toBeInTheDocument();
    expect(screen.getByText("任务产生制品（1个）：")).toBeInTheDocument();
  });
});
