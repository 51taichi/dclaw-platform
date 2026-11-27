import { useState, type ChangeEvent, type MouseEvent } from "react";
import {
  AudioLines,
  Download,
  Loader2,
  Play,
  Scissors,
  SlidersHorizontal,
} from "lucide-react";

import styles from "../../index.module.less";
import { downloadAssetSource } from "../assetDownload";
import { audioNodeStateFromNode } from "./audioNodeState";
import type { AudioNodeProps } from "./types";

type GeneratedAudioOutput = {
  kind?: unknown;
  name?: unknown;
  path?: unknown;
  url?: unknown;
};

type AudioTool = "trim" | "speed" | null;

const WAVEFORM_BARS = [24, 42, 34, 50, 28, 45, 58, 36, 26, 48, 40, 54, 32, 46];
const AUDIO_SPEED_OPTIONS = [0.5, 0.75, 1, 1.25, 1.5, 2];

const audioToolFromData = (value: unknown): AudioTool =>
  value === "trim" || value === "speed" ? value : null;

const numberValue = (value: unknown, fallback: number) =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;

const inputNumber = (value: string, fallback: number) => {
  const nextValue = Number(value);
  return Number.isFinite(nextValue) ? nextValue : fallback;
};

const clampAudioTime = (value: number, min: number, max: number) =>
  Math.min(Math.max(value, min), Math.max(min, max));

