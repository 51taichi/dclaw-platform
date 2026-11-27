import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import { AlertCircle, Loader2 } from "lucide-react";
import {
  isGeneratedTextNode,
  isScriptSourceTextNode,
} from "../../utils/textNode";
import styles from "../../index.module.less";
import { TextTryList } from "./TextTryList";
import { textNodeStateFromNode } from "./textNodeState";
import type { TextTryAction, Translate } from "./types";

type TextEditorSurfaceProps = {
  node: AigcCanvasNode;
  selected: boolean;
  isWriting: boolean;
  t: Translate;
  onTry: (node: AigcCanvasNode, action: TextTryAction) => void;
  onUpdateNodeData: (nodeId: string, data: Record<string, unknown>) => void;
  onBeginGeneratedEdit: (nodeId: string) => void;
};

export function TextEditorSurface({
  node,
  selected,
  isWriting,
  t,
  onTry,
  onUpdateNodeData,
  onBeginGeneratedEdit,
}: TextEditorSurfaceProps) {
  const textValue = String(node.data.text ?? "");
  const isGenerated = isGeneratedTextNode(node);
  const hasText = textValue.trim().length > 0;
  const generationState = textNodeStateFromNode(node);
  const jobError = String(node.data.job_error ?? "").trim();
  const textState = isWriting
    ? isGenerated
      ? "generated-editing"
      : "writing"
    : generationState === "generating"
    ? "generating"
    : generationState === "failed"
    ? "failed"
    : hasText
    ? isGenerated
      ? "generated"
      : "preview"
    : "empty";

  return (
    <div
      className={`${styles.textEditorSurface} ${
        isWriting ? styles.textEditorWriting : ""
      } ${isGenerated ? styles.textEditorGenerated : ""} ${
        isWriting && isGenerated ? styles.textEditorGeneratedEditing : ""
      } ${node.data.expanded === true ? styles.textEditorExpanded : ""}`}
      data-testid={selected ? "aigc-text-editor" : undefined}
      data-text-state={textState}
    >
      {isWriting ? (
        <textarea
          className={`${styles.textTextarea} ${
            styles[
              `textBlock_${String(node.data.blockStyle ?? "paragraph")}`
            ] ?? ""
          } ${node.data.bold === true ? styles.textBold : ""} ${
            node.data.italic === true ? styles.textItalic : ""
          } ${node.data.listStyle === "bullet" ? styles.textBulletList : ""} ${
            node.data.listStyle === "list" ? styles.textNumberList : ""
          } ${isGenerated ? styles.textGeneratedTextarea : ""}`}
          value={textValue}
          placeholder={t("aigcStudio.textNode.placeholder", "输入内容...")}
          aria-label={t("aigcStudio.textNode.editLabel", "文本内容")}
          onClick={(event) => {
            event.stopPropagation();
            if (isGenerated) {
              onBeginGeneratedEdit(node.id);
            }
          }}
          onFocus={() => {
            if (isGenerated) {
              onBeginGeneratedEdit(node.id);
            }
          }}
          onChange={(event) =>
            onUpdateNodeData(node.id, { text: event.target.value })
          }
        />
      ) : generationState === "generating" ? (
        <div className={styles.textGeneratingState}>
          <Loader2 size={20} />
          <span>{t("aigcStudio.textNode.generating", "文本生成中")}</span>
        </div>
      ) : generationState === "failed" ? (
        <div className={styles.textErrorState}>
          <AlertCircle size={18} />
          <span>
            {jobError ||
              t("aigcStudio.textNode.failedHint", "文本生成失败，请重试。")}
          </span>
        </div>
      ) : hasText ? (
        <div
          className={`${styles.textContent} ${
            isGenerated ? styles.textGeneratedContent : ""
          }`}
          data-testid={
            selected && isGenerated ? "aigc-text-generated-preview" : undefined
          }
          role={isGenerated ? "button" : undefined}
          tabIndex={isGenerated ? 0 : undefined}
          onClick={(event) => {
            event.stopPropagation();
            if (isGenerated) {
              onBeginGeneratedEdit(node.id);
            }
          }}
          onFocus={() => {
            if (isGenerated) {
              onBeginGeneratedEdit(node.id);
            }
          }}
          onKeyDown={(event) => {
            if (isGenerated && (event.key === "Enter" || event.key === " ")) {
              event.preventDefault();
              onBeginGeneratedEdit(node.id);
            }
          }}
        >
          {textValue}
        </div>
      ) : (
        <div className={styles.textGlyph} aria-hidden>
          <span />
          <span />
          <span />
          <span />
        </div>
      )}

      {node.data.showTryOptions === true && (
        <TextTryList node={node} t={t} onTry={onTry} />
      )}
    </div>
  );
}

export const canRenderTextNode = (node: AigcCanvasNode) =>
  node.type === "prompt" &&
  (!node.data.previewKind || isScriptSourceTextNode(node));
