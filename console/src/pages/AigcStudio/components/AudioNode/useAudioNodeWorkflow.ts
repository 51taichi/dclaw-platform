import { useCallback } from "react";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import { modelForNode } from "../../nodeModelSelection";
import {
  DEFAULT_AUDIO_DURATION,
  DEFAULT_AUDIO_FORMAT,
  DEFAULT_AUDIO_MODEL_LABEL,
  DEFAULT_AUDIO_VOICE_ID,
  DEFAULT_AUDIO_VOICE_NAME,
} from "./audioNodeState";
import type { AudioNodeWorkflow } from "./types";

type UseAudioNodeWorkflowArgs = {
  updateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
  modelOptions?: AigcCapabilityInfo[];
};

export function useAudioNodeWorkflow({
  updateNodeData,
  modelOptions = [],
}: UseAudioNodeWorkflowArgs): AudioNodeWorkflow {
  const handleAudioComposerSubmit = useCallback(
    (node: AigcCanvasNode) => {
      const prompt = String(
        node.data.composerText ?? node.data.text ?? "",
      ).trim();
      const audioModel = modelForNode(modelOptions, node, "text_to_audio");
      const modelLabel =
        audioModel?.model_name ??
        audioModel?.model_id ??
        String(
          node.data.modelLabel ?? node.data.title ?? DEFAULT_AUDIO_MODEL_LABEL,
        );

      const nextData = {
        text: prompt || node.data.text || "",
        lastRunPrompt: prompt,
        modelLabel,
        providerId: audioModel?.provider_id,
        modelId: audioModel?.model_id,
        modelCapability: audioModel?.capability,
        audioDuration: node.data.audioDuration ?? DEFAULT_AUDIO_DURATION,
        audioFormat: node.data.audioFormat ?? DEFAULT_AUDIO_FORMAT,
        audioPauseTag: node.data.audioPauseTag,
        audioFillerTag: node.data.audioFillerTag,
        audioVoiceId: node.data.audioVoiceId ?? DEFAULT_AUDIO_VOICE_ID,
        audioVoiceName: node.data.audioVoiceName ?? DEFAULT_AUDIO_VOICE_NAME,
        speechRate: node.data.speechRate ?? 1,
        speechPitch: node.data.speechPitch ?? 0,
        speechVolume: node.data.speechVolume ?? 1,
        speechTone: node.data.speechTone ?? 0,
        speechStrength: node.data.speechStrength ?? 0,
        speechTimbre: node.data.speechTimbre ?? 0,
        soundEffect: node.data.soundEffect ?? "无",
      };
      updateNodeData(node.id, nextData);
      return {
        ...node,
        data: {
          ...node.data,
          ...nextData,
        },
      };
    },
    [modelOptions, updateNodeData],
  );

  return { handleAudioComposerSubmit };
}
