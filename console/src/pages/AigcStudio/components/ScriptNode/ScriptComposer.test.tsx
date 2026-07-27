import type { ReactElement } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import { ScriptComposer } from "./ScriptComposer";
import type { ScriptNodeWorkflow, Translate } from "./types";

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
}) as unknown as Translate;

const scriptNode = (data: AigcCanvasNode["data"] = {}): AigcCanvasNode => ({
  id: "script-1",
  type: "script_generate",
  position: { x: 360, y: 120 },
  data: {
    title: "脚本生成器",
    ...data,
  },
});

const storyboardModel = (
  model_id: string,
  model_name = model_id,
): AigcCapabilityInfo => ({
  provider_id: "mxapi",
  provider_name: "MXAPI",
  model_id,
  model_name,
  capability: "storyboard",
  source: "model_registry",
});

const workflow = (): ScriptNodeWorkflow => ({
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

type DesiredScriptComposerProps = {
  node: AigcCanvasNode;
  currentModel?: AigcCapabilityInfo | null;
  modelOptions: AigcCapabilityInfo[];
  currentModelKey: string;
  modelMenuNodeId: string | null;
  t: Translate;
  scriptWorkflow: ScriptNodeWorkflow;
  onUpdateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
  onToggleModelMenu: (nodeId: string) => void;
  onSelectModel: (node: AigcCanvasNode, model: AigcCapabilityInfo) => void;
};

const DesiredScriptComposer = ScriptComposer as unknown as (
  props: DesiredScriptComposerProps,
) => ReactElement;

function renderScriptComposer(
  overrides: Partial<DesiredScriptComposerProps> = {},
) {
  const models = [
    storyboardModel("glm-4-7", "GLM-4.7"),
    storyboardModel("qwen-storyboard", "Qwen Storyboard"),
  ];
  const props: DesiredScriptComposerProps = {
    node: scriptNode(),
    currentModel: models[0],
    modelOptions: models,
    currentModelKey: "mxapi:glm-4-7",
    modelMenuNodeId: null,
    t,
    scriptWorkflow: workflow(),
    onUpdateNodeData: vi.fn(),
    onToggleModelMenu: vi.fn(),
    onSelectModel: vi.fn(),
    ...overrides,
  };
  const result = render(<DesiredScriptComposer {...props} />);
  return { ...result, props, models };
}

describe("ScriptComposer", () => {
  it("renders the default script composer as an empty editable prompt without a linked text chip", () => {
    const onUpdateNodeData = vi.fn();
    const scriptWorkflow = workflow();
    const { props, rerender } = renderScriptComposer({
      onUpdateNodeData,
      scriptWorkflow,
    });

    const input = screen.getByRole("textbox", {
      name: "脚本生成器输入",
    });
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute(
      "placeholder",
      "描述剧情片段、故事，为你生成分镜脚本",
    );
    expect(screen.queryByText("文本输入 1")).not.toBeInTheDocument();
    const composer = screen.getByTestId("aigc-script-composer");
    const toolbar = composer.querySelector("[class*='parameterBar']");
    expect(toolbar).not.toBeNull();
    expect(toolbar?.children.length).toBe(2);
    expect(screen.queryByText("6")).not.toBeInTheDocument();
    expect(composer.querySelectorAll("[class*='scriptComposerStatus']")).toHaveLength(
      0,
    );

    fireEvent.change(input, {
      target: { value: "把上传的故事整理成 12 个短剧分镜" },
    });

    expect(onUpdateNodeData).toHaveBeenCalledWith("script-1", {
      composerText: "把上传的故事整理成 12 个短剧分镜",
      inputUpdated: true,
    });

    rerender(
      <DesiredScriptComposer
        {...props}
        node={scriptNode({
          composerText: "把上传的故事整理成 12 个短剧分镜",
        })}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "提交脚本生成器" }),
    );
    expect(scriptWorkflow.handleScriptComposerSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "script-1",
        data: expect.objectContaining({
          composerText: "把上传的故事整理成 12 个短剧分镜",
        }),
      }),
    );
  });

  it("opens a storyboard model menu and selects a model for the script node", () => {
    const onToggleModelMenu = vi.fn();
    const onSelectModel = vi.fn();
    const { props, models, rerender } = renderScriptComposer({
      onToggleModelMenu,
      onSelectModel,
    });

    fireEvent.click(screen.getByRole("button", { name: /GLM-4.7/ }));
    expect(onToggleModelMenu).toHaveBeenCalledWith("script-1");

    rerender(
      <DesiredScriptComposer {...props} modelMenuNodeId="script-1" />,
    );

    const menu = screen.getByTestId("aigc-script-model-menu");
    expect(menu).toHaveTextContent("Qwen Storyboard");

    fireEvent.click(
      within(menu).getByRole("button", { name: /Qwen Storyboard/ }),
    );
    expect(onSelectModel).toHaveBeenCalledWith(
      expect.objectContaining({ id: "script-1" }),
      models[1],
    );
  });
});
