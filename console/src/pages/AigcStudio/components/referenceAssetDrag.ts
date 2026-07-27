import type { ImageReferenceAsset } from "../canvasJobActions";

export const AIGC_REFERENCE_ASSET_MIME =
  "application/x-dclaw-aigc-reference+json";

export function writeReferenceAssetDragData(
  dataTransfer: DataTransfer,
  asset: ImageReferenceAsset,
) {
  dataTransfer.effectAllowed = "copy";
  dataTransfer.setData(AIGC_REFERENCE_ASSET_MIME, JSON.stringify(asset));
  dataTransfer.setData("text/plain", `@${asset.alias} `);
}

export function readReferenceAssetDragData(
  dataTransfer: DataTransfer,
): ImageReferenceAsset | null {
  const serialized = dataTransfer.getData(AIGC_REFERENCE_ASSET_MIME);
  if (!serialized) return null;

  try {
    const asset = JSON.parse(serialized) as Partial<ImageReferenceAsset>;
    if (
      typeof asset.id !== "string" ||
      typeof asset.alias !== "string" ||
      typeof asset.name !== "string" ||
      typeof asset.previewUrl !== "string"
    ) {
      return null;
    }
    return asset as ImageReferenceAsset;
  } catch {
    return null;
  }
}

export function insertReferenceAlias(
  text: string,
  alias: string,
  selectionStart: number,
  selectionEnd = selectionStart,
) {
  const safeStart = Math.max(0, Math.min(selectionStart, text.length));
  const safeEnd = Math.max(safeStart, Math.min(selectionEnd, text.length));
  const before = text.slice(0, safeStart);
  const after = text.slice(safeEnd);
  const normalizedAlias = alias.trim().replace(/^@+/, "");
  const leadingSpace = before && !/\s$/.test(before) ? " " : "";
  const trailingSpace = after && /^\s/.test(after) ? "" : " ";
  const mention = `${leadingSpace}@${normalizedAlias}${trailingSpace}`;

  return {
    value: `${before}${mention}${after}`,
    cursor: before.length + mention.length,
  };
}
