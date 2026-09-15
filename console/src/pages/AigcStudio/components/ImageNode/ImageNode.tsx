import {
  useEffect,
  useState,
  type CSSProperties,
  type SyntheticEvent,
} from "react";
import { createPortal } from "react-dom";
import {
  AlertCircle,
  Brush,
  Camera,
  Download,
  Grid2X2,
  Grid3X3,
  Image,
  ImagePlus,
  Loader2,
  Maximize2,
  Upload,
} from "lucide-react";

import styles from "../../index.module.less";
import {
  assetPreviewSource,
  nodeOutputs,
  nodePrimaryOutput,
} from "../../canvasNodeUtils";
import {
  AuthenticatedAssetImage,
  shouldFetchAuthenticatedAsset,
} from "../AuthenticatedAssetImage";
import {
  downloadAssetSource,
  reusableRenderedAssetDownloadSource,
} from "../assetDownload";
import { imageNodeStateFromNode, isPanoramaImageNode } from "./imageNodeState";
import type { ImageNodeProps } from "./types";

type GeneratedImageOutput = {
  id?: unknown;
  name?: unknown;
  path?: unknown;
  url?: unknown;
  width?: unknown;
  height?: unknown;
  meta?: Record<string, unknown>;
};

const numberValue = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const generatedImageSizeLabel = (output: GeneratedImageOutput | undefined) => {
  const width = numberValue(output?.width);
  const height = numberValue(output?.height);
  if (width && height) return `${width} × ${height}`;
  return "";
};

const generatedOutputId = (output: GeneratedImageOutput, index: number) =>
  String(output.id ?? `output-${index + 1}`);

const generatedOutputLabel = (
  output: GeneratedImageOutput | undefined,
  fallback: string,
) => String(output?.name ?? output?.path ?? fallback);

const generatedOutputUrl = (output: GeneratedImageOutput | undefined) =>
  output ? assetPreviewSource(output) ?? "" : "";

const partialImageBatchFromOutputs = (outputs: GeneratedImageOutput[]) => {
  const meta = outputs.find(
    (output) => numberValue(output.meta?.partial_failure_count) !== null,
  )?.meta;
  const failed = numberValue(meta?.partial_failure_count);
  const requested =
    numberValue(meta?.image_count) ??
    numberValue(outputs[0]?.meta?.image_count);
  if (!failed || !requested || requested <= outputs.length) return null;
  const errors = Array.isArray(meta?.partial_failure_errors)
    ? meta.partial_failure_errors
        .map((item) => {
          if (!item || typeof item !== "object") return "";
          const error = item as Record<string, unknown>;
          const index = numberValue(error.image_index);
          const message = String(error.message ?? "").trim();
          return message ? `${index ? `第 ${index} 张：` : ""}${message}` : "";
        })
        .filter(Boolean)
        .join("\n")
    : "";
  return { requested, failed, errors };
};

const generatedOutputDownloadUrl = (
  output: GeneratedImageOutput | undefined,
) => {
  const source = generatedOutputUrl(output);
  const assetId = String(output?.id ?? "").trim();
  if (
    !source ||
    !assetId ||
    /^(blob:|data:)/i.test(source) ||
    shouldFetchAuthenticatedAsset(source)
  ) {
    return source;
  }
  return `/api/user/aigc-studio/assets/${encodeURIComponent(assetId)}/file`;
};

const hasChineseText = (value: string) => /[\u4e00-\u9fa5]/.test(value);

