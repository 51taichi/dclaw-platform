import { CheckCircle2, FileText, Image, PenLine } from "lucide-react";

import styles from "../../index.module.less";
import { StoryboardBatchDialog } from "../StoryboardWorkflow/StoryboardBatchDialog";
import { StoryboardVideoBatchDialog } from "../StoryboardWorkflow/StoryboardVideoBatchDialog";
import {
  scriptMode,
  scriptShotsFromNode,
  scriptWorkflowStep,
} from "./scriptNodeState";
import { ScriptResultPanel } from "./ScriptResultPanel";
import { ScriptToolbar } from "./ScriptToolbar";
import type { ScriptNodeProps } from "./types";

function scriptPromptStatesFromNode(node: ScriptNodeProps["node"]) {
  const states = node.data.scriptPromptStates;
  if (!states || typeof states !== "object" || Array.isArray(states)) {
    return {};
  }
  return states as Record<string, string>;
}

function areAllScriptPromptsReady(node: ScriptNodeProps["node"]) {
  const shots = scriptShotsFromNode(node);
  const promptStates = scriptPromptStatesFromNode(node);
  return (
    shots.length > 0 && shots.every((shot) => promptStates[shot.id] === "ready")
  );
}

function ScriptGenerating({ node, t, storyboardWorkflow }: ScriptNodeProps) {
  return (
    <>
      <div className={styles.scriptNodeLabel}>
        <span>
          <FileText size={15} />
          {String(
            node.data.title ??
              t("aigcStudio.templateNodes.storyGenerate.title", "脚本 V2.2"),
          )}
        </span>
      </div>
      <div
        className={styles.scriptGeneratingPanel}
        data-testid="aigc-script-generating"
      >
        <div className={styles.scriptSkeletonGrid}>
          {Array.from({ length: 21 }).map((_, index) => (
            <span key={index} />
          ))}
        </div>
        <div className={styles.scriptGeneratingBadge}>
          <strong>
            {t("aigcStudio.scriptNode.generating", "生成中 {{progress}}%...", {
              progress: Number(node.data.scriptProgress ?? 4),
            })}
          </strong>
          <button
            type="button"
            onClick={() =>
              storyboardWorkflow.handleCloseStoryboardComposer(node)
            }
          >
            {t("common.cancel", "取消")}
          </button>
        </div>
      </div>
    </>
  );
}

