import { useRef, useState, type MouseEvent } from "react";
import {
  AlertCircle,
  Captions,
  Camera,
  Crop,
  Download,
  FileText,
  Film,
  Layers,
  Loader2,
  Maximize2,
  Pause,
  Play,
  Scissors,
  Sparkles,
  Upload,
  Wand2,
  Volume2,
  VolumeX,
} from "lucide-react";

import styles from "../../index.module.less";
import {
  AuthenticatedAssetVideo,
  shouldFetchAuthenticatedAsset,
} from "../AuthenticatedAssetImage";
import { downloadAssetSource } from "../assetDownload";
import type { VideoNodeProps } from "./types";
import { videoNodeStateFromNode } from "./videoNodeState";

type GeneratedVideoOutput = {
  id?: unknown;
  name?: unknown;
  path?: unknown;
  url?: unknown;
  width?: unknown;
  height?: unknown;
  kind?: unknown;
};

const numberValue = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const stringValue = (value: unknown) =>
  typeof value === "string" ? value.trim() : "";

const generatedVideoSizeLabel = (
  output: GeneratedVideoOutput | undefined,
  playbackSize: { width: number; height: number } | null,
  aspectRatio: string,
  resolution: string,
) => {
  if (playbackSize) return `${playbackSize.width} × ${playbackSize.height}`;
  const width = numberValue(output?.width);
  const height = numberValue(output?.height);
  if (width && height) return `${width} × ${height}`;
  if (aspectRatio === "16:9" && resolution === "1080P") return "1920 × 1080";
  if (aspectRatio === "16:9" && resolution === "720P") return "1280 × 720";
  if (aspectRatio === "9:16" && resolution === "720P") return "720 × 1280";
  if (aspectRatio === "1:1" && resolution === "720P") return "720 × 720";
  return `${aspectRatio} · ${resolution}`;
};

const INLINE_DOWNLOAD_SOURCE_RE = /^(blob:|data:)/i;

const assetApiFileSource = (output: GeneratedVideoOutput | undefined) => {
  const assetId = stringValue(output?.id);
  return assetId
    ? `/api/user/aigc-studio/assets/${encodeURIComponent(assetId)}/file`
    : "";
};

const downloadableVideoSource = (
  output: GeneratedVideoOutput | undefined,
  previewSource: string,
) => {
  if (!previewSource) return "";
  if (
    INLINE_DOWNLOAD_SOURCE_RE.test(previewSource) ||
    shouldFetchAuthenticatedAsset(previewSource)
  ) {
    return previewSource;
  }
  return assetApiFileSource(output) || previewSource;
};

