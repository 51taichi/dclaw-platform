import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import { GenericNode } from "./GenericNode";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

describe("GenericNode", () => {
  it("renders script previews line by line", () => {
    const node: AigcCanvasNode = {
      id: "script-preview",
      type: "output",
      position: { x: 0, y: 0 },
      data: {
        title: "脚本预览",
        text: "第一镜：产品特写\n第二镜：人物入场",
        previewKind: "script",
      },
    };

    render(
      <GenericNode
        node={node}
        icon={<span data-testid="node-icon">I</span>}
        translatedType="输出"
        t={t}
      />,
    );

    expect(screen.getByText("脚本预览")).toBeInTheDocument();
    expect(screen.getByText("输出")).toBeInTheDocument();
    expect(screen.getByText("第一镜：产品特写")).toBeInTheDocument();
    expect(screen.getByText("第二镜：人物入场")).toBeInTheDocument();
  });

  it("renders director stage preview actions", () => {
    const node: AigcCanvasNode = {
      id: "stage-1",
      type: "director_stage",
      position: { x: 0, y: 0 },
      data: {
        title: "导演台",
        text: "安排角色和机位",
      },
    };

    render(
      <GenericNode
        node={node}
        icon={<span data-testid="node-icon">D</span>}
        translatedType="导演台"
        t={t}
      />,
    );

    expect(screen.getAllByText("导演台").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("打开导演台")).toBeInTheDocument();
  });
});
