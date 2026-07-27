import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import { VideoComposer } from "./VideoComposer";

const t = ((
  _key: string,
  fallback?: string,
  values?: Record<string, unknown>,
) => {
  const template = fallback ?? _key;
  return Object.entries(values ?? {}).reduce(
    (result, [key, value]) => result.replace(`{{${key}}}`, String(value)),
    template,
  );
}) as never;

const videoNode = (data: AigcCanvasNode["data"] = {}): AigcCanvasNode => ({
  id: "video-1",
  type: "video_generate",
  position: { x: 620, y: 220 },
  data: {
    title: "视频节点",
    composerText: "一只小猫在花园里玩耍",
    showTryOptions: false,
    ...data,
  },
});

const seedanceFastModel: AigcCapabilityInfo = {
  provider_id: "mxapi",
  provider_name: "MXAPI",
  model_id: "seedance2-fast",
  model_name: "Seedance 2.0 Fast",
  capability: "text_to_video",
  source: "model_registry",
  parameter_schema: {
    properties: {
      duration: { minimum: 4, maximum: 15, default: 5 },
      aspect_ratio: {
        enum: ["Auto", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"],
      },
      resolution: { enum: ["480P", "720P"] },
      generate_audio: { type: "boolean", default: false },
    },
  },
};

const seedanceMiniModel: AigcCapabilityInfo = {
  provider_id: "mxapi",
  provider_name: "MXAPI",
  model_id: "seedance2-mini",
  model_name: "Seedance 2.0 Mini",
  capability: "image_to_video",
  source: "model_registry",
  parameter_schema: {
    properties: {
      duration: { minimum: 4, maximum: 15, default: 5 },
      aspect_ratio: {
        enum: ["Auto", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9"],
      },
      resolution: { enum: ["480P", "720P"] },
      generate_audio: { type: "boolean", default: false },
    },
  },
};

const grokFastModel: AigcCapabilityInfo = {
  provider_id: "mxapi",
  provider_name: "MXAPI",
  model_id: "grok-imagine-video-1.5-fast",
  model_name: "Grok Imagine Video 1.5 Fast",
  capability: "text_to_video",
  source: "model_registry",
  parameter_schema: {
    properties: {
      duration: { minimum: 6, maximum: 30, default: 10 },
      aspect_ratio: { enum: ["2:3", "3:2", "1:1", "9:16", "16:9"] },
      resolution: { enum: ["480P", "720P"] },
    },
  },
};

const jimengFirstLastModel: AigcCapabilityInfo = {
  provider_id: "mxapi",
  provider_name: "MXAPI",
  model_id: "doubao-seedance-1-5-pro-251215",
  model_name: "即梦 Seedance 1.5 Pro",
  capability: "image_to_video",
  source: "model_registry",
  parameter_schema: {
    preferred_video_mode: "first_last_frames",
    properties: {
      duration: { minimum: 2, maximum: 12, default: 5 },
      aspect_ratio: { enum: ["Auto", "16:9", "9:16", "1:1", "4:3", "3:4"] },
      resolution: { enum: ["480P", "720P", "1080P"] },
    },
  },
};

const qwenVideoUnderstandingModel: AigcCapabilityInfo = {
  provider_id: "volcengine",
  provider_name: "Volcano Engine",
  model_id: "qwen3.5-122b-a10b",
  model_name: "Qwen3.5-122B-A10B",
  capability: "reference_video",
  source: "model_registry",
};

const configuredVideoModel = (index: number): AigcCapabilityInfo => ({
  provider_id: "mxapi",
  provider_name: "MXAPI",
  model_id: `seedance2-custom-${index}`,
  model_name: `Seedance Custom ${index}`,
  capability: index % 2 === 0 ? "image_to_video" : "text_to_video",
  source: "model_registry",
});

const renderComposer = (
  props: Partial<ComponentProps<typeof VideoComposer>> & {
    connectedInputs?: {
      imageCount: number;
      videoCount: number;
      audioCount: number;
      totalCount: number;
    };
  } = {},
) => {
  const node =
    props.node ??
    videoNode({
      modelLabel: "Seedance 2.0 VIP",
      videoModel: "Seedance 2.0 VIP",
    });
  const workflow = props.workflow ?? {
    handleVideoUpload: vi.fn(),
    handleVideoTryUpload: vi.fn(),
    handleVideoReferenceUpload: vi.fn(),
    handleGeneratedVideoAction: vi.fn(),
    handleVideoCancelGeneration: vi.fn(),
    handleVideoRetryGeneration: vi.fn(),
    handleVideoComposerSubmit: vi.fn((submittedNode: AigcCanvasNode) => ({
      ...submittedNode,
      data: {
        ...submittedNode.data,
        text: String(submittedNode.data.composerText ?? ""),
      },
    })),
  };
  const onSelectModel = props.onSelectModel ?? vi.fn();
  const onUpdateNodeData = props.onUpdateNodeData ?? vi.fn();
  const onToggleMenu = props.onToggleMenu ?? vi.fn();
  const onCloseMenu = props.onCloseMenu ?? vi.fn();

  return {
    onSelectModel,
    onUpdateNodeData,
    ...render(
      <VideoComposer
        node={node}
        videoComposerMenu={props.videoComposerMenu ?? null}
        currentModel={
          Object.prototype.hasOwnProperty.call(props, "currentModel")
            ? props.currentModel
            : seedanceFastModel
        }
        modelOptions={
          props.modelOptions ?? [
            qwenVideoUnderstandingModel,
            seedanceFastModel,
            seedanceMiniModel,
          ]
        }
        currentModelKey={props.currentModelKey ?? "mxapi:seedance2-fast"}
        connectedInputs={props.connectedInputs}
        referenceAssets={props.referenceAssets}
        t={t}
        workflow={workflow}
        onUpdateNodeData={onUpdateNodeData}
        onToggleMenu={onToggleMenu}
        onSelectModel={onSelectModel}
        onCloseMenu={onCloseMenu}
      />,
    ),
  };
};

const createReferenceDataTransfer = () => {
  const data = new Map<string, string>();
  return {
    effectAllowed: "none",
    dropEffect: "none",
    types: [],
    setData: vi.fn((type: string, value: string) => data.set(type, value)),
    getData: vi.fn((type: string) => data.get(type) ?? ""),
  } as unknown as DataTransfer;
};

describe("VideoComposer", () => {
  it("enables first-row modes from connected media inputs", () => {
    renderComposer({
      node: videoNode({
        activeVideoTab: "text_to_video",
      }),
      connectedInputs: {
        imageCount: 2,
        videoCount: 0,
        audioCount: 0,
        totalCount: 2,
      },
    });

    const composer = screen.getByTestId("aigc-video-composer");
    expect(
      within(composer).getByRole("button", { name: "文生视频" }),
    ).toBeDisabled();
    expect(
      within(composer).getByRole("button", { name: "图生视频" }),
    ).toBeDisabled();
    expect(
      within(composer).getByRole("button", { name: "全能参考" }),
    ).toBeEnabled();
    expect(
      within(composer).getByRole("button", { name: "首尾帧" }),
    ).toBeEnabled();
    expect(
      within(composer).getByRole("button", { name: "图片参考" }),
    ).toBeEnabled();
    expect(
      within(composer).getByRole("button", { name: "文生视频" }),
    ).toHaveAttribute("title", "已连接媒体输入，无法使用纯文生视频");
  });

  it("keeps media-dependent modes disabled before media is connected", () => {
    renderComposer({
      connectedInputs: {
        imageCount: 0,
        videoCount: 0,
        audioCount: 0,
        totalCount: 0,
      },
    });

    const composer = screen.getByTestId("aigc-video-composer");
    expect(
      within(composer).getByRole("button", { name: "文生视频" }),
    ).toBeEnabled();
    expect(
      within(composer).getByRole("button", { name: "全能参考" }),
    ).toBeDisabled();
    expect(
      within(composer).getByRole("button", { name: "图生视频" }),
    ).toBeDisabled();
    expect(
      within(composer).getByRole("button", { name: "首尾帧" }),
    ).toBeDisabled();
    expect(
      within(composer).getByRole("button", { name: "图片参考" }),
    ).toBeDisabled();
    expect(
      within(composer).getByRole("button", { name: "图生视频" }),
    ).toHaveAttribute("title", "需要连接图片节点（1个）");
  });

  it("submits the effective mode derived from connected inputs", () => {
    const workflow = {
      handleVideoUpload: vi.fn(),
      handleVideoTryUpload: vi.fn(),
      handleVideoReferenceUpload: vi.fn(),
      handleGeneratedVideoAction: vi.fn(),
      handleVideoCancelGeneration: vi.fn(),
      handleVideoRetryGeneration: vi.fn(),
      handleVideoComposerSubmit: vi.fn((submittedNode: AigcCanvasNode) => ({
        ...submittedNode,
        data: {
          ...submittedNode.data,
          text: String(submittedNode.data.composerText ?? ""),
        },
      })),
    };
    renderComposer({
      node: videoNode({
        activeVideoTab: "text_to_video",
        videoMode: "text_to_video",
      }),
      connectedInputs: {
        imageCount: 2,
        videoCount: 0,
        audioCount: 0,
        totalCount: 2,
      },
      workflow,
    });

    fireEvent.click(
      within(screen.getByTestId("aigc-video-composer")).getByRole("button", {
        name: "提交视频节点输入",
      }),
    );

    expect(workflow.handleVideoComposerSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          activeVideoTab: "all_reference",
          videoMode: "all_reference",
        }),
      }),
    );
  });

  it.each([
    {
      activeVideoTab: "first_frame",
      imageCount: 1,
      videoCount: 0,
      audioCount: 0,
      totalCount: 1,
    },
    {
      activeVideoTab: "all_reference",
      imageCount: 2,
      videoCount: 1,
      audioCount: 1,
      totalCount: 4,
    },
    {
      activeVideoTab: "first_frame",
      imageCount: 2,
      videoCount: 0,
      audioCount: 0,
      totalCount: 2,
    },
    {
      activeVideoTab: "image_reference",
      imageCount: 3,
      videoCount: 0,
      audioCount: 0,
      totalCount: 3,
    },
  ])(
    "does not render upstream reference upload panels for $activeVideoTab",
    ({ activeVideoTab, imageCount, videoCount, audioCount, totalCount }) => {
      renderComposer({
        node: videoNode({
          activeVideoTab,
          referenceThumb: true,
          referenceCount: totalCount,
        }),
        connectedInputs: {
          imageCount,
          videoCount,
          audioCount,
          totalCount,
        },
      });

      const composer = screen.getByTestId("aigc-video-composer");
      expect(
        within(composer).queryByTestId("aigc-video-reference-panel"),
      ).not.toBeInTheDocument();
      expect(within(composer).queryByText("待添加")).not.toBeInTheDocument();
      expect(
        within(composer).queryByText(/上传.*素材/),
      ).not.toBeInTheDocument();
      expect(within(composer).queryByLabelText(/上传/)).not.toBeInTheDocument();
    },
  );

  it("renders connected reference thumbnail through authenticated asset image", () => {
    renderComposer({
      node: videoNode({
        activeVideoTab: "image_to_video",
        referenceThumb: true,
        referencePreviewUrl: "/api/user/aigc-studio/assets/ref-image-1/file",
        referenceAssetName: "湘左记.jpg",
        referenceCount: 1,
      }),
      connectedInputs: {
        imageCount: 1,
        videoCount: 0,
        audioCount: 0,
        totalCount: 1,
      },
    });

    const thumb = screen.getByTestId("aigc-video-reference-thumb");
    const image = within(thumb).getByRole("img", { name: "湘左记.jpg" });
    expect(image).toHaveAttribute("data-authenticated-asset", "true");
  });

  it("renders every connected image reference in the composer", () => {
    renderComposer({
      node: videoNode({
        activeVideoTab: "image_reference",
        referenceThumb: true,
        referencePreviewUrl: "/api/user/aigc-studio/assets/front/file",
        referenceAssetName: "包装正面, 包装背面, 产品侧面",
        referenceCount: 3,
      }),
      connectedInputs: {
        imageCount: 3,
        videoCount: 0,
        audioCount: 0,
        totalCount: 3,
      },
      referenceAssets: [
        {
          id: "asset-front",
          alias: "图片1",
          name: "包装正面",
          previewUrl: "/api/user/aigc-studio/assets/front/file",
        },
        {
          id: "asset-back",
          alias: "图片2",
          name: "包装背面",
          previewUrl: "/api/user/aigc-studio/assets/back/file",
        },
        {
          id: "asset-side",
          alias: "图片3",
          name: "产品侧面",
          previewUrl: "/api/user/aigc-studio/assets/side/file",
        },
      ],
    });

    const thumbs = screen.getAllByTestId("aigc-video-reference-thumb");
    expect(thumbs).toHaveLength(3);
    expect(thumbs[0]).toHaveTextContent("1");
    expect(thumbs[1]).toHaveTextContent("2");
    expect(thumbs[2]).toHaveTextContent("3");
    expect(
      within(thumbs[0]).getByRole("img", { name: "包装正面" }),
    ).toBeInTheDocument();
    expect(
      within(thumbs[1]).getByRole("img", { name: "包装背面" }),
    ).toBeInTheDocument();
    expect(
      within(thumbs[2]).getByRole("img", { name: "产品侧面" }),
    ).toBeInTheDocument();
  });

  it("lets @素材 insert an ordered reference alias and keep the asset binding", async () => {
    const { onUpdateNodeData } = renderComposer({
      node: videoNode({ composerText: "" }),
      referenceAssets: [
        {
          id: "asset-front",
          alias: "图片1",
          name: "包装正面",
          previewUrl: "/api/user/aigc-studio/assets/front/file",
          sourceNodeId: "asset-reference-1",
        },
      ],
    });

    const input = screen.getByLabelText("视频节点输入");
    fireEvent.change(input, { target: { value: "参考 @" } });

    const option = await screen.findByRole("button", {
      name: /图片1.*包装正面/,
    });
    fireEvent.click(option);

    expect(onUpdateNodeData).toHaveBeenLastCalledWith(
      "video-1",
      expect.objectContaining({
        composerText: "参考 @图片1 ",
        referencedAssets: [
          expect.objectContaining({
            alias: "图片1",
            name: "包装正面",
            previewUrl: "/api/user/aigc-studio/assets/front/file",
          }),
        ],
        inputUpdated: true,
      }),
    );
  });

  it("drags an image reference thumbnail into the prompt at the drop point", async () => {
    const { onUpdateNodeData } = renderComposer({
      node: videoNode({ composerText: "镜头缓慢推进" }),
      referenceAssets: [
        {
          id: "asset-front",
          alias: "图片1",
          name: "产品正面",
          previewUrl: "/api/user/aigc-studio/assets/front/file",
          sourceNodeId: "asset-reference-1",
        },
      ],
    });
    const thumb = screen.getByTestId("aigc-video-reference-thumb");
    const input = screen.getByLabelText("视频节点输入") as HTMLTextAreaElement;
    const dataTransfer = createReferenceDataTransfer();
    input.setSelectionRange(0, 0);

    fireEvent.dragStart(thumb, { dataTransfer });
    fireEvent.dragOver(input, { dataTransfer });
    fireEvent.drop(input, { dataTransfer });

    await waitFor(() =>
      expect(onUpdateNodeData).toHaveBeenLastCalledWith(
        "video-1",
        expect.objectContaining({
          composerText: "@图片1 镜头缓慢推进",
          text: "@图片1 镜头缓慢推进",
          referencedAssets: [
            expect.objectContaining({
              alias: "图片1",
              sourceNodeId: "asset-reference-1",
            }),
          ],
          inputUpdated: true,
        }),
      ),
    );
  });

  it("opens a fullscreen prompt editor from the composer and syncs edits back", () => {
    const onUpdateNodeData = vi.fn();
    renderComposer({
      node: videoNode({ composerText: "原始视频提示词" }),
      onUpdateNodeData,
    });

    const composer = screen.getByTestId("aigc-video-composer");
    fireEvent.click(
      within(composer).getByRole("button", { name: "全屏编辑输入" }),
    );

    const dialog = screen.getByRole("dialog", {
      name: "视频节点输入全屏编辑",
    });
    expect(document.body).toContainElement(dialog);
    expect(composer).not.toContainElement(dialog);

    const fullscreenInput =
      within(dialog).getByLabelText("视频节点输入全屏编辑");
    expect(fullscreenInput).toHaveValue("原始视频提示词");

    fireEvent.change(fullscreenInput, {
      target: { value: "全屏里修改后的视频提示词" },
    });

    expect(onUpdateNodeData).toHaveBeenLastCalledWith("video-1", {
      composerText: "全屏里修改后的视频提示词",
      text: "全屏里修改后的视频提示词",
    });
    expect(screen.getByLabelText("视频节点输入")).toHaveValue(
      "全屏里修改后的视频提示词",
    );
  });

  it("shows selectable capability models instead of stale video presets", () => {
    const onSelectModel = vi.fn();
    const onUpdateNodeData = vi.fn();
    renderComposer({
      onSelectModel,
      onUpdateNodeData,
      videoComposerMenu: { nodeId: "video-1", menu: "model" },
    });

    const composer = screen.getByTestId("aigc-video-composer");
    expect(composer).toHaveTextContent("Seedance 2.0 Fast");
    expect(composer).not.toHaveTextContent("Seedance 2.0 VIP");

    const menu = screen.getByTestId("aigc-video-model-menu");
    expect(menu).toHaveTextContent("Seedance 2.0 Fast");
    expect(menu).toHaveTextContent("Seedance 2.0 Mini");
    expect(menu).toHaveTextContent("最长15s");
    expect(menu).not.toHaveTextContent("2min");
    expect(menu).not.toHaveTextContent("3min");
    expect(menu).not.toHaveTextContent("Qwen3.5-122B-A10B");
    expect(menu).not.toHaveTextContent("Wan 2.7");

    fireEvent.click(
      within(menu).getByRole("button", { name: /Seedance 2.0 Mini/ }),
    );

    expect(onSelectModel).toHaveBeenCalledWith(seedanceMiniModel);
    expect(onUpdateNodeData).not.toHaveBeenCalledWith(
      "video-1",
      expect.objectContaining({ videoModel: "Wan 2.7" }),
    );
  });

  it("switches to first-last-frame mode for the Jimeng 1.5 model", () => {
    const onSelectModel = vi.fn();
    const onUpdateNodeData = vi.fn();
    renderComposer({
      node: videoNode({
        activeVideoTab: "image_to_video",
        videoMode: "image_to_video",
        videoDuration: 15,
        aspectRatio: "21:9",
        videoResolution: "720P",
      }),
      modelOptions: [seedanceFastModel, jimengFirstLastModel],
      onSelectModel,
      onUpdateNodeData,
      videoComposerMenu: { nodeId: "video-1", menu: "model" },
    });

    fireEvent.click(
      within(screen.getByTestId("aigc-video-model-menu")).getByRole("button", {
        name: /即梦 Seedance 1.5 Pro/,
      }),
    );

    expect(onSelectModel).toHaveBeenCalledWith(jimengFirstLastModel);
    expect(onUpdateNodeData).toHaveBeenCalledWith("video-1", {
      videoDuration: 12,
      aspectRatio: "16:9",
      videoResolution: "720P",
      activeVideoTab: "first_frame",
      videoMode: "first_last_frames",
    });
  });

  it("does not show static video presets when no generation model is configured", () => {
    renderComposer({
      currentModel: null,
      currentModelKey: "",
      modelOptions: [qwenVideoUnderstandingModel],
      videoComposerMenu: { nodeId: "video-1", menu: "model" },
    });

    const composer = screen.getByTestId("aigc-video-composer");
    expect(composer).toHaveTextContent("未选择视频模型");
    expect(composer).not.toHaveTextContent("Seedance 2.0 VIP");

    const menu = screen.getByTestId("aigc-video-model-menu");
    expect(menu).toHaveTextContent("暂无可用视频生成模型");
    expect(menu).not.toHaveTextContent("Wan 2.7");
    expect(menu).not.toHaveTextContent("Kling 03");
  });

  it("shows all configured generation models without truncating the list", () => {
    const configuredModels = Array.from({ length: 10 }, (_, index) =>
      configuredVideoModel(index + 1),
    );
    renderComposer({
      currentModel: configuredModels[0],
      currentModelKey: "mxapi:seedance2-custom-1",
      modelOptions: configuredModels,
      videoComposerMenu: { nodeId: "video-1", menu: "model" },
    });

    const menu = screen.getByTestId("aigc-video-model-menu");
    expect(menu).toHaveTextContent("Seedance Custom 1");
    expect(menu).toHaveTextContent("Seedance Custom 10");
  });

  it("uses video duration limits from the selected model schema", () => {
    const onUpdateNodeData = vi.fn();
    renderComposer({
      node: videoNode({
        videoDuration: 15,
        aspectRatio: "16:9",
      }),
      currentModel: {
        ...seedanceFastModel,
        parameter_schema: {
          properties: {
            duration: {
              minimum: 4,
              maximum: 15,
            },
          },
        },
      },
      videoComposerMenu: { nodeId: "video-1", menu: "settings" },
      onUpdateNodeData,
    });

    const menu = screen.getByTestId("aigc-video-settings-menu");
    const durationInput = within(menu).getByLabelText("视频时长");
    expect(durationInput).toHaveAttribute("min", "4");
    expect(durationInput).toHaveAttribute("max", "15");
    expect(within(menu).getByText("15s")).toBeInTheDocument();
  });

  it("uses Grok Fast duration, ratio, and resolution rules from its schema", () => {
    renderComposer({
      node: videoNode({
        videoDuration: 10,
        aspectRatio: "16:9",
        videoResolution: "720P",
      }),
      currentModel: grokFastModel,
      currentModelKey: "mxapi:grok-imagine-video-1.5-fast",
      modelOptions: [grokFastModel],
      videoComposerMenu: { nodeId: "video-1", menu: "settings" },
    });

    const menu = screen.getByTestId("aigc-video-settings-menu");
    const durationInput = within(menu).getByLabelText("视频时长");
    expect(durationInput).toHaveAttribute("min", "6");
    expect(durationInput).toHaveAttribute("max", "30");
    expect(within(menu).queryByRole("button", { name: "Auto" })).toBeNull();
    expect(
      within(menu).getByRole("button", { name: "2:3" }),
    ).toBeInTheDocument();
    expect(
      within(menu).getByRole("button", { name: "720P" }),
    ).toBeInTheDocument();
    expect(within(menu).queryByRole("button", { name: "1080P" })).toBeNull();
    expect(within(menu).queryByText("生成音频")).toBeNull();
  });

  it("shows audio generation only for models that declare support", () => {
    renderComposer({
      node: videoNode({
        videoDuration: 5,
        aspectRatio: "9:16",
        videoResolution: "720P",
        videoAudio: true,
      }),
      currentModel: seedanceFastModel,
      modelOptions: [seedanceFastModel],
      videoComposerMenu: { nodeId: "video-1", menu: "settings" },
    });

    const menu = screen.getByTestId("aigc-video-settings-menu");
    expect(within(menu).getByText("生成音频")).toBeInTheDocument();
    expect(
      within(menu).getByRole("button", { name: "开启" }),
    ).toBeInTheDocument();
  });

  it("renders video ratio preview boxes with the selected aspect shape", () => {
    renderComposer({
      node: videoNode({
        aspectRatio: "9:16",
      }),
      videoComposerMenu: { nodeId: "video-1", menu: "settings" },
    });

    const menu = screen.getByTestId("aigc-video-settings-menu");
    const widePreview = within(
      within(menu).getByRole("button", { name: "16:9" }),
    ).getByTestId("aigc-video-ratio-preview-16:9");
    const tallPreview = within(
      within(menu).getByRole("button", { name: "9:16" }),
    ).getByTestId("aigc-video-ratio-preview-9:16");

    expect(widePreview).toHaveStyle({ width: "18px", height: "10px" });
    expect(tallPreview).toHaveStyle({ width: "7px", height: "12px" });
  });

  it("keeps a video settings menu open while options are selected", () => {
    const onUpdateNodeData = vi.fn();
    const onCloseMenu = vi.fn();
    renderComposer({
      node: videoNode({
        aspectRatio: "16:9",
        videoResolution: "720P",
        videoAudio: true,
      }),
      videoComposerMenu: { nodeId: "video-1", menu: "settings" },
      onUpdateNodeData,
      onCloseMenu,
    });

    const menu = screen.getByTestId("aigc-video-settings-menu");
    fireEvent.click(within(menu).getByRole("button", { name: "9:16" }));

    expect(onUpdateNodeData).toHaveBeenLastCalledWith("video-1", {
      aspectRatio: "9:16",
    });
    expect(onCloseMenu).not.toHaveBeenCalled();
  });

  it("closes an open option menu when the composer input is clicked", () => {
    const onCloseMenu = vi.fn();
    renderComposer({
      videoComposerMenu: { nodeId: "video-1", menu: "settings" },
      onCloseMenu,
    });

    fireEvent.mouseDown(screen.getByLabelText("视频节点输入"));

    expect(onCloseMenu).toHaveBeenCalledTimes(1);
  });
});
