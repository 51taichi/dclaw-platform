import type {
  AigcAsset,
  AigcCanvas,
  AigcCanvasNode,
} from "../../../../api/modules/aigcStudio";

export type LongImageTextSection = {
  id: string;
  kind: "text";
  title: string;
  text: string;
  sourceNodeId: string;
};

export type LongImageImageSection = {
  id: string;
  kind: "image";
  title: string;
  imageUrl: string;
  sourceNodeId: string;
};

export type LongImageSection = LongImageTextSection | LongImageImageSection;

export type LongImageSlice = {
  index: number;
  y: number;
  height: number;
};

const textValue = (value: unknown) =>
  typeof value === "string" ? value.trim() : "";

const paragraphsFromText = (value: unknown) => {
  const text = textValue(value).replace(/\r\n/g, "\n");
  if (!text) return [];
  const paragraphs = text.split(/\n\s*\n+/);
  const candidates = paragraphs.length > 1 ? paragraphs : text.split("\n");
  return candidates.map((item) => item.trim()).filter(Boolean);
};

const outputRecords = (node: AigcCanvasNode) =>
  Array.isArray(node.data.outputs)
    ? (node.data.outputs as Array<Partial<AigcAsset> & Record<string, unknown>>)
    : [];

const firstImageOutput = (node: AigcCanvasNode) =>
  outputRecords(node).find(
    (output) => textValue(output.kind || "image") === "image",
  );

const imageUrlFromOutput = (output: Partial<AigcAsset> | undefined) =>
  textValue(output?.url) || textValue(output?.path);

function upstreamNodes(canvas: AigcCanvas, target: AigcCanvasNode) {
  const nodesById = new Map(canvas.nodes.map((node) => [node.id, node]));
  return canvas.edges
    .filter((edge) => edge.target === target.id)
    .map((edge) => nodesById.get(edge.source))
    .filter((node): node is AigcCanvasNode => {
      if (!node) return false;
      return (
        node.type !== "reference_note" &&
        node.data.participatesInGeneration !== false
      );
    });
}

export function collectLongImageSections(
  canvas: AigcCanvas,
  target: AigcCanvasNode,
): LongImageSection[] {
  const sections: LongImageSection[] = [];
  upstreamNodes(canvas, target).forEach((node) => {
    const title = textValue(node.data.title) || node.type;
    if (node.type === "prompt") {
      sections.push(
        ...paragraphsFromText(node.data.text).map((paragraph, index) => ({
          id: `${node.id}-${index + 1}`,
          kind: "text" as const,
          title,
          text: paragraph,
          sourceNodeId: node.id,
        })),
      );
      return;
    }

    const output = firstImageOutput(node);
    const imageUrl = imageUrlFromOutput(output);
    if (imageUrl) {
      sections.push({
        id: `${node.id}-${textValue(output?.id) || "image"}`,
        kind: "image",
        title,
        imageUrl,
        sourceNodeId: node.id,
      });
      return;
    }

    sections.push(
      ...paragraphsFromText(node.data.text).map((paragraph, index) => ({
        id: `${node.id}-${index + 1}`,
        kind: "text" as const,
        title,
        text: paragraph,
        sourceNodeId: node.id,
      })),
    );
  });
  return sections;
}

export function calculateLongImageSlices({
  height,
  sliceHeight,
}: {
  height: number;
  sliceHeight: number;
}): LongImageSlice[] {
  const safeHeight = Math.max(0, Math.floor(height));
  const safeSliceHeight = Math.max(1, Math.floor(sliceHeight));
  const slices: LongImageSlice[] = [];
  for (let y = 0, index = 1; y < safeHeight; y += safeSliceHeight, index += 1) {
    slices.push({
      index,
      y,
      height: Math.min(safeSliceHeight, safeHeight - y),
    });
  }
  return slices;
}
