import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { message as antdMessage, Modal } from "antd";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AigcStudioPage from "./index";
import { SCRIPT_SHOTS } from "./components/ScriptNode/scriptNodeState";

const mockAigcStudioApi = vi.hoisted(() => ({
  listCapabilities: vi.fn(),
  listWorkflowCapabilities: vi.fn(),
  listVisualDnaDimensions: vi.fn(),
  listVisualDnaElements: vi.fn(),
  listStyleTemplates: vi.fn(),
  markStyleTemplateUsed: vi.fn(),
  listCanvases: vi.fn(),
  createCanvas: vi.fn(),
  saveCanvas: vi.fn(),
  deleteCanvas: vi.fn(),
  uploadAsset: vi.fn(),
  listJobs: vi.fn(),
  submitJob: vi.fn(),
  cancelJob: vi.fn(),
  retryJob: vi.fn(),
  runJob: vi.fn(),
  exportLongImage: vi.fn(),
}));

vi.mock("../../api/modules/aigcStudio", () => ({
  aigcStudioApi: mockAigcStudioApi,
}));

const originalCreateObjectUrl = URL.createObjectURL;
const originalRevokeObjectUrl = URL.revokeObjectURL;

const restoreUrlObjectMethods = () => {
  if (originalCreateObjectUrl) {
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: originalCreateObjectUrl,
    });
  } else {
    Reflect.deleteProperty(URL, "createObjectURL");
  }
  if (originalRevokeObjectUrl) {
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: originalRevokeObjectUrl,
    });
  } else {
    Reflect.deleteProperty(URL, "revokeObjectURL");
  }
};

const translations: Record<string, string> = {
  "aigcStudio.title": "AIGC 创意工作室",
  "aigcStudio.defaultName": "未命名 AIGC 画布",
  "aigcStudio.defaultNodes.prompt.title": "营销提示词",
  "aigcStudio.defaultNodes.prompt.text": "带有清晰品牌氛围的电影感产品片创意。",
  "aigcStudio.defaultNodes.image.title": "主视觉图片",
  "aigcStudio.defaultNodes.image.text": "基于选中的提示词生成图片变体。",
  "aigcStudio.defaultNodes.video.title": "动态片段",
  "aigcStudio.defaultNodes.video.text": "使用生成的关键帧和参考素材生成视频。",
  "aigcStudio.defaultNodes.reference.title": "参考素材板",
  "aigcStudio.defaultNodes.reference.text": "收集角色、物体、风格和品牌资产。",
  "aigcStudio.capability.text_to_image": "文生图",
  "aigcStudio.nodeType.video_generate": "视频生成",
  "aigcStudio.jobStatus.cancelled": "已取消",
  "aigcStudio.cancelJob": "取消",
  "aigcStudio.retryJob": "重试",
  "aigcStudio.runNode": "运行节点",
  "aigcStudio.addNode": "添加节点",
  "aigcStudio.templateHint": "双击画布 自由生成节点",
  "aigcStudio.minimap.fitAll": "适配全部",
  "aigcStudio.minimap.centerSelected": "回到选中",
  "aigcStudio.promptPlaceholder":
    "描述你想要生成的画面内容，按呼出指令，@引用素材",
  "aigcStudio.focus": "聚焦",
  "aigcStudio.imageNode.title": "图片节点",
  "aigcStudio.imageNode.upload": "上传参考图",
  "aigcStudio.imageNode.uploadLabel": "上传图片参考素材",
  "aigcStudio.imageNode.replaceSource": "替换参考图",
  "aigcStudio.imageNode.inputUpdated": "输入已更新",
  "aigcStudio.imageNode.composerLabel": "图片节点输入",
  "aigcStudio.imageNode.submitComposer": "提交图片节点输入",
  "aigcStudio.imageNode.advanced": "高级设置",
  "aigcStudio.imageNode.webSearch": "联网搜索",
  "aigcStudio.imageNode.resolution": "分辨率",
  "aigcStudio.imageNode.aspectRatio": "比例",
  "aigcStudio.imageNode.use": "使用",
  "aigcStudio.imageNode.modelHint": "照强图片编辑模型，一致性好",
  "aigcStudio.imageNode.countValue": "{{count}}张",
  "aigcStudio.imageNode.try.imageToImage": "图生图",
  "aigcStudio.imageNode.try.imageToImageUploadLabel": "上传图生图参考图",
  "aigcStudio.imageNode.try.upscaleUploadLabel": "上传高清放大原图",
  "aigcStudio.imageNode.try.upscale": "图片高清",
  "aigcStudio.imageNode.composer.imageToImage":
    "描述你想要生成的画面内容，按 / 呼出指令，@引用素材",
  "aigcStudio.imageNode.sources.image": "图片节点",
  "aigcStudio.imageNode.upscale.title": "高清",
  "aigcStudio.imageNode.upscale.placeholder": "配置参数生成高清图像",
  "aigcStudio.imageNode.upscale.panel": "高清放大",
  "aigcStudio.imageNode.upscale.provider": "模型选择",
  "aigcStudio.imageNode.upscale.modelLabel": "模型",
  "aigcStudio.imageNode.upscale.model": "通用",
  "aigcStudio.imageNode.upscale.portrait": "人像",
  "aigcStudio.imageNode.upscale.product": "商品",
  "aigcStudio.imageNode.upscale.factor": "放大倍数",
  "aigcStudio.videoNode.title": "视频节点",
  "aigcStudio.videoNode.upload": "上传",
  "aigcStudio.videoNode.uploadLabel": "上传视频素材",
  "aigcStudio.videoNode.composerLabel": "视频节点输入",
  "aigcStudio.videoNode.submitComposer": "提交视频节点输入",
  "aigcStudio.videoNode.advanced": "高级设置",
  "aigcStudio.videoNode.motion": "运镜",
  "aigcStudio.videoNode.characterLibrary": "角色库",
  "aigcStudio.videoNode.resolution": "清晰度",
  "aigcStudio.videoNode.duration": "视频时长",
  "aigcStudio.videoNode.generateAudio": "生成音频",
  "aigcStudio.videoNode.on": "开启",
  "aigcStudio.videoNode.off": "关闭",
  "aigcStudio.videoNode.preset": "预设",
  "aigcStudio.videoNode.custom": "自定义",
  "aigcStudio.videoNode.favorite": "我的收藏",
  "aigcStudio.videoNode.selected": "已选",
  "aigcStudio.videoNode.realPerson": "真人像",
  "aigcStudio.videoNode.image": "图片",
  "aigcStudio.videoNode.video": "视频",
  "aigcStudio.videoNode.audio": "音频",
  "aigcStudio.videoNode.localUpload": "本地上传",
  "aigcStudio.videoNode.historyAsset": "历史资产选择",
  "aigcStudio.videoNode.realPersonAsset": "真人资产录入",
  "aigcStudio.videoNode.uploadHint": "请上传<30M的图片",
  "aigcStudio.videoNode.countValue": "{{count}}个",
  "aigcStudio.videoNode.try.firstLast": "首尾帧生成视频",
  "aigcStudio.videoNode.try.firstFrame": "首帧生成视频",
  "aigcStudio.videoNode.try.firstLastUploadLabel": "上传首尾帧图片",
  "aigcStudio.videoNode.try.firstFrameUploadLabel": "上传首帧图片",
  "aigcStudio.videoNode.composer.placeholder":
    "描述你想要生成的画面内容，@引用素材",
  "aigcStudio.videoNode.composer.firstLast":
    "根据首尾帧与描述生成过渡自然的视频。",
  "aigcStudio.videoNode.composer.firstFrame": "以当前图为首帧生成视频。",
  "aigcStudio.videoNode.sources.firstFrame": "首帧",
  "aigcStudio.videoNode.sources.lastFrame": "尾帧",
  "aigcStudio.videoNode.tabs.text_to_video": "文生视频",
  "aigcStudio.videoNode.tabs.all_reference": "全能参考",
  "aigcStudio.videoNode.tabs.image_to_video": "图生视频",
  "aigcStudio.videoNode.tabs.first_frame": "首尾帧",
  "aigcStudio.videoNode.tabs.image_reference": "图片参考",
  "aigcStudio.textNode.title": "文本节点",
  "aigcStudio.textNode.placeholder": "输入内容...",
  "aigcStudio.textNode.tryTitle": "尝试：",
  "aigcStudio.textNode.try.write": "自己编写内容",
  "aigcStudio.textNode.try.textToVideo": "文生视频",
  "aigcStudio.textNode.try.imageToPrompt": "图片反推提示词",
  "aigcStudio.textNode.try.textToMusic": "文字生音乐",
  "aigcStudio.textNode.composer.write":
    "写下你想讲的故事、场景或角色设定。例如：一个来自未来的机器人，在城市屋顶看星星。",
  "aigcStudio.textNode.composer.textToVideo": "根据文字描述生成视频。",
  "aigcStudio.textNode.composer.imageToPrompt":
    "根据图片生成结构化中文提示词，包括主体描述、环境、光影、镜头语言、风格关键词。",
  "aigcStudio.textNode.composer.textToMusic": "描述您想要的音乐",
  "aigcStudio.textNode.editLabel": "文本内容",
  "aigcStudio.textNode.composerLabel": "文本节点输入",
  "aigcStudio.textNode.submitComposer": "提交文本节点输入",
  "aigcStudio.textNode.noModel": "未选择文本模型",
  "aigcStudio.textNode.generating": "文本生成中",
  "aigcStudio.textNode.missingModel":
    "当前文本节点没有可用模型，请先选择模型后再生成。",
  "aigcStudio.textNode.toolbar.clear": "清除格式",
  "aigcStudio.textNode.toolbar.h1": "一级标题",
  "aigcStudio.textNode.toolbar.h2": "二级标题",
  "aigcStudio.textNode.toolbar.h3": "三级标题",
  "aigcStudio.textNode.toolbar.paragraph": "段落",
  "aigcStudio.textNode.toolbar.bold": "加粗",
  "aigcStudio.textNode.toolbar.italic": "斜体",
  "aigcStudio.textNode.toolbar.list": "编号列表",
  "aigcStudio.textNode.toolbar.bullet": "项目列表",
  "aigcStudio.textNode.toolbar.rule": "插入分割线",
  "aigcStudio.textNode.toolbar.duplicate": "复制节点",
  "aigcStudio.textNode.toolbar.expand": "展开节点",
  "aigcStudio.textNode.samples.textToVideo":
    "高级广告镜头，黑色背景中一款高端腕表悬浮出现，镜头从极近距离微距开始，缓慢拉远，金属表面光泽细腻，细节清晰，柔光灯打亮轮廓，商业广告级质感，干净构图，慢速旋转展示。",
  "aigcStudio.textNode.samples.textToMusic":
    "生成一首现代品牌电子音乐（约 110 BPM），干净有力的低频贝斯，清晰电子鼓点，整体风格高级、未来感强。开场节奏型贝斯与简洁合成器音色建立律动。",
  "aigcStudio.textNode.sources.image": "图片",
  "aigcStudio.textNode.targets.video": "视频",
  "aigcStudio.textNode.targets.audio": "音频",
  "aigcStudio.contextMenu.delete": "删除",
  "aigcStudio.projects.open": "打开项目列表",
  "aigcStudio.projects.title": "项目",
  "aigcStudio.projects.new": "新建项目",
  "aigcStudio.projects.current": "当前",
  "aigcStudio.projects.delete": "删除项目 {{name}}",
  "aigcStudio.projects.deleteTitle": "删除项目",
  "aigcStudio.projects.deleteConfirm":
    "确定删除「{{name}}」吗？该项目的画布和任务记录会一起删除。",
  "aigcStudio.projects.empty": "暂无项目",
  "aigcStudio.templateNodes.storyGenerate.title": "脚本生成器",
  "aigcStudio.templateNodes.characterSource.title": "角色图",
  "aigcStudio.templateNodes.keyframeSource.title": "首帧",
  "aigcStudio.templateNodes.audioSource.title": "音频",
  "aigcStudio.templateNodes.audioImage.title": "图片",
  "common.save": "保存",
};
const t = (
  key: string,
  fallback: string,
  options?: Record<string, string | number>,
) => {
  const template = translations[key] ?? fallback;
  return Object.entries(options ?? {}).reduce(
    (result, [name, value]) => result.replace(`{{${name}}}`, String(value)),
    template,
  );
};

const clickToolbarSave = async () => {
  let saveButton: HTMLElement | null = null;
  await waitFor(() => {
    saveButton = screen.getByRole("button", { name: "保存" });
    expect(saveButton).toBeEnabled();
  });
  fireEvent.click(saveButton!);
};

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t }),
}));

function canvasFixture() {
  return {
    id: "canvas-1",
    name: "Untitled AIGC canvas",
    nodes: [
      {
        id: "prompt-1",
        type: "prompt",
        position: { x: 80, y: 90 },
        data: {
          title: "Campaign prompt",
          text: "A cinematic product film concept with clear brand mood.",
        },
      },
      {
        id: "image-1",
        type: "image_generate",
        position: { x: 360, y: 80 },
        data: {
          title: "Hero image",
          text: "Generate image variants from the selected prompt.",
        },
      },
    ],
    edges: [],
    viewport: { x: 0, y: 0, zoom: 1 },
    created_at: "2026-05-30T00:00:00Z",
    updated_at: "2026-05-30T00:00:00Z",
  };
}

function emptyCanvasFixture() {
  return {
    ...canvasFixture(),
    nodes: [],
    edges: [],
  };
}

function longImageCanvasFixture() {
  const canvas = canvasFixture();
  return {
    ...canvas,
    nodes: [
      ...canvas.nodes,
      {
        id: "long-1",
        type: "long_image_export",
        position: { x: 700, y: 80 },
        data: {
          title: "公众号长图",
          sliceHeight: 1400,
        },
      },
    ],
    edges: [
      {
        id: "edge-prompt-long",
        source: "prompt-1",
        target: "long-1",
        sourceHandle: "right",
        targetHandle: "left",
      },
      {
        id: "edge-image-long",
        source: "image-1",
        target: "long-1",
        sourceHandle: "right",
        targetHandle: "left",
      },
    ],
  };
}

function jobFixture() {
  return {
    id: "job-1",
    canvas_id: "canvas-1",
    node_id: "image-1",
    capability: "text_to_image",
    provider_id: "openai",
    model_id: "gpt-image-2",
    inputs: {},
    parameters: {},
    status: "cancelled" as const,
    outputs: [],
    logs: [],
    created_at: "2026-05-30T00:00:00Z",
    updated_at: "2026-05-30T00:00:00Z",
  };
}

function textCapability() {
  return {
    provider_id: "text-provider",
    provider_name: "Text Provider",
    model_id: "gvlm-3-1",
    model_name: "GVLM 3.1",
    capability: "storyboard",
    source: "model_registry",
  };
}

function fillScriptComposer(
  composer: HTMLElement,
  prompt = "现代办公室加班后穿越盛唐，整理成 12 个短剧分镜",
) {
  fireEvent.change(
    within(composer).getByRole("textbox", { name: "脚本生成器输入" }),
    {
      target: { value: prompt },
    },
  );
}

function storyboardScriptJobFixture() {
  return {
    ...jobFixture(),
    id: "job-2",
    node_id: "script-generate-1",
    capability: "storyboard",
    provider_id: "text-provider",
    model_id: "gvlm-3-1",
    status: "succeeded" as const,
    outputs: [
      {
        id: "asset-script-1",
        kind: "file",
        name: "storyboard.json",
        path: "aigc_studio/canvas-1/job-2/storyboard.json",
        url: "/api/user/aigc-studio/assets/asset-script-1/file",
        mime_type: "text/plain",
        created_at: "2026-05-30T00:00:00Z",
        meta: {
          text: JSON.stringify({
            title: "瓦房院子的梧桐树",
            shots: [
              {
                no: 1,
                duration: 5,
                imageDescription: "旧瓦房大院里，孩子抬头望向梧桐树梢。",
                character: "童年时期的我（约6岁）",
                characterDescription: "童年时期的我",
                scene: "瓦房大院，梧桐树下",
                shotType: "中景",
                camera: "缓慢仰拍",
                action: "孩子停在院子中央抬头。",
                emotion: "怀旧",
                lightingMood: "午后柔光",
                dialogue: "无",
                soundEffect: "树叶沙沙声",
                prompt: "电影感中景，旧瓦房大院，孩子仰望梧桐树。",
                finalPrompt: "电影感中景，旧瓦房大院，孩子仰望梧桐树。",
                videoPrompt: "镜头缓慢仰拍，梧桐叶在风中晃动。",
              },
            ],
          }),
        },
      },
    ],
  };
}

