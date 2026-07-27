import type { useTranslation } from "react-i18next";

import {
  JOB_STATUS_FALLBACKS,
  type CanvasAssetRecord,
} from "../../canvasNodeUtils";
import {
  TEMPLATE_CARDS,
  nodeIcon,
  type TemplateVariant,
} from "../../domain/componentRegistry";
import styles from "../../index.module.less";
import { AuthenticatedAssetImage } from "../AuthenticatedAssetImage";
import type { RailPanel } from "./CanvasRail";

type HistoryRecord = {
  id: string;
  title: string;
  kind: string;
  jobStatus: string;
};

type CanvasRailPanelProps = {
  railPanel: Exclude<RailPanel, null>;
  assetRecords: CanvasAssetRecord[];
  subjectRecords: CanvasAssetRecord[];
  historyRecords: HistoryRecord[];
  t: ReturnType<typeof useTranslation>["t"];
  onTemplate: (variant: TemplateVariant) => void;
  onUseAssetRecord: (record: CanvasAssetRecord) => void;
};

function AssetRecordButton({
  record,
  onUseAssetRecord,
}: {
  record: CanvasAssetRecord;
  onUseAssetRecord: (record: CanvasAssetRecord) => void;
}) {
  return (
    <button
      type="button"
      className={styles.assetRecord}
      onClick={() => onUseAssetRecord(record)}
    >
      <span className={styles.assetRecordPreview}>
        {record.assetPreviewUrl ? (
          <AuthenticatedAssetImage
            src={record.assetPreviewUrl}
            alt={record.title}
          />
        ) : (
          nodeIcon(record.nodeType)
        )}
      </span>
      <span>
        <strong>{record.title}</strong>
        <small>{record.kind}</small>
      </span>
    </button>
  );
}

export function CanvasRailPanel({
  railPanel,
  assetRecords,
  subjectRecords,
  historyRecords,
  t,
  onTemplate,
  onUseAssetRecord,
}: CanvasRailPanelProps) {
  return (
    <div
      className={`${styles.railPanel} ${
        railPanel === "assets" ? styles.railPanelAssets : ""
      }`}
      data-testid="aigc-rail-panel"
      data-panel-size={railPanel === "assets" ? "large" : "compact"}
      onClick={(event) => event.stopPropagation()}
    >
      {railPanel === "workflows" && (
        <>
          <div className={styles.railPanelHeader}>
            <strong>{t("aigcStudio.rail.workflows", "我的工具箱")}</strong>
            <small>
              {t("aigcStudio.rail.workflowsHint", "把常用组合发送到当前画布")}
            </small>
          </div>
          <div className={styles.railPanelList}>
            {TEMPLATE_CARDS.map((template) => (
              <button
                type="button"
                key={template.variant}
                className={styles.railPanelCard}
                onClick={() => onTemplate(template.variant)}
              >
                <span>{template.icon}</span>
                <strong>{t(template.titleKey, template.titleFallback)}</strong>
                <small>{t("aigcStudio.rail.sendToCanvas", "发送到画布")}</small>
              </button>
            ))}
          </div>
        </>
      )}

      {railPanel === "assets" && (
        <>
          <div className={styles.railPanelHeader}>
            <strong>{t("aigcStudio.rail.assets", "我的资产")}</strong>
            <small>
              {t("aigcStudio.rail.assetsHint", "右键节点可保存素材或创建主体")}
            </small>
          </div>
          <div className={styles.railPanelSectionTitle}>
            {t("aigcStudio.rail.materials", "素材")}
          </div>
          <div className={styles.railPanelList}>
            {assetRecords.length === 0 ? (
              <div className={styles.railPanelEmpty}>
                {t("aigcStudio.rail.noAssets", "暂无素材")}
              </div>
            ) : (
              assetRecords.map((record) => (
                <AssetRecordButton
                  key={record.id}
                  record={record}
                  onUseAssetRecord={onUseAssetRecord}
                />
              ))
            )}
          </div>
          <div className={styles.railPanelSectionTitle}>
            {t("aigcStudio.rail.subjects", "主体库")}
          </div>
          <div className={styles.railPanelList}>
            {subjectRecords.length === 0 ? (
              <div className={styles.railPanelEmpty}>
                {t("aigcStudio.rail.noSubjects", "暂无主体")}
              </div>
            ) : (
              subjectRecords.map((record) => (
                <AssetRecordButton
                  key={record.id}
                  record={record}
                  onUseAssetRecord={onUseAssetRecord}
                />
              ))
            )}
          </div>
        </>
      )}

      {railPanel === "history" && (
        <>
          <div className={styles.railPanelHeader}>
            <strong>{t("aigcStudio.rail.history", "历史记录")}</strong>
            <small>
              {t("aigcStudio.rail.historyHint", "当前项目的生成结果")}
            </small>
          </div>
          <div className={styles.railPanelList}>
            {historyRecords.length === 0 ? (
              <div className={styles.railPanelEmpty}>
                {t("aigcStudio.rail.noHistory", "暂无生成历史")}
              </div>
            ) : (
              historyRecords.map((record) => (
                <div key={record.id} className={styles.historyRecord}>
                  <strong>{record.title}</strong>
                  <small>
                    {record.kind} ·{" "}
                    {t(
                      `aigcStudio.jobStatus.${record.jobStatus}`,
                      JOB_STATUS_FALLBACKS[record.jobStatus] ??
                        record.jobStatus,
                    )}
                  </small>
                </div>
              ))
            )}
          </div>
        </>
      )}

      {railPanel === "help" && (
        <>
          <div className={styles.railPanelHeader}>
            <strong>{t("aigcStudio.rail.help", "使用教程")}</strong>
            <small>
              {t("aigcStudio.rail.helpHint", "画布操作指南")}
            </small>
          </div>
          <div className={styles.helpList}>
            <span>
              {t("aigcStudio.rail.helpAdd", "双击空画布或点 + 添加节点")}
            </span>
            <span>
              {t(
                "aigcStudio.rail.helpConnect",
                "节点两侧 + 用于串联素材和生成节点",
              )}
            </span>
            <span>
              {t(
                "aigcStudio.rail.helpMenu",
                "右键节点可复制、副本、保存素材、删除",
              )}
            </span>
            <span>
              {t("aigcStudio.rail.helpSlash", "图片输入框输入 / 呼出快捷工具")}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
