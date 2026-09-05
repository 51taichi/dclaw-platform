import { DeleteOutlined, StarFilled, StarOutlined } from "@ant-design/icons";
import { Button, Drawer, Select, Tag } from "antd";
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
  open: boolean;
  category: AigcModelCategory;
  draft: AigcCategoryDraft;
  inventory: AigcInventoryItem[];
  dirty: boolean;
  saving: boolean;
  onClose: () => void;
  onAdd: (model: AigcModelRef) => void;
  onRemove: (model: AigcModelRef) => void;
  onSetDefault: (model: AigcModelRef) => void;
  onSave: () => void;
}

export function AigcModelManagerDrawer({
  open,
  category,
  draft,
  inventory,
  dirty,
  saving,
  onClose,
  onAdd,
  onRemove,
  onSetDefault,
  onSave,
}: Props) {
  const { t } = useTranslation();
  const selectedKeys = new Set(draft.models.map(refKey));
  const inventoryByKey = new Map(
    inventory.map((model) => [refKey(model), model]),
  );
  const options = inventory.map((model) => ({
    value: refKey(model),
    label: `${model.model_name} · ${model.provider_name}${
      model.reasons.length
        ? ` · ${model.reasons
            .map((reason) => t(`models.aigc.reasons.${reason}`))
            .join(", ")}`
        : ""
    }`,
    disabled: !model.selectable || selectedKeys.has(refKey(model)),
  }));

  return (
    <Drawer
      title={t(`models.aigc.${category}Title`)}
      open={open}
      width={640}
      onClose={onClose}
      destroyOnClose
      footer={
        <div className={styles.aigcDrawerFooter}>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            type="primary"
            loading={saving}
            disabled={!dirty || draft.models.length === 0}
            onClick={onSave}
          >
            {t("models.aigc.save")}
          </Button>
        </div>
      }
    >
      <p className={styles.aigcDrawerDescription}>
        {t("models.aigc.drawerDescription")}
      </p>
      <Select
        aria-label={t("models.aigc.addModel")}
        className={styles.aigcModelSelect}
        placeholder={t("models.aigc.addModel")}
        showSearch
        virtual
        optionFilterProp="label"
        options={options}
        value={undefined}
        onChange={(key) => {
          if (!key) return;
          const model = inventoryByKey.get(key);
          if (model?.selectable) onAdd(model);
        }}
      />

      <div className={styles.aigcDrawerList}>
        {draft.models.map((ref) => {
          const model = inventoryByKey.get(refKey(ref));
          const isDefault = Boolean(
            draft.defaultModel && refKey(draft.defaultModel) === refKey(ref),
          );
          return (
            <div className={styles.aigcDrawerItem} key={refKey(ref)}>
              <div className={styles.aigcDrawerItemIdentity}>
                <strong>{model?.model_name ?? ref.model_id}</strong>
                <span>{model?.provider_name ?? ref.provider_id}</span>
                {model?.reasons.map((reason) => (
                  <Tag key={reason}>{t(`models.aigc.reasons.${reason}`)}</Tag>
                ))}
              </div>
              <div className={styles.aigcDrawerActions}>
                <Button
                  type={isDefault ? "primary" : "default"}
                  icon={isDefault ? <StarFilled /> : <StarOutlined />}
                  disabled={!model?.selectable}
                  onClick={() => onSetDefault(ref)}
                >
                  {isDefault
                    ? t("models.aigc.default")
                    : t("models.aigc.setDefault")}
                </Button>
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => onRemove(ref)}
                >
                  {t("models.aigc.remove")}
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </Drawer>
  );
}
