import { isGeneratedTextNode, isTextWriteMode } from "../../utils/textNode";
import styles from "../../index.module.less";
import { TextComposer } from "./TextComposer";
import { canRenderTextNode, TextEditorSurface } from "./TextEditorSurface";
import { TextToolbar } from "./TextToolbar";
import type { TextNodeProps } from "./types";

export { canRenderTextNode };
export type { TextFormatAction, TextTryAction } from "./types";

export function TextNode({
  node,
  selected,
  editingNodeId,
  textModelMenuNodeId,
  currentModel,
  modelOptions,
  currentModelKey,
  nodeIcon,
  t,
  onFormat,
  onTry,
  onUpdateNodeData,
  onBeginGeneratedEdit,
  onToggleModelMenu,
  onSelectTextModel,
  onSubmitComposer,
}: TextNodeProps) {
  const isWriting =
    isTextWriteMode(node) ||
    (editingNodeId === node.id && isGeneratedTextNode(node));

  return (
    <>
      {selected && isWriting && (
        <TextToolbar node={node} t={t} onFormat={onFormat} />
      )}

      <div className={styles.textNodeLabel}>
        <span>
          {nodeIcon(node.type)}
          {String(
            node.data.title ?? t("aigcStudio.textNode.title", "文本节点"),
          )}
        </span>
      </div>

      <TextEditorSurface
        node={node}
        selected={selected}
        isWriting={isWriting}
        t={t}
        onTry={onTry}
        onUpdateNodeData={onUpdateNodeData}
        onBeginGeneratedEdit={onBeginGeneratedEdit}
      />

      {selected && !node.data.previewKind && !isTextWriteMode(node) && (
        <TextComposer
          node={node}
          textModelMenuNodeId={textModelMenuNodeId}
          currentModel={currentModel}
          modelOptions={modelOptions}
          currentModelKey={currentModelKey}
          t={t}
          onUpdateNodeData={onUpdateNodeData}
          onToggleModelMenu={onToggleModelMenu}
          onSelectTextModel={onSelectTextModel}
          onSubmitComposer={onSubmitComposer}
        />
      )}
    </>
  );
}