const friendlyImageErrorMessage = (raw: unknown, fallback: string) => {
  const detail = String(raw ?? "").trim();
  if (!detail) return { summary: fallback, detail: "" };
  const normalized = detail.toLowerCase();
  const rules: Array<{ test: RegExp; summary: string }> = [
    {
      test: /no aigc adapter|adapter.*configured|not configured|provider.*not.*configured/,
      summary: "当前模型还没有可用生成通道，请切换模型或联系管理员检查配置。",
    },
    {
      test: /401|unauthori[sz]ed|authentication|invalid api key|api key|鉴权|密钥/,
      summary: "模型服务鉴权失败，请检查后台模型密钥配置。",
    },
    {
      test: /403|forbidden|permission|access denied/,
      summary: "当前账号或模型服务没有生成权限，请切换模型或检查服务权限。",
    },
    {
      test: /429|too many requests|rate limit|quota|insufficient|balance|余额|额度/,
      summary: "当前模型服务请求过多或额度不足，请稍后再试，或切换其他模型。",
    },
    {
      test: /451|legal[_ ]error/,
      summary:
        "提示词被模型服务的内容审核拒绝，请调整可能引发误判的文案后重试。",
    },
    {
      test: /safety policy|content policy|filtered|moderation|安全策略|安全审核|内容审核/,
      summary: "生成内容未通过模型安全策略，请调整提示词或参考图后重试。",
    },
    {
      test: /timeout|timed out|network|fetch failed|connection|econn/,
      summary: "模型服务连接超时，请检查网络后重试。",
    },
    {
      test: /5\d\d|bad gateway|service unavailable|gateway|internal server/,
      summary: "模型服务暂时不可用，请稍后重试或切换模型。",
    },
    {
      test: /400|bad request|invalid|validation|parameter|payload/,
      summary:
        "请求参数没有通过模型服务校验，请检查提示词、比例或参考图后重试。",
    },
  ];
  const matched = rules.find((rule) => rule.test.test(normalized));
  if (matched) return { summary: matched.summary, detail };
  if (hasChineseText(detail) && detail.length <= 64) {
    return { summary: detail, detail: "" };
  }
  return {
    summary: "图片生成服务返回异常，请稍后重试或切换模型。",
    detail,
  };
};

