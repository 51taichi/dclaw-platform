import type { useTranslation } from "react-i18next";
import { ChevronRight } from "lucide-react";

import type { AigcCanvasNode } from "../../../../api/modules/aigcStudio";
import type { PortMenuState } from "../../useCanvasFloatingMenus";
import {
  enabledPortTypesForNode,
  portMenuDefinitions,
} from "../../domain/componentRegistry";
import styles from "../../index.module.less";

type CanvasPortMenuProps = {
  menu: PortMenuState;
  node: AigcCanvasNode;
  t: ReturnType<typeof useTranslation>["t"];
  onCreatePortNode: (
    node: AigcCanvasNode,
    nodeType: string,
    side: PortMenuState["side"],
  ) => void;
};

const portMenuClassName = (enabled: boolean) =>
  `${styles.portMenuItem} ${enabled ? "" : styles.portMenuItemDisabled}`;

export function CanvasPortMenu({
  menu,
  node,
  t,
  onCreatePortNode,
}: CanvasPortMenuProps) {
  const title =
    menu.side === "left"
      ? t("aigcStudio.portMenu.addContext", "添加上下文")
      : t("aigcStudio.portMenu.useAsReference", "引用该节点生成");

  return (
    <div
      className={`${styles.contextMenu} ${styles.portMenu}`}
      data-testid="aigc-port-menu"
      style={{ left: menu.x, top: menu.y }}
      onClick={(event) => event.stopPropagation()}
    >
      <div className={styles.contextMenuTitle}>{title}</div>
      {portMenuDefinitions().map((definition) => {
        const definitionTitle = t(
          definition.titleKey,
          definition.titleFallback,
        );
        const enabled = enabledPortTypesForNode(node, menu.side).includes(
          definition.type,
        );
        const usesSubmenuAffordance =
          enabled &&
          menu.side === "right" &&
          definition.type === "script_generate";
        return (
          <button
            type="button"
            key={definition.type}
            aria-label={definitionTitle}
            disabled={!enabled}
            className={portMenuClassName(enabled)}
            onClick={() => onCreatePortNode(node, definition.type, menu.side)}
          >
            <span>
              {definition.icon}
              {definitionTitle}
            </span>
            {usesSubmenuAffordance ? (
              <span>
                <ChevronRight size={14} aria-hidden="true" />
              </span>
            ) : (
              definition.tag && <span>{definition.tag}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
