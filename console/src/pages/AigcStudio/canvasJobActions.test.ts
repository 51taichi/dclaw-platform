import { describe, expect, it } from "vitest";

import type {
  AigcCanvas,
  AigcCanvasNode,
  AigcCapabilityInfo,
  AigcJob,
} from "../../api/modules/aigcStudio";
import {
  applyFinishedJobToCanvas,
  buildRunNodeJobRequest,
  imageReferenceAssetsForNode,
  prependCanvasJob,
  replaceCanvasJob,
  videoConnectedInputsForNode,
} from "./canvasJobActions";

const model: AigcCapabilityInfo = {
  provider_id: "provider-1",
  provider_name: "Provider",
  model_id: "model-1",
  model_name: "Model",
  capability: "text_to_image",
  source: "model_registry",
};

const canvasFixture = (): AigcCanvas => ({
  id: "canvas-1",
  name: "Canvas",
  nodes: [
    {
      id: "prompt-1",
      type: "prompt",
      position: { x: 80, y: 90 },
      data: { title: "Prompt", text: "upstream prompt" },
    },
    {
      id: "image-1",
      type: "image_generate",
      position: { x: 360, y: 90 },
      data: {
        title: "Image",
        imageMode: "text_to_image",
        aspectRatio: "16:9",
        imageCount: 2,
      },
    },
  ],
  edges: [
    {
      id: "edge-prompt-image",
      source: "prompt-1",
      target: "image-1",
      sourceHandle: "right",
      targetHandle: "left",
    },
  ],
  viewport: { x: 0, y: 0, zoom: 1 },
  created_at: "2026-06-12T00:00:00Z",
  updated_at: "2026-06-12T00:00:00Z",
});

const jobFixture = (status: AigcJob["status"] = "succeeded"): AigcJob => ({
  id: "job-1",
  canvas_id: "canvas-1",
  node_id: "image-1",
  capability: "text_to_image",
  provider_id: "provider-1",
  model_id: "model-1",
  inputs: {},
  parameters: {},
  status,
  outputs: [
    {
      id: "asset-1",
      kind: "image",
      name: "image.png",
      path: "outputs/image.png",
      created_at: "2026-06-12T00:00:00Z",
    },
  ],
  logs: [],
  created_at: "2026-06-12T00:00:00Z",
  updated_at: "2026-06-12T00:00:00Z",
});

