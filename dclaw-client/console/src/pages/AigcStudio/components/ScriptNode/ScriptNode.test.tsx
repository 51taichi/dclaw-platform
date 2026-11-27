import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import { SCRIPT_SHOTS } from "./scriptNodeState";
import { ScriptNode } from "./ScriptNode";
import type { ScriptNodeWorkflow, StoryboardWorkflow } from "./types";

const t = ((
  _key: string,
  fallback?: string,
  values?: Record<string, unknown>,
) => {
  const template = fallback ?? _key;
  return Object.entries(values ?? {}).reduce(
    (result, [key, value]) => result.split(`{{${key}}}`).join(String(value)),
    template,
  );
}) as never;

const scriptNode = (data: AigcCanvasNode["data"] = {}): AigcCanvasNode => ({
  id: "script-1",
  type: "script_generate",
  position: { x: 360, y: 120 },
  data: {
    title: "脚本生成器",
    ...data,
  },
});

const IMAGE_MODEL_OPTIONS: AigcCapabilityInfo[] = [
  {
    provider_id: "lib",
    provider_name: "Lib",
    model_id: "lib-image",
    model_name: "Lib Image",
    capability: "text_to_image",
    source: "model_registry",
  },
  {
    provider_id: "seedream",
    provider_name: "Seedream",
    model_id: "seedream-4-6",
    model_name: "Seedream 4.6",
    capability: "text_to_image",
    source: "model_registry",
  },
];

const scriptWorkflow = (): ScriptNodeWorkflow => ({
  handleScriptTry: vi.fn(),
  handleScriptComposerSubmit: vi.fn(),
  handleScriptRegenerate: vi.fn(),
  handleScriptViewChange: vi.fn(),
  handleScriptGenerateStoryboard: vi.fn(),
  handleScriptWorkflowStepChange: vi.fn(),
  handleScriptAssetSelect: vi.fn(),
  handleScriptAssetGenerate: vi.fn(),
  handleScriptAssetsGenerateAll: vi.fn(),
  handleScriptPromptSelect: vi.fn(),
  handleScriptPromptGenerate: vi.fn(),
  handleScriptPromptsGenerateAll: vi.fn(),
  handleToggleScriptFullscreen: vi.fn(),
});

const storyboardWorkflow = (): StoryboardWorkflow => ({
  handleCloseStoryboardComposer: vi.fn(),
  handleStoryboardComposerSubmit: vi.fn(),
  handleRunStoryboardImageGroup: vi.fn(),
  handleToggleScriptShot: vi.fn(),
  handleToggleAllScriptShots: vi.fn(),
  handleSelectStoryboardStyle: vi.fn(),
  handleSelectStoryboardShot: vi.fn(),
  handleToggleStoryboardVideoShot: vi.fn(),
  handleToggleAllStoryboardVideoShots: vi.fn(),
  handleOpenStoryboardVideoDialog: vi.fn(),
  handleCloseStoryboardVideoDialog: vi.fn(),
  handleGenerateStoryboardVideos: vi.fn(),
  handleRunStoryboardVideoGroup: vi.fn(),
});

function renderScriptNode(
  data: AigcCanvasNode["data"] = {},
  workflow = scriptWorkflow(),
  selected = false,
  modelOptions = IMAGE_MODEL_OPTIONS,
) {
  const stories = storyboardWorkflow();
  render(
    <ScriptNode
      node={scriptNode(data)}
      selected={selected}
      t={t}
      modelOptions={modelOptions}
      scriptWorkflow={workflow}
      storyboardWorkflow={stories}
      onUpdateNodeData={vi.fn()}
    />,
  );
  return { workflow, storyboardWorkflow: stories };
}

