import { describe, expect, it } from "vitest";

import {
  cleanArtifactMessageText,
  extractArtifactPaths,
  filterVisibleArtifacts,
  messageImagePaths,
  mergeMessageArtifacts,
  normalizeMobileImageReference,
  shouldRecoverMissingArtifacts,
} from "./artifactTrigger";

const encodedFiles =
  "WyJcdTRlYTdcdTU0YzFcdTRlZjdcdTY4M2NcdTg4NjgueGxzeCJd";
const trigger = `[qwenpaw-artifact-card-trigger](http://qwenpaw.local/?data=${encodedFiles})`;

describe("artifact trigger compatibility", () => {
  it("decodes the web artifact trigger and removes it from mobile text", () => {
    const text = `文件已发送，请查收！\n\n🎯 **本次任务产生的制品和文件变更如下**：\n\n${trigger}`;

    expect(extractArtifactPaths(text)).toEqual(["产品价格表.xlsx"]);
    expect(cleanArtifactMessageText(text)).toBe("文件已发送，请查收！");
  });

  it("merges trigger-declared files while the artifact endpoint catches up", () => {
    expect(
      mergeMessageArtifacts(
        [{ role: "assistant", content: trigger }],
        [],
      ),
    ).toEqual([
      {
        name: "产品价格表.xlsx",
        path: "产品价格表.xlsx",
        kind: "document",
      },
    ]);
  });

  it("polls only for a bounded recovery window when a trigger has no artifacts", () => {
    const messages = [{ role: "assistant", content: trigger }];

    expect(
      shouldRecoverMissingArtifacts({
        messages,
        artifactCount: 0,
        recoveryPolls: 0,
      }),
    ).toBe(true);
    expect(
      shouldRecoverMissingArtifacts({
        messages,
        artifactCount: 1,
        recoveryPolls: 0,
      }),
    ).toBe(false);
    expect(
      shouldRecoverMissingArtifacts({
        messages,
        artifactCount: 0,
        recoveryPolls: 5,
      }),
    ).toBe(false);
  });

  it("extracts conversation images from rich content and markdown", () => {
    expect(
      messageImagePaths({
        role: "assistant",
        content: [
          { type: "text", text: "图片如下：![封面](artifacts/封面.png)" },
          { type: "image", path: "artifacts/详情图.webp" },
          {
            type: "image_url",
            image_url: { url: "https://example.com/remote.jpg" },
          },
        ],
      }),
    ).toEqual([
      "artifacts/封面.png",
      "artifacts/详情图.webp",
      "https://example.com/remote.jpg",
    ]);
  });

  it("treats image artifacts in delivery triggers as conversation images", () => {
    const imageTrigger =
      "[qwenpaw-artifact-card-trigger](http://qwenpaw.local/?data=WyJhcnRpZmFjdHMvXHU2NTQ4XHU2NzljXHU1NmZlLnBuZyJd)";

    expect(
      messageImagePaths({ role: "assistant", content: imageTrigger }),
    ).toEqual(["artifacts/效果图.png"]);
    expect(cleanArtifactMessageText(`图片已生成\n\n${imageTrigger}`)).toBe(
      "图片已生成",
    );
  });

  it("normalizes imagegen file URLs to session-relative artifact paths", () => {
    const absoluteImage =
      "file:///srv/qwenpaw/sessions_data/session-1/media/imagegen/imagegen_1.png";

    expect(normalizeMobileImageReference(absoluteImage)).toBe(
      "media/imagegen/imagegen_1.png",
    );
    expect(
      messageImagePaths({
        role: "assistant",
        content: [
          { type: "image", image_url: absoluteImage },
          {
            type: "text",
            text: "![生成图](media/imagegen/imagegen_1.png)",
          },
        ],
      }),
    ).toEqual(["media/imagegen/imagegen_1.png"]);
  });

  it("hides imagegen manifests from current and historical artifact lists", () => {
    expect(
      filterVisibleArtifacts([
        {
          name: "imagegen_1.imagegen.json",
          path: "media/imagegen/imagegen_1.imagegen.json",
          kind: "code",
        },
        {
          name: "imagegen_1.png",
          path: "media/imagegen/imagegen_1.png",
          kind: "image",
        },
      ]),
    ).toEqual([
      {
        name: "imagegen_1.png",
        path: "media/imagegen/imagegen_1.png",
        kind: "image",
      },
    ]);
  });
});
