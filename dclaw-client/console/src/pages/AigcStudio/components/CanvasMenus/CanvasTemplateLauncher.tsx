import type { useTranslation } from "react-i18next";

import {
  TEMPLATE_CARDS,
  type TemplateVariant,
} from "../../domain/componentRegistry";
import styles from "../../index.module.less";

type CanvasTemplateLauncherProps = {
  t: ReturnType<typeof useTranslation>["t"];
  onTemplate: (variant: TemplateVariant) => void;
};

export function CanvasTemplateLauncher({
  t,
  onTemplate,
}: CanvasTemplateLauncherProps) {
  return (
    <div className={styles.templateLauncher}>
      <div className={styles.templateHint}>
        {t("aigcStudio.templateHint", "双击画布 自由生成节点")}
      </div>
      <div className={styles.templateList}>
        {TEMPLATE_CARDS.map((template) => (
          <button
            type="button"
            key={template.type}
            className={`${styles.templateCard} ${
              styles[`template_${template.variant}`] ?? ""
            }`}
            data-testid={`aigc-template-${template.variant}`}
            onClick={() => onTemplate(template.variant)}
          >
            <span className={styles.templateIcon}>{template.icon}</span>
            <span className={styles.templateText}>
              {t(template.titleKey, template.titleFallback)}
            </span>
            <span className={styles.templateVisual} aria-hidden />
          </button>
        ))}
      </div>
    </div>
  );
}
