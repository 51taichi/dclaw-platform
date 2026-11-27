import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import { useAudioNodeWorkflow } from "./useAudioNodeWorkflow";

const audioNode: AigcCanvasNode = {
  id: "audio-1",
  type: "audio_generate",
  position: { x: 420, y: 220 },
  data: {
    title: "音频生成",
    composerText: "生成一段高级未来感品牌音乐",
  },
};

const selectedAudioModel: AigcCapabilityInfo = {
  provider_id: "minimax",
  provider_name: "MiniMax",
  model_id: "music-01",
  model_name: "Music 01",
  capability: "text_to_audio",
  source: "model_registry",
};

const selectedImageModel: AigcCapabilityInfo = {
  provider_id: "openai",
  provider_name: "OpenAI",
  model_id: "gpt-image-2",
  model_name: "GPT Image 2",
  capability: "text_to_image",
  source: "model_registry",
};

describe("useAudioNodeWorkflow", () => {
  it("submits composer text with selected audio model metadata", () => {
    const updateNodeData = vi.fn();

    const { result } = renderHook(() =>
      useAudioNodeWorkflow({
        updateNodeData,
        modelOptions: [selectedAudioModel],
      }),
    );

    act(() => {
      result.current.handleAudioComposerSubmit(audioNode);
    });

    expect(updateNodeData).toHaveBeenCalledWith(
      "audio-1",
      expect.objectContaining({
        audioDuration: 30,
        audioFormat: "wav",
        lastRunPrompt: "生成一段高级未来感品牌音乐",
        modelId: "music-01",
        modelLabel: "Music 01",
        providerId: "minimax",
        text: "生成一段高级未来感品牌音乐",
      }),
    );
  });

  it("does not write image model metadata into an audio node", () => {
    const updateNodeData = vi.fn();

    const { result } = renderHook(() =>
      useAudioNodeWorkflow({
        updateNodeData,
        modelOptions: [selectedImageModel],
      }),
    );

    act(() => {
      result.current.handleAudioComposerSubmit(audioNode);
    });

    expect(updateNodeData).toHaveBeenCalledWith(
      "audio-1",
      expect.objectContaining({
        modelId: undefined,
        modelLabel: "音频生成",
        providerId: undefined,
      }),
    );
  });

  it("submits speech controls with composer text", () => {
    const updateNodeData = vi.fn();
    const tunedAudioNode: AigcCanvasNode = {
      ...audioNode,
      data: {
        ...audioNode.data,
        audioPauseTag: "<#0.25#>",
        audioFillerTag: "(笑声)",
        audioVoiceId: "girl",
        audioVoiceName: "少女音色",
        speechRate: 1.12,
        speechPitch: 2,
        speechVolume: 0.85,
        speechTone: 1,
        speechStrength: -1,
        speechTimbre: 0.4,
        soundEffect: "电话失真",
      },
    };

    const { result } = renderHook(() =>
      useAudioNodeWorkflow({
        updateNodeData,
        modelOptions: [selectedAudioModel],
      }),
    );

    act(() => {
      result.current.handleAudioComposerSubmit(tunedAudioNode);
    });

    expect(updateNodeData).toHaveBeenCalledWith(
      "audio-1",
      expect.objectContaining({
        audioFillerTag: "(笑声)",
        audioPauseTag: "<#0.25#>",
        audioVoiceId: "girl",
        audioVoiceName: "少女音色",
        soundEffect: "电话失真",
        speechPitch: 2,
        speechRate: 1.12,
        speechStrength: -1,
        speechTimbre: 0.4,
        speechTone: 1,
        speechVolume: 0.85,
        text: "生成一段高级未来感品牌音乐",
      }),
    );
  });
});
