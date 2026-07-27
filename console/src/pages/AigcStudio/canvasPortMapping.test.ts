import { describe, expect, it } from "vitest";

import type { AigcCanvasNode } from "../../api/modules/aigcStudio";
import {
  downstreamDataFromSource,
  edgeRoleForSource,
  nodeDataForContextTarget,
} from "./canvasPortMapping";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

const nodeFixture = (
  type: string,
  data: Record<string, unknown> = {},
): AigcCanvasNode => ({
  id: `${type}-1`,
  type,
  position: { x: 80, y: 90 },
  data,
});

describe("canvasPortMapping", () => {
  it("creates context-node data for left-port additions", () => {
    expect(nodeDataForContextTarget(t, "prompt")).toEqual({
      text: "为当前节点补充提示词、镜头、风格或角色设定。",
      showTryOptions: false,
    });

    expect(nodeDataForContextTarget(t, "reference_note")).toEqual({
      title: "参考节点",
      text: "",
      placeholder: "双击输入参考说明（不参与生成）",
      participatesInGeneration: false,
      showTryOptions: false,
    });

    expect(nodeDataForContextTarget(t, "image_generate")).toEqual({
      showTryOptions: false,
      inputUpdated: true,
    });
  });

  it("maps source nodes to edge roles", () => {
    expect(edgeRoleForSource(nodeFixture("prompt"))).toBe("prompt");
    expect(edgeRoleForSource(nodeFixture("reference_note"))).toBe(
      "reference_note",
    );
    expect(
      edgeRoleForSource(nodeFixture("reference_asset", { assetKind: "audio" })),
    ).toBe("audio");
    expect(edgeRoleForSource(nodeFixture("video_generate"))).toBe(
      "reference_video",
    );
    expect(edgeRoleForSource(nodeFixture("reference_asset"))).toBe(
      "reference_image",
    );
    expect(
      edgeRoleForSource(
        nodeFixture("reference_asset", { assetRole: "style_template" }),
      ),
    ).toBe("style_template");
    expect(
      edgeRoleForSource(
        nodeFixture("reference_asset", {
          assetRole: "image_annotation",
          assetKind: "image",
        }),
      ),
    ).toBe("image_annotation");
    expect(
      edgeRoleForSource(
        nodeFixture("image_generate", {
          imageState: "generated",
          styleTemplateUuid: "dbc6dfc0990d46d28215bcdff87d53c3",
        }),
      ),
    ).toBe("reference_image");
  });

  it("maps source nodes to downstream target data", () => {
    expect(
      downstreamDataFromSource(
        t,
        nodeFixture("prompt", { text: " cinematic prompt " }),
        "image_generate",
      ),
    ).toEqual({
      showTryOptions: false,
      inputUpdated: true,
    });

    expect(
      downstreamDataFromSource(
        t,
        nodeFixture("reference_asset", {
          assetKind: "audio",
          assetName: "beat.wav",
          assetPreviewUrl: "audio-url",
        }),
        "video_generate",
      ),
    ).toMatchObject({
      activeVideoTab: "all_reference",
      videoMode: "reference",
      referenceAssetName: "beat.wav",
      referencePreviewUrl: "audio-url",
      composerPlaceholder: "根据音频节奏与描述生成视频。",
    });

    expect(
      downstreamDataFromSource(
        t,
        nodeFixture("reference_asset", {
          assetKind: "image",
          assetName: "first-frame.png",
          assetPreviewUrl: "first-frame-url",
        }),
        "video_generate",
      ),
    ).toMatchObject({
      activeVideoTab: "image_to_video",
      videoMode: "image_to_video",
      referenceAssetName: "first-frame.png",
      referencePreviewUrl: "first-frame-url",
      composerPlaceholder: "以当前图为首帧生成视频。",
    });

    expect(
      downstreamDataFromSource(
        t,
        nodeFixture("reference_asset", {
          assetKind: "image",
          assetName: "frame.png",
          assetPreviewUrl: "image-url",
        }),
        "image_generate",
      ),
    ).toMatchObject({
      imageMode: "image_to_image",
      referenceThumb: true,
      referenceAssetName: "frame.png",
      referencePreviewUrl: "image-url",
      composerPlaceholder: "描述你想要生成的画面内容，按 / 呼出指令，@引用素材",
    });

    expect(
      downstreamDataFromSource(
        t,
        nodeFixture("reference_asset", {
          title: "标注",
          assetRole: "image_annotation",
          assetKind: "image",
          assetName: "face-mark.png",
          assetPreviewUrl: "/marked-face.png",
          annotationSourcePreviewUrl: "/clean-face.png",
          annotationPreviewUrl: "/marked-face.png",
          annotationInstruction: "红圈是需要调整肤质的脸部区域",
        }),
        "image_generate",
      ),
    ).toMatchObject({
      imageMode: "image_to_image",
      imageEditScope: "annotated_region",
      annotationMode: "region_edit",
      referenceThumb: true,
      referenceAssetName: "face-mark.png",
      referencePreviewUrl: "/clean-face.png",
      annotationThumb: true,
      annotationAssetName: "face-mark.png",
      annotationPreviewUrl: "/marked-face.png",
      annotationSourcePreviewUrl: "/clean-face.png",
      annotationInstruction: "红圈是需要调整肤质的脸部区域",
      composerPlaceholder: "描述你想要生成的画面内容，按 / 呼出指令，@引用素材",
    });

    expect(
      downstreamDataFromSource(
        t,
        nodeFixture("reference_asset", {
          assetRole: "style_template",
          assetName: "一键国漫CGV2",
          assetPreviewUrl: "style-preview",
          styleTemplateUuid: "dbc6dfc0990d46d28215bcdff87d53c3",
          effectId: 22910748,
          styleKeywords: "国漫, CG, 银发角色",
          styleDescription: "国漫 CG 风格，冷色调金属质感。",
          styleSupplementalPrompt: "保留克制的金属高光。",
          visualDna: [
            { element_id: "lighting.cinematic_contrast", weight: 0.9 },
          ],
          styleReferenceImages: ["/style-reference.png"],
          aestheticProfileSnapshot: {
            id: "style-cgv2",
            version: "1.0",
          },
        }),
        "image_generate",
      ),
    ).toMatchObject({
      styleReferenceThumb: true,
      styleReferenceName: "一键国漫CGV2",
      styleReferencePreviewUrl: "style-preview",
      styleTemplateUuid: "dbc6dfc0990d46d28215bcdff87d53c3",
      effectTemplateUuids: ["dbc6dfc0990d46d28215bcdff87d53c3"],
      effectId: 22910748,
      effects: [22910748],
      styleKeywords: "国漫, CG, 银发角色",
      styleDescription: "国漫 CG 风格，冷色调金属质感。",
      styleSupplementalPrompt: "保留克制的金属高光。",
      visualDna: [{ element_id: "lighting.cinematic_contrast", weight: 0.9 }],
      styleReferenceImages: ["/style-reference.png"],
      aestheticProfileSnapshot: {
        id: "style-cgv2",
        version: "1.0",
      },
    });
  });
});
