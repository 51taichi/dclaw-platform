import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import { AudioComposer } from "./AudioComposer";

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

const audioModel: AigcCapabilityInfo = {
  provider_id: "minimax",
  provider_name: "MiniMax",
  model_id: "speech-2.8",
  model_name: "Minimax-speech-2.8-hd",
  capability: "text_to_audio",
  source: "model_registry",
};

const audioNode = (data: AigcCanvasNode["data"] = {}): AigcCanvasNode => ({
  id: "audio-1",
  type: "audio_generate",
  position: { x: 360, y: 120 },
  data: {
    title: "音频节点 2",
    text: "",
    ...data,
  },
});

const renderComposer = (
  props: Partial<React.ComponentProps<typeof AudioComposer>> = {},
) => {
  const onUpdateNodeData = vi.fn();
  const onRunNode = vi.fn();
  const workflow = {
    handleAudioComposerSubmit: vi.fn(),
  };

  render(
    <AudioComposer
      node={audioNode({ composerText: "虽然不曾怀疑你" })}
      currentModel={audioModel}
      modelOptions={[audioModel]}
      t={t}
      workflow={workflow}
      disabled={false}
      onUpdateNodeData={onUpdateNodeData}
      onRunNode={onRunNode}
      {...props}
    />,
  );

  return { onRunNode, onUpdateNodeData, workflow };
};

describe("AudioComposer", () => {
  it("opens a fullscreen text editor from the composer and syncs edits back", () => {
    const { onUpdateNodeData } = renderComposer({
      node: audioNode({ composerText: "原始音频文本" }),
    });

    const composer = screen.getByTestId("aigc-audio-composer");
    fireEvent.click(
      within(composer).getByRole("button", { name: "全屏编辑输入" }),
    );

    const dialog = screen.getByRole("dialog", {
      name: "音频节点输入全屏编辑",
    });
    expect(document.body).toContainElement(dialog);
    expect(composer).not.toContainElement(dialog);

    const fullscreenInput = within(dialog).getByLabelText(
      "音频节点输入全屏编辑",
    );
    expect(fullscreenInput).toHaveValue("原始音频文本");

    fireEvent.change(fullscreenInput, {
      target: { value: "全屏里修改后的音频文本" },
    });

    expect(onUpdateNodeData).toHaveBeenLastCalledWith("audio-1", {
      composerText: "全屏里修改后的音频文本",
    });
    expect(screen.getByLabelText("音频节点输入")).toHaveValue(
      "全屏里修改后的音频文本",
    );
  });

  it("inserts a custom pause token", () => {
    const { onUpdateNodeData } = renderComposer();

    const composer = screen.getByTestId("aigc-audio-composer");
    fireEvent.click(within(composer).getByRole("button", { name: "停顿" }));
    fireEvent.click(within(composer).getByRole("button", { name: "自定义" }));

    const customPauseRow = screen.getByTestId("aigc-audio-custom-pause");
    fireEvent.change(within(customPauseRow).getByLabelText("自定义停顿秒数"), {
      target: { value: "2.25" },
    });
    fireEvent.click(
      within(customPauseRow).getByRole("button", { name: "插入停顿" }),
    );

    expect(onUpdateNodeData).toHaveBeenCalledWith("audio-1", {
      audioPauseTag: "<#2.25#>",
      composerText: "虽然不曾怀疑你 <#2.25#>",
    });
  });

  it("filters voice options by search and gender", () => {
    renderComposer();

    const composer = screen.getByTestId("aigc-audio-composer");
    fireEvent.click(within(composer).getByRole("button", { name: "选择音色" }));
    const voicePanel = screen.getByTestId("aigc-audio-voice-panel");

    fireEvent.change(within(voicePanel).getByLabelText("搜索音色库"), {
      target: { value: "青年" },
    });
    expect(voicePanel).toHaveTextContent("青涩青年音色");
    expect(voicePanel).not.toHaveTextContent("少女音色");

    fireEvent.click(within(voicePanel).getByRole("button", { name: "女声" }));
    expect(voicePanel).toHaveTextContent("没有匹配音色");
  });

  it("previews a voice without selecting it", () => {
    const { onUpdateNodeData } = renderComposer();

    const composer = screen.getByTestId("aigc-audio-composer");
    fireEvent.click(within(composer).getByRole("button", { name: "选择音色" }));
    const voicePanel = screen.getByTestId("aigc-audio-voice-panel");
    fireEvent.click(
      within(voicePanel).getByRole("button", { name: "试听 御姐音色" }),
    );

    expect(voicePanel).toHaveTextContent("正在试听 御姐音色");
    expect(onUpdateNodeData).not.toHaveBeenCalled();
  });

  it("updates tuning sliders and sound effects", () => {
    const { onUpdateNodeData } = renderComposer({
      node: audioNode({
        composerText: "虽然不曾怀疑你",
        soundEffect: "电话失真",
        speechRate: 1.12,
      }),
    });

    const composer = screen.getByTestId("aigc-audio-composer");
    fireEvent.click(
      within(composer).getByRole("button", { name: "音频参数调节" }),
    );
    const tuningPanel = screen.getByTestId("aigc-audio-tuning-panel");

    expect(
      within(tuningPanel).getByRole("button", { name: "电话失真" }),
    ).toHaveAttribute("aria-pressed", "true");

    fireEvent.change(within(tuningPanel).getByLabelText("语速"), {
      target: { value: "1.45" },
    });
    fireEvent.click(within(tuningPanel).getByRole("button", { name: "电音" }));

    expect(onUpdateNodeData).toHaveBeenCalledWith("audio-1", {
      speechRate: 1.45,
    });
    expect(onUpdateNodeData).toHaveBeenCalledWith("audio-1", {
      soundEffect: "电音",
    });
    expect(
      screen.queryByTestId("aigc-audio-tuning-panel"),
    ).not.toBeInTheDocument();
  });

  it("closes an open audio menu when the composer input is clicked", () => {
    renderComposer();

    const composer = screen.getByTestId("aigc-audio-composer");
    fireEvent.click(within(composer).getByRole("button", { name: "选择音色" }));
    expect(screen.getByTestId("aigc-audio-voice-panel")).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByLabelText("音频节点输入"));

    expect(
      screen.queryByTestId("aigc-audio-voice-panel"),
    ).not.toBeInTheDocument();
  });

  it("resets tuning values", () => {
    const { onUpdateNodeData } = renderComposer({
      node: audioNode({
        composerText: "虽然不曾怀疑你",
        soundEffect: "电话失真",
        speechPitch: 2,
        speechRate: 1.45,
        speechStrength: -1,
        speechTimbre: 0.4,
        speechTone: 1,
        speechVolume: 0.85,
      }),
    });

    const composer = screen.getByTestId("aigc-audio-composer");
    fireEvent.click(
      within(composer).getByRole("button", { name: "音频参数调节" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "一键重置" }));

    expect(onUpdateNodeData).toHaveBeenCalledWith("audio-1", {
      soundEffect: "无",
      speechPitch: 0,
      speechRate: 1,
      speechStrength: 0,
      speechTimbre: 0,
      speechTone: 0,
      speechVolume: 1,
    });
  });
});