describe("canvasJobActions", () => {
  it("builds submit requests from node prompt, references, model, and parameters", () => {
    const canvas = canvasFixture();
    const node = canvas.nodes[1]!;

    expect(
      buildRunNodeJobRequest({
        canvas,
        selectedNode: node,
        selectedCapability: "text_to_image",
        selectedModel: model,
      }),
    ).toEqual({
      ok: true,
      request: {
        canvas_id: "canvas-1",
        node_id: "image-1",
        capability: "text_to_image",
        provider_id: "provider-1",
        model_id: "model-1",
        inputs: {
          prompt: "upstream prompt",
          node_type: "image_generate",
          reference_nodes: [
            {
              node_id: "prompt-1",
              type: "prompt",
              title: "Prompt",
              asset_name: undefined,
              preview_url: undefined,
            },
          ],
        },
        parameters: {
          aspectRatio: "16:9",
          imageCount: 2,
          imageMode: "text_to_image",
        },
      },
    });
  });

  it("exposes connected prompt nodes as text references without sending them as image references", () => {
    const canvas = canvasFixture();
    const node = canvas.nodes[1]!;

    expect(imageReferenceAssetsForNode(canvas, node)).toEqual([
      {
        id: "prompt-1",
        alias: "文本1",
        name: "Prompt",
        previewUrl: "",
        sourceNodeId: "prompt-1",
        kind: "text",
        text: "upstream prompt",
      },
    ]);

    const result = buildRunNodeJobRequest({
      canvas,
      selectedNode: node,
      selectedCapability: "text_to_image",
      selectedModel: model,
    });

    expect(result.ok && result.request.parameters).not.toHaveProperty(
      "referenceImages",
    );
  });

  it("replaces connected text reference aliases with text context in image prompts", () => {
    const canvas = canvasFixture();
    const node = {
      ...canvas.nodes[1]!,
      data: {
        ...canvas.nodes[1]!.data,
        text: "做一张背景图，把 @文本1 放进去",
      },
    };

    const result = buildRunNodeJobRequest({
      canvas: {
        ...canvas,
        nodes: [canvas.nodes[0]!, node],
      },
      selectedNode: node,
      selectedCapability: "text_to_image",
      selectedModel: model,
    });

    expect(result).toMatchObject({
      ok: true,
      request: {
        inputs: expect.objectContaining({
          prompt: "做一张背景图，把 第一段参考文本：upstream prompt 放进去",
        }),
      },
    });
    expect(result.ok && result.request.parameters).not.toHaveProperty(
      "referenceImages",
    );
  });

  it("resolves every repeated occurrence of the same @ reference alias", () => {
    const canvas = canvasFixture();
    const node = {
      ...canvas.nodes[1]!,
      data: {
        ...canvas.nodes[1]!.data,
        text: "先按 @文本1 生成标题，再按 @文本1 生成正文",
      },
    };

    const result = buildRunNodeJobRequest({
      canvas: {
        ...canvas,
        nodes: [canvas.nodes[0]!, node],
      },
      selectedNode: node,
      selectedCapability: "text_to_image",
      selectedModel: model,
    });

    expect(result).toMatchObject({
      ok: true,
      request: {
        inputs: expect.objectContaining({
          prompt:
            "先按 第一段参考文本：upstream prompt 生成标题，再按 第一段参考文本：upstream prompt 生成正文",
        }),
      },
    });
  });

  it("uses the selected model capability for image job submission", () => {
    const canvas = canvasFixture();
    const node = {
      ...canvas.nodes[1]!,
      data: {
        ...canvas.nodes[1]!.data,
        imageMode: "image_to_image",
        referenceAssetName: "reference.png",
        referencePreviewUrl: "/reference.png",
      },
    };
    const imageEditModel: AigcCapabilityInfo = {
      ...model,
      capability: "image_to_image",
    };

    const result = buildRunNodeJobRequest({
      canvas: {
        ...canvas,
        nodes: [canvas.nodes[0]!, node],
      },
      selectedNode: node,
      selectedCapability: "text_to_image",
      selectedModel: imageEditModel,
    });

    expect(result).toMatchObject({
      ok: true,
      request: {
        capability: "image_to_image",
        provider_id: "provider-1",
        model_id: "model-1",
      },
    });
  });

  it("builds storyboard script job requests from upstream script text and node instructions", () => {
    const sourceNode: AigcCanvasNode = {
      id: "source-1",
      type: "prompt",
      position: { x: 80, y: 90 },
      data: {
        title: "原始剧本",
        text: "现代办公室加班后穿越盛唐",
      },
    };
    const scriptNode: AigcCanvasNode = {
      id: "script-1",
      type: "script_generate",
      position: { x: 420, y: 90 },
      data: {
        scriptInputKind: "script",
        scriptPrompt: "把素材拆成 3 个短剧分镜",
      },
    };
    const storyboardModel: AigcCapabilityInfo = {
      ...model,
      capability: "storyboard",
    };

    const result = buildRunNodeJobRequest({
      canvas: {
        ...canvasFixture(),
        nodes: [sourceNode, scriptNode],
        edges: [
          {
            id: "edge-source-script",
            source: "source-1",
            target: "script-1",
          },
        ],
      },
      selectedNode: scriptNode,
      selectedCapability: "storyboard",
      selectedModel: storyboardModel,
    });

    expect(result).toEqual({
      ok: true,
      request: {
        canvas_id: "canvas-1",
        node_id: "script-1",
        capability: "storyboard",
        provider_id: "provider-1",
        model_id: "model-1",
        inputs: {
          prompt:
            "把素材拆成 3 个短剧分镜\n\n素材/剧本：\n现代办公室加班后穿越盛唐",
          node_type: "script_generate",
          reference_nodes: [
            {
              node_id: "source-1",
              type: "prompt",
              title: "原始剧本",
              asset_name: undefined,
              preview_url: undefined,
            },
          ],
        },
        parameters: {
          scriptInputKind: "script",
          textMode: "storyboard_script",
          outputFormat: "storyboard_shots_json",
        },
      },
    });
  });

  it("keeps style template inputs separate from uploaded reference images", () => {
    const canvas = canvasFixture();
    const imageReference = {
      id: "asset-reference-1",
      type: "reference_asset",
      position: { x: 90, y: 220 },
      data: {
        title: "上传照片",
        assetKind: "image",
        assetName: "portrait.png",
        assetPreviewUrl: "/api/user/aigc-studio/assets/portrait/file",
      },
    };
    const styleReference = {
      id: "style-reference-1",
      type: "reference_asset",
      position: { x: 90, y: 390 },
      data: {
        title: "素材-风格一键国漫CGV2",
        assetRole: "style_template",
        assetKind: "image",
        assetName: "一键国漫CGV2",
        assetPreviewUrl: "/style-preview.png",
        styleTemplateUuid: "dbc6dfc0990d46d28215bcdff87d53c3",
        effectId: 22910748,
        styleKeywords: "国漫, CG",
        styleDescription: "国漫 CG 风格，冷色调金属质感。",
        styleSupplementalPrompt: "保留克制的金属高光。",
        visualDna: [{ element_id: "lighting.cinematic_contrast", weight: 0.9 }],
        styleReferenceImages: ["/api/user/aigc-studio/assets/style/file"],
        aestheticProfileSnapshot: {
          id: "style-cgv2",
          title: "一键国漫CGV2",
          version: "1.0",
          visual_dna: [
            { element_id: "lighting.cinematic_contrast", weight: 0.9 },
          ],
          reference_image_urls: ["/api/user/aigc-studio/assets/style/file"],
        },
      },
    };
    const targetNode = {
      ...canvas.nodes[1]!,
      data: {
        ...canvas.nodes[1]!.data,
        text: "把我的照片做风格改造",
        imageMode: "image_to_image",
        styleReferenceName: "一键国漫CGV2",
        styleReferencePreviewUrl: "/style-preview.png",
        effectTemplateUuids: ["dbc6dfc0990d46d28215bcdff87d53c3"],
        effects: [22910748],
      },
    };

    const result = buildRunNodeJobRequest({
      canvas: {
        ...canvas,
        nodes: [canvas.nodes[0]!, imageReference, styleReference, targetNode],
        edges: [
          {
            id: "edge-image-reference",
            source: "asset-reference-1",
            target: "image-1",
          },
          {
            id: "edge-style-reference",
            source: "style-reference-1",
            target: "image-1",
            data: { role: "style_template" },
          },
        ],
      },
      selectedNode: targetNode,
      selectedCapability: "text_to_image",
      selectedModel: model,
    });

    expect(result).toMatchObject({
      ok: true,
      request: {
        inputs: {
          prompt: "把我的照片做风格改造",
          reference_nodes: [
            expect.objectContaining({
              node_id: "asset-reference-1",
              asset_name: "portrait.png",
            }),
          ],
        },
        parameters: expect.objectContaining({
          effectTemplateUuids: ["dbc6dfc0990d46d28215bcdff87d53c3"],
          effects: [22910748],
          styleReferenceName: "一键国漫CGV2",
          styleReferencePreviewUrl: "/style-preview.png",
          styleKeywords: "国漫, CG",
          styleDescription: "国漫 CG 风格，冷色调金属质感。",
          styleSupplementalPrompt: "保留克制的金属高光。",
          visualDna: [
            { element_id: "lighting.cinematic_contrast", weight: 0.9 },
          ],
          styleReferenceImages: ["/api/user/aigc-studio/assets/style/file"],
          aestheticProfileSnapshot: expect.objectContaining({
            id: "style-cgv2",
            version: "1.0",
          }),
        }),
      },
    });
    expect(result.ok && result.request.inputs.reference_nodes).not.toEqual(
      expect.arrayContaining([
        expect.objectContaining({ node_id: "style-reference-1" }),
      ]),
    );
  });

  it("maps @素材 aliases to ordered prompt references and model-limited image URLs", () => {
    const canvas = canvasFixture();
    const references = [
      {
        id: "asset-reference-1",
        type: "reference_asset",
        position: { x: 80, y: 160 },
        data: {
          title: "产品正面",
          assetKind: "image",
          assetName: "front.png",
          assetPreviewUrl: "/api/user/aigc-studio/assets/front/file",
        },
      },
      {
        id: "asset-reference-2",
        type: "reference_asset",
        position: { x: 80, y: 320 },
        data: {
          title: "产品背面",
          assetKind: "image",
          assetName: "back.png",
          assetPreviewUrl: "/api/user/aigc-studio/assets/back/file",
        },
      },
      {
        id: "asset-reference-3",
        type: "reference_asset",
        position: { x: 80, y: 480 },
        data: {
          title: "产品细节",
          assetKind: "image",
          assetName: "detail.png",
          assetPreviewUrl: "/api/user/aigc-studio/assets/detail/file",
        },
      },
    ];
    const targetNode = {
      ...canvas.nodes[1]!,
      data: {
        ...canvas.nodes[1]!.data,
        text: "参考 @图片1 的包装主体，结合 @图片2 的背面信息做一张产品海报",
        imageMode: "image_to_image",
      },
    };
    const multiReferenceModel: AigcCapabilityInfo = {
      ...model,
      capability: "image_to_image",
      parameter_schema: {
        max_reference_images: 2,
      },
    };

    const result = buildRunNodeJobRequest({
      canvas: {
        ...canvas,
        nodes: [...references, targetNode],
        edges: references.map((reference) => ({
          id: `edge-${reference.id}-image-1`,
          source: reference.id,
          target: "image-1",
          data: { role: "reference_image" },
        })),
      },
      selectedNode: targetNode,
      selectedCapability: "image_to_image",
      selectedModel: multiReferenceModel,
    });

    expect(result).toMatchObject({
      ok: true,
      request: {
        inputs: expect.objectContaining({
          prompt:
            "参考 第一张参考图 的包装主体，结合 第二张参考图 的背面信息做一张产品海报",
        }),
        parameters: expect.objectContaining({
          referenceImages: [
            "/api/user/aigc-studio/assets/front/file",
            "/api/user/aigc-studio/assets/back/file",
          ],
          referenceImageAliases: [
            expect.objectContaining({
              alias: "图片1",
              name: "front.png",
            }),
            expect.objectContaining({
              alias: "图片2",
              name: "back.png",
            }),
          ],
          referenceImageLimit: 2,
        }),
      },
    });
  });

  it("uses generated output URLs for upstream image references before stale source previews", () => {
    const canvas = canvasFixture();
    const generatedReference = {
      id: "generated-reference",
      type: "image_generate",
      position: { x: 80, y: 180 },
      data: {
        title: "已生成海报",
        assetName: "old-input.png",
        assetPreviewUrl: "/api/user/aigc-studio/assets/old-input/file",
        imageState: "generated",
        outputs: [
          {
            id: "generated-output",
            kind: "image",
            name: "generated-poster.png",
            url: "/api/user/aigc-studio/assets/generated-output/file",
            created_at: "2026-06-27T00:00:00Z",
          },
        ],
      },
    };
    const targetNode = {
      ...canvas.nodes[1]!,
      data: {
        ...canvas.nodes[1]!.data,
        text: "参考 @图片1 做中秋活动海报",
        imageMode: "image_to_image",
      },
    };

    const result = buildRunNodeJobRequest({
      canvas: {
        ...canvas,
        nodes: [canvas.nodes[0]!, generatedReference, targetNode],
        edges: [
          {
            id: "edge-generated-reference-image-1",
            source: "generated-reference",
            target: "image-1",
            data: { role: "reference_image" },
          },
        ],
      },
      selectedNode: targetNode,
      selectedCapability: "image_to_image",
      selectedModel: {
        ...model,
        capability: "image_to_image",
      },
    });

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("expected submit request to be built");
    expect(result.request?.parameters).toMatchObject({
      referenceImages: ["/api/user/aigc-studio/assets/generated-output/file"],
      referenceImageAliases: [
        expect.objectContaining({
          name: "generated-poster.png",
          previewUrl: "/api/user/aigc-studio/assets/generated-output/file",
        }),
      ],
    });
  });

  it("ignores stale target reference thumbnails when upstream references exist", () => {
    const canvas = canvasFixture();
    const references = [
      {
        id: "asset-reference-1",
        type: "reference_asset",
        position: { x: 80, y: 160 },
        data: {
          title: "正面素材",
          assetKind: "image",
          assetName: "front.png",
          assetPreviewUrl: "/api/user/aigc-studio/assets/front/file",
        },
      },
      {
        id: "asset-reference-2",
        type: "reference_asset",
        position: { x: 80, y: 320 },
        data: {
          title: "背面素材",
          assetKind: "image",
          assetName: "back.png",
          assetPreviewUrl: "/api/user/aigc-studio/assets/back/file",
        },
      },
    ];
    const targetNode = {
      ...canvas.nodes[1]!,
      data: {
        ...canvas.nodes[1]!.data,
        text: "参考 @图片1 和 @图片2 做海报",
        imageMode: "image_to_image",
        referenceThumb: true,
        referenceAssetName: "old-single.png",
        referencePreviewUrl: "/api/user/aigc-studio/assets/old-single/file",
      },
    };

    const result = buildRunNodeJobRequest({
      canvas: {
        ...canvas,
        nodes: [...references, targetNode],
        edges: references.map((reference) => ({
          id: `edge-${reference.id}-image-1`,
          source: reference.id,
          target: "image-1",
          data: { role: "reference_image" },
        })),
      },
      selectedNode: targetNode,
      selectedCapability: "image_to_image",
      selectedModel: {
        ...model,
        capability: "image_to_image",
      },
    });

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("expected submit request to be built");
    expect(result.request.parameters).toMatchObject({
      referenceImages: [
        "/api/user/aigc-studio/assets/front/file",
        "/api/user/aigc-studio/assets/back/file",
      ],
    });
  });

  it("ignores stale @ mention reference assets whose source edge was removed", () => {
    const canvas = canvasFixture();
    const references = [
      {
        id: "asset-reference-1",
        type: "reference_asset",
        position: { x: 80, y: 160 },
        data: {
          title: "正面素材",
          assetKind: "image",
          assetName: "front.png",
          assetPreviewUrl: "/api/user/aigc-studio/assets/front/file",
        },
      },
      {
        id: "asset-reference-2",
        type: "reference_asset",
        position: { x: 80, y: 320 },
        data: {
          title: "背面素材",
          assetKind: "image",
          assetName: "back.png",
          assetPreviewUrl: "/api/user/aigc-studio/assets/back/file",
        },
      },
    ];
    const targetNode = {
      ...canvas.nodes[1]!,
      data: {
        ...canvas.nodes[1]!.data,
        text: "参考 @图片1 做海报",
        imageMode: "image_to_image",
        referencedAssets: [
          {
            id: "asset-reference-1",
            alias: "图片1",
            name: "front.png",
            previewUrl: "/api/user/aigc-studio/assets/front/file",
            sourceNodeId: "asset-reference-1",
          },
          {
            id: "asset-reference-2",
            alias: "图片2",
            name: "back.png",
            previewUrl: "/api/user/aigc-studio/assets/back/file",
            sourceNodeId: "asset-reference-2",
          },
        ],
      },
    };
    const staleCanvas = {
      ...canvas,
      nodes: [...references, targetNode],
      edges: [
        {
          id: "edge-asset-reference-1-image-1",
          source: "asset-reference-1",
          target: "image-1",
          data: { role: "reference_image" },
        },
      ],
    };

    expect(imageReferenceAssetsForNode(staleCanvas, targetNode)).toEqual([
      expect.objectContaining({
        alias: "图片1",
        sourceNodeId: "asset-reference-1",
        previewUrl: "/api/user/aigc-studio/assets/front/file",
      }),
    ]);

    const result = buildRunNodeJobRequest({
      canvas: staleCanvas,
      selectedNode: targetNode,
      selectedCapability: "image_to_image",
      selectedModel: {
        ...model,
        capability: "image_to_image",
      },
    });

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("expected submit request to be built");
    expect(result.request.parameters).toMatchObject({
      referenceImages: ["/api/user/aigc-studio/assets/front/file"],
    });
  });

  it("submits image annotations as region edit references", () => {
    const canvas = canvasFixture();
    const annotationNode = {
      id: "annotation-1",
      type: "reference_asset",
      position: { x: 90, y: 220 },
      data: {
        title: "标注",
        assetRole: "image_annotation",
        assetKind: "image",
        assetName: "face-mark.png",
        assetPreviewUrl: "/marked-face.png",
        annotationSourcePreviewUrl: "/clean-face.png",
        annotationPreviewUrl: "/marked-face.png",
        annotationInstruction: "红圈是需要调整肤质的脸部区域",
      },
    };
    const targetNode = {
      ...canvas.nodes[1]!,
      data: {
        ...canvas.nodes[1]!.data,
        text: "脸蛋要加上皮肤质感",
        imageMode: "image_to_image",
        imageEditScope: "annotated_region",
        annotationMode: "region_edit",
        annotationAssetName: "face-mark.png",
        annotationSourcePreviewUrl: "/clean-face.png",
        annotationPreviewUrl: "/marked-face.png",
        annotationInstruction: "红圈是需要调整肤质的脸部区域",
      },
    };

    const result = buildRunNodeJobRequest({
      canvas: {
        ...canvas,
        nodes: [annotationNode, targetNode],
        edges: [
          {
            id: "edge-annotation-image",
            source: "annotation-1",
            target: "image-1",
            data: { role: "image_annotation" },
          },
        ],
      },
      selectedNode: targetNode,
      selectedCapability: "text_to_image",
      selectedModel: model,
    });

    expect(result).toMatchObject({
      ok: true,
      request: {
        inputs: {
          prompt: "脸蛋要加上皮肤质感",
          reference_nodes: [
            expect.objectContaining({
              node_id: "annotation-1",
              role: "image_annotation",
              asset_name: "face-mark.png",
              preview_url: "/clean-face.png",
              source_preview_url: "/clean-face.png",
              annotated_preview_url: "/marked-face.png",
              instruction: "红圈是需要调整肤质的脸部区域",
            }),
          ],
          annotations: [
            expect.objectContaining({
              node_id: "annotation-1",
              role: "image_annotation",
              preview_url: "/clean-face.png",
              annotated_preview_url: "/marked-face.png",
              instruction: "红圈是需要调整肤质的脸部区域",
            }),
          ],
        },
        parameters: expect.objectContaining({
          imageMode: "image_to_image",
          imageEditScope: "annotated_region",
          annotationMode: "region_edit",
          annotationAssetName: "face-mark.png",
          annotationSourcePreviewUrl: "/clean-face.png",
          annotationPreviewUrl: "/marked-face.png",
          annotationInstruction: "红圈是需要调整肤质的脸部区域",
        }),
      },
    });
  });

  it("filters unsupported image parameters for Seedream 4.5 submissions", () => {
    const canvas = canvasFixture();
    const node = {
      ...canvas.nodes[1]!,
      data: {
        ...canvas.nodes[1]!.data,
        aspectRatio: "2:1",
        imageQuality: "高画质",
        resolution: "1K",
        imageCount: 4,
        webSearch: true,
        stylePreset: "电影感",
        markPreset: "主体区域",
        focusPreset: "主体清晰",
        cameraProfile: "电影镜头",
        cameraBody: "Panavision DXL2",
        lens: "Arri Signature Prime",
        focal: "35 mm",
        aperture: "f/4",
      },
    };
    const seedream45: AigcCapabilityInfo = {
      ...model,
      provider_id: "volcengine",
      provider_name: "Volcano Engine",
      model_id: "doubao-seedream-4-5-251128",
      model_name: "doubao-seedream-4-5",
    };

    const result = buildRunNodeJobRequest({
      canvas: {
        ...canvas,
        nodes: [canvas.nodes[0]!, node],
      },
      selectedNode: node,
      selectedCapability: "text_to_image",
      selectedModel: seedream45,
    });

    expect(result).toEqual(
      expect.objectContaining({
        ok: true,
        request: expect.objectContaining({
          parameters: {
            aspectRatio: "16:9",
            imageCount: 4,
            imageMode: "text_to_image",
            resolution: "2K",
          },
        }),
      }),
    );
  });

  it("blocks slash image commands when no reference input exists", () => {
    const canvas = {
      ...canvasFixture(),
      edges: [],
      nodes: [
        {
          ...canvasFixture().nodes[1]!,
          data: { slashCommand: "upscale" },
        },
      ],
    };

    expect(
      buildRunNodeJobRequest({
        canvas,
        selectedNode: canvas.nodes[0]!,
        selectedCapability: "image_edit",
        selectedModel: model,
      }),
    ).toEqual({ ok: false, reason: "missing_reference" });
  });

  it("keeps video reference assets in the video generation job payload", () => {
    const videoModel: AigcCapabilityInfo = {
      ...model,
      provider_id: "mxapi",
      provider_name: "MXAPI",
      model_id: "seedance2",
      model_name: "Seedance 2.0",
      capability: "image_to_video",
      parameter_schema: {
        properties: {
          generate_audio: { type: "boolean", default: false },
        },
      },
    };
    const videoNode: AigcCanvasNode = {
      id: "video-1",
      type: "video_generate",
      position: { x: 360, y: 90 },
      data: {
        title: "Video",
        text: "小猫从睡觉到跳起来追蝴蝶",
        videoMode: "first_last_frames",
        activeVideoTab: "first_frame",
        aspectRatio: "Auto",
        videoResolution: "1080P",
        videoDuration: 5,
        videoAudio: false,
        videoReferenceAssets: [
          {
            id: "first-frame",
            kind: "image",
            name: "first.jpg",
            previewUrl: "https://cdn.example.test/first.jpg",
          },
          {
            id: "last-frame",
            kind: "image",
            name: "last.jpg",
            previewUrl: "https://cdn.example.test/last.jpg",
            role: "last_frame",
          },
        ],
      },
    };
    const canvas: AigcCanvas = {
      ...canvasFixture(),
      nodes: [videoNode],
      edges: [],
    };

    const result = buildRunNodeJobRequest({
      canvas,
      selectedNode: videoNode,
      selectedCapability: "text_to_video",
      selectedModel: videoModel,
    });

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("expected video job request");
    expect(result.request).toMatchObject({
      capability: "image_to_video",
      provider_id: "mxapi",
      model_id: "seedance2",
      inputs: {
        prompt: "小猫从睡觉到跳起来追蝴蝶",
        node_type: "video_generate",
      },
      parameters: expect.objectContaining({
        videoMode: "first_last_frames",
        activeVideoTab: "first_frame",
        aspectRatio: "Auto",
        videoResolution: "1080P",
        videoDuration: 5,
        videoAudio: false,
        videoReferenceAssets: videoNode.data.videoReferenceAssets,
      }),
    });
  });

  it("omits the audio switch for video models that do not support generation audio", () => {
    const videoNode: AigcCanvasNode = {
      id: "video-1",
      type: "video_generate",
      position: { x: 360, y: 90 },
      data: {
        title: "Video",
        text: "镜头缓慢推进",
        aspectRatio: "9:16",
        videoResolution: "720P",
        videoDuration: 10,
        videoAudio: true,
      },
    };
    const videoModel: AigcCapabilityInfo = {
      ...model,
      provider_id: "mxapi",
      model_id: "grok-imagine-video-1.5-fast",
      model_name: "Grok Imagine Video 1.5 Fast",
      capability: "text_to_video",
      parameter_schema: {
        properties: {
          duration: { minimum: 6, maximum: 30, default: 10 },
        },
      },
    };
    const result = buildRunNodeJobRequest({
      canvas: { ...canvasFixture(), nodes: [videoNode], edges: [] },
      selectedNode: videoNode,
      selectedCapability: "text_to_video",
      selectedModel: videoModel,
    });

    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error("expected video job request");
    expect(result.request.parameters).toMatchObject({
      aspectRatio: "9:16",
      videoResolution: "720P",
      videoDuration: 10,
    });
    expect(result.request.parameters).not.toHaveProperty("videoAudio");
  });

  it("counts connected media inputs for a video node", () => {
    const videoNode: AigcCanvasNode = {
      id: "video-1",
      type: "video_generate",
      position: { x: 640, y: 100 },
      data: { title: "视频" },
    };
    const imageNode: AigcCanvasNode = {
      id: "image-1",
      type: "image_generate",
      position: { x: 80, y: 100 },
      data: { title: "图片" },
    };
    const audioNode: AigcCanvasNode = {
      id: "audio-1",
      type: "audio_generate",
      position: { x: 80, y: 420 },
      data: { title: "音频" },
    };
    const canvas: AigcCanvas = {
      ...canvasFixture(),
      nodes: [imageNode, audioNode, videoNode],
      edges: [
        {
          id: "edge-image-video",
          source: "image-1",
          target: "video-1",
        },
        {
          id: "edge-audio-video",
          source: "audio-1",
          target: "video-1",
        },
      ],
    };

    expect(videoConnectedInputsForNode(canvas, videoNode)).toEqual({
      imageCount: 1,
      videoCount: 0,
      audioCount: 1,
      totalCount: 2,
    });
  });

  it("updates job lists and writes finished outputs back to the node", () => {
    const queued = jobFixture("queued");
    const finished = {
      ...jobFixture("succeeded"),
      parameters: {
        aspectRatio: "9:16",
      },
    };

    expect(prependCanvasJob([], queued)).toEqual([queued]);
    expect(replaceCanvasJob([queued], finished)).toEqual([finished]);

    const updated = applyFinishedJobToCanvas({
      canvas: canvasFixture(),
      nodeId: "image-1",
      job: finished,
    });

    expect(updated.nodes[1]?.data).toMatchObject({
      job_id: "job-1",
      job_status: "succeeded",
      generatedAspectRatio: "9:16",
      outputs: finished.outputs,
    });
  });

  it("stores the submitted ratio when a video job finishes", () => {
    const videoNode: AigcCanvasNode = {
      id: "video-1",
      type: "video_generate",
      position: { x: 360, y: 90 },
      data: { aspectRatio: "16:9", videoState: "generating" },
    };
    const finished: AigcJob = {
      ...jobFixture("succeeded"),
      node_id: videoNode.id,
      capability: "image_to_video",
      parameters: { aspectRatio: "9:16" },
      outputs: [
        {
          id: "video-output",
          kind: "video",
          name: "portrait.mp4",
          path: "outputs/portrait.mp4",
          created_at: "2026-07-21T00:00:00Z",
        },
      ],
    };

    const updated = applyFinishedJobToCanvas({
      canvas: { ...canvasFixture(), nodes: [videoNode], edges: [] },
      nodeId: videoNode.id,
      job: finished,
    });

    expect(updated.nodes[0]?.data).toMatchObject({
      videoState: "generated",
      generatedAspectRatio: "9:16",
      outputs: finished.outputs,
    });
  });

  it("marks a script asset ready when its image node job succeeds", () => {
    const scriptNode: AigcCanvasNode = {
      id: "script-1",
      type: "script_generate",
      position: { x: 600, y: 120 },
      data: {
        scriptAssetStates: {
          "character:林风": "generating",
          "scene:废弃便利店": "generating",
        },
      },
    };
    const assetNode: AigcCanvasNode = {
      id: "script-asset-script-1-character-林风",
      type: "image_generate",
      position: { x: 100, y: 120 },
      data: {
        imageMode: "text_to_image",
        sourceScriptNodeId: "script-1",
        scriptAssetId: "character:林风",
      },
    };

    const updated = applyFinishedJobToCanvas({
      canvas: {
        ...canvasFixture(),
        nodes: [scriptNode, assetNode],
        edges: [],
      },
      nodeId: assetNode.id,
      job: jobFixture("succeeded"),
    });

    expect(updated.nodes[0]?.data.scriptAssetStates).toEqual({
      "character:林风": "ready",
      "scene:废弃便利店": "generating",
    });
    expect(updated.nodes[1]?.data).toMatchObject({
      imageState: "generated",
      job_status: "succeeded",
    });
  });

  it("parses successful storyboard text jobs into script shots", () => {
    const scriptNode: AigcCanvasNode = {
      id: "script-1",
      type: "script_generate",
      position: { x: 100, y: 100 },
      data: {
        scriptMode: "generating_script",
        scriptShots: [],
        selectedShotIds: [],
      },
    };
    const job: AigcJob = {
      ...jobFixture("succeeded"),
      id: "job-script-1",
      node_id: "script-1",
      capability: "storyboard",
      outputs: [
        {
          id: "text-output-1",
          kind: "file",
          name: "storyboard.json",
          path: "outputs/storyboard.json",
          meta: {
            text: JSON.stringify({
              title: "夜班穿越",
              shots: [
                {
                  no: 1,
                  duration: 4,
                  imageDescription: "深夜办公室蓝色屏幕光",
                  scene: "现代办公室",
                  shotType: "特写",
                  action: "手指停下",
                  emotion: "疲惫",
                  prompt: "电影感办公室特写",
                },
              ],
            }),
          },
          created_at: "2026-06-12T00:00:00Z",
        },
      ],
    };

    const updated = applyFinishedJobToCanvas({
      canvas: { ...canvasFixture(), nodes: [scriptNode], edges: [] },
      nodeId: "script-1",
      job,
    });

    expect(updated.nodes[0]?.data).toMatchObject({
      job_id: "job-script-1",
      job_status: "succeeded",
      job_error: null,
      scriptMode: "script_ready",
      scriptProgress: 100,
      scriptParseStatus: "ready",
      scriptTitle: "夜班穿越",
      selectedShotIds: ["shot-1"],
      scriptShots: [
        expect.objectContaining({
          id: "shot-1",
          prompt: "电影感办公室特写",
        }),
      ],
      outputs: job.outputs,
    });
  });

  it("converts unstructured storyboard text into fallback shots without demo data", () => {
    const scriptNode: AigcCanvasNode = {
      id: "script-1",
      type: "script_generate",
      position: { x: 100, y: 100 },
      data: {
        scriptMode: "generating_script",
        scriptShots: [],
        selectedShotIds: [],
      },
    };
    const job: AigcJob = {
      ...jobFixture("succeeded"),
      id: "job-script-plain-text",
      node_id: "script-1",
      capability: "storyboard",
      outputs: [
        {
          id: "text-output-1",
          kind: "file",
          name: "storyboard.txt",
          path: "outputs/storyboard.txt",
          meta: {
            text: "第一幕：这里是普通文本，不是结构化 JSON。",
          },
          created_at: "2026-06-12T00:00:00Z",
        },
      ],
    };

    const updated = applyFinishedJobToCanvas({
      canvas: { ...canvasFixture(), nodes: [scriptNode], edges: [] },
      nodeId: "script-1",
      job,
    });

    expect(updated.nodes[0]?.data).toMatchObject({
      job_id: "job-script-plain-text",
      job_status: "succeeded",
      scriptMode: "script_ready",
      scriptParseStatus: "ready",
      scriptRawOutput: "第一幕：这里是普通文本，不是结构化 JSON。",
      scriptShots: [
        expect.objectContaining({
          id: "shot-1",
          imageDescription: "第一幕：这里是普通文本，不是结构化 JSON。",
        }),
      ],
      selectedShotIds: ["shot-1"],
      outputs: job.outputs,
    });
    expect(updated.nodes[0]?.data.scriptParseError).toBeNull();
  });
});
