import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CanvasAssetRecord } from "../../canvasNodeUtils";
import { CanvasRailPanel } from "./CanvasRailPanel";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

const assetRecord = (
  id: string,
  overrides: Partial<CanvasAssetRecord> = {},
): CanvasAssetRecord => ({
  id,
  title: `Asset ${id}`,
  kind: "图片",
  nodeType: "image_generate",
  sourceNodeId: `node-${id}`,
  text: "",
  createdAt: Date.now(),
  ...overrides,
});

describe("CanvasRailPanel", () => {
  it("renders workflow templates and routes template selection", () => {
    const template = vi.fn();

    render(
      <CanvasRailPanel
        railPanel="workflows"
        assetRecords={[]}
        subjectRecords={[]}
        historyRecords={[]}
        t={t}
        onTemplate={template}
        onUseAssetRecord={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /故事脚本生成/ }));

    expect(screen.getByText("我的工具箱")).toBeInTheDocument();
    expect(template).toHaveBeenCalledWith("story");
  });

  it("renders assets and subjects with selection callbacks", () => {
    const useAsset = vi.fn();
    const material = assetRecord("material", {
      title: "角色参考图",
      assetPreviewUrl: "/api/user/aigc-studio/assets/asset-1/file",
    });
    const subject = assetRecord("subject", { title: "主角主体" });

    render(
      <CanvasRailPanel
        railPanel="assets"
        assetRecords={[material]}
        subjectRecords={[subject]}
        historyRecords={[]}
        t={t}
        onTemplate={vi.fn()}
        onUseAssetRecord={useAsset}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /角色参考图/ }));
    fireEvent.click(screen.getByRole("button", { name: /主角主体/ }));

    expect(screen.getByText("素材")).toBeInTheDocument();
    expect(screen.getByText("主体库")).toBeInTheDocument();
    expect(screen.getByTestId("aigc-rail-panel")).toHaveAttribute(
      "data-panel-size",
      "large",
    );
    expect(screen.getByAltText("角色参考图")).toHaveAttribute(
      "data-authenticated-asset",
      "true",
    );
    expect(useAsset).toHaveBeenCalledWith(material);
    expect(useAsset).toHaveBeenCalledWith(subject);
  });

  it("renders history empty state and help instructions", () => {
    const { rerender } = render(
      <CanvasRailPanel
        railPanel="history"
        assetRecords={[]}
        subjectRecords={[]}
        historyRecords={[]}
        t={t}
        onTemplate={vi.fn()}
        onUseAssetRecord={vi.fn()}
      />,
    );

    expect(screen.getByText("暂无生成历史")).toBeInTheDocument();

    rerender(
      <CanvasRailPanel
        railPanel="help"
        assetRecords={[]}
        subjectRecords={[]}
        historyRecords={[]}
        t={t}
        onTemplate={vi.fn()}
        onUseAssetRecord={vi.fn()}
      />,
    );

    expect(screen.getByText("双击空画布或点 + 添加节点")).toBeInTheDocument();
    expect(screen.getByText("画布操作指南")).toBeInTheDocument();
    expect(screen.queryByText(/LibTV/i)).not.toBeInTheDocument();
    expect(
      screen.getByText("图片输入框输入 / 呼出快捷工具"),
    ).toBeInTheDocument();
  });
});
