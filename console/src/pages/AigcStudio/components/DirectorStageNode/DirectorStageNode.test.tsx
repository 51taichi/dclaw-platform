import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import { DirectorStageNode } from "./DirectorStageNode";
import type { DirectorStageWorkflow } from "./types";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

const stageNode = (data: AigcCanvasNode["data"] = {}): AigcCanvasNode => ({
  id: "stage-1",
  type: "director_stage",
  position: { x: 320, y: 160 },
  data: {
    title: "导演台",
    text: "3D 场景、机位、角色调度",
    ...data,
  },
});

const workflow = (
  overrides: Partial<DirectorStageWorkflow> = {},
): DirectorStageWorkflow => ({
  openNodeId: null,
  handleOpenStage: vi.fn(),
  handleCloseStage: vi.fn(),
  handleSaveProject: vi.fn(),
  handleCapture: vi.fn(),
  handleCaptureBatch: vi.fn(),
  handleUploadModel: vi.fn(),
  ...overrides,
});

describe("DirectorStageNode", () => {
  it("renders the empty director stage state and opens the editor", () => {
    const handleOpenStage = vi.fn();
    const node = stageNode();

    render(
      <DirectorStageNode
        node={node}
        selected={false}
        t={t}
        workflow={workflow({ handleOpenStage })}
      />,
    );

    expect(screen.getAllByText("导演台").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("未创建场景")).toBeInTheDocument();
    expect(screen.getByText("角色 0 · 道具 0 · 机位 0")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "打开导演台" }));

    expect(handleOpenStage).toHaveBeenCalledWith(node);
  });

  it("summarizes saved project objects and cameras", () => {
    render(
      <DirectorStageNode
        node={stageNode({
          directorStageProject: {
            version: 1,
            objects: [
              { id: "character-1", kind: "character", name: "角色01" },
              { id: "prop-1", kind: "prop", name: "立方体" },
            ],
            cameras: [{ id: "camera-1", name: "机位01" }],
          },
        })}
        selected
        t={t}
        workflow={workflow()}
      />,
    );

    expect(screen.getByText("已保存场景")).toBeInTheDocument();
    expect(screen.getByText("角色 1 · 道具 1 · 机位 1")).toBeInTheDocument();
  });

  it("renders the latest capture preview when captures exist", () => {
    render(
      <DirectorStageNode
        node={stageNode({
          previewUrl: "/api/user/aigc-studio/assets/capture-1/file",
          directorStageCaptures: [
            {
              id: "capture-1",
              assetId: "asset-1",
              name: "机位01.png",
              previewUrl: "/api/user/aigc-studio/assets/capture-1/file",
              createdAt: 1783500000000,
            },
          ],
        })}
        selected={false}
        t={t}
        workflow={workflow()}
      />,
    );

    expect(screen.getByText("截图 1 张")).toBeInTheDocument();
    const preview = screen.getByAltText("机位01.png");
    expect(preview).toHaveAttribute("data-authenticated-asset", "true");
  });
});
