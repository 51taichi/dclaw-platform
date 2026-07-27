import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
  AigcStyleTemplateCreatePayload,
} from "../../../../api/modules/aigcStudio";
import { ImageComposer } from "./ImageComposer";

const mockAuthState = vi.hoisted(() => ({
  role: "user" as string | null,
}));

const mockAigcStudioApi = vi.hoisted(() => ({
  listVisualDnaDimensions: vi.fn(),
  listVisualDnaElements: vi.fn(),
  listStyleTemplates: vi.fn(),
  listFavoriteStyleTemplates: vi.fn(),
  listRecentStyleTemplates: vi.fn(),
  markStyleTemplateUsed: vi.fn(),
  updateStyleTemplateFavorite: vi.fn(),
  createStyleTemplate: vi.fn(),
  updateStyleTemplate: vi.fn(),
  deleteStyleTemplate: vi.fn(),
  uploadAsset: vi.fn(),
}));

vi.mock("../../../../contexts/AuthContext", () => ({
  useAuth: () => ({
    role: mockAuthState.role,
    status: "ok",
    setRole: vi.fn(),
    logout: vi.fn(),
    checkAuth: vi.fn(),
  }),
}));

vi.mock("../../../../api/modules/aigcStudio", async (importOriginal) => {
  const actual = await importOriginal<
    typeof import("../../../../api/modules/aigcStudio")
  >();
  return {
    ...actual,
    aigcStudioApi: mockAigcStudioApi,
  };
});

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

const imageModel: AigcCapabilityInfo = {
  provider_id: "volcengine",
  provider_name: "Volcengine",
  model_id: "seedream-5",
  model_name: "Seedream 5.0",
  capability: "text_to_image",
  source: "model_registry",
};

const seedream45Model: AigcCapabilityInfo = {
  provider_id: "volcengine",
  provider_name: "Volcano Engine",
  model_id: "doubao-seedream-4-5-251128",
  model_name: "Seedream 4.5",
  capability: "text_to_image",
  source: "model_registry",
};

const gptImage2Model: AigcCapabilityInfo = {
  provider_id: "mxapi",
  provider_name: "MXAPI",
  model_id: "gpt-image-2",
  model_name: "GPT Image 2 - MXAPI",
  capability: "image_edit",
  source: "model_registry",
};

const imageNode = (data: AigcCanvasNode["data"] = {}): AigcCanvasNode => ({
  id: "image-1",
  type: "image_generate",
  position: { x: 320, y: 140 },
  data: {
    title: "图片节点",
    imageMode: "blank",
    composerText: "小姑娘",
    showTryOptions: false,
    ...data,
  },
});

