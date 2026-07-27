import { useState } from "react";

import { ChevronDown, ChevronRight, Clipboard, Upload } from "lucide-react";
import type { useTranslation } from "react-i18next";

import type { CanvasContextMenuState } from "../../useCanvasFloatingMenus";
import {
  NODE_DEFINITIONS,
  isContextMenuNodeType,
} from "../../domain/componentRegistry";
import styles from "../../index.module.less";

type CanvasContextMenuProps = {
  menu: CanvasContextMenuState;
  clipboardNode: unknown;
  t: ReturnType<typeof useTranslation>["t"];
  onAddNodeAt: (
    type: string,
    position: CanvasContextMenuState["position"],
  ) => void;
  onUploadImage: () => void;
  onUploadVideo: () => void;
  onUploadAudio: () => void;
  onPasteNode: () => void;
};

export function CanvasContextMenu({
  menu,
  clipboardNode,
  t,
  onAddNodeAt,
  onUploadImage,
  onUploadVideo,
  onUploadAudio,
  onPasteNode,
}: CanvasContextMenuProps) {
  const [addNodesOpen, setAddNodesOpen] = useState(false);
  const addNodeDefinitions = NODE_DEFINITIONS.filter((definition) =>
    isContextMenuNodeType(definition.type),
  );

  return (
    <div
      className={`${styles.contextMenu} ${styles.canvasContextMenu}`}
      data-testid="aigc-canvas-context-menu"
      style={{ left: menu.x, top: menu.y }}
      onClick={(event) => event.stopPropagation()}
    >
      <button
        type="button"
        className={styles.contextMenuSectionToggle}
        aria-expanded={addNodesOpen}
        onClick={() => setAddNodesOpen((open) => !open)}
      >
        <span>
          {addNodesOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          {t("aigcStudio.addNode", "添加节点")}
        </span>
      </button>
      {addNodesOpen &&
        addNodeDefinitions.map((definition) => {
          const title = t(definition.titleKey, definition.titleFallback);
          return (
            <button
              type="button"
              key={definition.type}
              aria-label={title}
              className={styles.contextMenuNestedItem}
              onClick={() => onAddNodeAt(definition.type, menu.position)}
            >
              <span>
                {definition.icon}
                {title}
              </span>
            </button>
          );
        })}
      <div className={styles.contextMenuDivider} />
      <button type="button" onClick={onUploadImage}>
        <span>
          <Upload size={14} />
          {t("aigcStudio.canvasMenu.uploadImage", "上传图片")}
        </span>
      </button>
      <button type="button" onClick={onUploadVideo}>
        <span>
          <Upload size={14} />
          {t("aigcStudio.canvasMenu.uploadVideo", "上传视频")}
        </span>
      </button>
      <button type="button" onClick={onUploadAudio}>
        <span>
          <Upload size={14} />
          {t("aigcStudio.canvasMenu.uploadAudio", "上传音频")}
        </span>
      </button>
      <button type="button" disabled={!clipboardNode} onClick={onPasteNode}>
        <span>
          <Clipboard size={14} />
          {t("aigcStudio.contextMenu.paste", "粘贴")}
        </span>
        <span>⌘V</span>
      </button>
    </div>
  );
}
