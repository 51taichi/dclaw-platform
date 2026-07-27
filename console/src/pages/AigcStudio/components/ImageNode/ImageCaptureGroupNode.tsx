import { useState } from "react";
import { Download, Image, ImagePlus, Maximize2 } from "lucide-react";

import styles from "../../index.module.less";
import { downloadAssetSource } from "../assetDownload";
import type { ImageCaptureGroupNodeProps } from "./types";

type CaptureFrame = {
  id?: unknown;
  label?: unknown;
  assetName?: unknown;
  assetPreviewUrl?: unknown;
  yaw?: unknown;
  pitch?: unknown;
  zoom?: unknown;
  position?: unknown;
  fov?: unknown;
};

const captureFrames = (frames: unknown): CaptureFrame[] =>
  Array.isArray(frames) ? (frames as CaptureFrame[]) : [];

const numberValue = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const zoomLabel = (value: number) =>
  Number.isInteger(value)
    ? String(value)
    : value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");

const captureFramePose = (frame: CaptureFrame) => {
  const yaw = numberValue(frame.yaw);
  const pitch = numberValue(frame.pitch);
  const zoom = numberValue(frame.zoom);
  if (yaw !== null && pitch !== null && zoom !== null) {
    return `横 ${yaw}° · 纵 ${pitch}° · 缩放 ${zoomLabel(zoom)}x`;
  }
  const fov = numberValue(frame.fov);
  const position = Array.isArray(frame.position)
    ? frame.position.map(numberValue)
    : [];
  if (fov === null || position.length !== 3 || position.includes(null)) {
    return null;
  }
  return `FOV ${zoomLabel(fov)}° · X ${zoomLabel(position[0]!)} · Y ${zoomLabel(
    position[1]!,
  )} · Z ${zoomLabel(position[2]!)}`;
};

const selectCaptureLabel = (
  t: ImageCaptureGroupNodeProps["t"],
  label: string,
) =>
  String(
    t("aigcStudio.imageNode.selectCapture", "选择{{label}}", { label }),
  ).replace("{{label}}", label);

