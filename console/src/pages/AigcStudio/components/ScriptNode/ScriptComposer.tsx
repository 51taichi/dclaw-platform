import { FileText, Film, Image, Maximize2, Play } from "lucide-react";
import { useRef } from "react";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import styles from "../../index.module.less";
import { useAutoGrowTextarea } from "../useAutoGrowTextarea";
import { scriptReferenceCount } from "./scriptNodeState";
import type { ScriptNodeWorkflow, Translate } from "./types";

type ScriptComposerProps = {
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

function hasScriptReference(node: AigcCanvasNode) {
  const scriptSourceNodeId = String(node.data.scriptSourceNodeId ?? "").trim();
  if (scriptSourceNodeId) return true;
  if (Array.isArray(node.data.scriptReferenceAssets)) {
    return node.data.scriptReferenceAssets.length > 0;
  }
  return (
    node.data.scriptInputKind === "character" ||
    node.data.scriptInputKind === "video"
  );
}

function ScriptReferenceThumb({ node }: { node: AigcCanvasNode }) {
  const icon =
    node.data.scriptInputKind === "video" ? (
      <Film size={15} />
    ) : node.data.scriptInputKind === "character" ? (
      <Image size={15} />
    ) : (
      <FileText size={15} />
    );

  return (
    <span
      className={`${styles.scriptComposerThumb} ${
        node.data.scriptInputKind === "character"
          ? styles.scriptComposerThumbStack
          : ""
      }`}
    >
      {icon}
      <em>{scriptReferenceCount(node)}</em>
    </span>
  );
}

export function ScriptComposer({
  node,
  currentModel,
  modelOptions,
  currentModelKey,
  modelMenuNodeId,
  t,
  scriptWorkflow,
  onUpdateNodeData,
  onToggleModelMenu,
  onSelectModel,
}: ScriptComposerProps) {
  const composerText = String(node.data.composerText ?? "");
  const composerInputRef = useRef<HTMLTextAreaElement | null>(null);
  useAutoGrowTextarea(composerText, composerInputRef);
  const hasReference = hasScriptReference(node);
  const modelLabel = String(
    node.data.modelLabel ??
      currentModel?.model_name ??
      currentModel?.model_id ??
      "GVLM 3.1",
  );

  return (
    <div
      className={styles.scriptComposer}
      data-testid="aigc-script-composer"
      onClick={(event) => event.stopPropagation()}
    >
      <span className={styles.composerExpand} aria-hidden>
        <Maximize2 size={15} />
      </span>
      {hasReference && <ScriptReferenceThumb node={node} />}
      <textarea
        ref={composerInputRef}
        className={`${styles.scriptComposerPrompt} ${styles.textComposerInput}`}
        value={composerText}
        placeholder={String(
          node.data.composerPlaceholder ??
            t(
              "aigcStudio.scriptNode.composerPlaceholder",
              "描述剧情片段、故事，为你生成分镜脚本",
            ),
        )}
        aria-label={t("aigcStudio.scriptNode.composerLabel", "脚本生成器输入")}
        onChange={(event) =>
          onUpdateNodeData(node.id, {
            composerText: event.target.value,
            inputUpdated: true,
          })
        }
      />
      <div className={styles.parameterBar}>
        <button
          type="button"
          className={styles.textModelButton}
          aria-expanded={modelMenuNodeId === node.id}
          onClick={(event) => {
            event.stopPropagation();
            onToggleModelMenu(node.id);
          }}
        >
          {modelLabel}
          <span>⌃</span>
        </button>
        {modelMenuNodeId === node.id && (
          <div
            className={styles.textModelMenu}
            data-testid="aigc-script-model-menu"
          >
            {modelOptions.map((model, index) => (
              <button
                type="button"
                key={`${model.provider_id}:${model.model_id}`}
                className={
                  currentModelKey === `${model.provider_id}:${model.model_id}`
                    ? styles.textModelActive
                    : ""
                }
                onClick={(event) => {
                  event.stopPropagation();
                  onSelectModel(node, model);
                }}
              >
                <span>
                  <strong>{model.model_name ?? model.model_id}</strong>
                  <small>{model.provider_name}</small>
                </span>
                <em>{index % 2 === 0 ? "20s" : "10s"}</em>
              </button>
            ))}
          </div>
        )}
        <button
          type="button"
          className={styles.runCircle}
          disabled={!composerText.trim() && !hasReference}
          aria-label={t("aigcStudio.scriptNode.submit", "提交脚本生成器")}
          onClick={(event) => {
            event.stopPropagation();
            scriptWorkflow.handleScriptComposerSubmit(node);
          }}
        >
          <Play size={15} />
        </button>
      </div>
    </div>
  );
}
