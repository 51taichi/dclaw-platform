import { Alert, Card, Spin } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { AigcModelCategory } from "@/api/modules/aigcModelPolicy";
import { useAppMessage } from "@/hooks/useAppMessage";
import {
  AIGC_MODEL_CATEGORIES,
  useAigcModelPolicy,
} from "../../hooks/useAigcModelPolicy";
import styles from "../../index.module.less";
import { AigcModelCategoryCard } from "./AigcModelCategoryCard";
import { AigcModelManagerDrawer } from "./AigcModelManagerDrawer";

export type PolicyState = ReturnType<typeof useAigcModelPolicy>;

export function AigcModelsSection({ state }: { state?: PolicyState }) {
  const internalState = useAigcModelPolicy();
  const policyState = state ?? internalState;
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [activeCategory, setActiveCategory] =
    useState<AigcModelCategory | null>(null);
  const [savingCategory, setSavingCategory] =
    useState<AigcModelCategory | null>(null);

  const save = async (category: AigcModelCategory) => {
    setSavingCategory(category);
    try {
      await policyState.saveCategory(category);
      message.success(t("models.aigc.saveSuccess"));
    } catch (cause) {
      message.error(
        cause instanceof Error ? cause.message : t("models.aigc.saveFailed"),
      );
    } finally {
      setSavingCategory(null);
    }
  };

  return (
    <Card className={`${styles.slotSection} ${styles.aigcModelsSection}`}>
      <div className={styles.aigcSectionHeading}>
        <h3>{t("models.aigc.title")}</h3>
      </div>
      {policyState.error && (
        <Alert type="error" showIcon message={policyState.error} />
      )}
      <Spin spinning={policyState.loading}>
        <div className={styles.aigcCategoryGrid}>
          {AIGC_MODEL_CATEGORIES.map((category) => (
            <AigcModelCategoryCard
              key={category}
              category={category}
              draft={policyState.drafts[category]}
              inventory={policyState.inventory?.categories[category] ?? []}
              configured={Boolean(policyState.policies?.categories[category])}
              dirty={policyState.dirtyCategories.has(category)}
              onManage={() => setActiveCategory(category)}
            />
          ))}
        </div>
      </Spin>
      {activeCategory && (
        <AigcModelManagerDrawer
          open
          category={activeCategory}
          draft={policyState.drafts[activeCategory]}
          inventory={policyState.inventory?.categories[activeCategory] ?? []}
          dirty={policyState.dirtyCategories.has(activeCategory)}
          saving={savingCategory === activeCategory}
          onClose={() => setActiveCategory(null)}
          onAdd={(model) => policyState.addModel(activeCategory, model)}
          onRemove={(model) => policyState.removeModel(activeCategory, model)}
          onSetDefault={(model) =>
            policyState.setDefault(activeCategory, model)
          }
          onSave={() => void save(activeCategory)}
        />
      )}
    </Card>
  );
}