describe("AigcStudioPage", () => {
  afterEach(() => {
    Modal.destroyAll();
    document
      .querySelectorAll(".ant-modal-root")
      .forEach((element) => element.remove());
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document
      .querySelectorAll("[data-aigc-download-link]")
      .forEach((element) => element.remove());
    restoreUrlObjectMethods();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mockAigcStudioApi.listCapabilities.mockResolvedValue({
      capabilities: [
        {
          provider_id: "openai",
          provider_name: "OpenAI",
          model_id: "gpt-image-2",
          model_name: "GPT Image 2",
          capability: "text_to_image",
          source: "model_registry",
        },
        {
          provider_id: "dashscope",
          provider_name: "DashScope",
          model_id: "qwen-image",
          model_name: "Qwen Image",
          capability: "text_to_image",
          source: "model_registry",
        },
        {
          provider_id: "mxapi",
          provider_name: "MXAPI",
          model_id: "seedance2",
          model_name: "Seedance 2.0",
          capability: "text_to_video",
          source: "model_registry",
        },
        {
          provider_id: "mxapi",
          provider_name: "MXAPI",
          model_id: "seedance2-fast",
          model_name: "Seedance 2.0 Fast",
          capability: "image_to_video",
          source: "model_registry",
        },
      ],
    });
    mockAigcStudioApi.listWorkflowCapabilities.mockResolvedValue({
      available_models: [],
    });
    mockAigcStudioApi.listStyleTemplates.mockResolvedValue({
      templates: [
        {
          id: "style-film",
          title: "电影感",
          type: "style",
          provider: "internal",
          model_family: "seedream-4.5",
          cover_url: "/api/user/aigc-studio/style-templates/style-film/cover",
          category: "推荐",
          tags: ["常用", "商用"],
          keywords: "电影感, 戏剧光影, 景深, 对比色",
          description: "电影级光影与景深，强调主体叙事和画面氛围。",
          visual_dna: [
            { element_id: "lighting.cinematic_contrast", weight: 0.95 },
            { element_id: "camera.shallow_depth", weight: 0.8 },
          ],
          commercial: true,
          runtime_mode: "prompt_style",
          use_count: 3300,
          status: "enabled",
        },
      ],
    });
    mockAigcStudioApi.listVisualDnaDimensions.mockResolvedValue({
      dimensions: [
        {
          id: "lighting",
          name: "光影",
          description: "光源与层次",
          element_count: 1,
        },
      ],
    });
    mockAigcStudioApi.listVisualDnaElements.mockResolvedValue({
      total: 1,
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
      ],
    });
    mockAigcStudioApi.markStyleTemplateUsed.mockResolvedValue(undefined);
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [canvasFixture()],
    });
    mockAigcStudioApi.createCanvas.mockImplementation(async (body) => ({
      id: "created-canvas",
      ...body,
      created_at: "2026-05-30T00:00:00Z",
      updated_at: "2026-05-30T00:00:00Z",
    }));
    mockAigcStudioApi.saveCanvas.mockImplementation(async (id, body) => ({
      id,
      ...body,
      created_at: "2026-05-30T00:00:00Z",
      updated_at: "2026-05-30T00:00:00Z",
    }));
    mockAigcStudioApi.deleteCanvas.mockResolvedValue(undefined);
    mockAigcStudioApi.uploadAsset.mockImplementation(async (file: File) => ({
      id: `asset-${file.name}`,
      kind: file.type.startsWith("video/")
        ? "video"
        : file.type.startsWith("image/")
        ? "image"
        : "file",
      name: file.name,
      path: `aigc_studio/uploads/${file.name}`,
      url: `/api/user/aigc-studio/assets/${file.name}/file`,
      mime_type: file.type,
      created_at: "2026-05-30T00:00:00Z",
    }));
    mockAigcStudioApi.listJobs.mockResolvedValue({ jobs: [] });
    mockAigcStudioApi.submitJob.mockResolvedValue({
      ...jobFixture(),
      id: "job-2",
      status: "queued",
    });
    mockAigcStudioApi.cancelJob.mockResolvedValue(jobFixture());
    mockAigcStudioApi.retryJob.mockResolvedValue({
      ...jobFixture(),
      id: "job-2",
      status: "queued",
    });
    mockAigcStudioApi.runJob.mockResolvedValue({
      ...jobFixture(),
      id: "job-2",
      status: "succeeded",
      outputs: [
        {
          id: "asset-1",
          kind: "image",
          name: "image-1.svg",
          path: "aigc_studio/canvas-1/job-2/image-1.svg",
          url: "/api/user/aigc-studio/assets/asset-1/file",
          mime_type: "image/svg+xml",
          created_at: "2026-05-30T00:00:00Z",
        },
      ],
    });
    mockAigcStudioApi.exportLongImage.mockResolvedValue({
      full_asset: {
        id: "asset-long-full",
        kind: "image",
        name: "long.png",
        path: "aigc_studio/canvas-1/long.png",
        url: "/api/user/aigc-studio/assets/asset-long-full/file",
        mime_type: "image/png",
        created_at: "2026-05-30T00:00:00Z",
      },
      slice_assets: [],
      width: 750,
      height: 1200,
      slice_height: 1400,
      section_count: 2,
    });
  });

  it("renders dynamic model capabilities and localizes legacy default canvas content", async () => {
    render(<AigcStudioPage />);

    await waitFor(() => {
      expect(screen.getAllByText("GPT Image 2").length).toBeGreaterThan(0);
    });

    await waitFor(() => {
      expect(screen.getAllByText("文生图").length).toBeGreaterThan(0);
    });
    expect(screen.getByText("AIGC 创意工作室")).toBeInTheDocument();
    expect(screen.getByText("未命名 AIGC 画布")).toBeInTheDocument();
    expect(screen.getByText("营销提示词")).toBeInTheDocument();
    expect(screen.getByText("主视觉图片")).toBeInTheDocument();
    expect(screen.queryByText("Untitled AIGC canvas")).not.toBeInTheDocument();
    expect(screen.queryByText("Campaign prompt")).not.toBeInTheDocument();
    expect(screen.queryByText("Hero image")).not.toBeInTheDocument();
  });

  it("keeps the studio chrome in Chinese when a translation key is missing", async () => {
    render(<AigcStudioPage />);

    await waitFor(() => {
      expect(screen.getAllByText("GPT Image 2").length).toBeGreaterThan(0);
    });

    expect(screen.getByText("新建画布")).toBeInTheDocument();
    expect(screen.getByText("画布")).toBeInTheDocument();
    expect(screen.getByText("节点面板")).toBeInTheDocument();
    expect(screen.getByText("检查器")).toBeInTheDocument();
    expect(screen.getByText("可用能力")).toBeInTheDocument();
    expect(screen.getByText("任务")).toBeInTheDocument();
    expect(screen.queryByText("New canvas")).not.toBeInTheDocument();
    expect(screen.queryByText("Canvases")).not.toBeInTheDocument();
    expect(screen.queryByText("Node palette")).not.toBeInTheDocument();
    expect(screen.queryByText("Inspector")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Available capabilities"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Jobs")).not.toBeInTheDocument();
  });

  it("submits the model selected in the inspector", async () => {
    render(<AigcStudioPage />);

    await waitFor(() => {
      expect(screen.getAllByText("GPT Image 2").length).toBeGreaterThan(0);
    });
    fireEvent.mouseDown(document.querySelector(".ant-select-selector")!);
    fireEvent.click(await screen.findByText("DashScope / Qwen Image"));
    fireEvent.click(screen.getByRole("button", { name: "运行节点" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.submitJob).toHaveBeenCalledWith(
        expect.objectContaining({
          provider_id: "dashscope",
          model_id: "qwen-image",
          capability: "text_to_image",
        }),
      );
    });
    expect(mockAigcStudioApi.runJob).toHaveBeenCalledWith("job-2");
    const outputImages = await screen.findAllByRole("img", {
      name: "image-1.svg",
    });
    expect(outputImages[0]).toHaveAttribute("data-authenticated-asset", "true");
    expect(screen.getByTestId("aigc-image-editor")).toHaveAttribute(
      "data-image-state",
      "generated",
    );
  });

  it("runs image generation from the image composer submit button with the latest prompt", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    const composer = screen.getByTestId("aigc-image-composer");
    fireEvent.change(within(composer).getByLabelText("图片节点输入"), {
      target: { value: "小女孩" },
    });
    fireEvent.click(
      within(composer).getByRole("button", { name: "提交图片节点输入" }),
    );

    await waitFor(() => {
      expect(mockAigcStudioApi.submitJob).toHaveBeenCalledWith(
        expect.objectContaining({
          inputs: expect.objectContaining({
            prompt: "小女孩",
            node_type: "image_generate",
          }),
        }),
      );
    });
    await waitFor(() => {
      expect(mockAigcStudioApi.runJob).toHaveBeenCalledWith("job-2");
    });
    await waitFor(() => {
      expect(screen.getByTestId("aigc-image-editor")).toHaveAttribute(
        "data-image-state",
        "generated",
      );
    });
  });

  it("blocks a saved image-node model when no configured capability is available", async () => {
    const canvas = canvasFixture();
    mockAigcStudioApi.listCapabilities.mockResolvedValueOnce({
      capabilities: [],
    });
    mockAigcStudioApi.listCanvases.mockResolvedValueOnce({
      canvases: [
        {
          ...canvas,
          nodes: [
            {
              ...canvas.nodes[1]!,
              data: {
                title: "主视觉图片",
                text: "",
                composerText: "修仙的，背着葫芦的小姑娘",
                imageMode: "blank",
                providerId: "volcengine",
                modelId: "doubao-seedream-4-5-251128",
                modelLabel: "doubao-seedream-4-5",
              },
            },
          ],
          edges: [],
        },
      ],
    });

    render(<AigcStudioPage />);

    const composer = await screen.findByTestId("aigc-image-composer");
    expect(
      within(composer).getByText("doubao-seedream-4-5"),
    ).toBeInTheDocument();
    fireEvent.click(
      within(composer).getByRole("button", { name: "提交图片节点输入" }),
    );

    expect(
      await screen.findByText("该模型已不可用，且当前没有可切换的默认模型。"),
    ).toBeInTheDocument();
    expect(mockAigcStudioApi.submitJob).not.toHaveBeenCalled();
  });

  it("offers the configured default instead of a stale saved image model", async () => {
    const canvas = canvasFixture();
    mockAigcStudioApi.listCapabilities.mockResolvedValueOnce({
      capabilities: [
        {
          provider_id: "openai",
          provider_name: "OpenAI",
          model_id: "gpt-image-2",
          model_name: "GPT Image 2",
          capability: "text_to_image",
          source: "model_registry",
        },
      ],
      defaults: {
        image: {
          configured: true,
          configured_default: {
            provider_id: "openai",
            model_id: "gpt-image-2",
          },
          effective_default: {
            provider_id: "openai",
            model_id: "gpt-image-2",
          },
          fallback_active: false,
          fallback_reason: [],
        },
      },
    });
    mockAigcStudioApi.listCanvases.mockResolvedValueOnce({
      canvases: [
        {
          ...canvas,
          nodes: [
            {
              ...canvas.nodes[1]!,
              data: {
                title: "主视觉图片",
                text: "",
                composerText: "修仙的，背着葫芦的小姑娘",
                imageMode: "blank",
                providerId: "volcengine",
                modelId: "doubao-seedream-4-5-251128",
                modelLabel: "doubao-seedream-4-5",
              },
            },
          ],
          edges: [],
        },
      ],
    });

    render(<AigcStudioPage />);

    const composer = await screen.findByTestId("aigc-image-composer");
    expect(within(composer).getByText("GPT Image 2")).toBeInTheDocument();
    expect(
      within(composer).queryByText("doubao-seedream-4-5"),
    ).not.toBeInTheDocument();

    fireEvent.click(
      within(composer).getByRole("button", { name: "提交图片节点输入" }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "该模型已不可用",
    });
    expect(dialog).toHaveTextContent(
      "是否切换到当前默认模型 GPT Image 2 后继续？",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "切换并继续" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.submitJob).toHaveBeenCalledWith(
        expect.objectContaining({
          provider_id: "openai",
          model_id: "gpt-image-2",
        }),
      );
    });
  });

  it("uses the ordinary model catalog for workflow-bound canvases", async () => {
    const canvas = canvasFixture();
    mockAigcStudioApi.listCapabilities.mockResolvedValueOnce({
      capabilities: [
        {
          provider_id: "openai",
          provider_name: "OpenAI",
          model_id: "gpt-image-2",
          model_name: "GPT Image 2",
          capability: "text_to_image",
          source: "model_registry",
        },
      ],
      defaults: {
        image: {
          configured: true,
          configured_default: {
            provider_id: "openai",
            model_id: "gpt-image-2",
          },
          effective_default: {
            provider_id: "openai",
            model_id: "gpt-image-2",
          },
          fallback_active: false,
          fallback_reason: [],
        },
      },
    });
    mockAigcStudioApi.listWorkflowCapabilities.mockResolvedValueOnce({
      available_models: [
        {
          provider_id: "volcengine",
          provider_name: "Volcano Engine",
          model_id: "workflow-seedream",
          model_name: "Workflow Seedream",
          capability: "text_to_image",
          source: "model_registry",
        },
      ],
    });
    mockAigcStudioApi.listCanvases.mockResolvedValueOnce({
      canvases: [
        {
          ...canvas,
          meta: { workflow_id: "expert-workflow" },
          nodes: [
            {
              ...canvas.nodes[1]!,
              data: {
                title: "主视觉图片",
                text: "",
                composerText: "专家工作流图片",
                imageMode: "blank",
                workflowLogicalNodeId: "hero_image",
                providerId: "volcengine",
                providerName: "Volcano Engine",
                modelId: "workflow-seedream",
                modelLabel: "Workflow Seedream",
                modelCapability: "text_to_image",
              },
            },
          ],
          edges: [],
        },
      ],
    });

    render(<AigcStudioPage />);

    const composer = await screen.findByTestId("aigc-image-composer");
    expect(within(composer).getByText("GPT Image 2")).toBeInTheDocument();
    fireEvent.click(
      within(composer).getByRole("button", { name: "提交图片节点输入" }),
    );

    await waitFor(() => {
      expect(mockAigcStudioApi.submitJob).toHaveBeenCalledWith(
        expect.objectContaining({
          provider_id: "openai",
          model_id: "gpt-image-2",
        }),
      );
    });
  });

  it("persists a newly created image node before submitting its run", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "图片生成/编辑" }));

    const composer = screen.getByTestId("aigc-image-composer");
    fireEvent.change(within(composer).getByLabelText("图片节点输入"), {
      target: { value: "刚创建就运行的图片" },
    });
    fireEvent.click(
      within(composer).getByRole("button", { name: "提交图片节点输入" }),
    );

    await waitFor(() => {
      expect(mockAigcStudioApi.submitJob).toHaveBeenCalled();
    });

    const submitOrder =
      mockAigcStudioApi.submitJob.mock.invocationCallOrder[0] ?? 0;
    const saveBeforeSubmit = mockAigcStudioApi.saveCanvas.mock.calls.find(
      ([, body], index) =>
        (mockAigcStudioApi.saveCanvas.mock.invocationCallOrder[index] ?? 0) <
          submitOrder &&
        body.nodes.some(
          (node: {
            type: string;
            data: { text?: string; lastRunPrompt?: string };
          }) =>
            node.type === "image_generate" &&
            node.data.text === "刚创建就运行的图片" &&
            node.data.lastRunPrompt === "刚创建就运行的图片",
        ),
    );
    expect(saveBeforeSubmit).toBeTruthy();
  });

  it("shows a node error instead of silently ignoring image submit when no model is available", async () => {
    mockAigcStudioApi.listCapabilities.mockResolvedValueOnce({
      capabilities: [],
    });
    render(<AigcStudioPage />);

    const composer = await screen.findByTestId("aigc-image-composer");
    fireEvent.change(within(composer).getByLabelText("图片节点输入"), {
      target: { value: "小女孩" },
    });
    fireEvent.click(
      within(composer).getByRole("button", { name: "提交图片节点输入" }),
    );

    expect(
      await screen.findByText(
        "当前图片节点没有可用模型，请先选择模型后再生成。",
      ),
    ).toBeInTheDocument();
    expect(mockAigcStudioApi.submitJob).not.toHaveBeenCalled();
    expect(screen.getByTestId("aigc-image-editor")).toHaveAttribute(
      "data-image-state",
      "failed",
    );
  });

  it("shows the image generating state before an immediate submit failure", async () => {
    mockAigcStudioApi.submitJob.mockRejectedValueOnce(
      new Error("No AIGC adapter is configured for volcengine/seedream."),
    );
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    const composer = screen.getByTestId("aigc-image-composer");
    fireEvent.change(within(composer).getByLabelText("图片节点输入"), {
      target: { value: "小女孩" },
    });
    fireEvent.click(
      within(composer).getByRole("button", { name: "提交图片节点输入" }),
    );

    await waitFor(() => {
      expect(screen.getByTestId("aigc-image-editor")).toHaveAttribute(
        "data-image-state",
        "generating",
      );
    });
    await waitFor(() => {
      expect(screen.getByTestId("aigc-image-editor")).toHaveAttribute(
        "data-image-state",
        "failed",
      );
    });
    expect(screen.getByTestId("aigc-image-editor")).toHaveTextContent(
      "No AIGC adapter is configured",
    );
  });

  it("shows image generation feedback while canvas save is still in flight", async () => {
    let resolveSave: (value: unknown) => void = () => {};
    mockAigcStudioApi.saveCanvas.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSave = resolve;
        }),
    );

    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    const composer = screen.getByTestId("aigc-image-composer");
    fireEvent.change(within(composer).getByLabelText("图片节点输入"), {
      target: { value: "保存慢也要有反馈" },
    });
    fireEvent.click(
      within(composer).getByRole("button", { name: "提交图片节点输入" }),
    );

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.getByTestId("aigc-image-editor")).toHaveAttribute(
        "data-image-state",
        "generating",
      );
    });
    expect(mockAigcStudioApi.submitJob).not.toHaveBeenCalled();

    resolveSave({});

    await waitFor(() => {
      expect(mockAigcStudioApi.submitJob).toHaveBeenCalled();
    });
  });

  it("shows generated image viewing tools after image generation", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    fireEvent.click(screen.getByRole("button", { name: "运行节点" }));

    const editor = await screen.findByTestId("aigc-image-editor");
    await waitFor(() => {
      expect(editor).toHaveAttribute("data-image-state", "generated");
    });

    const viewerToolbar = screen.getByTestId("aigc-image-viewer-toolbar");
    expect(viewerToolbar).toHaveAttribute("data-image-panorama", "false");
    expect(viewerToolbar).toHaveAttribute(
      "data-toolbar-placement",
      "node-above",
    );
    expect(editor).not.toContainElement(viewerToolbar);
    expect(
      within(viewerToolbar).queryByRole("button", { name: "当前视角截图" }),
    ).not.toBeInTheDocument();
    expect(
      within(viewerToolbar).queryByRole("button", { name: "4大视角截图" }),
    ).not.toBeInTheDocument();
    expect(
      within(viewerToolbar).queryByRole("button", { name: "12大视角截图" }),
    ).not.toBeInTheDocument();
    expect(
      within(viewerToolbar).getByRole("button", { name: "发送到图片节点" }),
    ).toBeInTheDocument();
    expect(
      within(viewerToolbar).getByRole("button", { name: "标注" }),
    ).toBeInTheDocument();
    expect(
      within(viewerToolbar).getByRole("button", { name: "下载结果" }),
    ).toBeInTheDocument();
    expect(
      within(viewerToolbar).getByRole("button", { name: "全屏查看" }),
    ).toBeInTheDocument();
    expect(editor).not.toHaveTextContent("1024 × 1024");
    expect(screen.getByTestId("aigc-image-node-meta")).toHaveTextContent(
      "1024 × 1024",
    );
    expect(editor).not.toHaveTextContent("720");
  });

  it("keeps the image composer visible when expanded generated results are open", async () => {
    const canvas = canvasFixture();
    mockAigcStudioApi.listCanvases.mockResolvedValueOnce({
      canvases: [
        {
          ...canvas,
          nodes: [
            canvas.nodes[0]!,
            {
              ...canvas.nodes[1]!,
              data: {
                title: "主视觉图片",
                imageState: "generated",
                text: "小螃蟹",
                outputs: [
                  {
                    id: "asset-1",
                    kind: "image",
                    name: "crab-1.jpg",
                    path: "blob:crab-1",
                    mime_type: "image/jpeg",
                    width: 2048,
                    height: 1152,
                    created_at: "2026-07-03T00:00:00Z",
                  },
                  {
                    id: "asset-2",
                    kind: "image",
                    name: "crab-2.jpg",
                    path: "blob:crab-2",
                    mime_type: "image/jpeg",
                    width: 2048,
                    height: 1152,
                    created_at: "2026-07-03T00:00:00Z",
                  },
                ],
              },
            },
          ],
        },
      ],
    });

    render(<AigcStudioPage />);

    const composer = await screen.findByTestId("aigc-image-composer");
    expect(composer).toBeInTheDocument();

    fireEvent.click(
      within(screen.getByTestId("aigc-image-viewer-toolbar")).getByRole(
        "button",
        { name: "展开 2 张图片" },
      ),
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("aigc-image-result-side-gallery"),
      ).toBeInTheDocument();
    });
    expect(screen.getByTestId("aigc-image-composer")).toBeInTheDocument();
    const nodeShell = screen
      .getByTestId("aigc-image-editor")
      .closest("[data-aigc-node]");
    expect(nodeShell).toHaveAttribute("data-image-results-expanded", "true");
    expect(
      (nodeShell as HTMLElement).style.getPropertyValue(
        "--aigc-image-primary-width",
      ),
    ).toBe("560px");
  });

  it("keeps expanded generated results anchored to the image node while panning the canvas", async () => {
    const getBoundingClientRect = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({
        x: 0,
        y: 0,
        left: 0,
        top: 0,
        right: 1000,
        bottom: 760,
        width: 1000,
        height: 760,
        toJSON: () => ({}),
      } as DOMRect);
    const canvas = canvasFixture();
    mockAigcStudioApi.listCanvases.mockResolvedValueOnce({
      canvases: [
        {
          ...canvas,
          nodes: [
            canvas.nodes[0]!,
            {
              ...canvas.nodes[1]!,
              position: { x: 100, y: 80 },
              data: {
                title: "主视觉图片",
                imageState: "generated",
                text: "小螃蟹",
                outputs: [
                  {
                    id: "asset-1",
                    kind: "image",
                    name: "crab-1.jpg",
                    path: "blob:crab-1",
                    mime_type: "image/jpeg",
                    width: 2048,
                    height: 1152,
                    created_at: "2026-07-03T00:00:00Z",
                  },
                  {
                    id: "asset-2",
                    kind: "image",
                    name: "crab-2.jpg",
                    path: "blob:crab-2",
                    mime_type: "image/jpeg",
                    width: 2048,
                    height: 1152,
                    created_at: "2026-07-03T00:00:00Z",
                  },
                ],
              },
            },
          ],
        },
      ],
    });

    render(<AigcStudioPage />);

    await screen.findByTestId("aigc-image-composer");
    fireEvent.click(
      within(screen.getByTestId("aigc-image-viewer-toolbar")).getByRole(
        "button",
        { name: "展开 2 张图片" },
      ),
    );

    const nodeShell = await screen.findByTestId("aigc-node-image-1");
    await waitFor(() => {
      expect(nodeShell).toHaveAttribute("data-image-results-expanded", "true");
    });
    const initialGalleryLeft = nodeShell.style.getPropertyValue(
      "--aigc-image-gallery-left",
    );
    const initialGalleryTop = nodeShell.style.getPropertyValue(
      "--aigc-image-gallery-top",
    );
    expect(initialGalleryLeft).toBe("0px");

    fireEvent.mouseDown(screen.getByTestId("aigc-canvas-surface"), {
      button: 0,
      clientX: 500,
      clientY: 320,
    });
    fireEvent.mouseMove(window, { clientX: 400, clientY: 320 });
    fireEvent.mouseUp(window);

    await waitFor(() => {
      expect(nodeShell.style.left).toBe("0px");
    });
    expect(nodeShell.style.getPropertyValue("--aigc-image-gallery-left")).toBe(
      initialGalleryLeft,
    );
    expect(nodeShell.style.getPropertyValue("--aigc-image-gallery-top")).toBe(
      initialGalleryTop,
    );
    getBoundingClientRect.mockRestore();
  });

  it("keeps portrait expanded generated results vertically aligned with the primary image", async () => {
    const getBoundingClientRect = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({
        x: 0,
        y: 0,
        left: 0,
        top: 0,
        right: 1000,
        bottom: 760,
        width: 1000,
        height: 760,
        toJSON: () => ({}),
      } as DOMRect);
    const canvas = canvasFixture();
    mockAigcStudioApi.listCanvases.mockResolvedValueOnce({
      canvases: [
        {
          ...canvas,
          nodes: [
            canvas.nodes[0]!,
            {
              ...canvas.nodes[1]!,
              position: { x: 300, y: 260 },
              data: {
                title: "主视觉图片",
                imageState: "generated",
                text: "小螃蟹",
                aspectRatio: "9:16",
                outputs: [
                  {
                    id: "asset-1",
                    kind: "image",
                    name: "crab-portrait-1.jpg",
                    path: "blob:crab-portrait-1",
                    mime_type: "image/jpeg",
                    width: 1152,
                    height: 2048,
                    created_at: "2026-07-03T00:00:00Z",
                  },
                  {
                    id: "asset-2",
                    kind: "image",
                    name: "crab-portrait-2.jpg",
                    path: "blob:crab-portrait-2",
                    mime_type: "image/jpeg",
                    width: 1152,
                    height: 2048,
                    created_at: "2026-07-03T00:00:00Z",
                  },
                ],
              },
            },
          ],
        },
      ],
    });

    render(<AigcStudioPage />);

    await screen.findByTestId("aigc-image-composer");
    fireEvent.click(
      within(screen.getByTestId("aigc-image-viewer-toolbar")).getByRole(
        "button",
        { name: "展开 2 张图片" },
      ),
    );

    const nodeShell = await screen.findByTestId("aigc-node-image-1");
    await waitFor(() => {
      expect(nodeShell).toHaveAttribute("data-image-results-expanded", "true");
    });
    expect(
      nodeShell.style.getPropertyValue("--aigc-image-gallery-placement"),
    ).toBe("right");
    expect(nodeShell.style.getPropertyValue("--aigc-image-gallery-top")).toBe(
      "0px",
    );

    getBoundingClientRect.mockRestore();
  });

  it("creates a visible image annotation node from the generated image toolbar", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    fireEvent.click(screen.getByRole("button", { name: "运行节点" }));

    const editor = await screen.findByTestId("aigc-image-editor");
    await waitFor(() => {
      expect(editor).toHaveAttribute("data-image-state", "generated");
    });

    const viewerToolbar = screen.getByTestId("aigc-image-viewer-toolbar");
    fireEvent.click(
      within(viewerToolbar).getByRole("button", { name: "标注" }),
    );

    const annotationEditor = await screen.findByTestId(
      "aigc-image-annotation-editor",
    );
    expect(annotationEditor).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("标注说明"), {
      target: { value: "红圈区域需要变得更有皮肤质感" },
    });
    const stage = screen.getByTestId("aigc-image-annotation-stage");
    fireEvent.pointerDown(stage, { clientX: 20, clientY: 20, pointerId: 1 });
    fireEvent.pointerMove(stage, { clientX: 120, clientY: 80, pointerId: 1 });
    fireEvent.pointerUp(stage, { clientX: 120, clientY: 80, pointerId: 1 });
    fireEvent.click(screen.getByRole("button", { name: "保存标注" }));

    expect(
      await screen.findByTestId(/aigc-node-image-annotation-/),
    ).toHaveTextContent("标注");

    await clickToolbarSave();

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "reference_asset",
              data: expect.objectContaining({
                title: "标注",
                previewKind: "uploaded_source",
                assetRole: "image_annotation",
                assetKind: "image",
                annotationSourcePreviewUrl:
                  "/api/user/aigc-studio/assets/asset-1/file",
                referencePreviewUrl:
                  "/api/user/aigc-studio/assets/asset-1/file",
                annotationInstruction: "红圈区域需要变得更有皮肤质感",
                annotationMode: "region_edit",
                imageEditScope: "annotated_region",
                participatesInGeneration: true,
                isAnnotation: true,
              }),
            }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              source: "image-1",
              target: expect.stringMatching(/^image-annotation-/),
              data: { role: "image_annotation" },
            }),
          ]),
        }),
      );
    });
  });

  it("marks generated panorama images in the viewer toolbar", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            {
              ...canvasFixture().nodes[1],
              data: {
                title: "全景图片",
                text: "女儿的卧室，很多布娃娃与玩具",
                imageMode: "panorama",
                panoramaMode: true,
                aspectRatio: "2:1",
                resolution: "2K",
                outputs: [
                  {
                    id: "asset-panorama",
                    kind: "image",
                    name: "panorama.png",
                    path: "aigc_studio/canvas-1/job-2/panorama.png",
                    width: 2048,
                    height: 1024,
                  },
                ],
              },
            },
          ],
        },
      ],
    });
    render(<AigcStudioPage />);

    await screen.findByText("全景图片");

    const editor = screen.getByTestId("aigc-image-editor");
    const viewerToolbar = screen.getByTestId("aigc-image-viewer-toolbar");
    expect(editor).toHaveAttribute("data-image-state", "generated");
    expect(viewerToolbar).toHaveAttribute("data-image-panorama", "true");
    expect(viewerToolbar).toHaveAttribute(
      "data-toolbar-placement",
      "node-above",
    );
    expect(editor).not.toContainElement(viewerToolbar);
    expect(viewerToolbar).toHaveTextContent("720");
    expect(
      within(viewerToolbar).getByRole("button", { name: "当前视角截图" }),
    ).toBeInTheDocument();
    expect(
      within(viewerToolbar).getByRole("button", { name: "4大视角截图" }),
    ).toBeInTheDocument();
    expect(
      within(viewerToolbar).getByRole("button", { name: "12大视角截图" }),
    ).toBeInTheDocument();
    expect(
      within(viewerToolbar).getByRole("button", { name: "发送到图片节点" }),
    ).toBeInTheDocument();
    expect(editor).not.toHaveTextContent("2048 × 1024");
    expect(screen.getByTestId("aigc-image-node-meta")).toHaveTextContent(
      "2048 × 1024",
    );
  });

  it("creates a connected image capture group from the generated image toolbar", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            {
              ...canvasFixture().nodes[1],
              data: {
                title: "全景图片",
                text: "女儿的卧室，很多布娃娃与玩具",
                imageMode: "panorama",
                panoramaMode: true,
                aspectRatio: "2:1",
                outputs: [
                  {
                    id: "asset-panorama",
                    kind: "image",
                    name: "panorama.png",
                    path: "aigc_studio/canvas-1/job-2/panorama.png",
                    width: 2048,
                    height: 1024,
                  },
                ],
              },
            },
          ],
        },
      ],
    });
    render(<AigcStudioPage />);

    await screen.findByText("全景图片");
    fireEvent.click(screen.getByRole("button", { name: "4大视角截图" }));

    const captureGroup = await screen.findByTestId("aigc-image-capture-group");
    expect(captureGroup).toHaveTextContent("全景截图组 (4张)");
    expect(captureGroup).toHaveTextContent("全景截图-前方");
    expect(captureGroup).toHaveTextContent("全景截图-左侧");
    expect(captureGroup).toHaveTextContent("全景截图-后方");
    expect(captureGroup).toHaveTextContent("全景截图-右侧");
    expect(captureGroup).toHaveTextContent("横 0° · 纵 0° · 缩放 1x");
    expect(
      within(captureGroup).getByRole("button", { name: "下载截图组" }),
    ).toBeInTheDocument();
    expect(
      within(captureGroup).getByRole("button", { name: "发送到图片节点" }),
    ).toBeInTheDocument();
    expect(
      within(captureGroup).getByRole("button", { name: "全屏查看截图组" }),
    ).toBeInTheDocument();

    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    fireEvent.click(
      within(captureGroup).getByRole("button", { name: "下载截图组" }),
    );
    await waitFor(() => {
      expect(captureGroup).toHaveTextContent("已准备下载");
    });
    anchorClick.mockRestore();

    fireEvent.click(
      within(captureGroup).getByRole("button", { name: "全屏查看截图组" }),
    );
    expect(captureGroup).toHaveAttribute("data-capture-expanded", "true");
    expect(captureGroup).toHaveTextContent("截图组预览");

    fireEvent.click(
      within(captureGroup).getByRole("button", { name: "发送到图片节点" }),
    );
    await clickToolbarSave();

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "reference_asset",
              data: expect.objectContaining({
                previewKind: "image_capture_group",
                captureMode: "four",
                captureCount: 4,
                sourceImageNodeId: "image-1",
                sourceImageOutputPath:
                  "aigc_studio/canvas-1/job-2/panorama.png",
              }),
            }),
            expect.objectContaining({
              type: "image_generate",
              data: expect.objectContaining({
                imageMode: "image_to_image",
                imageState: "editing",
                referenceAssetName: "全景截图组 (4张)",
                referencePreviewUrl: "aigc_studio/canvas-1/job-2/panorama.png",
                referenceCaptureGroupId:
                  expect.stringMatching(/^image-capture-four-/),
                referenceCaptureCount: 4,
              }),
            }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              source: "image-1",
              sourceHandle: "right",
              targetHandle: "left",
            }),
            expect.objectContaining({
              source: expect.stringMatching(/^image-capture-four-/),
              target: expect.stringMatching(/^image-from-capture-/),
              sourceHandle: "right",
              targetHandle: "left",
            }),
          ]),
        }),
      );
    });
  });

  it("shows image node generating state while the job is running", async () => {
    let finishJob: (value: unknown) => void = () => undefined;
    mockAigcStudioApi.runJob.mockReturnValue(
      new Promise((resolve) => {
        finishJob = resolve;
      }),
    );
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    fireEvent.click(screen.getByRole("button", { name: "运行节点" }));

    await waitFor(() => {
      expect(screen.getByTestId("aigc-image-editor")).toHaveAttribute(
        "data-image-state",
        "generating",
      );
    });
    expect(screen.getByTestId("aigc-image-editor")).toHaveTextContent("生成中");
    expect(
      screen.getByRole("button", { name: "取消生成" }),
    ).toBeInTheDocument();

    finishJob({
      ...jobFixture(),
      id: "job-2",
      status: "succeeded",
      outputs: [
        {
          id: "asset-1",
          kind: "image",
          name: "image-1.svg",
          path: "aigc_studio/canvas-1/job-2/image-1.svg",
          url: "/api/user/aigc-studio/assets/asset-1/file",
          mime_type: "image/svg+xml",
          created_at: "2026-05-30T00:00:00Z",
        },
      ],
    });

    await waitFor(() => {
      expect(screen.getByTestId("aigc-image-editor")).toHaveAttribute(
        "data-image-state",
        "generated",
      );
    });
  });

  it("allows another image node on the same canvas to run while one image node is still running", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            ...canvasFixture().nodes,
            {
              id: "image-2",
              type: "image_generate",
              position: { x: 720, y: 80 },
              data: {
                title: "Second image",
                text: "Generate a second image while the first one runs.",
              },
            },
          ],
        },
      ],
    });
    mockAigcStudioApi.submitJob.mockImplementation(async (body) => ({
      ...jobFixture(),
      id: `job-${body.node_id}`,
      node_id: body.node_id,
      capability: body.capability,
      provider_id: body.provider_id,
      model_id: body.model_id,
      status: "queued",
    }));
    let finishFirstJob: (value: unknown) => void = () => undefined;
    mockAigcStudioApi.runJob.mockImplementation((jobId: string) => {
      if (jobId === "job-image-1") {
        return new Promise((resolve) => {
          finishFirstJob = resolve;
        });
      }
      return Promise.resolve({
        ...jobFixture(),
        id: jobId,
        node_id: "image-2",
        status: "succeeded",
        outputs: [
          {
            id: "asset-image-2",
            kind: "image",
            name: "image-2.svg",
            path: "aigc_studio/canvas-1/job-image-2/image-2.svg",
            url: "/api/user/aigc-studio/assets/asset-image-2/file",
            mime_type: "image/svg+xml",
            created_at: "2026-05-30T00:00:00Z",
          },
        ],
      });
    });
    render(<AigcStudioPage />);
    const imageSurfaceFor = (nodeId: string) =>
      screen
        .getByTestId(`aigc-node-${nodeId}`)
        .querySelector("[data-image-state]") as HTMLElement;

    await screen.findByText("Second image");
    fireEvent.click(screen.getByRole("button", { name: "运行节点" }));

    await waitFor(() => {
      expect(imageSurfaceFor("image-1")).toHaveAttribute(
        "data-image-state",
        "generating",
      );
    });

    fireEvent.click(screen.getByTestId("aigc-node-image-2"));
    const secondComposer = screen.getByTestId("aigc-image-composer");
    expect(
      within(secondComposer).getByRole("button", {
        name: "提交图片节点输入",
      }),
    ).toBeEnabled();
    fireEvent.click(
      within(secondComposer).getByRole("button", {
        name: "提交图片节点输入",
      }),
    );

    await waitFor(() => {
      expect(mockAigcStudioApi.submitJob).toHaveBeenCalledWith(
        expect.objectContaining({ node_id: "image-2" }),
      );
    });
    await waitFor(() => {
      expect(imageSurfaceFor("image-2")).toHaveAttribute(
        "data-image-state",
        "generated",
      );
    });
    expect(imageSurfaceFor("image-1")).toHaveAttribute(
      "data-image-state",
      "generating",
    );

    finishFirstJob({
      ...jobFixture(),
      id: "job-image-1",
      node_id: "image-1",
      status: "succeeded",
      outputs: [
        {
          id: "asset-image-1",
          kind: "image",
          name: "image-1.svg",
          path: "aigc_studio/canvas-1/job-image-1/image-1.svg",
          url: "/api/user/aigc-studio/assets/asset-image-1/file",
          mime_type: "image/svg+xml",
          created_at: "2026-05-30T00:00:00Z",
        },
      ],
    });
  });

  it("does not submit duplicate jobs for the same node while it is already running", async () => {
    let finishJob: (value: unknown) => void = () => undefined;
    mockAigcStudioApi.runJob.mockReturnValue(
      new Promise((resolve) => {
        finishJob = resolve;
      }),
    );
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    const runButton = screen.getByRole("button", { name: "运行节点" });
    fireEvent.click(runButton);
    fireEvent.click(runButton);

    await waitFor(() => {
      expect(mockAigcStudioApi.runJob).toHaveBeenCalledTimes(1);
    });
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(mockAigcStudioApi.submitJob).toHaveBeenCalledTimes(1);

    finishJob({
      ...jobFixture(),
      id: "job-2",
      status: "succeeded",
      outputs: [
        {
          id: "asset-1",
          kind: "image",
          name: "image-1.svg",
          path: "aigc_studio/canvas-1/job-2/image-1.svg",
          url: "/api/user/aigc-studio/assets/asset-1/file",
          mime_type: "image/svg+xml",
          created_at: "2026-05-30T00:00:00Z",
        },
      ],
    });
  });

  it("advances simulated image progress while polling for the final result", async () => {
    let finishJob: (value: unknown) => void = () => undefined;
    mockAigcStudioApi.runJob.mockReturnValue(
      new Promise((resolve) => {
        finishJob = resolve;
      }),
    );
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    fireEvent.click(screen.getByRole("button", { name: "运行节点" }));

    const editor = await screen.findByTestId("aigc-image-editor");
    await waitFor(() => {
      expect(editor).toHaveAttribute("data-image-state", "generating");
    });
    expect(editor).toHaveTextContent("生成中 2%");

    await waitFor(
      () => {
        expect(editor).toHaveTextContent(/生成中 (?!2%)\d+%/);
      },
      { timeout: 2500 },
    );

    finishJob({
      ...jobFixture(),
      id: "job-2",
      status: "succeeded",
      outputs: [
        {
          id: "asset-1",
          kind: "image",
          name: "image-1.svg",
          path: "aigc_studio/canvas-1/job-2/image-1.svg",
          url: "/api/user/aigc-studio/assets/asset-1/file",
          mime_type: "image/svg+xml",
          created_at: "2026-05-30T00:00:00Z",
        },
      ],
    });

    await waitFor(() => {
      expect(editor).toHaveAttribute("data-image-state", "generated");
    });
  });

  it("supports cancelling and retrying jobs from the job list", async () => {
    mockAigcStudioApi.listJobs.mockResolvedValue({ jobs: [jobFixture()] });
    render(<AigcStudioPage />);

    await screen.findByText("已取消");
    fireEvent.click(screen.getByRole("button", { name: "取 消" }));
    await waitFor(() => {
      expect(mockAigcStudioApi.cancelJob).toHaveBeenCalledWith("job-1");
    });

    fireEvent.click(screen.getByRole("button", { name: "重 试" }));
    await waitFor(() => {
      expect(mockAigcStudioApi.retryJob).toHaveBeenCalledWith("job-1");
    });
  });

  it("adds nodes from the palette and persists them on save", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "视频生成" }));
    expect(screen.getByText("视频节点")).toBeInTheDocument();

    await clickToolbarSave();

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({ type: "video_generate" }),
          ]),
        }),
      );
    });
  });

  it("creates a new project as an empty canvas", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByLabelText("打开项目列表"));
    fireEvent.click(screen.getByRole("button", { name: /新建项目/ }));

    await waitFor(() => {
      expect(mockAigcStudioApi.createCanvas).toHaveBeenCalledWith(
        expect.objectContaining({
          nodes: [],
          edges: [],
        }),
      );
    });
    expect(screen.getByText("双击画布 自由生成节点")).toBeInTheDocument();
  });

  it("deletes a project from the project switcher and selects the next project", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        canvasFixture(),
        {
          ...emptyCanvasFixture(),
          id: "canvas-2",
          name: "我的项目",
        },
      ],
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByLabelText("打开项目列表"));
    fireEvent.click(screen.getByLabelText("删除项目 未命名 AIGC 画布"));

    await waitFor(() => {
      expect(mockAigcStudioApi.deleteCanvas).toHaveBeenCalledWith("canvas-1");
    });
    expect(confirmSpy).toHaveBeenCalledWith(
      "确定删除「未命名 AIGC 画布」吗？该项目的画布和任务记录会一起删除。",
    );
    expect(screen.getByDisplayValue("我的项目")).toBeInTheDocument();
    expect(mockAigcStudioApi.listJobs).toHaveBeenCalledWith("canvas-2");

    confirmSpy.mockRestore();
  });

  it("builds a LibTV-style video node with frame references and video menus", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "视频生成" }));

    const editor = screen.getByTestId("aigc-video-editor");
    expect(editor).toHaveTextContent("首尾帧生成视频");
    expect(editor).toHaveTextContent("首帧生成视频");

    fireEvent.change(within(editor).getByLabelText("上传首尾帧图片"), {
      target: {
        files: [
          new File(["first"], "first.png", { type: "image/png" }),
          new File(["last"], "last.png", { type: "image/png" }),
        ],
      },
    });

    await waitFor(() => {
      expect(screen.queryByText("输入已更新")).not.toBeInTheDocument();
      expect(screen.getAllByText("首帧").length).toBeGreaterThan(0);
      expect(screen.getAllByText("尾帧").length).toBeGreaterThan(0);
      const referenceThumbs = screen.getAllByTestId(
        "aigc-video-reference-thumb",
      );
      expect(referenceThumbs).toHaveLength(2);
      expect(referenceThumbs[0]).toHaveTextContent("1");
      expect(referenceThumbs[1]).toHaveTextContent("2");
    });

    const composer = screen.getByTestId("aigc-video-composer");
    expect(within(composer).getByText("文生视频")).toBeInTheDocument();
    expect(within(composer).getByText("全能参考")).toBeInTheDocument();
    expect(within(composer).getByText("图生视频")).toBeInTheDocument();
    fireEvent.change(within(composer).getByLabelText("视频节点输入"), {
      target: { value: "从产品特写自然过渡到人物饮用场景" },
    });
    fireEvent.click(
      within(composer).getByRole("button", { name: /Seedance 2.0/ }),
    );
    fireEvent.click(
      within(screen.getByTestId("aigc-video-model-menu")).getByRole("button", {
        name: /Seedance 2.0 Fast/,
      }),
    );
    fireEvent.click(within(composer).getByRole("button", { name: /720P/ }));
    fireEvent.click(
      within(screen.getByTestId("aigc-video-settings-menu")).getByText("1080P"),
    );
    fireEvent.click(within(composer).getByRole("button", { name: "运镜" }));
    expect(screen.getByTestId("aigc-video-motion-library")).toHaveTextContent(
      "镜头前推",
    );
    fireEvent.click(screen.getByText("镜头前推"));
    fireEvent.click(within(composer).getByRole("button", { name: "角色库" }));
    expect(
      screen.getByTestId("aigc-video-character-library"),
    ).toHaveTextContent("本地上传");
    fireEvent.click(within(composer).getByRole("button", { name: /1个/ }));
    fireEvent.click(
      within(screen.getByTestId("aigc-video-count-menu")).getByText("4个"),
    );
    fireEvent.click(
      within(composer).getByRole("button", { name: "提交视频节点输入" }),
    );
    await clickToolbarSave();

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "reference_asset",
              data: expect.objectContaining({
                previewKind: "uploaded_source",
                assetShape: "wide",
                assetName: "first.png",
              }),
            }),
            expect.objectContaining({
              type: "reference_asset",
              data: expect.objectContaining({
                previewKind: "uploaded_source",
                assetName: "last.png",
              }),
            }),
            expect.objectContaining({
              type: "video_generate",
              data: expect.objectContaining({
                videoMode: "first_last_frames",
                referenceCount: 2,
                videoModel: "Seedance 2.0 Fast",
                modelId: "seedance2-fast",
                videoResolution: "1080P",
                videoCount: 4,
                motionPreset: "镜头前推",
                text: "从产品特写自然过渡到人物饮用场景",
              }),
            }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              sourceHandle: "right",
              targetHandle: "left",
            }),
          ]),
        }),
      );
    });
  }, 10000);

  it("derives video composer modes from connected media nodes", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            {
              id: "image-a",
              type: "image_generate",
              position: { x: 80, y: 80 },
              data: { title: "图片节点 A", previewKind: "generated" },
            },
            {
              id: "image-b",
              type: "image_generate",
              position: { x: 80, y: 380 },
              data: { title: "图片节点 B", previewKind: "generated" },
            },
            {
              id: "video-1",
              type: "video_generate",
              position: { x: 660, y: 120 },
              data: {
                title: "视频节点 3",
                activeVideoTab: "text_to_video",
                videoMode: "text_to_video",
              },
            },
          ],
          edges: [
            {
              id: "edge-image-a-video-1",
              source: "image-a",
              target: "video-1",
              sourceHandle: "right",
              targetHandle: "left",
            },
            {
              id: "edge-image-b-video-1",
              source: "image-b",
              target: "video-1",
              sourceHandle: "right",
              targetHandle: "left",
            },
          ],
        },
      ],
    });

    render(<AigcStudioPage />);

    await screen.findByText("视频节点 3");
    fireEvent.click(screen.getByTestId("aigc-node-video-1"));

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
  });

  it("shows the video generation progress state inside the node preview", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            {
              id: "video-1",
              type: "video_generate",
              position: { x: 360, y: 80 },
              data: {
                title: "视频节点 2",
                text: "修仙小女孩踩着飞剑，像是冲浪一样划过云端",
                job_status: "running",
                videoProgress: 1,
                aspectRatio: "16:9",
                videoResolution: "720P",
                videoDuration: 5,
                outputs: [],
              },
            },
          ],
          edges: [],
        },
      ],
    });

    render(<AigcStudioPage />);

    await screen.findByText("视频节点 2");
    fireEvent.click(screen.getByTestId("aigc-node-video-1"));

    const editor = screen.getByTestId("aigc-video-editor");
    expect(editor).toHaveAttribute("data-video-state", "generating");
    expect(editor).toHaveTextContent("生成中 1%...");
    expect(within(editor).getByRole("button", { name: "取消生成" }));
  });

  it("advances simulated video progress while the video job is running", async () => {
    let finishJob: (value: unknown) => void = () => undefined;
    mockAigcStudioApi.runJob.mockReturnValue(
      new Promise((resolve) => {
        finishJob = resolve;
      }),
    );
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            {
              id: "video-1",
              type: "video_generate",
              position: { x: 360, y: 80 },
              data: {
                title: "视频节点 2",
                text: "小姑娘飞在空中，穿梭在高楼大厦之间",
                aspectRatio: "16:9",
                videoResolution: "720P",
                videoDuration: 5,
                outputs: [],
              },
            },
          ],
          edges: [],
        },
      ],
    });

    render(<AigcStudioPage />);

    await screen.findByText("视频节点 2");
    fireEvent.click(screen.getByTestId("aigc-node-video-1"));
    fireEvent.click(screen.getByRole("button", { name: "运行节点" }));

    const editor = await screen.findByTestId("aigc-video-editor");
    await waitFor(() => {
      expect(editor).toHaveAttribute("data-video-state", "generating");
    });
    expect(editor).toHaveTextContent("生成中 1%");

    await waitFor(
      () => {
        expect(editor).toHaveTextContent(/生成中 (?!1%)\d+%/);
      },
      { timeout: 2500 },
    );

    finishJob({
      ...jobFixture(),
      id: "job-2",
      node_id: "video-1",
      capability: "text_to_video",
      status: "succeeded",
      outputs: [
        {
          id: "asset-video-1",
          kind: "video",
          name: "video-1.mp4",
          path: "aigc_studio/canvas-1/job-2/video-1.mp4",
          url: "/api/user/aigc-studio/assets/asset-video-1/file",
          mime_type: "video/mp4",
          created_at: "2026-05-30T00:00:00Z",
        },
      ],
    });

    await waitFor(() => {
      expect(editor).toHaveAttribute("data-video-state", "generated");
    });
  });

  it("cancels video generation from the node preview", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            {
              id: "video-1",
              type: "video_generate",
              position: { x: 360, y: 80 },
              data: {
                title: "视频节点 2",
                text: "修仙小女孩踩着飞剑，像是冲浪一样划过云端",
                job_status: "running",
                videoProgress: 18,
                outputs: [],
              },
            },
          ],
          edges: [],
        },
      ],
    });

    render(<AigcStudioPage />);

    await screen.findByText("视频节点 2");
    fireEvent.click(screen.getByTestId("aigc-node-video-1"));

    const editor = screen.getByTestId("aigc-video-editor");
    fireEvent.click(within(editor).getByRole("button", { name: "取消生成" }));
    expect(await within(editor).findByText("已取消生成")).toBeInTheDocument();

    await clickToolbarSave();

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              id: "video-1",
              data: expect.objectContaining({
                job_error: "已取消生成",
                job_status: "cancelled",
                videoProgress: null,
                videoState: "failed",
              }),
            }),
          ]),
        }),
      );
    });
  });

  it("retries failed video generation from the node preview", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            {
              id: "video-1",
              type: "video_generate",
              position: { x: 360, y: 80 },
              data: {
                title: "视频节点 2",
                text: "修仙小女孩踩着飞剑，像是冲浪一样划过云端",
                error: "生成超时",
                job_error: "生成超时",
                job_status: "failed",
                videoProgress: null,
                videoState: "failed",
              },
            },
          ],
          edges: [],
        },
      ],
    });

    render(<AigcStudioPage />);

    await screen.findByText("视频节点 2");
    fireEvent.click(screen.getByTestId("aigc-node-video-1"));

    const editor = screen.getByTestId("aigc-video-editor");
    expect(editor).toHaveAttribute("data-video-state", "failed");
    fireEvent.click(within(editor).getByRole("button", { name: "重试生成" }));
    await waitFor(() => {
      expect(editor).toHaveAttribute("data-video-state", "generating");
    });

    await clickToolbarSave();

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              id: "video-1",
              data: expect.objectContaining({
                error: null,
                job_error: null,
                job_status: "running",
                outputs: [],
                videoProgress: 1,
                videoState: "generating",
              }),
            }),
          ]),
        }),
      );
    });
  });

  it("shows generated video playback, dimensions, and result actions", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            {
              id: "video-1",
              type: "video_generate",
              position: { x: 360, y: 80 },
              data: {
                title: "视频节点 2",
                text: "修仙小女孩踩着飞剑，像是冲浪一样划过云端",
                aspectRatio: "16:9",
                videoResolution: "720P",
                videoDuration: 5,
                outputs: [
                  {
                    id: "asset-video-1",
                    kind: "video",
                    name: "flying-sword.mp4",
                    path: "aigc_studio/canvas-1/job-2/flying-sword.mp4",
                    url: "/api/user/aigc-studio/assets/asset-video-1/file",
                    mime_type: "video/mp4",
                    width: 1280,
                    height: 720,
                    created_at: "2026-05-30T00:00:00Z",
                  },
                ],
              },
            },
          ],
          edges: [],
        },
      ],
    });

    render(<AigcStudioPage />);

    await screen.findByText("视频节点 2");
    fireEvent.click(screen.getByTestId("aigc-node-video-1"));

    const editor = screen.getByTestId("aigc-video-editor");
    expect(editor).toHaveAttribute("data-video-state", "generated");
    expect(screen.getByTestId("aigc-video-result-preview")).toBeInTheDocument();
    expect(
      screen.queryByText("/api/user/aigc-studio/assets/asset-video-1/file"),
    ).not.toBeInTheDocument();
    expect(editor).toHaveTextContent("1280 × 720");
    expect(
      screen.getByTestId("aigc-video-playback-controls"),
    ).toHaveTextContent("0:00");
    expect(
      screen.getByTestId("aigc-video-playback-controls"),
    ).toHaveTextContent("0:05");
    expect(screen.getByRole("button", { name: "播放视频" }));
    expect(screen.getByRole("button", { name: "当前画面截图" }));

    const toolbar = screen.getByTestId("aigc-video-viewer-toolbar");
    expect(within(toolbar).getByRole("button", { name: "剪辑" }));
    expect(within(toolbar).getByRole("button", { name: "裁剪" }));
    expect(within(toolbar).getByRole("button", { name: "高清" }));
    expect(within(toolbar).getByRole("button", { name: "解析" }));
    expect(within(toolbar).getByRole("button", { name: "智能去字幕" }));
    expect(within(toolbar).getByRole("button", { name: "音频分离" }));
    expect(within(toolbar).getByRole("button", { name: "下载视频" }));
    expect(within(toolbar).getByRole("button", { name: "全屏查看视频" }));
  });

  it("creates downstream nodes from generated video result actions", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            {
              id: "video-1",
              type: "video_generate",
              position: { x: 360, y: 80 },
              data: {
                title: "视频节点 2",
                text: "修仙小女孩踩着飞剑，像是冲浪一样划过云端",
                aspectRatio: "16:9",
                videoResolution: "720P",
                videoDuration: 5,
                outputs: [
                  {
                    id: "asset-video-1",
                    kind: "video",
                    name: "flying-sword.mp4",
                    path: "aigc_studio/canvas-1/job-2/flying-sword.mp4",
                    mime_type: "video/mp4",
                    width: 1280,
                    height: 720,
                    created_at: "2026-05-30T00:00:00Z",
                  },
                ],
              },
            },
          ],
          edges: [],
        },
      ],
    });

    render(<AigcStudioPage />);

    await screen.findByText("视频节点 2");
    const clickVideoAction = (name: string) => {
      fireEvent.click(screen.getByTestId("aigc-node-video-1"));
      const toolbar = screen.getByTestId("aigc-video-viewer-toolbar");
      fireEvent.click(within(toolbar).getByRole("button", { name }));
    };

    clickVideoAction("高清");
    clickVideoAction("解析");
    clickVideoAction("音频分离");
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              id: expect.stringMatching(/^video-upscale-/),
              type: "video_generate",
              data: expect.objectContaining({
                title: "视频高清",
                videoMode: "video_upscale",
                referenceVideoNodeId: "video-1",
                referenceAssetName: "flying-sword.mp4",
                referencePreviewUrl:
                  "aigc_studio/canvas-1/job-2/flying-sword.mp4",
              }),
            }),
            expect.objectContaining({
              id: expect.stringMatching(/^video-analysis-/),
              type: "prompt",
              data: expect.objectContaining({
                title: "视频解析",
                sourceVideoNodeId: "video-1",
                sourceVideoOutputPath:
                  "aigc_studio/canvas-1/job-2/flying-sword.mp4",
              }),
            }),
            expect.objectContaining({
              id: expect.stringMatching(/^video-audio-/),
              type: "reference_asset",
              data: expect.objectContaining({
                title: "分离音频",
                assetKind: "audio",
                sourceVideoNodeId: "video-1",
                sourceVideoOutputPath:
                  "aigc_studio/canvas-1/job-2/flying-sword.mp4",
              }),
            }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              source: "video-1",
              target: expect.stringMatching(/^video-upscale-/),
              sourceHandle: "right",
              targetHandle: "left",
            }),
            expect.objectContaining({
              source: "video-1",
              target: expect.stringMatching(/^video-analysis-/),
            }),
            expect.objectContaining({
              source: "video-1",
              target: expect.stringMatching(/^video-audio-/),
            }),
          ]),
        }),
      );
    });
  });

  it("creates edit, crop, and subtitle-removal video nodes from generated result actions", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            {
              id: "video-1",
              type: "video_generate",
              position: { x: 360, y: 80 },
              data: {
                title: "视频节点 2",
                text: "修仙小女孩踩着飞剑，像是冲浪一样划过云端",
                aspectRatio: "16:9",
                videoResolution: "720P",
                videoDuration: 5,
                outputs: [
                  {
                    id: "asset-video-1",
                    kind: "video",
                    name: "flying-sword.mp4",
                    path: "aigc_studio/canvas-1/job-2/flying-sword.mp4",
                    mime_type: "video/mp4",
                    width: 1280,
                    height: 720,
                    created_at: "2026-05-30T00:00:00Z",
                  },
                ],
              },
            },
          ],
          edges: [],
        },
      ],
    });

    render(<AigcStudioPage />);

    await screen.findByText("视频节点 2");
    const clickVideoAction = (name: string) => {
      fireEvent.click(screen.getByTestId("aigc-node-video-1"));
      const toolbar = screen.getByTestId("aigc-video-viewer-toolbar");
      fireEvent.click(within(toolbar).getByRole("button", { name }));
    };

    clickVideoAction("剪辑");
    clickVideoAction("裁剪");
    clickVideoAction("智能去字幕");
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              id: expect.stringMatching(/^video-edit-/),
              type: "video_generate",
              data: expect.objectContaining({
                title: "视频剪辑",
                videoMode: "video_edit",
                referenceVideoNodeId: "video-1",
                referenceAssetName: "flying-sword.mp4",
              }),
            }),
            expect.objectContaining({
              id: expect.stringMatching(/^video-crop-/),
              type: "video_generate",
              data: expect.objectContaining({
                title: "视频裁剪",
                videoMode: "video_crop",
                cropMode: "free",
                referenceVideoNodeId: "video-1",
              }),
            }),
            expect.objectContaining({
              id: expect.stringMatching(/^video-subtitle-removal-/),
              type: "video_generate",
              data: expect.objectContaining({
                title: "智能去字幕",
                videoMode: "remove_subtitles",
                referenceVideoNodeId: "video-1",
              }),
            }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              source: "video-1",
              target: expect.stringMatching(/^video-edit-/),
              sourceHandle: "right",
              targetHandle: "left",
            }),
            expect.objectContaining({
              source: "video-1",
              target: expect.stringMatching(/^video-crop-/),
            }),
            expect.objectContaining({
              source: "video-1",
              target: expect.stringMatching(/^video-subtitle-removal-/),
            }),
          ]),
        }),
      );
    });
  });

  it("creates downstream nodes from uploaded video tool actions", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            {
              id: "video-1",
              type: "video_generate",
              position: { x: 360, y: 80 },
              data: {
                title: "视频节点 2",
                previewKind: "uploaded_video",
                videoAssetName: "uploaded-demo.mp4",
                videoPreviewUrl: "blob:uploaded-demo",
                videoDuration: 5,
                videoResolution: "720P",
                aspectRatio: "16:9",
              },
            },
          ],
          edges: [],
        },
      ],
    });

    render(<AigcStudioPage />);

    await screen.findByText("视频节点 2");
    fireEvent.click(screen.getByTestId("aigc-node-video-1"));

    const strip = screen.getByTestId("aigc-video-tool-strip");
    fireEvent.click(within(strip).getByRole("button", { name: "智能去字幕" }));
    fireEvent.click(screen.getByTestId("aigc-node-video-1"));
    fireEvent.click(within(strip).getByRole("button", { name: "音频分离" }));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              id: expect.stringMatching(/^video-subtitle-removal-/),
              type: "video_generate",
              data: expect.objectContaining({
                title: "智能去字幕",
                videoMode: "remove_subtitles",
                referenceVideoNodeId: "video-1",
                referenceAssetName: "uploaded-demo.mp4",
                referencePreviewUrl: "blob:uploaded-demo",
              }),
            }),
            expect.objectContaining({
              id: expect.stringMatching(/^video-audio-/),
              type: "reference_asset",
              data: expect.objectContaining({
                title: "分离音频",
                assetKind: "audio",
                sourceVideoNodeId: "video-1",
                sourceVideoName: "uploaded-demo.mp4",
                sourceVideoOutputPath: "blob:uploaded-demo",
              }),
            }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              source: "video-1",
              target: expect.stringMatching(/^video-subtitle-removal-/),
              sourceHandle: "right",
              targetHandle: "left",
            }),
            expect.objectContaining({
              source: "video-1",
              target: expect.stringMatching(/^video-audio-/),
            }),
          ]),
        }),
      );
    });
  });

  it("shows uploaded video preview metadata and playback controls", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            {
              id: "video-1",
              type: "video_generate",
              position: { x: 360, y: 80 },
              data: {
                title: "视频节点 2",
                previewKind: "uploaded_video",
                videoAssetName: "uploaded-demo.mp4",
                videoPreviewUrl: "blob:uploaded-demo",
                videoDuration: 5,
                videoResolution: "720P",
                aspectRatio: "16:9",
              },
            },
          ],
          edges: [],
        },
      ],
    });

    render(<AigcStudioPage />);

    await screen.findByText("视频节点 2");
    fireEvent.click(screen.getByTestId("aigc-node-video-1"));

    const editor = screen.getByTestId("aigc-video-editor");
    expect(editor).toHaveTextContent("uploaded-demo.mp4");
    expect(editor).toHaveTextContent("16:9 · 720P · 5s");

    const controls = within(editor).getByTestId("aigc-uploaded-video-controls");
    expect(
      within(controls).getByRole("button", { name: "播放上传视频" }),
    ).toBeInTheDocument();
    expect(
      within(controls).getByRole("progressbar", {
        name: "上传视频播放进度",
      }),
    ).toBeInTheDocument();
    fireEvent.click(
      within(controls).getByRole("button", { name: "当前画面截图" }),
    );
    expect(editor).not.toHaveTextContent("已准备下载");
  });

  it("creates edit and crop nodes from uploaded video tool actions", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            {
              id: "video-1",
              type: "video_generate",
              position: { x: 360, y: 80 },
              data: {
                title: "视频节点 2",
                previewKind: "uploaded_video",
                videoAssetName: "uploaded-demo.mp4",
                videoPreviewUrl: "blob:uploaded-demo",
                videoDuration: 5,
                videoResolution: "720P",
                aspectRatio: "16:9",
              },
            },
          ],
          edges: [],
        },
      ],
    });

    render(<AigcStudioPage />);

    await screen.findByText("视频节点 2");
    fireEvent.click(screen.getByTestId("aigc-node-video-1"));

    const strip = screen.getByTestId("aigc-video-tool-strip");
    fireEvent.click(within(strip).getByRole("button", { name: "剪辑" }));
    fireEvent.click(screen.getByTestId("aigc-node-video-1"));
    fireEvent.click(within(strip).getByRole("button", { name: "裁剪" }));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              id: expect.stringMatching(/^video-edit-/),
              type: "video_generate",
              data: expect.objectContaining({
                title: "视频剪辑",
                videoMode: "video_edit",
                referenceVideoNodeId: "video-1",
                referenceAssetName: "uploaded-demo.mp4",
                referencePreviewUrl: "blob:uploaded-demo",
              }),
            }),
            expect.objectContaining({
              id: expect.stringMatching(/^video-crop-/),
              type: "video_generate",
              data: expect.objectContaining({
                title: "视频裁剪",
                videoMode: "video_crop",
                cropMode: "free",
                referenceVideoNodeId: "video-1",
                referenceAssetName: "uploaded-demo.mp4",
                referencePreviewUrl: "blob:uploaded-demo",
              }),
            }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              source: "video-1",
              target: expect.stringMatching(/^video-edit-/),
              sourceHandle: "right",
              targetHandle: "left",
            }),
            expect.objectContaining({
              source: "video-1",
              target: expect.stringMatching(/^video-crop-/),
            }),
          ]),
        }),
      );
    });
  });

  it("aligns video composer quick tools with effects, motion, and prompt helpers", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "视频生成" }));

    const composer = screen.getByTestId("aigc-video-composer");
    expect(within(composer).getByRole("button", { name: "标记" }));
    fireEvent.click(within(composer).getByRole("button", { name: "特效" }));
    expect(screen.getByTestId("aigc-video-effect-library")).toHaveTextContent(
      "特效广场",
    );
    expect(screen.getByTestId("aigc-video-effect-library")).toHaveTextContent(
      "穿云而入",
    );

    fireEvent.click(within(composer).getByRole("button", { name: "运镜" }));
    expect(screen.getByTestId("aigc-video-motion-library")).toHaveTextContent(
      "固定镜头",
    );

    const promptOptimize = within(composer).getByRole("button", {
      name: "提示词优化",
    });
    fireEvent.mouseEnter(promptOptimize);
    expect(screen.getByRole("tooltip")).toHaveTextContent("提示词优化");
    fireEvent.mouseLeave(promptOptimize);

    const translatePrompt = within(composer).getByRole("button", {
      name: "翻译提示词",
    });
    fireEvent.focus(translatePrompt);
    expect(screen.getByRole("tooltip")).toHaveTextContent("翻译提示词");
  });

  it("disables media reference modes until upstream media is connected", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "视频生成" }));

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
      within(composer).queryByTestId("aigc-video-reference-panel"),
    ).not.toBeInTheDocument();
  });

  it("uploads image-to-video references from the video node and persists preview metadata", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "视频生成" }));

    const composer = screen.getByTestId("aigc-video-composer");
    fireEvent.change(screen.getByLabelText("上传首帧图片"), {
      target: {
        files: [new File(["start"], "start-frame.png", { type: "image/png" })],
      },
    });

    expect(screen.queryByText("输入已更新")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(
        screen.getByTestId("aigc-video-reference-thumb"),
      ).toHaveTextContent("1");
    });

    fireEvent.change(within(composer).getByLabelText("视频节点输入"), {
      target: { value: "让角色从参考图里自然转身走向镜头" },
    });
    fireEvent.click(
      within(composer).getByRole("button", { name: "提交视频节点输入" }),
    );
    await clickToolbarSave();

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "reference_asset",
              data: expect.objectContaining({
                previewKind: "uploaded_source",
                assetName: "start-frame.png",
              }),
            }),
            expect.objectContaining({
              type: "video_generate",
              data: expect.objectContaining({
                activeVideoTab: "image_to_video",
                videoMode: "image_to_video",
                referenceThumb: true,
                referenceAssetName: "start-frame.png",
                referenceCount: 1,
                text: "让角色从参考图里自然转身走向镜头",
              }),
            }),
          ]),
        }),
      );
    });
  }, 10000);

  it("selects compliant character assets from the video material library", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "视频生成" }));

    const composer = screen.getByTestId("aigc-video-composer");
    fireEvent.click(within(composer).getByRole("button", { name: "角色库" }));

    const library = screen.getByTestId("aigc-video-character-library");
    expect(library).toHaveTextContent("Seedance2.0合规素材库");
    expect(library).toHaveTextContent("真人像");
    expect(library).toHaveTextContent("NEW");
    expect(library).toHaveTextContent("图片");
    expect(library).toHaveTextContent("视频");
    expect(library).toHaveTextContent("音频");
    expect(library).toHaveTextContent("已选 0/9 张");
    expect(library).toHaveTextContent("历史资产选择");

    fireEvent.click(
      within(library).getByRole("button", { name: "湘左记门店" }),
    );
    fireEvent.click(within(library).getByRole("button", { name: "产品包装" }));

    expect(library).toHaveTextContent("已选 2/9 张");
    expect(
      within(library).getByRole("button", { name: "湘左记门店" }),
    ).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(within(library).getByRole("button", { name: "确定" }));

    expect(
      screen.queryByTestId("aigc-video-character-library"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("aigc-video-character-summary"),
    ).toHaveTextContent("2");
    expect(
      screen.getByTestId("aigc-video-character-summary"),
    ).toHaveTextContent("湘左记门店、产品包装");
  }, 10000);

  it("filters video material assets by tab and caps character selections at nine", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "视频生成" }));

    const composer = screen.getByTestId("aigc-video-composer");
    fireEvent.click(within(composer).getByRole("button", { name: "角色库" }));

    const library = screen.getByTestId("aigc-video-character-library");
    fireEvent.click(within(library).getByRole("button", { name: "图片" }));
    expect(
      within(library).queryByRole("button", { name: "湘左记门店" }),
    ).not.toBeInTheDocument();
    expect(
      within(library).getByRole("button", { name: "产品包装" }),
    ).toBeInTheDocument();

    fireEvent.click(within(library).getByRole("button", { name: "真人像" }));
    [
      "湘左记门店",
      "门店讲解员",
      "顾客侧影",
      "外景主持",
      "侧脸参考",
      "手部动作",
      "儿童演员",
      "银发顾客",
      "骑手演员",
    ].forEach((name) => {
      fireEvent.click(within(library).getByRole("button", { name }));
    });

    expect(library).toHaveTextContent("已选 9/9 张");
    expect(
      within(library).getByRole("button", { name: "收银员" }),
    ).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(within(library).getByRole("button", { name: "收银员" }));
    expect(library).toHaveTextContent("已选 9/9 张");
  }, 10000);

  it("renders a LibTV-style canvas shell with floating add menu and templates", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [emptyCanvasFixture()],
    });
    render(<AigcStudioPage />);

    await screen.findByText("双击画布 自由生成节点");
    expect(screen.getByLabelText("添加节点")).toBeInTheDocument();
    expect(screen.getByText("故事脚本生成")).toBeInTheDocument();
    expect(screen.getByText("角色三视图")).toBeInTheDocument();
    expect(screen.getByTestId("aigc-template-story")).toBeInTheDocument();
    expect(screen.getByTestId("aigc-template-character")).toBeInTheDocument();
    expect(screen.getByTestId("aigc-template-keyframe")).toBeInTheDocument();
    expect(screen.getByTestId("aigc-template-audioVideo")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("添加节点"));

    expect(screen.getByText("文本")).toBeInTheDocument();
    expect(screen.getByText("图片")).toBeInTheDocument();
    expect(screen.getByText("视频")).toBeInTheDocument();
    expect(screen.getByText("视频合成")).toBeInTheDocument();
    expect(screen.getByText("导演台")).toBeInTheDocument();
    expect(screen.getByText("音频")).toBeInTheDocument();
    expect(screen.getByText("脚本")).toBeInTheDocument();
  });

  it("creates director stage nodes through the AIGC add menu", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [emptyCanvasFixture()],
    });
    render(<AigcStudioPage />);

    await screen.findByText("双击画布 自由生成节点");
    fireEvent.click(screen.getByLabelText("添加节点"));

    const directorStageDescription = await screen.findByText(
      "3D 场景、机位、角色调度",
    );
    fireEvent.click(
      directorStageDescription.closest("button") as HTMLButtonElement,
    );

    expect(await screen.findByText("未创建场景")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "打开导演台" }),
    ).toBeInTheDocument();
  });

  it("opens a blank-canvas context menu for adding nodes, uploading assets and pasting", async () => {
    const canvas = canvasFixture();
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [canvas],
    });
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    const surface = screen.getByTestId("aigc-canvas-surface");
    fireEvent.contextMenu(surface, { clientX: 460, clientY: 280 });

    const menu = screen.getByTestId("aigc-canvas-context-menu");
    expect(within(menu).getByText("添加节点")).toBeInTheDocument();
    expect(within(menu).getByText("上传图片")).toBeInTheDocument();
    expect(within(menu).getByText("上传视频")).toBeInTheDocument();
    expect(within(menu).getByText("上传音频")).toBeInTheDocument();
    expect(
      within(menu).queryByRole("button", { name: "图片" }),
    ).not.toBeInTheDocument();

    fireEvent.click(within(menu).getByRole("button", { name: "添加节点" }));
    fireEvent.click(within(menu).getByRole("button", { name: "图片" }));
    expect(screen.getByText("图片节点")).toBeInTheDocument();
  });

  it("opens the add-node menu on blank-canvas double click", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [emptyCanvasFixture()],
    });
    render(<AigcStudioPage />);

    await screen.findByText("双击画布 自由生成节点");
    const surface = screen.getByTestId("aigc-canvas-surface");
    fireEvent.doubleClick(surface, { clientX: 600, clientY: 400 });

    const imageNodeDescription = await screen.findByText(
      "文生图、图生图、参考图",
    );
    fireEvent.click(
      imageNodeDescription.closest("button") as HTMLButtonElement,
    );
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "image_generate",
              position: { x: 600, y: 400 },
            }),
          ]),
        }),
      );
    });
  });

  it("creates double-click nodes at the operated canvas point after pan and zoom", async () => {
    const getBoundingClientRect = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({
        x: 200,
        y: 80,
        left: 200,
        top: 80,
        right: 1200,
        bottom: 840,
        width: 1000,
        height: 760,
        toJSON: () => ({}),
      } as DOMRect);
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...emptyCanvasFixture(),
          viewport: { x: -120, y: -70, zoom: 0.5 },
        },
      ],
    });
    render(<AigcStudioPage />);

    await screen.findByText("双击画布 自由生成节点");
    const surface = screen.getByTestId("aigc-canvas-surface");
    fireEvent.doubleClick(surface, { clientX: 700, clientY: 430 });

    const imageNodeDescription = await screen.findByText(
      "文生图、图生图、参考图",
    );
    fireEvent.click(
      imageNodeDescription.closest("button") as HTMLButtonElement,
    );
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "image_generate",
              position: { x: 1240, y: 840 },
            }),
          ]),
        }),
      );
    });
    getBoundingClientRect.mockRestore();
  });

  it("creates right-click context-menu nodes at the operated canvas point after pan and zoom", async () => {
    const getBoundingClientRect = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({
        x: 200,
        y: 80,
        left: 200,
        top: 80,
        right: 1200,
        bottom: 840,
        width: 1000,
        height: 760,
        toJSON: () => ({}),
      } as DOMRect);
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...emptyCanvasFixture(),
          viewport: { x: -120, y: -70, zoom: 0.5 },
        },
      ],
    });
    render(<AigcStudioPage />);

    await screen.findByText("双击画布 自由生成节点");
    const surface = screen.getByTestId("aigc-canvas-surface");
    fireEvent.contextMenu(surface, { clientX: 700, clientY: 430 });

    const menu = screen.getByTestId("aigc-canvas-context-menu");
    fireEvent.click(within(menu).getByRole("button", { name: "添加节点" }));
    fireEvent.click(within(menu).getByRole("button", { name: "图片" }));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "image_generate",
              position: { x: 1240, y: 840 },
            }),
          ]),
        }),
      );
    });
    getBoundingClientRect.mockRestore();
  });

  it("creates right-click uploaded asset nodes at the operated canvas point after pan and zoom", async () => {
    const getBoundingClientRect = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({
        x: 200,
        y: 80,
        left: 200,
        top: 80,
        right: 1200,
        bottom: 840,
        width: 1000,
        height: 760,
        toJSON: () => ({}),
      } as DOMRect);
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...emptyCanvasFixture(),
          viewport: { x: -120, y: -70, zoom: 0.5 },
        },
      ],
    });
    const { container } = render(<AigcStudioPage />);

    await screen.findByText("双击画布 自由生成节点");
    const surface = screen.getByTestId("aigc-canvas-surface");
    fireEvent.contextMenu(surface, { clientX: 700, clientY: 430 });

    const menu = screen.getByTestId("aigc-canvas-context-menu");
    fireEvent.click(within(menu).getByRole("button", { name: "上传图片" }));
    const imageInput = container.querySelector<HTMLInputElement>(
      'input[accept="image/*"]',
    );
    expect(imageInput).toBeTruthy();
    fireEvent.change(imageInput!, {
      target: {
        files: [new File(["image"], "right-click.png", { type: "image/png" })],
      },
    });

    await waitFor(() => {
      expect(mockAigcStudioApi.uploadAsset).toHaveBeenCalledTimes(1);
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "reference_asset",
              position: { x: 1240, y: 840 },
              data: expect.objectContaining({
                assetName: "right-click.png",
              }),
            }),
          ]),
        }),
      );
    });
    getBoundingClientRect.mockRestore();
  });

  it("keeps double-click node creation at negative canvas coordinates", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...emptyCanvasFixture(),
          viewport: { x: 600, y: 420, zoom: 1 },
        },
      ],
    });
    render(<AigcStudioPage />);

    await screen.findByText("双击画布 自由生成节点");
    const surface = screen.getByTestId("aigc-canvas-surface");
    fireEvent.doubleClick(surface, { clientX: 300, clientY: 280 });

    const imageNodeDescription = await screen.findByText(
      "文生图、图生图、参考图",
    );
    fireEvent.click(
      imageNodeDescription.closest("button") as HTMLButtonElement,
    );
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "image_generate",
              position: { x: -300, y: -140 },
            }),
          ]),
        }),
      );
    });
  });

  it("keeps right-click node creation at negative canvas coordinates", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...emptyCanvasFixture(),
          viewport: { x: 600, y: 420, zoom: 1 },
        },
      ],
    });
    render(<AigcStudioPage />);

    await screen.findByText("双击画布 自由生成节点");
    const surface = screen.getByTestId("aigc-canvas-surface");
    fireEvent.contextMenu(surface, { clientX: 300, clientY: 280 });

    const menu = screen.getByTestId("aigc-canvas-context-menu");
    fireEvent.click(within(menu).getByRole("button", { name: "添加节点" }));
    fireEvent.click(within(menu).getByRole("button", { name: "图片" }));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "image_generate",
              position: { x: -300, y: -140 },
            }),
          ]),
        }),
      );
    });
  });

  it("turns the script try action into an editable storyboard-script input flow", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...emptyCanvasFixture(),
          nodes: [
            {
              id: "script-standalone",
              type: "script_generate",
              position: { x: 500, y: 170 },
              data: {
                title: "脚本生成器",
                text: "根据上传的脚本生成一个完整的故事脚本",
                scriptMode: "idle",
                scriptView: "script",
                scriptInputKind: "script",
                scriptPrompt: "根据我上传的脚本生成一个完整的故事脚本",
                selectedShotIds: [],
              },
            },
          ],
          edges: [],
        },
      ],
    });
    render(<AigcStudioPage />);

    await screen.findByTestId("aigc-script-generator");
    fireEvent.click(screen.getByRole("button", { name: "剧本生成分镜脚本" }));

    expect(screen.queryByText(/我在盛唐写天下/)).not.toBeInTheDocument();
    const composer = screen.getByTestId("aigc-script-composer");
    const input = within(composer).getByRole("textbox", {
      name: "脚本生成器输入",
    });
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute(
      "placeholder",
      "描述剧情片段、故事，为你生成分镜脚本",
    );
    fillScriptComposer(composer, "女主加班后穿越盛唐，在朝堂用诗自证");

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalled();
    });
    const saveCanvasCalls = mockAigcStudioApi.saveCanvas.mock.calls;
    const savedPayload = saveCanvasCalls[saveCanvasCalls.length - 1]?.[1] as
      | {
          nodes: Array<{
            id: string;
            type: string;
            data: Record<string, unknown>;
          }>;
          edges: Array<Record<string, unknown>>;
        }
      | undefined;
    const sourceNode = savedPayload?.nodes.find(
      (node) => node.type === "prompt",
    );
    const scriptNode = savedPayload?.nodes.find(
      (node) => node.id === "script-standalone",
    );

    expect(sourceNode).toBeUndefined();
    expect(scriptNode?.data.scriptPrompt).toBe(
      "描述剧情或添加角色参考、视频参考等，为你生成分镜脚本",
    );
    expect(scriptNode?.data.composerText).toBe(
      "女主加班后穿越盛唐，在朝堂用诗自证",
    );
    expect(scriptNode?.data.scriptSourceNodeId).toBeNull();
    expect(savedPayload?.edges).toEqual([]);
  });

  it("moves from the script shot table into the asset preparation step", async () => {
    mockAigcStudioApi.listCapabilities.mockResolvedValueOnce({
      capabilities: [textCapability()],
    });
    mockAigcStudioApi.runJob.mockResolvedValueOnce(
      storyboardScriptJobFixture(),
    );
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [emptyCanvasFixture()],
    });
    render(<AigcStudioPage />);

    await screen.findByText("双击画布 自由生成节点");
    fireEvent.click(screen.getByTestId("aigc-template-story"));

    const composer = await screen.findByTestId("aigc-script-composer");
    fillScriptComposer(composer);
    fireEvent.click(
      within(composer).getByRole("button", { name: "提交脚本生成器" }),
    );

    const workflowEntry = await screen.findByTestId(
      "aigc-script-workflow-entry",
    );
    expect(workflowEntry).toHaveTextContent("打开脚本节点");
    fireEvent.click(
      within(workflowEntry).getByRole("button", { name: "打开脚本节点" }),
    );

    const table = await screen.findByTestId("aigc-script-table");
    expect(table).toHaveTextContent("镜号");
    const fullscreenNode = table.closest("[data-aigc-node]");
    expect(fullscreenNode).toHaveStyle({
      left: "28px",
      top: "48px",
      width: "calc(100% - 72px)",
      height: "calc(100% - 112px)",
    });
    const headers = Array.from(table.querySelectorAll("th")).map(
      (header) => header.textContent?.trim(),
    );
    expect(headers).toEqual(
      expect.arrayContaining([
        "镜号",
        "时长",
        "画面描述",
        "景别",
        "光影氛围",
        "对白-旁白",
        "音效",
        "运镜",
        "最终提示词",
        "操作",
      ]),
    );
    expect(
      screen.queryByTestId("aigc-storyboard-image-node"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("下一步：准备资产"));

    const assets = await screen.findByTestId("aigc-script-assets");
    expect(assets).toHaveTextContent("生成或上传角色图");
    expect(assets).toHaveTextContent("生成或上传场景图");
    expect(assets).not.toHaveTextContent("生成或上传道具图");
    expect(screen.getByText("一键生成所有资产")).toBeInTheDocument();
    expect(
      screen.queryByTestId("aigc-storyboard-composer"),
    ).not.toBeInTheDocument();
  });

  it("creates real script asset image nodes instead of marking assets ready", async () => {
    mockAigcStudioApi.listCapabilities.mockResolvedValueOnce({
      capabilities: [textCapability()],
    });
    mockAigcStudioApi.runJob.mockResolvedValueOnce(
      storyboardScriptJobFixture(),
    );
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [emptyCanvasFixture()],
    });
    render(<AigcStudioPage />);

    await screen.findByText("双击画布 自由生成节点");
    fireEvent.click(screen.getByTestId("aigc-template-story"));

    const composer = await screen.findByTestId("aigc-script-composer");
    fillScriptComposer(composer);
    fireEvent.click(
      within(composer).getByRole("button", { name: "提交脚本生成器" }),
    );

    const workflowEntry = await screen.findByTestId(
      "aigc-script-workflow-entry",
    );
    fireEvent.click(
      within(workflowEntry).getByRole("button", { name: "打开脚本节点" }),
    );
    await screen.findByTestId("aigc-script-table");
    fireEvent.click(screen.getByText("下一步：准备资产"));

    fireEvent.click(screen.getByText("一键生成所有资产"));
    const assetDialog = screen.getByRole("dialog", {
      name: "一键生成所有资产",
    });
    fireEvent.click(within(assetDialog).getByText(/^生成\(/));

    await waitFor(() => {
      expect(
        screen.getByText("资产图 · 童年时期的我（约6岁）"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText("资产图 · 瓦房大院，梧桐树下")).toBeInTheDocument();
    expect(screen.queryByText("资产图 · 关键道具")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "下一步：合成提示词" }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("aigc-script-workbench")).toHaveTextContent(
      "检测到有 2 个资产未生成",
    );
  }, 10000);

  it("keeps the expanded script node inside the canvas and lets users shrink it back", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [emptyCanvasFixture()],
    });
    render(<AigcStudioPage />);

    await screen.findByText("双击画布 自由生成节点");
    fireEvent.click(screen.getByTestId("aigc-template-story"));

    const composer = await screen.findByTestId("aigc-script-composer");
    fillScriptComposer(composer);
    fireEvent.click(
      within(composer).getByRole("button", { name: "提交脚本生成器" }),
    );

    const workflowEntry = await screen.findByTestId(
      "aigc-script-workflow-entry",
    );
    const scriptNode = workflowEntry.closest("[data-aigc-node]") as HTMLElement;
    expect(scriptNode).toBeTruthy();

    fireEvent.click(
      within(workflowEntry).getByRole("button", { name: "打开脚本节点" }),
    );
    expect(scriptNode).toHaveStyle({
      left: "28px",
      top: "48px",
      width: "calc(100% - 72px)",
      height: "calc(100% - 112px)",
    });
    expect(
      within(scriptNode).getByRole("button", { name: "退出放大" }),
    ).toBeInTheDocument();

    fireEvent.click(
      within(scriptNode).getByRole("button", { name: "退出放大" }),
    );
    expect(scriptNode).toHaveStyle({ width: "350px" });
    expect(
      within(scriptNode).getByRole("button", { name: "打开脚本节点" }),
    ).toBeInTheDocument();
  });

  it("keeps real script asset nodes linked to the fullscreen workflow", async () => {
    mockAigcStudioApi.listCapabilities.mockResolvedValueOnce({
      capabilities: [textCapability()],
    });
    mockAigcStudioApi.runJob.mockResolvedValueOnce(
      storyboardScriptJobFixture(),
    );
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [emptyCanvasFixture()],
    });
    render(<AigcStudioPage />);

    await screen.findByText("双击画布 自由生成节点");
    fireEvent.click(screen.getByTestId("aigc-template-story"));

    const composer = await screen.findByTestId("aigc-script-composer");
    fillScriptComposer(composer);
    fireEvent.click(
      within(composer).getByRole("button", { name: "提交脚本生成器" }),
    );

    const workflowEntry = await screen.findByTestId(
      "aigc-script-workflow-entry",
    );
    fireEvent.click(
      within(workflowEntry).getByRole("button", { name: "打开脚本节点" }),
    );
    await screen.findByTestId("aigc-script-table");
    fireEvent.click(screen.getByText("下一步：准备资产"));
    fireEvent.click(screen.getByText("一键生成所有资产"));
    const assetDialog = screen.getByRole("dialog", {
      name: "一键生成所有资产",
    });
    fireEvent.click(within(assetDialog).getByText(/^生成\(/));

    await waitFor(() => {
      expect(
        screen.getByText("资产图 · 童年时期的我（约6岁）"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText("资产图 · 瓦房大院，梧桐树下")).toBeInTheDocument();
    expect(screen.queryByText("资产图 · 关键道具")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "下一步：合成提示词" }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("aigc-script-workbench")).toHaveTextContent(
      "检测到有 2 个资产未生成",
    );
  });

  it("creates real storyboard image nodes from completed script prompts", async () => {
    const shots = SCRIPT_SHOTS.slice(0, 4);
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...emptyCanvasFixture(),
          nodes: [
            {
              id: "script-ready",
              type: "script_generate",
              position: { x: 520, y: 180 },
              data: {
                title: "诡异世界降临，我与裂口女不得不说的爱情鬼遗故事",
                scriptPrompt: "诡异世界降临，我与裂口女不得不说的爱情鬼遗故事",
                scriptMode: "script_ready",
                scriptView: "script",
                scriptWorkflowStep: "prompts",
                scriptShots: shots,
                selectedShotIds: shots.map((shot) => shot.id),
                scriptPromptStates: shots.reduce<Record<string, string>>(
                  (states, shot) => ({
                    ...states,
                    [shot.id]: "ready",
                  }),
                  {},
                ),
              },
            },
          ],
          edges: [],
        },
      ],
    });

    render(<AigcStudioPage />);

    const scriptNode = await screen.findByTestId("aigc-node-script-ready");
    fireEvent.click(scriptNode);

    const toolbar = await screen.findByTestId("aigc-script-ready-toolbar");
    fireEvent.click(
      within(toolbar).getByRole("button", { name: "批量生成分镜" }),
    );

    const dialog = await screen.findByRole("dialog", {
      name: "分镜批量生图",
    });
    expect(dialog).toHaveTextContent(
      "会优先使用已生成的角色、场景和道具参考图",
    );
    expect(dialog).toHaveTextContent("已选 4/4");

    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "确认并创建生成器组 (4)",
      }),
    );

    await waitFor(() => {
      expect(
        screen.getByTestId("aigc-node-storyboard-image-script-ready-shot-1"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByTestId("aigc-node-storyboard-image-script-ready-shot-2"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("aigc-node-storyboard-image-script-ready-shot-3"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("aigc-node-storyboard-image-script-ready-shot-4"),
    ).toBeInTheDocument();
    expect(screen.getByText("分镜图 1")).toBeInTheDocument();
    expect(screen.getByText(shots[0].prompt)).toBeInTheDocument();
    expect(
      screen.queryByTestId("aigc-storyboard-image-node"),
    ).not.toBeInTheDocument();
  });

  it("creates a storyboard video generator group and runs the batch", async () => {
    const shots = SCRIPT_SHOTS.slice(0, 8);
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...emptyCanvasFixture(),
          nodes: [
            {
              id: "script-ready",
              type: "script_generate",
              position: { x: 520, y: 180 },
              data: {
                title: "诡异世界降临，我与裂口女不得不说的爱情鬼遗故事",
                scriptPrompt: "诡异世界降临，我与裂口女不得不说的爱情鬼遗故事",
                scriptMode: "script_ready",
                scriptView: "script",
                scriptWorkflowStep: "prompts",
                scriptShots: shots,
                selectedShotIds: shots.map((shot) => shot.id),
                storyboardImageNodeId: "storyboard-images",
                storyboardImageShotIds: shots.map((shot) => shot.id),
                selectedStoryboardVideoShotIds: shots.map((shot) => shot.id),
                scriptPromptStates: shots.reduce<Record<string, string>>(
                  (states, shot) => ({
                    ...states,
                    [shot.id]: "ready",
                  }),
                  {},
                ),
              },
            },
            {
              id: "storyboard-images",
              type: "image_generate",
              position: { x: 1000, y: 180 },
              data: {
                title: "分镜图 - 诡异世界降临",
                imageMode: "storyboard_from_script",
                storyboardImageMode: "grid",
                previewKind: "storyboard_image_batch",
                sourceScriptNodeId: "script-ready",
                scriptShots: shots,
                storyboardImageShotIds: shots.map((shot) => shot.id),
                selectedStoryboardVideoShotIds: shots.map((shot) => shot.id),
                storyboardGroupStatus: "ready",
              },
            },
          ],
          edges: [
            {
              id: "edge-script-images",
              source: "script-ready",
              target: "storyboard-images",
            },
          ],
        },
      ],
    });

    render(<AigcStudioPage />);

    const scriptNode = await screen.findByTestId("aigc-node-script-ready");
    fireEvent.click(scriptNode);

    const toolbar = await screen.findByTestId("aigc-script-ready-toolbar");
    fireEvent.click(
      within(toolbar).getByRole("button", { name: "批量生视频" }),
    );

    const dialog = await screen.findByRole("dialog", { name: "批量生视频" });
    expect(dialog).toHaveTextContent(
      "会优先使用已生成的角色、场景和道具参考图",
    );
    expect(dialog).toHaveTextContent("已选 8/8");
    expect(dialog).toHaveTextContent("Seedance 2.0");
    expect(dialog).toHaveTextContent("720P");
    expect(within(dialog).getByText("镜头 1")).toBeInTheDocument();
    expect(within(dialog).getAllByText("5s").length).toBeGreaterThan(0);

    fireEvent.click(
      within(dialog).getByRole("button", {
        name: "确认并创建视频生成器组 (8)",
      }),
    );
    expect(dialog).toHaveTextContent("真人校验并创建中");

    const videoGroup = await screen.findByTestId("aigc-storyboard-video-batch");
    expect(videoGroup).toHaveTextContent("分镜视频-1");
    expect(videoGroup).toHaveTextContent("分镜视频-8");
    expect(videoGroup).not.toHaveTextContent("生成中 2%");
    expect(
      screen.getByRole("button", { name: "整组执行" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "整组执行" }));

    expect(await screen.findByText("停止 (3/8)")).toBeInTheDocument();
    expect(videoGroup).toHaveTextContent("生成中 2%");
    expect(videoGroup).toHaveTextContent("等待中");
    expect(videoGroup).toHaveTextContent("生成失败");
    expect(videoGroup).toHaveTextContent("算力不足");
  });

  it("uploads dropped local media and creates persistent asset nodes on the canvas", async () => {
    const closeToast = vi.fn();
    const loadingToast = vi
      .spyOn(antdMessage, "loading")
      .mockReturnValue(
        closeToast as unknown as ReturnType<typeof antdMessage.loading>,
      );
    const successToast = vi
      .spyOn(antdMessage, "success")
      .mockReturnValue(
        closeToast as unknown as ReturnType<typeof antdMessage.success>,
      );
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [emptyCanvasFixture()],
    });
    render(<AigcStudioPage />);

    await screen.findByText("双击画布 自由生成节点");
    const surface = screen.getByTestId("aigc-canvas-surface");
    const imageFile = new File(["image"], "product.png", {
      type: "image/png",
    });
    const videoFile = new File(["video"], "clip.mp4", {
      type: "video/mp4",
    });
    fireEvent.drop(surface, {
      dataTransfer: {
        files: [imageFile, videoFile],
      },
    });

    await waitFor(() => {
      expect(mockAigcStudioApi.uploadAsset).toHaveBeenCalledTimes(2);
    });
    expect(loadingToast).toHaveBeenCalledWith(
      expect.objectContaining({
        content: "正在上传 2 个素材...",
        duration: 0,
      }),
    );
    await waitFor(() => {
      expect(successToast).toHaveBeenCalledWith(
        expect.objectContaining({
          content: "已上传 2 个素材",
          duration: 2,
        }),
      );
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "reference_asset",
              data: expect.objectContaining({
                assetName: "product.png",
                assetPath: "aigc_studio/uploads/product.png",
              }),
            }),
            expect.objectContaining({
              type: "reference_asset",
              data: expect.objectContaining({
                assetName: "clip.mp4",
                assetPath: "aigc_studio/uploads/clip.mp4",
                assetShape: "wide",
              }),
            }),
          ]),
        }),
      );
    });
  });

  it("creates semantic downstream nodes from node-side plus handles", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    const promptNode = screen.getByTestId("aigc-node-prompt-1");
    fireEvent.click(
      within(promptNode).getByRole("button", {
        name: "从 营销提示词 创建下游节点",
      }),
    );

    const menu = screen.getByTestId("aigc-port-menu");
    expect(within(menu).getByText("图片")).toBeInTheDocument();
    expect(within(menu).getByText("视频")).toBeInTheDocument();
    expect(within(menu).getByText("引用该节点生成")).toBeInTheDocument();
    fireEvent.click(within(menu).getByRole("button", { name: "视频" }));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "video_generate",
              data: expect.objectContaining({
                text: "带有清晰品牌氛围的电影感产品片创意。",
              }),
            }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              source: "prompt-1",
              target: expect.stringContaining("video_generate"),
              sourceHandle: "right",
              targetHandle: "left",
              data: expect.objectContaining({
                role: "prompt",
              }),
            }),
          ]),
        }),
      );
    });
  });

  it("creates upstream context nodes from the left plus handle and keeps invalid choices disabled", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    const imageNode = screen.getByTestId("aigc-node-image-1");
    fireEvent.click(
      within(imageNode).getByRole("button", {
        name: "为 主视觉图片 添加上游节点",
      }),
    );

    const imageMenu = screen.getByTestId("aigc-port-menu");
    expect(within(imageMenu).getByText("添加上下文")).toBeInTheDocument();
    expect(
      within(imageMenu).getByRole("button", { name: "视频" }),
    ).toBeDisabled();
    fireEvent.click(within(imageMenu).getByRole("button", { name: "文本" }));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "prompt",
              data: expect.objectContaining({
                text: "为当前节点补充提示词、镜头、风格或角色设定。",
              }),
            }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              source: expect.stringContaining("prompt"),
              target: "image-1",
              sourceHandle: "right",
              targetHandle: "left",
            }),
          ]),
        }),
      );
    });
  });

  it("creates a non-generating reference note from the left plus handle", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    const imageNode = screen.getByTestId("aigc-node-image-1");
    fireEvent.click(
      within(imageNode).getByRole("button", {
        name: "为 主视觉图片 添加上游节点",
      }),
    );

    const menu = screen.getByTestId("aigc-port-menu");
    fireEvent.click(within(menu).getByRole("button", { name: "参考节点" }));
    expect(
      screen.getByText("双击输入参考说明（不参与生成）"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("aigc-node-composer")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "reference_note",
              data: expect.objectContaining({
                title: "参考节点",
                placeholder: "双击输入参考说明（不参与生成）",
                participatesInGeneration: false,
              }),
            }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              source: expect.stringContaining("reference_note"),
              target: "image-1",
              sourceHandle: "right",
              targetHandle: "left",
              data: expect.objectContaining({
                role: "reference_note",
              }),
            }),
          ]),
        }),
      );
    });
  });

  it("connects an uploaded image to an image node by dragging the right plus handle", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            {
              id: "asset-1",
              type: "reference_asset",
              position: { x: 80, y: 90 },
              data: {
                title: "图片节点",
                assetKind: "image",
                assetName: "portrait.png",
                assetPreviewUrl:
                  "/api/user/aigc-studio/assets/portrait.png/file",
                previewKind: "uploaded_source",
              },
            },
            {
              id: "image-1",
              type: "image_generate",
              position: { x: 520, y: 90 },
              data: {
                title: "小女孩",
                text: "小女孩",
                imageState: "generated",
              },
            },
          ],
          edges: [],
        },
      ],
    });
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    const sourceNode = screen.getByTestId("aigc-node-asset-1");
    const imageNode = screen.getByTestId("aigc-node-image-1");
    const sourceRightHandle = within(sourceNode).getByRole("button", {
      name: "从 图片节点 创建下游节点",
    });
    const originalElementFromPoint = document.elementFromPoint;
    Object.defineProperty(document, "elementFromPoint", {
      configurable: true,
      value: vi.fn(() => imageNode),
    });

    fireEvent.mouseDown(sourceRightHandle, {
      button: 0,
      clientX: 360,
      clientY: 240,
    });
    fireEvent.mouseMove(window, { clientX: 560, clientY: 240 });
    fireEvent.mouseUp(window, { clientX: 560, clientY: 240 });
    Object.defineProperty(document, "elementFromPoint", {
      configurable: true,
      value: originalElementFromPoint,
    });
    expect(
      within(screen.getByTestId("aigc-image-reference-thumb")).getByRole(
        "img",
        { name: "portrait.png" },
      ),
    ).toHaveAttribute("data-authenticated-asset", "true");
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          edges: expect.arrayContaining([
            expect.objectContaining({
              source: "asset-1",
              target: "image-1",
            }),
          ]),
          nodes: expect.arrayContaining([
            expect.objectContaining({
              id: "image-1",
              data: expect.objectContaining({
                title: "小女孩",
                text: "小女孩",
                imageMode: "image_to_image",
                referenceThumb: true,
                referenceAssetName: "portrait.png",
                referencePreviewUrl:
                  "/api/user/aigc-studio/assets/portrait.png/file",
              }),
            }),
          ]),
        }),
      );
    });
  });

  it("opens the matching port menu when a plus-handle drag ends on empty canvas", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    const imageNode = screen.getByTestId("aigc-node-image-1");
    const rightHandle = within(imageNode).getByRole("button", {
      name: "从 主视觉图片 创建下游节点",
    });
    const originalElementFromPoint = document.elementFromPoint;
    Object.defineProperty(document, "elementFromPoint", {
      configurable: true,
      value: vi.fn(() => null),
    });

    fireEvent.mouseDown(rightHandle, {
      button: 0,
      clientX: 650,
      clientY: 240,
    });
    fireEvent.mouseMove(window, { clientX: 860, clientY: 260 });
    fireEvent.mouseUp(window, { clientX: 860, clientY: 260 });
    Object.defineProperty(document, "elementFromPoint", {
      configurable: true,
      value: originalElementFromPoint,
    });

    expect(screen.getByTestId("aigc-port-menu")).toHaveTextContent(
      "引用该节点生成",
    );
  });

  it("drags nodes on the canvas and persists their new position", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    const promptNode = screen.getByTestId("aigc-node-prompt-1");
    fireEvent.mouseDown(promptNode, {
      button: 0,
      clientX: 120,
      clientY: 120,
    });
    fireEvent.mouseMove(window, { clientX: 180, clientY: 150 });
    fireEvent.mouseUp(window);
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              id: "prompt-1",
              position: { x: 140, y: 120 },
            }),
          ]),
        }),
      );
    });
  });

  it("adds LibTV-inspired node categories from the floating menu", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByLabelText("添加节点"));
    fireEvent.click(screen.getByRole("button", { name: /音频/ }));

    expect(screen.getAllByText("音频生成").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({ type: "audio_generate" }),
          ]),
        }),
      );
    });
  });

  it("edits audio text with pause, filler, voice, and tuning controls", async () => {
    mockAigcStudioApi.listCapabilities.mockResolvedValue({
      capabilities: [
        {
          provider_id: "minimax",
          provider_name: "MiniMax",
          model_id: "speech-2.8-hd",
          model_name: "Minimax-speech-2.8-hd",
          capability: "text_to_audio",
          source: "model_registry",
        },
      ],
    });
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            {
              id: "audio-1",
              type: "audio_generate",
              position: { x: 360, y: 80 },
              data: {
                title: "音频节点 2",
                text: "",
              },
            },
          ],
          edges: [],
        },
      ],
    });

    render(<AigcStudioPage />);

    await screen.findByText("音频节点 2");
    fireEvent.click(screen.getByTestId("aigc-node-audio-1"));

    const composer = screen.getByTestId("aigc-audio-composer");
    const input = within(composer).getByLabelText("音频节点输入");
    fireEvent.change(input, {
      target: { value: "虽然不曾怀疑你" },
    });
    fireEvent.click(within(composer).getByRole("button", { name: "停顿" }));
    fireEvent.click(within(composer).getByRole("button", { name: "0.25s" }));
    fireEvent.click(within(composer).getByRole("button", { name: "语气词" }));
    fireEvent.click(within(composer).getByRole("button", { name: "笑声" }));

    expect(input).toHaveValue("虽然不曾怀疑你 <#0.25#> (笑声)");
    fireEvent.click(within(composer).getByRole("button", { name: "选择音色" }));
    const voicePanel = screen.getByTestId("aigc-audio-voice-panel");
    expect(voicePanel).toHaveTextContent("音色选择");
    fireEvent.click(
      within(voicePanel).getByRole("button", { name: "选择 御姐音色" }),
    );

    fireEvent.click(
      within(composer).getByRole("button", { name: "音频参数调节" }),
    );
    const tuningPanel = screen.getByTestId("aigc-audio-tuning-panel");
    expect(tuningPanel).toHaveTextContent("基础调节");
    fireEvent.change(within(tuningPanel).getByLabelText("语速"), {
      target: { value: "1.12" },
    });
    fireEvent.click(
      within(tuningPanel).getByRole("button", { name: "电话失真" }),
    );

    fireEvent.click(
      within(composer).getByRole("button", { name: "提交音频节点输入" }),
    );
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "保存" })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              id: "audio-1",
              data: expect.objectContaining({
                audioFillerTag: "(笑声)",
                audioPauseTag: "<#0.25#>",
                audioVoiceId: "mature",
                audioVoiceName: "御姐音色",
                modelId: "speech-2.8-hd",
                modelLabel: "Minimax-speech-2.8-hd",
                providerId: "minimax",
                soundEffect: "电话失真",
                speechRate: 1.12,
                text: "虽然不曾怀疑你 <#0.25#> (笑声)",
              }),
            }),
          ]),
        }),
      );
    });
  }, 10000);

  it("creates a LibTV-style default text node with its own model composer", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "提示词/文本" }));

    const editor = screen.getByTestId("aigc-text-editor");
    expect(editor).toHaveTextContent("自己编写内容");
    expect(editor).toHaveTextContent("文生视频");
    expect(editor).toHaveTextContent("图片反推提示词");
    expect(editor).toHaveTextContent("文字生音乐");
    expect(screen.queryByTestId("aigc-text-toolbar")).not.toBeInTheDocument();
    const composer = screen.getByTestId("aigc-text-composer");
    expect(within(composer).getByLabelText("文本节点输入")).toHaveAttribute(
      "placeholder",
      expect.stringContaining("写下你想讲的故事"),
    );
    expect(
      within(composer).getByRole("button", { name: /未选择文本模型/ }),
    ).toBeInTheDocument();
    expect(
      within(composer).queryByRole("button", { name: /GPT Image 2/ }),
    ).not.toBeInTheDocument();
  });

  it("runs text composer input through submitJob and renders generated text", async () => {
    let finishJob: (value: unknown) => void = () => undefined;
    mockAigcStudioApi.listCapabilities.mockResolvedValueOnce({
      capabilities: [
        textCapability(),
        {
          provider_id: "openai",
          provider_name: "OpenAI",
          model_id: "gpt-image-2",
          model_name: "GPT Image 2",
          capability: "text_to_image",
          source: "model_registry",
        },
      ],
    });
    mockAigcStudioApi.runJob.mockReturnValueOnce(
      new Promise((resolve) => {
        finishJob = resolve;
      }),
    );
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "提示词/文本" }));

    const composer = screen.getByTestId("aigc-text-composer");
    fireEvent.change(within(composer).getByLabelText("文本节点输入"), {
      target: { value: "城市屋顶的机器人短片设定" },
    });
    fireEvent.click(
      within(composer).getByRole("button", {
        name: "提交文本节点输入",
      }),
    );

    await waitFor(() => {
      expect(screen.getByTestId("aigc-text-editor")).toHaveAttribute(
        "data-text-state",
        "generating",
      );
    });
    await waitFor(() => {
      expect(mockAigcStudioApi.submitJob).toHaveBeenCalledWith(
        expect.objectContaining({
          capability: "storyboard",
          provider_id: "text-provider",
          model_id: "gvlm-3-1",
          inputs: expect.objectContaining({
            prompt: "城市屋顶的机器人短片设定",
            node_type: "prompt",
          }),
        }),
      );
    });
    const submitBody = mockAigcStudioApi.submitJob.mock.calls[0]![0];
    finishJob({
      ...jobFixture(),
      id: "job-text",
      canvas_id: submitBody.canvas_id,
      node_id: submitBody.node_id,
      capability: "storyboard",
      provider_id: "text-provider",
      model_id: "gvlm-3-1",
      status: "succeeded",
      outputs: [
        {
          id: "text-asset-1",
          kind: "file",
          name: "prompt-1.txt",
          path: "aigc_studio/canvas-1/job-text/prompt-1.txt",
          url: "/api/user/aigc-studio/assets/text-asset-1/file",
          mime_type: "text/plain",
          created_at: "2026-05-30T00:00:00Z",
          meta: { text: "生成后的城市屋顶机器人短片设定" },
        },
      ],
    });

    await waitFor(() => {
      expect(screen.getByTestId("aigc-text-editor")).toHaveAttribute(
        "data-text-state",
        "generated",
      );
    });
    expect(screen.getByTestId("aigc-text-editor")).toHaveTextContent(
      "生成后的城市屋顶机器人短片设定",
    );
    expect(
      screen.getByTestId("aigc-text-editor").closest("[data-aigc-node-id]"),
    ).not.toHaveTextContent("/api/user/aigc-studio/assets/text-asset-1/file");
  });

  it("shows a text node error and skips submit when no text model is available", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "提示词/文本" }));

    const composer = screen.getByTestId("aigc-text-composer");
    fireEvent.change(within(composer).getByLabelText("文本节点输入"), {
      target: { value: "请写一段品牌故事" },
    });
    fireEvent.click(
      within(composer).getByRole("button", {
        name: "提交文本节点输入",
      }),
    );

    expect(
      await screen.findByText(
        "当前文本节点没有可用模型，请先选择模型后再生成。",
      ),
    ).toBeInTheDocument();
    expect(screen.getByTestId("aigc-text-editor")).toHaveAttribute(
      "data-text-state",
      "failed",
    );
    expect(mockAigcStudioApi.submitJob).not.toHaveBeenCalled();
  });

  it("lets generated text enter inline edit mode while keeping its composer", async () => {
    mockAigcStudioApi.listCapabilities.mockResolvedValueOnce({
      capabilities: [textCapability()],
    });
    mockAigcStudioApi.runJob.mockImplementationOnce(async () => {
      const calls = mockAigcStudioApi.submitJob.mock.calls;
      const submitBody = calls[calls.length - 1]![0];
      return {
        ...jobFixture(),
        id: "job-text",
        canvas_id: submitBody.canvas_id,
        node_id: submitBody.node_id,
        capability: "storyboard",
        provider_id: "text-provider",
        model_id: "gvlm-3-1",
        status: "succeeded",
        outputs: [
          {
            id: "text-asset-1",
            kind: "file",
            name: "prompt-1.txt",
            path: "aigc_studio/canvas-1/job-text/prompt-1.txt",
            url: "/api/user/aigc-studio/assets/text-asset-1/file",
            mime_type: "text/plain",
            created_at: "2026-05-30T00:00:00Z",
            meta: { text: "写一个悬疑短片故事" },
          },
        ],
      };
    });
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "提示词/文本" }));

    const composer = screen.getByTestId("aigc-text-composer");
    fireEvent.change(within(composer).getByLabelText("文本节点输入"), {
      target: { value: "写一个悬疑短片故事" },
    });
    fireEvent.click(
      within(composer).getByRole("button", {
        name: "提交文本节点输入",
      }),
    );

    await waitFor(() => {
      expect(screen.getByTestId("aigc-text-editor")).toHaveAttribute(
        "data-text-state",
        "generated",
      );
    });
    fireEvent.click(screen.getByTestId("aigc-text-generated-preview"));

    expect(screen.getByTestId("aigc-text-editor")).toHaveAttribute(
      "data-text-state",
      "generated-editing",
    );
    expect(screen.getByTestId("aigc-text-toolbar")).toBeInTheDocument();
    expect(screen.getByLabelText("文本内容")).toHaveValue("写一个悬疑短片故事");
    expect(screen.getByTestId("aigc-text-composer")).toHaveAttribute(
      "data-text-flow",
      "generated",
    );

    fireEvent.change(screen.getByLabelText("文本内容"), {
      target: { value: "写一个悬疑短片故事，加入雨夜咖啡馆。" },
    });

    expect(screen.getByLabelText("文本内容")).toHaveValue(
      "写一个悬疑短片故事，加入雨夜咖啡馆。",
    );
  });

  it("turns write-your-own-content into an editable text node without a composer", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "提示词/文本" }));
    fireEvent.click(screen.getByRole("button", { name: "自己编写内容" }));

    const textarea = screen.getByLabelText("文本内容");
    fireEvent.change(textarea, {
      target: { value: "第一场：城市屋顶，机器人看见星星。" },
    });
    fireEvent.click(screen.getByRole("button", { name: "一级标题" }));
    fireEvent.click(screen.getByRole("button", { name: "加粗" }));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "prompt",
              data: expect.objectContaining({
                text: "第一场：城市屋顶，机器人看见星星。",
                textMode: "write",
                blockStyle: "h1",
                bold: true,
              }),
            }),
          ]),
        }),
      );
    });
    expect(screen.getByTestId("aigc-text-toolbar")).toHaveTextContent("H1");
    expect(screen.queryByTestId("aigc-text-composer")).not.toBeInTheDocument();
  }, 10000);

  it("duplicates and expands editable text nodes from the toolbar", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "提示词/文本" }));
    fireEvent.click(screen.getByRole("button", { name: "自己编写内容" }));
    fireEvent.change(screen.getByLabelText("文本内容"), {
      target: { value: "可复制的文本节点" },
    });

    fireEvent.click(screen.getByRole("button", { name: "展开节点" }));
    fireEvent.click(screen.getByRole("button", { name: "复制节点" }));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalled();
    });
    const calls = mockAigcStudioApi.saveCanvas.mock.calls;
    const savedPayload = calls[calls.length - 1]?.[1] ?? { nodes: [] };
    const copiedNodes = savedPayload.nodes.filter(
      (node: { type: string; data: { text?: string } }) =>
        node.type === "prompt" && node.data.text === "可复制的文本节点",
    );
    expect(copiedNodes).toHaveLength(2);
    expect(copiedNodes[0].data.expanded).toBe(true);
    expect(copiedNodes[1].data.expanded).toBe(true);
  }, 10000);

  it("inserts text dividers and clears formatting from the toolbar", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "提示词/文本" }));
    fireEvent.click(screen.getByRole("button", { name: "自己编写内容" }));
    fireEvent.change(screen.getByLabelText("文本内容"), {
      target: { value: "段落内容" },
    });
    fireEvent.click(screen.getByRole("button", { name: "三级标题" }));
    fireEvent.click(screen.getByRole("button", { name: "插入分割线" }));
    fireEvent.click(screen.getByRole("button", { name: "清除格式" }));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "prompt",
              data: expect.objectContaining({
                text: "段落内容\n---\n",
                blockStyle: "paragraph",
                bold: false,
                italic: false,
              }),
            }),
          ]),
        }),
      );
    });
    expect(
      (screen.getByLabelText("文本内容") as HTMLTextAreaElement).value,
    ).toBe("段落内容\n---\n");
  }, 10000);

  it("keeps the selected text model configurable from the text composer", async () => {
    mockAigcStudioApi.listCapabilities.mockResolvedValueOnce({
      capabilities: [
        ...Array.from({ length: 7 }, (_, index) => ({
          provider_id: "text-provider",
          provider_name: "Text Provider",
          model_id: `gvlm-${index + 1}`,
          model_name: `GVLM ${index + 1}`,
          capability: "storyboard",
          source: "model_registry" as const,
        })),
        {
          provider_id: "openai",
          provider_name: "OpenAI",
          model_id: "gpt-image-2",
          model_name: "GPT Image 2",
          capability: "text_to_image",
          source: "model_registry",
        },
      ],
    });
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "提示词/文本" }));
    const composer = screen.getByTestId("aigc-text-composer");
    fireEvent.click(within(composer).getByRole("button", { name: /GVLM 1/ }));
    expect(
      within(screen.getByTestId("aigc-text-model-menu")).getByRole("button", {
        name: /GVLM 7/,
      }),
    ).toBeInTheDocument();
    fireEvent.click(
      within(screen.getByTestId("aigc-text-model-menu")).getByRole("button", {
        name: /GVLM 7/,
      }),
    );

    expect(
      within(screen.getByTestId("aigc-text-composer")).getByRole("button", {
        name: /GVLM 7/,
      }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("aigc-text-composer")).queryByRole("button", {
        name: /GPT Image 2/,
      }),
    ).not.toBeInTheDocument();
  });

  it("turns a text node try action into a text-to-video connected group", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "提示词/文本" }));
    fireEvent.click(screen.getByRole("button", { name: "文生视频" }));

    expect(screen.getAllByText(/高级广告镜头/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("视频").length).toBeGreaterThan(0);

    await clickToolbarSave();

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "prompt",
              data: expect.objectContaining({
                textMode: "text_to_video",
              }),
            }),
            expect.objectContaining({ type: "video_generate" }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              sourceHandle: "right",
              targetHandle: "left",
            }),
          ]),
        }),
      );
    });
  }, 10000);

  it("auto-runs text try actions as video and music jobs", async () => {
    mockAigcStudioApi.listCapabilities.mockResolvedValueOnce({
      capabilities: [
        {
          provider_id: "media-provider",
          provider_name: "Media Provider",
          model_id: "video-model",
          model_name: "Video Model",
          capability: "text_to_video",
          source: "model_registry",
        },
        {
          provider_id: "media-provider",
          provider_name: "Media Provider",
          model_id: "music-model",
          model_name: "Music Model",
          capability: "text_to_audio",
          source: "model_registry",
        },
      ],
    });
    mockAigcStudioApi.runJob.mockImplementation(async () => {
      const calls = mockAigcStudioApi.submitJob.mock.calls;
      const body = calls[calls.length - 1]![0];
      const isAudio = body.capability === "text_to_audio";
      return {
        ...jobFixture(),
        id: `job-${body.node_id}`,
        canvas_id: body.canvas_id,
        node_id: body.node_id,
        capability: body.capability,
        provider_id: body.provider_id,
        model_id: body.model_id,
        status: "succeeded",
        outputs: [
          {
            id: `asset-${body.node_id}`,
            kind: isAudio ? "audio" : "video",
            name: isAudio ? "music.json" : "video.json",
            path: `aigc_studio/canvas-1/${body.node_id}/asset.json`,
            url: `/api/user/aigc-studio/assets/asset-${body.node_id}/file`,
            mime_type: "application/json",
            created_at: "2026-05-30T00:00:00Z",
          },
        ],
      };
    });

    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "提示词/文本" }));
    fireEvent.click(screen.getByRole("button", { name: "文生视频" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.submitJob).toHaveBeenCalledWith(
        expect.objectContaining({
          capability: "text_to_video",
          provider_id: "media-provider",
          model_id: "video-model",
          inputs: expect.objectContaining({
            prompt: expect.stringContaining("高级广告镜头"),
            node_type: "video_generate",
          }),
        }),
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "提示词/文本" }));
    fireEvent.click(screen.getByRole("button", { name: "文字生音乐" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.submitJob).toHaveBeenCalledWith(
        expect.objectContaining({
          capability: "text_to_audio",
          provider_id: "media-provider",
          model_id: "music-model",
          inputs: expect.objectContaining({
            prompt: expect.stringContaining("现代品牌电子音乐"),
            node_type: "audio_generate",
          }),
        }),
      );
    });
  }, 10000);

  it.each([
    {
      variant: "story",
      title: "脚本生成器",
      nodeTypes: ["prompt", "script_generate"],
      edgeCount: 1,
    },
    {
      variant: "character",
      title: "角色三视图",
      nodeTypes: ["reference_asset", "image_generate"],
      edgeCount: 1,
    },
    {
      variant: "keyframe",
      title: "视频",
      nodeTypes: ["reference_asset", "video_generate"],
      edgeCount: 1,
    },
    {
      variant: "audioVideo",
      title: "视频",
      nodeTypes: ["audio_generate", "reference_asset", "video_generate"],
      edgeCount: 2,
    },
  ])(
    "creates the $variant template as a connected node group",
    async ({ variant, title, nodeTypes, edgeCount }) => {
      mockAigcStudioApi.listCanvases.mockResolvedValue({
        canvases: [emptyCanvasFixture()],
      });
      render(<AigcStudioPage />);

      fireEvent.click(await screen.findByTestId(`aigc-template-${variant}`));
      expect(screen.getByText(title)).toBeInTheDocument();

      const selectedComposer =
        screen.queryByTestId("aigc-node-composer") ??
        screen.queryByTestId("aigc-video-composer") ??
        screen.queryByTestId("aigc-script-composer") ??
        screen.getByTestId("aigc-image-composer");
      const selectedNode = selectedComposer.parentElement?.closest(
        "[data-testid^='aigc-node-']",
      );
      expect(selectedNode).not.toBeNull();
      const selectedNodeQueries = within(selectedNode as HTMLElement);
      expect(
        selectedNodeQueries.getByRole("button", { name: /添加上游节点/ }),
      ).toBeInTheDocument();
      expect(
        selectedNodeQueries.getByRole("button", { name: /创建下游节点/ }),
      ).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: "保存" }));

      await waitFor(() => {
        expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
          "canvas-1",
          expect.objectContaining({
            nodes: expect.arrayContaining(
              nodeTypes.map((type) => expect.objectContaining({ type })),
            ),
            edges: expect.arrayContaining(
              Array.from({ length: edgeCount }, () =>
                expect.objectContaining({
                  sourceHandle: "right",
                  targetHandle: "left",
                }),
              ),
            ),
          }),
        );
      });
      const calls = mockAigcStudioApi.saveCanvas.mock.calls;
      const savedPayload = calls[calls.length - 1]?.[1] ?? {};
      expect(savedPayload.edges).toHaveLength(edgeCount);
    },
  );

  it("opens a node context menu and deletes the node with connected edges", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          edges: [{ id: "edge-1", source: "prompt-1", target: "image-1" }],
        },
      ],
    });
    render(<AigcStudioPage />);

    const imageNode = await screen.findByTestId("aigc-node-image-1");
    fireEvent.contextMenu(imageNode, { clientX: 480, clientY: 220 });

    const menu = screen.getByRole("menu");
    expect(within(menu).getByText("删除")).toBeInTheDocument();
    fireEvent.click(within(menu).getByText("删除"));

    expect(screen.queryByTestId("aigc-node-image-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("aigc-node-composer")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: [expect.objectContaining({ id: "prompt-1" })],
          edges: [],
        }),
      );
    });
  });

  it("saves node assets and creates subjects from the context menu", async () => {
    render(<AigcStudioPage />);

    const imageNode = await screen.findByTestId("aigc-node-image-1");
    fireEvent.contextMenu(imageNode, { clientX: 480, clientY: 220 });
    fireEvent.click(screen.getByRole("menuitem", { name: /保存到我的素材/ }));

    expect(screen.getByText("我的资产")).toBeInTheDocument();
    expect(screen.getAllByText("素材").length).toBeGreaterThan(0);
    expect(screen.getAllByText("主视觉图片").length).toBeGreaterThan(0);

    fireEvent.contextMenu(imageNode, { clientX: 480, clientY: 220 });
    fireEvent.click(screen.getByRole("menuitem", { name: /创建主体/ }));

    expect(screen.getByText("主体库")).toBeInTheDocument();
    expect(screen.getByText("主体")).toBeInTheDocument();
  });

  it("restores saved asset records after switching away from and back to a project", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        canvasFixture(),
        {
          ...emptyCanvasFixture(),
          id: "canvas-2",
          name: "第二项目",
        },
      ],
    });
    render(<AigcStudioPage />);

    const imageNode = await screen.findByTestId("aigc-node-image-1");
    fireEvent.contextMenu(imageNode, { clientX: 480, clientY: 220 });
    fireEvent.click(screen.getByRole("menuitem", { name: /保存到我的素材/ }));

    expect(screen.getAllByText("主视觉图片").length).toBeGreaterThan(1);

    fireEvent.click(screen.getByRole("button", { name: /第二项目/ }));
    await waitFor(() => {
      expect(screen.getByDisplayValue("第二项目")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /未命名 AIGC 画布/ }));
    await waitFor(() => {
      expect(screen.getByDisplayValue("未命名 AIGC 画布")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByLabelText("打开我的资产"));

    expect(screen.getByText("我的资产")).toBeInTheDocument();
    expect(screen.getAllByText("主视觉图片").length).toBeGreaterThan(1);
  });

  it("copies, pastes and duplicates nodes from the context menu", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          edges: [{ id: "edge-1", source: "prompt-1", target: "image-1" }],
        },
      ],
    });
    render(<AigcStudioPage />);

    const imageNode = await screen.findByTestId("aigc-node-image-1");
    fireEvent.contextMenu(imageNode, { clientX: 480, clientY: 220 });
    fireEvent.click(screen.getByRole("menuitem", { name: /复制节点/ }));
    fireEvent.contextMenu(imageNode, { clientX: 480, clientY: 220 });
    fireEvent.click(screen.getByRole("menuitem", { name: /^粘贴/ }));
    fireEvent.contextMenu(imageNode, { clientX: 480, clientY: 220 });
    fireEvent.click(screen.getByRole("menuitem", { name: /创建副本/ }));

    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              id: expect.stringContaining("paste"),
              type: "image_generate",
            }),
            expect.objectContaining({
              id: expect.stringContaining("copy"),
              type: "image_generate",
            }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              target: expect.stringContaining("copy"),
              source: "prompt-1",
            }),
          ]),
        }),
      );
    });
  });

  it("opens the toolbox panel and sends a workflow template to the canvas", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [emptyCanvasFixture()],
    });
    render(<AigcStudioPage />);

    fireEvent.click(
      await screen.findByRole("button", { name: "打开我的工具箱" }),
    );
    expect(screen.getByText("我的工具箱")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /故事脚本生成/ })[0]);
    expect(screen.getByText("脚本生成器")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({ type: "script_generate" }),
          ]),
        }),
      );
    });
  });

  it("opens the minimap and updates the zoom label", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    expect(screen.getByText("100%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "画布小地图" }));
    expect(screen.getByTestId("aigc-minimap")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "放大" }));
    expect(screen.getByText("110%")).toBeInTheDocument();
  });

  it("keeps persistent canvas controls in a viewport overlay outside the pannable surface", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    const surface = screen.getByTestId("aigc-canvas-surface");
    const chrome = screen.getByTestId("aigc-canvas-chrome");
    const dock = screen.getByTestId("aigc-minimap-dock");
    const rail = screen.getByRole("button", { name: "添加节点" }).parentElement;
    const style = window.getComputedStyle(dock);

    expect(surface).not.toContainElement(chrome);
    expect(dock.parentElement).toBe(chrome);
    expect(rail?.parentElement).toBe(chrome);
    expect(style.position).toBe("absolute");
    expect(style.left).toBe("50%");
    expect(style.transform).toContain("translateX(-50%)");
    expect(style.right).not.toBe("28px");
  });

  it("pans the viewport by dragging blank canvas without moving nodes", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    const surface = screen.getByTestId("aigc-canvas-surface");
    const promptNode = screen.getByTestId("aigc-node-prompt-1");

    fireEvent.mouseDown(surface, {
      button: 0,
      clientX: 500,
      clientY: 320,
    });
    fireEvent.mouseMove(window, { clientX: 560, clientY: 350 });
    fireEvent.mouseUp(window);
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          viewport: expect.objectContaining({ x: 60, y: 30, zoom: 1 }),
          nodes: expect.arrayContaining([
            expect.objectContaining({
              id: "prompt-1",
              position: { x: 80, y: 90 },
            }),
          ]),
        }),
      );
    });
    expect(promptNode).toBeInTheDocument();
  });

  it("pans the viewport with wheel gestures while preserving zoom", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    fireEvent.wheel(screen.getByTestId("aigc-canvas-surface"), {
      deltaX: 24,
      deltaY: 32,
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          viewport: expect.objectContaining({ x: -24, y: -32, zoom: 1 }),
        }),
      );
    });
  });

  it("fits all nodes and centers the selected node from viewport controls", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    fireEvent.click(screen.getByRole("button", { name: "适配全部" }));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalled();
    });
    let calls = mockAigcStudioApi.saveCanvas.mock.calls;
    let savedPayload = calls[calls.length - 1]?.[1] ?? {
      viewport: { x: 0, y: 0, zoom: 1 },
    };
    expect(savedPayload.viewport).not.toEqual({ x: 0, y: 0, zoom: 1 });

    fireEvent.click(screen.getByRole("button", { name: "回到选中" }));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      calls = mockAigcStudioApi.saveCanvas.mock.calls;
      savedPayload = calls[calls.length - 1]?.[1] ?? {
        viewport: { x: 0, y: 0, zoom: 1 },
      };
      expect(savedPayload.viewport).not.toEqual({ x: 0, y: 0, zoom: 1 });
    });
  }, 10000);

  it("centers the clicked minimap node and persists the changed viewport", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    fireEvent.click(screen.getByRole("button", { name: "画布小地图" }));

    const minimap = screen.getByTestId("aigc-minimap");
    const minimapNodes = minimap.querySelectorAll(
      "button, [role='button'], span",
    );
    expect(minimapNodes.length).toBeGreaterThanOrEqual(2);

    fireEvent.click(minimapNodes[1]);
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalled();
    });
    const calls = mockAigcStudioApi.saveCanvas.mock.calls;
    const savedPayload = calls[calls.length - 1]?.[1] ?? {
      viewport: { x: 0, y: 0 },
    };
    expect(savedPayload.viewport.x).not.toBe(0);
    expect(savedPayload.viewport.y).not.toBe(0);
  });

  it("supports keyboard copy, paste, delete and undo on canvas nodes", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    expect(screen.getByTestId("aigc-node-image-1")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Backspace" });
    expect(screen.queryByTestId("aigc-node-image-1")).not.toBeInTheDocument();

    fireEvent.keyDown(window, { key: "z", metaKey: true });
    expect(screen.getByTestId("aigc-node-image-1")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "c", metaKey: true });
    fireEvent.keyDown(window, { key: "v", metaKey: true });

    expect(screen.getByText("主视觉图片 副本")).toBeInTheDocument();
  });

  it("shows a node-local prompt composer and parameter bar for selected generation nodes", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");

    const selectedNode = screen.getByTestId("aigc-node-image-1");
    const composer = screen.getByTestId("aigc-image-composer");
    expect(screen.getByTestId("aigc-image-editor")).toHaveAttribute(
      "data-image-state",
      "editing",
    );
    expect(composer).toHaveAttribute("data-image-flow", "editing");
    expect(selectedNode).toContainElement(composer);
    expect(within(composer).getByLabelText("图片节点输入")).toHaveAttribute(
      "placeholder",
      "描述你想要生成的画面内容，按呼出指令，@引用素材",
    );
    expect(screen.getByText("风格")).toBeInTheDocument();
    expect(screen.getByText("聚焦")).toBeInTheDocument();
    expect(screen.getByText("16:9 · 标准画质 · 2K")).toBeInTheDocument();
  });

  it("keeps the long-image export node out of model-backed generation controls", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [longImageCanvasFixture()],
    });

    render(<AigcStudioPage />);

    const longImageNode = await screen.findByTestId("aigc-node-long-1");
    fireEvent.click(longImageNode);

    expect(screen.queryByTestId("aigc-node-composer")).not.toBeInTheDocument();
    expect(screen.queryByText("模型")).not.toBeInTheDocument();
    expect(screen.queryByText("分镜")).not.toBeInTheDocument();
    expect(screen.getAllByText("本地排版导出").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "运行节点" })).toBeDisabled();
  });

  it("clears individual image tool summary chips from the composer", async () => {
    const canvas = canvasFixture();
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvas,
          nodes: canvas.nodes.map((node) =>
            node.id === "image-1"
              ? {
                  ...node,
                  data: {
                    ...node.data,
                    imageState: "editing",
                    stylePreset: "电影感",
                    markPreset: "主体区域",
                    focusPreset: "主体清晰",
                  },
                }
              : node,
          ),
        },
      ],
    });
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");

    const summary = screen.getByTestId("aigc-image-tool-summary");
    expect(summary).toHaveTextContent("电影感");
    expect(summary).toHaveTextContent("主体区域");
    expect(summary).toHaveTextContent("主体清晰");

    fireEvent.click(within(summary).getByRole("button", { name: "清除标记" }));

    expect(summary).toHaveTextContent("电影感");
    expect(summary).not.toHaveTextContent("主体区域");
    expect(summary).toHaveTextContent("主体清晰");

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              id: "image-1",
              data: expect.objectContaining({
                stylePreset: "电影感",
                markPreset: null,
                focusPreset: "主体清晰",
              }),
            }),
          ]),
        }),
      );
    });
  });

  it("keeps image panorama, quality, and ratio parameters in the composer", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "图片生成/编辑" }));

    const composer = screen.getByTestId("aigc-image-composer");
    const panoramaButton = within(composer).getByRole("button", {
      name: "720全景",
    });
    expect(panoramaButton).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(panoramaButton);

    expect(panoramaButton).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(
      within(composer).getByRole("button", {
        name: /2:1 · 标准画质 · 2K/,
      }),
    );
    const sizeMenu = screen.getByTestId("aigc-image-size-menu");
    expect(sizeMenu).toHaveAttribute("data-image-size-mode", "panorama");
    expect(
      within(sizeMenu).getByRole("button", { name: "1:1" }),
    ).toBeDisabled();
    expect(
      within(sizeMenu).getByRole("button", { name: "2:1" }),
    ).not.toBeDisabled();

    fireEvent.click(within(sizeMenu).getByRole("button", { name: "高画质" }));

    expect(
      within(composer).getByRole("button", {
        name: /2:1 · 高画质 · 2K/,
      }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "image_generate",
              data: expect.objectContaining({
                imageMode: "panorama",
                panoramaMode: true,
                aspectRatio: "2:1",
                imageQuality: "高画质",
                resolution: "2K",
              }),
            }),
          ]),
        }),
      );
    });
  });

  it("supports LibTV-style image node try actions and image composer menus", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "图片生成/编辑" }));

    const imageEditor = screen.getByTestId("aigc-image-editor");
    expect(imageEditor).toHaveAttribute("data-image-state", "empty");
    expect(imageEditor).toHaveTextContent("图生图");
    expect(imageEditor).toHaveTextContent("图片高清");
    fireEvent.change(
      within(screen.getByTestId("aigc-image-editor")).getByLabelText(
        "上传图生图参考图",
      ),
      {
        target: {
          files: [new File(["image"], "reference.png", { type: "image/png" })],
        },
      },
    );
    await waitFor(() => {
      expect(mockAigcStudioApi.uploadAsset).toHaveBeenCalledWith(
        expect.objectContaining({ name: "reference.png" }),
      );
    });
    await screen.findByText("图生图");

    const composer = screen.getByTestId("aigc-image-composer");
    expect(screen.queryByText("输入已更新")).not.toBeInTheDocument();
    expect(
      await screen.findByTestId("aigc-image-reference-thumb"),
    ).toBeInTheDocument();
    fireEvent.change(within(composer).getByLabelText("图片节点输入"), {
      target: { value: "冬日雪景中的品牌模特，电影感光影" },
    });
    fireEvent.click(within(composer).getByRole("button", { name: "风格" }));
    const styleDialog = screen.getByRole("dialog", { name: "风格广场" });
    expect(
      await within(styleDialog).findByText("审美 DNA · 2"),
    ).toBeInTheDocument();
    fireEvent.click(
      await within(styleDialog).findByRole("button", {
        name: "电影感",
      }),
    );
    expect(
      screen.queryByRole("dialog", { name: "风格广场" }),
    ).not.toBeInTheDocument();
    fireEvent.click(within(composer).getByRole("button", { name: "标记" }));
    fireEvent.click(
      within(screen.getByTestId("aigc-image-mark-panel")).getByRole("button", {
        name: "主体区域",
      }),
    );
    fireEvent.click(within(composer).getByRole("button", { name: "聚焦" }));
    fireEvent.click(
      within(screen.getByTestId("aigc-image-focus-panel")).getByRole("button", {
        name: "主体清晰",
      }),
    );
    const imageToolSummary = screen.getByTestId("aigc-image-tool-summary");
    expect(imageToolSummary).toHaveTextContent("风格");
    expect(imageToolSummary).toHaveTextContent("电影感");
    expect(imageToolSummary).toHaveTextContent("标记");
    expect(imageToolSummary).toHaveTextContent("主体区域");
    expect(imageToolSummary).toHaveTextContent("聚焦");
    expect(imageToolSummary).toHaveTextContent("主体清晰");
    fireEvent.click(
      within(composer).getByRole("button", { name: /GPT Image 2/ }),
    );
    fireEvent.click(
      within(screen.getByTestId("aigc-image-model-menu")).getByRole("button", {
        name: /Qwen Image/,
      }),
    );
    fireEvent.click(within(composer).getByRole("button", { name: /16:9/ }));
    fireEvent.click(
      within(screen.getByTestId("aigc-image-size-menu")).getByText("4K"),
    );
    expect(screen.getByTestId("aigc-image-size-menu")).toBeInTheDocument();
    fireEvent.click(
      within(screen.getByTestId("aigc-image-size-menu")).getByText("1:1"),
    );
    expect(screen.getByTestId("aigc-image-size-menu")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("aigc-canvas-surface"));
    expect(
      screen.queryByTestId("aigc-image-size-menu"),
    ).not.toBeInTheDocument();
    fireEvent.click(within(composer).getByRole("button", { name: "高级设置" }));
    fireEvent.click(
      within(screen.getByTestId("aigc-image-advanced-menu")).getByLabelText(
        "联网搜索",
      ),
    );
    fireEvent.click(within(composer).getByRole("button", { name: "镜头" }));
    fireEvent.click(
      within(screen.getByTestId("aigc-image-camera-menu")).getByRole("button", {
        name: "使用",
      }),
    );
    expect(within(composer).getByText("35 mm · f/4")).toBeInTheDocument();
    fireEvent.click(within(composer).getByRole("button", { name: /1张/ }));
    fireEvent.click(
      within(screen.getByTestId("aigc-image-count-menu")).getByText("4张"),
    );
    fireEvent.click(
      within(composer).getByRole("button", { name: "提交图片节点输入" }),
    );
    await waitFor(() => {
      expect(mockAigcStudioApi.submitJob).toHaveBeenCalledWith(
        expect.objectContaining({
          inputs: expect.objectContaining({
            prompt: "冬日雪景中的品牌模特，电影感光影",
            node_type: "image_generate",
          }),
          parameters: expect.objectContaining({
            aspectRatio: "1:1",
            resolution: "4K",
            imageCount: 4,
          }),
        }),
      );
    });
    await waitFor(() => {
      expect(screen.getByTestId("aigc-image-editor")).toHaveAttribute(
        "data-image-state",
        "generated",
      );
    });
    expect(composer).toHaveAttribute("data-image-flow", "generated");

    fireEvent.click(
      within(screen.getByTestId("aigc-image-composer")).getByRole("button", {
        name: "提交图片节点输入",
      }),
    );
    await waitFor(() => {
      expect(mockAigcStudioApi.submitJob).toHaveBeenCalledTimes(2);
    });
    expect(mockAigcStudioApi.submitJob.mock.calls[1]?.[0]).toEqual(
      expect.objectContaining({
        parameters: expect.objectContaining({ imageCount: 4 }),
      }),
    );
    await waitFor(() => {
      expect(screen.getByTestId("aigc-image-editor")).toHaveAttribute(
        "data-image-state",
        "generated",
      );
    });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "reference_asset",
              data: expect.objectContaining({
                previewKind: "uploaded_source",
                assetName: "reference.png",
              }),
            }),
            expect.objectContaining({
              type: "image_generate",
              data: expect.objectContaining({
                title: "图生图",
                imageMode: "image_to_image",
                referenceThumb: true,
                referenceAssetName: "reference.png",
                text: "冬日雪景中的品牌模特，电影感光影",
                lastRunPrompt: "冬日雪景中的品牌模特，电影感光影",
                imageState: "generated",
                modelLabel: "Qwen Image",
                aspectRatio: "1:1",
                resolution: "4K",
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
              }),
            }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              sourceHandle: "right",
              targetHandle: "left",
            }),
          ]),
        }),
      );
    });
  }, 10000);

  it("submits image node parameters and reference inputs to the job API", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "图片生成/编辑" }));
    fireEvent.change(
      within(screen.getByTestId("aigc-image-editor")).getByLabelText(
        "上传图生图参考图",
      ),
      {
        target: {
          files: [new File(["image"], "reference.png", { type: "image/png" })],
        },
      },
    );
    await waitFor(() => {
      expect(mockAigcStudioApi.uploadAsset).toHaveBeenCalledWith(
        expect.objectContaining({ name: "reference.png" }),
      );
    });
    await screen.findByText("图生图");

    const composer = screen.getByTestId("aigc-image-composer");
    fireEvent.change(within(composer).getByLabelText("图片节点输入"), {
      target: { value: "冬日雪景中的品牌模特，电影感光影" },
    });
    fireEvent.click(within(composer).getByRole("button", { name: "风格" }));
    const styleDialog = screen.getByRole("dialog", { name: "风格广场" });
    fireEvent.click(
      await within(styleDialog).findByRole("button", {
        name: "电影感",
      }),
    );
    fireEvent.click(within(composer).getByRole("button", { name: "标记" }));
    fireEvent.click(
      within(screen.getByTestId("aigc-image-mark-panel")).getByRole("button", {
        name: "主体区域",
      }),
    );
    fireEvent.click(within(composer).getByRole("button", { name: "聚焦" }));
    fireEvent.click(
      within(screen.getByTestId("aigc-image-focus-panel")).getByRole("button", {
        name: "主体清晰",
      }),
    );
    fireEvent.click(within(composer).getByRole("button", { name: /16:9/ }));
    fireEvent.click(
      within(screen.getByTestId("aigc-image-size-menu")).getByText("4K"),
    );
    fireEvent.click(
      within(screen.getByTestId("aigc-image-size-menu")).getByText("1:1"),
    );
    fireEvent.click(within(composer).getByRole("button", { name: "高级设置" }));
    fireEvent.click(
      within(screen.getByTestId("aigc-image-advanced-menu")).getByLabelText(
        "联网搜索",
      ),
    );
    fireEvent.click(within(composer).getByRole("button", { name: "镜头" }));
    fireEvent.click(
      within(screen.getByTestId("aigc-image-camera-menu")).getByRole("button", {
        name: "使用",
      }),
    );
    fireEvent.click(within(composer).getByRole("button", { name: /1张/ }));
    fireEvent.click(
      within(screen.getByTestId("aigc-image-count-menu")).getByText("4张"),
    );
    fireEvent.click(
      within(composer).getByRole("button", { name: "提交图片节点输入" }),
    );

    await waitFor(() => {
      expect(mockAigcStudioApi.submitJob).toHaveBeenCalledWith(
        expect.objectContaining({
          inputs: expect.objectContaining({
            prompt: "冬日雪景中的品牌模特，电影感光影",
            node_type: "image_generate",
            reference_nodes: expect.arrayContaining([
              expect.objectContaining({
                asset_name: "reference.png",
              }),
            ]),
          }),
          parameters: expect.objectContaining({
            imageMode: "image_to_image",
            aspectRatio: "1:1",
            resolution: "4K",
            imageCount: 4,
            referenceAssetName: "reference.png",
            webSearch: true,
            stylePreset: "电影感",
            styleTemplateId: "style-film",
            styleRuntimeMode: "prompt_style",
            styleDescription: "电影级光影与景深，强调主体叙事和画面氛围。",
            visualDna: [
              { element_id: "lighting.cinematic_contrast", weight: 0.95 },
              { element_id: "camera.shallow_depth", weight: 0.8 },
            ],
            markPreset: "主体区域",
            focusPreset: "主体清晰",
            cameraProfile: "电影镜头",
            cameraBody: "Panavision DXL2",
            lens: "Arri Signature Prime",
            focal: "35 mm",
            aperture: "f/4",
          }),
        }),
      );
    });
  }, 10000);

  it("shows image slash quick commands and stores the selected command", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    const composer = screen.getByTestId("aigc-image-composer");
    fireEvent.change(within(composer).getByLabelText("图片节点输入"), {
      target: { value: "/" },
    });

    const slashMenu = screen.getByTestId("aigc-image-slash-menu");
    expect(within(slashMenu).getByText("角色三视图生成")).toBeInTheDocument();
    fireEvent.click(within(slashMenu).getByText("角色三视图生成"));
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              id: "image-1",
              data: expect.objectContaining({
                slashCommand: "角色三视图生成",
                composerText: "根据角色参考图生成正面、侧面、背面三视图。",
              }),
            }),
          ]),
        }),
      );
    });
  });

  it("keeps image slash commands from submitting without a reference image", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("主视觉图片");
    const composer = screen.getByTestId("aigc-image-composer");
    const input = within(composer).getByLabelText("图片节点输入");
    fireEvent.change(input, {
      target: { value: "/" },
    });

    fireEvent.click(
      within(screen.getByTestId("aigc-image-slash-menu")).getByText(
        "角色三视图生成",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "运行节点" }));

    expect(
      await within(composer).findByText(
        "请先上传或连接参考图，再运行这个快捷指令。",
      ),
    ).toBeInTheDocument();
    expect(mockAigcStudioApi.submitJob).not.toHaveBeenCalled();
    expect(input).toHaveValue("根据角色参考图生成正面、侧面、背面三视图。");
  });

  it("submits image slash commands with reference inputs when a reference image exists", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "图片生成/编辑" }));
    fireEvent.change(
      within(screen.getByTestId("aigc-image-editor")).getByLabelText(
        "上传图生图参考图",
      ),
      {
        target: {
          files: [new File(["image"], "reference.png", { type: "image/png" })],
        },
      },
    );

    await screen.findByTestId("aigc-image-reference-thumb");
    const composer = screen.getByTestId("aigc-image-composer");
    fireEvent.change(within(composer).getByLabelText("图片节点输入"), {
      target: { value: "/" },
    });
    fireEvent.click(
      within(screen.getByTestId("aigc-image-slash-menu")).getByText(
        "角色三视图生成",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "运行节点" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.submitJob).toHaveBeenCalledWith(
        expect.objectContaining({
          inputs: expect.objectContaining({
            reference_nodes: expect.arrayContaining([
              expect.objectContaining({
                asset_name: "reference.png",
              }),
            ]),
          }),
          parameters: expect.objectContaining({
            slashCommand: "角色三视图生成",
            referenceAssetName: "reference.png",
          }),
        }),
      );
    });
  });

  it("turns image upscale into a connected source and configurable upscale panel", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "图片生成/编辑" }));
    fireEvent.change(
      within(screen.getByTestId("aigc-image-editor")).getByLabelText(
        "上传高清放大原图",
      ),
      {
        target: {
          files: [new File(["image"], "upscale.png", { type: "image/png" })],
        },
      },
    );

    expect(screen.queryByText("输入已更新")).not.toBeInTheDocument();
    expect(await screen.findByText("高清放大")).toBeInTheDocument();
    expect(screen.getByText("配置参数生成高清图像")).toBeInTheDocument();
    const upscaleNode = screen
      .getByText("高清")
      .closest("[data-testid^='aigc-node-']");
    expect(upscaleNode).not.toBeNull();
    expect(
      within(upscaleNode as HTMLElement).queryByLabelText("上传图片参考素材"),
    ).not.toBeInTheDocument();
    const upscaleComposer = screen.getByTestId("aigc-image-composer");
    expect(
      within(upscaleComposer).queryByLabelText("图片节点输入"),
    ).not.toBeInTheDocument();
    expect(
      within(upscaleComposer).queryByText("16:9 · 标准画质 · 2K"),
    ).not.toBeInTheDocument();
    expect(within(upscaleComposer).queryByText("镜头")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "4" }));
    fireEvent.click(
      within(upscaleComposer).getByRole("button", {
        name: "提交图片节点输入",
      }),
    );

    await waitFor(() => {
      expect(mockAigcStudioApi.submitJob).toHaveBeenCalledWith(
        expect.objectContaining({
          inputs: expect.objectContaining({
            prompt: "",
            node_type: "image_generate",
            reference_nodes: expect.arrayContaining([
              expect.objectContaining({
                asset_name: "upscale.png",
              }),
            ]),
          }),
          parameters: expect.objectContaining({
            imageMode: "upscale",
            referenceAssetName: "upscale.png",
            upscaleProvider: "Topazlabs",
            upscaleModel: "通用",
            upscaleFactor: 4,
          }),
        }),
      );
    });
    await waitFor(() => {
      expect(screen.getByTestId("aigc-image-editor")).toHaveAttribute(
        "data-image-state",
        "generated",
      );
    });
    expect(screen.getAllByText("image-1.svg").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "reference_asset",
              data: expect.objectContaining({
                previewKind: "uploaded_source",
                assetName: "upscale.png",
              }),
            }),
            expect.objectContaining({
              type: "image_generate",
              data: expect.objectContaining({
                title: "高清",
                imageMode: "upscale",
                referenceAssetName: "upscale.png",
                inputUpdated: true,
                upscaleFactor: 4,
              }),
            }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              sourceHandle: "right",
              targetHandle: "left",
            }),
          ]),
        }),
      );
    });
  });

  it("continues from generated upscale results through download, preview, and image editing", async () => {
    mockAigcStudioApi.listCanvases.mockResolvedValue({
      canvases: [
        {
          ...canvasFixture(),
          nodes: [
            {
              id: "upscale-1",
              type: "image_generate",
              position: { x: 320, y: 140 },
              data: {
                title: "高清",
                imageMode: "upscale",
                imageState: "generated",
                referenceAssetName: "upscale.png",
                outputs: [
                  {
                    id: "asset-upscale",
                    kind: "image",
                    name: "image-1.svg",
                    path: "aigc_studio/canvas-1/job-2/image-1.svg",
                    url: "/api/user/aigc-studio/assets/asset-upscale/file",
                    width: 2048,
                    height: 2048,
                  },
                ],
              },
            },
          ],
          edges: [],
        },
      ],
    });
    render(<AigcStudioPage />);

    await screen.findByText("高清");
    fireEvent.click(screen.getByTestId("aigc-node-upscale-1"));
    const editor = screen.getByTestId("aigc-image-editor");
    expect(editor).toHaveAttribute("data-image-state", "generated");
    expect(editor).not.toHaveTextContent("2048 × 2048");
    expect(screen.getByTestId("aigc-image-node-meta")).toHaveTextContent(
      "2048 × 2048",
    );

    const viewerToolbar = screen.getByTestId("aigc-image-viewer-toolbar");
    expect(viewerToolbar).toHaveAttribute(
      "data-toolbar-placement",
      "node-above",
    );
    expect(editor).not.toContainElement(viewerToolbar);
    expect(
      within(viewerToolbar).queryByRole("button", { name: "当前视角截图" }),
    ).not.toBeInTheDocument();
    expect(
      within(viewerToolbar).queryByRole("button", { name: "4大视角截图" }),
    ).not.toBeInTheDocument();
    expect(
      within(viewerToolbar).queryByRole("button", { name: "12大视角截图" }),
    ).not.toBeInTheDocument();
    const anchorClick = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      blob: vi
        .fn()
        .mockResolvedValue(
          new Blob(["upscale image"], { type: "image/svg+xml" }),
        ),
    });
    const createObjectUrl = vi.fn(() => "blob:upscale-download");
    const revokeObjectUrl = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectUrl,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectUrl,
    });
    fireEvent.click(
      within(viewerToolbar).getByRole("button", { name: "下载结果" }),
    );
    await waitFor(() => {
      expect(anchorClick).toHaveBeenCalled();
    });
    expect(
      screen.queryByTestId("aigc-image-node-download-status"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("已准备下载")).not.toBeInTheDocument();
    expect(editor).not.toHaveTextContent("已准备下载");
    const downloadAnchor = document.querySelector("a[download='image-1.svg']");
    expect(downloadAnchor).toBeInTheDocument();
    expect(downloadAnchor).toHaveAttribute("href", "blob:upscale-download");
    expect(revokeObjectUrl).not.toHaveBeenCalled();
    anchorClick.mockRestore();

    fireEvent.click(
      within(viewerToolbar).getByRole("button", { name: "全屏查看" }),
    );
    expect(editor).toHaveAttribute("data-image-expanded", "true");
    expect(screen.getByText("图片预览")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "关闭图片预览" }));

    fireEvent.click(
      within(viewerToolbar).getByRole("button", { name: "发送到图片节点" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              id: "upscale-1",
              type: "image_generate",
            }),
            expect.objectContaining({
              type: "image_generate",
              data: expect.objectContaining({
                imageMode: "image_to_image",
                imageState: "editing",
                referenceThumb: true,
                referenceAssetName: "image-1.svg",
                referencePreviewUrl:
                  "/api/user/aigc-studio/assets/asset-upscale/file",
                referenceImageNodeId: "upscale-1",
              }),
            }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              source: "upscale-1",
              target: expect.stringMatching(/^image-from-result-/),
              sourceHandle: "right",
              targetHandle: "left",
            }),
          ]),
        }),
      );
    });
  });

  it("records image uploads as image-to-image references on the selected image node", async () => {
    render(<AigcStudioPage />);

    await screen.findByText("AIGC 创意工作室");
    fireEvent.click(screen.getByRole("button", { name: "图片生成/编辑" }));
    const selectedNode = screen
      .getByTestId("aigc-image-editor")
      .closest("[data-testid^='aigc-node-']");
    expect(selectedNode).not.toBeNull();
    fireEvent.change(
      within(selectedNode as HTMLElement).getByLabelText("上传图片参考素材"),
      {
        target: {
          files: [new File(["image"], "reference.png", { type: "image/png" })],
        },
      },
    );
    await waitFor(() => {
      expect(mockAigcStudioApi.uploadAsset).toHaveBeenCalledWith(
        expect.objectContaining({ name: "reference.png" }),
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => {
      expect(mockAigcStudioApi.saveCanvas).toHaveBeenCalledWith(
        "canvas-1",
        expect.objectContaining({
          nodes: expect.arrayContaining([
            expect.objectContaining({
              type: "reference_asset",
              data: expect.objectContaining({
                assetKind: "image",
                assetName: "reference.png",
                assetPath: "aigc_studio/uploads/reference.png",
                assetPreviewUrl:
                  "/api/user/aigc-studio/assets/reference.png/file",
                previewKind: "uploaded_source",
                savedToAssets: true,
              }),
            }),
            expect.objectContaining({
              type: "image_generate",
              data: expect.objectContaining({
                imageMode: "image_to_image",
                imageState: "editing",
                referenceThumb: true,
                referenceAssetName: "reference.png",
                referencePreviewUrl:
                  "/api/user/aigc-studio/assets/reference.png/file",
              }),
            }),
          ]),
          edges: expect.arrayContaining([
            expect.objectContaining({
              source: expect.stringMatching(/^image-source-/),
              target: expect.stringMatching(/^image_generate-/),
              sourceHandle: "right",
              targetHandle: "left",
            }),
          ]),
        }),
      );
    });
  });
});
