import { describe, expect, it, vi } from "vitest";

import {
  AIGC_REFERENCE_ASSET_MIME,
  insertReferenceAlias,
  readReferenceAssetDragData,
  writeReferenceAssetDragData,
} from "./referenceAssetDrag";

const createDataTransfer = () => {
  const data = new Map<string, string>();
  return {
    effectAllowed: "none",
    setData: vi.fn((type: string, value: string) => data.set(type, value)),
    getData: vi.fn((type: string) => data.get(type) ?? ""),
  } as unknown as DataTransfer;
};

describe("referenceAssetDrag", () => {
  it("round-trips the reference binding through drag data", () => {
    const dataTransfer = createDataTransfer();
    const asset = {
      id: "prompt-1",
      alias: "文本1",
      name: "文案",
      previewUrl: "",
      sourceNodeId: "prompt-1",
      kind: "text" as const,
      text: "参考文案",
    };

    writeReferenceAssetDragData(dataTransfer, asset);

    expect(dataTransfer.effectAllowed).toBe("copy");
    expect(dataTransfer.setData).toHaveBeenCalledWith(
      AIGC_REFERENCE_ASSET_MIME,
      JSON.stringify(asset),
    );
    expect(dataTransfer.setData).toHaveBeenCalledWith("text/plain", "@文本1 ");
    expect(readReferenceAssetDragData(dataTransfer)).toEqual(asset);
  });

  it("inserts an @ alias at the selection with readable spacing", () => {
    expect(insertReferenceAlias("生成海报", "文本1", 4)).toEqual({
      value: "生成海报 @文本1 ",
      cursor: 10,
    });
    expect(insertReferenceAlias("镜头推进", "图片1", 0)).toEqual({
      value: "@图片1 镜头推进",
      cursor: 5,
    });
  });
});