const renderComposer = (
  props: Partial<ComponentProps<typeof ImageComposer>> = {},
) => {
  const node = props.node ?? imageNode();
  const workflow = {
    handleImageUpload: vi.fn(),
    handleImageToImageUpload: vi.fn(),
    handleImageUpscaleUpload: vi.fn(),
    handleImageComposerSubmit: vi.fn((submittedNode: AigcCanvasNode) => ({
      ...submittedNode,
      data: {
        ...submittedNode.data,
        text: "小姑娘",
        lastRunPrompt: "小姑娘",
      },
    })),
    handleImageCaptureGroup: vi.fn(),
    handleGeneratedImageSendToImage: vi.fn(),
    handleGeneratedImageAnnotate: vi.fn(),
    handleGeneratedImageSetPrimary: vi.fn(),
    handleGeneratedImageToggleResults: vi.fn(),
    handleImageCaptureGroupSendToImage: vi.fn(),
    handleImageCaptureGroupSelect: vi.fn(),
    handleImageSlashCommand: vi.fn(),
  };
  const onRunNode = vi.fn();
  const onUpdateNodeData = vi.fn();

  render(
    <ImageComposer
      node={node}
      imageComposerMenu={null}
      currentModel={imageModel}
      modelOptions={[imageModel]}
      currentModelKey="volcengine:seedream-5"
      referenceAssets={[]}
      t={t}
      workflow={workflow}
      disabled={false}
      onUpdateNodeData={onUpdateNodeData}
      onRunNode={onRunNode}
      onToggleMenu={vi.fn()}
      onSelectModel={vi.fn()}
      onCloseMenu={vi.fn()}
      {...props}
    />,
  );

  return { node, onRunNode, onUpdateNodeData, workflow };
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

describe("ImageComposer", () => {
  beforeEach(() => {
    mockAuthState.role = "user";
    mockAigcStudioApi.listVisualDnaDimensions.mockResolvedValue({
      dimensions: [
        {
          id: "lighting",
          name: "光影",
          description: "光源与层次",
          scope: "aesthetic_profile",
          element_count: 1,
        },
        {
          id: "camera",
          name: "镜头",
          description: "焦段与景深",
          scope: "shot",
          element_count: 2,
        },
      ],
    });
    mockAigcStudioApi.listVisualDnaElements.mockResolvedValue({
      total: 3,
      elements: [
        {
          id: "lighting.cinematic_contrast",
          dimension: "lighting",
          name: "电影级戏剧光影",
          aliases: ["Cinematic Lighting"],
          definition: "用明确光向建立电影层次",
          visual_effect: "叙事集中、空间纵深强",
          prompt_text: "电影级主光与受控暗部",
          tags: ["电影感"],
          compatible_with: [],
          conflicts_with: [],
          constraints: [],
          model_overrides: {},
          status: "enabled",
          version: "1.0",
        },
        {
          id: "camera.85mm_portrait",
          dimension: "camera",
          name: "85mm 人像镜头",
          aliases: ["85mm Portrait"],
          definition: "中长焦人像视角",
          visual_effect: "主体突出、背景压缩",
          prompt_text: "85mm 中长焦人像视角",
          tags: ["人像"],
          compatible_with: [],
          conflicts_with: ["camera.35mm_environmental"],
          constraints: [],
          model_overrides: {},
          status: "enabled",
          version: "1.0",
        },
        {
          id: "camera.35mm_environmental",
          dimension: "camera",
          name: "35mm 环境叙事镜头",
          aliases: ["35mm Environmental Portrait"],
          definition: "适度广角环境视角",
          visual_effect: "主体与空间共同叙事",
          prompt_text: "35mm 环境叙事视角",
          tags: ["环境人像"],
          compatible_with: [],
          conflicts_with: ["camera.85mm_portrait"],
          constraints: [],
          model_overrides: {},
          status: "enabled",
          version: "1.0",
        },
      ],
    });
    mockAigcStudioApi.listStyleTemplates.mockResolvedValue({
      templates: [
        {
          id: "style-cgv2",
          title: "一键国漫CGV2",
          type: "style",
          provider: "libtv",
          model_family: "seedream-4.5",
          cover_url: "/api/user/aigc-studio/style-templates/style-cgv2/cover",
          category: "推荐",
          tags: ["推荐", "商用"],
          keywords: "国漫, CG, 角色海报, 冷色调, 金属质感",
          description:
            "国漫 CG 风格，突出角色轮廓、冷色调光影、金属质感与高对比氛围。",
          commercial: true,
          runtime_mode: "native_effect",
          effect_template_uuid: "dbc6dfc0990d46d28215bcdff87d53c3",
          effect_id: 22910748,
          use_count: 3300,
        },
      ],
    });
    mockAigcStudioApi.listFavoriteStyleTemplates.mockResolvedValue({
      templates: [],
    });
    mockAigcStudioApi.listRecentStyleTemplates.mockResolvedValue({
      templates: [],
    });
    mockAigcStudioApi.markStyleTemplateUsed.mockResolvedValue(undefined);
    mockAigcStudioApi.updateStyleTemplateFavorite.mockImplementation(
      async (templateId: string, favorite: boolean) => ({
        id: templateId,
        title: "一键国漫CGV2",
        type: "style",
        provider: "libtv",
        model_family: "seedream-4.5",
        cover_url: "/api/user/aigc-studio/style-templates/style-cgv2/cover",
        category: "推荐",
        tags: ["推荐", "商用"],
        keywords: "国漫, CG, 角色海报, 冷色调, 金属质感",
        description:
          "国漫 CG 风格，突出角色轮廓、冷色调光影、金属质感与高对比氛围。",
        commercial: true,
        runtime_mode: "native_effect",
        effect_template_uuid: "dbc6dfc0990d46d28215bcdff87d53c3",
        effect_id: 22910748,
        use_count: 3300,
        favorite,
        status: "enabled",
      }),
    );
    mockAigcStudioApi.createStyleTemplate.mockImplementation(
      async (body: AigcStyleTemplateCreatePayload) => ({
        id: "style-custom-guoman",
        title: body.title,
        type: "style",
        provider: "internal",
        model_family: body.model_family ?? null,
        cover_url: body.cover_url ?? null,
        category: body.category ?? "我的风格",
        tags: body.tags ?? ["我的风格"],
        keywords: body.keywords ?? "",
        description: body.description ?? "",
        supplemental_prompt: body.supplemental_prompt ?? "",
        prompt_template: body.prompt_template ?? "",
        visual_dna: body.visual_dna ?? [],
        reference_image_urls: body.reference_image_urls ?? [],
        profile_version: body.profile_version ?? "1.0",
        commercial: false,
        runtime_mode: "prompt_style",
        effect_template_uuid: null,
        effect_id: null,
        use_count: 0,
        favorite: false,
        status: "enabled",
      }),
    );
    mockAigcStudioApi.updateStyleTemplate.mockResolvedValue({
      id: "style-custom-brand",
      title: "高端品牌海报",
      type: "style",
      provider: "internal",
      model_family: "seedream-4.5",
      cover_url: null,
      category: "我的风格",
      tags: ["我的风格"],
      keywords: "",
      description: "只影响背景、光影、版式和氛围。",
      commercial: false,
      runtime_mode: "prompt_style",
      effect_template_uuid: null,
      effect_id: null,
      use_count: 0,
      favorite: false,
      status: "enabled",
    });
    mockAigcStudioApi.deleteStyleTemplate.mockResolvedValue(undefined);
    mockAigcStudioApi.uploadAsset.mockResolvedValue({
      id: "asset-uploaded-cover",
      kind: "image",
      name: "uploaded-cover.png",
      path: "aigc/uploaded-cover.png",
      url: "/api/user/aigc-studio/assets/asset-uploaded-cover",
      mime_type: "image/png",
      created_at: "2026-06-25T00:00:00Z",
    });
  });

  it("submits composer data and starts the selected image node run", () => {
    const { onRunNode, workflow } = renderComposer();

    fireEvent.click(
      within(screen.getByTestId("aigc-image-composer")).getByRole("button", {
        name: "提交图片节点输入",
      }),
    );

    expect(workflow.handleImageComposerSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          composerText: "小姑娘",
          text: "小姑娘",
        }),
      }),
    );
    expect(onRunNode).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          text: "小姑娘",
          lastRunPrompt: "小姑娘",
        }),
      }),
    );
  });

  it("keeps pointer events inside the composer from reaching the canvas", () => {
    const canvasPointerDown = vi.fn();
    const node = imageNode();
    const workflow = {
      handleImageUpload: vi.fn(),
      handleImageToImageUpload: vi.fn(),
      handleImageUpscaleUpload: vi.fn(),
      handleImageComposerSubmit: vi.fn((submittedNode: AigcCanvasNode) => ({
        ...submittedNode,
        data: {
          ...submittedNode.data,
          text: "小姑娘",
          lastRunPrompt: "小姑娘",
        },
      })),
      handleImageCaptureGroup: vi.fn(),
      handleGeneratedImageSendToImage: vi.fn(),
      handleGeneratedImageAnnotate: vi.fn(),
      handleGeneratedImageSetPrimary: vi.fn(),
      handleGeneratedImageToggleResults: vi.fn(),
      handleImageCaptureGroupSendToImage: vi.fn(),
      handleImageCaptureGroupSelect: vi.fn(),
      handleImageSlashCommand: vi.fn(),
    };
    const onRunNode = vi.fn();

    render(
      <div onPointerDown={canvasPointerDown}>
        <ImageComposer
          node={node}
          imageComposerMenu={null}
          currentModel={imageModel}
          modelOptions={[imageModel]}
          currentModelKey="volcengine:seedream-5"
          t={t}
          workflow={workflow}
          disabled={false}
          onUpdateNodeData={vi.fn()}
          onRunNode={onRunNode}
          onToggleMenu={vi.fn()}
          onSelectModel={vi.fn()}
          onCloseMenu={vi.fn()}
        />
      </div>,
    );

    const submit = within(screen.getByTestId("aigc-image-composer")).getByRole(
      "button",
      { name: "提交图片节点输入" },
    );
    fireEvent.pointerDown(submit);
    fireEvent.click(submit);

    expect(canvasPointerDown).not.toHaveBeenCalled();
    expect(onRunNode).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          text: "小姑娘",
          lastRunPrompt: "小姑娘",
        }),
      }),
    );
  });

  it("renders aspect ratio preview icons with the matching shape", () => {
    renderComposer({
      imageComposerMenu: { nodeId: "image-1", menu: "size" },
      node: imageNode({ aspectRatio: "16:9" }),
    });

    const menu = screen.getByTestId("aigc-image-size-menu");
    const wideIcon = within(menu)
      .getByRole("button", { name: "16:9" })
      .querySelector("span");
    const tallIcon = within(menu)
      .getByRole("button", { name: "9:16" })
      .querySelector("span");

    expect(wideIcon).toHaveStyle({ width: "18px", height: "10px" });
    expect(tallIcon).toHaveStyle({ width: "7px", height: "12px" });
  });

  it("keeps an image settings menu open while options are selected", () => {
    const onUpdateNodeData = vi.fn();
    const onCloseMenu = vi.fn();
    renderComposer({
      imageComposerMenu: { nodeId: "image-1", menu: "size" },
      node: imageNode({ aspectRatio: "16:9" }),
      onUpdateNodeData,
      onCloseMenu,
    });

    const menu = screen.getByTestId("aigc-image-size-menu");
    fireEvent.click(within(menu).getByRole("button", { name: "9:16" }));

    expect(onUpdateNodeData).toHaveBeenLastCalledWith("image-1", {
      aspectRatio: "9:16",
    });
    expect(onCloseMenu).not.toHaveBeenCalled();
  });

  it("closes an open option menu when the composer input is clicked", () => {
    const onCloseMenu = vi.fn();
    renderComposer({
      imageComposerMenu: { nodeId: "image-1", menu: "size" },
      onCloseMenu,
    });

    fireEvent.mouseDown(screen.getByLabelText("图片节点输入"));

    expect(onCloseMenu).toHaveBeenCalledTimes(1);
  });

  it("shows model menu runtime badges from the shared image estimate", () => {
    renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model, gptImage2Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
      imageComposerMenu: { nodeId: "image-1", menu: "model" },
      node: imageNode({ resolution: "2K", imageCount: 1 }),
    });

    const menu = screen.getByTestId("aigc-image-model-menu");
    expect(
      within(menu).getByRole("button", { name: /Seedream 4.5/ }),
    ).toHaveTextContent("30s");
    expect(
      within(menu).getByRole("button", { name: /GPT Image 2/ }),
    ).toHaveTextContent("40s");
    expect(menu).not.toHaveTextContent("GPT Image 2 - MXAPI");
    expect(menu).not.toHaveTextContent("50s");
    expect(menu).not.toHaveTextContent("20s");
  });

  it("shows all configured image models in the model menu", () => {
    const models = Array.from({ length: 9 }, (_, index) => ({
      ...imageModel,
      model_id: `seedream-${index + 1}`,
      model_name: `Seedream ${index + 1}`,
    }));

    renderComposer({
      currentModel: models[0],
      modelOptions: models,
      currentModelKey: "volcengine:seedream-1",
      imageComposerMenu: { nodeId: "image-1", menu: "model" },
    });

    expect(
      within(screen.getByTestId("aigc-image-model-menu")).getByRole("button", {
        name: /Seedream 9/,
      }),
    ).toBeInTheDocument();
  });

  it("hides relay suffixes from the selected GPT Image 2 model label", () => {
    renderComposer({
      currentModel: gptImage2Model,
      modelOptions: [gptImage2Model],
      currentModelKey: "mxapi:gpt-image-2",
    });

    const composer = screen.getByTestId("aigc-image-composer");
    expect(
      within(composer).getByRole("button", { name: /GPT Image 2/ }),
    ).toBeInTheDocument();
    expect(composer).not.toHaveTextContent("GPT Image 2 - MXAPI");
  });

  it("renders the compact Seedream 4.5 parameter surface", () => {
    renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
      imageComposerMenu: { nodeId: "image-1", menu: "size" },
      node: imageNode({
        aspectRatio: "2:1",
        imageQuality: "高画质",
        resolution: "1K",
        webSearch: true,
        cameraBody: "Panavision DXL2",
        stylePreset: "电影感",
        markPreset: "主体区域",
        focusPreset: "主体清晰",
      }),
    });

    const composer = screen.getByTestId("aigc-image-composer");
    expect(composer).toHaveTextContent("16:9 · 2K");
    expect(
      within(composer).getByRole("button", { name: "风格" }),
    ).toBeInTheDocument();
    expect(
      within(composer).queryByRole("button", { name: "标记" }),
    ).not.toBeInTheDocument();
    expect(
      within(composer).queryByRole("button", { name: "聚焦" }),
    ).not.toBeInTheDocument();
    expect(
      within(composer).queryByRole("button", { name: "720全景" }),
    ).not.toBeInTheDocument();
    expect(
      within(composer).queryByRole("button", { name: /镜头/ }),
    ).not.toBeInTheDocument();
    expect(
      within(composer).queryByRole("button", { name: "高级设置" }),
    ).not.toBeInTheDocument();
    expect(composer).not.toHaveTextContent("✦ 14");

    const sizeMenu = screen.getByTestId("aigc-image-size-menu");
    expect(
      within(sizeMenu).queryByRole("button", { name: "高画质" }),
    ).not.toBeInTheDocument();
    expect(
      within(sizeMenu).queryByRole("button", { name: "1K" }),
    ).not.toBeInTheDocument();
    expect(
      within(sizeMenu).queryByRole("button", { name: "2:1" }),
    ).not.toBeInTheDocument();
    expect(
      within(sizeMenu).getByRole("button", { name: "2K" }),
    ).toBeInTheDocument();
    expect(
      within(sizeMenu).getByRole("button", { name: "4K" }),
    ).toBeInTheDocument();
    expect(
      within(sizeMenu).getByRole("button", { name: "21:9" }),
    ).toBeInTheDocument();
  });

  it("shows four prompt rows by default in the image composer", () => {
    renderComposer();

    const promptInput = screen.getByLabelText("图片节点输入");

    expect(promptInput).toHaveAttribute("rows", "4");
  });

  it("opens a fullscreen prompt editor from the composer and syncs edits back", () => {
    const { onUpdateNodeData } = renderComposer({
      node: imageNode({ composerText: "原始提示词" }),
    });

    const composer = screen.getByTestId("aigc-image-composer");
    fireEvent.click(
      within(composer).getByRole("button", { name: "全屏编辑输入" }),
    );

    const dialog = screen.getByRole("dialog", {
      name: "图片节点输入全屏编辑",
    });
    expect(document.body).toContainElement(dialog);
    expect(composer).not.toContainElement(dialog);

    const fullscreenInput =
      within(dialog).getByLabelText("图片节点输入全屏编辑");
    expect(fullscreenInput).toHaveValue("原始提示词");

    fireEvent.change(fullscreenInput, {
      target: { value: "全屏里修改后的提示词" },
    });

    expect(onUpdateNodeData).toHaveBeenLastCalledWith("image-1", {
      composerText: "全屏里修改后的提示词",
      text: "全屏里修改后的提示词",
    });
    expect(screen.getByLabelText("图片节点输入")).toHaveValue(
      "全屏里修改后的提示词",
    );
    fireEvent.click(
      within(dialog).getByRole("button", { name: "关闭全屏编辑" }),
    );
    expect(
      screen.queryByRole("dialog", { name: "图片节点输入全屏编辑" }),
    ).not.toBeInTheDocument();
  });

  it("opens the style gallery as an overlay dialog and selects template effect metadata from the backend", async () => {
    const { onUpdateNodeData } = renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
    });

    fireEvent.click(screen.getByRole("button", { name: "风格" }));

    const dialog = screen.getByRole("dialog", { name: "风格广场" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByTestId("aigc-image-composer")).not.toContainElement(
      dialog,
    );
    await waitFor(() => {
      expect(mockAigcStudioApi.listStyleTemplates).toHaveBeenCalledWith(
        expect.objectContaining({
          model_family: "seedream-4.5",
        }),
      );
    });
    fireEvent.click(
      await within(dialog).findByRole("button", { name: "一键国漫CGV2" }),
    );

    expect(onUpdateNodeData).toHaveBeenCalledWith(
      "image-1",
      expect.objectContaining({
        activeTool: null,
        styleTemplateId: "style-cgv2",
        styleRuntimeMode: "native_effect",
        stylePreset: "一键国漫CGV2",
        styleReferenceThumb: true,
        styleReferenceName: "一键国漫CGV2",
        styleTemplateUuid: "dbc6dfc0990d46d28215bcdff87d53c3",
        effectTemplateUuids: ["dbc6dfc0990d46d28215bcdff87d53c3"],
        effectId: 22910748,
        effects: [22910748],
        styleKeywords: expect.stringContaining("国漫"),
        styleDescription: expect.stringContaining("CG"),
      }),
    );
    expect(mockAigcStudioApi.markStyleTemplateUsed).toHaveBeenCalledWith(
      "style-cgv2",
    );
  });

  it("does not show current-style state when the style library is opened from the canvas rail", async () => {
    renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
      node: imageNode({
        activeTool: "style",
        stylePreset: "一键国漫CGV2",
        styleTemplateId: "style-cgv2",
        styleTemplateUuid: "dbc6dfc0990d46d28215bcdff87d53c3",
      }),
    });

    const dialog = screen.getByRole("dialog", { name: "风格广场" });
    const styleCard = await within(dialog).findByLabelText(
      "风格卡片 一键国漫CGV2",
    );

    expect(within(styleCard).queryByText("当前使用")).not.toBeInTheDocument();
  });

  it("shows current-style state when the style gallery is opened from the composer style control", async () => {
    renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
      node: imageNode({
        stylePreset: "一键国漫CGV2",
        styleTemplateId: "style-cgv2",
        styleTemplateUuid: "dbc6dfc0990d46d28215bcdff87d53c3",
      }),
    });

    fireEvent.click(screen.getByRole("button", { name: "风格" }));
    const dialog = screen.getByRole("dialog", { name: "风格广场" });
    const styleCard = await within(dialog).findByLabelText(
      "风格卡片 一键国漫CGV2",
    );

    expect(within(styleCard).getByText("当前使用")).toBeInTheDocument();
  });

  it("does not treat a legacy style prompt template as image content", async () => {
    const promptTemplate =
      "画面主体：{产品/人物}\n品牌名称：{品牌名称}\n主标题：{主标题}\n卖点1：{卖点1}";
    mockAigcStudioApi.listStyleTemplates.mockResolvedValue({
      templates: [
        {
          id: "style-brand-strength-poster",
          title: "高端品牌实力海报",
          type: "style",
          provider: "internal",
          model_family: "seedream-4.5",
          cover_url: null,
          category: "海报场景",
          tags: ["海报场景", "商用"],
          keywords: "品牌实力, 工厂, 产品背书",
          description: "高端品牌实力海报风格",
          prompt_template: promptTemplate,
          commercial: true,
          runtime_mode: "prompt_style",
          effect_template_uuid: null,
          effect_id: null,
          use_count: 7,
          favorite: false,
          status: "enabled",
        },
      ],
    });
    const { onUpdateNodeData } = renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
    });

    fireEvent.click(screen.getByRole("button", { name: "风格" }));
    const gallery = screen.getByRole("dialog", { name: "风格广场" });
    fireEvent.click(
      await within(gallery).findByRole("button", {
        name: "高端品牌实力海报",
      }),
    );

    const selectionCall = onUpdateNodeData.mock.calls.find(
      ([nodeId, patch]) =>
        nodeId === "image-1" &&
        patch &&
        typeof patch === "object" &&
        "styleTemplateId" in patch,
    );
    expect(selectionCall?.[1]).toEqual(
      expect.objectContaining({
        activeTool: null,
        styleTemplateId: "style-brand-strength-poster",
        styleRuntimeMode: "prompt_style",
        stylePreset: "高端品牌实力海报",
        stylePromptTemplate: "",
      }),
    );
    expect(selectionCall?.[1]).not.toHaveProperty("composerText");
    expect(
      screen.queryByRole("dialog", { name: "使用创作模板？" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("aigc-image-slash-menu"),
    ).not.toBeInTheDocument();
    expect(mockAigcStudioApi.markStyleTemplateUsed).toHaveBeenCalledWith(
      "style-brand-strength-poster",
    );
  });

  it("fills image content from the separate creation-template entry", async () => {
    const promptTemplate =
      "画面主体：{产品/人物}\n品牌名称：{品牌名称}\n主标题：{主标题}";
    mockAigcStudioApi.listStyleTemplates.mockImplementation(async (params) => ({
      templates:
        params.type === "play"
          ? [
              {
                id: "style-brand-strength-poster",
                title: "高端品牌实力海报",
                type: "play" as const,
                provider: "internal",
                model_family: "seedream-4.5",
                cover_url: null,
                category: "海报场景",
                tags: ["海报场景", "商用"],
                keywords: "品牌实力, 工厂, 产品背书",
                description: "高端品牌实力海报模板",
                prompt_template: promptTemplate,
                commercial: true,
                runtime_mode: "prompt_style" as const,
                effect_template_uuid: null,
                effect_id: null,
                use_count: 7,
                favorite: false,
                status: "enabled" as const,
              },
            ]
          : [],
    }));
    const { onUpdateNodeData } = renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
    });

    fireEvent.click(screen.getByRole("button", { name: "风格" }));
    const gallery = screen.getByRole("dialog", { name: "风格广场" });
    fireEvent.click(within(gallery).getByRole("button", { name: /创作模板/ }));
    fireEvent.click(
      await within(gallery).findByRole("button", {
        name: "高端品牌实力海报",
      }),
    );

    const promptDialog = await screen.findByRole("dialog", {
      name: "使用创作模板？",
    });
    expect(promptDialog).toHaveTextContent("不会改变当前审美风格");
    fireEvent.click(
      within(promptDialog).getByRole("button", { name: "回填模板" }),
    );

    expect(onUpdateNodeData).toHaveBeenCalledWith("image-1", {
      composerText: promptTemplate,
      creationTemplateId: "style-brand-strength-poster",
      creationTemplateName: "高端品牌实力海报",
      activeTool: null,
      inputUpdated: true,
    });
    expect(mockAigcStudioApi.listStyleTemplates).toHaveBeenCalledWith(
      expect.objectContaining({ type: "play" }),
    );
  });

  it("does not show slash commands for plain prompt text that contains slash characters", () => {
    renderComposer({
      node: imageNode({
        composerText: "画面主体：{产品/人物}\n参考图说明：包装/人物关系",
      }),
    });

    expect(
      screen.queryByTestId("aigc-image-slash-menu"),
    ).not.toBeInTheDocument();
  });

  it("lets @素材 insert an ordered reference alias and keep the asset binding", async () => {
    const { onUpdateNodeData } = renderComposer({
      node: imageNode({ composerText: "" }),
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

    const input = screen.getByLabelText("图片节点输入");
    fireEvent.change(input, { target: { value: "参考 @" } });

    const option = await screen.findByRole("button", {
      name: /图片1.*包装正面/,
    });
    fireEvent.click(option);

    expect(onUpdateNodeData).toHaveBeenLastCalledWith(
      "image-1",
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

  it("lets inline @ mention connected text references in Chinese prompts", async () => {
    const { onUpdateNodeData } = renderComposer({
      node: imageNode({ composerText: "" }),
      referenceAssets: [
        {
          id: "prompt-1",
          alias: "文本1",
          name: "文本节点",
          previewUrl: "",
          sourceNodeId: "prompt-1",
          kind: "text",
          text: "小明上课睡觉被老师抓到。",
        },
      ],
    });

    const input = screen.getByLabelText("图片节点输入");
    fireEvent.change(input, { target: { value: "做一张背景图，把文章@" } });

    const option = await screen.findByRole("button", {
      name: /文本1.*文本节点/,
    });
    fireEvent.click(option);

    expect(onUpdateNodeData).toHaveBeenLastCalledWith(
      "image-1",
      expect.objectContaining({
        composerText: "做一张背景图，把文章@文本1 ",
        referencedAssets: [
          expect.objectContaining({
            alias: "文本1",
            kind: "text",
            sourceNodeId: "prompt-1",
            text: "小明上课睡觉被老师抓到。",
          }),
        ],
        inputUpdated: true,
      }),
    );
  });

  it("allows repeatedly dragging the same reference while keeping one binding", async () => {
    const { onUpdateNodeData } = renderComposer({
      node: imageNode({ composerText: "生成海报" }),
      referenceAssets: [
        {
          id: "prompt-1",
          alias: "文本1",
          name: "文案节点",
          previewUrl: "",
          sourceNodeId: "prompt-1",
          kind: "text",
          text: "品牌文案",
        },
      ],
    });
    const thumb = screen.getByTestId("aigc-image-reference-thumb");
    const input = screen.getByLabelText("图片节点输入") as HTMLTextAreaElement;
    const dataTransfer = createReferenceDataTransfer();
    input.setSelectionRange(input.value.length, input.value.length);

    fireEvent.dragStart(thumb, { dataTransfer });
    fireEvent.dragOver(input, { dataTransfer });
    fireEvent.drop(input, { dataTransfer });

    await waitFor(() => expect(input).toHaveValue("生成海报 @文本1 "));

    const secondDataTransfer = createReferenceDataTransfer();
    input.setSelectionRange(input.value.length, input.value.length);
    fireEvent.dragStart(thumb, { dataTransfer: secondDataTransfer });
    fireEvent.dragOver(input, { dataTransfer: secondDataTransfer });
    fireEvent.drop(input, { dataTransfer: secondDataTransfer });

    await waitFor(() =>
      expect(onUpdateNodeData).toHaveBeenLastCalledWith(
        "image-1",
        expect.objectContaining({
          composerText: "生成海报 @文本1 @文本1 ",
          text: "生成海报 @文本1 @文本1 ",
          referencedAssets: [
            expect.objectContaining({
              alias: "文本1",
              kind: "text",
              sourceNodeId: "prompt-1",
            }),
          ],
          inputUpdated: true,
        }),
      ),
    );
  });

  it("grows the prompt textarea to fit its content without a height cap", () => {
    const scrollHeight = vi
      .spyOn(HTMLTextAreaElement.prototype, "scrollHeight", "get")
      .mockReturnValue(384);

    renderComposer({ node: imageNode({ composerText: "多行提示词" }) });

    expect(screen.getByLabelText("图片节点输入")).toHaveStyle({
      height: "384px",
      overflowY: "hidden",
    });
    scrollHeight.mockRestore();
  });

  it("loads favorites and recent style tabs from their dedicated endpoints", async () => {
    mockAigcStudioApi.listFavoriteStyleTemplates.mockResolvedValue({
      templates: [
        {
          id: "style-favorite",
          title: "收藏海报",
          type: "style",
          provider: "internal",
          model_family: "seedream-4.5",
          cover_url: null,
          category: "海报场景",
          tags: ["海报场景"],
          keywords: "收藏",
          description: "收藏的海报风格",
          commercial: true,
          runtime_mode: "prompt_style",
          effect_template_uuid: null,
          effect_id: null,
          use_count: 2,
          favorite: true,
          status: "enabled",
        },
      ],
    });
    mockAigcStudioApi.listRecentStyleTemplates.mockResolvedValue({
      templates: [
        {
          id: "style-recent",
          title: "最近使用海报",
          type: "style",
          provider: "internal",
          model_family: "seedream-4.5",
          cover_url: null,
          category: "海报场景",
          tags: ["海报场景"],
          keywords: "最近",
          description: "最近使用的海报风格",
          commercial: true,
          runtime_mode: "prompt_style",
          effect_template_uuid: null,
          effect_id: null,
          use_count: 3,
          favorite: false,
          status: "enabled",
        },
      ],
    });

    renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
    });

    fireEvent.click(screen.getByRole("button", { name: "风格" }));
    const dialog = screen.getByRole("dialog", { name: "风格广场" });
    fireEvent.click(within(dialog).getByRole("button", { name: "我的收藏" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.listFavoriteStyleTemplates).toHaveBeenCalled();
    });
    expect(
      await within(dialog).findByRole("button", { name: "收藏海报" }),
    ).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "最近使用" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.listRecentStyleTemplates).toHaveBeenCalled();
    });
    expect(
      await within(dialog).findByRole("button", { name: "最近使用海报" }),
    ).toBeInTheDocument();
  });

  it("filters the style gallery by category and search without commercial-only UI", async () => {
    renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
    });

    fireEvent.click(screen.getByRole("button", { name: "风格" }));
    const dialog = screen.getByRole("dialog", { name: "风格广场" });
    expect(within(dialog).queryByText("仅看可商用")).not.toBeInTheDocument();

    mockAigcStudioApi.listStyleTemplates.mockClear();
    fireEvent.click(within(dialog).getByRole("button", { name: "海报场景" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.listStyleTemplates).toHaveBeenCalledWith(
        expect.objectContaining({
          category: "海报场景",
          q: "",
        }),
      );
    });

    fireEvent.change(
      within(dialog).getByPlaceholderText("搜索风格名称、作者"),
      {
        target: { value: "品牌" },
      },
    );

    await waitFor(() => {
      expect(mockAigcStudioApi.listStyleTemplates).toHaveBeenCalledWith(
        expect.objectContaining({
          category: "海报场景",
          q: "品牌",
        }),
      );
    });
  });

  it("toggles style template favorites from each style card", async () => {
    renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
    });

    fireEvent.click(screen.getByRole("button", { name: "风格" }));
    const dialog = screen.getByRole("dialog", { name: "风格广场" });
    const styleCard = await within(dialog).findByLabelText(
      "风格卡片 一键国漫CGV2",
    );
    fireEvent.click(
      within(styleCard).getByRole("button", { name: "收藏风格 一键国漫CGV2" }),
    );

    await waitFor(() => {
      expect(
        mockAigcStudioApi.updateStyleTemplateFavorite,
      ).toHaveBeenCalledWith("style-cgv2", true);
    });
  });

  it("renders style template cover images in the gallery grid", async () => {
    mockAigcStudioApi.listStyleTemplates.mockResolvedValue({
      templates: [
        {
          id: "style-covered",
          title: "带封面风格",
          type: "style",
          provider: "internal",
          model_family: "seedream-4.5",
          cover_url: "https://cdn.example.test/style-cover.png",
          category: "我的风格",
          tags: ["我的风格"],
          keywords: "",
          description: "有封面的风格",
          commercial: false,
          runtime_mode: "prompt_style",
          effect_template_uuid: null,
          effect_id: null,
          use_count: 0,
          favorite: false,
          status: "enabled",
        },
      ],
    });

    renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
    });

    fireEvent.click(screen.getByRole("button", { name: "风格" }));
    const dialog = screen.getByRole("dialog", { name: "风格广场" });
    const styleCard = await within(dialog).findByLabelText(
      "风格卡片 带封面风格",
    );

    expect(within(styleCard).getByAltText("带封面风格")).toHaveAttribute(
      "src",
      "https://cdn.example.test/style-cover.png",
    );
  });

  it("selects a new style template without removing the generated image output", async () => {
    const generatedOutput = {
      id: "asset-1",
      kind: "image",
      name: "generated.png",
      path: "aigc/generated.png",
      url: "/api/user/aigc-studio/assets/asset-1",
      created_at: "2026-06-24T00:00:00Z",
    };
    const { onUpdateNodeData } = renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
      node: imageNode({
        text: "少女",
        imageState: "generated",
        job_status: "succeeded",
        outputs: [generatedOutput],
      }),
    });

    fireEvent.click(screen.getByRole("button", { name: "风格" }));
    const dialog = screen.getByRole("dialog", { name: "风格广场" });
    fireEvent.click(
      await within(dialog).findByRole("button", { name: "一键国漫CGV2" }),
    );

    const [, update] = onUpdateNodeData.mock.calls.find(
      ([nodeId, data]) =>
        nodeId === "image-1" &&
        data &&
        typeof data === "object" &&
        "styleTemplateId" in data,
    )!;

    expect(update).toMatchObject({
      activeTool: null,
      styleTemplateId: "style-cgv2",
      stylePreset: "一键国漫CGV2",
      inputUpdated: true,
    });
    expect(update).not.toHaveProperty("outputs");
    expect(update).not.toHaveProperty("imageState");
    expect(update).not.toHaveProperty("job_status");
  });

  it("clears the selected style without removing the generated image output", () => {
    const generatedOutput = {
      id: "asset-1",
      kind: "image",
      name: "generated.png",
      path: "aigc/generated.png",
      url: "/api/user/aigc-studio/assets/asset-1",
      created_at: "2026-06-24T00:00:00Z",
    };
    const { onUpdateNodeData } = renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
      node: imageNode({
        stylePreset: "一键国漫CGV2",
        styleRuntimeMode: "native_effect",
        styleTemplateId: "style-cgv2",
        imageState: "succeeded",
        job_status: "succeeded",
        outputs: [generatedOutput],
      }),
    });

    fireEvent.click(screen.getByRole("button", { name: "清除风格" }));

    expect(onUpdateNodeData).toHaveBeenCalledWith(
      "image-1",
      expect.objectContaining({
        stylePreset: null,
        styleTemplateId: null,
        styleRuntimeMode: null,
        inputUpdated: true,
      }),
    );
    expect(onUpdateNodeData).not.toHaveBeenCalledWith(
      "image-1",
      expect.objectContaining({
        outputs: [],
      }),
    );
    expect(onUpdateNodeData).not.toHaveBeenCalledWith(
      "image-1",
      expect.objectContaining({
        imageState: "editing",
      }),
    );
  });

  it("creates an aesthetic profile from global DNA and applies an immutable snapshot", async () => {
    const generatedOutput = {
      id: "asset-cover",
      kind: "image",
      name: "cover.png",
      path: "aigc/cover.png",
      url: "/api/user/aigc-studio/assets/asset-cover",
      created_at: "2026-06-24T00:00:00Z",
    };
    const { onUpdateNodeData } = renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
      node: imageNode({
        imageState: "generated",
        outputs: [generatedOutput],
      }),
    });

    fireEvent.click(screen.getByRole("button", { name: "风格" }));
    const dialog = screen.getByRole("dialog", { name: "风格广场" });
    fireEvent.click(within(dialog).getByRole("button", { name: "创建风格" }));
    fireEvent.change(within(dialog).getByLabelText("风格名称"), {
      target: { value: "国漫 CG 风格" },
    });
    fireEvent.change(within(dialog).getByLabelText("风格补充说明（可选）"), {
      target: {
        value: "国漫 CG 风格，强化角色轮廓和冷色调光影。",
      },
    });
    expect(
      within(dialog).queryByLabelText("画面提示词模板"),
    ).not.toBeInTheDocument();
    const visualDnaBuilder = within(dialog).getByRole("region", {
      name: "审美 DNA",
    });
    fireEvent.click(
      await within(visualDnaBuilder).findByRole("button", {
        name: "选择审美元素 电影级戏剧光影",
      }),
    );
    fireEvent.click(
      within(visualDnaBuilder).getByRole("button", {
        name: "电影级戏剧光影影响强度：强",
      }),
    );
    expect(
      within(visualDnaBuilder).queryByRole("button", { name: /镜头/ }),
    ).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "保存风格" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.createStyleTemplate).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "国漫 CG 风格",
          description: "国漫 CG 风格，强化角色轮廓和冷色调光影。",
          supplemental_prompt: "国漫 CG 风格，强化角色轮廓和冷色调光影。",
          prompt_template: "",
          category: "我的风格",
          tags: ["我的风格"],
          model_family: null,
          provider: "internal",
          runtime_mode: "prompt_style",
          cover_url: "/api/user/aigc-studio/assets/asset-cover/file",
          visual_dna: [
            {
              element_id: "lighting.cinematic_contrast",
              weight: 0.9,
            },
          ],
          reference_image_urls: [],
          profile_version: "1.0",
        }),
      );
    });
    await waitFor(() => {
      expect(onUpdateNodeData).toHaveBeenCalledWith(
        "image-1",
        expect.objectContaining({
          activeTool: null,
          styleTemplateId: "style-custom-guoman",
          styleRuntimeMode: "prompt_style",
          stylePreset: "国漫 CG 风格",
          styleReferenceName: "国漫 CG 风格",
          styleDescription: "国漫 CG 风格，强化角色轮廓和冷色调光影。",
          styleSupplementalPrompt: "国漫 CG 风格，强化角色轮廓和冷色调光影。",
          visualDna: [
            { element_id: "lighting.cinematic_contrast", weight: 0.9 },
          ],
          aestheticProfileSnapshot: expect.objectContaining({
            id: "style-custom-guoman",
            version: "1.0",
            visual_dna: [
              { element_id: "lighting.cinematic_contrast", weight: 0.9 },
            ],
          }),
        }),
      );
    });
  });

  it("keeps the gallery cover separate from generation reference images", async () => {
    mockAigcStudioApi.uploadAsset.mockImplementation(async (file: File) => {
      const slug = file.name.includes("style-reference")
        ? "style-reference"
        : "uploaded-cover";
      return {
        id: `asset-${slug}`,
        kind: "image",
        name: file.name,
        path: `aigc/${slug}.png`,
        url: `/api/user/aigc-studio/assets/asset-${slug}`,
        mime_type: "image/png",
        size: file.size,
        created_at: "2026-06-24T00:00:00Z",
      };
    });
    renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
    });

    fireEvent.click(screen.getByRole("button", { name: "风格" }));
    const dialog = screen.getByRole("dialog", { name: "风格广场" });
    fireEvent.click(within(dialog).getByRole("button", { name: "创建风格" }));
    fireEvent.change(within(dialog).getByLabelText("风格名称"), {
      target: { value: "高端品牌海报" },
    });
    fireEvent.change(within(dialog).getByLabelText("风格补充说明（可选）"), {
      target: {
        value: "高端品牌海报，工厂纵深，香槟金点缀。",
      },
    });
    fireEvent.change(within(dialog).getByLabelText("应用场景"), {
      target: { value: "海报场景" },
    });
    fireEvent.change(within(dialog).getByLabelText("上传卡片封面"), {
      target: {
        files: [
          new File(["cover"], "uploaded-cover.png", { type: "image/png" }),
        ],
      },
    });
    fireEvent.change(within(dialog).getByLabelText("上传风格参考图"), {
      target: {
        files: [
          new File(["reference"], "style-reference.png", {
            type: "image/png",
          }),
        ],
      },
    });

    await waitFor(() => {
      expect(mockAigcStudioApi.uploadAsset).toHaveBeenCalledTimes(2);
    });

    fireEvent.click(within(dialog).getByRole("button", { name: "保存风格" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.createStyleTemplate).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "高端品牌海报",
          description: "高端品牌海报，工厂纵深，香槟金点缀。",
          supplemental_prompt: "高端品牌海报，工厂纵深，香槟金点缀。",
          prompt_template: "",
          category: "海报场景",
          tags: ["海报场景"],
          cover_url: "/api/user/aigc-studio/assets/asset-uploaded-cover/file",
          reference_image_urls: [
            "/api/user/aigc-studio/assets/asset-style-reference/file",
          ],
        }),
      );
    });
  });

  it("edits a user prompt style template from the style gallery", async () => {
    mockAigcStudioApi.listStyleTemplates.mockResolvedValue({
      templates: [
        {
          id: "style-custom-brand",
          title: "旧品牌海报",
          type: "style",
          provider: "internal",
          model_family: "seedream-4.5",
          cover_url: null,
          category: "我的风格",
          tags: ["我的风格"],
          keywords: "",
          description: "旧提示词",
          supplemental_prompt: "旧补充说明",
          visual_dna: [
            { element_id: "lighting.cinematic_contrast", weight: 0.6 },
          ],
          commercial: false,
          runtime_mode: "prompt_style",
          effect_template_uuid: null,
          effect_id: null,
          use_count: 0,
          favorite: false,
          status: "enabled",
        },
      ],
    });

    renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
    });

    fireEvent.click(screen.getByRole("button", { name: "风格" }));
    const dialog = screen.getByRole("dialog", { name: "风格广场" });
    const styleCard = await within(dialog).findByLabelText(
      "风格卡片 旧品牌海报",
    );
    fireEvent.click(
      within(styleCard).getByRole("button", { name: "编辑风格 旧品牌海报" }),
    );
    fireEvent.change(within(dialog).getByLabelText("风格补充说明（可选）"), {
      target: {
        value: "只影响背景、光影、版式和氛围。",
      },
    });
    fireEvent.change(within(dialog).getByLabelText("风格名称"), {
      target: {
        value: "高端品牌海报",
      },
    });
    const visualDnaBuilder = within(dialog).getByRole("region", {
      name: "审美 DNA",
    });
    expect(
      await within(visualDnaBuilder).findByRole("button", {
        name: "取消审美元素 电影级戏剧光影",
      }),
    ).toBeInTheDocument();
    fireEvent.click(
      within(visualDnaBuilder).getByRole("button", {
        name: "电影级戏剧光影影响强度：强",
      }),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "保存修改" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.updateStyleTemplate).toHaveBeenCalledWith(
        "style-custom-brand",
        expect.objectContaining({
          title: "高端品牌海报",
          description: "只影响背景、光影、版式和氛围。",
          supplemental_prompt: "只影响背景、光影、版式和氛围。",
          category: "我的风格",
          tags: ["我的风格"],
          provider: "internal",
          runtime_mode: "prompt_style",
          visual_dna: [
            {
              element_id: "lighting.cinematic_contrast",
              weight: 0.9,
            },
          ],
        }),
      );
    });
  });

  it("keeps built-in prompt style templates read-only for ordinary users", async () => {
    mockAigcStudioApi.listStyleTemplates.mockResolvedValue({
      templates: [
        {
          id: "style-brand-strength-poster",
          title: "高端品牌实力海报",
          type: "style",
          provider: "internal",
          model_family: "seedream-4.5",
          cover_url: null,
          category: "海报场景",
          tags: ["海报场景", "商用"],
          keywords: "品牌实力, 工厂, 产品背书",
          description: "系统提示词",
          commercial: true,
          runtime_mode: "prompt_style",
          effect_template_uuid: null,
          effect_id: null,
          use_count: 0,
          favorite: false,
          status: "enabled",
        },
      ],
    });

    renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
    });

    fireEvent.click(screen.getByRole("button", { name: "风格" }));
    const dialog = screen.getByRole("dialog", { name: "风格广场" });
    const styleCard = await within(dialog).findByLabelText(
      "风格卡片 高端品牌实力海报",
    );

    expect(
      within(styleCard).queryByRole("button", {
        name: "编辑风格 高端品牌实力海报",
      }),
    ).not.toBeInTheDocument();
    expect(
      within(styleCard).queryByRole("button", {
        name: "删除风格 高端品牌实力海报",
      }),
    ).not.toBeInTheDocument();
  });

  it("lets admins edit built-in prompt style templates without reclassifying them", async () => {
    mockAuthState.role = "admin";
    const builtinTemplate = {
      id: "style-brand-strength-poster",
      title: "高端品牌实力海报",
      type: "style" as const,
      provider: "internal",
      model_family: "seedream-4.5",
      cover_url: null,
      category: "海报场景",
      tags: ["海报场景", "商用"],
      keywords: "品牌实力, 工厂, 产品背书",
      description: "系统提示词",
      supplemental_prompt: "",
      commercial: true,
      runtime_mode: "prompt_style" as const,
      effect_template_uuid: null,
      effect_id: null,
      use_count: 0,
      favorite: false,
      status: "enabled" as const,
    };
    mockAigcStudioApi.listStyleTemplates.mockResolvedValue({
      templates: [builtinTemplate],
    });
    mockAigcStudioApi.updateStyleTemplate.mockResolvedValue({
      ...builtinTemplate,
      title: "高端品牌实力海报 V2",
      description: "管理员新版提示词",
    });

    renderComposer({
      currentModel: seedream45Model,
      modelOptions: [seedream45Model],
      currentModelKey: "volcengine:doubao-seedream-4-5-251128",
    });

    fireEvent.click(screen.getByRole("button", { name: "风格" }));
    const dialog = screen.getByRole("dialog", { name: "风格广场" });
    const styleCard = await within(dialog).findByLabelText(
      "风格卡片 高端品牌实力海报",
    );
    expect(
      within(styleCard).getByRole("button", {
        name: "删除风格 高端品牌实力海报",
      }),
    ).toBeInTheDocument();
    fireEvent.click(
      within(styleCard).getByRole("button", {
        name: "编辑风格 高端品牌实力海报",
      }),
    );
    fireEvent.change(within(dialog).getByLabelText("风格补充说明（可选）"), {
      target: { value: "管理员新版审美补充说明" },
    });
    fireEvent.change(within(dialog).getByLabelText("风格名称"), {
      target: { value: "高端品牌实力海报 V2" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "保存修改" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.updateStyleTemplate).toHaveBeenCalledWith(
        "style-brand-strength-poster",
        expect.objectContaining({
          title: "高端品牌实力海报 V2",
          description: "管理员新版审美补充说明",
          supplemental_prompt: "管理员新版审美补充说明",
          category: "海报场景",
          tags: ["海报场景", "商用"],
          keywords: "品牌实力, 工厂, 产品背书",
          commercial: true,
          provider: "internal",
          runtime_mode: "prompt_style",
        }),
      );
    });
    expect(mockAigcStudioApi.updateStyleTemplate).not.toHaveBeenCalledWith(
      "style-brand-strength-poster",
      expect.objectContaining({
        category: "我的风格",
      }),
    );
  });

  it("renders the style template slot before ordinary image references", () => {
    renderComposer({
      node: imageNode({
        styleReferenceThumb: true,
        styleReferenceName: "一键国漫CGV2",
        styleReferencePreviewUrl: "/style-preview.png",
        referenceThumb: true,
        referenceAssetName: "portrait.png",
        referencePreviewUrl: "/portrait.png",
      }),
    });

    const tools = screen.getByTestId("aigc-image-composer-tools");
    const styleThumb = screen.getByTestId("aigc-image-style-thumb");
    const referenceThumb = screen.getByTestId("aigc-image-reference-thumb");

    expect(tools).toContainElement(styleThumb);
    expect(tools).toContainElement(referenceThumb);
    expect(
      styleThumb.compareDocumentPosition(referenceThumb) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("renders multiple ordinary reference thumbnails in alias order", () => {
    renderComposer({
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
      ],
    });

    const thumbs = screen.getAllByTestId("aigc-image-reference-thumb");

    expect(thumbs).toHaveLength(2);
    expect(thumbs[0]).toHaveTextContent("1");
    expect(thumbs[1]).toHaveTextContent("2");
  });

  it("shows reference badge numbers from each asset alias instead of global order", () => {
    renderComposer({
      referenceAssets: [
        {
          id: "prompt-1",
          alias: "文本1",
          name: "文本提示",
          previewUrl: "prompt",
          kind: "text",
        },
        {
          id: "asset-front",
          alias: "图片1",
          name: "包装正面",
          previewUrl: "/api/user/aigc-studio/assets/front/file",
        },
      ],
    });

    const thumbs = screen.getAllByTestId("aigc-image-reference-thumb");

    expect(thumbs).toHaveLength(2);
    expect(thumbs[0]).toHaveTextContent("1");
    expect(thumbs[1]).toHaveTextContent("1");
  });

  it("renders text references with a document icon instead of a broken image preview", () => {
    renderComposer({
      referenceAssets: [
        {
          id: "prompt-1",
          alias: "文本1",
          name: "prompt",
          previewUrl: "prompt",
          kind: "text",
        },
      ],
    });

    const thumb = screen.getByTestId("aigc-image-reference-thumb");

    expect(
      within(thumb).getByTestId("aigc-text-reference-icon"),
    ).toBeInTheDocument();
    expect(within(thumb).queryByRole("img")).not.toBeInTheDocument();
    expect(thumb).toHaveTextContent("1");
  });

  it("treats legacy prompt preview tokens as text reference thumbnails", () => {
    renderComposer({
      referenceAssets: [
        {
          id: "prompt-1",
          alias: "文本1",
          name: "prompt",
          previewUrl: "prompt",
        },
      ],
    });

    const thumb = screen.getByTestId("aigc-image-reference-thumb");

    expect(
      within(thumb).getByTestId("aigc-text-reference-icon"),
    ).toBeInTheDocument();
    expect(within(thumb).queryByRole("img")).not.toBeInTheDocument();
  });
});
