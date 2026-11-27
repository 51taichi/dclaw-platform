import { message } from "antd";

import { buildAuthHeaders } from "../../../api/authHeaders";
import {
  absoluteAuthenticatedAssetFetchUrl,
  shouldFetchAuthenticatedAsset,
} from "./AuthenticatedAssetImage";
import { isDesktopApp } from "../../../utils/env";
import { saveDownloadedBlob } from "../../../utils/download";

const DOWNLOAD_CLEANUP_DELAY_MS = 1000;
let downloadToastSequence = 0;

export const safeDownloadFileName = (value: string) =>
  value.trim().replace(/[\\/:*?"<>|]+/g, "-") || "generated-asset";

export const reusableRenderedAssetDownloadSource = (
  source: string,
  renderedSource: string,
) => {
  const trimmed = renderedSource.trim();
  if (!trimmed) return "";
  if (shouldFetchAuthenticatedAsset(source)) {
    return /^blob:/i.test(trimmed) ? trimmed : "";
  }
  return /^(blob:|data:)/i.test(trimmed) ? trimmed : "";
};

const nextDownloadToastKey = () =>
  `aigc-asset-download-${Date.now()}-${downloadToastSequence++}`;

const isHttpAssetSource = (source: string) => {
  if (!source) return false;
  try {
    const url = new URL(
      source,
      typeof window === "undefined" ? "http://localhost" : window.location.href,
    );
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
};

const downloadFetchUrl = (source: string) =>
  shouldFetchAuthenticatedAsset(source)
    ? absoluteAuthenticatedAssetFetchUrl(source)
    : new URL(
        source,
        typeof window === "undefined"
          ? "http://localhost"
          : window.location.href,
      ).toString();

const downloadFetchOptions = (source: string) =>
  shouldFetchAuthenticatedAsset(source)
    ? {
        credentials: "include" as const,
        headers: buildAuthHeaders(),
      }
    : {
        credentials: "omit" as const,
      };

const clickDownloadLink = (
  href: string,
  filename: string,
  cleanup?: () => void,
) => {
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.rel = "noreferrer";
  anchor.dataset.aigcDownloadLink = "true";
  document.body.appendChild(anchor);
  anchor.click();
  window.setTimeout(() => {
    anchor.remove();
    cleanup?.();
  }, DOWNLOAD_CLEANUP_DELAY_MS);
};

export async function downloadAssetSource({
  source,
  label,
  reusableHref = "",
  warnLabel = "asset",
  loadingMessage = "正在下载图片...",
  successMessage = "图片已开始下载",
  errorMessage = "图片下载失败",
  fetchHttp = false,
  cleanup,
}: {
  source: string;
  label: string;
  reusableHref?: string;
  warnLabel?: string;
  loadingMessage?: string;
  successMessage?: string;
  errorMessage?: string;
  fetchHttp?: boolean;
  cleanup?: () => void;
}) {
  if (!source || typeof document === "undefined") return;
  let objectUrl = "";
  let cleanupScheduled = false;
  const toastKey = nextDownloadToastKey();
  message.loading({
    content: loadingMessage,
    duration: 0,
    key: toastKey,
  });
  try {
    if (isDesktopApp()) {
      const href = reusableHref || downloadFetchUrl(source);
      let saved = false;
      try {
        const response = await fetch(
          href,
          reusableHref ? undefined : downloadFetchOptions(source),
        );
        if (!response.ok) {
          throw new Error(`Asset download failed: ${response.status}`);
        }
        saved = await saveDownloadedBlob(
          await response.blob(),
          safeDownloadFileName(label),
        );
      } finally {
        cleanup?.();
      }
      if (!saved) {
        message.info({
          content: "已取消保存",
          duration: 2,
          key: toastKey,
        });
        return;
      }
    } else if (reusableHref) {
      clickDownloadLink(reusableHref, safeDownloadFileName(label), cleanup);
    } else if (
      shouldFetchAuthenticatedAsset(source) ||
      (fetchHttp && isHttpAssetSource(source))
    ) {
      const response = await fetch(
        downloadFetchUrl(source),
        downloadFetchOptions(source),
      );
      if (!response.ok) {
        throw new Error(`Asset download failed: ${response.status}`);
      }
      objectUrl = URL.createObjectURL(await response.blob());
      clickDownloadLink(objectUrl, safeDownloadFileName(label), () => {
        URL.revokeObjectURL(objectUrl);
      });
      cleanupScheduled = true;
    } else {
      clickDownloadLink(source, safeDownloadFileName(label), cleanup);
    }
    message.success({
      content: successMessage,
      duration: 2,
      key: toastKey,
    });
  } catch (error) {
    message.error({
      content: errorMessage,
      key: toastKey,
    });
    console.warn(`Failed to download ${warnLabel}:`, error);
  } finally {
    if (objectUrl && !cleanupScheduled) {
      URL.revokeObjectURL(objectUrl);
    }
  }
}
