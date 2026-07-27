import {
  BookOpen,
  Clock3,
  Package,
  Plus,
  Sparkles,
  Workflow,
} from "lucide-react";
import type { useTranslation } from "react-i18next";

import styles from "../../index.module.less";

export type RailPanel = "workflows" | "assets" | "history" | "help" | null;

type CanvasRailProps = {
  railPanel: RailPanel;
  t: ReturnType<typeof useTranslation>["t"];
  onToggleAddMenu: () => void;
  onSelectPanel: (panel: Exclude<RailPanel, null>) => void;
  onOpenStyleLibrary: () => void;
};

const railItems: Array<{
  panel: Exclude<RailPanel, null>;
  labelKey: string;
  labelFallback: string;
  icon: JSX.Element;
}> = [
  {
    panel: "workflows",
    labelKey: "aigcStudio.rail.openWorkflows",
    labelFallback: "打开我的工具箱",
    icon: <Workflow size={17} />,
  },
  {
    panel: "assets",
    labelKey: "aigcStudio.rail.openAssets",
    labelFallback: "打开我的资产",
    icon: <Package size={17} />,
  },
  {
    panel: "history",
    labelKey: "aigcStudio.rail.openHistory",
    labelFallback: "打开历史记录",
    icon: <Clock3 size={17} />,
  },
  {
    panel: "help",
    labelKey: "aigcStudio.rail.openHelp",
    labelFallback: "打开使用教程",
    icon: <BookOpen size={17} />,
  },
];

export function CanvasRail({
  railPanel,
  t,
  onToggleAddMenu,
  onSelectPanel,
  onOpenStyleLibrary,
}: CanvasRailProps) {
  return (
    <div className={styles.canvasRail}>
      <button
        type="button"
        aria-label={t("aigcStudio.addNode", "添加节点")}
        className={styles.railPrimary}
        onClick={(event) => {
          event.stopPropagation();
          onToggleAddMenu();
        }}
      >
        <Plus size={24} />
      </button>
      <button
        type="button"
        aria-label={t("aigcStudio.rail.openStyleLibrary", "打开风格库")}
        className={styles.railButton}
        onClick={(event) => {
          event.stopPropagation();
          onOpenStyleLibrary();
        }}
      >
        <Sparkles size={17} />
      </button>
      {railItems.map((item) => (
        <button
          type="button"
          key={item.panel}
          aria-label={t(item.labelKey, item.labelFallback)}
          className={`${styles.railButton} ${
            railPanel === item.panel ? styles.railButtonActive : ""
          }`}
          onClick={(event) => {
            event.stopPropagation();
            onSelectPanel(item.panel);
          }}
        >
          {item.icon}
        </button>
      ))}
    </div>
  );
}
