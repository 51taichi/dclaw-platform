import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createNodeForType,
  createTemplateParts,
  defaultCanvasPayload,
} from "./canvasTemplateFactory";

const t = ((_key: string, fallback?: string) => fallback ?? _key) as never;

describe("canvasTemplateFactory", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("creates the default canvas payload with canonical nodes and edges", () => {
    const payload = defaultCanvasPayload(t, "默认画布");

    expect(payload).toMatchObject({
      name: "默认画布",
      viewport: { x: 0, y: 0, zoom: 1 },
      meta: { version: 1 },
    });
    expect(payload.nodes.map((node) => node.id)).toEqual([
      "prompt-1",
      "image-1",
      "video-1",
      "reference-1",
    ]);
    expect(payload.edges).toEqual([
      { id: "edge-1", source: "prompt-1", target: "image-1" },
      { id: "edge-2", source: "image-1", target: "video-1" },
      { id: "edge-3", source: "reference-1", target: "video-1" },
    ]);
  });

  it("creates a video node with default video generation settings", () => {
    vi.spyOn(Date, "now").mockReturnValue(36);

    const node = createNodeForType(t, "video_generate", 5);

    expect(node).toMatchObject({
      id: "video_generate-10-6",
      type: "video_generate",
      position: { x: 360, y: 300 },
      data: {
        activeVideoTab: "text_to_video",
        aspectRatio: "16:9",
        showTryOptions: true,
        videoAudio: true,
        videoCount: 1,
        videoDuration: 5,
        videoMode: "blank",
        videoResolution: "720P",
      },
    });
  });

  it("creates audio-video template nodes with connected references", () => {
    vi.spyOn(Date, "now").mockReturnValue(36);

    const template = createTemplateParts(t, "audioVideo", 3);

    expect(template.selectedNodeId).toBe("audio-video-audioVideo-10-4");
    expect(template.nodes.map((node) => node.type)).toEqual([
      "audio_generate",
      "reference_asset",
      "video_generate",
    ]);
    expect(template.edges).toEqual([
      expect.objectContaining({
        source: "audio-source-audioVideo-10-4",
        target: "audio-video-audioVideo-10-4",
        sourceHandle: "right",
        targetHandle: "left",
      }),
      expect.objectContaining({
        source: "audio-image-audioVideo-10-4",
        target: "audio-video-audioVideo-10-4",
        sourceHandle: "right",
        targetHandle: "left",
      }),
    ]);
  });
});
