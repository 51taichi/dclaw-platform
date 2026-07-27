import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RuntimeProgressCard from "./RuntimeProgressCard";

vi.mock("@agentscope-ai/chat", () => ({
  Markdown: ({ content }: { content: string }) => <div>{content}</div>,
}));

describe("RuntimeProgressCard", () => {
  it("collapses repeated tool and reasoning events into a progress summary", () => {
    render(
      <RuntimeProgressCard
        data={{
          status: "in_progress",
          output: [
            {
              id: "msg-1",
              type: "message",
              status: "completed",
              content: [{ type: "text", text: "我来帮你修改标题。" }],
            },
            {
              id: "reasoning-1",
              type: "reasoning",
              status: "completed",
              content: [{ type: "text", text: "" }],
            },
            {
              id: "tool-1",
              type: "plugin_call",
              status: "completed",
              content: [
                {
                  type: "data",
                  data: {
                    name: "edit_file",
                    arguments: { file_path: "/tmp/project/post.md" },
                  },
                },
              ],
            },
            {
              id: "tool-2",
              type: "plugin_call",
              status: "in_progress",
              content: [
                {
                  type: "data",
                  data: {
                    name: "edit_file",
                    arguments: { file_path: "/tmp/project/about.md" },
                  },
                },
              ],
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("DClaw")).toBeInTheDocument();
    expect(screen.getByText("我来帮你修改标题。")).toBeInTheDocument();
    expect(screen.getByText(/正在修改文件/)).toBeInTheDocument();
    expect(screen.getByText("修改文件 2")).toBeInTheDocument();
    expect(screen.getByText("思考 1")).toBeInTheDocument();
    expect(screen.queryByText("Thinking")).not.toBeInTheDocument();
    expect(screen.queryByText("edit_file")).not.toBeInTheDocument();
  });

  it("shows a calm thinking status when no text has arrived yet", () => {
    render(
      <RuntimeProgressCard
        data={{
          status: "in_progress",
          output: [],
        }}
      />,
    );

    expect(screen.getByText("DClaw")).toBeInTheDocument();
    expect(screen.getByText("正在思考下一步...")).toBeInTheDocument();
  });

  it("renders response images inline and opens a detail preview", () => {
    render(
      <RuntimeProgressCard
        data={{
          status: "completed",
          output: [
            {
              id: "msg-1",
              type: "message",
              status: "completed",
              content: [
                { type: "text", text: "请选择视觉方案。" },
                {
                  type: "image",
                  image_url: "/api/user/workspace/preview/scheme.png",
                },
              ],
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("请选择视觉方案。")).toBeInTheDocument();
    const preview = screen.getByAltText("对话图片 1");
    expect(preview).toBeInTheDocument();
    expect(preview).toHaveAttribute(
      "src",
      "/api/user/workspace/preview/scheme.png",
    );

    fireEvent.click(preview);

    const dialog = screen.getByRole("dialog", { name: "图片预览" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByAltText("图片预览")).toHaveAttribute(
      "src",
      "/api/user/workspace/preview/scheme.png",
    );
  });

  it("hides generated image file paths from assistant text", () => {
    render(
      <RuntimeProgressCard
        data={{
          status: "completed",
          output: [
            {
              id: "msg-1",
              type: "message",
              status: "completed",
              content: [
                {
                  type: "text",
                  text: [
                    "新生成的图像文件：",
                    "- 方案一：/app/working/workspaces/default/sessions_data/<session_id>/media/imagegen/imagegen_1782365209213.png",
                    "- 方案二：/app/working/workspaces/default/sessions_data/<session_id>/media/imagegen/imagegen_1782365278687.png",
                    "选择后，我将继续进行设计系统提取。",
                  ].join("\n"),
                },
                {
                  type: "image",
                  image_url:
                    "/api/user/files/preview//app/working/workspaces/default/sessions_data/1782359420083/media/imagegen/imagegen_1782365209213.png",
                },
              ],
            },
          ],
        }}
      />,
    );

    expect(screen.getByText(/方案一：见下方图片 1/)).toBeInTheDocument();
    expect(screen.getByText(/方案二：见下方图片 2/)).toBeInTheDocument();
    expect(screen.queryByText(/\/app\/working/)).not.toBeInTheDocument();
    expect(screen.queryByText(/<session_id>/)).not.toBeInTheDocument();
    expect(screen.getByAltText("对话图片 1")).toBeInTheDocument();
  });

  it("labels imagegen visual scheme previews and rewrites local workspace image URLs", () => {
    render(
      <RuntimeProgressCard
        chatId="chat-123"
        agentId="default"
        data={{
          status: "completed",
          output: [
            {
              id: "msg-1",
              type: "message",
              status: "completed",
              content: [
                {
                  type: "image",
                  source: {
                    type: "url",
                    url: "file:///app/working/workspaces/default/media/ppt_visual_schemes/imagegen_1782712947438.png",
                  },
                },
                {
                  type: "text",
                  text: [
                    "Generated image with imagegen (GPT Image 2 / MXAPI)",
                    "Style direction: 战略AI指挥中心（AI Command Center）- 深色控制室画布、模块化系统拓扑",
                  ].join("\n"),
                },
              ],
            },
          ],
        }}
      />,
    );

    expect(screen.getByText("战略AI指挥中心")).toBeInTheDocument();
    const preview = screen.getByAltText("战略AI指挥中心");
    expect(preview).toHaveAttribute(
      "src",
      "/api/user/workspace/preview/__qwenpaw_preview__/default/chat-123/media/ppt_visual_schemes/imagegen_1782712947438.png",
    );
  });

  it("does not duplicate long tool names in the detail row when no target exists", () => {
    render(
      <RuntimeProgressCard
        data={{
          status: "in_progress",
          output: [
            {
              id: "tool-1",
              type: "plugin_call",
              status: "in_progress",
              content: [
                {
                  type: "data",
                  data: {
                    name: "presentation_builder",
                    arguments: {},
                  },
                },
              ],
            },
          ],
        }}
      />,
    );

    fireEvent.click(screen.getByText("查看详细操作"));

    expect(screen.getAllByText("presentation_builder")).toHaveLength(1);
  });
});
