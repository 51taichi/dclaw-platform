import { useEffect, useMemo, useState } from "react";
import { SaveOutlined, StopOutlined } from "@ant-design/icons";
import { Button, Card, Select } from "@agentscope-ai/design";

import api from "../../../../../api";
import type { ActiveModelsInfo, ProviderInfo } from "../../../../../api/types";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../../hooks/useAppMessage";
import styles from "../../index.module.less";

interface EmbeddingModelsSectionProps {
  providers: ProviderInfo[];
  activeModels: ActiveModelsInfo | null;
  onSaved: () => void;
}

export function EmbeddingModelsSection({
  providers,
  activeModels,
  onSaved,
}: EmbeddingModelsSectionProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [saving, setSaving] = useState(false);
  const [selectedProviderId, setSelectedProviderId] = useState<
    string | undefined
  >();
  const [selectedModel, setSelectedModel] = useState<string | undefined>();
  const currentSlot = activeModels?.active_embedding;

  const eligible = useMemo(
    () =>
      providers.filter((provider) => {
        if (provider.disabled) return false;
        const models = [
          ...(provider.models ?? []),
          ...(provider.extra_models ?? []),
        ];
        if (!models.some((model) => model.model_type === "embedding")) {
          return false;
        }
        if (provider.require_api_key === false)
          return Boolean(provider.base_url);
        if (provider.is_custom) return Boolean(provider.base_url);
        return Boolean(provider.api_key && provider.base_url);
      }),
    [providers],
  );

  useEffect(() => {
    setSelectedProviderId(currentSlot?.provider_id || undefined);
    setSelectedModel(currentSlot?.model || undefined);
  }, [currentSlot]);

  const selectedProvider = providers.find(
    (provider) => provider.id === selectedProviderId,
  );
  const modelOptions = [
    ...(selectedProvider?.models ?? []),
    ...(selectedProvider?.extra_models ?? []),
  ].filter((model) => model.model_type === "embedding");

  const handleSave = async () => {
    if (!selectedProviderId || !selectedModel) return;
    setSaving(true);
    try {
      await api.setActiveEmbedding({
        provider_id: selectedProviderId,
        model: selectedModel,
      });
      message.success(t("models.embeddingModelUpdated"));
      onSaved();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("models.failedToSave"),
      );
    } finally {
      setSaving(false);
    }
  };

  const handleDisable = async () => {
    setSaving(true);
    try {
      await api.clearActiveEmbedding();
      setSelectedProviderId(undefined);
      setSelectedModel(undefined);
      message.success(t("models.embeddingDisabled"));
      onSaved();
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : t("models.failedToSave"),
      );
    } finally {
      setSaving(false);
    }
  };

  const isActive =
    currentSlot?.provider_id === selectedProviderId &&
    currentSlot?.model === selectedModel;

  return (
    <Card className={styles.slotSection} title={t("models.defaultEmbedding")}>
      <div className={styles.slotForm}>
        <div className={styles.slotField}>
          <label className={styles.slotLabel}>{t("models.provider")}</label>
          <Select
            style={{ width: "100%" }}
            placeholder={t("models.selectEmbeddingProvider")}
            value={selectedProviderId}
            onChange={(providerId) => {
              setSelectedProviderId(providerId);
              setSelectedModel(undefined);
            }}
            options={eligible.map((provider) => ({
              value: provider.id,
              label: provider.name,
            }))}
          />
        </div>

        <div className={styles.slotField}>
          <label className={styles.slotLabel}>{t("models.model")}</label>
          <Select
            style={{ width: "100%" }}
            placeholder={t("models.selectEmbeddingModel")}
            disabled={!selectedProviderId || modelOptions.length === 0}
            showSearch
            optionFilterProp="label"
            value={selectedModel}
            onChange={(modelId) => {
              const selected = modelOptions.find(
                (model) => model.id === modelId,
              );
              if (selected?.billing_eligible !== false) {
                setSelectedModel(modelId);
              }
            }}
            options={modelOptions.map((model) => ({
              value: model.id,
              label: `${model.name} (${model.id})${
                model.billing_eligible === false
                  ? ` · ${t("models.unpriced")}`
                  : ""
              }`,
              disabled: model.billing_eligible === false,
            }))}
          />
        </div>

        <div className={[styles.slotField, styles.slotActionField].join(" ")}>
          <label
            className={[styles.slotLabel, styles.visuallyHiddenLabel].join(" ")}
          >
            {t("models.actions")}
          </label>
          <div style={{ display: "flex", gap: 8 }}>
            <Button
              type="primary"
              loading={saving}
              disabled={!selectedProviderId || !selectedModel}
              onClick={handleSave}
              block
              icon={<SaveOutlined />}
            >
              {isActive ? t("models.saved") : t("models.testAndEnable")}
            </Button>
            {currentSlot && (
              <Button
                disabled={saving}
                onClick={handleDisable}
                icon={<StopOutlined />}
              >
                {t("models.disableEmbedding")}
              </Button>
            )}
          </div>
        </div>
      </div>
      <p className={styles.slotDescription}>
        {t("models.embeddingDescription")}
      </p>
    </Card>
  );
}
