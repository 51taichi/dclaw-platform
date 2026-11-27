import { Plus } from "lucide-react";
import type { useTranslation } from "react-i18next";

import styles from "../../index.module.less";

type CanvasEmptyProjectLauncherProps = {
  t: ReturnType<typeof useTranslation>["t"];
  onCreateCanvas: () => void;
};

export function CanvasEmptyProjectLauncher({
  t,
  onCreateCanvas,
}: CanvasEmptyProjectLauncherProps) {
  return (
    <div className={styles.emptyProjectLauncher}>
      <div>{t("aigcStudio.projects.empty", "暂无项目")}</div>
      <button
        type="button"
        onClick={onCreateCanvas}
        data-platform-control-id="aigc.canvas.create"
      >
        <Plus size={14} />
        {t("aigcStudio.projects.new", "新建项目")}
      </button>
    </div>
  );
}
