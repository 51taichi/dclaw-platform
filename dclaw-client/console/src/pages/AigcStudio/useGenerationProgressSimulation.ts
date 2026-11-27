import { useEffect, useRef, useState } from "react";

import {
  estimatedImageGenerationMs,
  simulatedImageGenerationProgress,
} from "./generationProgress";

type GenerationProgressTimer = number;

type GenerationProgressModel = {
  provider_id?: string | null;
  model_id?: string | null;
};

type StartGenerationProgressSimulationInput = {
  nodeId: string;
  model: GenerationProgressModel;
  parameters: Record<string, unknown>;
  initialProgress?: number;
};

export function useGenerationProgressSimulation() {
  const [progressOverrides, setProgressOverrides] = useState<
    Record<string, number>
  >({});
  const progressTimersRef = useRef<Map<string, GenerationProgressTimer>>(
    new Map(),
  );

  const clearProgressSimulation = (nodeId: string) => {
    const timer = progressTimersRef.current.get(nodeId);
    if (timer) {
      if (typeof window !== "undefined") {
        window.clearInterval(timer);
      }
      progressTimersRef.current.delete(nodeId);
    }
    setProgressOverrides((prev) => {
      if (!(nodeId in prev)) return prev;
      const next = { ...prev };
      delete next[nodeId];
      return next;
    });
  };

  const startProgressSimulation = ({
    nodeId,
    model,
    parameters,
    initialProgress = 2,
  }: StartGenerationProgressSimulationInput) => {
    clearProgressSimulation(nodeId);
    if (typeof window === "undefined") return;

    const estimatedMs = estimatedImageGenerationMs({
      providerId: model.provider_id,
      modelId: model.model_id,
      parameters,
    });
    const startedAt = Date.now();
    const tick = () => {
      const progress = simulatedImageGenerationProgress(
        Date.now() - startedAt,
        estimatedMs,
      );
      setProgressOverrides((prev) =>
        prev[nodeId] === progress ? prev : { ...prev, [nodeId]: progress },
      );
    };

    setProgressOverrides((prev) => ({ ...prev, [nodeId]: initialProgress }));
    const timer = window.setInterval(tick, 750);
    progressTimersRef.current.set(nodeId, timer);
  };

  useEffect(
    () => () => {
      progressTimersRef.current.forEach((timer) => {
        if (typeof window !== "undefined") {
          window.clearInterval(timer);
        }
      });
      progressTimersRef.current.clear();
    },
    [],
  );

  return {
    clearProgressSimulation,
    progressOverrides,
    startProgressSimulation,
  };
}
