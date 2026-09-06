import { SettingOutlined } from "@ant-design/icons";
import { Button, Card, Tag } from "antd";
import { useTranslation } from "react-i18next";

import type {
  AigcInventoryItem,
  AigcModelCategory,
  AigcModelRef,
} from "@/api/modules/aigcModelPolicy";
import type { AigcCategoryDraft } from "../../hooks/useAigcModelPolicy";
import styles from "../../index.module.less";

const refKey = (model: AigcModelRef) =>
  `${model.provider_id}\u0000${model.model_id}`;

interface Props {
  category: AigcModelCategory;
  draft: AigcCategoryDraft;
  inventory: AigcInventoryItem[];
  configured: boolean;
  dirty: boolean;
  onManage: () => void;
}

export function AigcModelCategoryCard({
  category,
  draft,
  inventory,
  configured,
  dirty,
  onManage,
}: Props) {
  const { t } = useTranslation();
  const inventoryByKey = new Map(
    inventory.map((model) => [refKey(model), model]),
  );

  return (
    <section className={styles.aigcCategorySection}>
      <Card className={styles.aigcCategoryCard}>
        <div className={styles.aigcCategoryHeader}>
          <div>
            <div className={styles.aigcCategoryTitle}>
              {t(`models.aigc.${category}Title`)}
              {!configured && <Tag>{t("models.aigc.legacy")}</Tag>}
              {dirty && <span className={styles.aigcDirtyMark}>•</span>}
            </div>
          </div>
          <Button icon={<SettingOutlined />} onClick={onManage}>
            {t("models.aigc.manage")}
          </Button>
        </div>

        <div className={styles.aigcModelSummary}>
          {draft.models.length === 0 ? (
            <span className={styles.aigcEmpty}>{t("models.aigc.empty")}</span>
          ) : (
            draft.models.slice(0, 3).map((ref) => {
              const model = inventoryByKey.get(refKey(ref));
              const isDefault = Boolean(
                draft.defaultModel &&
                  refKey(draft.defaultModel) === refKey(ref),
              );
              return (
                <div
                  className={styles.aigcSummaryItem}
                  data-testid="selected-model"
                  key={refKey(ref)}
                >
                  <span className={styles.aigcSummaryName}>
                    {model?.model_name ?? ref.model_id}
                  </span>
                  <span className={styles.aigcSummaryProvider}>
                    {model?.provider_name ?? ref.provider_id}
                  </span>
                  {isDefault && (
                    <Tag color="blue">{t("models.aigc.default")}</Tag>
                  )}
                </div>
              );
            })
          )}
        </div>

        <div className={styles.aigcCategoryFooter}>
          <span>
            {t("models.aigc.selectedCount", { count: draft.models.length })}
          </span>
          {draft.models.length > 3 && (
            <Button type="link" onClick={onManage}>
              {t("models.aigc.viewAll", { count: draft.models.length })}
            </Button>
          )}
        </div>
      </Card>
    </section>
  );
}