export function ImageNode({ node, selected, t, workflow }: ImageNodeProps) {
  const [previewDialogOpen, setPreviewDialogOpen] = useState(false);
  const [naturalImageSize, setNaturalImageSize] = useState<{
    source: string;
    width: number;
    height: number;
  } | null>(null);
  const [renderedImageDownloadUrl, setRenderedImageDownloadUrl] = useState<{
    source: string;
    href: string;
  } | null>(null);
  const imageState = imageNodeStateFromNode(node);
  const isPanorama = isPanoramaImageNode(node);
  const progress = Number(node.data.imageProgress ?? 2);
  const safeProgress = Math.min(
    98,
    Math.max(2, Number.isFinite(progress) ? progress : 2),
  );
  const outputs = nodeOutputs(node) as GeneratedImageOutput[];
  const primaryOutput = nodePrimaryOutput(node) as
    | GeneratedImageOutput
    | undefined;
  const outputEntries = outputs.map((output, index) => ({
    id: generatedOutputId(output, index),
    index,
    output,
  }));
  const primaryEntry =
    outputEntries.find((entry) => entry.output === primaryOutput) ??
    outputEntries[0];
  const secondaryEntries = outputEntries.filter(
    (entry) => entry.id !== primaryEntry?.id,
  );
  const partialImageBatch = partialImageBatchFromOutputs(outputs);
  const multiOutput = outputs.length > 1;
  const resultsExpanded =
    multiOutput && node.data.imageResultsExpanded === true;
  const resultFrameStyle = multiOutput
    ? ({
        "--aigc-image-result-count": outputs.length,
        "--aigc-image-side-count": Math.max(1, outputs.length - 1),
        "--aigc-image-side-columns": outputs.length <= 2 ? 1 : 2,
      } as CSSProperties)
    : undefined;
  const generatedFallbackLabel = t(
    "aigcStudio.imageNode.generated",
    "生成结果",
  );
  const generatedLabel = generatedOutputLabel(
    primaryOutput,
    generatedFallbackLabel,
  );
  const generatedImageUrl = generatedOutputUrl(primaryOutput);
  const explicitSizeLabel = generatedImageSizeLabel(primaryOutput);
  const naturalSizeLabel =
    naturalImageSize?.source === generatedImageUrl
      ? `${naturalImageSize.width} × ${naturalImageSize.height}`
      : "";
  const generatedSizeLabel =
    explicitSizeLabel ||
    naturalSizeLabel ||
    (isPanorama ? "2048 × 1024" : "1024 × 1024");
  const failedError = friendlyImageErrorMessage(
    node.data.job_error ?? node.data.error,
    t("aigcStudio.imageNode.failedHint", "请调整输入后重试。"),
  );

  useEffect(() => {
    setNaturalImageSize(null);
    setRenderedImageDownloadUrl(null);
  }, [generatedImageUrl]);

  const handleGeneratedImageLoad =
    (source: string) => (event: SyntheticEvent<HTMLImageElement>) => {
      const renderedSource =
        event.currentTarget.currentSrc || event.currentTarget.src || "";
      const reusableSource = reusableRenderedAssetDownloadSource(
        source,
        renderedSource,
      );
      if (source && reusableSource) {
        setRenderedImageDownloadUrl({
          source,
          href: reusableSource,
        });
      }

      const { naturalWidth, naturalHeight } = event.currentTarget;
      if (!source || !naturalWidth || !naturalHeight) return;
      setNaturalImageSize({
        source,
        width: naturalWidth,
        height: naturalHeight,
      });
    };
  const handleDownloadOutput = async (output = primaryOutput) => {
    const source = generatedOutputDownloadUrl(output);
    const previewSource = generatedOutputUrl(output);
    const label = generatedOutputLabel(output, generatedFallbackLabel);
    const reusableSource =
      renderedImageDownloadUrl?.source === previewSource
        ? renderedImageDownloadUrl.href
        : "";
    await downloadAssetSource({
      source,
      label,
      reusableHref: reusableSource,
      warnLabel: "generated image",
    });
  };
  const imagePreviewDialog =
    previewDialogOpen && typeof document !== "undefined"
      ? createPortal(
          <div
            className={styles.imageResultFullscreen}
            data-aigc-floating-panel
            data-testid="aigc-image-result-preview"
            role="dialog"
            aria-modal="true"
            aria-label={t("aigcStudio.imageNode.imagePreview", "图片预览")}
            onClick={(event) => event.stopPropagation()}
            onMouseDown={(event) => event.stopPropagation()}
            onPointerDown={(event) => event.stopPropagation()}
          >
            <section className={styles.imageResultFullscreenPanel}>
              <div className={styles.imageResultFullscreenHeader}>
                <strong>
                  {t("aigcStudio.imageNode.imagePreview", "图片预览")}
                </strong>
                <button
                  type="button"
                  aria-label={t(
                    "aigcStudio.imageNode.closeImagePreview",
                    "关闭图片预览",
                  )}
                  onClick={(event) => {
                    event.stopPropagation();
                    setPreviewDialogOpen(false);
                  }}
                >
                  ×
                </button>
              </div>
              <div className={styles.imageResultFullscreenBody}>
                <div
                  className={styles.imageResultFullscreenViewport}
                  data-testid="aigc-image-result-preview-viewport"
                >
                  {generatedImageUrl ? (
                    <AuthenticatedAssetImage
                      className={styles.imageResultFullscreenImage}
                      src={generatedImageUrl}
                      alt={generatedLabel}
                      onLoad={handleGeneratedImageLoad(generatedImageUrl)}
                    />
                  ) : (
                    <Image size={42} />
                  )}
                </div>
              </div>
            </section>
          </div>,
          document.body,
        )
      : null;

  return (
    <>
      <div className={styles.imageNodeLabel}>
        <span className={styles.imageNodeTitle}>
          <Image size={15} />
          {String(
            node.data.title ?? t("aigcStudio.imageNode.title", "图片节点"),
          )}
        </span>
        {imageState === "generated" && (
          <span
            className={styles.imageNodeMeta}
            data-testid="aigc-image-node-meta"
          >
            {generatedSizeLabel}
          </span>
        )}
      </div>
      {imageState === "generated" && selected && (
        <div
          className={styles.imageViewerToolbar}
          data-aigc-floating-panel
          data-testid="aigc-image-viewer-toolbar"
          data-image-panorama={isPanorama ? "true" : "false"}
          data-toolbar-placement="node-above"
          onClick={(event) => event.stopPropagation()}
          onMouseDown={(event) => event.stopPropagation()}
          onPointerDown={(event) => event.stopPropagation()}
        >
          {isPanorama && (
            <span className={styles.imageViewerPanoramaBadge}>720</span>
          )}
          {isPanorama && (
            <>
              <button
                type="button"
                aria-label={t(
                  "aigcStudio.imageNode.currentViewCapture",
                  "当前视角截图",
                )}
                onClick={() =>
                  workflow.handleImageCaptureGroup(node, "current")
                }
              >
                <Camera size={15} />
              </button>
              <button
                type="button"
                aria-label={t(
                  "aigcStudio.imageNode.fourViewCapture",
                  "4大视角截图",
                )}
                onClick={() => workflow.handleImageCaptureGroup(node, "four")}
              >
                <Grid2X2 size={15} />
              </button>
              <button
                type="button"
                aria-label={t(
                  "aigcStudio.imageNode.twelveViewCapture",
                  "12大视角截图",
                )}
                onClick={() => workflow.handleImageCaptureGroup(node, "twelve")}
              >
                <Grid3X3 size={15} />
              </button>
              <span className={styles.imageViewerDivider} />
            </>
          )}
          <button
            type="button"
            aria-label={t(
              "aigcStudio.imageNode.sendGeneratedImageToImage",
              "发送到图片节点",
            )}
            onClick={() => workflow.handleGeneratedImageSendToImage(node)}
          >
            <ImagePlus size={15} />
          </button>
          <button
            type="button"
            aria-label={t("aigcStudio.imageNode.annotate", "标注")}
            onClick={() => workflow.handleGeneratedImageAnnotate(node)}
          >
            <Brush size={15} />
          </button>
          {multiOutput && (
            <button
              type="button"
              className={styles.imageViewerCountButton}
              aria-label={
                resultsExpanded
                  ? t("aigcStudio.imageNode.collapseResults", "收起图片结果")
                  : `展开 ${outputs.length} 张图片`
              }
              onClick={(event) => {
                event.stopPropagation();
                workflow.handleGeneratedImageToggleResults(
                  node,
                  !resultsExpanded,
                );
              }}
            >
              <Grid2X2 size={14} />
              <span>
                {resultsExpanded
                  ? t("aigcStudio.imageNode.collapse", "收起")
                  : t("aigcStudio.imageNode.countValue", "{{count}}张", {
                      count: outputs.length,
                    })}
              </span>
            </button>
          )}
          <button
            type="button"
            aria-label={t("aigcStudio.imageNode.download", "下载结果")}
            onClick={() => void handleDownloadOutput(primaryOutput)}
          >
            <Download size={15} />
          </button>
          <button
            type="button"
            aria-label={t("aigcStudio.imageNode.fullscreen", "全屏查看")}
            onClick={() => setPreviewDialogOpen(true)}
          >
            <Maximize2 size={15} />
          </button>
        </div>
      )}
      {imageState !== "generating" &&
        imageState !== "generated" &&
        node.data.imageMode !== "upscale" &&
        !(
          node.data.imageMode === "image_to_image" &&
          node.data.referenceThumb === true
        ) && (
          <label
            className={styles.imageUploadButton}
            onClick={(event) => event.stopPropagation()}
          >
            <Upload size={14} />
            {t("aigcStudio.imageNode.upload", "上传参考图")}
            <input
              type="file"
              accept="image/*"
              aria-label={t(
                "aigcStudio.imageNode.uploadLabel",
                "上传图片参考素材",
              )}
              onChange={(event) => {
                void workflow.handleImageUpload(node, event.target.files?.[0]);
                event.target.value = "";
              }}
            />
          </label>
        )}
      <div
        className={`${styles.imageEditorSurface} ${
          node.data.previewKind === "uploaded" ? styles.imageEditorUploaded : ""
        } ${imageState === "generating" ? styles.imageEditorGenerating : ""} ${
          imageState === "generated" ? styles.imageEditorGenerated : ""
        } ${imageState === "failed" ? styles.imageEditorFailed : ""}`}
        data-image-expanded={
          previewDialogOpen || resultsExpanded ? "true" : "false"
        }
        data-image-state={imageState}
        data-testid={selected ? "aigc-image-editor" : undefined}
      >
        {imageState === "generating" ? (
          <div className={styles.imageGeneratingState}>
            <span className={styles.imageGeneratingHalo}>
              <Loader2 size={18} />
            </span>
            <div className={styles.imageGeneratingCopy}>
              <strong>
                {t(
                  "aigcStudio.imageNode.generating",
                  "生成中 {{progress}}%...",
                  {
                    progress: safeProgress,
                  },
                )}
              </strong>
              <span
                aria-valuemax={98}
                aria-valuemin={2}
                aria-valuenow={safeProgress}
                className={styles.imageGeneratingTrack}
                role="progressbar"
              >
                <span style={{ width: `${safeProgress}%` }} />
              </span>
            </div>
            <button
              type="button"
              aria-label={t(
                "aigcStudio.imageNode.cancelGeneration",
                "取消生成",
              )}
            >
              {t("aigcStudio.cancelJob", "取消")}
            </button>
          </div>
        ) : imageState === "generated" ? (
          <div
            className={styles.generatedImageFrame}
            data-expanded={resultsExpanded ? "true" : "false"}
            data-multi-output={multiOutput ? "true" : "false"}
            style={resultFrameStyle}
          >
            <div
              className={styles.generatedImagePreview}
              data-testid="aigc-image-primary-preview"
            >
              {multiOutput && !resultsExpanded && (
                <div
                  className={styles.generatedImageStack}
                  data-testid="aigc-image-result-stack"
                  aria-hidden="true"
                >
                  {secondaryEntries.slice(0, 3).map((entry) => {
                    const outputUrl = generatedOutputUrl(entry.output);
                    const outputLabel = generatedOutputLabel(
                      entry.output,
                      generatedFallbackLabel,
                    );
                    return (
                      <span
                        className={styles.generatedImageStackCard}
                        key={entry.id}
                      >
                        {outputUrl ? (
                          <AuthenticatedAssetImage
                            src={outputUrl}
                            alt=""
                            title={outputLabel}
                          />
                        ) : null}
                      </span>
                    );
                  })}
                </div>
              )}
              {generatedImageUrl ? (
                <AuthenticatedAssetImage
                  src={generatedImageUrl}
                  alt={generatedLabel}
                  onLoad={handleGeneratedImageLoad(generatedImageUrl)}
                />
              ) : (
                <Image size={42} />
              )}
              {partialImageBatch ? (
                <div
                  className={styles.generatedImagePartialNotice}
                  data-testid="aigc-image-partial-notice"
                  title={partialImageBatch.errors || undefined}
                >
                  <AlertCircle size={14} />
                  {t(
                    "aigcStudio.imageNode.partialSuccess",
                    "已生成 {{succeeded}}/{{requested}} 张",
                    {
                      succeeded: outputs.length,
                      requested: partialImageBatch.requested,
                    },
                  )}
                </div>
              ) : null}
              {resultsExpanded ? (
                <div className={styles.generatedImagePrimaryActions}>
                  <button
                    type="button"
                    aria-label={`${t(
                      "aigcStudio.imageNode.download",
                      "下载结果",
                    )} ${generatedLabel}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      void handleDownloadOutput(primaryOutput);
                    }}
                  >
                    <Download size={14} />
                    {t("aigcStudio.imageNode.downloadShort", "下载")}
                  </button>
                  <button
                    type="button"
                    aria-label={t(
                      "aigcStudio.imageNode.collapseResults",
                      "收起图片结果",
                    )}
                    onClick={(event) => {
                      event.stopPropagation();
                      workflow.handleGeneratedImageToggleResults(node, false);
                    }}
                  >
                    {t("aigcStudio.imageNode.collapse", "收起")}
                  </button>
                </div>
              ) : (
                multiOutput && (
                  <button
                    type="button"
                    className={styles.generatedImageCountButton}
                    aria-label={`展开 ${outputs.length} 张图片`}
                    onClick={(event) => {
                      event.stopPropagation();
                      workflow.handleGeneratedImageToggleResults(node, true);
                    }}
                  >
                    {t("aigcStudio.imageNode.countValue", "{{count}}张", {
                      count: outputs.length,
                    })}
                  </button>
                )
              )}
            </div>
            {resultsExpanded && (
              <div
                className={styles.generatedImageSideGallery}
                data-testid="aigc-image-result-side-gallery"
              >
                {secondaryEntries.map((entry) => {
                  const outputLabel = generatedOutputLabel(
                    entry.output,
                    generatedFallbackLabel,
                  );
                  const outputUrl = generatedOutputUrl(entry.output);
                  return (
                    <figure
                      className={styles.generatedImageSideItem}
                      key={entry.id}
                    >
                      <div className={styles.generatedImageSidePreview}>
                        {outputUrl ? (
                          <AuthenticatedAssetImage
                            src={outputUrl}
                            alt={outputLabel}
                            onLoad={handleGeneratedImageLoad(outputUrl)}
                          />
                        ) : (
                          <Image size={42} />
                        )}
                      </div>
                      <figcaption>
                        <button
                          type="button"
                          aria-label={`${t(
                            "aigcStudio.imageNode.download",
                            "下载结果",
                          )} ${outputLabel}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            void handleDownloadOutput(entry.output);
                          }}
                        >
                          <Download size={14} />
                          {t("aigcStudio.imageNode.downloadShort", "下载")}
                        </button>
                        <button
                          type="button"
                          aria-label={`${t(
                            "aigcStudio.imageNode.setPrimary",
                            "设为主图",
                          )} ${outputLabel}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            workflow.handleGeneratedImageSetPrimary(
                              node,
                              entry.id,
                            );
                          }}
                        >
                          {t("aigcStudio.imageNode.setPrimary", "设为主图")}
                        </button>
                      </figcaption>
                    </figure>
                  );
                })}
              </div>
            )}
          </div>
        ) : imageState === "failed" ? (
          <div className={styles.imageFailedState}>
            <AlertCircle size={28} />
            <strong>{t("aigcStudio.imageNode.failed", "生成失败")}</strong>
            <span className={styles.imageFailedSummary}>
              {failedError.summary}
            </span>
            {failedError.detail ? (
              <details className={styles.imageErrorDetails}>
                <summary>
                  {t("aigcStudio.imageNode.rawError", "查看原始错误")}
                </summary>
                <code>{failedError.detail}</code>
              </details>
            ) : null}
          </div>
        ) : node.data.previewKind === "uploaded" ? (
          <div className={styles.uploadedImagePreview}>
            <Image size={42} />
            <span>{String(node.data.assetName ?? "")}</span>
          </div>
        ) : (
          <Image size={58} className={styles.imageEmptyIcon} />
        )}
        {imageState !== "generating" && node.data.imageMode === "upscale" ? (
          <div className={styles.imageSurfaceText}>
            {t(
              "aigcStudio.imageNode.upscale.placeholder",
              "配置参数生成高清图像",
            )}
          </div>
        ) : null}
        {imageState === "empty" && node.data.showTryOptions === true && (
          <div className={styles.imageTryList}>
            <div className={styles.textTryTitle}>
              {t("aigcStudio.textNode.tryTitle", "尝试：")}
            </div>
            <label
              className={styles.textTryButton}
              onClick={(event) => event.stopPropagation()}
            >
              <Upload size={15} />
              {t("aigcStudio.imageNode.try.imageToImage", "图生图")}
              <input
                type="file"
                accept="image/*"
                aria-label={t(
                  "aigcStudio.imageNode.try.imageToImageUploadLabel",
                  "上传图生图参考图",
                )}
                onChange={(event) => {
                  void workflow.handleImageToImageUpload(
                    node,
                    event.target.files?.[0],
                  );
                  event.target.value = "";
                }}
              />
            </label>
            <label
              className={styles.textTryButton}
              onClick={(event) => event.stopPropagation()}
            >
              <span className={styles.hdIcon}>HD</span>
              {t("aigcStudio.imageNode.try.upscale", "图片高清")}
              <input
                type="file"
                accept="image/*"
                aria-label={t(
                  "aigcStudio.imageNode.try.upscaleUploadLabel",
                  "上传高清放大原图",
                )}
                onChange={(event) => {
                  void workflow.handleImageUpscaleUpload(
                    node,
                    event.target.files?.[0],
                  );
                  event.target.value = "";
                }}
              />
            </label>
          </div>
        )}
      </div>
      {imagePreviewDialog}
    </>
  );
}
