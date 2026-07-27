import styles from "../../index.module.less";
import type { ReferenceNoteNodeProps } from "./types";

export function ReferenceNoteNode({
  node,
  icon,
  t,
  setSelectedNodeId,
  onUpdateNodeData,
}: ReferenceNoteNodeProps) {
  return (
    <>
      <div className={styles.textNodeLabel}>
        <span>
          {icon}
          {String(
            node.data.title ??
              t("aigcStudio.nodeLibrary.referenceNode.title", "参考节点"),
          )}
        </span>
      </div>
      <div
        className={styles.referenceNoteSurface}
        data-testid="aigc-reference-note"
        onDoubleClick={(event) => {
          event.stopPropagation();
          setSelectedNodeId(node.id);
          onUpdateNodeData(node.id, { referenceEditing: true });
        }}
      >
        {node.data.referenceEditing === true ? (
          <textarea
            autoFocus
            className={styles.referenceNoteTextarea}
            value={String(node.data.text ?? "")}
            placeholder={t("aigcStudio.textNode.placeholder", "输入内容...")}
            aria-label={t("aigcStudio.referenceNode.editLabel", "参考说明")}
            onClick={(event) => event.stopPropagation()}
            onBlur={() =>
              onUpdateNodeData(node.id, {
                referenceEditing: false,
              })
            }
            onChange={(event) =>
              onUpdateNodeData(node.id, { text: event.target.value })
            }
          />
        ) : String(node.data.text ?? "").trim() ? (
          <div className={styles.referenceNoteContent}>
            {String(node.data.text ?? "")}
          </div>
        ) : (
          <div className={styles.referenceNoteEmpty}>
            <span>
              {String(
                node.data.placeholder ??
                  t(
                    "aigcStudio.referenceNode.hint",
                    "双击输入参考说明（不参与生成）",
                  ),
              )}
            </span>
            <div className={styles.textGlyph} aria-hidden>
              <span />
              <span />
              <span />
              <span />
            </div>
          </div>
        )}
      </div>
    </>
  );
}
