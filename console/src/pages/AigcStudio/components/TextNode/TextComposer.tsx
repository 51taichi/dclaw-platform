import { Play } from "lucide-react";
import { useRef } from "react";

import type {
  AigcCanvasNode,
  AigcCapabilityInfo,
} from "../../../../api/modules/aigcStudio";
import styles from "../../index.module.less";
import { useAutoGrowTextarea } from "../useAutoGrowTextarea";
import type { Translate } from "./types";

type TextComposerProps = {
  node: AigcCanvasNode;
  textModelMenuNodeId: string | null;
  currentModel?: AigcCapabilityInfo | null;
  modelOptions: AigcCapabilityInfo[];
  currentModelKey: string;
  t: Translate;
  onUpdateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
  onToggleModelMenu: (nodeId: string) => void;
  onSelectTextModel: (node: AigcCanvasNode, model: AigcCapabilityInfo) => void;
  onSubmitComposer: (node: AigcCanvasNode) => void | Promise<void>;
};

export function TextComposer({
  node,
  textModelMenuNodeId,
  currentModel,
  modelOptions,
  currentModelKey,
  t,
  onUpdateNodeData,
  onToggleModelMenu,
  onSelectTextModel,
  onSubmitComposer,
}: TextComposerProps) {
  const composerText = String(node.data.composerText ?? "");
  const composerInputRef = useRef<HTMLTextAreaElement | null>(null);
  useAutoGrowTextarea(composerText, composerInputRef);
  const textFlow =
    node.data.textMode === "generated"
      ? "generated"
      : String(node.data.textMode ?? "draft");

  return (
    <div
      className={`${styles.textComposer} ${
        textFlow === "generated" ? styles.textComposerGenerated : ""
      }`}
      data-testid="aigc-text-composer"
      data-text-flow={textFlow}
      onClick={(event) => event.stopPropagation()}
    >
      {node.data.referenceThumb === true && (
        <span className={styles.composerThumb} />
      )}
      <textarea
        ref={composerInputRef}
        className={`${styles.promptPlaceholder} ${styles.textComposerInput}`}
        value={composerText}
        placeholder={String(
          node.data.composerPlaceholder ??
            t(
              "aigcStudio.textNode.composer.write",
              "写下你想讲的故事、场景或角色设定。例如：一个来自未来的机器人，在城市屋顶看星星。",
            ),
        )}
        aria-label={t("aigcStudio.textNode.composerLabel", "文本节点输入")}
        onChange={(event) =>
          onUpdateNodeData(node.id, { composerText: event.target.value })
        }
      />
      <div className={styles.parameterBar}>
        <button
          type="button"
          className={styles.textModelButton}
          onClick={(event) => {
            event.stopPropagation();
            onToggleModelMenu(node.id);
          }}
        >
          {String(
            node.data.modelLabel ??
              currentModel?.model_name ??
              currentModel?.model_id ??
              t("aigcStudio.textNode.noModel", "未选择文本模型"),
          )}
          <span>⌃</span>
        </button>
        {textModelMenuNodeId === node.id && (
          <div
            className={styles.textModelMenu}
            data-testid="aigc-text-model-menu"
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
                  onSelectTextModel(node, model);
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
        <span>1</span>
        <button
          type="button"
          className={styles.runCircle}
          disabled={!composerText.trim()}
          aria-label={t(
            "aigcStudio.textNode.submitComposer",
            "提交文本节点输入",
          )}
          onClick={(event) => {
            event.stopPropagation();
            onSubmitComposer(node);
          }}
        >
          <Play size={15} />
        </button>
      </div>
    </div>
  );
}