function ScriptIdle({ node, t, scriptWorkflow }: ScriptNodeProps) {
  const tryItems = [
    {
      action: "script" as const,
      label: t("aigcStudio.scriptNode.try.script", "剧本生成分镜脚本"),
      icon: <FileText size={15} />,
    },
    {
      action: "character" as const,
      label: t("aigcStudio.scriptNode.try.character", "角色生成分镜脚本"),
      icon: <Image size={15} />,
    },
    {
      action: "write" as const,
      label: t("aigcStudio.scriptNode.try.write", "自己编写分镜脚本"),
      icon: <PenLine size={15} />,
    },
  ];

  return (
    <>
      <div className={styles.scriptNodeLabel}>
        <span>
          <FileText size={15} />
          {String(
            node.data.title ??
              t("aigcStudio.nodeType.script_generate", "脚本生成器"),
          )}
        </span>
      </div>
      <div
        className={styles.scriptPlaceholderCard}
        data-testid="aigc-script-generator"
      >
        <div className={styles.textGlyph} aria-hidden>
          <span />
          <span />
          <span />
          <span />
        </div>
        <div className={styles.scriptTryList}>
          <span>{t("aigcStudio.textNode.tryTitle", "尝试：")}</span>
          {tryItems.map((item) => (
            <button
              type="button"
              key={item.action}
              className={styles.textTryButton}
              onClick={(event) => {
                event.stopPropagation();
                scriptWorkflow.handleScriptTry(node, item.action);
              }}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </div>
      </div>
    </>
  );
}

function ScriptWorkflowEntry({
  node,
  selected,
  t,
  scriptWorkflow,
  storyboardWorkflow,
}: ScriptNodeProps) {
  const steps = [
    {
      value: "shots",
      label: t("aigcStudio.scriptNode.steps.confirmShots", "确认镜头"),
    },
    {
      value: "assets",
      label: t("aigcStudio.scriptNode.steps.prepareAssets", "准备资产"),
    },
    {
      value: "prompts",
      label: t("aigcStudio.scriptNode.steps.composePrompts", "合成提示词"),
    },
  ];
  const activeIndex = steps.findIndex(
    (step) => step.value === scriptWorkflowStep(node),
  );
  const completedCount = areAllScriptPromptsReady(node)
    ? steps.length
    : Math.max(0, activeIndex);

  return (
    <>
      {selected && areAllScriptPromptsReady(node) && (
        <ScriptToolbar
          node={node}
          t={t}
          onRegenerate={scriptWorkflow.handleScriptRegenerate}
          onGenerateStoryboard={scriptWorkflow.handleScriptGenerateStoryboard}
          onGenerateVideo={storyboardWorkflow.handleOpenStoryboardVideoDialog}
        />
      )}
      <div className={styles.scriptNodeLabel}>
        <span>
          <FileText size={15} />
          {String(node.data.scriptPrompt ?? node.data.title ?? "脚本 V2.2")}
        </span>
      </div>
      <div
        className={styles.scriptWorkflowEntry}
        data-testid="aigc-script-workflow-entry"
      >
        <div className={styles.textGlyph} aria-hidden>
          <span />
          <span />
          <span />
          <span />
        </div>
        <div className={styles.scriptWorkflowSteps}>
          {steps.map((step, index) => (
            <div
              className={[
                styles.scriptWorkflowStep,
                index < completedCount ? styles.scriptWorkflowStepDone : "",
                index === completedCount && completedCount < steps.length
                  ? styles.scriptWorkflowStepActive
                  : "",
              ].join(" ")}
              key={step.value}
            >
              <span className={styles.scriptWorkflowStepIcon}>
                {index < completedCount ? (
                  <CheckCircle2 size={16} />
                ) : (
                  index + 1
                )}
              </span>
              <span>{step.label}</span>
              {index < steps.length - 1 && <em aria-hidden />}
            </div>
          ))}
        </div>
        <button
          type="button"
          className={styles.scriptOpenWorkflowButton}
          onClick={(event) => {
            event.stopPropagation();
            scriptWorkflow.handleToggleScriptFullscreen(node);
          }}
        >
          {t("aigcStudio.scriptNode.openWorkflow", "打开脚本节点")}
          <span aria-hidden>→</span>
        </button>
      </div>
      {node.data.storyboardBatchDialogOpen === true && (
        <StoryboardBatchDialog
          node={node}
          t={t}
          storyboardWorkflow={storyboardWorkflow}
        />
      )}
      {node.data.storyboardVideoDialogOpen === true && (
        <StoryboardVideoBatchDialog
          node={node}
          t={t}
          storyboardWorkflow={storyboardWorkflow}
        />
      )}
    </>
  );
}

export function ScriptNode(props: ScriptNodeProps) {
  const { node, t, scriptWorkflow, storyboardWorkflow, modelOptions } = props;
  const mode = scriptMode(node);

  if (mode === "generating_script") {
    return <ScriptGenerating {...props} />;
  }

  if (
    mode === "script_ready" ||
    mode === "storyboard_select" ||
    mode === "storyboard_image_generating" ||
    mode === "storyboard_grid"
  ) {
    if (node.data.scriptFullscreen !== true) {
      return <ScriptWorkflowEntry {...props} />;
    }

    return (
      <ScriptResultPanel
        node={node}
        t={t}
        modelOptions={modelOptions}
        scriptWorkflow={scriptWorkflow}
        storyboardWorkflow={storyboardWorkflow}
      />
    );
  }

  return <ScriptIdle {...props} />;
}
