import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import { CanvasPortMenu } from "./CanvasPortMenu";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

const node = (type: string): AigcCanvasNode => ({
  id: `${type}-1`,
  type,
  position: { x: 0, y: 0 },
  data: {},
});

describe("CanvasPortMenu", () => {
  it("renders left-port context title and routes enabled choices", () => {
    const createPortNode = vi.fn();
    const promptNode = node("prompt");

    render(
      <CanvasPortMenu
        menu={{ nodeId: promptNode.id, side: "left", x: 12, y: 34 }}
        node={promptNode}
        t={t}
        onCreatePortNode={createPortNode}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "文本" }));

    expect(screen.getByTestId("aigc-port-menu")).toHaveStyle({
      left: "12px",
      top: "34px",
    });
    expect(screen.getByText("添加上下文")).toBeInTheDocument();
    expect(createPortNode).toHaveBeenCalledWith(promptNode, "prompt", "left");
  });

  it("disables unsupported right-port choices", () => {
    const audioNode = node("audio_generate");

    render(
      <CanvasPortMenu
        menu={{ nodeId: audioNode.id, side: "right", x: 0, y: 0 }}
        node={audioNode}
        t={t}
        onCreatePortNode={vi.fn()}
      />,
    );

    expect(screen.getByText("引用该节点生成")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "视频" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "文本" })).toBeDisabled();
  });

  it("matches prompt left-port context choices", () => {
    const promptNode = node("prompt");

    render(
      <CanvasPortMenu
        menu={{ nodeId: promptNode.id, side: "left", x: 0, y: 0 }}
        node={promptNode}
        t={t}
        onCreatePortNode={vi.fn()}
      />,
    );

    expect(screen.getByText("添加上下文")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "文本" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "图片" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "视频" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /参考节点/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /视频合成/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /导演台/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "音频" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /脚本/ })).toBeDisabled();
  });

  it("matches prompt right-port generation choices", () => {
    const promptNode = node("prompt");

    render(
      <CanvasPortMenu
        menu={{ nodeId: promptNode.id, side: "right", x: 0, y: 0 }}
        node={promptNode}
        t={t}
        onCreatePortNode={vi.fn()}
      />,
    );

    expect(screen.getByText("引用该节点生成")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "文本" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "图片" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "视频" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "音频" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /脚本/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /公众号长图/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /脚本/ })).not.toHaveTextContent(
      "NEW",
    );
    expect(screen.getByRole("button", { name: /视频合成/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /导演台/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /参考节点/ })).toBeDisabled();
  });

  it("matches image left-port context choices", () => {
    const imageNode = node("image_generate");

    render(
      <CanvasPortMenu
        menu={{ nodeId: imageNode.id, side: "left", x: 0, y: 0 }}
        node={imageNode}
        t={t}
        onCreatePortNode={vi.fn()}
      />,
    );

    expect(screen.getByText("添加上下文")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "文本" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "图片" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /参考节点/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: "视频" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /视频合成/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /导演台/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "音频" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /脚本/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /脚本/ })).toHaveTextContent(
      "NEW",
    );
  });

  it("matches image right-port generation choices", () => {
    const imageNode = node("image_generate");

    render(
      <CanvasPortMenu
        menu={{ nodeId: imageNode.id, side: "right", x: 0, y: 0 }}
        node={imageNode}
        t={t}
        onCreatePortNode={vi.fn()}
      />,
    );

    expect(screen.getByText("引用该节点生成")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "文本" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "图片" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "视频" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /导演台/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /脚本/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /公众号长图/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /脚本/ })).not.toHaveTextContent(
      "NEW",
    );
    expect(screen.getByRole("button", { name: /视频合成/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "音频" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /参考节点/ })).toBeDisabled();
  });

  it("matches video left-port context choices", () => {
    const videoNode = node("video_generate");

    render(
      <CanvasPortMenu
        menu={{ nodeId: videoNode.id, side: "left", x: 0, y: 0 }}
        node={videoNode}
        t={t}
        onCreatePortNode={vi.fn()}
      />,
    );

    expect(screen.getByText("添加上下文")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "文本" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "图片" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "视频" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /视频合成/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: "音频" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /参考节点/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /导演台/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /脚本/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /脚本/ })).toHaveTextContent(
      "NEW",
    );
  });

  it("matches video right-port generation choices", () => {
    const videoNode = node("video_generate");

    render(
      <CanvasPortMenu
        menu={{ nodeId: videoNode.id, side: "right", x: 0, y: 0 }}
        node={videoNode}
        t={t}
        onCreatePortNode={vi.fn()}
      />,
    );

    expect(screen.getByText("引用该节点生成")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "文本" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "视频" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /视频合成/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /脚本/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /脚本/ })).not.toHaveTextContent(
      "NEW",
    );
    expect(screen.getByRole("button", { name: "图片" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /导演台/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "音频" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /参考节点/ })).toBeDisabled();
  });
});
