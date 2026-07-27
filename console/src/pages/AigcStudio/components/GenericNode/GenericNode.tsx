import styles from "../../index.module.less";
import { NodePreviewBlocks } from "./NodePreviewBlocks";
import type { GenericNodeProps } from "./types";

export function GenericNode({
  node,
  icon,
  translatedType,
  t,
}: GenericNodeProps) {
  return (
    <>
      <div className={styles.nodeLabel}>
        <span>
          {icon}
          {String(node.data.title ?? node.type)}
        </span>
        <span className={styles.nodeTypeBadge}>{translatedType}</span>
      </div>
      <div className={styles.nodeText}>{String(node.data.text ?? "")}</div>
      <NodePreviewBlocks node={node} t={t} />
    </>
  );
}
