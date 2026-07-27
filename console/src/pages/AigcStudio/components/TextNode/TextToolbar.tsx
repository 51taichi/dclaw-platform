import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import styles from "../../index.module.less";
import type { TextFormatAction, Translate } from "./types";

const formatButtons = [
  { action: "clear", label: "/", key: "clear", fallback: "清除格式" },
  { action: "h1", label: "H1", key: "h1", fallback: "一级标题" },
  { action: "h2", label: "H2", key: "h2", fallback: "二级标题" },
  { action: "h3", label: "H3", key: "h3", fallback: "三级标题" },
  { action: "paragraph", label: "¶", key: "paragraph", fallback: "段落" },
] as const;

const inlineButtons = [
  { action: "bold", label: "B", key: "bold", fallback: "加粗" },
  { action: "italic", label: "I", key: "italic", fallback: "斜体" },
  { action: "list", label: "≡", key: "list", fallback: "编号列表" },
  { action: "bullet", label: "•", key: "bullet", fallback: "项目列表" },
  { action: "rule", label: "−", key: "rule", fallback: "插入分割线" },
  { action: "duplicate", label: "⧉", key: "duplicate", fallback: "复制节点" },
  { action: "expand", label: "↗", key: "expand", fallback: "展开节点" },
] as const;

const isInlineButtonActive = (
  node: AigcCanvasNode,
  action: TextFormatAction,
) => {
  if (action === "bold") return node.data.bold === true;
  if (action === "italic") return node.data.italic === true;
  if (action === "list") return node.data.listStyle === "list";
  if (action === "bullet") return node.data.listStyle === "bullet";
  if (action === "expand") return node.data.expanded === true;
  return false;
};

type TextToolbarProps = {
  node: AigcCanvasNode;
  t: Translate;
  onFormat: (node: AigcCanvasNode, action: TextFormatAction) => void;
};

export function TextToolbar({ node, t, onFormat }: TextToolbarProps) {
  return (
    <div
      className={styles.textToolbar}
      data-testid="aigc-text-toolbar"
      onClick={(event) => event.stopPropagation()}
    >
      {formatButtons.map((item) => {
        const title = t(
          `aigcStudio.textNode.toolbar.${item.key}`,
          item.fallback,
        );
        return (
          <button
            type="button"
            key={item.action}
            aria-label={title}
            title={title}
            className={
              node.data.blockStyle === item.action
                ? styles.textToolbarActive
                : ""
            }
            onMouseDown={(event) => event.preventDefault()}
            onClick={(event) => {
              event.stopPropagation();
              onFormat(node, item.action);
            }}
          >
            {item.label}
          </button>
        );
      })}
      <span />
      {inlineButtons.map((item) => {
        const title = t(
          `aigcStudio.textNode.toolbar.${item.key}`,
          item.fallback,
        );
        return (
          <button
            type="button"
            key={item.action}
            aria-label={title}
            title={title}
            className={
              isInlineButtonActive(node, item.action)
                ? styles.textToolbarActive
                : ""
            }
            onMouseDown={(event) => event.preventDefault()}
            onClick={(event) => {
              event.stopPropagation();
              onFormat(node, item.action);
            }}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