export function ImageCaptureGroupNode({
  node,
  t,
  workflow,
}: ImageCaptureGroupNodeProps) {
  const [downloadReady, setDownloadReady] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const frames = captureFrames(node.data.captureFrames);
  const selectedCaptureId = String(
    node.data.selectedCaptureId ?? frames[0]?.id ?? "",
  );
  const captureCount = Number(node.data.captureCount ?? frames.length);
  const compact = captureCount <= 4;
  const title = String(
    node.data.title ?? t("aigcStudio.imageNode.captureGroup", "全景截图组"),
  );
  const handleDownload = async () => {
    const manifest = {
      title,
      captureMode: node.data.captureMode ?? "",
      captureCount,
      sourceImageNodeId: node.data.sourceImageNodeId ?? "",
      sourceImageOutputPath: node.data.sourceImageOutputPath ?? "",
      frames,
    };
    try {
      if (
        typeof document !== "undefined" &&
        typeof Blob !== "undefined" &&
        typeof URL !== "undefined" &&
        typeof URL.createObjectURL === "function"
      ) {
        const blob = new Blob([JSON.stringify(manifest, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        await downloadAssetSource({
          source: url,
          label: `${title}.json`,
          warnLabel: "capture group",
          cleanup: () => URL.revokeObjectURL(url),
        });
      }
    } finally {
      setDownloadReady(true);
    }
  };

  return (
    <>
      <div className={styles.uploadedAssetLabel}>
        <span>
          <Image size={15} />
          {title}
        </span>
      </div>
      <div
        className={styles.imageCaptureGroup}
        data-testid="aigc-image-capture-group"
        data-capture-count={String(captureCount)}
        data-capture-expanded={expanded ? "true" : "false"}
      >
        <div className={styles.imageCaptureGroupHeader}>
          <div className={styles.imageCaptureGroupTitle}>
            <strong>{title}</strong>
            <span>
              {t("aigcStudio.imageNode.captureCount", "{{count}}张", {
                count: captureCount,
              })}
            </span>
            {downloadReady && (
              <span className={styles.imageCaptureDownloadStatus}>
                {t("aigcStudio.imageNode.captureDownloadReady", "已准备下载")}
              </span>
            )}
          </div>
          <div
            className={styles.imageCaptureGroupTools}
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              aria-label={t(
                "aigcStudio.imageNode.downloadCaptureGroup",
                "下载截图组",
              )}
              onClick={() => void handleDownload()}
            >
              <Download size={14} />
            </button>
            <button
              type="button"
              aria-label={t(
                "aigcStudio.imageNode.sendCaptureGroupToImage",
                "发送到图片节点",
              )}
              onClick={() => workflow.handleImageCaptureGroupSendToImage(node)}
            >
              <ImagePlus size={14} />
            </button>
            <button
              type="button"
              aria-label={t(
                "aigcStudio.imageNode.fullscreenCaptureGroup",
                "全屏查看截图组",
              )}
              onClick={() => setExpanded(true)}
            >
              <Maximize2 size={14} />
            </button>
          </div>
        </div>
        <div
          className={`${styles.imageCaptureGrid} ${
            compact ? styles.imageCaptureGridCompact : ""
          }`}
        >
          {frames.map((frame, index) => {
            const pose = captureFramePose(frame);
            const frameId = String(frame.id ?? index);
            const frameLabel = String(frame.label ?? "");
            const selected = frameId === selectedCaptureId;
            return (
              <figure key={frameId}>
                <button
                  type="button"
                  className={styles.imageCaptureFrameButton}
                  aria-label={selectCaptureLabel(t, frameLabel)}
                  aria-pressed={selected}
                  onClick={(event) => {
                    event.stopPropagation();
                    workflow.handleImageCaptureGroupSelect(node, frameId);
                  }}
                >
                  {String(frame.assetPreviewUrl ?? "") ? (
                    <img src={String(frame.assetPreviewUrl)} alt={frameLabel} />
                  ) : (
                    <div className={styles.imageCapturePlaceholder}>
                      <Image size={22} />
                    </div>
                  )}
                </button>
                <figcaption>
                  <span>{frameLabel}</span>
                  {pose ? <small>{pose}</small> : null}
                </figcaption>
              </figure>
            );
          })}
        </div>
        {expanded && (
          <div className={styles.imageCaptureFullscreen}>
            <div className={styles.imageCaptureFullscreenHeader}>
              <strong>
                {t("aigcStudio.imageNode.capturePreview", "截图组预览")}
              </strong>
              <button
                type="button"
                aria-label={t(
                  "aigcStudio.imageNode.closeCapturePreview",
                  "关闭截图组预览",
                )}
                onClick={(event) => {
                  event.stopPropagation();
                  setExpanded(false);
                }}
              >
                ×
              </button>
            </div>
            <div className={styles.imageCaptureFullscreenGrid}>
              {frames.map((frame, index) => {
                const pose = captureFramePose(frame);
                const frameId = String(frame.id ?? index);
                const frameLabel = String(frame.label ?? "");
                return (
                  <figure key={frameId}>
                    <button
                      type="button"
                      className={styles.imageCaptureFrameButton}
                      aria-label={selectCaptureLabel(t, frameLabel)}
                      aria-pressed={frameId === selectedCaptureId}
                      onClick={(event) => {
                        event.stopPropagation();
                        workflow.handleImageCaptureGroupSelect(node, frameId);
                      }}
                    >
                      {String(frame.assetPreviewUrl ?? "") ? (
                        <img
                          src={String(frame.assetPreviewUrl)}
                          alt={frameLabel}
                        />
                      ) : (
                        <div className={styles.imageCapturePlaceholder}>
                          <Image size={22} />
                        </div>
                      )}
                    </button>
                    <figcaption>
                      <span>{frameLabel}</span>
                      {pose ? <small>{pose}</small> : null}
                    </figcaption>
                  </figure>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