const formatAudioTime = (value: number) => {
  const safeValue = Math.max(0, Math.floor(value));
  const minutes = String(Math.floor(safeValue / 60)).padStart(2, "0");
  const seconds = String(safeValue % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
};

function AudioWaveform({ label }: { label: string }) {
  return (
    <div className={styles.audioWaveform} aria-label={label}>
      {WAVEFORM_BARS.map((height, index) => (
        <span key={`${height}-${index}`} style={{ height }} />
      ))}
    </div>
  );
}

export function AudioNode({ node, t, onUpdateNodeData }: AudioNodeProps) {
  const [downloadReady, setDownloadReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const audioState =
    node.data.previewKind === "audioWave"
      ? "generated"
      : audioNodeStateFromNode(node);
  const progress = Number(node.data.audioProgress ?? node.data.progress ?? 1);
  const outputs = Array.isArray(node.data.outputs) ? node.data.outputs : [];
  const firstOutput = outputs.find(
    (output): output is GeneratedAudioOutput =>
      Boolean(output) &&
      typeof output === "object" &&
      String((output as GeneratedAudioOutput).kind ?? "audio") === "audio",
  ) as GeneratedAudioOutput | undefined;
  const generatedLabel = String(
    firstOutput?.name ??
      firstOutput?.path ??
      node.data.assetName ??
      t("aigcStudio.audioNode.generated", "生成音频"),
  );
  const generatedAudioUrl = String(
    firstOutput?.url ?? firstOutput?.path ?? node.data.assetPreviewUrl ?? "",
  );
  const duration = numberValue(node.data.audioDuration, 3);
  const [activeTool, setActiveTool] = useState<AudioTool>(() =>
    audioToolFromData(node.data.audioActiveTool),
  );
  const [trimStart, setTrimStart] = useState(() =>
    numberValue(node.data.audioTrimStart, 0),
  );
  const [trimEnd, setTrimEnd] = useState(() =>
    numberValue(node.data.audioTrimEnd, duration),
  );
  const [selectedSpeed, setSelectedSpeed] = useState(() =>
    numberValue(node.data.audioSpeed, 1),
  );
  const durationLabel = `${formatAudioTime(duration)} / ${formatAudioTime(
    duration,
  )}`;

  const handleDownload = async (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    await downloadAssetSource({
      source: generatedAudioUrl,
      label: generatedLabel,
      warnLabel: "generated audio",
      loadingMessage: t("aigcStudio.audioNode.downloading", "正在下载音频..."),
      successMessage: t(
        "aigcStudio.audioNode.downloadStarted",
        "音频已开始下载",
      ),
      errorMessage: t("aigcStudio.audioNode.downloadFailed", "音频下载失败"),
    });
    setDownloadReady(true);
  };

  const handleToggleTool = (
    event: MouseEvent<HTMLButtonElement>,
    tool: Exclude<AudioTool, null>,
  ) => {
    event.stopPropagation();
    setActiveTool((current) => (current === tool ? null : tool));
  };

  const handleTrimInput =
    (setter: (value: number) => void, fallback: number) =>
    (event: ChangeEvent<HTMLInputElement>) => {
      setter(inputNumber(event.target.value, fallback));
    };

  const handleApplyTrim = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    const safeStart = clampAudioTime(trimStart, 0, duration);
    const safeEnd = clampAudioTime(trimEnd, safeStart, duration);
    setTrimStart(safeStart);
    setTrimEnd(safeEnd);
    setActiveTool("trim");
    onUpdateNodeData?.(node.id, {
      audioActiveTool: "trim",
      audioTrimEnd: safeEnd,
      audioTrimStart: safeStart,
    });
  };

  const handleSelectSpeed = (
    event: MouseEvent<HTMLButtonElement>,
    speed: number,
  ) => {
    event.stopPropagation();
    setSelectedSpeed(speed);
    setActiveTool("speed");
    onUpdateNodeData?.(node.id, {
      audioActiveTool: "speed",
      audioSpeed: speed,
    });
  };

  return (
    <>
      <div className={styles.nodeLabel}>
        <span>
          <AudioLines size={15} />
          {String(
            node.data.title ??
              t("aigcStudio.nodeType.audio_generate", "音频生成"),
          )}
        </span>
        <span className={styles.nodeTypeBadge}>
          {t("aigcStudio.nodeType.audio_generate", "音频生成")}
        </span>
      </div>
      <div className={styles.nodeText}>{String(node.data.text ?? "")}</div>
      <div
        className={`${styles.audioEditorSurface} ${
          audioState === "generating" ? styles.audioEditorGenerating : ""
        } ${audioState === "generated" ? styles.audioEditorGenerated : ""} ${
          audioState === "failed" ? styles.audioEditorFailed : ""
        }`}
        data-audio-state={audioState}
        data-testid="aigc-audio-editor"
      >
        {audioState === "generating" ? (
          <div className={styles.audioGeneratingState}>
            <AudioWaveform
              label={t(
                "aigcStudio.audioNode.generatingWaveform",
                "音频生成波形",
              )}
            />
            <div>
              <Loader2 size={15} />
              <strong>
                {t(
                  "aigcStudio.audioNode.generating",
                  "生成中 {{progress}}%...",
                  {
                    progress: Number.isFinite(progress) ? progress : 1,
                  },
                )}
              </strong>
              <button type="button">{t("aigcStudio.cancelJob", "取消")}</button>
            </div>
          </div>
        ) : audioState === "generated" ? (
          <div
            className={styles.generatedAudioFrame}
            data-testid="aigc-audio-result"
          >
            <div
              className={styles.audioViewerToolbar}
              data-testid="aigc-audio-viewer-toolbar"
              onClick={(event) => event.stopPropagation()}
            >
              <button
                type="button"
                aria-label={t("aigcStudio.audioNode.trim", "截取")}
                aria-pressed={activeTool === "trim"}
                onClick={(event) => handleToggleTool(event, "trim")}
              >
                <Scissors size={15} />
                <span>{t("aigcStudio.audioNode.trim", "截取")}</span>
              </button>
              <button
                type="button"
                aria-label={t("aigcStudio.audioNode.speed", "变速")}
                aria-pressed={activeTool === "speed"}
                onClick={(event) => handleToggleTool(event, "speed")}
              >
                <SlidersHorizontal size={15} />
                <span>{t("aigcStudio.audioNode.speed", "变速")}</span>
              </button>
              <button
                type="button"
                aria-label={t("aigcStudio.audioNode.download", "下载音频")}
                onClick={(event) => void handleDownload(event)}
              >
                <Download size={15} />
              </button>
            </div>
            {downloadReady && (
              <span className={styles.audioResultDownloadStatus}>
                {t("aigcStudio.audioNode.downloadReady", "已准备下载")}
              </span>
            )}
            {activeTool && (
              <span className={styles.audioToolStatus}>
                {activeTool === "trim"
                  ? t("aigcStudio.audioNode.trimMode", "截取模式")
                  : t("aigcStudio.audioNode.speedMode", "变速模式")}
              </span>
            )}
            {activeTool === "trim" && (
              <div
                className={styles.audioToolPanel}
                data-testid="aigc-audio-trim-panel"
                onClick={(event) => event.stopPropagation()}
              >
                <label>
                  <span>{t("aigcStudio.audioNode.trimStart", "开始")}</span>
                  <input
                    aria-label={t("aigcStudio.audioNode.trimStart", "开始")}
                    type="number"
                    min={0}
                    max={duration}
                    step={0.1}
                    value={trimStart}
                    onChange={handleTrimInput(setTrimStart, 0)}
                  />
                </label>
                <label>
                  <span>{t("aigcStudio.audioNode.trimEnd", "结束")}</span>
                  <input
                    aria-label={t("aigcStudio.audioNode.trimEnd", "结束")}
                    type="number"
                    min={0}
                    max={duration}
                    step={0.1}
                    value={trimEnd}
                    onChange={handleTrimInput(setTrimEnd, duration)}
                  />
                </label>
                <button type="button" onClick={handleApplyTrim}>
                  {t("aigcStudio.audioNode.applyTrim", "应用截取")}
                </button>
              </div>
            )}
            {activeTool === "speed" && (
              <div
                className={styles.audioToolPanel}
                data-testid="aigc-audio-speed-panel"
                onClick={(event) => event.stopPropagation()}
              >
                {AUDIO_SPEED_OPTIONS.map((speed) => (
                  <button
                    key={speed}
                    type="button"
                    aria-pressed={selectedSpeed === speed}
                    onClick={(event) => handleSelectSpeed(event, speed)}
                  >
                    {speed}x
                  </button>
                ))}
              </div>
            )}
            <AudioWaveform
              label={t("aigcStudio.audioNode.waveform", "音频波形")}
            />
            <div className={styles.generatedAudioControls}>
              <span>{durationLabel}</span>
              <button
                type="button"
                aria-label={
                  playing
                    ? t("aigcStudio.audioNode.pause", "暂停音频")
                    : t("aigcStudio.audioNode.play", "播放音频")
                }
                onClick={(event) => {
                  event.stopPropagation();
                  setPlaying((current) => !current);
                }}
              >
                <Play size={14} />
              </button>
              <strong>{generatedLabel}</strong>
            </div>
          </div>
        ) : (
          <div className={styles.audioEmptyState}>
            <AudioLines size={34} />
          </div>
        )}
      </div>
    </>
  );
}