describe("ScriptNode", () => {
  it("renders the updated script generator empty state", () => {
    const workflow = scriptWorkflow();
    renderScriptNode({}, workflow);

    const generator = screen.getByTestId("aigc-script-generator");
    expect(generator).toHaveTextContent("尝试：");
    expect(
      within(generator).getByRole("button", { name: "剧本生成分镜脚本" }),
    ).toBeInTheDocument();
    expect(
      within(generator).getByRole("button", { name: "角色生成分镜脚本" }),
    ).toBeInTheDocument();
    expect(
      within(generator).getByRole("button", { name: "自己编写分镜脚本" }),
    ).toBeInTheDocument();
    expect(
      within(generator).queryByRole("button", { name: "视频参考生成分镜脚本" }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      within(generator).getByRole("button", { name: "角色生成分镜脚本" }),
    );
    expect(workflow.handleScriptTry).toHaveBeenCalledWith(
      expect.objectContaining({ id: "script-1" }),
      "character",
    );

    fireEvent.click(
      within(generator).getByRole("button", { name: "自己编写分镜脚本" }),
    );
    expect(workflow.handleScriptTry).toHaveBeenCalledWith(
      expect.objectContaining({ id: "script-1" }),
      "write",
    );
  });

  it("renders the compact script generating state", () => {
    const { storyboardWorkflow: stories } = renderScriptNode({
      scriptMode: "generating_script",
      scriptProgress: 1,
    });

    const generating = screen.getByTestId("aigc-script-generating");
    expect(generating).toHaveTextContent("生成中 1%...");
    expect(generating).not.toHaveTextContent("脚本视图");

    fireEvent.click(within(generating).getByRole("button", { name: "取消" }));
    expect(stories.handleCloseStoryboardComposer).toHaveBeenCalledWith(
      expect.objectContaining({ id: "script-1" }),
    );
  });

  it("renders a workflow entry instead of the full script table after generation", () => {
    const workflow = scriptWorkflow();
    renderScriptNode(
      {
        scriptMode: "script_ready",
        scriptShots: SCRIPT_SHOTS.slice(0, 3),
        selectedShotIds: SCRIPT_SHOTS.slice(0, 3).map((shot) => shot.id),
      },
      workflow,
    );

    const entry = screen.getByTestId("aigc-script-workflow-entry");
    expect(entry).toHaveTextContent("确认镜头");
    expect(entry).toHaveTextContent("准备资产");
    expect(entry).toHaveTextContent("合成提示词");
    expect(entry).not.toHaveTextContent("提示词已合成");
    expect(entry).toHaveTextContent("打开脚本节点");
    expect(screen.queryByTestId("aigc-script-table")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("aigc-script-ready-toolbar"),
    ).not.toBeInTheDocument();

    fireEvent.click(
      within(entry).getByRole("button", { name: "打开脚本节点" }),
    );
    expect(workflow.handleToggleScriptFullscreen).toHaveBeenCalledWith(
      expect.objectContaining({ id: "script-1" }),
    );
  });

  it("keeps the compact workflow focused on the three pre-video steps", () => {
    renderScriptNode({
      scriptMode: "script_ready",
      scriptShots: SCRIPT_SHOTS.slice(0, 2),
      selectedShotIds: ["shot-1", "shot-2"],
      scriptPromptStates: {
        "shot-1": "ready",
        "shot-2": "ready",
      },
    });

    const entry = screen.getByTestId("aigc-script-workflow-entry");
    expect(entry).toHaveTextContent("确认镜头");
    expect(entry).toHaveTextContent("准备资产");
    expect(entry).toHaveTextContent("合成提示词");
    expect(entry).not.toHaveTextContent("提示词已合成");
    expect(
      screen.queryByRole("button", { name: "批量生视频" }),
    ).not.toBeInTheDocument();
  });

  it("shows the compact batch storyboard toolbar after final prompts are ready", () => {
    const workflow = scriptWorkflow();
    renderScriptNode(
      {
        scriptMode: "script_ready",
        scriptShots: SCRIPT_SHOTS.slice(0, 2),
        selectedShotIds: ["shot-1", "shot-2"],
        scriptPromptStates: {
          "shot-1": "ready",
          "shot-2": "ready",
        },
      },
      workflow,
      true,
    );

    const toolbar = screen.getByTestId("aigc-script-ready-toolbar");
    expect(toolbar).toHaveTextContent("重新生成");
    expect(toolbar).toHaveTextContent("批量生成分镜");
    expect(toolbar).toHaveTextContent("批量生视频");

    fireEvent.click(
      within(toolbar).getByRole("button", { name: "批量生成分镜" }),
    );
    expect(workflow.handleScriptGenerateStoryboard).toHaveBeenCalledWith(
      expect.objectContaining({ id: "script-1" }),
    );
  });

  it("renders the full-screen shot confirmation workbench", () => {
    renderScriptNode({
      scriptMode: "script_ready",
      scriptFullscreen: true,
      scriptShots: SCRIPT_SHOTS.slice(0, 2),
      selectedShotIds: SCRIPT_SHOTS.slice(0, 2).map((shot) => shot.id),
    });

    const workbench = screen.getByTestId("aigc-script-workbench");
    expect(workbench).toHaveTextContent("确认镜头");
    expect(workbench).toHaveTextContent("准备资产");
    expect(workbench).toHaveTextContent("合成提示词");
    expect(workbench).toHaveTextContent("2个镜头已就绪");
    expect(workbench).toHaveTextContent("下一步：准备资产");
    expect(workbench).not.toHaveTextContent("脚本视图");
    expect(workbench).not.toHaveTextContent("创意视图");

    const table = screen.getByTestId("aigc-script-table");
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
    expect(table).toHaveTextContent("沈昭昭在深夜办公室疯狂加班");
    expect(table).toHaveTextContent("特写 (Close-Up)");
    expect(table).toHaveTextContent("待生成提示词");
  });

  it("shows parse failure details instead of an empty shot table", () => {
    const workflow = scriptWorkflow();
    renderScriptNode(
      {
        scriptMode: "script_ready",
        scriptFullscreen: true,
        scriptParseStatus: "failed",
        scriptParseError: "Storyboard output is not valid JSON.",
        scriptRawOutput: "坏输出",
        scriptShots: [],
      },
      workflow,
    );

    const workbench = screen.getByTestId("aigc-script-workbench");
    expect(workbench).toHaveTextContent("脚本解析失败");
    expect(workbench).toHaveTextContent("坏输出");
    expect(screen.queryByTestId("aigc-script-table")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重新生成脚本" }));
    expect(workflow.handleScriptRegenerate).toHaveBeenCalledWith(
      expect.objectContaining({ id: "script-1" }),
    );
  });

  it("recovers old plain-text parse failures as a shot table", () => {
    renderScriptNode({
      scriptMode: "script_ready",
      scriptFullscreen: true,
      scriptParseStatus: "failed",
      scriptParseError: "Storyboard output is not valid JSON.",
      scriptRawOutput: "那时的梧桐叶又大又密，风一吹就哗啦啦地响。",
      scriptShots: [],
      selectedShotIds: [],
    });

    const table = screen.getByTestId("aigc-script-table");
    expect(table).toHaveTextContent("那时的梧桐叶又大又密");
    expect(table).toHaveTextContent("待生成提示词");
    expect(screen.queryByTestId("aigc-script-parse-failure")).not.toBeInTheDocument();
  });

  it("advances the full-screen workbench to asset preparation", () => {
    const workflow = {
      ...scriptWorkflow(),
      handleScriptWorkflowStepChange: vi.fn(),
    };
    renderScriptNode(
      {
        scriptMode: "script_ready",
        scriptFullscreen: true,
        scriptShots: SCRIPT_SHOTS.slice(0, 2),
      },
      workflow,
    );

    fireEvent.click(screen.getByRole("button", { name: "下一步：准备资产" }));
    expect(workflow.handleScriptWorkflowStepChange).toHaveBeenCalledWith(
      expect.objectContaining({ id: "script-1" }),
      "assets",
    );
  });

  it("renders the asset preparation board before batch generation", () => {
    renderScriptNode({
      scriptMode: "script_ready",
      scriptFullscreen: true,
      scriptWorkflowStep: "assets",
      scriptShots: SCRIPT_SHOTS.slice(0, 4),
    });

    const assets = screen.getByTestId("aigc-script-assets");
    expect(assets).toHaveTextContent("角色");
    expect(assets).toHaveTextContent("场景");
    expect(assets).toHaveTextContent("道具");
    expect(assets).toHaveTextContent("生成或上传角色图");
    expect(assets).toHaveTextContent("生成或上传场景图");
    expect(assets).toHaveTextContent("生成或上传道具图");
    expect(
      screen.getByRole("button", { name: "一键生成所有资产" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "下一步：合成提示词" }),
    ).not.toBeInTheDocument();
  });

  it("does not turn empty script fields into asset cards", () => {
    renderScriptNode({
      scriptMode: "script_ready",
      scriptFullscreen: true,
      scriptWorkflowStep: "assets",
      scriptShots: [
        {
          id: "shot-empty-assets",
          no: 1,
          duration: 3,
          imageDescription: "夏日午后，院子里的梧桐树轻轻摇晃。",
          character: "童年时期的我（约6岁）",
          characterDescription: "童年时期的我",
          character2: "无",
          characterDescription2: "无",
          scene: "瓦房大院，梧桐树下",
          shotType: "远景",
          action: "抬头看树",
          emotion: "安静",
          dialogue: "无",
          prompt: "院子里的梧桐树，童年回忆感",
          videoPrompt: "微风吹过树叶",
        },
      ],
    });

    const assets = screen.getByTestId("aigc-script-assets");
    expect(assets).toHaveTextContent("童年时期的我（约6岁）");
    expect(assets).toHaveTextContent("瓦房大院，梧桐树下");
    expect(assets).not.toHaveTextContent("角色形象：无");
    expect(assets).not.toHaveTextContent("关键道具：关键道具");
    expect(assets).not.toHaveTextContent("生成或上传道具图");
  });

  it("opens a confirmation dialog before batch asset generation", () => {
    const workflow = scriptWorkflow();
    renderScriptNode(
      {
        scriptMode: "script_ready",
        scriptFullscreen: true,
        scriptWorkflowStep: "assets",
        scriptShots: SCRIPT_SHOTS.slice(0, 1),
      },
      workflow,
    );

    fireEvent.click(screen.getByRole("button", { name: "一键生成所有资产" }));
    const dialog = screen.getByRole("dialog", { name: "一键生成所有资产" });
    expect(dialog).toHaveTextContent("角色");
    expect(dialog).toHaveTextContent("场景");
    expect(dialog).toHaveTextContent("道具");
    expect(dialog).toHaveTextContent("Lib Image");
    expect(dialog).toHaveTextContent("标准画质");
    expect(dialog).toHaveTextContent("2K");
    expect(dialog).toHaveTextContent("2:1");

    fireEvent.click(
      within(dialog).getByRole("button", { name: /Lib Image/ }),
    );
    fireEvent.click(
      within(screen.getByTestId("aigc-script-asset-model-menu")).getByRole(
        "button",
        { name: /Seedream 4.6/ },
      ),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: /2:1/ }));
    fireEvent.click(
      within(screen.getByTestId("aigc-script-asset-ratio-menu")).getByRole(
        "button",
        { name: /16:9/ },
      ),
    );

    fireEvent.click(within(dialog).getByRole("button", { name: "生成(3)" }));
    expect(workflow.handleScriptAssetsGenerateAll).toHaveBeenCalledWith(
      expect.objectContaining({ id: "script-1" }),
      expect.arrayContaining([
        "character:沈昭昭现代",
        "scene:现代办公室，凌乱桌面，电脑屏幕发光",
        "prop:屏幕",
      ]),
      expect.objectContaining({
        modelLabel: "Seedream 4.6",
        providerId: "seedream",
        providerName: "Seedream",
        modelId: "seedream-4-6",
        modelCapability: "text_to_image",
        imageQuality: "标准画质",
        resolution: "2K",
        aspectRatio: "16:9",
      }),
    );
  });

  it("shows generating cards while all selected assets are being created", () => {
    renderScriptNode({
      scriptMode: "script_ready",
      scriptFullscreen: true,
      scriptWorkflowStep: "assets",
      scriptShots: SCRIPT_SHOTS.slice(0, 1),
      scriptAssetProgress: 4,
      scriptAssetStates: {
        "character:沈昭昭现代": "generating",
        "scene:现代办公室，凌乱桌面，电脑屏幕发光": "generating",
        "prop:屏幕": "generating",
      },
    });

    const assets = screen.getByTestId("aigc-script-assets");
    expect(assets).toHaveTextContent("生成中 4%...");
    expect(
      screen.getByRole("button", { name: "一键生成所有资产" }),
    ).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "下一步：合成提示词" }),
    ).not.toBeInTheDocument();
  });

  it("keeps prompt composition locked until all script assets are ready", () => {
    renderScriptNode({
      scriptMode: "script_ready",
      scriptFullscreen: true,
      scriptWorkflowStep: "assets",
      scriptShots: SCRIPT_SHOTS.slice(0, 1),
    });

    expect(
      screen.queryByRole("button", { name: "下一步：合成提示词" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("aigc-script-workbench-stepper"),
    ).toHaveTextContent("0/3 已生成，还差 3 个");
  });

  it("allows prompt composition after all script assets are ready", () => {
    const workflow = scriptWorkflow();
    renderScriptNode(
      {
        scriptMode: "script_ready",
        scriptFullscreen: true,
        scriptWorkflowStep: "assets",
        scriptShots: SCRIPT_SHOTS.slice(0, 1),
        scriptAssetStates: {
          "character:沈昭昭现代": "ready",
          "scene:现代办公室，凌乱桌面，电脑屏幕发光": "ready",
          "prop:屏幕": "ready",
        },
      },
      workflow,
    );

    expect(
      screen.getByTestId("aigc-script-workbench-stepper"),
    ).toHaveTextContent("3/3 已生成");
    fireEvent.click(screen.getByRole("button", { name: "下一步：合成提示词" }));
    expect(workflow.handleScriptWorkflowStepChange).toHaveBeenCalledWith(
      expect.objectContaining({ id: "script-1" }),
      "prompts",
    );
  });

  it("renders prompt composition as a shot table and confirms batch composition", () => {
    const workflow = scriptWorkflow();
    renderScriptNode(
      {
        scriptMode: "script_ready",
        scriptFullscreen: true,
        scriptWorkflowStep: "prompts",
        selectedScriptPromptShotId: "shot-1",
        scriptShots: SCRIPT_SHOTS.slice(0, 2),
      },
      workflow,
    );

    const prompts = screen.getByTestId("aigc-script-prompts");
    expect(prompts).toHaveTextContent("沈昭昭在深夜办公室疯狂加班");
    expect(prompts).toHaveTextContent("待生成提示词");

    fireEvent.click(screen.getByRole("button", { name: "一键合成全部提示词" }));
    const dialog = screen.getByRole("dialog", { name: "合成最终提示词" });
    expect(dialog).toHaveTextContent("镜头 1");
    expect(dialog).toHaveTextContent("镜头 2");
    expect(dialog).toHaveTextContent("GVLM 3.1 Flash");
    expect(dialog).toHaveTextContent("已选2/2");

    fireEvent.click(within(dialog).getByRole("button", { name: "确认生成" }));
    expect(workflow.handleScriptPromptsGenerateAll).toHaveBeenCalledWith(
      expect.objectContaining({ id: "script-1" }),
      ["shot-1", "shot-2"],
    );
  });

  it("shows final prompt composition progress inside the table", () => {
    renderScriptNode({
      scriptMode: "script_ready",
      scriptFullscreen: true,
      scriptWorkflowStep: "prompts",
      scriptPromptProgress: 3,
      scriptPromptStates: {
        "shot-1": "generating",
        "shot-2": "generating",
      },
      scriptShots: SCRIPT_SHOTS.slice(0, 2),
    });

    expect(
      screen.queryByRole("button", { name: "下一步：批量生视频" }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("aigc-script-prompts")).toHaveTextContent(
      "合成中 3%",
    );
  });

  it("opens generated prompt details without leaving the prompt table", () => {
    const workflow = scriptWorkflow();
    renderScriptNode(
      {
        scriptMode: "script_ready",
        scriptFullscreen: true,
        scriptWorkflowStep: "prompts",
        selectedScriptPromptShotId: "shot-1",
        scriptPromptStates: {
          "shot-1": "ready",
          "shot-2": "ready",
        },
        scriptShots: SCRIPT_SHOTS.slice(0, 2),
        selectedShotIds: ["shot-1", "shot-2"],
      },
      workflow,
    );

    const prompts = screen.getByTestId("aigc-script-prompts");
    expect(prompts).toHaveTextContent("查看提示词");
    expect(
      screen.getByTestId("aigc-script-workbench-stepper"),
    ).toHaveTextContent("2/2 已合成");
    expect(
      screen.queryByRole("button", { name: "下一步：批量生视频" }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      within(prompts).getAllByRole("button", { name: "查看提示词" })[0],
    );
    const dialog = screen.getByRole("dialog", { name: "第 1 镜：最终提示词" });
    expect(dialog).toHaveTextContent("分镜提示词");
    expect(dialog).toHaveTextContent("视频运动提示词");
    expect(dialog).toHaveTextContent("GVLM 3.1 Flash");

    fireEvent.click(
      within(dialog).getByRole("button", { name: "重新合成提示词" }),
    );
    expect(workflow.handleScriptPromptGenerate).toHaveBeenCalledWith(
      expect.objectContaining({ id: "script-1" }),
      "shot-1",
    );
  });

  it("returns to the compact completed workflow after leaving fullscreen", () => {
    const workflow = scriptWorkflow();
    renderScriptNode(
      {
        scriptMode: "script_ready",
        scriptFullscreen: true,
        scriptWorkflowStep: "prompts",
        scriptPromptStates: {
          "shot-1": "ready",
          "shot-2": "ready",
        },
        scriptShots: SCRIPT_SHOTS.slice(0, 2),
        selectedShotIds: ["shot-1", "shot-2"],
      },
      workflow,
    );

    fireEvent.click(screen.getByRole("button", { name: "退出放大" }));
    expect(workflow.handleToggleScriptFullscreen).toHaveBeenCalledWith(
      expect.objectContaining({ id: "script-1" }),
    );

    renderScriptNode({
      scriptMode: "script_ready",
      scriptWorkflowStep: "prompts",
      scriptPromptStates: {
        "shot-1": "ready",
        "shot-2": "ready",
      },
      scriptShots: SCRIPT_SHOTS.slice(0, 2),
      selectedShotIds: ["shot-1", "shot-2"],
    });

    const entry = screen.getByTestId("aigc-script-workflow-entry");
    expect(entry).toHaveTextContent("确认镜头");
    expect(entry).toHaveTextContent("准备资产");
    expect(entry).toHaveTextContent("合成提示词");
    expect(entry).not.toHaveTextContent("提示词已合成");
  });
});
