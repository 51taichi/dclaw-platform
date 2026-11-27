import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const cssBlockFor = (css: string, className: string) => {
  const escapedClassName = className.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(
    `(?:^|\\n)[^{]*\\.${escapedClassName}(?![-_a-zA-Z0-9])[^{]*\\{([\\s\\S]*?)\\n\\}`,
    "m",
  ).exec(css);
  if (!match) {
    throw new Error(`Missing .${className} style block`);
  }
  return match[1];
};

const zIndexFor = (css: string, className: string) => {
  const block = cssBlockFor(css, className);
  const match = /\bz-index:\s*(-?\d+)\s*;/.exec(block);
  if (!match) {
    throw new Error(`Missing z-index for .${className}`);
  }
  return Number(match[1]);
};

describe("AIGC canvas layering styles", () => {
  it("keeps every node-side plus handle below node-local composers and popups", async () => {
    const css = await readFile(
      resolve(process.cwd(), "src/pages/AigcStudio/index.module.less"),
      "utf8",
    );
    const nodeLocalLayerClasses = [
      "nodeComposer",
      "imageComposer",
      "videoComposer",
      "audioComposer",
      "textComposer",
      "scriptComposer",
      "storyboardComposer",
      "imageModelMenu",
      "videoModelMenu",
      "imageSizeMenu",
      "videoSettingsMenu",
      "cameraPanel",
      "advancedPanel",
      "countMenu",
      "textModelMenu",
      "audioVoicePanel",
      "shotImageEditor",
      "paramTooltip",
      "effectLibrary",
      "motionLibrary",
      "characterLibrary",
    ];

    ["nodeHandleLeft", "nodeHandleRight"].forEach((handleClassName) => {
      const handleZIndex = zIndexFor(css, handleClassName);
      nodeLocalLayerClasses.forEach((layerClassName) => {
        expect(
          handleZIndex,
          `.${handleClassName} must stay below .${layerClassName}`,
        ).toBeLessThan(zIndexFor(css, layerClassName));
      });
    });
  });
});