const formatVideoTime = (value: number | null) => {
  const safeValue = Math.max(0, Math.floor(value ?? 0));
  const minutes = Math.floor(safeValue / 60);
  const seconds = String(safeValue % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
};

export function VideoNode({ node, selected, t, workflow }: VideoNodeProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [playbackTime, setPlaybackTime] = useState(0);
  const [playbackDuration, setPlaybackDuration] = useState<number | null>(null);
  const [playbackSize, setPlaybackSize] = useState<{
    width: number;
    height: number;
  } | null>(null);
  const [playbackPlaying, setPlaybackPlaying] = useState(false);
  const videoState = videoNodeStateFromNode(node);
  const progress = Number(node.data.videoProgress ?? node.data.progress ?? 1);
  const safeProgress = Math.min(
    98,
    Math.max(1, Number.isFinite(progress) ? progress : 1),
  );
  const outputs = Array.isArray(node.data.outputs) ? node.data.outputs : [];
  const firstOutput = outputs.find(
    (output): output is GeneratedVideoOutput =>
      Boolean(output) &&
      typeof output === "object" &&
      String((output as GeneratedVideoOutput).kind ?? "video") === "video",
  ) as GeneratedVideoOutput | undefined;
  const generatedLabel = String(
    firstOutput?.name ??
      firstOutput?.path ??
      t("aigcStudio.videoNode.generated", "生成视频"),
  );
  const generatedVideoUrl = String(firstOutput?.url ?? firstOutput?.path ?? "");
  const generatedVideoDownloadUrl = downloadableVideoSource(
    firstOutput,
    generatedVideoUrl,
  );
  const uploadedVideoUrl = String(node.data.videoPreviewUrl ?? "");
  const uploadedVideoName = String(
    node.data.videoAssetName ??
      node.data.assetName ??
      t("aigcStudio.videoNode.uploadedVideo", "上传视频"),
  );
  const aspectRatio = String(node.data.aspectRatio ?? "16:9");
  const resolution = String(node.data.videoResolution ?? "720P");
  const configuredDuration = numberValue(node.data.videoDuration) ?? 5;
  const videoParameterLabel = `${aspectRatio} · ${resolution} · ${configuredDuration}s`;
  const effectivePlaybackDuration = Math.max(
    1,
    playbackDuration ?? configuredDuration,
  );
  const playbackProgress = Math.min(
    100,
    Math.max(0, (playbackTime / effectivePlaybackDuration) * 100),
  );
  const generatedSizeLabel = generatedVideoSizeLabel(
    firstOutput,
    playbackSize,
    aspectRatio,
    resolution,
  );
  const handleDownload = async (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    await downloadAssetSource({
      source: generatedVideoDownloadUrl,
      label: generatedLabel,
      warnLabel: "generated video",
      loadingMessage: t("aigcStudio.videoNode.downloading", "正在下载视频..."),
      successMessage: t(
        "aigcStudio.videoNode.downloadStarted",
        "视频已开始下载",
      ),
      errorMessage: t("aigcStudio.videoNode.downloadFailed", "视频下载失败"),
      fetchHttp: true,
    });
  };
  const handleTogglePlayback = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    const video = videoRef.current;
    if (!video) {
      setPlaybackPlaying((playing) => !playing);
      return;
    }
    try {
      if (playbackPlaying || !video.paused) {
        video.pause();
        setPlaybackPlaying(false);
        return;
      }
      const playResult = video.play();
      setPlaybackPlaying(true);
      if (playResult && typeof playResult.catch === "function") {
        playResult.catch(() => setPlaybackPlaying(false));
      }
    } catch {
      setPlaybackPlaying((playing) => !playing);
    }
  };
  const handleCaptureFrame = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
  };
  const generatedVideoToolbar =
    videoState === "generated" && selected ? (
      <div
        className={styles.videoViewerToolbar}
        data-aigc-floating-panel
        data-testid="aigc-video-viewer-toolbar"
        data-toolbar-placement="node-above"
        onClick={(event) => event.stopPropagation()}
        onMouseDown={(event) => event.stopPropagation()}
        onPointerDown={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          aria-label={t("aigcStudio.videoNode.edit", "剪辑")}
          onClick={() => workflow.handleGeneratedVideoAction(node, "edit")}
        >
          <Scissors size={15} />
          <span>{t("aigcStudio.videoNode.edit", "剪辑")}</span>
        </button>
        <button
          type="button"
          aria-label={t("aigcStudio.videoNode.crop", "裁剪")}
          onClick={() => workflow.handleGeneratedVideoAction(node, "crop")}
        >
          <Crop size={15} />
          <span>{t("aigcStudio.videoNode.crop", "裁剪")}</span>
        </button>
        <button
          type="button"
          aria-label={t("aigcStudio.videoNode.upscale", "高清")}
          onClick={() => workflow.handleGeneratedVideoAction(node, "upscale")}
        >
          <Sparkles size={15} />
          <span>{t("aigcStudio.videoNode.upscale", "高清")}</span>
        </button>
        <button
          type="button"
          aria-label={t("aigcStudio.videoNode.analyze", "解析")}
          onClick={() => workflow.handleGeneratedVideoAction(node, "analyze")}
        >
          <FileText size={15} />
          <span>{t("aigcStudio.videoNode.analyze", "解析")}</span>
        </button>
        <button
          type="button"
          aria-label={t("aigcStudio.videoNode.removeSubtitles", "智能去字幕")}
          onClick={() =>
            workflow.handleGeneratedVideoAction(node, "remove_subtitles")
          }
        >
          <Captions size={15} />
          <span>{t("aigcStudio.videoNode.removeSubtitles", "智能去字幕")}</span>
        </button>
        <button
          type="button"
          aria-label={t("aigcStudio.videoNode.extractAudio", "音频分离")}
          onClick={() =>
            workflow.handleGeneratedVideoAction(node, "extract_audio")
          }
        >
          <VolumeX size={15} />
          <span>{t("aigcStudio.videoNode.extractAudio", "音频分离")}</span>
        </button>
        <span className={styles.imageViewerDivider} />
        <button
          type="button"
          aria-label={t("aigcStudio.videoNode.download", "下载视频")}
          onClick={(event) => void handleDownload(event)}
        >
          <Download size={15} />
        </button>
        <button
          type="button"
          aria-label={t("aigcStudio.videoNode.fullscreen", "全屏查看视频")}
          onClick={() => setExpanded(true)}
        >
          <Maximize2 size={15} />
        </button>
      </div>
    ) : null;

  return (
    <>
      <div className={styles.videoNodeLabel}>
        <span>
          <Film size={15} />
          {String(
            node.data.title ?? t("aigcStudio.videoNode.title", "视频节点"),
          )}
        </span>
      </div>
      {generatedVideoToolbar}
      {videoState !== "generating" && videoState !== "generated" && (
        <label
          className={styles.imageUploadButton}
          onClick={(event) => event.stopPropagation()}
        >
          <Upload size={14} />
          {t("aigcStudio.videoNode.upload", "上传")}
          <input
            type="file"
            accept="video/*"
            aria-label={t("aigcStudio.videoNode.uploadLabel", "上传视频素材")}
            onChange={(event) =>
              workflow.handleVideoUpload(node, event.target.files?.[0])
            }
          />
        </label>
      )}
      <div
        className={`${styles.videoEditorSurface} ${
          node.data.previewKind === "uploaded_video"
            ? styles.videoEditorUploaded
            : ""
        } ${videoState === "generating" ? styles.videoEditorGenerating : ""} ${
          videoState === "generated" ? styles.videoEditorGenerated : ""
        } ${videoState === "failed" ? styles.videoEditorFailed : ""}`}
        data-video-expanded={expanded ? "true" : "false"}
        data-video-state={videoState}
        data-video-aspect-ratio={aspectRatio}
        data-testid={selected ? "aigc-video-editor" : undefined}
      >
        {videoState === "generating" ? (
          <div className={styles.videoGeneratingState}>
            <span className={styles.videoGeneratingHalo}>
              <Loader2 size={18} />
            </span>
            <div className={styles.videoGeneratingCopy}>
              <strong>
                {t(
                  "aigcStudio.videoNode.generating",
                  "生成中 {{progress}}%...",
                  {
                    progress: safeProgress,
                  },
                )}
              </strong>
              <span
                aria-valuemax={98}
                aria-valuemin={1}
                aria-valuenow={safeProgress}
                className={styles.videoGeneratingTrack}
                role="progressbar"
              >
                <span style={{ width: `${safeProgress}%` }} />
              </span>
            </div>
            <button
              type="button"
              aria-label={t(
                "aigcStudio.videoNode.cancelGeneration",
                "取消生成",
              )}
              onClick={(event) => {
                event.stopPropagation();
                workflow.handleVideoCancelGeneration(node);
              }}
            >
              {t("aigcStudio.cancelJob", "取消")}
            </button>
          </div>
        ) : videoState === "generated" ? (
          <div
            className={styles.generatedVideoFrame}
            data-platform-control-id="aigc.video.result-preview"
          >
            <span className={styles.generatedVideoSize}>
              {generatedSizeLabel}
            </span>
            <div className={styles.generatedVideoPreview}>
              {generatedVideoUrl ? (
                <AuthenticatedAssetVideo
                  ref={videoRef}
                  src={generatedVideoUrl}
                  data-testid="aigc-video-result-preview"
                  playsInline
                  style={{ objectFit: "contain" }}
                  onLoadedMetadata={(event) => {
                    const duration = numberValue(event.currentTarget.duration);
                    if (duration && duration > 0) {
                      setPlaybackDuration(duration);
                    }
                    const width = numberValue(event.currentTarget.videoWidth);
                    const height = numberValue(event.currentTarget.videoHeight);
                    if (width && height) setPlaybackSize({ width, height });
                  }}
                  onTimeUpdate={(event) =>
                    setPlaybackTime(event.currentTarget.currentTime)
                  }
                  onPlay={() => setPlaybackPlaying(true)}
                  onPause={() => setPlaybackPlaying(false)}
                  onEnded={() => setPlaybackPlaying(false)}
                />
              ) : (
                <Play size={58} className={styles.videoEmptyIcon} />
              )}
            </div>
            {generatedVideoUrl && (
              <div
                className={styles.generatedVideoControls}
                data-testid="aigc-video-playback-controls"
                onClick={(event) => event.stopPropagation()}
              >
                <button
                  type="button"
                  aria-label={t(
                    playbackPlaying
                      ? "aigcStudio.videoNode.pauseVideo"
                      : "aigcStudio.videoNode.playVideo",
                    playbackPlaying ? "暂停视频" : "播放视频",
                  )}
                  aria-pressed={playbackPlaying}
                  onClick={handleTogglePlayback}
                >
                  {playbackPlaying ? <Pause size={14} /> : <Play size={14} />}
                </button>
                <span>{formatVideoTime(playbackTime)}</span>
                <div
                  className={styles.generatedVideoProgress}
                  role="progressbar"
                  aria-label={t(
                    "aigcStudio.videoNode.playbackProgress",
                    "视频播放进度",
                  )}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(playbackProgress)}
                >
                  <span style={{ width: `${playbackProgress}%` }} />
                </div>
                <span>{formatVideoTime(effectivePlaybackDuration)}</span>
                <button
                  type="button"
                  aria-label={t("aigcStudio.videoNode.videoVolume", "视频音量")}
                  onClick={(event) => event.stopPropagation()}
                >
                  <Volume2 size={14} />
                </button>
                <button
                  type="button"
                  aria-label={t(
                    "aigcStudio.videoNode.captureFrame",
                    "当前画面截图",
                  )}
                  onClick={handleCaptureFrame}
                >
                  <Camera size={14} />
                </button>
              </div>
            )}
            {expanded && (
              <div
                className={styles.videoResultFullscreen}
                data-testid="aigc-video-result-fullscreen"
              >
                <div className={styles.imageResultFullscreenHeader}>
                  <strong>
                    {t("aigcStudio.videoNode.videoPreview", "视频预览")}
                  </strong>
                  <button
                    type="button"
                    aria-label={t(
                      "aigcStudio.videoNode.closeVideoPreview",
                      "关闭视频预览",
                    )}
                    onClick={(event) => {
                      event.stopPropagation();
                      setExpanded(false);
                    }}
                  >
                    ×
                  </button>
                </div>
                <div className={styles.videoResultFullscreenBody}>
                  {generatedVideoUrl ? (
                    <AuthenticatedAssetVideo src={generatedVideoUrl} controls />
                  ) : (
                    <Play size={58} className={styles.videoEmptyIcon} />
                  )}
                </div>
              </div>
            )}
          </div>
        ) : videoState === "failed" ? (
          <div className={styles.imageFailedState}>
            <AlertCircle size={28} />
            <strong>{t("aigcStudio.videoNode.failed", "生成失败")}</strong>
            <span>
              {String(
                node.data.job_error ??
                  node.data.error ??
                  t("aigcStudio.videoNode.failedHint", "请调整输入后重试。"),
              )}
            </span>
            <button
              type="button"
              aria-label={t("aigcStudio.videoNode.retryGeneration", "重试生成")}
              onClick={(event) => {
                event.stopPropagation();
                workflow.handleVideoRetryGeneration(node);
              }}
            >
              {t("aigcStudio.retryJob", "重试")}
            </button>
          </div>
        ) : node.data.previewKind === "uploaded_video" ? (
          <div className={styles.uploadedVideoFrame}>
            <AuthenticatedAssetVideo
              ref={videoRef}
              src={uploadedVideoUrl}
              data-testid="aigc-video-preview"
              muted
              playsInline
              onLoadedMetadata={(event) => {
                const duration = numberValue(event.currentTarget.duration);
                if (duration && duration > 0) {
                  setPlaybackDuration(duration);
                }
              }}
              onTimeUpdate={(event) =>
                setPlaybackTime(event.currentTarget.currentTime)
              }
              onPlay={() => setPlaybackPlaying(true)}
              onPause={() => setPlaybackPlaying(false)}
              onEnded={() => setPlaybackPlaying(false)}
            />
            <div className={styles.uploadedVideoMeta}>
              <strong>{uploadedVideoName}</strong>
              <span>{videoParameterLabel}</span>
            </div>
            {uploadedVideoUrl && (
              <div
                className={`${styles.generatedVideoControls} ${styles.uploadedVideoControls}`}
                data-testid="aigc-uploaded-video-controls"
                onClick={(event) => event.stopPropagation()}
              >
                <button
                  type="button"
                  aria-label={t(
                    playbackPlaying
                      ? "aigcStudio.videoNode.pauseUploadedVideo"
                      : "aigcStudio.videoNode.playUploadedVideo",
                    playbackPlaying ? "暂停上传视频" : "播放上传视频",
                  )}
                  aria-pressed={playbackPlaying}
                  onClick={handleTogglePlayback}
                >
                  {playbackPlaying ? <Pause size={14} /> : <Play size={14} />}
                </button>
                <span>{formatVideoTime(playbackTime)}</span>
                <div
                  className={styles.generatedVideoProgress}
                  role="progressbar"
                  aria-label={t(
                    "aigcStudio.videoNode.uploadedPlaybackProgress",
                    "上传视频播放进度",
                  )}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={Math.round(playbackProgress)}
                >
                  <span style={{ width: `${playbackProgress}%` }} />
                </div>
                <span>{formatVideoTime(effectivePlaybackDuration)}</span>
                <button
                  type="button"
                  aria-label={t("aigcStudio.videoNode.videoVolume", "视频音量")}
                  onClick={(event) => event.stopPropagation()}
                >
                  <Volume2 size={14} />
                </button>
                <button
                  type="button"
                  aria-label={t(
                    "aigcStudio.videoNode.captureFrame",
                    "当前画面截图",
                  )}
                  onClick={handleCaptureFrame}
                >
                  <Camera size={14} />
                </button>
              </div>
            )}
            <div
              className={styles.videoToolStrip}
              data-testid="aigc-video-tool-strip"
            >
              <button
                type="button"
                onClick={() =>
                  workflow.handleGeneratedVideoAction(node, "edit")
                }
              >
                <Scissors size={14} />
                剪辑
              </button>
              <button
                type="button"
                onClick={() =>
                  workflow.handleGeneratedVideoAction(node, "crop")
                }
              >
                <Crop size={14} />
                裁剪
              </button>
              <button
                type="button"
                onClick={() =>
                  workflow.handleGeneratedVideoAction(node, "remove_subtitles")
                }
              >
                <Wand2 size={14} />
                智能去字幕
              </button>
              <button
                type="button"
                onClick={() =>
                  workflow.handleGeneratedVideoAction(node, "extract_audio")
                }
              >
                <VolumeX size={14} />
                音频分离
              </button>
            </div>
          </div>
        ) : (
          <Play size={64} className={styles.videoEmptyIcon} />
        )}
        {videoState !== "generating" &&
          videoState !== "generated" &&
          node.data.showTryOptions === true &&
          node.data.previewKind !== "uploaded_video" && (
            <div className={styles.videoTryList}>
              <div className={styles.textTryTitle}>
                {t("aigcStudio.textNode.tryTitle", "尝试：")}
              </div>
              <label
                className={styles.textTryButton}
                onClick={(event) => event.stopPropagation()}
              >
                <Layers size={15} />
                {t("aigcStudio.videoNode.try.firstLast", "首尾帧生成视频")}
                <input
                  type="file"
                  accept="image/*"
                  multiple
                  aria-label={t(
                    "aigcStudio.videoNode.try.firstLastUploadLabel",
                    "上传首尾帧图片",
                  )}
                  onChange={(event) =>
                    workflow.handleVideoTryUpload(
                      node,
                      "first_last_frames",
                      event.target.files,
                    )
                  }
                />
              </label>
              <label
                className={styles.textTryButton}
                onClick={(event) => event.stopPropagation()}
              >
                <Sparkles size={15} />
                {t("aigcStudio.videoNode.try.firstFrame", "首帧生成视频")}
                <input
                  type="file"
                  accept="image/*"
                  aria-label={t(
                    "aigcStudio.videoNode.try.firstFrameUploadLabel",
                    "上传首帧图片",
                  )}
                  onChange={(event) =>
                    workflow.handleVideoTryUpload(
                      node,
                      "first_frame",
                      event.target.files,
                    )
                  }
                />
              </label>
            </div>
          )}
      </div>
    </>
  );
}
