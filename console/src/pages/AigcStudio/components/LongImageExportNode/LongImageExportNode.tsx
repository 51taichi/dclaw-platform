import { Download, FileText, Image, Loader2, Newspaper } from "lucide-react";

import type {
  AigcAsset,
  AigcCanvas,
  AigcCanvasNode,
} from "../../../../api/modules/aigcStudio";
import { nodeOutputs } from "../../canvasNodeUtils";
import styles from "../../index.module.less";
import { downloadAssetSource } from "../assetDownload";
import { AuthenticatedAssetImage } from "../AuthenticatedAssetImage";
import type { Translate } from "../TextNode/types";
import {
  collectLongImageSections,
  type LongImageSection,
} from "./longImageExport";

type LongImageExportNodeProps = {
  node: AigcCanvasNode;
  canvas: AigcCanvas;
  selected: boolean;
  exporting: boolean;
  t: Translate;
  onExport: (node: AigcCanvasNode) => void;
};

const numberValue = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const outputUrl = (asset: AigcAsset | undefined) =>
  String(asset?.url ?? asset?.path ?? "");

const outputLabel = (asset: AigcAsset | undefined, fallback: string) =>
  String(asset?.name ?? asset?.path ?? fallback);

function SectionPreview({ section }: { section: LongImageSection }) {
  if (section.kind === "image") {
    return (
      <div className={styles.longImageSectionPreview}>
        <Image size={14} />
        <span>{section.title}</span>
      </div>
    );
  }
  return (
    <div className={styles.longImageSectionPreview}>
      <FileText size={14} />
      <span>{section.text}</span>
    </div>
  );
}

export function LongImageExportNode({
  node,
  canvas,
  selected,
  exporting,
  t,
  onExport,
}: LongImageExportNodeProps) {
  const sections = collectLongImageSections(canvas, node);
  const outputs = nodeOutputs(node);
  const fullAsset = outputs[0];
  const sliceAssets = outputs.slice(1);
  const fullUrl = outputUrl(fullAsset);
  const sliceHeight = numberValue(node.data.sliceHeight) ?? 1400;
  const disabled = exporting || sections.length === 0;
  const handleDownloadAsset = async (
    asset: AigcAsset | undefined,
    fallback: string,
  ) => {
    await downloadAssetSource({
      source: outputUrl(asset),
      label: outputLabel(asset, fallback),
      warnLabel: "long image asset",
    });
  };

  return (
    <section className={styles.longImageExportNode}>
      <div className={styles.nodeLabel}>
        <span>
          <Newspaper size={16} />
          {String(
            node.data.title ??
              t("aigcStudio.longImageExport.title", "公众号长图"),
          )}
        </span>
        <span className={styles.nodeTypeBadge}>
          {t("aigcStudio.nodeType.long_image_export", "长图导出")}
        </span>
      </div>

      <div className={styles.longImageExportStats}>
        <span>
          {t("aigcStudio.longImageExport.sections", "{{count}} 个内容块", {
            count: sections.length,
          })}
        </span>
        <span>
          {t("aigcStudio.longImageExport.sliceHeight", "切片 {{height}}px", {
            height: sliceHeight,
          })}
        </span>
        <span>
          {t("aigcStudio.longImageExport.workflowOnly", "本地排版导出")}
        </span>
      </div>

      <div className={styles.longImageSectionList}>
        {sections.slice(0, 4).map((section) => (
          <SectionPreview key={section.id} section={section} />
        ))}
        {sections.length === 0 && (
          <p className={styles.nodeText}>
            {t(
              "aigcStudio.longImageExport.empty",
              "从左右加号连接文本和图片，内容会按连线顺序排成长图。",
            )}
          </p>
        )}
      </div>

      {sections.length > 0 && (
        <p className={styles.longImageHint}>
          {t(
            "aigcStudio.longImageExport.readyHint",
            "点击导出后生成完整长图，并按切片高度输出小图。",
          )}
        </p>
      )}

      {fullUrl && (
        <div className={styles.longImageResultPreview}>
          <AuthenticatedAssetImage
            src={fullUrl}
            alt={String(fullAsset?.name ?? "")}
          />
          <span>
            {t("aigcStudio.longImageExport.ready", "{{count}} 张切片已生成", {
              count: sliceAssets.length,
            })}
          </span>
          <div className={styles.longImageDownloadActions}>
            <button
              type="button"
              aria-label={t(
                "aigcStudio.longImageExport.downloadFull",
                "下载完整长图",
              )}
              onClick={(event) => {
                event.stopPropagation();
                void handleDownloadAsset(fullAsset, "long-image-full.png");
              }}
            >
              <Download size={14} />
              {t("aigcStudio.longImageExport.downloadFullShort", "完整长图")}
            </button>
            {sliceAssets.map((asset, index) => (
              <button
                type="button"
                key={String(asset.id ?? index)}
                aria-label={t(
                  "aigcStudio.longImageExport.downloadSlice",
                  "下载切片 {{index}}",
                  { index: index + 1 },
                )}
                onClick={(event) => {
                  event.stopPropagation();
                  void handleDownloadAsset(
                    asset,
                    `long-image-slice-${String(index + 1).padStart(2, "0")}.png`,
                  );
                }}
              >
                <Download size={14} />
                {t("aigcStudio.longImageExport.sliceShort", "切片 {{index}}", {
                  index: index + 1,
                })}
              </button>
            ))}
          </div>
        </div>
      )}

      {selected && (
        <button
          type="button"
          className={styles.longImageExportButton}
          disabled={disabled}
          aria-label={t("aigcStudio.longImageExport.export", "导出公众号长图")}
          onClick={(event) => {
            event.stopPropagation();
            onExport(node);
          }}
        >
          {exporting ? <Loader2 size={16} /> : <Download size={16} />}
          {exporting
            ? t("aigcStudio.longImageExport.exporting", "导出中")
            : t("aigcStudio.longImageExport.export", "导出公众号长图")}
        </button>
      )}
    </section>
  );
}
