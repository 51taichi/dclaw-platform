import { aigcStudioApi, type AigcCanvas } from "../../api/modules/aigcStudio";
import { canvasSignature, localizeLegacyCanvas } from "./canvasAssetFactory";
import { emptyCanvasPayload } from "./canvasTemplateFactory";
import type { Translate } from "./canvasNodeUtils";

type PersistCanvas = (canvas: AigcCanvas) => Promise<void>;

function shouldPersistCanvas(
  canvas: AigcCanvas | null,
  savedCanvasSignature: string | null,
) {
  return Boolean(canvas && canvasSignature(canvas) !== savedCanvasSignature);
}

export async function createCanvasProject({
  t,
  activeCanvas,
  savedCanvasSignature,
  persistCanvas,
}: {
  t: Translate;
  activeCanvas: AigcCanvas | null;
  savedCanvasSignature: string | null;
  persistCanvas: PersistCanvas;
}) {
  if (shouldPersistCanvas(activeCanvas, savedCanvasSignature) && activeCanvas) {
    await persistCanvas(activeCanvas);
  }

  const created = await aigcStudioApi.createCanvas(
    emptyCanvasPayload(t("aigcStudio.defaultName", "未命名 AIGC 画布")),
  );
  const canvas = localizeLegacyCanvas(t, created);
  return {
    canvas,
    signature: canvasSignature(canvas),
  };
}

export async function selectCanvasProject({
  activeCanvas,
  targetCanvas,
  savedCanvasSignature,
  persistCanvas,
}: {
  activeCanvas: AigcCanvas | null;
  targetCanvas: AigcCanvas;
  savedCanvasSignature: string | null;
  persistCanvas: PersistCanvas;
}) {
  if (shouldPersistCanvas(activeCanvas, savedCanvasSignature) && activeCanvas) {
    await persistCanvas(activeCanvas);
  }

  const jobRes = await aigcStudioApi.listJobs(targetCanvas.id);
  return {
    canvas: targetCanvas,
    signature: canvasSignature(targetCanvas),
    jobs: jobRes.jobs,
  };
}

export async function deleteCanvasProject({
  canvas,
  activeCanvas,
  canvases,
}: {
  canvas: AigcCanvas;
  activeCanvas: AigcCanvas | null;
  canvases: AigcCanvas[];
}) {
  await aigcStudioApi.deleteCanvas(canvas.id);

  const remainingCanvases = canvases.filter((item) => item.id !== canvas.id);
  const nextCanvas =
    activeCanvas?.id === canvas.id
      ? remainingCanvases[0] ?? null
      : activeCanvas;

  return {
    remainingCanvases,
    nextCanvas,
    nextSignature: nextCanvas ? canvasSignature(nextCanvas) : null,
  };
}
