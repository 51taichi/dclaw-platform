import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import { AudioNode } from "./AudioNode";

const t = ((
  _key: string,
  fallback?: string,
  values?: Record<string, unknown>,
) => {
  const template = fallback ?? _key;
  return Object.entries(values ?? {}).reduce(
    (result, [key, value]) => result.replace(`{{${key}}}`, String(value)),
    template,
  );
}) as never;

const audioNode = (data: AigcCanvasNode["data"]): AigcCanvasNode => ({
  id: "audio-1",
  type: "audio_generate",
  position: { x: 360, y: 120 },
  data: {
    title: "音频节点 2",
    text: "虽然不曾怀疑你",
    ...data,
  },
});

describe("AudioNode", () => {
  it("renders the generating waveform state", () => {
    render(
      <AudioNode
        node={audioNode({
          audioState: "generating",
          audioProgress: 2,
        })}
        t={t}
      />,
    );

    const editor = screen.getByTestId("aigc-audio-editor");
    expect(editor).toHaveAttribute("data-audio-state", "generating");
    expect(editor).toHaveTextContent("生成中 2%...");
    expect(within(editor).getByLabelText("音频生成波形")).toBeInTheDocument();
  });

  it("renders generated audio controls and download status", async () => {
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    render(
      <AudioNode
        node={audioNode({
          audioState: "generated",
          audioDuration: 3,
          outputs: [
            {
              kind: "audio",
              name: "speech.wav",
              path: "/outputs/speech.wav",
              url: "blob:speech",
            },
          ],
        })}
        t={t}
      />,
    );

    const result = screen.getByTestId("aigc-audio-result");
    expect(result).toHaveTextContent("speech.wav");
    expect(result).toHaveTextContent("00:03 / 00:03");

    const toolbar = screen.getByTestId("aigc-audio-viewer-toolbar");
    expect(within(toolbar).getByRole("button", { name: "截取" })).toBeEnabled();
    expect(within(toolbar).getByRole("button", { name: "变速" })).toBeEnabled();
    fireEvent.click(within(toolbar).getByRole("button", { name: "下载音频" }));

    await waitFor(() => {
      expect(screen.getByText("已准备下载")).toBeInTheDocument();
    });
    expect(clickSpy).toHaveBeenCalled();
    clickSpy.mockRestore();
  });

  it("edits generated audio trim range", () => {
    const onUpdateNodeData = vi.fn();

    render(
      <AudioNode
        node={audioNode({
          audioState: "generated",
          audioDuration: 12,
          outputs: [{ kind: "audio", name: "speech.wav" }],
        })}
        t={t}
        onUpdateNodeData={onUpdateNodeData}
      />,
    );

    const toolbar = screen.getByTestId("aigc-audio-viewer-toolbar");
    fireEvent.click(within(toolbar).getByRole("button", { name: "截取" }));
    const panel = screen.getByTestId("aigc-audio-trim-panel");
    fireEvent.change(within(panel).getByLabelText("开始"), {
      target: { value: "1.2" },
    });
    fireEvent.change(within(panel).getByLabelText("结束"), {
      target: { value: "8.5" },
    });
    fireEvent.click(within(panel).getByRole("button", { name: "应用截取" }));

    expect(onUpdateNodeData).toHaveBeenCalledWith("audio-1", {
      audioActiveTool: "trim",
      audioTrimEnd: 8.5,
      audioTrimStart: 1.2,
    });
  });

  it("edits generated audio speed", () => {
    const onUpdateNodeData = vi.fn();

    render(
      <AudioNode
        node={audioNode({
          audioState: "generated",
          audioDuration: 12,
          outputs: [{ kind: "audio", name: "speech.wav" }],
        })}
        t={t}
        onUpdateNodeData={onUpdateNodeData}
      />,
    );

    const toolbar = screen.getByTestId("aigc-audio-viewer-toolbar");
    fireEvent.click(within(toolbar).getByRole("button", { name: "变速" }));
    const panel = screen.getByTestId("aigc-audio-speed-panel");
    fireEvent.click(within(panel).getByRole("button", { name: "1.5x" }));

    expect(onUpdateNodeData).toHaveBeenCalledWith("audio-1", {
      audioActiveTool: "speed",
      audioSpeed: 1.5,
    });
  });
});
