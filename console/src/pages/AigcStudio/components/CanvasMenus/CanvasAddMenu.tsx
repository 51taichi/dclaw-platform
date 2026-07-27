import type { useTranslation } from "react-i18next";

import type { AddMenuAnchor } from "../../useCanvasFloatingMenus";
import {
  NODE_DEFINITIONS,
  isAddMenuNodeType,
} from "../../domain/componentRegistry";
import styles from "../../index.module.less";

type CanvasAddMenuProps = {
  anchor?: AddMenuAnchor | null;
  t: ReturnType<typeof useTranslation>["t"];
  onAddNode: (type: string) => void;
};

export function CanvasAddMenu({ anchor, t, onAddNode }: CanvasAddMenuProps) {
  return (
    <div
      className={styles.addMenu}
      data-testid="aigc-add-node-menu"
      style={anchor ? { left: anchor.x, top: anchor.y } : undefined}
      onClick={(event) => event.stopPropagation()}
    >
      <div className={styles.addMenuTitle}>
        {t("aigcStudio.addNode", "添加节点")}
      </div>
      {NODE_DEFINITIONS.filter((definition) =>
        isAddMenuNodeType(definition.type),
      ).map((definition) => (
        <button
          type="button"
          key={definition.type}
          className={styles.addMenuItem}
          onClick={() => onAddNode(definition.type)}
        >
          <span className={styles.addMenuIcon}>{definition.icon}</span>
          <span>
            <strong>{t(definition.titleKey, definition.titleFallback)}</strong>
            <small>
              {t(definition.descriptionKey, definition.descriptionFallback)}
            </small>
          </span>
          {definition.tag && (
            <em className={styles.menuTag}>{definition.tag}</em>
          )}
        </button>
      ))}
    </div>
  );
}
