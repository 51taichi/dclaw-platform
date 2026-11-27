import type {
  AigcCanvas,
  AigcCanvasEdge,
  AigcCanvasNode,
} from "../../api/modules/aigcStudio";
import {
  nodePrimaryOutputName,
  nodePrimaryOutputPreviewSource,
  nodeVisualWidth,
} from "./canvasNodeUtils";

type CreateImageAnnotationCanvasArgs = {
  canvas: AigcCanvas;
  sourceNode: AigcCanvasNode;
  annotationPreviewUrl: string;
  annotationPaths?: ImageAnnotationPath[];
  annotationViewBox?: ImageAnnotationViewBox;
  sourcePreviewUrl?: string;
  instruction?: string;
  now?: number;
};

export type ImageAnnotationPoint = {
  x: number;
  y: number;
};

export type ImageAnnotationPath = {
  id: string;
  points: ImageAnnotationPoint[];
};

export type ImageAnnotationViewBox = {
  width: number;
  height: number;
};

const DEFAULT_SOURCE_SIZE = { width: 16, height: 9 };
const VIEWBOX_WIDTH = 1000;

export const imageAnnotationPathD = (path: ImageAnnotationPath) =>
  path.points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`)
    .join(" ");

const nonEmptyString = (...values: unknown[]) =>
  values.map((value) => String(value ?? "").trim()).find(Boolean) ?? "";

const numberValue = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : null;

const firstOutput = (node: AigcCanvasNode) =>
  Array.isArray(node.data.outputs) ? node.data.outputs[0] : undefined;

const outputNumberValue = (node: AigcCanvasNode, key: string) => {
  const output = firstOutput(node);
  if (!output || typeof output !== "object") return null;
  return numberValue((output as Record<string, unknown>)[key]);
};

const parseAspectRatio = (value: unknown) => {
  if (typeof value !== "string") return null;
  const match = value.trim().match(/^(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)$/);
  if (!match) return null;
  const width = Number(match[1]);
  const height = Number(match[2]);
  if (!Number.isFinite(width) || !Number.isFinite(height)) return null;
  if (width <= 0 || height <= 0) return null;
  return { width, height };
};

const stripExtension = (name: string) => name.replace(/\.[^.]+$/, "");

const sourceImageName = (sourceNode: AigcCanvasNode) =>
  nonEmptyString(
    sourceNode.data.assetName,
    sourceNode.data.referenceAssetName,
    nodePrimaryOutputName(sourceNode),
    sourceNode.data.title,
    "图片",
  );

export const imageAnnotationSourcePreviewUrl = (sourceNode: AigcCanvasNode) =>
  nonEmptyString(
    sourceNode.data.assetPreviewUrl,
    sourceNode.data.referencePreviewUrl,
    nodePrimaryOutputPreviewSource(sourceNode),
  );

export const imageAnnotationSourceSize = (sourceNode: AigcCanvasNode) => {
  const storedWidth = numberValue(sourceNode.data.sourceImageWidth);
  const storedHeight = numberValue(sourceNode.data.sourceImageHeight);
  if (storedWidth && storedHeight) {
    return { width: storedWidth, height: storedHeight };
  }

  const outputWidth = outputNumberValue(sourceNode, "width");
  const outputHeight = outputNumberValue(sourceNode, "height");
  if (outputWidth && outputHeight) {
    return { width: outputWidth, height: outputHeight };
  }

  return (
    parseAspectRatio(sourceNode.data.annotationAspectRatio) ??
    parseAspectRatio(sourceNode.data.generatedAspectRatio) ??
    parseAspectRatio(sourceNode.data.aspectRatio) ??
    DEFAULT_SOURCE_SIZE
  );
};

export const imageAnnotationViewBoxForNode = (
  sourceNode: AigcCanvasNode,
): ImageAnnotationViewBox => {
  const storedWidth = numberValue(sourceNode.data.annotationViewBoxWidth);
  const storedHeight = numberValue(sourceNode.data.annotationViewBoxHeight);
  if (storedWidth && storedHeight) {
    return { width: Math.round(storedWidth), height: Math.round(storedHeight) };
  }

  const sourceSize = imageAnnotationSourceSize(sourceNode);
  const ratio = sourceSize.width / sourceSize.height;
  return {
    width: VIEWBOX_WIDTH,
    height: Math.max(1, Math.round(VIEWBOX_WIDTH / ratio)),
  };
};

const imageAnnotationEdge = (
  sourceNode: AigcCanvasNode,
  annotationNode: AigcCanvasNode,
): AigcCanvasEdge => ({
  id: `edge-${sourceNode.id}-${annotationNode.id}`,
  source: sourceNode.id,
  target: annotationNode.id,
  sourceHandle: "right",
  targetHandle: "left",
  data: { role: "image_annotation" },
});

export function createImageAnnotationCanvas({
  canvas,
  sourceNode,
  annotationPreviewUrl,
  annotationPaths = [],
  annotationViewBox,
  sourcePreviewUrl,
  instruction,
  now = Date.now(),
}: CreateImageAnnotationCanvasArgs) {
  const seed = `${now.toString(36)}-${canvas.nodes.length + 1}`;
  const baseName = stripExtension(sourceImageName(sourceNode));
  const cleanSourcePreviewUrl =
    sourcePreviewUrl || imageAnnotationSourcePreviewUrl(sourceNode);
  const sourceSize = imageAnnotationSourceSize(sourceNode);
  const viewBox = annotationViewBox ?? imageAnnotationViewBoxForNode(sourceNode);
  const annotationNode: AigcCanvasNode = {
    id: `image-annotation-${seed}`,
    type: "reference_asset",
    position: {
      x: sourceNode.position.x + nodeVisualWidth(sourceNode) + 150,
      y: sourceNode.position.y,
    },
    data: {
      title: "标注",
      text: "",
      previewKind: "uploaded_source",
      assetRole: "image_annotation",
      assetKind: "image",
      assetName: `${baseName}-标注.svg`,
      assetMimeType: "image/svg+xml",
      assetPreviewUrl: cleanSourcePreviewUrl || annotationPreviewUrl,
      annotationPreviewUrl,
      annotatedPreviewUrl: annotationPreviewUrl,
      annotationPaths,
      annotationViewBoxWidth: viewBox.width,
      annotationViewBoxHeight: viewBox.height,
      annotationSourcePreviewUrl: cleanSourcePreviewUrl,
      sourcePreviewUrl: cleanSourcePreviewUrl,
      referencePreviewUrl: cleanSourcePreviewUrl,
      sourceImageNodeId: sourceNode.id,
      sourceImageName: sourceImageName(sourceNode),
      sourceImageWidth: sourceSize.width,
      sourceImageHeight: sourceSize.height,
      annotationAspectRatio: `${sourceSize.width}:${sourceSize.height}`,
      annotationInstruction: instruction,
      annotationMode: "region_edit",
      imageEditScope: "annotated_region",
      participatesInGeneration: true,
      isAnnotation: true,
      savedToAssets: false,
      createdAt: now,
    },
  };

  return {
    annotationNode,
    canvas: {
      ...canvas,
      nodes: [...canvas.nodes, annotationNode],
      edges: [...canvas.edges, imageAnnotationEdge(sourceNode, annotationNode)],
    },
  };
}
