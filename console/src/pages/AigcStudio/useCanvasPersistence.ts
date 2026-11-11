import { useCallback, useEffect, useRef, useState } from "react";

import {
  aigcStudioApi,
  type AigcCanvas,
  type AigcCapabilityDefaultsByCategory,
  type AigcCapabilityInfo,
  type AigcJob,
} from "../../api/modules/aigcStudio";
import {
  canvasPayload,
  canvasSignature,
  localizeLegacyCanvas,
} from "./canvasAssetFactory";
import { reconcileCanvasConnectionData } from "./canvasConnectionActions";
import type { Translate } from "./canvasNodeUtils";

export type AutoSaveStatus = "saved" | "dirty" | "saving" | "error";

type UseCanvasPersistenceOptions = {
  t: Translate;
  onViewportScaleChange: (scale: number) => void;
  autoLoad?: boolean;
  autoSaveDelay?: number;
};

export function useCanvasPersistence({
  t,
  onViewportScaleChange,
  autoLoad = true,
  autoSaveDelay = 900,
}: UseCanvasPersistenceOptions) {
  const autoSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const saveInFlightRef = useRef(false);
  const savePromiseRef = useRef<Promise<void> | null>(null);
  const pendingSaveCanvasRef = useRef<AigcCanvas | null>(null);
  const savedCanvasSignatureRef = useRef<string | null>(null);
  const [capabilities, setCapabilities] = useState<AigcCapabilityInfo[]>([]);
  const [capabilityDefaults, setCapabilityDefaults] =
    useState<AigcCapabilityDefaultsByCategory>({});
  const [canvases, setCanvases] = useState<AigcCanvas[]>([]);
  const [activeCanvas, setActiveCanvas] = useState<AigcCanvas | null>(null);
  const [jobs, setJobs] = useState<AigcJob[]>([]);
  const [autoSaveStatus, setAutoSaveStatus] = useState<AutoSaveStatus>("saved");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const refreshCapabilities = useCallback(async () => {
    const result = await aigcStudioApi.listCapabilities();
    setCapabilities(result.capabilities);
    setCapabilityDefaults(result.defaults ?? {});
    return result.capabilities;
  }, []);

  const persistCanvas = useCallback((canvas: AigcCanvas): Promise<void> => {
    pendingSaveCanvasRef.current = canvas;
    if (saveInFlightRef.current) {
      setAutoSaveStatus("dirty");
      return savePromiseRef.current ?? Promise.resolve();
    }

    saveInFlightRef.current = true;
    const savePromise = (async () => {
      setSaving(true);
      try {
        while (pendingSaveCanvasRef.current) {
          const nextCanvas = pendingSaveCanvasRef.current;
          pendingSaveCanvasRef.current = null;
          const signature = canvasSignature(nextCanvas);
          if (signature === savedCanvasSignatureRef.current) {
            continue;
          }

          setAutoSaveStatus("saving");
          await aigcStudioApi.saveCanvas(
            nextCanvas.id,
            canvasPayload(nextCanvas),
          );
          savedCanvasSignatureRef.current = signature;
          setCanvases((prev) =>
            prev.map((item) => (item.id === nextCanvas.id ? nextCanvas : item)),
          );
        }
        setAutoSaveStatus("saved");
      } catch (error) {
        console.error("Failed to save AIGC canvas", error);
        setAutoSaveStatus("error");
      } finally {
        saveInFlightRef.current = false;
        savePromiseRef.current = null;
        setSaving(false);
      }
    })();
    savePromiseRef.current = savePromise;
    return savePromise;
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [, canvasRes] = await Promise.all([
        refreshCapabilities(),
        aigcStudioApi.listCanvases(),
      ]);

      const localizedCanvases = canvasRes.canvases.map(
        (canvas) =>
          reconcileCanvasConnectionData({
            canvas: localizeLegacyCanvas(t, canvas),
            t,
          }).canvas,
      );

      if (localizedCanvases.length > 0) {
        setCanvases(localizedCanvases);
        setActiveCanvas(localizedCanvases[0]);
        onViewportScaleChange(localizedCanvases[0].viewport.zoom || 1);
        savedCanvasSignatureRef.current = canvasSignature(localizedCanvases[0]);
        setAutoSaveStatus("saved");
        const jobRes = await aigcStudioApi.listJobs(localizedCanvases[0].id);
        setJobs(jobRes.jobs);
      } else {
        setCanvases([]);
        setActiveCanvas(null);
        setJobs([]);
        savedCanvasSignatureRef.current = null;
        setAutoSaveStatus("saved");
      }
    } finally {
      setLoading(false);
    }
  }, [onViewportScaleChange, refreshCapabilities, t]);

  const activateCanvasById = useCallback(
    async (canvasId: string) => {
      const requestedId = canvasId.trim();
      if (!requestedId) throw new Error("AIGC canvas id is required");
      let canvas = canvases.find((item) => item.id === requestedId) ?? null;
      if (!canvas) {
        const loaded = await aigcStudioApi.getCanvas(requestedId);
        canvas = reconcileCanvasConnectionData({
          canvas: localizeLegacyCanvas(t, loaded),
          t,
        }).canvas;
        setCanvases((current) => [
          ...current.filter((item) => item.id !== requestedId),
          canvas as AigcCanvas,
        ]);
      }
      savedCanvasSignatureRef.current = canvasSignature(canvas);
      setActiveCanvas(canvas);
      onViewportScaleChange(canvas.viewport.zoom || 1);
      setAutoSaveStatus("saved");
      const jobRes = await aigcStudioApi.listJobs(canvas.id);
      setJobs(jobRes.jobs);
      return canvas;
    },
    [canvases, onViewportScaleChange, t],
  );

  useEffect(() => {
    if (!autoLoad) return;
    void load();
  }, [autoLoad, load]);

  useEffect(() => {
    if (loading || !activeCanvas) return;

    const signature = canvasSignature(activeCanvas);
    if (signature === savedCanvasSignatureRef.current) {
      setAutoSaveStatus("saved");
      return;
    }

    setAutoSaveStatus("dirty");
    if (autoSaveTimerRef.current) {
      clearTimeout(autoSaveTimerRef.current);
    }
    autoSaveTimerRef.current = setTimeout(() => {
      autoSaveTimerRef.current = null;
      void persistCanvas(activeCanvas);
    }, autoSaveDelay);

    return () => {
      if (autoSaveTimerRef.current) {
        clearTimeout(autoSaveTimerRef.current);
      }
    };
  }, [activeCanvas, autoSaveDelay, loading, persistCanvas]);

  return {
    autoSaveTimerRef,
    savedCanvasSignatureRef,
    capabilities,
    setCapabilities,
    refreshCapabilities,
    capabilityDefaults,
    setCapabilityDefaults,
    canvases,
    setCanvases,
    activeCanvas,
    setActiveCanvas,
    jobs,
    setJobs,
    autoSaveStatus,
    setAutoSaveStatus,
    loading,
    setLoading,
    saving,
    setSaving,
    persistCanvas,
    activateCanvasById,
    load,
  };
}
